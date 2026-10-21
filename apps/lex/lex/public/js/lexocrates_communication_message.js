(function () {
	window.lexocratesCommunicationMessageVersion = "20261016-2";

	const escapeHTML = (value) => {
		if (window.frappe?.utils?.escape_html) return frappe.utils.escape_html(value || "");
		return String(value || "")
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;")
			.replace(/'/g, "&#039;");
	};

	const htmlToText = (html) => {
		const box = document.createElement("div");
		box.innerHTML = html || "";
		box.querySelectorAll("script, style").forEach((node) => node.remove());
		box.querySelectorAll("br").forEach((node) => node.replaceWith("\n"));
		box.querySelectorAll("p, div, blockquote, li").forEach((node) => node.appendChild(document.createTextNode("\n")));
		return box.textContent.replace(/\u00a0/g, " ").replace(/\n{3,}/g, "\n\n").trim();
	};

	const formatDateTime = (value) => {
		if (!value) return { date: __("No date"), time: "", full: __("No date") };
		try {
			const full = frappe.datetime.str_to_user(value);
			const parts = full.split(" ").filter(Boolean);
			return { date: parts[0] || full, time: parts.slice(1).join(" "), full };
		} catch (e) {
			const parts = String(value).split(" ");
			return { date: parts[0] || value, time: parts.slice(1, 3).join(" "), full: value };
		}
	};

	const asLines = (value) => {
		return String(value || "")
			.split(/[;,\n]/)
			.map((item) => item.trim())
			.filter(Boolean);
	};

	const peopleHtml = (label, value, fallback) => {
		const items = asLines(value);
		const rendered = items.length
			? items.slice(0, 6).map((item) => `<span class="lex-comm-person">${escapeHTML(item)}</span>`).join("")
			: `<span class="lex-comm-person is-empty">${escapeHTML(fallback || "—")}</span>`;
		const more = items.length > 6 ? `<span class="lex-comm-more">+${items.length - 6}</span>` : "";
		return `<div class="lex-comm-line"><span class="lex-comm-label">${escapeHTML(label)}</span><div class="lex-comm-people">${rendered}${more}</div></div>`;
	};

	const linkedHtml = (doc) => {
		if (!doc.reference_doctype || !doc.reference_name) return "";
		const href = frappe.utils.get_form_link(doc.reference_doctype, doc.reference_name);
		return `<a class="lex-comm-pill lex-comm-linked" href="${href}"><i class="fa fa-link"></i>${escapeHTML(doc.reference_doctype)}: ${escapeHTML(doc.reference_name)}</a>`;
	};

	const parseQuoteHeader = (line) => {
		const clean = line.replace(/^>\s*/, "").trim();
		const match = clean.match(/^On\s+(.+?),\s*(.+?)\s*wrote:\s*$/i);
		if (!match) return null;
		let date = match[1].trim();
		let sender = match[2].trim();
		const senderMatch = sender.match(/^(.*?)(?:,?\s*)?<([^>]+)>$/);
		if (senderMatch) {
			sender = `${senderMatch[1].replace(/,$/, "").trim() || senderMatch[2]} <${senderMatch[2]}>`;
		}
		return { date, sender };
	};

	const parseThread = (doc) => {
		const text = htmlToText(doc.content || doc.text_content || "");
		if (!text) return [];

		const lines = text.split("\n");
		const messages = [];
		let current = {
			sender: doc.sent_or_received === "Sent" ? doc.user || doc.sender || __("Lexocrates") : doc.sender_full_name || doc.sender || __("Sender"),
			date: formatDateTime(doc.communication_date || doc.creation).full,
			body: [],
			own: doc.sent_or_received === "Sent",
			latest: true,
		};

		for (const line of lines) {
			const header = parseQuoteHeader(line);
			if (header) {
				if (current.body.join("\n").trim()) messages.push(current);
				current = {
					sender: header.sender,
					date: header.date,
					body: [],
					own: /sales@lexocrates\.com|support@lexocrates\.com|lexocrates/i.test(header.sender),
					latest: false,
				};
				continue;
			}
			current.body.push(line.replace(/^>\s?/, ""));
		}
		if (current.body.join("\n").trim()) messages.push(current);

		return messages
			.map((message) => ({ ...message, body: message.body.join("\n").replace(/\n{3,}/g, "\n\n").trim() }))
			.filter((message) => message.body);
	};


	const hasTemplateLayout = (html) => {
		const value = String(html || "");
		const tagCount = (value.match(/<\/?[a-z][\s\S]*?>/gi) || []).length;
		return tagCount > 8 || /<(table|style|img|tbody|tr|td|html|body)\b/i.test(value) || /style=|class=/i.test(value);
	};

	const previewHtml = (doc) => {
		if (!doc.content || !hasTemplateLayout(doc.content)) return "";
		const safeContent = String(doc.content)
			.replace(/<script[\s\S]*?<\/script>/gi, "")
			.replace(/<style[\s\S]*?<\/style>/gi, (style) => style);
		const srcdoc = `<!doctype html><html><head><base target="_blank"><style>
			body{margin:0;padding:18px;background:#fff;color:#0f172a;font-family:Arial,sans-serif;line-height:1.55;}
			table{max-width:100%;}
			img{max-width:100%;height:auto;}
			a{color:#0b1736;}
		</style></head><body>${safeContent}</body></html>`;
		return `
			<section class="lex-email-template-preview-card" data-lex-template-preview="20261007-5">
				<div class="lex-email-template-preview-head">
					<div>
						<span>${__("Email Preview")}</span>
						<h4>${__("Original template view")}</h4>
					</div>
					<div class="lex-email-template-preview-head-right">
						<span class="lex-email-template-preview-pill">HTML</span>
					</div>
				</div>
				<iframe class="lex-email-template-preview-frame" sandbox="allow-popups allow-popups-to-escape-sandbox allow-same-origin" srcdoc="${escapeHTML(srcdoc)}"></iframe>
			</section>
		`;
	};

	const resizeFrame = (frame) => {
		try {
			const height = frame.contentDocument?.documentElement?.scrollHeight || frame.contentDocument?.body?.scrollHeight;
			if (height) frame.style.height = `${Math.min(Math.max(height + 8, 260), 900)}px`;
		} catch (e) {
			frame.style.height = "420px";
		}
	};

	const resizePreviewFrames = (frm) => {
		frm.$wrapper.find(".lex-email-template-preview-frame").each(function () {
			const frame = this;
			frame.addEventListener("load", () => resizeFrame(frame), { once: true });
			setTimeout(() => resizeFrame(frame), 250);
			setTimeout(() => resizeFrame(frame), 1000);
		});
	};

	// The email body reflows (and so needs a new height) whenever the viewport
	// changes width -- bind this once globally rather than per-render so rotating
	// a phone or resizing the window keeps every open preview correctly sized.
	let global_resize_bound = false;
	const bindGlobalResize = () => {
		if (global_resize_bound) return;
		global_resize_bound = true;
		window.addEventListener(
			"resize",
			frappe.utils.debounce(() => {
				document.querySelectorAll(".lex-email-template-preview-frame").forEach(resizeFrame);
			}, 200)
		);
	};

	const threadHtml = (doc) => {
		const messages = parseThread(doc);
		if (!messages.length) return "";
		const bubbles = messages.map((message) => {
			const body = escapeHTML(message.body).replace(/\n/g, "<br>");
			return `
				<article class="lex-email-thread-message ${message.own ? "is-own" : ""} ${message.latest ? "is-latest" : ""}">
					<div class="lex-email-thread-avatar">${escapeHTML((message.sender || "?").trim().charAt(0).toUpperCase() || "?")}</div>
					<div class="lex-email-thread-bubble">
						<div class="lex-email-thread-meta">
							<strong>${escapeHTML(message.sender)}</strong>
							<span>${escapeHTML(message.date)}</span>
						</div>
						<div class="lex-email-thread-body">${body}</div>
					</div>
				</article>
			`;
		}).join("");
		return `
			<section class="lex-email-thread-card" data-lex-thread-ui="20261007-5">
				<div class="lex-email-thread-head">
					<div>
						<span>${__("Conversation View")}</span>
						<h4>${__("Email thread as chat")}</h4>
					</div>
					<span class="lex-email-thread-count">${messages.length} ${messages.length === 1 ? __("message") : __("messages")}</span>
				</div>
				<div class="lex-email-thread-list">${bubbles}</div>
			</section>
		`;
	};

	const historyBubbleHtml = (message, currentSubject) => {
		const own = message.sent_or_received === "Sent";
		const sender = own ? __("You") : message.sender_full_name || message.sender || __("Sender");
		const when = formatDateTime(message.communication_date);
		const subjectLine =
			message.subject && message.subject !== currentSubject
				? `<div class="lex-email-thread-subject">${escapeHTML(message.subject)}</div>`
				: "";
		const attachment = message.has_attachment
			? `<i class="fa fa-paperclip lex-email-thread-attachment" title="${__("Has Attachments")}"></i>`
			: "";
		const body = escapeHTML(message.snippet || "").replace(/\n/g, "<br>");

		return `
			<article class="lex-email-thread-message ${own ? "is-own" : ""} ${message.is_current ? "is-latest" : ""} ${message.is_current ? "" : "is-clickable"}" data-communication="${escapeHTML(message.name)}">
				<div class="lex-email-thread-avatar">${escapeHTML((sender || "?").trim().charAt(0).toUpperCase() || "?")}</div>
				<div class="lex-email-thread-bubble">
					<div class="lex-email-thread-meta">
						<strong>${escapeHTML(sender)}</strong>
						<span>${escapeHTML(when.full)}</span>
						${attachment}
					</div>
					${subjectLine}
					<div class="lex-email-thread-body">${body}</div>
				</div>
			</article>
		`;
	};

	const historyCardHtml = (doc, result) => {
		const messages = result.messages || [];
		if (messages.length <= 1) return "";
		const bubbles = messages.map((message) => historyBubbleHtml(message, doc.subject)).join("");
		return `
			<section class="lex-email-thread-card lex-comm-history-card" data-lex-history-ui="20261016-2">
				<div class="lex-email-thread-head">
					<div>
						<span>${__("Communication History")}</span>
						<h4>${__("Every email exchanged on this record and with this address")}</h4>
					</div>
					<span class="lex-email-thread-count">${messages.length} ${messages.length === 1 ? __("message") : __("messages")}</span>
				</div>
				<div class="lex-email-thread-list">${bubbles}</div>
			</section>
		`;
	};

	const renderHistoryPanel = (frm) => {
		const doc = frm.doc || {};
		if (doc.communication_medium !== "Email" || doc.__islocal) return;

		const contentField = frm.fields_dict?.content?.$wrapper;
		if (!contentField?.length) return;

		const requestedFor = doc.name;
		frappe.call({
			method: "lex.communication_history.get_conversation_history",
			args: { communication: requestedFor },
			callback: (r) => {
				// The form may have navigated to a different Communication (or been
				// reloaded) while this request was in flight -- re-check before
				// touching the DOM so a slow response can't paint a stale thread
				// over whatever the user is looking at now.
				if (frm.doc.name !== requestedFor) return;
				frm.$wrapper.find(".lex-comm-history-card").remove();

				const result = r.message || {};
				const card = $(historyCardHtml(doc, result));
				if (!card.length) return;

				card.insertBefore(contentField);
				card.find(".lex-email-thread-message.is-clickable").on("click", function () {
					const name = $(this).attr("data-communication");
					if (name) frappe.set_route("Form", "Communication", name);
				});
			},
			// This panel is a convenience add-on, not the primary content of the
			// page -- if the lookup fails for any reason (permission edge case,
			// a deleted linked record, etc.) the email itself must still display
			// normally, so swallow the error here instead of letting frappe.call's
			// default handler pop a dialog over it.
			error: () => {},
		});
	};

	const renderPanel = (frm) => {
		const doc = frm.doc || {};
		if (doc.communication_medium !== "Email") return;

		const contentField = frm.fields_dict?.content?.$wrapper;
		if (!contentField?.length) return;

		frm.$wrapper.addClass("lex-communication-form");
		// All three sections are re-inserted below on every refresh (onload_post_render
		// AND refresh both call this) -- without clearing the preview card too, an HTML
		// email (the only kind that gets one) stacks a duplicate "Email Preview" iframe
		// on each refresh, which is what made HTML mail look broken while plain-text
		// mail (no preview card) looked fine.
		frm.$wrapper.find(".lex-communication-message-card, .lex-email-thread-card, .lex-email-template-preview-card").remove();

		const when = formatDateTime(doc.communication_date || doc.creation);
		const direction = doc.sent_or_received || "Email";
		const directionClass = direction === "Received" ? "received" : "sent";
		// When no real display name was ever set, sender_full_name falls back
		// (in frappe's mail_sender_fullname) to the email address itself --
		// showing that back as `"same@address" <same@address>` is just the
		// address twice, so collapse to the plain address in that case.
		const bareAddress = (value) => String(value || "").trim().replace(/^"|"$/g, "").toLowerCase();
		const hasRealName = doc.sender_full_name && doc.sender && bareAddress(doc.sender_full_name) !== bareAddress(doc.sender);
		const senderName = hasRealName ? `${doc.sender_full_name} <${doc.sender}>` : doc.sender || doc.sender_full_name;
		const primaryFrom = senderName || doc.user || "—";
		const status = doc.status || doc.email_status || "Open";
		const relative = typeof comment_when === "function" ? comment_when(doc.communication_date || doc.creation, true) : "";

		const panel = $(`
			<section class="lex-communication-message-card" data-lex-communication-ui="20261007-5">
				<div class="lex-comm-card-head">
					<div class="lex-comm-title-block">
						<span class="lex-comm-eyebrow">${__("Email Message")}</span>
						<h3>${escapeHTML(doc.subject || __("No subject"))}</h3>
					</div>
					<div class="lex-comm-time-block" title="${escapeHTML(when.full)}">
						<span class="lex-comm-time">${escapeHTML(when.time)}</span>
						<span class="lex-comm-date">${escapeHTML(when.date)}</span>
						<span class="lex-comm-relative">${relative}</span>
					</div>
				</div>
				<div class="lex-comm-badges">
					<span class="lex-comm-pill ${directionClass}">${escapeHTML(direction)}</span>
					<span class="lex-comm-pill">${escapeHTML(status)}</span>
					${doc.email_account ? `<span class="lex-comm-pill">${escapeHTML(doc.email_account)}</span>` : ""}
					${linkedHtml(doc)}
				</div>
				<div class="lex-comm-address-grid">
					${peopleHtml(__("From"), primaryFrom)}
					${peopleHtml(__("To"), doc.recipients)}
					${doc.cc ? peopleHtml(__("CC"), doc.cc) : ""}
				</div>
			</section>
		`);

		panel.insertBefore(contentField);
		const preview = $(previewHtml(doc));
		if (preview.length) {
			preview.insertBefore(contentField);
			bindGlobalResize();
		} else {
			// Only fall back to the parsed quote-chain chat bubbles when there's
			// no real HTML to show -- showing both is the same message twice.
			const thread = $(threadHtml(doc));
			if (thread.length) thread.insertBefore(contentField);
		}
		resizePreviewFrames(frm);

		const contentWrapper = contentField.find(".control-input-wrapper, .form-group").first();
		(contentWrapper.length ? contentWrapper : contentField).addClass("lex-communication-body-wrap");
		contentField.find(".ql-editor, .control-value, .like-disabled-input").first().addClass("lex-communication-body");

		if (preview.length) {
			// The Text Editor control re-renders arbitrary email HTML through Quill,
			// which strips most inline styles/layout -- it's the iframe above that
			// shows the email correctly, so keep this raw version out of the way by
			// default rather than displaying a second, visually mangled copy of it.
			contentField.addClass("lex-raw-email-content-hidden");
		} else {
			contentField.addClass("lex-raw-email-content-collapsed");
			const label = contentField.find(".control-label").first();
			if (label.length && !label.find(".lex-raw-email-note").length) {
				label.append(`<span class="lex-raw-email-note">${__("Raw email below")}</span>`);
			}
		}
	};

	// The right-hand document sidebar (Frappe's generic "Modified X ago by ..."
	// / "Created X ago by ..." + heart-shaped Like stat) makes sense for a
	// Task or a Lead, but reads oddly for an email: a message doesn't get
	// "liked", and its header should show the exact moment it was sent/received,
	// not a decaying relative time. Scoped to the Communication doctype only.
	const patchSidebar = () => {
		const Sidebar = frappe.ui.form.Sidebar;
		if (!Sidebar) return false;
		if (Sidebar.__lexocrates_patched === "20261007-5") return true;

		const originalRefresh = Sidebar.prototype.refresh;
		Sidebar.prototype.refresh = function () {
			if (this.frm?.doctype !== "Communication") {
				return originalRefresh.apply(this, arguments);
			}

			const originalCommentWhen = window.comment_when;
			window.comment_when = (datetime) => {
				if (!datetime) return originalCommentWhen(datetime);
				try {
					return frappe.datetime.str_to_user(datetime);
				} catch (e) {
					return originalCommentWhen(datetime);
				}
			};
			let result;
			try {
				result = originalRefresh.apply(this, arguments);
			} finally {
				window.comment_when = originalCommentWhen;
			}

			const likes = this.sidebar.find(".form-stats-likes");
			likes.next(".mx-2").hide();
			likes.hide();

			return result;
		};

		Sidebar.__lexocrates_patched = "20261007-5";
		return true;
	};

	const install = () => {
		if (!window.frappe?.ui?.form) return false;
		const sidebarPatched = patchSidebar();
		if (frappe.ui.form.__lexocrates_communication_message !== "20261016-2") {
			frappe.ui.form.on("Communication", {
				refresh: renderPanel,
				onload_post_render: renderPanel,
			});
			// Registered in a second frappe.ui.form.on call so it lands after
			// renderPanel in the handler list and so runs after it on every
			// refresh -- renderPanel's own DOM cleanup removes any
			// .lex-email-thread-card (a class the history card shares, see
			// historyCardHtml) before re-drawing its own cards, which would
			// wipe out a history card painted earlier in the same refresh.
			frappe.ui.form.on("Communication", {
				refresh: renderHistoryPanel,
				onload_post_render: renderHistoryPanel,
			});
			frappe.ui.form.__lexocrates_communication_message = "20261016-2";
		}
		return sidebarPatched;
	};

	const timer = setInterval(() => {
		if (install()) clearInterval(timer);
	}, 250);
	setTimeout(() => clearInterval(timer), 30000);

	$(document).on("page-change form-refresh", install);
	$(install);
})();
