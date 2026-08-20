from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import zipfile

import frappe
from frappe import _
from frappe.utils import now_datetime

from lex.client_access import get_portal_user, has_matter_access, is_client_user
from lex.portal_audit import create_portal_audit_event


# Pluggable quarantine and malware scanner module (API-008)
ALLOWED_MIME_TYPES = {
	"application/pdf",
	"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
	"application/msword",
	"text/plain",
	"text/csv",
	"image/jpeg",
	"image/png",
}


@frappe.whitelist()
def scan_and_validate_inbound_file(file_doc_name: str) -> dict:
	"""Validate file identity and release only after a real malware engine returns clean."""
	if not frappe.db.exists("File", file_doc_name):
		frappe.throw(_("File document not found."), frappe.DoesNotExistError)
	doc = frappe.get_doc("File", file_doc_name)
	_verify_scan_permission(doc)
	file_name = doc.file_name or doc.name
	content = doc.get_content()
	if isinstance(content, str):
		content = content.encode("utf-8")
	checksum = hashlib.sha256(content).hexdigest()
	client = _file_client(doc)
	_set_scan_state(doc.name, "Scanning", checksum=checksum)

	try:
		_validate_file_identity(file_name, content)
	except frappe.ValidationError as exc:
		_set_scan_state(doc.name, "Rejected", checksum=checksum, reason=str(exc))
		_audit_scan(doc, client, "Inbound File Rejected", "Rejected", checksum, str(exc))
		raise

	status, engine, detail = _run_malware_scan(content)
	_set_scan_state(doc.name, status, checksum=checksum, engine=engine, reason=detail)
	_audit_scan(doc, client, "Inbound File Malware Scan", status, checksum, detail)
	return {
		"status": status,
		"file": doc.name,
		"checksum": checksum,
		"scanner_engine": engine,
		"quarantine_passed": status == "Clean",
		"detail": detail,
	}


def _verify_scan_permission(doc):
	if not is_client_user():
		roles = set(frappe.get_roles(frappe.session.user))
		if frappe.session.user == "Administrator" or roles.intersection({"LPO_Admin", "LPO_Manager", "System Manager"}):
			return
	if doc.attached_to_doctype == "LPO Matter" and has_matter_access(doc.attached_to_name, "upload"):
		return
	if doc.attached_to_doctype == "Lexocrates Work Intake":
		actor = get_portal_user()
		intake = frappe.db.get_value(
			"Lexocrates Work Intake", doc.attached_to_name, ["client", "portal_user", "sla_accepted"], as_dict=True
		)
		if actor and intake and actor.client == intake.client and intake.sla_accepted:
			if actor.matter_access_scope == "All Client Matters" or intake.portal_user == actor.name:
				return
	frappe.throw(_("You cannot scan this File."), frappe.PermissionError)


def _validate_file_identity(file_name: str, content: bytes):
	extension = os.path.splitext(file_name.lower())[1]
	allowed = {".pdf", ".docx", ".doc", ".txt", ".csv", ".jpg", ".jpeg", ".png"}
	if extension not in allowed:
		frappe.throw(_("File type not permitted by security policy."), frappe.ValidationError)
	if content.startswith((b"MZ", b"\x7fELF")) or b"<script" in content[:4096].lower():
		frappe.throw(_("Executable or active content is not permitted."), frappe.ValidationError)
	valid = {
		".pdf": content.startswith(b"%PDF-"),
		".png": content.startswith(b"\x89PNG\r\n\x1a\n"),
		".jpg": content.startswith(b"\xff\xd8\xff"),
		".jpeg": content.startswith(b"\xff\xd8\xff"),
		".doc": content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
	}
	if extension == ".docx":
		try:
			with zipfile.ZipFile(io.BytesIO(content)) as archive:
				names = set(archive.namelist())
			valid[extension] = "[Content_Types].xml" in names and "word/document.xml" in names
		except (OSError, zipfile.BadZipFile):
			valid[extension] = False
	if extension in {".txt", ".csv"}:
		try:
			content.decode("utf-8")
			valid[extension] = b"\x00" not in content
		except UnicodeDecodeError:
			valid[extension] = False
	if not valid.get(extension, False):
		frappe.throw(_("File content does not match its declared extension."), frappe.ValidationError)


def _run_malware_scan(content: bytes) -> tuple[str, str, str]:
	if b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in content:
		return "Infected", "Built-in EICAR Guard", "EICAR malware test signature detected"
	configured = (frappe.conf.get("lexocrates_clamscan_path") or "").strip()
	executable = configured or shutil.which("clamscan")
	if not executable:
		return "Scanner Unavailable", "ClamAV", "ClamAV is not configured; file remains quarantined"
	try:
		result = subprocess.run(
			[executable, "--no-summary", "-"],
			input=content,
			capture_output=True,
			timeout=60,
			check=False,
		)
	except (OSError, subprocess.TimeoutExpired) as exc:
		return "Scanner Unavailable", "ClamAV", f"Scanner failed: {exc}"
	detail = (result.stdout or result.stderr).decode("utf-8", errors="replace").strip()[:500]
	if result.returncode == 0:
		return "Clean", "ClamAV", detail or "No malware detected"
	if result.returncode == 1:
		return "Infected", "ClamAV", detail or "Malware detected"
	return "Scanner Unavailable", "ClamAV", detail or f"Scanner exit code {result.returncode}"


def _set_scan_state(file_name, status, *, checksum=None, engine=None, reason=None):
	values = {
		"custom_lex_scan_status": status,
		"custom_lex_checksum": checksum,
		"custom_lex_scanned_on": now_datetime(),
		"custom_lex_scanner_engine": engine,
		"custom_lex_quarantine_reason": reason,
	}
	available = {field.fieldname for field in frappe.get_meta("File").fields}
	frappe.db.set_value("File", file_name, {key: value for key, value in values.items() if key in available}, update_modified=False)


def _file_client(doc):
	if doc.attached_to_doctype == "Lexocrates Work Intake":
		return frappe.db.get_value("Lexocrates Work Intake", doc.attached_to_name, "client")
	if doc.attached_to_doctype == "LPO Matter":
		return frappe.db.get_value("LPO Matter", doc.attached_to_name, "customer")
	if doc.attached_to_doctype == "LPO Job":
		return frappe.db.get_value("LPO Job", doc.attached_to_name, "customer")
	return None


def _audit_scan(doc, client, action, status, checksum, detail):
	create_portal_audit_event(
		client=client,
		user=frappe.session.user,
		action=action,
		object_type="File",
		object_id=doc.name,
		new_value={"file_name": doc.file_name, "status": status, "checksum": checksum},
		details=detail,
	)
