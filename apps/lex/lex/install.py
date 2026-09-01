import json

import frappe
from frappe.utils import now_datetime


LPO_ROLES = ("LPO_Admin", "LPO_Manager", "LPO_Analyst")
PORTAL_ROLES = (
	"Lexocrates Client Administrator",
	"Lexocrates Partner General Counsel",
	"Lexocrates Legal User",
	"Lexocrates Operations User",
	"Lexocrates Finance User",
	"Lexocrates Procurement User",
	"Lexocrates Compliance User",
	"Lexocrates Read Only User",
)
DEFAULT_CHAT_CHANNELS = {
	"#legal-research": "Legal research collaboration, authorities, citations, and research assignments.",
	"#qa-review": "Quality review coordination, failed-review alerts, and corrective action follow-up.",
	"#compliance-alerts": "Compliance, confidentiality, AI-governance, and SLA alerts.",
}
BRAND_WORDMARK_DARK = "/assets/lex/images/lexocrates-logo-dark.svg"
BRAND_WORDMARK_LIGHT = "/assets/lex/images/lexocrates-logo-light.svg"
BRAND_MARK_DARK = "/assets/lex/images/lexocrates-mark-dark.png"
HOME_WORKSPACE_ACTIONS = (
	{
		"id": "lexocrates_lpo_operation_shortcut",
		"label": "LPO Operation",
		"url": "/app/lpo-operation",
		"color": "#2490ef",
	},
	{
		"id": "lexocrates_lex_shortcut",
		"label": "Lex",
		"url": "/app/lpo-msg",
		"color": "#29cd42",
	},
)
HOME_WORKSPACE_BLOCK_IDS = {
	"lexocrates_legal_operations_header",
	*(action["id"] for action in HOME_WORKSPACE_ACTIONS),
}
LEXPACK_ITEM_CODE = "LEXPACK-LEGAL-CAPACITY"
FIXED_QUOTE_ITEM_CODE = "LEXOCRATES-FIXED-QUOTE"
LEXPACK_MODE_OF_PAYMENT = "Razorpay"
LEGAL_DOCUMENT_MAX_UPLOAD_MB = 250
LEXPACK_PLANS = (
	{
		"plan_code": "STARTER", "plan_name": "Starter", "price": 299, "lexpoints": 100,
		"value_advantage": "Standard", "display_order": 1, "rolling_qualification_spend": 299,
		"qualification_bonus_points": 0, "description": "Entry prepaid legal-capacity bundle.",
	},
	{
		"plan_code": "GROWTH", "plan_name": "Growth", "price": 899, "lexpoints": 350,
		"value_advantage": "Save 14%", "display_order": 2, "rolling_qualification_spend": 899,
		"qualification_bonus_points": 30, "description": "Growth bundle with the concept-note value advantage.",
	},
	{
		"plan_code": "PROFESSIONAL", "plan_name": "Professional", "price": 1999, "lexpoints": 900,
		"value_advantage": "Save 26%", "display_order": 3, "rolling_qualification_spend": 1999,
		"qualification_bonus_points": 145, "description": "Professional legal-capacity bundle.",
	},
	{
		"plan_code": "BUSINESS", "plan_name": "Business", "price": 3999, "lexpoints": 2000,
		"value_advantage": "Save 33%", "display_order": 4, "rolling_qualification_spend": 3999,
		"qualification_bonus_points": 0, "description": "Business legal-capacity bundle.",
	},
	{
		"plan_code": "ENTERPRISE", "plan_name": "Enterprise", "price": 0, "lexpoints": 0,
		"value_advantage": "Custom Commercial Terms", "display_order": 5, "rolling_qualification_spend": 0,
		"qualification_bonus_points": 0, "description": "Custom enterprise commercial agreement.",
		"enterprise_custom": 1, "self_service": 0,
	},
)
ACCOUNTING_WORKSPACE_ACTIONS = (
	{"id": "lexpack_plans_shortcut", "label": "LexPack Plans", "type": "DocType", "link_to": "LexPack Plan", "color": "#2490ef"},
	{"id": "lexpack_purchases_shortcut", "label": "LexPack Purchases", "type": "DocType", "link_to": "LexPack Purchase", "color": "#29cd42"},
	{"id": "lexpack_wallets_shortcut", "label": "LexPoint Wallets", "type": "DocType", "link_to": "Lexocrates Client Wallet", "color": "#f8c629"},
	{"id": "lexpack_settings_shortcut", "label": "Razorpay Settings", "type": "DocType", "link_to": "LexPack Settings", "color": "#ff5858"},
)
ACCOUNTING_WORKSPACE_BLOCK_IDS = {
	"lexpack_accounting_header",
	*(action["id"] for action in ACCOUNTING_WORKSPACE_ACTIONS),
}


def ensure_lpo_roles():
	"""Create the application roles before DocType permissions are imported."""
	for role_name in (*LPO_ROLES, *PORTAL_ROLES):
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc(
				{
					"doctype": "Role",
					"role_name": role_name,
					"desk_access": int(role_name in LPO_ROLES),
					"is_custom": 0,
				}
			).insert(ignore_permissions=True)
		elif role_name in LPO_ROLES and not frappe.db.get_value("Role", role_name, "desk_access"):
			frappe.db.set_value("Role", role_name, "desk_access", 1, update_modified=False)


def ensure_app_is_first():
	"""Keep LPO Operation immediately after Frappe in the Desk app-switcher order."""
	installed_apps = frappe.get_installed_apps()
	if "lex" not in installed_apps:
		return

	ordered_apps = ["frappe", "lex"]
	ordered_apps.extend(app for app in installed_apps if app not in ordered_apps)
	if ordered_apps != installed_apps:
		frappe.db.set_global("installed_apps", json.dumps(ordered_apps))
		frappe.clear_cache()


def after_install():
	ensure_lpo_roles()
	ensure_legal_document_upload_capacity()
	ensure_app_is_first()
	ensure_lexocrates_branding()
	ensure_home_workspace_actions()
	ensure_lexpack_master_data()
	ensure_lexpack_catalog()
	ensure_accounting_workspace_actions()
	ensure_default_chat_channels()
	from lex.client_schema import ensure_client_schema

	ensure_client_schema()
	from lex.persona_workspaces import ensure_persona_workspaces

	ensure_persona_workspaces()
	from lex.ai_document_engine import ensure_default_ai_document_services

	ensure_default_ai_document_services()
	from lex.lex.doctype.lpo_ai_settings.lpo_ai_settings import ensure_ai_provider_registry

	ensure_ai_provider_registry()
	ensure_standalone_estimation_ai_route()
	from lex.lexpoint_estimation import ensure_default_lexpoint_rules

	ensure_default_lexpoint_rules()
	ensure_ai_document_estimate_workspace_link()


def ensure_legal_document_upload_capacity():
	"""Keep Frappe's upload ceiling suitable for large legal bundles.

	This is deliberately a high, configurable ceiling rather than an unlimited
	request body, which would expose every web worker to trivial memory exhaustion.
	Existing administrators can raise the value later from System Settings.
	"""
	if not frappe.db.exists("DocType", "System Settings"):
		return
	meta = frappe.get_meta("System Settings")
	if not meta.has_field("max_file_size"):
		return
	target_bytes = LEGAL_DOCUMENT_MAX_UPLOAD_MB * 1024 * 1024
	current_mb = int(frappe.db.get_single_value("System Settings", "max_file_size") or 0)
	if current_mb < LEGAL_DOCUMENT_MAX_UPLOAD_MB:
		frappe.db.set_single_value("System Settings", "max_file_size", LEGAL_DOCUMENT_MAX_UPLOAD_MB)
	# Frappe v15 has two upload-size resolvers: the modern File API reads
	# System Settings, while frappe.utils.file_manager.save_file reads site
	# config. Keep both sources aligned so the final persistence step cannot
	# unexpectedly fall back to its legacy 10 MB default.
	if int(frappe.conf.get("max_file_size") or 0) < target_bytes:
		from frappe.installer import update_site_config

		update_site_config("max_file_size", target_bytes, validate=False)
	frappe.clear_cache()


def ensure_standalone_estimation_ai_route():
	"""Enable the dedicated estimator route and inherit the verified intake route once."""
	if not frappe.db.exists("DocType", "LPO AI Settings"):
		return
	meta = frappe.get_meta("LPO AI Settings")
	if not meta.has_field("enable_standalone_estimation"):
		return
	settings = frappe.get_single("LPO AI Settings")
	initialized_fields = {
		row[0]
		for row in frappe.db.sql(
			"""select `field` from `tabSingles`
			where `doctype` = %s and `field` in
			('enable_standalone_estimation', 'estimation_credential', 'estimation_provider', 'estimation_model')""",
			("LPO AI Settings",),
		)
	}
	values = {}
	if "enable_standalone_estimation" not in initialized_fields:
		values["enable_standalone_estimation"] = 1
	for target, source in (
		("estimation_credential", "intake_credential"),
		("estimation_provider", "intake_provider"),
		("estimation_model", "intake_model"),
	):
		if (
			meta.has_field(target)
			and target not in initialized_fields
			and settings.get(source)
		):
			values[target] = settings.get(source)
	if values:
		frappe.db.set_value("LPO AI Settings", "LPO AI Settings", values, update_modified=False)
	frappe.clear_cache(doctype="LPO AI Settings")


def ensure_lexpack_master_data():
	"""Create neutral accounting masters without guessing a clearing account or enabling payments."""
	if frappe.db.exists("DocType", "Mode of Payment") and not frappe.db.exists("Mode of Payment", LEXPACK_MODE_OF_PAYMENT):
		frappe.get_doc(
			{
				"doctype": "Mode of Payment",
				"mode_of_payment": LEXPACK_MODE_OF_PAYMENT,
				"type": "Bank",
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
	if frappe.db.exists("DocType", "Item") and not frappe.db.exists("Item", LEXPACK_ITEM_CODE):
		item_group = frappe.db.get_value("Item Group", {"name": "Services", "is_group": 0}, "name")
		item_group = item_group or frappe.db.get_value("Item Group", {"is_group": 0}, "name")
		stock_uom = "Nos" if frappe.db.exists("UOM", "Nos") else frappe.db.get_value("UOM", {}, "name")
		if item_group and stock_uom:
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": LEXPACK_ITEM_CODE,
					"item_name": "LexPack Legal Capacity",
					"description": "Prepaid, non-expiring legal capacity issued as LexPoints.",
					"item_group": item_group,
					"stock_uom": stock_uom,
					"is_stock_item": 0,
					"include_item_in_manufacturing": 0,
					"is_sales_item": 1,
					"is_purchase_item": 0,
				}
			).insert(ignore_permissions=True)
	if frappe.db.exists("DocType", "Item") and not frappe.db.exists("Item", FIXED_QUOTE_ITEM_CODE):
		item_group = frappe.db.get_value("Item Group", {"name": "Services", "is_group": 0}, "name")
		item_group = item_group or frappe.db.get_value("Item Group", {"is_group": 0}, "name")
		stock_uom = "Nos" if frappe.db.exists("UOM", "Nos") else frappe.db.get_value("UOM", {}, "name")
		if item_group and stock_uom:
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": FIXED_QUOTE_ITEM_CODE,
					"item_name": "Lexocrates Fixed Quote Legal Service",
					"description": "Client-approved fixed quote for a confirmed legal work intake.",
					"item_group": item_group,
					"stock_uom": stock_uom,
					"is_stock_item": 0,
					"include_item_in_manufacturing": 0,
					"is_sales_item": 1,
					"is_purchase_item": 0,
				}
			).insert(ignore_permissions=True)
	if frappe.db.exists("DocType", "LexPack Settings"):
		frappe.clear_cache(doctype="LexPack Settings")
		companies = frappe.get_all("Company", pluck="name", limit_page_length=2)
		defaults = {
			"enabled": 0,
			"test_mode": 1,
			"api_timeout_seconds": 15,
			"checkout_name": "Lexocrates Legal Services Pvt. Ltd.",
			"checkout_description": "Purchase prepaid legal capacity with non-expiring LexPoints.",
			"checkout_theme_color": "#1f2937",
			"selling_item": LEXPACK_ITEM_CODE if frappe.db.exists("Item", LEXPACK_ITEM_CODE) else None,
			"direct_quote_item": FIXED_QUOTE_ITEM_CODE if frappe.db.exists("Item", FIXED_QUOTE_ITEM_CODE) else None,
			"mode_of_payment": LEXPACK_MODE_OF_PAYMENT if frappe.db.exists("Mode of Payment", LEXPACK_MODE_OF_PAYMENT) else None,
			"company": companies[0] if companies else None,
			"intake_sla_version": "CLIENT-INTAKE-SLA-1.0",
			"quote_currency": "USD",
			"direct_quote_rate_per_point": 3,
			"quote_validity_days": 7,
			"low_confidence_threshold": 72,
			"enable_ai_intake_analysis": 0,
			"intake_ai_provider": "OpenAI",
			"intake_ai_model": "gpt-4o",
		}
		for fieldname, value in defaults.items():
			current = frappe.db.get_single_value("LexPack Settings", fieldname)
			positive_numeric_fields = {
				"api_timeout_seconds", "direct_quote_rate_per_point", "quote_validity_days",
				"low_confidence_threshold",
			}
			is_missing = current in (None, "") or (
				fieldname in positive_numeric_fields and float(current or 0) <= 0
			)
			if value is not None and is_missing:
				frappe.db.set_single_value("LexPack Settings", fieldname, value)


def ensure_lexpack_catalog():
	"""Seed the five bundles from LexPack Business Model v1.0 without overwriting approved edits."""
	if not frappe.db.exists("DocType", "LexPack Plan"):
		return
	for values in LEXPACK_PLANS:
		if frappe.db.exists("LexPack Plan", values["plan_code"]):
			continue
		frappe.get_doc(
			{
				"doctype": "LexPack Plan",
				"status": "Active",
				"currency": "USD",
				"self_service": 1,
				"enterprise_custom": 0,
				"no_expiry": 1,
				**values,
			}
		).insert(ignore_permissions=True)


def ensure_accounting_workspace_actions():
	"""Expose LexPack commercial and ledger records beside ERPNext accounting tools."""
	if not frappe.db.exists("DocType", "Workspace") or not frappe.db.exists("Workspace", "Accounting"):
		return
	workspace = frappe.get_doc("Workspace", "Accounting")
	try:
		content = json.loads(workspace.content or "[]")
	except (TypeError, ValueError):
		content = []
	if not isinstance(content, list):
		content = []
	managed_labels = {action["label"] for action in ACCOUNTING_WORKSPACE_ACTIONS}
	content = [
		block for block in content
		if block.get("id") not in ACCOUNTING_WORKSPACE_BLOCK_IDS
		and not (block.get("type") == "shortcut" and block.get("data", {}).get("shortcut_name") in managed_labels)
	]
	blocks = [
		{
			"id": "lexpack_accounting_header",
			"type": "header",
			"data": {
				"text": '<span class="h4"><b>LexPack Prepaid Legal Capacity</b></span><p class="text-muted">Plans, Razorpay purchases, Sales Invoices, Payment Entries and LexPoint wallets.</p>',
				"col": 12,
			},
		}
	]
	blocks.extend(
		{"id": action["id"], "type": "shortcut", "data": {"shortcut_name": action["label"], "col": 3}}
		for action in ACCOUNTING_WORKSPACE_ACTIONS
	)
	updated_content = json.dumps([*blocks, *content], separators=(",", ":"))
	existing_rows = frappe.get_all(
		"Workspace Shortcut",
		filters={"parent": "Accounting", "parenttype": "Workspace", "parentfield": "shortcuts"},
		fields=["name", "idx", "label", "type", "link_to", "url", "color"],
		order_by="idx asc",
	)
	next_idx = max((int(row.idx or 0) for row in existing_rows), default=0)
	changed = workspace.content != updated_content
	for action in ACCOUNTING_WORKSPACE_ACTIONS:
		matching = [row for row in existing_rows if row.label == action["label"]]
		if matching:
			row = matching[0]
			if len(matching) > 1:
				frappe.db.delete("Workspace Shortcut", {"name": ["in", [item.name for item in matching[1:]]]})
				changed = True
		else:
			next_idx += 1
			row = frappe.get_doc(
				{
					"doctype": "Workspace Shortcut", "parent": "Accounting", "parenttype": "Workspace",
					"parentfield": "shortcuts", "idx": next_idx,
				}
			)
			row.db_insert()
			changed = True
		values = {"label": action["label"], "type": action["type"], "link_to": action["link_to"], "url": None, "color": action["color"]}
		if any(row.get(fieldname) != value for fieldname, value in values.items()):
			frappe.db.set_value("Workspace Shortcut", row.name, values, update_modified=False)
			changed = True
	if changed:
		frappe.db.set_value("Workspace", "Accounting", "content", updated_content, update_modified=False)
		frappe.clear_cache()


def ensure_ai_document_estimate_workspace_link():
	"""Expose governed estimation records and management-controlled pricing rules."""
	if (
		not frappe.db.exists("DocType", "Workspace")
		or not frappe.db.exists("Workspace", "AI Workspace")
	):
		return
	managed_links = (
		("Standalone LexPoint Estimator", "lexpoint-estimator", "Page"),
		("Standalone Estimate History", "LPO Standalone Estimate", "DocType"),
		("Intake AI Estimates", "LPO AI Document Estimate", "DocType"),
		("LexPoint Service Rules", "LPO LexPoint Service Rule", "DocType"),
		("LexPoint Multipliers", "LPO LexPoint Multiplier", "DocType"),
		("LexPoint Formula Settings", "LPO LexPoint Settings", "DocType"),
	)
	changed = False
	next_idx = frappe.db.get_value(
		"Workspace Link",
		{"parent": "AI Workspace", "parenttype": "Workspace", "parentfield": "links"},
		"max(idx)",
	) or 0
	for label, link_to, link_type in managed_links:
		if not frappe.db.exists(link_type, link_to):
			continue
		existing = frappe.get_all(
			"Workspace Link",
			filters={
				"parent": "AI Workspace", "parenttype": "Workspace", "parentfield": "links",
				"type": "Link", "link_to": link_to,
			},
			fields=["name", "label", "link_type"], limit_page_length=1,
		)
		if existing:
			row = existing[0]
			if row.label != label or row.link_type != link_type:
				frappe.db.set_value(
					"Workspace Link", row.name, {"label": label, "link_type": link_type}, update_modified=False,
				)
				changed = True
			continue
		next_idx += 1
		frappe.get_doc({
			"doctype": "Workspace Link", "parent": "AI Workspace", "parenttype": "Workspace",
			"parentfield": "links", "idx": int(next_idx), "type": "Link", "label": label,
			"link_to": link_to, "link_type": link_type,
		}).db_insert()
		changed = True

	card = frappe.get_all(
		"Workspace Link",
		filters={"parent": "AI Workspace", "parenttype": "Workspace", "parentfield": "links", "type": "Card Break"},
		fields=["name", "link_count"],
		order_by="idx asc",
		limit_page_length=1,
	)
	link_count = frappe.db.count(
		"Workspace Link",
		{"parent": "AI Workspace", "parenttype": "Workspace", "parentfield": "links", "type": "Link"},
	)
	if card and card[0].link_count != link_count:
		frappe.db.set_value("Workspace Link", card[0].name, "link_count", link_count, update_modified=False)
		changed = True

	if changed:
		frappe.clear_cache()


def ensure_home_workspace_actions():
	"""Keep the two primary LPO applications at the top of ERPNext Home."""
	if not frappe.db.exists("DocType", "Workspace") or not frappe.db.exists("Workspace", "Home"):
		return

	workspace = frappe.get_doc("Workspace", "Home")
	try:
		content = json.loads(workspace.content or "[]")
	except (TypeError, ValueError):
		content = []
	if not isinstance(content, list):
		content = []

	managed_labels = {action["label"] for action in HOME_WORKSPACE_ACTIONS}
	content = [
		block
		for block in content
		if block.get("id") not in HOME_WORKSPACE_BLOCK_IDS
		and not (
			block.get("type") == "shortcut"
			and block.get("data", {}).get("shortcut_name") in managed_labels
		)
	]
	home_actions = [
		{
			"id": "lexocrates_legal_operations_header",
			"type": "header",
			"data": {
				"text": (
					'<span class="h4"><b>Lexocrates Legal Operations</b></span>'
					'<p class="text-muted">Open operational monitoring or secure internal communication.</p>'
				),
				"col": 12,
			},
		}
	]
	for action in HOME_WORKSPACE_ACTIONS:
		home_actions.append(
			{
				"id": action["id"],
				"type": "shortcut",
				"data": {"shortcut_name": action["label"], "col": 6},
			}
		)
	updated_content = json.dumps([*home_actions, *content], separators=(",", ":"))

	changed = workspace.content != updated_content
	existing_rows = frappe.get_all(
		"Workspace Shortcut",
		filters={"parent": "Home", "parenttype": "Workspace", "parentfield": "shortcuts"},
		fields=["name", "idx", "label", "type", "link_to", "url", "color"],
		order_by="idx asc",
	)
	next_idx = max((int(row.idx or 0) for row in existing_rows), default=0)
	for action in HOME_WORKSPACE_ACTIONS:
		matching_rows = [row for row in existing_rows if row.label == action["label"]]
		if matching_rows:
			row = matching_rows[0]
			duplicate_names = [duplicate.name for duplicate in matching_rows[1:]]
			if duplicate_names:
				frappe.db.delete("Workspace Shortcut", {"name": ["in", duplicate_names]})
				changed = True
		else:
			next_idx += 1
			row = frappe.get_doc(
				{
					"doctype": "Workspace Shortcut",
					"parent": "Home",
					"parenttype": "Workspace",
					"parentfield": "shortcuts",
					"idx": next_idx,
				}
			)
			row.db_insert()
			changed = True
		values = {
			"label": action["label"],
			"type": "URL",
			"link_to": None,
			"url": action["url"],
			"color": action["color"],
		}
		if any(row.get(fieldname) != value for fieldname, value in values.items()):
			frappe.db.set_value(
				"Workspace Shortcut",
				row.name,
				values,
				update_modified=False,
			)
			changed = True

	if changed:
		frappe.db.set_value(
			"Workspace",
			"Home",
			"content",
			updated_content,
			update_modified=False,
		)
		frappe.clear_cache()


def ensure_lexocrates_branding():
	"""Apply the canonical Lexocrates identity to Website, login, Desk, and Email surfaces."""
	brand_html = (
		'<span class="lexocrates-brand-wordmark">'
		f'<img class="lexocrates-logo-dark" src="{BRAND_WORDMARK_DARK}" alt="Lexocrates">'
		f'<img class="lexocrates-logo-light" src="{BRAND_WORDMARK_LIGHT}" alt="Lexocrates">'
		'</span>'
	)
	settings = (
		(
			"Website Settings",
			{
				"app_name": "Lexocrates",
				"app_logo": BRAND_WORDMARK_DARK,
				"banner_image": BRAND_WORDMARK_DARK,
				"brand_html": brand_html,
				"favicon": BRAND_MARK_DARK,
				"footer_logo": BRAND_WORDMARK_DARK,
				"splash_image": BRAND_WORDMARK_DARK,
				"footer_powered": 'Powered by <a href="https://www.linkedin.com/in/deepak-rankawat-658b0a259/" target="_blank" rel="noopener noreferrer" style="color: #0284c7; font-weight: 600; text-decoration: underline;">Deepak Rankawat</a>',
			},
		),
		("Navbar Settings", {"app_logo": BRAND_WORDMARK_DARK}),
		(
			"System Settings",
			{
				"app_name": "Lexocrates",
				"disable_standard_email_footer": 1,
				"email_footer_address": "Lexocrates Legal Services · Legal Operations & Technology",
				"otp_issuer_name": "Lexocrates",
			},
		),
	)
	changed = False
	for doctype, values in settings:
		if not frappe.db.exists("DocType", doctype):
			continue
		doc = frappe.get_single(doctype)
		doc_changed = False
		for fieldname, value in values.items():
			if doc.meta.has_field(fieldname) and doc.get(fieldname) != value:
				doc.set(fieldname, value)
				doc_changed = True
		if doc_changed:
			doc.save(ignore_permissions=True)
			changed = True

	ensure_lexocrates_email_templates()

	if changed:
		frappe.clear_cache()


def ensure_lexocrates_email_templates():
	"""Create or update canonical Lexocrates email templates without any third-party branding."""
	templates = [
		{
			"name": "Lexocrates Welcome & Portal Invitation",
			"subject": "Welcome to Lexocrates Legal Operations Platform",
			"use_html": 1,
			"response_html": """<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 15px; color: #1e293b; line-height: 1.6;">
	<h2 style="color: #0f172a; margin-top: 0; font-size: 20px;">Welcome to Lexocrates</h2>
	<p>Dear {{ user or recipient_name or 'Client' }},</p>
	<p>Your secure access to the <strong>Lexocrates Legal Operations Platform</strong> has been initialized.</p>
	<p>Through the portal, you can:</p>
	<ul style="padding-left: 20px; color: #334155; margin: 16px 0;">
		<li style="margin-bottom: 6px;">Initiate and track legal matters in real-time</li>
		<li style="margin-bottom: 6px;">Collaborate securely with dedicated legal analysts and counsel</li>
		<li style="margin-bottom: 6px;">Review work deliverables and audited QA certificates</li>
		<li style="margin-bottom: 6px;">Manage LexPack legal capacity and invoices</li>
	</ul>
	<p style="margin: 28px 0;">
		<a href="{{ login_url or frappe.utils.get_url('/login') }}" style="display: inline-block; background-color: #0284c7; color: #ffffff; padding: 12px 28px; border-radius: 6px; font-weight: 600; text-decoration: none; box-shadow: 0 2px 4px rgba(2,132,199,0.25);">Access Lexocrates Portal →</a>
	</p>
	<p style="color: #64748b; font-size: 13px;">If you have any questions or require onboarding assistance, reply directly to this email.</p>
	<p style="margin-top: 24px;">Warm regards,<br><strong>Lexocrates Client Operations</strong></p>
</div>"""
		},
		{
			"name": "Lexocrates Password Reset & Security Code",
			"subject": "Lexocrates Security: Reset Your Account Password",
			"use_html": 1,
			"response_html": """<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 15px; color: #1e293b; line-height: 1.6;">
	<h2 style="color: #0f172a; margin-top: 0; font-size: 20px;">Security Verification & Password Reset</h2>
	<p>Hello {{ user_name or 'User' }},</p>
	<p>We received a request to reset the password for your <strong>Lexocrates</strong> account (<code>{{ user }}</code>).</p>
	<p>Please click the button below to set a new secure password:</p>
	<p style="margin: 24px 0;">
		<a href="{{ link or frappe.utils.get_url() }}" style="display: inline-block; background-color: #0284c7; color: #ffffff; padding: 12px 26px; border-radius: 6px; font-weight: 600; text-decoration: none;">Set New Password →</a>
	</p>
	<p style="color: #64748b; font-size: 13px;">This link is valid for a limited time. If you did not request this change, you can safely disregard this email or contact our security team immediately.</p>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates Security & Trust</strong></p>
</div>"""
		},
		{
			"name": "Lexocrates New Legal Matter Created",
			"subject": "New Legal Matter Initialized: {{ doc.name }} - {{ doc.matter_title }}",
			"use_html": 1,
			"response_html": """<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 15px; color: #1e293b; line-height: 1.6;">
	<h2 style="color: #0f172a; margin-top: 0; font-size: 20px;">Legal Matter Confirmation</h2>
	<p>Dear {{ doc.client_name or 'Client' }},</p>
	<p>A new legal matter has been successfully opened and registered on the Lexocrates Operations Platform.</p>
	<table style="width: 100%; border-collapse: collapse; margin: 20px 0; border: 1px solid #e2e8f0; border-radius: 6px; overflow: hidden;">
		<tr style="background-color: #0f172a; color: #ffffff;">
			<th style="padding: 10px 14px; text-align: left; font-size: 13px;">Matter ID</th>
			<th style="padding: 10px 14px; text-align: left; font-size: 13px;">Title</th>
			<th style="padding: 10px 14px; text-align: left; font-size: 13px;">Practice Area</th>
			<th style="padding: 10px 14px; text-align: left; font-size: 13px;">Lead Manager</th>
		</tr>
		<tr style="background-color: #f8fafc;">
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0; font-weight: 700; color: #0284c7;">{{ doc.name }}</td>
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0;">{{ doc.matter_title }}</td>
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0;">{{ doc.practice_area or 'General LPO' }}</td>
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0;">{{ doc.matter_manager or 'Assigned Team' }}</td>
		</tr>
	</table>
	<p style="margin: 24px 0;">
		<a href="{{ frappe.utils.get_url('/app/lpo-matter/' + doc.name) }}" style="display: inline-block; background-color: #0284c7; color: #ffffff; padding: 11px 24px; border-radius: 6px; font-weight: 600; text-decoration: none;">Open Matter in Workspace →</a>
	</p>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates Legal Operations</strong></p>
</div>"""
		},
		{
			"name": "Lexocrates Legal Matter Status Update",
			"subject": "Matter Status Update: {{ doc.name }} is now {{ doc.status }}",
			"use_html": 1,
			"response_html": """<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 15px; color: #1e293b; line-height: 1.6;">
	<h2 style="color: #0f172a; margin-top: 0; font-size: 20px;">Matter Status Milestone</h2>
	<p>Dear {{ doc.client_name or 'Client' }},</p>
	<p>Please be advised that legal matter <strong>{{ doc.name }}</strong> ({{ doc.matter_title }}) has transitioned to status: <span style="display: inline-block; padding: 3px 10px; border-radius: 999px; background: #e0f2fe; color: #0284c7; font-weight: 700; font-size: 13px;">{{ doc.status }}</span>.</p>
	<div style="margin: 20px 0; padding: 16px; background-color: #f8fafc; border-left: 4px solid #0284c7; border-radius: 4px;">
		<strong>Latest Operational Notes:</strong><br>
		{{ doc.description or 'Work is progressing according to agreed SLA guidelines.' }}
	</div>
	<p style="margin: 24px 0;">
		<a href="{{ frappe.utils.get_url('/app/lpo-matter/' + doc.name) }}" style="display: inline-block; background-color: #0284c7; color: #ffffff; padding: 11px 24px; border-radius: 6px; font-weight: 600; text-decoration: none;">Review Matter Progress →</a>
	</p>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates Legal Operations</strong></p>
</div>"""
		},
		{
			"name": "Lexocrates LPO Job Assignment",
			"subject": "Task Assigned: {{ doc.name }} - {{ doc.job_title }}",
			"use_html": 1,
			"response_html": """<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 15px; color: #1e293b; line-height: 1.6;">
	<h2 style="color: #0f172a; margin-top: 0; font-size: 20px;">New Job Assignment</h2>
	<p>Dear {{ doc.assigned_analyst or 'Team Member' }},</p>
	<p>You have been assigned to execute the following legal task under Matter <strong>{{ doc.engagement }}</strong>:</p>
	<table style="width: 100%; border-collapse: collapse; margin: 20px 0; border: 1px solid #e2e8f0; border-radius: 6px; overflow: hidden;">
		<tr style="background-color: #0f172a; color: #ffffff;">
			<th style="padding: 10px 14px; text-align: left; font-size: 13px;">Job ID</th>
			<th style="padding: 10px 14px; text-align: left; font-size: 13px;">Title</th>
			<th style="padding: 10px 14px; text-align: left; font-size: 13px;">Priority</th>
			<th style="padding: 10px 14px; text-align: left; font-size: 13px;">Status</th>
		</tr>
		<tr style="background-color: #f8fafc;">
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0; font-weight: 700; color: #0284c7;">{{ doc.name }}</td>
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0;">{{ doc.job_title }}</td>
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0;">{{ doc.priority or 'Medium' }}</td>
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0;">{{ doc.job_status or 'Draft' }}</td>
		</tr>
	</table>
	<p style="margin: 24px 0;">
		<a href="{{ frappe.utils.get_url('/app/lpo-job/' + doc.name) }}" style="display: inline-block; background-color: #0284c7; color: #ffffff; padding: 11px 24px; border-radius: 6px; font-weight: 600; text-decoration: none;">Open Job Task →</a>
	</p>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates Operations Desk</strong></p>
</div>"""
		},
		{
			"name": "Lexocrates LPO Job Deliverable Ready",
			"subject": "Deliverable Ready for Review: {{ doc.job_title }} (Matter: {{ doc.engagement }})",
			"use_html": 1,
			"response_html": """<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 15px; color: #1e293b; line-height: 1.6;">
	<h2 style="color: #0f172a; margin-top: 0; font-size: 20px;">Work Deliverable Ready</h2>
	<p>Dear {{ doc.client_name or 'Client' }},</p>
	<p>We are pleased to inform you that the deliverables for task <strong>{{ doc.name }}</strong> (<em>{{ doc.job_title }}</em>) have been completed, audited for quality, and uploaded to your secure workspace.</p>
	<p style="margin: 24px 0;">
		<a href="{{ frappe.utils.get_url('/app/lpo-job/' + doc.name) }}" style="display: inline-block; background-color: #0284c7; color: #ffffff; padding: 12px 26px; border-radius: 6px; font-weight: 600; text-decoration: none;">Download & Review Deliverable →</a>
	</p>
	<p>Please review the work product and provide your comments or approval via the portal chat.</p>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates Legal Team</strong></p>
</div>"""
		},
		{
			"name": "Lexocrates QA Review & Approval Notice",
			"subject": "QA Audit Certificate Passed: {{ doc.name }} for Job {{ doc.job }}",
			"use_html": 1,
			"response_html": """<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 15px; color: #1e293b; line-height: 1.6;">
	<h2 style="color: #0f172a; margin-top: 0; font-size: 20px;">Quality Assurance Audit Clearance</h2>
	<p>Hello Team,</p>
	<p>Quality Review audit record <strong>{{ doc.name }}</strong> for Job <strong>{{ doc.job }}</strong> has been completed with status: <strong style="color: #16a34a;">{{ doc.review_status }}</strong>.</p>
	<table style="width: 100%; border-collapse: collapse; margin: 18px 0; border: 1px solid #e2e8f0; border-radius: 6px; overflow: hidden;">
		<tr style="background-color: #0f172a; color: #ffffff;">
			<th style="padding: 9px 12px; text-align: left; font-size: 13px;">Reviewer</th>
			<th style="padding: 9px 12px; text-align: left; font-size: 13px;">Score</th>
			<th style="padding: 9px 12px; text-align: left; font-size: 13px;">Status</th>
		</tr>
		<tr style="background-color: #f8fafc;">
			<td style="padding: 9px 12px; border-top: 1px solid #e2e8f0;">{{ doc.reviewer }}</td>
			<td style="padding: 9px 12px; border-top: 1px solid #e2e8f0; font-weight: 700;">{{ doc.score or '100%' }}</td>
			<td style="padding: 9px 12px; border-top: 1px solid #e2e8f0; color: #16a34a; font-weight: 700;">{{ doc.review_status }}</td>
		</tr>
	</table>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates Quality & Compliance</strong></p>
</div>"""
		},
		{
			"name": "Lexocrates Work Intake Acknowledgment",
			"subject": "Work Intake Request Received: {{ doc.name }} - {{ doc.title }}",
			"use_html": 1,
			"response_html": """<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 15px; color: #1e293b; line-height: 1.6;">
	<h2 style="color: #0f172a; margin-top: 0; font-size: 20px;">Work Intake Acknowledgment</h2>
	<p>Dear {{ doc.submitted_by or 'Client' }},</p>
	<p>Thank you for submitting your legal intake request. We have received your request and assigned reference <strong>{{ doc.name }}</strong>.</p>
	<div style="margin: 18px 0; padding: 16px; background-color: #f8fafc; border-left: 4px solid #0284c7; border-radius: 4px;">
		<strong>Intake Title:</strong> {{ doc.title }}<br>
		<strong>Service Stream:</strong> {{ doc.service_stream or 'General LPO' }}<br>
		<strong>Urgency:</strong> {{ doc.urgency or 'Standard' }}
	</div>
	<p>Our intake counsel is currently reviewing your documentation and will provide scoping and fixed-quote terms within the standard SLA window.</p>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates Intake Desk</strong></p>
</div>"""
		},
		{
			"name": "Lexocrates Fixed Quote Proposal",
			"subject": "Fixed-Fee Legal Quote Proposal: {{ doc.name }} - {{ doc.title }}",
			"use_html": 1,
			"response_html": """<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 15px; color: #1e293b; line-height: 1.6;">
	<h2 style="color: #0f172a; margin-top: 0; font-size: 20px;">Fixed-Fee Legal Proposal</h2>
	<p>Dear {{ doc.client_name or 'Client' }},</p>
	<p>We are pleased to provide the fixed-fee quotation for <strong>{{ doc.title }}</strong> (Reference: <code>{{ doc.name }}</code>).</p>
	<div style="margin: 20px 0; padding: 20px; background-color: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 6px; text-align: center;">
		<span style="font-size: 13px; color: #166534; font-weight: 600; text-transform: uppercase;">Fixed Quote Amount</span>
		<div style="font-size: 28px; font-weight: 800; color: #15803d; margin: 4px 0;">{{ doc.currency or '$' }} {{ doc.quote_amount or '0.00' }}</div>
		<span style="font-size: 12px; color: #166534;">Includes standard QA audit, revisions, and compliance verification</span>
	</div>
	<p style="margin: 24px 0; text-align: center;">
		<a href="{{ frappe.utils.get_url('/app/lexocrates-work-intake/' + doc.name) }}" style="display: inline-block; background-color: #16a34a; color: #ffffff; padding: 12px 28px; border-radius: 6px; font-weight: 700; text-decoration: none;">Review & Accept Proposal →</a>
	</p>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates Commercial Operations</strong></p>
</div>"""
		},
		{
			"name": "Lexocrates Sales Invoice & Payment Link",
			"subject": "Invoice {{ doc.name }} from Lexocrates Legal Services",
			"use_html": 1,
			"response_html": """<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 15px; color: #1e293b; line-height: 1.6;">
	<h2 style="color: #0f172a; margin-top: 0; font-size: 20px;">Invoice for Legal Services</h2>
	<p>Dear {{ doc.customer_name or 'Client' }},</p>
	<p>Please find details for Invoice <strong>{{ doc.name }}</strong> issued by Lexocrates Legal Services.</p>
	<table style="width: 100%; border-collapse: collapse; margin: 20px 0; border: 1px solid #e2e8f0; border-radius: 6px; overflow: hidden;">
		<tr style="background-color: #0f172a; color: #ffffff;">
			<th style="padding: 10px 14px; text-align: left; font-size: 13px;">Invoice No</th>
			<th style="padding: 10px 14px; text-align: left; font-size: 13px;">Posting Date</th>
			<th style="padding: 10px 14px; text-align: left; font-size: 13px;">Due Date</th>
			<th style="padding: 10px 14px; text-align: right; font-size: 13px;">Grand Total</th>
		</tr>
		<tr style="background-color: #f8fafc;">
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0; font-weight: 700; color: #0284c7;">{{ doc.name }}</td>
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0;">{{ doc.posting_date }}</td>
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0;">{{ doc.due_date or doc.posting_date }}</td>
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0; font-weight: 800; text-align: right; color: #0f172a;">{{ doc.currency }} {{ doc.grand_total }}</td>
		</tr>
	</table>
	<p style="margin: 24px 0;">
		<a href="{{ frappe.utils.get_url('/app/sales-invoice/' + doc.name) }}" style="display: inline-block; background-color: #0284c7; color: #ffffff; padding: 12px 26px; border-radius: 6px; font-weight: 600; text-decoration: none;">View Invoice & Pay Online →</a>
	</p>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates Finance Operations</strong></p>
</div>"""
		},
		{
			"name": "Lexocrates Payment Receipt & Confirmation",
			"subject": "Payment Receipt for Invoice {{ doc.name or doc.voucher_no }}",
			"use_html": 1,
			"response_html": """<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 15px; color: #1e293b; line-height: 1.6;">
	<h2 style="color: #0f172a; margin-top: 0; font-size: 20px;">Payment Confirmation & Receipt</h2>
	<p>Dear {{ doc.party_name or doc.customer or 'Client' }},</p>
	<p>We gratefully acknowledge receipt of your payment for <strong>{{ doc.name or doc.voucher_no }}</strong>.</p>
	<div style="margin: 20px 0; padding: 20px; background-color: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 6px;">
		<table style="width: 100%; border-collapse: collapse;">
			<tr>
				<td style="padding: 6px 0; color: #166534; font-size: 13px;">Payment Reference:</td>
				<td style="padding: 6px 0; font-weight: 700; color: #15803d; text-align: right;">{{ doc.reference_no or doc.name }}</td>
			</tr>
			<tr>
				<td style="padding: 6px 0; color: #166534; font-size: 13px;">Payment Date:</td>
				<td style="padding: 6px 0; font-weight: 700; color: #15803d; text-align: right;">{{ doc.posting_date or doc.clearance_date }}</td>
			</tr>
			<tr>
				<td style="padding: 6px 0; color: #166534; font-size: 13px;">Amount Cleared:</td>
				<td style="padding: 6px 0; font-weight: 800; font-size: 18px; color: #15803d; text-align: right;">{{ doc.paid_amount or doc.grand_total }}</td>
			</tr>
		</table>
	</div>
	<p>Your client ledger and matter balances have been updated in real-time.</p>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates Accounts & Finance</strong></p>
</div>"""
		},
		{
			"name": "Lexocrates LexPack Legal Capacity Purchase",
			"subject": "LexPack Capacity Purchase Confirmed - {{ doc.plan_name }} ({{ doc.lexpoints }} LexPoints)",
			"use_html": 1,
			"response_html": """<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 15px; color: #1e293b; line-height: 1.6;">
	<h2 style="color: #0f172a; margin-top: 0; font-size: 20px;">LexPack Legal Capacity Confirmed</h2>
	<p>Dear {{ doc.client_name or 'Client' }},</p>
	<p>Your purchase of <strong>{{ doc.plan_name }}</strong> LexPack Legal Capacity bundle has been processed successfully.</p>
	<div style="margin: 20px 0; padding: 20px; background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px;">
		<table style="width: 100%; border-collapse: collapse;">
			<tr>
				<td style="padding: 6px 0; color: #64748b;">Bundle Purchased:</td>
				<td style="padding: 6px 0; font-weight: 700; color: #0f172a; text-align: right;">{{ doc.plan_name }}</td>
			</tr>
			<tr>
				<td style="padding: 6px 0; color: #64748b;">LexPoints Credited:</td>
				<td style="padding: 6px 0; font-weight: 800; font-size: 16px; color: #0284c7; text-align: right;">+{{ doc.lexpoints }} LexPoints</td>
			</tr>
			<tr>
				<td style="padding: 6px 0; color: #64748b;">Amount Paid:</td>
				<td style="padding: 6px 0; font-weight: 700; color: #0f172a; text-align: right;">{{ doc.currency or '$' }} {{ doc.price }}</td>
			</tr>
		</table>
	</div>
	<p>Your LexPoints do not expire and can be redeemed across all legal research, contract management, and compliance workflows.</p>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates LexPack Services</strong></p>
</div>"""
		},
		{
			"name": "Lexocrates General Legal Communication",
			"subject": "Lexocrates Communication: {{ subject or 'Notice' }}",
			"use_html": 1,
			"response_html": """<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 15px; color: #1e293b; line-height: 1.6;">
	<p>Dear {{ recipient_name or 'Client' }},</p>
	<div style="margin: 20px 0; padding: 18px; background-color: #f8fafc; border-left: 4px solid #0284c7; border-radius: 4px;">
		{{ message_body or content }}
	</div>
	<p>For more details or actions, please visit the <a href="{{ link or frappe.utils.get_url() }}" style="color: #0284c7; font-weight: 600;">Lexocrates Portal</a>.</p>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates Legal Services</strong></p>
</div>"""
		},
	]

	for tmpl in templates:
		if frappe.db.exists("Email Template", tmpl["name"]):
			doc = frappe.get_doc("Email Template", tmpl["name"])
			doc.subject = tmpl["subject"]
			doc.use_html = tmpl["use_html"]
			doc.response_html = tmpl["response_html"]
			doc.save(ignore_permissions=True)
		else:
			frappe.get_doc({
				"doctype": "Email Template",
				**tmpl
			}).insert(ignore_permissions=True)


def ensure_default_chat_channels():
	"""Create the operational public channels without manufacturing business data."""
	if not frappe.db.exists("DocType", "Lexocrates Chat Channel"):
		return

	for channel_name, description in DEFAULT_CHAT_CHANNELS.items():
		if frappe.db.exists("Lexocrates Chat Channel", {"channel_name": channel_name}):
			continue
		frappe.get_doc(
			{
				"doctype": "Lexocrates Chat Channel",
				"channel_name": channel_name,
				"channel_type": "Public",
				"status": "Active",
				"description": description,
				"members": [
					{
						"user": "Administrator",
						"channel_role": "Owner",
						"can_post_messages": 1,
						"can_invite_members": 1,
						"joined_on": now_datetime(),
					}
				],
			}
		).insert(ignore_permissions=True)


def migrate_legacy_chat_records():
	"""Copy the original LPO Channel history into the production chat model once."""
	if not all(
		frappe.db.exists("DocType", doctype)
		for doctype in ("LPO Channel", "LPO Message", "Lexocrates Chat Channel", "Lexocrates Chat Message")
	):
		return

	from lex.lex.doctype.lexocrates_chat_channel.lexocrates_chat_channel import (
		ensure_contextual_channel,
	)

	legacy_channels = frappe.get_all(
		"LPO Channel",
		fields=["name", "reference_doctype", "reference_name"],
		limit_page_length=0,
	)
	for legacy in legacy_channels:
		if not (
			legacy.reference_doctype
			and legacy.reference_name
			and frappe.db.exists("DocType", legacy.reference_doctype)
			and frappe.db.exists(legacy.reference_doctype, legacy.reference_name)
		):
			continue
		members = frappe.get_all(
			"LPO Channel Member",
			filters={"parent": legacy.name, "parenttype": "LPO Channel"},
			pluck="user",
			limit_page_length=0,
		)
		channel = ensure_contextual_channel(
			legacy.reference_doctype, legacy.reference_name, members
		)
		_legacy_messages_to_channel(legacy.name, channel.name)


def _legacy_messages_to_channel(legacy_channel: str, channel: str):
	legacy_messages = frappe.get_all(
		"LPO Message",
		filters={"channel": legacy_channel},
		fields=["name", "sender", "content", "timestamp"],
		order_by="timestamp asc, creation asc",
		limit_page_length=0,
	)
	for legacy_message in legacy_messages:
		automation_key = f"legacy-message:{legacy_message.name}"
		if frappe.db.exists("Lexocrates Chat Message", {"automation_key": automation_key}):
			continue
		previous_flag = getattr(frappe.flags, "lexocrates_chat_import", False)
		frappe.flags.lexocrates_chat_import = True
		try:
			frappe.get_doc(
				{
					"doctype": "Lexocrates Chat Message",
					"channel": channel,
					"sender": legacy_message.sender,
					"sent_at": legacy_message.timestamp,
					"message_text": legacy_message.content,
					"mentions": "[]",
					"attachments": "[]",
					"automation_key": automation_key,
				}
			).insert(ignore_permissions=True)
		finally:
			frappe.flags.lexocrates_chat_import = previous_flag
