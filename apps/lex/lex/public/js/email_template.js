frappe.ui.form.on("Email Template", {
	refresh(frm) {
		if (frm.doc.custom_use_ai_template && frm.doc.custom_ai_email_template) {
			frm.add_custom_button(__("✨ Open AI Prompt Settings"), () => {
				frappe.set_route("Form", "AI Email Template", frm.doc.custom_ai_email_template);
			}, __("AI Actions"));
		}
	},

	custom_ai_email_template(frm) {
		if (frm.doc.custom_ai_email_template) {
			frappe.db.get_doc("AI Email Template", frm.doc.custom_ai_email_template).then((ai_doc) => {
				if (!frm.doc.subject || frm.doc.subject.trim() === "") {
					frm.set_value("subject", ai_doc.subject);
				}
				if (!frm.doc.response || frm.doc.response.trim() === "") {
					frm.set_value("response", ai_doc.response || `<p>AI Personalized Template: ${ai_doc.name}</p>`);
				}
			});
		}
	},
});
