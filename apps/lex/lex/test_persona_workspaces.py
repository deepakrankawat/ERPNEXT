from __future__ import annotations

import json

import frappe
from frappe.desk.desktop import get_workspace_sidebar_items
from frappe.tests.utils import FrappeTestCase

from lex import client_workspace, install, persona_workspaces


class TestPersonaWorkspaces(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		persona_workspaces.ensure_persona_workspaces()

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_workspace_definitions_have_valid_roles_cards_and_shortcuts(self):
		self.assertEqual(len(persona_workspaces.WORKSPACES), 12)
		for spec in persona_workspaces.WORKSPACES:
			workspace = frappe.get_doc("Workspace", spec.name)
			self.assertTrue(workspace.public, spec.name)
			self.assertFalse(workspace.is_hidden, spec.name)
			self.assertEqual(
				{row.role for row in workspace.roles},
				set(persona_workspaces.get_workspace_roles(spec)),
				spec.name,
			)
			self.assertEqual(
				{row.number_card_name for row in workspace.number_cards},
				set(spec.cards),
				spec.name,
			)
			blocks = json.loads(workspace.content)
			self.assertTrue(blocks and blocks[0]["type"] == "header", spec.name)
			for shortcut in workspace.shortcuts:
				self.assertTrue(
					frappe.db.exists(shortcut.type, shortcut.link_to),
					f"{spec.name}: missing {shortcut.type} {shortcut.link_to}",
				)

	def test_client_workspace_uses_onboarding_block_for_client_role(self):
		workspace = frappe.get_doc("Workspace", client_workspace.CLIENT_WORKSPACE)
		self.assertFalse(workspace.shortcuts)
		self.assertFalse(workspace.links)
		self.assertEqual(
			[row.custom_block_name for row in workspace.custom_blocks],
			[client_workspace.CLIENT_ONBOARDING_BLOCK],
		)
		block = frappe.get_doc("Custom HTML Block", client_workspace.CLIENT_ONBOARDING_BLOCK)
		self.assertIn("get_client_workspace_onboarding", block.script)
		self.assertEqual({row.role for row in block.roles}, {"Lexocrates Client"})

	def test_client_onboarding_is_scoped_to_logged_in_website_user(self):
		client = _make_client("Onboarding Client")
		user = _make_user("Lexocrates Client")
		_make_portal_user(user.name, client)
		frappe.set_user(user.name)
		result = client_workspace.get_client_workspace_onboarding()
		self.assertTrue(result["available"])
		self.assertEqual(result["organization"], client)
		self.assertGreaterEqual(result["completed_steps"], 1)
		self.assertGreaterEqual(result["total_steps"], 3)
		self.assertEqual(result["steps"][0]["title"], "Organization connected")
		self.assertEqual(frappe.db.get_value("User", user.name, "user_type"), "Website User")
		self.assertFalse(frappe.db.get_value("Role", "Lexocrates Client", "desk_access"))

	def test_role_profiles_include_persona_and_base_roles(self):
		for persona, base_roles in persona_workspaces.PERSONA_BASE_ROLES.items():
			profile_name = f"Lexocrates - {persona.removeprefix('Lexocrates ')}"
			profile = frappe.get_doc("Role Profile", profile_name)
			self.assertEqual(
				{row.role for row in profile.roles},
				{persona, *base_roles},
				profile_name,
			)

	def test_personas_only_receive_matching_custom_workspaces(self):
		custom_names = {spec.name for spec in persona_workspaces.WORKSPACES}
		for persona, base_roles in persona_workspaces.PERSONA_BASE_ROLES.items():
			if persona == "Lexocrates Client" or persona in persona_workspaces.ADMIN_WORKSPACE_ROLES:
				continue
			user = _make_user(persona, *base_roles, user_type="System User")
			frappe.set_user(user.name)
			visible = {
				page.name
				for page in get_workspace_sidebar_items()["pages"]
				if page.name in custom_names
			}
			effective_roles = {persona, *base_roles, "All", "Desk User"}
			expected = {
				spec.name
				for spec in persona_workspaces.WORKSPACES
				if effective_roles.intersection(persona_workspaces.get_workspace_roles(spec))
			}
			self.assertEqual(visible, expected, persona)

	def test_administrative_roles_receive_all_custom_workspaces(self):
		custom_names = {spec.name for spec in persona_workspaces.WORKSPACES}
		for admin_role in persona_workspaces.ADMIN_WORKSPACE_ROLES:
			base_roles = persona_workspaces.PERSONA_BASE_ROLES.get(admin_role, ())
			user = _make_user(admin_role, *base_roles, user_type="System User")
			frappe.set_user(user.name)
			visible = {
				page.name
				for page in get_workspace_sidebar_items()["pages"]
				if page.name in custom_names
			}
			self.assertEqual(visible, custom_names, admin_role)

	def test_unassigned_desk_user_receives_no_custom_workspace(self):
		custom_names = {spec.name for spec in persona_workspaces.WORKSPACES}
		user = _make_user(user_type="System User")
		frappe.set_user(user.name)
		visible = {
			page.name
			for page in get_workspace_sidebar_items()["pages"]
			if page.name in custom_names
		}
		self.assertFalse(visible)

	def test_live_metrics_accept_browser_filters_and_return_routes(self):
		for label, (method_name, _color, document_type) in persona_workspaces.NUMBER_CARDS.items():
			card = frappe.get_doc("Number Card", label)
			self.assertEqual(card.type, "Custom", label)
			self.assertEqual(card.document_type, document_type, label)
			result = getattr(persona_workspaces, method_name)(filters=[])
			self.assertIn("value", result, label)
			self.assertEqual(result["route"], ["List", document_type], label)

	def test_home_workspace_starts_with_lpo_application_actions(self):
		install.ensure_home_workspace_actions()
		install.ensure_home_workspace_actions()
		workspace = frappe.get_doc("Workspace", "Home")
		blocks = json.loads(workspace.content)
		self.assertEqual(
			[block["id"] for block in blocks[:3]],
			[
				"lexocrates_legal_operations_header",
				"lexocrates_lpo_operation_shortcut",
				"lexocrates_lex_shortcut",
			],
		)
		shortcuts = {row.label: row for row in workspace.shortcuts}
		self.assertEqual(shortcuts["LPO Operation"].url, "/app/lpo-operation")
		self.assertEqual(shortcuts["Lex"].url, "/app/lpo-msg")
		self.assertEqual(sum(row.label == "LPO Operation" for row in workspace.shortcuts), 1)
		self.assertEqual(sum(row.label == "Lex" for row in workspace.shortcuts), 1)


def _make_client(label: str) -> str:
	suffix = frappe.generate_hash(length=8).lower()
	return frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": f"{label} {suffix}",
			"customer_type": "Company",
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
			"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
		}
	).insert(ignore_permissions=True).name


def _make_user(*roles: str, user_type: str = "Website User"):
	email = f"test-persona-{frappe.generate_hash(length=10).lower()}@example.invalid"
	prev_flag = getattr(frappe.flags, "in_import", False)
	frappe.flags.in_import = True
	try:
		return frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Persona",
				"last_name": "Test",
				"enabled": 1,
				"user_type": user_type,
				"send_welcome_email": 0,
				"roles": [{"role": role} for role in roles],
			}
		).insert(ignore_permissions=True)
	finally:
		frappe.flags.in_import = prev_flag


def _make_portal_user(user: str, client: str):
	return frappe.get_doc(
		{
			"doctype": "Lexocrates Portal User",
			"user": user,
			"client": client,
			"portal_role": "Client Administrator",
			"account_status": "Active",
			"matter_access_scope": "All Client Matters",
		}
	).insert(ignore_permissions=True)
