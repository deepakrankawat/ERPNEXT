(() => {
	const existing = frappe.listview_settings["Lead"] || {};
	const existing_onload = existing.onload;

	frappe.listview_settings["Lead"] = Object.assign({}, existing, {
		onload(listview) {
			// ERPNext's own lead_list.js (loaded separately, by doctype-folder
			// convention) sets frappe.listview_settings["Lead"] too, and load
			// order between it and this hook-loaded file isn't guaranteed --
			// whichever runs second would otherwise wipe out the other's
			// onload entirely. Chain them instead of replacing.
			if (typeof existing_onload === "function") existing_onload(listview);

			listview.page.add_actions_menu_item(__("Send Email Campaign"), () => {
				const leads = listview.get_checked_items().map((d) => d.name);
				if (!leads.length) {
					frappe.msgprint(__("Select at least one Lead first."));
					return;
				}
				const dialog = new frappe.ui.Dialog({
					title: __("Send Email Campaign to {0} Lead(s)", [leads.length]),
					fields: [
						{ fieldname: "campaign_name", fieldtype: "Link", options: "Campaign", label: __("Campaign"), reqd: 1 },
						{ fieldname: "sender", fieldtype: "Link", options: "User", label: __("Sender"), reqd: 1, default: frappe.session.user },
						{ fieldname: "col1", fieldtype: "Column Break" },
						{ fieldname: "start_date", fieldtype: "Date", label: __("Start Date"), reqd: 1, default: frappe.datetime.get_today() },
						{ fieldname: "start_time", fieldtype: "Time", label: __("Start Time"), reqd: 1, default: frappe.datetime.now_time() },
						{ fieldname: "time_zone", fieldtype: "Select", label: __("Timezone"), reqd: 1, default: "Asia/Kolkata",
							options: ["Asia/Kolkata", "America/Toronto", "America/New_York", "Europe/London"].join("\n") },
					],
					primary_action_label: __("Send"),
					primary_action: (values) => {
						dialog.hide();
						frappe.call({
							method: "lex.email_campaign_scheduler.create_bulk_email_campaigns",
							args: { leads, ...values },
							freeze: true,
							freeze_message: __("Creating Email Campaigns..."),
						}).then((r) => {
							const result = r.message || {};
							const created = result.created || [];
							const skipped = result.skipped || [];
							let msg = __("Created {0} Email Campaign(s).", [created.length]);
							if (skipped.length) {
								msg += "<br>" + __("Skipped {0}:", [skipped.length]) + "<ul>" +
									skipped.map((s) => `<li>${frappe.utils.escape_html(s.lead)} — ${frappe.utils.escape_html(s.reason)}</li>`).join("") + "</ul>";
							}
							frappe.msgprint({ title: __("Email Campaign"), message: msg, indicator: created.length ? "green" : "orange" });
							listview.refresh();
						});
					},
				});
				dialog.show();
			});

			listview.page.add_actions_menu_item(__("Add to Lead Group"), () => {
				const leads = listview.get_checked_items().map((d) => d.name);
				if (!leads.length) {
					frappe.msgprint(__("Select at least one Lead first."));
					return;
				}
				const dialog = new frappe.ui.Dialog({
					title: __("Add {0} Lead(s) to Lead Group", [leads.length]),
					fields: [
						{
							fieldname: "lead_group",
							fieldtype: "Link",
							options: "Lead Group",
							label: __("Lead Group"),
							description: __("Type a new name to create a Lead Group, or pick an existing one."),
							reqd: 1,
						},
					],
					primary_action_label: __("Add"),
					primary_action: (values) => {
						dialog.hide();
						frappe.call({
							method: "lex.lex.doctype.lead_group.lead_group.add_leads",
							args: { name: values.lead_group, leads },
							freeze: true,
							freeze_message: __("Adding to Lead Group..."),
						}).then((r) => {
							const result = r.message || {};
							const added = result.added || [];
							const skipped = result.skipped || [];
							let msg = __("Added {0} Lead(s) to {1}.", [added.length, result.lead_group]);
							if (skipped.length) {
								msg += "<br>" + __("Already in the group: {0}", [skipped.length]);
							}
							frappe.msgprint({ title: __("Lead Group"), message: msg, indicator: added.length ? "green" : "orange" });
							listview.refresh();
						});
					},
				});
				dialog.show();
			});
		},
	});
})();
