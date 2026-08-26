frappe.ui.form.on("LPO AI Model Registry", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Run Compatibility Test"), async () => {
				const response = await frappe.call({
					method: "lex.lex.doctype.lpo_ai_settings.lpo_ai_settings.test_ai_provider_connection",
					args: { provider: frm.doc.provider, model: frm.doc.model_id },
					freeze: true,
					freeze_message: __("Testing {0}...", [frm.doc.model_id]),
				});
				const result = response.message || {};
				frappe.msgprint({
					title: result.status === "success" ? __("Compatibility verified") : __("Compatibility failed"),
					message: frappe.utils.escape_html(result.message || result.error_type || __("No diagnostic returned.")),
					indicator: result.status === "success" ? "green" : "red",
				});
				frm.reload_doc();
			}, __("Diagnostics"));
		}
	},
});
