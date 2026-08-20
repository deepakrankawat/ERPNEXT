import frappe
from frappe import _
from frappe.model.document import Document


class LexocratesClientRegistration(Document):
	def before_insert(self):
		if not getattr(frappe.flags, "lexocrates_portal_service", False):
			frappe.throw(_("Client registrations can only be created by the registration service."), frappe.PermissionError)

	def before_save(self):
		if not self.is_new() and not getattr(frappe.flags, "lexocrates_portal_service", False):
			frappe.throw(_("Client registrations can only be changed by the registration service."), frappe.PermissionError)

	def on_trash(self):
		frappe.throw(_("Client registration evidence cannot be deleted."), frappe.PermissionError)
