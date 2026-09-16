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
			frm.add_custom_button(__("Re-run AI Estimation with Model"), () => {
				frappe.prompt(
					[
						{
							fieldname: "ai_model",
							label: __("Select LPO AI Model"),
							fieldtype: "Link",
							options: "LPO AI Model Registry",
							default: frm.doc.ai_model,
							reqd: 1,
							get_query: () => ({ filters: { enabled: 1 } }),
							description: __("Choose which AI model from LPO AI Registry to use for evidence classification"),
						},
					],
					async (values) => {
						if (frm.is_dirty()) await frm.save();
						await frappe.call({
							method: "lex.lex.doctype.lpo_ai_document_estimate.lpo_ai_document_estimate.rerun_estimate_with_model",
							args: {
								estimate_name: frm.doc.name,
								model_id: values.ai_model,
							},
							freeze: true,
							freeze_message: __("Re-running AI evidence classification with selected model..."),
						});
						frappe.show_alert({ message: __("AI estimation re-run complete"), indicator: "green" });
						await frm.reload_doc();
					},
					__("Re-run AI Estimation"),
					__("Run Estimate")
				);
			}, __("Estimate"));
			frm.add_custom_button(__("Reset to Proposal"), () => {
				frm.set_value("reviewed_lexpoints", frm.doc.proposed_lexpoints);
				frm.set_value("reviewed_amount", frm.doc.proposed_amount);
				frm.set_value("reviewed_delivery_hours", frm.doc.proposed_delivery_hours);
				frm.set_value("reviewed_scope", frm.doc.proposed_scope);
			}, __("Estimate"));
		}
	},

	ai_model(frm) {
		if (frm.doc.ai_model) {
			frappe.db.get_value("LPO AI Model Registry", frm.doc.ai_model, ["provider", "model_id"], (r) => {
				if (r) {
					frm.set_value("analysis_provider", r.provider);
					frm.set_value("analysis_model", r.model_id);
				}
			});
		}
	},
});
