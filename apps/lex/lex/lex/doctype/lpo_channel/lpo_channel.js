frappe.ui.form.on("LPO Channel", {
	setup(frm) {
		frm.set_query("reference_doctype", () => ({
			filters: {
				name: ["in", ["LPO Matter", "LPO Job"]],
			},
		}));

		frm.set_query("user", "members", () => ({
			filters: {
				enabled: 1,
				user_type: "System User",
			},
		}));
	},
});
