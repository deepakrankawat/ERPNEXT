# Copyright (c) 2026, Lexocrates and contributors
# For license information, please see license.txt

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import zipfile
import xml.etree.ElementTree as ET

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, flt, get_datetime, now_datetime
from frappe.utils.file_manager import save_file

from lex.ai_gateway import invoke_ai_gateway
from lex.document_export import build_export_files, export_metadata, normalize_export_options, safe_export_filename
from lex.file_quarantine import release_internally_generated_file
from lex.pdf_watermark import secure_pdf_download_url
from lex.portal_audit import create_portal_audit_event

INTERNAL_AI_ROLES = {"LPO_Admin", "LPO_Manager", "LPO_Analyst", "System Manager"}


def _ensure_internal_system_user():
	"""Strictly ensure AI Document Processing is available ONLY to internal System Users, never website/portal users."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Authentication required."), frappe.AuthenticationError)
	roles = set(frappe.get_roles(user))
	if user != "Administrator" and not roles.intersection(INTERNAL_AI_ROLES):
		frappe.throw(
			_("AI Document Processing is strictly restricted to internal System Users (LPO Operations staff). Website users are not authorized."),
			frappe.PermissionError,
		)


def extract_text_from_file(
	file_url_or_path: str,
	max_chars: int = 60000,
	file_doc_name: str | None = None,
) -> tuple[str, str, int, int]:
	"""Extract readable text and metadata from uploaded file (TXT, MD, PDF, DOCX, CSV, JSON).
	Returns: (extracted_text, sha256_checksum, word_count, char_count)
	"""
	if not file_url_or_path:
		return "", "", 0, 0

	raw_bytes = None
	file_name = os.path.basename(file_url_or_path)

	# Try fetching via Frappe File doctype
	if file_doc_name and frappe.db.exists("File", file_doc_name):
		file_doc = frappe.get_doc("File", file_doc_name)
		file_name = file_doc.file_name or file_name
		content = file_doc.get_content()
		if isinstance(content, bytes):
			raw_bytes = content
		elif isinstance(content, str):
			raw_bytes = content.encode("utf-8")
	elif frappe.db.exists("File", {"file_url": file_url_or_path}):
		matching_files = frappe.get_all(
			"File", filters={"file_url": file_url_or_path}, pluck="name", order_by="creation desc", limit=1
		)
		file_doc = frappe.get_doc("File", matching_files[0])
		file_name = file_doc.file_name or file_name
		content = file_doc.get_content()
		if isinstance(content, bytes):
			raw_bytes = content
		elif isinstance(content, str):
			raw_bytes = content.encode("utf-8")

	# Fallback: check direct file path on disk
	if raw_bytes is None:
		site_path = frappe.get_site_path()
		candidate_paths = [
			file_url_or_path,
			os.path.join(site_path, "public", file_url_or_path.lstrip("/")),
			os.path.join(site_path, file_url_or_path.lstrip("/")),
		]
		for p in candidate_paths:
			if os.path.exists(p) and os.path.isfile(p):
				with open(p, "rb") as f:
					raw_bytes = f.read()
				break

	if not raw_bytes:
		return f"[Document Reference: {file_name}]", "", 0, 0

	checksum = hashlib.sha256(raw_bytes).hexdigest()
	extracted_text = ""

	ext = os.path.splitext(file_name)[1].lower()

	# 1. Plain text / Markdown / JSON / CSV
	if ext in {".txt", ".md", ".json", ".csv", ".xml", ".html", ".htm", ".py", ".sql"}:
		try:
			extracted_text = raw_bytes.decode("utf-8", errors="replace")
		except Exception:
			extracted_text = raw_bytes.decode("latin-1", errors="replace")

	# 2. DOCX (Word Document) via zip extraction
	elif ext in {".docx", ".docm"}:
		try:
			import io
			with zipfile.ZipFile(io.BytesIO(raw_bytes)) as docx_zip:
				xml_content = docx_zip.read("word/document.xml")
				tree = ET.fromstring(xml_content)
				paragraphs = []
				# XML namespace for wordprocessingml
				for p in tree.iter():
					if p.tag.endswith("p"):
						texts = [t.text for t in p.iter() if t.tag.endswith("t") and t.text]
						if texts:
							paragraphs.append("".join(texts))
				extracted_text = "\n\n".join(paragraphs)
		except Exception as e:
			extracted_text = f"[DOCX Extraction Note: {e}]"

	# 3. PDF Extraction
	elif ext == ".pdf":
		try:
			import io
			try:
				import pypdf
				reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
				extracted_text = "\n\n".join(
					[page.extract_text() or "" for page in reader.pages]
				)
			except ImportError:
				# Basic fallback string extraction from PDF stream
				extracted_text = raw_bytes.decode("latin-1", errors="ignore")
				# Clean non-printable characters
				extracted_text = "".join(c for c in extracted_text if c.isprintable() or c in "\n\r\t")
		except Exception as e:
			extracted_text = f"[PDF Extraction Note: {e}]"

	else:
		try:
			extracted_text = raw_bytes.decode("utf-8", errors="ignore")
		except Exception:
			extracted_text = f"[Binary Legal File: {file_name} ({len(raw_bytes)} bytes)]"

	extracted_text = extracted_text.strip()
	if len(extracted_text) > max_chars:
		extracted_text = extracted_text[:max_chars] + "\n\n...[Content truncated for token context optimization]..."

	word_count = len(extracted_text.split())
	char_count = len(extracted_text)
	return extracted_text, checksum, word_count, char_count


def ensure_default_ai_document_services():
	"""Seed the standard production-grade AI Document Services catalog."""
	standard_services = [
		{
			"service_code": "SUMMARIZE",
			"service_name": "Executive Summarization & Brief",
			"category": "Summarization",
			"description": "Synthesizes the entire document into an executive summary, key provisions, and operational action items.",
			"icon": "align-left",
			"output_format": "Markdown",
			"default_provider": "OpenAI",
			"default_model": "gpt-4o",
			"max_tokens": 750,
			"temperature": 0.2,
			"system_directive": (
				"You are an expert Legal Operations Assistant at Lexocrates. Provide structured, authoritative summaries "
				"tailored for corporate counsel and legal analysts."
			),
			"prompt_template": (
				"LEXOCRATES LEGAL OPERATIONS - DOCUMENT EXECUTIVE SUMMARY\n"
				"Document Title: {{job_title}}\n"
				"Matter Context: {{matter_title}} (Practice Area: {{practice_area}})\n"
				"Additional Instructions: {{instructions}}\n\n"
				"--- SOURCE DOCUMENT TEXT ---\n{{document_text}}\n--- END SOURCE DOCUMENT ---\n\n"
				"Please provide a comprehensive summary formatted in Markdown with the following sections:\n"
				"### 1. Executive Overview (2-3 sentences)\n"
				"### 2. Core Legal Obligations & Deliverables\n"
				"### 3. Key Dates, Milestones & Financial Terms\n"
				"### 4. Critical Dependencies & Action Items"
			),
		},
		{
			"service_code": "RISK_ANALYSIS",
			"service_name": "Risk & Clause Analysis",
			"category": "Risk Analysis",
			"description": "Audits document for high-risk clauses, uncapped liabilities, missing indemnities, and termination triggers.",
			"icon": "alert-triangle",
			"output_format": "Markdown",
			"default_provider": "OpenAI",
			"default_model": "gpt-4o",
			"max_tokens": 850,
			"temperature": 0.1,
			"system_directive": (
				"You are a Senior Legal Risk & Compliance Specialist at Lexocrates. Conduct rigorous clause analysis, "
				"spot contractual ambiguities, and assess liability exposure."
			),
			"prompt_template": (
				"LEXOCRATES CONTRACT RISK & CLAUSE AUDIT\n"
				"Document: {{job_title}} | Matter: {{matter_title}}\n"
				"Specific Focus: {{focus_areas}} | Instructions: {{instructions}}\n\n"
				"--- SOURCE DOCUMENT ---\n{{document_text}}\n--- END SOURCE DOCUMENT ---\n\n"
				"Perform an exhaustive risk assessment formatted in Markdown:\n"
				"### 1. Overall Risk Rating: (Low / Medium / High / Critical)\n"
				"### 2. High-Risk Clauses & Exposure Points (Clause citation, risk rationale, severity)\n"
				"### 3. Missing or Non-Standard Terms\n"
				"### 4. Recommended Mitigations & Redline Suggestions"
			),
		},
		{
			"service_code": "EXTRACT_METADATA",
			"service_name": "Key Entity & Metadata Extraction",
			"category": "Entity & Data Extraction",
			"description": "Extracts structured metadata, entities, parties, governing laws, and key commercial numbers into structured JSON/Tables.",
			"icon": "database",
			"output_format": "Structured JSON",
			"default_provider": "OpenAI",
			"default_model": "gpt-4o",
			"max_tokens": 600,
			"temperature": 0.0,
			"system_directive": (
				"You are a Legal Knowledge & Entity Extraction Engine. Extract factual metadata strictly grounded in the provided document. "
				"Output valid JSON."
			),
			"prompt_template": (
				"Extract key contract metadata and entities from the legal document below into JSON format.\n\n"
				"--- DOCUMENT ---\n{{document_text}}\n--- END DOCUMENT ---\n\n"
				"Output valid JSON containing:\n"
				"{\n"
				"  \"document_type\": \"...\",\n"
				"  \"parties\": [\"Party A\", \"Party B\"],\n"
				"  \"effective_date\": \"YYYY-MM-DD or Not Stated\",\n"
				"  \"expiration_date\": \"YYYY-MM-DD or Perpetual\",\n"
				"  \"governing_law_jurisdiction\": \"...\",\n"
				"  \"monetary_value\": \"...\",\n"
				"  \"payment_terms\": \"...\",\n"
				"  \"confidentiality_duration\": \"...\",\n"
				"  \"dispute_resolution_mechanism\": \"...\"\n"
				"}"
			),
		},
		{
			"service_code": "REDRAFT_POLISH",
			"service_name": "Legal Redrafting & Clause Enhancement",
			"category": "Redrafting & Polishing",
			"description": "Rewrites or enhances clauses with formal legal phrasing, improved clarity, or protective bias based on user prompting.",
			"icon": "edit-3",
			"output_format": "Markdown",
			"default_provider": "OpenAI",
			"default_model": "gpt-4o",
			"max_tokens": 1000,
			"temperature": 0.3,
			"system_directive": (
				"You are an expert Legal Drafter at Lexocrates. Redraft clauses with impeccable precision, clarity, and legal enforceability."
			),
			"prompt_template": (
				"LEXOCRATES LEGAL CLAUSE REDRAFTING & REVISION\n"
				"Matter: {{matter_title}} | Job: {{job_title}}\n"
				"Drafting Goal / Redline Directive: {{instructions}}\n\n"
				"--- SOURCE TEXT TO REVISE ---\n{{document_text}}\n--- END SOURCE TEXT ---\n\n"
				"Provide:\n"
				"### 1. Proposed Revised Language (Clean, enforceable legal draft)\n"
				"### 2. Explanation of Key Changes & Legal Advantages\n"
				"### 3. Alternative Fallback Positions"
			),
		},
		{
			"service_code": "TRANSLATE",
			"service_name": "Multi-Lingual Legal Translation",
			"category": "Translation",
			"description": "Translates legal documents or summaries into target languages while preserving strict legal terminology and nuances.",
			"icon": "globe",
			"output_format": "Markdown",
			"default_provider": "OpenAI",
			"default_model": "gpt-4o",
			"max_tokens": 1200,
			"temperature": 0.1,
			"system_directive": (
				"You are a Certified Legal Translator specializing in international commercial and legal documentation."
			),
			"prompt_template": (
				"LEXOCRATES LEGAL TRANSLATION ENGINE\n"
				"Target Language: {{target_language}}\n"
				"Special Instructions: {{instructions}}\n\n"
				"--- SOURCE DOCUMENT ---\n{{document_text}}\n--- END SOURCE DOCUMENT ---\n\n"
				"Translate the document content accurately into {{target_language}}, preserving formatting, clause numbering, and precise legal terminology."
			),
		},
		{
			"service_code": "COMPLIANCE_CHECK",
			"service_name": "SOP & Regulatory Compliance Audit",
			"category": "Compliance & SOP",
			"description": "Verifies the document against standard operating procedures, confidentiality policies, and regulatory compliance standards.",
			"icon": "shield-check",
			"output_format": "Markdown",
			"default_provider": "OpenAI",
			"default_model": "gpt-4o",
			"max_tokens": 700,
			"temperature": 0.1,
			"system_directive": (
				"You are a Quality & Compliance Auditor at Lexocrates. Verify adherence to SOPs, confidentiality rules, and regulatory frameworks."
			),
			"prompt_template": (
				"LEXOCRATES SOP & COMPLIANCE VERIFICATION\n"
				"Job: {{job_title}} | Practice Area: {{practice_area}}\n"
				"Compliance Checklist / Directives: {{instructions}}\n\n"
				"--- DOCUMENT ---\n{{document_text}}\n--- END DOCUMENT ---\n\n"
				"Audit Results Format:\n"
				"### 1. Compliance Verdict: (Compliant / Minor Deviations / Non-Compliant)\n"
				"### 2. Verified Compliance Checkpoints\n"
				"### 3. Deviations, Vulnerabilities & Flagged Items\n"
				"### 4. Mandatory Remediation Steps Prior to Delivery"
			),
		},
		{
			"service_code": "CUSTOM_PROMPT",
			"service_name": "Custom AI Prompt & Transformation",
			"category": "Custom Prompt",
			"description": "Applies user-defined custom prompt and transformation instructions directly against the document.",
			"icon": "terminal",
			"output_format": "Markdown",
			"default_provider": "OpenAI",
			"default_model": "gpt-4o",
			"max_tokens": 900,
			"temperature": 0.3,
			"system_directive": (
				"You are the Lexocrates Legal Document Copilot. Execute the user's custom document processing instructions with maximum accuracy."
			),
			"prompt_template": (
				"LEXOCRATES DOCUMENT COPILOT\n"
				"Matter: {{matter_title}} | Job: {{job_title}}\n\n"
				"User Custom Prompt / Directive:\n{{instructions}}\n\n"
				"--- DOCUMENT CONTEXT ---\n{{document_text}}\n--- END DOCUMENT CONTEXT ---\n\n"
				"Execute the prompt directive thoroughly and respond in clean, well-formatted Markdown."
			),
		},
	]

	for srv in standard_services:
		if not frappe.db.exists("LPO AI Document Service", srv["service_code"]):
			doc = frappe.get_doc({"doctype": "LPO AI Document Service", **srv})
			doc.insert(ignore_permissions=True)
		else:
			# Update template and directive if existing
			existing = frappe.get_doc("LPO AI Document Service", srv["service_code"])
			existing.prompt_template = srv["prompt_template"]
			existing.system_directive = srv["system_directive"]
			existing.description = srv["description"]
			existing.category = srv["category"]
			existing.output_format = srv["output_format"]
			existing.save(ignore_permissions=True)


def interpolate_prompt(
	template: str,
	document_text: str,
	job_doc: dict | None = None,
	matter_doc: dict | None = None,
	extra_vars: dict | None = None,
) -> str:
	"""Interpolate template placeholders with document text and job/matter context."""
	extra = extra_vars or {}
	job = job_doc or {}
	matter = matter_doc or {}

	replacements = {
		"{{document_text}}": document_text or "[Empty Document Content]",
		"{{job_title}}": job.get("job_title") or job.get("name") or "Operational Job",
		"{{job_type}}": job.get("job_type") or "Legal Analysis",
		"{{matter_title}}": matter.get("matter_title") or matter.get("name") or "Legal Matter",
		"{{customer_name}}": job.get("customer_name") or job.get("customer") or "Client",
		"{{practice_area}}": job.get("practice_area") or matter.get("practice_area") or "General LPO",
		"{{instructions}}": extra.get("instructions") or extra.get("custom_instructions") or "Apply standard professional legal rigor.",
		"{{target_language}}": extra.get("target_language") or "English",
		"{{focus_areas}}": extra.get("focus_areas") or "All standard contractual clauses and risk exposures",
	}

	result = template
	for key, val in replacements.items():
		result = result.replace(key, str(val))
	return result


def _get_or_create_processor(job_id: str, source_file_url: str | None = None) -> "LPOAIDocumentProcessor":
	"""Get existing active document processor for job or initialize a new one."""
	job = frappe.get_doc("LPO Job", job_id)
	file_url = source_file_url or job.source_document

	processor_name = frappe.db.get_value(
		"LPO AI Document Processor",
		{"job": job.name, "status": ["!=", "Cancelled"]},
		"name",
	)

	if processor_name:
		processor = frappe.get_doc("LPO AI Document Processor", processor_name)
		if file_url and processor.source_file != file_url:
			processor.source_file = file_url
			text, checksum, w_cnt, c_cnt = extract_text_from_file(file_url)
			processor.extracted_text = text
			processor.source_checksum = checksum
			processor.word_count = w_cnt
			processor.char_count = c_cnt
			processor.save(ignore_permissions=True)
		return processor

	# Create new processor
	text, checksum, w_cnt, c_cnt = extract_text_from_file(file_url) if file_url else ("", "", 0, 0)
	doc = frappe.get_doc({
		"doctype": "LPO AI Document Processor",
		"title": f"AI Processor - {job.job_title}",
		"job": job.name,
		"matter": job.engagement,
		"customer": job.customer,
		"document_category": "Contract / Agreement" if "Contract" in (job.job_type or "") else "General Document",
		"status": "Extracted" if text else "Draft",
		"source_file": file_url,
		"extracted_text": text,
		"source_checksum": checksum,
		"word_count": w_cnt,
		"char_count": c_cnt,
	}).insert(ignore_permissions=True)

	return doc


@frappe.whitelist()
def extract_job_document_text(job_id: str, file_url: str | None = None) -> dict:
	"""API endpoint: Extract text from Job source document and prepare processor."""
	_ensure_internal_system_user()
	if not frappe.db.exists("LPO Job", job_id):
		frappe.throw(_("Job {0} does not exist.").format(job_id), frappe.DoesNotExistError)

	processor = _get_or_create_processor(job_id, file_url)
	if file_url or not processor.extracted_text:
		target_url = file_url or processor.source_file
		text, checksum, w_cnt, c_cnt = extract_text_from_file(target_url)
		processor.extracted_text = text
		processor.source_checksum = checksum
		processor.word_count = w_cnt
		processor.char_count = c_cnt
		processor.status = "Extracted" if text else "Draft"
		processor.save(ignore_permissions=True)

	return {
		"status": "success",
		"processor_id": processor.name,
		"extracted_text": processor.extracted_text,
		"word_count": processor.word_count,
		"char_count": processor.char_count,
		"source_file": processor.source_file,
	}


@frappe.whitelist()
def process_job_document_service(
	job_id: str,
	service_code: str,
	custom_instructions: str | None = None,
	file_url: str | None = None,
	provider: str | None = None,
	model: str | None = None,
	credential_name: str | None = None,
	max_tokens: int | None = None,
	extra_params: str | dict | None = None,
) -> dict:
	"""Execute a configured AI Document Service with dynamic prompt interpolation on an LPO Job document."""
	_ensure_internal_system_user()
	start_ts = time.time()

	if not frappe.db.exists("LPO Job", job_id):
		frappe.throw(_("Job {0} not found.").format(job_id), frappe.DoesNotExistError)

	service_code = (service_code or "").strip().upper()
	if not frappe.db.exists("LPO AI Document Service", service_code):
		ensure_default_ai_document_services()
		if not frappe.db.exists("LPO AI Document Service", service_code):
			frappe.throw(_("AI Document Service '{0}' is not configured.").format(service_code), frappe.DoesNotExistError)

	service_doc = frappe.get_doc("LPO AI Document Service", service_code)
	job_doc = frappe.get_doc("LPO Job", job_id)
	matter_doc = frappe.get_doc("LPO Matter", job_doc.engagement) if job_doc.engagement else None

	processor = _get_or_create_processor(job_id, file_url)
	if not processor.extracted_text and processor.source_file:
		text, checksum, w_cnt, c_cnt = extract_text_from_file(processor.source_file)
		processor.extracted_text = text
		processor.source_checksum = checksum
		processor.word_count = w_cnt
		processor.char_count = c_cnt
		processor.save(ignore_permissions=True)

	extracted_doc_text = processor.extracted_text or f"[Job Task: {job_doc.task_description or 'No source text'}]"

	# Parse extra variables
	params = {}
	if isinstance(extra_params, str) and extra_params.strip():
		try:
			params = json.loads(extra_params)
		except Exception:
			params = {"instructions": extra_params}
	elif isinstance(extra_params, dict):
		params = extra_params
	if custom_instructions:
		params["instructions"] = custom_instructions

	# Build interpolated prompt
	full_prompt = interpolate_prompt(
		template=service_doc.prompt_template,
		document_text=extracted_doc_text,
		job_doc=job_doc.as_dict(),
		matter_doc=matter_doc.as_dict() if matter_doc else {},
		extra_vars=params,
	)

	# Resolve only a live-verified model through the central use-case router.
	from lex.lex.doctype.lpo_ai_settings.lpo_ai_settings import resolve_ai_route

	target_provider, target_model, credential_name = resolve_ai_route(
		provider, model, f"AI Document - {service_doc.service_name}", credential_name
	)

	target_tokens = cint(max_tokens or service_doc.max_tokens or 1000)

	# Execute via AI Gateway
	service_item = processor.append("services_applied", {
		"service": service_doc.name,
		"service_name": service_doc.service_name,
		"service_code": service_doc.service_code,
		"status": "Running",
		"custom_instructions": params.get("instructions") or "",
		"prompt_snapshot": full_prompt[:2000],
		"executed_by": frappe.session.user,
		"executed_on": now_datetime(),
	})
	processor.status = "In Processing"
	processor.save(ignore_permissions=True)

	try:
		gateway_result = invoke_ai_gateway(
			use_case=f"AI Doc - {service_doc.service_name}",
			prompt_text=full_prompt,
			job_id=job_doc.name,
			matter_id=job_doc.engagement,
			provider=target_provider,
			model=target_model,
			credential_name=credential_name,
			max_tokens=target_tokens,
		)

		output_text = gateway_result.get("response_text") or ""
		tokens_used = cint(gateway_result.get("tokens") or 0)
		cost = flt(gateway_result.get("cost") or 0.0)
		duration = round(time.time() - start_ts, 2)

		# Update child table entry
		service_item.status = "Completed"
		service_item.output_result = output_text
		service_item.tokens_used = tokens_used
		service_item.cost = cost
		service_item.execution_time_seconds = duration
		service_item.ai_execution = gateway_result.get("ai_execution")

		processor.status = "Ready for Review"
		processor.save(ignore_permissions=True)

		# Update Job AI tokens used
		cur_used = cint(job_doc.get("ai_tokens_used") or 0)
		frappe.db.set_value("LPO Job", job_doc.name, "ai_tokens_used", cur_used + tokens_used, update_modified=False)

		create_portal_audit_event(
			client=job_doc.customer,
			action="AI Document Service Executed",
			object_type="LPO AI Document Processor",
			object_id=processor.name,
			new_value={
				"service_code": service_code,
				"tokens": tokens_used,
				"duration": duration,
				"provider": target_provider,
			},
		)

		return {
			"status": "success",
			"service_code": service_code,
			"service_name": service_doc.service_name,
			"output_text": output_text,
			"tokens_consumed": tokens_used,
			"cost": cost,
			"duration_seconds": duration,
			"processor_id": processor.name,
			"output_format": service_doc.output_format,
			"provider": target_provider,
			"model": target_model,
			"credential_name": credential_name,
		}

	except Exception as exc:
		duration = round(time.time() - start_ts, 2)
		service_item.status = "Failed"
		service_item.error_message = str(exc)[:400]
		service_item.execution_time_seconds = duration
		processor.status = "Failed"
		processor.save(ignore_permissions=True)
		frappe.log_error(
			title="LPO AI Document Engine",
			message=frappe.get_traceback(),
			reference_doctype="LPO AI Document Processor",
			reference_name=processor.name,
			defer_insert=True,
		)
		raise


@frappe.whitelist()
def run_job_document_pipeline(
	job_id: str,
	service_codes: list | str,
	custom_instructions: str | None = None,
	provider: str | None = None,
	model: str | None = None,
	credential_name: str | None = None,
) -> dict:
	"""Execute a chained multi-service AI pipeline against the Job document."""
	_ensure_internal_system_user()
	if isinstance(service_codes, str):
		try:
			service_codes = json.loads(service_codes)
		except Exception:
			service_codes = [s.strip() for s in service_codes.split(",") if s.strip()]

	if not service_codes:
		frappe.throw(_("At least one service code is required for pipeline execution."), frappe.MandatoryError)

	results = []
	total_tokens = 0
	total_cost = 0.0

	for code in service_codes:
		res = process_job_document_service(
			job_id=job_id,
			service_code=code,
			custom_instructions=custom_instructions,
			provider=provider,
			model=model,
			credential_name=credential_name,
		)
		results.append(res)
		total_tokens += res.get("tokens_consumed", 0)
		total_cost += res.get("cost", 0.0)

	# Aggregate pipeline outputs
	aggregated_sections = [
		f"## 📋 Pipeline Step: {r.get('service_name')} ({r.get('service_code')})\n\n{r.get('output_text')}\n"
		for r in results
	]
	combined_markdown = "\n---\n\n".join(aggregated_sections)

	processor = _get_or_create_processor(job_id)
	processor.final_output_text = combined_markdown
	processor.status = "Ready for Review"
	processor.save(ignore_permissions=True)

	return {
		"status": "success",
		"job_id": job_id,
		"processor_id": processor.name,
		"pipeline_results": results,
		"combined_output": combined_markdown,
		"total_tokens": total_tokens,
		"total_cost": total_cost,
	}


@frappe.whitelist()
def complete_job_document(
	job_id: str,
	final_text: str | None = None,
	update_job_status: str = "Ready for Delivery",
	completion_notes: str | None = None,
	output_format: str = "PDF",
	document_title: str | None = None,
	page_size: str = "A4",
	document_style: str = "Legal Professional",
	confidentiality_label: str = "Privileged & Confidential",
	include_cover_page: int = 1,
	include_metadata: int = 1,
	include_page_numbers: int = 1,
) -> dict:
	"""Generate versioned PDF/DOCX deliverables, attach them, and advance Job status."""
	_ensure_internal_system_user()
	if not frappe.db.exists("LPO Job", job_id):
		frappe.throw(_("Job {0} not found.").format(job_id), frappe.DoesNotExistError)

	# Serialize exports for the same Job so concurrent clicks cannot create the
	# same version number or overwrite one another's delivery pointer.
	frappe.db.sql("select name from `tabLPO Job` where name = %s for update", job_id)
	job = frappe.get_doc("LPO Job", job_id)
	processor = _get_or_create_processor(job_id)

	content = final_text or processor.final_output_text or ""
	if not content.strip():
		frappe.throw(_("Final document content is empty. Please run AI services or provide final text before completing."), frappe.ValidationError)

	options = normalize_export_options(
		output_format=output_format,
		document_title=document_title or job.job_title or "Legal Operations Deliverable",
		page_size=page_size,
		document_style=document_style,
		confidentiality_label=confidentiality_label,
		include_cover_page=include_cover_page,
		include_metadata=include_metadata,
		include_page_numbers=include_page_numbers,
	)
	matter = frappe.get_doc("LPO Matter", job.engagement)
	latest_export = frappe.get_all(
		"LPO AI Document Export",
		filters={"job": job.name},
		fields=["version"],
		order_by="version desc",
		limit=1,
	)
	export_version = max(
		_version_number(job.delivery_document_version),
		_version_number(processor.get("export_version")),
		_version_number(latest_export[0].version) if latest_export else 0,
	) + 1
	metadata = export_metadata(
		job,
		matter,
		title=options.document_title,
		version=export_version,
		generated_by=frappe.session.user,
	)
	generated_bytes = build_export_files(content, metadata, options)
	artifacts = {}
	for format_name, file_bytes in generated_bytes.items():
		extension = format_name.lower()
		file_name = safe_export_filename(job.name, options.document_title, export_version, extension)
		checksum = hashlib.sha256(file_bytes).hexdigest()
		saved_file = save_file(
			fname=file_name,
			content=file_bytes,
			dt="LPO Job",
			dn=job.name,
			is_private=1,
		)
		release_internally_generated_file(
			saved_file.name,
			expected_checksum=checksum,
			generator=f"Lexocrates {format_name} Export Engine",
			allowed_extensions={f".{extension}"},
		)
		export_record = frappe.get_doc({
			"doctype": "LPO AI Document Export",
			"document_title": options.document_title,
			"processor": processor.name,
			"job": job.name,
			"matter": job.engagement,
			"customer": job.customer,
			"export_format": format_name,
			"version": export_version,
			"status": "Generated",
			"file_url": saved_file.file_url,
			"file_checksum": checksum,
			"file_size": len(file_bytes),
			"page_size": options.page_size,
			"document_style": options.document_style,
			"confidentiality_label": options.confidentiality_label,
			"include_cover_page": options.include_cover_page,
			"include_metadata": options.include_metadata,
			"include_page_numbers": options.include_page_numbers,
			"generation_options": json.dumps(options.__dict__, default=str, sort_keys=True),
			"generated_by": frappe.session.user,
			"generated_on": now_datetime(),
		}).insert(ignore_permissions=True)
		artifacts[format_name] = {
			"file_id": saved_file.name,
			"file_url": saved_file.file_url,
			"download_url": secure_pdf_download_url(saved_file.name) if format_name == "PDF" else saved_file.file_url,
			"file_name": file_name,
			"checksum": checksum,
			"file_size": len(file_bytes),
			"export_record": export_record.name,
		}

	primary_format = "PDF" if "PDF" in artifacts else "DOCX"
	primary_artifact = artifacts[primary_format]

	# Update Processor
	processor.final_output_text = content
	processor.final_output_file = primary_artifact["file_url"]
	processor.final_output_pdf = artifacts.get("PDF", {}).get("file_url") or processor.get("final_output_pdf")
	processor.final_output_docx = artifacts.get("DOCX", {}).get("file_url") or processor.get("final_output_docx")
	processor.output_format = options.output_format
	processor.export_version = export_version
	processor.completed_by = frappe.session.user
	processor.completed_on = now_datetime()
	processor.completion_summary = completion_notes or f"Completed via AI Document Studio on {now_datetime()}"
	processor.status = "Completed"
	processor.save(ignore_permissions=True)

	# File attachment hooks may update the parent timestamp. Reload before saving
	# to avoid false "Document has been modified" conflicts during export.
	job.reload()

	# Update Job
	valid_statuses = ["Ready for Delivery", "QA Review", "In Progress"]
	if update_job_status == "Completed":
		frappe.throw(
			_("AI document generation cannot complete a Job. QA and client approval must finish first."),
			frappe.ValidationError,
		)
	target_status = update_job_status if update_job_status in valid_statuses else "QA Review"
	if target_status == "Ready for Delivery" and job.qa_required:
		target_status = "QA Review"

	job.delivery_document = primary_artifact["file_url"]
	# LPO Job's validation increments this field when the delivery URL changes.
	job.delivery_document_version = max(export_version - 1, 0)
	job.delivery_document_checksum = primary_artifact["checksum"]
	job.delivery_notes = completion_notes or _("AI deliverable v{0}.0 generated in {1} format.").format(export_version, options.output_format)
	job.job_status = target_status
	job.save(ignore_permissions=True)

	create_portal_audit_event(
		client=job.customer,
		action="Job Document Deliverable Completed",
		object_type="LPO Job",
		object_id=job.name,
		new_value={
			"delivery_file": primary_artifact["file_url"],
			"artifacts": {key: value["file_url"] for key, value in artifacts.items()},
			"export_version": export_version,
			"output_format": options.output_format,
			"job_status": target_status,
			"completed_by": frappe.session.user,
		},
	)

	return {
		"status": "success",
		"job_id": job.name,
		"processor_id": processor.name,
		"delivery_file_url": primary_artifact["file_url"],
		"pdf_file_url": artifacts.get("PDF", {}).get("file_url"),
		"pdf_download_url": artifacts.get("PDF", {}).get("download_url"),
		"docx_file_url": artifacts.get("DOCX", {}).get("file_url"),
		"artifacts": artifacts,
		"export_version": export_version,
		"output_format": options.output_format,
		"job_status": job.job_status,
		"message": _("Document v{0}.0 generated as {1} and attached to Job {2}.").format(export_version, options.output_format, job.name),
	}


def _version_number(value) -> int:
	match = re.search(r"\d+", str(value or ""))
	return int(match.group(0)) if match else 0


@frappe.whitelist()
def get_job_document_studio_context(job_id: str) -> dict:
	"""Fetch complete state payload for the interactive Desk AI Document Studio."""
	_ensure_internal_system_user()
	if not frappe.db.exists("LPO Job", job_id):
		frappe.throw(_("Job {0} not found.").format(job_id), frappe.DoesNotExistError)

	ensure_default_ai_document_services()

	job = frappe.get_doc("LPO Job", job_id)
	matter = frappe.get_doc("LPO Matter", job.engagement) if job.engagement else None
	processor = _get_or_create_processor(job_id)

	# Fetch active services
	services = frappe.get_all(
		"LPO AI Document Service",
		filters={"is_active": 1},
		fields=["name", "service_name", "service_code", "category", "description", "icon", "output_format", "default_provider", "default_model", "max_tokens"],
		order_by="category asc, service_name asc",
	)

	# Fetch history
	history = []
	for item in processor.services_applied:
		history.append({
			"name": item.name,
			"service": item.service,
			"service_name": item.service_name,
			"service_code": item.service_code,
			"status": item.status,
			"custom_instructions": item.custom_instructions,
			"output_result": item.output_result,
			"tokens_used": item.tokens_used,
			"cost": item.cost,
			"execution_time_seconds": item.execution_time_seconds,
			"executed_by": item.executed_by,
			"executed_on": item.executed_on,
			"error_message": item.error_message,
		})

	return {
		"job": {
			"name": job.name,
			"job_title": job.job_title,
			"job_type": job.job_type,
			"job_status": job.job_status,
			"engagement": job.engagement,
			"customer": job.customer,
			"customer_name": job.customer_name,
			"source_document": job.source_document,
			"delivery_document": job.delivery_document,
			"ai_tokens_used": job.ai_tokens_used or 0,
			"ai_token_budget": job.ai_token_budget or 1000,
		},
		"matter": {
			"name": matter.name if matter else "",
			"matter_title": matter.matter_title if matter else "",
			"practice_area": matter.practice_area if matter else "",
		} if matter else {},
		"processor": {
			"name": processor.name,
			"status": processor.status,
			"source_file": processor.source_file,
			"extracted_text": processor.extracted_text,
			"word_count": processor.word_count,
			"char_count": processor.char_count,
			"final_output_text": processor.final_output_text,
			"final_output_file": processor.final_output_file,
			"completed_by": processor.completed_by,
			"completed_on": processor.completed_on,
		},
		"services": services,
		"history": history,
	}
