frappe.ui.form.on("LPO Compliance Log", {
	job(frm) {
		if (!frm.doc.job) return;
		frappe.db.get_value("LPO Job", frm.doc.job, ["engagement", "customer"]).then(({ message }) => {
			frm.set_value("engagement", message.engagement);
			frm.set_value("customer", message.customer);
		});
	},

	refresh(frm) {
		if (!frm.is_new() && frm.doc.job) {
			frm.add_custom_button(__("LPO Job"), () => {
				frappe.set_route("Form", "LPO Job", frm.doc.job);
			}, __("View"));
		}
	},
});
