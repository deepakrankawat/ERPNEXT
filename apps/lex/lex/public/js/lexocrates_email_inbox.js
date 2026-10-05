(function () {
	window.lexocratesEmailInboxPatchVersion = "20261002-2";

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
			return { date: __("No date"), time: "", tooltip: __("No communication date"), relative: "" };
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

		return {
			date,
			time,
			tooltip,
			relative: typeof comment_when === "function" ? comment_when(value, true) : "",
		};
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
			<div class="level-item list-row-activity lex-email-inbox-meta" data-lex-email-ui="20261002-2">
				<div class="lex-email-meta-top">
					${linked}
					${attachment}
					${status}
				</div>
				<div class="lex-email-timebox" title="${escapeHTML(when.tooltip)}">
					<span class="lex-email-time">${escapeHTML(when.time)}</span>
					<span class="lex-email-date">${escapeHTML(when.date)}</span>
					<span class="lex-email-relative">${when.relative}</span>
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
		if (InboxView.__lexocrates_inbox_patched === "20261002-2") {
			return true;
		}

		const originalRender = InboxView.prototype.render;
		InboxView.prototype.get_meta_html = buildMetaHtml;
		InboxView.prototype.render = function () {
			const result = originalRender.apply(this, arguments);
			this.$result?.addClass("lex-email-inbox-list");
			return result;
		};
		InboxView.__lexocrates_inbox_patched = "20261002-2";
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
