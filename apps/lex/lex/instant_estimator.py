from __future__ import annotations

import base64
import io
from decimal import Decimal, ROUND_CEILING
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, now_datetime, nowdate

from lex.client_access import get_portal_user

PAGES_PER_HOUR = 30
PRICING_VERSION = "CAD-FIXED-30PPH-1.0"
FIXED_SERVICE_RATES_CAD: dict[str, Decimal] = {
	"Legal Research & Writing": Decimal("24.50"),
	"Litigation Support": Decimal("28.00"),
	"Contract Lifecycle Management (CLM)": Decimal("35.01"),
	"Contract Review": Decimal("29.40"),
	"eDiscovery & Document Review": Decimal("24.50"),
	"Compliance & Regulatory Support": Decimal("35.01"),
	"Paralegal & Virtual Legal Assistance": Decimal("17.50"),
	"Legal Operations Support": Decimal("38.51"),
}
SERVICES_LIST = list(FIXED_SERVICE_RATES_CAD)


def extract_pdf_pages_and_text(pdf_bytes: bytes) -> tuple[int, str]:
	"""Extract the PDF's exact native page count; text is never used for pricing."""
	from pypdf import PdfReader

	stream = io.BytesIO(pdf_bytes)
	reader = PdfReader(stream)
	pages = len(reader.pages)

	return pages, ""


def round_up_to_cad_five(amount: Decimal) -> Decimal:
	"""Round a non-negative CAD amount upward to the next whole $5 amount."""
	if amount < 0:
		raise ValueError("CAD amount cannot be negative.")
	return (amount / Decimal("5")).to_integral_value(rounding=ROUND_CEILING) * Decimal("5")


def calculate_page_based_pricing(pages: int, service: str, turnaround: str = "Standard (3-5 Business Days)") -> dict[str, Any]:
	"""Return the authoritative, deterministic fixed-rate CAD estimate.

	Turnaround is recorded for scope/audit continuity but deliberately does not
	change the fixed hourly rate.  Browser, OCR and integrations must consume
	the saved final CAD price rather than recalculate it.
	"""
	if isinstance(pages, bool) or not isinstance(pages, int) or pages <= 0:
		raise ValueError("PDF page count must be a positive integer.")
	service = str(service or "").strip()
	if service not in FIXED_SERVICE_RATES_CAD:
		raise ValueError("Select a service from the fixed CAD pricing table.")
	rate = FIXED_SERVICE_RATES_CAD[service]
	if rate <= 0:
		raise ValueError("The selected service does not have a valid fixed CAD hourly rate.")

	exact_hours = Decimal(pages) / Decimal(PAGES_PER_HOUR)
	# Multiply before division so amounts such as 29.40 x 100 / 30 remain
	# exact Decimal values instead of carrying a repeating intermediate value.
	raw_price = (Decimal(pages) * rate) / Decimal(PAGES_PER_HOUR)
	final_price = round_up_to_cad_five(raw_price)
	turnaround_text = str(turnaround or "Standard (3-5 Business Days)").strip()

	return {
		"has_error": False,
		"price_amount": f"{int(final_price)} CAD",
		"volume_text": f"{pages} exact native PDF pages / {PAGES_PER_HOUR} pages/hour = {exact_hours} hours",
		"service_text": service,
		"rate_text": f"{rate:.2f} CAD/hour",
		"fx_text": "CAD pricing; no currency conversion applied.",
		"turnaround_text": turnaround_text,
		"page_count_source": "Exact native PDF page count",
		"calculation_text": "Final CAD price is calculated server-side from exact native PDF pages and the selected fixed CAD hourly rate.",
		"pages": pages,
		"estimated_hours": exact_hours,
		"exact_hours": exact_hours,
		"fixed_service_rate_cad": rate,
		"raw_price_cad": raw_price,
		"final_price_cad": final_price,
		"price_min": final_price,
		"price_max": final_price,
		"currency": "CAD",
		"source_currency": "CAD",
		"exchange_rate": Decimal("1"),
		"exchange_rate_date": None,
		"pages_per_hour": PAGES_PER_HOUR,
		"pricing_version": PRICING_VERSION,
	}


def _decode_uploaded_file(filename: str, content: Any) -> bytes:
	if isinstance(content, bytes):
		return content
	if isinstance(content, str):
		if "," in content and ";base64" in content:
			content = content.split(",", 1)[1]
		return base64.b64decode(content)
	if hasattr(content, "read"):
		return content.read()
	frappe.throw(_("Invalid file content received."), frappe.ValidationError)


SERVICE_TO_INTAKE_TYPE = {
	"Legal Research & Writing": "Legal Research",
	"Litigation Support": "Litigation Support",
	"Contract Lifecycle Management (CLM)": "Contract Review",
	"Contract Review": "Contract Review",
	"eDiscovery & Document Review": "Document Review",
	"Compliance & Regulatory Support": "Compliance Review",
	"Due Diligence Support": "Due Diligence",
	"Paralegal & Virtual Legal Assistance": "Drafting",
}

SERVICE_TO_PRACTICE_AREA = {
	"Legal Research & Writing": "Legal Research",
	"Litigation Support": "Litigation Support",
	"Contract Lifecycle Management (CLM)": "Contract Review",
	"Contract Review": "Contract Review",
	"eDiscovery & Document Review": "Corporate & Commercial",
	"Compliance & Regulatory Support": "Regulatory & Compliance",
	"Due Diligence Support": "Due Diligence",
	"Paralegal & Virtual Legal Assistance": "Corporate & Commercial",
}


class _service_writes:
	def __enter__(self):
		self.previous = getattr(frappe.flags, "lexocrates_intake_service", False)
		frappe.flags.lexocrates_intake_service = True

	def __exit__(self, exc_type, exc_value, traceback):
		frappe.flags.lexocrates_intake_service = self.previous


class _portal_service_writes:
	def __enter__(self):
		self.previous = getattr(frappe.flags, "lexocrates_portal_service", False)
		frappe.flags.lexocrates_portal_service = True

	def __exit__(self, exc_type, exc_value, traceback):
		frappe.flags.lexocrates_portal_service = self.previous


@frappe.whitelist()
def calculate_instant_pdf_estimate(
	filename: str | None = None,
	content: str | None = None,
	service: str | None = None,
	turnaround: str | None = None,
) -> dict[str, Any]:
	"""Calculate and persist the selected service's fixed-rate CAD PDF estimate."""
	if not filename and getattr(frappe.local, "uploaded_filename", None):
		filename = frappe.local.uploaded_filename
	if not content and getattr(frappe.local, "uploaded_file", None):
		content = frappe.local.uploaded_file

	if not filename or not str(filename).lower().endswith(".pdf"):
		return {
			"has_error": True,
			"validation_error": _("Only PDF files are supported for exact page counting."),
			"price_amount": "Estimate unavailable",
			"volume_text": _("Only PDF files are supported for exact page counting."),
			"service_text": service or "Auto-Detect from Document",
			"rate_text": "—",
			"fx_text": "CAD pricing; no currency conversion applied.",
			"turnaround_text": turnaround or "Standard",
			"page_count_source": "Not available",
			"calculation_text": "Please upload a valid PDF and try again.",
		}

	try:
		pdf_bytes = _decode_uploaded_file(filename, content)
	except Exception as exc:
		return {
			"has_error": True,
			"validation_error": f"Failed to decode PDF: {str(exc)[:200]}",
			"price_amount": "Estimate unavailable",
			"volume_text": "The PDF could not be read.",
			"service_text": service or "Auto-Detect from Document",
			"rate_text": "—",
			"fx_text": "CAD pricing; no currency conversion applied.",
			"turnaround_text": turnaround or "Standard",
			"page_count_source": "Not available",
			"calculation_text": "Please upload a valid PDF and try again.",
		}

	try:
		pages, _unused_text = extract_pdf_pages_and_text(pdf_bytes)
	except Exception as exc:
		return {
			"has_error": True,
			"validation_error": f"The PDF could not be read: {str(exc)[:200]}",
			"price_amount": "Estimate unavailable",
			"volume_text": "The PDF could not be read. Please upload a valid, non-password-protected PDF.",
			"service_text": service or "Auto-Detect from Document",
			"rate_text": "—",
			"fx_text": "CAD pricing; no currency conversion applied.",
			"turnaround_text": turnaround or "Standard",
			"page_count_source": "Not available",
			"calculation_text": "Please upload a valid PDF and try again.",
		}

	if not pages or pages < 1:
		return {
			"has_error": True,
			"validation_error": "The PDF page count could not be determined.",
			"price_amount": "Estimate unavailable",
			"volume_text": "The PDF page count could not be determined.",
			"service_text": service or "Auto-Detect from Document",
			"rate_text": "—",
			"fx_text": "CAD pricing; no currency conversion applied.",
			"turnaround_text": turnaround or "Standard",
			"page_count_source": "Not available",
			"calculation_text": "Please upload a valid PDF and try again.",
		}

	selected_service = str(service or "").strip()
	try:
		pricing = calculate_page_based_pricing(pages, selected_service, turnaround or "Standard (3-5 Business Days)")
	except ValueError as exc:
		return {
			"has_error": True,
			"validation_error": str(exc),
			"price_amount": "Estimate unavailable",
			"volume_text": f"{pages} exact native PDF pages were found.",
			"service_text": selected_service or "Service selection required",
			"rate_text": "—",
			"fx_text": "CAD pricing; no currency conversion applied.",
			"turnaround_text": turnaround or "Standard",
			"page_count_source": "Exact native PDF page count",
			"calculation_text": "Choose a service from the fixed CAD pricing table.",
		}
	detected_service = selected_service
	final_price_cad = int(pricing["final_price_cad"])
	pricing_audit = (
		f"Pricing version {pricing['pricing_version']}; exact native PDF pages={pages}; "
		f"calculated hours={pricing['exact_hours']}; selected service={detected_service}; "
		f"fixed CAD/hour={pricing['fixed_service_rate_cad']}; raw CAD price={pricing['raw_price_cad']}; "
		f"final rounded CAD price={final_price_cad}; exchange rate=1 CAD/CAD."
	)


	# Link or create intake & Razorpay order
	portal_user = get_portal_user()
	client = portal_user.client if portal_user else None
	intake_name = None
	matter_name = None

	if client:
		from frappe.utils.file_manager import save_file
		from lex.work_intake import _sla_hash, _sla_snapshot

		intake_title = f"{detected_service} - {filename[:60]} ({pages} pp)"
		customer_name = frappe.db.get_value("Customer", client, "customer_name") or client
		practice_area = SERVICE_TO_PRACTICE_AREA.get(detected_service, "Other")
		intake_service = SERVICE_TO_INTAKE_TYPE.get(detected_service, "Other")
		sla_version, sla_terms, sla_doc = _sla_snapshot()
		sla_hash = _sla_hash(sla_terms, sla_doc)

		with _service_writes(), _portal_service_writes():
			matter = frappe.get_doc({
				"doctype": "LPO Matter",
				"matter_title": intake_title,
				"customer": client,
				"status": "Active",
				"matter_model": "Project",
				"matter_manager": "Administrator",
				"matter_nature": "Advisory",
				"represented_party_name": customer_name,
				"our_side_role": "Represented Party",
				"billing_method": "Job Based",
				"practice_area": practice_area,
				"jurisdictions": "Canada",
				"description": f"Instant native PDF estimate: {pricing['price_amount']} ({pages} pages). {pricing_audit}",
				"start_date": frappe.utils.nowdate(),
				"standard_turnaround_hours": 72,
				"sla_warning_hours": 8,
				"confidentiality_level": "Confidential",
				"conflict_check_status": "Cleared",
				"matter_acceptance_status": "Accepted",
				"authorized_portal_users": [{
					"portal_user": portal_user.name,
					"user": portal_user.user,
					"can_view": 1,
					"can_upload": 1,
					"can_comment": 1,
					"can_approve": 1,
					"can_view_billing": 1,
				}],
			}).insert(ignore_permissions=True)
			matter_name = matter.name

			intake = frappe.get_doc({
				"doctype": "Lexocrates Work Intake",
				"intake_title": intake_title,
				"client": client,
				"portal_user": portal_user.name,
				"submitted_by": frappe.session.user,
				"matter": matter.name,
				"service_type": intake_service,
				"priority": "Urgent" if "Emergency" in str(turnaround) else ("High" if "Rush" in str(turnaround) else "Medium"),
				"jurisdiction": "Canada",
				"status": "Quote Ready",
				"created_on": frappe.utils.now_datetime(),
				"expected_outcome": f"Instant native PDF estimate: {pricing['price_amount']} ({pages} pages)",
				"preliminary_details": pricing_audit,
				"confidentiality_level": "Confidential",
				"sla_version": sla_version,
				"sla_terms_snapshot": sla_terms,
				"sla_snapshot_hash": sla_hash,
				"sla_accepted": 1,
				"sla_accepted_by": frappe.session.user,
				"sla_accepted_on": frappe.utils.now_datetime(),
				"currency": "CAD",
				"exchange_rate": 1,
				"document_count": 1,
				"page_count": pages,
				"quote_status": "Ready",
				"quoted_amount": final_price_cad,
				"required_lexpoints": max(1, final_price_cad),
				"scope_summary": pricing_audit,
				"pricing_approval_status": "Approved",
				"detailed_instructions": pricing_audit,
			}).insert(ignore_permissions=True)
			intake_name = intake.name

			job = frappe.get_doc({
				"doctype": "LPO Job",
				"job_title": intake_title,
				"engagement": matter.name,
				"customer": client,
				"work_intake": intake.name,
				"job_type": intake_service,
				"job_status": "Draft",
				"priority": intake.priority,
				"confidentiality_level": "Confidential",
				"task_description": f"Instant PDF estimate: {pricing['price_amount']}",
				"received_at": frappe.utils.now_datetime(),
				"due_date": frappe.utils.add_days(frappe.utils.nowdate(), 3),
				"qa_required": 1,
			}).insert(ignore_permissions=True)

			intake.job = job.name
			intake.save(ignore_permissions=True)

			# Save attached PDF to the intake
			save_file(
				filename,
				pdf_bytes,
				"Lexocrates Work Intake",
				intake.name,
				is_private=1,
				df="documents",
			)

	# Prepare Razorpay order payload
	razorpay_order = _prepare_razorpay_checkout(
		amount_cad=final_price_cad,
		service_name=detected_service,
		pages=pages,
		turnaround=pricing["turnaround_text"],
		intake_name=intake_name,
		matter_name=matter_name,
		portal_user=portal_user,
	)

	pricing["intake"] = intake_name
	pricing["matter"] = matter_name
	pricing["razorpay_order"] = razorpay_order
	return _serialize_pricing(pricing)


def _prepare_razorpay_checkout(
	amount_cad: int,
	service_name: str,
	pages: int,
	turnaround: str,
	intake_name: str | None = None,
	matter_name: str | None = None,
	portal_user: Any = None,
) -> dict[str, Any]:
	"""Use the existing verified Direct Quote checkout; never trust browser pricing."""
	if not intake_name:
		return {
			"is_live_order": False,
			"currency": "CAD",
			"amount": amount_cad * 100,
			"reason": "Sign in through the Client Portal before creating a Razorpay order.",
		}
	try:
		from lex.work_intake import create_direct_quote_order

		return create_direct_quote_order(intake_name)
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "Instant Estimator Razorpay Order")
		return {
			"is_live_order": False,
			"currency": "CAD",
			"amount": amount_cad * 100,
			"intake": intake_name,
			"matter": matter_name,
			"reason": str(exc)[:300],
		}


@frappe.whitelist()
def verify_instant_estimate_payment(
	intake: str,
	razorpay_payment_id: str,
	razorpay_order_id: str | None = None,
	razorpay_signature: str | None = None,
) -> dict[str, Any]:
	"""Delegate payment verification to the existing signed Direct Quote flow."""
	from lex.work_intake import verify_direct_quote_payment

	if not razorpay_order_id or not razorpay_signature:
		frappe.throw(_("Razorpay order ID and signature are required."), frappe.ValidationError)
	return verify_direct_quote_payment(
		intake=intake,
		razorpay_payment_id=razorpay_payment_id,
		razorpay_order_id=razorpay_order_id,
		razorpay_signature=razorpay_signature,
	)


def _serialize_pricing(pricing: dict[str, Any]) -> dict[str, Any]:
	"""Serialize Decimal calculation evidence without ever exposing a price range."""
	result = dict(pricing)
	for fieldname in ("final_price_cad", "price_min", "price_max"):
		if fieldname in result:
			result[fieldname] = int(result[fieldname])
	for fieldname in ("estimated_hours", "exact_hours", "fixed_service_rate_cad", "raw_price_cad", "exchange_rate"):
		if fieldname in result:
			result[fieldname] = str(result[fieldname])
	return result
