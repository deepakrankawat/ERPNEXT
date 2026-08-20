frappe.ui.form.on("LPO QA Review", {
	setup(frm) {
		frm.set_query("job", () => ({
			filters: { job_status: ["not in", ["Delivered", "Completed", "Cancelled"]] },
		}));
	},

	refresh(frm) {
		if (!frm.is_new() && frm.doc.job) {
			frm.add_custom_button(__("LPO Job"), () => {
				frappe.set_route("Form", "LPO Job", frm.doc.job);
			}, __("View"));
		}
	},
});
