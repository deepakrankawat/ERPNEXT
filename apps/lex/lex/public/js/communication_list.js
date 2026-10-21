(() => {
	const existing = frappe.listview_settings["Communication"] || {};
	const existing_onload = existing.onload;

	frappe.listview_settings["Communication"] = Object.assign({}, existing, {
		// The "sender" field only ever holds the raw email address (see
		// frappe.email.receive.Email._build_communication_doc, which sets
		// sender: self.from_email) -- the display name lives separately in
		// sender_full_name. Fetch it too so the Inbox row can show the name
		// instead of the address (see lexocrates_email_inbox.js, which swaps
		// it in at render time).
		add_fields: [...(existing.add_fields || []), "sender_full_name"],
		// "ID" is auto-appended by Frappe's list view whenever title_field (here
		// "subject") differs from "name" -- not useful next to the subject text.
		hide_name_column: true,
		onload(listview) {
			// frappe's own communication_list.js (loaded separately, by
			// doctype-folder convention -- adds "Mark as Read/Unread") sets
			// frappe.listview_settings["Communication"] too, and load order
			// between it and this hook-loaded file isn't guaranteed --
			// whichever runs second would otherwise wipe the other's onload
			// entirely. Chain them instead of replacing.
			if (typeof existing_onload === "function") existing_onload(listview);

			listview.page.add_actions_menu_item(__("Add Sender to Email Group"), () => {
				const communications = listview.get_checked_items().map((d) => d.name);
				if (!communications.length) {
					frappe.msgprint(__("Select at least one email first."));
					return;
				}
				const dialog = new frappe.ui.Dialog({
					title: __("Add {0} Sender(s) to Email Group", [communications.length]),
					fields: [
						{
							fieldname: "email_group",
							fieldtype: "Link",
							options: "Email Group",
							label: __("Email Group"),
							description: __("Type a new name to create an Email Group, or pick an existing one."),
							reqd: 1,
						},
					],
					primary_action_label: __("Add"),
					primary_action: (values) => {
						dialog.hide();
						frappe.call({
							method: "lex.email_campaign_scheduler.add_communications_to_email_group",
							args: { communications, email_group: values.email_group },
							freeze: true,
							freeze_message: __("Adding to Email Group..."),
						}).then((r) => {
							const result = r.message || {};
							const added = result.added || [];
							const skipped = result.skipped || [];
							let msg = __("Added {0} sender(s) to {1}.", [added.length, result.email_group]);
							if (skipped.length) {
								msg += "<br>" + __("Skipped {0}:", [skipped.length]) + "<ul>" +
									skipped.map((s) => `<li>${frappe.utils.escape_html(s.email || s.communication)} — ${frappe.utils.escape_html(s.reason)}</li>`).join("") + "</ul>";
							}
							frappe.msgprint({ title: __("Email Group"), message: msg, indicator: added.length ? "green" : "orange" });
							listview.refresh();
						});
					},
				});
				dialog.show();
			});
		},
	});

	// "Comment Type" is a hidden internal field (always empty on a real email,
	// Frappe's activity log uses it) that still shows up as a list column
	// because it's flagged in_list_view in core -- and the stock right-hand
	// meta row shows a decaying "X ago" plus a like count, neither useful for
	// an email list. Patch ListView itself (there's no per-doctype hook for
	// either), scoped to Communication only so every other doctype's list is
	// untouched.
	const patchListView = () => {
		const ListView = frappe.views.ListView;
		if (!ListView) return false;
		if (ListView.__lexocrates_comm_list_patched === "20261008-1") return true;

		const originalFieldsInListView = ListView.prototype.get_fields_in_list_view;
		ListView.prototype.get_fields_in_list_view = function () {
			const fields = originalFieldsInListView.apply(this, arguments);
			if (this.doctype !== "Communication") return fields;
			return fields.filter((df) => df.fieldname !== "comment_type");
		};

		const originalGetMetaHtml = ListView.prototype.get_meta_html;
		ListView.prototype.get_meta_html = function (doc) {
			if (this.doctype !== "Communication") return originalGetMetaHtml.apply(this, arguments);

			const value = doc.communication_date || doc.modified;
			let date = "";
			let time = "";
			let tooltip = "";
			try {
				tooltip = frappe.datetime.str_to_user(value);
				const parts = tooltip.split(" ").filter(Boolean);
				date = parts[0] || tooltip;
				time = parts.slice(1).join(" ");
			} catch (e) {
				date = value || "";
				tooltip = value || "";
			}

			return `
				<div class="level-item list-row-activity hidden-xs lex-email-timebox" title="${frappe.utils.escape_html(tooltip)}">
					<span class="lex-email-time">${frappe.utils.escape_html(time)}</span>
					<span class="lex-email-date">${frappe.utils.escape_html(date)}</span>
				</div>
				<div class="level-item visible-xs text-right">
					${this.get_indicator_html(doc)}
				</div>
			`;
		};

		ListView.__lexocrates_comm_list_patched = "20261008-1";
		return true;
	};

	const timer = setInterval(() => {
		if (patchListView()) clearInterval(timer);
	}, 250);
	setTimeout(() => clearInterval(timer), 30000);
	$(document).on("page-change list-refresh", patchListView);
	$(patchListView);
})();
