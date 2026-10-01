from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from lex.audit_worm_chain import compute_audit_event_hash, verify_audit_trail_integrity
from lex.lex.doctype.master_service_level_agreement.master_service_level_agreement import (
	accept,
	hash_terms_html,
)
from lex.portal_audit import create_portal_audit_event
from lex.test_client_portal_architecture import _make_client


def _accept_kwargs(name: str) -> dict:
	return dict(
		name=name,
		accepted_by_name="Jane Signatory",
		accepted_by_designation="General Counsel",
		ack_read_and_understood=1,
		ack_business_week=1,
		ack_no_24x7_production=1,
		ack_submission_not_sla_start=1,
		ack_lextimator_indicative=1,
		ack_fixed_quote_protection=1,
		ack_scope_changes_affect_price=1,
		ack_confirmed_delivery_date_controls=1,
		ack_priority_subject_to_availability=1,
		ack_no_automatic_express_service=1,
		ack_signatory_authority=1,
	)


def _make_pending_sla(client: str, terms_html: str = "<p>Sample terms</p>"):
	return frappe.get_doc(
		{
			"doctype": "Master Service Level Agreement",
			"version": "1.0",
			"effective_date": frappe.utils.nowdate(),
			"client": client,
			"terms_html": terms_html,
			"status": "Sent for Acceptance",
			"lexocrates_representative_name": "Lexocrates Legal Operations",
			"lexocrates_representative_designation": "Legal Operations",
			"lexocrates_signed_on": frappe.utils.nowdate(),
		}
	).insert(ignore_permissions=True)


class TestMasterServiceLevelAgreementAcceptance(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.previous_in_test = getattr(frappe.flags, "in_test", False)
		frappe.flags.in_test = True

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.flags.in_test = self.previous_in_test

	def test_accept_records_terms_hash_and_passes_audit_verification(self):
		client = _make_client()
		sla = _make_pending_sla(client, terms_html="<p>Version A terms</p>")

		result = accept(**_accept_kwargs(sla.name))

		doc = frappe.get_doc("Master Service Level Agreement", sla.name)
		self.assertEqual(doc.status, "Accepted")
		self.assertEqual(doc.accepted_terms_hash, hash_terms_html("<p>Version A terms</p>"))
		self.assertTrue(result["acceptance_audit_reference"])

		audit = frappe.get_doc("Lexocrates Portal Audit Event", result["acceptance_audit_reference"])
		self.assertEqual(audit.hash_version, 2)
		self.assertEqual(json.loads(audit.new_value)["accepted_terms_hash"], doc.accepted_terms_hash)

		self.assertTrue(verify_audit_trail_integrity(client)["verified"])

	def test_accepted_sla_cannot_be_edited(self):
		client = _make_client()
		sla = _make_pending_sla(client)
		accept(**_accept_kwargs(sla.name))

		doc = frappe.get_doc("Master Service Level Agreement", sla.name)
		doc.terms_html = "<p>Tampered terms</p>"
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_accepted_sla_cannot_be_deleted(self):
		client = _make_client()
		sla = _make_pending_sla(client)
		accept(**_accept_kwargs(sla.name))

		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc("Master Service Level Agreement", sla.name, ignore_permissions=True)

	def test_pending_sla_can_still_be_edited_before_acceptance(self):
		client = _make_client()
		sla = _make_pending_sla(client)

		doc = frappe.get_doc("Master Service Level Agreement", sla.name)
		doc.terms_html = "<p>Revised before acceptance</p>"
		doc.save(ignore_permissions=True)

		self.assertEqual(
			frappe.db.get_value("Master Service Level Agreement", sla.name, "terms_html"),
			"<p>Revised before acceptance</p>",
		)

	def test_harmless_resave_of_accepted_sla_does_not_raise(self):
		client = _make_client()
		sla = _make_pending_sla(client)
		accept(**_accept_kwargs(sla.name))

		doc = frappe.get_doc("Master Service Level Agreement", sla.name)
		doc.save(ignore_permissions=True)  # no field changes - must not raise

	def test_legacy_hash_version_1_audit_event_still_verifies(self):
		client = _make_client()
		event = create_portal_audit_event(
			client=client,
			action="Legacy Style Event",
			object_type="Customer",
			object_id=client,
			new_value={"note": "pre-v2"},
		)
		# Simulate a row written before the user_agent field/v2 hashing existed:
		# downgrade it to a hash_version=1 hash via a direct DB write (bypassing
		# the document's own immutability guard, as a real historical row
		# already sitting in the database would not go through before_insert
		# again). Verification must still accept it using the v1 field set.
		stored = frappe.get_doc("Lexocrates Portal Audit Event", event.name)
		v1_hash = compute_audit_event_hash(stored.as_dict(), stored.previous_hash, hash_version=1)
		frappe.db.set_value(
			"Lexocrates Portal Audit Event",
			event.name,
			{"hash_version": 1, "event_hash": v1_hash, "user_agent": None},
			update_modified=False,
		)
		self.assertTrue(verify_audit_trail_integrity(client)["verified"])
