from __future__ import annotations

import frappe
from frappe import _

from lex.client_access import get_portal_user


CLIENT_WORKSPACE = "Client Workspace"
CLIENT_ONBOARDING_BLOCK = "Lexocrates Client Getting Started"
CLIENT_MODULE_PROFILE = "Lexocrates Client Only"


CLIENT_ONBOARDING_HTML = """
<section class="lex-client-start" aria-live="polite">
	<div class="lex-loading">
		<span class="lex-spinner" aria-hidden="true"></span>
		<span>Preparing your Client Workspace...</span>
	</div>
</section>
""".strip()


CLIENT_ONBOARDING_SCRIPT = r"""
const panel = root_element.querySelector(".lex-client-start");

const escapeHtml = (value) => String(value ?? "")
	.replaceAll("&", "&amp;")
	.replaceAll("<", "&lt;")
	.replaceAll(">", "&gt;")
	.replaceAll('"', "&quot;")
	.replaceAll("'", "&#039;");

const actionLabels = {
	"new-matter": __("Create first matter"),
	"new-job": __("Submit work request"),
	"messages": __("Open messages"),
	"team": __("Invite team member"),
	"my-matters": __("View my matters"),
	"billing": __("View billing"),
	"lexpack": __("View LexPack"),
};

function actionButton(action, primary = false) {
	if (!action) return "";
	return `<button class="btn ${primary ? "btn-primary" : "btn-default"} btn-sm" data-action="${escapeHtml(action)}">${escapeHtml(actionLabels[action] || __("Open"))}</button>`;
}

function render(data) {
	if (!data.available) {
		panel.innerHTML = `<div class="lex-error"><strong>${escapeHtml(__("Client onboarding indicator"))}</strong><span>${escapeHtml(data.message || __("This indicator is shown to active Client accounts."))}</span></div>`;
		return;
	}
	const steps = data.steps || [];
	const nextStep = steps.find((step) => !step.complete && step.action);
	panel.innerHTML = `
		<div class="lex-start-head">
			<div>
				<div class="lex-eyebrow">${escapeHtml(__("GETTING STARTED"))}</div>
				<h2>${escapeHtml(__("Welcome, {0}", [data.first_name || data.full_name]))}</h2>
				<p>${escapeHtml(data.organization)} · ${escapeHtml(data.portal_role)}</p>
			</div>
			<div class="lex-progress-copy">
				<strong>${escapeHtml(data.completed_steps)}/${escapeHtml(data.total_steps)}</strong>
				<span>${escapeHtml(__("steps complete"))}</span>
			</div>
		</div>
		<div class="lex-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${escapeHtml(data.progress)}">
			<span style="width:${escapeHtml(data.progress)}%"></span>
		</div>
		<div class="lex-start-body">
			<div class="lex-next">
				<span class="lex-next-label">${escapeHtml(nextStep ? __("RECOMMENDED NEXT STEP") : __("WORKSPACE READY"))}</span>
				<h3>${escapeHtml(nextStep ? nextStep.title : __("Your workspace setup is complete"))}</h3>
				<p>${escapeHtml(nextStep ? nextStep.description : __("Use the shortcuts below to manage matters, requests and secure conversations."))}</p>
				${nextStep ? actionButton(nextStep.action, true) : actionButton("new-matter", true)}
			</div>
			<div class="lex-checklist">
				${steps.map((step) => `
					<div class="lex-step ${step.complete ? "is-complete" : ""}">
						<span class="lex-step-icon" aria-hidden="true">${step.complete ? "✓" : escapeHtml(step.number)}</span>
						<div class="lex-step-copy">
							<strong>${escapeHtml(step.title)}</strong>
							<span>${escapeHtml(step.description)}</span>
						</div>
						${!step.complete ? actionButton(step.action) : `<span class="lex-done">${escapeHtml(__("Done"))}</span>`}
					</div>
				`).join("")}
			</div>
		</div>
		<div class="lex-quick-actions">
			${(data.quick_actions || []).map((item) => `
				<button data-action="${escapeHtml(item.action)}"><span>${escapeHtml(item.icon)}</span><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.description)}</small></button>
			`).join("")}
		</div>
	`;
}

function showError(error) {
	const message = error?.message || __("The onboarding status could not be loaded.");
	panel.innerHTML = `<div class="lex-error"><strong>${escapeHtml(__("Workspace setup is unavailable"))}</strong><span>${escapeHtml(message)}</span><button class="btn btn-default btn-sm" data-action="reload">${escapeHtml(__("Try again"))}</button></div>`;
}

async function refresh() {
	try {
		const response = await frappe.call({
			method: "lex.client_workspace.get_client_workspace_onboarding",
		});
		render(response.message);
	} catch (error) {
		showError(error);
	}
}

function openMatterDialog() {
	const dialog = new frappe.ui.Dialog({
		title: __("Create a Matter"),
		fields: [
			{ fieldname: "matter_title", fieldtype: "Data", label: __("Matter Name"), reqd: 1 },
			{ fieldname: "practice_area", fieldtype: "Select", label: __("Practice Area"), options: "Corporate & Commercial\nContract Review\nLitigation Support\nEmployment\nIntellectual Property\nRegulatory & Compliance\nDue Diligence\nLegal Research\nOther", reqd: 1 },
			{ fieldname: "jurisdictions", fieldtype: "Small Text", label: __("Jurisdictions"), reqd: 1 },
			{ fieldname: "billing_method", fieldtype: "Select", label: __("Billing Method"), options: "Quoted Price\nLexPack", default: "Quoted Price", reqd: 1 },
			{ fieldname: "description", fieldtype: "Text Editor", label: __("Scope and Instructions") },
		],
		primary_action_label: __("Create Matter"),
		primary_action: async (values) => {
			const response = await frappe.call({ method: "lex.client_portal.create_matter", args: values, freeze: true, freeze_message: __("Creating matter...") });
			dialog.hide();
			frappe.show_alert({ message: __("Matter {0} created", [response.message.name]), indicator: "green" });
			await refresh();
			frappe.set_route("Form", "LPO Matter", response.message.name);
		},
	});
	dialog.show();
}

function openInviteDialog() {
	const dialog = new frappe.ui.Dialog({
		title: __("Invite a Team Member"),
		fields: [
			{ fieldname: "invitee_name", fieldtype: "Data", label: __("Full Name"), reqd: 1 },
			{ fieldname: "invitee_email", fieldtype: "Data", label: __("Email"), options: "Email", reqd: 1 },
			{ fieldname: "designation", fieldtype: "Data", label: __("Designation") },
			{ fieldname: "portal_role", fieldtype: "Select", label: __("Client Role"), options: "Partner / General Counsel\nLegal User\nOperations User\nFinance User\nProcurement User\nCompliance User\nRead-Only User", default: "Legal User", reqd: 1 },
		],
		primary_action_label: __("Send Invitation"),
		primary_action: async (values) => {
			await frappe.call({ method: "lex.portal_management.invite_portal_user", args: values, freeze: true, freeze_message: __("Sending invitation...") });
			dialog.hide();
			frappe.show_alert({ message: __("Invitation sent"), indicator: "green" });
			await refresh();
		},
	});
	dialog.show();
}

function openWorkRequestDialog() {
	const dialog = new frappe.ui.Dialog({
		title: __("Submit a Work Request"),
		fields: [
			{ fieldname: "engagement", fieldtype: "Link", options: "LPO Matter", label: __("Matter"), reqd: 1 },
			{ fieldname: "job_title", fieldtype: "Data", label: __("Request Title"), reqd: 1 },
			{ fieldname: "job_type", fieldtype: "Select", label: __("Work Type"), options: "Contract Review\nLegal Research\nDocument Review\nDue Diligence\nCompliance Review\nLitigation Support\nDrafting\nSummarization\nOther", reqd: 1 },
			{ fieldname: "priority", fieldtype: "Select", label: __("Priority"), options: "Low\nMedium\nHigh\nUrgent", default: "Medium", reqd: 1 },
			{ fieldname: "due_date", fieldtype: "Datetime", label: __("Requested Due Date"), reqd: 1 },
			{ fieldname: "task_description", fieldtype: "Text Editor", label: __("Instructions"), reqd: 1 },
		],
		primary_action_label: __("Submit Request"),
		primary_action: async (values) => {
			const response = await frappe.call({ method: "lex.client_portal.create_work_request", args: values, freeze: true, freeze_message: __("Submitting work request...") });
			dialog.hide();
			frappe.show_alert({ message: __("Work request {0} submitted", [response.message.name]), indicator: "green" });
			await refresh();
			frappe.set_route("Form", "LPO Job", response.message.name);
		},
	});
	dialog.show();
}

panel.addEventListener("click", (event) => {
	const button = event.target.closest("[data-action]");
	if (!button) return;
	const action = button.dataset.action;
	if (action === "reload") refresh();
	if (action === "new-matter") openMatterDialog();
	if (action === "new-job") openWorkRequestDialog();
	if (action === "my-matters") frappe.set_route("List", "LPO Matter");
	if (action === "messages") frappe.set_route("lexocrates-chat");
	if (action === "team") openInviteDialog();
	if (action === "billing") frappe.set_route("List", "Sales Invoice");
	if (action === "lexpack") frappe.set_route("List", "Lexocrates Client Wallet");
});

refresh();
""".strip()


CLIENT_ONBOARDING_STYLE = """
:host { display: block; color: var(--text-color); }
* { box-sizing: border-box; }
.lex-client-start { border: 1px solid var(--border-color); border-radius: var(--border-radius-md); background: var(--card-bg); overflow: hidden; box-shadow: var(--card-shadow); }
.lex-loading, .lex-error { min-height: 180px; display: flex; align-items: center; justify-content: center; gap: 10px; padding: 24px; color: var(--text-muted); }
.lex-error { flex-direction: column; text-align: center; }
.lex-error strong { color: var(--text-color); font-size: var(--text-lg); }
.lex-spinner { width: 18px; height: 18px; border: 2px solid var(--border-color); border-top-color: var(--primary); border-radius: 50%; animation: lex-spin .8s linear infinite; }
@keyframes lex-spin { to { transform: rotate(360deg); } }
.lex-start-head { display: flex; justify-content: space-between; gap: 24px; align-items: center; padding: 22px 24px 16px; }
.lex-eyebrow, .lex-next-label { color: var(--text-muted); font-size: var(--text-xs); font-weight: 700; letter-spacing: .08em; }
.lex-start-head h2 { margin: 4px 0; font-size: 22px; line-height: 1.25; }
.lex-start-head p { margin: 0; color: var(--text-muted); }
.lex-progress-copy { min-width: 100px; text-align: right; }
.lex-progress-copy strong { display: block; color: var(--primary); font-size: 20px; }
.lex-progress-copy span { color: var(--text-muted); font-size: var(--text-xs); }
.lex-progress { height: 5px; background: var(--bg-light-gray); }
.lex-progress span { display: block; height: 100%; background: var(--primary); transition: width .25s ease; }
.lex-start-body { display: grid; grid-template-columns: minmax(240px, .85fr) minmax(360px, 1.4fr); border-top: 1px solid var(--border-color); }
.lex-next { padding: 24px; background: var(--subtle-fg); border-right: 1px solid var(--border-color); }
.lex-next h3 { margin: 8px 0; font-size: var(--text-xl); }
.lex-next p { color: var(--text-muted); margin: 0 0 18px; line-height: 1.55; }
.lex-checklist { padding: 10px 20px; }
.lex-step { display: grid; grid-template-columns: 32px minmax(0, 1fr) auto; gap: 12px; align-items: center; padding: 12px 4px; border-bottom: 1px solid var(--border-color); }
.lex-step:last-child { border-bottom: 0; }
.lex-step-icon { width: 26px; height: 26px; display: grid; place-items: center; border: 1px solid var(--border-color); border-radius: 50%; color: var(--text-muted); font-size: var(--text-sm); font-weight: 700; }
.lex-step.is-complete .lex-step-icon { color: var(--green-700); background: var(--green-100); border-color: var(--green-200); }
.lex-step-copy { min-width: 0; }
.lex-step-copy strong, .lex-step-copy span { display: block; }
.lex-step-copy strong { font-size: var(--text-md); }
.lex-step-copy span { color: var(--text-muted); font-size: var(--text-sm); margin-top: 2px; }
.lex-done { color: var(--green-700); font-size: var(--text-sm); font-weight: 600; }
.lex-quick-actions { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0; border-top: 1px solid var(--border-color); }
.lex-quick-actions button { display: grid; grid-template-columns: 32px 1fr; column-gap: 10px; text-align: left; padding: 16px 18px; border: 0; border-right: 1px solid var(--border-color); background: transparent; color: var(--text-color); cursor: pointer; }
.lex-quick-actions button:last-child { border-right: 0; }
.lex-quick-actions button:hover { background: var(--bg-light-gray); }
.lex-quick-actions button > span { grid-row: 1 / span 2; width: 30px; height: 30px; display: grid; place-items: center; border-radius: var(--border-radius); background: var(--control-bg); color: var(--primary); font-size: 18px; }
.lex-quick-actions strong { font-size: var(--text-md); }
.lex-quick-actions small { color: var(--text-muted); margin-top: 2px; }
@media (max-width: 900px) {
	.lex-start-body { grid-template-columns: 1fr; }
	.lex-next { border-right: 0; border-bottom: 1px solid var(--border-color); }
	.lex-quick-actions { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 560px) {
	.lex-start-head { align-items: flex-start; padding: 18px; }
	.lex-progress-copy { min-width: auto; }
	.lex-next, .lex-checklist { padding: 16px; }
	.lex-step { grid-template-columns: 30px minmax(0, 1fr); }
	.lex-step .btn, .lex-done { grid-column: 2; justify-self: start; }
	.lex-quick-actions { grid-template-columns: 1fr; }
	.lex-quick-actions button { border-right: 0; border-bottom: 1px solid var(--border-color); }
}
""".strip()


@frappe.whitelist()
def get_client_workspace_onboarding():
	portal_user = get_portal_user()
	if not portal_user:
		return {
			"available": False,
			"message": _("This indicator is personalized after an active Client account signs in."),
		}

	customer_fields = ["customer_name"]
	if frappe.get_meta("Customer").has_field("custom_lexocrates_client_id"):
		customer_fields.append("custom_lexocrates_client_id")
	client = frappe.db.get_value("Customer", portal_user.client, customer_fields, as_dict=True)
	if not client:
		frappe.throw(_("The Client organization linked to this account is unavailable."), frappe.PermissionError)

	matter_count = _permitted_count("LPO Matter")
	job_count = _permitted_count("LPO Job")
	message_count = _permitted_count("Lexocrates Chat Message", {"sender": frappe.session.user})
	team_count = frappe.db.count(
		"Lexocrates Portal User",
		{"client": portal_user.client, "account_status": "Active"},
	)

	steps = [
		{
			"title": _("Organization connected"),
			"description": _("Your account is securely linked to {0}.").format(client.customer_name),
			"complete": True,
			"action": None,
		},
	]
	if portal_user.matter_access_scope != "No Matter Access":
		steps.append(
			{
				"title": _("Create your first matter"),
				"description": _("Add the legal matter, jurisdiction and working scope."),
				"complete": matter_count > 0,
				"action": "new-matter" if portal_user.can_create_matters else "my-matters",
			}
		)
		steps.append(
			{
				"title": _("Submit the first work request"),
				"description": _("Send instructions and a due date to the Lexocrates operations team."),
				"complete": job_count > 0,
				"action": "new-job" if portal_user.can_create_matters and matter_count else "my-matters",
			}
		)
	if portal_user.user_management_authority:
		steps.append(
			{
				"title": _("Invite your internal team"),
				"description": _("Give colleagues only the client role and access they require."),
				"complete": team_count > 1,
				"action": "team",
			}
		)
	steps.append(
		{
			"title": _("Start a secure conversation"),
			"description": _("Use record-linked messaging for questions, updates and approvals."),
			"complete": message_count > 0,
			"action": "messages",
		}
	)

	for index, step in enumerate(steps, start=1):
		step["number"] = index
	completed_steps = sum(bool(step["complete"]) for step in steps)
	total_steps = len(steps)
	full_name = frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user
	quick_actions = _client_quick_actions(portal_user, matter_count)

	return {
		"available": True,
		"full_name": full_name,
		"first_name": full_name.split(" ", 1)[0],
		"organization": client.customer_name,
		"client_id": client.get("custom_lexocrates_client_id"),
		"portal_role": portal_user.portal_role,
		"completed_steps": completed_steps,
		"total_steps": total_steps,
		"progress": round((completed_steps / total_steps) * 100) if total_steps else 100,
		"steps": steps,
		"quick_actions": quick_actions,
	}


def _permitted_count(doctype: str, filters: dict | None = None) -> int:
	if not frappe.db.exists("DocType", doctype) or not frappe.has_permission(doctype, "read"):
		return 0
	rows = frappe.get_list(
		doctype,
		filters=filters or {},
		fields=["count(name) as value"],
		limit_page_length=1,
	)
	return int(rows[0].value or 0) if rows else 0


def _client_quick_actions(portal_user, matter_count: int) -> list[dict]:
	actions = []
	if portal_user.matter_access_scope != "No Matter Access":
		actions.append(
			{"action": "my-matters", "icon": "▤", "label": _("My Matters"), "description": _("Status and activity")}
		)
	if portal_user.can_create_matters:
		actions.insert(
			0,
			{"action": "new-matter", "icon": "+", "label": _("New Matter"), "description": _("Open a legal matter")},
		)
		if matter_count:
			actions.insert(
				1,
				{"action": "new-job", "icon": "↗", "label": _("Work Request"), "description": _("Send instructions to the LPO team")},
			)
	if portal_user.billing_access and portal_user.portal_role in {"Finance User", "Procurement User"}:
		actions.append(
			{"action": "billing", "icon": "₹", "label": _("Billing"), "description": _("Client invoices and payments")}
		)
	if portal_user.lexpack_view_access and portal_user.portal_role in {"Finance User", "Procurement User"}:
		actions.append(
			{"action": "lexpack", "icon": "◇", "label": _("LexPack"), "description": _("Balance and transactions")}
		)
	actions.append(
		{"action": "messages", "icon": "◌", "label": _("Messages"), "description": _("Secure matter conversations")}
	)
	return actions


def ensure_client_onboarding_block():
	if not frappe.db.exists("DocType", "Custom HTML Block"):
		return
	if frappe.db.exists("Custom HTML Block", CLIENT_ONBOARDING_BLOCK):
		doc = frappe.get_doc("Custom HTML Block", CLIENT_ONBOARDING_BLOCK)
	else:
		doc = frappe.new_doc("Custom HTML Block")
		doc.name = CLIENT_ONBOARDING_BLOCK
	doc.html = CLIENT_ONBOARDING_HTML
	doc.script = CLIENT_ONBOARDING_SCRIPT
	doc.style = CLIENT_ONBOARDING_STYLE
	doc.private = 0
	doc.set("roles", [{"role": "Lexocrates Client"}])
	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)


def ensure_client_module_profile():
	"""Hide internal ERPNext modules from scoped Client Workspace users."""
	if not frappe.db.exists("DocType", "Module Profile"):
		return
	from frappe.config import get_modules_from_all_apps

	blocked_modules = sorted(
		{
			row.get("module_name")
			for row in get_modules_from_all_apps()
			if row.get("module_name") and row.get("module_name") != "Lex"
		}
	)
	if frappe.db.exists("Module Profile", CLIENT_MODULE_PROFILE):
		doc = frappe.get_doc("Module Profile", CLIENT_MODULE_PROFILE)
		if {row.module for row in doc.block_modules} == set(blocked_modules):
			return
	else:
		doc = frappe.new_doc("Module Profile")
		doc.module_profile_name = CLIENT_MODULE_PROFILE
	doc.set("block_modules", [{"module": module} for module in blocked_modules])
	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)


def migrate_client_users_to_portal():
	"""Keep mapped clients as Website Users landing in the native client portal."""
	if not frappe.db.exists("DocType", "Lexocrates Portal User"):
		return
	for name in frappe.get_all("Lexocrates Portal User", pluck="name", limit_page_length=0):
		frappe.get_doc("Lexocrates Portal User", name)._synchronize_user()


def migrate_client_users_to_workspace():
	"""Backward-compatible alias for older deployments."""
	migrate_client_users_to_portal()


def ensure_client_customer_permission(user: str, client: str):
	"""Apply one organization boundary to standard ERPNext records linked to Customer."""
	existing = frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": "Customer"},
		fields=["name", "for_value"],
		limit_page_length=0,
	)
	for row in existing:
		if row.for_value != client:
			frappe.delete_doc("User Permission", row.name, ignore_permissions=True, force=True)
	permission_name = frappe.db.get_value(
		"User Permission",
		{"user": user, "allow": "Customer", "for_value": client},
		"name",
	)
	if permission_name:
		frappe.db.set_value(
			"User Permission",
			permission_name,
			{"apply_to_all_doctypes": 1, "is_default": 1},
			update_modified=False,
		)
	else:
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": user,
				"allow": "Customer",
				"for_value": client,
				"apply_to_all_doctypes": 1,
				"is_default": 1,
			}
		).insert(ignore_permissions=True)
	frappe.clear_cache(user=user)
