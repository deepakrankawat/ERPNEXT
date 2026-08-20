import frappe
from frappe.tests.utils import FrappeTestCase


class TestLPOMatter(FrappeTestCase):
	def setUp(self):
		self.customer = _make_customer()

	def test_end_date_cannot_precede_start_date(self):
		matter = _make_matter(
			self.customer,
			start_date="2026-08-11",
			end_date="2026-08-10",
			insert=False,
		)
		with self.assertRaises(frappe.ValidationError):
			matter.insert()


def _make_customer():
	name = "_Test LPO Operations Customer"
	if frappe.db.exists("Customer", name):
		return name

	return frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": name,
			"customer_type": "Company",
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
			"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
		}
	).insert().name


def _make_matter(customer, insert=True, **values):
	doc = frappe.get_doc(
		{
			"doctype": "LPO Matter",
			"matter_title": "_Test Canadian Contract Review",
			"customer": customer,
			"status": "Active",
			"matter_model": "Project",
			"matter_manager": "Administrator",
			"billing_method": "Quoted Price",
			"quoted_amount": 1000,
			"quote_status": "Approved",
			"practice_area": "Contract Review",
			"jurisdictions": "Canada; Ontario",
			"start_date": "2026-08-11",
			"confidentiality_level": "Highly Confidential",
			**values,
		}
	)
	return doc.insert() if insert else doc


# Alias for backward compatibility in tests
_make_engagement = _make_matter
