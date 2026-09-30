import frappe
from frappe import _
from frappe.model.document import Document


class LeadGroup(Document):
	def update_total_leads(self):
		self.total_leads = self.get_total_leads()
		self.db_update()
		return self.total_leads

	def get_total_leads(self):
		return frappe.db.count("Lead Group Member", {"lead_group": self.name})

	def on_trash(self):
		for d in frappe.get_all("Lead Group Member", "name", {"lead_group": self.name}):
			frappe.delete_doc("Lead Group Member", d.name, ignore_permissions=True)


@frappe.whitelist()
def add_leads(name, leads):
	"""Add the given Leads to a Lead Group, creating the group if it doesn't exist yet."""
	if isinstance(leads, str):
		leads = frappe.parse_json(leads)
	if not leads:
		frappe.throw(_("Select at least one Lead."), frappe.ValidationError)

	if frappe.db.exists("Lead Group", name):
		group = frappe.get_doc("Lead Group", name)
		group.check_permission("write")
	else:
		group = frappe.get_doc({"doctype": "Lead Group", "title": name}).insert()

	added, skipped = [], []
	for lead in leads:
		if frappe.db.exists("Lead Group Member", {"lead_group": group.name, "lead": lead}):
			skipped.append(lead)
			continue
		frappe.get_doc({
			"doctype": "Lead Group Member",
			"lead_group": group.name,
			"lead": lead,
		}).insert(ignore_permissions=True)
		added.append(lead)

	frappe.db.commit()
	return {"lead_group": group.name, "added": added, "skipped": skipped}
