(() => {
	"use strict";

	const THEME_STORAGE_KEY = "lexocrates-portal-theme";
	const enforceLightTheme = () => {
		document.documentElement.setAttribute("data-theme", "light");
		document.documentElement.style.colorScheme = "light";
		try { localStorage.removeItem(THEME_STORAGE_KEY); } catch (_) { /* localStorage unavailable */ }
	};

	enforceLightTheme();
	new MutationObserver(() => {
		if (document.documentElement.getAttribute("data-theme") !== "light") enforceLightTheme();
	}).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

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
	const statusClass = (value) => String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
	const indicatorColor = (value) => {
		const status = String(value || "").toLowerCase();
		if (["active", "completed", "approved", "delivered", "paid"].includes(status)) return "green";
		if (["urgent", "changes requested", "overdue", "unpaid", "overdue"].includes(status)) return "red";
		if (["high", "ready for delivery", "pending", "draft", "on hold"].includes(status)) return "orange";
		return "blue";
	};
	const call = (method, args = {}) => frappe.call({ method, args }).then((response) => response.message);
	const presence = new Map();
	let currentPresenceUser = null;
	let presenceHeartbeatTimer = null;
	let lastPresenceActivity = Date.now();
	const presenceApi = "lex.lex.doctype.lexocrates_chat_presence.lexocrates_chat_presence";
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
	const initials = (name) => String(name || "L").split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
	const empty = (text) => `<div class="lex-empty">${escapeHTML(text)}</div>`;
	const presenceDot = (user) => {
		const item = presence.get(user) || { status: "Offline" };
		return `<span class="lex-presence-dot is-${statusClass(item.status || "Offline")}" data-presence-user="${escapeHTML(user || "")}" title="${escapeHTML(presenceSummary(item))}"></span>`;
	};
	const presenceSummary = (item) => {
		item = item || { status: "Offline" };
		if (item.status === "Online") return "Online";
		const timestamp = item.status === "Offline" ? item.last_seen_at : item.last_activity_at;
		return timestamp ? `${item.status} · ${item.status === "Offline" ? "Last seen" : "Active"} ${fmtDate(timestamp)}` : item.status;
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

	function bindLogout(button) {
		button?.addEventListener("click", async () => {
			button.disabled = true;
			button.textContent = "Signing out...";
			try {
				localStorage.removeItem("current_app");
				localStorage.removeItem("current_route");
				await frappe.call({ method: "logout" });
			} finally { window.location.assign("/login"); }
		});
	}

	function renderFailure(root, error) {
		root.setAttribute("aria-busy", "false");
		root.innerHTML = `<div class="lex-state-card" role="alert"><div class="lex-state-mark">!</div><h1>Client workspace unavailable</h1><p>${escapeHTML(errorMessage(error))}</p><button id="lex-portal-logout" class="lex-button btn btn-primary btn-sm" type="button">Log out and use another account</button></div>`;
		bindLogout(document.getElementById("lex-portal-logout"));
	}

	function icon(name) {
		// Self-contained line icons (no external sprite dependency).
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
		};
		return `<span class="lex-icon" aria-hidden="true"><svg viewBox="0 0 24 24">${paths[name] || paths.file}</svg></span>`;
	}

	function render(root, data) {
		root.setAttribute("aria-busy", "false");
		const clientId = data.client.custom_lexocrates_client_id || data.client.name;
		root.innerHTML = `<div class="lex-desk-shell" id="lex-app">
			<header class="lex-navbar navbar navbar-expand sticky-top" role="navigation">
				<div class="container">
					<a class="navbar-brand navbar-home" href="/client-portal" aria-label="Client Workspace home"><span class="lexocrates-brand-wordmark"><img class="app-logo lexocrates-logo-dark" src="/assets/lex/images/lexocrates-logo-dark.svg" alt="Lexocrates"><img class="app-logo lexocrates-logo-light" src="/assets/lex/images/lexocrates-logo-light.svg" alt=""></span></a>
					<ul class="nav navbar-nav lex-breadcrumbs d-none d-sm-flex"><li><a href="/client-portal">Client Workspace</a></li><li id="lex-navbar-page-title">Dashboard</li></ul>
					<div class="collapse navbar-collapse justify-content-end">
						<form id="lex-workspace-search" class="form-inline fill-width justify-content-end" role="search"><div class="input-group search-bar text-muted"><input name="query" type="search" class="form-control" placeholder="Search this workspace"><span class="search-icon">${icon("search")}</span></div></form>
						<ul class="navbar-nav">
							<li class="nav-item"><button class="btn-reset nav-link notifications-icon text-muted" type="button" data-go="messages" aria-label="Messages">${icon("message")}</button></li>
							<li class="vertical-bar d-none d-sm-block"></li>
							<li class="nav-item d-none d-md-block"><a class="nav-link" href="mailto:support@lexocrates.com">Help</a></li>
							<li class="nav-item dropdown lex-user-dropdown"><button class="btn-reset nav-link" type="button" data-user-menu-toggle aria-label="User menu"><span class="lex-presence-avatar"><span class="avatar avatar-medium" title="${escapeHTML(data.profile.full_name)}">${escapeHTML(initials(data.profile.full_name))}</span>${presenceDot(data.profile.email)}</span></button><div class="dropdown-menu dropdown-menu-right" data-user-menu><div class="lex-user-menu-head"><strong>${escapeHTML(data.profile.full_name)}</strong><span>${escapeHTML(data.profile.portal_role)}</span><small id="lex-current-presence">Offline</small></div><div class="dropdown-divider"></div><div class="lex-presence-menu"><label for="lex-presence-select">Availability</label><select id="lex-presence-select" class="form-control input-xs"><option value="Online">Online</option><option value="Away">Away</option><option value="Busy">Busy</option><option value="Offline">Offline</option></select></div><div class="dropdown-divider"></div><button class="dropdown-item" type="button" data-go="organization">Organization</button><button id="lex-portal-logout" class="dropdown-item" type="button">Log out</button></div></li>
						</ul>
					</div>
				</div>
			</header>
			<div class="lex-desk-body">
				<div class="lex-sidebar-overlay" data-close-sidebar></div>
				<aside id="lex-client-navigation" class="lex-sidebar desk-sidebar standard-sidebar" aria-label="Client workspace navigation">
					<div class="lex-sidebar-title"><button class="btn-reset" type="button" data-close-sidebar aria-label="Close navigation">${icon("menu")}</button><div><strong>Client Workspace</strong><span>${escapeHTML(data.client.customer_name)}</span></div></div>
					<nav class="lex-nav standard-sidebar-section"><div class="lex-nav-label standard-sidebar-label">Workspace</div>${data.navigation.map((item, index) => navItem(item, index, data)).join("")}</nav>
					<div class="lex-sidebar-footer"><span>${escapeHTML(clientId)}</span><small>Secure client access</small></div>
				</aside>
				<div class="lex-workspace">
					<header class="lex-topbar page-head"><div class="lex-topbar-inner page-head-content"><div class="lex-topbar-start"><button class="lex-mobile-menu btn btn-default btn-sm" type="button" data-open-sidebar aria-label="Open navigation" aria-controls="lex-client-navigation" aria-expanded="false">${icon("menu")}</button><div class="lex-page-heading"><h1 id="lex-page-title">Dashboard</h1><span>${escapeHTML(data.client.customer_name)}</span></div></div><div class="lex-topbar-end"><span class="indicator-pill blue no-indicator-dot">${escapeHTML(clientId)}</span></div></div></header>
					<div class="lex-content layout-main-section">
					${data.profile.mfa_required && !data.profile.mfa_enabled ? '<div class="lex-alert">Multi-factor authentication is required for this account. Contact Lexocrates support before handling sensitive work.</div>' : ''}
					${overviewSection(data)}${mattersSection(data)}${workIntakeSection(data)}${workRequestsSection(data)}${documentsSection(data)}${approvalsSection(data)}${reportsSection(data)}${messagesSection()}${billingSection(data)}${walletSection(data)}${usersSection(data)}${organizationSection(data)}
					</div>
				</div>
			</div>
		</div>`;
		bindLogout(document.getElementById("lex-portal-logout"));
		bindNavigation(root, data);
		bindNavbar(root, data);
		bindForms(root, data);
		setupPresence(data.profile.email);
	}

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

	function navItem(item, index, data) {
		const badge = item.section === "approvals" && data.metrics.approvals ? `<span class="lex-nav-badge">${data.metrics.approvals}</span>` : "";
		if (item.href) return `<a class="standard-sidebar-item" href="${escapeHTML(item.href)}">${icon(item.icon)}<span class="sidebar-item-label">${escapeHTML(item.label)}</span></a>`;
		return `<button type="button" data-section="${escapeHTML(item.section)}" data-title="${escapeHTML(item.label)}" class="standard-sidebar-item ${index === 0 ? "active selected" : ""}">${icon(item.icon)}<span class="sidebar-item-label">${escapeHTML(item.label)}</span>${badge}</button>`;
	}

	function sectionHeader(title, text, actions = "") {
		return `<div class="lex-section-header"><div><h2>${escapeHTML(title)}</h2><p>${escapeHTML(text)}</p></div>${actions ? `<div class="lex-section-actions">${actions}</div>` : ""}</div>`;
	}
	function card(title, note, body, className = "") {
		return `<article class="lex-card widget border ${className}"><div class="lex-card-head widget-head"><div class="widget-label"><h3 class="widget-title">${escapeHTML(title)}</h3><small>${escapeHTML(note)}</small></div></div>${body}</article>`;
	}
	function formCard(title, note, formId, body) {
		return `<article class="lex-form-shell std-form-layout"><div class="form-layout"><div class="form-page"><div class="form-section card-section visible-section"><div class="section-head">${escapeHTML(title)}</div><div class="form-section-description">${escapeHTML(note)}</div><div class="section-body"><form id="${escapeHTML(formId)}" class="lex-form">${body}</form></div></div></div></div></article>`;
	}
	function metric(label, value, note, iconName) {
		return `<article class="lex-metric widget number-widget-box"><div class="lex-metric-head"><span>${escapeHTML(label)}</span>${icon(iconName)}</div><strong>${escapeHTML(value)}</strong><small>${escapeHTML(note)}</small></article>`;
	}

	function overviewSection(data) {
		const progress = Math.round((data.onboarding.completed / data.onboarding.total) * 100);
		const quick = [
			data.permissions.can_create_matters ? ["new-matter", "Submit new work", "Start with details and SLA", "plus"] : null,
			data.permissions.can_create_matters ? ["work-requests", "Work status", "Monitor funded and activated jobs", "clipboard"] : null,
			["messages", "Secure messages", "Talk to the delivery team", "message"],
			["documents", "Documents", "Your uploads and completed deliverables", "file"],
		].filter(Boolean);
		return `<section class="lex-section active" data-panel="overview">
			<div class="lex-welcome"><div><p class="lex-eyebrow">Secure organization workspace</p><h2>Welcome, ${escapeHTML(data.profile.full_name)}</h2><p>Everything shown here is limited to ${escapeHTML(data.client.customer_name)} and your assigned permissions.</p></div><div class="lex-progress"><div class="lex-progress-meta"><span>Workspace setup</span><strong>${data.onboarding.completed}/${data.onboarding.total}</strong></div><div class="lex-progress-track"><span style="width:${progress}%"></span></div><div class="lex-progress-steps">${data.onboarding.steps.map((step) => `<button type="button" data-go="${escapeHTML(step.section)}" class="${step.complete ? "done" : ""}">${step.complete ? "✓" : "○"} ${escapeHTML(step.label)}</button>`).join("")}</div></div></div>
			<div class="lex-metrics">${metric("Active intakes", data.metrics.active_intakes, "Before Matter confirmation", "plus")}${metric("Open work", data.metrics.open_jobs, "Funded jobs in progress", "clipboard")}${metric("Pending approvals", data.metrics.approvals, "Your decisions required", "check")}${metric("Documents", data.metrics.documents, "Secure files available", "file")}</div>
			<div class="lex-grid"><div class="lex-stack">${card("Recent matters", "Permission-filtered", matterTable(data.matters.slice(0, 6)))}${card("Current work", "Latest authorized requests", jobTable(data.jobs.slice(0, 7)))}</div><div class="lex-stack">${card("Quick actions", "Common client tasks", `<div class="lex-card-body"><div class="lex-quick-actions">${quick.map(([section, title, note, iconName]) => `<button type="button" class="lex-action-tile" data-go="${section}">${icon(iconName)}<span><strong>${escapeHTML(title)}</strong><span>${escapeHTML(note)}</span></span></button>`).join("")}</div></div>`)}${walletCard(data)}${auditCard(data.audit_events)}</div></div>
		</section>`;
	}

	function matterTable(rows) {
		if (!rows.length) return empty("No authorized matters yet.");
		return `<div class="lex-table-wrap"><table class="lex-table table"><thead><tr><th>Matter</th><th>Practice area</th><th>Billing</th><th>Status</th><th>Target</th></tr></thead><tbody>${rows.map((row) => `<tr><td><strong>${escapeHTML(row.matter_title)}</strong><br><small>${escapeHTML(row.name)}</small></td><td>${escapeHTML(row.practice_area)}</td><td>${escapeHTML(row.billing_method)}</td><td><span class="lex-pill indicator-pill ${indicatorColor(row.status)} ${statusClass(row.status)}">${escapeHTML(row.status)}</span></td><td>${escapeHTML(fmtDate(row.end_date))}</td></tr>`).join("")}</tbody></table></div>`;
	}

	function jobTable(rows) {
		if (!rows.length) return empty("No current work requests.");
		return `<div class="lex-table-wrap"><table class="lex-table table"><thead><tr><th>Work item</th><th>Matter</th><th>Priority</th><th>Due</th><th>Status</th><th></th></tr></thead><tbody>${rows.map((row) => `<tr><td><strong>${escapeHTML(row.job_title)}</strong><br><small>${escapeHTML(row.name)}</small></td><td>${escapeHTML(row.engagement)}</td><td><span class="lex-pill indicator-pill ${indicatorColor(row.priority)} ${statusClass(row.priority)}">${escapeHTML(row.priority)}</span></td><td>${escapeHTML(fmtDate(row.due_date))}</td><td><span class="lex-pill indicator-pill ${indicatorColor(row.job_status)} ${statusClass(row.job_status)}">${escapeHTML(row.job_status)}</span></td><td>${row.delivery_download_url ? `<a class="lex-button secondary btn btn-default btn-sm" href="${escapeHTML(row.delivery_download_url)}" target="_blank" rel="noopener">Download deliverable</a>` : ""}</td></tr>`).join("")}</tbody></table></div>`;
	}

	function mattersSection(data) {
		if (!data.navigation.some((row) => row.section === "matters")) return "";
		return `<section class="lex-section" data-panel="matters">${sectionHeader("My Matters", "Legal matters you are authorized to access")}${card("Matter register", `${data.matters.length} authorized matters`, matterTable(data.matters))}</section>`;
	}

	function workIntakeSection(data) {
		if (!data.permissions.can_create_matters) return "";
		const services = ["Contract Review", "Legal Research", "Document Review", "Due Diligence", "Compliance Review", "Litigation Support", "Drafting", "Summarization", "Other"];
		const matterOptions = `<option value="">Create a new Matter</option>${(data.matters || []).filter((row) => !["On Hold", "Completed", "Closed"].includes(row.status)).map((row) => `<option value="${escapeHTML(row.name)}">${escapeHTML(row.matter_title)} · ${escapeHTML(row.name)}</option>`).join("")}`;
		const form = formCard("1. Matter context and preliminary work", "The Matter and a Draft Job are created now. No purchase is required until Job documents have been scanned and estimated.", "lex-new-intake", `
			<label class="wide">Matter<select name="matter" data-matter-select>${matterOptions}</select></label>
			<label class="wide" data-new-matter-field>Matter title<input name="matter_title" required maxlength="140" placeholder="Example: Acme vendor contracting programme"></label>
			<label data-new-matter-field>Matter nature<select name="matter_nature"><option>Advisory</option><option>Contract / Transaction</option><option>Litigation / Dispute</option><option>Regulatory / Compliance</option><option>Due Diligence</option><option>Other</option></select></label>
			<label data-new-matter-field>Represented party<input name="represented_party_name" placeholder="Client or entity represented"></label>
			<label data-new-matter-field>Represented party role<input name="our_side_role" placeholder="Buyer, petitioner, employer..."></label>
			<label data-new-matter-field>Counterparty / opposing party<input name="counterparty_name" placeholder="Second or adverse party"></label>
			<label data-new-matter-field>Counterparty role<input name="counterparty_role" placeholder="Seller, respondent, employee..."></label>
			<label class="wide" data-new-matter-field>Opposing counsel / law firm<input name="opposing_counsel" placeholder="If known"></label>
			<label class="wide">Job / work title<input name="intake_title" required maxlength="140" placeholder="Example: Review vendor master agreement"></label>
			<label>Service type<select name="service_type" required>${services.map((item) => `<option>${item}</option>`).join("")}</select></label>
			<label>Priority<select name="priority"><option>Low</option><option selected>Medium</option><option>High</option><option>Urgent</option></select></label>
			<label>Jurisdiction<input name="jurisdiction" required placeholder="India, Delhi High Court, UK law..."></label>
			<label>Requested delivery<input name="requested_delivery_date" type="datetime-local"></label>
			<label class="wide">Expected outcome<textarea name="expected_outcome" required placeholder="Describe the deliverable you need"></textarea></label>
			<label class="wide">Preliminary instructions<textarea name="preliminary_details" required placeholder="Do not upload documents yet. Add background, parties and initial instructions."></textarea></label>
			<label>Confidentiality<select name="confidentiality_level"><option>Standard</option><option selected>Confidential</option><option>Highly Confidential</option><option>Restricted</option></select></label>
			<div class="wide lex-button-row"><button class="lex-button btn btn-primary btn-sm" type="submit">Create Draft Job and review SLA</button><span class="lex-form-note text-muted">Documents attach only to the Draft Job. Funding activates operational work and starts its SLA.</span></div>`);
		const intakeCards = (data.intakes || []).map((intake) => intakeCard(intake, data)).join("");
		return `<section class="lex-section" data-panel="new-matter">${sectionHeader("Submit New Work", "Matter + Draft Job → SLA → Job documents → estimate → funding → Job activation")}${form}${intakeCards || card("Current intake", "No intake submitted", empty("Submit preliminary details to begin."))}</section>`;
	}

	function additionalJobDocuments(intake, docs) {
		return `<details class="lex-intake-action"><summary>Add or update Draft Job documents</summary><p class="text-muted">Any pre-funding change supersedes the previous estimate and creates a new version automatically.</p><form class="lex-form lex-intake-instructions" data-intake-instructions="${escapeHTML(intake.name)}"><label class="wide">Detailed instructions<textarea name="detailed_instructions" required>${escapeHTML(intake.detailed_instructions || "")}</textarea></label><div class="wide"><button class="lex-button secondary btn btn-default btn-sm" type="submit">Save and re-estimate</button></div></form><form class="lex-form lex-intake-upload" data-intake-upload="${escapeHTML(intake.name)}"><label class="wide">Job document<input class="lex-file-input" name="file" type="file" accept=".pdf,.doc,.docx,.txt,.csv,.png,.jpg,.jpeg" required></label><div class="wide"><button class="lex-button btn btn-primary btn-sm" type="submit">Upload, scan and estimate</button></div></form>${docs ? `<ul class="lex-intake-files">${docs}</ul>` : empty("No Job documents uploaded yet.")}</details>`;
	}

	function intakeCard(intake, data) {
		const docs = (intake.documents || []).map((row) => `<li><span><strong>${row.download_url ? `<a href="${escapeHTML(row.download_url)}" target="_blank" rel="noopener">${escapeHTML(row.file_name)}</a>` : escapeHTML(row.file_name)}</strong><small>${formatBytes(row.file_size)}</small></span><span class="indicator-pill ${indicatorColor(row.custom_lex_scan_status)} ${statusClass(row.custom_lex_scan_status)}">${escapeHTML(row.custom_lex_scan_status || "Pending")}</span></li>`).join("");
		let action = "";
		if (intake.status === "SLA Pending") {
			action = `<div class="lex-intake-action"><h4>2. Review and accept SLA Document</h4>${intake.sla_document_snapshot ? `<a class="lex-button secondary btn btn-default btn-sm" href="${escapeHTML(intake.sla_download_url || intake.sla_document_snapshot)}" target="_blank" rel="noopener">Download protected SLA PDF</a>` : ""}<div class="lex-sla-document">${escapeHTML(intake.sla_terms_snapshot).replace(/\n/g, "<br>")}</div><label class="lex-check"><input type="checkbox" data-sla-check="${escapeHTML(intake.name)}"> I reviewed SLA ${escapeHTML(intake.sla_version)} and agree to this exact snapshot (SHA-256 ${escapeHTML(intake.sla_snapshot_hash.slice(0, 12))}…).</label><button class="lex-button btn btn-primary btn-sm" type="button" data-accept-sla="${escapeHTML(intake.name)}">Accept SLA and unlock upload</button></div>`;
		} else if (["Documents Pending", "Security Review", "Analysis Pending"].includes(intake.status)) {
			action = `<div class="lex-intake-action"><h4>3. Add Job documents and detailed instructions</h4><p class="text-muted">Every Job document remains quarantined until its security scan is clean. Once documents and instructions are ready, the governed cost estimate runs automatically.</p></div>${additionalJobDocuments(intake, docs)}<p class="text-muted">Client access is limited to cost estimation. AI chat, legal analysis, prompts, models and internal AI output are not available in this workspace.</p>`;
		} else if (intake.status === "Operations Review") {
			action = `<div class="lex-intake-action lex-review-state"><h4>4. Cost estimate under review</h4><p>Legal Operations is validating scope, LexPoints, price and delivery before the estimate is released.</p></div>${additionalJobDocuments(intake, docs)}`;
		} else if (intake.status === "Pending CEO Approval") {
			action = `<div class="lex-intake-action lex-review-state"><h4>5. Awaiting internal pricing approval</h4><div class="lex-quote-summary"><span><small>Estimated price</small><strong>${escapeHTML(fmtMoney(intake.quoted_amount, intake.currency))}</strong></span><span><small>Required</small><strong>${fmtNumber(intake.required_lexpoints)} LexPoints</strong></span><span><small>Delivery</small><strong>${fmtNumber(intake.delivery_timeline_hours)} hours after funding</strong></span></div><p>This price is awaiting internal approval before payment opens. No action is needed from you — we'll notify you as soon as it's approved.</p></div>`;
		} else if (["Quote Ready", "Funding Pending"].includes(intake.status)) {
			action = fundingOptions(intake, data) + (intake.status === "Quote Ready" ? additionalJobDocuments(intake, docs) : "");
		} else if (["Funded", "Matter Confirmed"].includes(intake.status)) {
			action = `<div class="lex-intake-action lex-funded-state"><h4>Work funded and activated</h4><div class="lex-confirm-grid"><span><small>Funding</small><strong>${escapeHTML(intake.funding_route)}</strong></span><span><small>Matter</small><strong>${escapeHTML(intake.matter || "Confirming...")}</strong></span><span><small>Job</small><strong>${escapeHTML(intake.job || "Activating...")}</strong></span><span><small>SLA started</small><strong>${escapeHTML(fmtDate(intake.sla_started_on))}</strong></span><span><small>Delivery due</small><strong>${escapeHTML(fmtDate(intake.delivery_due_on))}</strong></span></div></div>`;
		}
		if (intake.status === "Pending CEO Approval") action += additionalJobDocuments(intake, docs);
		return `<article class="lex-card lex-intake-card"><div class="lex-card-head widget-head"><div><h3>${escapeHTML(intake.intake_title)}</h3><small>${escapeHTML(intake.matter || "Matter pending")} · ${escapeHTML(intake.job || "Draft Job pending")} · ${escapeHTML(intake.name)}</small></div><span class="indicator-pill ${indicatorColor(intake.status)} ${statusClass(intake.status)}">${escapeHTML(intake.status)}</span></div><div class="lex-intake-steps"><span class="${intake.matter ? "done" : ""}">Matter</span><span class="${intake.job ? "done" : ""}">Draft Job</span><span class="${intake.sla_accepted ? "done" : ""}">SLA</span><span class="${intake.document_count ? "done" : ""}">Documents</span><span class="${["Under Review", "Ready"].includes(intake.cost_estimate_status) ? "done" : ""}">Estimate</span><span class="${["Ready", "Accepted"].includes(intake.quote_status) ? "done" : ""}">Quote</span><span class="${intake.funding_status === "Funded" ? "done" : ""}">Funding</span><span class="${intake.status === "Matter Confirmed" ? "done" : ""}">Activated</span></div>${action}</article>`;
	}

	function fundingOptions(intake, data) {
		const enough = Number(intake.available_lexpoints || 0) >= Number(intake.required_lexpoints || 0);
		const plan = intake.recommended_plan_details;
		const paymentEnabled = Boolean(data.lexpack?.payment_enabled);
		let options = "";
		if (enough) {
			options = intake.can_fund_lexpoints ? `<button class="lex-button btn btn-primary btn-sm" type="button" data-fund-existing="${escapeHTML(intake.name)}">Reserve existing ${fmtNumber(intake.required_lexpoints)} LexPoints</button>` : '<span class="text-muted">LexPack funding authority is required.</span>';
		} else {
			const packAction = plan && intake.can_fund_lexpoints && paymentEnabled && plan.self_service ? `<button class="lex-button btn btn-primary btn-sm" type="button" data-buy-lexpack="${escapeHTML(plan.name)}" data-work-intake="${escapeHTML(intake.name)}">Buy Recommended LexPack · ${escapeHTML(plan.plan_name)}</button>` : `<button class="lex-button btn btn-primary btn-sm" type="button" disabled>${plan ? `Recommended: ${escapeHTML(plan.plan_name)}` : "Contact Legal Operations for capacity"}</button>`;
			const directAction = intake.can_pay_direct && paymentEnabled ? `<button class="lex-button secondary btn btn-default btn-sm" type="button" data-pay-direct="${escapeHTML(intake.name)}">Pay Fixed Quote Directly · ${escapeHTML(fmtMoney(intake.quoted_amount, intake.currency))}</button>` : '<button class="lex-button secondary btn btn-default btn-sm" type="button" disabled>Direct payment setup/authority required</button>';
			options = `<div class="lex-funding-choice"><article><strong>Option 1 · Buy Recommended LexPack</strong><p>Razorpay credits ${fmtNumber(plan?.lexpoints || 0)} LexPoints to your wallet, then reserves ${fmtNumber(intake.required_lexpoints)} for this work.</p>${packAction}</article><article><strong>Option 2 · Pay Fixed Quote Directly</strong><p>Razorpay pays only this quote. No LexPack or wallet credit is created.</p>${directAction}</article></div>`;
		}
		return `<div class="lex-intake-action"><h4>5. Confirm quote and funding</h4><div class="lex-quote-summary"><span><small>Fixed quote</small><strong>${escapeHTML(fmtMoney(intake.quoted_amount, intake.currency))}</strong></span><span><small>Required</small><strong>${fmtNumber(intake.required_lexpoints)} LexPoints</strong></span><span><small>Available</small><strong>${fmtNumber(intake.available_lexpoints)} LexPoints</strong></span><span><small>Delivery</small><strong>${fmtNumber(intake.delivery_timeline_hours)} hours after funding</strong></span></div><div class="lex-scope-box"><strong>Confirmed scope · quote v${fmtNumber(intake.quote_version)}</strong><p>${escapeHTML(intake.scope_summary)}</p><small>Valid until ${escapeHTML(fmtDate(intake.quote_valid_until))}</small></div>${options}${intake.failure_reason ? `<div class="lex-alert">${escapeHTML(intake.failure_reason)}</div>` : ""}</div>`;
	}

	function workRequestsSection(data) {
		if (!data.permissions.can_create_matters) return "";
		return `<section class="lex-section" data-panel="work-requests">${sectionHeader("Work Status", "Draft, funded and active Job work")}<article class="lex-commercial-note"><strong>New work always starts with Submit New Work.</strong><span>The Matter and Draft Job provide context first; secure Job documents, estimate and funding are required before operations begin.</span><button class="lex-button btn btn-primary btn-sm" type="button" data-go="new-matter">Submit new work</button></article>${card("Visible Jobs", `${data.jobs.length} visible items`, jobTable(data.jobs))}</section>`;
	}

	function documentsSection(data) {
		if (!data.navigation.some((row) => row.section === "documents")) return "";
		return `<section class="lex-section" data-panel="documents">${sectionHeader("Documents", "Client uploads and completed Job deliverables only")}<article class="lex-commercial-note"><strong>Controlled document access</strong><span>Upload source documents after SLA acceptance. The final deliverable unlocks only when the Job is Completed.</span><button class="lex-button secondary btn btn-default btn-sm" type="button" data-go="new-matter">Open Work Intake</button></article>${card("Document library", `${data.documents.length} files`, documentTable(data.documents))}</section>`;
	}

	function documentTable(rows) {
		if (!rows.length) return empty("No documents are available yet.");
		return `<div class="lex-table-wrap"><table class="lex-table table"><thead><tr><th>Document</th><th>Linked record</th><th>Size</th><th>Updated</th><th></th></tr></thead><tbody>${rows.map((row) => {
			const isPDF = String(row.file_name || row.file_url || "").toLowerCase().split("?")[0].endsWith(".pdf");
			const downloadURL = row.download_url || row.file_url;
			return `<tr><td><strong>${escapeHTML(row.file_name)}</strong><br><small>${escapeHTML(row.portal_document_type || "Client Upload")}${isPDF ? " · Personalized on download" : ""}</small></td><td>${escapeHTML(row.attached_to_name)}<br><small>${escapeHTML(row.attached_to_doctype)}</small></td><td>${formatBytes(row.file_size)}</td><td>${escapeHTML(fmtDate(row.modified))}</td><td><a class="lex-button secondary btn btn-default btn-sm" href="${escapeHTML(downloadURL)}" target="_blank" rel="noopener">${isPDF ? "Download protected copy" : "Download"}</a></td></tr>`;
		}).join("")}</tbody></table></div>`;
	}
	function formatBytes(bytes) { const value = Number(bytes || 0); return value > 1048576 ? `${(value / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(value / 1024))} KB`; }

	function approvalsSection(data) {
		if (!data.navigation.some((row) => row.section === "approvals")) return "";
		const body = data.approvals.length ? `<div class="lex-approval-list">${data.approvals.map((row) => `<article class="lex-approval frappe-card" data-approval="${escapeHTML(row.name)}"><div class="lex-approval-head"><div><h3>${escapeHTML(row.job_title)}</h3><p>${escapeHTML(row.name)} · ${escapeHTML(row.engagement)}</p></div><span class="lex-pill indicator-pill orange ready-for-delivery">Ready for Delivery</span></div><p class="text-muted">Review the personalized protected preview before recording your decision. Approval completes the Job and unlocks the final document library copy.</p>${row.delivery_preview_url ? `<a class="lex-button secondary btn btn-default btn-sm" href="${escapeHTML(row.delivery_preview_url)}" target="_blank" rel="noopener">Review protected preview</a>` : `<div class="lex-alert">Preview is unavailable. Ask Legal Operations to regenerate the delivery document.</div>`}<textarea class="form-control" data-approval-notes placeholder="Decision notes (required when requesting changes)"></textarea><div class="lex-button-row"><button class="lex-button btn btn-primary btn-sm" type="button" data-decision="Approved">Approve and complete</button><button class="lex-button danger btn btn-danger btn-sm" type="button" data-decision="Changes Requested">Request changes</button></div></article>`).join("")}</div>` : empty("No deliverables are waiting for your approval.");
		return `<section class="lex-section" data-panel="approvals">${sectionHeader("Approvals", "Review delivery-ready work and record an auditable decision")}${body}</section>`;
	}

	function reportsSection(data) {
		if (!data.navigation.some((row) => row.section === "reports")) return "";
		const reports = data.reports.length ? `<div class="lex-report-grid">${data.reports.map((row) => `<article class="lex-report frappe-card"><h3>${escapeHTML(row.name)}</h3><p>${escapeHTML(row.description)}</p><button class="lex-button secondary btn btn-default btn-sm" type="button" data-report="${escapeHTML(row.name)}">Download CSV</button></article>`).join("")}</div>` : empty("No reports are enabled for your role.");
		return `<section class="lex-section" data-panel="reports">${sectionHeader("Reports", `Access scope: ${data.permissions.report_access || "None"}`)}${reports}</section>`;
	}

	function messagesSection() {
		return `<section class="lex-section" data-panel="messages">${sectionHeader("Secure Messages", "Real-time, contextual and auditable communication")}<article class="lex-card widget border"><div class="lex-chat"><div id="lex-chat-channels" class="lex-chat-sidebar">${empty("Loading Matter conversations...")}</div><div class="lex-chat-main"><div id="lex-chat-header" class="lex-chat-header"><strong>Choose a Matter conversation</strong><span>Your Matter rooms and approved conversations</span></div><div id="lex-chat-messages" class="lex-chat-messages" role="log" aria-live="polite" tabindex="0" aria-label="Conversation history">${empty("Choose a Matter room to view messages.")}</div><form id="lex-chat-compose" class="lex-chat-compose"><select class="form-control lex-chat-job-picker" name="job_mention" aria-label="Mention a related Job" disabled><option value="">@ Job</option></select><input class="form-control" name="message" maxlength="10000" placeholder="Write a secure message" autocomplete="off" disabled><button class="lex-button btn btn-primary btn-sm" type="submit" disabled>Send</button></form></div></div></article></section>`;
	}

	function billingSection(data) {
		if (!data.permissions.billing_access) return "";
		const rows = data.invoices.length ? `<div class="lex-table-wrap"><table class="lex-table table"><thead><tr><th>Invoice</th><th>Posting date</th><th>Due date</th><th>Status</th><th>Total</th><th>Outstanding</th></tr></thead><tbody>${data.invoices.map((row) => `<tr><td><strong>${escapeHTML(row.name)}</strong></td><td>${escapeHTML(fmtDate(row.posting_date))}</td><td>${escapeHTML(fmtDate(row.due_date))}</td><td><span class="lex-pill indicator-pill ${indicatorColor(row.status)} ${statusClass(row.status)}">${escapeHTML(row.status)}</span></td><td>${escapeHTML(fmtMoney(row.grand_total, row.currency))}</td><td>${escapeHTML(fmtMoney(row.outstanding_amount, row.currency))}</td></tr>`).join("")}</tbody></table></div>` : empty("No invoices are available for this organization.");
		return `<section class="lex-section" data-panel="billing">${sectionHeader("Billing", "Organization invoices and outstanding balances")}${card("Invoices", "Financial access required", rows)}</section>`;
	}

	function walletCard(data) {
		if (!data.wallet) return card("LexPack", "Role protected", empty("LexPack balance is not available for your role."));
		return `<article class="lex-card"><div class="lex-wallet"><span class="lex-wallet-label">Available balance · never expires</span><div class="lex-wallet-balance">${fmtNumber(data.wallet.current_balance)} <small>LexPoints</small></div><div class="lex-wallet-meta"><span>${fmtNumber(data.wallet.reserved_balance)} reserved</span><span>${fmtNumber(data.wallet.total_consumed)} consumed</span><span>${fmtNumber(data.wallet.bonus_points_earned)} bonus earned</span></div><div class="lex-wallet-tier"><span><small>Current tier</small><strong>${escapeHTML(data.wallet.current_pricing_tier || "Not qualified")}</strong></span><span><small>Rolling 12-month spend</small><strong>${escapeHTML(fmtMoney(data.wallet.rolling_12_month_spend, "USD"))}</strong></span></div></div></article>`;
	}
	function walletSection(data) {
		if (!data.wallet) return "";
		const lexpack = data.lexpack || { plans: [], purchases: [], payment_enabled: false, purchase_access: false };
		const planCards = lexpack.plans.map((plan) => {
			const price = plan.enterprise_custom ? "Custom" : fmtMoney(plan.price, plan.currency);
			const points = plan.enterprise_custom ? "Custom LexPoints" : `${fmtNumber(plan.lexpoints)} LexPoints`;
			let action = '<a class="lex-button secondary btn btn-default btn-sm" href="mailto:sales@lexocrates.com?subject=LexPack%20Enterprise">Contact sales</a>';
			if (!plan.enterprise_custom) action = '<button class="lex-button secondary btn btn-default btn-sm" type="button" data-go="new-matter">Available after your work quote</button>';
			return `<article class="lex-plan-card frappe-card ${plan.plan_code === "PROFESSIONAL" ? "recommended" : ""}"><div class="lex-plan-top"><div><span class="lex-plan-code">${escapeHTML(plan.plan_code)}</span><h3>${escapeHTML(plan.plan_name)}</h3></div><span class="lex-plan-advantage">${escapeHTML(plan.value_advantage)}</span></div><div class="lex-plan-price">${escapeHTML(price)}</div><div class="lex-plan-points">${escapeHTML(points)}</div><ul><li>One client-owned wallet</li><li>All practice areas</li><li>No expiry</li><li>Rolling fair-pricing qualification</li></ul><div class="lex-plan-action">${action}</div></article>`;
		}).join("");
		const ledger = data.transactions.length ? `<div class="lex-table-wrap"><table class="lex-table table"><thead><tr><th>Transaction</th><th>Points</th><th>Matter</th><th>Balance</th><th>Date</th></tr></thead><tbody>${data.transactions.map((row) => `<tr><td>${escapeHTML(row.transaction_type)}</td><td>${fmtNumber(row.points)}</td><td>${escapeHTML(row.matter || "—")}</td><td>${fmtNumber(row.available_balance_after)}</td><td>${escapeHTML(fmtDate(row.posted_on))}</td></tr>`).join("")}</tbody></table></div>` : empty("No LexPoint transactions yet.");
		const purchaseHistory = lexpack.purchases.length ? `<div class="lex-table-wrap"><table class="lex-table table"><thead><tr><th>Purchase</th><th>Plan</th><th>Status</th><th>Amount</th><th>LexPoints</th><th>Paid on</th><th>Invoice</th></tr></thead><tbody>${lexpack.purchases.map((row) => `<tr><td><strong>${escapeHTML(row.name)}</strong></td><td>${escapeHTML(row.plan_name_snapshot)}</td><td><span class="indicator-pill ${indicatorColor(row.status)} ${statusClass(row.status)}">${escapeHTML(row.status)}</span></td><td>${escapeHTML(fmtMoney(row.amount, row.currency))}</td><td>${fmtNumber(row.total_lexpoints)}</td><td>${escapeHTML(fmtDate(row.paid_on))}</td><td>${escapeHTML(row.sales_invoice || "—")}</td></tr>`).join("")}</tbody></table></div>` : empty("No LexPack purchases yet.");
		return `<section class="lex-section" data-panel="wallet">${sectionHeader("LexPack", "Prepaid legal capacity — not a subscription and not hourly billing")}${walletCard(data)}<div class="lex-commercial-note"><strong>No upfront purchase during onboarding.</strong><span>Submit preliminary details, accept the SLA and upload documents first. The confirmed quote then offers the recommended LexPack or direct fixed-quote payment. Existing sufficient balance is reserved automatically when you choose it.</span><small>${escapeHTML(lexpack.fair_pricing_note || "")}</small></div>${card("LexPack bundles", "Shown for transparency; recommendation is calculated from your quote", `<div class="lex-plan-grid">${planCards || empty("No active LexPack plans.")}</div>`)}${card("Purchase history", `${lexpack.purchases.length} purchases`, purchaseHistory)}${card("LexPoint ledger", `${data.transactions.length} transactions`, ledger)}</section>`;
	}
	function auditCard(rows) {
		const body = rows.length ? `<div class="lex-card-body"><ol class="lex-audit">${rows.slice(0, 8).map((row) => `<li><strong>${escapeHTML(row.action)}</strong><span>${escapeHTML(fmtDate(row.event_timestamp))} · ${escapeHTML(row.user || "System")}</span></li>`).join("")}</ol></div>` : empty("No portal activity yet.");
		return card("Organization activity", "Protected audit trail", body);
	}

	function usersSection(data) {
		if (!data.permissions.user_management_authority) return "";
		const roles = ["Client Administrator", "Partner / General Counsel", "Legal User", "Operations User", "Finance User", "Procurement User", "Compliance User", "Read-Only User"];
		const roleOptions = roles.map((role) => `<option>${escapeHTML(role)}</option>`).join("");
		const userOptions = data.portal_users.map((row) => `<option value="${escapeHTML(row.name)}">${escapeHTML(row.full_name)} · ${escapeHTML(row.portal_role)}</option>`).join("");
		const matterOptions = data.matters.map((row) => `<option value="${escapeHTML(row.name)}">${escapeHTML(row.matter_title)}</option>`).join("");
		const table = data.portal_users.length ? `<div class="lex-table-wrap"><table class="lex-table table"><thead><tr><th>User</th><th>Role</th><th>Status</th><th>Last login</th><th></th></tr></thead><tbody>${data.portal_users.map((row) => `<tr><td><strong>${escapeHTML(row.full_name)}</strong><br><small>${escapeHTML(row.email)}</small></td><td>${escapeHTML(row.portal_role)}</td><td><span class="lex-pill indicator-pill ${indicatorColor(row.account_status)} ${statusClass(row.account_status)}">${escapeHTML(row.account_status)}</span></td><td>${escapeHTML(fmtDate(row.last_login))}</td><td>${row.account_status === "Active" && row.email !== data.profile.email ? `<button type="button" class="lex-button danger btn btn-danger btn-sm" data-disable-user="${escapeHTML(row.name)}">Disable</button>` : ""}</td></tr>`).join("")}</tbody></table></div>` : empty("No portal users.");
		return `<section class="lex-section" data-panel="users">${sectionHeader("Team & Access", "Manage client Website Users without granting Desk access")}${card("Portal users", `${data.portal_users.length} organization users`, table)}
			<article class="lex-card"><div class="lex-card-head"><div><h3>Invite client user</h3><small>Secure activation link expires in 72 hours</small></div></div><div class="lex-card-body"><form id="lex-invite-user" class="lex-form"><label>Full name<input name="invitee_name" required></label><label>Email<input name="invitee_email" type="email" required></label><label>Designation<input name="designation"></label><label>Portal role<select name="portal_role">${roleOptions}</select></label><label class="wide lex-check"><input name="mfa_required" type="checkbox" value="1"> Require multi-factor authentication</label><div class="wide"><button class="lex-button" type="submit">Send invitation</button></div></form></div></article>
			<article class="lex-card"><div class="lex-card-head"><div><h3>Function permissions</h3><small>Legal, financial and administrative controls</small></div></div><div class="lex-card-body"><form id="lex-user-permissions" class="lex-form"><label class="wide">Portal user<select name="portal_user" required>${userOptions}</select></label><label>Portal role<select name="portal_role">${roleOptions}</select></label><label>Matter scope<select name="matter_access_scope"><option>Assigned Matters</option><option>All Client Matters</option><option>No Matter Access</option></select></label><label>Approval authority<select name="approval_authority"><option>None</option><option>Matter Approval</option><option>Deliverable Approval</option><option>Commercial Approval</option><option>All Client Approvals</option></select></label><label>Report access<select name="report_access"><option>None</option><option>Matter Reports</option><option>Financial Reports</option><option>Compliance Reports</option><option>All Client Reports</option></select></label><div class="wide lex-check-grid">${["can_create_matters:Create matters", "can_upload_documents:Upload documents", "can_comment:Comment", "billing_access:Billing", "lexpack_view_access:View LexPack", "lexpack_purchase_access:Purchase LexPack", "user_management_authority:Manage users", "mfa_required:Require MFA"].map((item) => { const [name, label] = item.split(":"); return `<label class="lex-check"><input name="${name}" type="checkbox" value="1"> ${label}</label>`; }).join("")}</div><div class="wide"><button class="lex-button" type="submit">Update permissions</button></div></form></div></article>
			${data.matters.length ? `<article class="lex-card"><div class="lex-card-head"><div><h3>Matter authorization</h3><small>Per-matter access and actions</small></div></div><div class="lex-card-body"><form id="lex-matter-access" class="lex-form"><label>Matter<select name="matter">${matterOptions}</select></label><label>Portal user<select name="portal_user">${userOptions}</select></label><div class="wide lex-check-grid">${["can_view:View", "can_upload:Upload", "can_comment:Comment", "can_approve:Approve", "can_view_billing:View billing"].map((item) => { const [name, label] = item.split(":"); return `<label class="lex-check"><input name="${name}" type="checkbox" value="1" ${name === "can_view" ? "checked" : ""}> ${label}</label>`; }).join("")}</div><div class="wide"><button class="lex-button" type="submit">Save matter access</button></div></form></div></article>` : ""}
		</section>`;
	}

	function organizationSection(data) {
		if (!data.permissions.user_management_authority) return "";
		return `<section class="lex-section" data-panel="organization">${sectionHeader("Organization", "Read-only client identity and portal security context")}${card("Client profile", "Maintained by Lexocrates", `<div class="lex-card-body"><div class="lex-form"><label>Client ID<input readonly value="${escapeHTML(data.client.custom_lexocrates_client_id || data.client.name)}"></label><label>Organization type<input readonly value="${escapeHTML(data.client.custom_organization_type || "—")}"></label><label>Default currency<input readonly value="${escapeHTML(data.client.default_currency || "INR")}"></label><label>Primary jurisdiction<input readonly value="${escapeHTML(data.client.custom_primary_jurisdiction || "—")}"></label></div></div>`)}</section>`;
	}

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
			root.querySelectorAll("[data-section]").forEach((item) => { const active = item.dataset.section === section; item.classList.toggle("active", active); item.classList.toggle("selected", active); });
			root.querySelectorAll("[data-panel]").forEach((item) => item.classList.toggle("active", item.dataset.panel === section));
			const title = titleBySection[section] || "Dashboard";
			document.getElementById("lex-page-title").textContent = title;
			document.getElementById("lex-navbar-page-title").textContent = title;
			setSidebarOpen(false);
			if (section === "messages") loadChat();
			window.scrollTo({ top: 0, behavior: "smooth" });
		};
		root.querySelectorAll("[data-section]").forEach((button) => button.addEventListener("click", () => { window.location.hash = button.dataset.section; activate(button.dataset.section); }));
		root.querySelectorAll("[data-go]").forEach((button) => button.addEventListener("click", () => { window.location.hash = button.dataset.go; activate(button.dataset.go); }));
		menuButton?.addEventListener("click", () => setSidebarOpen(true));
		root.querySelectorAll("[data-close-sidebar]").forEach((button) => button.addEventListener("click", () => setSidebarOpen(false)));
		document.addEventListener("keydown", (event) => {
			if (event.key === "Escape") setSidebarOpen(false);
		});
		window.addEventListener("resize", () => {
			if (window.innerWidth >= 1080) setSidebarOpen(false);
		}, { passive: true });
		window.addEventListener("hashchange", () => activate(window.location.hash.slice(1)), { passive: true });
		activate(window.location.hash.slice(1) || "overview");
	}

	function bindNavbar(root, data) {
		const menu = root.querySelector('[data-user-menu]');
		const menuToggle = root.querySelector('[data-user-menu-toggle]');
		menuToggle?.setAttribute('aria-expanded', 'false');
		menuToggle?.addEventListener('click', (event) => {
			event.stopPropagation();
			const open = !menu?.classList.contains('show');
			menu?.classList.toggle('show', open);
			menuToggle.setAttribute('aria-expanded', String(open));
		});
		document.addEventListener('click', (event) => {
			if (!event.target.closest('.lex-user-dropdown')) {
				menu?.classList.remove('show');
				menuToggle?.setAttribute('aria-expanded', 'false');
			}
		});
		const search = document.getElementById('lex-workspace-search');
		search?.addEventListener('submit', (event) => {
			event.preventDefault();
			const query = search.elements.query.value.trim().toLowerCase();
			if (!query) return;
			const navMatch = data.navigation.find((item) => item.section && item.label.toLowerCase().includes(query));
			const matterMatch = data.matters.some((row) => `${row.name} ${row.matter_title}`.toLowerCase().includes(query));
			const jobMatch = data.jobs.some((row) => `${row.name} ${row.job_title}`.toLowerCase().includes(query));
			const section = navMatch?.section || (matterMatch ? 'matters' : jobMatch ? 'work-requests' : null);
			if (section) { window.location.hash = section; root.querySelector(`[data-section="${CSS.escape(section)}"]`)?.click(); search.reset(); }
			else notify('No matching workspace item', 'orange');
		});
	}

	function formValues(form, checks = []) {
		const values = Object.fromEntries(new FormData(form));
		for (const name of checks) values[name] = form.elements[name]?.checked ? 1 : 0;
		return values;
	}

	function bindForms(root, data) {
		const matterSelect = root.querySelector("[data-matter-select]");
		const toggleMatterFields = () => {
			const existing = Boolean(matterSelect?.value);
			root.querySelectorAll("[data-new-matter-field]").forEach((field) => { field.hidden = existing; });
			const title = root.querySelector('[name="matter_title"]');
			if (title) title.required = !existing;
		};
		matterSelect?.addEventListener("change", toggleMatterFields);
		toggleMatterFields();
		bindSubmit("lex-new-intake", "lex.work_intake.create_work_intake", "Matter and Draft Job created", "Could not start work");
		root.querySelectorAll("[data-accept-sla]").forEach((button) => button.addEventListener("click", async () => {
			const intake = button.dataset.acceptSla;
			const checked = root.querySelector(`[data-sla-check="${CSS.escape(intake)}"]`)?.checked;
			if (!checked) return showError("SLA acceptance required", "Review the SLA Document and select the acceptance checkbox.");
			button.disabled = true;
			try { await call("lex.work_intake.accept_sla", { intake, accepted: 1 }); notify("SLA accepted. Secure upload is now unlocked."); reloadSection("new-matter"); }
			catch (error) { showError("SLA acceptance failed", error); button.disabled = false; }
		}));
		root.querySelectorAll("[data-intake-upload]").forEach((upload) => upload.addEventListener("submit", async (event) => {
			event.preventDefault();
			const button = upload.querySelector("button[type=submit]");
			const file = upload.elements.file.files[0];
			if (!file) return;
			if (file.size > 10 * 1024 * 1024) return showError("Upload failed", "File must be 10 MB or smaller.");
			button.disabled = true;
			try {
				const content = await readFile(file);
				const response = await call("lex.work_intake.upload_document", { intake: upload.dataset.intakeUpload, filename: file.name, content });
				if (response.estimate) notify("Document scanned and Job cost estimate updated");
				else if (response.quarantine_passed) notify("Document passed security scanning. Add detailed instructions to run the estimate.");
				else notify(`Document remains quarantined: ${response.scan_status}`, "orange");
				reloadSection("new-matter");
			} catch (error) { showError("Upload failed", error); button.disabled = false; }
		}));
		root.querySelectorAll("[data-intake-instructions]").forEach((form) => form.addEventListener("submit", async (event) => {
			event.preventDefault();
			const button = form.querySelector("button[type=submit]");
			button.disabled = true;
			try {
				const response = await call("lex.work_intake.save_detailed_instructions", {
					intake: form.dataset.intakeInstructions,
					detailed_instructions: form.elements.detailed_instructions.value,
				});
				notify(response.cost_estimate_status ? "Instructions saved and Job cost estimate updated" : "Detailed instructions saved");
				reloadSection("new-matter");
			} catch (error) { showError("Instructions could not be saved", error); button.disabled = false; }
		}));
		root.querySelectorAll("[data-analyze-intake]").forEach((button) => button.addEventListener("click", async () => {
			button.disabled = true; button.textContent = "Estimating...";
			try {
				const result = await call("lex.work_intake.request_cost_estimate", { intake: button.dataset.analyzeIntake });
				const message = result.status === "Operations Review"
					? "Cost estimate sent to Legal Operations review"
					: result.status === "Quote Ready"
						? "AI estimate approved by policy. Funding options are ready."
						: "Cost estimate submitted for approval";
				notify(message, result.status === "Operations Review" ? "orange" : "green");
				reloadSection("new-matter");
			} catch (error) { showError("Cost estimate could not start", error); button.disabled = false; button.textContent = "Request cost estimate"; }
		}));
		root.querySelectorAll("[data-fund-existing]").forEach((button) => button.addEventListener("click", async () => {
			if (!window.confirm("Reserve the quoted LexPoints and activate this Matter and Job?")) return;
			button.disabled = true; button.textContent = "Reserving and activating...";
			try { const result = await call("lex.work_intake.fund_with_existing_lexpoints", { intake: button.dataset.fundExisting }); notify(`Activated ${result.matter} / ${result.job}`); reloadSection("new-matter"); }
			catch (error) { showError("Funding failed", error); button.disabled = false; button.textContent = "Reserve existing LexPoints"; }
		}));

		root.querySelectorAll("[data-approval]").forEach((card) => card.querySelectorAll("[data-decision]").forEach((button) => button.addEventListener("click", async () => {
			const notes = card.querySelector("[data-approval-notes]").value.trim(); const decision = button.dataset.decision;
			if (decision === "Changes Requested" && !notes) return showError("Notes required", "Explain the changes required before submitting.");
			card.querySelectorAll("button").forEach((item) => { item.disabled = true; });
			try { await call("lex.client_portal.submit_client_approval", { job: card.dataset.approval, decision, notes }); notify(`Decision recorded: ${decision}`); card.remove(); }
			catch (error) { showError("Approval failed", error); card.querySelectorAll("button").forEach((item) => { item.disabled = false; }); }
		})));

		root.querySelectorAll("[data-report]").forEach((button) => button.addEventListener("click", async () => {
			button.disabled = true;
			try { const report = await call("lex.client_portal.generate_portal_report", { report_name: button.dataset.report }); downloadCSV(report); notify("Report downloaded"); }
			catch (error) { showError("Report unavailable", error); }
			finally { button.disabled = false; }
		}));
		root.querySelectorAll("[data-buy-lexpack]").forEach((button) => button.addEventListener("click", () => buyLexPack(button)));
		root.querySelectorAll("[data-pay-direct]").forEach((button) => button.addEventListener("click", () => payDirectQuote(button)));
		bindAdministration(data);
	}

	function reloadSection(section) {
		setTimeout(() => window.location.assign(`/client-portal?refresh=${Date.now()}#${encodeURIComponent(section)}`), 650);
	}

	let razorpayLoader = null;
	function loadRazorpayCheckout() {
		if (window.Razorpay) return Promise.resolve(window.Razorpay);
		if (razorpayLoader) return razorpayLoader;
		razorpayLoader = new Promise((resolve, reject) => {
			const script = document.createElement("script");
			script.src = "https://checkout.razorpay.com/v1/checkout.js";
			script.async = true;
			script.onload = () => window.Razorpay ? resolve(window.Razorpay) : reject(new Error("Razorpay Checkout did not initialize."));
			script.onerror = () => reject(new Error("Razorpay Checkout could not be loaded."));
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
			const order = await call("lex.lexpack.create_razorpay_order", { plan: button.dataset.buyLexpack, work_intake: button.dataset.workIntake });
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
						notify(result.status === "Paid" ? `${fmtNumber(result.total_lexpoints)} LexPoints credited` : result.message, result.status === "Paid" ? "green" : "orange");
						reloadSection("new-matter");
					} catch (error) {
						showError("Payment verification failed", error);
						button.disabled = false;
						button.textContent = original;
					}
				},
				modal: { ondismiss: () => { button.disabled = false; button.textContent = original; } },
				retry: { enabled: true, max_count: 2 },
			});
			checkout.on("payment.failed", (response) => showError("Payment failed", response.error?.description || "Razorpay could not complete the payment."));
			checkout.open();
		} catch (error) {
			showError("Payment unavailable", error);
			button.disabled = false;
			button.textContent = original;
		}
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
			checkout.on("payment.failed", (response) => showError("Payment failed", response.error?.description || "Razorpay could not complete the payment."));
			checkout.open();
		} catch (error) { showError("Direct payment unavailable", error); button.disabled = false; button.textContent = original; }
	}

	function bindSubmit(formId, method, success, failure) {
		const form = document.getElementById(formId); if (!form) return;
		form.addEventListener("submit", async (event) => {
			event.preventDefault(); const button = form.querySelector("button[type=submit]"); button.disabled = true;
			try { const result = await call(method, Object.fromEntries(new FormData(form))); notify(`${success}: ${result.name}`); const section = String(result.route || "").split("#")[1] || "overview"; window.location.assign(`/client-portal?refresh=${Date.now()}#${encodeURIComponent(section)}`); }
			catch (error) { showError(failure, error); }
			finally { button.disabled = false; }
		});
	}

	function bindAdministration(data) {
		const invite = document.getElementById("lex-invite-user");
		invite?.addEventListener("submit", async (event) => { event.preventDefault(); const button = invite.querySelector("button"); button.disabled = true; try { await call("lex.portal_management.invite_portal_user", formValues(invite, ["mfa_required"])); notify("Invitation sent"); setTimeout(() => window.location.reload(), 500); } catch (error) { showError("Invitation failed", error); } finally { button.disabled = false; } });
		const permissions = document.getElementById("lex-user-permissions");
		const checks = ["can_create_matters", "can_upload_documents", "can_comment", "billing_access", "lexpack_view_access", "lexpack_purchase_access", "user_management_authority", "mfa_required"];
		const populate = () => { if (!permissions) return; const row = data.portal_users.find((item) => item.name === permissions.elements.portal_user.value); if (!row) return; for (const name of ["portal_role", "matter_access_scope", "approval_authority", "report_access"]) permissions.elements[name].value = row[name] || "None"; for (const name of checks) permissions.elements[name].checked = Boolean(row[name]); };
		permissions?.elements.portal_user.addEventListener("change", populate); populate();
		permissions?.addEventListener("submit", async (event) => { event.preventDefault(); const values = formValues(permissions, checks); const portalUser = values.portal_user; delete values.portal_user; try { await call("lex.portal_management.update_portal_user_permissions", { portal_user: portalUser, values }); notify("Permissions updated"); setTimeout(() => window.location.reload(), 500); } catch (error) { showError("Update failed", error); } });
		const matterAccess = document.getElementById("lex-matter-access");
		matterAccess?.addEventListener("submit", async (event) => { event.preventDefault(); try { await call("lex.portal_management.set_matter_authorization", formValues(matterAccess, ["can_view", "can_upload", "can_comment", "can_approve", "can_view_billing"])); notify("Matter access updated"); } catch (error) { showError("Authorization failed", error); } });
		document.querySelectorAll("[data-disable-user]").forEach((button) => button.addEventListener("click", async () => { const reason = window.prompt("Reason for disabling this client user:"); if (!reason) return; try { await call("lex.portal_management.deactivate_portal_user", { portal_user: button.dataset.disableUser, reason }); window.location.reload(); } catch (error) { showError("Deactivation failed", error); } }));
	}

	const readFile = (file) => new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(file); });
	function downloadCSV(report) {
		const quote = (value) => `"${String(value ?? "").replace(/"/g, '""')}"`;
		const rows = [report.columns.map(quote).join(","), ...report.rows.map((row) => report.columns.map((column) => quote(row[column])).join(","))];
		const blob = new Blob(["\ufeff", rows.join("\r\n")], { type: "text/csv;charset=utf-8" });
		const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = `${report.name.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}.csv`; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(link.href);
	}

	let chatPromise = null;
	function loadChat() {
		if (chatPromise) return chatPromise;
		chatPromise = initializeChat().catch((error) => { const box = document.getElementById("lex-chat-channels"); if (box) box.innerHTML = empty(errorMessage(error)); throw error; });
		return chatPromise;
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
		messageBox.addEventListener("keydown", (event) => {
			if (!["Home", "End", "PageUp", "PageDown"].includes(event.key)) return;
			event.preventDefault();
			const page = Math.max(120, messageBox.clientHeight * 0.85);
			messageBox.scrollTop = event.key === "Home"
				? 0
				: event.key === "End"
				? messageBox.scrollHeight
				: messageBox.scrollTop + (event.key === "PageUp" ? -page : page);
		});
	}

	async function initializeChat() {
		const channelBox = document.getElementById("lex-chat-channels");
		const messageBox = document.getElementById("lex-chat-messages");
		const header = document.getElementById("lex-chat-header");
		const form = document.getElementById("lex-chat-compose");
		if (!channelBox || !messageBox || !form) return;
		bindChatWheel(messageBox.closest(".lex-chat-main"), messageBox);
		let selected = null;
		let realtimeUnsubscribe = null;
		let channelGeneration = 0;
		const onRealtimeMessage = (message) => {
			if (selected && message.channel === selected.name) {
				appendMessage(message, messageBox);
				call("lex.lex.doctype.lexocrates_chat_message.lexocrates_chat_message.mark_channel_read", { channel: selected.name, message_name: message.name }).catch(() => {});
			}
		};
		await refreshPresence().catch(() => []);
		const channels = await call("lex.lex.doctype.lexocrates_chat_channel.lexocrates_chat_channel.get_channels");
		const channelRows = channels.map((channel) => {
			const label = channel.matter_title || channel.display_name || channel.channel_name;
			const context = channel.is_matter_channel
				? [channel.matter_id, channel.organization_name || channel.organization_id].filter(Boolean).join(" · ")
				: channel.reference_name || channel.channel_type;
			const search = [label, channel.matter_id, channel.organization_name, channel.organization_id, channel.reference_name, channel.channel_name].filter(Boolean).join(" ").toLowerCase();
			return `<button type="button" class="lex-chat-channel" data-channel="${escapeHTML(channel.name)}" data-matter-search="${escapeHTML(search)}"><span class="lex-channel-mark">${channel.is_direct_message ? escapeHTML(initials(channel.display_name)) : "#"}</span><span class="lex-channel-text"><strong>${escapeHTML(label)}</strong><span>${escapeHTML(context)}</span></span>${channel.unread_count ? `<span class="lex-nav-badge">${channel.unread_count}</span>` : ""}</button>`;
		}).join("");
		channelBox.innerHTML = channels.length
			? `<div class="lex-chat-matter-search"><input type="search" class="form-control" placeholder="Search Matter ID, name or organization" aria-label="Search Matter channels by ID, name or organization"></div><div class="lex-chat-channel-list">${channelRows}</div>`
			: empty("No Matter conversations are available yet.");
		channelBox.querySelector(".lex-chat-matter-search input")?.addEventListener("input", (event) => {
			const value = event.currentTarget.value.trim().toLowerCase();
			channelBox.querySelectorAll("[data-channel]").forEach((button) => {
				button.classList.toggle("hidden", Boolean(value) && !button.dataset.matterSearch.includes(value));
			});
		});
		for (const button of channelBox.querySelectorAll("[data-channel]")) button.addEventListener("click", async () => {
			const generation = ++channelGeneration;
			realtimeUnsubscribe?.();
			realtimeUnsubscribe = null;
			selected = channels.find((item) => item.name === button.dataset.channel); if (!selected) return;
			channelBox.querySelectorAll("[data-channel]").forEach((item) => item.classList.remove("active")); button.classList.add("active"); button.querySelector(".lex-nav-badge")?.remove();
			header.innerHTML = `<strong>${escapeHTML(selected.display_name || selected.channel_name)}</strong><span>${escapeHTML(selected.description || selected.reference_name || "Secure conversation")}</span>`;
			const messages = await call("lex.lex.doctype.lexocrates_chat_message.lexocrates_chat_message.get_messages", { channel: selected.name, limit: 100 });
			if (generation !== channelGeneration) return;
			renderMessages(messages, messageBox);
			const latestSequence = Math.max(0, ...messages.map((message) => Number(message.channel_sequence || 0)));
			if (window.lexocratesReliableChat) {
				realtimeUnsubscribe = window.lexocratesReliableChat.subscribe(selected.name, {
					afterSequence: latestSequence,
					onMessage: onRealtimeMessage,
				});
			} else {
				frappe.realtime?.emit("doc_subscribe", "Lexocrates Chat Channel", selected.name);
			}
			const jobPicker = form.elements.job_mention;
			const jobs = ["LPO Matter", "LPO Job"].includes(selected.reference_doctype)
				? await call("lex.lex.doctype.lexocrates_chat_message.lexocrates_chat_message.get_channel_jobs", { channel: selected.name, limit: 100 }).catch(() => [])
				: [];
			jobPicker.innerHTML = `<option value="">@ Job</option>${jobs.map((job) => `<option value="${escapeHTML(job.name)}">${escapeHTML(job.name)} · ${escapeHTML(job.job_title || "")}</option>`).join("")}`;
			jobPicker.disabled = !selected.can_post || !jobs.length;
			await call("lex.lex.doctype.lexocrates_chat_message.lexocrates_chat_message.mark_channel_read", { channel: selected.name, message_name: messages.at(-1)?.name }).catch(() => {});
			form.elements.message.disabled = !selected.can_post; form.querySelector("button").disabled = !selected.can_post;
		});
		form.elements.job_mention.addEventListener("change", (event) => {
			const job = event.currentTarget.value;
			if (!job) return;
			const input = form.elements.message;
			input.value = `${input.value}${input.value && !/\s$/.test(input.value) ? " " : ""}@${job} `;
			event.currentTarget.value = "";
			input.focus();
		});
		channelBox.querySelector("[data-channel]")?.click();
		form.addEventListener("submit", async (event) => {
			event.preventDefault(); const text = form.elements.message.value.trim(); if (!selected || !text) return; const button = form.querySelector("button"); button.disabled = true;
			try {
				const args = { channel: selected.name, message_text: text, attachments: "[]" };
				const message = window.lexocratesReliableChat
					? await window.lexocratesReliableChat.send({ method: "lex.lex.doctype.lexocrates_chat_message.lexocrates_chat_message.send_message", args })
					: await call("lex.lex.doctype.lexocrates_chat_message.lexocrates_chat_message.send_message", args);
				appendMessage(message, messageBox); form.reset();
			}
			catch (error) { showError("Message not sent", error); }
			finally { button.disabled = !selected.can_post; }
		});
		if (!window.lexocratesReliableChat) frappe.realtime?.on("new_chat_message", onRealtimeMessage);
	}

	function renderMessages(messages, box) { box.innerHTML = ""; messages.forEach((message) => appendMessage(message, box)); if (!messages.length) box.innerHTML = empty("No messages yet. Start the conversation."); }
	function appendMessage(message, box) {
		if (!message?.name || box.querySelector(`[data-message="${CSS.escape(message.name)}"]`)) return;
		const shouldStick = box.scrollHeight - box.scrollTop - box.clientHeight < 100;
		box.querySelector(".lex-empty")?.remove(); const item = document.createElement("article"); item.className = `lex-message ${message.system_generated ? "system" : ""} ${message.sender === frappe.session.user ? "own" : ""}`; item.dataset.message = message.name;
		const avatar = document.createElement("div"); avatar.className = "lex-message-avatar"; avatar.textContent = message.system_generated ? "S" : initials(message.sender_full_name || message.sender); if (!message.system_generated) avatar.insertAdjacentHTML("beforeend", presenceDot(message.sender));
		const content = document.createElement("div"); content.className = "lex-message-content"; const meta = document.createElement("div"); meta.className = "lex-message-meta"; const author = document.createElement("strong"); author.textContent = message.sender_full_name || message.sender || "System"; const time = document.createElement("span"); time.textContent = message.formatted_timestamp || fmtDate(message.sent_at); meta.append(author, time); const text = document.createElement("p"); text.innerHTML = message.message_text || ""; content.append(meta, text);
		if (message.job_mentions?.length) {
			const refs = document.createElement("div"); refs.className = "lex-message-job-refs";
			refs.innerHTML = message.job_mentions.map((job) => `<a href="/client-portal#work-requests" title="${escapeHTML(job.title || job.name)}">@${escapeHTML(job.name)}<span>${escapeHTML(job.status || "")}</span></a>`).join("");
			content.appendChild(refs);
		}
		item.append(avatar, content); box.appendChild(item); if (shouldStick) box.scrollTop = box.scrollHeight;
	}
})();
