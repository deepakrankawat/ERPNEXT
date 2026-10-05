(function () {
	window.lexocratesCommunicationMessageVersion = "20261002-3";

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

	const stripName = (value) => String(value || "").replace(/<([^>]+)>/g, "&lt;$1&gt;");

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
			? items.slice(0, 6).map((item) => `<span class="lex-comm-person">${escapeHTML(stripName(item))}</span>`).join("")
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
			<section class="lex-email-template-preview-card" data-lex-template-preview="20261002-3">
				<div class="lex-email-template-preview-head">
					<div>
						<span>${__("Email Preview")}</span>
						<h4>${__("Original template view")}</h4>
					</div>
					<span class="lex-email-template-preview-pill">HTML</span>
				</div>
				<iframe class="lex-email-template-preview-frame" sandbox="allow-popups allow-popups-to-escape-sandbox" srcdoc="${escapeHTML(srcdoc)}"></iframe>
			</section>
		`;
	};

	const resizePreviewFrames = (frm) => {
		frm.$wrapper.find(".lex-email-template-preview-frame").each(function () {
			const frame = this;
			const resize = () => {
				try {
					const height = frame.contentDocument?.documentElement?.scrollHeight || frame.contentDocument?.body?.scrollHeight;
					if (height) frame.style.height = `${Math.min(Math.max(height + 8, 260), 900)}px`;
				} catch (e) {
					frame.style.height = "420px";
				}
			};
			frame.addEventListener("load", resize, { once: true });
			setTimeout(resize, 250);
			setTimeout(resize, 1000);
		});
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
							<strong>${escapeHTML(stripName(message.sender))}</strong>
							<span>${escapeHTML(message.date)}</span>
						</div>
						<div class="lex-email-thread-body">${body}</div>
					</div>
				</article>
			`;
		}).join("");
		return `
			<section class="lex-email-thread-card" data-lex-thread-ui="20261002-3">
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

	const renderPanel = (frm) => {
		const doc = frm.doc || {};
		if (doc.communication_medium !== "Email") return;

		const contentField = frm.fields_dict?.content?.$wrapper;
		if (!contentField?.length) return;

		frm.$wrapper.addClass("lex-communication-form");
		frm.$wrapper.find(".lex-communication-message-card, .lex-email-thread-card").remove();

		const when = formatDateTime(doc.communication_date || doc.creation);
		const direction = doc.sent_or_received || "Email";
		const directionClass = direction === "Received" ? "received" : "sent";
		const senderName = doc.sender_full_name && doc.sender ? `${doc.sender_full_name} <${doc.sender}>` : doc.sender;
		const primaryFrom = senderName || doc.user || "—";
		const status = doc.status || doc.email_status || "Open";
		const relative = typeof comment_when === "function" ? comment_when(doc.communication_date || doc.creation, true) : "";

		const panel = $(`
			<section class="lex-communication-message-card" data-lex-communication-ui="20261002-3">
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
		if (preview.length) preview.insertBefore(contentField);
		const thread = $(threadHtml(doc));
		if (thread.length) thread.insertBefore(contentField);
		resizePreviewFrames(frm);

		contentField.addClass("lex-raw-email-content-collapsed");
		const label = contentField.find(".control-label").first();
		if (label.length && !label.find(".lex-raw-email-note").length) {
			label.append(`<span class="lex-raw-email-note">${__("Raw email below")}</span>`);
		}

		const contentWrapper = contentField.find(".control-input-wrapper, .form-group").first();
		(contentWrapper.length ? contentWrapper : contentField).addClass("lex-communication-body-wrap");
		contentField.find(".ql-editor, .control-value, .like-disabled-input").first().addClass("lex-communication-body");
	};

	const install = () => {
		if (!window.frappe?.ui?.form) return false;
		if (frappe.ui.form.__lexocrates_communication_message === "20261002-3") return true;
		frappe.ui.form.on("Communication", {
			refresh: renderPanel,
			onload_post_render: renderPanel,
		});
		frappe.ui.form.__lexocrates_communication_message = "20261002-3";
		return true;
	};

	const timer = setInterval(() => {
		if (install()) clearInterval(timer);
	}, 250);
	setTimeout(() => clearInterval(timer), 30000);

	$(document).on("page-change form-refresh", install);
	$(install);
})();
