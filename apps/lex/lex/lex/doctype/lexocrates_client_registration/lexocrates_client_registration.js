frappe.ui.form.on("Lexocrates Client Registration", {
	refresh(frm) {
		if (!["Pending Compliance Review", "Changes Required"].includes(frm.doc.status)) return;
		frm.add_custom_button(__("Record Compliance Decision"), () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Client onboarding review"),
				fields: [
					{ fieldname: "kyc_status", fieldtype: "Select", label: __("KYC Status"), options: "Pending\nPassed\nFailed\nNeeds Review", default: frm.doc.kyc_status, reqd: 1 },
					{ fieldname: "conflict_check_status", fieldtype: "Select", label: __("Conflict Check"), options: "Pending\nPassed\nFailed\nNeeds Review", default: frm.doc.conflict_check_status, reqd: 1 },
					{ fieldname: "sanctions_check_status", fieldtype: "Select", label: __("Sanctions Check"), options: "Pending\nPassed\nFailed\nNeeds Review", default: frm.doc.sanctions_check_status, reqd: 1 },
					{ fieldname: "commercial_approval_status", fieldtype: "Select", label: __("Commercial Approval"), options: "Pending\nApproved\nRejected", default: frm.doc.commercial_approval_status, reqd: 1 },
					{ fieldname: "review_notes", fieldtype: "Small Text", label: __("Review Notes"), default: frm.doc.review_notes },
				],
				primary_action_label: __("Record decision"),
				primary_action(values) {
					frappe.call({
						method: "lex.portal_management.record_registration_compliance",
						args: { registration: frm.doc.name, ...values },
						freeze: true,
					}).then((response) => {
						dialog.hide();
						frm.reload_doc();
						const result = response.message || {};
						frappe.msgprint(result.activation_url
							? `${__("Registration approved. Activation link:")}<br><a href="${result.activation_url}">${result.activation_url}</a>`
							: __("Compliance decision recorded."));
					});
				},
			});
			dialog.show();
		}, __("Onboarding"));
	},
});
