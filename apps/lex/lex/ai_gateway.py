from __future__ import annotations

import hashlib
import json

import frappe
import requests
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from lex.ai_citation_verifier import verify_ai_citations
from lex.ai_dlp_sanitizer import sanitize_text_for_ai
from lex.client_access import get_portal_user, has_matter_access
from lex.portal_audit import create_portal_audit_event


POLICY_DOCTYPE = "LPO AI Governance Policy"
INTERNAL_AI_ROLES = {"LPO_Admin", "LPO_Manager", "LPO_Analyst", "System Manager"}
SCOPE_LABELS = {"global": "Global", "provider": "Provider", "model": "Model", "use_case": "Use Case"}


@frappe.whitelist()
def set_ai_kill_switch(target_type: str, target_name: str, enabled: bool):
	"""Persist an emergency kill switch so it survives workers, restarts, and deployments."""
	if frappe.session.user != "Administrator" and "LPO_Admin" not in frappe.get_roles(frappe.session.user):
		frappe.throw(_("Administrator permission is required for AI Kill Switch."), frappe.PermissionError)
	if target_type not in SCOPE_LABELS:
		frappe.throw(_("Kill switch scope must be global, provider, model, or use_case."), frappe.ValidationError)
	scope = SCOPE_LABELS[target_type]
	target = "*" if target_type == "global" else (target_name or "").strip()
	if not target:
		frappe.throw(_("Kill switch target is required."), frappe.MandatoryError)
	policy = _get_policy(scope, target, create=True)
	policy.disabled = cint(enabled)
	policy.updated_by = frappe.session.user
	policy.updated_on = now_datetime()
	policy.save(ignore_permissions=True)
	create_portal_audit_event(
		client=None,
		user=frappe.session.user,
		action="AI Kill Switch Toggled",
		object_type=POLICY_DOCTYPE,
		object_id=policy.name,
		new_value={"target_type": target_type, "target_name": target, "enabled": bool(cint(enabled))},
		details="Global AI governance action; no client-owned record is linked.",
	)
	return {"status": "updated", "target": f"{target_type}:{target}", "enabled": bool(cint(enabled))}


@frappe.whitelist()
def invoke_ai_gateway(
	use_case: str,
	prompt_text: str,
	client_id: str | None = None,
	matter_id: str | None = None,
	job_id: str | None = None,
	provider: str = "OpenAI",
	model: str = "gpt-4o",
	prompt_version: str | None = None,
	is_high_risk: int = 0,
	source_corpus: str | list | None = None,
):
	"""Execute an authorized, retained, retry-bounded AI call through a configured gateway."""
	client_id = _authorize_ai_subject(client_id, matter_id, job_id)
	_assert_kill_switches(provider, model, use_case)
	provider_policy = _get_policy("Provider", provider, create=True)
	_assert_circuit_available(provider_policy)

	sanitized_prompt, dlp_meta = sanitize_text_for_ai(prompt_text)
	started = now_datetime()
	execution_values = {
		"doctype": "LPO AI Execution",
		"use_case": use_case,
		"client": client_id,
		"matter": matter_id,
		"job": job_id,
		"model_provider_version": f"{provider}/{model}",
		"status": "Running",
		"redaction_consent": json.dumps(dlp_meta, default=str),
		"start_time": started,
		"retention_until": add_to_date(started, days=int(provider_policy.retention_days or 90)),
		"evaluation_status": "Pending",
	}
	if prompt_version and frappe.db.exists("LPO Prompt Version", prompt_version):
		execution_values["prompt_version"] = prompt_version
	execution_doc = frappe.get_doc(execution_values).insert(ignore_permissions=True)

	retry_count = 0
	try:
		provider_result, retry_count = _call_provider_with_retries(
			provider=provider,
			model=model,
			use_case=use_case,
			prompt=sanitized_prompt,
			correlation_id=execution_doc.name,
			retry_limit=int(provider_policy.retry_limit or 0),
		)
		raw_response = str(provider_result.get("output_text") or "")
		if not raw_response:
			raise RuntimeError("AI provider returned an empty normalized response")
		usage = provider_result.get("usage") or {}
		total_tokens = int(usage.get("total_tokens") or 0)
		provider_cost = float(usage.get("cost") or 0)
		citation_res = verify_ai_citations(raw_response, source_corpus or "")
		requires_human_review = bool(cint(is_high_risk)) or not citation_res["verified"]
		execution_doc.status = "Human Review" if requires_human_review else "Completed"
		execution_doc.evaluation_status = "Human Review" if requires_human_review else "Passed"
		execution_doc.raw_normalized_result = raw_response
		execution_doc.citations = json.dumps(citation_res, default=str)
		execution_doc.tokens = total_tokens
		execution_doc.provider_cost = provider_cost
		execution_doc.retries = retry_count
		execution_doc.provider_request_id = provider_result.get("request_id")
		execution_doc.input_output_hash = hashlib.sha256(
			f"{sanitized_prompt}\0{raw_response}".encode("utf-8")
		).hexdigest()
		execution_doc.end_time = now_datetime()
		execution_doc.save(ignore_permissions=True)
		_record_provider_success(provider_policy)
		create_portal_audit_event(
			client=client_id,
			action="AI Gateway Execution Completed",
			object_type="LPO AI Execution",
			object_id=execution_doc.name,
			new_value={
				"tokens": total_tokens,
				"cost": provider_cost,
				"human_review_required": requires_human_review,
				"retries": retry_count,
			},
		)
		return {
			"ai_execution": execution_doc.name,
			"response_text": raw_response,
			"tokens": total_tokens,
			"cost": provider_cost,
			"citation_verified": citation_res["verified"],
			"requires_human_review": requires_human_review,
		}
	except Exception as exc:
		execution_doc.status = "Failed"
		execution_doc.evaluation_status = "Failed"
		execution_doc.error = str(exc)[:500]
		execution_doc.retries = retry_count
		execution_doc.end_time = now_datetime()
		execution_doc.save(ignore_permissions=True)
		_record_provider_failure(provider_policy, str(exc))
		create_portal_audit_event(
			client=client_id,
			action="AI Gateway Execution Failed",
			object_type="LPO AI Execution",
			object_id=execution_doc.name,
			result="Failure",
			new_value={"provider": provider, "model": model, "retries": retry_count},
			details=str(exc)[:500],
		)
		frappe.throw(_("AI execution failed and was recorded for review."), frappe.ValidationError)


def _authorize_ai_subject(client_id, matter_id, job_id):
	portal_user = get_portal_user()
	if portal_user:
		client_id = portal_user.client
		if matter_id and not has_matter_access(matter_id, "view"):
			frappe.throw(_("You cannot use AI for this Matter."), frappe.PermissionError)
		if job_id:
			job = frappe.db.get_value("LPO Job", job_id, ["customer", "engagement", "ai_processing_allowed"], as_dict=True)
			if not job or job.customer != client_id or not has_matter_access(job.engagement, "view"):
				frappe.throw(_("You cannot use AI for this Job."), frappe.PermissionError)
			if not job.ai_processing_allowed:
				frappe.throw(_("AI processing is disabled for this Job."), frappe.PermissionError)
	else:
		roles = set(frappe.get_roles(frappe.session.user))
		if frappe.session.user != "Administrator" and not roles.intersection(INTERNAL_AI_ROLES):
			frappe.throw(_("AI Gateway permission is required."), frappe.PermissionError)
	if matter_id:
		matter_client = frappe.db.get_value("LPO Matter", matter_id, "customer")
		if not matter_client or (client_id and matter_client != client_id):
			frappe.throw(_("Matter does not belong to the selected Client."), frappe.ValidationError)
		client_id = matter_client
	if job_id:
		job_client = frappe.db.get_value("LPO Job", job_id, "customer")
		if not job_client or (client_id and job_client != client_id):
			frappe.throw(_("Job does not belong to the selected Client."), frappe.ValidationError)
		client_id = job_client
	return client_id


def _get_policy(scope_type: str, target_name: str, *, create: bool):
	name = frappe.db.get_value(POLICY_DOCTYPE, {"scope_type": scope_type, "target_name": target_name}, "name")
	if name:
		return frappe.get_doc(POLICY_DOCTYPE, name)
	if not create:
		return None
	return frappe.get_doc({
		"doctype": POLICY_DOCTYPE,
		"scope_type": scope_type,
		"target_name": target_name,
		"disabled": 0,
		"retry_limit": 2,
		"retention_days": 90,
		"circuit_failure_threshold": 3,
		"circuit_state": "Closed",
		"consecutive_failures": 0,
		"updated_by": frappe.session.user,
		"updated_on": now_datetime(),
	}).insert(ignore_permissions=True)


def _assert_kill_switches(provider, model, use_case):
	for scope, target, label in (
		("Global", "*", _("AI Gateway")),
		("Provider", provider, _("Provider '{0}'").format(provider)),
		("Model", model, _("Model '{0}'").format(model)),
		("Use Case", use_case, _("Use Case '{0}'").format(use_case)),
	):
		policy = _get_policy(scope, target, create=False)
		if policy and policy.disabled:
			frappe.throw(_("{0} is disabled by a durable Kill Switch.").format(label), frappe.PermissionError)


def _assert_circuit_available(policy):
	if policy.circuit_state != "Open":
		return
	if policy.circuit_open_until and get_datetime(policy.circuit_open_until) <= now_datetime():
		policy.circuit_state = "Half Open"
		policy.save(ignore_permissions=True)
		return
	frappe.throw(_("The AI provider circuit is open after repeated failures."), frappe.ValidationError)


def _call_provider_with_retries(*, provider, model, use_case, prompt, correlation_id, retry_limit):
	if getattr(frappe.flags, "in_test", False):
		text = f"AI test output for [{use_case}]"
		return {
			"output_text": text,
			"usage": {"total_tokens": len(prompt.split()) + len(text.split()), "cost": 0},
			"request_id": f"test-{correlation_id}",
		}, 0
	config = _provider_config(provider)
	last_error = None
	for attempt in range(retry_limit + 1):
		try:
			response = requests.post(
				config["endpoint"],
				headers={"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"},
				json={"model": model, "use_case": use_case, "prompt": prompt, "correlation_id": correlation_id},
				timeout=int(config.get("timeout_seconds") or 60),
			)
			response.raise_for_status()
			data = response.json()
			if not isinstance(data, dict):
				raise RuntimeError("AI gateway returned an invalid response contract")
			return data, attempt
		except (requests.RequestException, ValueError, RuntimeError) as exc:
			last_error = exc
	raise RuntimeError(f"AI provider failed after {retry_limit + 1} attempts: {last_error}")


def _provider_config(provider):
	providers = frappe.conf.get("lexocrates_ai_providers") or {}
	if isinstance(providers, str):
		providers = json.loads(providers)
	config = providers.get(provider) if isinstance(providers, dict) else None
	if not config or not config.get("endpoint") or not config.get("api_key"):
		raise RuntimeError(f"AI provider '{provider}' is not configured")
	return config


def _record_provider_success(policy):
	frappe.db.set_value(POLICY_DOCTYPE, policy.name, {
		"circuit_state": "Closed",
		"consecutive_failures": 0,
		"circuit_open_until": None,
		"last_failure": None,
	}, update_modified=False)


def _record_provider_failure(policy, error):
	failures = int(policy.consecutive_failures or 0) + 1
	threshold = max(1, int(policy.circuit_failure_threshold or 3))
	values = {"consecutive_failures": failures, "last_failure": error[:500]}
	if failures >= threshold:
		values.update({"circuit_state": "Open", "circuit_open_until": add_to_date(now_datetime(), minutes=5)})
	frappe.db.set_value(POLICY_DOCTYPE, policy.name, values, update_modified=False)
