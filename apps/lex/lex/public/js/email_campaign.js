function permitted_send_from_accounts() {
	// frappe.boot.email_accounts is the same permission-scoped list (via the
	// "User Email" grants on the current user) that the standard email
	// composer's "Sender" dropdown uses -- the synthetic "All Accounts" /
	// "Sent" / "Spam" / "Trash" rows it also contains have no
	// enable_outgoing key, so they're excluded here for free.
	return (frappe.boot.email_accounts || [])
		.filter((a) => a.enable_outgoing)
		.map((a) => a.email_account);
}

frappe.ui.form.on("Email Campaign", {
	onload: function (frm) {
		const accounts = permitted_send_from_accounts();
		frm.set_query("send_from", () => ({ filters: { name: ["in", accounts] } }));
		if (frm.is_new() && !frm.doc.send_from && accounts.length === 1) {
			frm.set_value("send_from", accounts[0]);
		}
	},
});
