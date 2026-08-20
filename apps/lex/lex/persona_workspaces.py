from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any

import frappe
from frappe.utils import add_days, add_to_date, get_first_day, now_datetime, nowdate

from lex.client_workspace import (
	CLIENT_ONBOARDING_BLOCK,
	CLIENT_WORKSPACE,
	ensure_client_module_profile,
	ensure_client_onboarding_block,
)


PERSONA_ROLES = (
	"CEO",
	"Lexocrates Client",
	"Junior Legal Associate",
	"Senior Legal Associate",
	"Lexocrates QA Manager",
	"Lexocrates Operations Manager",
	"Lexocrates AI Manager",
	"Lexocrates Sales & Marketing",
	"Lexocrates HR",
	"Lexocrates Compliance Officer",
	"Lexocrates Finance",
	"Lexocrates Director",
)

PERSONA_BASE_ROLES = {
	"CEO": ("LPO_Admin", "Sales Manager", "Accounts Manager"),
	"Lexocrates Client": ("Customer",),
	"Junior Legal Associate": ("LPO_Analyst",),
	"Senior Legal Associate": ("LPO_Manager",),
	"Lexocrates QA Manager": ("LPO_Manager",),
	"Lexocrates Operations Manager": ("LPO_Manager",),
	"Lexocrates AI Manager": ("LPO_Manager",),
	"Lexocrates Sales & Marketing": ("Sales Manager",),
	"Lexocrates HR": ("HR Manager",),
	"Lexocrates Compliance Officer": ("LPO_Manager",),
	"Lexocrates Finance": ("Accounts Manager",),
	"Lexocrates Director": ("LPO_Admin", "Sales Manager", "Accounts Manager"),
}

# Administrative users need a complete view of the company's functional
# workspaces. Everyone else continues to be matched against the roles declared
# on the individual workspace specification.
ADMIN_WORKSPACE_ROLES = ("CEO", "LPO_Admin", "System Manager")


@dataclass(frozen=True)
class Shortcut:
	label: str
	type: str
	link_to: str
	doc_view: str | None = None
	stats_filter: str | None = None
	color: str | None = None


@dataclass(frozen=True)
class PersonaWorkspace:
	name: str
	roles: tuple[str, ...]
	subtitle: str
	cards: tuple[str, ...] = ()
	shortcuts: tuple[Shortcut, ...] = ()
	icon: str = "dashboard"
	sequence_id: float = 10
	custom_blocks: tuple[str, ...] = ()



CEO_MONITORING_BLOCK = "Lexocrates CEO Executive Monitoring Cockpit"

CHAT = Shortcut("Communication", "Page", "lexocrates-chat", color="#2490ef")


WORKSPACES = (
	PersonaWorkspace(
		"Executive Workspace",
		("CEO", "Lexocrates Director"),
		"Analytics-only executive cockpit with 360-degree real-time monitoring of LexPacks, Clients, Waiting Jobs & Matters, and Active Lawyer Workload.",
		(
			"Monthly Revenue",
			"LexPack Sales",
			"Total Clients",
			"Client Registrations Pending",
			"Open Matters",
			"Jobs Waiting In Queue",
			"Intakes Waiting Review",
			"Jobs Delivered",
			"Active Lawyers On Projects",
			"Overdue LPO Jobs",
			"Average TAT Hours",
			"SLA Compliance",
			"Average QA Score",
			"Active Employees",
		),
		(
			Shortcut("Work Intakes Waiting", "DocType", "Lexocrates Work Intake", "List"),
			Shortcut("Jobs Waiting Queue", "DocType", "LPO Job", "List"),
			Shortcut("Delivered Jobs", "DocType", "LPO Job", "List"),
			Shortcut("Open Matters", "DocType", "LPO Matter", "List"),
			Shortcut("LexPack Purchases", "DocType", "LexPack Purchase", "List"),
			Shortcut("Customers & Clients", "DocType", "Customer", "List"),
			Shortcut("Client Registrations", "DocType", "Lexocrates Client Registration", "List"),
			Shortcut("Portal Users & Lawyers", "DocType", "Lexocrates Portal User", "List"),
			Shortcut("Employees & Staff", "DocType", "Employee", "List"),
			Shortcut("QA Review Queue", "DocType", "LPO QA Review", "List"),
			Shortcut("Client Wallets", "DocType", "Lexocrates Client Wallet", "List"),
			CHAT,
		),
		icon="chart",
		sequence_id=1,
		custom_blocks=(CEO_MONITORING_BLOCK,),
	),
	PersonaWorkspace(
		"Legal Operations Workspace",
		("Lexocrates Operations Manager", "LPO_Admin", "LPO_Manager"),
		"Production command center for queues, matters, clients, delivery, SLA, QA, and compliance.",
		("Open LPO Jobs", "Overdue LPO Jobs", "Open Matters", "Open Compliance Actions"),
		(
			Shortcut("Work Intakes", "DocType", "Lexocrates Work Intake", "List"),
			Shortcut("Jobs", "DocType", "LPO Job", "List"),
			Shortcut("Matters", "DocType", "LPO Matter", "List"),
			Shortcut("Clients", "DocType", "Customer", "List"),
			Shortcut("Portal Users", "DocType", "Lexocrates Portal User", "List"),
			Shortcut("Client Registrations", "DocType", "Lexocrates Client Registration", "List"),
			Shortcut("Client Departments", "DocType", "Lexocrates Client Department", "List"),
			Shortcut("Portal Invitations", "DocType", "Lexocrates Portal Invitation", "List"),
			Shortcut("QA Queue", "DocType", "LPO QA Review", "List"),
			Shortcut("Compliance Logs", "DocType", "LPO Compliance Log", "List"),
			Shortcut("Portal Audit", "DocType", "Lexocrates Portal Audit Event", "List"),
			Shortcut("Workflow Definitions", "DocType", "LPO Workflow Definition", "List"),
			Shortcut("Workflow Versions", "DocType", "LPO Workflow Version", "List"),
			Shortcut("Workflow Executions", "DocType", "LPO Workflow Execution", "List"),
			Shortcut("SOPs", "DocType", "LPO SOP", "List"),
			Shortcut("SOP Versions", "DocType", "LPO SOP Version", "List"),
			Shortcut("SOP Runs", "DocType", "LPO SOP Run", "List"),
			Shortcut("Node Runs", "DocType", "LPO Node Run", "List"),
			Shortcut("Prompts", "DocType", "LPO Prompt", "List"),
			Shortcut("Prompt Versions", "DocType", "LPO Prompt Version", "List"),
			Shortcut("AI Executions", "DocType", "LPO AI Execution", "List"),
			Shortcut("AI Governance", "DocType", "LPO AI Governance Policy", "List"),
			Shortcut("LexPack Plans", "DocType", "LexPack Plan", "List"),
			Shortcut("LexPack Purchases", "DocType", "LexPack Purchase", "List"),
			Shortcut("Client Wallets", "DocType", "Lexocrates Client Wallet", "List"),
			Shortcut("Wallet Transactions", "DocType", "Lexocrates Wallet Transaction", "List"),
			Shortcut("LexPack Settings", "DocType", "LexPack Settings", "List"),
			Shortcut("Chat Channels", "DocType", "Lexocrates Chat Channel", "List"),
			Shortcut("Chat Messages", "DocType", "Lexocrates Chat Message", "List"),
			Shortcut("SLA Clocks", "DocType", "LPO Clock", "List"),
			CHAT,
		),
		icon="organization",
		sequence_id=2,
	),
	PersonaWorkspace(
		"Junior Associate Workspace",
		("Junior Legal Associate",),
		"Daily assignments, deadlines, completed work, knowledge, and job discussions.",
		("My Open Jobs", "My Jobs Due Today", "My Jobs Completed Today"),
		(
			Shortcut("My Assigned Jobs", "DocType", "LPO Job", "List"),
			Shortcut("Due Today", "DocType", "LPO Job", "List"),
			Shortcut("Completed Jobs", "DocType", "LPO Job", "List"),
			Shortcut("Templates", "DocType", "File", "List"),
			Shortcut("Knowledge Library", "DocType", "Help Article", "List"),
			CHAT,
		),
		icon="employee",
		sequence_id=3,
	),
	PersonaWorkspace(
		"Senior Associate Workspace",
		("Senior Legal Associate",),
		"Team queue, legal review, returned work, escalations, and matter discussions.",
		("Open LPO Jobs", "Pending QA Reviews", "Failed QA Reviews"),
		(
			Shortcut("Team Queue", "DocType", "LPO Job", "List"),
			Shortcut("Pending Legal Review", "DocType", "LPO QA Review", "List"),
			Shortcut("Returned Jobs", "DocType", "LPO QA Review", "List"),
			Shortcut("Escalations", "DocType", "Lexocrates Portal Audit Event", "List"),
			Shortcut("Templates", "DocType", "File", "List"),
			Shortcut("Knowledge Base", "DocType", "Help Article", "List"),
			CHAT,
		),
		icon="team",
		sequence_id=4,
	),
	PersonaWorkspace(
		"QA Workspace",
		("Lexocrates QA Manager",),
		"Pending and failed reviews, reviewer performance, checklists, and quality discussions.",
		("Pending QA Reviews", "Failed QA Reviews", "Average QA Score"),
		(
			Shortcut("Pending QA", "DocType", "LPO QA Review", "List"),
			Shortcut("Failed QA", "DocType", "LPO QA Review", "List"),
			Shortcut("Returned Jobs", "DocType", "LPO Job", "List"),
			Shortcut("Quality Reports", "DocType", "LPO QA Review", "List"),
			Shortcut("Clause Library", "DocType", "File", "List"),
			Shortcut("Checklists", "DocType", "File", "List"),
			CHAT,
		),
		icon="quality",
		sequence_id=5,
	),
	PersonaWorkspace(
		"AI Workspace",
		("Lexocrates AI Manager", "Lexocrates Operations Manager", "Lexocrates Director"),
		"Governed AI-enabled jobs, review queue, results validation, retries, and alerts.",
		("AI Enabled Jobs", "Open LPO Jobs", "Pending QA Reviews"),
		(
			Shortcut("AI Processing Queue", "DocType", "LPO Job", "List"),
			Shortcut("AI Results Awaiting Review", "DocType", "LPO Job", "List"),
			Shortcut("Prompt Instructions", "DocType", "LPO Job", "List"),
			Shortcut("Quality Validation", "DocType", "LPO QA Review", "List"),
			CHAT,
		),
		icon="integration",
		sequence_id=6,
	),
	PersonaWorkspace(
		"Business Workspace",
		("Lexocrates Sales & Marketing", "Sales Manager", "Lexocrates Director"),
		"CRM, opportunities, campaigns, customers, contracts, subscriptions, and revenue.",
		("Open Leads", "Total Clients", "Monthly Revenue"),
		(
			Shortcut("Leads", "DocType", "Lead", "List"),
			Shortcut("Opportunities", "DocType", "Opportunity", "List"),
			Shortcut("Campaigns", "DocType", "Campaign", "List"),
			Shortcut("Customers", "DocType", "Customer", "List"),
			Shortcut("Contracts", "DocType", "Contract", "List"),
			Shortcut("LexPack Sales", "DocType", "Subscription", "List"),
			Shortcut("Revenue", "DocType", "Sales Invoice", "List"),
			CHAT,
		),
		icon="crm",
		sequence_id=7,
	),
	PersonaWorkspace(
		"HR Workspace",
		("Lexocrates HR", "HR Manager", "Lexocrates Director"),
		"Employees, recruitment documents, performance records, training material, and policies.",
		("Active Employees",),
		(
			Shortcut("Employees", "DocType", "Employee", "List"),
			Shortcut("Recruitment", "DocType", "File", "List"),
			Shortcut("Performance", "DocType", "Employee", "List"),
			Shortcut("Training", "DocType", "File", "List"),
			Shortcut("Policies", "DocType", "File", "List"),
			CHAT,
		),
		icon="users",
		sequence_id=8,
	),
	PersonaWorkspace(
		"Compliance Workspace",
		("Lexocrates Compliance Officer", "Lexocrates Director"),
		"Compliance actions, retention evidence, incidents, audit trail, risk, and policies.",
		("Open Compliance Actions", "Overdue LPO Jobs"),
		(
			Shortcut("Compliance Tasks", "DocType", "Lexocrates Portal Audit Event", "List"),
			Shortcut("Retention", "DocType", "File", "List"),
			Shortcut("Data Requests", "DocType", "Issue", "List"),
			Shortcut("Incident Register", "DocType", "Lexocrates Portal Audit Event", "List"),
			Shortcut("Audit Trails", "DocType", "Version", "List"),
			Shortcut("Risk Register", "DocType", "Lexocrates Portal Audit Event", "List"),
			Shortcut("Policies", "DocType", "File", "List"),
			CHAT,
		),
		icon="shield",
		sequence_id=9,
	),
	PersonaWorkspace(
		"Finance Workspace",
		("Lexocrates Finance", "Accounts Manager", "Accounts User", "Lexocrates Director"),
		"Invoices, payments, subscriptions, revenue, expenses, and financial reporting.",
		("Open Invoices", "Monthly Revenue"),
		(
			Shortcut("Invoices", "DocType", "Sales Invoice", "List"),
			Shortcut("Payments", "DocType", "Payment Entry", "List"),
			Shortcut("Subscriptions", "DocType", "Subscription", "List"),
			Shortcut("Revenue", "DocType", "Sales Invoice", "List"),
			Shortcut("Expenses", "DocType", "Journal Entry", "List"),
			Shortcut("Financial Reports", "DocType", "Account", "List"),
			CHAT,
		),
		icon="accounting",
		sequence_id=10,
	),
	PersonaWorkspace(
		"System Administration Workspace",
		("System Manager",),
		"Users, roles, permissions, integrations, email, automation, health, and logs.",
		("System Errors - 24 Hours", "Chat Messages Today"),
		(
			Shortcut("Users", "DocType", "User", "List"),
			Shortcut("Roles", "DocType", "Role", "List"),
			Shortcut("Permissions", "DocType", "DocPerm", "List"),
			Shortcut("Integrations", "DocType", "Integration Request", "List"),
			Shortcut("API Access", "DocType", "User", "List"),
			Shortcut("Email", "DocType", "Email Account", "List"),
			Shortcut("Automation", "DocType", "Server Script", "List"),
			Shortcut("System Health", "DocType", "System Health Report", "List"),
			Shortcut("Logs", "DocType", "Error Log", "List"),
		),
		icon="setting-gear",
		sequence_id=11,
	),
	PersonaWorkspace(
		"Client Workspace",
		("Lexocrates Client",),
		"Your matters, work requests, and secure messages.",
		("Client Open Jobs", "Client Completed This Month"),
		(),
		icon="customer",
		sequence_id=50,
	),
)


NUMBER_CARDS = {
	"Client Open Jobs": ("client_open_jobs", "#2490ef", "LPO Job"),
	"Client Completed This Month": ("client_completed_this_month", "#29cd42", "LPO Job"),
	"My Open Jobs": ("my_open_jobs", "#2490ef", "LPO Job"),
	"My Jobs Due Today": ("my_jobs_due_today", "#f5a623", "LPO Job"),
	"My Jobs Completed Today": ("my_jobs_completed_today", "#29cd42", "LPO Job"),
	"Open LPO Jobs": ("open_lpo_jobs", "#2490ef", "LPO Job"),
	"Pending QA Reviews": ("pending_qa_reviews", "#f5a623", "LPO QA Review"),
	"Failed QA Reviews": ("failed_qa_reviews", "#ff5858", "LPO QA Review"),
	"Average QA Score": ("average_qa_score", "#29cd42", "LPO QA Review"),
	"Overdue LPO Jobs": ("overdue_lpo_jobs", "#ff5858", "LPO Job"),
	"Open Matters": ("open_matters", "#29cd42", "LPO Matter"),
	"Open Engagements": ("open_matters", "#29cd42", "LPO Matter"),
	"Open Compliance Actions": ("open_compliance_actions", "#ff5858", "LPO Compliance Log"),
	"AI Enabled Jobs": ("ai_enabled_jobs", "#7c5cff", "LPO Job"),
	"Open Leads": ("open_leads", "#2490ef", "Lead"),
	"Total Clients": ("total_clients", "#29cd42", "Customer"),
	"Monthly Revenue": ("monthly_revenue", "#29cd42", "Sales Invoice"),
	"Active Employees": ("active_employees", "#2490ef", "Employee"),
	"Open Invoices": ("open_invoices", "#f5a623", "Sales Invoice"),
	"Average TAT Hours": ("average_tat_hours", "#2490ef", "LPO Job"),
	"SLA Compliance": ("sla_compliance", "#29cd42", "LPO Job"),
	"System Errors - 24 Hours": ("system_errors_24h", "#ff5858", "Error Log"),
	"Chat Messages Today": ("chat_messages_today", "#2490ef", "Lexocrates Chat Message"),
	"Jobs Waiting In Queue": ("jobs_waiting_in_queue", "#f5a623", "LPO Job"),
	"Intakes Waiting Review": ("intakes_waiting_review", "#7c5cff", "Lexocrates Work Intake"),
	"Jobs Delivered": ("jobs_submitted_delivered", "#29cd42", "LPO Job"),
	"Active Lawyers On Projects": ("active_lawyers_on_projects", "#2490ef", "User"),
	"LexPack Sales": ("lexpack_sales", "#29cd42", "LexPack Purchase"),
	"Client Registrations Pending": ("pending_client_registrations", "#f5a623", "Lexocrates Client Registration"),
}


def ensure_persona_roles():
	for role_name in PERSONA_ROLES:
		desk_access = int(role_name != "Lexocrates Client")
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc(
				{
					"doctype": "Role",
					"role_name": role_name,
					"desk_access": desk_access,
					"is_custom": 0,
				}
			).insert(ignore_permissions=True)
		elif int(bool(frappe.db.get_value("Role", role_name, "desk_access"))) != desk_access:
			frappe.db.set_value("Role", role_name, "desk_access", desk_access, update_modified=False)
	ensure_persona_role_profiles()
	ensure_persona_permissions()


def ensure_persona_permissions():
	"""Ensure CEO, Lexocrates Director and LPO_Admin roles have Read/Select permissions on Item, Customer, Sales Invoice, Payment Entry, Account."""
	doctypes = ["Item", "Customer", "Sales Invoice", "Payment Entry", "Account", "Mode of Payment", "LexPack Purchase", "LexPack Plan"]
	roles = ["CEO", "Lexocrates Director", "LPO_Admin"]
	for dt in doctypes:
		if not frappe.db.exists("DocType", dt):
			continue
		for role in roles:
			if frappe.db.exists("Role", role) and not frappe.db.exists("Custom DocPerm", {"parent": dt, "role": role}):
				try:
					frappe.get_doc({
						"doctype": "Custom DocPerm",
						"parent": dt,
						"parenttype": "DocType",
						"parentfield": "permissions",
						"role": role,
						"read": 1,
						"select": 1,
						"export": 1,
						"write": 1 if dt in ("LexPack Purchase", "LexPack Plan") else 0,
					}).insert(ignore_permissions=True)
				except Exception:
					pass


def ensure_persona_role_profiles():
	"""Provide an assignable profile that includes the persona and its functional permissions."""
	if not frappe.db.exists("DocType", "Role Profile"):
		return
	for persona_role, base_roles in PERSONA_BASE_ROLES.items():
		profile_name = f"Lexocrates - {persona_role.removeprefix('Lexocrates ')}"
		roles = [persona_role, *base_roles]
		roles = [role for role in roles if frappe.db.exists("Role", role)]
		profile_exists = bool(frappe.db.exists("Role Profile", profile_name))
		if profile_exists:
			doc = frappe.get_doc("Role Profile", profile_name)
			if {row.role for row in doc.roles} == set(roles):
				continue
		else:
			doc = frappe.get_doc(
				{"doctype": "Role Profile", "name": profile_name, "role_profile": profile_name}
			)
		_replace_role_profile_roles(doc, roles, is_new=not profile_exists)


def _replace_role_profile_roles(doc, roles: list[str], *, is_new: bool):
	"""Update profiles without enqueueing Role Profile's migration-hostile user sync."""
	if is_new:
		doc.name = doc.role_profile
	else:
		frappe.db.delete(
			"Has Role",
			{"parent": doc.name, "parenttype": "Role Profile", "parentfield": "roles"},
		)
	doc.set("roles", [])
	for role in roles:
		doc.append("roles", {"role": role})
	doc.set_parent_in_children()
	if is_new:
		doc.db_insert()
	for row in doc.roles:
		row.db_insert()


def ensure_persona_workspaces():
	if not frappe.db.exists("DocType", "Workspace"):
		return
	ensure_persona_roles()
	_ensure_number_cards()
	ensure_client_module_profile()
	ensure_client_onboarding_block()
	ensure_ceo_monitoring_block()
	for spec in WORKSPACES:
		_upsert_workspace(spec)
	restrict_admin_only_workspaces()
	ensure_lpo_translation()
	frappe.clear_cache()


def ensure_lpo_translation():
	"""Ensure 'Public' category label in Desk sidebar is translated to 'LPO'."""
	if not frappe.db.exists("DocType", "Translation"):
		return
	translation_name = frappe.db.get_value("Translation", {"source_text": "Public", "language": "en"}, "name")
	if not translation_name:
		frappe.get_doc({
			"doctype": "Translation",
			"language": "en",
			"source_text": "Public",
			"translated_text": "LPO"
		}).insert(ignore_permissions=True)
	else:
		frappe.db.set_value("Translation", translation_name, "translated_text", "LPO")
	frappe.db.commit()


def restrict_admin_only_workspaces():
	"""Ensure Stock, Manufacturing, and Home are completely hidden/removed, and Buying, Assets, Website, Tools, ERPNext Settings, Integrations, Build, and Client Workspace are exclusively restricted to Admin roles."""
	completely_removed_titles = {
		"stock",
		"manufacturing",
		"home",
	}

	admin_only_titles = {
		"buying",
		"assets",
		"website",
		"tools",
		"erpnext settings",
		"settings",
		"integrations",
		"erpnext integration",
		"erpnext integrations",
		"build",
		"client workspace",
	}

	if not frappe.db.exists("DocType", "Workspace"):
		return

	workspaces = frappe.get_all("Workspace", fields=["name", "title", "label"])
	for ws in workspaces:
		ws_name_clean = (ws.name or "").strip().lower()
		ws_title_clean = (ws.title or ws.label or "").strip().lower()

		# Completely remove / hide Stock and Manufacturing workspaces for all users
		if ws_name_clean in completely_removed_titles or ws_title_clean in completely_removed_titles:
			doc = frappe.get_doc("Workspace", ws.name)
			doc.is_hidden = 1
			doc.public = 0
			doc.set("roles", [])
			doc.flags.ignore_permissions = True
			doc.save(ignore_permissions=True)
			continue

		# Restrict admin-only workspaces
		if ws_name_clean in admin_only_titles or ws_title_clean in admin_only_titles:
			doc = frappe.get_doc("Workspace", ws.name)
			doc.is_hidden = 0
			doc.public = 1
			target_roles = ["System Manager"]
			if frappe.db.exists("Role", "LPO_Admin"):
				target_roles.append("LPO_Admin")
			if frappe.db.exists("Role", "CEO"):
				target_roles.append("CEO")

			# Client Workspace remains accessible to Lexocrates Client website users
			if ws_name_clean == "client workspace" or ws_title_clean == "client workspace":
				if frappe.db.exists("Role", "Lexocrates Client"):
					target_roles.append("Lexocrates Client")

			doc.set("roles", [])
			for r in target_roles:
				doc.append("roles", {"role": r})

			doc.flags.ignore_permissions = True
			doc.save(ignore_permissions=True)

	frappe.db.commit()


def _ensure_number_cards():
	default_currency = frappe.db.get_default("currency") or "INR"
	for label, (function_name, color, document_type) in NUMBER_CARDS.items():
		values = {
			"doctype": "Number Card",
			"name": label,
			"label": label,
			"type": "Custom",
			"method": f"lex.persona_workspaces.{function_name}",
			"document_type": document_type,
			"is_public": 1,
			"is_standard": 1,
			"module": "Lex",
			"show_percentage_stats": 0,
			"show_full_number": 1,
			"currency": default_currency if label == "Monthly Revenue" else "",
			"color": color,
		}
		if frappe.db.exists("Number Card", label):
			doc = frappe.get_doc("Number Card", label)
			if all(doc.get(fieldname) == value for fieldname, value in values.items() if fieldname not in {"doctype", "name"}):
				continue
			doc.update(values)
			doc.save(ignore_permissions=True)
		else:
			frappe.get_doc(values).insert(ignore_permissions=True)


def _upsert_workspace(spec: PersonaWorkspace):
	valid_shortcuts = tuple(shortcut for shortcut in spec.shortcuts if _link_target_exists(shortcut))
	spec = replace(spec, shortcuts=valid_shortcuts)
	if frappe.db.exists("Workspace", spec.name):
		doc = frappe.get_doc("Workspace", spec.name)
	else:
		doc = frappe.new_doc("Workspace")
		doc.name = spec.name

	doc.update(
		{
			"title": spec.name,
			"label": spec.name,
			"module": "Lex",
			"public": 1,
			"is_hidden": 0,
			"icon": spec.icon,
			"sequence_id": spec.sequence_id,
			"parent_page": "",
		}
	)
	for table in ("roles", "number_cards", "charts", "shortcuts", "links", "quick_lists", "custom_blocks"):
		doc.set(table, [])
	for role in get_workspace_roles(spec):
		doc.append("roles", {"role": role})
	if spec.name == CLIENT_WORKSPACE:
		doc.append(
			"custom_blocks",
			{"custom_block_name": CLIENT_ONBOARDING_BLOCK, "label": CLIENT_ONBOARDING_BLOCK},
		)
	for custom_block_name in spec.custom_blocks:
		doc.append(
			"custom_blocks",
			{"custom_block_name": custom_block_name, "label": custom_block_name},
		)
	for label in spec.cards:
		doc.append("number_cards", {"label": label, "number_card_name": label})
	for shortcut in spec.shortcuts:
		row = {
			"label": shortcut.label,
			"type": shortcut.type,
			"link_to": shortcut.link_to,
		}
		if shortcut.doc_view:
			row["doc_view"] = shortcut.doc_view
		if shortcut.stats_filter:
			row["stats_filter"] = shortcut.stats_filter
		if shortcut.color:
			row["color"] = shortcut.color
		doc.append("shortcuts", row)

	if valid_shortcuts:
		doc.append(
			"links",
			{
				"type": "Card Break",
				"label": "Decision Center",
				"link_count": len(valid_shortcuts),
				"hidden": 0,
				"onboard": 0,
			},
		)
		for shortcut in valid_shortcuts:
			doc.append(
				"links",
				{
					"type": "Link",
					"label": shortcut.label,
					"link_type": shortcut.type,
					"link_to": shortcut.link_to,
					"hidden": 0,
					"onboard": 0,
				},
			)
	doc.content = json.dumps(_workspace_content(spec), separators=(",", ":"))
	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)


def get_workspace_roles(spec: PersonaWorkspace) -> tuple[str, ...]:
	"""Return functional roles plus company/system administrative access."""
	return tuple(dict.fromkeys((*spec.roles, *ADMIN_WORKSPACE_ROLES)))


def _workspace_content(spec: PersonaWorkspace) -> list[dict[str, Any]]:
	blocks: list[dict[str, Any]] = [
		{
			"id": f"{frappe.scrub(spec.name)}_header",
			"type": "header",
			"data": {
				"text": f'<span class="h4"><b>{spec.name}</b></span><p class="text-muted">{spec.subtitle}</p>',
				"col": 12,
			},
		}
	]
	if spec.name == CLIENT_WORKSPACE:
		blocks.append(
			{
				"id": "client_getting_started",
				"type": "custom_block",
				"data": {"custom_block_name": CLIENT_ONBOARDING_BLOCK, "col": 12},
			}
		)
	for custom_block_name in spec.custom_blocks:
		blocks.append(
			{
				"id": f"custom_block_{frappe.scrub(custom_block_name)}",
				"type": "custom_block",
				"data": {"custom_block_name": custom_block_name, "col": 12},
			}
		)
	for index, label in enumerate(spec.cards):
		blocks.append(
			{
				"id": f"metric_{index}_{frappe.scrub(label)}",
				"type": "number_card",
				"data": {"number_card_name": label, "col": 3},
			}
		)
	if spec.shortcuts:
		blocks.append(
			{
				"id": "decision_center_header",
				"type": "header",
				"data": {"text": '<span class="h4"><b>Decision Center</b></span>', "col": 12},
			}
		)
	for index, shortcut in enumerate(spec.shortcuts):
		blocks.append(
			{
				"id": f"shortcut_{index}_{frappe.scrub(shortcut.label)}",
				"type": "shortcut",
				"data": {"shortcut_name": shortcut.label, "col": 3},
			}
		)
	if spec.shortcuts:
		blocks.extend(
			[
				{
					"id": "workspace_links_header",
					"type": "header",
					"data": {"text": '<span class="h4"><b>Workspace Tools</b></span>', "col": 12},
				},
				{
					"id": "workspace_links_card",
					"type": "card",
					"data": {"card_name": "Decision Center", "col": 12},
				},
			]
		)
	return blocks


def _link_target_exists(shortcut: Shortcut) -> bool:
	if shortcut.type == "DocType":
		return bool(frappe.db.exists("DocType", shortcut.link_to))
	if shortcut.type == "Page":
		return bool(frappe.db.exists("Page", shortcut.link_to))
	return True


def _count(doctype: str, filters=None) -> int:
	if not frappe.db.exists("DocType", doctype) or not frappe.has_permission(doctype, "read"):
		return 0
	rows = frappe.get_list(
		doctype,
		filters=filters or {},
		fields=["count(name) as value"],
		limit_page_length=1,
	)
	return int(rows[0].value or 0) if rows else 0


def _card(value, doctype, filters=None, fieldtype="Int", route_options=None):
	return {
		"value": value,
		"fieldtype": fieldtype,
		"route": ["List", doctype],
		"route_options": route_options or filters or {},
	}


OPEN_JOB_FILTER = {"job_status": ["not in", ["Delivered", "Completed", "Cancelled"]]}


@frappe.whitelist()
def client_open_jobs(filters=None):
	return _card(_count("LPO Job", OPEN_JOB_FILTER), "LPO Job", OPEN_JOB_FILTER)


@frappe.whitelist()
def client_completed_this_month(filters=None):
	filters = {"job_status": ["in", ["Delivered", "Completed"]], "completed_on": [">=", get_first_day(nowdate())]}
	return _card(_count("LPO Job", filters), "LPO Job", filters)


@frappe.whitelist()
def my_open_jobs(filters=None):
	filters = {**OPEN_JOB_FILTER, "assigned_analyst": frappe.session.user}
	return _card(_count("LPO Job", filters), "LPO Job", filters)


@frappe.whitelist()
def my_jobs_due_today(filters=None):
	filters = {**OPEN_JOB_FILTER, "assigned_analyst": frappe.session.user, "due_date": ["between", [nowdate(), add_days(nowdate(), 1)]]}
	return _card(_count("LPO Job", filters), "LPO Job", filters)


@frappe.whitelist()
def my_jobs_completed_today(filters=None):
	filters = {"assigned_analyst": frappe.session.user, "job_status": ["in", ["Delivered", "Completed"]], "completed_on": ["between", [nowdate(), add_days(nowdate(), 1)]]}
	return _card(_count("LPO Job", filters), "LPO Job", filters)


@frappe.whitelist()
def open_lpo_jobs(filters=None):
	return _card(_count("LPO Job", OPEN_JOB_FILTER), "LPO Job", OPEN_JOB_FILTER)


@frappe.whitelist()
def pending_qa_reviews(filters=None):
	filters = {"review_status": ["not in", ["Approved", "Rejected"]]}
	return _card(_count("LPO QA Review", filters), "LPO QA Review", filters)


@frappe.whitelist()
def failed_qa_reviews(filters=None):
	filters = {"review_status": ["in", ["Changes Required", "Rejected"]]}
	return _card(_count("LPO QA Review", filters), "LPO QA Review", filters)


@frappe.whitelist()
def average_qa_score(filters=None):
	rows = frappe.get_list("LPO QA Review", filters={"score": ["is", "set"]}, fields=["score"], limit_page_length=500)
	value = round(sum(row.score for row in rows) / len(rows), 1) if rows else 0
	return _card(value, "LPO QA Review", fieldtype="Percent")


@frappe.whitelist()
def overdue_lpo_jobs(filters=None):
	filters = {**OPEN_JOB_FILTER, "due_date": ["<", str(now_datetime()).split(".")[0]]}
	return _card(_count("LPO Job", filters), "LPO Job", filters)


@frappe.whitelist()
def open_matters(filters=None):
	filters = {"status": ["not in", ["Completed", "Closed"]]}
	return _card(_count("LPO Matter", filters), "LPO Matter", filters)


open_engagements = open_matters


@frappe.whitelist()
def open_compliance_actions(filters=None):
	filters = {"status": ["not in", ["Resolved", "Closed"]]}
	return _card(_count("LPO Compliance Log", filters), "LPO Compliance Log", filters)


@frappe.whitelist()
def ai_enabled_jobs(filters=None):
	filters = {"ai_processing_allowed": 1, "job_status": ["not in", ["Delivered", "Completed", "Cancelled"]]}
	return _card(_count("LPO Job", filters), "LPO Job", filters)


@frappe.whitelist()
def open_leads(filters=None):
	filters = {"status": ["not in", ["Converted", "Do Not Contact"]]}
	return _card(_count("Lead", filters), "Lead", filters)


@frappe.whitelist()
def total_clients(filters=None):
	return _card(_count("Customer"), "Customer")


@frappe.whitelist()
def monthly_revenue(filters=None):
	filters = {"docstatus": 1, "posting_date": [">=", get_first_day(nowdate())]}
	rows = frappe.get_list("Sales Invoice", filters=filters, fields=["grand_total"], limit_page_length=1000)
	value = sum(row.grand_total or 0 for row in rows)
	return _card(value, "Sales Invoice", filters, fieldtype="Currency")


@frappe.whitelist()
def active_employees(filters=None):
	filters = {"status": "Active"}
	return _card(_count("Employee", filters), "Employee", filters)


@frappe.whitelist()
def open_invoices(filters=None):
	filters = {"docstatus": 1, "outstanding_amount": [">", 0]}
	return _card(_count("Sales Invoice", filters), "Sales Invoice", filters)


@frappe.whitelist()
def average_tat_hours(filters=None):
	rows = frappe.get_list(
		"LPO Job",
		filters={"completed_on": ["is", "set"]},
		fields=["received_at", "completed_on"],
		limit_page_length=500,
	)
	hours = [
		(row.completed_on - row.received_at).total_seconds() / 3600
		for row in rows
		if row.completed_on and row.received_at and row.completed_on >= row.received_at
	]
	return _card(round(sum(hours) / len(hours), 1) if hours else 0, "LPO Job", fieldtype="Float")


@frappe.whitelist()
def sla_compliance(filters=None):
	completed = frappe.get_list(
		"LPO Job",
		filters={"completed_on": ["is", "set"]},
		fields=["due_date", "completed_on"],
		limit_page_length=500,
	)
	value = round(100 * sum(1 for row in completed if row.completed_on <= row.due_date) / len(completed), 1) if completed else 100
	return _card(value, "LPO Job", fieldtype="Percent")


@frappe.whitelist()
def system_errors_24h(filters=None):
	filters = {"creation": [">=", add_days(now_datetime(), -1)]}
	return _card(_count("Error Log", filters), "Error Log", filters)


@frappe.whitelist()
def chat_messages_today(filters=None):
	filters = {"sent_at": [">=", nowdate()]}
	return _card(_count("Lexocrates Chat Message", filters), "Lexocrates Chat Message", filters)


@frappe.whitelist()
def jobs_waiting_in_queue(filters=None):
	filters = {"job_status": ["in", ["Draft", "Pending", "In Progress"]]}
	return _card(_count("LPO Job", filters), "LPO Job", filters)


@frappe.whitelist()
def intakes_waiting_review(filters=None):
	filters = {"status": ["not in", ["Funded", "Matter Confirmed", "Cancelled"]]}
	return _card(_count("Lexocrates Work Intake", filters), "Lexocrates Work Intake", filters)


@frappe.whitelist()
def jobs_submitted_delivered(filters=None):
	filters = {"job_status": ["in", ["Delivered", "Completed"]]}
	return _card(_count("LPO Job", filters), "LPO Job", filters)


@frappe.whitelist()
def active_lawyers_on_projects(filters=None):
	if not frappe.db.exists("DocType", "LPO Job"):
		return _card(0, "User")
	rows = frappe.db.sql("""
		SELECT COUNT(DISTINCT assigned_analyst) as cnt 
		FROM `tabLPO Job` 
		WHERE job_status IN ('Draft', 'Pending', 'In Progress', 'QA Review')
		  AND assigned_analyst IS NOT NULL AND assigned_analyst != ''
	""")
	val = int(rows[0][0]) if rows else 0
	return _card(val, "User")


@frappe.whitelist()
def lexpack_sales(filters=None):
	if not frappe.db.exists("DocType", "LexPack Purchase"):
		return _card(0, "LexPack Purchase", fieldtype="Currency")
	filters = {"status": "Paid", "created_on": [">=", get_first_day(nowdate())]}
	rows = frappe.get_list("LexPack Purchase", filters=filters, fields=["amount"], limit_page_length=1000)
	value = sum(row.amount or 0 for row in rows)
	return _card(value, "LexPack Purchase", filters, fieldtype="Currency")


@frappe.whitelist()
def pending_client_registrations(filters=None):
	filters = {"status": "Pending"}
	return _card(_count("Lexocrates Client Registration", filters), "Lexocrates Client Registration", filters)


from lex.ceo_dashboard_template import (
	CEO_MONITORING_BLOCK,
	CEO_MONITORING_HTML,
	CEO_MONITORING_SCRIPT,
	CEO_MONITORING_STYLE,
)


def ensure_ceo_monitoring_block():
	if not frappe.db.exists("DocType", "Custom HTML Block"):
		return
	if frappe.db.exists("Custom HTML Block", CEO_MONITORING_BLOCK):
		doc = frappe.get_doc("Custom HTML Block", CEO_MONITORING_BLOCK)
	else:
		doc = frappe.new_doc("Custom HTML Block")
		doc.name = CEO_MONITORING_BLOCK
	doc.html = CEO_MONITORING_HTML
	doc.script = CEO_MONITORING_SCRIPT
	doc.style = CEO_MONITORING_STYLE
	doc.private = 0
	doc.set("roles", [{"role": "CEO"}, {"role": "Lexocrates Director"}, {"role": "LPO_Admin"}, {"role": "System Manager"}])
	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)


@frappe.whitelist()
def get_ceo_dashboard_data():
	"""Return 100% REAL live database metrics for CEO Dashboard directly from MariaDB."""
	now_dt = now_datetime()
	today_str = nowdate()

	# 1. Top Metrics Strip (100% Real DB Queries)
	jobs_in_progress = frappe.db.count("LPO Job", {"job_status": ["in", ["Draft", "Pending", "In Progress", "QA Review", "Client Review"]]}) if frappe.db.exists("DocType", "LPO Job") else 0
	jobs_completed_today = frappe.db.count("LPO Job", {"job_status": ["in", ["Delivered", "Completed"]], "modified": [">=", today_str]}) if frappe.db.exists("DocType", "LPO Job") else 0
	jobs_due_today = frappe.db.count("LPO Job", {"job_status": ["not in", ["Delivered", "Completed", "Cancelled"]], "due_date": ["between", [today_str, add_days(today_str, 1)]]}) if frappe.db.exists("DocType", "LPO Job") else 0

	# Real SLA Compliance % calculation
	sla_compliance = 100.0
	avg_tat_hrs = 0.0
	if frappe.db.exists("DocType", "LPO Job"):
		completed_jobs = frappe.get_all("LPO Job", filters={"completed_on": ["is", "set"]}, fields=["creation", "completed_on", "due_date"], limit_page_length=500)
		if completed_jobs:
			on_time = sum(1 for j in completed_jobs if j.due_date and j.completed_on <= j.due_date)
			sla_compliance = round((on_time / len(completed_jobs)) * 100, 1)
			durations = [(j.completed_on - j.creation).total_seconds() / 3600.0 for j in completed_jobs if j.completed_on and j.creation and j.completed_on >= j.creation]
			if durations:
				avg_tat_hrs = round(sum(durations) / len(durations), 1)

	# SLA At Risk (Due in next 4 hours)
	sla_at_risk = frappe.db.count("LPO Job", {"job_status": ["not in", ["Delivered", "Completed", "Cancelled"]], "due_date": ["between", [str(now_dt), str(add_to_date(now_dt, hours=4))]]}) if frappe.db.exists("DocType", "LPO Job") else 0

	# AI Queue Count
	ai_queue = frappe.db.count("LPO Job", {"ai_processing_allowed": 1, "job_status": ["not in", ["Delivered", "Completed", "Cancelled"]]}) if frappe.db.exists("DocType", "LPO Job") else 0

	# Escalations Count
	escalations_count = frappe.db.count("LPO Compliance Log", {"status": ["not in", ["Resolved", "Closed"]]}) if frappe.db.exists("DocType", "LPO Compliance Log") else 0

	metrics = {
		"jobs_in_progress": jobs_in_progress,
		"jobs_completed_today": jobs_completed_today,
		"jobs_due_today": jobs_due_today,
		"sla_compliance": sla_compliance,
		"sla_at_risk": sla_at_risk,
		"avg_tat_hrs": avg_tat_hrs,
		"ai_queue": ai_queue,
		"escalations": escalations_count,
	}

	# 2. Pipeline Overview (100% Real DB Queries)
	intakes_waiting = frappe.db.count("Lexocrates Work Intake", {"status": ["not in", ["Funded", "Matter Confirmed", "Cancelled"]]}) if frappe.db.exists("DocType", "Lexocrates Work Intake") else 0
	review_count = frappe.db.count("LPO Job", {"job_status": ["in", ["QA Review", "Client Review"]]}) if frappe.db.exists("DocType", "LPO Job") else 0
	jobs_pending_qa = frappe.db.count("LPO QA Review", {"review_status": ["not in", ["Approved", "Rejected"]]}) if frappe.db.exists("DocType", "LPO QA Review") else 0
	jobs_delivered = frappe.db.count("LPO Job", {"job_status": ["in", ["Delivered", "Completed"]]}) if frappe.db.exists("DocType", "LPO Job") else 0
	open_matters = frappe.db.count("LPO Matter", {"status": ["not in", ["Completed", "Closed"]]}) if frappe.db.exists("DocType", "LPO Matter") else 0

	pipeline = {
		"intakes_waiting": intakes_waiting,
		"ai_queue_count": ai_queue,
		"in_progress_count": jobs_in_progress,
		"review_count": review_count,
		"jobs_pending_qa": jobs_pending_qa,
		"jobs_delivered": jobs_delivered,
		"open_matters": open_matters,
	}

	# 3. Priority Breakdown (Real DB Counts)
	priority_high = frappe.db.count("LPO Job", {"priority": ["in", ["High", "Urgent"]]}) if frappe.db.exists("DocType", "LPO Job") else 0
	priority_medium = frappe.db.count("LPO Job", {"priority": "Medium"}) if frappe.db.exists("DocType", "LPO Job") else 0
	priority_low = frappe.db.count("LPO Job", {"priority": ["in", ["Low", "Normal", ""]]}) if frappe.db.exists("DocType", "LPO Job") else 0

	priorities = {
		"high": priority_high,
		"medium": priority_medium,
		"low": priority_low,
		"total": priority_high + priority_medium + priority_low,
	}

	# 4. Team Workload Matrix (Real DB User Join)
	lawyers = []
	if frappe.db.exists("DocType", "LPO Job"):
		lawyers = frappe.db.sql("""
			SELECT 
				u.name as user_id,
				u.full_name,
				u.user_image,
				COUNT(CASE WHEN j.job_status IN ('Draft', 'Pending', 'In Progress', 'QA Review') THEN 1 END) as active_jobs,
				COUNT(CASE WHEN j.job_status = 'In Progress' THEN 1 END) as in_progress,
				COUNT(CASE WHEN j.job_status = 'QA Review' THEN 1 END) as review,
				COUNT(CASE WHEN j.job_status IN ('Delivered', 'Completed') THEN 1 END) as completed_jobs
			FROM `tabUser` u
			INNER JOIN `tabHas Role` hr ON hr.parent = u.name
			LEFT JOIN `tabLPO Job` j ON (j.assigned_analyst = u.name OR j.qa_reviewer = u.name)
			WHERE u.enabled = 1 
			  AND hr.role IN ('Junior Legal Associate', 'Senior Legal Associate', 'LPO_Analyst', 'LPO_Manager', 'Lexocrates QA Manager')
			GROUP BY u.name, u.full_name, u.user_image
			ORDER BY active_jobs DESC, completed_jobs DESC
			LIMIT 15
		""", as_dict=True)

	# 5. Bottlenecks (Real DB Queries)
	bottlenecks = [
		{"stage": "AI Queue", "pending": ai_queue, "impact": "High" if ai_queue > 10 else "Low"},
		{"stage": "Senior Review", "pending": review_count, "impact": "High" if review_count > 10 else "Medium"},
		{"stage": "QA Review", "pending": jobs_pending_qa, "impact": "Medium" if jobs_pending_qa > 5 else "Low"},
		{"stage": "Client Delivery", "pending": jobs_delivered, "impact": "Low"},
	]

	# 6. Real Escalations List
	escalations = []
	if frappe.db.exists("DocType", "LPO Compliance Log"):
		esc_rows = frappe.get_all(
			"LPO Compliance Log",
			filters={"status": ["not in", ["Closed"]]},
			fields=["name", "compliance_type", "job", "engagement", "status"],
			order_by="creation desc",
			limit_page_length=5,
		)
		for r in esc_rows:
			escalations.append({
				"id": r.name,
				"type": r.compliance_type or "Compliance",
				"reference": r.job or r.engagement or "-",
				"status": r.status or "Open",
			})

	# 7. Financials / LexPack (Real DB Aggregation)
	total_clients = frappe.db.count("Customer") if frappe.db.exists("DocType", "Customer") else 0
	pending_registrations = frappe.db.count("Lexocrates Client Registration", {"status": "Pending"}) if frappe.db.exists("DocType", "Lexocrates Client Registration") else 0
	active_plans = frappe.db.count("LexPack Plan", {"status": "Active"}) if frappe.db.exists("DocType", "LexPack Plan") else 0
	purchases_count = frappe.db.count("LexPack Purchase", {"status": "Paid"}) if frappe.db.exists("DocType", "LexPack Purchase") else 0
	total_revenue = frappe.db.sql("SELECT COALESCE(SUM(amount), 0) FROM `tabLexPack Purchase` WHERE status='Paid'")[0][0] if frappe.db.exists("DocType", "LexPack Purchase") else 0

	financials = {
		"total_clients": total_clients,
		"pending_registrations": pending_registrations,
		"active_plans": active_plans,
		"purchases_count": purchases_count,
		"total_revenue": total_revenue,
	}

	return {
		"metrics": metrics,
		"pipeline": pipeline,
		"priorities": priorities,
		"lawyers": lawyers,
		"bottlenecks": bottlenecks,
		"escalations": escalations,
		"financials": financials,
	}
