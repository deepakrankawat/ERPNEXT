import frappe
from frappe.model.document import Document

class CustomerInteractionNote(Document):
    def validate(self):
        """Validate interaction date and follow up date"""
        if self.follow_up_date and self.follow_up_date < self.interaction_date:
            frappe.throw("Follow-Up Date cannot be before Interaction Date.")
