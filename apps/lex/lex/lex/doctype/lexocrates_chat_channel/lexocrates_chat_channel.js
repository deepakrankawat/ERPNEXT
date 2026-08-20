frappe.ui.form.on("Lexocrates Chat Channel", {
	setup(frm) {
		frm.set_query("reference_doctype", () => ({
			filters: { name: ["in", ["LPO Matter", "LPO Job", "LPO QA Review", "AI Job Request", "LPO AI Job Request"]] },
		}));
		frm.set_query("user", "members", () => ({
			filters: { enabled: 1, user_type: "System User" },
		}));
	},
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Open Chat"), () => {
				frappe.set_route("lexocrates-chat", { channel: frm.doc.name });
			});
		}
		if (frm.doc.status === "Archived") {
			frm.set_intro(__("This channel is archived. Its audit history remains readable, but new messages are blocked."), "orange");
		}
	},
});
