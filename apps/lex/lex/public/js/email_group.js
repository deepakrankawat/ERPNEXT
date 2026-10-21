frappe.ui.form.on("Email Group", {
	refresh: function (frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(
			__("Import from CSV"),
			function () {
				new frappe.ui.FileUploader({
					doctype: frm.doctype,
					docname: frm.docname,
					frm: frm,
					folder: "Home",
					on_success: (file_doc) => {
						frappe.call({
							method: "lex.email_campaign_scheduler.import_csv_to_email_group",
							args: { email_group: frm.doc.name, file_url: file_doc.file_url },
							freeze: true,
							freeze_message: __("Scanning CSV for email addresses..."),
						}).then((r) => {
							const result = r.message || {};
							const added = result.added || [];
							const skipped = result.skipped || [];
							frappe.msgprint({
								title: __("Import from CSV"),
								indicator: added.length ? "green" : "orange",
								message: __("Found {0} email address(es) in the file -- added {1}, {2} were already in this group.", [
									result.total_found || 0, added.length, skipped.length,
								]),
							});
							frm.reload_doc();
						});
					},
				});
			},
			__("Action")
		);
	},
});
