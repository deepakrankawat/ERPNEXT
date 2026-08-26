from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import frappe
import requests
from frappe import _
from frappe.utils import cint, now_datetime


MODEL_REGISTRY_DOCTYPE = "LPO AI Model Registry"
SUPPORTED_PROVIDERS = ("OpenAI", "Google Gemini", "Anthropic")
DEFAULT_ENDPOINT_TYPES = {
	"OpenAI": "Responses API",
	"Google Gemini": "Gemini Generate Content",
	"Anthropic": "Anthropic Messages",
}
PROVIDER_PREFIXES = {
	"OpenAI": ("gpt-", "o1", "o3", "o4"),
	"Google Gemini": ("gemini-",),
	"Anthropic": ("claude-",),
}
REJECTED_MODEL_MARKERS = (
	"audio",
	"codex",
	"computer-use",
	"embedding",
	"image",
	"imagen",
	"instruct",
	"moderation",
	"realtime",
	"robotics",
	"search",
	"sora",
	"speech",
	"transcribe",
	"translation",
	"tts",
	"veo",
	"whisper",
)
OPENAI_MODEL_PREFERENCE = (
	"gpt-5.6-luna",
	"gpt-5.6-terra",
	"gpt-5.6",
	"gpt-5.6-sol",
	"gpt-4o-mini",
	"gpt-4o",
	"gpt-4.1-mini",
	"gpt-4.1",
)
GEMINI_MODEL_PREFERENCE = (
	"gemini-3.7-flash",
	"gemini-3.6-flash",
	"gemini-3.5-flash-lite",
	"gemini-3.5-flash",
	"gemini-2.5-flash",
	"gemini-1.5-flash",
	"gemini-2.5-pro",
)
ANTHROPIC_MODEL_PREFERENCE = (
	"claude-sonnet-4-6",
	"claude-opus-4-6",
	"claude-haiku-4-5",
	"claude-sonnet-4-5",
	"claude-3-7-sonnet-latest",
	"claude-3-5-sonnet-latest",
	"claude-3-5-sonnet-20241022",
	"claude-3-5-haiku-latest",
)


@dataclass
class AIProviderError(RuntimeError):
	provider: str
	message: str
	category: str = "PROVIDER_ERROR"
	status_code: int | None = None
	retryable: bool = False
	model: str | None = None
	request_id: str | None = None

	def __post_init__(self):
		RuntimeError.__init__(self, self.safe_message)

	@property
	def safe_message(self) -> str:
		status = f" (HTTP {self.status_code})" if self.status_code else ""
		return f"{self.provider}{status} [{self.category}]: {_redact_secret(self.message)[:500]}"


def normalize_provider(provider: str | None) -> str:
	value = (provider or "").strip()
	aliases = {
		"Gemini": "Google Gemini",
		"Google": "Google Gemini",
		"Claude": "Anthropic",
		"ChatGPT": "OpenAI",
		"GPT": "OpenAI",
	}
	value = aliases.get(value, value)
	if value not in SUPPORTED_PROVIDERS:
		raise AIProviderError(value or "Unknown", _("Unsupported AI provider."), "UNSUPPORTED_PROVIDER")
	return value


def is_text_model_candidate(provider: str, model_id: str, metadata: dict | None = None) -> bool:
	provider = normalize_provider(provider)
	model = str(model_id or "").replace("models/", "").strip().lower()
	if not model or not model.startswith(PROVIDER_PREFIXES[provider]):
		return False
	if any(marker in model for marker in REJECTED_MODEL_MARKERS):
		return False
	if provider == "OpenAI" and model.endswith("-instruct"):
		return False
	if provider == "Google Gemini":
		methods = (metadata or {}).get("supportedGenerationMethods") or (metadata or {}).get("supportedActions") or []
		if methods and "generateContent" not in methods:
			return False
	return True


def choose_preferred_model(provider: str, models: list[str], current: str | None = None) -> str | None:
	provider = normalize_provider(provider)
	clean_models = list(dict.fromkeys(str(m).replace("models/", "").strip() for m in models if m))
	if current and current in clean_models and is_text_model_candidate(provider, current):
		return current
	preferences = {
		"OpenAI": OPENAI_MODEL_PREFERENCE,
		"Google Gemini": GEMINI_MODEL_PREFERENCE,
		"Anthropic": ANTHROPIC_MODEL_PREFERENCE,
	}[provider]
	for preferred in preferences:
		if preferred in clean_models:
			return preferred
	return clean_models[0] if clean_models else None


def discover_provider_models(provider: str, api_key: str, settings=None, timeout: int | None = None) -> list[dict]:
	provider = normalize_provider(provider)
	api_key = _validate_api_key(api_key, provider)
	timeout = _timeout(settings, timeout)

	if provider == "OpenAI":
		url = f"{_base_url(provider, settings)}/models"
		response = requests.get(url, headers=_openai_headers(api_key, settings), timeout=timeout)
		_raise_for_status(provider, response)
		rows = response.json().get("data") or []
		models = [
			_model_metadata(provider, row.get("id"), DEFAULT_ENDPOINT_TYPES[provider])
			for row in rows
			if row.get("id") and is_text_model_candidate(provider, row["id"], row)
		]
	elif provider == "Anthropic":
		url = f"{_base_url(provider, settings)}/models"
		response = requests.get(url, headers=_anthropic_headers(api_key), params={"limit": 1000}, timeout=timeout)
		_raise_for_status(provider, response)
		rows = response.json().get("data") or []
		models = [
			_model_metadata(provider, row.get("id"), DEFAULT_ENDPOINT_TYPES[provider], row.get("display_name"))
			for row in rows
			if row.get("id") and is_text_model_candidate(provider, row["id"], row)
		]
	else:
		url = f"{_base_url(provider, settings)}/models"
		response = requests.get(url, headers={"x-goog-api-key": api_key}, params={"pageSize": 1000}, timeout=timeout)
		_raise_for_status(provider, response)
		rows = response.json().get("models") or []
		models = [
			_model_metadata(provider, row.get("name"), DEFAULT_ENDPOINT_TYPES[provider], row.get("displayName"), row)
			for row in rows
			if row.get("name") and is_text_model_candidate(provider, row["name"], row)
		]

	models = [row for row in models if row.get("model_id")]
	models.sort(key=lambda row: _model_sort_key(provider, row["model_id"]))
	return models


def call_provider(
	*,
	provider: str,
	model: str,
	prompt: str,
	api_key: str,
	max_tokens: int = 200,
	settings=None,
	correlation_id: str | None = None,
	endpoint_type: str | None = None,
	timeout: int | None = None,
) -> dict:
	provider = normalize_provider(provider)
	model = str(model or "").replace("models/", "").strip()
	if not is_text_model_candidate(provider, model):
		raise AIProviderError(provider, _("Model is not compatible with text chat."), "MODEL_INCOMPATIBLE", model=model)
	api_key = _validate_api_key(api_key, provider)
	endpoint_type = endpoint_type or get_registry_endpoint(provider, model) or DEFAULT_ENDPOINT_TYPES[provider]
	timeout = _timeout(settings, timeout)
	max_tokens = max(1, min(cint(max_tokens or 200), 32000))

	custom = _custom_gateway(provider)
	if custom:
		return _call_custom_gateway(custom, provider, model, prompt, api_key, max_tokens, correlation_id, timeout)
	if provider == "OpenAI":
		if endpoint_type == "Chat Completions":
			return _call_openai_chat(model, prompt, api_key, max_tokens, settings, timeout)
		return _call_openai_responses(model, prompt, api_key, max_tokens, settings, timeout)
	if provider == "Anthropic":
		return _call_anthropic(model, prompt, api_key, max_tokens, settings, timeout)
	return _call_gemini(model, prompt, api_key, max_tokens, settings, timeout)


def call_provider_with_retries(**kwargs) -> tuple[dict, int]:
	retry_limit = max(0, min(cint(kwargs.pop("retry_limit", 0)), 5))
	last_error: Exception | None = None
	for attempt in range(retry_limit + 1):
		try:
			return call_provider(**kwargs), attempt
		except AIProviderError as exc:
			exc.attempts = attempt
			last_error = exc
			if not exc.retryable or attempt >= retry_limit:
				raise
		except (requests.Timeout, requests.ConnectionError) as exc:
			last_error = AIProviderError(
				kwargs.get("provider", "AI Provider"),
				str(exc) or _("Network connection failed."),
				"NETWORK",
				retryable=True,
				model=kwargs.get("model"),
			)
			last_error.attempts = attempt
			if attempt >= retry_limit:
				raise last_error from exc
		if attempt < retry_limit:
			time.sleep(min(0.5 * (2**attempt) + random.uniform(0, 0.2), 4.0))
	if last_error:
		raise last_error
	raise AIProviderError(kwargs.get("provider", "AI Provider"), _("Unknown provider failure."))


def verify_provider_model(
	provider: str,
	model: str,
	api_key: str,
	settings=None,
	*,
	update_registry: bool = True,
) -> dict:
	started = time.monotonic()
	try:
		result = call_provider(
			provider=provider,
			model=model,
			prompt="Reply with exactly: CONNECTED",
			api_key=api_key,
			max_tokens=64,
			settings=settings,
			timeout=20,
		)
		latency = round((time.monotonic() - started) * 1000, 1)
		if update_registry:
			mark_model_verification(provider, model, True, latency_ms=latency)
		return {"status": "success", "provider": provider, "model": model, "latency_ms": latency, "sample_response": result.get("output_text", "")[:100]}
	except AIProviderError as exc:
		latency = round((time.monotonic() - started) * 1000, 1)
		if update_registry:
			mark_model_verification(
				provider,
				model,
				False,
				latency_ms=latency,
				status_code=exc.status_code,
				error_code=exc.category,
				error_message=exc.safe_message,
			)
		return {
			"status": "error",
			"provider": provider,
			"model": model,
			"latency_ms": latency,
			"error_type": exc.category,
			"http_status": exc.status_code,
			"retryable": exc.retryable,
			"message": exc.safe_message,
		}


def sync_model_registry(provider: str, models: list[dict]) -> None:
	if not _registry_available():
		return
	provider = normalize_provider(provider)
	now = now_datetime()
	for row in models:
		model_id = row.get("model_id")
		if not model_id:
			continue
		name = frappe.db.get_value(MODEL_REGISTRY_DOCTYPE, {"provider": provider, "model_id": model_id}, "name")
		values = {
			"display_name": row.get("display_name") or model_id,
			"endpoint_type": row.get("endpoint_type") or DEFAULT_ENDPOINT_TYPES[provider],
			"supports_text": 1,
			"supports_vision": cint(row.get("supports_vision")),
			"supports_tools": cint(row.get("supports_tools")),
			"supports_structured_output": cint(row.get("supports_structured_output")),
			"supports_streaming": cint(row.get("supports_streaming", 1)),
			"discovered_on": now,
		}
		if name:
			frappe.db.set_value(MODEL_REGISTRY_DOCTYPE, name, values, update_modified=False)
		else:
			frappe.get_doc({
				"doctype": MODEL_REGISTRY_DOCTYPE,
				"provider": provider,
				"model_id": model_id,
				"enabled": 1,
				"verified": 0,
				"verification_status": "Discovered",
				**values,
			}).insert(ignore_permissions=True)


def mark_model_verification(
	provider: str,
	model: str,
	success: bool,
	*,
	latency_ms: float | None = None,
	status_code: int | None = None,
	error_code: str | None = None,
	error_message: str | None = None,
) -> None:
	if not _registry_available():
		return
	provider = normalize_provider(provider)
	model = str(model).replace("models/", "").strip()
	name = frappe.db.get_value(MODEL_REGISTRY_DOCTYPE, {"provider": provider, "model_id": model}, "name")
	if not name:
		sync_model_registry(provider, [_model_metadata(provider, model, DEFAULT_ENDPOINT_TYPES[provider])])
		name = frappe.db.get_value(MODEL_REGISTRY_DOCTYPE, {"provider": provider, "model_id": model}, "name")
	if not name:
		return
	values = {
		"verified": cint(success),
		"verification_status": "Verified" if success else ("Incompatible" if error_code in {"MODEL_INCOMPATIBLE", "MODEL_NOT_FOUND"} else "Failed"),
		"last_verified_on": now_datetime(),
		"last_error_code": None if success else error_code,
		"last_error_message": None if success else _redact_secret(error_message or "")[:500],
	}
	if latency_ms is not None:
		values["last_latency_ms"] = latency_ms
	if status_code is not None:
		values["last_http_status"] = status_code
	frappe.db.set_value(MODEL_REGISTRY_DOCTYPE, name, values, update_modified=False)


def get_verified_models(provider: str) -> list[dict]:
	if not _registry_available():
		return []
	provider = normalize_provider(provider)
	return frappe.get_all(
		MODEL_REGISTRY_DOCTYPE,
		filters={"provider": provider, "enabled": 1, "verified": 1, "verification_status": "Verified"},
		fields=["model_id", "display_name", "endpoint_type", "supports_vision", "supports_tools", "supports_structured_output", "supports_streaming", "last_latency_ms"],
		order_by="model_id asc",
		limit_page_length=200,
	)


def get_registry_endpoint(provider: str, model: str) -> str | None:
	if not _registry_available():
		return None
	return frappe.db.get_value(
		MODEL_REGISTRY_DOCTYPE,
		{"provider": normalize_provider(provider), "model_id": str(model).replace("models/", ""), "enabled": 1},
		"endpoint_type",
	)


def require_verified_model(provider: str, model: str) -> str:
	provider = normalize_provider(provider)
	model = str(model or "").replace("models/", "").strip()
	if not is_text_model_candidate(provider, model):
		raise AIProviderError(provider, _("Selected model is not a text/chat model."), "MODEL_INCOMPATIBLE", model=model)
	if _registry_available() and not frappe.db.exists(
		MODEL_REGISTRY_DOCTYPE,
		{"provider": provider, "model_id": model, "enabled": 1, "verified": 1, "verification_status": "Verified"},
	):
		raise AIProviderError(
			provider,
			_("Model '{0}' has not passed the live compatibility test. Verify it in LPO AI Settings.").format(model),
			"MODEL_NOT_VERIFIED",
			model=model,
		)
	return model


def _call_openai_responses(model, prompt, api_key, max_tokens, settings, timeout):
	response = requests.post(
		f"{_base_url('OpenAI', settings)}/responses",
		headers=_openai_headers(api_key, settings),
		json={
			"model": model,
			"instructions": "You are a professional legal operations assistant at Lexocrates.",
			"input": prompt,
			"max_output_tokens": max_tokens,
			"store": False,
		},
		timeout=timeout,
	)
	_raise_for_status("OpenAI", response, model)
	data = response.json()
	output = str(data.get("output_text") or "").strip()
	if not output:
		parts = []
		for item in data.get("output") or []:
			if item.get("type") != "message":
				continue
			for content in item.get("content") or []:
				if content.get("type") == "output_text" and content.get("text"):
					parts.append(content["text"])
		output = "\n".join(parts).strip()
	if not output:
		raise AIProviderError("OpenAI", _("The model returned no text output."), "EMPTY_RESPONSE", model=model)
	usage = data.get("usage") or {}
	return _normalized_result(output, usage, data.get("id") or _request_id(response))


def _call_openai_chat(model, prompt, api_key, max_tokens, settings, timeout):
	response = requests.post(
		f"{_base_url('OpenAI', settings)}/chat/completions",
		headers=_openai_headers(api_key, settings),
		json={
			"model": model,
			"messages": [
				{"role": "system", "content": "You are a professional legal operations assistant at Lexocrates."},
				{"role": "user", "content": prompt},
			],
			"max_tokens": max_tokens,
		},
		timeout=timeout,
	)
	_raise_for_status("OpenAI", response, model)
	data = response.json()
	choices = data.get("choices") or []
	output = choices[0].get("message", {}).get("content", "") if choices else ""
	if not output:
		raise AIProviderError("OpenAI", _("The model returned no text output."), "EMPTY_RESPONSE", model=model)
	return _normalized_result(output, data.get("usage") or {}, data.get("id") or _request_id(response))


def _call_anthropic(model, prompt, api_key, max_tokens, settings, timeout):
	response = requests.post(
		f"{_base_url('Anthropic', settings)}/messages",
		headers=_anthropic_headers(api_key),
		json={
			"model": model,
			"system": "You are a professional legal operations assistant at Lexocrates.",
			"messages": [{"role": "user", "content": prompt}],
			"max_tokens": max_tokens,
		},
		timeout=timeout,
	)
	_raise_for_status("Anthropic", response, model)
	data = response.json()
	output = "".join(part.get("text", "") for part in data.get("content") or [] if part.get("type") == "text").strip()
	if not output:
		raise AIProviderError("Anthropic", _("Claude returned no text output."), "EMPTY_RESPONSE", model=model)
	usage = data.get("usage") or {}
	usage["total_tokens"] = cint(usage.get("input_tokens")) + cint(usage.get("output_tokens"))
	return _normalized_result(output, usage, data.get("id") or _request_id(response))


def _call_gemini(model, prompt, api_key, max_tokens, settings, timeout):
	encoded_model = quote(model, safe="-._")
	response = requests.post(
		f"{_base_url('Google Gemini', settings)}/models/{encoded_model}:generateContent",
		headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
		json={
			"systemInstruction": {"parts": [{"text": "You are a professional legal operations assistant at Lexocrates."}]},
			"contents": [{"role": "user", "parts": [{"text": prompt}]}],
			"generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2},
		},
		timeout=timeout,
	)
	_raise_for_status("Google Gemini", response, model)
	data = response.json()
	candidates = data.get("candidates") or []
	parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
	output = "".join(part.get("text", "") for part in parts if part.get("text")).strip()
	if not output:
		feedback = data.get("promptFeedback") or {}
		raise AIProviderError("Google Gemini", _("Gemini returned no text output: {0}").format(feedback), "EMPTY_RESPONSE", model=model)
	usage = data.get("usageMetadata") or {}
	usage["total_tokens"] = cint(usage.get("totalTokenCount"))
	return _normalized_result(output, usage, _request_id(response))


def _call_custom_gateway(endpoint, provider, model, prompt, api_key, max_tokens, correlation_id, timeout):
	response = requests.post(
		endpoint,
		headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
		json={"provider": provider, "model": model, "prompt": prompt, "max_tokens": max_tokens, "correlation_id": correlation_id},
		timeout=timeout,
	)
	_raise_for_status(provider, response, model)
	data = response.json()
	output = data.get("output_text") or data.get("response")
	if not output:
		raise AIProviderError(provider, _("Custom gateway returned no text output."), "EMPTY_RESPONSE", model=model)
	return _normalized_result(output, data.get("usage") or {}, data.get("request_id") or _request_id(response))


def _raise_for_status(provider: str, response, model: str | None = None):
	if 200 <= int(response.status_code) < 300:
		return
	message = response.text or f"HTTP {response.status_code}"
	code = None
	try:
		error = response.json().get("error") or {}
		if isinstance(error, dict):
			message = error.get("message") or message
			code = error.get("code") or error.get("type")
		elif error:
			message = str(error)
	except Exception:
		pass
	status = int(response.status_code)
	lower = str(message).lower()
	if "not a chat model" in lower or ("not supported" in lower and "model" in lower):
		category = "MODEL_INCOMPATIBLE"
	elif status in {401, 403}:
		category = "AUTHENTICATION" if status == 401 or "api key" in lower else "PERMISSION"
	elif status == 404:
		category = "MODEL_NOT_FOUND" if "model" in lower else "NOT_FOUND"
	elif status == 429:
		category = "RATE_LIMIT"
	elif status == 400:
		category = "BAD_REQUEST"
	elif status in {408, 409, 425}:
		category = "TRANSIENT_REQUEST"
	elif status >= 500:
		category = "PROVIDER_UNAVAILABLE"
	else:
		category = str(code or "PROVIDER_ERROR").upper()
	raise AIProviderError(
		provider,
		str(message),
		category,
		status_code=status,
		retryable=status in {408, 409, 425, 429, 500, 502, 503, 504},
		model=model,
		request_id=_request_id(response),
	)


def _normalized_result(output: str, usage: dict, request_id: str | None) -> dict:
	total = cint(usage.get("total_tokens") or usage.get("totalTokenCount"))
	if not total:
		total = cint(usage.get("input_tokens")) + cint(usage.get("output_tokens"))
	return {"output_text": str(output).strip(), "usage": {**usage, "total_tokens": total, "cost": 0}, "request_id": request_id}


def _model_metadata(provider, model_id, endpoint_type, display_name=None, raw=None):
	model = str(model_id or "").replace("models/", "").strip()
	return {
		"model_id": model,
		"display_name": display_name or model,
		"endpoint_type": endpoint_type,
		"supports_text": 1,
		"supports_vision": cint("vision" in model or provider in {"OpenAI", "Google Gemini"}),
		"supports_tools": cint(provider in SUPPORTED_PROVIDERS),
		"supports_structured_output": cint(provider in SUPPORTED_PROVIDERS),
		"supports_streaming": 1,
	}


def _model_sort_key(provider: str, model: str):
	preferences = {
		"OpenAI": OPENAI_MODEL_PREFERENCE,
		"Google Gemini": GEMINI_MODEL_PREFERENCE,
		"Anthropic": ANTHROPIC_MODEL_PREFERENCE,
	}[provider]
	try:
		return (0, preferences.index(model))
	except ValueError:
		return (1, model)


def _base_url(provider: str, settings=None) -> str:
	defaults = {
		"OpenAI": "https://api.openai.com/v1",
		"Anthropic": "https://api.anthropic.com/v1",
		"Google Gemini": "https://generativelanguage.googleapis.com/v1beta",
	}
	fields = {
		"OpenAI": "openai_base_url",
		"Anthropic": "anthropic_base_url",
		"Google Gemini": "gemini_base_url",
	}
	value = settings.get(fields[provider]) if settings and hasattr(settings, "get") else None
	return str(value or defaults[provider]).rstrip("/")


def _timeout(settings=None, explicit=None) -> int:
	value = explicit or (settings.get("provider_timeout_seconds") if settings and hasattr(settings, "get") else None) or 45
	return max(5, min(cint(value), 120))


def _openai_headers(api_key, settings=None):
	headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
	if settings and settings.get("openai_organization_id"):
		headers["OpenAI-Organization"] = settings.openai_organization_id
	if settings and settings.get("openai_project_id"):
		headers["OpenAI-Project"] = settings.openai_project_id
	return headers


def _anthropic_headers(api_key):
	return {"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}


def _custom_gateway(provider):
	config = frappe.conf.get("lexocrates_ai_providers", {})
	if isinstance(config, dict) and isinstance(config.get(provider), dict):
		return config[provider].get("endpoint")
	return None


def _validate_api_key(api_key, provider):
	value = str(api_key or "").strip()
	if len(value) < 6 or "\n" in value or value.startswith(("*", "AQ.")):
		raise AIProviderError(provider, _("API key is missing or has an invalid format."), "MISSING_KEY")
	return value


def _request_id(response):
	return response.headers.get("x-request-id") or response.headers.get("request-id") if getattr(response, "headers", None) else None


def _registry_available():
	return bool(frappe.db.exists("DocType", MODEL_REGISTRY_DOCTYPE))


def _redact_secret(value: str) -> str:
	text = str(value or "")
	text = re.sub(r"\b(sk-(?:proj-|ant-)?[A-Za-z0-9_-]{8,})\b", "[REDACTED_API_KEY]", text)
	text = re.sub(r"\bAIza[A-Za-z0-9_-]{12,}\b", "[REDACTED_API_KEY]", text)
	text = re.sub(r"([?&](?:key|api_key)=)[^&\s]+", r"\1[REDACTED]", text, flags=re.IGNORECASE)
	return text
