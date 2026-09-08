from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase


class TestLexocratesTheme(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.app_path = Path(frappe.get_app_path("lex"))

	def read(self, relative_path: str) -> str:
		return (self.app_path / relative_path).read_text(encoding="utf-8")

	def test_theme_is_loaded_for_desk_and_website(self):
		hooks = self.read("hooks.py")
		asset = "/assets/lex/css/lexocrates_branding.css?v=20260908-1"

		self.assertIn("app_include_css", hooks)
		self.assertIn("web_include_css", hooks)
		self.assertGreaterEqual(hooks.count(asset), 2)

	def test_theme_exposes_required_design_tokens(self):
		css = self.read("public/css/lexocrates_branding.css")
		required_tokens = {
			"--lex-bg": "#f4f6f8",
			"--lex-surface": "#ffffff",
			"--lex-surface-2": "#eef1f4",
			"--lex-surface-3": "#e4e9ee",
			"--lex-border": "#e1e6ea",
			"--lex-border-strong": "#ccd4db",
			"--lex-ink": "#101828",
			"--lex-ink-muted": "#5c6b7a",
			"--lex-primary": "#1e293b",
			"--lex-primary-hover": "#0f172a",
			"--lex-accent": "#0d9488",
		}

		for token, value in required_tokens.items():
			self.assertIn(f"{token}: {value};", css)

	def test_branding_and_chat_responsive_contract(self):
		branding = self.read("public/css/lexocrates_branding.css")
		staff_login = self.read("www/login.html")
		client_login = self.read("www/client-login.html")
		chat_css = self.read("lex/page/lexocrates_chat/lexocrates_chat.css")
		chat_js = self.read("lex/page/lexocrates_chat/lexocrates_chat.js")
		portal_css = self.read("public/css/client_portal.css")
		portal_js = self.read("public/js/client_portal.js")
		transport_js = self.read("public/js/lexocrates_realtime_transport.js")
		portal_template = self.read("www/client-portal.html")

		self.assertIn("height: 58px !important;", branding)
		self.assertIn("height: 44px;", staff_login)
		self.assertIn("height: 44px;", client_login)
		self.assertIn("lex-chat__mobile-back", chat_js)
		self.assertIn('this.$root.addClass("is-conversation-open")', chat_js)
		self.assertNotIn('frappe.utils.icon("user-plus"', chat_js)
		self.assertIn('frappe.utils.icon("users", "sm")', chat_js)
		self.assertIn('frappe.utils.icon("add", "sm")', chat_js)
		self.assertIn('dialog.$wrapper.addClass("lex-chat__dm-dialog")', chat_js)
		self.assertIn(".lex-chat.is-conversation-open .lex-chat__conversation", chat_css)
		self.assertIn('body[data-route="lexocrates-chat"] .lex-floating-chat-container', chat_css)
		self.assertIn("background: var(--lex-primary, #1e293b);", chat_css)
		self.assertIn(".lex-chat__brand-actions .btn-primary", chat_css)
		self.assertIn("--icon-stroke: #ffffff;", chat_css)
		self.assertIn(".lex-chat__dm-dialog .modal-body", chat_css)
		self.assertIn(".lex-chat__unread.indicator-pill", chat_css)
		self.assertIn("color: #ffffff !important;", chat_css)
		self.assertIn('.lex-chat__message:not(.is-own):not(.is-system) .lex-chat__bubble', chat_css)
		self.assertIn("border-left: 3px solid var(--lex-accent, #0d9488);", chat_css)
		self.assertIn('.lex-chat__message:not(.is-own):not(.is-system) .lex-chat__avatar .standard-image', chat_css)
		self.assertIn(".lex-chat__message.is-system.is-own .lex-chat__message-body", chat_css)
		self.assertIn("color: var(--lex-ink, #101828);", chat_css)
		self.assertIn("color: var(--lex-ink-muted, #5c6b7a);", chat_css)
		self.assertIn("lex-chat-mobile-back", portal_js)
		self.assertIn('chat?.classList.add("is-conversation-open")', portal_js)
		self.assertIn(".lex-chat.is-conversation-open .lex-chat-main", portal_css)
		self.assertNotIn('frappe.provide("lex.chat")', transport_js)
		self.assertIn("window.lex.chat.realtime", transport_js)
		self.assertIn("lexocrates_realtime_transport.js?v=20260908-1", portal_template)
