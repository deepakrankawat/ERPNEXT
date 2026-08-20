frappe.pages["lexocrates-chat"].on_page_load = (wrapper) => {
	wrapper.lexocrates_chat = new LexocratesChatPage(wrapper);
};

frappe.pages["lexocrates-chat"].on_page_show = (wrapper) => {
	wrapper.lexocrates_chat?.show();
};

class LexocratesChatPage {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.api = "lex.lex.page.lexocrates_chat.lexocrates_chat";
		this.channels = [];
		this.messages = new Map();
		this.attachments = [];
		this.selected_channel = null;
		this.reply_to = null;
		this.has_more = false;
		this.oldest_message_at = null;
		this.typing_timer = null;
		this.typing_stop_timer = null;
		this.typing_users = new Map();
		this.presence = new Map();
		this.presence_heartbeat_timer = null;
		this.presence_clock_timer = null;
		this.last_presence_activity = Date.now();
		this.last_presence_activity_event = 0;
		this.realtime_connected = Boolean(frappe.realtime?.socket?.connected);
		this.loaded = false;
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Lexocrates Chat"),
			single_column: true,
		});
		this.page.set_secondary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.render_shell();
		this.bind_events();
		this.bind_realtime();
	}

	render_shell() {
		this.$root = $(
			`<div class="lex-chat" aria-label="${__("Lexocrates internal communication")}">
				<aside class="lex-chat__sidebar">
					<div class="lex-chat__brand">
						<div>
							<div class="lex-chat__eyebrow">${__("Lexocrates Legal Services")}</div>
							<h2>${__("Internal Channels")}</h2>
						</div>
						<div class="lex-chat__brand-actions">
							<button class="btn btn-default btn-sm lex-chat__new-dm hidden" title="${__("New direct message")}">${frappe.utils.icon("user-plus", "sm")}</button>
							<button class="btn btn-primary btn-sm lex-chat__new-channel hidden" title="${__("Create channel")}">+</button>
						</div>
					</div>
					<div class="lex-chat__self-presence">
						<div class="lex-chat__self-avatar"></div>
						<div class="lex-chat__self-copy">
							<strong class="lex-chat__self-name">${__("Loading user")}</strong>
							<span class="lex-chat__self-status text-muted">${__("Offline")}</span>
						</div>
						<select class="form-control input-xs lex-chat__presence-select" aria-label="${__("Set your presence status")}">
							<option value="Online">${__("Online")}</option>
							<option value="Away">${__("Away")}</option>
							<option value="Busy">${__("Busy")}</option>
							<option value="Offline">${__("Offline")}</option>
						</select>
					</div>
					<div class="lex-chat__channel-search">
						<span class="lex-chat__search-icon">${frappe.utils.icon("search", "sm")}</span>
						<input type="search" class="form-control lex-chat__channel-filter" placeholder="${__("Search Matter ID, name or organization")}" aria-label="${__("Search Matter channels by ID, name or organization")}">
					</div>
					<div class="lex-chat__channel-list" role="navigation"></div>
			</aside>
			<section class="lex-chat__conversation">
				<button type="button" class="btn btn-default btn-sm lex-chat__jump-latest hidden" aria-label="${__("Jump to latest messages")}">${frappe.utils.icon("down", "sm")} <span>${__("Latest messages")}</span></button>
				<div class="lex-chat__empty-state">
					<div class="lex-chat__empty-icon">${frappe.utils.icon("message-circle", "xl")}</div>
					<h3>${__("Secure legal operations communication")}</h3>
					<p>${__("Choose a channel to review its auditable conversation history.")}</p>
				</div>
				<div class="lex-chat__active hidden">
					<header class="lex-chat__header">
						<div class="lex-chat__header-copy">
							<div class="lex-chat__channel-title"></div>
							<div class="lex-chat__channel-meta text-muted"></div>
						</div>
						<div class="lex-chat__header-actions">
							<span class="lex-chat__live-status indicator-pill gray">${__("Connecting")}</span>
							<div class="lex-chat__message-search">
								<input type="search" class="form-control input-xs lex-chat__message-search-input" placeholder="${__("Search this channel")}">
							</div>
							<button class="btn btn-default btn-sm lex-chat__pinned">${__("Pinned")}</button>
							<button class="btn btn-default btn-sm lex-chat__notifications">${frappe.utils.icon("notification", "sm")}</button>
							<button class="btn btn-default btn-sm lex-chat__manage-channel hidden">${__("Manage")}</button>
						</div>
					</header>
					<div class="lex-chat__search-status hidden"></div>
					<div class="lex-chat__messages" role="log" aria-live="polite" tabindex="0" aria-label="${__("Conversation history")}">
						<button class="btn btn-default btn-xs lex-chat__load-older hidden">${__("Load older messages")}</button>
					</div>
					<div class="lex-chat__typing hidden" aria-live="polite"></div>
					<div class="lex-chat__reply-banner hidden">
						<div><span class="text-muted">${__("Replying to")}</span> <strong class="lex-chat__reply-label"></strong></div>
						<button class="btn btn-link btn-sm lex-chat__cancel-reply">${__("Cancel")}</button>
					</div>
					<div class="lex-chat__attachment-tray hidden"></div>
					<footer class="lex-chat__composer">
						<textarea class="form-control lex-chat__composer-input" maxlength="10000" placeholder="${__("Write a message. Use @username to mention a colleague.")}"></textarea>
						<div class="lex-chat__composer-actions">
						<div>
							<button class="btn btn-default btn-sm lex-chat__mention" title="${__("Mention a user")}">@</button>
							<button class="btn btn-default btn-sm lex-chat__job-mention hidden" title="${__("Mention a related Job")}">@Job</button>
							<button class="btn btn-default btn-sm lex-chat__attach" title="${__("Attach files")}">${frappe.utils.icon("attachment", "sm")}</button>
							</div>
							<div class="lex-chat__send-group">
								<span class="text-muted lex-chat__send-hint">${__("Ctrl/⌘ + Enter")}</span>
								<button class="btn btn-primary btn-sm lex-chat__send">${__("Send")}</button>
							</div>
						</div>
					</footer>
				</div>
			</section>
		</div>`
		).appendTo(this.page.body.empty());

		this.$channel_list = this.$root.find(".lex-chat__channel-list");
		this.$messages = this.$root.find(".lex-chat__messages");
		this.$input = this.$root.find(".lex-chat__composer-input");
		this.$send = this.$root.find(".lex-chat__send");
	}

	bind_events() {
		this.$root.on("click", ".lex-chat__channel", (event) => {
			this.open_channel($(event.currentTarget).attr("data-channel"));
		});
		this.$root.find(".lex-chat__channel-filter").on("input", (event) => {
			this.render_channels($(event.currentTarget).val());
		});
		this.$root.find(".lex-chat__new-channel").on("click", () => this.open_channel_dialog());
		this.$root.find(".lex-chat__new-dm").on("click", () => this.open_direct_message_dialog());
		this.$root.find(".lex-chat__presence-select").on("change", (event) => {
			this.set_manual_presence($(event.currentTarget).val());
		});
		this.$root.find(".lex-chat__manage-channel").on("click", () => {
			if (this.selected_channel) {
				frappe.set_route("Form", "Lexocrates Chat Channel", this.selected_channel);
			}
		});
		this.$send.on("click", () => this.send_message());
		this.$root.find(".lex-chat__jump-latest").on("click", () => this.scroll_to_bottom(true));
		this.$messages.on("scroll", () => this.update_jump_to_latest());
		this.$messages.on("keydown", (event) => this.handle_history_keydown(event));
		this.bind_conversation_wheel();
		this.$input.on("keydown", (event) => {
			if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
				event.preventDefault();
				this.send_message();
			}
		});
		this.$root.on("click", ".lex-chat__reply", (event) => {
			this.begin_reply($(event.currentTarget).attr("data-message"));
		});
		this.$root.on("click", ".lex-chat__edit", (event) => {
			this.open_edit_dialog($(event.currentTarget).attr("data-message"));
		});
		this.$root.find(".lex-chat__cancel-reply").on("click", () => this.clear_reply());
		this.$root.find(".lex-chat__mention").on("click", () => this.open_mention_dialog());
		this.$root.find(".lex-chat__job-mention").on("click", () => this.open_job_mention_dialog());
		this.$root.find(".lex-chat__attach").on("click", () => this.open_file_uploader());
		this.$root.on("click", ".lex-chat__remove-attachment", (event) => {
			const url = $(event.currentTarget).attr("data-url");
			this.attachments = this.attachments.filter((item) => item !== url);
			this.render_attachments();
		});
		this.$root.find(".lex-chat__message-search-input").on("keydown", (event) => {
			if (event.key === "Enter") this.search_messages($(event.currentTarget).val());
			if (event.key === "Escape") this.clear_message_search();
		});
		this.$root.on("click", ".lex-chat__react", (event) => {
			this.open_reaction_menu($(event.currentTarget).attr("data-message"));
		});
		this.$root.on("click", ".lex-chat__reaction", (event) => {
			this.toggle_reaction(
				$(event.currentTarget).attr("data-message"),
				$(event.currentTarget).attr("data-emoji")
			);
		});
		this.$root.on("click", ".lex-chat__pin", (event) => {
			this.toggle_pin($(event.currentTarget).attr("data-message"));
		});
		this.$root.on("click", ".lex-chat__thread", (event) => {
			this.open_thread($(event.currentTarget).attr("data-message"));
		});
		this.$root.find(".lex-chat__pinned").on("click", () => this.open_pinned_messages());
		this.$root.find(".lex-chat__notifications").on("click", () => this.open_notification_preferences());
		this.$root.on("click", ".lex-chat__load-older", () => this.load_older_messages());
		this.$input.on("input", () => {
			this.notify_typing();
			this.resize_composer();
		});
		$(window).on("focus.lexocrates-chat", () => {
			this.record_presence_activity();
			this.heartbeat_presence(true);
			if (this.selected_channel) this.mark_read();
		});
		$(document).on(
			"mousemove.lexocrates-chat-presence keydown.lexocrates-chat-presence click.lexocrates-chat-presence touchstart.lexocrates-chat-presence",
			() => this.record_presence_activity()
		);
		document.addEventListener("visibilitychange", () => {
			if (document.hidden) this.heartbeat_presence(false);
			else {
				this.record_presence_activity();
				this.heartbeat_presence(true);
			}
		});
		window.addEventListener("pagehide", () => this.send_presence_offline());
	}

	bind_realtime() {
		this.on_new_message = (message) => {
			if (message.thread_reference && this.messages.has(message.thread_reference)) {
				const root = this.messages.get(message.thread_reference);
				root.reply_count = Number(root.reply_count || 0) + (this.messages.has(message.name) ? 0 : 1);
				this.upsert_message(root, false);
			}
			if (message.channel === this.selected_channel) {
				this.upsert_message(message, true);
				this.mark_read(message.name);
			} else {
				this.bump_channel(message.channel);
				this.notify_new_message(message);
			}
			if (this.thread_dialog && (message.thread_reference || message.name) === this.thread_root) {
				this.refresh_open_thread();
			}
		};
		this.on_message_updated = (message) => {
			if (message.channel === this.selected_channel) this.upsert_message(message, false);
		};
		this.on_mention = (message) => {
			if (message.channel !== this.selected_channel) {
				frappe.show_alert({
					message: __("You were mentioned in {0}", [this.channel_label(message.channel)]),
					indicator: "blue",
				});
			}
		};
		this.on_job_mention = (message) => {
			if (message.channel !== this.selected_channel) {
				frappe.show_alert({
					message: __("Job {0} was mentioned in {1}", [
						message.mentioned_job?.name || "",
						this.channel_label(message.channel),
					]),
					indicator: "blue",
				});
			}
		};
		this.on_reaction_changed = (payload) => {
			const message = this.messages.get(payload.message);
			if (!message || payload.channel !== this.selected_channel) return;
			message.reactions = payload.reactions || [];
			this.upsert_message(message, false);
		};
		this.on_message_pinned = (message) => {
			if (message.channel === this.selected_channel) this.upsert_message(message, false);
		};
		this.on_read_receipt = (payload) => {
			if (payload.channel !== this.selected_channel || payload.user === this.bootstrap?.current_user) return;
			for (const message of this.messages.values()) {
				if (
					message.sender === this.bootstrap?.current_user &&
					new Date(message.sent_at) <= new Date(payload.last_read_at) &&
					!(message.read_by || []).includes(payload.user)
				) {
					message.read_by = [...(message.read_by || []), payload.user];
					this.upsert_message(message, false);
				}
			}
		};
		this.on_typing = (payload) => {
			if (payload.channel !== this.selected_channel || payload.user === this.bootstrap?.current_user) return;
			if (payload.is_typing) {
				this.typing_users.set(payload.user, payload.full_name || payload.user);
				setTimeout(() => {
					this.typing_users.delete(payload.user);
					this.render_typing();
				}, 5000);
			} else {
				this.typing_users.delete(payload.user);
			}
			this.render_typing();
		};
		this.on_presence_changed = (payload) => this.apply_presence(payload);
		this.on_socket_connect = () => {
			this.set_realtime_status(true);
			this.heartbeat_presence(!document.hidden);
		};
		this.on_socket_disconnect = () => this.set_realtime_status(false);
		frappe.realtime.on("new_chat_message", this.on_new_message);
		frappe.realtime.on("chat_message_updated", this.on_message_updated);
		frappe.realtime.on("chat_mention", this.on_mention);
		frappe.realtime.on("chat_job_mention", this.on_job_mention);
		frappe.realtime.on("chat_reaction_changed", this.on_reaction_changed);
		frappe.realtime.on("chat_message_pinned", this.on_message_pinned);
		frappe.realtime.on("chat_read_receipt", this.on_read_receipt);
		frappe.realtime.on("chat_typing", this.on_typing);
		frappe.realtime.on("chat_presence_changed", this.on_presence_changed);
		frappe.realtime.on("connect", this.on_socket_connect);
		frappe.realtime.on("disconnect", this.on_socket_disconnect);
	}

	async show() {
		const requested = frappe.route_options?.channel || this.selected_channel;
		frappe.route_options = null;
		if (!this.loaded) {
			await this.load_bootstrap(requested);
		} else if (requested && requested !== this.selected_channel) {
			await this.open_channel(requested);
		}
	}

	async load_bootstrap(selected_channel = null) {
		this.$channel_list.html(this.loading_markup(__("Loading channels")));
		const response = await frappe.call({
			method: `${this.api}.get_chat_bootstrap`,
			args: { selected_channel },
		});
		this.bootstrap = response.message || {};
		this.channels = this.bootstrap.channels || [];
		this.presence = new Map((this.bootstrap.presence || []).map((item) => [item.user, item]));
		this.loaded = true;
		this.$root.find(".lex-chat__new-channel").toggleClass("hidden", !this.bootstrap.can_create_channel);
		this.$root.find(".lex-chat__new-dm").toggleClass("hidden", !this.bootstrap.can_start_direct_message);
		this.set_realtime_status(Boolean(frappe.realtime?.socket?.connected));
		this.render_self_presence();
		this.render_channels();
		this.start_presence_tracking();
		await this.heartbeat_presence(!document.hidden);
		if (this.bootstrap.selected_channel) await this.open_channel(this.bootstrap.selected_channel);
	}

	async refresh() {
		const current = this.selected_channel;
		this.loaded = false;
		await this.load_bootstrap(current);
		frappe.show_alert({ message: __("Chat refreshed"), indicator: "green" });
	}

	render_channels(filter = "") {
		const value = (filter || "").trim().toLowerCase();
		const direct_messages = this.channels.filter(
			(channel) => channel.is_direct_message && this.channel_matches_filter(channel, value)
		);
		const groups = [
			{ key: "Direct Messages", title: __("Direct Messages"), rows: direct_messages },
			{
				key: "Public",
				title: __("Public Channels"),
				rows: this.channels.filter(
					(channel) =>
						!channel.is_direct_message &&
						channel.channel_type === "Public" &&
						this.channel_matches_filter(channel, value)
				),
			},
			{
				key: "Private",
				title: __("Private Channels"),
				rows: this.channels.filter(
					(channel) =>
						!channel.is_direct_message &&
						channel.channel_type === "Private" &&
						this.channel_matches_filter(channel, value)
				),
			},
			{
				key: "Contextual",
				title: __("Matter Channels"),
				rows: this.channels.filter(
					(channel) =>
						!channel.is_direct_message &&
						channel.channel_type === "Contextual" &&
						this.channel_matches_filter(channel, value)
				),
			},
		];

		const html = groups
			.map((group) => {
				if (!group.rows.length) return "";
				return `<section class="lex-chat__channel-group">
					<div class="lex-chat__group-label">${group.title}</div>
					${group.rows.map((channel) => this.channel_markup(channel)).join("")}
				</section>`;
			})
			.join("");
		this.$channel_list.html(html || `<div class="lex-chat__sidebar-empty">${__("No matching Matters or channels")}</div>`);
	}

	channel_matches_filter(channel, value) {
		if (!value) return true;
		return [
			channel.channel_name,
			channel.display_name,
			channel.reference_name,
			channel.matter_id,
			channel.matter_title,
			channel.organization_id,
			channel.organization_name,
		].some((field) => String(field || "").toLowerCase().includes(value));
	}

	channel_markup(channel) {
		const active = channel.name === this.selected_channel ? "is-active" : "";
		const direct_presence = channel.direct_user ? this.presence_for(channel.direct_user) : null;
		const matter_context = [channel.matter_id, channel.organization_name || channel.organization_id]
			.filter(Boolean)
			.join(" · ");
		const context = channel.is_direct_message
			? `<span>${frappe.utils.escape_html(this.presence_summary(direct_presence, true))}</span>`
			: channel.is_matter_channel
			? `<span title="${frappe.utils.escape_html(matter_context)}">${frappe.utils.escape_html(matter_context)}</span>`
			: channel.reference_name
			? `<span>${frappe.utils.escape_html(channel.reference_name)}</span>`
			: `<span>${channel.member_count || 0} ${__("members")}</span>`;
		const unread = Number(channel.unread_count || 0);
		const label = channel.matter_title || channel.display_name || channel.channel_name;
		const symbol = channel.is_direct_message && channel.direct_user
			? `<span class="lex-chat__channel-avatar" title="${frappe.utils.escape_html(this.presence_title(direct_presence))}">${frappe.avatar(channel.direct_user, "avatar-small")}${this.presence_dot(channel.direct_user)}</span>`
			: `<span class="lex-chat__channel-symbol">${channel.channel_type === "Private" ? frappe.utils.icon("lock", "xs") : "#"}</span>`;
		return `<button class="lex-chat__channel ${active}" data-channel="${frappe.utils.escape_html(channel.name)}">
			${symbol}
			<span class="lex-chat__channel-copy">
				<strong>${frappe.utils.escape_html(label.replace(/^#/, ""))}</strong>
				<small>${channel.muted ? `${frappe.utils.icon("mute", "xs")} ` : ""}${context}</small>
			</span>
			<span class="lex-chat__unread ${unread ? "" : "hidden"}">${unread}</span>
		</button>`;
	}

	async open_channel(channel_name) {
		const channel = this.channels.find((item) => item.name === channel_name);
		if (!channel) return;
		if (this.selected_channel && this.selected_channel !== channel_name) {
			frappe.realtime.doc_unsubscribe("Lexocrates Chat Channel", this.selected_channel);
		}
		this.selected_channel = channel_name;
		this.selected_channel_doc = channel;
		this.messages.clear();
		this.typing_users.clear();
		this.attachments = [];
		this.clear_reply();
		this.$root.find(".lex-chat__jump-latest").addClass("hidden");
		this.render_channels(this.$root.find(".lex-chat__channel-filter").val());
		this.$root.find(".lex-chat__empty-state").addClass("hidden");
		this.$root.find(".lex-chat__active").removeClass("hidden");
		this.render_channel_header(channel);
		this.$messages.html(this.loading_markup(__("Loading conversation")));
		this.$input.prop("disabled", !channel.can_post);
		this.$send.prop("disabled", !channel.can_post);
		frappe.realtime.emit("doc_subscribe", "Lexocrates Chat Channel", channel.name);

		const response = await frappe.call({
			method: `${this.api}.get_messages`,
			args: { channel: channel.name, limit: 100 },
		});
		if (this.selected_channel !== channel_name) return;
		this.$messages.empty();
		const messages = response.message || [];
		this.has_more = messages.length === 100;
		this.oldest_message_at = messages[0]?.sent_at || null;
		if (!messages.length) {
			this.$messages.html(`<div class="lex-chat__no-messages"><h4>${__("No messages yet")}</h4><p>${__("Start the secure conversation below.")}</p></div>`);
		} else {
			messages.forEach((message) => this.upsert_message(message, false));
			this.scroll_to_bottom();
		}
		this.$messages.prepend(`<button class="btn btn-default btn-xs lex-chat__load-older ${this.has_more ? "" : "hidden"}">${__("Load older messages")}</button>`);
		this.$channel_list.find(`[data-channel="${CSS.escape(channel_name)}"] .lex-chat__unread`).addClass("hidden").text("0");
		channel.unread_count = 0;
		await this.mark_read(messages.at(-1)?.name);
	}

	render_channel_header(channel) {
		const channel_title = channel.matter_title || channel.display_name || channel.channel_name;
		this.$root.find(".lex-chat__channel-title").html(
			`<h2>${frappe.utils.escape_html(channel_title)}</h2><span class="indicator-pill ${channel.status === "Active" ? "green" : "gray"}">${__(channel.status)}</span>`
		);
		const context = channel.is_direct_message && channel.direct_user
			? `<span class="lex-chat__direct-presence">${this.presence_dot(channel.direct_user)} ${frappe.utils.escape_html(this.presence_summary(this.presence_for(channel.direct_user)))}</span>`
			: channel.is_matter_channel
			? `<a href="/app/${frappe.router.slug(channel.reference_doctype)}/${encodeURIComponent(channel.reference_name)}">${frappe.utils.escape_html(channel.matter_id || channel.reference_name)}</a>${channel.organization_name || channel.organization_id ? ` <span>· ${frappe.utils.escape_html(channel.organization_name || channel.organization_id)}</span>` : ""}`
			: channel.reference_doctype && channel.reference_name
			? `<a href="/app/${frappe.router.slug(channel.reference_doctype)}/${encodeURIComponent(channel.reference_name)}">${frappe.utils.escape_html(channel.reference_doctype)} · ${frappe.utils.escape_html(channel.reference_name)}</a>`
			: `${__(channel.channel_type)} · ${channel.member_count || 0} ${__("members")}`;
		this.$root.find(".lex-chat__channel-meta").html(context);
		this.$root.find(".lex-chat__manage-channel").toggleClass("hidden", !channel.can_manage);
		this.$root.find(".lex-chat__notifications").attr("title", __(channel.notification_level || "All Messages"));
		this.$root.find(".lex-chat__job-mention").toggleClass(
			"hidden",
			!["LPO Matter", "LPO Job"].includes(channel.reference_doctype)
		);
	}

	upsert_message(message, scroll = false) {
		const existed = this.messages.has(message.name);
		const was_near_bottom = this.is_near_bottom();
		this.messages.set(message.name, message);
		this.$messages.find(".lex-chat__no-messages").remove();
		const $markup = $(this.message_markup(message));
		const $existing = this.$messages.find(`[data-message="${CSS.escape(message.name)}"]`);
		if ($existing.length) $existing.replaceWith($markup);
		else this.$messages.append($markup);
		this.decorate_message_flow();
		if (scroll || (!existed && was_near_bottom)) this.scroll_to_bottom();
		else if (!existed) this.$root.find(".lex-chat__jump-latest").removeClass("hidden");
	}

	message_markup(message) {
		const own = message.sender === this.bootstrap.current_user ? "is-own" : "";
		const reply = message.thread_reference ? "is-reply" : "";
		const system = message.system_generated ? "is-system" : "";
		const source = message.source_doctype && message.source_name
			? `<a class="lex-chat__source" href="/app/${frappe.router.slug(message.source_doctype)}/${encodeURIComponent(message.source_name)}">${frappe.utils.escape_html(message.source_doctype)} · ${frappe.utils.escape_html(message.source_name)}</a>`
			: "";
		const attachments = (message.attachments || [])
			.map((url) => `<a class="lex-chat__file" href="${frappe.utils.escape_html(url)}" target="_blank" rel="noopener">${frappe.utils.icon("attachment", "xs")} ${frappe.utils.escape_html(url.split("/").pop())}</a>`)
			.join("");
		const job_mentions = (message.job_mentions || [])
			.map((job) => `<a class="lex-chat__job-ref" href="/app/lpo-job/${encodeURIComponent(job.name)}" title="${frappe.utils.escape_html(job.title || job.name)}">@${frappe.utils.escape_html(job.name)}<span>${frappe.utils.escape_html(job.status || "")}</span></a>`)
			.join("");
		const reactions = (message.reactions || [])
			.map((reaction) => `<button class="lex-chat__reaction ${reaction.reacted_by_me ? "is-active" : ""}" data-message="${frappe.utils.escape_html(message.name)}" data-emoji="${frappe.utils.escape_html(reaction.emoji)}" title="${frappe.utils.escape_html((reaction.users || []).join(", "))}"><span>${reaction.emoji}</span><strong>${reaction.count}</strong></button>`)
			.join("");
		const read_by = message.read_by || [];
		const seen = own && read_by.length
			? `<span class="lex-chat__seen" title="${frappe.utils.escape_html(read_by.join(", "))}">${__("Seen by {0}", [read_by.length])}</span>`
			: "";
		const footer = `${source}${message.edited_on ? `<span class="text-muted">${__("Edited")}</span>` : ""}${seen}`;
		const actions = `<div class="lex-chat__message-actions" role="toolbar" aria-label="${__("Message actions")}">
			<button class="btn btn-link btn-xs lex-chat__react" data-message="${frappe.utils.escape_html(message.name)}">${__("React")}</button>
			<button class="btn btn-link btn-xs lex-chat__reply" data-message="${frappe.utils.escape_html(message.name)}">${__("Reply")}</button>
			${message.reply_count || message.thread_reference ? `<button class="btn btn-link btn-xs lex-chat__thread" data-message="${frappe.utils.escape_html(message.thread_reference || message.name)}">${message.reply_count || ""} ${__("Thread")}</button>` : ""}
			${this.selected_channel_doc?.can_manage ? `<button class="btn btn-link btn-xs lex-chat__pin" data-message="${frappe.utils.escape_html(message.name)}">${message.is_pinned ? __("Unpin") : __("Pin")}</button>` : ""}
			${message.can_edit ? `<button class="btn btn-link btn-xs lex-chat__edit" data-message="${frappe.utils.escape_html(message.name)}">${__("Edit")}</button>` : ""}
		</div>`;
		return `<article class="lex-chat__message ${own} ${reply} ${system}" data-message="${frappe.utils.escape_html(message.name)}" data-sender="${frappe.utils.escape_html(message.sender || "")}" data-sent-at="${frappe.utils.escape_html(message.sent_at || "")}">
			<div class="lex-chat__avatar" title="${frappe.utils.escape_html(this.presence_title(this.presence_for(message.sender)))}">${frappe.avatar(message.sender, "avatar-medium")}${this.presence_dot(message.sender)}</div>
			<div class="lex-chat__bubble">
				${actions}
				<div class="lex-chat__message-head">
					<div><strong>${frappe.utils.escape_html(message.sender_full_name || message.sender)}</strong>${message.system_generated ? `<span class="lex-chat__system-label">${__("System")}</span>` : ""}${message.is_pinned ? `<span class="lex-chat__pinned-label">${frappe.utils.icon("pin", "xs")} ${__("Pinned")}</span>` : ""}</div>
					<time title="${frappe.utils.escape_html(message.sent_at)}">${frappe.utils.escape_html(message.formatted_timestamp || message.sent_at)}</time>
				</div>
				<div class="lex-chat__message-body">${message.message_text || ""}</div>
				${job_mentions ? `<div class="lex-chat__job-refs">${job_mentions}</div>` : ""}
				${attachments ? `<div class="lex-chat__files">${attachments}</div>` : ""}
				${reactions ? `<div class="lex-chat__reactions">${reactions}</div>` : ""}
				${footer ? `<div class="lex-chat__message-footer">${footer}</div>` : ""}
			</div>
		</article>`;
	}

	async send_message() {
		const text = this.$input.val().trim();
		if (!text || !this.selected_channel || this.$send.prop("disabled")) return;
		const message_text = frappe.utils.escape_html(text).replace(/\n/g, "<br>");
		this.$send.prop("disabled", true);
		try {
			const response = await frappe.call({
				method: `${this.api}.send_message`,
				args: {
					channel: this.selected_channel,
					message_text,
					thread_reference: this.reply_to,
					attachments: this.attachments,
				},
			});
			if (response.message) this.upsert_message(response.message, true);
			this.$input.val("");
			this.resize_composer();
			this.publish_typing(false);
			this.attachments = [];
			this.render_attachments();
			this.clear_reply();
		} finally {
			this.$send.prop("disabled", !this.selected_channel_doc?.can_post);
			this.$input.trigger("focus");
		}
	}

	begin_reply(message_name) {
		const message = this.messages.get(message_name);
		if (!message) return;
		this.reply_to = message.thread_reference || message.name;
		this.$root.find(".lex-chat__reply-label").text(message.sender_full_name || message.sender);
		this.$root.find(".lex-chat__reply-banner").removeClass("hidden");
		this.$input.trigger("focus");
	}

	clear_reply() {
		this.reply_to = null;
		this.$root.find(".lex-chat__reply-banner").addClass("hidden");
	}

	open_edit_dialog(message_name) {
		const message = this.messages.get(message_name);
		if (!message?.can_edit) return;
		const dialog = new frappe.ui.Dialog({
			title: __("Edit message"),
			fields: [{ fieldname: "message_text", fieldtype: "Small Text", label: __("Message"), reqd: 1, default: $("<div>").html(message.message_text).text() }],
			primary_action_label: __("Save"),
			primary_action: async (values) => {
				await frappe.call({ method: `${this.api}.edit_message`, args: { message_name, message_text: frappe.utils.escape_html(values.message_text).replace(/\n/g, "<br>") } });
				dialog.hide();
			},
		});
		dialog.show();
	}

	open_mention_dialog() {
		const dialog = new frappe.ui.Dialog({
			title: __("Mention a colleague"),
			fields: [{ fieldname: "user", fieldtype: "Link", options: "User", label: __("User"), reqd: 1, get_query: () => ({ filters: { enabled: 1, user_type: "System User" } }) }],
			primary_action_label: __("Insert mention"),
			primary_action: (values) => {
				const current = this.$input.val();
				this.$input.val(`${current}${current && !/\s$/.test(current) ? " " : ""}@${values.user} `).trigger("focus");
				dialog.hide();
			},
		});
		dialog.show();
	}

	async open_job_mention_dialog() {
		if (!this.selected_channel) return;
		const response = await frappe.call({
			method: `${this.api}.get_channel_jobs`,
			args: { channel: this.selected_channel, limit: 100 },
		});
		const jobs = response.message || [];
		if (!jobs.length) {
			frappe.show_alert({ message: __("No related Jobs are available in this Matter."), indicator: "orange" });
			return;
		}
		const dialog = new frappe.ui.Dialog({
			title: __("Mention a related Job"),
			fields: [
				{
					fieldname: "job",
					fieldtype: "Select",
					label: __("Job"),
					reqd: 1,
					options: jobs.map((job) => job.name),
					description: __("Only Jobs linked to this Matter are shown."),
				},
			],
			primary_action_label: __("Insert Job mention"),
			primary_action: (values) => {
				const current = this.$input.val();
				this.$input.val(`${current}${current && !/\s$/.test(current) ? " " : ""}@${values.job} `).trigger("focus");
				dialog.hide();
			},
		});
		dialog.show();
	}

	open_file_uploader() {
		new frappe.ui.FileUploader({
			allow_multiple: true,
			folder: "Home/Attachments",
			on_success: (file) => {
				if (file?.file_url && !this.attachments.includes(file.file_url)) {
					this.attachments.push(file.file_url);
					this.render_attachments();
				}
			},
		});
	}

	render_attachments() {
		const $tray = this.$root.find(".lex-chat__attachment-tray");
		if (!this.attachments.length) return $tray.addClass("hidden").empty();
		$tray
			.removeClass("hidden")
			.html(this.attachments.map((url) => `<span class="lex-chat__attachment-chip">${frappe.utils.icon("attachment", "xs")} ${frappe.utils.escape_html(url.split("/").pop())}<button class="btn btn-link btn-xs lex-chat__remove-attachment" data-url="${frappe.utils.escape_html(url)}">×</button></span>`).join(""));
	}

	async load_older_messages() {
		if (!this.selected_channel || !this.has_more || !this.oldest_message_at) return;
		const previous_height = this.$messages[0]?.scrollHeight || 0;
		const response = await frappe.call({
			method: `${this.api}.get_messages`,
			args: { channel: this.selected_channel, before: this.oldest_message_at, limit: 100 },
		});
		const older = response.message || [];
		older.forEach((message) => this.messages.set(message.name, message));
		this.has_more = older.length === 100;
		this.oldest_message_at = older[0]?.sent_at || this.oldest_message_at;
		this.render_message_collection();
		this.$messages.scrollTop((this.$messages[0]?.scrollHeight || 0) - previous_height);
	}

	render_message_collection() {
		const messages = [...this.messages.values()].sort(
			(a, b) => new Date(a.sent_at) - new Date(b.sent_at)
		);
		this.$messages.empty().append(
			`<button class="btn btn-default btn-xs lex-chat__load-older ${this.has_more ? "" : "hidden"}">${__("Load older messages")}</button>`
		);
		messages.forEach((message) => this.$messages.append(this.message_markup(message)));
		this.decorate_message_flow();
	}

	decorate_message_flow() {
		this.$messages.find(".lex-chat__date-separator").remove();
		let previous_date = "";
		let previous_sender = "";
		let previous_time = 0;
		let previous_system = false;
		this.$messages.children(".lex-chat__message").each((index, element) => {
			const $message = $(element);
			$message.removeClass("is-grouped");
			const sent_at = this.parse_chat_datetime($message.attr("data-sent-at"));
			const date_key = sent_at ? `${sent_at.getFullYear()}-${sent_at.getMonth()}-${sent_at.getDate()}` : "unknown";
			if (date_key !== previous_date) {
				$message.before(`<div class="lex-chat__date-separator"><span>${frappe.utils.escape_html(this.chat_date_label(sent_at))}</span></div>`);
				previous_date = date_key;
				previous_sender = "";
				previous_time = 0;
			}
			const sender = $message.attr("data-sender") || "";
			const is_system = $message.hasClass("is-system");
			const timestamp = sent_at?.getTime() || 0;
			if (
				!is_system &&
				!previous_system &&
				sender === previous_sender &&
				timestamp && previous_time &&
				timestamp - previous_time <= 5 * 60 * 1000
			) {
				$message.addClass("is-grouped");
			}
			previous_sender = sender;
			previous_time = timestamp;
			previous_system = is_system;
		});
	}

	parse_chat_datetime(value) {
		if (!value) return null;
		const parsed = new Date(String(value).replace(" ", "T"));
		return Number.isNaN(parsed.getTime()) ? null : parsed;
	}

	chat_date_label(date) {
		if (!date) return __("Conversation history");
		const today = new Date();
		const start_today = new Date(today.getFullYear(), today.getMonth(), today.getDate());
		const start_date = new Date(date.getFullYear(), date.getMonth(), date.getDate());
		const difference = Math.round((start_today - start_date) / 86400000);
		if (difference === 0) return __("Today");
		if (difference === 1) return __("Yesterday");
		return new Intl.DateTimeFormat(undefined, {
			weekday: "short",
			day: "numeric",
			month: "short",
			year: start_date.getFullYear() === start_today.getFullYear() ? undefined : "numeric",
		}).format(start_date);
	}

	resize_composer() {
		const input = this.$input?.[0];
		if (!input) return;
		input.style.setProperty("height", "auto", "important");
		input.style.setProperty(
			"height",
			`${Math.min(Math.max(input.scrollHeight, 46), 140)}px`,
			"important"
		);
	}

	bind_conversation_wheel() {
		const conversation = this.$root.find(".lex-chat__conversation")[0];
		if (!conversation) return;
		conversation.addEventListener(
			"wheel",
			(event) => {
				if (!this.selected_channel || event.ctrlKey || Math.abs(event.deltaX) > Math.abs(event.deltaY)) return;
				if (event.target.closest(".lex-chat__messages")) return;

				const nested_scroll = event.target.closest("textarea");
				if (nested_scroll && nested_scroll.scrollHeight > nested_scroll.clientHeight) {
					const nested_max = nested_scroll.scrollHeight - nested_scroll.clientHeight;
					if ((event.deltaY < 0 && nested_scroll.scrollTop > 0) || (event.deltaY > 0 && nested_scroll.scrollTop < nested_max)) return;
				}

				const messages = this.$messages?.[0];
				if (!messages || messages.scrollHeight <= messages.clientHeight) return;
				const maximum = messages.scrollHeight - messages.clientHeight;
				const next = Math.max(0, Math.min(maximum, messages.scrollTop + event.deltaY));
				if (next === messages.scrollTop) return;
				event.preventDefault();
				messages.scrollTop = next;
				this.update_jump_to_latest();
			},
			{ passive: false }
		);
	}

	handle_history_keydown(event) {
		const messages = this.$messages?.[0];
		if (!messages || !["Home", "End", "PageUp", "PageDown"].includes(event.key)) return;
		event.preventDefault();
		const page = Math.max(120, messages.clientHeight * 0.85);
		const top = event.key === "Home"
			? 0
			: event.key === "End"
			? messages.scrollHeight
			: messages.scrollTop + (event.key === "PageUp" ? -page : page);
		messages.scrollTo({ top, behavior: "auto" });
		this.update_jump_to_latest();
	}

	is_near_bottom() {
		const element = this.$messages?.[0];
		if (!element) return true;
		return element.scrollHeight - element.scrollTop - element.clientHeight < 120;
	}

	update_jump_to_latest() {
		this.$root.find(".lex-chat__jump-latest").toggleClass("hidden", this.is_near_bottom());
	}

	async mark_read(message_name = null) {
		if (!this.selected_channel || document.hidden) return;
		try {
			await frappe.call({
				method: `${this.api}.mark_channel_read`,
				args: { channel: this.selected_channel, message_name },
				freeze: false,
			});
		} catch (error) {
			console.warn("Could not persist chat read state", error);
		}
	}

	notify_typing() {
		if (!this.selected_channel || !this.selected_channel_doc?.can_post) return;
		const now = Date.now();
		if (!this.last_typing_sent || now - this.last_typing_sent > 2000) {
			this.last_typing_sent = now;
			this.publish_typing(true);
		}
		clearTimeout(this.typing_stop_timer);
		this.typing_stop_timer = setTimeout(() => this.publish_typing(false), 1800);
	}

	publish_typing(is_typing) {
		if (!this.selected_channel) return;
		frappe.call({
			method: `${this.api}.publish_typing`,
			args: { channel: this.selected_channel, is_typing: is_typing ? 1 : 0 },
			freeze: false,
		}).catch(() => {});
	}

	render_typing() {
		const names = [...this.typing_users.values()];
		const $typing = this.$root.find(".lex-chat__typing");
		if (!names.length) return $typing.addClass("hidden").empty();
		$typing.removeClass("hidden").text(
			names.length === 1
				? __("{0} is typing…", [names[0]])
				: __("{0} people are typing…", [names.length])
		);
	}

	set_realtime_status(connected) {
		const was_connected = this.realtime_connected;
		this.realtime_connected = connected;
		this.$root.find(".lex-chat__live-status")
			.toggleClass("green", connected)
			.toggleClass("gray", !connected)
			.text(connected ? __("Live") : __("Reconnecting"));
		if (connected && !was_connected && this.selected_channel) {
			frappe.realtime.emit("doc_subscribe", "Lexocrates Chat Channel", this.selected_channel);
		}
	}

	presence_for(user) {
		return this.presence.get(user) || {
			user,
			full_name: user,
			status: "Offline",
			preferred_status: "Online",
			last_seen_at: null,
		};
	}

	presence_dot(user) {
		const presence = this.presence_for(user);
		const status = String(presence.status || "Offline").toLowerCase();
		return `<span class="lex-chat__presence-dot is-${status}" data-presence-user="${frappe.utils.escape_html(user || "")}" aria-label="${frappe.utils.escape_html(presence.status || "Offline")}"></span>`;
	}

	presence_summary(presence, compact = false) {
		presence = presence || { status: "Offline" };
		const status = __(presence.status || "Offline");
		if (presence.status === "Online" || compact) return status;
		const timestamp = presence.last_activity_at || presence.last_seen_at;
		if (!timestamp) return status;
		let formatted = timestamp;
		try { formatted = frappe.datetime.str_to_user(timestamp); } catch (_) { /* keep server value */ }
		return presence.status === "Offline"
			? `${status} · ${__("Last seen")} ${formatted}`
			: `${status} · ${__("Active")} ${formatted}`;
	}

	presence_title(presence) {
		if (!presence) return __("Offline");
		return `${presence.full_name || presence.user || ""} · ${this.presence_summary(presence)}`;
	}

	render_self_presence() {
		if (!this.bootstrap?.current_user) return;
		const presence = this.presence_for(this.bootstrap.current_user);
		this.$root.find(".lex-chat__self-avatar").html(
			`${frappe.avatar(this.bootstrap.current_user, "avatar-medium")}${this.presence_dot(this.bootstrap.current_user)}`
		).attr("title", this.presence_title(presence));
		this.$root.find(".lex-chat__self-name").text(this.bootstrap.current_user_full_name || this.bootstrap.current_user);
		this.$root.find(".lex-chat__self-status").text(this.presence_summary(presence));
		this.$root.find(".lex-chat__presence-select").val(presence.preferred_status || "Online");
	}

	apply_presence(payload) {
		if (!payload?.user) return;
		this.presence.set(payload.user, payload);
		if (payload.user === this.bootstrap?.current_user) this.render_self_presence();
		const filter = this.$root.find(".lex-chat__channel-filter").val();
		this.render_channels(filter);
		if (this.selected_channel_doc?.direct_user === payload.user) {
			this.render_channel_header(this.selected_channel_doc);
		}
		for (const message of this.messages.values()) {
			if (message.sender === payload.user) this.upsert_message(message, false);
		}
	}

	record_presence_activity() {
		const now = Date.now();
		if (now - this.last_presence_activity_event < 2000) return;
		const was_idle = now - this.last_presence_activity > 5 * 60 * 1000;
		this.last_presence_activity_event = now;
		this.last_presence_activity = now;
		if (was_idle && this.loaded && !document.hidden) this.heartbeat_presence(true);
	}

	start_presence_tracking() {
		if (!this.presence_heartbeat_timer) {
			this.presence_heartbeat_timer = window.setInterval(() => {
				const is_active = !document.hidden && Date.now() - this.last_presence_activity < 5 * 60 * 1000;
				this.heartbeat_presence(is_active);
			}, 30000);
		}
		if (!this.presence_clock_timer) {
			this.presence_clock_timer = window.setInterval(() => {
				this.render_self_presence();
				if (this.selected_channel_doc?.is_direct_message) this.render_channel_header(this.selected_channel_doc);
			}, 60000);
		}
	}

	async heartbeat_presence(is_active = true) {
		if (!this.loaded || !this.bootstrap?.current_user) return;
		try {
			const response = await frappe.call({
				method: `${this.api}.update_presence`,
				args: { is_active: is_active ? 1 : 0 },
				freeze: false,
			});
			if (response.message) this.apply_presence(response.message);
		} catch (error) {
			console.warn("Could not update chat presence", error);
		}
	}

	async set_manual_presence(status) {
		if (!status) return;
		try {
			const response = await frappe.call({
				method: `${this.api}.update_presence`,
				args: { status, is_active: document.hidden ? 0 : 1 },
			});
			if (response.message) this.apply_presence(response.message);
			frappe.show_alert({ message: __("Status set to {0}", [status]), indicator: status === "Online" ? "green" : status === "Busy" ? "red" : "orange" });
		} catch (error) {
			this.render_self_presence();
			throw error;
		}
	}

	send_presence_offline() {
		if (!this.loaded || !frappe.csrf_token) return;
		const body = new URLSearchParams({ is_active: "0", disconnect: "1" });
		fetch(`/api/method/${this.api}.update_presence`, {
			method: "POST",
			body,
			credentials: "same-origin",
			keepalive: true,
			headers: { "X-Frappe-CSRF-Token": frappe.csrf_token },
		}).catch(() => {});
	}

	notify_new_message(message) {
		const channel = this.channels.find((item) => item.name === message.channel);
		if (!channel || channel.notification_level === "Muted") return;
		if (channel.notification_level === "Mentions Only" && !(message.mentions || []).includes(this.bootstrap?.current_user)) return;
		frappe.show_alert({ message: `${channel.display_name || channel.channel_name}: ${message.sender_full_name || message.sender}`, indicator: "blue" });
		if (document.hidden && window.Notification?.permission === "granted") {
			new Notification(channel.display_name || channel.channel_name, {
				body: $("<div>").html(message.message_text || "").text().slice(0, 160),
			});
		}
	}

	open_reaction_menu(message_name) {
		frappe.prompt(
			[{ fieldname: "emoji", fieldtype: "Select", label: __("Reaction"), options: ["👍", "❤️", "✅", "👀", "🎉", "🙏"], reqd: 1 }],
			(values) => this.toggle_reaction(message_name, values.emoji),
			__("React to message"),
			__("React")
		);
	}

	async toggle_reaction(message_name, emoji) {
		const response = await frappe.call({ method: `${this.api}.toggle_reaction`, args: { message_name, emoji } });
		const message = this.messages.get(message_name);
		if (message && response.message) {
			message.reactions = response.message.reactions || [];
			this.upsert_message(message, false);
		}
	}

	async toggle_pin(message_name) {
		const message = this.messages.get(message_name);
		if (!message) return;
		const response = await frappe.call({ method: `${this.api}.set_message_pinned`, args: { message_name, pinned: message.is_pinned ? 0 : 1 } });
		if (response.message) this.upsert_message({ ...message, ...response.message }, false);
	}

	async open_pinned_messages() {
		if (!this.selected_channel) return;
		const response = await frappe.call({ method: `${this.api}.get_pinned_messages`, args: { channel: this.selected_channel } });
		const rows = response.message || [];
		const dialog = new frappe.ui.Dialog({ title: __("Pinned messages"), fields: [{ fieldname: "content", fieldtype: "HTML" }] });
		dialog.fields_dict.content.$wrapper.html(
			rows.length
				? rows.map((message) => `<article class="lex-chat__pinned-item"><strong>${frappe.utils.escape_html(message.sender_full_name || message.sender)}</strong><div>${message.message_text}</div><small>${frappe.utils.escape_html(message.formatted_timestamp || message.sent_at)}</small></article>`).join("")
				: `<div class="text-muted">${__("No pinned messages in this channel.")}</div>`
		);
		dialog.show();
	}

	open_notification_preferences() {
		if (!this.selected_channel_doc) return;
		const dialog = new frappe.ui.Dialog({
			title: __("Channel notifications"),
			fields: [{ fieldname: "notification_level", fieldtype: "Select", label: __("Notify me for"), options: ["All Messages", "Mentions Only", "Muted"], default: this.selected_channel_doc.notification_level || "All Messages", reqd: 1 }],
			primary_action_label: __("Save"),
			primary_action: async (values) => {
				await frappe.call({ method: `${this.api}.set_channel_preferences`, args: { channel: this.selected_channel, notification_level: values.notification_level } });
				this.selected_channel_doc.notification_level = values.notification_level;
				this.selected_channel_doc.muted = values.notification_level === "Muted";
				this.render_channels(this.$root.find(".lex-chat__channel-filter").val());
				this.render_channel_header(this.selected_channel_doc);
				dialog.hide();
			},
		});
		dialog.show();
	}

	async open_direct_message_dialog() {
		const response = await frappe.call({ method: `${this.api}.search_users`, args: { search_text: "" } });
		const users = response.message || [];
		if (!users.length) return frappe.show_alert({ message: __("No eligible chat users found"), indicator: "orange" });
		const dialog = new frappe.ui.Dialog({
			title: __("New direct message"),
			fields: [{ fieldname: "other_user", fieldtype: "Autocomplete", label: __("User"), options: users.map((user) => ({ label: `${user.full_name || user.name} · ${user.name}`, value: user.name })), reqd: 1 }],
			primary_action_label: __("Start conversation"),
			primary_action: async (values) => {
				const created = await frappe.call({ method: `${this.api}.get_or_create_direct_channel`, args: { other_user: values.other_user } });
				dialog.hide();
				await this.refresh();
				if (created.message?.name) await this.open_channel(created.message.name);
			},
		});
		dialog.show();
	}

	async open_thread(message_name) {
		this.thread_root = message_name;
		const response = await frappe.call({ method: `${this.api}.get_thread`, args: { message_name } });
		const dialog = new frappe.ui.Dialog({
			title: __("Conversation thread"),
			size: "large",
			fields: [{ fieldname: "thread_messages", fieldtype: "HTML" }, { fieldname: "reply", fieldtype: "Small Text", label: __("Reply"), reqd: 1 }],
			primary_action_label: __("Send reply"),
			primary_action: async (values) => {
				await frappe.call({ method: `${this.api}.send_message`, args: { channel: this.selected_channel, message_text: frappe.utils.escape_html(values.reply).replace(/\n/g, "<br>"), thread_reference: this.thread_root, attachments: [] } });
				dialog.set_value("reply", "");
				await this.refresh_open_thread();
			},
		});
		this.thread_dialog = dialog;
		this.render_thread_messages(response.message?.messages || []);
		dialog.$wrapper.one("hidden.bs.modal", () => { this.thread_dialog = null; this.thread_root = null; });
		dialog.show();
	}

	async refresh_open_thread() {
		if (!this.thread_dialog || !this.thread_root) return;
		const response = await frappe.call({ method: `${this.api}.get_thread`, args: { message_name: this.thread_root } });
		this.render_thread_messages(response.message?.messages || []);
	}

	render_thread_messages(messages) {
		if (!this.thread_dialog) return;
		this.thread_dialog.fields_dict.thread_messages.$wrapper.html(
			`<div class="lex-chat__thread-list">${messages.map((message, index) => `<article class="lex-chat__thread-item ${index ? "is-reply" : "is-root"}"><div><strong>${frappe.utils.escape_html(message.sender_full_name || message.sender)}</strong><time>${frappe.utils.escape_html(message.formatted_timestamp || message.sent_at)}</time></div><div>${message.message_text}</div></article>`).join("")}</div>`
		);
	}

	open_channel_dialog() {
		const context_doctypes = this.bootstrap.context_doctypes || [];
		const dialog = new frappe.ui.Dialog({
			title: __("Create chat channel"),
			fields: [
				{ fieldname: "channel_name", fieldtype: "Data", label: __("Channel Name"), reqd: 1, description: __("Example: #legal-research") },
				{ fieldname: "channel_type", fieldtype: "Select", label: __("Channel Type"), options: ["Public", "Private", "Contextual"], default: "Public", reqd: 1 },
				{ fieldname: "description", fieldtype: "Small Text", label: __("Description") },
				{ fieldname: "reference_section", fieldtype: "Section Break", label: __("ERP Record Context"), depends_on: "eval:doc.channel_type == 'Contextual'" },
				{ fieldname: "reference_doctype", fieldtype: "Select", label: __("Reference DocType"), options: context_doctypes, depends_on: "eval:doc.channel_type == 'Contextual'", mandatory_depends_on: "eval:doc.channel_type == 'Contextual'" },
				{ fieldname: "reference_name", fieldtype: "Dynamic Link", label: __("Reference Name"), options: "reference_doctype", depends_on: "eval:doc.channel_type == 'Contextual'", mandatory_depends_on: "eval:doc.channel_type == 'Contextual'" },
			],
			primary_action_label: __("Create"),
			primary_action: async (values) => {
				const response = await frappe.call({ method: `${this.api}.create_channel`, args: values });
				dialog.hide();
				await this.refresh();
				if (response.message?.name) await this.open_channel(response.message.name);
			},
		});
		dialog.show();
	}

	async search_messages(value) {
		const text = (value || "").trim();
		if (text.length < 2) return this.clear_message_search();
		const response = await frappe.call({ method: `${this.api}.search_messages`, args: { search_text: text, channel: this.selected_channel } });
		const messages = response.message || [];
		this.messages.clear();
		this.$messages.empty();
		messages.slice().reverse().forEach((message) => this.upsert_message(message, false));
		this.$root.find(".lex-chat__search-status").removeClass("hidden").html(`${messages.length} ${__("results for")} <strong>${frappe.utils.escape_html(text)}</strong> <button class="btn btn-link btn-xs lex-chat__clear-search">${__("Clear")}</button>`);
		this.$root.find(".lex-chat__clear-search").one("click", () => this.clear_message_search(true));
	}

	async clear_message_search(reload = false) {
		this.$root.find(".lex-chat__message-search-input").val("");
		this.$root.find(".lex-chat__search-status").addClass("hidden").empty();
		if (reload && this.selected_channel) await this.open_channel(this.selected_channel);
	}

	bump_channel(channel_name) {
		const $badge = this.$channel_list.find(`[data-channel="${CSS.escape(channel_name)}"] .lex-chat__unread`);
		if (!$badge.length) return;
		const count = Number($badge.text() || 0) + 1;
		$badge.text(count).removeClass("hidden");
		const channel = this.channels.find((item) => item.name === channel_name);
		if (channel) channel.unread_count = count;
	}

	channel_label(channel_name) {
		const channel = this.channels.find((item) => item.name === channel_name);
		return channel?.display_name || channel?.channel_name || __("another channel");
	}

	loading_markup(label) {
		return `<div class="lex-chat__loading">${frappe.utils.icon("spinner", "md")}<span>${label}</span></div>`;
	}

	scroll_to_bottom(smooth = false) {
		const element = this.$messages?.[0];
		if (!element) return;
		requestAnimationFrame(() => {
			element.scrollTo({ top: element.scrollHeight, behavior: smooth ? "smooth" : "auto" });
			this.$root.find(".lex-chat__jump-latest").addClass("hidden");
		});
	}
}
