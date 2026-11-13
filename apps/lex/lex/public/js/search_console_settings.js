frappe.ui.form.on("Search Console Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Connect to Google Search Console"), () => {
			frappe.call({
				method: "lex.google_search_console.get_authentication_url",
				callback(r) {
					if (r.message) window.location.href = r.message;
				},
			});
		});
	},
});
