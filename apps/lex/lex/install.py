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
LEGAL_DOCUMENT_MAX_UPLOAD_MB = 500
LEXPACK_PLANS = (
	{
		"plan_code": "STARTER", "plan_name": "Starter", "currency": "USD", "price": 299,
		"discount_percent": 7, "value_advantage": "7% savings", "display_order": 1,
		"rolling_qualification_spend": 299, "description": "Entry prepaid legal-capacity bundle.",
	},
	{
		"plan_code": "GROWTH", "plan_name": "Growth", "currency": "USD", "price": 899,
		"discount_percent": 14, "value_advantage": "14% savings", "display_order": 2,
		"rolling_qualification_spend": 899, "description": "Growth prepaid legal-capacity bundle.",
	},
	{
		"plan_code": "PROFESSIONAL", "plan_name": "Professional", "currency": "USD", "price": 1999,
		"discount_percent": 21, "value_advantage": "21% savings", "display_order": 3,
		"rolling_qualification_spend": 1999, "description": "Professional legal-capacity bundle.",
	},
	{
		"plan_code": "BUSINESS", "plan_name": "Business", "currency": "USD", "price": 3999,
		"discount_percent": 28, "value_advantage": "28% savings", "display_order": 4,
		"rolling_qualification_spend": 3999, "description": "Business legal-capacity bundle.",
	},
	{
		"plan_code": "ENTERPRISE", "plan_name": "Enterprise", "currency": "USD", "price": 0,
		"discount_percent": 0,
		"value_advantage": "Custom Commercial Terms", "display_order": 5, "rolling_qualification_spend": 0,
		"description": "Custom enterprise commercial agreement.",
		"enterprise_custom": 1, "self_service": 0,
	},
)
ACCOUNTING_WORKSPACE_ACTIONS = (
	{"id": "lexpack_plans_shortcut", "label": "LexPack Plans", "type": "DocType", "link_to": "LexPack Plan", "color": "#2490ef"},
	{"id": "lexpack_purchases_shortcut", "label": "LexPack Purchases", "type": "DocType", "link_to": "LexPack Purchase", "color": "#29cd42"},
	{"id": "lexpack_wallets_shortcut", "label": "Legal Capacity Wallets", "type": "DocType", "link_to": "Lexocrates Client Wallet", "color": "#f8c629"},
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
	ensure_account_creation_form_fields()
	ensure_default_chat_channels()
	from lex.client_schema import ensure_client_schema

	ensure_client_schema()
	from lex.persona_workspaces import ensure_persona_workspaces

	ensure_persona_workspaces()
	from lex.ai_document_engine import ensure_default_ai_document_services

	ensure_default_ai_document_services()
	from lex.lex.doctype.lpo_ai_settings.lpo_ai_settings import ensure_ai_provider_registry

	ensure_ai_provider_registry()


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
			"description": "Prepaid, non-expiring Legal Capacity in the client's selected currency.",
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
			"checkout_description": "Purchase prepaid, non-expiring Legal Capacity in the selected currency.",
			"checkout_theme_color": "#1f2937",
			"selling_item": LEXPACK_ITEM_CODE if frappe.db.exists("Item", LEXPACK_ITEM_CODE) else None,
			"direct_quote_item": FIXED_QUOTE_ITEM_CODE if frappe.db.exists("Item", FIXED_QUOTE_ITEM_CODE) else None,
			"mode_of_payment": LEXPACK_MODE_OF_PAYMENT if frappe.db.exists("Mode of Payment", LEXPACK_MODE_OF_PAYMENT) else None,
			"company": companies[0] if companies else None,
			"intake_sla_version": "CLIENT-INTAKE-SLA-1.0",
			"quote_currency": "CAD",
			"quote_validity_days": 7,
			"low_confidence_threshold": 72,
			"enable_ai_intake_analysis": 0,
			"intake_ai_provider": "OpenAI",
			"intake_ai_model": "gpt-4o",
		}
		for fieldname, value in defaults.items():
			current = frappe.db.get_single_value("LexPack Settings", fieldname)
			positive_numeric_fields = {
				"api_timeout_seconds", "quote_validity_days",
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
				"text": '<span class="h4"><b>LexPack Prepaid Legal Capacity</b></span><p class="text-muted">Plans, Razorpay purchases, Sales Invoices, Payment Entries and Legal Capacity wallets.</p>',
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


def ensure_account_creation_form_fields():
	"""Restore core Account fields that a stale Desk customization can hide.

	``account_name`` and ``parent_account`` are required by ERPNext's Account
	tree.  Without them an administrator can open *New Account* but cannot create
	a child account.  These fields have no standard visibility conditions, so a
	hidden, conditional, or read-only Property Setter is always stale and safe
	to remove.
	"""
	if not frappe.db.exists("DocType", "Account") or not frappe.db.exists("DocType", "Property Setter"):
		return

	fieldnames = ("account_name", "parent_account")
	stale_setters = frappe.get_all(
		"Property Setter",
		filters={
			"doc_type": "Account",
			"field_name": ["in", fieldnames],
			"property": ["in", ("hidden", "depends_on", "read_only")],
		},
		pluck="name",
	)
	if stale_setters:
		frappe.db.delete("Property Setter", {"name": ["in", stale_setters]})

	# Both fields are standard, mandatory Account fields. Clear meta cache even
	# when no setter was found so Desk receives the current schema after migrate.
	frappe.clear_cache(doctype="Account")


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


_EMAIL_HEADER = """<style>
  body, table, td, p, a, li { -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%; font-family:Arial, Helvetica, sans-serif; }
  table, td { mso-table-lspace:0pt; mso-table-rspace:0pt; border-collapse:collapse !important; }
  img { -ms-interpolation-mode:bicubic; border:0; outline:none; text-decoration:none; }
  @media screen and (max-width:600px) {
    .email-card { width:100% !important; max-width:100% !important; }
    .card-body { padding:26px 20px !important; }
    .card-header { padding:24px 22px !important; }
    .card-footer { padding:22px 20px !important; }
  }
</style>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F3F4F6;">
  <tr>
    <td align="center" style="padding:32px 12px;">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" class="email-card" style="width:100%; max-width:600px; background:#FFFFFF;">
        <tr>
          <td class="card-header" align="left" style="background:#0B2545; border-bottom:3px solid #3476B9; padding:28px 38px 30px 20px; text-align:left;">
            <img src="https://engine.lexocrates.com/assets/lex/images/lexocrates-logo-light.svg" alt="Lexocrates logo" width="180" style="display:block; width:180px; max-width:100%; height:auto; color:#FFFFFF;">
            <p style="margin:16px 0 0; padding-left:18px; font-size:20px; font-weight:bold; line-height:27px; letter-spacing:.1px; color:#FFFFFF;">{{TAGLINE}}</p>
          </td>
        </tr>
        <tr>
          <td class="card-body" style="background:#FFFFFF; padding:38px 38px 32px; font-size:14.5px; line-height:24px; color:#111111;">
"""

_EMAIL_FOOTER = """
          </td>
        </tr>
        <tr>
          <td class="card-footer" align="center" style="background:#F7F8FA; border-top:1px solid #D9E0E8; padding:23px 38px 25px; text-align:center; color:#4B5563;">
            <p style="margin:0 0 11px; font-size:13px; font-weight:bold; line-height:19px; color:#0B2545;">Lexocrates Legal Services</p>

            <table role="presentation" cellpadding="0" cellspacing="0" align="center" style="margin:0 auto 17px;">
              <tr>
                <td style="padding-right:10px;">
                  <a href="https://www.lexocrates.com/" target="_blank" title="Lexocrates website" style="display:inline-block; border:1px solid #CBD5E1; border-radius:4px; padding:7px 11px; color:#0B2545; background:#FFFFFF; font-size:12px; line-height:18px; font-weight:bold; text-decoration:none;"><span aria-hidden="true" style="font-size:14px; vertical-align:middle;">&#127760;</span> &nbsp;Website</a>
                </td>
                <td>
                  <a href="https://www.linkedin.com/company/lexocrates-legal-services-pvt-ltd/" target="_blank" title="Lexocrates on LinkedIn" style="display:inline-block; border:1px solid #CBD5E1; border-radius:4px; padding:7px 11px; color:#0B2545; background:#FFFFFF; font-size:12px; line-height:18px; font-weight:bold; text-decoration:none;"><span aria-hidden="true" style="font-size:14px;">in</span> &nbsp;LinkedIn</a>
                </td>
              </tr>
            </table>

            <p style="margin:0 0 4px; font-size:10px; font-weight:bold; line-height:15px; color:#6B7280;">Confidentiality Notice</p>
            <p style="margin:0; font-size:10px; line-height:15px; color:#7A8492;">This email may contain confidential information. If you received it in error, please notify the sender and delete it.</p>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>"""


def _branded_email(tagline: str, body: str) -> str:
	"""Wrap one template's body content in the shared Lexocrates branded header
	(logo + tagline on navy background) and footer (website/LinkedIn +
	confidentiality notice).

	Deliberately a *fragment* (no <!DOCTYPE>/<html>/<head>/<body>): Frappe's
	frappe.sendmail() unconditionally re-wraps whatever `message` it is given
	inside its own templates/emails/standard.html shell (`<p>{{ content }}</p>`,
	see frappe/email/email_body.py get_formatted_html) — there is no supported
	way to opt out of that wrapper. Handing it a second complete HTML document
	as "content" nested a real <html> inside Frappe's own <html><body>, which
	most mail clients then mangle (stripping the nested <style>/<head> and
	falling back to unstyled/plain rendering — the "old" template the user
	kept seeing). Handing it a fragment instead lets Frappe's own shell — which
	adds no visible branding of its own here since header/with_container are
	never passed — carry it without conflict.

	A plain string replace, not .format()/%, because the body is full of
	literal Jinja {{ }} expressions that must survive untouched for rendering
	at send time."""
	return _EMAIL_HEADER.replace("{{TAGLINE}}", tagline) + body + _EMAIL_FOOTER


def ensure_lexocrates_email_templates():
	"""Create or update canonical Lexocrates email templates without any third-party branding."""
	templates = [
		{
			"name": "Lexocrates Welcome & Portal Invitation",
			"subject": "Welcome to Lexocrates Legal Operations Platform",
			"use_html": 1,
			"response_html": _branded_email("Welcome to Lexocrates", """	<p>Dear {{ user or recipient_name or 'Client' }},</p>
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
""")
		},
		{
			"name": "Lexocrates Password Reset & Security Code",
			"subject": "Lexocrates Security: Reset Your Account Password",
			"use_html": 1,
			"response_html": _branded_email("Security Verification & Password Reset", """	<p>Hello {{ user_name or 'User' }},</p>
	<p>We received a request to reset the password for your <strong>Lexocrates</strong> account (<code>{{ user }}</code>).</p>
	<p>Please click the button below to set a new secure password:</p>
	<p style="margin: 24px 0;">
		<a href="{{ link or frappe.utils.get_url() }}" style="display: inline-block; background-color: #0284c7; color: #ffffff; padding: 12px 26px; border-radius: 6px; font-weight: 600; text-decoration: none;">Set New Password →</a>
	</p>
	<p style="color: #64748b; font-size: 13px;">This link is valid for a limited time. If you did not request this change, you can safely disregard this email or contact our security team immediately.</p>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates Security & Trust</strong></p>
""")
		},
		{
			"name": "Lexocrates New Legal Matter Created",
			"subject": "New Legal Matter Initialized: {{ name }} - {{ matter_title }}",
			"use_html": 1,
			"response_html": _branded_email("Legal Matter Confirmation", """	<p>Dear {{ client_name or 'Client' }},</p>
	<p>A new legal matter has been successfully opened and registered on the Lexocrates Operations Platform.</p>
	<table style="width: 100%; border-collapse: collapse; margin: 20px 0; border: 1px solid #e2e8f0; border-radius: 6px; overflow: hidden;">
		<tr style="background-color: #0f172a; color: #ffffff;">
			<th style="padding: 10px 14px; text-align: left; font-size: 13px;">Matter ID</th>
			<th style="padding: 10px 14px; text-align: left; font-size: 13px;">Title</th>
			<th style="padding: 10px 14px; text-align: left; font-size: 13px;">Practice Area</th>
			<th style="padding: 10px 14px; text-align: left; font-size: 13px;">Lead Manager</th>
		</tr>
		<tr style="background-color: #f8fafc;">
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0; font-weight: 700; color: #0284c7;">{{ name }}</td>
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0;">{{ matter_title }}</td>
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0;">{{ practice_area or 'General LPO' }}</td>
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0;">{{ matter_manager or 'Assigned Team' }}</td>
		</tr>
	</table>
	<p style="margin: 24px 0;">
		<a href="{{ frappe.utils.get_url('/app/lpo-matter/' + name) }}" style="display: inline-block; background-color: #0284c7; color: #ffffff; padding: 11px 24px; border-radius: 6px; font-weight: 600; text-decoration: none;">Open Matter in Workspace →</a>
	</p>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates Legal Operations</strong></p>
""")
		},
		{
			"name": "Lexocrates Legal Matter Status Update",
			"subject": "Matter Status Update: {{ name }} is now {{ status }}",
			"use_html": 1,
			"response_html": _branded_email("Matter Status Milestone", """	<p>Dear {{ client_name or 'Client' }},</p>
	<p>Please be advised that legal matter <strong>{{ name }}</strong> ({{ matter_title }}) has transitioned to status: <span style="display: inline-block; padding: 3px 10px; border-radius: 999px; background: #e0f2fe; color: #0284c7; font-weight: 700; font-size: 13px;">{{ status }}</span>.</p>
	<div style="margin: 20px 0; padding: 16px; background-color: #f8fafc; border-left: 4px solid #0284c7; border-radius: 4px;">
		<strong>Latest Operational Notes:</strong><br>
		{{ description or 'Work is progressing according to agreed SLA guidelines.' }}
	</div>
	<p style="margin: 24px 0;">
		<a href="{{ frappe.utils.get_url('/app/lpo-matter/' + name) }}" style="display: inline-block; background-color: #0284c7; color: #ffffff; padding: 11px 24px; border-radius: 6px; font-weight: 600; text-decoration: none;">Review Matter Progress →</a>
	</p>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates Legal Operations</strong></p>
""")
		},
		{
			"name": "Lexocrates LPO Job Assignment",
			"subject": "Task Assigned: {{ name }} - {{ job_title }}",
			"use_html": 1,
			"response_html": _branded_email("New Job Assignment", """	<p>Dear {{ assigned_analyst or 'Team Member' }},</p>
	<p>You have been assigned to execute the following legal task under Matter <strong>{{ engagement }}</strong>:</p>
	<table style="width: 100%; border-collapse: collapse; margin: 20px 0; border: 1px solid #e2e8f0; border-radius: 6px; overflow: hidden;">
		<tr style="background-color: #0f172a; color: #ffffff;">
			<th style="padding: 10px 14px; text-align: left; font-size: 13px;">Job ID</th>
			<th style="padding: 10px 14px; text-align: left; font-size: 13px;">Title</th>
			<th style="padding: 10px 14px; text-align: left; font-size: 13px;">Priority</th>
			<th style="padding: 10px 14px; text-align: left; font-size: 13px;">Status</th>
		</tr>
		<tr style="background-color: #f8fafc;">
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0; font-weight: 700; color: #0284c7;">{{ name }}</td>
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0;">{{ job_title }}</td>
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0;">{{ priority or 'Medium' }}</td>
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0;">{{ job_status or 'Draft' }}</td>
		</tr>
	</table>
	<p style="margin: 24px 0;">
		<a href="{{ frappe.utils.get_url('/app/lpo-job/' + name) }}" style="display: inline-block; background-color: #0284c7; color: #ffffff; padding: 11px 24px; border-radius: 6px; font-weight: 600; text-decoration: none;">Open Job Task →</a>
	</p>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates Operations Desk</strong></p>
""")
		},
		{
			"name": "Lexocrates LPO Job Deliverable Ready",
			"subject": "Deliverable Ready for Review: {{ job_title }} (Matter: {{ engagement }})",
			"use_html": 1,
			"response_html": _branded_email("Work Deliverable Ready", """	<p>Dear {{ client_name or 'Client' }},</p>
	<p>We are pleased to inform you that the deliverables for task <strong>{{ name }}</strong> (<em>{{ job_title }}</em>) have been completed, audited for quality, and uploaded to your secure workspace.</p>
	<p style="margin: 24px 0;">
		<a href="https://engine.lexocrates.com/client-portal#approvals" style="display: inline-block; background-color: #0284c7; color: #ffffff; padding: 12px 26px; border-radius: 6px; font-weight: 600; text-decoration: none;">Download & Review Deliverable →</a>
	</p>
	<p>Please review the work product and provide your comments or approval via the portal chat.</p>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates Legal Team</strong></p>
""")
		},
		{
			"name": "Lexocrates QA Review & Approval Notice",
			"subject": "QA Audit Certificate Passed: {{ name }} for Job {{ job }}",
			"use_html": 1,
			"response_html": _branded_email("Quality Assurance Audit Clearance", """	<p>Hello Team,</p>
	<p>Quality Review audit record <strong>{{ name }}</strong> for Job <strong>{{ job }}</strong> has been completed with status: <strong style="color: #16a34a;">{{ review_status }}</strong>.</p>
	<table style="width: 100%; border-collapse: collapse; margin: 18px 0; border: 1px solid #e2e8f0; border-radius: 6px; overflow: hidden;">
		<tr style="background-color: #0f172a; color: #ffffff;">
			<th style="padding: 9px 12px; text-align: left; font-size: 13px;">Reviewer</th>
			<th style="padding: 9px 12px; text-align: left; font-size: 13px;">Score</th>
			<th style="padding: 9px 12px; text-align: left; font-size: 13px;">Status</th>
		</tr>
		<tr style="background-color: #f8fafc;">
			<td style="padding: 9px 12px; border-top: 1px solid #e2e8f0;">{{ reviewer }}</td>
			<td style="padding: 9px 12px; border-top: 1px solid #e2e8f0; font-weight: 700;">{{ score or '100%' }}</td>
			<td style="padding: 9px 12px; border-top: 1px solid #e2e8f0; color: #16a34a; font-weight: 700;">{{ review_status }}</td>
		</tr>
	</table>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates Quality & Compliance</strong></p>
""")
		},
		{
			"name": "Lexocrates Work Intake Acknowledgment",
			"subject": "Work Intake Request Received: {{ name }} - {{ title }}",
			"use_html": 1,
			"response_html": _branded_email("Work Intake Acknowledgment", """	<p>Dear {{ submitted_by or 'Client' }},</p>
	<p>Thank you for submitting your legal intake request. We have received your request and assigned reference <strong>{{ name }}</strong>.</p>
	<div style="margin: 18px 0; padding: 16px; background-color: #f8fafc; border-left: 4px solid #0284c7; border-radius: 4px;">
		<strong>Intake Title:</strong> {{ title }}<br>
		<strong>Service Stream:</strong> {{ service_stream or 'General LPO' }}<br>
		<strong>Urgency:</strong> {{ urgency or 'Standard' }}
	</div>
	<p>Our intake counsel is currently reviewing your documentation and will provide scoping and fixed-quote terms within the standard SLA window.</p>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates Intake Desk</strong></p>
""")
		},
		{
			"name": "Lexocrates Fixed Quote Proposal",
			"subject": "Fixed-Fee Legal Quote Proposal: {{ name }} - {{ title }}",
			"use_html": 1,
			"response_html": _branded_email("Fixed-Fee Legal Proposal", """	<p>Dear {{ client_name or 'Client' }},</p>
	<p>We are pleased to provide the fixed-fee quotation for <strong>{{ title }}</strong> (Reference: <code>{{ name }}</code>).</p>
	<div style="margin: 20px 0; padding: 20px; background-color: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 6px; text-align: center;">
		<span style="font-size: 13px; color: #166534; font-weight: 600; text-transform: uppercase;">Fixed Quote Amount</span>
		<div style="font-size: 28px; font-weight: 800; color: #15803d; margin: 4px 0;">{{ currency or '$' }} {{ quote_amount or '0.00' }}</div>
		<span style="font-size: 12px; color: #166534;">Includes standard QA audit, revisions, and compliance verification</span>
	</div>
	<p style="margin: 24px 0; text-align: center;">
		<a href="{{ frappe.utils.get_url('/app/lexocrates-work-intake/' + name) }}" style="display: inline-block; background-color: #16a34a; color: #ffffff; padding: 12px 28px; border-radius: 6px; font-weight: 700; text-decoration: none;">Review & Accept Proposal →</a>
	</p>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates Commercial Operations</strong></p>
""")
		},
		{
			"name": "Lexocrates Sales Invoice & Payment Link",
			"subject": "Invoice {{ name }} from Lexocrates Legal Services",
			"use_html": 1,
			"response_html": _branded_email("Invoice for Legal Services", """	<p>Dear {{ customer_name or 'Client' }},</p>
	<p>Please find details for Invoice <strong>{{ name }}</strong> issued by Lexocrates Legal Services.</p>
	<table style="width: 100%; border-collapse: collapse; margin: 20px 0; border: 1px solid #e2e8f0; border-radius: 6px; overflow: hidden;">
		<tr style="background-color: #0f172a; color: #ffffff;">
			<th style="padding: 10px 14px; text-align: left; font-size: 13px;">Invoice No</th>
			<th style="padding: 10px 14px; text-align: left; font-size: 13px;">Posting Date</th>
			<th style="padding: 10px 14px; text-align: left; font-size: 13px;">Due Date</th>
			<th style="padding: 10px 14px; text-align: right; font-size: 13px;">Grand Total</th>
		</tr>
		<tr style="background-color: #f8fafc;">
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0; font-weight: 700; color: #0284c7;">{{ name }}</td>
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0;">{{ posting_date }}</td>
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0;">{{ due_date or posting_date }}</td>
			<td style="padding: 10px 14px; border-top: 1px solid #e2e8f0; font-weight: 800; text-align: right; color: #0f172a;">{{ currency }} {{ grand_total }}</td>
		</tr>
	</table>
	<p style="margin: 24px 0;">
		<a href="{{ frappe.utils.get_url('/app/sales-invoice/' + name) }}" style="display: inline-block; background-color: #0284c7; color: #ffffff; padding: 12px 26px; border-radius: 6px; font-weight: 600; text-decoration: none;">View Invoice & Pay Online →</a>
	</p>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates Finance Operations</strong></p>
""")
		},
		{
			"name": "Lexocrates Payment Receipt & Confirmation",
			"subject": "Payment Receipt for Invoice {{ name or voucher_no }}",
			"use_html": 1,
			"response_html": _branded_email("Payment Confirmation & Receipt", """	<p>Dear {{ party_name or customer or 'Client' }},</p>
	<p>We gratefully acknowledge receipt of your payment for <strong>{{ name or voucher_no }}</strong>.</p>
	<div style="margin: 20px 0; padding: 20px; background-color: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 6px;">
		<table style="width: 100%; border-collapse: collapse;">
			<tr>
				<td style="padding: 6px 0; color: #166534; font-size: 13px;">Payment Reference:</td>
				<td style="padding: 6px 0; font-weight: 700; color: #15803d; text-align: right;">{{ reference_no or name }}</td>
			</tr>
			<tr>
				<td style="padding: 6px 0; color: #166534; font-size: 13px;">Payment Date:</td>
				<td style="padding: 6px 0; font-weight: 700; color: #15803d; text-align: right;">{{ posting_date or clearance_date }}</td>
			</tr>
			<tr>
				<td style="padding: 6px 0; color: #166534; font-size: 13px;">Amount Cleared:</td>
				<td style="padding: 6px 0; font-weight: 800; font-size: 18px; color: #15803d; text-align: right;">{{ paid_amount or grand_total }}</td>
			</tr>
		</table>
	</div>
	<p>Your client ledger and matter balances have been updated in real-time.</p>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates Accounts & Finance</strong></p>
""")
		},
		{
			"name": "Lexocrates LexPack Legal Capacity Purchase",
			"subject": "LexPack Legal Capacity Purchase Confirmed - {{ plan_name }}",
			"use_html": 1,
			"response_html": _branded_email("LexPack Legal Capacity Confirmed", """	<p>Dear {{ client_name or 'Client' }},</p>
	<p>Your purchase of <strong>{{ plan_name }}</strong> LexPack Legal Capacity bundle has been processed successfully.</p>
	<div style="margin: 20px 0; padding: 20px; background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px;">
		<table style="width: 100%; border-collapse: collapse;">
			<tr>
				<td style="padding: 6px 0; color: #64748b;">Bundle Purchased:</td>
				<td style="padding: 6px 0; font-weight: 700; color: #0f172a; text-align: right;">{{ plan_name }}</td>
			</tr>
			<tr>
				<td style="padding: 6px 0; color: #64748b;">Legal Capacity Credited:</td>
				<td style="padding: 6px 0; font-weight: 800; font-size: 16px; color: #0284c7; text-align: right;">{{ currency }} {{ legal_capacity_amount }}</td>
			</tr>
			<tr>
				<td style="padding: 6px 0; color: #64748b;">Amount Paid:</td>
				<td style="padding: 6px 0; font-weight: 700; color: #0f172a; text-align: right;">{{ currency or '$' }} {{ price }}</td>
			</tr>
		</table>
	</div>
	<p>Your Legal Capacity does not expire and can be used for eligible legal assignments in the same currency.</p>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates LexPack Services</strong></p>
""")
		},
		{
			"name": "Lexocrates Website Contact - Sales Notification",
			"subject": "New website enquiry: {{ request_subject }}",
			"use_html": 1,
			"response_html": _branded_email("New Website Enquiry", """	<p>A new enquiry has been submitted through the Lexocrates compliance contact page.</p>
	<table style="width: 100%; border-collapse: collapse; margin: 20px 0; border: 1px solid #e2e8f0;">
		<tr><th style="width: 150px; padding: 9px 12px; text-align: left; background: #f8fafc; border-bottom: 1px solid #e2e8f0;">CRM Lead</th><td style="padding: 9px 12px; border-bottom: 1px solid #e2e8f0;"><a href="{{ lead_url }}" style="color: #0284c7;">{{ lead_name }}</a></td></tr>
		<tr><th style="padding: 9px 12px; text-align: left; background: #f8fafc; border-bottom: 1px solid #e2e8f0;">Contact</th><td style="padding: 9px 12px; border-bottom: 1px solid #e2e8f0;">{{ request_name }}</td></tr>
		<tr><th style="padding: 9px 12px; text-align: left; background: #f8fafc; border-bottom: 1px solid #e2e8f0;">Email</th><td style="padding: 9px 12px; border-bottom: 1px solid #e2e8f0;"><a href="mailto:{{ request_email }}" style="color: #0284c7;">{{ request_email }}</a></td></tr>
		<tr><th style="padding: 9px 12px; text-align: left; background: #f8fafc; border-bottom: 1px solid #e2e8f0;">Subject</th><td style="padding: 9px 12px; border-bottom: 1px solid #e2e8f0;">{{ request_subject }}</td></tr>
		<tr><th style="padding: 9px 12px; text-align: left; background: #f8fafc;">Submitted</th><td style="padding: 9px 12px;">{{ submitted_on }}</td></tr>
	</table>
	<div style="margin: 18px 0; padding: 16px; white-space: pre-wrap; background: #f8fafc; border-left: 4px solid #0284c7; border-radius: 4px;">{{ request_message }}</div>
	<p style="margin: 24px 0;"><a href="{{ lead_url }}" style="display: inline-block; background: #0284c7; color: #fff; padding: 11px 22px; border-radius: 6px; font-weight: 700; text-decoration: none;">Open CRM Lead →</a></p>
	<p style="color: #64748b; font-size: 13px;">Service level: acknowledge the sender within 24 business hours. Replying to this notification will address the enquiry sender.</p>
""")
		},
		{
			"name": "Lexocrates General Legal Communication",
			"subject": "Lexocrates Communication: {{ subject or 'Notice' }}",
			"use_html": 1,
			"response_html": _branded_email("Lexocrates Communication", """	<p>Dear {{ recipient_name or 'Client' }},</p>
	<div style="margin: 20px 0; padding: 18px; background-color: #f8fafc; border-left: 4px solid #0284c7; border-radius: 4px;">
		{{ message_body or content }}
	</div>
	<p>For more details or actions, please visit the <a href="{{ link or frappe.utils.get_url() }}" style="color: #0284c7; font-weight: 600;">Lexocrates Portal</a>.</p>
	<p style="margin-top: 24px;">Sincerely,<br><strong>Lexocrates Legal Services</strong></p>
""")
		},
		{
			"name": "Lexocrates Pilot Engagement Outreach",
			"subject": "Know the cost before you delegate.",
			"use_html": 1,
			"response_html": _branded_email("Know the cost before you delegate.", """              <p style="margin:0 0 16px; color:#111111;">Dear {{ first_name }},</p>

              <p style="margin:0 0 16px; color:#111111;">A legal assignment may be ready to delegate, but the decision often pauses at one question: what will it cost?</p>

              <p style="margin:0 0 16px; color:#111111;">When the answer depends on how many hours the work eventually takes, it can be difficult to budget for the assignment or discuss the cost with your client in advance.</p>

              <p style="margin:0 0 16px; color:#111111;">At Lexocrates, we bring that conversation forward. Once you share an assignment, <strong>Lextimator™</strong> assesses its scope, volume, complexity, and delivery requirements, then provides a confirmed fixed quotation before work begins. You can review the quotation and decide whether you wish to proceed.</p>

              <p style="margin:0 0 10px; color:#111111;">For firms with ongoing legal support needs, <strong>LexPack™</strong> lets you prepay for legal processing capacity and save on eligible assignments. Choose the tier that fits your expected volume:</p>

              <ul style="margin:0 0 16px; padding-left:24px; color:#111111;">
                <li>Starter — 7% savings</li>
                <li>Growth — 14% savings</li>
                <li>Professional — 21% savings</li>
                <li>Business — 28% savings</li>
              </ul>

              <p style="margin:0 0 16px; color:#111111;">There’s no monthly retainer or expiration date.</p>

              <p style="margin:0 0 16px; color:#111111;">We support law firms with legal research and memoranda, litigation support, document review, and related legal workflows.</p>

              <p style="margin:0 0 16px; color:#111111;"><strong>Experience Lexocrates before you commit.</strong> Start with a complimentary, limited-scope Pilot Engagement. Share a suitable legal task and see our work quality, responsiveness, and process firsthand.</p>

              <p style="margin:0 0 16px; color:#111111;">If you decide to continue, Lextimator™ provides a fixed quotation before each assignment. You can work with us one assignment at a time or choose LexPack™ for ongoing work. No subscription or LexPack™ purchase is needed for the pilot.</p>

              <p style="margin:0 0 16px; color:#111111;">If you have an assignment you’re considering delegating, simply reply to this email. I’d be glad to discuss the requirements and explain how we would assess it.</p>

              <p style="margin:0 0 24px; color:#111111;">See how our workflow works through the website button below.</p>

              <p style="margin:0 0 16px; color:#111111;">Warm regards,</p>

              <p style="margin:0; line-height:22px; color:#111111;">Khushal Singh Shekhawat<br>Sales and Marketing Manager<br><strong>Lexocrates Legal Services Pvt. Ltd.</strong></p>
""")
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
