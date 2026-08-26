from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import get_decrypted_password, set_encrypted_password

from lex.ai_providers import AIProviderError, mark_model_verification, sync_model_registry
from lex.lex.doctype.lpo_ai_settings.lpo_ai_settings import (
	_get_provider_key,
	get_ai_provider_config,
	resolve_ai_route,
)


class TestAIMultiCredentials(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("DocType", "LPO AI Provider Credential"):
			self.skipTest("LPO AI Provider Credential has not been migrated")

		self.suffix = frappe.generate_hash(length=8).lower()
		self.primary_name = f"OpenAI Primary Test {self.suffix}"
		self.secondary_name = f"OpenAI Secondary Test {self.suffix}"
		self.model = f"gpt-multi-key-test-{self.suffix}"
		self.primary_secret = f"sk-primary-{self.suffix}"
		self.secondary_secret = f"sk-secondary-{self.suffix}"

		sync_model_registry("OpenAI", [{"model_id": self.model, "endpoint_type": "Responses API"}])
		mark_model_verification("OpenAI", self.model, True)

		settings = frappe.get_single("LPO AI Settings")
		primary = settings.append("provider_credentials", {
			"credential_name": self.primary_name,
			"provider": "OpenAI",
			"enabled": 1,
			"priority": 20,
			"default_model": self.model,
			"available_models": self.model,
			"verification_status": "Active - verified",
		})
		secondary = settings.append("provider_credentials", {
			"credential_name": self.secondary_name,
			"provider": "OpenAI",
			"enabled": 1,
			"priority": 5,
			"default_model": self.model,
			"available_models": self.model,
			"verification_status": "Active - verified",
		})
		settings.job_chat_credential = self.primary_name
		settings.job_chat_provider = "OpenAI"
		settings.job_chat_model = self.model
		settings.save(ignore_permissions=True)
		set_encrypted_password("LPO AI Provider Credential", primary.name, self.primary_secret, "api_key")
		set_encrypted_password("LPO AI Provider Credential", secondary.name, self.secondary_secret, "api_key")
		self.primary_row_name = primary.name
		self.secondary_row_name = secondary.name

	def test_use_case_route_selects_named_credential_and_secret(self):
		provider, model, credential = resolve_ai_route(None, None, "Job Legal Copilot")
		self.assertEqual((provider, model, credential), ("OpenAI", self.model, self.primary_name))
		settings = frappe.get_single("LPO AI Settings")
		self.assertEqual(
			_get_provider_key(settings, provider, credential_name=credential),
			self.primary_secret,
		)

	def test_priority_selects_best_credential_without_explicit_route(self):
		settings = frappe.get_single("LPO AI Settings")
		settings.default_credential = None
		settings.job_chat_credential = None
		settings.job_chat_provider = None
		settings.job_chat_model = None
		settings.default_provider = "OpenAI"
		settings.save(ignore_permissions=True)
		provider, model, credential = resolve_ai_route(None, None, "Unrouted Internal AI Use")
		self.assertEqual((provider, model, credential), ("OpenAI", self.model, self.secondary_name))

	def test_public_config_never_returns_api_secret(self):
		config = get_ai_provider_config()
		serialized = json.dumps(config, default=str)
		self.assertNotIn(self.primary_secret, serialized)
		self.assertNotIn(self.secondary_secret, serialized)
		credential = next(row for row in config["credentials"] if row["credential_name"] == self.primary_name)
		self.assertTrue(credential["has_key"])
		self.assertNotIn("api_key", credential)
		self.assertEqual(
			get_decrypted_password(
				"LPO AI Provider Credential",
				self.primary_row_name,
				"api_key",
				raise_exception=False,
			),
			self.primary_secret,
		)

	def test_provider_mismatch_and_disabled_credential_are_blocked(self):
		with self.assertRaises(AIProviderError) as mismatch:
			resolve_ai_route("Anthropic", None, credential_name=self.primary_name)
		self.assertEqual(mismatch.exception.category, "CREDENTIAL_PROVIDER_MISMATCH")

		frappe.db.set_value(
			"LPO AI Provider Credential",
			self.primary_row_name,
			"enabled",
			0,
			update_modified=False,
		)
		with self.assertRaises(AIProviderError) as disabled:
			resolve_ai_route(None, None, credential_name=self.primary_name)
		self.assertEqual(disabled.exception.category, "CREDENTIAL_DISABLED")
