frappe.ui.form.on("LPO Job", {
	setup(frm) {
		frm.set_query("engagement", () => ({
			filters: { status: ["in", ["Draft", "Active"]] },
		}));
	},

	refresh(frm) {
		if (!frm.is_new() && frm.doc.engagement) {
			frm.add_custom_button(__("Parent Matter"), () => {
				frappe.set_route("Form", "LPO Matter", frm.doc.engagement);
			}, __("View"));
		}
	},
});
