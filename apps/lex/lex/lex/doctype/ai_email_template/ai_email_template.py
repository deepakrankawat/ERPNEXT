from __future__ import annotations

import json
import re
from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_fullname, strip_html

from lex.ai_gateway import invoke_ai_gateway


class AIEmailTemplate(Document):
	def validate(self):
		if not self.prompt or not self.prompt.strip():
			frappe.throw(_("AI Personalization Prompt is required."), frappe.MandatoryError)
		if not self.subject or not self.subject.strip():
			frappe.throw(_("Subject line is required."), frappe.MandatoryError)

	def on_update(self):
		self.sync_with_email_template()

	def sync_with_email_template(self):
		"""Ensure standard Email Template exists so it can be selected in Campaigns."""
		if not frappe.db.exists("DocType", "Email Template"):
			return

		template_name = self.template_name or self.name
		if not frappe.db.exists("Email Template", template_name):
			email_tmpl = frappe.get_doc({
				"doctype": "Email Template",
				"name": template_name,
				"subject": self.subject,
				"response": self.response or f"<p>AI Personalized Outreach powered by AI Email Template: <b>{template_name}</b></p>",
				"use_html": 0,
			})
			if hasattr(email_tmpl, "custom_use_ai_template"):
				email_tmpl.custom_use_ai_template = 1
				email_tmpl.custom_ai_email_template = self.name
			email_tmpl.insert(ignore_permissions=True)
		else:
			email_tmpl = frappe.get_doc("Email Template", template_name)
			email_tmpl.subject = self.subject
			if self.response:
				email_tmpl.response = self.response
			if hasattr(email_tmpl, "custom_use_ai_template"):
				email_tmpl.custom_use_ai_template = 1
				email_tmpl.custom_ai_email_template = self.name
			email_tmpl.save(ignore_permissions=True)


@frappe.whitelist()
def generate_email_for_lead(
	lead: str,
	template: str | None = None,
	custom_notes: str | None = None,
	prompt_override: str | None = None,
	tone_override: str | None = None,
) -> dict[str, Any]:
	"""Generate a bespoke personalized outreach email for a Lead using the AI Gateway."""
	if not lead or not frappe.db.exists("Lead", lead):
		frappe.throw(_("Valid Lead is required."), frappe.DoesNotExistError)

	lead_doc = frappe.get_doc("Lead", lead)
	tmpl_doc = None
	if template:
		if not frappe.db.exists("AI Email Template", template):
			frappe.throw(_("AI Email Template {0} not found.").format(template), frappe.DoesNotExistError)
		tmpl_doc = frappe.get_doc("AI Email Template", template)

	# Extract and sanitize Lead context
	lead_context = {
		"lead_name": lead_doc.lead_name or lead_doc.name,
		"first_name": lead_doc.first_name or (lead_doc.lead_name.split()[0] if lead_doc.lead_name else "there"),
		"last_name": lead_doc.last_name or "",
		"company_name": lead_doc.company_name or lead_doc.get("organization") or "your organization",
		"job_title": lead_doc.get("job_title") or lead_doc.get("designation") or "Legal Counsel",
		"email_id": lead_doc.email_id or "",
		"phone": lead_doc.phone or lead_doc.mobile_no or "",
		"industry": lead_doc.industry or "Legal / Enterprise",
		"territory": lead_doc.territory or "General Jurisdiction",
		"qualification_status": lead_doc.qualification_status or "Unqualified",
		"notes": (custom_notes or "").strip() or (lead_doc.notes or ""),
	}

	prompt_body = prompt_override or (tmpl_doc.prompt if tmpl_doc else "")
	if not prompt_body:
		prompt_body = (
			"Draft a compelling, personalized legal services outreach email highlighting our "
			"LPO capabilities, high turnaround quality, and complimentary pilot engagement."
		)

	# Render Jinja variables in prompt if present
	try:
		prompt_rendered = frappe.render_template(prompt_body, lead_context)
	except Exception:
		prompt_rendered = prompt_body

	tone = tone_override or (tmpl_doc.tone if tmpl_doc else "Consultative & Advisory")
	target_service = tmpl_doc.target_service if tmpl_doc else ""
	base_response = (tmpl_doc.response if tmpl_doc else "") or ""
	generate_subject = cint(tmpl_doc.generate_subject_with_ai) if tmpl_doc else 1
	default_subject = tmpl_doc.subject if tmpl_doc else "Partnership Opportunity with Lexocrates LPO"

	try:
		rendered_subject = frappe.render_template(default_subject, lead_context)
	except Exception:
		rendered_subject = default_subject

	# Build system & instruction prompt
	prompt_text = (
		"You are an elite legal BD & client outreach specialist at Lexocrates, a premier Legal Process Outsourcing (LPO) firm.\n"
		"Write a high-converting, personalized outreach email to the following prospective client:\n\n"
		"--- PROSPECT PROFILE ---\n"
		f"Name: {lead_context['lead_name']}\n"
		f"First Name: {lead_context['first_name']}\n"
		f"Title / Role: {lead_context['job_title']}\n"
		f"Company / Firm: {lead_context['company_name']}\n"
		f"Industry: {lead_context['industry']}\n"
		f"Jurisdiction / Territory: {lead_context['territory']}\n"
		f"Special Notes / Context: {lead_context['notes'] or 'None provided'}\n\n"
		"--- EMAIL OBJECTIVE & GUIDELINES ---\n"
		f"Tone: {tone}\n"
		f"Featured Service Focus: {target_service or 'General LPO (Contract Review, Litigation Support, Research)'}\n"
		f"Custom Instructions: {prompt_rendered}\n"
	)

	if base_response and strip_html(base_response).strip():
		prompt_text += (
			"\n--- BASE REFERENCE TEMPLATE / OUTLINE ---\n"
			f"{strip_html(base_response)}\n"
			"(Adapt, polish, and personalize the above outline for this specific prospect)\n"
		)

	prompt_text += (
		"\n--- CRITICAL OUTPUT RULES ---\n"
		"1. Provide a clear, catchy, professional Subject Line.\n"
		"2. Provide the Email Body formatted in clean HTML (using <p>, <strong>, <ul>/<li> for clarity; no <html> or <body> tags).\n"
		"3. Keep the email authentic, relevant to their industry, concise, and value-driven.\n"
		"4. Mention Lexocrates's Complimentary Pilot Engagement (first assignment eligible at no cost) as a risk-free CTA.\n"
		"5. Format your EXACT output in this structure:\n"
		"SUBJECT: <Subject line here>\n"
		"BODY:\n"
		"<HTML formatted email content here>\n"
	)

	max_tokens = cint(tmpl_doc.max_tokens) if tmpl_doc else 800
	if max_tokens <= 0:
		max_tokens = 800

	provider = (tmpl_doc.ai_provider if tmpl_doc and tmpl_doc.ai_provider else None)
	model = (tmpl_doc.ai_model if tmpl_doc and tmpl_doc.ai_model else None)

	# Call governed AI Gateway
	ai_result = invoke_ai_gateway(
		use_case="Lead Email Personalization",
		prompt_text=prompt_text,
		provider=provider,
		model=model,
		max_tokens=max_tokens,
	)

	raw_text = str(ai_result.get("response_text") or "").strip()
	subject_match = re.search(r"SUBJECT:\s*(.*?)(?:\n|BODY:)", raw_text, re.IGNORECASE)
	body_match = re.search(r"BODY:\s*([\s\S]+)", raw_text, re.IGNORECASE)

	final_subject = subject_match.group(1).strip() if (subject_match and generate_subject) else rendered_subject
	if not final_subject:
		final_subject = rendered_subject

	if body_match:
		final_body = body_match.group(1).strip()
	else:
		final_body = raw_text

	# Clean code fences if AI wrapped HTML in ```html ... ```
	if "```html" in final_body:
		final_body = final_body.split("```html", 1)[1].split("```", 1)[0].strip()
	elif "```" in final_body:
		final_body = final_body.split("```", 1)[1].split("```", 1)[0].strip()

	# If AI returned plain text paragraphs, wrap in <p> tags for email readability
	if "<p>" not in final_body and "<br>" not in final_body:
		paragraphs = [f"<p>{p.strip()}</p>" for p in final_body.split("\n\n") if p.strip()]
		final_body = "".join(paragraphs)

	return {
		"status": "success",
		"lead": lead,
		"lead_name": lead_context["lead_name"],
		"company_name": lead_context["company_name"],
		"email_id": lead_context["email_id"],
		"subject": final_subject,
		"body": final_body,
		"ai_execution": ai_result.get("ai_execution"),
		"tokens_used": ai_result.get("tokens", 0),
		"provider": ai_result.get("provider"),
	}


@frappe.whitelist()
def send_ai_generated_email(
	lead: str,
	subject: str,
	body: str,
	sender: str | None = None,
	cc: str | None = None,
) -> dict[str, Any]:
	"""Send the AI-generated email to the Lead and record it in Communication timeline."""
	if not lead or not frappe.db.exists("Lead", lead):
		frappe.throw(_("Lead {0} not found.").format(lead), frappe.DoesNotExistError)

	lead_doc = frappe.get_doc("Lead", lead)
	recipient = lead_doc.email_id
	if not recipient:
		frappe.throw(_("Lead {0} does not have an email address.").format(lead_doc.lead_name or lead), frappe.ValidationError)

	from frappe.core.doctype.communication.email import make

	sender_email = sender or frappe.session.user
	user_fullname = get_fullname(sender_email)
	formatted_sender = f"{user_fullname} <{sender_email}>" if "@" in sender_email else sender_email

	communication = make(
		doctype="Lead",
		name=lead_doc.name,
		subject=subject,
		content=body,
		sender=formatted_sender,
		recipients=[recipient],
		cc=[c.strip() for c in (cc or "").split(",") if c.strip()],
		communication_medium="Email",
		sent_or_received="Sent",
		send_email=True,
	)

	return {
		"status": "success",
		"communication": communication.get("name") if isinstance(communication, dict) else str(communication),
		"recipient": recipient,
		"message": _("Personalized email successfully sent to {0}.").format(recipient),
	}
