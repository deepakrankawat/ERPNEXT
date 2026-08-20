frappe.ui.form.on("Lexocrates Portal User", {
	refresh(frm) {
		if (!frm.is_new() && frm.has_perm("write")) {
			frm.add_custom_button(__("Apply Role Defaults"), () => {
				frappe.call({
					method: "lex.lex.doctype.lexocrates_portal_user.lexocrates_portal_user.apply_role_defaults",
					args: { portal_user: frm.doc.name },
					freeze: true,
					callback: () => frm.reload_doc(),
				});
			}, __("Permissions"));
		}
	},
});
