"""Permanently remove retired LexPoint records and schema.

This is intentionally *not* listed in ``patches.txt``.  It is a destructive,
one-time migration and may only be registered after every runtime caller has
been converted to currency Legal Capacity.  Before registering it, an
administrator must explicitly set this site configuration value:

    bench --site <site> set-config lex_confirm_lexpoint_purge 1

The confirmation prevents a copied patch list or an unrelated migrate from
deleting financial history unexpectedly.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model import delete_fields
from frappe.utils import cint


CONFIRMATION_CONFIG_KEY = "lex_confirm_lexpoint_purge"

# These DocTypes belonged exclusively to the retired unit-pricing estimator.
LEGACY_DOCTYPES = (
	"LPO AI Document Estimate",
	"LPO Standalone Estimate",
	"LPO LexPoint Service Rule",
	"LPO LexPoint Multiplier",
	"LPO LexPoint Settings",
)

LEGACY_PAGE = "lexpoint-estimator"

# Fields that used the retired unit system, or only linked to its retired
# estimate records.  Every entry is checked against the live schema so the
# migration is safe to re-run after a partial deployment.
LEGACY_FIELDS = {
	"LPO Matter": (
		"quoted_amount",
		"quote_status",
		"quote_approved_by",
		"quote_approved_on",
		"billing_column_break",
		"lexpoints_estimated",
		"lexpoints_reserved",
		"lexpoints_consumed",
		"funding_status",
		"funding_transaction",
	),
	"LPO Job": (
		"required_lexpoints",
		"intake_estimate_doctype",
		"intake_estimate",
	),
	"Lexocrates Work Intake": (
		"required_lexpoints",
		"ai_estimate_reference_doctype",
		"ai_document_estimate",
	),
	"LexPack Settings": ("direct_quote_rate_per_point",),
	"LexPack Plan": ("lexpoints", "qualification_bonus_points"),
	"LexPack Purchase": ("base_lexpoints", "bonus_lexpoints", "total_lexpoints"),
	"Lexocrates Client Wallet": ("bonus_points_earned",),
	"Lexocrates Wallet Transaction": ("points",),
	"LPO AI Settings": (
		"enable_standalone_estimation",
		"estimation_credential",
		"estimation_provider",
		"estimation_model",
	),
}


def execute():
	"""Run the confirmed, irreversible LexPoint data and metadata purge."""
	if not cint(frappe.conf.get(CONFIRMATION_CONFIG_KEY)):
		frappe.throw(
			_(
				"LexPoint purge is deliberately disabled. Set site_config value {0}=1 only after "
				"taking a backup and completing the currency-only code deployment."
			).format(CONFIRMATION_CONFIG_KEY),
			frappe.ValidationError,
		)

	# Remove active-schema fields before deleting the retired DocTypes they
	# reference.  delete_fields handles both regular tables and Singles.
	_delete_retired_fields()
	_remove_legacy_workspace_metadata()
	_remove_legacy_page()
	_remove_legacy_documents_and_attachments()
	_remove_legacy_doctype_metadata_and_tables()
	_remove_legacy_references()
	frappe.clear_cache()


def _delete_retired_fields():
	fields_to_drop = {
		doctype: [fieldname for fieldname in fields if _field_exists(doctype, fieldname)]
		for doctype, fields in LEGACY_FIELDS.items()
		if frappe.db.exists("DocType", doctype)
	}
	delete_fields(fields_to_drop, delete=True)


def _remove_legacy_workspace_metadata():
	targets = [*LEGACY_DOCTYPES, LEGACY_PAGE]
	if _field_exists("Workspace Link", "link_to"):
		frappe.db.delete("Workspace Link", {"link_to": ("in", targets)})
	if _field_exists("Workspace Shortcut", "link_to"):
		frappe.db.delete("Workspace Shortcut", {"link_to": ("in", targets)})


def _remove_legacy_page():
	if frappe.db.exists("Page", LEGACY_PAGE):
		frappe.delete_doc(
			"Page",
			LEGACY_PAGE,
			force=1,
			ignore_permissions=True,
			delete_permanently=True,
		)


def _remove_legacy_documents_and_attachments():
	for doctype in LEGACY_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		_remove_attachments(doctype)
		if frappe.db.get_value("DocType", doctype, "issingle"):
			frappe.db.delete("Singles", {"doctype": doctype})
			continue
		# Direct database deletion is intentional: these data belong only to the
		# retired pricing model and must not create Deleted Document history.
		frappe.db.delete(doctype, {})


def _remove_attachments(doctype: str):
	if not _field_exists("File", "attached_to_doctype"):
		return
	# The Python controller for a retired DocType is intentionally absent from
	# this deployment. Delete File metadata directly so Frappe never attempts to
	# import that retired controller during File.on_trash.
	frappe.db.delete("File", {"attached_to_doctype": doctype})


def _remove_legacy_doctype_metadata_and_tables():
	for doctype in LEGACY_DOCTYPES:
		_remove_doctype_metadata(doctype)
		_drop_table(doctype)


def _remove_doctype_metadata(doctype: str):
	# Remove inbound metadata first.  This avoids stale Desk links and Dynamic
	# Links even on databases where a user created custom fields against a
	# retired DocType.
	for metadata_doctype, filters in (
		("Custom Field", {"options": doctype}),
		("DocField", {"options": doctype}),
		("DocType Link", {"link_doctype": doctype}),
		("Property Setter", {"doc_type": doctype}),
		("Report", {"ref_doctype": doctype}),
		("Dashboard Chart", {"document_type": doctype}),
		("Number Card", {"document_type": doctype}),
	):
		_delete_if_field_exists(metadata_doctype, filters)

	if frappe.db.exists("DocType", doctype):
		frappe.delete_doc(
			"DocType",
			doctype,
			force=1,
			ignore_permissions=True,
			delete_permanently=True,
		)


def _remove_legacy_references():
	"""Delete records whose only subject was a removed estimator DocType."""
	for doctype in LEGACY_DOCTYPES:
		for reference_doctype, reference_field in (
			("Comment", "reference_doctype"),
			("Communication", "reference_doctype"),
			("ToDo", "reference_type"),
			("Version", "ref_doctype"),
			("Activity Log", "reference_doctype"),
			("DocShare", "share_doctype"),
			("Dynamic Link", "link_doctype"),
			("Email Queue", "reference_doctype"),
			("Lexocrates Portal Audit Event", "object_type"),
			("Deleted Document", "deleted_doctype"),
		):
			if _field_exists(reference_doctype, reference_field):
				frappe.db.delete(reference_doctype, {reference_field: doctype})


def _delete_if_field_exists(doctype: str, filters: dict):
	if not frappe.db.table_exists(doctype):
		return
	if all(_field_exists(doctype, fieldname) for fieldname in filters):
		frappe.db.delete(doctype, filters)


def _field_exists(doctype: str, fieldname: str) -> bool:
	if not frappe.db.exists("DocType", doctype):
		return False
	if frappe.db.get_value("DocType", doctype, "issingle"):
		return frappe.db.field_exists(doctype, fieldname)
	if not frappe.db.table_exists(doctype):
		return False
	try:
		return frappe.db.has_column(doctype, fieldname)
	except frappe.db.TableMissingError:
		return False


def _drop_table(doctype: str):
	if not frappe.db.table_exists(doctype):
		return
	quote = '"' if frappe.db.db_type == "postgres" else "`"
	table_name = f"tab{doctype}"
	frappe.db.sql_ddl(f"DROP TABLE IF EXISTS {quote}{table_name}{quote}")
