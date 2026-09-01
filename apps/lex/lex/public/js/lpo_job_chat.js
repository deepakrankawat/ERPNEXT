frappe.provide("lex.chat");
frappe.provide("lex.ai");

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
				.lpo-chat { border: 1px solid var(--border-color); border-radius: 8px; overflow: hidden; margin-bottom: 20px; }
				.lpo-chat__header { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 12px 16px; border-bottom: 1px solid var(--border-color); background: var(--card-bg); }
				.lpo-chat__header span { color: var(--text-muted); font-size: var(--text-xs); }
				.lpo-chat__history { min-height: 180px; max-height: 380px; overflow-y: auto; padding: 14px; background: var(--subtle-fg); }
				.lpo-chat__message { margin-bottom: 12px; padding: 10px 14px; background: var(--card-bg); border-radius: 8px; border: 1px solid var(--border-color); }
				.lpo-chat__meta { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 5px; color: var(--text-muted); font-size: var(--text-xs); }
				.lpo-chat__content > :last-child { margin-bottom: 0; }
				.lpo-chat__composer { padding: 12px 16px; background: var(--card-bg); border-top: 1px solid var(--border-color); }
				.lpo-chat__composer textarea { min-height: 76px; resize: vertical; border-radius: 6px; }
				.lpo-chat__actions { display: flex; justify-content: space-between; gap: 8px; margin-top: 8px; }
				.lpo-chat__job-refs { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 7px; }
				.lpo-chat__job-ref { padding: 3px 8px; border: 1px solid var(--blue-200); border-radius: 999px; background: var(--blue-50); color: var(--blue-700); font-size: var(--text-xs); font-weight: 600; }
				.lpo-chat__job-ref span { margin-left: 6px; color: var(--text-muted); font-weight: 400; }
				.lpo-chat__empty { padding: 40px 12px; text-align: center; color: var(--text-muted); }

				/* AI Copilot & Matter Review Styles */
				.lex-ai-card { border: 1px solid #0284c7; border-radius: 8px; background: #f8fafc; overflow: hidden; margin: 12px 0 24px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
				.lex-ai-header { background: #0f172a; color: #ffffff; padding: 12px 18px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
				.lex-ai-header h4 { margin: 0; color: #ffffff; font-size: 15px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
				.lex-ai-badge { display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; border-radius: 999px; font-size: 11px; font-weight: 600; }
				.lex-ai-badge--token { background: rgba(2, 132, 199, 0.25); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.4); }
				.lex-ai-badge--pass { background: #dcfce7; color: #166534; }
				.lex-ai-badge--warn { background: #fef3c7; color: #92400e; }

				.lex-ai-controls { padding: 12px 18px; background: #ffffff; border-bottom: 1px solid #e2e8f0; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
				.lex-ai-controls select { padding: 5px 10px; border-radius: 6px; border: 1px solid #cbd5e1; font-size: 13px; font-weight: 500; }

				.lex-ai-body { padding: 16px 18px; max-height: 380px; overflow-y: auto; background: #f8fafc; }
				.lex-ai-msg { margin-bottom: 12px; padding: 12px 14px; border-radius: 8px; font-size: 13.5px; line-height: 1.5; }
				.lex-ai-msg--user { background: #e0f2fe; color: #0369a1; border-left: 4px solid #0284c7; margin-left: 30px; }
				.lex-ai-msg--ai { background: #ffffff; color: #1e293b; border: 1px solid #e2e8f0; border-left: 4px solid #10b981; margin-right: 30px; }
				.lex-ai-msg-header { font-size: 11px; font-weight: 700; text-transform: uppercase; margin-bottom: 4px; color: #64748b; }

				.lex-ai-footer { padding: 12px 18px; background: #ffffff; border-top: 1px solid #e2e8f0; }
				.lex-ai-input-row { display: flex; gap: 8px; }
				.lex-ai-input-row textarea { flex: 1; min-height: 56px; border-radius: 6px; border: 1px solid #cbd5e1; padding: 8px 12px; font-size: 13px; resize: vertical; }

				/* Matter Review Table */
				.lex-matter-table { width: 100%; border-collapse: collapse; margin-top: 10px; background: #ffffff; border-radius: 6px; overflow: hidden; border: 1px solid #e2e8f0; }
				.lex-matter-table th { background: #0f172a; color: #ffffff; padding: 10px 14px; font-size: 12px; text-align: left; font-weight: 600; }
				.lex-matter-table td { padding: 10px 14px; border-bottom: 1px solid #f1f5f9; font-size: 13px; vertical-align: middle; }
				.lex-matter-table tr:hover { background-color: #f8fafc; }
			`)
			.appendTo(document.head);
	}

	// -------------------------------------------------------------
	// 1. Matter Chat Interface
	// -------------------------------------------------------------
	function get_chat_wrapper(frm) {
		const html_field = frm.fields_dict.chat_interface_html;
		if (html_field) return html_field.$wrapper.empty();
		if (!frm.__lpo_chat_dashboard_wrapper) {
			frm.__lpo_chat_dashboard_wrapper = frm.dashboard.add_section("", __("Secure LPO Communication"), "lpo-chat-dashboard");
		}
		frm.dashboard.show();
		return frm.__lpo_chat_dashboard_wrapper.empty();
	}

	function render_chat_shell(frm) {
		const $wrapper = get_chat_wrapper(frm);
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

	function render_chat_message($history, data) {
		if (!data?.name || $history.find(`[data-message-name="${CSS.escape(data.name)}"]`).length) return;
		const sender = frappe.utils.escape_html(data.sender_full_name || data.sender || "");
		const timestamp = frappe.utils.escape_html(data.formatted_timestamp || data.timestamp || "");
		const $message = $(
			`<article class="lpo-chat__message" data-message-name="${frappe.utils.escape_html(data.name)}">
				<div class="lpo-chat__meta"><strong>${sender}</strong><time>${timestamp}</time></div>
				<div class="lpo-chat__content"></div>
			</article>`
		);
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

	function deactivate_chat() {
		chat.realtime_unsubscribe?.();
		chat.realtime_unsubscribe = null;
		if (chat.channel && !window.lexocratesReliableChat) frappe.realtime.doc_unsubscribe("Lexocrates Chat Channel", chat.channel);
		if (chat.listener && !window.lexocratesReliableChat) frappe.realtime.off("new_chat_message", chat.listener);
		chat.channel = null;
		chat.listener = null;
		chat.frm = null;
	}

	async function initialize_chat(frm) {
		install_styles();
		const $wrapper = render_chat_shell(frm);
		const $history = $wrapper.find(".lpo-chat__history");
		const $header = $wrapper.find(".lpo-chat__header");
		const $input = $wrapper.find(".lpo-chat__input");
		const $send = $wrapper.find(".lpo-chat__send");
		const $job_mention = $wrapper.find(".lpo-chat__job-mention");
		deactivate_chat();
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
					render_chat_message($history, data);
					frappe.call({ method: `${API_ROOT}.mark_channel_read`, args: { channel: chat.channel, message_name: data.name }, freeze: false }).catch(() => {});
				}
			};
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
				messages.forEach((message) => render_chat_message($history, message));
			}
			const latest_sequence = Math.max(0, ...messages.map((message) => Number(message.channel_sequence || 0)));
			if (window.lexocratesReliableChat) {
				chat.realtime_unsubscribe = window.lexocratesReliableChat.subscribe(channel.name, {
					afterSequence: latest_sequence,
					onMessage: chat.listener,
				});
			} else {
				frappe.realtime.on("new_chat_message", chat.listener);
				frappe.realtime.emit("doc_subscribe", "Lexocrates Chat Channel", channel.name);
			}
			frappe.call({ method: `${API_ROOT}.mark_channel_read`, args: { channel: channel.name, message_name: messages.at(-1)?.name }, freeze: false }).catch(() => {});

			const send = async () => {
				const content = $input.val().trim();
				if (!content || $send.prop("disabled")) return;
				const safe_html = frappe.utils.escape_html(content).replace(/\n/g, "<br>");
				$send.prop("disabled", true);
				try {
					const args = { channel: channel.name, message_text: safe_html };
					const message = window.lexocratesReliableChat
						? await window.lexocratesReliableChat.send({ method: `${API_ROOT}.send_message`, args })
						: (await frappe.call({ method: `${API_ROOT}.send_message`, args })).message;
					if (message) render_chat_message($history, message);
					$input.val("");
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
					fields: [{ fieldname: "job", fieldtype: "Select", label: __("Job"), reqd: 1, options: jobs.map((j) => j.name) }],
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
		}
	}

	// -------------------------------------------------------------
	// 2. Job AI Legal Copilot (with 200 Token Budget & Dynamic Model Selection)
	// -------------------------------------------------------------
	async function initialize_job_ai_copilot(frm) {
		if (frm.doctype !== "LPO Job") return;
		install_styles();

		const $wrapper = frm.fields_dict.ai_copilot_html?.$wrapper;
		if (!$wrapper) return;
		$wrapper.empty();

		if (frm.is_new()) {
			$wrapper.html(`<div class="text-muted p-3">${__("Save Job to enable the AI Legal Copilot.")}</div>`);
			return;
		}

		// Fetch Provider Config
		let config = { default_provider: "", default_credential: "", default_max_tokens: 2000, providers: {}, credentials: [], routes: {} };
		let config_error = false;
		let attachment_info = { eligible: [], eligible_count: 0, skipped_count: 0 };

		try {
			const res = await frappe.call({ method: "lex.lex.doctype.lpo_ai_settings.lpo_ai_settings.get_ai_provider_config" });
			if (res.message) config = res.message;
		} catch (e) {
			config_error = true;
		}
		try {
			const attachment_res = await frappe.call({
				method: "lex.ai_gateway.get_job_ai_attachments",
				args: { job_id: frm.doc.name },
			});
			if (attachment_res.message) attachment_info = attachment_res.message;
		} catch (e) {
			// The backend will perform the authoritative attachment check on send.
		}

		const token_budget = frm.doc.ai_token_budget || config.default_max_tokens || 200;
		const tokens_used = frm.doc.ai_tokens_used || 0;
		const tokens_remaining = Math.max(0, token_budget - tokens_used);

		const active_providers = Object.entries(config.providers || {}).filter(([name, p]) => p.enabled && p.has_key && p.models?.length);
		const active_credentials = (config.credentials || []).filter((item) => item.enabled && item.has_key && item.models?.length);
		const has_any_provider = active_providers.length > 0;
		const preferred_credential = config.routes?.job_chat || config.default_credential || active_credentials[0]?.credential_name || "";
		const ready_documents = attachment_info.eligible || [];
		const ready_document_names = ready_documents.map((doc) => doc.file_name).join(", ");
		const has_ready_documents = ready_documents.length > 0;

		const $card = $(`
			<div class="lex-ai-card">
				<div class="lex-ai-header">
					<h4>Lexocrates Legal Copilot</h4>
					<div class="d-flex align-items-center gap-2 flex-wrap">
						<span class="lex-ai-badge lex-ai-badge--token" id="token-badge">
							Budget: <strong>${tokens_used}</strong> / <strong>${token_budget}</strong> tokens (${tokens_remaining} left)
						</span>
						<button class="btn btn-xs btn-outline-light btn-add-tokens" data-amount="500" style="font-size:11px; font-weight:600;">+500 Tokens</button>
						<button class="btn btn-xs btn-outline-light btn-add-tokens" data-amount="1000" style="font-size:11px; font-weight:600;">+1000 Tokens</button>
						<button class="btn btn-xs btn-default btn-launch-doc-studio" style="color:#0284c7; font-weight:700; background:#ffffff;">Document Studio</button>
						<button class="btn btn-xs btn-default btn-review-job" style="color:#0f172a; font-weight:600;">Run AI Review</button>
					</div>
				</div>
				<div class="lex-ai-controls">
					<div class="d-flex align-items-center gap-2">
						<label class="mb-0 font-weight-bold text-muted">${__("API:")}</label>
						<select class="form-control-sm" id="copilot-credential" ${!active_credentials.length ? "disabled" : ""}>
							${active_credentials.length ? active_credentials.map((item) => `
								<option value="${frappe.utils.escape_html(item.credential_name)}" ${preferred_credential === item.credential_name ? "selected" : ""}>
									${frappe.utils.escape_html(item.credential_name)}
								</option>
							`).join("") : `<option value="">(Legacy provider key)</option>`}
						</select>
						<label class="mb-0 font-weight-bold text-muted">${__("Model:")}</label>
						<select class="form-control-sm" id="copilot-provider">
							${has_any_provider ? active_providers.map(([name, p]) => `
								<option value="${frappe.utils.escape_html(name)}" ${config.default_provider === name ? "selected" : ""}>
									${frappe.utils.escape_html(name)}
								</option>
							`).join("") : `<option value="">(No verified AI model)</option>`}
						</select>
						<select class="form-control-sm" id="copilot-model" ${!has_any_provider ? "disabled" : ""}></select>
					</div>
					<div class="d-flex align-items-center gap-2 ml-auto flex-wrap">
						<label class="mb-0 font-weight-bold text-muted">${__("Limit:")}</label>
						<select class="form-control-sm" id="copilot-token-limit">
							<option value="200" selected>200 Tokens (Quick Q&A)</option>
							<option value="500">500 Tokens (Summary)</option>
							<option value="1000">1000 Tokens (Clause Drafting)</option>
							<option value="2000">2000 Tokens (Document Analysis)</option>
							<option value="4000">4000 Tokens (Full Service Contract)</option>
						</select>
						<label class="mb-0 ml-2 small d-flex align-items-center gap-1" style="cursor:pointer;" title="${frappe.utils.escape_html(ready_document_names || "No clean PDF/DOCX/text document is ready")}">
							<input type="checkbox" id="include-source-doc" ${has_ready_documents ? "checked" : ""} ${has_ready_documents ? "" : "disabled"}>
							<span>Include Job Documents (${ready_documents.length} ready${attachment_info.skipped_count ? `, ${attachment_info.skipped_count} skipped` : ""})</span>
						</label>
					</div>
				</div>
				<div class="lex-ai-body" id="copilot-body">
					<div class="lex-ai-msg lex-ai-msg--ai">
						<div class="lex-ai-msg-header">AI Copilot (${frappe.utils.escape_html(frm.doc.job_title)})</div>
						${has_any_provider ?
							`Hello! I am your AI Legal Assistant. Ask me to draft clauses, review documents, or research law.` :
							`<strong>${config_error ? "AI configuration could not be loaded" : "No live-verified AI model is enabled"}</strong>. Open <a href="/app/lpo-ai-settings" target="_blank" style="text-decoration:underline;">LPO AI Settings</a>, save a provider key, and run its compatibility test.`
						}
					</div>
				</div>
				<div class="lex-ai-footer">
					<div class="lex-ai-input-row">
						<textarea class="form-control" id="copilot-input" placeholder="${__("Ask AI (e.g. Draft full contract clause, summarize risks from document...)")}" ${!has_any_provider ? "disabled" : ""}></textarea>
						<button class="btn btn-primary" id="copilot-send" style="background:#0284c7; border-color:#0284c7;" ${!has_any_provider ? "disabled" : ""}>${__("Ask AI")}</button>
					</div>
				</div>
			</div>
		`);

		$wrapper.append($card);

		const $provider = $card.find("#copilot-provider");
		const $credential = $card.find("#copilot-credential");
		const $model = $card.find("#copilot-model");
		const $token_limit = $card.find("#copilot-token-limit");
		const $include_doc = $card.find("#include-source-doc");
		const $body = $card.find("#copilot-body");
		const $input = $card.find("#copilot-input");
		const $send = $card.find("#copilot-send");
		const $token_badge = $card.find("#token-badge");

		function update_models() {
			const p = $provider.val();
			if (!p) {
				$model.empty().append('<option value="">(No active models)</option>');
				return;
			}
			const prov = config.providers?.[p] || {};
			const credential = active_credentials.find((item) => item.credential_name === $credential.val() && item.provider === p);
			const models = credential?.models?.length ? credential.models : (prov.models?.length ? prov.models : (prov.default_model ? [prov.default_model] : []));
			const defaultModel = credential?.default_model || prov.default_model;
			$model.empty();
			if (models.length) {
				models.forEach((m) => {
					$model.append(`<option value="${frappe.utils.escape_html(m)}" ${m === defaultModel ? "selected" : ""}>${frappe.utils.escape_html(m)}</option>`);
				});
			} else {
				$model.append('<option value="">(No models found)</option>');
			}
		}
		$credential.on("change", () => {
			const credential = active_credentials.find((item) => item.credential_name === $credential.val());
			if (credential) $provider.val(credential.provider);
			update_models();
		});
		$provider.on("change", () => {
			const matching = active_credentials.find((item) => item.provider === $provider.val());
			if (matching) $credential.val(matching.credential_name);
			update_models();
		});
		if ($credential.val()) {
			const credential = active_credentials.find((item) => item.credential_name === $credential.val());
			if (credential) $provider.val(credential.provider);
		}
		update_models();

		// Quick Top-up Tokens
		$card.on("click", ".btn-add-tokens", async function() {
			const amount = parseInt($(this).attr("data-amount"), 10) || 500;
			frappe.show_alert({ message: __("Adding +{0} tokens to the Job budget...", [amount]), indicator: "blue" });
			try {
				const res = await frappe.call({
					method: "lex.ai_gateway.increase_job_token_budget",
					args: {
						job_id: frm.doc.name,
						additional_tokens: amount
					}
				});
				if (res.message) {
					const m = res.message;
					$token_badge.html(`Budget: <strong>${m.tokens_used}</strong> / <strong>${m.token_budget}</strong> tokens (${m.tokens_remaining} left)`);
					frm.set_value("ai_token_budget", m.token_budget);
					frappe.show_alert({ message: m.message, indicator: "green" });
				}
			} catch (e) {
				frappe.show_alert({ message: __("Failed to increase tokens: {0}", [e.message]), indicator: "red" });
			}
		});

		// Send AI Query
		async function send_ai_query() {
			const prompt = $input.val().trim();
			if (!prompt) return;

			const selected_limit = parseInt($token_limit.val(), 10) || 200;
			const include_doc = $include_doc.is(":checked") ? 1 : 0;

			$body.append(`
				<div class="lex-ai-msg lex-ai-msg--user">
					<div class="lex-ai-msg-header">You (limit: ${selected_limit} tokens ${include_doc ? `with ${ready_documents.length} Job document(s)` : ""})</div>
					${frappe.utils.escape_html(prompt)}
				</div>
			`);
			$input.val("");
			$body.scrollTop($body[0].scrollHeight);
			$send.prop("disabled", true).text(__("Thinking..."));

			try {
				const res = await frappe.call({
					method: "lex.ai_gateway.chat_job_ai",
					args: {
						job_id: frm.doc.name,
						prompt: prompt,
						provider: $provider.val(),
						model: $model.val(),
						credential_name: $credential.val() || null,
						max_tokens: selected_limit,
						include_job_documents: include_doc,
					}
				});

				const msg = res.message || {};
				const is_exhausted = msg.status === "budget_exhausted";
				const response_html = frappe.markdown ? frappe.markdown(msg.response_text || "") : frappe.utils.escape_html(msg.response_text || "");
				const included_files = (msg.documents_included || []).map((doc) => frappe.utils.escape_html(doc.file_name)).join(", ");

				$body.append(`
					<div class="lex-ai-msg lex-ai-msg--ai" style="${is_exhausted ? 'border-left-color: #f59e0b; background: #fffbeb;' : ''}">
						<div class="lex-ai-msg-header d-flex justify-content-between">
							<span>${frappe.utils.escape_html(msg.provider || $provider.val())} (${frappe.utils.escape_html(msg.model || $model.val())})</span>
							<span>${msg.tokens_consumed || 0} tokens used</span>
						</div>
						${response_html}
						${included_files ? `<div class="mt-2 small text-muted"><strong>Documents analysed:</strong> ${included_files}</div>` : ""}
						${!is_exhausted ? `<div class="mt-2 text-right"><button class="btn btn-xs btn-default btn-insert-note" data-text="${frappe.utils.escape_html(msg.response_text || "")}">Insert in Delivery Notes</button></div>` : ''}
					</div>
				`);

				// Update token badge
				const new_used = msg.tokens_used || 0;
				const new_budget = msg.token_budget || token_budget;
				const new_rem = msg.tokens_remaining || 0;
				$token_badge.html(`Budget: <strong>${new_used}</strong> / <strong>${new_budget}</strong> tokens (${new_rem} left)`);

				frm.set_value("ai_tokens_used", new_used);
			} catch (err) {
				const safe_error = String(err?.message || __("The AI request failed. Check provider diagnostics in LPO AI Settings.")).slice(0, 320);
				$body.append(`
					<div class="lex-ai-msg lex-ai-msg--ai text-danger" role="alert">
						<div class="lex-ai-msg-header">AI request failed</div>
						<div>${frappe.utils.escape_html(safe_error)}</div>
						<div class="mt-2"><a href="/app/lpo-ai-settings" target="_blank">Open provider diagnostics</a></div>
					</div>
				`);
			} finally {
				$send.prop("disabled", false).text(__("Ask AI"));
				$body.scrollTop($body[0].scrollHeight);
			}
		}

		$send.on("click", send_ai_query);
		$input.on("keydown", (e) => {
			if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
				e.preventDefault();
				send_ai_query();
			}
		});

		$body.on("click", ".btn-insert-note", function() {
			const text = $(this).attr("data-text");
			if (text) {
				const current = frm.doc.delivery_notes || "";
				frm.set_value("delivery_notes", `${current}\n\n[AI Copilot Note]:\n${text}`.trim());
				frappe.show_alert({ message: __("Inserted into Delivery Notes!"), indicator: "green" });
			}
		});

		// Launch AI Document Processing Studio
		$card.find(".btn-launch-doc-studio").on("click", () => {
			if (typeof open_job_ai_document_studio === "function") {
				open_job_ai_document_studio(frm);
			} else {
				frappe.set_route("List", "LPO AI Document Processor", { job: frm.doc.name });
			}
		});

		// Trigger Single Job Review
		$card.find(".btn-review-job").on("click", async () => {
			frappe.show_alert({ message: __("Running AI Quality & Compliance Audit…"), indicator: "blue" });
			try {
				const res = await frappe.call({
					method: "lex.ai_gateway.review_matter_job_ai",
					args: {
						job_id: frm.doc.name,
						provider: $provider.val(),
						model: $model.val(),
						max_tokens: 350
					}
				});
				if (res.message) {
					frappe.show_alert({ message: __("AI Review Completed: {0} ({1}%)", [res.message.review_status, res.message.review_score]), indicator: "green" });
					frm.reload_doc();
				}
			} catch (e) {
				frappe.show_alert({ message: __("AI Review failed: {0}", [e.message]), indicator: "red" });
			}
		});
	}

	// -------------------------------------------------------------
	// 3. AI Matter Review & Job Audits in LPO Matter
	// -------------------------------------------------------------
	async function initialize_matter_ai_review(frm) {
		if (frm.doctype !== "LPO Matter") return;
		install_styles();

		const $wrapper = frm.fields_dict.ai_matter_review_html?.$wrapper;
		if (!$wrapper) return;
		$wrapper.empty();

		if (frm.is_new()) {
			$wrapper.html(`<div class="text-muted p-3">${__("Save Matter to enable the AI Job Review Engine.")}</div>`);
			return;
		}

		// Fetch jobs under this matter
		const jobs_res = await frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "LPO Job",
				filters: { engagement: frm.doc.name },
				fields: ["name", "job_title", "job_type", "job_status", "ai_review_status", "ai_review_score", "ai_review_provider", "ai_review_date", "ai_tokens_used", "ai_token_budget"],
				limit_page_length: 50,
			}
		});

		const jobs = jobs_res.message || [];

		const active_matter_providers = Object.entries(config.providers || {}).filter(([name, p]) => p.has_key);
		const active_matter_credentials = (config.credentials || []).filter((item) => item.enabled && item.has_key && item.models?.length);
		const has_any_matter_prov = active_matter_providers.length > 0;
		const preferred_review_credential = config.routes?.qa_review || config.default_credential || active_matter_credentials[0]?.credential_name || "";

		const $section = $(`
			<div class="lex-ai-card">
				<div class="lex-ai-header">
					<h4>🔍 AI Matter Review & Job Audits</h4>
					<div class="d-flex align-items-center gap-2">
						<select class="form-control-sm" id="matter-ai-credential" style="background:#1e293b; color:#ffffff; border-color:#334155;" ${!active_matter_credentials.length ? "disabled" : ""}>
							${active_matter_credentials.length ? active_matter_credentials.map((item) => `
								<option value="${frappe.utils.escape_html(item.credential_name)}" ${preferred_review_credential === item.credential_name ? "selected" : ""}>${frappe.utils.escape_html(item.credential_name)}</option>
							`).join("") : `<option value="">(Legacy provider key)</option>`}
						</select>
						<select class="form-control-sm" id="matter-ai-provider" style="background:#1e293b; color:#ffffff; border-color:#334155;" ${!has_any_matter_prov ? "disabled" : ""}>
							${has_any_matter_prov ? active_matter_providers.map(([name, p]) => `
								<option value="${frappe.utils.escape_html(name)}" ${config.default_provider === name ? "selected" : ""}>
									${frappe.utils.escape_html(name)}
								</option>
							`).join("") : `<option value="">(No AI Key Configured)</option>`}
						</select>
						<button class="btn btn-xs btn-primary btn-review-all-jobs" style="background:#0284c7; border-color:#0284c7; font-weight:600;" ${!has_any_matter_prov ? "disabled" : ""}>
							⚡ Audit All Jobs with AI
						</button>
					</div>
				</div>
				<div style="padding: 16px 18px;">
					<p class="text-muted small mb-3">
						The <strong>AI Matter Review Engine</strong> audits every Job against Matter SLA requirements, detects missing clauses and compliance risks, and scores work deliverables.
					</p>
					${!jobs.length ? `<div class="text-muted text-center p-4">No Jobs created yet under this Matter.</div>` : `
						<table class="lex-matter-table">
							<thead>
								<tr>
									<th>Job ID & Title</th>
									<th>Type & Status</th>
									<th>AI Tokens</th>
									<th>AI Audit Status</th>
									<th>Quality Score</th>
									<th>Actions</th>
								</tr>
							</thead>
							<tbody>
								${jobs.map((j) => {
									const is_pass = j.ai_review_status === "Passed";
									const is_pending = !j.ai_review_status || j.ai_review_status === "Not Reviewed";
									const badge_cls = is_pass ? "lex-ai-badge--pass" : (is_pending ? "lex-ai-badge--token" : "lex-ai-badge--warn");
									const badge_text = j.ai_review_status || "Not Reviewed";
									return `
										<tr data-job="${frappe.utils.escape_html(j.name)}">
											<td>
												<a href="/app/lpo-job/${encodeURIComponent(j.name)}" style="font-weight:700; color:#0284c7;">${frappe.utils.escape_html(j.name)}</a>
												<div style="font-size:12px; color:#475569;">${frappe.utils.escape_html(j.job_title)}</div>
											</td>
											<td>
												<div>${frappe.utils.escape_html(j.job_type || "")}</div>
												<span class="badge badge-light" style="font-size:11px;">${frappe.utils.escape_html(j.job_status || "")}</span>
											</td>
											<td>
												<span style="font-size:12px; font-weight:600; color:#0369a1;">${j.ai_tokens_used || 0} / ${j.ai_token_budget || 200}</span>
											</td>
											<td>
												<span class="lex-ai-badge ${badge_cls}">${frappe.utils.escape_html(badge_text)}</span>
												${j.ai_review_provider ? `<div style="font-size:10px; color:#64748b;">${frappe.utils.escape_html(j.ai_review_provider)}</div>` : ''}
											</td>
											<td>
												<strong style="color: ${is_pass ? '#16a34a' : '#d97706'}; font-size:14px;">
													${j.ai_review_score ? j.ai_review_score + '%' : '—'}
												</strong>
											</td>
											<td>
												<button class="btn btn-xs btn-default btn-audit-single-job" data-job="${frappe.utils.escape_html(j.name)}">
													🔍 Review
												</button>
											</td>
										</tr>
									`;
								}).join("")}
							</tbody>
						</table>
					`}
				</div>
			</div>
		`);

		$wrapper.append($section);
		const $matterCredential = $section.find("#matter-ai-credential");
		const syncMatterProvider = () => {
			const credential = active_matter_credentials.find((item) => item.credential_name === $matterCredential.val());
			if (credential) $section.find("#matter-ai-provider").val(credential.provider);
		};
		$matterCredential.on("change", syncMatterProvider);
		syncMatterProvider();

		// Single Job Review
		$section.on("click", ".btn-audit-single-job", async function() {
			const job_id = $(this).attr("data-job");
			const provider = $section.find("#matter-ai-provider").val();
			const credential_name = $matterCredential.val() || null;
			frappe.show_alert({ message: __("Auditing {0} with {1}…", [job_id, provider]), indicator: "blue" });

			try {
				const res = await frappe.call({
					method: "lex.ai_gateway.review_matter_job_ai",
					args: { job_id, provider, credential_name, max_tokens: 350 }
				});
				if (res.message) {
					frappe.show_alert({ message: __("✅ Audit Completed: {0} ({1}%)", [res.message.review_status, res.message.review_score]), indicator: "green" });
					initialize_matter_ai_review(frm);
				}
			} catch (e) {
				frappe.show_alert({ message: __("Audit failed: {0}", [e.message]), indicator: "red" });
			}
		});

		// Audit All Jobs
		$section.find(".btn-review-all-jobs").on("click", async () => {
			if (!jobs.length) return;
			const provider = $section.find("#matter-ai-provider").val();
			const credential_name = $matterCredential.val() || null;
			frappe.show_alert({ message: __("Auditing all {0} Jobs with {1}…", [jobs.length, provider]), indicator: "blue" });

			for (const j of jobs) {
				try {
					await frappe.call({
						method: "lex.ai_gateway.review_matter_job_ai",
						args: { job_id: j.name, provider, credential_name, max_tokens: 350 },
						freeze: false
					});
				} catch (e) {}
			}
			frappe.show_alert({ message: __("✅ All Job Audits Completed!"), indicator: "green" });
			frm.reload_doc();
		});
	}

	function is_internal_system_user() {
		if (frappe.session.user === "Administrator") return true;
		const roles = frappe.user_roles || [];
		return roles.some((r) => ["System Manager", "LPO_Admin", "LPO_Manager", "LPO_Analyst", "Desk User"].includes(r));
	}

	// -------------------------------------------------------------
	// Form Bindings
	// -------------------------------------------------------------
	if (!chat.route_cleanup_bound) {
		frappe.router.on("change", () => {
			const route = frappe.get_route();
			if (!(route[0] === "Form" && ALLOWED_DOCTYPES.includes(route[1]))) deactivate_chat();
		});
		chat.route_cleanup_bound = true;
	}

	ALLOWED_DOCTYPES.forEach((doctype) => {
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				initialize_chat(frm);
				if (is_internal_system_user()) {
					if (doctype === "LPO Job") {
						initialize_job_ai_copilot(frm);
					}
					if (doctype === "LPO Matter") {
						initialize_matter_ai_review(frm);
					}
				} else {
					// Strictly hide internal AI copilot and review from clients
					if (frm.fields_dict.ai_copilot_html) frm.toggle_display("ai_copilot_section", false);
					if (frm.fields_dict.ai_review_section) frm.toggle_display("ai_review_section", false);
					if (frm.fields_dict.ai_matter_review_section) frm.toggle_display("ai_matter_review_section", false);
				}
			},
		});
	});
})();
