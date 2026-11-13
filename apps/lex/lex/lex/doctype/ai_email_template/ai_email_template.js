frappe.ui.form.on("AI Email Template", {
	refresh(frm) {
		frm.add_custom_button(__("✨ Test Run with Lead"), () => {
			if (!frm.doc.sample_lead) {
				frappe.prompt(
					{
						label: __("Select Lead"),
						fieldname: "lead",
						fieldtype: "Link",
						options: "Lead",
						reqd: 1,
					},
					(values) => {
						frm.set_value("sample_lead", values.lead);
						frm.trigger("btn_test_generate");
					},
					__("Test AI Template with Lead"),
					__("Run Test")
				);
				return;
			}
			frm.trigger("btn_test_generate");
		}, __("Actions"));

		if (frm.doc.preview_html && frm.doc.sample_lead) {
			frm.add_custom_button(__("📧 Send Test Email to Lead"), () => {
				frm.events.send_preview_email(frm);
			}, __("Actions"));
		}
	},

	btn_test_generate(frm) {
		if (!frm.doc.sample_lead) {
			frappe.msgprint(__("Please select a Sample Lead in the test section first."));
			return;
		}

		if (frm.is_dirty()) {
			frappe.msgprint(__("Please save your changes before testing."));
			return;
		}

		frappe.call({
			method: "lex.lex.doctype.ai_email_template.ai_email_template.generate_email_for_lead",
			args: {
				lead: frm.doc.sample_lead,
				template: frm.doc.name,
			},
			freeze: true,
			freeze_message: __("Generating personalized AI email..."),
			callback(r) {
				if (r.message && r.message.status === "success") {
					frm.set_value("preview_subject", r.message.subject);
					frm.set_value("preview_html", r.message.body);
					frappe.show_alert({
						message: __("✨ Personalized email generated successfully!"),
						indicator: "green",
					});
					frm.scroll_to_field("preview_section");
				}
			},
		});
	},

	send_preview_email(frm) {
		if (!frm.doc.preview_subject || !frm.doc.preview_html) {
			frappe.msgprint(__("Generate a preview first before sending."));
			return;
		}

		frappe.confirm(
			__("Are you sure you want to send this test email to Lead <b>{0}</b>?", [frm.doc.sample_lead]),
			() => {
				frappe.call({
					method: "lex.lex.doctype.ai_email_template.ai_email_template.send_ai_generated_email",
					args: {
						lead: frm.doc.sample_lead,
						subject: frm.doc.preview_subject,
						body: frm.doc.preview_html,
					},
					freeze: true,
					freeze_message: __("Sending personalized email..."),
					callback(r) {
						if (r.message && r.message.status === "success") {
							frappe.msgprint({
								title: __("Email Sent"),
								indicator: "green",
								message: r.message.message,
							});
						}
					},
				});
			}
		);
	},
});
