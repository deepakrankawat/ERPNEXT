# Copyright (c) 2026, Lexocrates and contributors
# For license information, please see license.txt

from __future__ import annotations

import os
from urllib.parse import urlparse

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, now_datetime
from frappe.utils.password import decrypt, get_decrypted_password, set_encrypted_password

from lex.ai_providers import (
	AIProviderError,
	DEFAULT_ENDPOINT_TYPES,
	SUPPORTED_PROVIDERS,
	choose_preferred_model,
	discover_provider_models,
	get_verified_models,
	is_text_model_candidate,
	mark_model_verification,
	normalize_provider,
	require_verified_model,
	sync_model_registry,
	verify_provider_model,
)


AI_SETTINGS_ADMIN_ROLES = {"System Manager", "LPO_Admin"}
AI_INTERNAL_ROLES = {"System Manager", "LPO_Admin", "LPO_Manager", "LPO_Analyst"}
PROVIDER_FIELDS = {
	"OpenAI": {
		"key": "openai_api_key",
		"legacy_key": "encrypted_openai_key",
		"enabled": "enable_openai",
		"status": "openai_status",
		"default_model": "openai_default_model",
		"available_models": "openai_available_models",
		"last_verified_on": "openai_last_verified_on",
		"last_latency_ms": "openai_last_latency_ms",
		"last_error": "openai_last_error",
	},
	"Google Gemini": {
		"key": "gemini_api_key",
		"legacy_key": "encrypted_gemini_key",
		"enabled": "enable_gemini",
		"status": "gemini_status",
		"default_model": "gemini_default_model",
		"available_models": "gemini_available_models",
		"last_verified_on": "gemini_last_verified_on",
		"last_latency_ms": "gemini_last_latency_ms",
		"last_error": "gemini_last_error",
	},
	"Anthropic": {
		"key": "anthropic_api_key",
		"legacy_key": "encrypted_anthropic_key",
		"enabled": "enable_anthropic",
		"status": "anthropic_status",
		"default_model": "anthropic_default_model",
		"available_models": "anthropic_available_models",
		"last_verified_on": "anthropic_last_verified_on",
		"last_latency_ms": "anthropic_last_latency_ms",
		"last_error": "anthropic_last_error",
	},
}
ENVIRONMENT_KEYS = {
	"OpenAI": ("OPENAI_API_KEY", "LEXOCRATES_OPENAI_API_KEY"),
	"Google Gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY", "LEXOCRATES_GEMINI_API_KEY"),
	"Anthropic": ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "LEXOCRATES_ANTHROPIC_API_KEY"),
}


class LPOAISettings(Document):
	def validate(self):
		self.default_max_tokens = max(200, min(cint(self.default_max_tokens or 2000), 32000))
		self.provider_timeout_seconds = max(5, min(cint(self.provider_timeout_seconds or 45), 120))
		self._validate_endpoints()
		self._validate_named_credentials()
		self._protect_direct_password_inputs()

	def _validate_named_credentials(self):
		seen = set()
		for row in self.get("provider_credentials") or []:
			row.credential_name = _validate_credential_name(row.credential_name)
			key = row.credential_name.casefold()
			if key in seen:
				frappe.throw(_("API credential names must be unique."), frappe.ValidationError)
			seen.add(key)
			row.provider = normalize_provider(row.provider)
			row.priority = max(1, min(cint(row.priority or 10), 999))
			_validate_provider_base_url(row.provider, row.base_url)
			if cint(row.enabled) and "verified" not in str(row.verification_status or "").lower():
				frappe.throw(
					_("Credential '{0}' must pass live verification before it can be enabled.").format(row.credential_name),
					frappe.ValidationError,
				)

	def _validate_endpoints(self):
		allowed_hosts = {
			"openai_base_url": "api.openai.com",
			"gemini_base_url": "generativelanguage.googleapis.com",
			"anthropic_base_url": "api.anthropic.com",
		}
		allow_custom = cint(frappe.conf.get("allow_custom_ai_endpoints"))
		for fieldname, official_host in allowed_hosts.items():
			value = str(self.get(fieldname) or "").strip()
			if not value:
				continue
			parsed = urlparse(value)
			if parsed.scheme != "https" or not parsed.netloc:
				frappe.throw(_("{0} must be a valid HTTPS API URL.").format(self.meta.get_label(fieldname)), frappe.ValidationError)
			if not allow_custom and parsed.hostname != official_host:
				frappe.throw(
					_("{0} must use the official provider host. Configure approved custom gateways in site_config.json.").format(self.meta.get_label(fieldname)),
					frappe.ValidationError,
				)

	def _protect_direct_password_inputs(self):
		ignore_fields = []
		for provider, fields in PROVIDER_FIELDS.items():
			fieldname = fields["key"]
			value = self.get(fieldname)
			if not value or _is_dummy_password(value):
				ignore_fields.append(fieldname)
				continue
			clean_key = _validate_key_input(value)
			set_encrypted_password("LPO AI Settings", "LPO AI Settings", clean_key, fieldname)
			self.set(fields["enabled"], 0)
			self.set(fields["status"], "Verification required")
			ignore_fields.append(fieldname)
		self.flags.ignore_save_passwords = ignore_fields

	@frappe.whitelist()
	def fetch_provider_models(self, provider: str, api_key: str | None = None, verify_limit: int = 3) -> dict:
		return _fetch_models_logic(self, provider, api_key, verify_limit=verify_limit)


def _require_ai_settings_admin():
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Authentication required."), frappe.AuthenticationError)
	roles = set(frappe.get_roles(user))
	if user != "Administrator" and not roles.intersection(AI_SETTINGS_ADMIN_ROLES):
		frappe.throw(_("System Manager or LPO Admin permission is required for AI provider settings."), frappe.PermissionError)


def _require_internal_ai_user():
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Authentication required."), frappe.AuthenticationError)
	roles = set(frappe.get_roles(user))
	if user != "Administrator" and not roles.intersection(AI_INTERNAL_ROLES):
		frappe.throw(_("AI provider configuration is restricted to internal System Users."), frappe.PermissionError)


@frappe.whitelist()
def fetch_provider_models(provider: str, api_key: str | None = None, verify_limit: int = 3) -> dict:
	_require_ai_settings_admin()
	settings = _get_settings()
	return _fetch_models_logic(settings, provider, api_key, verify_limit=verify_limit)


def _fetch_models_logic(settings: Document | None, provider: str, api_key: str | None = None, verify_limit: int = 3) -> dict:
	_require_ai_settings_admin()
	provider = normalize_provider(provider)
	key = _get_provider_key(settings, provider, api_key)
	if not key:
		return _missing_key_result(provider, settings)

	try:
		discovered = discover_provider_models(provider, key, settings)
		sync_model_registry(provider, discovered)
		model_ids = [row["model_id"] for row in discovered]
		fields = PROVIDER_FIELDS[provider]
		current = settings.get(fields["default_model"]) if settings else None
		preferred = choose_preferred_model(provider, model_ids, current)
		limit = max(1, min(cint(verify_limit or 3), 10))
		candidates = list(dict.fromkeys([preferred, *model_ids]))[:limit]
		results = [verify_provider_model(provider, model, key, settings) for model in candidates if model]
		verified = [row["model_id"] for row in get_verified_models(provider)]
		default_model = preferred if preferred in verified else (verified[0] if verified else None)
		_update_provider_state(
			settings,
			provider,
			success=bool(default_model),
			model=default_model,
			models=verified,
			latency_ms=next((row.get("latency_ms") for row in results if row.get("status") == "success"), None),
			error=None if default_model else _("No discovered model passed the live text-generation test."),
			disable_on_failure=True,
		)
		return {
			"status": "success" if default_model else "error",
			"provider": provider,
			"discovered_count": len(model_ids),
			"verified_count": len(verified),
			"models": verified,
			"default_model": default_model,
			"diagnostics": results,
			"message": _("Discovered {0} compatible candidates; {1} model(s) passed live verification.").format(len(model_ids), len(verified)),
		}
	except AIProviderError as exc:
		_update_provider_state(settings, provider, success=False, error=exc.safe_message, disable_on_failure=exc.category in {"AUTHENTICATION", "MISSING_KEY"})
		_log_settings_error(provider, exc)
		return _provider_error_result(exc)
	except Exception as exc:
		_update_provider_state(settings, provider, success=False, error=str(exc))
		_log_settings_error(provider, exc)
		return {"status": "error", "provider": provider, "error_type": "DISCOVERY_ERROR", "message": _("Model discovery failed: {0}").format(str(exc)[:300])}


@frappe.whitelist()
def save_provider_api_key(provider: str, api_key: str) -> dict:
	_require_ai_settings_admin()
	provider = normalize_provider(provider)
	fields = PROVIDER_FIELDS[provider]
	settings = _get_settings()

	if api_key == "CLEAR_KEY":
		set_encrypted_password("LPO AI Settings", "LPO AI Settings", "", fields["key"])
		frappe.db.set_value("LPO AI Settings", "LPO AI Settings", {
			fields["legacy_key"]: None,
			fields["enabled"]: 0,
			fields["status"]: "Key missing",
			fields["available_models"]: None,
			fields["last_error"]: None,
		}, update_modified=False)
		return {"status": "success", "provider": provider, "message": _("API key removed. Provider is disabled.")}

	clean_key = _validate_key_input(api_key)
	try:
		discovered = discover_provider_models(provider, clean_key, settings)
		model_ids = [row["model_id"] for row in discovered]
		current = settings.get(fields["default_model"]) if settings else None
		model = choose_preferred_model(provider, model_ids, current)
		if not model:
			raise AIProviderError(provider, _("No compatible text-generation model was returned for this key."), "NO_COMPATIBLE_MODEL")
		test_result = verify_provider_model(provider, model, clean_key, settings)
		if test_result.get("status") != "success":
			return {
				"status": "error",
				"provider": provider,
				"error_type": test_result.get("error_type"),
				"message": _("Key was not saved because the live provider test failed: {0}").format(test_result.get("message")),
			}

		set_encrypted_password("LPO AI Settings", "LPO AI Settings", clean_key, fields["key"])
		sync_model_registry(provider, discovered)
		mark_model_verification(provider, model, True, latency_ms=test_result.get("latency_ms"))
		_update_provider_state(
			settings,
			provider,
			success=True,
			model=model,
			models=[model],
			latency_ms=test_result.get("latency_ms"),
		)
		frappe.db.set_value("LPO AI Settings", "LPO AI Settings", fields["legacy_key"], None, update_modified=False)
		if not settings.default_provider or not _get_provider_key(settings, settings.default_provider):
			frappe.db.set_value("LPO AI Settings", "LPO AI Settings", "default_provider", provider, update_modified=False)
		return {
			"status": "success",
			"provider": provider,
			"model": model,
			"latency_ms": test_result.get("latency_ms"),
			"message": _("API key encrypted in Frappe Password storage and live-verified successfully."),
		}
	except AIProviderError as exc:
		_log_settings_error(provider, exc)
		return _provider_error_result(exc, prefix=_("Key was not saved"))


@frappe.whitelist()
def save_provider_credential(
	credential_name: str,
	provider: str,
	api_key: str,
	base_url: str | None = None,
	organization_id: str | None = None,
	project_id: str | None = None,
	priority: int = 10,
) -> dict:
	"""Live-verify and store one named credential in encrypted child Password storage."""
	_require_ai_settings_admin()
	settings = _get_settings()
	credential_name = _validate_credential_name(credential_name)
	provider = normalize_provider(provider)
	clean_key = _validate_key_input(api_key)
	base_url = str(base_url or "").strip() or None
	_validate_provider_base_url(provider, base_url)
	credential_settings = _credential_request_settings(
		settings,
		provider=provider,
		base_url=base_url,
		organization_id=organization_id,
		project_id=project_id,
	)

	try:
		discovered = discover_provider_models(provider, clean_key, credential_settings)
		model_ids = [row["model_id"] for row in discovered]
		preferred = choose_preferred_model(provider, model_ids)
		if not preferred:
			raise AIProviderError(provider, _("No compatible text-generation model was returned for this key."), "NO_COMPATIBLE_MODEL")
		candidates = list(dict.fromkeys([preferred, *model_ids]))[:3]
		results = [
			verify_provider_model(
				provider,
				candidate,
				clean_key,
				credential_settings,
				update_registry=False,
			)
			for candidate in candidates
		]
		verified_models = [candidate for candidate, result in zip(candidates, results) if result.get("status") == "success"]
		if not verified_models:
			failure = results[0] if results else {}
			return {
				"status": "error",
				"provider": provider,
				"credential_name": credential_name,
				"error_type": failure.get("error_type"),
				"message": _("Credential was not saved because live verification failed: {0}").format(failure.get("message")),
			}

		sync_model_registry(provider, discovered)
		for candidate, result in zip(candidates, results):
			# A model is globally usable when at least one enabled credential can
			# access it. Never let a failed secondary credential invalidate a
			# model that is still verified through another key.
			if result.get("status") == "success":
				mark_model_verification(provider, candidate, True, latency_ms=result.get("latency_ms"))
		model = choose_preferred_model(provider, verified_models, preferred) or verified_models[0]
		latency_ms = next((result.get("latency_ms") for result in results if result.get("status") == "success"), None)
		row = _find_named_credential(settings, credential_name)
		if not row:
			row = settings.append("provider_credentials", {})
		row.update({
			"credential_name": credential_name,
			"provider": provider,
			"enabled": 1,
			"priority": max(1, min(cint(priority or 10), 999)),
			"default_model": model,
			"available_models": ", ".join(verified_models),
			"base_url": base_url,
			"organization_id": str(organization_id or "").strip() or None,
			"project_id": str(project_id or "").strip() or None,
			"verification_status": "Active - verified",
			"last_verified_on": now_datetime(),
			"last_latency_ms": latency_ms,
			"last_error": None,
		})
		settings.save(ignore_permissions=True)
		set_encrypted_password("LPO AI Provider Credential", row.name, clean_key, "api_key")
		if not settings.default_credential:
			frappe.db.set_value("LPO AI Settings", "LPO AI Settings", "default_credential", credential_name, update_modified=False)
		return {
			"status": "success",
			"credential_name": credential_name,
			"provider": provider,
			"model": model,
			"models": verified_models,
			"latency_ms": latency_ms,
			"message": _("Named credential encrypted and live-verified successfully."),
		}
	except AIProviderError as exc:
		_log_settings_error(provider, exc)
		return _provider_error_result(exc, prefix=_("Credential was not saved"))


@frappe.whitelist()
def test_provider_credential(credential_name: str) -> dict:
	_require_ai_settings_admin()
	settings = _get_settings()
	row = _require_named_credential(settings, credential_name)
	key = _get_named_credential_key(row)
	if not key:
		return {"status": "error", "credential_name": row.credential_name, "provider": row.provider, "error_type": "MISSING_KEY", "message": _("Encrypted key is missing.")}
	credential_settings = _credential_request_settings(settings, row=row)
	model = row.default_model or next(iter(_credential_models(row)), None)
	if not model:
		return {"status": "error", "credential_name": row.credential_name, "provider": row.provider, "error_type": "NO_VERIFIED_MODEL", "message": _("No verified model is assigned to this credential.")}
	try:
		result = verify_provider_model(
			row.provider,
			model,
			key,
			credential_settings,
			update_registry=False,
		)
		if result.get("status") == "success":
			mark_model_verification(row.provider, model, True, latency_ms=result.get("latency_ms"))
		values = {
			"last_verified_on": now_datetime(),
			"last_latency_ms": result.get("latency_ms"),
			"last_error": None if result.get("status") == "success" else str(result.get("message") or "")[:500],
			"verification_status": "Active - verified" if result.get("status") == "success" else "Failed",
			"enabled": 1 if result.get("status") == "success" else 0,
		}
		frappe.db.set_value("LPO AI Provider Credential", row.name, values, update_modified=False)
		return {**result, "credential_name": row.credential_name, "provider": row.provider, "model": model}
	except AIProviderError as exc:
		frappe.db.set_value("LPO AI Provider Credential", row.name, {
			"enabled": 0,
			"verification_status": "Failed",
			"last_verified_on": now_datetime(),
			"last_error": exc.safe_message[:500],
		}, update_modified=False)
		return {**_provider_error_result(exc), "credential_name": row.credential_name}


@frappe.whitelist()
def set_provider_credential_enabled(credential_name: str, enabled: int = 1) -> dict:
	_require_ai_settings_admin()
	settings = _get_settings()
	row = _require_named_credential(settings, credential_name)
	if cint(enabled) and "verified" not in str(row.verification_status or "").lower():
		frappe.throw(_("Run a successful live test before enabling this credential."), frappe.ValidationError)
	frappe.db.set_value("LPO AI Provider Credential", row.name, "enabled", cint(enabled), update_modified=False)
	return {"status": "success", "credential_name": row.credential_name, "enabled": bool(cint(enabled))}


@frappe.whitelist()
def remove_provider_credential(credential_name: str) -> dict:
	_require_ai_settings_admin()
	settings = _get_settings()
	row = _require_named_credential(settings, credential_name)
	row_name = row.name
	settings.remove(row)
	for fieldname in ("default_credential", "job_chat_credential", "document_analysis_credential", "qa_review_credential", "intake_credential"):
		if settings.get(fieldname) == credential_name:
			settings.set(fieldname, None)
	settings.save(ignore_permissions=True)
	frappe.db.delete("__Auth", {"doctype": "LPO AI Provider Credential", "name": row_name})
	return {"status": "success", "credential_name": credential_name, "message": _("Credential and encrypted key removed.")}


@frappe.whitelist()
def test_ai_provider_connection(provider: str, api_key: str | None = None, model: str | None = None) -> dict:
	_require_ai_settings_admin()
	provider = normalize_provider(provider)
	settings = _get_settings()
	key = _get_provider_key(settings, provider, api_key)
	if not key:
		return _missing_key_result(provider, settings)

	fields = PROVIDER_FIELDS[provider]
	try:
		if model:
			target_model = str(model).replace("models/", "").strip()
			if not is_text_model_candidate(provider, target_model):
				raise AIProviderError(provider, _("Selected model is not compatible with text generation."), "MODEL_INCOMPATIBLE", model=target_model)
		else:
			verified = [row["model_id"] for row in get_verified_models(provider)]
			current = settings.get(fields["default_model"]) if settings else None
			target_model = choose_preferred_model(provider, verified, current)
			if not target_model:
				discovered = discover_provider_models(provider, key, settings)
				sync_model_registry(provider, discovered)
				target_model = choose_preferred_model(provider, [row["model_id"] for row in discovered], current)
		if not target_model:
			raise AIProviderError(provider, _("No compatible text model is available."), "NO_COMPATIBLE_MODEL")

		result = verify_provider_model(provider, target_model, key, settings)
		if result.get("status") == "success":
			verified = [row["model_id"] for row in get_verified_models(provider)]
			_update_provider_state(settings, provider, success=True, model=target_model, models=verified, latency_ms=result.get("latency_ms"))
			result["message"] = _("{0} connected on {1} via {2} ({3} ms).").format(
				provider, target_model, DEFAULT_ENDPOINT_TYPES[provider], result.get("latency_ms")
			)
		else:
			_update_provider_state(
				settings,
				provider,
				success=False,
				error=result.get("message"),
				latency_ms=result.get("latency_ms"),
				disable_on_failure=result.get("error_type") in {"AUTHENTICATION", "MISSING_KEY"},
			)
		return result
	except AIProviderError as exc:
		_update_provider_state(settings, provider, success=False, error=exc.safe_message, disable_on_failure=exc.category in {"AUTHENTICATION", "MISSING_KEY"})
		_log_settings_error(provider, exc)
		return _provider_error_result(exc)


@frappe.whitelist()
def get_ai_provider_config() -> dict:
	_require_internal_ai_user()
	settings = _get_settings()
	credentials = [_credential_public_config(row) for row in _sorted_named_credentials(settings)]
	providers = {}
	for provider in SUPPORTED_PROVIDERS:
		fields = PROVIDER_FIELDS[provider]
		provider_credentials = [row for row in credentials if row["provider"] == provider and row["enabled"]]
		has_key = bool(provider_credentials or _get_provider_key(settings, provider))
		verified_rows = get_verified_models(provider) if has_key and cint(settings.get(fields["enabled"])) else []
		models = list(dict.fromkeys([
			*(_model for credential in provider_credentials for _model in credential["models"]),
			*(row["model_id"] for row in verified_rows),
		]))
		configured_default = settings.get(fields["default_model"])
		credential_default = next((row["default_model"] for row in provider_credentials if row["default_model"] in models), None)
		default_model = configured_default if configured_default in models else (credential_default or (models[0] if models else None))
		providers[provider] = {
			"enabled": bool(has_key and models),
			"has_key": has_key,
			"status": settings.get(fields["status"]),
			"default_model": default_model,
			"models": models,
			"model_details": verified_rows,
			"credentials": [row["credential_name"] for row in provider_credentials],
		}

	active = settings.default_provider if settings.default_provider in providers and providers[settings.default_provider]["enabled"] else None
	if not active:
		active = next((provider for provider in SUPPORTED_PROVIDERS if providers[provider]["enabled"]), "")
	return {
		"default_provider": active,
		"default_credential": settings.default_credential or "",
		"default_max_tokens": cint(settings.default_max_tokens or 2000),
		"providers": providers,
		"credentials": credentials,
		"routes": {
			"job_chat": settings.job_chat_credential or "",
			"document_analysis": settings.document_analysis_credential or "",
			"qa_review": settings.qa_review_credential or "",
			"intake": settings.intake_credential or "",
		},
	}


def resolve_provider_model(provider: str | None, model: str | None, use_case: str | None = None) -> tuple[str, str]:
	provider, model, _credential_name = resolve_ai_route(provider, model, use_case)
	return provider, model


def resolve_ai_route(
	provider: str | None,
	model: str | None,
	use_case: str | None = None,
	credential_name: str | None = None,
) -> tuple[str, str, str | None]:
	"""Resolve an enabled named credential first, then fall back to legacy provider keys."""
	settings = _get_settings()
	route_field = _route_fields(use_case)
	route_credential = settings.get(route_field[0]) if route_field else None
	route_provider = settings.get(route_field[1]) if route_field else None
	route_model = settings.get(route_field[2]) if route_field else None
	selected_credential = None
	requested_credential = str(credential_name or route_credential or "").strip()
	requested_provider = str(provider or route_provider or "").strip()
	if requested_credential:
		selected_credential = _require_named_credential(settings, requested_credential)
		if not cint(selected_credential.enabled):
			raise AIProviderError(selected_credential.provider, _("Selected API credential is disabled."), "CREDENTIAL_DISABLED")
		if requested_provider and normalize_provider(requested_provider) != selected_credential.provider:
			raise AIProviderError(selected_credential.provider, _("Selected credential does not belong to the requested provider."), "CREDENTIAL_PROVIDER_MISMATCH")
		provider = selected_credential.provider
	else:
		if not requested_provider and settings.default_credential:
			candidate = _find_named_credential(settings, settings.default_credential)
			if candidate and cint(candidate.enabled):
				selected_credential = candidate
				provider = candidate.provider
		if not selected_credential:
			provider = normalize_provider(requested_provider or settings.default_provider)
			selected_credential = _best_named_credential(settings, provider)

	provider = normalize_provider(provider or requested_provider or settings.default_provider)
	fields = PROVIDER_FIELDS[provider]
	credential_models = _credential_models(selected_credential) if selected_credential else []
	verified = credential_models or [row["model_id"] for row in get_verified_models(provider)]
	routed_model = route_model if route_provider == provider else None
	selected = model or routed_model or (selected_credential.default_model if selected_credential else None) or settings.get(fields["default_model"])
	if selected not in verified:
		selected = verified[0] if not model and verified else selected
	if not selected:
		raise AIProviderError(provider, _("No live-verified model is enabled for this provider."), "NO_VERIFIED_MODEL")
	if selected_credential and selected not in credential_models:
		raise AIProviderError(provider, _("Selected model was not verified for this API credential."), "CREDENTIAL_MODEL_MISMATCH", model=selected)
	return provider, require_verified_model(provider, selected), selected_credential.credential_name if selected_credential else None


def ensure_ai_provider_registry():
	"""Migrate legacy encrypted keys and seed only historically live-tested defaults as verified."""
	if not frappe.db.exists("DocType", "LPO AI Settings") or not frappe.db.exists("DocType", "LPO AI Model Registry"):
		return
	settings = _get_settings()
	for row in frappe.get_all("LPO AI Model Registry", fields=["name", "provider", "model_id"]):
		if not is_text_model_candidate(row.provider, row.model_id):
			frappe.db.set_value("LPO AI Model Registry", row.name, {
				"enabled": 0,
				"verified": 0,
				"verification_status": "Incompatible",
				"last_error_code": "MODEL_INCOMPATIBLE",
				"last_error_message": "Filtered because this is not a supported text-generation model.",
			}, update_modified=False)
	for provider, fields in PROVIDER_FIELDS.items():
		legacy = frappe.db.get_single_value("LPO AI Settings", fields["legacy_key"])
		if legacy:
			try:
				key = decrypt(legacy)
				if key:
					set_encrypted_password("LPO AI Settings", "LPO AI Settings", key, fields["key"])
					frappe.db.set_value("LPO AI Settings", "LPO AI Settings", fields["legacy_key"], None, update_modified=False)
			except Exception:
				pass

		available = [item.strip() for item in str(settings.get(fields["available_models"]) or "").split(",") if item.strip()]
		compatible = [item for item in available if is_text_model_candidate(provider, item)]
		default_model = settings.get(fields["default_model"])
		if default_model and is_text_model_candidate(provider, default_model) and default_model not in compatible:
			compatible.insert(0, default_model)
		sync_model_registry(provider, [
			{"model_id": item, "display_name": item, "endpoint_type": DEFAULT_ENDPOINT_TYPES[provider], "supports_text": 1, "supports_streaming": 1}
			for item in compatible
		])
		status = str(settings.get(fields["status"]) or "").lower()
		if default_model and ("active" in status or "verified" in status):
			mark_model_verification(provider, default_model, True)
		verified = [row["model_id"] for row in get_verified_models(provider)]
		if verified:
			frappe.db.set_value("LPO AI Settings", "LPO AI Settings", fields["available_models"], ", ".join(verified), update_modified=False)
	_migrate_legacy_credentials(_get_settings())


def _get_provider_key(
	settings: Document | None,
	provider: str,
	explicit_key: str | None = None,
	credential_name: str | None = None,
) -> str | None:
	provider = normalize_provider(provider)
	if explicit_key and not _is_dummy_password(explicit_key):
		return _validate_key_input(explicit_key)
	if settings is not None:
		credential = _find_named_credential(settings, credential_name) if credential_name else _best_named_credential(settings, provider)
		if credential:
			if credential.provider != provider:
				raise AIProviderError(provider, _("Selected API credential belongs to a different provider."), "CREDENTIAL_PROVIDER_MISMATCH")
			key = _get_named_credential_key(credential)
			if key:
				return key
	return _get_legacy_provider_key(settings, provider)


def _get_legacy_provider_key(settings: Document | None, provider: str) -> str | None:
	provider = normalize_provider(provider)
	fields = PROVIDER_FIELDS[provider]
	if settings is not None:
		try:
			key = get_decrypted_password("LPO AI Settings", "LPO AI Settings", fields["key"], raise_exception=False)
			if key and not _is_dummy_password(key):
				return str(key).strip()
		except Exception:
			pass
		try:
			legacy = frappe.db.get_single_value("LPO AI Settings", fields["legacy_key"])
			if legacy:
				key = decrypt(legacy)
				if key and not _is_dummy_password(key):
					return str(key).strip()
		except Exception:
			pass
	config = frappe.conf.get("lexocrates_ai_providers", {})
	if isinstance(config, dict) and isinstance(config.get(provider), dict):
		key = config[provider].get("api_key")
		if key and not _is_dummy_password(key):
			return str(key).strip()
	for env_name in ENVIRONMENT_KEYS[provider]:
		key = os.getenv(env_name)
		if key and not _is_dummy_password(key):
			return str(key).strip()
	return None


def _validate_credential_name(value: str) -> str:
	value = " ".join(str(value or "").strip().split())
	if not value or len(value) > 80:
		frappe.throw(_("Credential Name is required and cannot exceed 80 characters."), frappe.ValidationError)
	return value


def _find_named_credential(settings: Document | None, credential_name: str | None):
	needle = str(credential_name or "").strip().casefold()
	if not settings or not needle:
		return None
	return next((row for row in settings.get("provider_credentials") or [] if str(row.credential_name or "").casefold() == needle), None)


def _require_named_credential(settings: Document, credential_name: str):
	row = _find_named_credential(settings, credential_name)
	if not row:
		frappe.throw(_("API credential '{0}' was not found in LPO AI Settings.").format(credential_name), frappe.DoesNotExistError)
	return row


def _sorted_named_credentials(settings: Document | None, provider: str | None = None):
	rows = list(settings.get("provider_credentials") or []) if settings else []
	if provider:
		provider = normalize_provider(provider)
		rows = [row for row in rows if row.provider == provider]
	return sorted(rows, key=lambda row: (0 if cint(row.enabled) else 1, cint(row.priority or 10), str(row.credential_name or "").casefold()))


def _best_named_credential(settings: Document | None, provider: str):
	return next((row for row in _sorted_named_credentials(settings, provider) if cint(row.enabled) and "verified" in str(row.verification_status or "").lower()), None)


def _credential_models(row) -> list[str]:
	if not row:
		return []
	return list(dict.fromkeys(item.strip() for item in str(row.available_models or "").split(",") if item.strip()))


def _get_named_credential_key(row) -> str | None:
	if not row or not row.name:
		return None
	try:
		key = get_decrypted_password("LPO AI Provider Credential", row.name, "api_key", raise_exception=False)
		return str(key).strip() if key and not _is_dummy_password(key) else None
	except Exception:
		return None


def _credential_public_config(row) -> dict:
	return {
		"credential_name": row.credential_name,
		"provider": row.provider,
		"enabled": bool(cint(row.enabled)),
		"priority": cint(row.priority or 10),
		"status": row.verification_status,
		"default_model": row.default_model,
		"models": _credential_models(row),
		"last_verified_on": row.last_verified_on,
		"last_latency_ms": row.last_latency_ms,
		"has_key": bool(_get_named_credential_key(row)),
	}


def _credential_request_settings(
	settings: Document,
	*,
	row=None,
	provider: str | None = None,
	base_url: str | None = None,
	organization_id: str | None = None,
	project_id: str | None = None,
):
	provider = normalize_provider(provider or row.provider)
	config = frappe._dict(settings.as_dict())
	base_url = str(base_url if row is None else row.base_url or "").strip()
	organization_id = organization_id if row is None else row.organization_id
	project_id = project_id if row is None else row.project_id
	if provider == "OpenAI":
		if base_url:
			config.openai_base_url = base_url
		config.openai_organization_id = str(organization_id or "").strip() or None
		config.openai_project_id = str(project_id or "").strip() or None
	elif provider == "Google Gemini" and base_url:
		config.gemini_base_url = base_url
	elif provider == "Anthropic" and base_url:
		config.anthropic_base_url = base_url
	return config


def _validate_provider_base_url(provider: str, base_url: str | None):
	value = str(base_url or "").strip()
	if not value:
		return
	provider = normalize_provider(provider)
	official_hosts = {
		"OpenAI": "api.openai.com",
		"Google Gemini": "generativelanguage.googleapis.com",
		"Anthropic": "api.anthropic.com",
	}
	parsed = urlparse(value)
	if parsed.scheme != "https" or not parsed.netloc:
		frappe.throw(_("Credential Base URL must be a valid HTTPS API URL."), frappe.ValidationError)
	if not cint(frappe.conf.get("allow_custom_ai_endpoints")) and parsed.hostname != official_hosts[provider]:
		frappe.throw(_("Custom AI endpoints are disabled; use the official {0} host.").format(provider), frappe.ValidationError)


def _migrate_legacy_credentials(settings: Document):
	"""Expose existing primary keys as named credentials without removing the legacy fallback."""
	changed = False
	pending_keys = []
	for provider, fields in PROVIDER_FIELDS.items():
		if _sorted_named_credentials(settings, provider):
			continue
		key = _get_legacy_provider_key(settings, provider)
		if not key:
			continue
		models = [row["model_id"] for row in get_verified_models(provider)]
		default_model = settings.get(fields["default_model"])
		if default_model and default_model not in models:
			models.insert(0, default_model)
		status = str(settings.get(fields["status"]) or "")
		verified = bool(cint(settings.get(fields["enabled"])) and (models or "verified" in status.lower()))
		row = settings.append("provider_credentials", {
			"credential_name": f"{provider} Primary",
			"provider": provider,
			"enabled": cint(verified),
			"priority": 10,
			"default_model": default_model,
			"available_models": ", ".join(models),
			"verification_status": "Active - verified" if verified else (status or "Verification required"),
			"last_verified_on": settings.get(fields["last_verified_on"]),
			"last_latency_ms": settings.get(fields["last_latency_ms"]),
			"last_error": settings.get(fields["last_error"]),
		})
		pending_keys.append((row, key))
		changed = True
	if not changed:
		return
	settings.save(ignore_permissions=True)
	for row, key in pending_keys:
		set_encrypted_password("LPO AI Provider Credential", row.name, key, "api_key")
	if not settings.default_credential:
		first = next((row for row in _sorted_named_credentials(settings) if cint(row.enabled)), None)
		if first:
			frappe.db.set_value("LPO AI Settings", "LPO AI Settings", "default_credential", first.credential_name, update_modified=False)


def _update_provider_state(settings, provider, *, success, model=None, models=None, latency_ms=None, error=None, disable_on_failure=False):
	if not settings:
		return
	fields = PROVIDER_FIELDS[provider]
	values = {
		fields["status"]: f"Active - verified ({latency_ms} ms)" if success and latency_ms is not None else ("Active - verified" if success else "Failed"),
		fields["enabled"]: 1 if success else (0 if disable_on_failure else cint(settings.get(fields["enabled"]))),
		fields["last_verified_on"]: now_datetime(),
		fields["last_error"]: None if success else str(error or "Unknown provider error")[:500],
	}
	if latency_ms is not None:
		values[fields["last_latency_ms"]] = latency_ms
	if model:
		values[fields["default_model"]] = model
	if models is not None:
		values[fields["available_models"]] = ", ".join(models)
	frappe.db.set_value("LPO AI Settings", "LPO AI Settings", values, update_modified=False)


def _missing_key_result(provider, settings=None):
	if settings:
		fields = PROVIDER_FIELDS[provider]
		frappe.db.set_value("LPO AI Settings", "LPO AI Settings", {fields["status"]: "Key missing", fields["enabled"]: 0}, update_modified=False)
	return {"status": "error", "provider": provider, "error_type": "MISSING_KEY", "message": _("No API key is configured for {0}.").format(provider)}


def _provider_error_result(exc: AIProviderError, prefix: str | None = None):
	message = exc.safe_message
	if prefix:
		message = f"{prefix}: {message}"
	return {
		"status": "error",
		"provider": exc.provider,
		"model": exc.model,
		"error_type": exc.category,
		"http_status": exc.status_code,
		"retryable": exc.retryable,
		"message": message,
	}


def _validate_key_input(api_key):
	value = str(api_key or "").strip()
	if len(value) < 6 or "\n" in value or _is_dummy_password(value):
		frappe.throw(_("Please enter a valid live API key."), frappe.ValidationError)
	return value


def _is_dummy_password(value):
	text = str(value or "")
	return not text or text.startswith(("*", "AQ.")) or (text and set(text) == {"*"})


def _route_fields(use_case):
	value = str(use_case or "").lower()
	if "job" in value and ("chat" in value or "copilot" in value):
		return "job_chat_credential", "job_chat_provider", "job_chat_model"
	if "document" in value:
		return "document_analysis_credential", "document_analysis_provider", "document_analysis_model"
	if "qa" in value or "review" in value:
		return "qa_review_credential", "qa_review_provider", "qa_review_model"
	if "intake" in value:
		return "intake_credential", "intake_provider", "intake_model"
	return None


def _get_settings():
	return frappe.get_single("LPO AI Settings")


def _log_settings_error(provider, exc):
	frappe.log_error(
		title="LPO AI Provider Diagnostic",
		message=f"Provider: {provider}\n{type(exc).__name__}: {str(exc)[:1000]}",
		defer_insert=True,
	)
