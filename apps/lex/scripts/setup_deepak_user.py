import frappe
from frappe.utils.password import update_password

import os

def run():
    os.chdir("/home/frappe/frappe-bench/sites")
    frappe.init(site="development.localhost")
    frappe.connect()

    email = "deepakrankawatcode@gmail.com"
    alt_email = "deepakrankawatcode@gmai.com"

    for em in [email, alt_email]:
        if not frappe.db.exists("User", em):
            user = frappe.get_doc({
                "doctype": "User",
                "email": em,
                "first_name": "Deepak",
                "last_name": "Rankawat",
                "enabled": 1,
                "send_welcome_email": 0,
                "roles": [{"role": "Customer"}]
            }).insert(ignore_permissions=True)
            print(f"Created User: {em}")
        else:
            user = frappe.get_doc("User", em)
            user.enabled = 1
            user.save(ignore_permissions=True)
            print(f"User exists: {em}")

        update_password(em, "deepak@762")
        print(f"Password updated for {em}")

        pu_name = frappe.db.get_value("Lexocrates Portal User", {"user": em}, "name")
        if not pu_name:
            pu = frappe.get_doc({
                "doctype": "Lexocrates Portal User",
                "user": em,
                "full_name": "Deepak Rankawat",
                "client": "Lexocrates Demo Client Pvt. Ltd.",
                "portal_role": "Client Administrator",
                "account_status": "Active",
                "matter_access_scope": "All Client Matters",
                "can_create_matters": 1,
                "can_upload_documents": 1,
                "can_comment": 1,
                "billing_access": 1,
                "lexpack_view_access": 1,
                "lexpack_purchase_access": 1,
                "approval_authority": "All Client Approvals",
                "user_management_authority": 1,
                "report_access": "All Client Reports"
            }).insert(ignore_permissions=True)
            print(f"Created Portal User: {pu.name}")
        else:
            pu = frappe.get_doc("Lexocrates Portal User", pu_name)
            pu.account_status = "Active"
            pu.portal_role = "Client Administrator"
            pu.can_create_matters = 1
            pu.can_upload_documents = 1
            pu.can_comment = 1
            pu.billing_access = 1
            pu.lexpack_view_access = 1
            pu.lexpack_purchase_access = 1
            pu.approval_authority = "All Client Approvals"
            pu.user_management_authority = 1
            pu.report_access = "All Client Reports"
            pu.save(ignore_permissions=True)
            print(f"Updated Portal User: {pu_name}")

    update_password("client.demo@lexocrates.com", "deepak@762")
    frappe.db.commit()
    print("ALL DONE")

if __name__ == "__main__":
    run()
