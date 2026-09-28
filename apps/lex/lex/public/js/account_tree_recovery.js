// The Chart of Accounts "New" action opens a tree dialog, not an Account form.
// Keep its essential name field available even if stale custom metadata or
// another client script has modified the standard tree settings.
(() => {
	const settings = frappe.treeview_settings && frappe.treeview_settings.Account;
	if (!settings) return;

	settings.fields = settings.fields || [];
	let accountName = settings.fields.find((field) => field.fieldname === "account_name");
	if (!accountName) {
		accountName = {
			fieldtype: "Data",
			fieldname: "account_name",
			label: __("New Account Name"),
		};
		settings.fields.unshift(accountName);
	}

	accountName.hidden = 0;
	accountName.reqd = 1;
	delete accountName.depends_on;
})();
