from __future__ import annotations

import base64
import hashlib
import io
import os
from decimal import Decimal, ROUND_CEILING
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, now_datetime, nowdate

from lex.client_access import get_portal_user

PAGES_PER_HOUR = 30
PRICING_VERSION = "COUNTRY-CURRENCY-FIXED-30PPH-1.1"
SUPPORTED_ESTIMATE_CURRENCIES = {"CAD", "USD", "GBP"}
COUNTRY_CURRENCY = {
	"canada": "CAD",
	"united states": "USD",
	"usa": "USD",
	"united kingdom": "GBP",
	"uk": "GBP",
	"great britain": "GBP",
}
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


def _store_instant_estimate_document_on_job(job, filename: str, pdf_bytes: bytes) -> dict[str, Any]:
	"""Store the instant-estimate source PDF on its Draft Job, never the Matter.

	The Matter remains the commercial/legal parent only.  The Job is the source
	of truth for the assignment document, including scan result and checksum.
	This deliberately does not invalidate the already-calculated fixed quote.
	"""
	from frappe.utils.file_manager import save_file
	from lex.file_quarantine import scan_and_validate_inbound_file

	filename = os.path.basename((filename or "").strip())
	if not filename:
		frappe.throw(_("A source PDF filename is required."), frappe.ValidationError)

	with _service_writes():
		file_doc = save_file(
			filename,
			pdf_bytes,
			"LPO Job",
			job.name,
			is_private=1,
			df="source_document",
		)

	scan = scan_and_validate_inbound_file(file_doc.name)
	file_doc.reload()
	job.reload()
	with _portal_service_writes():
		job.append("job_documents", {
			"file": file_doc.name,
			"file_name": file_doc.file_name,
			"document_role": "Source",
			"scan_status": scan["status"],
			"checksum": file_doc.get("custom_lex_checksum"),
			"document_version": 1,
			"included_in_estimate": 1,
			"uploaded_by": frappe.session.user,
			"uploaded_on": now_datetime(),
		})
		if scan["status"] == "Clean":
			job.source_document = file_doc.file_url
		job.save(ignore_permissions=True)

	return {
		"file": file_doc.name,
		"scan_status": scan["status"],
		"quarantine_passed": scan["quarantine_passed"],
	}


def extract_pdf_pages_and_text(pdf_bytes: bytes) -> tuple[int, str]:
	"""Extract the PDF's exact native page count; text is never used for pricing."""
	from pypdf import PdfReader

	stream = io.BytesIO(pdf_bytes)
	reader = PdfReader(stream)
	pages = len(reader.pages)

	return pages, ""


def round_up_to_cad_five(amount: Decimal) -> Decimal:
	"""Round a non-negative amount upward to the next whole multiple of five."""
	if amount < 0:
		raise ValueError("CAD amount cannot be negative.")
	return (amount / Decimal("5")).to_integral_value(rounding=ROUND_CEILING) * Decimal("5")


def _estimate_currency_for_client(client: str | None) -> tuple[str, str]:
	"""Resolve the estimate currency from the client's registered country."""
	if not client:
		return "CAD", "Canada"
	customer = frappe.db.get_value(
		"Customer", client, ["custom_primary_jurisdiction", "territory", "default_currency"], as_dict=True
	) or {}
	country = str(customer.get("custom_primary_jurisdiction") or customer.get("territory") or "Canada").strip()
	lookup = country.lower()
	for marker, currency in COUNTRY_CURRENCY.items():
		if marker in lookup:
			return currency, country
	configured = str(customer.get("default_currency") or "").upper()
	return (configured if configured in SUPPORTED_ESTIMATE_CURRENCIES else "CAD"), country


def _cad_exchange_rate(currency: str) -> Decimal:
	if currency == "CAD":
		return Decimal("1")
	from erpnext.setup.utils import get_exchange_rate

	rate = Decimal(str(get_exchange_rate("CAD", currency, nowdate(), "for_selling") or 0))
	if rate <= 0:
		raise ValueError(f"A current CAD to {currency} exchange rate is required before estimating this assignment.")
	return rate


def calculate_page_based_pricing(
	pages: int,
	service: str,
	turnaround: str = "Standard (3-5 Business Days)",
	*,
	currency: str = "CAD",
	exchange_rate: Decimal | None = None,
) -> dict[str, Any]:
	"""Return the authoritative country-currency fixed-rate PDF estimate.

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
	raw_price_cad = (Decimal(pages) * rate) / Decimal(PAGES_PER_HOUR)
	currency = str(currency or "CAD").upper()
	if currency not in SUPPORTED_ESTIMATE_CURRENCIES:
		raise ValueError("Only CAD, USD and GBP are supported for country-based pricing.")
	fx_rate = Decimal(str(exchange_rate)) if exchange_rate is not None else _cad_exchange_rate(currency)
	if fx_rate <= 0:
		raise ValueError("A positive exchange rate is required.")
	raw_price = raw_price_cad * fx_rate
	final_price = round_up_to_cad_five(raw_price)
	turnaround_text = str(turnaround or "Standard (3-5 Business Days)").strip()

	return {
		"has_error": False,
		"price_amount": f"{int(final_price)} {currency}",
		"volume_text": f"{pages} exact native PDF pages / {PAGES_PER_HOUR} pages/hour = {exact_hours} hours",
		"service_text": service,
		"rate_text": f"{rate:.2f} CAD/hour",
		"fx_text": "CAD base pricing; converted server-side using the saved exchange rate.",
		"turnaround_text": turnaround_text,
		"page_count_source": "Exact native PDF page count",
		"calculation_text": "Final price is calculated server-side from exact native PDF pages and the selected fixed CAD hourly rate.",
		"pages": pages,
		"estimated_hours": exact_hours,
		"exact_hours": exact_hours,
		"fixed_service_rate_cad": rate,
		"raw_price_cad": raw_price_cad,
		"final_price_cad": round_up_to_cad_five(raw_price_cad),
		"raw_price": raw_price,
		"final_price": final_price,
		"price_min": final_price,
		"price_max": final_price,
		"currency": currency,
		"source_currency": "CAD",
		"exchange_rate": fx_rate,
		"exchange_rate_date": nowdate(),
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
	"Legal Operations Support": "Other",
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
	"Legal Operations Support": "Other",
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


def _find_saved_quick_estimate(client: str, portal_user_name: str, checksum: str, service: str):
	"""Return an unfunded saved Quick Lextimator estimate for the same PDF.

	The checksum, selected service and portal user together make a repeat of an
	estimate request idempotent.  In particular, a browser retry must not create
	another Matter, Work Intake or Draft Job before the client has paid.
	"""
	jobs = frappe.get_all(
		"LPO Job",
		filters={
			"customer": client,
			"source_document_checksum": checksum,
			"selected_pricing_service": service,
			"job_status": "Draft",
		},
		fields=[
			"name",
			"engagement",
			"work_intake",
			"currency",
			"quoted_amount",
			"pricing_exchange_rate",
			"final_rounded_price_cad",
		],
		order_by="modified desc",
		limit_page_length=10,
	)
	for job in jobs:
		if not job.work_intake:
			continue
		intake = frappe.db.get_value(
			"Lexocrates Work Intake",
			job.work_intake,
			["name", "portal_user", "status", "funding_status", "quote_status"],
			as_dict=True,
		)
		if not intake or intake.portal_user != portal_user_name:
			continue
		if intake.quote_status == "Ready" and intake.funding_status != "Funded" and intake.status != "Matter Confirmed":
			return frappe._dict({"job": job, "intake": intake})
	return None


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

	portal_user = get_portal_user()
	client = portal_user.client if portal_user else None
	estimate_currency, client_country = _estimate_currency_for_client(client)
	selected_service = str(service or "").strip()
	try:
		pricing = calculate_page_based_pricing(
			pages, selected_service, turnaround or "Standard (3-5 Business Days)", currency=estimate_currency
		)
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
	final_price = int(pricing["final_price"])
	delivery_hours = max(1, int(pricing["exact_hours"].to_integral_value(rounding=ROUND_CEILING)))
	pricing_audit = (
		f"Pricing version {pricing['pricing_version']}; exact native PDF pages={pages}; "
		f"calculated hours={pricing['exact_hours']}; selected service={detected_service}; "
		f"fixed CAD/hour={pricing['fixed_service_rate_cad']}; raw CAD price={pricing['raw_price_cad']}; "
		f"final rounded {pricing['currency']} price={final_price}; CAD/{pricing['currency']} exchange rate={pricing['exchange_rate']}."
	)


	# Save an estimate record first.  A Razorpay order is deliberately created
	# later, only when the client explicitly selects secure payment.
	intake_name = None
	matter_name = None

	if client:
		saved = _find_saved_quick_estimate(
			client, portal_user.name, hashlib.sha256(pdf_bytes).hexdigest(), detected_service
		)
		if saved:
			saved_job = saved.job
			intake_name = saved.intake.name
			matter_name = saved_job.engagement
			# Preserve the original saved fixed quote on retries, even if an FX rate
			# changes after the client first received the estimate.
			if saved_job.quoted_amount is not None:
				saved_price = Decimal(str(saved_job.quoted_amount))
				pricing["price_amount"] = f"{int(saved_price)} {saved_job.currency}"
				pricing["final_price"] = saved_price
				pricing["price_min"] = saved_price
				pricing["price_max"] = saved_price
				pricing["currency"] = saved_job.currency
				pricing["exchange_rate"] = Decimal(str(saved_job.pricing_exchange_rate or pricing["exchange_rate"]))
			pricing["intake"] = intake_name
			pricing["matter"] = matter_name
			pricing["payment_ready"] = True
			return _serialize_pricing(pricing)

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
				"jurisdictions": client_country,
				"description": "Parent Matter for the Draft Job created from this client request.",
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
				"jurisdiction": client_country,
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
				"currency": pricing["currency"],
				"exchange_rate": pricing["exchange_rate"],
				"document_count": 1,
				"selected_pricing_service": detected_service,
				"exact_pdf_page_count": pages,
				"calculated_hours": str(pricing["exact_hours"]),
				"fixed_service_rate_cad": pricing["fixed_service_rate_cad"],
				"raw_price_cad": pricing["raw_price_cad"],
				"final_rounded_price_cad": pricing["final_price_cad"],
				"pricing_exchange_rate": pricing["exchange_rate"],
				"pricing_exchange_rate_date": pricing["exchange_rate_date"],
				"pricing_version": pricing["pricing_version"],
				"quote_status": "Ready",
				"quoted_amount": final_price,
				"required_legal_capacity": final_price,
				"delivery_timeline_hours": delivery_hours,
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
				"estimate_status": "Ready",
				"quote_version": 1,
				"required_legal_capacity": final_price,
				"quoted_amount": final_price,
				"currency": pricing["currency"],
				"selected_pricing_service": detected_service,
				"exact_pdf_page_count": pages,
				"calculated_hours": str(pricing["exact_hours"]),
				"fixed_service_rate_cad": pricing["fixed_service_rate_cad"],
				"raw_price_cad": pricing["raw_price_cad"],
				"final_rounded_price_cad": pricing["final_price_cad"],
				"pricing_exchange_rate": pricing["exchange_rate"],
				"pricing_exchange_rate_date": pricing["exchange_rate_date"],
				"pricing_version": pricing["pricing_version"],
				"received_at": frappe.utils.now_datetime(),
				"due_date": frappe.utils.add_days(frappe.utils.nowdate(), 3),
				"qa_required": 1,
			}).insert(ignore_permissions=True)

			intake.job = job.name
			intake.save(ignore_permissions=True)

			# The uploaded PDF and its estimate lineage belong to the Draft Job.
			# Matter is intentionally only the parent legal/commercial container.
			_store_instant_estimate_document_on_job(job, filename, pdf_bytes)

	pricing["intake"] = intake_name
	pricing["matter"] = matter_name
	pricing["payment_ready"] = bool(intake_name)
	return _serialize_pricing(pricing)


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
