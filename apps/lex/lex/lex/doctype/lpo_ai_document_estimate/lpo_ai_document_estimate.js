frappe.ui.form.on("LPO AI Document Estimate", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (frm.doc.work_intake) {
			frm.add_custom_button(__("Work Intake"), () => {
				frappe.set_route("Form", "Lexocrates Work Intake", frm.doc.work_intake);
			}, __("View"));
		}
		if (frm.doc.job) {
			frm.add_custom_button(__("Activated Job"), () => {
				frappe.set_route("Form", "LPO Job", frm.doc.job);
			}, __("View"));
		}
		if (!["Activated", "Superseded"].includes(frm.doc.status) && frm.perm?.[0]?.write) {
			frm.add_custom_button(__("Apply Reviewed Estimate"), async () => {
				if (frm.is_dirty()) await frm.save();
				await frappe.call({
					method: "lex.work_intake.apply_document_estimate",
					args: { estimate: frm.doc.name },
					freeze: true,
					freeze_message: __("Applying the reviewed estimate and routing pricing approval..."),
				});
				frappe.show_alert({ message: __("Reviewed estimate applied to Work Intake"), indicator: "green" });
				await frm.reload_doc();
			}, __("Estimate"));
			frm.add_custom_button(__("Reset to Proposal"), () => {
				frm.set_value("reviewed_lexpoints", frm.doc.proposed_lexpoints);
				frm.set_value("reviewed_amount", frm.doc.proposed_amount);
				frm.set_value("reviewed_delivery_hours", frm.doc.proposed_delivery_hours);
				frm.set_value("reviewed_scope", frm.doc.proposed_scope);
			}, __("Estimate"));
		}
	},
});
