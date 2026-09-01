app_name = "lex"
app_title = "Lex"
app_publisher = "Lexocrates"
app_description = "Native legal operations and real-time communications for Lexocrates LPO"
app_email = "dev@lexocrates.com"
app_license = "mit"

# Apps
# ------------------

required_apps = ["erpnext"]
app_logo_url = "/assets/lex/images/lexocrates-logo-dark.svg"

# Show operations and messaging as separate Desk tabs. Installed-app ordering is
# maintained by install.ensure_app_is_first so both appear before ERPNext.
add_to_apps_screen = [
	{
		"name": "lex",
		"logo": "/assets/lex/images/lexocrates-mark-dark.png",
		"title": "LPO",
		"route": "/app/executive-workspace",
		"has_permission": "lex.permissions.can_access_operations_app",
	},
]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
app_include_css = "/assets/lex/css/lexocrates_branding.css?v=20260825-1"
app_include_js = [
	"/assets/lex/js/lexocrates_realtime_transport.js?v=20260901-2",
	"/assets/lex/js/lexocrates_chat_sound.js?v=20260825-1",
	"/assets/lex/js/lexocrates_desk_navbar.js?v=20260901-1",
]

# include js, css files in header of web template
web_include_css = "/assets/lex/css/lexocrates_branding.css?v=20260818-1"
web_include_js = "/assets/lex/js/lexocrates_login_enhance.js?v=20260826-2"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "lex/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
	"LPO Matter": "public/js/lpo_job_chat.js",
	"LPO Job": "public/js/lpo_job_chat.js",
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "lex/public/icons.svg"

# Home Pages
# ----------

get_website_user_home_page = "lex.portal_management.get_website_user_home_page"

# Website clients land in their native portal. Internal System Users retain Desk.
role_home_page = {
	"Lexocrates Client": "client-portal",
	"Lexocrates Client Administrator": "client-portal",
	"Lexocrates Partner General Counsel": "client-portal",
	"Lexocrates Legal User": "client-portal",
	"Lexocrates Operations User": "client-portal",
	"Lexocrates Finance User": "client-portal",
	"Lexocrates Procurement User": "client-portal",
	"Lexocrates Compliance User": "client-portal",
	"Lexocrates Read Only User": "client-portal",
	"Customer": "client-portal",
}

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "lex.utils.jinja_methods",
# 	"filters": "lex.utils.jinja_filters"
# }

# Installation
# ------------

before_install = "lex.install.ensure_lpo_roles"
before_migrate = "lex.install.ensure_lpo_roles"
after_install = "lex.install.after_install"
after_migrate = [
	"lex.install.ensure_lpo_roles",
	"lex.install.ensure_legal_document_upload_capacity",
	"lex.install.ensure_lexocrates_branding",
	"lex.client_schema.ensure_client_schema",
	"lex.client_schema.migrate_contact_client_links",
	"lex.install.ensure_app_is_first",
	"lex.install.ensure_home_workspace_actions",
	"lex.install.ensure_lexpack_master_data",
	"lex.install.ensure_lexpack_catalog",
	"lex.install.ensure_accounting_workspace_actions",
	"lex.install.ensure_default_chat_channels",
	"lex.install.migrate_legacy_chat_records",
	"lex.persona_workspaces.ensure_persona_roles",
	"lex.persona_workspaces.ensure_persona_workspaces",
	"lex.client_workspace.migrate_client_users_to_portal",
	"lex.ai_document_engine.ensure_default_ai_document_services",
	"lex.execution_policies.ensure_default_execution_policies",
	"lex.lex.doctype.lpo_ai_settings.lpo_ai_settings.ensure_ai_provider_registry",
	"lex.install.ensure_standalone_estimation_ai_route",
	"lex.pdf_watermark.ensure_all_pdfs_private",
	"lex.lexpoint_estimation.ensure_default_lexpoint_rules",
	"lex.install.ensure_ai_document_estimate_workspace_link",
	"lex.audit_worm_chain.backfill_audit_hash_chain",
	"lex.lexocrates_chat_sync.backfill_matter_chat_channels",
]

# Uninstallation
# ------------

# before_uninstall = "lex.uninstall.before_uninstall"
# after_uninstall = "lex.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "lex.utils.before_app_install"
# after_app_install = "lex.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "lex.utils.before_app_uninstall"
# after_app_uninstall = "lex.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "lex.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

permission_query_conditions = {
	"LPO Matter": "lex.lex.doctype.lpo_matter.lpo_matter.get_permission_query_conditions",
	"LPO Job": "lex.lex.doctype.lpo_job.lpo_job.get_permission_query_conditions",
	"LPO QA Review": "lex.lex.doctype.lpo_qa_review.lpo_qa_review.get_permission_query_conditions",
	"LPO Compliance Log": "lex.lex.doctype.lpo_compliance_log.lpo_compliance_log.get_permission_query_conditions",
	"LPO Channel": "lex.lex.doctype.lpo_channel.lpo_channel.get_permission_query_conditions",
	"LPO Message": "lex.lex.doctype.lpo_message.lpo_message.get_permission_query_conditions",
	"Lexocrates Chat Channel": "lex.lex.doctype.lexocrates_chat_channel.lexocrates_chat_channel.get_permission_query_conditions",
	"Lexocrates Chat Message": "lex.lex.doctype.lexocrates_chat_message.lexocrates_chat_message.get_permission_query_conditions",
	"Lexocrates Portal User": "lex.lex.doctype.lexocrates_portal_user.lexocrates_portal_user.get_permission_query_conditions",
	"Lexocrates Client Department": "lex.lex.doctype.lexocrates_client_department.lexocrates_client_department.get_permission_query_conditions",
	"Lexocrates Portal Invitation": "lex.lex.doctype.lexocrates_portal_invitation.lexocrates_portal_invitation.get_permission_query_conditions",
	"Lexocrates Portal Audit Event": "lex.lex.doctype.lexocrates_portal_audit_event.lexocrates_portal_audit_event.get_permission_query_conditions",
	"Lexocrates Client Wallet": "lex.lex.doctype.lexocrates_client_wallet.lexocrates_client_wallet.get_permission_query_conditions",
	"Lexocrates Wallet Transaction": "lex.lex.doctype.lexocrates_wallet_transaction.lexocrates_wallet_transaction.get_permission_query_conditions",
	"LexPack Purchase": "lex.lex.doctype.lexpack_purchase.lexpack_purchase.get_permission_query_conditions",
	"Lexocrates Work Intake": "lex.lex.doctype.lexocrates_work_intake.lexocrates_work_intake.get_permission_query_conditions",
	"LPO AI Document Export": "lex.lex.doctype.lpo_ai_document_export.lpo_ai_document_export.get_permission_query_conditions",
}

has_permission = {
	"LPO Matter": "lex.lex.doctype.lpo_matter.lpo_matter.has_permission",
	"LPO Job": "lex.lex.doctype.lpo_job.lpo_job.has_permission",
	"LPO QA Review": "lex.lex.doctype.lpo_qa_review.lpo_qa_review.has_permission",
	"LPO Compliance Log": "lex.lex.doctype.lpo_compliance_log.lpo_compliance_log.has_permission",
	"LPO Channel": "lex.lex.doctype.lpo_channel.lpo_channel.has_permission",
	"LPO Message": "lex.lex.doctype.lpo_message.lpo_message.has_permission",
	"Lexocrates Chat Channel": "lex.lex.doctype.lexocrates_chat_channel.lexocrates_chat_channel.has_permission",
	"Lexocrates Chat Message": "lex.lex.doctype.lexocrates_chat_message.lexocrates_chat_message.has_permission",
	"Lexocrates Portal User": "lex.lex.doctype.lexocrates_portal_user.lexocrates_portal_user.has_permission",
	"Lexocrates Client Department": "lex.lex.doctype.lexocrates_client_department.lexocrates_client_department.has_permission",
	"Lexocrates Portal Invitation": "lex.lex.doctype.lexocrates_portal_invitation.lexocrates_portal_invitation.has_permission",
	"Lexocrates Portal Audit Event": "lex.lex.doctype.lexocrates_portal_audit_event.lexocrates_portal_audit_event.has_permission",
	"Lexocrates Client Wallet": "lex.lex.doctype.lexocrates_client_wallet.lexocrates_client_wallet.has_permission",
	"Lexocrates Wallet Transaction": "lex.lex.doctype.lexocrates_wallet_transaction.lexocrates_wallet_transaction.has_permission",
	"LexPack Purchase": "lex.lex.doctype.lexpack_purchase.lexpack_purchase.has_permission",
	"Lexocrates Work Intake": "lex.lex.doctype.lexocrates_work_intake.lexocrates_work_intake.has_permission",
	"LPO AI Document Export": "lex.lex.doctype.lpo_ai_document_export.lpo_ai_document_export.has_permission",
}

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"File": {
		"before_validate": [
			"lex.pdf_watermark.enforce_pdf_private_storage",
			"lex.document_policy.block_matter_attachment",
		],
		"after_insert": "lex.file_quarantine.enqueue_lpo_job_file_scan",
	},
	"User": {
		"on_update": "lex.portal_audit.sync_portal_user_security",
	},
	"LPO Job": {
		"after_insert": "lex.chat_automation.notify_lpo_job_created",
		"on_update": "lex.chat_automation.notify_lpo_job_updated",
	},
	"LPO QA Review": {
		"after_insert": "lex.chat_automation.notify_qa_failure",
		"on_update": "lex.chat_automation.notify_qa_failure",
	},
	"LPO Compliance Log": {
		"after_insert": "lex.chat_automation.notify_compliance_action",
	},
	"AI Job Request": {
		"after_insert": "lex.chat_automation.notify_ai_job_request_created",
	},
	"LPO AI Job Request": {
		"after_insert": "lex.chat_automation.notify_ai_job_request_created",
	},
}

on_session_creation = "lex.portal_audit.audit_login"
on_logout = "lex.portal_audit.audit_logout"

# Scheduled Tasks
# ---------------

scheduler_events = {
	"hourly": [
		"lex.chat_automation.publish_sla_breaches",
		"lex.tasks.expire_portal_security_states",
		"lex.work_intake.reconcile_funded_intakes",
		"lex.file_quarantine.rescan_unavailable_files",
	],
	"cron": {
		"* * * * *": [
			"lex.lex.doctype.lexocrates_chat_presence.lexocrates_chat_presence.mark_stale_presences_offline",
		],
	},
	"daily": [
		"lex.lexpack.recalculate_all_lexpack_tiers",
	],
}

# Testing
# -------

# before_tests = "lex.install.before_tests"

# Overriding Methods
# ------------------------------
override_whitelisted_methods = {
	# Prevent Frappe's generic download endpoint from returning an unmarked PDF.
	# Non-PDF downloads preserve the framework's normal response behavior.
	"frappe.handler.download_file": "lex.pdf_watermark.secure_download_file",
	"frappe.utils.file_manager.download_file": "lex.pdf_watermark.secure_download_file",
	"frappe.core.doctype.file.file.download_file": "lex.pdf_watermark.secure_download_file",
}
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "lex.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
before_request = ["lex.pdf_watermark.install_private_pdf_download_guard"]
after_request = ["lex.pdf_watermark.watermark_system_user_pdf_response"]

# Job Events
# ----------
# before_job = ["lex.utils.before_job"]
# after_job = ["lex.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"lex.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
