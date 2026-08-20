from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.model.naming import make_autoname


CLIENT_CUSTOM_FIELDS = {
	"Customer": [
		{
			"fieldname": "custom_lexocrates_client_id",
			"label": "Lexocrates Client ID",
			"fieldtype": "Data",
			"insert_after": "customer_name",
			"read_only": 1,
			"unique": 1,
			"in_standard_filter": 1,
		},
		{
			"fieldname": "custom_organization_type",
			"label": "Organization Type",
			"fieldtype": "Select",
			"options": "Law Firm\nCorporate Legal Department\nBank / Financial Institution\nInsurance Company\nAccounting Firm\nConsulting Firm\nOther",
			"insert_after": "customer_type",
		},
		{
			"fieldname": "custom_state_province",
			"label": "State / Province",
			"fieldtype": "Data",
			"insert_after": "custom_organization_type",
		},
		{
			"fieldname": "custom_primary_jurisdiction",
			"label": "Primary Jurisdiction",
			"fieldtype": "Data",
			"insert_after": "custom_state_province",
		},
		{
			"fieldname": "custom_industry_practice_type",
			"label": "Industry / Practice Type",
			"fieldtype": "Data",
			"insert_after": "custom_primary_jurisdiction",
		},
		{
			"fieldname": "custom_tax_information",
			"label": "Tax / VAT / GST Information",
			"fieldtype": "Small Text",
			"insert_after": "tax_id",
		},
	],
	"File": [
		{
			"fieldname": "custom_lex_scan_status",
			"label": "Lexocrates Scan Status",
			"fieldtype": "Select",
			"options": "Pending\nScanning\nClean\nInfected\nRejected\nScanner Unavailable",
			"default": "Pending",
			"read_only": 1,
			"insert_after": "is_private",
		},
		{
			"fieldname": "custom_lex_checksum",
			"label": "SHA-256 Checksum",
			"fieldtype": "Data",
			"read_only": 1,
			"insert_after": "custom_lex_scan_status",
		},
		{
			"fieldname": "custom_lex_scanned_on",
			"label": "Scanned On",
			"fieldtype": "Datetime",
			"read_only": 1,
			"insert_after": "custom_lex_checksum",
		},
		{
			"fieldname": "custom_lex_scanner_engine",
			"label": "Scanner Engine",
			"fieldtype": "Data",
			"read_only": 1,
			"insert_after": "custom_lex_scanned_on",
		},
		{
			"fieldname": "custom_lex_quarantine_reason",
			"label": "Quarantine Reason",
			"fieldtype": "Small Text",
			"read_only": 1,
			"insert_after": "custom_lex_scanner_engine",
		},
	],
}


def ensure_client_schema():
	if not frappe.db.exists("DocType", "Customer"):
		return
	create_custom_fields(CLIENT_CUSTOM_FIELDS, update=True)
	_assign_missing_client_ids()
	_create_missing_wallets()


def new_client_id() -> str:
	return make_autoname("CLI-.YYYY.-.#####")


def _assign_missing_client_ids():
	if not frappe.db.has_column("Customer", "custom_lexocrates_client_id"):
		return
	customers = frappe.get_all(
		"Customer",
		filters={"custom_lexocrates_client_id": ["is", "not set"]},
		pluck="name",
		limit_page_length=0,
	)
	for customer in customers:
		# Assign only organizations already participating in the Lexocrates domain.
		if _is_lexocrates_client(customer):
			frappe.db.set_value(
				"Customer", customer, "custom_lexocrates_client_id", new_client_id(), update_modified=False
			)


def _is_lexocrates_client(customer: str) -> bool:
	for doctype, fieldname in (
		("Lexocrates Portal User", "client"),
		("LPO Matter", "customer"),
	):
		if frappe.db.exists("DocType", doctype) and frappe.db.exists(doctype, {fieldname: customer}):
			return True
	return False


def _create_missing_wallets():
	if not all(
		frappe.db.exists("DocType", doctype)
		for doctype in ("Lexocrates Portal User", "Lexocrates Client Wallet")
	):
		return
	clients = frappe.get_all(
		"Lexocrates Portal User", filters={"client": ["is", "set"]}, pluck="client", limit_page_length=0
	)
	for client in dict.fromkeys(clients):
		if not frappe.db.exists("Lexocrates Client Wallet", {"client": client}):
			frappe.get_doc(
				{"doctype": "Lexocrates Client Wallet", "client": client, "status": "Active"}
			).insert(ignore_permissions=True)


def migrate_contact_client_links():
	"""Create the direct Portal User mapping for legacy Contact-linked client users.

	Contacts are retained as historical ERP records, but authorization immediately
	moves to Lexocrates Portal User and no new Contact is created by this app.
	"""
	if not all(
		frappe.db.exists("DocType", doctype)
		for doctype in ("Contact", "Dynamic Link", "Lexocrates Portal User")
	):
		return
	links = frappe.db.sql(
		"""
		select distinct contact.user, link.link_name as client
		from `tabContact` contact
		inner join `tabDynamic Link` link
			on link.parent = contact.name and link.parenttype = 'Contact'
		where contact.user is not null and contact.user != ''
			and link.link_doctype = 'Customer'
		""",
		as_dict=True,
	)
	by_user: dict[str, list[str]] = {}
	for row in links:
		by_user.setdefault(row.user, []).append(row.client)
	for user, clients in by_user.items():
		clients = list(dict.fromkeys(clients))
		if len(clients) != 1 or frappe.db.exists("Lexocrates Portal User", {"user": user}):
			continue
		if "Lexocrates Client" not in frappe.get_roles(user):
			continue
		previous_flag = getattr(frappe.flags, "lexocrates_portal_service", False)
		frappe.flags.lexocrates_portal_service = True
		try:
			frappe.get_doc(
				{
					"doctype": "Lexocrates Portal User",
					"user": user,
					"client": clients[0],
					"portal_role": "Client Administrator",
					"account_status": "Active",
					"matter_access_scope": "All Client Matters",
				}
			).insert(ignore_permissions=True)
		finally:
			frappe.flags.lexocrates_portal_service = previous_flag


def schedule_portal_contact_cleanup(user: str):
	"""Remove only Frappe's empty auto-generated Contact for a direct Portal User.

	Frappe creates a Contact on every User save. The Lexocrates client domain does
	not use that entity, so a cleanup job is queued after the core job. Contacts
	with real ERP Dynamic Links are retained as historical business data.
	"""
	if getattr(frappe.flags, "in_test", False):
		remove_empty_portal_contact(user)
		return
	frappe.enqueue(
		"lex.client_schema.remove_empty_portal_contact",
		user=user,
		enqueue_after_commit=True,
	)


def remove_empty_portal_contact(user: str):
	for contact in frappe.get_all("Contact", filters={"user": user}, pluck="name", limit_page_length=0):
		if frappe.db.exists("Dynamic Link", {"parenttype": "Contact", "parent": contact}):
			continue
		frappe.delete_doc("Contact", contact, ignore_permissions=True, force=True)
