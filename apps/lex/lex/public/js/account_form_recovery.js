// Keep ERPNext's two core child-account fields available on the New Account form.
// This is intentionally limited to unsaved Accounts; it does not alter any
// existing account's financial settings or tree structure.
frappe.ui.form.on("Account", {
	refresh(frm) {
		if (!frm.is_new()) return;
		frm.toggle_display("account_name", true);
		frm.toggle_display("parent_account", true);
		frm.set_df_property("account_name", "reqd", 1);
		frm.set_df_property("parent_account", "reqd", 1);
	},
});
