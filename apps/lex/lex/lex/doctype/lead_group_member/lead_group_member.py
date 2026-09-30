import frappe
from frappe.model.document import Document


class LeadGroupMember(Document):
	def after_insert(self):
		frappe.get_doc("Lead Group", self.lead_group).update_total_leads()

	def after_delete(self):
		frappe.get_doc("Lead Group", self.lead_group).update_total_leads()


def after_doctype_insert():
	frappe.db.add_unique("Lead Group Member", ("lead_group", "lead"))
