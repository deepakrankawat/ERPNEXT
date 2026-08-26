from __future__ import annotations

from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from lex.ai_providers import (
	AIProviderError,
	call_provider,
	call_provider_with_retries,
	is_text_model_candidate,
	mark_model_verification,
	require_verified_model,
	sync_model_registry,
)


def response(status: int, payload: dict, text: str = ""):
	result = Mock()
	result.status_code = status
	result.json.return_value = payload
	result.text = text or str(payload)
	result.headers = {"x-request-id": "req-test-123"}
	return result


class TestAIProviderAdapters(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_text_model_filter_rejects_non_chat_openai_models(self):
		self.assertTrue(is_text_model_candidate("OpenAI", "gpt-5.6-terra"))
		self.assertTrue(is_text_model_candidate("OpenAI", "gpt-4o"))
		self.assertFalse(is_text_model_candidate("OpenAI", "chatgpt-image-latest"))
		self.assertFalse(is_text_model_candidate("OpenAI", "gpt-3.5-turbo-instruct"))
		self.assertFalse(is_text_model_candidate("OpenAI", "gpt-5-codex"))
		self.assertFalse(is_text_model_candidate("OpenAI", "gpt-realtime"))

	@patch("lex.ai_providers.requests.post")
	def test_openai_uses_responses_api_and_normalizes_output(self, mock_post):
		mock_post.return_value = response(200, {
			"id": "resp_123",
			"output": [{"type": "message", "content": [{"type": "output_text", "text": "CONNECTED"}]}],
			"usage": {"input_tokens": 4, "output_tokens": 1, "total_tokens": 5},
		})

		result = call_provider(
			provider="OpenAI",
			model="gpt-5.6-terra",
			prompt="ping",
			api_key="sk-test-openai-key",
			max_tokens=64,
		)

		url = mock_post.call_args.args[0]
		payload = mock_post.call_args.kwargs["json"]
		self.assertEqual(url, "https://api.openai.com/v1/responses")
		self.assertEqual(payload["input"], "ping")
		self.assertEqual(payload["max_output_tokens"], 64)
		self.assertFalse(payload["store"])
		self.assertNotIn("messages", payload)
		self.assertEqual(result["output_text"], "CONNECTED")
		self.assertEqual(result["usage"]["total_tokens"], 5)

	@patch("lex.ai_providers.time.sleep")
	@patch("lex.ai_providers.requests.post")
	def test_non_retryable_model_error_is_not_retried(self, mock_post, mock_sleep):
		mock_post.return_value = response(404, {"error": {"message": "This is not a chat model"}})
		with self.assertRaises(AIProviderError) as raised:
			call_provider_with_retries(
				provider="OpenAI",
				model="gpt-4o",
				prompt="ping",
				api_key="sk-test-openai-key",
				max_tokens=32,
				retry_limit=3,
			)
		self.assertEqual(raised.exception.category, "MODEL_INCOMPATIBLE")
		self.assertFalse(raised.exception.retryable)
		self.assertEqual(mock_post.call_count, 1)
		mock_sleep.assert_not_called()

	@patch("lex.ai_providers.time.sleep")
	@patch("lex.ai_providers.requests.post")
	def test_rate_limit_retries_then_succeeds(self, mock_post, mock_sleep):
		mock_post.side_effect = [
			response(429, {"error": {"message": "Rate limit exceeded"}}),
			response(200, {"id": "resp_2", "output_text": "CONNECTED", "usage": {"total_tokens": 2}}),
		]
		result, retries = call_provider_with_retries(
			provider="OpenAI",
			model="gpt-4o",
			prompt="ping",
			api_key="sk-test-openai-key",
			max_tokens=32,
			retry_limit=2,
		)
		self.assertEqual(result["output_text"], "CONNECTED")
		self.assertEqual(retries, 1)
		self.assertEqual(mock_post.call_count, 2)
		mock_sleep.assert_called_once()

	@patch("lex.ai_providers.requests.post")
	def test_gemini_uses_generate_content_and_header_auth(self, mock_post):
		mock_post.return_value = response(200, {
			"candidates": [{"content": {"parts": [{"text": "CONNECTED"}]}}],
			"usageMetadata": {"totalTokenCount": 7},
		})
		result = call_provider(
			provider="Google Gemini",
			model="gemini-3.7-flash",
			prompt="ping",
			api_key="AIza-test-gemini-key",
			max_tokens=64,
		)
		url = mock_post.call_args.args[0]
		headers = mock_post.call_args.kwargs["headers"]
		self.assertTrue(url.endswith("/models/gemini-3.7-flash:generateContent"))
		self.assertNotIn("?key=", url)
		self.assertEqual(headers["x-goog-api-key"], "AIza-test-gemini-key")
		self.assertEqual(result["usage"]["total_tokens"], 7)

	@patch("lex.ai_providers.requests.post")
	def test_anthropic_uses_messages_api_and_normalizes_usage(self, mock_post):
		mock_post.return_value = response(200, {
			"id": "msg_123",
			"content": [{"type": "text", "text": "CONNECTED"}],
			"usage": {"input_tokens": 3, "output_tokens": 1},
		})
		result = call_provider(
			provider="Anthropic",
			model="claude-sonnet-4-6",
			prompt="ping",
			api_key="sk-ant-test-key",
			max_tokens=64,
		)
		url = mock_post.call_args.args[0]
		payload = mock_post.call_args.kwargs["json"]
		self.assertEqual(url, "https://api.anthropic.com/v1/messages")
		self.assertEqual(payload["messages"][0]["role"], "user")
		self.assertEqual(result["usage"]["total_tokens"], 4)

	def test_registry_blocks_discovered_but_unverified_model(self):
		if not frappe.db.exists("DocType", "LPO AI Model Registry"):
			self.skipTest("Model registry DocType has not been migrated")
		good = "gpt-verified-test-model"
		bad = "gpt-discovered-test-model"
		sync_model_registry("OpenAI", [
			{"model_id": good, "endpoint_type": "Responses API"},
			{"model_id": bad, "endpoint_type": "Responses API"},
		])
		mark_model_verification("OpenAI", good, True)
		self.assertEqual(require_verified_model("OpenAI", good), good)
		with self.assertRaises(AIProviderError) as raised:
			require_verified_model("OpenAI", bad)
		self.assertEqual(raised.exception.category, "MODEL_NOT_VERIFIED")

	@patch("lex.lex.doctype.lpo_ai_settings.lpo_ai_settings.set_encrypted_password")
	@patch("lex.lex.doctype.lpo_ai_settings.lpo_ai_settings.discover_provider_models")
	def test_invalid_key_is_not_persisted(self, mock_discover, mock_set_password):
		from lex.lex.doctype.lpo_ai_settings.lpo_ai_settings import save_provider_api_key

		mock_discover.side_effect = AIProviderError("OpenAI", "Incorrect API key", "AUTHENTICATION", status_code=401)
		result = save_provider_api_key("OpenAI", "sk-invalid-test-key")
		self.assertEqual(result["status"], "error")
		self.assertEqual(result["error_type"], "AUTHENTICATION")
		mock_set_password.assert_not_called()
