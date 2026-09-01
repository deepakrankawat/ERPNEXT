frappe.pages["lexocrates-chat"].on_page_load = (wrapper) => {
	wrapper.lexocrates_chat = new LexocratesChatPage(wrapper);
};

frappe.pages["lexocrates-chat"].on_page_show = (wrapper) => {
	wrapper.lexocrates_chat?.show();
};

const EMOJI_CATEGORIES = {
	"Reactions": ["👍", "❤️", "🔥", "🚀", "✅", "👀", "🎉", "🙏", "💡", "👏", "💯", "📌", "😂", "🤝", "⚡", "🎯"],
	"Smileys": ["😀", "😃", "😄", "😁", "😆", "😅", "🤣", "😂", "🙂", "😉", "😊", "😇", "🥰", "😍", "🤩", "😘", "😗", "😋", "😛", "😜", "🤪", "😝", "🤑", "🤗", "🤭", "🤫", "🤔", "🤐", "🤨", "😐", "😑", "😶", "😏", "😒", "🙄", "😬", "😮", "😴", "😷", "🤒", "🤕", "🤢", "🤮", "🤧", "🥵", "🥶", "🥴", "😵", "🤯", "🤠", "🥳", "😎", "🤓", "🧐"],
	"Hands & Gestures": ["👍", "👎", "👊", "✊", "🤛", "🤜", "🤞", "✌️", "🤟", "🤘", "👌", "🤌", "🤏", "👈", "👉", "👆", "👇", "☝️", "✋", "🤚", "🖐️", "🖖", "👋", "🤙", "💪", "🦾", "🖕", "✍️", "🙏", "🤝", "👏", "🙌", "👐", "🤲"],
	"Work & Legal": ["💼", "📁", "📂", "📄", "📜", "📑", "📊", "📈", "📉", "⚖️", "🏛️", "🏢", "💻", "🖥️", "🖨️", "⌨️", "🖱️", "💾", "💿", "📱", "📞", "📠", "🔍", "🔎", "🔐", "🔒", "🔓", "✉️", "📧", "📦", "🏷️", "📌", "📍", "📎", "📏", "📋", "📅", "📆", "⏱️", "⏳", "⌛", "⏰"],
	"Symbols & Badges": ["✅", "✔️", "☑️", "❌", "❎", "❓", "❗", "‼️", "⁉️", "⚠️", "⛔", "🚫", "💯", "💢", "💥", "💫", "💦", "💨", "🕳️", "💬", "💭", "🗯️", "🔴", "🟢", "🟡", "🔵", "🟣", "⚫", "⚪", "⭐", "🌟", "✨", "⚡", "🔥", "🚀", "💡", "🎯"]
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
		this.oldest_sequence = null;
		this.typing_timer = null;
		this.typing_stop_timer = null;
		this.typing_users = new Map();
		this.presence = new Map();
		this.presence_heartbeat_timer = null;
		this.presence_clock_timer = null;
		this.last_presence_activity = Date.now();
		this.last_presence_activity_event = 0;
		this.realtime_connected = Boolean(frappe.realtime?.socket?.connected);
		this.realtime_unsubscribe = null;
		this.read_timer = null;
		this.read_inflight = false;
		this.pending_read_message = null;
		this.loaded = false;
		this.sound_muted = window.lexocratesChatSound?.isMuted()
			?? localStorage.getItem("lex_chat_sound_muted") === "1";
		this.media_recorder = null;
		this.audio_chunks = [];
		this.recording_timer = null;

		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Lexocrates Chat"),
			single_column: true,
		});
		this.page.set_secondary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.render_shell();
		this.bind_events();
		this.bind_realtime();
		this.bind_paste_and_drop();
	}

	update_sound_button() {
		this.sound_muted = window.lexocratesChatSound?.isMuted() ?? this.sound_muted;
		this.$root
			.find(".lex-chat__sound-toggle")
			.html(this.sound_muted ? "&#128263;" : "&#128276;")
			.attr("title", this.sound_muted ? __("Unmute Sound") : __("Mute Sound"))
			.attr("aria-label", this.sound_muted ? __("Unmute chat sounds") : __("Mute chat sounds"))
			.attr("aria-pressed", this.sound_muted ? "true" : "false")
			.toggleClass("is-muted", this.sound_muted);
	}

	play_chat_sound(kind, key = null) {
		if (this.sound_muted) return;
		window.lexocratesChatSound?.play(kind, key);
	}

	should_sound_message(message) {
		if (!message || message.sender === this.bootstrap?.current_user) return false;
		const channel = this.channels.find((item) => item.name === message.channel);
		if (!channel || channel.notification_level === "Muted") return false;
		if (
			channel.notification_level === "Mentions Only" &&
			!(message.mentions || []).includes(this.bootstrap?.current_user)
		) return false;
		return true;
	}

	play_incoming_message(message) {
		if (!this.should_sound_message(message)) return;
		const key = message.name ? `incoming:${message.name}` : null;
		this.play_chat_sound("incoming", key);
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
							<span class="lex-chat__self-role"></span>
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
						<input type="search" class="form-control lex-chat__channel-filter" placeholder="${__("Search Matter ID, name or user")}" aria-label="${__("Search channels")}">
					</div>
					<div class="lex-chat__channel-list" role="navigation"></div>
			</aside>
			<section class="lex-chat__conversation">
				<button type="button" class="btn btn-default btn-sm lex-chat__jump-latest hidden" aria-label="${__("Jump to latest messages")}">${frappe.utils.icon("down", "sm")} <span>${__("Latest messages")}</span></button>
				<div class="lex-chat__empty-state">
					<div class="lex-chat__empty-icon">${frappe.utils.icon("message-circle", "xl")}</div>
					<h3>${__("Secure legal operations communication")}</h3>
					<p>${__("Choose a channel or team member to review conversations.")}</p>
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
								<input type="search" class="form-control input-xs lex-chat__message-search-input" placeholder="${__("Search messages…")}">
							</div>
							<button class="btn btn-default btn-sm lex-chat__members" type="button" title="${__("Channel Members")}">${frappe.utils.icon("users", "sm")} <span>0</span></button>
							<button class="btn btn-default btn-sm lex-chat__sound-toggle${this.sound_muted ? " is-muted" : ""}" type="button" title="${this.sound_muted ? __("Unmute Sound") : __("Mute Sound")}" aria-label="${this.sound_muted ? __("Unmute chat sounds") : __("Mute chat sounds")}" aria-pressed="${this.sound_muted ? "true" : "false"}">${this.sound_muted ? "&#128263;" : "&#128276;"}</button>
							<button class="btn btn-default btn-sm lex-chat__pinned" title="${__("Pinned Messages")}">${__("Pinned")}</button>
							<button class="btn btn-default btn-sm lex-chat__notifications" title="${__("Notification Settings")}">${frappe.utils.icon("notification", "sm")}</button>
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

					<!-- Rich WYSIWYG Composer Area -->
					<footer class="lex-chat__composer-container">
						<div class="lex-chat__md-toolbar">
							<button type="button" class="btn btn-link btn-xs lex-md-btn" data-format="bold" title="${__("Bold (Ctrl+B)")}"><b>B</b></button>
							<button type="button" class="btn btn-link btn-xs lex-md-btn" data-format="italic" title="${__("Italic (Ctrl+I)")}"><i>I</i></button>
							<button type="button" class="btn btn-link btn-xs lex-md-btn" data-format="strike" title="${__("Strikethrough")}"><s>S</s></button>
							<span class="lex-md-divider"></span>
							<button type="button" class="btn btn-link btn-xs lex-md-btn" data-format="code" title="${__("Inline Code")}"><code>&lt;&gt;</code></button>
							<button type="button" class="btn btn-link btn-xs lex-md-btn" data-format="codeblock" title="${__("Code Block")}"><code>{ }</code></button>
							<button type="button" class="btn btn-link btn-xs lex-md-btn" data-format="quote" title="${__("Blockquote")}">❝</button>
							<button type="button" class="btn btn-link btn-xs lex-md-btn" data-format="bullet" title="${__("Bullet List")}">• List</button>
							<button type="button" class="btn btn-link btn-xs lex-md-btn" data-format="link" title="${__("Insert Link")}">🔗</button>
						</div>

						<div class="lex-chat__composer-inner">
						<div class="form-control lex-chat__composer-input" contenteditable="true" role="textbox" aria-multiline="true" data-placeholder="${__("Write a message… Click B to type in bold, @username to mention, or drop files.")}"></div>

							<!-- Audio Recording Bar Overlay -->
							<div class="lex-chat__voice-bar hidden">
								<div class="lex-voice-pulse"></div>
								<span class="lex-voice-status">${__("Recording audio…")}</span>
								<span class="lex-voice-timer">00:00</span>
								<button type="button" class="btn btn-danger btn-xs lex-voice-cancel">${__("Cancel")}</button>
								<button type="button" class="btn btn-success btn-xs lex-voice-send">${__("Send Audio")}</button>
							</div>

							<div class="lex-chat__composer-actions">
								<div class="lex-chat__tools-group">
									<button class="btn btn-default btn-sm lex-chat__emoji-picker-btn" title="${__("Emoji Picker")}">😊</button>
									<button class="btn btn-default btn-sm lex-chat__mention" title="${__("Mention a user")}">@</button>
									<button class="btn btn-default btn-sm lex-chat__job-mention hidden" title="${__("Mention a related Job")}">@Job</button>
									<button class="btn btn-default btn-sm lex-chat__attach" title="${__("Attach files / images")}">${frappe.utils.icon("attachment", "sm")}</button>
									<button class="btn btn-default btn-sm lex-chat__voice-btn" title="${__("Record Voice Note")}">🎙️</button>
								</div>
								<div class="lex-chat__send-group">
									<span class="text-muted lex-chat__send-hint">${__("Enter to Send · Shift+Enter for Newline")}</span>
									<button class="btn btn-primary btn-sm lex-chat__send">${__("Send")}</button>
								</div>
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
		this.$root.find(".lex-chat__members").on("click", () => this.open_channel_members_dialog());
		this.$root.find(".lex-chat__presence-select").on("change", (event) => {
			this.set_manual_presence($(event.currentTarget).val());
		});
		this.$root.find(".lex-chat__manage-channel").on("click", () => {
			if (this.selected_channel) {
				frappe.set_route("Form", "Lexocrates Chat Channel", this.selected_channel);
			}
		});
		this.$send.on("click", () => {
			window.lexocratesChatSound?.unlock();
			this.send_message();
		});
		this.$root.find(".lex-chat__jump-latest").on("click", () => {
			this.scroll_to_bottom(true);
			this.mark_read(this.latest_message_name());
		});
		this.$messages.on("scroll", () => {
			this.update_jump_to_latest();
			if (this.is_near_bottom()) this.mark_read(this.latest_message_name());
		});
		this.$messages.on("keydown", (event) => this.handle_history_keydown(event));
		this.bind_conversation_wheel();

		// Live Contenteditable Input Handling
		this.$input.on("keydown", (event) => {
			if (event.key === "Enter" && !event.shiftKey) {
				event.preventDefault();
				window.lexocratesChatSound?.unlock();
				this.send_message();
			}
		});

		this.$input.on("input", () => {
			this.notify_typing();
			this.update_toolbar_active_states();
		});

		this.$input.on("keyup mouseup focus blur", () => {
			this.update_toolbar_active_states();
		});

		document.addEventListener("selectionchange", () => {
			if (document.activeElement === this.$input[0]) {
				this.update_toolbar_active_states();
			}
		});

		this.$root.on("click", ".lex-chat__reply", (event) => {
			this.begin_reply($(event.currentTarget).attr("data-message"));
		});
		this.$root.on("click", ".lex-chat__edit", (event) => {
			this.open_edit_dialog($(event.currentTarget).attr("data-message"));
		});
		this.$root.on("click", ".lex-chat__copy", (event) => {
			this.copy_message_text($(event.currentTarget).attr("data-message"));
		});
		this.$root.find(".lex-chat__cancel-reply").on("click", () => this.clear_reply());
		this.$root.find(".lex-chat__mention").on("click", () => this.open_mention_dialog());
		this.$root.find(".lex-chat__job-mention").on("click", () => this.open_job_mention_dialog());
		this.$root.find(".lex-chat__attach").on("click", () => this.open_file_uploader());
		this.$root.find(".lex-chat__emoji-picker-btn").on("click", (e) => this.toggle_emoji_picker(e));
		this.$root.find(".lex-chat__voice-btn").on("click", () => this.start_voice_recording());

		this.$root.find(".lex-chat__sound-toggle").on("click", () => {
			this.sound_muted = window.lexocratesChatSound?.setMuted(!this.sound_muted) ?? !this.sound_muted;
			if (!window.lexocratesChatSound) {
				localStorage.setItem("lex_chat_sound_muted", this.sound_muted ? "1" : "0");
			}
			this.update_sound_button();
			if (!this.sound_muted) window.lexocratesChatSound?.unlock();
			frappe.show_alert({ message: this.sound_muted ? __("Chat sound muted") : __("Chat sound enabled"), indicator: "blue" });
		});
		this.on_sound_preference_changed = (event) => {
			this.sound_muted = Boolean(event.detail?.muted);
			this.update_sound_button();
		};
		window.addEventListener(window.lexocratesChatSound?.CHANGE_EVENT || "lex-chat-sound-change", this.on_sound_preference_changed);

		// Rich WYSIWYG Toolbar Click & Mousedown
		this.$root.on("mousedown", ".lex-md-btn", (e) => {
			e.preventDefault(); // Keep selection / cursor position in contenteditable
		});

		this.$root.on("click", ".lex-md-btn", (e) => {
			e.preventDefault();
			e.stopPropagation();
			const format = $(e.currentTarget).attr("data-format");
			this.apply_markdown_format(format);
		});

		// Image Lightbox trigger
		this.$root.on("click", ".lex-chat__img-thumb", (e) => {
			const url = $(e.currentTarget).attr("data-full-url") || $(e.currentTarget).attr("src");
			this.open_lightbox(url);
		});

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

	update_toolbar_active_states() {
		try {
			const isBold = document.queryCommandState("bold");
			const isItalic = document.queryCommandState("italic");
			const isStrike = document.queryCommandState("strikeThrough");
			const isList = document.queryCommandState("insertUnorderedList");

			this.$root.find('.lex-md-btn[data-format="bold"]').toggleClass("is-active", Boolean(isBold));
			this.$root.find('.lex-md-btn[data-format="italic"]').toggleClass("is-active", Boolean(isItalic));
			this.$root.find('.lex-md-btn[data-format="strike"]').toggleClass("is-active", Boolean(isStrike));
			this.$root.find('.lex-md-btn[data-format="bullet"]').toggleClass("is-active", Boolean(isList));
		} catch (e) {}
	}

	apply_markdown_format(type) {
		this.$input.trigger("focus");

		switch (type) {
			case "bold":
				document.execCommand("bold", false, null);
				break;
			case "italic":
				document.execCommand("italic", false, null);
				break;
			case "strike":
				document.execCommand("strikeThrough", false, null);
				break;
			case "bullet":
				document.execCommand("insertUnorderedList", false, null);
				break;
			case "code": {
				const sel = window.getSelection();
				if (!sel || sel.rangeCount === 0) return;
				const range = sel.getRangeAt(0);
				const codeEl = document.createElement("code");
				codeEl.className = "lex-inline-code";
				if (range.collapsed) {
					codeEl.textContent = "code";
					range.insertNode(codeEl);
				} else {
					codeEl.appendChild(range.extractContents());
					range.insertNode(codeEl);
				}
				break;
			}
			case "codeblock": {
				const sel = window.getSelection();
				if (!sel || sel.rangeCount === 0) return;
				const range = sel.getRangeAt(0);
				const preEl = document.createElement("pre");
				preEl.className = "lex-code-block";
				const codeEl = document.createElement("code");
				if (range.collapsed) {
					codeEl.textContent = "code block";
				} else {
					codeEl.appendChild(range.extractContents());
				}
				preEl.appendChild(codeEl);
				range.insertNode(preEl);
				break;
			}
			case "quote": {
				const sel = window.getSelection();
				if (!sel || sel.rangeCount === 0) return;
				const range = sel.getRangeAt(0);
				const bqEl = document.createElement("blockquote");
				bqEl.className = "lex-blockquote";
				if (range.collapsed) {
					bqEl.textContent = "quote";
				} else {
					bqEl.appendChild(range.extractContents());
				}
				range.insertNode(bqEl);
				break;
			}
			case "link": {
				const selText = window.getSelection()?.toString() || "";
				frappe.prompt(
					[
						{ fieldname: "title", fieldtype: "Data", label: __("Link Title"), default: selText },
						{ fieldname: "url", fieldtype: "Data", label: __("URL"), reqd: 1, default: "https://" }
					],
					(values) => {
						this.$input.trigger("focus");
						const a = document.createElement("a");
						a.href = values.url;
						a.textContent = values.title || values.url;
						a.target = "_blank";
						a.rel = "noopener noreferrer";
						a.className = "lex-chat-link";
						const sel = window.getSelection();
						if (sel && sel.rangeCount > 0) {
							const range = sel.getRangeAt(0);
							range.deleteContents();
							range.insertNode(a);
						}
					},
					__("Insert Link"),
					__("Insert")
				);
				break;
			}
		}
		this.update_toolbar_active_states();
	}

	insert_content(content, isHtml = false) {
		this.$input.trigger("focus");
		if (isHtml) {
			document.execCommand("insertHTML", false, content);
		} else {
			document.execCommand("insertText", false, content);
		}
		this.update_toolbar_active_states();
	}

	bind_paste_and_drop() {
		// Clipboard paste for images
		this.$input.on("paste", (e) => {
			const items = (e.originalEvent || e).clipboardData?.items;
			if (!items) return;
			for (let i = 0; i < items.length; i++) {
				if (items[i].type.indexOf("image") !== -1) {
					const blob = items[i].getAsFile();
					this.upload_pasted_file(blob, `pasted-image-${Date.now()}.png`);
					e.preventDefault();
					break;
				}
			}
		});

		// Drag and drop onto messages
		const dropZone = this.$messages[0];
		if (dropZone) {
			dropZone.addEventListener("dragover", (e) => {
				e.preventDefault();
				this.$messages.addClass("lex-drop-active");
			});
			dropZone.addEventListener("dragleave", () => {
				this.$messages.removeClass("lex-drop-active");
			});
			dropZone.addEventListener("drop", (e) => {
				e.preventDefault();
				this.$messages.removeClass("lex-drop-active");
				if (e.dataTransfer?.files?.length) {
					for (let i = 0; i < e.dataTransfer.files.length; i++) {
						const file = e.dataTransfer.files[i];
						this.upload_pasted_file(file, file.name);
					}
				}
			});
		}
	}

	async upload_pasted_file(fileBlob, fileName) {
		frappe.show_alert({ message: __("Uploading attachment…"), indicator: "blue" });
		const formData = new FormData();
		formData.append("file", fileBlob, fileName);
		formData.append("is_private", "0");
		formData.append("folder", "Home/Attachments");

		try {
			const res = await fetch("/api/method/upload_file", {
				method: "POST",
				body: formData,
				headers: { "X-Frappe-CSRF-Token": frappe.csrf_token },
			});
			const data = await res.json();
			const fileUrl = data.message?.file_url;
			if (fileUrl && !this.attachments.includes(fileUrl)) {
				this.attachments.push(fileUrl);
				this.render_attachments();
				frappe.show_alert({ message: __("Attachment uploaded!"), indicator: "green" });
			}
		} catch (err) {
			frappe.show_alert({ message: __("Failed to upload image"), indicator: "red" });
		}
	}

	toggle_emoji_picker(e) {
		let $pop = $("#lex-emoji-picker-popover");
		if ($pop.length) {
			$pop.remove();
			return;
		}

		const categoriesHtml = Object.entries(EMOJI_CATEGORIES).map(([cat, emojis]) => `
			<div class="lex-emoji-cat-section">
				<div class="lex-emoji-cat-title">${frappe.utils.escape_html(cat)}</div>
				<div class="lex-emoji-cat-grid">
					${emojis.map((em) => `<button type="button" class="lex-emoji-pick-btn" data-emoji="${em}">${em}</button>`).join("")}
				</div>
			</div>
		`).join("");

		$pop = $(`
			<div id="lex-emoji-picker-popover" class="lex-emoji-popover">
				<div class="lex-emoji-pop-header">
					<input type="search" class="form-control input-xs lex-emoji-search" placeholder="${__("Search emojis…")}">
				</div>
				<div class="lex-emoji-pop-body">${categoriesHtml}</div>
			</div>
		`);

		$(document.body).append($pop);
		const rect = e.currentTarget.getBoundingClientRect();
		$pop.css({
			bottom: `${window.innerHeight - rect.top + 8}px`,
			left: `${Math.max(12, rect.left - 120)}px`,
		});

		$pop.on("click", ".lex-emoji-pick-btn", (ev) => {
			const emoji = $(ev.currentTarget).data("emoji");
			this.insert_content(emoji);
			$pop.remove();
		});

		$pop.find(".lex-emoji-search").on("input", (ev) => {
			const query = ev.target.value.toLowerCase();
			$pop.find(".lex-emoji-pick-btn").each((_, btn) => {
				const em = $(btn).data("emoji");
				$(btn).toggle(!query || em.includes(query));
			});
		});

		$(document).one("click", (docEv) => {
			if (!$(docEv.target).closest("#lex-emoji-picker-popover, .lex-chat__emoji-picker-btn").length) {
				$("#lex-emoji-picker-popover").remove();
			}
		});
	}

	async start_voice_recording() {
		if (!navigator.mediaDevices?.getUserMedia) {
			return frappe.show_alert({ message: __("Microphone not supported on this browser"), indicator: "red" });
		}
		try {
			const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
			this.media_recorder = new MediaRecorder(stream);
			this.audio_chunks = [];

			const $bar = this.$root.find(".lex-chat__voice-bar");
			const $timer = $bar.find(".lex-voice-timer");
			$bar.removeClass("hidden");

			let seconds = 0;
			this.recording_timer = setInterval(() => {
				seconds++;
				const mins = String(Math.floor(seconds / 60)).padStart(2, "0");
				const secs = String(seconds % 60).padStart(2, "0");
				$timer.text(`${mins}:${secs}`);
			}, 1000);

			this.media_recorder.ondataavailable = (e) => {
				if (e.data.size > 0) this.audio_chunks.push(e.data);
			};

			this.media_recorder.onstop = async () => {
				clearInterval(this.recording_timer);
				$bar.addClass("hidden");
				stream.getTracks().forEach((track) => track.stop());

				if (this.send_voice_note && this.audio_chunks.length) {
					const audioBlob = new Blob(this.audio_chunks, { type: "audio/webm" });
					await this.upload_pasted_file(audioBlob, `voice-message-${Date.now()}.webm`);
				}
				this.send_voice_note = false;
			};

			$bar.find(".lex-voice-send").one("click", () => {
				this.send_voice_note = true;
				this.media_recorder.stop();
			});

			$bar.find(".lex-voice-cancel").one("click", () => {
				this.send_voice_note = false;
				this.media_recorder.stop();
			});

			this.media_recorder.start();
		} catch (err) {
			frappe.show_alert({ message: __("Microphone access denied"), indicator: "red" });
		}
	}

	open_lightbox(imageUrl) {
		let $modal = $("#lex-chat-lightbox-modal");
		if (!$modal.length) {
			$modal = $(`
				<div id="lex-chat-lightbox-modal" class="lex-lightbox-modal">
					<div class="lex-lightbox-backdrop"></div>
					<div class="lex-lightbox-content">
						<img class="lex-lightbox-img" src="" alt="Full view">
						<div class="lex-lightbox-toolbar">
							<a href="" target="_blank" download class="btn btn-default btn-xs lex-lb-dl">⬇ ${__("Download")}</a>
							<button class="btn btn-default btn-xs lex-lb-close">✕ ${__("Close")}</button>
						</div>
					</div>
				</div>
			`).appendTo(document.body);

			$modal.find(".lex-lightbox-backdrop, .lex-lb-close").on("click", () => $modal.addClass("hidden"));
		}

		$modal.find(".lex-lightbox-img").attr("src", imageUrl);
		$modal.find(".lex-lb-dl").attr("href", imageUrl);
		$modal.removeClass("hidden");
	}

	copy_message_text(message_name) {
		const message = this.messages.get(message_name);
		if (!message) return;
		const raw = $("<div>").html(message.message_text || "").text();
		navigator.clipboard.writeText(raw).then(() => {
			frappe.show_alert({ message: __("Message copied to clipboard"), indicator: "green" });
		});
	}

	format_markdown(text) {
		if (!text) return "";
		let str = String(text).replace(/<br\s*[\/]?>/gi, "\n");

		// Code blocks
		str = str.replace(/```([a-zA-Z0-9_-]*)\n?([\s\S]+?)```/g, (match, lang, code) => {
			return `\n<pre class="lex-code-block"><code>${frappe.utils.escape_html(code.trim())}</code></pre>\n`;
		});

		// Inline code
		str = str.replace(/`([^`\n]+)`/g, (match, code) => {
			return `<code class="lex-inline-code">${frappe.utils.escape_html(code)}</code>`;
		});

		// Blockquotes
		str = str.replace(/(?:^|\n)>\s*([^\n]+)/g, (match, quote) => {
			return `\n<blockquote class="lex-blockquote">${quote.trim()}</blockquote>\n`;
		});

		// Bullet lists
		str = str.replace(/(?:^|\n)(?:-|\*)\s+([^\n]+)/g, (match, item) => {
			return `\n<div class="lex-list-item"><span class="lex-bullet">•</span> ${item.trim()}</div>\n`;
		});

		// Links
		str = str.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (match, title, url) => {
			return `<a href="${frappe.utils.escape_html(url)}" target="_blank" rel="noopener noreferrer" class="lex-chat-link">${frappe.utils.escape_html(title)}</a>`;
		});

		// Bold
		str = str.replace(/\*\*([^*\n]+?)\*\*/g, "<strong>$1</strong>");

		// Italic
		str = str.replace(/(?<!\*)\*([^*\n]+?)\*(?!\*)/g, "<em>$1</em>");
		str = str.replace(/(?<!_)_([^_\n]+?)_(?!_)/g, "<em>$1</em>");

		// Strikethrough
		str = str.replace(/~([^~\n]+?)~/g, "<del>$1</del>");

		const parts = str.split(/(<pre[\s\S]*?<\/pre>|<blockquote[\s\S]*?<\/blockquote>|<div class="lex-list-item"[\s\S]*?<\/div>)/g);
		return parts.map((part) => {
			if (part.startsWith("<pre") || part.startsWith("<blockquote") || part.startsWith("<div class=\"lex-list-item\"")) {
				return part;
			}
			return part.trim() ? part.replace(/\n/g, "<br>") : "";
		}).join("");
	}

	message_markup(message) {
		const own = message.sender === this.bootstrap.current_user ? "is-own" : "";
		const reply = message.thread_reference ? "is-reply" : "";
		const system = message.system_generated ? "is-system" : "";
		const source = message.source_doctype && message.source_name
			? `<a class="lex-chat__source" href="/app/${frappe.router.slug(message.source_doctype)}/${encodeURIComponent(message.source_name)}">${frappe.utils.escape_html(message.source_doctype)} · ${frappe.utils.escape_html(message.source_name)}</a>`
			: "";

		const attachments = (message.attachments || []).map((url) => {
			const cleanUrl = frappe.utils.escape_html(url);
			const fileName = cleanUrl.split("/").pop();
			const isImg = /\.(png|jpg|jpeg|webp|gif|svg)(\?.*)?$/i.test(url);
			const isAudio = /\.(webm|mp3|wav|ogg|m4a)(\?.*)?$/i.test(url);

			if (isImg) {
				return `<div class="lex-chat__img-card">
					<img src="${cleanUrl}" class="lex-chat__img-thumb" data-full-url="${cleanUrl}" alt="${fileName}">
				</div>`;
			}
			if (isAudio) {
				return `<div class="lex-chat__audio-card">
					<audio controls preload="metadata" src="${cleanUrl}"></audio>
				</div>`;
			}
			return `<a class="lex-chat__file" href="${cleanUrl}" target="_blank" rel="noopener">${frappe.utils.icon("attachment", "xs")} ${fileName}</a>`;
		}).join("");

		const job_mentions = (message.job_mentions || [])
			.map((job) => `<a class="lex-chat__job-ref" href="/app/lpo-job/${encodeURIComponent(job.name)}" title="${frappe.utils.escape_html(job.title || job.name)}">@${frappe.utils.escape_html(job.name)}<span>${frappe.utils.escape_html(job.status || "")}</span></a>`)
			.join("");

		const reactions = (message.reactions || [])
			.map((reaction) => `<button class="lex-chat__reaction ${reaction.reacted_by_me ? "is-active" : ""}" data-message="${frappe.utils.escape_html(message.name)}" data-emoji="${frappe.utils.escape_html(reaction.emoji)}" title="${frappe.utils.escape_html((reaction.users || []).join(", "))}"><span>${reaction.emoji}</span><strong>${reaction.count}</strong></button>`)
			.join("");

		const read_by = message.read_by || [];
		const seen = own && read_by.length
			? `<span class="lex-chat__seen" title="${frappe.utils.escape_html(read_by.join(", "))}">✓✓ ${__("Seen by {0}", [read_by.length])}</span>`
			: own ? `<span class="lex-chat__seen">✓ ${__("Delivered")}</span>` : "";

		const footer = `${source}${message.edited_on ? `<span class="text-muted">${__("Edited")}</span>` : ""}${seen}`;
		const formatted_body = this.format_markdown(message.message_text || "");
		const sender_role = frappe.utils.escape_html(message.sender_role || __("System User"));
		const role_title = frappe.utils.escape_html((message.sender_roles || []).join(", ") || message.sender_role || "");

		const actions = `<div class="lex-chat__message-actions" role="toolbar" aria-label="${__("Message actions")}">
			<button class="btn btn-link btn-xs lex-chat__react" data-message="${frappe.utils.escape_html(message.name)}" title="${__("React with emoji")}">😊 ${__("React")}</button>
			<button class="btn btn-link btn-xs lex-chat__reply" data-message="${frappe.utils.escape_html(message.name)}" title="${__("Reply in thread")}">↩ ${__("Reply")}</button>
			<button class="btn btn-link btn-xs lex-chat__copy" data-message="${frappe.utils.escape_html(message.name)}" title="${__("Copy text")}">📋 ${__("Copy")}</button>
			${message.reply_count || message.thread_reference ? `<button class="btn btn-link btn-xs lex-chat__thread" data-message="${frappe.utils.escape_html(message.thread_reference || message.name)}">${message.reply_count || ""} ${__("Thread")}</button>` : ""}
			${this.selected_channel_doc?.can_manage ? `<button class="btn btn-link btn-xs lex-chat__pin" data-message="${frappe.utils.escape_html(message.name)}">${message.is_pinned ? __("Unpin") : __("Pin")}</button>` : ""}
			${message.can_edit ? `<button class="btn btn-link btn-xs lex-chat__edit" data-message="${frappe.utils.escape_html(message.name)}">${__("Edit")}</button>` : ""}
		</div>`;

		return `<article class="lex-chat__message ${own} ${reply} ${system}" data-message="${frappe.utils.escape_html(message.name)}" data-sender="${frappe.utils.escape_html(message.sender || "")}" data-sent-at="${frappe.utils.escape_html(message.sent_at || "")}">
			<div class="lex-chat__avatar" title="${frappe.utils.escape_html(this.presence_title(this.presence_for(message.sender)))}">${frappe.avatar(message.sender, "avatar-medium")}${this.presence_dot(message.sender)}</div>
			<div class="lex-chat__bubble">
				${actions}
				<div class="lex-chat__message-head">
					<div class="lex-chat__sender-identity"><strong>${frappe.utils.escape_html(message.sender_full_name || message.sender)}</strong><span class="lex-chat__role-label" title="${role_title}">${sender_role}</span>${message.system_generated ? `<span class="lex-chat__system-label">${__("System")}</span>` : ""}${message.is_pinned ? `<span class="lex-chat__pinned-label">${frappe.utils.icon("pin", "xs")} ${__("Pinned")}</span>` : ""}</div>
					<time title="${frappe.utils.escape_html(message.sent_at)}">${frappe.utils.escape_html(message.formatted_timestamp || message.sent_at)}</time>
				</div>
				<div class="lex-chat__message-body">${formatted_body}</div>
				${job_mentions ? `<div class="lex-chat__job-refs">${job_mentions}</div>` : ""}
				${attachments ? `<div class="lex-chat__files">${attachments}</div>` : ""}
				${reactions ? `<div class="lex-chat__reactions">${reactions}</div>` : ""}
				${footer ? `<div class="lex-chat__message-footer">${footer}</div>` : ""}
			</div>
		</article>`;
	}

	bind_realtime() {
		this.on_new_message = (message) => {
			this.play_incoming_message(message);
			const was_near_bottom = this.is_near_bottom();
			if (message.thread_reference && this.messages.has(message.thread_reference)) {
				const root = this.messages.get(message.thread_reference);
				root.reply_count = Number(root.reply_count || 0) + (this.messages.has(message.name) ? 0 : 1);
				this.upsert_message(root, false);
			}
			if (message.channel === this.selected_channel) {
				this.upsert_message(message, false);
				if (was_near_bottom) this.mark_read(message.name);
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
			// The shared sound key prevents the mention event and its matching
			// message event from producing two tones.
			this.play_incoming_message(message);
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
					(
						payload.last_read_sequence
							? Number(message.channel_sequence || 0) <= Number(payload.last_read_sequence)
							: new Date(message.sent_at) <= new Date(payload.last_read_at)
					) &&
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
			if (!window.lexocratesReliableChat) this.set_realtime_status(true);
			this.heartbeat_presence(!document.hidden);
		};
		this.on_socket_disconnect = () => {
			if (!window.lexocratesReliableChat) this.set_realtime_status(false);
		};
		if (!window.lexocratesReliableChat) {
			frappe.realtime.on("new_chat_message", this.on_new_message);
		}
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

	channel_matches_filter(channel, filter) {
		if (!filter) return true;
		const haystack = [
			channel.display_name,
			channel.channel_name,
			channel.matter_id,
			channel.organization_name,
			channel.organization_id,
			channel.reference_name,
			channel.direct_user,
		]
			.filter(Boolean)
			.join(" ")
			.toLowerCase();
		return haystack.includes(filter);
	}

	channel_markup(channel) {
		const active = channel.name === this.selected_channel ? "is-active" : "";
		const unread = Number(channel.unread_count || 0);
		const badge = unread ? `<span class="lex-chat__unread indicator-pill red">${unread}</span>` : `<span class="lex-chat__unread indicator-pill red hidden">0</span>`;
		const presence = channel.is_direct_message ? this.presence_dot(channel.direct_user) : "";
		const avatar = channel.is_direct_message
			? `<div class="lex-chat__channel-avatar">${frappe.avatar(channel.direct_user, "avatar-small")}${presence}</div>`
			: `<span class="lex-chat__channel-hash">${channel.channel_type === "Private" ? "🔒" : "#"}</span>`;
		const title = frappe.utils.escape_html(channel.display_name || channel.channel_name);
		const meta = channel.matter_id
			? `${frappe.utils.escape_html(channel.matter_id)}${channel.organization_name ? ` · ${frappe.utils.escape_html(channel.organization_name)}` : ""}`
			: channel.is_direct_message
			? [channel.direct_user_role, this.presence_summary(this.presence_for(channel.direct_user), true)].filter(Boolean).join(" · ")
			: channel.system_user_only
			? `${__("Internal team")} · ${__("{0} members", [channel.member_count || 0])}`
			: channel.reference_name || channel.channel_type;

		return `<button type="button" class="lex-chat__channel ${active}" data-channel="${frappe.utils.escape_html(channel.name)}" aria-label="${title}">
			${avatar}
			<div class="lex-chat__channel-copy">
				<div class="lex-chat__channel-row">
					<span class="lex-chat__channel-name">${title}</span>
					${channel.muted ? `<span class="lex-chat__muted-icon" title="${__("Muted")}">${frappe.utils.icon("notification-off", "xs")}</span>` : ""}
				</div>
				<small class="text-muted">${frappe.utils.escape_html(meta || "")}</small>
			</div>
			${badge}
		</button>`;
	}

	async open_channel(channel_name) {
		const channel = this.channels.find((item) => item.name === channel_name);
		if (!channel) return;
		this.realtime_unsubscribe?.();
		this.realtime_unsubscribe = null;
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
		this.$input.attr("contenteditable", channel.can_post ? "true" : "false");
		this.$send.prop("disabled", !channel.can_post);
		const response = await frappe.call({
			method: `${this.api}.get_messages`,
			args: { channel: channel.name, limit: 100 },
		});
		if (this.selected_channel !== channel_name) return;
		this.$messages.empty();
		const messages = response.message || [];
		this.has_more = messages.length === 100;
		this.oldest_message_at = messages[0]?.sent_at || null;
		this.oldest_sequence = messages[0]?.channel_sequence ?? null;
		if (!messages.length) {
			this.$messages.html(`<div class="lex-chat__no-messages"><h4>${__("No messages yet")}</h4><p>${__("Start the secure conversation below.")}</p></div>`);
		} else {
			messages.forEach((message) => this.upsert_message(message, false));
			this.scroll_to_bottom();
		}
		const latest_sequence = Math.max(0, ...messages.map((message) => Number(message.channel_sequence || 0)));
		if (window.lexocratesReliableChat) {
			this.realtime_unsubscribe = window.lexocratesReliableChat.subscribe(channel.name, {
				afterSequence: latest_sequence,
				onMessage: this.on_new_message,
				onState: ({ state }) => this.set_realtime_transport_state(state),
			});
		} else {
			frappe.realtime.emit("doc_subscribe", "Lexocrates Chat Channel", channel.name);
		}
		this.$messages.prepend(`<button class="btn btn-default btn-xs lex-chat__load-older ${this.has_more ? "" : "hidden"}">${__("Load older messages")}</button>`);
		this.mark_read(messages.at(-1)?.name);
		this.$input.trigger("focus");
	}

	render_channel_header(channel) {
		const title = frappe.utils.escape_html(channel.display_name || channel.channel_name);
		const meta = channel.is_direct_message
			? [frappe.utils.escape_html(channel.direct_user_role || __("System User")), this.presence_summary(this.presence_for(channel.direct_user))].filter(Boolean).join(" · ")
			: [channel.matter_id, channel.organization_name, channel.reference_doctype, channel.reference_name, channel.description].filter(Boolean).map((item) => frappe.utils.escape_html(item)).join(" · ");

		this.$root.find(".lex-chat__channel-title").html(`<h3>${title}</h3>`);
		this.$root.find(".lex-chat__channel-meta").html(meta || __("Secure communication"));
		this.$root.find(".lex-chat__members span").text(channel.member_count || 0);
		this.$root.find(".lex-chat__members").attr("aria-label", __("View {0} channel members", [channel.member_count || 0]));
		this.$root.find(".lex-chat__manage-channel").toggleClass("hidden", !channel.can_manage);
		const notification_level = channel.notification_level || "All Messages";
		this.$root.find(".lex-chat__notifications")
			.attr("title", __(notification_level))
			.attr("aria-label", notification_level === "Muted" ? __("Channel notifications muted") : __("Channel notification settings"))
			.attr("aria-pressed", notification_level === "Muted" ? "true" : "false")
			.toggleClass("is-muted", notification_level === "Muted");
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
		if ($existing.length) {
			$existing.replaceWith($markup);
		} else {
			const sequence = Number(message.channel_sequence || 0);
			const next = [...this.messages.values()]
				.filter((item) => item.name !== message.name && Number(item.channel_sequence || 0) > sequence)
				.sort((left, right) => Number(left.channel_sequence || 0) - Number(right.channel_sequence || 0))[0];
			const $next = next ? this.$messages.find(`[data-message="${CSS.escape(next.name)}"]`) : $();
			if ($next.length) $markup.insertBefore($next);
			else this.$messages.append($markup);
		}
		this.decorate_message_flow();
		if (scroll || (!existed && was_near_bottom)) this.scroll_to_bottom();
		else if (!existed) this.$root.find(".lex-chat__jump-latest").removeClass("hidden");
	}

	async send_message() {
		const html_content = this.$input.html().trim();
		const plain_text = this.$input.text().trim();
		if ((!plain_text && !this.attachments.length) || !this.selected_channel || this.$send.prop("disabled")) return;

		const message_text = plain_text ? html_content : "📎 [Attachment]";
		this.$send.prop("disabled", true);
		try {
			const args = {
					channel: this.selected_channel,
					message_text,
					thread_reference: this.reply_to,
					attachments: this.attachments,
				};
			const message = window.lexocratesReliableChat
				? await window.lexocratesReliableChat.send({ method: `${this.api}.send_message`, args })
				: (await frappe.call({ method: `${this.api}.send_message`, args })).message;
			if (message) {
				this.upsert_message(message, true);
				this.play_chat_sound("sent", `sent:${message.name}`);
			}
			this.$input.empty();
			this.update_toolbar_active_states();
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
				this.insert_content(`@${values.user} `);
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
				this.insert_content(`@${values.job} `);
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
		if (!this.selected_channel || !this.has_more || this.oldest_sequence == null) return;
		const previous_height = this.$messages[0]?.scrollHeight || 0;
		const response = await frappe.call({
			method: `${this.api}.get_messages`,
			args: { channel: this.selected_channel, before_sequence: this.oldest_sequence, limit: 100 },
		});
		const older = response.message || [];
		older.forEach((message) => this.messages.set(message.name, message));
		this.has_more = older.length === 100;
		this.oldest_message_at = older[0]?.sent_at || this.oldest_message_at;
		this.oldest_sequence = older[0]?.channel_sequence ?? this.oldest_sequence;
		this.render_message_collection();
		this.$messages.scrollTop((this.$messages[0]?.scrollHeight || 0) - previous_height);
	}

	render_message_collection() {
		const messages = [...this.messages.values()].sort(
			(a, b) => Number(a.channel_sequence || 0) - Number(b.channel_sequence || 0)
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

	bind_conversation_wheel() {
		const conversation = this.$root.find(".lex-chat__conversation")[0];
		if (!conversation) return;
		conversation.addEventListener(
			"wheel",
			(event) => {
				if (!this.selected_channel || event.ctrlKey || Math.abs(event.deltaX) > Math.abs(event.deltaY)) return;
				if (event.target.closest(".lex-chat__messages")) return;

				const nested_scroll = event.target.closest(".lex-chat__composer-input");
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

	latest_message_name() {
		return [...this.messages.values()]
			.sort((left, right) => Number(left.channel_sequence || 0) - Number(right.channel_sequence || 0))
			.at(-1)?.name || null;
	}

	mark_read(message_name = null) {
		if (!this.selected_channel || document.hidden) return;
		if (message_name) this.pending_read_message = message_name;
		window.clearTimeout(this.read_timer);
		this.read_timer = window.setTimeout(() => this.flush_read_state(), 250);
	}

	async flush_read_state() {
		if (!this.selected_channel || document.hidden || this.read_inflight) return;
		const channel = this.selected_channel;
		const message_name = this.pending_read_message;
		this.pending_read_message = null;
		this.read_inflight = true;
		try {
			await frappe.call({
				method: `${this.api}.mark_channel_read`,
				args: { channel, message_name },
				freeze: false,
			});
		} catch (error) {
			console.warn("Could not persist chat read state", error);
		} finally {
			this.read_inflight = false;
			if (this.pending_read_message && channel === this.selected_channel) this.mark_read(this.pending_read_message);
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
		if (connected && !was_connected && this.selected_channel && !window.lexocratesReliableChat) {
			frappe.realtime.emit("doc_subscribe", "Lexocrates Chat Channel", this.selected_channel);
		}
	}

	set_realtime_transport_state(state) {
		const live = state === "live";
		this.realtime_connected = live;
		const labels = {
			live: __("Live"),
			recovering: __("Syncing"),
			reconnecting: __("Reconnecting"),
			degraded: __("Recovering"),
			offline: __("Offline"),
		};
		this.$root.find(".lex-chat__live-status")
			.toggleClass("green", live)
			.toggleClass("gray", !live)
			.text(labels[state] || labels.offline);
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
		this.$root.find(".lex-chat__self-role").text(this.bootstrap.current_user_identity?.primary_role || __("System User"));
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
		const emojis = EMOJI_CATEGORIES["Reactions"];
		const buttons = emojis.map((em) => `<button type="button" class="btn btn-default btn-sm lex-quick-react-btn" data-emoji="${em}">${em}</button>`).join(" ");

		const dialog = new frappe.ui.Dialog({
			title: __("Quick Reaction"),
			fields: [{ fieldname: "react_area", fieldtype: "HTML" }],
		});

		dialog.fields_dict.react_area.$wrapper.html(`
			<div class="lex-quick-react-tray">${buttons}</div>
		`);

		dialog.$wrapper.on("click", ".lex-quick-react-btn", (e) => {
			const emoji = $(e.currentTarget).data("emoji");
			this.toggle_reaction(message_name, emoji);
			dialog.hide();
		});

		dialog.show();
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
				const channel = this.channels.find((item) => item.name === this.selected_channel);
				if (channel) {
					channel.notification_level = values.notification_level;
					channel.muted = values.notification_level === "Muted";
				}
				window.dispatchEvent(new CustomEvent("lex-chat-channel-notification-change", {
					detail: { channel: this.selected_channel, notification_level: values.notification_level },
				}));
				this.render_channels(this.$root.find(".lex-chat__channel-filter").val());
				this.render_channel_header(this.selected_channel_doc);
				dialog.hide();
			},
		});
		dialog.show();
	}

	async open_channel_members_dialog() {
		if (!this.selected_channel) return;
		const response = await frappe.call({
			method: `${this.api}.get_channel_members`,
			args: { channel: this.selected_channel },
		});
		const members = response.message || [];
		const member_markup = members.map((member) => {
			const presence = this.presence_for(member.name);
			const status = this.presence_summary(presence);
			return `<article class="lex-chat__member-row">
				<div class="lex-chat__member-avatar">${frappe.avatar(member.name, "avatar-medium")}${this.presence_dot(member.name)}</div>
				<div class="lex-chat__member-copy">
					<strong>${frappe.utils.escape_html(member.full_name || member.name)}</strong>
					<span>${frappe.utils.escape_html(member.primary_role || __("System User"))} · ${frappe.utils.escape_html(member.name)}</span>
					<small>${frappe.utils.escape_html(status)}</small>
				</div>
				<div class="lex-chat__member-access">
					<span class="lex-chat__channel-role">${frappe.utils.escape_html(member.channel_role || __("Member"))}</span>
					<small>${member.can_post_messages ? __("Can post") : __("Read only")}</small>
				</div>
			</article>`;
		}).join("");
		const can_manage = Boolean(this.selected_channel_doc?.can_manage);
		const dialog = new frappe.ui.Dialog({
			title: __("Channel members ({0})", [members.length]),
			size: "large",
			fields: [{ fieldname: "member_list", fieldtype: "HTML" }],
			primary_action_label: can_manage ? __("Manage Members & Roles") : __("Close"),
			primary_action: () => {
				dialog.hide();
				if (can_manage) frappe.set_route("Form", "Lexocrates Chat Channel", this.selected_channel);
			},
		});
		dialog.fields_dict.member_list.$wrapper.html(
			`<div class="lex-chat__member-list">${member_markup || `<div class="text-muted">${__("No members found")}</div>`}</div>`
		);
		dialog.show();
	}

	async open_direct_message_dialog() {
		const response = await frappe.call({ method: `${this.api}.search_users`, args: { search_text: "" } });
		const users = response.message || [];
		if (!users.length) return frappe.show_alert({ message: __("No eligible chat users found"), indicator: "orange" });
		const dialog = new frappe.ui.Dialog({
			title: __("New direct message"),
			fields: [{ fieldname: "other_user", fieldtype: "Autocomplete", label: __("System User"), options: users.map((user) => ({ label: `${user.full_name || user.name} · ${user.primary_role || __("System User")} · ${user.name}`, value: user.name, description: user.primary_role || __("System User") })), reqd: 1, description: __("Direct messages are private and available only between enabled System Users.") }],
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
			`<div class="lex-chat__thread-list">${messages.map((message, index) => `<article class="lex-chat__thread-item ${index ? "is-reply" : "is-root"}"><div><span><strong>${frappe.utils.escape_html(message.sender_full_name || message.sender)}</strong><small class="lex-chat__role-label">${frappe.utils.escape_html(message.sender_role || __("System User"))}</small></span><time>${frappe.utils.escape_html(message.formatted_timestamp || message.sent_at)}</time></div><div>${message.message_text}</div></article>`).join("")}</div>`
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
				{ fieldname: "members_section", fieldtype: "Section Break", label: __("Internal Team Members"), depends_on: "eval:doc.channel_type != 'Contextual'" },
				{
					fieldname: "members",
					fieldtype: "MultiSelectPills",
					label: __("Add System Users"),
					depends_on: "eval:doc.channel_type != 'Contextual'",
					description: __("The creator is Owner. Selected users join as Members; channel roles can be changed from Manage."),
					get_data: async (text) => {
						const response = await frappe.call({ method: `${this.api}.search_users`, args: { search_text: text || "" } });
						return (response.message || []).map((user) => ({
							value: user.name,
							label: `${user.full_name || user.name} · ${user.primary_role || __("System User")}`,
							description: user.name,
						}));
					},
				},
				{ fieldname: "reference_section", fieldtype: "Section Break", label: __("ERP Record Context"), depends_on: "eval:doc.channel_type == 'Contextual'" },
				{ fieldname: "reference_doctype", fieldtype: "Select", label: __("Reference DocType"), options: context_doctypes, depends_on: "eval:doc.channel_type == 'Contextual'", mandatory_depends_on: "eval:doc.channel_type == 'Contextual'" },
				{ fieldname: "reference_name", fieldtype: "Dynamic Link", label: __("Reference Name"), options: "reference_doctype", depends_on: "eval:doc.channel_type == 'Contextual'", mandatory_depends_on: "eval:doc.channel_type == 'Contextual'" },
			],
			primary_action_label: __("Create"),
			primary_action: async (values) => {
				const internal_channel = values.channel_type !== "Contextual";
				const members = internal_channel
					? (values.members || []).map((user) => ({ user, channel_role: "Member", can_post_messages: 1, can_invite_members: 0 }))
					: [];
				const response = await frappe.call({
					method: `${this.api}.create_channel`,
					args: {
						...values,
						members: JSON.stringify(members),
						system_user_only: internal_channel ? 1 : 0,
					},
				});
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
