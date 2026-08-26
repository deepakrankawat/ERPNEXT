(() => {
	"use strict";

	const CHAT_ROUTE = "/app/lexocrates-chat";
	const API_ROOT = "lex.lex.page.lexocrates_chat.lexocrates_chat";
	const CHAT_ROLES = new Set([
		"LPO_Admin",
		"LPO_Manager",
		"LPO_Analyst",
		"System Manager",
		"Junior Legal Associate",
		"Senior Legal Associate",
		"Lexocrates QA Manager",
		"Lexocrates Operations Manager",
		"Lexocrates AI Manager",
		"Lexocrates Compliance Officer",
		"Lexocrates Director",
		"Lexocrates Sales & Marketing",
		"Lexocrates HR",
		"Lexocrates Finance",
	]);

	const LPO_WORKSPACES = new Set([
		"Executive Workspace",
		"Legal Operations Workspace",
		"Junior Associate Workspace",
		"Senior Associate Workspace",
		"QA Workspace",
		"AI Workspace",
		"Client Workspace",
		"LPO Operation",
		"Lex",
		"Lexocrates Chat",
		"LPO Chat",
	]);

	let sound_muted = window.lexocratesChatSound?.isMuted()
		?? localStorage.getItem("lex_chat_sound_muted") === "1";
	let quick_chat_open = false;
	let active_quick_channel = null;
	let quick_messages = [];
	let chat_summary = { total_unread: 0, channels: [], all_channels: [] };
	function update_sound_button() {
		const soundBtn = document.getElementById("lex-floating-sound-toggle");
		if (!soundBtn) return;
		sound_muted = window.lexocratesChatSound?.isMuted() ?? sound_muted;
		soundBtn.innerHTML = sound_muted ? "&#128263;" : "&#128276;";
		soundBtn.title = sound_muted ? __("Unmute Sound") : __("Mute Sound");
		soundBtn.setAttribute("aria-label", sound_muted ? __("Unmute chat sounds") : __("Mute chat sounds"));
		soundBtn.setAttribute("aria-pressed", sound_muted ? "true" : "false");
		soundBtn.classList.toggle("is-muted", sound_muted);
	}

	function play_chat_sound(kind, key = null) {
		if (sound_muted) return;
		window.lexocratesChatSound?.play(kind, key);
	}

	function channel_allows_sound(message) {
		if (!message || message.sender === frappe.session.user) return false;
		const channel = (chat_summary.all_channels || []).find((item) => item.name === message.channel);
		if (!channel || channel.notification_level === "Muted") return false;
		if (
			channel.notification_level === "Mentions Only" &&
			!(message.mentions || []).includes(frappe.session.user)
		) return false;
		return true;
	}

	window.addEventListener(window.lexocratesChatSound?.CHANGE_EVENT || "lex-chat-sound-change", (event) => {
		sound_muted = Boolean(event.detail?.muted);
		update_sound_button();
	});
	window.addEventListener("lex-chat-channel-notification-change", (event) => {
		const changed = event.detail || {};
		for (const channel of chat_summary.all_channels || []) {
			if (channel.name === changed.channel) {
				channel.notification_level = changed.notification_level;
				channel.muted = changed.notification_level === "Muted";
			}
		}
	});

	function can_access_chat() {
		try {
			if (!window.frappe || !frappe.session) return false;
			return (
				frappe.session.user === "Administrator" ||
				(frappe.user_roles || []).some((role) => CHAT_ROLES.has(role))
			);
		} catch (e) {
			return false;
		}
	}

	function rename_lpo_operation_titles() {
		try {
			if (window.frappe && frappe.boot) {
				if (!frappe.boot._messages) frappe.boot._messages = {};
				frappe.boot._messages["Public"] = "LPO";
				frappe.boot._messages["PUBLIC"] = "LPO";
				frappe.boot._messages["Public Workspaces"] = "LPO Workspaces";
				frappe.boot._messages["LPO Operation"] = "LPO";
			}

			const pageTitles = document.querySelectorAll(".title-text, .navbar-brand, .app-title, .breadcrumb-item a, .dropdown-app-name");
			pageTitles.forEach((el) => {
				const txt = el.textContent.trim();
				if (txt === "LPO Operation") {
					el.textContent = "LPO";
				}
			});
		} catch (e) {
			console.warn("Could not rename LPO Operation titles", e);
		}
	}

	function patch_workspace_sidebar_natively() {
		try {
			rename_lpo_operation_titles();
			if (!window.frappe || !frappe.views || !frappe.views.Workspace) return false;
			if (frappe.views.Workspace.prototype._lpo_dual_patched) return true;

			frappe.views.Workspace.prototype._lpo_dual_patched = true;

			frappe.views.Workspace.prototype.make_sidebar = function () {
				if (this.sidebar.find(".standard-sidebar-section")[0]) {
					this.sidebar.find(".standard-sidebar-section").remove();
				}

				const allPublic = (this.public_pages || [])
					.filter((page) => !page.parent_page)
					.uniqBy((d) => d.title);

				const lpoPages = allPublic.filter((p) => LPO_WORKSPACES.has(p.title) || LPO_WORKSPACES.has(p.name));
				const generalPages = allPublic.filter((p) => !LPO_WORKSPACES.has(p.title) && !LPO_WORKSPACES.has(p.name));

				if (lpoPages.length) {
					this.build_sidebar_section({ id: "Public", label: "LPO" }, lpoPages);
				}
				if (generalPages.length) {
					this.build_sidebar_section({ id: "General", label: "General & ERPNext" }, generalPages);
				}

				this.sidebar.find(".selected").length &&
					!frappe.dom.is_element_in_viewport(this.sidebar.find(".selected")) &&
					this.sidebar.find(".selected")[0].scrollIntoView();

				this.remove_sidebar_skeleton();
			};

			if (frappe.workspace && typeof frappe.workspace.make_sidebar === "function") {
				frappe.workspace.make_sidebar();
			}
			return true;
		} catch (e) {
			console.warn("Could not patch Workspace sidebar natively", e);
			return false;
		}
	}

	async function fetch_unread_summary() {
		if (!can_access_chat()) return;
		try {
			const res = await frappe.call({
				method: `${API_ROOT}.get_unread_summary`,
				freeze: false,
			});
			if (res.message) {
				chat_summary = res.message;
				update_unread_badge();
				render_quick_channel_list();
			}
		} catch (e) {}
	}

	function update_unread_badge() {
		const total = Number(chat_summary.total_unread || 0);
		const badge = document.querySelector("#lexocrates-chat-navbar-badge");
		const launcherBadge = document.querySelector("#lex-floating-chat-badge");

		if (badge) {
			badge.textContent = total > 99 ? "99+" : total;
			badge.classList.toggle("hidden", total === 0);
		}
		if (launcherBadge) {
			launcherBadge.textContent = total > 99 ? "99+" : total;
			launcherBadge.classList.toggle("hidden", total === 0);
		}
	}

	function setup_chat_navbar_link() {
		patch_workspace_sidebar_natively();
		try {
			if (!window.frappe || !frappe.session) return false;
			const navbars = [...document.querySelectorAll("header.navbar ul.navbar-nav")];
			const navbar =
				navbars.find((candidate) => candidate.querySelector(".dropdown-navbar-user")) ||
				navbars.at(-1);
			if (!navbar) return false;

			let item = navbar.querySelector("#lexocrates-chat-navbar");
			if (!can_access_chat()) {
				item?.remove();
				remove_floating_chat();
				return true;
			}
			if (!item) {
				item = document.createElement("li");
				item.id = "lexocrates-chat-navbar";
				const notifications = navbar.querySelector(".dropdown-notifications");
				navbar.insertBefore(item, notifications || navbar.firstChild);
			}

			const label = typeof window.__ === "function" ? __("Lexocrates Chat") : "Lexocrates Chat";
			item.className = "nav-item lexocrates-chat-navbar";
			item.innerHTML = `
				<a class="nav-link lexocrates-chat-navbar-link" href="${CHAT_ROUTE}"
					title="${label}" aria-label="${label}">
					<svg class="es-icon icon-sm" aria-hidden="true">
						<use href="#es-line-chat-alt"></use>
					</svg>
					<span class="lexocrates-chat-navbar-label">${label}</span>
					<span id="lexocrates-chat-navbar-badge" class="lex-chat-nav-badge hidden">0</span>
				</a>`;

			const link = item.querySelector("a");
			const sync_active_state = () => {
				try {
					if (typeof frappe.get_route_str === "function") {
						const isChat = frappe.get_route_str() === "lexocrates-chat";
						link.classList.toggle("active", isChat);
						if (isChat) {
							hide_floating_widget();
						}
					}
					patch_workspace_sidebar_natively();
				} catch (e) {}
			};
			sync_active_state();
			if (window.$) {
				$(document).off("page-change.lexocrates-chat").on("page-change.lexocrates-chat", sync_active_state);
			}

			setup_floating_chat();
			fetch_unread_summary();
			bind_realtime_events();

			return true;
		} catch (err) {
			console.warn("Could not setup Lexocrates chat navbar link", err);
			return false;
		}
	}

	function setup_floating_chat() {
		if (!can_access_chat() || document.getElementById("lex-floating-chat-container")) return;

		const container = document.createElement("div");
		container.id = "lex-floating-chat-container";
		container.className = "lex-floating-chat-container";
		container.innerHTML = `
			<!-- Floating Launcher Button -->
			<button id="lex-floating-chat-launcher" class="lex-floating-launcher" title="${__("Quick Chat")}" aria-label="${__("Open Quick Chat")}">
				<svg class="es-icon icon-md lex-launcher-icon" aria-hidden="true">
					<use href="#es-line-chat-alt"></use>
				</svg>
				<span id="lex-floating-chat-badge" class="lex-floating-badge hidden">0</span>
			</button>

			<!-- Slide-out Glassmorphic Chat Widget -->
			<div id="lex-floating-chat-widget" class="lex-floating-widget hidden">
				<header class="lex-floating-header">
					<div class="lex-floating-title-area">
						<div class="lex-floating-status-dot"></div>
						<strong class="lex-floating-title">${__("Lexocrates Chat")}</strong>
					</div>
					<div class="lex-floating-header-actions">
						<button id="lex-floating-sound-toggle" class="btn btn-xs btn-default${sound_muted ? " is-muted" : ""}" type="button" title="${sound_muted ? __("Unmute Sound") : __("Mute Sound")}" aria-label="${sound_muted ? __("Unmute chat sounds") : __("Mute chat sounds")}" aria-pressed="${sound_muted ? "true" : "false"}">
							${sound_muted ? "&#128263;" : "&#128276;"}
						</button>
						<a href="${CHAT_ROUTE}" id="lex-floating-expand" class="btn btn-xs btn-default" title="${__("Open Full Page")}">
							<svg class="es-icon icon-xs"><use href="#es-line-expand"></use></svg>
						</a>
						<button id="lex-floating-close" class="btn btn-xs btn-default" title="${__("Minimize")}">×</button>
					</div>
				</header>

				<div class="lex-floating-body">
					<!-- Channels & DMs Sidebar/Tabs -->
					<div class="lex-floating-nav">
						<div class="lex-floating-search-box">
							<input type="search" id="lex-floating-search" class="form-control input-xs" placeholder="${__("Search conversations…")}">
						</div>
						<div id="lex-floating-channels-list" class="lex-floating-channels-list"></div>
					</div>

					<!-- Conversation Area -->
					<div class="lex-floating-conversation">
						<div class="lex-floating-conv-header">
							<span id="lex-floating-conv-name">${__("Select conversation")}</span>
						</div>
						<div id="lex-floating-messages" class="lex-floating-messages">
							<div class="lex-floating-empty">${__("Choose a channel or direct message to chat")}</div>
						</div>
						<footer class="lex-floating-composer">
							<input type="text" id="lex-floating-input" class="form-control input-sm" placeholder="${__("Type a message…")}" disabled>
							<button id="lex-floating-send" class="btn btn-primary btn-sm" disabled>→</button>
						</footer>
					</div>
				</div>
			</div>
		`;

		document.body.appendChild(container);

		// Event handlers for floating launcher & widget
		const launcher = document.getElementById("lex-floating-chat-launcher");
		const widget = document.getElementById("lex-floating-chat-widget");
		const closeBtn = document.getElementById("lex-floating-close");
		const soundBtn = document.getElementById("lex-floating-sound-toggle");
		const searchInput = document.getElementById("lex-floating-search");
		const input = document.getElementById("lex-floating-input");
		const sendBtn = document.getElementById("lex-floating-send");

		launcher.addEventListener("click", () => {
			if (typeof frappe.get_route_str === "function" && frappe.get_route_str() === "lexocrates-chat") {
				return;
			}
			quick_chat_open = !quick_chat_open;
			widget.classList.toggle("hidden", !quick_chat_open);
			if (quick_chat_open) {
				fetch_unread_summary();
				if (!active_quick_channel && chat_summary.all_channels?.length) {
					select_quick_channel(chat_summary.all_channels[0].name);
				}
			}
		});

		closeBtn.addEventListener("click", hide_floating_widget);

		soundBtn.addEventListener("click", () => {
			sound_muted = window.lexocratesChatSound?.setMuted(!sound_muted) ?? !sound_muted;
			if (!window.lexocratesChatSound) {
				localStorage.setItem("lex_chat_sound_muted", sound_muted ? "1" : "0");
			}
			update_sound_button();
			if (!sound_muted) window.lexocratesChatSound?.unlock();
			frappe.show_alert({ message: sound_muted ? __("Chat sounds muted") : __("Chat sounds enabled"), indicator: "blue" });
		});

		searchInput.addEventListener("input", (e) => {
			render_quick_channel_list(e.target.value);
		});

		const send_msg = async () => {
			const text = input.value.trim();
			if (!text || !active_quick_channel) return;
			window.lexocratesChatSound?.unlock();
			input.value = "";
			input.focus();
			try {
				const response = await frappe.call({
					method: `${API_ROOT}.send_message`,
					args: {
						channel: active_quick_channel,
						message_text: frappe.utils.escape_html(text).replace(/\n/g, "<br>"),
					},
					freeze: false,
				});
				if (response.message?.name) {
					play_chat_sound("sent", `sent:${response.message.name}`);
				}
				load_quick_messages(active_quick_channel);
			} catch (err) {
				frappe.show_alert({ message: __("Could not send message"), indicator: "red" });
			}
		};

		sendBtn.addEventListener("click", send_msg);
		input.addEventListener("keydown", (e) => {
			if (e.key === "Enter") {
				e.preventDefault();
				send_msg();
			}
		});
	}

	function hide_floating_widget() {
		quick_chat_open = false;
		const widget = document.getElementById("lex-floating-chat-widget");
		if (widget) widget.classList.add("hidden");
	}

	function remove_floating_chat() {
		document.getElementById("lex-floating-chat-container")?.remove();
	}

	function render_quick_channel_list(query = "") {
		const list = document.getElementById("lex-floating-channels-list");
		if (!list) return;
		const q = (query || "").toLowerCase().trim();
		const channels = (chat_summary.all_channels || []).filter((c) => {
			const label = (c.display_name || c.channel_name || "").toLowerCase();
			return !q || label.includes(q);
		});

		if (!channels.length) {
			list.innerHTML = `<div class="lex-floating-empty-sm">${__("No channels")}</div>`;
			return;
		}

		list.innerHTML = channels.map((c) => {
			const active = c.name === active_quick_channel ? "active" : "";
			const unread = Number(c.unread_count || 0);
			const label = frappe.utils.escape_html(c.display_name || c.channel_name);
			return `
				<button class="lex-floating-chan-item ${active}" data-channel="${frappe.utils.escape_html(c.name)}">
					<span class="lex-floating-chan-icon">${c.is_direct_message ? "@" : "#"}</span>
					<span class="lex-floating-chan-text">${label}</span>
					${unread > 0 ? `<span class="lex-floating-unread-badge">${unread}</span>` : ""}
				</button>
			`;
		}).join("");

		list.querySelectorAll(".lex-floating-chan-item").forEach((btn) => {
			btn.addEventListener("click", () => {
				select_quick_channel(btn.dataset.channel);
			});
		});
	}

	async function select_quick_channel(channel_name) {
		active_quick_channel = channel_name;
		render_quick_channel_list();

		const channel = (chat_summary.all_channels || []).find((c) => c.name === channel_name);
		const nameEl = document.getElementById("lex-floating-conv-name");
		const input = document.getElementById("lex-floating-input");
		const sendBtn = document.getElementById("lex-floating-send");

		if (nameEl) nameEl.textContent = channel?.display_name || channel?.channel_name || channel_name;
		if (input) input.disabled = false;
		if (sendBtn) sendBtn.disabled = false;

		if (window.frappe?.realtime) {
			frappe.realtime.emit("doc_subscribe", "Lexocrates Chat Channel", channel_name);
		}

		await load_quick_messages(channel_name);
		input?.focus();
	}

	async function load_quick_messages(channel_name) {
		const box = document.getElementById("lex-floating-messages");
		if (!box) return;
		try {
			const res = await frappe.call({
				method: `${API_ROOT}.get_messages`,
				args: { channel: channel_name, limit: 30 },
				freeze: false,
			});
			const messages = res.message || [];
			quick_messages = messages;
			if (!messages.length) {
				box.innerHTML = `<div class="lex-floating-empty">${__("No messages yet. Send a hello!")}</div>`;
				return;
			}
			box.innerHTML = messages.map((m) => {
				const isOwn = m.sender === frappe.session.user;
				const sender = frappe.utils.escape_html(m.sender_full_name || m.sender);
				return `
					<div class="lex-floating-msg ${isOwn ? "is-own" : ""}">
						<div class="lex-floating-msg-head">
							<strong>${sender}</strong>
							<time>${frappe.utils.escape_html(m.formatted_timestamp || "")}</time>
						</div>
						<div class="lex-floating-msg-text">${m.message_text || ""}</div>
					</div>
				`;
			}).join("");
			box.scrollTop = box.scrollHeight;
		} catch (e) {}
	}

	let realtime_bound = false;
	function bind_realtime_events() {
		if (realtime_bound || !window.frappe?.realtime) return;
		realtime_bound = true;

		frappe.realtime.on("new_chat_message", (message) => {
			const should_notify = channel_allows_sound(message);
			if (should_notify) {
				play_chat_sound("incoming", message.name ? `incoming:${message.name}` : null);
			}
			fetch_unread_summary();

			if (quick_chat_open && message.channel === active_quick_channel) {
				load_quick_messages(active_quick_channel);
			} else if (!quick_chat_open && should_notify) {
				const channel = (chat_summary.all_channels || []).find((c) => c.name === message.channel);
				const title = channel?.display_name || channel?.channel_name || message.sender_full_name || message.sender;
				frappe.show_alert({
					message: `💬 <strong>${frappe.utils.escape_html(title)}</strong>: ${frappe.utils.escape_html(message.sender_full_name || message.sender)}: ${$("<div>").html(message.message_text).text().slice(0, 60)}`,
					indicator: "blue"
				});
			}
		});

		frappe.realtime.on("chat_mention", (message) => {
			const should_notify = channel_allows_sound(message);
			if (should_notify) {
				play_chat_sound("incoming", message.name ? `incoming:${message.name}` : null);
			}
			fetch_unread_summary();
			if (!should_notify) return;

			const channel = (chat_summary.all_channels || []).find((c) => c.name === message.channel);
			const title = channel?.display_name || channel?.channel_name || message.sender_full_name || message.sender;
			const cleanText = $("<div>").html(message.message_text || "").text().slice(0, 100);

			// Prominent Alert Toast in Desk
			frappe.show_alert({
				message: `📢 <strong>${frappe.utils.escape_html(message.sender_full_name || message.sender)}</strong> mentioned you in <strong>#${frappe.utils.escape_html(title)}</strong>: "${frappe.utils.escape_html(cleanText)}"`,
				indicator: "orange"
			}, 10);

			// Browser Desktop Push Notification
			if (window.Notification) {
				if (Notification.permission === "granted" && document.hidden) {
					try {
						new Notification(`📢 Mentioned by ${message.sender_full_name || message.sender}`, {
							body: `#${title}: ${cleanText}`,
							tag: `mention-${message.name}`
						});
					} catch (e) {}
				} else if (Notification.permission === "default") {
					Notification.requestPermission();
				}
			}
		});

		frappe.realtime.on("chat_read_receipt", () => {
			fetch_unread_summary();
		});
	}

	if (window.$) {
		$(document).on("toolbar_setup", setup_chat_navbar_link);
		$(document).on("page-change", patch_workspace_sidebar_natively);
	}
	function initialize_when_toolbar_is_ready(attempt = 0) {
		patch_workspace_sidebar_natively();
		if (setup_chat_navbar_link() || attempt >= 100) return;
		window.setTimeout(() => initialize_when_toolbar_is_ready(attempt + 1), 100);
	}
	const toolbar_observer = new MutationObserver(() => {
		patch_workspace_sidebar_natively();
		if (setup_chat_navbar_link()) toolbar_observer.disconnect();
	});
	toolbar_observer.observe(document.documentElement, { childList: true, subtree: true });

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", () => initialize_when_toolbar_is_ready(), { once: true });
	} else {
		initialize_when_toolbar_is_ready();
	}
})();
