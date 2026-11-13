(() => {
	"use strict";

	const THEME_STORAGE_KEY = "lexocrates-portal-theme";
	const INTAKE_DRAFT_KEY = "lexocrates_client_intake_draft_v1";
	const enforceLightTheme = () => {
		document.documentElement.setAttribute("data-theme", "light");
		document.documentElement.style.colorScheme = "light";
		try { localStorage.removeItem(THEME_STORAGE_KEY); } catch (_) { /* localStorage unavailable */ }
	};

	enforceLightTheme();
	new MutationObserver(() => {
		if (document.documentElement.getAttribute("data-theme") !== "light") enforceLightTheme();
	}).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

	const state = {
		data: null,
		activeSection: "overview",
		matterView: "cards",
		matterFilter: { query: "", status: "all", practice: "all" },
		jobFilter: { query: "", status: "all", priority: "all" },
		intakeFilter: "all",
		docFilter: { query: "", matter: "all", type: "all" },
		invoiceFilter: { query: "", status: "all" },
		selectedApprovalJob: null,
		drawer: null,
		pendingMatterForIntake: null,
	};

	const activeBlobUrls = new Set();
	const trackBlobUrl = (url) => { if (url) activeBlobUrls.add(url); return url; };
	const revokeBlobUrl = (url) => { if (url && activeBlobUrls.has(url)) { URL.revokeObjectURL(url); activeBlobUrls.delete(url); } };
	const revokeAllBlobUrls = () => { for (const url of activeBlobUrls) URL.revokeObjectURL(url); activeBlobUrls.clear(); };

	const init = () => {
		const root = document.getElementById("lex-client-portal");
		if (!root) return;
		bindLogout(document.getElementById("lex-portal-logout"));
		if (root.dataset.portalAccess === "denied") return;
		call("lex.client_portal.get_portal_dashboard")
			.then((data) => render(root, data))
			.catch((error) => renderFailure(root, error));
	};

	if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
	else init();

	const escapeHTML = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
		"&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
	})[char]);
	const brandedText = (value) => escapeHTML(value)
		.replace(/\bLextimator\b/g, 'Lextimator<sup class="lex-tm">TM</sup>')
		.replace(/\bLexPack(s?)\b/g, 'LexPack<sup class="lex-tm">TM</sup>$1');
	const statusClass = (value) => String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
	const indicatorColor = (value) => {
		const status = String(value || "").toLowerCase();
		if (["active", "completed", "approved", "delivered", "paid", "clean", "accepted"].includes(status)) return "green";
		if (["urgent", "changes requested", "overdue", "unpaid", "blocked", "rejected", "highly confidential", "restricted"].includes(status)) return "red";
		if (["high", "ready for delivery", "pending", "draft", "on hold", "pending client information", "pending client approval", "sla paused"].includes(status)) return "orange";
		if (["confidential"].includes(status)) return "purple";
		return "blue";
	};
	const call = (method, args = {}) => frappe.call({ method, args }).then((response) => response.message);

	function callWithProgress(method, args, onProgress, onUploadDone) {
		return new Promise((resolve, reject) => {
			const xhr = new XMLHttpRequest();
			xhr.open("POST", `/api/method/${method}`);
			xhr.setRequestHeader("Content-Type", "application/json; charset=utf-8");
			xhr.setRequestHeader("X-Frappe-CSRF-Token", frappe.csrf_token || "");
			xhr.upload.onprogress = (event) => {
				if (onProgress && event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
			};
			xhr.upload.onload = () => { if (onUploadDone) onUploadDone(); };
			xhr.onload = () => {
				let data;
				try { data = JSON.parse(xhr.responseText); } catch (error) { return reject(error); }
				if (xhr.status >= 200 && xhr.status < 300) resolve(data.message);
				else reject(data);
			};
			xhr.onerror = () => reject(new Error("Network error during upload."));
			xhr.send(JSON.stringify(args));
		});
	}

	const presence = new Map();
	let currentPresenceUser = null;
	let presenceHeartbeatTimer = null;
	let lastPresenceActivity = Date.now();
	const presenceApi = "lex.lex.doctype.lexocrates_chat_presence.lexocrates_chat_presence";

	let navigationGlobalsBound = false;
	let navbarGlobalsBound = false;
	let presenceGlobalsBound = false;
	let chatGlobalsBound = false;
	let currentActivate = () => {};
	let currentSetSidebarOpen = () => {};
	let currentCloseUserMenu = () => {};
	let currentChatCleanup = null;
	let currentChatController = null;

	const fmtDate = (value) => {
		if (!value) return "—";
		try { return frappe.datetime.str_to_user(value); }
		catch (_) { return String(value); }
	};
	const fmtNumber = (value) => Number(value || 0).toLocaleString();
	const fmtMoney = (value, currency = "INR") => {
		try { return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(Number(value || 0)); }
		catch (_) { return `${currency} ${fmtNumber(value)}`; }
	};
	const pilotMoney = (value, currency) => {
		const prefix = { CAD: "CA$", USD: "US$", GBP: "£" }[currency] || `${currency} `;
		return `${prefix}${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
	};
	const capacityMoney = (value, currency) => fmtMoney(value || 0, currency || "CAD");
	const initials = (name) => String(name || "L").split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
	const empty = (text) => `<div class="lex-empty">${escapeHTML(text)}</div>`;
	const formatBytes = (bytes) => { const value = Number(bytes || 0); return value > 1048576 ? `${(value / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(value / 1024))} KB`; };

	const presenceSummary = (item) => {
		item = item || { status: "Offline" };
		if (item.status === "Online") return "Online";
		const timestamp = item.status === "Offline" ? item.last_seen_at : item.last_activity_at;
		return timestamp ? `${item.status} · ${item.status === "Offline" ? "Last seen" : "Active"} ${fmtDate(timestamp)}` : item.status;
	};
	const presenceDot = (user) => {
		const item = presence.get(user) || { status: "Offline" };
		return `<span class="lex-presence-dot is-${statusClass(item.status || "Offline")}" data-presence-user="${escapeHTML(user || "")}" title="${escapeHTML(presenceSummary(item))}"></span>`;
	};

	const errorMessage = (error) => {
		if (typeof error === "string") return error;
		try {
			const messages = JSON.parse(error?._server_messages || "[]");
			for (const item of messages) {
				const parsed = typeof item === "string" ? JSON.parse(item) : item;
				if (parsed?.message) return String(parsed.message).replace(/<[^>]+>/g, "");
			}
		} catch (_) { /* use fallback */ }
		return error?.message && error.message !== "[object Object]"
			? error.message
			: "The requested action could not be completed.";
	};

	function notify(message, indicator = "green") {
		if (frappe.show_alert) frappe.show_alert({ message, indicator }, 5);
		else window.alert(message);
	}

	function showError(title, error) {
		const message = escapeHTML(errorMessage(error));
		if (frappe.msgprint) frappe.msgprint({ title, message, indicator: "red" });
		else window.alert(`${title}: ${message}`);
	}

	function setBusy(button, label) {
		if (!button) return;
		if (!button.dataset.lexIdleHtml) button.dataset.lexIdleHtml = button.innerHTML;
		button.disabled = true;
		button.innerHTML = `<span class="lex-spinner" aria-hidden="true"></span>${escapeHTML(label)}`;
	}

	function clearBusy(button) {
		if (!button) return;
		button.disabled = false;
		if (button.dataset.lexIdleHtml) {
			button.innerHTML = button.dataset.lexIdleHtml;
			delete button.dataset.lexIdleHtml;
		}
	}

	function setUploadProgress(button, percent) {
		if (!button) return;
		if (!button.dataset.lexIdleHtml) button.dataset.lexIdleHtml = button.innerHTML;
		button.disabled = true;
		button.innerHTML = `<span class="lex-spinner" aria-hidden="true"></span>Uploading... ${percent}%`;
	}

	function bindLogout(button) {
		button?.addEventListener("click", async () => {
			button.disabled = true;
			button.textContent = "Signing out...";
			try {
				localStorage.removeItem("current_app");
				localStorage.removeItem("current_route");
				await frappe.call({ method: "logout" });
			} finally { window.location.assign("/client-login"); }
		});
	}

	function renderFailure(root, error) {
		root.setAttribute("aria-busy", "false");
		root.innerHTML = `<div class="lex-state-card" role="alert"><div class="lex-state-mark">!</div><h1>Client workspace unavailable</h1><p>${escapeHTML(errorMessage(error))}</p><button id="lex-portal-logout" class="lex-button btn btn-primary btn-sm" type="button">Log out and use another account</button></div>`;
		bindLogout(document.getElementById("lex-portal-logout"));
	}

	function icon(name) {
		const paths = {
			home: '<rect x="3.5" y="3.5" width="17" height="17" rx="4"/><path d="M3.5 9.5h17M9 21V13h6v8"/>',
			briefcase: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5.5A1.5 1.5 0 0 1 9.5 4h5A1.5 1.5 0 0 1 16 5.5V7M3 12h18"/>',
			plus: '<path d="M12 5v14M5 12h14"/>',
			clipboard: '<rect x="6" y="4" width="12" height="17" rx="2"/><path d="M9 4V3.5A1.5 1.5 0 0 1 10.5 2h3A1.5 1.5 0 0 1 15 3.5V4M9 11h6M9 15h6"/>',
			file: '<path d="M7 3h7l4 4v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z"/><path d="M14 3v4h4"/>',
			check: '<path d="M4.5 12.5 9 17l10.5-10.5"/>',
			chart: '<path d="M4 20V10M11 20V4M18 20v-7"/><path d="M3 20h18"/>',
			message: '<path d="M4 5h16a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9l-5 4v-4H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Z"/>',
			invoice: '<path d="M6 2h9l4 4v16H6z"/><path d="M15 2v4h4M9 11h6M9 15h4"/>',
			wallet: '<rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18M15 14h2.5"/>',
			users: '<circle cx="9" cy="8" r="3.2"/><path d="M3.5 20a5.5 5.5 0 0 1 11 0"/><circle cx="17.5" cy="9" r="2.5"/><path d="M15.5 13a5 5 0 0 1 5.5 5"/>',
			settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1.1-1.55 1.7 1.7 0 0 0-1.88.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.55-1.1 1.7 1.7 0 0 0-.34-1.88l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34H9a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87V9a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.55 1Z"/>',
			help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 0 1 4.9.7c0 1.6-2.4 1.9-2.4 3.6"/><path d="M12 17.5h.01"/>',
			menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
			logout: '<path d="M9 21H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h4"/><path d="M15 16l5-4-5-4M20 12H9"/>',
			search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m20 20-4.35-4.35"/>',
			shield: '<path d="M12 3 4.5 6v6c0 4.8 3.2 8.2 7.5 9.5 4.3-1.3 7.5-4.7 7.5-9.5V6L12 3Z"/><path d="m9.5 12.2 1.8 1.8 3.5-3.8"/>',
			clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
			eye: '<path d="M2.5 12s3.5-6.5 9.5-6.5 9.5 6.5 9.5 6.5-3.5 6.5-9.5 6.5S2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="2.5"/>',
			upload: '<path d="M12 15V4M7.5 8.5 12 4l4.5 4.5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
			calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/>',
		};
		return `<span class="lex-icon" aria-hidden="true"><svg viewBox="0 0 24 24">${paths[name] || paths.file}</svg></span>`;
	}

	/* ---------- Custom Accessible Modal & Drawer Layer ---------- */

	function closeModal() {
		document.getElementById("lex-modal-root")?.replaceChildren();
		document.body.classList.remove("lex-portal-sidebar-open");
	}

	function openModal({ title, subtitle = "", bodyHtml, wide = false, confirmText = "", cancelText = "Cancel", danger = false, onMount, onConfirm }) {
		const host = document.getElementById("lex-modal-root");
		if (!host) return;
		host.innerHTML = `<div class="lex-modal-backdrop" data-modal-backdrop>
			<div class="lex-modal ${wide ? "is-wide" : ""}" role="dialog" aria-modal="true" aria-labelledby="lex-modal-title">
				<div class="lex-modal-head">
					<div><h2 id="lex-modal-title">${escapeHTML(title)}</h2>${subtitle ? `<p>${escapeHTML(subtitle)}</p>` : ""}</div>
					<button type="button" class="lex-close-x" data-modal-close aria-label="Close dialog">&times;</button>
				</div>
				<div class="lex-modal-body">${bodyHtml}<div data-modal-error class="lex-alert" hidden></div></div>
				${(confirmText || cancelText) ? `<div class="lex-modal-foot">
					${cancelText ? `<button type="button" class="lex-button secondary btn btn-default btn-sm" data-modal-close>${escapeHTML(cancelText)}</button>` : ""}
					${confirmText ? `<button type="button" class="lex-button ${danger ? "danger btn-danger" : "btn-primary"} btn btn-sm" data-modal-confirm>${escapeHTML(confirmText)}</button>` : ""}
				</div>` : ""}
			</div>
		</div>`;
		const backdrop = host.querySelector("[data-modal-backdrop]");
		const errBox = host.querySelector("[data-modal-error]");
		const confirmBtn = host.querySelector("[data-modal-confirm]");
		const close = () => closeModal();
		host.querySelectorAll("[data-modal-close]").forEach((btn) => btn.addEventListener("click", close));
		backdrop?.addEventListener("click", (event) => { if (event.target === backdrop) close(); });
		onMount?.(host);
		confirmBtn?.addEventListener("click", async () => {
			if (!onConfirm) return close();
			errBox.hidden = true;
			setBusy(confirmBtn, "Processing...");
			try {
				const shouldClose = await onConfirm(host, errBox);
				if (shouldClose !== false) close();
				else clearBusy(confirmBtn);
			} catch (error) {
				errBox.textContent = errorMessage(error);
				errBox.hidden = false;
				clearBusy(confirmBtn);
			}
		});
		host.querySelector("input, textarea, select, [data-modal-confirm], [data-modal-close]")?.focus();
	}

	function closeDrawer() {
		state.drawer = null;
		document.getElementById("lex-drawer-root")?.replaceChildren();
	}

	function openDrawer({ title, subtitle = "", tabs = [], activeTab = 0, onMount }) {
		const host = document.getElementById("lex-drawer-root");
		if (!host) return;
		const renderDrawerTabs = (idx) => {
			const current = tabs[idx] || tabs[0];
			host.innerHTML = `<div class="lex-drawer-backdrop" data-drawer-backdrop>
				<aside class="lex-drawer" role="dialog" aria-modal="true" aria-labelledby="lex-drawer-title">
					<div class="lex-drawer-head">
						<div><h2 id="lex-drawer-title">${escapeHTML(title)}</h2>${subtitle ? `<p>${escapeHTML(subtitle)}</p>` : ""}</div>
						<button type="button" class="lex-close-x" data-drawer-close aria-label="Close drawer">&times;</button>
					</div>
					${tabs.length > 1 ? `<div class="lex-drawer-tabs" role="tablist">${tabs.map((tab, i) => `<button type="button" role="tab" class="lex-drawer-tab ${i === idx ? "is-active" : ""}" data-drawer-tab="${i}" aria-selected="${i === idx}">${escapeHTML(tab.label)}</button>`).join("")}</div>` : ""}
					<div class="lex-drawer-body">${current ? current.html : ""}</div>
				</aside>
			</div>`;
			host.querySelectorAll("[data-drawer-close]").forEach((btn) => btn.addEventListener("click", closeDrawer));
			const backdrop = host.querySelector("[data-drawer-backdrop]");
			backdrop?.addEventListener("click", (event) => { if (event.target === backdrop) closeDrawer(); });
			host.querySelectorAll("[data-drawer-tab]").forEach((btn) => btn.addEventListener("click", () => renderDrawerTabs(Number(btn.dataset.drawerTab))));
			onMount?.(host, current?.id);
		};
		renderDrawerTabs(activeTab);
	}

	async function loadProtectedPreviewInto(container, url, title) {
		if (!container || !url) return;
		container.innerHTML = `<div class="lex-empty"><span class="lex-spinner" aria-hidden="true"></span> Loading watermarked preview...</div>`;
		try {
			const response = await fetch(url, { credentials: "same-origin" });
			if (!response.ok) throw new Error("Unable to load protected preview.");
			const contentType = (response.headers.get("Content-Type") || "").toLowerCase();
			if (contentType.includes("application/pdf")) {
				const blob = await response.blob();
				const blobUrl = trackBlobUrl(URL.createObjectURL(new Blob([blob], { type: "application/pdf" })));
				container.innerHTML = `<iframe class="lex-pdf-frame" title="${escapeHTML(title)}" src="${blobUrl}#toolbar=1"></iframe>`;
			} else if (contentType.startsWith("text/")) {
				const text = await response.text();
				container.innerHTML = `<pre class="lex-text-preview">${escapeHTML(text)}</pre>`;
			} else {
				container.innerHTML = `<div class="lex-empty">Inline preview is only supported for PDF and text files. Use the protected download button to view this file.</div>`;
			}
		} catch (error) {
			container.innerHTML = `<div class="lex-alert">${escapeHTML(errorMessage(error))}</div>`;
		}
	}

	function openDocumentPreviewModal(title, subtitle, url) {
		openModal({
			title,
			subtitle: `${subtitle || "Protected Document"} · Watermarked & audited on access`,
			wide: true,
			cancelText: "Close",
			bodyHtml: `<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
				<span class="lex-trust-badge">${icon("shield")} Personalized Watermark Active</span>
				<a class="lex-button secondary btn btn-default btn-sm" href="${escapeHTML(url)}" target="_blank" rel="noopener">Download protected copy</a>
			</div>
			<div id="lex-modal-preview-frame"></div>`,
			onMount: (host) => {
				loadProtectedPreviewInto(host.querySelector("#lex-modal-preview-frame"), url, title);
			},
		});
	}

	/* ---------- Main Shell Render ---------- */

	function render(root, data) {
		state.data = data;
		revokeAllBlobUrls();
		currentChatCleanup?.();
		currentChatCleanup = null;
		currentChatController = null;
		root.setAttribute("aria-busy", "false");
		const clientName = data.client.customer_name || "Client Workspace";
		const actionItems = buildActionQueue(data);
		const actionTotal = actionItems.length;
		root.innerHTML = `<div class="lex-desk-shell" id="lex-app">
			<header class="lex-navbar navbar navbar-expand sticky-top" role="navigation">
				<div class="container">
					<a class="navbar-brand navbar-home" href="/client-portal" aria-label="Client Workspace home"><span class="lexocrates-brand-wordmark"><img class="app-logo lexocrates-logo-dark" src="/assets/lex/images/lexocrates-logo-dark.svg" alt="Lexocrates"><img class="app-logo lexocrates-logo-light" src="/assets/lex/images/lexocrates-logo-light.svg" alt=""></span></a>
					<ul class="nav navbar-nav lex-breadcrumbs d-none d-sm-flex"><li><a href="/client-portal">Client Workspace</a></li></ul>
					<div class="collapse navbar-collapse justify-content-end">
						<div class="lex-search-wrap">
							<form id="lex-workspace-search" class="form-inline fill-width justify-content-end" role="search"><div class="input-group search-bar text-muted"><input name="query" type="search" class="form-control" placeholder="Search matters, jobs, documents..." autocomplete="off"><span class="lex-search-kbd">⌘K</span><span class="search-icon">${icon("search")}</span></div></form>
							<div id="lex-command-popover" class="lex-command-popover" hidden></div>
						</div>
						<ul class="navbar-nav">
							<li class="nav-item"><button class="btn-reset nav-link notifications-icon text-muted" type="button" data-go="messages" aria-label="Messages" title="Privileged Messages">${icon("message")}</button></li>
							<li class="vertical-bar d-none d-sm-block"></li>
							<li class="nav-item d-none d-md-block"><a class="nav-link" href="mailto:support@lexocrates.com">Help</a></li>
							<li class="nav-item dropdown lex-user-dropdown"><button class="btn-reset nav-link" type="button" data-user-menu-toggle aria-label="User menu"><span class="lex-presence-avatar"><span class="avatar avatar-medium" title="${escapeHTML(data.profile.full_name)}">${escapeHTML(initials(data.profile.full_name))}</span>${presenceDot(data.profile.email)}</span></button><div class="dropdown-menu dropdown-menu-right" data-user-menu><div class="lex-user-menu-head"><strong>${escapeHTML(data.profile.full_name)}</strong><span>${escapeHTML(data.profile.portal_role)}</span><small id="lex-current-presence">Offline</small></div><div class="dropdown-divider"></div><div class="lex-presence-menu"><label for="lex-presence-select">Availability</label><select id="lex-presence-select" class="form-control input-xs"><option value="Online">Online</option><option value="Away">Away</option><option value="Busy">Busy</option><option value="Offline">Offline</option></select></div><div class="dropdown-divider"></div><button id="lex-portal-logout" class="dropdown-item" type="button">Log out</button></div></li>
						</ul>
					</div>
				</div>
			</header>
			<div class="lex-desk-body">
				<div class="lex-sidebar-overlay" data-close-sidebar></div>
				<aside id="lex-client-navigation" class="lex-sidebar desk-sidebar standard-sidebar" aria-label="Client workspace navigation">
					<div class="lex-sidebar-title"><button class="btn-reset" type="button" data-close-sidebar aria-label="Close navigation">${icon("menu")}</button><div><strong>Client Workspace</strong><span>${escapeHTML(data.client.customer_name)}</span></div></div>
					<nav class="lex-nav standard-sidebar-section"><div class="lex-nav-label standard-sidebar-label">Workspace</div>${data.navigation.map((item, index) => navItem(item, index, data, actionTotal)).join("")}</nav>
				</aside>
				<div class="lex-workspace">
					<header class="lex-topbar page-head"><div class="lex-topbar-inner page-head-content"><div class="lex-topbar-start"><button class="lex-mobile-menu btn btn-default btn-sm" type="button" data-open-sidebar aria-label="Open navigation" aria-controls="lex-client-navigation" aria-expanded="false">${icon("menu")}</button><div class="lex-page-heading"><h1 id="lex-page-title">Dashboard</h1><span>${escapeHTML(data.client.customer_name)}</span></div></div><div class="lex-topbar-end"><span class="lex-trust-badge" title="Private encrypted document storage with WORM audit logging">${icon("shield")} Private Vault · Audited</span><span class="indicator-pill blue no-indicator-dot">${escapeHTML(clientName)}</span></div></div></header>
					<div class="lex-content layout-main-section">
					${data.profile.mfa_required && !data.profile.mfa_enabled ? '<div class="lex-alert">Multi-factor authentication is required for this account. Contact Lexocrates support before handling sensitive work.</div>' : ''}
					${overviewSection(data, actionItems)}${mattersSection(data)}${workIntakeSection(data)}${workRequestsSection(data)}${documentsSection(data)}${approvalsSection(data)}${reportsSection(data)}${messagesSection()}${billingSection(data)}${walletSection(data)}${usersSection(data)}${organizationSection(data)}
					</div>
				</div>
			</div>
			<footer class="lex-portal-legal-footer" aria-label="Legal and compliance">
				<span>© 2026 Lexocrates Legal Services Private Limited</span>
				<nav><a href="/terms-and-conditions">Terms</a><a href="/privacy-policy">Privacy</a><a href="/refund-cancellation-policy">Refunds &amp; Cancellations</a><a href="/contact-us">Contact</a></nav>
			</footer>
			<div id="lex-drawer-root"></div>
			<div id="lex-modal-root"></div>
		</div>`;

		bindLogout(document.getElementById("lex-portal-logout"));
		bindNavigation(root, data);
		bindNavbar(root, data);
		bindForms(root, data);
		bindInteractiveWorkspace(root, data);
		setupPresence(data.profile.email);
	}

	/* ---------- Presence ---------- */

	function applyPresence(item) {
		if (!item?.user) return;
		presence.set(item.user, item);
		document.querySelectorAll(`[data-presence-user="${CSS.escape(item.user)}"]`).forEach((dot) => {
			dot.className = `lex-presence-dot is-${statusClass(item.status || "Offline")}`;
			dot.title = presenceSummary(item);
		});
		if (item.user === currentPresenceUser) {
			const label = document.getElementById("lex-current-presence");
			if (label) label.textContent = presenceSummary(item);
			const select = document.getElementById("lex-presence-select");
			if (select) select.value = item.preferred_status || "Online";
		}
	}

	async function refreshPresence(users = null) {
		const items = await call(`${presenceApi}.get_presence`, users ? { users: JSON.stringify(users) } : {});
		(items || []).forEach(applyPresence);
		return items || [];
	}

	async function heartbeatPresence(isActive = true, status = null) {
		if (!currentPresenceUser) return;
		try {
			const item = await call(`${presenceApi}.update_presence`, {
				status: status || "",
				is_active: isActive ? 1 : 0,
			});
			applyPresence(item);
		} catch (_) { /* stale scheduler handles missed heartbeats */ }
	}

	function setupPresence(user) {
		currentPresenceUser = user;
		refreshPresence().then(() => heartbeatPresence(!document.hidden)).catch(() => {});
		document.getElementById("lex-presence-select")?.addEventListener("change", (event) => {
			heartbeatPresence(!document.hidden, event.target.value);
		});
		if (presenceGlobalsBound) return;
		presenceGlobalsBound = true;
		for (const eventName of ["mousemove", "keydown", "click", "touchstart"]) {
			document.addEventListener(eventName, () => { lastPresenceActivity = Date.now(); }, { passive: true });
		}
		document.addEventListener("visibilitychange", () => heartbeatPresence(!document.hidden));
		frappe.realtime?.on("chat_presence_changed", applyPresence);
		if (!presenceHeartbeatTimer) {
			presenceHeartbeatTimer = window.setInterval(() => {
				const active = !document.hidden && Date.now() - lastPresenceActivity < 5 * 60 * 1000;
				heartbeatPresence(active);
			}, 30000);
		}
		window.addEventListener("pagehide", sendPresenceOffline, { once: true });
	}

	function sendPresenceOffline() {
		if (!currentPresenceUser || !frappe.csrf_token) return;
		fetch(`/api/method/${presenceApi}.update_presence`, {
			method: "POST",
			body: new URLSearchParams({ is_active: "0", disconnect: "1" }),
			credentials: "same-origin",
			keepalive: true,
			headers: { "X-Frappe-CSRF-Token": frappe.csrf_token },
		}).catch(() => {});
	}

	/* ---------- Navigation & Layout Primitives ---------- */

	function navItem(item, index, data, actionTotal = 0) {
		let count = 0;
		if (item.section === "approvals") count = Number(data.metrics.approvals || 0);
		else if (item.section === "new-matter") count = Number(data.metrics.info_holds || 0);
		else if (item.section === "work-requests") count = Number(data.metrics.pending_confirmations || 0) + Number(data.metrics.pending_scope_changes || 0);
		else if (item.section === "overview" && actionTotal) count = actionTotal;
		const badge = count ? `<span class="lex-nav-badge">${count}</span>` : "";
		if (item.href) return `<a class="standard-sidebar-item" href="${escapeHTML(item.href)}">${icon(item.icon)}<span class="sidebar-item-label">${brandedText(item.label)}</span></a>`;
		return `<button type="button" data-section="${escapeHTML(item.section)}" data-title="${escapeHTML(item.label)}" class="standard-sidebar-item ${index === 0 ? "active selected" : ""}">${icon(item.icon)}<span class="sidebar-item-label">${brandedText(item.label)}</span>${badge}</button>`;
	}

	function sectionHeader(_title, text, actions = "") {
		return `<div class="lex-section-header"><div><p>${brandedText(text)}</p></div>${actions ? `<div class="lex-section-actions">${actions}</div>` : ""}</div>`;
	}
	function card(title, note, body, className = "") {
		return `<article class="lex-card widget border ${className}"><div class="lex-card-head widget-head"><div class="widget-label"><h3 class="widget-title">${brandedText(title)}</h3><small>${brandedText(note)}</small></div></div>${body}</article>`;
	}
	function formCard(title, note, formId, body) {
		return `<article class="lex-form-shell std-form-layout"><div class="form-layout"><div class="form-page"><div class="form-section card-section visible-section"><div class="section-head">${brandedText(title)}</div><div class="form-section-description">${brandedText(note)}</div><div class="section-body"><form id="${escapeHTML(formId)}" class="lex-form">${body}</form></div></div></div></div></article>`;
	}
	function metric(label, value, note, iconName, goSection = "") {
		if (goSection) {
			return `<button type="button" class="lex-metric lex-metric-btn widget number-widget-box" data-go="${escapeHTML(goSection)}"><div class="lex-metric-head"><span>${escapeHTML(label)}</span>${icon(iconName)}</div><strong>${escapeHTML(value)}</strong><small>${escapeHTML(note)}</small></button>`;
		}
		return `<article class="lex-metric widget number-widget-box"><div class="lex-metric-head"><span>${escapeHTML(label)}</span>${icon(iconName)}</div><strong>${escapeHTML(value)}</strong><small>${escapeHTML(note)}</small></article>`;
	}

	/* ---------- Action Center & Dashboard ---------- */

	function buildActionQueue(data) {
		const items = [];
		if (data.permissions.can_create_matters && data.master_sla && data.master_sla.status !== "Accepted") {
			items.push({
				urgent: true,
				badge: "Compliance Gate",
				title: "Accept Master Service Level Agreement",
				detail: "Required once before submitting new legal assignments.",
				buttonLabel: "Review & Accept SLA",
				attr: 'data-go="new-matter"',
			});
		}
		for (const intake of data.intakes || []) {
			if (intake.status === "Pending Client Information") {
				items.push({
					urgent: Boolean(intake.information_is_critical),
					badge: intake.information_is_critical ? "Critical Info Hold" : "Info Requested",
					title: intake.intake_title,
					detail: intake.information_received_on
						? "Clarification submitted — awaiting Legal Operations verification."
						: (intake.missing_information || "Additional client clarification is needed to resume SLA."),
					buttonLabel: intake.information_received_on ? "View Response" : "Respond Now",
					attr: `data-open-info-hold="${escapeHTML(intake.name)}"`,
				});
			} else if (["Quote Ready", "Funding Pending"].includes(intake.status)) {
				items.push({
					urgent: false,
					badge: "Quote Ready",
					title: intake.intake_title,
					detail: `Fixed quote ${fmtMoney(intake.quoted_amount, intake.currency || "CAD")} ready for funding or pilot.`,
					buttonLabel: "Review & Fund",
					attr: `data-go="new-matter"`,
				});
			}
		}
		for (const conf of data.assignment_confirmations || []) {
			if (conf.client_decision === "Pending") {
				items.push({
					urgent: true,
					badge: "SLA Sign-Off",
					title: `Confirm Assignment: ${conf.job_title}`,
					detail: `Confirmed delivery ${fmtDate(conf.confirmed_delivery_date)} · ${conf.service_level}`,
					buttonLabel: "Review Scope",
					attr: `data-open-job="${escapeHTML(conf.job)}"`,
				});
			}
		}
		for (const sc of data.scope_changes || []) {
			if (sc.status === "Pending Client Approval") {
				items.push({
					urgent: true,
					badge: "Scope Change",
					title: `Approve Scope Change: ${sc.job_title}`,
					detail: sc.reason || "Revised scope and pricing awaits your sign-off.",
					buttonLabel: "Review Change",
					attr: `data-open-job="${escapeHTML(sc.job)}"`,
				});
			}
		}
		for (const approval of data.approvals || []) {
			items.push({
				urgent: true,
				badge: "Deliverable Ready",
				title: approval.job_title,
				detail: `${approval.matter_title || "Matter"} · Review protected preview and approve final release.`,
				buttonLabel: "Open Studio",
				attr: `data-open-approval="${escapeHTML(approval.name)}"`,
			});
		}
		return items;
	}

	function actionCenterCard(items) {
		if (!items.length) return "";
		return `<section class="lex-action-center" aria-label="Client actions required">
			<div class="lex-action-center-head">
				<h3>${icon("clock")} Client Action Required <span class="lex-pill indicator-pill orange">${items.length} pending</span></h3>
				<small class="text-muted">Prioritized items awaiting your signature, clarification, or funding</small>
			</div>
			<div class="lex-action-grid">
				${items.slice(0, 6).map((item) => `<article class="lex-action-item ${item.urgent ? "is-urgent" : ""}">
					<div class="lex-action-item-copy">
						<div><span class="lex-owner-pill with-client">${escapeHTML(item.badge)}</span></div>
						<strong>${escapeHTML(item.title)}</strong>
						<span>${escapeHTML(item.detail)}</span>
					</div>
					<button type="button" class="lex-button btn btn-primary btn-sm" ${item.attr}>${escapeHTML(item.buttonLabel)}</button>
				</article>`).join("")}
			</div>
		</section>`;
	}

	function deadlinesCard(data) {
		const rows = data.deadlines || [];
		const body = rows.length
			? `<ul class="lex-deadline-list">${rows.slice(0, 6).map((row) => {
				const attr = row.job ? `data-open-job="${escapeHTML(row.job)}"` : row.matter ? `data-open-matter="${escapeHTML(row.matter)}"` : `data-go="new-matter"`;
				return `<li class="lex-deadline-row" ${attr} tabindex="0" role="button">
					<div style="min-width:0;">
						<strong style="display:block;font-size:13px;">${escapeHTML(row.title)}</strong>
						<small class="text-muted">${escapeHTML(row.kind)} · ${escapeHTML(row.subtitle || "")}</small>
					</div>
					<div style="display:flex;align-items:center;gap:6px;flex-shrink:0;">
						<span class="lex-pill indicator-pill ${indicatorColor(row.status)}">${escapeHTML(row.status)}</span>
						<span class="lex-deadline-date">${escapeHTML(fmtDate(row.date))}</span>
					</div>
				</li>`;
			}).join("")}</ul>`
			: empty("No upcoming legal deadlines scheduled.");
		return card("Deadlines & SLA Radar", "Confirmed dates, milestones and quote expirations", body);
	}

	function overviewSection(data, actionItems) {
		const progress = Math.round((data.onboarding.completed / data.onboarding.total) * 100);
		const quick = [
			data.permissions.can_create_matters ? ["new-matter", "Submit new work", "Start with details and SLA", "plus"] : null,
			data.permissions.can_create_matters ? ["work-requests", "Work status", "Monitor funded and activated jobs", "clipboard"] : null,
			["messages", "Secure messages", "Talk to the delivery team", "message"],
			["documents", "Documents", "Your uploads and completed deliverables", "file"],
		].filter(Boolean);
		const hasWallet = Boolean(data.wallet && !data.wallet.requires_legal_capacity_reconciliation);
		const walletCurrency = data.wallet?.capacity_currency || data.lexpack?.selected_currency || "CAD";
		const metricsHtml = [
			metric("Active intakes", data.metrics.active_intakes, data.metrics.info_holds ? `${data.metrics.info_holds} info hold` : "Before confirmation", "plus", data.permissions.can_create_matters ? "new-matter" : ""),
			metric("Open work", data.metrics.open_jobs, "Funded jobs in progress", "clipboard", data.permissions.can_create_matters ? "work-requests" : "matters"),
			metric("Pending approvals", data.metrics.approvals, "Your decisions required", "check", data.navigation.some((n) => n.section === "approvals") ? "approvals" : ""),
			metric("Documents", data.metrics.documents, "Protected files", "file", data.navigation.some((n) => n.section === "documents") ? "documents" : ""),
			hasWallet ? metric("Legal Capacity", capacityMoney(data.wallet.current_balance, walletCurrency), `${capacityMoney(data.wallet.reserved_balance, walletCurrency)} reserved`, "wallet", "wallet") : "",
		].filter(Boolean).join("");
		return `<section class="lex-section active" data-panel="overview">
			<div class="lex-welcome"><div><p class="lex-eyebrow">Secure organization workspace</p><h2>Welcome, ${escapeHTML(data.profile.full_name)}</h2><p>Everything shown here is limited to ${escapeHTML(data.client.customer_name)} and your assigned permissions.</p></div><div class="lex-progress"><div class="lex-progress-meta"><span>Workspace setup</span><strong>${data.onboarding.completed}/${data.onboarding.total}</strong></div><div class="lex-progress-track"><span style="width:${progress}%"></span></div><div class="lex-progress-steps">${data.onboarding.steps.map((step) => `<button type="button" data-go="${escapeHTML(step.section)}" class="${step.complete ? "done" : ""}">${step.complete ? "✓" : "○"} ${escapeHTML(step.label)}</button>`).join("")}</div></div></div>
			${actionCenterCard(actionItems)}
			<div class="lex-metrics ${hasWallet ? "has-five" : ""}">${metricsHtml}</div>
			<div class="lex-grid"><div class="lex-stack">${pilotCard(data)}${card("Recent matters", "Click any matter to inspect parties, jobs and files", matterTable(data.matters.slice(0, 6)))}${card("Current work", "Click any job for SLA clock and scope controls", jobTable(data.jobs.slice(0, 7), data.matters))}</div><div class="lex-stack">${deadlinesCard(data)}${card("Quick actions", "Common client tasks", `<div class="lex-card-body"><div class="lex-quick-actions">${quick.map(([section, title, note, iconName]) => `<button type="button" class="lex-action-tile" data-go="${section}">${icon(iconName)}<span><strong>${escapeHTML(title)}</strong><span>${escapeHTML(note)}</span></span></button>`).join("")}</div></div>`)}${walletCard(data)}${auditCard(data.audit_events)}</div></div>
		</section>`;
	}

	function pilotCard(data) {
		const pilot = data.pilot;
		if (!pilot) return "";
		const limit = pilot.value_limit ? `Applicable limit: ${escapeHTML(pilotMoney(pilot.value_limit, pilot.currency))}.` : "The applicable market limit will be shown when configured.";
		const status = pilot.status === "Used" ? "Pilot used by this organisation" : pilot.status === "Requested" ? "Pilot approval requested" : "One pilot per client organisation";
		return card("Complimentary Pilot Engagement", "Limited-Scope Assignment at No Cost", `<div class="lex-card-body"><p>Eligible new clients may begin with one limited-scope assignment, up to the applicable complimentary pilot value, at no charge.</p><p>${limit} Subject to Lexocrates approving the scope.</p><small>${escapeHTML(status)}</small></div>`);
	}

	/* ---------- Matters & Interactive Dossier Drawer ---------- */

	function matterTable(rows) {
		if (!rows.length) return empty("No authorized matters yet.");
		return `<div class="lex-table-wrap"><table class="lex-table table"><thead><tr><th>Matter</th><th>Practice area</th><th>Confidentiality</th><th>Status</th><th>Target</th><th></th></tr></thead><tbody>${rows.map((row) => `<tr class="lex-clickable-row" data-open-matter="${escapeHTML(row.name)}"><td><strong>${escapeHTML(row.matter_title)}</strong>${row.counterparty_name ? `<br><small class="text-muted">vs. ${escapeHTML(row.counterparty_name)}</small>` : ""}</td><td>${escapeHTML(row.practice_area || "—")}</td><td><span class="lex-pill indicator-pill ${indicatorColor(row.confidentiality_level)}">${escapeHTML(row.confidentiality_level || "Standard")}</span></td><td><span class="lex-pill indicator-pill ${indicatorColor(row.status)} ${statusClass(row.status)}">${escapeHTML(row.status)}</span></td><td class="lex-mono">${escapeHTML(fmtDate(row.end_date))}</td><td style="white-space:nowrap;">${row.can_client_delete ? `<button class="lex-button danger btn btn-danger btn-sm" type="button" data-delete-matter="${escapeHTML(row.name)}">Delete Matter</button>` : `<button class="lex-button secondary btn btn-default btn-sm" type="button" data-open-matter="${escapeHTML(row.name)}">Inspect</button>`}</td></tr>`).join("")}</tbody></table></div>`;
	}

	function matterCardsGrid(rows, jobs) {
		if (!rows.length) return empty("No authorized matters match the selected filters.");
		return `<div class="lex-matter-grid">${rows.map((row) => {
			const jobCount = (jobs || []).filter((j) => j.engagement === row.name).length;
			return `<article class="lex-matter-card">
				<div class="lex-matter-card-head">
					<div>
						<h3>${escapeHTML(row.matter_title)}</h3>
						<small class="text-muted">${escapeHTML(row.practice_area || "General")} · ${escapeHTML(row.matter_nature || "Advisory")}</small>
					</div>
					<span class="lex-pill indicator-pill ${indicatorColor(row.status)} ${statusClass(row.status)}">${escapeHTML(row.status)}</span>
				</div>
				<div class="lex-matter-parties">
					<span><small>${escapeHTML(row.our_side_role || "Represented Party")}</small><strong>${escapeHTML(row.represented_party_name || state.data.client.customer_name || "Client")}</strong></span>
					<span><small>${escapeHTML(row.counterparty_role || "Counterparty")}</small><strong>${escapeHTML(row.counterparty_name || "Not specified")}</strong></span>
				</div>
				<div class="lex-matter-card-foot">
					<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
						<span class="lex-pill indicator-pill ${indicatorColor(row.confidentiality_level)}">${escapeHTML(row.confidentiality_level || "Confidential")}</span>
						<span class="lex-pill indicator-pill blue">${jobCount} ${jobCount === 1 ? "Job" : "Jobs"}</span>
					</div>
					<div style="display:flex;gap:6px;">
						${row.can_client_delete ? `<button class="lex-button danger btn btn-danger btn-sm" type="button" data-delete-matter="${escapeHTML(row.name)}">Delete Matter</button>` : ""}
						<button class="lex-button secondary btn btn-default btn-sm" type="button" data-open-matter="${escapeHTML(row.name)}">Open Dossier</button>
					</div>
				</div>
			</article>`;
		}).join("")}</div>`;
	}

	function filteredMatters(data) {
		const q = state.matterFilter.query.trim().toLowerCase();
		return (data.matters || []).filter((row) => {
			if (state.matterFilter.status !== "all" && row.status !== state.matterFilter.status) return false;
			if (q && !`${row.matter_title} ${row.practice_area} ${row.counterparty_name} ${row.opposing_counsel} ${row.represented_party_name}`.toLowerCase().includes(q)) return false;
			return true;
		});
	}

	function mattersSection(data) {
		if (!data.navigation.some((row) => row.section === "matters")) return "";
		const rows = filteredMatters(data);
		const statuses = ["all", "Active", "Draft", "On Hold", "Completed"];
		const body = state.matterView === "cards" ? matterCardsGrid(rows, data.jobs) : card("Matter register", `${rows.length} of ${data.matters.length} authorized matters`, matterTable(rows));
		const actions = data.permissions.can_create_matters ? `<button type="button" class="lex-button btn btn-primary btn-sm" data-go="new-matter">+ New Matter / Job</button>` : "";
		return `<section class="lex-section" data-panel="matters">
			${sectionHeader("My Matters", "Legal matters, party matrices and linked assignments", actions)}
			<div class="lex-filter-bar">
				<div class="lex-filter-controls">
					<input type="search" class="lex-filter-input" data-matter-search placeholder="Filter matters, counterparties, counsel..." value="${escapeHTML(state.matterFilter.query)}">
					<div class="lex-chip-group">${statuses.map((s) => `<button type="button" class="lex-chip ${state.matterFilter.status === s ? "is-active" : ""}" data-matter-status="${escapeHTML(s)}">${s === "all" ? "All" : escapeHTML(s)}</button>`).join("")}</div>
				</div>
				<div class="lex-chip-group">
					<button type="button" class="lex-chip ${state.matterView === "cards" ? "is-active" : ""}" data-matter-view="cards">Cards</button>
					<button type="button" class="lex-chip ${state.matterView === "table" ? "is-active" : ""}" data-matter-view="table">Table</button>
				</div>
			</div>
			<div id="lex-matters-container">${body}</div>
		</section>`;
	}

	function openMatterDrawer(matterName) {
		const data = state.data;
		const matter = (data?.matters || []).find((m) => m.name === matterName);
		if (!matter) return;
		const linkedJobs = (data.jobs || []).filter((j) => j.engagement === matter.name);
		const linkedDocs = (data.documents || []).filter((d) => d.linked_matter_title === matter.matter_title);
		const partiesHtml = `<div class="lex-card"><div class="lex-card-head"><div><h3>Legal Matter Dossier</h3><small>${escapeHTML(matter.practice_area || "General")} · ${escapeHTML(matter.billing_method || "Quoted Price")}</small></div><span class="lex-pill indicator-pill ${indicatorColor(matter.confidentiality_level)}">${escapeHTML(matter.confidentiality_level || "Confidential")}</span></div>
			<div class="lex-card-body">
				<div class="lex-kv-grid">
					<div><small>Nature</small><strong>${escapeHTML(matter.matter_nature || "Advisory")}</strong></div>
					<div><small>Status</small><strong>${escapeHTML(matter.status)}</strong></div>
					<div><small>Target Date</small><strong class="lex-mono">${escapeHTML(fmtDate(matter.end_date))}</strong></div>
					<div><small>Represented Party</small><strong>${escapeHTML(matter.represented_party_name || data.client.customer_name)}</strong></div>
					<div><small>Our Role</small><strong>${escapeHTML(matter.our_side_role || "—")}</strong></div>
					<div><small>Counterparty</small><strong>${escapeHTML(matter.counterparty_name || "—")}</strong></div>
					<div><small>Counterparty Role</small><strong>${escapeHTML(matter.counterparty_role || "—")}</strong></div>
					<div style="grid-column:span 2;"><small>Opposing Counsel</small><strong>${escapeHTML(matter.opposing_counsel || "Not specified")}</strong></div>
				</div>
				<div class="lex-button-row" style="margin-top:8px;">
					${data.permissions.can_create_matters ? `<button type="button" class="lex-button btn btn-primary btn-sm" data-new-job-in-matter="${escapeHTML(matter.name)}">+ New Job in this Matter</button>` : ""}
					<button type="button" class="lex-button secondary btn btn-default btn-sm" data-open-matter-chat="${escapeHTML(matter.matter_title)}">Open Matter Messages</button>
					${matter.can_client_delete ? `<button type="button" class="lex-button danger btn btn-danger btn-sm" data-delete-matter="${escapeHTML(matter.name)}">Delete Matter</button>` : ""}
				</div>
			</div>
		</div>`;
		const jobsHtml = linkedJobs.length ? jobTable(linkedJobs, data.matters) : empty("No Jobs linked to this Matter yet.");
		const docsHtml = linkedDocs.length ? documentTable(linkedDocs) : empty("No documents available for this Matter yet.");
		openDrawer({
			title: matter.matter_title,
			subtitle: `${matter.practice_area || "Legal Matter"} · ${matter.status}`,
			tabs: [
				{ id: "overview", label: "Parties & Details", html: partiesHtml },
				{ id: "jobs", label: `Jobs (${linkedJobs.length})`, html: jobsHtml },
				{ id: "docs", label: `Documents (${linkedDocs.length})`, html: docsHtml },
			],
			onMount: (host) => {
				host.querySelectorAll("[data-open-job]").forEach((el) => el.addEventListener("click", () => openJobDrawer(el.dataset.openJob)));
				host.querySelectorAll("[data-preview-doc]").forEach((btn) => btn.addEventListener("click", () => openDocumentPreviewModal(btn.dataset.previewTitle, btn.dataset.previewMatter, btn.dataset.previewDoc)));
				host.querySelector("[data-new-job-in-matter]")?.addEventListener("click", () => {
					state.pendingMatterForIntake = matter.name;
					closeDrawer();
					window.location.hash = "new-matter";
					currentActivate("new-matter");
					applyPendingMatterToIntake();
				});
				host.querySelector("[data-open-matter-chat]")?.addEventListener("click", () => {
					closeDrawer();
					window.location.hash = "messages";
					currentActivate("messages");
					window.setTimeout(() => selectMatterChannelByTitle(matter.matter_title), 150);
				});
				host.querySelector("[data-delete-matter]")?.addEventListener("click", () => confirmDeleteMatter(matter.name));
			},
		});
	}

	/* ---------- Jobs & SLA Execution Drawer ---------- */

	function jobTable(rows, matters = []) {
		if (!rows.length) return empty("No current work requests.");
		return `<div class="lex-table-wrap"><table class="lex-table table"><thead><tr><th>Work item</th><th>Matter</th><th>Priority</th><th>Confirmed / Due</th><th>Status</th><th></th></tr></thead><tbody>${rows.map((row) => {
			const matter = row.matter_title || matters.find((item) => item.name === row.engagement)?.matter_title || "Matter";
			const status = row.client_deleted ? "Deleted by Client" : row.job_status;
			const due = row.confirmed_delivery_date || row.delivery_due_on || row.due_date;
			return `<tr class="lex-clickable-row" data-open-job="${escapeHTML(row.name)}"><td><strong>${escapeHTML(row.job_title)}</strong>${row.sla_paused ? ' <span class="lex-pill indicator-pill orange">SLA Paused</span>' : ""}</td><td>${escapeHTML(matter)}</td><td><span class="lex-pill indicator-pill ${indicatorColor(row.priority)} ${statusClass(row.priority)}">${escapeHTML(row.priority)}</span></td><td class="lex-mono">${escapeHTML(fmtDate(due))}</td><td><span class="lex-pill indicator-pill ${indicatorColor(row.job_status)} ${statusClass(row.job_status)}">${escapeHTML(status)}</span></td><td style="white-space:nowrap;">${row.delivery_download_url ? `<a class="lex-button secondary btn btn-default btn-sm" href="${escapeHTML(row.delivery_download_url)}" target="_blank" rel="noopener" data-stop-row>Download</a>` : `<button class="lex-button secondary btn btn-default btn-sm" type="button" data-open-job="${escapeHTML(row.name)}">Details</button>`}</td></tr>`;
		}).join("")}</tbody></table></div>`;
	}

	function openJobDrawer(jobName) {
		const data = state.data;
		const job = (data?.jobs || []).find((j) => j.name === jobName);
		if (!job) return;
		const confirmations = (data.assignment_confirmations || []).filter((c) => c.job === job.name);
		const scopeChanges = (data.scope_changes || []).filter((s) => s.job === job.name);
		const corrections = (data.correction_requests || []).filter((r) => r.job === job.name);
		const canRequestScope = data.permissions.can_create_matters && !["Draft", "Cancelled", "Completed"].includes(job.job_status);
		const canRequestCorrection = data.permissions.can_comment && ["Delivered", "Completed"].includes(job.job_status);
		const activeConf = confirmations.find((c) => c.client_decision === "Pending") || confirmations[0];

		const confBlock = activeConf ? `<div class="lex-confirmation-box">
			<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
				<strong>Assignment Confirmation v${fmtNumber(activeConf.confirmation_version)}</strong>
				<span class="lex-pill indicator-pill ${indicatorColor(activeConf.client_decision)}">${escapeHTML(activeConf.client_decision)}</span>
			</div>
			<div class="lex-kv-grid">
				<div><small>Confirmed Delivery</small><strong class="lex-mono">${escapeHTML(fmtDate(activeConf.confirmed_delivery_date))}</strong></div>
				<div><small>Service Level</small><strong>${escapeHTML(activeConf.service_level || "Standard")}</strong></div>
				<div><small>Fixed Quote</small><strong class="lex-mono">${activeConf.fixed_quote ? escapeHTML(fmtMoney(activeConf.fixed_quote, activeConf.currency || "CAD")) : "Covered"}</strong></div>
			</div>
			<div class="lex-scope-box"><strong>Confirmed Scope</strong><p>${escapeHTML(activeConf.scope_summary)}</p>${activeConf.assumptions ? `<small><strong>Assumptions:</strong> ${escapeHTML(activeConf.assumptions)}</small>` : ""}${activeConf.exclusions ? `<small><strong>Exclusions:</strong> ${escapeHTML(activeConf.exclusions)}</small>` : ""}</div>
			${activeConf.client_decision === "Pending" && activeConf.can_decide ? `<div class="lex-button-row"><button type="button" class="lex-button btn btn-primary btn-sm" data-approve-confirmation="${escapeHTML(activeConf.name)}">Approve Confirmation</button><button type="button" class="lex-button secondary btn btn-default btn-sm" data-change-confirmation="${escapeHTML(activeConf.name)}">Request Scope/Date Change</button></div>` : ""}
		</div>` : "";

		const overviewHtml = `<div class="lex-card"><div class="lex-card-head"><div><h3>${escapeHTML(job.job_title)}</h3><small>${escapeHTML(job.matter_title || "Matter")} · ${escapeHTML(job.job_type || "Legal Service")}</small></div><span class="lex-pill indicator-pill ${indicatorColor(job.job_status)}">${escapeHTML(job.job_status)}</span></div>
			<div class="lex-card-body">
				<div class="lex-kv-grid">
					<div><small>Priority</small><strong>${escapeHTML(job.priority)}</strong></div>
					<div><small>Service Level</small><strong>${escapeHTML(job.service_level || "Standard")}</strong></div>
					<div><small>SLA Status</small><strong>${job.sla_paused ? `Paused (${fmtNumber(job.total_paused_minutes)} mins)` : job.sla_started_on ? "Running" : "Pending Start"}</strong></div>
					<div><small>SLA Started</small><strong class="lex-mono">${escapeHTML(fmtDate(job.sla_started_on))}</strong></div>
					<div><small>Confirmed / Due Date</small><strong class="lex-mono">${escapeHTML(fmtDate(job.confirmed_delivery_date || job.delivery_due_on || job.due_date))}</strong></div>
					<div><small>Funding</small><strong>${escapeHTML(job.funding_status || "Pending")}</strong></div>
				</div>
				${job.task_description ? `<div class="lex-scope-box"><strong>Assignment Brief</strong><p>${escapeHTML(job.task_description)}</p></div>` : ""}
				${confBlock}
				<div class="lex-button-row">
					${job.delivery_download_url ? `<a class="lex-button btn btn-primary btn-sm" href="${escapeHTML(job.delivery_download_url)}" target="_blank" rel="noopener">Download Final Deliverable</a>` : ""}
					${job.delivery_preview_url ? `<button type="button" class="lex-button btn btn-primary btn-sm" data-jump-approval="${escapeHTML(job.name)}">Open Approval Studio</button>` : ""}
					${canRequestScope ? `<button type="button" class="lex-button secondary btn btn-default btn-sm" data-request-scope-change="${escapeHTML(job.name)}">Request Scope Change</button>` : ""}
					${canRequestCorrection ? `<button type="button" class="lex-button secondary btn btn-default btn-sm" data-request-correction="${escapeHTML(job.name)}">Request Correction</button>` : ""}
				</div>
			</div>
		</div>`;

		const scopeHtml = scopeChanges.length
			? scopeChanges.map((sc) => `<article class="lex-card"><div class="lex-card-head"><div><h3>Scope Change</h3><small class="lex-mono">${escapeHTML(fmtDate(sc.requested_on))}</small></div><span class="lex-pill indicator-pill ${indicatorColor(sc.status)}">${escapeHTML(sc.status)}</span></div><div class="lex-card-body"><p><strong>Requested:</strong> ${escapeHTML(sc.requested_change)}</p><p><strong>Reason:</strong> ${escapeHTML(sc.reason)}</p><div class="lex-kv-grid"><div><small>Additional Price</small><strong class="lex-mono">${escapeHTML(fmtMoney(sc.additional_price, sc.currency || "CAD"))}</strong></div><div><small>Revised Delivery</small><strong class="lex-mono">${escapeHTML(fmtDate(sc.revised_delivery_date))}</strong></div></div>${sc.status === "Pending Client Approval" && sc.can_approve ? `<div class="lex-button-row"><button type="button" class="lex-button btn btn-primary btn-sm" data-approve-scope-change="${escapeHTML(sc.name)}">Approve Scope Change</button></div>` : ""}</div></article>`).join("")
			: empty("No scope changes recorded for this assignment.");

		const correctionHtml = corrections.length
			? corrections.map((cr) => `<article class="lex-card"><div class="lex-card-head"><div><h3>Correction Request</h3><small class="lex-mono">${escapeHTML(fmtDate(cr.correction_request_date))}</small></div><span class="lex-pill indicator-pill ${indicatorColor(cr.status)}">${escapeHTML(cr.status)}</span></div><div class="lex-card-body"><p>${escapeHTML(cr.issue_description)}</p>${cr.resolution_notes ? `<div class="lex-scope-box"><strong>Resolution Notes</strong><p>${escapeHTML(cr.resolution_notes)}</p></div>` : ""}</div></article>`).join("")
			: empty("No post-delivery correction requests submitted.");

		openDrawer({
			title: job.job_title,
			subtitle: `${job.matter_title || "Matter"} · ${job.job_status}`,
			tabs: [
				{ id: "overview", label: "SLA & Scope", html: overviewHtml },
				{ id: "scope", label: `Scope Changes (${scopeChanges.length})`, html: scopeHtml },
				{ id: "corrections", label: `Corrections (${corrections.length})`, html: correctionHtml },
			],
			onMount: (host) => {
				host.querySelector("[data-approve-confirmation]")?.addEventListener("click", async (e) => {
					const btn = e.currentTarget;
					setBusy(btn, "Approving...");
					try {
						await call("lex.lex.doctype.lpo_assignment_confirmation.lpo_assignment_confirmation.approve", { name: btn.dataset.approveConfirmation });
						notify("Assignment Confirmation approved.");
						closeDrawer();
						reloadSection(state.activeSection);
					} catch (error) { showError("Confirmation approval failed", error); clearBusy(btn); }
				});
				host.querySelector("[data-change-confirmation]")?.addEventListener("click", (e) => {
					const confName = e.currentTarget.dataset.changeConfirmation;
					openModal({
						title: "Request Assignment Confirmation Change",
						subtitle: job.job_title,
						bodyHtml: `<label class="wide" style="display:flex;flex-direction:column;gap:6px;font-size:13px;font-weight:600;">Requested scope or delivery date change<textarea id="lex-conf-change-notes" class="form-control" rows="4" required placeholder="Explain the scope or delivery revision requested."></textarea></label>`,
						confirmText: "Submit Change Request",
						onConfirm: async (modalHost) => {
							const notes = modalHost.querySelector("#lex-conf-change-notes").value.trim();
							if (!notes) throw new Error("Enter the requested change details.");
							await call("lex.lex.doctype.lpo_assignment_confirmation.lpo_assignment_confirmation.request_change", { name: confName, notes });
							notify("Change request sent to Legal Operations.");
							closeDrawer();
							reloadSection(state.activeSection);
						},
					});
				});
				host.querySelector("[data-approve-scope-change]")?.addEventListener("click", async (e) => {
					const btn = e.currentTarget;
					setBusy(btn, "Approving...");
					try {
						await call("lex.lex.doctype.lpo_assignment_scope_change.lpo_assignment_scope_change.approve_client", { name: btn.dataset.approveScopeChange });
						notify("Scope change approved.");
						closeDrawer();
						reloadSection(state.activeSection);
					} catch (error) { showError("Scope change approval failed", error); clearBusy(btn); }
				});
				host.querySelector("[data-request-scope-change]")?.addEventListener("click", () => {
					openModal({
						title: "Request Assignment Scope Change",
						subtitle: job.job_title,
						bodyHtml: `<div class="lex-form">
							<label class="wide">Original scope reference<textarea id="lex-sc-orig" rows="2" required>${escapeHTML(activeConf?.scope_summary || job.task_description || job.job_title)}</textarea></label>
							<label class="wide">Requested scope change<textarea id="lex-sc-req" rows="3" required placeholder="Describe additions or modifications to deliverables/scope."></textarea></label>
							<label class="wide">Business / legal reason<textarea id="lex-sc-reason" rows="2" required placeholder="Why is this scope change required?"></textarea></label>
							<label class="wide">Requested revised delivery date (optional)<input id="lex-sc-date" type="datetime-local"></label>
						</div>`,
						confirmText: "Submit Scope Change",
						onConfirm: async (modalHost) => {
							const original_scope = modalHost.querySelector("#lex-sc-orig").value.trim();
							const requested_change = modalHost.querySelector("#lex-sc-req").value.trim();
							const reason = modalHost.querySelector("#lex-sc-reason").value.trim();
							const revised_delivery_date = modalHost.querySelector("#lex-sc-date").value || null;
							if (!original_scope || !requested_change || !reason) throw new Error("Complete all required scope change fields.");
							await call("lex.lex.doctype.lpo_assignment_scope_change.lpo_assignment_scope_change.request_scope_change", {
								job: job.name, original_scope, requested_change, reason, revised_delivery_date,
							});
							notify("Scope change request submitted to Legal Operations.");
							closeDrawer();
							reloadSection(state.activeSection);
						},
					});
				});
				host.querySelector("[data-request-correction]")?.addEventListener("click", () => {
					openModal({
						title: "Submit Post-Delivery Correction Request",
						subtitle: `${job.job_title} (5-business-day correction window)`,
						bodyHtml: `<div class="lex-form">
							<label class="wide">Describe the issue or error<textarea id="lex-corr-issue" rows="4" required placeholder="Specify the exact section, citation, or deliverable discrepancy."></textarea></label>
							<div class="wide lex-check-grid">
								<label class="lex-check"><input type="checkbox" id="lex-corr-within" checked> Within original agreed scope</label>
								<label class="lex-check"><input type="checkbox" id="lex-corr-facts"> Involves new facts</label>
								<label class="lex-check"><input type="checkbox" id="lex-corr-docs"> Involves new documents</label>
								<label class="lex-check"><input type="checkbox" id="lex-corr-instr"> Changed instructions</label>
							</div>
						</div>`,
						confirmText: "Submit Correction Request",
						onConfirm: async (modalHost) => {
							const issue_description = modalHost.querySelector("#lex-corr-issue").value.trim();
							if (!issue_description) throw new Error("Describe the issue requiring correction.");
							await call("lex.lex.doctype.lpo_correction_request.lpo_correction_request.create_correction_request", {
								job: job.name,
								issue_description,
								within_original_scope: modalHost.querySelector("#lex-corr-within").checked ? 1 : 0,
								new_facts: modalHost.querySelector("#lex-corr-facts").checked ? 1 : 0,
								new_documents: modalHost.querySelector("#lex-corr-docs").checked ? 1 : 0,
								changed_instructions: modalHost.querySelector("#lex-corr-instr").checked ? 1 : 0,
							});
							notify("Correction request submitted.");
							closeDrawer();
							reloadSection(state.activeSection);
						},
					});
				});
				host.querySelector("[data-jump-approval]")?.addEventListener("click", (e) => {
					state.selectedApprovalJob = e.currentTarget.dataset.jumpApproval;
					closeDrawer();
					window.location.hash = "approvals";
					currentActivate("approvals");
				});
			},
		});
	}

	/* ---------- Master SLA & Work Intake ---------- */

	const MASTER_SLA_ACKS = [
		["ack_read_and_understood", "it has read and understood the SLA"],
		["ack_business_week", "it understands that Lexocrates operates a Monday-to-Friday Business Week"],
		["ack_no_24x7_production", "it understands that the Client Portal may accept submissions outside Business Days but that this does not constitute 24/7 production service"],
		["ack_submission_not_sla_start", "it understands that submission of an Assignment does not itself commence the delivery period"],
		["ack_lextimator_indicative", "it understands that Lextimator™ may provide an Indicative Turnaround which is subject to scope and capacity review"],
		["ack_fixed_quote_protection", "it understands that a Fixed Quote will not be increased merely because Lexocrates underestimated the internal time or resources required for the unchanged agreed scope"],
		["ack_scope_changes_affect_price", "it understands that material Client-initiated changes to scope may result in a revised price and delivery date"],
		["ack_confirmed_delivery_date_controls", "it understands that the Confirmed Delivery Date contained in the approved Assignment Confirmation is the applicable delivery commitment"],
		["ack_priority_subject_to_availability", "it understands that Priority Service is subject to operational availability"],
		["ack_no_automatic_express_service", "it understands that Lexocrates does not presently provide a general entitlement to Express, same-day, weekend or emergency delivery"],
		["ack_signatory_authority", "the individual accepting this SLA is authorized to accept it on behalf of the Client"],
	];

	function masterSlaGate(data) {
		const sla = data.master_sla || {};
		if (sla.status === "Error") {
			return `<article class="lex-card widget border"><div class="lex-card-body"><strong>Your Master Service Level Agreement status could not be loaded.</strong><p>Reload the page, or contact support if this continues — you cannot submit new work until this is resolved.</p></div></article>`;
		}
		const checks = MASTER_SLA_ACKS.map(([name, label]) => (
			`<label class="lex-check wide"><input type="checkbox" name="${name}" value="1" required> ${escapeHTML(label)}</label>`
		)).join("");
		return `<article class="lex-card widget border">
			<div class="lex-card-head widget-head"><div class="widget-label"><h3 class="widget-title">Master Service Level Agreement</h3><small>Accept once during onboarding — required before submitting new work</small></div></div>
			<div class="lex-card-body">
				<div class="lex-scope-box">${sla.terms_html || ""}</div>
				<p>By accepting this SLA, the Client confirms that:</p>
				<form id="lex-master-sla-accept" class="lex-form" data-master-sla="${escapeHTML(sla.name || "")}">
					<div class="wide">${checks}</div>
					<label class="wide">Organization<input type="text" value="${escapeHTML(sla.client_legal_name || "")}" disabled></label>
					<label>Authorized Representative<input type="text" name="accepted_by_name" required maxlength="140" placeholder="Full name"></label>
					<label>Designation<input type="text" name="accepted_by_designation" required maxlength="140" placeholder="e.g. General Counsel"></label>
					<label class="wide">Email<input type="text" value="${escapeHTML(sla.prefill_email || "")}" disabled></label>
					<div class="wide"><button class="lex-button btn btn-primary btn-md" type="submit">Accept SLA &amp; Continue</button></div>
				</form>
			</div>
		</article>`;
	}

	function workIntakeSection(data) {
		if (!data.permissions.can_create_matters) return "";
		const filteredIntakes = (data.intakes || []).filter((intake) => {
			if (state.intakeFilter === "action") return ["SLA Pending", "Documents Pending", "Pending Client Information", "Quote Ready", "Funding Pending"].includes(intake.status);
			if (state.intakeFilter === "review") return ["Security Review", "Analysis Pending", "Operations Review", "Pending CEO Approval"].includes(intake.status);
			if (state.intakeFilter === "active") return ["Funded", "Matter Confirmed"].includes(intake.status);
			return true;
		});
		const intakeListHtml = (data.intakes || []).length
			? `<div style="margin-top: 22px; display:flex; flex-direction:column; gap:12px;">
				<div class="lex-filter-bar">
					<strong>Your Jobs (${filteredIntakes.length})</strong>
					<div class="lex-chip-group">
						${[["all", "All"], ["action", "Action Required"], ["review", "Under Review"], ["active", "Activated"]].map(([key, label]) => `<button type="button" class="lex-chip ${state.intakeFilter === key ? "is-active" : ""}" data-intake-filter="${key}">${label}</button>`).join("")}
					</div>
				</div>
				${filteredIntakes.length ? filteredIntakes.map((intake) => intakeCard(intake, data)).join("") : empty("No jobs match this filter.")}
			</div>`
			: "";
		if (data.master_sla && data.master_sla.status !== "Accepted") {
			return `<section class="lex-section" data-panel="new-matter">${masterSlaGate(data)}${intakeListHtml}</section>`;
		}
		const standardServices = [
			{ value: "Legal Research", label: "Legal Research & Writing" },
			{ value: "Litigation Support", label: "Litigation Support" },
			{ value: "Contract Review", label: "Contract Lifecycle Management (CLM)" },
			{ value: "Contract Review", label: "Contract Review" },
			{ value: "Document Review", label: "eDiscovery & Document Review" },
			{ value: "Compliance Review", label: "Compliance & Regulatory Support" },
			{ value: "Drafting", label: "Paralegal & Virtual Legal Assistance" },
			{ value: "Other", label: "Legal Operations Support" }
		];
		const serviceDescriptions = {
			"Legal Research & Writing": "Case law, statutory memoranda & opinion letters (SOP-001)",
			"Litigation Support": "Pleadings, docketing & procedural chronology (SOP-002)",
			"Contract Lifecycle Management (CLM)": "Playbook redlining, renewals & key obligations (SOP-003)",
			"Contract Review": "Single-agreement risk review & fallback drafting (SOP-003)",
			"eDiscovery & Document Review": "Protocol coding, privilege logs & Bates review (SOP-004)",
			"Compliance & Regulatory Support": "Jurisdiction mapping & policy gap assessment (SOP-005)",
			"Paralegal & Virtual Legal Assistance": "Routine, client-facing or filing support tasks (SOP-006)",
			"Legal Operations Support": "Custom legal ops, workflows & matter administration",
		};
		const matterOptions = (data.matters || []).map((matter) => (
			`<option value="${escapeHTML(matter.name)}">${escapeHTML(matter.matter_title || "Matter")}</option>`
		)).join("");
		const standardIntake = formCard("Create a Job", "Answer the essentials first. Draft progress saves automatically in this session.", "lex-new-intake", `
			<div class="wide lex-wizard-stepper" aria-label="Work intake steps">
				<button class="lex-wizard-step is-active" type="button" data-intake-step="1"><span class="lex-step-badge">1</span>Choose a Matter</button>
				<span class="lex-wizard-step-line" aria-hidden="true"></span>
				<button class="lex-wizard-step" type="button" data-intake-step="2"><span class="lex-step-badge">2</span>Describe the Job</button>
			</div>
			<section class="wide lex-wizard-page is-active" data-intake-page="1">
				<div class="wide lex-wizard-page-head"><h4>Where should this Job be filed?</h4><p>Choose an existing Matter, or create a new one with a title.</p></div>
				<label class="wide">Matter<select name="matter_mode" data-matter-mode required><option value="new">Create a new Matter</option>${matterOptions ? '<option value="existing">Use an existing Matter</option>' : ""}</select></label>
				<div class="wide lex-linked-matter-card" data-existing-matter hidden>
					<label class="wide" style="width:100%;">Select existing Matter<select name="matter" data-existing-matter-select><option value="">Select a Matter</option>${matterOptions}</select></label>
				</div>
				<div class="wide lex-wizard-page" data-new-matter-fields>
					<label class="wide">Matter title<input name="matter_title" maxlength="140" placeholder="e.g. Northstar v. Redline"></label>
					<section class="wide lex-intake-details lex-wizard-page"><div class="wide lex-wizard-page-head"><h4>Parties and dispute details</h4></div><label>Matter nature<select name="matter_nature"><option value="Advisory">Advisory</option><option value="Contract / Transaction">Contract / Transaction</option><option value="Litigation / Dispute">Litigation / Dispute</option><option value="Regulatory / Compliance">Regulatory / Compliance</option><option value="Due Diligence">Due Diligence</option><option value="Other">Other</option></select></label><label>Represented party<input name="represented_party_name" maxlength="140" placeholder="Client or represented party"></label><label>Our role<input name="our_side_role" maxlength="100" placeholder="e.g. Advisor or Claimant"></label><label>Counterparty<input name="counterparty_name" maxlength="140" placeholder="Counterparty name"></label><label>Counterparty role<input name="counterparty_role" maxlength="100" placeholder="e.g. Vendor or Defendant"></label><label class="wide">Opposing counsel<input name="opposing_counsel" maxlength="140" placeholder="Name or firm, if known"></label></section>
				</div>
				<div class="wide lex-button-row"><button class="lex-button btn btn-primary btn-md" type="button" data-next-intake-step>Continue</button></div>
			</section>
			<section class="wide lex-wizard-page" data-intake-page="2" hidden>
				<div class="wide lex-wizard-page-head"><h4>What would you like us to do?</h4><p>These details create your Draft Job. Uploading its PDF is the next step.</p></div>
				<label class="wide">Job title<input name="intake_title" required maxlength="140" placeholder="e.g. Review vendor agreement"></label>
				<div class="wide">
					<span style="display:block;font-size:12.5px;font-weight:600;color:var(--lex-ink-muted);margin-bottom:6px;">Select Legal Service</span>
					<div class="lex-service-grid">
						${standardServices.map((item, idx) => `<button type="button" class="lex-service-card ${idx === 0 ? "is-selected" : ""}" data-service-choice="${escapeHTML(item.value)}" data-service-label="${escapeHTML(item.label)}"><strong>${escapeHTML(item.label)}</strong><small>${escapeHTML(serviceDescriptions[item.label] || "")}</small></button>`).join("")}
					</div>
				</div>
				<label class="wide" style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;">Service<select name="service_type" data-service-type required>${standardServices.map((item) => `<option value="${escapeHTML(item.value)}">${escapeHTML(item.label)}</option>`).join("")}</select></label>
				<section class="wide lex-intake-details lex-wizard-page" data-legal-research-fields hidden>
					<div class="wide lex-wizard-page-head"><h4>Legal research instructions</h4><p>These fields are required so the legal team can define the question, research the correct law and protect your confidentiality.</p></div>
					<label class="wide">Legal question(s)<textarea name="legal_questions" data-legal-research-required placeholder="State each legal question in writing."></textarea></label>
					<label class="wide">Relevant factual background<textarea name="factual_background" data-legal-research-required placeholder="Provide the facts, assumptions and any unknown facts relevant to the question."></textarea></label>
					<label>Deliverable format<select name="deliverable_format" data-legal-research-required><option value="Formal Legal Memorandum">Formal legal memorandum</option><option value="Opinion Letter">Opinion letter</option><option value="Short Research Note">Short research note</option><option value="Substantive Email Response">Substantive email response</option></select></label>
					<label>Citation style<input name="citation_style" data-legal-research-required value="McGill Guide" maxlength="140"></label>
					<label>Instructing individual<input name="instructing_contact_name" data-legal-research-required maxlength="140" placeholder="Full name"></label>
					<label>Role / designation<input name="instructing_contact_role" data-legal-research-required maxlength="140" placeholder="e.g. General Counsel"></label>
					<label>Email<input name="instructing_contact_email" data-legal-research-required type="email" maxlength="140" placeholder="name@example.com"></label>
					<label>Data handling / residency restrictions<input name="data_handling_restrictions" maxlength="250" required data-legal-research-required placeholder="e.g. Canada only - enter 'No additional restrictions' if none"></label>
					<label class="wide lex-check"><input name="no_ai_tools" type="checkbox" value="1"> This assignment must not use AI-assisted research tools.</label>
				</section>
				<section class="wide lex-intake-details lex-wizard-page" data-service-sop-fields hidden><div class="wide lex-wizard-page-head"><h4 data-service-sop-title>Service instructions</h4><p>These required details let the legal team apply the correct service SOP.</p></div><div class="wide" data-service-sop-field-container></div></section>
				<label class="wide">Instructions<textarea name="preliminary_details" required minlength="20" placeholder="Tell us what you need, relevant background and any key deadline."></textarea></label>
				<section class="wide lex-intake-details lex-wizard-page"><div class="wide lex-wizard-page-head"><h4>Delivery preferences</h4></div><label>Priority<select name="priority" required><option value="Medium">Standard</option><option value="High">High</option><option value="Urgent">Urgent</option><option value="Low">Low</option></select></label><label>Jurisdiction<input name="jurisdiction" required maxlength="100" value="Canada"></label><label>Delivery deadline<input name="requested_delivery_date" type="datetime-local" required></label><label>Confidentiality<select name="confidentiality_level"><option value="Confidential">Confidential</option><option value="Highly Confidential">Highly Confidential</option><option value="Standard">Standard</option></select></label><label class="wide">Expected outcome<textarea name="expected_outcome" placeholder="Describe the result or deliverable you need."></textarea></label></section>
				<div class="wide lex-next-step"><strong>Next:</strong> review the service terms, upload the Job PDF, then receive the fixed price.</div>
				<div class="wide lex-button-row"><button class="lex-button secondary btn btn-default btn-md" type="button" data-previous-intake-step>Back</button><button class="lex-button secondary btn btn-default btn-md" type="button" data-clear-intake-draft>Reset Draft</button><button class="lex-button btn btn-primary btn-md" type="submit">Create Draft Job</button></div>
			</section>
		`);
		return `<section class="lex-section" data-panel="new-matter">${standardIntake}${intakeListHtml}</section>`;
	}

	function additionalJobDocuments(intake, docs) {
		return `<details class="lex-intake-action"><summary>Add or update Draft Job documents</summary><p class="text-muted">Any pre-funding change supersedes the previous estimate and creates a new version automatically.</p><form class="lex-form lex-intake-instructions" data-intake-instructions="${escapeHTML(intake.name)}"><label class="wide">Detailed instructions<textarea name="detailed_instructions" required>${escapeHTML(intake.detailed_instructions || "")}</textarea></label><div class="wide"><button class="lex-button secondary btn btn-default btn-sm" type="submit">Save and re-estimate</button></div></form><form class="lex-form lex-intake-upload" data-intake-upload="${escapeHTML(intake.name)}"><div class="wide lex-dropzone" data-pdf-dropzone>${icon("upload")}<strong>Drop your PDF here or click to browse</strong><span class="lex-dropzone-meta" data-dropzone-label>PDF only · Max 10 MB · Malware-scanned on upload</span><input class="lex-file-input" name="file" type="file" accept=".pdf,application/pdf" required></div><div class="wide lex-upload-bar" data-upload-bar hidden><span style="width:0%"></span></div><div class="wide"><button class="lex-button btn btn-primary btn-sm" type="submit">Upload, scan and estimate</button></div></form>${docs ? `<ul class="lex-intake-files">${docs}</ul>` : empty("No Job documents uploaded yet.")}</details>`;
	}

	function clientDeleteAction(intake) {
		if (intake.client_deleted || !intake.can_client_delete) return "";
		return `<div class="lex-intake-action"><button class="lex-button danger btn btn-danger btn-sm" type="button" data-delete-intake="${escapeHTML(intake.name)}">Delete Job</button></div>`;
	}

	function infoHoldActionBox(intake) {
		const critical = Boolean(intake.information_is_critical);
		const submitted = Boolean(intake.information_received_on);
		return `<div class="lex-intake-action"><div class="lex-info-hold-box ${critical ? "is-critical" : ""}">
			<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
				<h4>${critical ? "Critical Information Requested — SLA Paused" : "Information Requested — SLA Paused"}</h4>
				<span class="lex-mono" style="font-size:11.5px;">Requested ${escapeHTML(fmtDate(intake.information_requested_on))}</span>
			</div>
			<p>${escapeHTML(intake.missing_information || "Legal Operations requires additional clarification before proceeding.")}</p>
			${submitted ? `<div class="lex-scope-box"><strong>Clarification Submitted (${escapeHTML(fmtDate(intake.information_received_on))})</strong><p>${escapeHTML(intake.information_resolution_note || "")}</p><small>Pending verification by Legal Operations to resume SLA clock.</small></div>` : ""}
			<form class="lex-form" data-sop-info-form="${escapeHTML(intake.name)}">
				<label class="wide">${submitted ? "Update clarification" : "Provide requested information"}<textarea name="response_note" required rows="3" placeholder="Enter facts, file numbers, instructions, or answers requested above.">${submitted ? escapeHTML(intake.information_resolution_note || "") : ""}</textarea></label>
				<div class="wide"><button type="submit" class="lex-button btn btn-primary btn-sm">${submitted ? "Update Response" : "Submit Clarification"}</button></div>
			</form>
		</div></div>`;
	}

	function intakeProgressCard(intake, data) {
		const docs = (intake.documents || []).map((row) => `<li><span><strong>${row.download_url ? `<a href="${escapeHTML(row.download_url)}" target="_blank" rel="noopener">${escapeHTML(row.file_name)}</a>` : escapeHTML(row.file_name)}</strong><small>${formatBytes(row.file_size)}</small></span><span class="indicator-pill ${indicatorColor(row.custom_lex_scan_status)} ${statusClass(row.custom_lex_scan_status)}">${escapeHTML(row.custom_lex_scan_status || "Pending")}</span></li>`).join("");
		let action = "";
		if (intake.client_deleted) {
			action = clientDeleteAction(intake);
		} else if (intake.status === "Pending Client Information") {
			action = infoHoldActionBox(intake);
		} else if (intake.status === "SLA Pending") {
			action = `<div class="lex-intake-action"><h4>Review service terms</h4>${intake.sla_document_snapshot ? `<a class="lex-button secondary btn btn-default btn-sm" href="${escapeHTML(intake.sla_download_url || intake.sla_document_snapshot)}" target="_blank" rel="noopener">Download service terms</a>` : ""}<div class="lex-sla-document">${escapeHTML(intake.sla_terms_snapshot).replace(/\n/g, "<br>")}</div><label class="lex-check"><input type="checkbox" data-sla-check="${escapeHTML(intake.name)}"> I have reviewed and accept these service terms.</label><button class="lex-button btn btn-primary btn-sm" type="button" data-accept-sla="${escapeHTML(intake.name)}">Accept and upload PDF</button></div>`;
		} else if (["Documents Pending", "Security Review", "Analysis Pending"].includes(intake.status)) {
			action = `<div class="lex-intake-action"><h4>Upload the Job PDF</h4><p class="text-muted">Once the security scan is clean, Lextimator calculates the fixed price automatically.</p></div>${additionalJobDocuments(intake, docs)}`;
		} else if (intake.status === "Operations Review") {
			action = `<div class="lex-intake-action lex-review-state"><h4>Preparing your fixed price</h4><p>We are validating the scope, price and delivery before payment opens.</p></div>${additionalJobDocuments(intake, docs)}`;
		} else if (intake.status === "Pending CEO Approval") {
			action = `<div class="lex-intake-action lex-review-state"><h4>Finalising your price</h4><div class="lex-quote-summary"><span><small>Estimated price</small><strong>${escapeHTML(fmtMoney(intake.quoted_amount, intake.currency || "CAD"))}</strong></span><span><small>Delivery deadline</small><strong>${escapeHTML(fmtDate(intake.requested_delivery_date))}</strong></span></div><p>Your fixed price is being confirmed. We will notify you when payment is available.</p></div>`;
		} else if (["Quote Ready", "Funding Pending"].includes(intake.status)) {
			action = fundingOptions(intake, data) + (intake.status === "Quote Ready" ? additionalJobDocuments(intake, docs) : "");
		} else if (["Funded", "Matter Confirmed"].includes(intake.status)) {
			const pilot = intake.funding_route === "Complimentary Pilot";
			action = `<div class="lex-intake-action lex-funded-state"><h4>${pilot ? "Complimentary pilot approved and activated" : "Work funded and activated"}</h4><div class="lex-confirm-grid"><span><small>${pilot ? "Engagement" : "Funding"}</small><strong>${escapeHTML(intake.funding_route)}</strong></span><span><small>Matter</small><strong>${escapeHTML(intake.matter_title || "Confirming...")}</strong></span><span><small>Job</small><strong>${escapeHTML(intake.job_title || "Activating...")}</strong></span><span><small>SLA started</small><strong>${escapeHTML(fmtDate(intake.sla_started_on))}</strong></span><span><small>Delivery due</small><strong>${escapeHTML(fmtDate(intake.delivery_due_on))}</strong></span></div></div>`;
		}
		if (intake.status === "Pending CEO Approval") action += additionalJobDocuments(intake, docs);
		if (!intake.client_deleted) action += clientDeleteAction(intake);
		const status = intake.client_deleted ? "Deleted by Client" : intake.status;
		const withClient = ["SLA Pending", "Documents Pending", "Pending Client Information", "Quote Ready", "Funding Pending"].includes(intake.status);
		const payStep = intake.funding_route === "Complimentary Pilot"
			? `<span class="${intake.funding_status === "Funded" ? "done" : ""}">Pilot</span>`
			: `<span class="${intake.funding_status === "Funded" ? "done" : ""}">Payment</span>`;
		return `<article class="lex-card lex-intake-card"><div class="lex-card-head widget-head"><div><h3>${escapeHTML(intake.intake_title)}</h3><small>${escapeHTML(intake.matter_title || "Matter pending")} · ${escapeHTML(intake.job_title || "Draft Job pending")}</small></div><div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;"><span class="lex-owner-pill ${withClient ? "with-client" : "with-ops"}">${withClient ? "With You" : "With Legal Team"}</span><span class="indicator-pill ${indicatorColor(intake.status)} ${statusClass(intake.status)}">${escapeHTML(status)}</span></div></div><div class="lex-intake-steps"><span class="${intake.job ? "done" : ""}">Job</span><span class="${intake.sla_accepted ? "done" : ""}">Terms</span><span class="${intake.document_count ? "done" : ""}">PDF</span><span class="${["Under Review", "Ready"].includes(intake.cost_estimate_status) || ["Ready", "Accepted"].includes(intake.quote_status) ? "done" : ""}">Price</span>${payStep}</div>${action}</article>`;
	}

	function intakeCard(intake, data) {
		if (!["Operations Review", "Pending CEO Approval", "Quote Ready", "Funding Pending"].includes(intake.status)) {
			return intakeProgressCard(intake, data);
		}
		const review = ["Operations Review", "Pending CEO Approval"].includes(intake.status);
		const docs = (intake.documents || []).map((row) => `<li><span><strong>${escapeHTML(row.file_name)}</strong></span><span class="indicator-pill ${indicatorColor(row.custom_lex_scan_status)}">${escapeHTML(row.custom_lex_scan_status || "Pending")}</span></li>`).join("");
		const action = review
			? `<div class="lex-intake-action lex-review-state"><h4>Human validation where required</h4><div class="lex-quote-summary"><span><small>Estimated cost</small><strong>${escapeHTML(fmtMoney(intake.quoted_amount, intake.currency))}</strong></span><span><small>Delivery deadline</small><strong>${escapeHTML(fmtDate(intake.requested_delivery_date))}</strong></span></div><p>Lextimator<sup class="lex-tm">TM</sup> has prepared the estimate. Legal Operations will confirm the scope and fixed price before payment opens.</p></div>${additionalJobDocuments(intake, docs)}`
			: fundingOptions(intake, data) + (intake.status === "Quote Ready" ? additionalJobDocuments(intake, docs) : "");
		const withClient = ["Quote Ready", "Funding Pending"].includes(intake.status);
		return `<article class="lex-card lex-intake-card"><div class="lex-card-head widget-head"><div><h3>${escapeHTML(intake.intake_title)}</h3><small>${escapeHTML(intake.matter_title || "Matter pending")} · ${escapeHTML(intake.job_title || "Draft Job pending")}</small></div><div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;"><span class="lex-owner-pill ${withClient ? "with-client" : "with-ops"}">${withClient ? "With You" : "With Legal Team"}</span><span class="indicator-pill ${indicatorColor(intake.status)} ${statusClass(intake.status)}">${escapeHTML(intake.status)}</span></div></div><div class="lex-intake-steps"><span class="${intake.document_count ? "done" : ""}">Documents</span><span class="${intake.cost_estimate_status === "Ready" ? "done" : ""}">Lextimator<sup class="lex-tm">TM</sup> estimate</span><span class="${["Ready", "Accepted"].includes(intake.quote_status) ? "done" : ""}">Confirmed fixed price</span><span class="${intake.funding_status === "Funded" ? "done" : ""}">${intake.funding_route === "Complimentary Pilot" ? "Complimentary pilot" : "Payment or Legal Capacity"}</span></div>${action}${clientDeleteAction(intake)}</article>`;
	}

	function fundingOptions(intake, data) {
		const currency = intake.currency || "CAD";
		const required = Number(intake.required_legal_capacity || intake.quoted_amount || 0);
		const available = Number(intake.available_legal_capacity || 0);
		const enough = available >= required;
		const plan = intake.recommended_plan_details;
		const paymentEnabled = Boolean(data.lexpack?.payment_enabled);
		const pilot = data.pilot || {};
		const canRequestPilot = data.permissions.can_create_matters && pilot.status === "Available" && (!intake.pilot_status || intake.pilot_status === "Not Requested")
			&& pilot.currency === currency && Number(intake.quoted_amount) <= Number(pilot.value_limit);
		const pilotAction = intake.pilot_status === "Requested"
			? '<article><strong>Complimentary Pilot Engagement</strong><p>Awaiting Lexocrates scope approval. This one-time allowance is separate from LexPack Legal Capacity.</p></article>'
			: canRequestPilot
				? `<article><strong>Complimentary Pilot Engagement</strong><p>Limited-scope assignment at no cost. Activates immediately — this one-time allowance is separate from LexPack Legal Capacity. Applicable limit: ${escapeHTML(pilotMoney(pilot.value_limit, currency))}.</p><button class="lex-button btn btn-primary btn-sm" type="button" data-request-pilot="${escapeHTML(intake.name)}">Activate complimentary pilot</button></article>`
				: "";
		const capacityAction = enough && intake.can_fund_legal_capacity
			? `<button class="lex-button btn btn-primary btn-sm" type="button" data-fund-existing="${escapeHTML(intake.name)}">Use ${escapeHTML(capacityMoney(required, currency))} Legal Capacity</button>`
			: "";
		const planAction = plan && intake.can_fund_legal_capacity && paymentEnabled && plan.self_service
			? `<button class="lex-button btn btn-primary btn-sm" type="button" data-buy-lexpack="${escapeHTML(plan.name)}" data-work-intake="${escapeHTML(intake.name)}">Choose ${escapeHTML(plan.plan_name)} LexPack<sup class="lex-tm">TM</sup></button>`
			: "";
		const directAction = intake.can_pay_direct && paymentEnabled
			? `<button class="lex-button secondary btn btn-default btn-sm" type="button" data-pay-direct="${escapeHTML(intake.name)}">Pay this assignment · ${escapeHTML(fmtMoney(intake.quoted_amount, currency))}</button>`
			: '<button class="lex-button secondary btn btn-default btn-sm" type="button" disabled>Direct payment setup/authority required</button>';
		const lexpackOption = plan
			? `<article><strong>Option 2 · Explore LexPack<sup class="lex-tm">TM</sup> savings</strong><p>${escapeHTML(plan.discount_percent)}% value advantage: pay ${escapeHTML(fmtMoney(plan.price, plan.currency))} and receive ${escapeHTML(capacityMoney(plan.legal_capacity_amount, plan.currency))} Legal Capacity.</p>${planAction || '<span class="text-muted">LexPack checkout is not available for this account.</span>'}</article>`
			: "";
		return `<div class="lex-intake-action"><h4>Confirmed fixed price</h4><div class="lex-quote-summary"><span><small>Pay per assignment</small><strong>${escapeHTML(fmtMoney(intake.quoted_amount, currency))}</strong></span><span><small>Legal Capacity required</small><strong>${escapeHTML(capacityMoney(required, currency))}</strong></span><span><small>Available Legal Capacity</small><strong>${escapeHTML(capacityMoney(available, currency))}</strong></span><span><small>Delivery deadline</small><strong>${escapeHTML(fmtDate(intake.requested_delivery_date))}</strong></span></div><div class="lex-scope-box"><strong>Confirmed scope · quote v${fmtNumber(intake.quote_version)}</strong><p>${escapeHTML(intake.scope_summary)}</p><small>Valid until ${escapeHTML(fmtDate(intake.quote_valid_until))}</small></div><div class="lex-funding-choice">${pilotAction}<article><strong>Pay for this assignment</strong><p>Pay the confirmed fixed price without purchasing a LexPack<sup class="lex-tm">TM</sup>.</p>${directAction}${capacityAction}</article>${lexpackOption}</div>${intake.failure_reason ? `<div class="lex-alert">${escapeHTML(intake.failure_reason)}</div>` : ""}</div>`;
	}

	/* ---------- Work Status, Documents & Approvals ---------- */

	function filteredJobs(data) {
		const q = state.jobFilter.query.trim().toLowerCase();
		return (data.jobs || []).filter((row) => {
			if (state.jobFilter.status !== "all" && row.job_status !== state.jobFilter.status) return false;
			if (state.jobFilter.priority !== "all" && row.priority !== state.jobFilter.priority) return false;
			if (q && !`${row.job_title} ${row.matter_title} ${row.job_type}`.toLowerCase().includes(q)) return false;
			return true;
		});
	}

	function workRequestsSection(data) {
		if (!data.permissions.can_create_matters) return "";
		const rows = filteredJobs(data);
		const statuses = ["all", "Draft", "Activated", "Confirmed", "In Progress", "Ready for Delivery", "Completed"];
		const pendingConfirmations = (data.assignment_confirmations || []).filter((c) => c.client_decision === "Pending");
		const confBanner = pendingConfirmations.length
			? `<article class="lex-confirmation-box"><strong>${pendingConfirmations.length} Assignment Confirmation awaiting sign-off</strong><span>Review the confirmed scope and delivery date so the SLA clock can begin.</span><div class="lex-button-row">${pendingConfirmations.map((c) => `<button type="button" class="lex-button btn btn-primary btn-sm" data-open-job="${escapeHTML(c.job)}">Review ${escapeHTML(c.job_title)}</button>`).join("")}</div></article>`
			: "";
		return `<section class="lex-section" data-panel="work-requests">
			${sectionHeader("Work Status", "Draft, funded and active Job work — click any item for SLA & scope controls")}
			<article class="lex-commercial-note"><strong>New work always starts with Submit New Work.</strong><span>The Matter and Draft Job provide context first; secure Job documents, estimate and funding are required before operations begin.</span><button class="lex-button btn btn-primary btn-sm" type="button" data-go="new-matter">Submit new work</button></article>
			${confBanner}
			<div class="lex-filter-bar">
				<div class="lex-filter-controls">
					<input type="search" class="lex-filter-input" data-job-search placeholder="Search jobs, matters, services..." value="${escapeHTML(state.jobFilter.query)}">
					<select class="lex-filter-input" style="min-width:140px;" data-job-priority><option value="all">All Priorities</option>${["Urgent", "High", "Medium", "Low"].map((p) => `<option value="${p}" ${state.jobFilter.priority === p ? "selected" : ""}>${p}</option>`).join("")}</select>
				</div>
				<div class="lex-chip-group">${statuses.map((s) => `<button type="button" class="lex-chip ${state.jobFilter.status === s ? "is-active" : ""}" data-job-status="${escapeHTML(s)}">${s === "all" ? "All" : escapeHTML(s)}</button>`).join("")}</div>
			</div>
			<div id="lex-jobs-container">${card("Visible Jobs", `${rows.length} of ${data.jobs.length} visible items`, jobTable(rows, data.matters))}</div>
		</section>`;
	}

	function filteredDocuments(data) {
		const q = state.docFilter.query.trim().toLowerCase();
		return (data.documents || []).filter((row) => {
			if (state.docFilter.matter !== "all" && row.linked_matter_title !== state.docFilter.matter) return false;
			if (state.docFilter.type !== "all" && row.portal_document_type !== state.docFilter.type) return false;
			if (q && !`${row.file_name} ${row.linked_record_title} ${row.linked_matter_title}`.toLowerCase().includes(q)) return false;
			return true;
		});
	}

	function documentsSection(data) {
		if (!data.navigation.some((row) => row.section === "documents")) return "";
		const rows = filteredDocuments(data);
		const matterTitles = [...new Set((data.documents || []).map((d) => d.linked_matter_title).filter(Boolean))];
		return `<section class="lex-section" data-panel="documents">
			${sectionHeader("Documents", "Protected document vault — client uploads and completed deliverables")}
			<article class="lex-commercial-note"><strong>Controlled document access</strong><span>Upload source documents after SLA acceptance. The final deliverable unlocks only when the Job is Completed.</span><button class="lex-button secondary btn btn-default btn-sm" type="button" data-go="new-matter">Open Work Intake</button></article>
			<div class="lex-filter-bar">
				<div class="lex-filter-controls">
					<input type="search" class="lex-filter-input" data-doc-search placeholder="Search filenames, matters, jobs..." value="${escapeHTML(state.docFilter.query)}">
					<select class="lex-filter-input" style="min-width:170px;" data-doc-matter><option value="all">All Matters</option>${matterTitles.map((m) => `<option value="${escapeHTML(m)}" ${state.docFilter.matter === m ? "selected" : ""}>${escapeHTML(m)}</option>`).join("")}</select>
				</div>
				<div class="lex-chip-group">
					${[["all", "All Files"], ["Client Upload", "Client Uploads"], ["Completed Deliverable", "Deliverables"]].map(([val, lbl]) => `<button type="button" class="lex-chip ${state.docFilter.type === val ? "is-active" : ""}" data-doc-type="${val}">${lbl}</button>`).join("")}
				</div>
			</div>
			<div id="lex-documents-container">${card("Document library", `${rows.length} of ${data.documents.length} files`, documentTable(rows))}</div>
		</section>`;
	}

	function documentTable(rows) {
		if (!rows.length) return empty("No documents are available yet.");
		return `<div class="lex-table-wrap"><table class="lex-table table"><thead><tr><th>Document</th><th>Linked record</th><th>Security</th><th>Size</th><th>Updated</th><th></th></tr></thead><tbody>${rows.map((row) => {
			const isPDF = String(row.file_name || row.file_url || "").toLowerCase().split("?")[0].endsWith(".pdf");
			const downloadURL = row.download_url || row.file_url;
			const scan = row.custom_lex_scan_status || "Clean";
			return `<tr><td><strong>${escapeHTML(row.file_name)}</strong><br><small>${escapeHTML(row.portal_document_type || "Client Upload")}${isPDF ? " · Personalized watermark" : ""}</small></td><td><strong>${escapeHTML(row.linked_record_title || "Work item")}</strong><br><small>${escapeHTML(row.linked_record_type || "Work item")}${row.linked_matter_title ? ` · ${escapeHTML(row.linked_matter_title)}` : ""}</small></td><td><span class="lex-pill indicator-pill ${indicatorColor(scan)}">${escapeHTML(scan)}</span></td><td class="lex-mono">${formatBytes(row.file_size)}</td><td class="lex-mono">${escapeHTML(fmtDate(row.modified))}</td><td style="white-space:nowrap;display:flex;gap:6px;"><button class="lex-button secondary btn btn-default btn-sm" type="button" data-preview-doc="${escapeHTML(downloadURL)}" data-preview-title="${escapeHTML(row.file_name)}" data-preview-matter="${escapeHTML(row.linked_matter_title || "")}">${icon("eye")} Preview</button><a class="lex-button secondary btn btn-default btn-sm" href="${escapeHTML(downloadURL)}" target="_blank" rel="noopener">${isPDF ? "Download protected copy" : "Download"}</a></td></tr>`;
		}).join("")}</tbody></table></div>`;
	}

	function approvalsSection(data) {
		if (!data.navigation.some((row) => row.section === "approvals")) return "";
		const list = data.approvals || [];
		if (!list.length) {
			return `<section class="lex-section" data-panel="approvals">${sectionHeader("Approvals", "Review delivery-ready work and record an auditable decision")}${empty("No deliverables are waiting for your approval.")}</section>`;
		}
		const selected = list.find((r) => r.name === state.selectedApprovalJob) || list[0];
		state.selectedApprovalJob = selected.name;
		const selectorBar = list.length > 1
			? `<div class="lex-filter-bar"><strong>Select Deliverable (${list.length} pending)</strong><div class="lex-chip-group">${list.map((r) => `<button type="button" class="lex-chip ${r.name === selected.name ? "is-active" : ""}" data-select-approval="${escapeHTML(r.name)}">${escapeHTML(r.job_title)}</button>`).join("")}</div></div>`
			: "";
		const studio = `<div class="lex-approval-studio">
			<div class="lex-approval-preview-pane">
				<div class="lex-approval-preview-head">
					<div><strong>Protected Deliverable Preview</strong><br><small class="text-muted">${escapeHTML(selected.job_title)}</small></div>
					${selected.delivery_preview_url ? `<div style="display:flex;gap:6px;"><button type="button" class="lex-button secondary btn btn-default btn-sm" data-load-studio-preview="${escapeHTML(selected.delivery_preview_url)}">Refresh Preview</button><a class="lex-button secondary btn btn-default btn-sm" href="${escapeHTML(selected.delivery_preview_url)}" target="_blank" rel="noopener">Open in New Tab</a></div>` : ""}
				</div>
				<div class="lex-approval-preview-body" id="lex-studio-preview-box" data-auto-preview="${escapeHTML(selected.delivery_preview_url || "")}">
					${selected.delivery_preview_url ? empty("Click Refresh Preview or wait for preview to render...") : '<div class="lex-alert">Preview is unavailable. Ask Legal Operations to regenerate the delivery document.</div>'}
				</div>
			</div>
			<article class="lex-approval frappe-card" data-approval="${escapeHTML(selected.name)}">
				<div class="lex-approval-head"><div><h3>${escapeHTML(selected.job_title)}</h3><p>${escapeHTML(selected.matter_title || "Matter")} · ${escapeHTML(selected.job_type || "Deliverable")}</p></div><span class="lex-pill indicator-pill orange ready-for-delivery">Ready for Delivery</span></div>
				<p class="text-muted">Review the personalized protected preview before recording your decision. Approval completes the Job and unlocks the final document library copy.</p>
				<div class="lex-scope-box">
					<strong>Client Review Verification</strong>
					<label class="lex-check"><input type="checkbox" data-approval-ack> I have reviewed the deliverable scope and confirmed completeness.</label>
				</div>
				<textarea class="form-control" data-approval-notes placeholder="Decision notes (required when requesting changes)"></textarea>
				<div class="lex-button-row"><button class="lex-button btn btn-primary btn-sm" type="button" data-decision="Approved">Approve and complete</button><button class="lex-button danger btn btn-danger btn-sm" type="button" data-decision="Changes Requested">Request changes</button></div>
			</article>
		</div>`;
		return `<section class="lex-section" data-panel="approvals">${sectionHeader("Approvals", "Split-screen review studio — inspect watermarked output and record an auditable decision")}${selectorBar}${studio}</section>`;
	}

	function reportsSection(data) {
		if (!data.navigation.some((row) => row.section === "reports")) return "";
		const reports = data.reports.length ? `<div class="lex-report-grid">${data.reports.map((row) => `<article class="lex-report frappe-card"><h3>${escapeHTML(row.name)}</h3><p>${escapeHTML(row.description)}</p><button class="lex-button secondary btn btn-default btn-sm" type="button" data-report="${escapeHTML(row.name)}">Download CSV</button></article>`).join("")}</div>` : empty("No reports are enabled for your role.");
		return `<section class="lex-section" data-panel="reports">${sectionHeader("Reports", `Access scope: ${data.permissions.report_access || "None"}`)}${reports}</section>`;
	}

	/* ---------- Billing, LexPack Wallet, Users & Organization ---------- */

	function billingSection(data) {
		if (!data.permissions.billing_access) return "";
		const all = data.invoices || [];
		const q = state.invoiceFilter.query.trim().toLowerCase();
		const filtered = all.filter((row) => {
			if (state.invoiceFilter.status !== "all" && row.status !== state.invoiceFilter.status) return false;
			if (q && !`${row.name} ${row.status}`.toLowerCase().includes(q)) return false;
			return true;
		});
		const totalBilled = all.reduce((sum, r) => sum + Number(r.grand_total || 0), 0);
		const totalOutstanding = all.reduce((sum, r) => sum + Number(r.outstanding_amount || 0), 0);
		const currency = all[0]?.currency || data.client.default_currency || "CAD";
		const rows = filtered.length ? `<div class="lex-table-wrap"><table class="lex-table table"><thead><tr><th>Invoice</th><th>Posting date</th><th>Due date</th><th>Status</th><th>Total</th><th>Outstanding</th></tr></thead><tbody>${filtered.map((row) => `<tr><td class="lex-mono"><strong>${escapeHTML(row.name)}</strong></td><td class="lex-mono">${escapeHTML(fmtDate(row.posting_date))}</td><td class="lex-mono">${escapeHTML(fmtDate(row.due_date))}</td><td><span class="lex-pill indicator-pill ${indicatorColor(row.status)} ${statusClass(row.status)}">${escapeHTML(row.status)}</span></td><td class="lex-mono">${escapeHTML(fmtMoney(row.grand_total, row.currency))}</td><td class="lex-mono">${escapeHTML(fmtMoney(row.outstanding_amount, row.currency))}</td></tr>`).join("")}</tbody></table></div>` : empty("No invoices match the current filter.");
		return `<section class="lex-section" data-panel="billing">
			${sectionHeader("Billing", "Organization invoices and outstanding balances")}
			<div class="lex-metrics">${metric("Total Invoiced", fmtMoney(totalBilled, currency), `${all.length} invoices`, "invoice")}${metric("Outstanding", fmtMoney(totalOutstanding, currency), totalOutstanding > 0 ? "Payment pending" : "All settled", "clock")}</div>
			<div class="lex-filter-bar">
				<input type="search" class="lex-filter-input" data-invoice-search placeholder="Search invoice ID..." value="${escapeHTML(state.invoiceFilter.query)}">
				<div class="lex-chip-group">${["all", "Paid", "Unpaid", "Overdue"].map((s) => `<button type="button" class="lex-chip ${state.invoiceFilter.status === s ? "is-active" : ""}" data-invoice-status="${s}">${s === "all" ? "All" : s}</button>`).join("")}</div>
			</div>
			<div id="lex-billing-container">${card("Invoices", "Financial access required", rows)}</div>
		</section>`;
	}

	function walletCard(data) {
		if (!data.wallet) return card("LexPack", "Role protected", empty("Legal Capacity is not available for your role."));
		if (data.wallet.requires_legal_capacity_reconciliation) return card("LexPack", "Legal Capacity reconciliation required", empty("Your legacy prepaid balance is being reconciled into currency Legal Capacity. Contact Legal Operations before using it for work."));
		const currency = data.wallet.capacity_currency || data.lexpack?.selected_currency || "CAD";
		const avail = Number(data.wallet.current_balance || 0);
		const res = Number(data.wallet.reserved_balance || 0);
		const cons = Number(data.wallet.total_consumed || 0);
		const total = Math.max(avail + res + cons, 1);
		return `<article class="lex-card"><div class="lex-wallet"><span class="lex-wallet-label">Available Legal Capacity · never expires</span><div class="lex-wallet-balance">${escapeHTML(capacityMoney(avail, currency))}</div>
			<div class="lex-capacity-bar" aria-label="Legal Capacity allocation"><span class="lex-capacity-seg-available" style="width:${(avail / total) * 100}%"></span><span class="lex-capacity-seg-reserved" style="width:${(res / total) * 100}%"></span><span class="lex-capacity-seg-consumed" style="width:${(cons / total) * 100}%"></span></div>
			<div class="lex-capacity-legend"><span><i class="lex-dot-swatch" style="background:var(--lex-green);"></i> Available ${escapeHTML(capacityMoney(avail, currency))}</span><span><i class="lex-dot-swatch" style="background:var(--lex-accent);"></i> Reserved ${escapeHTML(capacityMoney(res, currency))}</span><span><i class="lex-dot-swatch" style="background:var(--lex-primary);opacity:.5;"></i> Used ${escapeHTML(capacityMoney(cons, currency))}</span></div>
			<div class="lex-wallet-tier"><span><small>Current tier</small><strong>${escapeHTML(data.wallet.current_pricing_tier || "Not qualified")}</strong></span><span><small>Rolling 12-month spend</small><strong class="lex-mono">${escapeHTML(capacityMoney(data.wallet.rolling_12_month_spend, currency))}</strong></span></div></div></article>`;
	}

	function walletSection(data) {
		if (!data.wallet) return "";
		if (data.wallet.requires_legal_capacity_reconciliation) return `<section class="lex-section" data-panel="wallet">${sectionHeader("LexPack", "Prepaid Legal Capacity")}${walletCard(data)}</section>`;
		const lexpack = data.lexpack || { plans: [], purchases: [], payment_enabled: false, purchase_access: false };
		const planCards = lexpack.plans.map((plan) => {
			const price = plan.enterprise_custom ? "Custom" : fmtMoney(plan.price, plan.currency);
			const capacity = plan.enterprise_custom ? "Custom Legal Capacity" : capacityMoney(plan.legal_capacity_amount, plan.currency);
			let action = '<a class="lex-button secondary btn btn-default btn-sm" href="mailto:sales@lexocrates.com?subject=LexPack%20Enterprise">Contact sales</a>';
			if (!plan.enterprise_custom && !lexpack.purchase_access) action = '<button class="lex-button secondary btn btn-default btn-sm" type="button" disabled>Ask your portal admin to enable purchase access</button>';
			else if (!plan.enterprise_custom && !lexpack.payment_enabled) action = '<button class="lex-button secondary btn btn-default btn-sm" type="button" disabled>Razorpay setup pending</button>';
			else if (!plan.enterprise_custom) action = `<button class="lex-button btn btn-primary btn-sm" type="button" data-buy-lexpack="${escapeHTML(plan.name)}" data-currency="${escapeHTML(plan.currency)}">Buy LexPack<sup class="lex-tm">TM</sup> · ${escapeHTML(price)}</button>`;
			return `<article class="lex-plan-card frappe-card ${plan.plan_code === "PROFESSIONAL" ? "recommended" : ""}"><div class="lex-plan-top"><div><span class="lex-plan-code">${escapeHTML(plan.plan_code)}</span><h3>${escapeHTML(plan.plan_name)}</h3></div><span class="lex-plan-advantage">${escapeHTML(plan.value_advantage)}</span></div><div class="lex-plan-price">${escapeHTML(price)}</div><div class="lex-plan-points">${escapeHTML(capacity)} Legal Capacity</div><ul><li>Prepaid legal capacity</li><li>All practice areas</li><li>No expiry</li><li>Pricing improves as your relationship grows</li></ul><div class="lex-plan-action">${action}</div></article>`;
		}).join("");
		const statementBar = `<div class="lex-filter-bar">
			<div class="lex-filter-controls">
				<label style="font-size:12px;font-weight:600;display:flex;align-items:center;gap:6px;">From <input type="date" class="lex-filter-input" style="min-width:140px;" id="lex-stmt-from"></label>
				<label style="font-size:12px;font-weight:600;display:flex;align-items:center;gap:6px;">To <input type="date" class="lex-filter-input" style="min-width:140px;" id="lex-stmt-to"></label>
			</div>
			<button type="button" class="lex-button secondary btn btn-default btn-sm" data-download-wallet-csv>Download CSV Statement</button>
		</div>`;
		const ledger = data.transactions.length ? `<div class="lex-table-wrap"><table class="lex-table table"><thead><tr><th>Transaction</th><th>Legal Capacity</th><th>Matter</th><th>Balance</th><th>Date</th></tr></thead><tbody>${data.transactions.map((row) => `<tr><td>${escapeHTML(row.transaction_type)}</td><td class="lex-mono">${escapeHTML(capacityMoney(row.legal_capacity_amount, row.currency))}</td><td>${escapeHTML(row.matter_title || "—")}</td><td class="lex-mono">${escapeHTML(capacityMoney(row.available_balance_after, row.currency))}</td><td class="lex-mono">${escapeHTML(fmtDate(row.posted_on))}</td></tr>`).join("")}</tbody></table></div>` : empty("No Legal Capacity transactions yet.");
		const purchaseHistory = lexpack.purchases.length ? `<div class="lex-table-wrap"><table class="lex-table table"><thead><tr><th>Plan</th><th>Status</th><th>Paid</th><th>Legal Capacity</th><th>Paid on</th></tr></thead><tbody>${lexpack.purchases.map((row) => `<tr><td>${escapeHTML(row.plan_name_snapshot)}</td><td><span class="indicator-pill ${indicatorColor(row.status)} ${statusClass(row.status)}">${escapeHTML(row.status)}</span></td><td class="lex-mono">${escapeHTML(fmtMoney(row.amount, row.currency))}</td><td class="lex-mono">${escapeHTML(capacityMoney(row.legal_capacity_amount, row.currency))}</td><td class="lex-mono">${escapeHTML(fmtDate(row.paid_on))}</td></tr>`).join("")}</tbody></table></div>` : empty("No LexPack purchases yet.");
		return `<section class="lex-section" data-panel="wallet">${sectionHeader("LexPack", "Prepaid legal capacity for ongoing legal work. Pay per assignment remains available.")}${walletCard(data)}<div class="lex-commercial-note"><strong>Pay only for the work you need, or choose LexPack<sup class="lex-tm">TM</sup> for greater value.</strong><span>Lextimator<sup class="lex-tm">TM</sup> confirms the scope and fixed price. You can pay that assignment directly or prepay Legal Capacity for a 7%–28% value advantage.</span><small>${escapeHTML(lexpack.fair_pricing_note || "")}</small></div>${card("LexPack plans", "Prepaid Legal Capacity with 7%, 14%, 21% or 28% value advantage", `<div class="lex-plan-grid">${planCards || empty("No active LexPack plans.")}</div>`)}${card("Purchase history", `${lexpack.purchases.length} purchases`, purchaseHistory)}${statementBar}${card("Legal Capacity ledger", `${data.transactions.length} transactions`, ledger)}</section>`;
	}

	function auditCard(rows) {
		const body = rows.length ? `<div class="lex-card-body"><ol class="lex-audit">${rows.slice(0, 8).map((row) => `<li><strong>${escapeHTML(row.action)}</strong><span>${escapeHTML(fmtDate(row.event_timestamp))} · ${escapeHTML(row.user || "System")}</span></li>`).join("")}</ol></div>` : empty("No portal activity yet.");
		return card("Organization activity", "Protected audit trail", body);
	}

	const ROLE_PRESET_SUMMARIES = {
		"Client Administrator": "Full organization administration, team & access control, Matter creation, approvals, billing, and reporting.",
		"Partner / General Counsel": "All-matter visibility, Matter/Job creation, deliverable & commercial approvals, and reporting.",
		"Legal User": "Create Matters/Jobs, upload source documents, collaborate in Matter rooms, and view assigned Matters.",
		"Operations User": "Coordinate intakes, upload documents, and track active Jobs across assigned Matters.",
		"Finance User": "View organization invoices, billing statements, and LexPack Legal Capacity ledger.",
		"Procurement User": "Commercial quote review, LexPack purchasing, and vendor compliance oversight.",
		"Compliance User": "Compliance audit log inspection, Master SLA status, and compliance report downloads.",
		"Read-Only User": "Read-only inspection of assigned Matters without creation, upload, or approval authority.",
	};

	function usersSection(data) {
		if (!data.permissions.user_management_authority) return "";
		const roles = Object.keys(ROLE_PRESET_SUMMARIES);
		const roleOptions = roles.map((role) => `<option>${escapeHTML(role)}</option>`).join("");
		const userOptions = data.portal_users.map((row) => `<option value="${escapeHTML(row.name)}">${escapeHTML(row.full_name)} · ${escapeHTML(row.portal_role)}</option>`).join("");
		const matterOptions = data.matters.map((row) => `<option value="${escapeHTML(row.name)}">${escapeHTML(row.matter_title)}</option>`).join("");
		const table = data.portal_users.length ? `<div class="lex-table-wrap"><table class="lex-table table"><thead><tr><th>User</th><th>Role</th><th>Status</th><th>Last login</th><th></th></tr></thead><tbody>${data.portal_users.map((row) => `<tr><td><strong>${escapeHTML(row.full_name)}</strong><br><small>${escapeHTML(row.email)}</small></td><td>${escapeHTML(row.portal_role)}</td><td><span class="lex-pill indicator-pill ${indicatorColor(row.account_status)} ${statusClass(row.account_status)}">${escapeHTML(row.account_status)}</span></td><td class="lex-mono">${escapeHTML(fmtDate(row.last_login))}</td><td>${row.account_status === "Active" && row.email !== data.profile.email ? `<button type="button" class="lex-button danger btn btn-danger btn-sm" data-disable-user="${escapeHTML(row.name)}" data-disable-user-name="${escapeHTML(row.full_name)}">Disable</button>` : ""}</td></tr>`).join("")}</tbody></table></div>` : empty("No portal users.");
		return `<section class="lex-section" data-panel="users">${sectionHeader("Team & Access", "Manage client Website Users without granting Desk access")}${card("Portal users", `${data.portal_users.length} organization users`, table)}
			<article class="lex-card"><div class="lex-card-head"><div><h3>Invite client user</h3><small>Secure activation link expires in 72 hours</small></div></div><div class="lex-card-body"><form id="lex-invite-user" class="lex-form"><label>Full name<input name="invitee_name" required></label><label>Email<input name="invitee_email" type="email" required></label><label>Designation<input name="designation"></label><label>Portal role<select name="portal_role" data-invite-role>${roleOptions}</select></label><div class="wide lex-scope-box" data-invite-role-summary>${escapeHTML(ROLE_PRESET_SUMMARIES[roles[0]])}</div><label class="wide lex-check"><input name="mfa_required" type="checkbox" value="1"> Require multi-factor authentication</label><div class="wide"><button class="lex-button btn btn-primary btn-sm" type="submit">Send invitation</button></div></form></div></article>
			<article class="lex-card"><div class="lex-card-head"><div><h3>Function permissions</h3><small>Legal, financial and administrative controls</small></div></div><div class="lex-card-body"><form id="lex-user-permissions" class="lex-form"><label class="wide">Portal user<select name="portal_user" required>${userOptions}</select></label><label>Portal role<select name="portal_role">${roleOptions}</select></label><label>Matter scope<select name="matter_access_scope"><option>Assigned Matters</option><option>All Client Matters</option><option>No Matter Access</option></select></label><label>Approval authority<select name="approval_authority"><option>None</option><option>Matter Approval</option><option>Deliverable Approval</option><option>Commercial Approval</option><option>All Client Approvals</option></select></label><label>Report access<select name="report_access"><option>None</option><option>Matter Reports</option><option>Financial Reports</option><option>Compliance Reports</option><option>All Client Reports</option></select></label><div class="wide lex-check-grid">${["can_create_matters:Create matters", "can_upload_documents:Upload documents", "can_comment:Comment", "billing_access:Billing", "lexpack_view_access:View LexPack", "lexpack_purchase_access:Purchase LexPack", "user_management_authority:Manage users", "mfa_required:Require MFA"].map((item) => { const [name, label] = item.split(":"); return `<label class="lex-check"><input name="${name}" type="checkbox" value="1"> ${label}</label>`; }).join("")}</div><div class="wide"><button class="lex-button btn btn-primary btn-sm" type="submit">Update permissions</button></div></form></div></article>
			${data.matters.length ? `<article class="lex-card"><div class="lex-card-head"><div><h3>Matter authorization</h3><small>Per-matter access and actions</small></div></div><div class="lex-card-body"><form id="lex-matter-access" class="lex-form"><label>Matter<select name="matter">${matterOptions}</select></label><label>Portal user<select name="portal_user">${userOptions}</select></label><div class="wide lex-check-grid">${["can_view:View", "can_upload:Upload", "can_comment:Comment", "can_approve:Approve", "can_view_billing:View billing"].map((item) => { const [name, label] = item.split(":"); return `<label class="lex-check"><input name="${name}" type="checkbox" value="1" ${name === "can_view" ? "checked" : ""}> ${label}</label>`; }).join("")}</div><div class="wide"><button class="lex-button btn btn-primary btn-sm" type="submit">Save matter access</button></div></form></div></article>` : ""}
		</section>`;
	}

	function organizationSection(data) {
		if (!data.permissions.user_management_authority) return "";
		const sla = data.master_sla || {};
		const slaDetails = sla.status === "Accepted"
			? `<div class="lex-kv-grid">
				<div><small>Status</small><strong style="color:var(--lex-green);">Accepted (Locked Record)</strong></div>
				<div><small>Version</small><strong class="lex-mono">${escapeHTML(sla.version || "—")}</strong></div>
				<div><small>Accepted On</small><strong class="lex-mono">${escapeHTML(fmtDate(sla.acceptance_datetime))}</strong></div>
				<div><small>Authorized Signatory</small><strong>${escapeHTML(sla.accepted_by_name || "—")}</strong></div>
				<div><small>Designation</small><strong>${escapeHTML(sla.accepted_by_designation || "—")}</strong></div>
				<div><small>Record ID</small><strong class="lex-mono">${escapeHTML(sla.name || "—")}</strong></div>
			</div>`
			: empty("Master Service Level Agreement has not been accepted yet.");
		return `<section class="lex-section" data-panel="organization">
			${sectionHeader("Organization", "Read-only client identity, jurisdiction and Master SLA governance")}
			${card("Client profile", "Maintained by Lexocrates", `<div class="lex-card-body"><div class="lex-form"><label>Organization<input readonly value="${escapeHTML(data.client.customer_name || "—")}"></label><label>Organization type<input readonly value="${escapeHTML(data.client.custom_organization_type || "—")}"></label><label>Default currency<input readonly value="${escapeHTML(data.client.default_currency || "INR")}"></label><label>Primary jurisdiction<input readonly value="${escapeHTML(data.client.custom_primary_jurisdiction || "—")}"></label></div></div>`)}
			${card("Master Service Level Agreement", "Immutable execution record", `<div class="lex-card-body">${slaDetails}</div>`)}
		</section>`;
	}

	/* ---------- Messaging Section & Controller ---------- */

	function messagesSection() {
		return `<section class="lex-section" data-panel="messages">${sectionHeader("Secure Messages", "Real-time, contextual and auditable communication")}<article class="lex-card widget border lex-chat-card"><div class="lex-chat"><aside id="lex-chat-channels" class="lex-chat-sidebar" aria-label="Matter conversations">${empty("Loading Matter conversations...")}</aside><main class="lex-chat-main" style="position:relative;"><header id="lex-chat-header" class="lex-chat-header"><button class="lex-chat-mobile-back" type="button" aria-label="Back to conversations"><span aria-hidden="true">&#8592;</span></button><div class="lex-chat-header-copy"><strong>Choose a Matter conversation</strong><span>Your Matter rooms and approved conversations</span></div><div class="lex-chat-toolbar"><button type="button" class="lex-chat-pill-btn" data-chat-pins hidden>Pinned</button><button type="button" class="lex-chat-pill-btn" data-chat-search-toggle hidden>Search</button><button type="button" class="lex-chat-pill-btn" data-chat-members hidden>Members</button><span class="lex-chat-security">Private channel</span></div></header><div id="lex-chat-subbar" class="lex-chat-subbar" hidden></div><div style="display:flex;flex:1 1 auto;min-height:0;position:relative;"><div style="display:flex;flex-direction:column;flex:1 1 auto;min-width:0;"><div id="lex-chat-messages" class="lex-chat-messages" role="log" aria-live="polite" tabindex="0" aria-label="Conversation history">${empty("Choose a Matter room to view messages.")}</div><div id="lex-chat-typing" class="lex-chat-typing" aria-live="polite"></div></div><aside id="lex-chat-thread-pane" class="lex-chat-thread-pane" hidden></aside></div><form id="lex-chat-compose" class="lex-chat-compose"><select class="form-control lex-chat-job-picker" name="job_mention" aria-label="Mention a related Job" disabled><option value="">@ Job</option></select><input class="form-control" name="message" maxlength="10000" placeholder="Write a secure message" aria-label="Message" autocomplete="off" disabled><button class="lex-button btn btn-primary btn-sm" type="submit" disabled>Send</button></form></main></div></article></section>`;
	}

	/* ---------- Binding: Navigation, Navbar Command Search, Forms, Interactive Filters ---------- */

	function bindNavigation(root, data) {
		const app = document.getElementById("lex-app");
		const menuButton = root.querySelector("[data-open-sidebar]");
		const setSidebarOpen = (open) => {
			app.classList.toggle("sidebar-open", open);
			document.body.classList.toggle("lex-portal-sidebar-open", open);
			menuButton?.setAttribute("aria-expanded", String(open));
		};
		const available = new Set(data.navigation.filter((item) => item.section).map((item) => item.section));
		const titleBySection = Object.fromEntries(data.navigation.filter((item) => item.section).map((item) => [item.section, item.label]));
		const activate = (requested) => {
			const section = available.has(requested) ? requested : "overview";
			state.activeSection = section;
			root.querySelectorAll("[data-section]").forEach((item) => { const active = item.dataset.section === section; item.classList.toggle("active", active); item.classList.toggle("selected", active); });
			root.querySelectorAll("[data-panel]").forEach((item) => item.classList.toggle("active", item.dataset.panel === section));
			const title = titleBySection[section] || "Dashboard";
			document.getElementById("lex-page-title").textContent = title;
			setSidebarOpen(false);
			if (section === "messages") mountChat();
			if (section === "approvals") autoLoadApprovalPreview(root);
			window.scrollTo({ top: 0, behavior: "smooth" });
		};
		currentActivate = activate;
		currentSetSidebarOpen = setSidebarOpen;
		root.querySelectorAll("[data-section]").forEach((button) => button.addEventListener("click", () => { window.location.hash = button.dataset.section; activate(button.dataset.section); }));
		root.querySelectorAll("[data-go]").forEach((button) => button.addEventListener("click", () => { window.location.hash = button.dataset.go; activate(button.dataset.go); }));
		menuButton?.addEventListener("click", () => setSidebarOpen(true));
		root.querySelectorAll("[data-close-sidebar]").forEach((button) => button.addEventListener("click", () => setSidebarOpen(false)));
		if (!navigationGlobalsBound) {
			navigationGlobalsBound = true;
			document.addEventListener("keydown", (event) => {
				if (event.key === "Escape") {
					currentSetSidebarOpen(false);
					closeModal();
					closeDrawer();
					const popover = document.getElementById("lex-command-popover");
					if (popover) popover.hidden = true;
				}
				if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
					event.preventDefault();
					document.querySelector("#lex-workspace-search input")?.focus();
				}
			});
			window.addEventListener("resize", () => {
				if (window.innerWidth >= 1080) currentSetSidebarOpen(false);
			}, { passive: true });
			window.addEventListener("hashchange", () => currentActivate(window.location.hash.slice(1)), { passive: true });
		}
		activate(window.location.hash.slice(1) || "overview");
	}

	function bindNavbar(root, data) {
		const menu = root.querySelector("[data-user-menu]");
		const menuToggle = root.querySelector("[data-user-menu-toggle]");
		menuToggle?.setAttribute("aria-expanded", "false");
		menuToggle?.addEventListener("click", (event) => {
			event.stopPropagation();
			const open = !menu?.classList.contains("show");
			menu?.classList.toggle("show", open);
			menuToggle.setAttribute("aria-expanded", String(open));
		});
		currentCloseUserMenu = (event) => {
			if (!event.target.closest(".lex-user-dropdown")) {
				menu?.classList.remove("show");
				menuToggle?.setAttribute("aria-expanded", "false");
			}
			if (!event.target.closest(".lex-search-wrap")) {
				const popover = document.getElementById("lex-command-popover");
				if (popover) popover.hidden = true;
			}
		};
		if (!navbarGlobalsBound) {
			navbarGlobalsBound = true;
			document.addEventListener("click", (event) => currentCloseUserMenu(event));
		}

		const search = document.getElementById("lex-workspace-search");
		const input = search?.elements.query;
		const popover = document.getElementById("lex-command-popover");
		const renderCommandResults = (raw) => {
			if (!popover) return;
			const query = (raw || "").trim().toLowerCase();
			if (!query) { popover.hidden = true; popover.innerHTML = ""; return; }
			const groups = [];
			const matters = (data.matters || []).filter((m) => `${m.matter_title} ${m.practice_area} ${m.counterparty_name}`.toLowerCase().includes(query)).slice(0, 4);
			if (matters.length) groups.push({ label: "Matters", items: matters.map((m) => ({ title: m.matter_title, sub: `${m.practice_area || "Legal"} · ${m.status}`, attr: `data-cmd-matter="${escapeHTML(m.name)}"` })) });
			const jobs = (data.jobs || []).filter((j) => `${j.job_title} ${j.matter_title} ${j.job_type}`.toLowerCase().includes(query)).slice(0, 4);
			if (jobs.length) groups.push({ label: "Jobs", items: jobs.map((j) => ({ title: j.job_title, sub: `${j.matter_title} · ${j.job_status}`, attr: `data-cmd-job="${escapeHTML(j.name)}"` })) });
			const docs = (data.documents || []).filter((d) => `${d.file_name} ${d.linked_matter_title}`.toLowerCase().includes(query)).slice(0, 4);
			if (docs.length) groups.push({ label: "Documents", items: docs.map((d) => ({ title: d.file_name, sub: d.linked_matter_title || d.portal_document_type, attr: `data-cmd-doc="${escapeHTML(d.download_url || d.file_url)}" data-cmd-doc-title="${escapeHTML(d.file_name)}" data-cmd-doc-matter="${escapeHTML(d.linked_matter_title || "")}"` })) });
			const navs = (data.navigation || []).filter((n) => n.section && n.label.toLowerCase().includes(query)).slice(0, 4);
			if (navs.length) groups.push({ label: "Sections", items: navs.map((n) => ({ title: n.label, sub: "Navigate to section", attr: `data-cmd-section="${escapeHTML(n.section)}"` })) });

			popover.innerHTML = groups.length
				? groups.map((g) => `<div class="lex-command-group-label">${escapeHTML(g.label)}</div>${g.items.map((item) => `<button type="button" class="lex-command-item" ${item.attr}><span class="lex-command-item-copy"><strong>${escapeHTML(item.title)}</strong><small>${escapeHTML(item.sub)}</small></span><span>↵</span></button>`).join("")}`).join("")
				: empty(`No matches for "${query}"`);
			popover.hidden = false;
			popover.querySelectorAll("[data-cmd-matter]").forEach((btn) => btn.addEventListener("click", () => { popover.hidden = true; openMatterDrawer(btn.dataset.cmdMatter); }));
			popover.querySelectorAll("[data-cmd-job]").forEach((btn) => btn.addEventListener("click", () => { popover.hidden = true; openJobDrawer(btn.dataset.cmdJob); }));
			popover.querySelectorAll("[data-cmd-doc]").forEach((btn) => btn.addEventListener("click", () => { popover.hidden = true; openDocumentPreviewModal(btn.dataset.cmdDocTitle, btn.dataset.cmdDocMatter, btn.dataset.cmdDoc); }));
			popover.querySelectorAll("[data-cmd-section]").forEach((btn) => btn.addEventListener("click", () => { popover.hidden = true; window.location.hash = btn.dataset.cmdSection; currentActivate(btn.dataset.cmdSection); }));
		};
		input?.addEventListener("input", () => renderCommandResults(input.value));
		input?.addEventListener("focus", () => { if (input.value.trim()) renderCommandResults(input.value); });
		search?.addEventListener("submit", (event) => {
			event.preventDefault();
			const first = popover?.querySelector(".lex-command-item");
			if (first) { first.click(); search.reset(); }
			else notify("No matching workspace item", "orange");
		});
	}

	function formValues(form, checks = []) {
		const values = Object.fromEntries(new FormData(form));
		for (const name of checks) values[name] = form.elements[name]?.checked ? 1 : 0;
		return values;
	}

	function applyPendingMatterToIntake() {
		const form = document.getElementById("lex-new-intake");
		if (!form || !state.pendingMatterForIntake) return;
		const mode = form.querySelector("[data-matter-mode]");
		const sel = form.querySelector("[data-existing-matter-select]");
		if (mode && sel && [...sel.options].some((o) => o.value === state.pendingMatterForIntake)) {
			mode.value = "existing";
			sel.value = state.pendingMatterForIntake;
			mode.dispatchEvent(new Event("change"));
		}
		state.pendingMatterForIntake = null;
	}

	function bindForms(root, data) {
		root.querySelectorAll("[data-master-sla]").forEach((form) => form.addEventListener("submit", async (event) => {
			event.preventDefault();
			const button = form.querySelector("button[type=submit]");
			const values = formValues(form, MASTER_SLA_ACKS.map(([name]) => name));
			setBusy(button, "Accepting...");
			try {
				await call("lex.lex.doctype.master_service_level_agreement.master_service_level_agreement.accept", {
					name: form.dataset.masterSla,
					accepted_by_name: values.accepted_by_name,
					accepted_by_designation: values.accepted_by_designation,
					...Object.fromEntries(MASTER_SLA_ACKS.map(([name]) => [name, values[name]])),
				});
				notify("Master Service Level Agreement accepted. You can now submit new work.");
				reloadSection("new-matter");
			} catch (error) { showError("SLA acceptance failed", error); clearBusy(button); }
		}));

		const serviceSopFields = {
			"Litigation Support": [["court_tribunal", "Court or tribunal"], ["court_file_number", "Court file number (or state action is uncommenced)"], ["party_details", "All parties, roles and represented side"], ["procedural_stage", "Current procedural stage"], ["known_deadlines", "Known deadlines / limitation dates"], ["supporting_documents", "Supporting court documents and orders"], ["deliverable_type", "Requested deliverable type and format"], ["data_handling_restrictions", "Data residency / handling restrictions (enter 'No additional restrictions' if none)"]],
			"Contract Review": [["contract_type", "Contract type"], ["counterparty_names", "Counterparty name(s)"], ["governing_law", "Governing law and jurisdiction"], ["business_terms", "Key business terms / instructions"], ["key_dates", "Renewal date, notice period and key obligations"], ["supporting_documents", "Contract version, template and supporting documents"], ["deliverable_type", "Requested deliverable type and format"], ["data_handling_restrictions", "Data residency / handling restrictions (enter 'No additional restrictions' if none)"]],
			"Document Review": [["matter_context", "Matter / litigation or regulatory context"], ["custodians_data_sources", "Custodians and data sources"], ["known_parties", "Known parties relevant to conflict screening"], ["review_protocol", "Review protocol and coding scheme"], ["volume_format", "Document / ESI volume and format"], ["preservation_confirmation", "Litigation Hold / preservation confirmation"], ["production_specs", "Production deadline, Bates and format requirements"], ["supporting_documents", "Protective order, prior privilege log or search terms"], ["data_handling_restrictions", "Data residency / handling restrictions (enter 'No additional restrictions' if none)"]],
			"Compliance Review": [["industry_regime", "Industry and applicable regulatory regime"], ["operating_jurisdictions", "Jurisdictions of operation"], ["current_policies", "Current policies / compliance documentation"], ["regulatory_dates", "Known filing, renewal and reporting dates"], ["supporting_documents", "Regulator correspondence and supporting documents"], ["deliverable_type", "Requested deliverable type"], ["data_handling_restrictions", "Data residency / handling restrictions (enter 'No additional restrictions' if none)"]],
			"Drafting": [["task_category", "Task type / category"], ["task_instructions", "Task description and specific instructions"], ["recurrence_schedule", "One-time or recurring schedule and standing instructions"], ["task_deadlines", "Deadline or scheduling constraint"], ["required_access", "Required documents or system access"], ["supporting_documents", "Source documents and templates"], ["deliverable_type", "Requested deliverable format"], ["data_handling_restrictions", "Data residency / handling restrictions (enter 'No additional restrictions' if none)"], ["review_tier", "Review tier: Routine, Client-Facing, or Filing/Court-Facing"]]
		};

		const intakeForm = document.getElementById("lex-new-intake");
		if (intakeForm) {
			const pages = intakeForm.querySelectorAll("[data-intake-page]");
			const stepButtons = intakeForm.querySelectorAll("[data-intake-step]");
			const matterMode = intakeForm.querySelector("[data-matter-mode]");
			const existingMatter = intakeForm.querySelector("[data-existing-matter]");
			const existingMatterSelect = intakeForm.querySelector("[data-existing-matter-select]");
			const newMatterFields = intakeForm.querySelector("[data-new-matter-fields]");
			const matterTitle = intakeForm.elements.matter_title;
			const serviceType = intakeForm.querySelector("[data-service-type]");
			const legalResearchFields = intakeForm.querySelector("[data-legal-research-fields]");
			const serviceSopFieldsPanel = intakeForm.querySelector("[data-service-sop-fields]");
			const serviceSopFieldContainer = intakeForm.querySelector("[data-service-sop-field-container]");

			const setMatterMode = () => {
				const isExisting = matterMode?.value === "existing";
				existingMatter.hidden = !isExisting;
				newMatterFields.hidden = isExisting;
				if (matterTitle) matterTitle.required = !isExisting;
				if (existingMatterSelect) existingMatterSelect.required = isExisting;
			};
			const setServiceFields = () => {
				const isLegalResearch = serviceType?.value === "Legal Research";
				if (legalResearchFields) legalResearchFields.hidden = !isLegalResearch;
				intakeForm.querySelectorAll("[data-legal-research-required]").forEach((field) => {
					field.required = isLegalResearch;
				});
				const sopFields = serviceSopFields[serviceType?.value] || [];
				if (serviceSopFieldsPanel) serviceSopFieldsPanel.hidden = !sopFields.length;
				if (serviceSopFieldContainer) {
					serviceSopFieldContainer.innerHTML = sopFields.map(([name, label]) => {
						const control = name === "review_tier"
							? `<select data-service-sop-field="${name}" required><option value="">Select review tier</option><option>Routine</option><option>Client-Facing</option><option>Filing/Court-Facing</option></select>`
							: `<textarea data-service-sop-field="${name}" required placeholder="${escapeHTML(label)}"></textarea>`;
						return `<label class="wide">${escapeHTML(label)}${control}</label>`;
					}).join("") + (sopFields.length ? '<label class="wide lex-check"><input name="no_ai_tools" type="checkbox" value="1"> This assignment must not use AI-assisted or TAR tools.</label>' : "");
				}
			};
			const showStep = (step) => {
				pages.forEach((page) => {
					const active = page.dataset.intakePage === String(step);
					page.hidden = !active;
					page.classList.toggle("is-active", active);
				});
				stepButtons.forEach((button) => {
					const active = button.dataset.intakeStep === String(step);
					button.classList.toggle("is-active", active);
					button.classList.toggle("is-complete", Number(button.dataset.intakeStep) < Number(step));
				});
			};
			const validateMatterStep = () => {
				setMatterMode();
				if (matterMode?.value === "existing") {
					if (existingMatterSelect?.value) return true;
					showError("Matter required", "Select an existing active Matter before continuing.");
					return false;
				}
				if (matterTitle?.value.trim()) return true;
				showError("Matter title required", "Enter a Matter title before continuing to Job details.");
				matterTitle?.focus();
				return false;
			};

			// Service Card Picker sync
			intakeForm.querySelectorAll("[data-service-choice]").forEach((cardBtn) => cardBtn.addEventListener("click", () => {
				intakeForm.querySelectorAll("[data-service-choice]").forEach((b) => b.classList.remove("is-selected"));
				cardBtn.classList.add("is-selected");
				if (serviceType) {
					serviceType.value = cardBtn.dataset.serviceChoice;
					serviceType.dispatchEvent(new Event("change"));
				}
			}));

			matterMode?.addEventListener("change", setMatterMode);
			serviceType?.addEventListener("change", setServiceFields);
			setMatterMode();
			setServiceFields();
			applyPendingMatterToIntake();

			// Draft persistence in sessionStorage
			const syncServiceCards = () => {
				const selectedVal = serviceType?.value;
				const cards = [...intakeForm.querySelectorAll("[data-service-choice]")];
				const active = cards.find((c) => c.classList.contains("is-selected"));
				if (active && active.dataset.serviceChoice === selectedVal) return;
				cards.forEach((c) => c.classList.remove("is-selected"));
				const match = cards.find((c) => c.dataset.serviceChoice === selectedVal);
				if (match) match.classList.add("is-selected");
			};
			try {
				const saved = JSON.parse(sessionStorage.getItem(INTAKE_DRAFT_KEY) || "null");
				if (saved && typeof saved === "object") {
					for (const [k, v] of Object.entries(saved)) {
						const el = intakeForm.elements[k];
						if (el && el.type !== "checkbox" && el.type !== "file" && !el.value) el.value = v;
					}
					setMatterMode();
					setServiceFields();
					syncServiceCards();
				}
			} catch (_) { /* ignore storage errors */ }

			intakeForm.addEventListener("input", () => {
				try {
					const draft = {};
					for (const key of ["matter_mode", "matter_title", "intake_title", "service_type", "preliminary_details", "jurisdiction", "expected_outcome", "priority"]) {
						if (intakeForm.elements[key]) draft[key] = intakeForm.elements[key].value;
					}
					sessionStorage.setItem(INTAKE_DRAFT_KEY, JSON.stringify(draft));
				} catch (_) { /* ignore */ }
			});
			intakeForm.querySelector("[data-clear-intake-draft]")?.addEventListener("click", () => {
				intakeForm.reset();
				try { sessionStorage.removeItem(INTAKE_DRAFT_KEY); } catch (_) { /* ignore */ }
				setMatterMode();
				setServiceFields();
				syncServiceCards();
				notify("Intake draft cleared.", "blue");
			});

			intakeForm.querySelector("[data-next-intake-step]")?.addEventListener("click", () => { if (validateMatterStep()) showStep(2); });
			intakeForm.querySelector("[data-previous-intake-step]")?.addEventListener("click", () => showStep(1));
			stepButtons.forEach((button) => button.addEventListener("click", () => {
				const step = Number(button.dataset.intakeStep);
				if (step === 1 || validateMatterStep()) showStep(step);
			}));

			intakeForm.addEventListener("submit", async (event) => {
				event.preventDefault();
				if (!validateMatterStep() || !intakeForm.reportValidity()) return;
				const button = intakeForm.querySelector("button[type=submit]");
				setBusy(button, "Creating Draft Job...");
				try {
					const values = Object.fromEntries(new FormData(intakeForm));
					const details = {};
					intakeForm.querySelectorAll("[data-service-sop-field]").forEach((field) => { details[field.dataset.serviceSopField] = field.value.trim(); });
					if (Object.keys(details).length) values.service_sop_details = JSON.stringify(details);
					delete values.matter_mode;
					await call("lex.work_intake.create_work_intake", values);
					try { sessionStorage.removeItem(INTAKE_DRAFT_KEY); } catch (_) { /* ignore */ }
					notify("Draft Job created. Next, accept the service terms and upload its PDF to receive the fixed price.", "green");
					reloadSection("new-matter");
				} catch (error) {
					showError("Work intake could not be created", error);
					clearBusy(button);
				}
			});
		}

		// Dropzone interactions + uploads
		root.querySelectorAll("[data-pdf-dropzone]").forEach((zone) => {
			const input = zone.querySelector("input[type='file']");
			const label = zone.querySelector("[data-dropzone-label]");
			const updateLabel = () => {
				const file = input?.files?.[0];
				if (label) label.textContent = file ? `${file.name} (${formatBytes(file.size)}) ready to upload` : "PDF only · Max 10 MB · Malware-scanned on upload";
			};
			input?.addEventListener("change", updateLabel);
			zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("is-dragover"); });
			zone.addEventListener("dragleave", () => zone.classList.remove("is-dragover"));
			zone.addEventListener("drop", (e) => {
				e.preventDefault();
				zone.classList.remove("is-dragover");
				if (e.dataTransfer?.files?.length && input) {
					input.files = e.dataTransfer.files;
					updateLabel();
				}
			});
		});

		root.querySelectorAll("[data-accept-sla]").forEach((button) => button.addEventListener("click", async () => {
			const intake = button.dataset.acceptSla;
			const checked = root.querySelector(`[data-sla-check="${CSS.escape(intake)}"]`)?.checked;
			if (!checked) return showError("SLA acceptance required", "Review the SLA Document and select the acceptance checkbox.");
			setBusy(button, "Accepting...");
			try { await call("lex.work_intake.accept_sla", { intake, accepted: 1 }); notify("SLA accepted. Secure upload is now unlocked."); reloadSection("new-matter"); }
			catch (error) { showError("SLA acceptance failed", error); clearBusy(button); }
		}));

		root.querySelectorAll("[data-sop-info-form]").forEach((form) => form.addEventListener("submit", async (event) => {
			event.preventDefault();
			const btn = form.querySelector("button[type=submit]");
			setBusy(btn, "Submitting...");
			try {
				await call("lex.work_intake.submit_sop_information_response", {
					intake: form.dataset.sopInfoForm,
					response_note: form.elements.response_note.value,
				});
				notify("Clarification submitted for Legal Operations verification.");
				reloadSection(state.activeSection);
			} catch (error) { showError("Clarification could not be saved", error); clearBusy(btn); }
		}));

		root.querySelectorAll("[data-intake-upload]").forEach((upload) => upload.addEventListener("submit", async (event) => {
			event.preventDefault();
			const button = upload.querySelector("button[type=submit]");
			const bar = upload.querySelector("[data-upload-bar]");
			const barFill = bar?.querySelector("span");
			const file = upload.elements.file.files[0];
			if (!file) return;
			if (!file.name.toLowerCase().endsWith(".pdf")) return showError("Upload failed", "Only PDF documents are permitted.");
			if (file.size > 10 * 1024 * 1024) return showError("Upload failed", "File must be 10 MB or smaller.");
			setUploadProgress(button, 0);
			if (bar) bar.hidden = false;
			try {
				const content = await readFile(file);
				const response = await callWithProgress(
					"lex.work_intake.upload_document",
					{ intake: upload.dataset.intakeUpload, filename: file.name, content },
					(percent) => { setUploadProgress(button, percent); if (barFill) barFill.style.width = `${percent}%`; },
					() => setBusy(button, "Scanning and estimating..."),
				);
				if (response.estimate) notify("Document scanned and Job cost estimate updated");
				else if (response.quarantine_passed) notify("Document passed security scanning. Add detailed instructions to run the estimate.");
				else notify(`Document remains quarantined: ${response.scan_status}`, "orange");
				reloadSection("new-matter");
			} catch (error) { showError("Upload failed", error); clearBusy(button); if (bar) bar.hidden = true; }
		}));

		root.querySelectorAll("[data-intake-instructions]").forEach((form) => form.addEventListener("submit", async (event) => {
			event.preventDefault();
			const button = form.querySelector("button[type=submit]");
			setBusy(button, "Saving...");
			try {
				const response = await call("lex.work_intake.save_detailed_instructions", {
					intake: form.dataset.intakeInstructions,
					detailed_instructions: form.elements.detailed_instructions.value,
				});
				notify(response.cost_estimate_status ? "Instructions saved and Job cost estimate updated" : "Detailed instructions saved");
				reloadSection("new-matter");
			} catch (error) { showError("Instructions could not be saved", error); clearBusy(button); }
		}));

		root.querySelectorAll("[data-fund-existing]").forEach((button) => button.addEventListener("click", () => {
			const intakeName = button.dataset.fundExisting;
			openModal({
				title: "Confirm Legal Capacity Reservation",
				subtitle: "This will reserve Legal Capacity and activate your Matter and Job immediately.",
				bodyHtml: `<p>Are you ready to reserve the required Legal Capacity from your organization's LexPack wallet and commence execution?</p>`,
				confirmText: "Reserve Capacity & Activate",
				onConfirm: async () => {
					const result = await call("lex.work_intake.fund_with_existing_legal_capacity", { intake: intakeName });
					notify(`Activated ${result.matter} / ${result.job}`);
					reloadSection("new-matter");
				},
			});
		}));

		root.querySelectorAll("[data-request-pilot]").forEach((button) => button.addEventListener("click", async () => {
			setBusy(button, "Activating pilot...");
			try {
				await call("lex.pilot.request_complimentary_pilot", { intake: button.dataset.requestPilot });
				notify("Complimentary pilot approved — your Job is now active.");
				reloadSection("new-matter");
			} catch (error) { showError("Pilot activation failed", error); clearBusy(button); }
		}));

		root.querySelectorAll("[data-delete-intake]").forEach((button) => button.addEventListener("click", () => {
			const intakeName = button.dataset.deleteIntake;
			openModal({
				title: "Delete Unfunded Draft Job",
				subtitle: "This removes the Job from your Client Workspace.",
				danger: true,
				bodyHtml: `<p>You will no longer see this Draft Job or its activity history in the Client Portal.</p>`,
				confirmText: "Delete Job",
				onConfirm: async () => {
					await call("lex.work_intake.cancel_work_intake", { intake: intakeName });
					notify("Job removed from the Client Workspace.", "green");
					reloadSection("new-matter");
				},
			});
		}));

		root.querySelectorAll("[data-delete-matter]").forEach((button) => button.addEventListener("click", (e) => {
			e.stopPropagation();
			confirmDeleteMatter(button.dataset.deleteMatter);
		}));

		bindApprovals(root);

		root.querySelectorAll("[data-report]").forEach((button) => button.addEventListener("click", async () => {
			setBusy(button, "Generating...");
			try { const report = await call("lex.client_portal.generate_portal_report", { report_name: button.dataset.report }); downloadCSV(report); notify("Report downloaded"); }
			catch (error) { showError("Report unavailable", error); }
			finally { clearBusy(button); }
		}));

		root.querySelectorAll("[data-buy-lexpack]").forEach((button) => button.addEventListener("click", () => buyLexPack(button)));
		root.querySelectorAll("[data-pay-direct]").forEach((button) => button.addEventListener("click", () => payDirectQuote(button)));
		root.querySelector("[data-download-wallet-csv]")?.addEventListener("click", () => {
			const from = root.querySelector("#lex-stmt-from")?.value || "";
			const to = root.querySelector("#lex-stmt-to")?.value || "";
			const params = new URLSearchParams();
			if (from) params.set("from_date", from);
			if (to) params.set("to_date", to);
			window.open(`/api/method/lex.wallet_statement.download_wallet_statement_csv?${params.toString()}`, "_blank", "noopener");
		});
		bindAdministration(data);
	}

	function confirmDeleteMatter(matterName) {
		openModal({
			title: "Delete Empty Matter",
			subtitle: "Removes this Matter from your Client Workspace",
			danger: true,
			bodyHtml: `<p>Only Matters whose Jobs have been cancelled can be removed. Its cancelled items will remain hidden.</p>`,
			confirmText: "Delete Matter",
			onConfirm: async () => {
				await call("lex.client_portal.delete_matter", { matter: matterName });
				notify("Matter removed from the Client Workspace.", "green");
				closeDrawer();
				reloadSection("matters");
			},
		});
	}

	function bindApprovals(root) {
		root.querySelectorAll("[data-select-approval]").forEach((btn) => btn.addEventListener("click", () => {
			state.selectedApprovalJob = btn.dataset.selectApproval;
			const panel = root.querySelector('[data-panel="approvals"]');
			if (panel) {
				panel.outerHTML = approvalsSection(state.data);
				bindApprovals(root);
				autoLoadApprovalPreview(root);
			}
		}));
		root.querySelector("[data-load-studio-preview]")?.addEventListener("click", (e) => {
			loadProtectedPreviewInto(root.querySelector("#lex-studio-preview-box"), e.currentTarget.dataset.loadStudioPreview, "Protected Deliverable Preview");
		});
		root.querySelectorAll("[data-approval]").forEach((cardEl) => cardEl.querySelectorAll("[data-decision]").forEach((button) => button.addEventListener("click", async () => {
			const notes = cardEl.querySelector("[data-approval-notes]").value.trim();
			const ack = cardEl.querySelector("[data-approval-ack]")?.checked;
			const decision = button.dataset.decision;
			if (decision === "Approved" && !ack) return showError("Review confirmation required", "Confirm that you have reviewed the deliverable scope and completeness.");
			if (decision === "Changes Requested" && !notes) return showError("Notes required", "Explain the changes required before submitting.");
			cardEl.querySelectorAll("button").forEach((item) => { item.disabled = true; });
			try {
				await call("lex.client_portal.submit_client_approval", { job: cardEl.dataset.approval, decision, notes });
				notify(`Decision recorded: ${decision}`);
				reloadSection("approvals");
			} catch (error) {
				showError("Approval failed", error);
				cardEl.querySelectorAll("button").forEach((item) => { item.disabled = false; });
			}
		})));
	}

	function autoLoadApprovalPreview(root) {
		const box = root.querySelector("#lex-studio-preview-box");
		if (!box || box.dataset.loaded) return;
		const url = box.dataset.autoPreview;
		if (url) {
			box.dataset.loaded = "1";
			loadProtectedPreviewInto(box, url, "Protected Deliverable Preview");
		}
	}

	function bindInteractiveWorkspace(root, data) {
		// Clickable Matter & Job rows/buttons
		root.querySelectorAll("[data-open-matter]").forEach((el) => el.addEventListener("click", (e) => {
			if (e.target.closest("[data-delete-matter], [data-stop-row]")) return;
			e.stopPropagation();
			openMatterDrawer(el.dataset.openMatter);
		}));
		root.querySelectorAll("[data-open-job]").forEach((el) => el.addEventListener("click", (e) => {
			if (e.target.closest("[data-stop-row]")) return;
			e.stopPropagation();
			openJobDrawer(el.dataset.openJob);
		}));
		root.querySelectorAll("[data-preview-doc]").forEach((btn) => btn.addEventListener("click", () => {
			openDocumentPreviewModal(btn.dataset.previewTitle, btn.dataset.previewMatter, btn.dataset.previewDoc);
		}));
		root.querySelectorAll("[data-open-approval]").forEach((btn) => btn.addEventListener("click", () => {
			state.selectedApprovalJob = btn.dataset.openApproval;
			window.location.hash = "approvals";
			currentActivate("approvals");
		}));
		root.querySelectorAll("[data-open-info-hold]").forEach((btn) => btn.addEventListener("click", () => {
			const intake = (data.intakes || []).find((i) => i.name === btn.dataset.openInfoHold);
			if (!intake) return;
			openModal({
				title: intake.information_is_critical ? "Critical Information Hold" : "Information Requested",
				subtitle: `${intake.intake_title} · Requested ${fmtDate(intake.information_requested_on)}`,
				bodyHtml: `<p>${escapeHTML(intake.missing_information || "Legal Operations requires clarification to proceed.")}</p>
					<label style="display:flex;flex-direction:column;gap:6px;font-size:13px;font-weight:600;">Your clarification / response<textarea id="lex-modal-sop-note" class="form-control" rows="4" required>${escapeHTML(intake.information_resolution_note || "")}</textarea></label>`,
				confirmText: "Submit Clarification",
				onConfirm: async (modalHost) => {
					const note = modalHost.querySelector("#lex-modal-sop-note").value.trim();
					if (!note) throw new Error("Provide the requested information before submitting.");
					await call("lex.work_intake.submit_sop_information_response", { intake: intake.name, response_note: note });
					notify("Clarification submitted for Legal Operations verification.");
					reloadSection(state.activeSection);
				},
			});
		}));

		// Matters filtering & view toggle
		const rerenderMatters = () => {
			const container = root.querySelector("#lex-matters-container");
			if (!container) return;
			const rows = filteredMatters(data);
			container.innerHTML = state.matterView === "cards" ? matterCardsGrid(rows, data.jobs) : card("Matter register", `${rows.length} of ${data.matters.length} authorized matters`, matterTable(rows));
			container.querySelectorAll("[data-open-matter]").forEach((el) => el.addEventListener("click", () => openMatterDrawer(el.dataset.openMatter)));
			container.querySelectorAll("[data-delete-matter]").forEach((btn) => btn.addEventListener("click", (e) => { e.stopPropagation(); confirmDeleteMatter(btn.dataset.deleteMatter); }));
		};
		root.querySelector("[data-matter-search]")?.addEventListener("input", (e) => { state.matterFilter.query = e.target.value; rerenderMatters(); });
		root.querySelectorAll("[data-matter-status]").forEach((btn) => btn.addEventListener("click", () => {
			state.matterFilter.status = btn.dataset.matterStatus;
			root.querySelectorAll("[data-matter-status]").forEach((b) => b.classList.toggle("is-active", b === btn));
			rerenderMatters();
		}));
		root.querySelectorAll("[data-matter-view]").forEach((btn) => btn.addEventListener("click", () => {
			state.matterView = btn.dataset.matterView;
			root.querySelectorAll("[data-matter-view]").forEach((b) => b.classList.toggle("is-active", b === btn));
			rerenderMatters();
		}));

		// Intake filter
		root.querySelectorAll("[data-intake-filter]").forEach((btn) => btn.addEventListener("click", () => {
			state.intakeFilter = btn.dataset.intakeFilter;
			const panel = root.querySelector('[data-panel="new-matter"]');
			if (panel) {
				panel.outerHTML = workIntakeSection(data);
				bindForms(root, data);
				bindInteractiveWorkspace(root, data);
				root.querySelector('[data-panel="new-matter"]')?.classList.add("active");
			}
		}));

		// Jobs filter
		const rerenderJobs = () => {
			const container = root.querySelector("#lex-jobs-container");
			if (!container) return;
			const rows = filteredJobs(data);
			container.innerHTML = card("Visible Jobs", `${rows.length} of ${data.jobs.length} visible items`, jobTable(rows, data.matters));
			container.querySelectorAll("[data-open-job]").forEach((el) => el.addEventListener("click", () => openJobDrawer(el.dataset.openJob)));
		};
		root.querySelector("[data-job-search]")?.addEventListener("input", (e) => { state.jobFilter.query = e.target.value; rerenderJobs(); });
		root.querySelector("[data-job-priority]")?.addEventListener("change", (e) => { state.jobFilter.priority = e.target.value; rerenderJobs(); });
		root.querySelectorAll("[data-job-status]").forEach((btn) => btn.addEventListener("click", () => {
			state.jobFilter.status = btn.dataset.jobStatus;
			root.querySelectorAll("[data-job-status]").forEach((b) => b.classList.toggle("is-active", b === btn));
			rerenderJobs();
		}));

		// Docs filter
		const rerenderDocs = () => {
			const container = root.querySelector("#lex-documents-container");
			if (!container) return;
			const rows = filteredDocuments(data);
			container.innerHTML = card("Document library", `${rows.length} of ${data.documents.length} files`, documentTable(rows));
			container.querySelectorAll("[data-preview-doc]").forEach((btn) => btn.addEventListener("click", () => openDocumentPreviewModal(btn.dataset.previewTitle, btn.dataset.previewMatter, btn.dataset.previewDoc)));
		};
		root.querySelector("[data-doc-search]")?.addEventListener("input", (e) => { state.docFilter.query = e.target.value; rerenderDocs(); });
		root.querySelector("[data-doc-matter]")?.addEventListener("change", (e) => { state.docFilter.matter = e.target.value; rerenderDocs(); });
		root.querySelectorAll("[data-doc-type]").forEach((btn) => btn.addEventListener("click", () => {
			state.docFilter.type = btn.dataset.docType;
			root.querySelectorAll("[data-doc-type]").forEach((b) => b.classList.toggle("is-active", b === btn));
			rerenderDocs();
		}));

		// Billing filter
		const rerenderInvoices = () => {
			const container = root.querySelector("#lex-billing-container");
			if (!container) return;
			const q = state.invoiceFilter.query.trim().toLowerCase();
			const filtered = (data.invoices || []).filter((row) => {
				if (state.invoiceFilter.status !== "all" && row.status !== state.invoiceFilter.status) return false;
				if (q && !`${row.name} ${row.status}`.toLowerCase().includes(q)) return false;
				return true;
			});
			const tableHtml = filtered.length ? `<div class="lex-table-wrap"><table class="lex-table table"><thead><tr><th>Invoice</th><th>Posting date</th><th>Due date</th><th>Status</th><th>Total</th><th>Outstanding</th></tr></thead><tbody>${filtered.map((row) => `<tr><td class="lex-mono"><strong>${escapeHTML(row.name)}</strong></td><td class="lex-mono">${escapeHTML(fmtDate(row.posting_date))}</td><td class="lex-mono">${escapeHTML(fmtDate(row.due_date))}</td><td><span class="lex-pill indicator-pill ${indicatorColor(row.status)} ${statusClass(row.status)}">${escapeHTML(row.status)}</span></td><td class="lex-mono">${escapeHTML(fmtMoney(row.grand_total, row.currency))}</td><td class="lex-mono">${escapeHTML(fmtMoney(row.outstanding_amount, row.currency))}</td></tr>`).join("")}</tbody></table></div>` : empty("No invoices match the current filter.");
			container.innerHTML = card("Invoices", "Financial access required", tableHtml);
		};
		root.querySelector("[data-invoice-search]")?.addEventListener("input", (e) => { state.invoiceFilter.query = e.target.value; rerenderInvoices(); });
		root.querySelectorAll("[data-invoice-status]").forEach((btn) => btn.addEventListener("click", () => {
			state.invoiceFilter.status = btn.dataset.invoiceStatus;
			root.querySelectorAll("[data-invoice-status]").forEach((b) => b.classList.toggle("is-active", b === btn));
			rerenderInvoices();
		}));
	}

	async function reloadSection(section) {
		const root = document.getElementById("lex-client-portal");
		if (!root) return window.location.assign(`/client-portal?refresh=${Date.now()}#${encodeURIComponent(section)}`);
		window.location.hash = section;
		try {
			const data = await call("lex.client_portal.get_portal_dashboard");
			render(root, data);
		} catch (error) {
			window.location.assign(`/client-portal?refresh=${Date.now()}#${encodeURIComponent(section)}`);
		}
	}

	/* ---------- Razorpay Payments ---------- */

	let razorpayLoader = null;
	function loadRazorpayCheckout() {
		if (window.Razorpay) return Promise.resolve(window.Razorpay);
		if (razorpayLoader) return razorpayLoader;
		razorpayLoader = new Promise((resolve, reject) => {
			const script = document.createElement("script");
			script.src = "https://checkout.razorpay.com/v1/checkout.js";
			script.async = true;
			script.onload = () => {
				if (window.Razorpay) return resolve(window.Razorpay);
				razorpayLoader = null;
				script.remove();
				reject(new Error("Razorpay Checkout did not initialize."));
			};
			script.onerror = () => {
				razorpayLoader = null;
				script.remove();
				reject(new Error("Razorpay Checkout could not be loaded."));
			};
			document.head.appendChild(script);
		});
		return razorpayLoader;
	}

	async function buyLexPack(button) {
		button.disabled = true;
		const original = button.textContent;
		button.textContent = "Preparing secure payment...";
		try {
			await loadRazorpayCheckout();
			const order = await call("lex.lexpack.create_razorpay_order", { plan: button.dataset.buyLexpack, work_intake: button.dataset.workIntake, currency: button.dataset.currency });
			const checkout = new window.Razorpay({
				...order,
				handler: async (response) => {
					button.textContent = "Verifying payment...";
					try {
						const result = await call("lex.lexpack.verify_razorpay_payment", {
							purchase: order.purchase,
							razorpay_payment_id: response.razorpay_payment_id,
							razorpay_order_id: response.razorpay_order_id,
							razorpay_signature: response.razorpay_signature,
						});
						notify(result.status === "Paid" ? `${fmtMoney(result.legal_capacity_amount, result.currency)} Legal Capacity credited` : result.message, result.status === "Paid" ? "green" : "orange");
						reloadSection(order.work_intake ? "new-matter" : "wallet");
					} catch (error) { showError("Payment verification failed", error); button.disabled = false; button.textContent = original; }
				},
				modal: { ondismiss: () => { button.disabled = false; button.textContent = original; } },
				retry: { enabled: true, max_count: 2 },
			});
			checkout.on("payment.failed", (response) => { showError("Payment failed", response.error?.description || "Razorpay could not complete the payment."); button.disabled = false; button.textContent = original; });
			checkout.open();
		} catch (error) { showError("Payment unavailable", error); button.disabled = false; button.textContent = original; }
	}

	async function payDirectQuote(button) {
		button.disabled = true;
		const original = button.textContent;
		button.textContent = "Preparing direct payment...";
		try {
			await loadRazorpayCheckout();
			const order = await call("lex.work_intake.create_direct_quote_order", { intake: button.dataset.payDirect });
			const checkout = new window.Razorpay({
				...order,
				handler: async (response) => {
					button.textContent = "Verifying and activating...";
					try {
						const result = await call("lex.work_intake.verify_direct_quote_payment", {
							intake: order.intake,
							razorpay_payment_id: response.razorpay_payment_id,
							razorpay_order_id: response.razorpay_order_id,
							razorpay_signature: response.razorpay_signature,
						});
						notify(result.matter ? `Payment confirmed. ${result.matter} activated.` : (result.message || "Payment pending capture"), result.matter ? "green" : "orange");
						reloadSection("new-matter");
					} catch (error) { showError("Payment verification failed", error); button.disabled = false; button.textContent = original; }
				},
				modal: { ondismiss: () => { button.disabled = false; button.textContent = original; } },
				retry: { enabled: true, max_count: 2 },
			});
			checkout.on("payment.failed", (response) => { showError("Payment failed", response.error?.description || "Razorpay could not complete the payment."); button.disabled = false; button.textContent = original; });
			checkout.open();
		} catch (error) { showError("Direct payment unavailable", error); button.disabled = false; button.textContent = original; }
	}

	/* ---------- Administration ---------- */

	function bindAdministration(data) {
		const invite = document.getElementById("lex-invite-user");
		const roleSelect = invite?.querySelector("[data-invite-role]");
		const roleSummary = invite?.querySelector("[data-invite-role-summary]");
		roleSelect?.addEventListener("change", () => {
			if (roleSummary) roleSummary.textContent = ROLE_PRESET_SUMMARIES[roleSelect.value] || "";
		});
		invite?.addEventListener("submit", async (event) => {
			event.preventDefault();
			const button = invite.querySelector("button");
			setBusy(button, "Sending...");
			try { await call("lex.portal_management.invite_portal_user", formValues(invite, ["mfa_required"])); notify("Invitation sent"); reloadSection("users"); }
			catch (error) { showError("Invitation failed", error); clearBusy(button); }
		});
		const permissions = document.getElementById("lex-user-permissions");
		const checks = ["can_create_matters", "can_upload_documents", "can_comment", "billing_access", "lexpack_view_access", "lexpack_purchase_access", "user_management_authority", "mfa_required"];
		const populate = () => {
			if (!permissions) return;
			const row = data.portal_users.find((item) => item.name === permissions.elements.portal_user.value);
			if (!row) return;
			for (const name of ["portal_role", "matter_access_scope", "approval_authority", "report_access"]) permissions.elements[name].value = row[name] || "None";
			for (const name of checks) permissions.elements[name].checked = Boolean(row[name]);
		};
		permissions?.elements.portal_user.addEventListener("change", populate);
		populate();
		permissions?.addEventListener("submit", async (event) => {
			event.preventDefault();
			const values = formValues(permissions, checks);
			const portalUser = values.portal_user;
			delete values.portal_user;
			try { await call("lex.portal_management.update_portal_user_permissions", { portal_user: portalUser, values }); notify("Permissions updated"); reloadSection("users"); }
			catch (error) { showError("Update failed", error); }
		});
		const matterAccess = document.getElementById("lex-matter-access");
		matterAccess?.addEventListener("submit", async (event) => {
			event.preventDefault();
			try { await call("lex.portal_management.set_matter_authorization", formValues(matterAccess, ["can_view", "can_upload", "can_comment", "can_approve", "can_view_billing"])); notify("Matter access updated"); }
			catch (error) { showError("Authorization failed", error); }
		});
		document.querySelectorAll("[data-disable-user]").forEach((button) => button.addEventListener("click", () => {
			const userId = button.dataset.disableUser;
			const userName = button.dataset.disableUserName || userId;
			openModal({
				title: `Disable ${userName}`,
				subtitle: "Revokes portal login while retaining audit records",
				danger: true,
				bodyHtml: `<label style="display:flex;flex-direction:column;gap:6px;font-size:13px;font-weight:600;">Reason for disabling this client user<textarea id="lex-disable-reason" class="form-control" rows="3" required placeholder="e.g. Role change or offboarding"></textarea></label>`,
				confirmText: "Disable User",
				onConfirm: async (modalHost) => {
					const reason = modalHost.querySelector("#lex-disable-reason").value.trim();
					if (!reason) throw new Error("Enter a reason for disabling this user.");
					await call("lex.portal_management.deactivate_portal_user", { portal_user: userId, reason });
					notify("User disabled.");
					reloadSection("users");
				},
			});
		}));
	}

	const readFile = (file) => new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(file); });
	function downloadCSV(report) {
		const quote = (value) => `"${String(value ?? "").replace(/"/g, '""')}"`;
		const rows = [report.columns.map(quote).join(","), ...report.rows.map((row) => report.columns.map((column) => quote(row[column])).join(","))];
		const blob = new Blob(["\ufeff", rows.join("\r\n")], { type: "text/csv;charset=utf-8" });
		const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = `${report.name.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}.csv`; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(link.href);
	}

	/* ---------- Upgraded Privileged Real-Time Chat ---------- */

	function selectMatterChannelByTitle(matterTitle) {
		const channelBox = document.getElementById("lex-chat-channels");
		if (!channelBox || !matterTitle) return;
		const target = [...channelBox.querySelectorAll("[data-channel]")].find((btn) => (btn.dataset.matterSearch || "").includes(matterTitle.toLowerCase()));
		target?.click();
	}

	function mountChat() {
		const channelBox = document.getElementById("lex-chat-channels");
		if (!channelBox || channelBox.dataset.chatMounted === "1") return;
		channelBox.dataset.chatMounted = "1";
		initializeChat().catch((error) => {
			channelBox.dataset.chatMounted = "";
			channelBox.innerHTML = empty(errorMessage(error));
		});
	}

	function bindChatWheel(main, messageBox) {
		if (!main || main.dataset.chatWheelBound) return;
		main.dataset.chatWheelBound = "1";
		main.addEventListener("wheel", (event) => {
			if (event.ctrlKey || Math.abs(event.deltaX) > Math.abs(event.deltaY) || event.target.closest(".lex-chat-messages")) return;
			if (messageBox.scrollHeight <= messageBox.clientHeight) return;
			const maximum = messageBox.scrollHeight - messageBox.clientHeight;
			const next = Math.max(0, Math.min(maximum, messageBox.scrollTop + event.deltaY));
			if (next === messageBox.scrollTop) return;
			event.preventDefault();
			messageBox.scrollTop = next;
		}, { passive: false });
	}

	async function initializeChat() {
		const channelBox = document.getElementById("lex-chat-channels");
		const messageBox = document.getElementById("lex-chat-messages");
		const header = document.getElementById("lex-chat-header");
		const subbar = document.getElementById("lex-chat-subbar");
		const threadPane = document.getElementById("lex-chat-thread-pane");
		const typingBar = document.getElementById("lex-chat-typing");
		const form = document.getElementById("lex-chat-compose");
		if (!channelBox || !messageBox || !form) return;

		const chat = channelBox.closest(".lex-chat");
		const headerTitle = header?.querySelector("strong");
		const headerSubtitle = header?.querySelector(".lex-chat-header-copy span");
		const pinsBtn = header?.querySelector("[data-chat-pins]");
		const searchBtn = header?.querySelector("[data-chat-search-toggle]");
		const membersBtn = header?.querySelector("[data-chat-members]");

		header?.querySelector(".lex-chat-mobile-back")?.addEventListener("click", () => {
			chat?.classList.remove("is-conversation-open");
		});
		bindChatWheel(messageBox.closest(".lex-chat-main"), messageBox);

		let selected = null;
		let realtimeUnsubscribe = null;
		let channelGeneration = 0;
		let readTimer = null;
		let typingStopTimer = null;
		const typingUsers = new Map();
		const msgApi = "lex.lex.doctype.lexocrates_chat_message.lexocrates_chat_message";
		const chanApi = "lex.lex.doctype.lexocrates_chat_channel.lexocrates_chat_channel";

		const canMarkLatestRead = () => (
			!document.hidden &&
			messageBox.offsetParent !== null &&
			messageBox.scrollHeight - messageBox.scrollTop - messageBox.clientHeight < 100
		);
		const markVisibleRead = (messageName) => {
			if (!selected || !messageName || !canMarkLatestRead()) return;
			call(`${msgApi}.mark_channel_read`, { channel: selected.name, message_name: messageName }).catch(() => {});
		};
		const renderTypingBar = () => {
			if (!typingBar) return;
			const now = Date.now();
			for (const [k, v] of typingUsers.entries()) if (v.expires < now) typingUsers.delete(k);
			const names = [...typingUsers.values()].map((v) => v.label);
			typingBar.textContent = names.length ? `${names.join(", ")} ${names.length === 1 ? "is" : "are"} typing...` : "";
		};

		const controller = {
			onMessage: (message) => {
				if (selected && message.channel === selected.name) {
					const wasViewingLatest = canMarkLatestRead();
					appendOrUpdateMessage(message, messageBox);
					if (wasViewingLatest) markVisibleRead(message.name);
				}
			},
			onReaction: (payload) => {
				if (selected && payload?.channel === selected.name && payload.message_name) {
					const el = messageBox.querySelector(`[data-message="${CSS.escape(payload.message_name)}"]`);
					if (el && payload.reactions) updateReactionsDom(el, payload.message_name, payload.reactions);
				}
			},
			onTyping: (payload) => {
				if (!selected || payload?.channel !== selected.name || payload.user === frappe.session.user) return;
				if (payload.is_typing) typingUsers.set(payload.user, { label: payload.full_name || "Team member", expires: Date.now() + 4500 });
				else typingUsers.delete(payload.user);
				renderTypingBar();
			},
		};
		currentChatController = controller;
		currentChatCleanup = () => {
			realtimeUnsubscribe?.();
			realtimeUnsubscribe = null;
			window.clearTimeout(readTimer);
			window.clearTimeout(typingStopTimer);
		};

		if (!chatGlobalsBound) {
			chatGlobalsBound = true;
			frappe.realtime?.on("new_chat_message", (msg) => currentChatController?.onMessage(msg));
			frappe.realtime?.on("chat_message_updated", (msg) => currentChatController?.onMessage(msg));
			frappe.realtime?.on("chat_reaction_changed", (payload) => currentChatController?.onReaction(payload));
			frappe.realtime?.on("chat_typing", (payload) => currentChatController?.onTyping(payload));
		}

		messageBox.addEventListener("scroll", () => {
			window.clearTimeout(readTimer);
			readTimer = window.setTimeout(() => {
				const messages = messageBox.querySelectorAll("[data-message]");
				markVisibleRead(messages[messages.length - 1]?.dataset.message);
			}, 200);
		}, { passive: true });

		await refreshPresence().catch(() => []);
		const channels = await call(`${chanApi}.get_channels`);
		const channelRows = channels.map((channel) => {
			const label = channel.matter_title || channel.display_name || channel.channel_name;
			const context = channel.is_matter_channel
				? [channel.matter_title, channel.organization_name].filter(Boolean).join(" · ")
				: channel.reference_name || channel.channel_type;
			const search = [label, channel.matter_title, channel.organization_name, channel.reference_name].filter(Boolean).join(" ").toLowerCase();
			return `<button type="button" class="lex-chat-channel" data-channel="${escapeHTML(channel.name)}" data-matter-search="${escapeHTML(search)}"><span class="lex-channel-mark">${channel.is_direct_message ? escapeHTML(initials(channel.display_name)) : "#"}</span><span class="lex-channel-text"><strong>${escapeHTML(label)}</strong><span>${escapeHTML(context)}</span></span>${channel.unread_count ? `<span class="lex-nav-badge">${channel.unread_count}</span>` : ""}</button>`;
		}).join("");
		channelBox.innerHTML = channels.length
			? `<div class="lex-chat-matter-search"><input type="search" class="form-control" placeholder="Search Matter name or organization" aria-label="Search Matter channels by name or organization"></div><div class="lex-chat-channel-list">${channelRows}</div>`
			: empty("No Matter conversations are available yet.");
		channelBox.querySelector(".lex-chat-matter-search input")?.addEventListener("input", (event) => {
			const value = event.currentTarget.value.trim().toLowerCase();
			channelBox.querySelectorAll("[data-channel]").forEach((button) => {
				button.classList.toggle("hidden", Boolean(value) && !button.dataset.matterSearch.includes(value));
			});
		});

		const openSubbarMode = async (mode) => {
			if (!subbar || !selected) return;
			const currentMode = subbar.dataset.mode;
			if (!subbar.hidden && currentMode === mode) { subbar.hidden = true; subbar.dataset.mode = ""; return; }
			subbar.dataset.mode = mode;
			subbar.hidden = false;
			if (mode === "search") {
				subbar.innerHTML = `<form style="display:flex;gap:8px;" data-chat-search-form><input type="search" class="lex-filter-input" style="flex:1;" placeholder="Search messages in this room..." required><button class="lex-button btn btn-primary btn-sm" type="submit">Find</button></form><div data-chat-search-results></div>`;
				subbar.querySelector("[data-chat-search-form]").addEventListener("submit", async (e) => {
					e.preventDefault();
					const q = e.target.querySelector("input").value.trim();
					const resBox = subbar.querySelector("[data-chat-search-results]");
					resBox.innerHTML = `<small class="text-muted">Searching...</small>`;
					const hits = await call(`${msgApi}.search_messages`, { search_text: q, channel: selected.name, limit: 20 });
					resBox.innerHTML = hits.length
						? hits.map((m) => `<div style="padding:6px 0;border-top:1px solid var(--lex-border);font-size:12px;"><strong>${escapeHTML(m.sender_full_name)}</strong> <small class="text-muted">${escapeHTML(m.formatted_timestamp || fmtDate(m.sent_at))}</small><div>${m.message_text || ""}</div></div>`).join("")
						: `<small class="text-muted">No matching messages.</small>`;
				});
			} else if (mode === "pins") {
				subbar.innerHTML = `<small class="text-muted">Loading pinned items...</small>`;
				const pins = await call(`${msgApi}.get_pinned_messages`, { channel: selected.name });
				subbar.innerHTML = `<strong>Pinned Legal Instructions (${pins.length})</strong>` + (pins.length
					? pins.map((m) => `<div style="padding:6px 0;border-top:1px solid var(--lex-border);font-size:12px;"><strong>${escapeHTML(m.sender_full_name)}</strong> · <small>${escapeHTML(m.formatted_timestamp || fmtDate(m.sent_at))}</small><div>${m.message_text || ""}</div></div>`).join("")
					: `<small class="text-muted">No pinned messages in this channel.</small>`);
			} else if (mode === "members") {
				subbar.innerHTML = `<small class="text-muted">Loading participants...</small>`;
				const members = await call(`${chanApi}.get_channel_members`, { channel: selected.name });
				subbar.innerHTML = `<strong>Authorized Room Participants (${members.length})</strong><div style="display:flex;flex-wrap:wrap;gap:6px;">${members.map((m) => `<span class="lex-pill indicator-pill blue">${escapeHTML(m.display_name || m.role_label || m.user)}</span>`).join("")}</div>`;
			}
		};
		pinsBtn?.addEventListener("click", () => openSubbarMode("pins"));
		searchBtn?.addEventListener("click", () => openSubbarMode("search"));
		membersBtn?.addEventListener("click", () => openSubbarMode("members"));

		const openThread = async (messageName) => {
			if (!threadPane || !selected) return;
			threadPane.hidden = false;
			threadPane.innerHTML = `<div class="lex-drawer-head"><div><h2 style="font-size:14px;">Thread Replies</h2></div><button type="button" class="lex-close-x" data-close-thread>&times;</button></div><div class="lex-drawer-body">${empty("Loading thread...")}</div>`;
			threadPane.querySelector("[data-close-thread]").addEventListener("click", () => { threadPane.hidden = true; });
			const data = await call(`${msgApi}.get_thread`, { message_name: messageName, limit: 100 });
			const items = [data.root, ...(data.replies || [])].filter(Boolean);
			threadPane.innerHTML = `<div class="lex-drawer-head"><div><h2 style="font-size:14px;">Thread (${(data.replies || []).length} replies)</h2></div><button type="button" class="lex-close-x" data-close-thread>&times;</button></div>
				<div class="lex-drawer-body" style="gap:10px;" data-thread-list>
					${items.map((m, i) => `<article class="lex-card" style="padding:10px;${i === 0 ? "border-left:3px solid var(--lex-accent);" : ""}"><div style="display:flex;justify-content:space-between;font-size:11.5px;margin-bottom:4px;"><strong>${escapeHTML(m.sender_full_name)}</strong><span class="text-muted">${escapeHTML(m.formatted_timestamp || fmtDate(m.sent_at))}</span></div><div style="font-size:12.5px;">${m.message_text || ""}</div></article>`).join("")}
				</div>
				<form class="lex-chat-compose" style="border-top:1px solid var(--lex-border);" data-thread-form>
					<input class="form-control" name="reply" placeholder="Reply in thread..." required autocomplete="off" ${selected.can_post ? "" : "disabled"}>
					<button class="lex-button btn btn-primary btn-sm" type="submit" ${selected.can_post ? "" : "disabled"}>Reply</button>
				</form>`;
			threadPane.querySelector("[data-close-thread]").addEventListener("click", () => { threadPane.hidden = true; });
			threadPane.querySelector("[data-thread-form]")?.addEventListener("submit", async (e) => {
				e.preventDefault();
				const input = e.target.elements.reply;
				const txt = input.value.trim();
				if (!txt) return;
				await call(`${msgApi}.send_message`, { channel: selected.name, message_text: escapeHTML(txt).replace(/\n/g, "<br>"), thread_reference: data.root?.name || messageName, attachments: "[]" });
				openThread(messageName);
			});
		};

		messageBox.addEventListener("click", async (event) => {
			const jobLink = event.target.closest("[data-chat-job-ref]");
			if (jobLink) { event.preventDefault(); openJobDrawer(jobLink.dataset.chatJobRef); return; }
			const reactBtn = event.target.closest("[data-react-msg]");
			if (reactBtn) {
				const res = await call(`${msgApi}.toggle_reaction`, { message_name: reactBtn.dataset.reactMsg, emoji: reactBtn.dataset.reactEmoji }).catch((err) => showError("Reaction failed", err));
				if (res?.reactions) {
					const cardEl = messageBox.querySelector(`[data-message="${CSS.escape(reactBtn.dataset.reactMsg)}"]`);
					if (cardEl) updateReactionsDom(cardEl, reactBtn.dataset.reactMsg, res.reactions);
				}
				return;
			}
			const threadBtn = event.target.closest("[data-thread-msg]");
			if (threadBtn) { openThread(threadBtn.dataset.threadMsg); return; }
			const editBtn = event.target.closest("[data-edit-msg]");
			if (editBtn) {
				const msgEl = messageBox.querySelector(`[data-message="${CSS.escape(editBtn.dataset.editMsg)}"]`);
				const currentText = msgEl?.querySelector(".lex-message-content p")?.textContent || "";
				openModal({
					title: "Edit Message",
					bodyHtml: `<textarea id="lex-edit-msg-input" class="form-control" rows="3" required>${escapeHTML(currentText)}</textarea>`,
					confirmText: "Save Edit",
					onConfirm: async (modalHost) => {
						const next = modalHost.querySelector("#lex-edit-msg-input").value.trim();
						if (!next) throw new Error("Message cannot be empty.");
						const updated = await call(`${msgApi}.edit_message`, { message_name: editBtn.dataset.editMsg, message_text: escapeHTML(next).replace(/\n/g, "<br>") });
						appendOrUpdateMessage(updated, messageBox);
					},
				});
				return;
			}
			const delBtn = event.target.closest("[data-delete-msg]");
			if (delBtn) {
				openModal({
					title: "Delete Message",
					danger: true,
					bodyHtml: `<p>Delete this message from the conversation? Its audit record remains retained.</p>`,
					confirmText: "Delete",
					onConfirm: async () => {
						const updated = await call(`${msgApi}.delete_message`, { message_name: delBtn.dataset.deleteMsg });
						appendOrUpdateMessage(updated, messageBox);
					},
				});
			}
		});

		let initializingChannel = true;
		for (const button of channelBox.querySelectorAll("[data-channel]")) button.addEventListener("click", async () => {
			const generation = ++channelGeneration;
			realtimeUnsubscribe?.();
			realtimeUnsubscribe = null;
			if (subbar) { subbar.hidden = true; subbar.dataset.mode = ""; }
			if (threadPane) threadPane.hidden = true;
			typingUsers.clear();
			renderTypingBar();

			selected = channels.find((item) => item.name === button.dataset.channel);
			if (!selected) return;
			if (!initializingChannel) chat?.classList.add("is-conversation-open");
			channelBox.querySelectorAll("[data-channel]").forEach((item) => item.classList.remove("active"));
			button.classList.add("active");
			button.querySelector(".lex-nav-badge")?.remove();
			if (pinsBtn) pinsBtn.hidden = false;
			if (searchBtn) searchBtn.hidden = false;
			if (membersBtn) membersBtn.hidden = false;

			if (headerTitle) headerTitle.textContent = selected.matter_title || selected.display_name || selected.channel_name;
			if (headerSubtitle) {
				headerSubtitle.textContent = selected.is_matter_channel
					? [selected.matter_title, selected.organization_name].filter(Boolean).join(" / ")
					: selected.description || selected.reference_name || "Secure conversation";
			}
			const messages = await call(`${msgApi}.get_messages`, { channel: selected.name, limit: 100 });
			if (generation !== channelGeneration) return;
			renderMessages(messages, messageBox);
			const latestSequence = Math.max(0, ...messages.map((message) => Number(message.channel_sequence || 0)));
			if (window.lexocratesReliableChat) {
				realtimeUnsubscribe = window.lexocratesReliableChat.subscribe(selected.name, {
					afterSequence: latestSequence,
					onMessage: controller.onMessage,
				});
			} else {
				frappe.realtime?.emit("doc_subscribe", "Lexocrates Chat Channel", selected.name);
			}
			const jobPicker = form.elements.job_mention;
			const jobs = ["LPO Matter", "LPO Job"].includes(selected.reference_doctype)
				? await call(`${msgApi}.get_channel_jobs`, { channel: selected.name, limit: 100 }).catch(() => [])
				: [];
			if (generation !== channelGeneration) return;
			jobPicker.innerHTML = `<option value="">@ Job</option>${jobs.map((job) => `<option value="${escapeHTML(job.name)}">${escapeHTML(job.job_title || job.title || "Work item")}</option>`).join("")}`;
			jobPicker.disabled = !selected.can_post || !jobs.length;
			markVisibleRead(messages.at(-1)?.name);
			form.elements.message.disabled = !selected.can_post;
			form.querySelector("button").disabled = !selected.can_post;
		});

		form.elements.job_mention.addEventListener("change", (event) => {
			const job = event.currentTarget.value;
			if (!job) return;
			const input = form.elements.message;
			input.value = `${input.value}${input.value && !/\s$/.test(input.value) ? " " : ""}@${job} `;
			event.currentTarget.value = "";
			input.focus();
		});

		form.elements.message.addEventListener("input", () => {
			if (!selected) return;
			call(`${msgApi}.publish_typing`, { channel: selected.name, is_typing: 1 }).catch(() => {});
			window.clearTimeout(typingStopTimer);
			typingStopTimer = window.setTimeout(() => {
				if (selected) call(`${msgApi}.publish_typing`, { channel: selected.name, is_typing: 0 }).catch(() => {});
			}, 2500);
		});

		channelBox.querySelector("[data-channel]")?.click();
		initializingChannel = false;

		form.addEventListener("submit", async (event) => {
			event.preventDefault();
			const text = form.elements.message.value.trim();
			if (!selected || !text) return;
			const button = form.querySelector("button");
			button.disabled = true;
			const sendChannel = selected;
			try {
				const args = { channel: sendChannel.name, message_text: escapeHTML(text).replace(/\n/g, "<br>"), attachments: "[]" };
				const message = window.lexocratesReliableChat
					? await window.lexocratesReliableChat.send({ method: `${msgApi}.send_message`, args })
					: await call(`${msgApi}.send_message`, args);
				if (selected?.name === sendChannel.name) appendOrUpdateMessage(message, messageBox);
				form.reset();
			} catch (error) { showError("Message not sent", error); }
			finally { button.disabled = !selected.can_post; }
		});
	}

	function renderMessages(messages, box) {
		box.innerHTML = "";
		messages.forEach((message) => appendOrUpdateMessage(message, box));
		if (!messages.length) box.innerHTML = empty("No messages yet. Start the conversation.");
	}

	function updateReactionsDom(item, messageName, reactions) {
		const container = item.querySelector(".lex-msg-reactions");
		if (!container) return;
		const quickEmojis = ["👍", "✅", "👀", "📌"];
		const byEmoji = new Map((reactions || []).map((r) => [r.emoji, r]));
		const existingHtml = (reactions || []).map((r) => `<button type="button" class="lex-react-btn ${r.reacted_by_me ? "is-mine" : ""}" data-react-msg="${escapeHTML(messageName)}" data-react-emoji="${escapeHTML(r.emoji)}">${escapeHTML(r.emoji)} ${Number(r.count || 0)}</button>`).join("");
		const addHtml = quickEmojis.filter((e) => !byEmoji.has(e)).map((e) => `<button type="button" class="lex-msg-mini-btn" data-react-msg="${escapeHTML(messageName)}" data-react-emoji="${e}" title="React ${e}">${e}</button>`).join("");
		container.innerHTML = `${existingHtml}${addHtml}`;
	}

	function appendOrUpdateMessage(message, box) {
		if (!message?.name) return;
		const existing = box.querySelector(`[data-message="${CSS.escape(message.name)}"]`);
		const shouldStick = box.scrollHeight - box.scrollTop - box.clientHeight < 100;
		box.querySelector(".lex-empty")?.remove();

		const item = existing || document.createElement("article");
		item.className = `lex-message ${message.system_generated ? "system" : ""} ${message.sender === frappe.session.user ? "own" : ""}`;
		item.dataset.message = message.name;
		item.innerHTML = "";

		const avatar = document.createElement("div");
		avatar.className = "lex-message-avatar";
		avatar.textContent = message.system_generated ? "S" : initials(message.sender_full_name || message.sender);
		if (!message.system_generated) avatar.insertAdjacentHTML("beforeend", presenceDot(message.sender));

		const content = document.createElement("div");
		content.className = "lex-message-content";
		const meta = document.createElement("div");
		meta.className = "lex-message-meta";
		const author = document.createElement("strong");
		author.textContent = message.sender_full_name || message.sender || "System";
		const time = document.createElement("span");
		time.textContent = `${message.formatted_timestamp || fmtDate(message.sent_at)}${message.edited_on ? " (edited)" : ""}`;
		meta.append(author, time);

		const text = document.createElement("p");
		text.innerHTML = message.message_text || "";
		content.append(meta, text);

		if (message.job_mentions?.length) {
			const refs = document.createElement("div");
			refs.className = "lex-message-job-refs";
			refs.innerHTML = message.job_mentions.map((job) => `<a href="/client-portal#work-requests" data-chat-job-ref="${escapeHTML(job.name || "")}" title="${escapeHTML(job.title || "Work item")}">@${escapeHTML(job.title || "Work item")}<span>${escapeHTML(job.status || "")}</span></a>`).join("");
			content.appendChild(refs);
		}

		if (!message.is_deleted) {
			const actions = document.createElement("div");
			actions.className = "lex-msg-actions";
			const reactionsSpan = document.createElement("span");
			reactionsSpan.className = "lex-msg-reactions";
			reactionsSpan.style.display = "inline-flex";
			reactionsSpan.style.gap = "4px";
			actions.appendChild(reactionsSpan);

			const replyLabel = message.reply_count ? `Thread (${message.reply_count})` : "Reply";
			actions.insertAdjacentHTML("beforeend", `<button type="button" class="lex-msg-mini-btn" data-thread-msg="${escapeHTML(message.name)}">${escapeHTML(replyLabel)}</button>`);
			if (message.sender === frappe.session.user && !message.system_generated) {
				actions.insertAdjacentHTML("beforeend", `<button type="button" class="lex-msg-mini-btn" data-edit-msg="${escapeHTML(message.name)}">Edit</button><button type="button" class="lex-msg-mini-btn" data-delete-msg="${escapeHTML(message.name)}">Delete</button>`);
			}
			content.appendChild(actions);
			updateReactionsDom(content, message.name, message.reactions || []);
		}

		item.append(avatar, content);
		if (!existing) box.appendChild(item);
		if (!existing && shouldStick) box.scrollTop = box.scrollHeight;
	}
})();
