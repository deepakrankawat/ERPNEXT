(() => {
	"use strict";

	const CHAT_ROUTE = "/app/lexocrates-chat";
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

			// Rename page title, navbar title and breadcrumbs
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
				</a>`;

			const link = item.querySelector("a");
			const sync_active_state = () => {
				try {
					if (typeof frappe.get_route_str === "function") {
						link.classList.toggle("active", frappe.get_route_str() === "lexocrates-chat");
					}
					patch_workspace_sidebar_natively();
				} catch (e) {}
			};
			sync_active_state();
			if (window.$) {
				$(document).off("page-change.lexocrates-chat").on("page-change.lexocrates-chat", sync_active_state);
			}
			return true;
		} catch (err) {
			console.warn("Could not setup Lexocrates chat navbar link", err);
			return false;
		}
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
