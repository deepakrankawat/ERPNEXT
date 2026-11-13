frappe.ui.form.on("Lead", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("✨ AI Personalized Email"), () => {
			show_ai_email_dialog(frm);
		}, __("Actions"));
	},
});

function show_ai_email_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("✨ Generate AI Email for {0}", [frm.doc.lead_name || frm.doc.name]),
		size: "large",
		fields: [
			{
				fieldname: "template",
				fieldtype: "Link",
				options: "AI Email Template",
				label: __("Select AI Email Template"),
				reqd: 1,
			},
			{
				fieldname: "custom_notes",
				fieldtype: "Small Text",
				label: __("Additional Context / Meeting Notes (Optional)"),
				description: __("Add specific details like: 'Met at LegalTech conference, keen on Contract Review'"),
			},
			{
				fieldname: "btn_generate",
				fieldtype: "Button",
				label: __("✨ Generate Email with AI"),
				click: () => {
					const values = dialog.get_values();
					if (!values || !values.template) {
						frappe.msgprint(__("Please select an AI Email Template first."));
						return;
					}

					frappe.call({
						method: "lex.lex.doctype.ai_email_template.ai_email_template.generate_email_for_lead",
						args: {
							lead: frm.doc.name,
							template: values.template,
							custom_notes: values.custom_notes,
						},
						freeze: true,
						freeze_message: __("Synthesizing lead profile and drafting email..."),
						callback(r) {
							if (r.message && r.message.status === "success") {
								dialog.set_value("generated_section", 1);
								dialog.set_value("email_subject", r.message.subject);
								dialog.set_value("email_body", r.message.body);
								dialog.get_field("email_subject").$wrapper.show();
								dialog.get_field("email_body").$wrapper.show();
								frappe.show_alert({
									message: __("✨ Personalized email drafted!"),
									indicator: "green",
								});
							}
						},
					});
				},
			},
			{
				fieldname: "generated_section",
				fieldtype: "Section Break",
				label: __("Generated Email (Review & Edit)"),
			},
			{
				fieldname: "email_subject",
				fieldtype: "Data",
				label: __("Subject"),
				reqd: 1,
			},
			{
				fieldname: "email_body",
				fieldtype: "Text Editor",
				label: __("Email Body"),
				reqd: 1,
			},
		],
		primary_action_label: __("Send Email Now"),
		primary_action: (values) => {
			if (!values.email_subject || !values.email_body) {
				frappe.msgprint(__("Generate and review the email before sending."));
				return;
			}
			if (!frm.doc.email_id) {
				frappe.msgprint(__("This Lead has no email address configured."));
				return;
			}

			frappe.confirm(
				__("Send this email directly to <b>{0}</b> ({1})?", [frm.doc.lead_name || frm.doc.name, frm.doc.email_id]),
				() => {
					frappe.call({
						method: "lex.lex.doctype.ai_email_template.ai_email_template.send_ai_generated_email",
						args: {
							lead: frm.doc.name,
							subject: values.email_subject,
							body: values.email_body,
						},
						freeze: true,
						freeze_message: __("Sending email..."),
						callback(r) {
							if (r.message && r.message.status === "success") {
								dialog.hide();
								frappe.msgprint({
									title: __("Email Dispatched"),
									indicator: "green",
									message: r.message.message,
								});
								frm.reload_doc();
							}
						},
					});
				}
			);
		},
		secondary_action_label: __("Copy to Clipboard"),
		secondary_action: () => {
			const values = dialog.get_values();
			if (!values || !values.email_body) {
				frappe.msgprint(__("No email content to copy yet."));
				return;
			}
			const tempEl = document.createElement("div");
			tempEl.innerHTML = values.email_body;
			const text = `Subject: ${values.email_subject}\n\n${tempEl.innerText || tempEl.textContent}`;
			navigator.clipboard.writeText(text).then(() => {
				frappe.show_alert({ message: __("Copied to clipboard!"), indicator: "green" });
			});
		},
	});

	dialog.show();
}
