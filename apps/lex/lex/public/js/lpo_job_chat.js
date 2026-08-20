frappe.provide("lex.chat");

(() => {
	const chat = lex.chat;
	const ALLOWED_DOCTYPES = ["LPO Matter", "LPO Job"];
	const API_ROOT = "lex.lex.page.lexocrates_chat.lexocrates_chat";
	if (chat.controller_bound) return;
	chat.controller_bound = true;

	function install_styles() {
		if (document.getElementById("lexocrates-lpo-chat-styles")) return;

		$("<style>", { id: "lexocrates-lpo-chat-styles" })
			.text(`
				.lpo-chat { border: 1px solid var(--border-color); border-radius: var(--border-radius); overflow: hidden; }
				.lpo-chat__header { display: flex; justify-content: space-between; gap: 12px; padding: 11px 12px; border-bottom: 1px solid var(--border-color); background: var(--card-bg); }
				.lpo-chat__header span { color: var(--text-muted); font-size: var(--text-xs); }
				.lpo-chat__history { min-height: 180px; max-height: 420px; overflow-y: auto; padding: 12px; background: var(--subtle-fg); }
				.lpo-chat__message { margin-bottom: 12px; padding: 10px 12px; background: var(--card-bg); border-radius: var(--border-radius); }
				.lpo-chat__meta { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 5px; color: var(--text-muted); font-size: var(--text-xs); }
				.lpo-chat__content > :last-child { margin-bottom: 0; }
				.lpo-chat__composer { padding: 12px; background: var(--card-bg); border-top: 1px solid var(--border-color); }
				.lpo-chat__composer textarea { min-height: 76px; resize: vertical; }
				.lpo-chat__actions { display: flex; justify-content: space-between; gap: 8px; margin-top: 8px; }
				.lpo-chat__job-refs { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 7px; }
				.lpo-chat__job-ref { padding: 3px 8px; border: 1px solid var(--blue-200); border-radius: 999px; background: var(--blue-50); color: var(--blue-700); font-size: var(--text-xs); font-weight: 600; }
				.lpo-chat__job-ref span { margin-left: 6px; color: var(--text-muted); font-weight: 400; }
				.lpo-chat__empty { padding: 50px 12px; text-align: center; color: var(--text-muted); }
			`)
			.appendTo(document.head);
	}

	function get_wrapper(frm) {
		const html_field = frm.fields_dict.chat_interface_html;
		if (html_field) {
			return html_field.$wrapper.empty();
		}

		if (!frm.__lpo_chat_dashboard_wrapper) {
			frm.__lpo_chat_dashboard_wrapper = frm.dashboard.add_section(
				"",
				__("Secure LPO Communication"),
				"lpo-chat-dashboard"
			);
		}
		frm.dashboard.show();
		return frm.__lpo_chat_dashboard_wrapper.empty();
	}

	function render_shell(frm) {
		const $wrapper = get_wrapper(frm);
		$wrapper.html(`
			<div class="lpo-chat">
				<div class="lpo-chat__header"><strong>${__("Matter Room")}</strong><span>${__("Loading context")}</span></div>
				<div class="lpo-chat__history" role="log" aria-live="polite">
					<div class="lpo-chat__empty">${__("Loading secure conversation…")}</div>
				</div>
				<div class="lpo-chat__composer">
					<textarea class="form-control lpo-chat__input" maxlength="10000" placeholder="${__("Write a message")}"></textarea>
					<div class="lpo-chat__actions">
						<button type="button" class="btn btn-default btn-sm lpo-chat__job-mention" disabled>${__("@ Job")}</button>
						<button type="button" class="btn btn-primary btn-sm lpo-chat__send">${__("Send")}</button>
					</div>
				</div>
			</div>
		`);
		return $wrapper;
	}

	function render_message($history, data) {
		if (!data?.name || $history.find(`[data-message-name="${CSS.escape(data.name)}"]`).length) return;

		const sender = frappe.utils.escape_html(data.sender_full_name || data.sender || "");
		const timestamp = frappe.utils.escape_html(data.formatted_timestamp || data.timestamp || "");
		const $message = $(
			`<article class="lpo-chat__message" data-message-name="${frappe.utils.escape_html(data.name)}">
				<div class="lpo-chat__meta"><strong>${sender}</strong><time>${timestamp}</time></div>
				<div class="lpo-chat__content"></div>
			</article>`
		);
		// The server sanitizes Text Editor HTML before persistence. Rendering that
		// committed value preserves formatting without trusting browser input.
		$message.find(".lpo-chat__content").html(data.message_text || "");
		if (data.job_mentions?.length) {
			$message.append(
				`<div class="lpo-chat__job-refs">${data.job_mentions.map((job) => `<a class="lpo-chat__job-ref" href="/app/lpo-job/${encodeURIComponent(job.name)}">@${frappe.utils.escape_html(job.name)}<span>${frappe.utils.escape_html(job.status || "")}</span></a>`).join("")}</div>`
			);
		}
		$history.find(".lpo-chat__empty").remove();
		$history.append($message);
		$history.scrollTop($history[0].scrollHeight);
	}

	function deactivate() {
		if (chat.channel) {
			frappe.realtime.doc_unsubscribe("Lexocrates Chat Channel", chat.channel);
		}
		if (chat.listener) {
			frappe.realtime.off("new_chat_message", chat.listener);
		}
		chat.channel = null;
		chat.listener = null;
		chat.frm = null;
	}

	async function initialize(frm) {
		install_styles();
		const $wrapper = render_shell(frm);
		const $history = $wrapper.find(".lpo-chat__history");
		const $header = $wrapper.find(".lpo-chat__header");
		const $input = $wrapper.find(".lpo-chat__input");
		const $send = $wrapper.find(".lpo-chat__send");
		const $job_mention = $wrapper.find(".lpo-chat__job-mention");
		deactivate();
		chat.frm = frm;
		chat.generation = (chat.generation || 0) + 1;
		const generation = chat.generation;

		if (frm.is_new()) {
			$history.html(`<div class="lpo-chat__empty">${__("Save this record to start its secure conversation.")}</div>`);
			$input.prop("disabled", true);
			$send.prop("disabled", true);
			return;
		}

		try {
			const response = await frappe.call({
				method: `${API_ROOT}.get_or_create_contextual_channel`,
				args: { reference_doctype: frm.doctype, reference_name: frm.docname },
			});
			if (chat.generation !== generation || chat.frm !== frm) return;
			const channel = response.message;
			chat.channel = channel.name;
			$header.html(
				`<strong>${__("Matter Room")}</strong><span>${frappe.utils.escape_html(channel.display_name || channel.channel_name)} · ${frappe.utils.escape_html(channel.reference_name || "")}</span>`
			);
			$job_mention.prop("disabled", !["LPO Matter", "LPO Job"].includes(channel.reference_doctype));

			chat.listener = (data) => {
				if (data.channel === chat.channel) {
					render_message($history, data);
					frappe.call({ method: `${API_ROOT}.mark_channel_read`, args: { channel: chat.channel, message_name: data.name }, freeze: false }).catch(() => {});
				}
			};
			frappe.realtime.on("new_chat_message", chat.listener);

			// Form loading already consumes Frappe's throttled doc_subscribe call for
			// the Job/Engagement. Emitting directly joins the separate Channel room;
			// the Socket.IO server still calls can_subscribe_doc and enforces RBAC.
			frappe.realtime.emit("doc_subscribe", "Lexocrates Chat Channel", channel.name);

			const history_response = await frappe.call({
				method: `${API_ROOT}.get_messages`,
				args: { channel: channel.name },
			});
			if (chat.generation !== generation || chat.frm !== frm) return;
			$history.empty();
			const messages = history_response.message || [];
			if (!messages.length) {
				$history.html(`<div class="lpo-chat__empty">${__("No messages yet.")}</div>`);
			} else {
				messages.forEach((message) => render_message($history, message));
			}
			frappe.call({ method: `${API_ROOT}.mark_channel_read`, args: { channel: channel.name, message_name: messages.at(-1)?.name }, freeze: false }).catch(() => {});

			const send = async () => {
				const content = $input.val().trim();
				if (!content || $send.prop("disabled")) return;
				const safe_html = frappe.utils.escape_html(content).replace(/\n/g, "<br>");

				$send.prop("disabled", true);
				try {
					const response = await frappe.call({
						method: `${API_ROOT}.send_message`,
						args: {
							channel: channel.name,
							message_text: safe_html,
						},
					});
					if (response.message) render_message($history, response.message);
					$input.val("");
					// Intentionally no local append: only the after-commit realtime event
					// may place a message into the legal audit-trail UI.
				} finally {
					$send.prop("disabled", false);
					$input.trigger("focus");
				}
			};

			$send.on("click", send);
			$job_mention.on("click", async () => {
				const jobs_response = await frappe.call({
					method: `${API_ROOT}.get_channel_jobs`,
					args: { channel: channel.name, limit: 100 },
				});
				const jobs = jobs_response.message || [];
				if (!jobs.length) {
					frappe.show_alert({ message: __("No related Jobs are available in this Matter."), indicator: "orange" });
					return;
				}
				const dialog = new frappe.ui.Dialog({
					title: __("Mention a related Job"),
					fields: [{ fieldname: "job", fieldtype: "Select", label: __("Job"), reqd: 1, options: jobs.map((job) => job.name) }],
					primary_action_label: __("Insert Job mention"),
					primary_action: (values) => {
						const current = $input.val();
						$input.val(`${current}${current && !/\s$/.test(current) ? " " : ""}@${values.job} `).trigger("focus");
						dialog.hide();
					},
				});
				dialog.show();
			});
			$input.on("keydown", (event) => {
				if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
					event.preventDefault();
					send();
				}
			});
		} catch (error) {
			if (chat.generation !== generation || chat.frm !== frm) return;
			$history.html(`<div class="lpo-chat__empty text-danger">${__("The secure conversation could not be loaded.")}</div>`);
			$input.prop("disabled", true);
			$send.prop("disabled", true);
			console.error("LPO Operation chat initialization failed", error);
		}
	}

	if (!chat.route_cleanup_bound) {
		frappe.router.on("change", () => {
			const route = frappe.get_route();
			if (!(route[0] === "Form" && ALLOWED_DOCTYPES.includes(route[1]))) deactivate();
		});
		chat.route_cleanup_bound = true;
	}

	ALLOWED_DOCTYPES.forEach((doctype) => {
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				initialize(frm);
			},
		});
	});
})();
