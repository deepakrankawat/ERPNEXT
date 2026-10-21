(function () {
	window.lexocratesEmailInboxPatchVersion = "20261007-1";

	const escapeHTML = (value) => {
		if (window.frappe?.utils?.escape_html) {
			return frappe.utils.escape_html(value || "");
		}
		return String(value || "")
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;")
			.replace(/'/g, "&#039;");
	};

	const formatWhen = (value) => {
		if (!value) {
			return { date: __("No date"), time: "", tooltip: __("No communication date") };
		}

		let date = "";
		let time = "";
		let tooltip = value;

		try {
			const parts = frappe.datetime.str_to_user(value).split(" ").filter(Boolean);
			date = parts[0] || value;
			time = parts.slice(1).join(" ");
			tooltip = frappe.datetime.str_to_user(value);
		} catch (e) {
			const parts = String(value).split(" ");
			date = parts[0] || value;
			time = parts.slice(1, 3).join(" ");
		}

		return { date, time, tooltip };
	};

	const isInboxRoute = () => {
		const route = window.frappe?.get_route ? frappe.get_route() : [];
		return String(route?.[0] || "").toLowerCase() === "list"
			&& String(route?.[1] || "").toLowerCase() === "communication"
			&& String(route?.[2] || "").toLowerCase() === "inbox";
	};

	const buildMetaHtml = function (email) {
		const when = formatWhen(email.communication_date || email.creation);
		const attachment = email.has_attachment
			? `<span class="lex-email-chip" title="${__("Has Attachments")}"><i class="fa fa-paperclip"></i></span>`
			: "";

		const status =
			email.status === "Closed"
				? `<span class="lex-email-chip lex-email-chip-success" title="${__("Closed")}"><i class="fa fa-check"></i></span>`
				: email.status === "Replied"
				? `<span class="lex-email-chip lex-email-chip-info" title="${__("Replied")}"><i class="fa fa-mail-reply"></i></span>`
				: "";

		let linked = "";
		if (email.reference_doctype && email.reference_doctype !== this.doctype && email.reference_name) {
			const label = `${email.reference_doctype}: ${email.reference_name}`;
			linked = `<a class="lex-email-link-pill" href="${frappe.utils.get_form_link(
				email.reference_doctype,
				email.reference_name
			)}" title="${escapeHTML(label)}">
				<i class="fa fa-link"></i>
				<span>${escapeHTML(email.reference_doctype)}</span>
			</a>`;
		}

		return `
			<div class="level-item list-row-activity lex-email-inbox-meta" data-lex-email-ui="20261007-1">
				<div class="lex-email-meta-top">
					${linked}
					${attachment}
					${status}
				</div>
				<div class="lex-email-timebox" title="${escapeHTML(when.tooltip)}">
					<span class="lex-email-time">${escapeHTML(when.time)}</span>
					<span class="lex-email-date">${escapeHTML(when.date)}</span>
				</div>
			</div>
		`;
	};

	const refreshOpenInbox = () => {
		if (isInboxRoute() && window.cur_list?.view_name === "Inbox" && cur_list.doctype === "Communication") {
			setTimeout(() => cur_list.render && cur_list.render(), 50);
		}
	};

	const patchInbox = () => {
		if (!window.frappe?.views?.InboxView) {
			return false;
		}

		const InboxView = frappe.views.InboxView;
		if (InboxView.__lexocrates_inbox_patched === "20261007-1") {
			return true;
		}

		const originalRender = InboxView.prototype.render;
		InboxView.prototype.get_meta_html = buildMetaHtml;
		InboxView.prototype.render = function () {
			const result = originalRender.apply(this, arguments);
			this.$result?.addClass("lex-email-inbox-list");

			// The one column used for every row is always fieldname "sender"
			// once a specific account / "All Accounts" mixes Sent in with
			// Received (get_inbox_filters no longer forces
			// sent_or_received="Received" there -- see below), because
			// setup_columns() picks that fieldname once for the whole list,
			// not per row. Left alone, every Sent row would show *our own*
			// account's address under "From" instead of who it was actually
			// sent to. Fix the displayed text per row instead: the sender's
			// full name (fetched via communication_list.js's add_fields) for
			// Received, the recipient address for Sent -- there's no stored
			// display name for recipients, so that one stays as an address.
			// Edited as DOM text only, never doc.sender/doc.recipients
			// themselves, so the column's data-filter attribute still points
			// at the real address and click-to-filter keeps working.
			const display_by_name = {};
			(this.data || []).forEach((doc) => {
				if (doc.sent_or_received === "Sent") {
					if (doc.recipients) display_by_name[doc.name] = doc.recipients;
				} else if (doc.sender_full_name && doc.sender_full_name !== doc.sender) {
					display_by_name[doc.name] = doc.sender_full_name;
				}
			});
			if (Object.keys(display_by_name).length) {
				this.$result?.find(".list-row-container").each(function () {
					const row_name = $(this).find(".list-row-checkbox").attr("data-name");
					const display = display_by_name[row_name];
					if (!display) return;
					$(this)
						.find('a.filterable[data-filter^="sender,"], a.filterable[data-filter^="recipients,"]')
						.each(function () {
							$(this).text(display);
						});
				});
			}

			return result;
		};

		// Picking a specific mailbox (e.g. "Hr") should show that account's
		// full conversation -- what it sent as well as what it received --
		// not just currently-"Open" inbound messages. Frappe's own filter
		// here scopes to sent_or_received="Received" and status="Open",
		// which silently hides replied/linked/closed threads even though
		// they plainly belong to this account (reported: a received Gmail
		// reply wasn't showing under its account because its status had
		// already moved on from "Open" to "Linked"/"Replied").
		const originalGetInboxFilters = InboxView.prototype.get_inbox_filters;
		InboxView.prototype.get_inbox_filters = function () {
			const email_account = this.email_account;
			if (!email_account || ["Sent", "Spam", "Trash"].includes(email_account)) {
				return originalGetInboxFilters.apply(this, arguments);
			}
			// "All Accounts" means every mailbox the user can see, not the
			// literal string "All Accounts" -- same list core Frappe resolves
			// to in its own (otherwise Received+Open-only) branch below.
			let op = "=";
			let value = email_account;
			if (email_account === "All Accounts") {
				op = "in";
				value = frappe.boot.all_accounts;
			}
			return [
				["Communication", "communication_type", "=", "Communication", true],
				["Communication", "communication_medium", "=", "Email", true],
				["Communication", "email_account", op, value, true],
				["Communication", "email_status", "not in", "Spam,Trash", true],
			];
		};

		InboxView.__lexocrates_inbox_patched = "20261007-1";
		refreshOpenInbox();
		return true;
	};

	const install = () => {
		patchInbox();
		setTimeout(patchInbox, 250);
		setTimeout(patchInbox, 1000);
		setTimeout(refreshOpenInbox, 1200);
	};

	const timer = setInterval(() => {
		if (patchInbox()) {
			clearInterval(timer);
		}
	}, 250);
	setTimeout(() => clearInterval(timer), 30000);

	if (window.frappe?.router?.on) {
		frappe.router.on("change", install);
	}
	$(document).on("page-change list-refresh", install);
	$(install);
})();
