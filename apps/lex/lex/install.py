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
	"""Apply the canonical Lexocrates identity to Website, login and Desk surfaces."""
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
	if changed:
		frappe.clear_cache()


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
