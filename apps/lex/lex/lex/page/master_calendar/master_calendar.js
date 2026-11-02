frappe.pages["master-calendar"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Master Calendar"), single_column: true });
	const todayDate = () => new Date(`${frappe.datetime.get_today()}T00:00:00`);
	const initialMonth = todayDate(); initialMonth.setDate(1);
	const state = { month: initialMonth, events: [], selected: null, services: [] };
	const $root = $(wrapper).find(".layout-main-section").addClass("lex-master-calendar");

	const pad = (value) => String(value).padStart(2, "0");
	const iso = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
	const title = () => state.month.toLocaleDateString(frappe.boot.lang === "en" ? "en-CA" : undefined, { month: "long", year: "numeric" });
	const monthBounds = () => ({
		start: iso(new Date(state.month.getFullYear(), state.month.getMonth(), 1)),
		end: iso(new Date(state.month.getFullYear(), state.month.getMonth() + 1, 0)),
	});
	const escape = (value) => frappe.utils.escape_html(value || "");

	function selectedDetail() {
		const event = state.selected;
		if (!event) return '<div class="text-muted">Select a calendar item to view its Matter, Job and control details.</div>';
		return `<h4>${escape(event.title)}</h4><dl><dt>Date</dt><dd>${escape(event.date)}</dd><dt>Type</dt><dd>${escape(event.kind)}</dd><dt>Alert</dt><dd><span class="lex-calendar-pill lex-key-${escape(event.alert === "due_soon" ? "soon" : event.alert)}">${escape(event.alert.replace("_", " "))}</span></dd><dt>Matter</dt><dd>${event.matter ? `<a href="/app/lpo-matter/${encodeURIComponent(event.matter)}">${escape(event.matter_title)}</a>` : "—"}</dd><dt>Job</dt><dd>${event.job ? `<a href="/app/lpo-job/${encodeURIComponent(event.job)}">${escape(event.job_title)}</a>` : "—"}</dd><dt>Service / status</dt><dd>${escape(event.service || "—")} ${event.status ? `· ${escape(event.status)}` : ""}</dd>${event.control ? `<dt>Control detail</dt><dd>${escape(event.control)}</dd>` : ""}</dl>`;
	}

	function render() {
		const bounds = monthBounds();
		const eventsByDate = state.events.reduce((map, event) => { (map[event.date] ||= []).push(event); return map; }, {});
		const first = new Date(state.month.getFullYear(), state.month.getMonth(), 1);
		const gridStart = new Date(first); gridStart.setDate(first.getDate() - first.getDay());
		const today = frappe.datetime.get_today();
		const summary = state.summary || {};
		$root.html(`
			<section class="lex-calendar-hero"><div><h2>Master Matter & Job Calendar</h2><p>One operational view for Matter milestones, Job delivery dates and independently verified SOP controls. Alerts are generated from the same server-side records.</p></div><div class="lex-calendar-key"><span class="lex-key-overdue">Overdue</span><span class="lex-key-soon">Due in 7 days</span><span class="lex-key-scheduled">Scheduled</span></div></section>
			<div class="lex-calendar-toolbar"><div class="lex-calendar-nav"><button class="btn btn-default btn-sm" data-cal-nav="previous">‹</button><button class="btn btn-default btn-sm" data-cal-nav="today">Today</button><h3>${escape(title())}</h3><button class="btn btn-default btn-sm" data-cal-nav="next">›</button></div><div class="d-flex" style="gap:10px"><div class="form-group"><label class="control-label small">Service</label><select class="form-control input-sm" data-cal-service><option value="">All services</option>${state.services.map((service) => `<option value="${escape(service)}">${escape(service)}</option>`).join("")}</select></div><div class="form-group"><label class="control-label small">Job status</label><select class="form-control input-sm" data-cal-status><option value="">All active statuses</option><option>In Progress</option><option>QA Review</option><option>Ready for Delivery</option><option>On Hold</option></select></div><button class="btn btn-primary btn-sm" style="align-self:end" data-cal-refresh>Refresh</button></div></div>
			<div class="lex-calendar-summary"><div class="lex-summary-card"><b>${summary.overdue || 0}</b><span>Overdue / at risk</span></div><div class="lex-summary-card"><b>${summary.due_soon || 0}</b><span>Due in 7 days</span></div><div class="lex-summary-card"><b>${summary.scheduled || 0}</b><span>Scheduled controls</span></div><div class="lex-summary-card"><b>${summary.matters || 0}</b><span>Matters in scope</span></div><div class="lex-summary-card"><b>${summary.jobs || 0}</b><span>Jobs in scope</span></div></div>
			<section class="lex-calendar-shell"><div class="lex-calendar-weekdays">${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((day) => `<div>${day}</div>`).join("")}</div><div class="lex-calendar-grid">${Array.from({ length: 42 }, (_, index) => { const day = new Date(gridStart); day.setDate(gridStart.getDate() + index); const key = iso(day); const eventButtons = (eventsByDate[key] || []).slice(0, 4).map((event) => `<button class="lex-calendar-event ${event.alert} ${state.selected?.key === event.key ? "is-selected" : ""}" data-cal-event="${escape(event.key)}" title="${escape(event.title)}">${escape(event.title)}</button>`).join(""); const remainder = (eventsByDate[key] || []).length - 4; return `<div class="lex-calendar-day ${day.getMonth() !== state.month.getMonth() ? "is-outside" : ""} ${key === today ? "is-today" : ""}"><span class="lex-day-number">${day.getDate()}</span>${eventButtons}${remainder > 0 ? `<span class="text-muted small">+${remainder} more</span>` : ""}</div>`; }).join("")}</div></section>
			<section class="lex-calendar-detail">${selectedDetail()}</section>
			<footer class="lex-calendar-chat-dock"><div><strong>Secure Matter Chat</strong><small>${state.selected?.matter ? `${escape(state.selected.matter_title)}${state.selected.job ? ` · ${escape(state.selected.job_title)}` : ""}` : "Select a Matter or Job calendar item to open its conversation."}</small></div><div><button class="btn btn-default btn-sm" data-cal-open-matter ${state.selected?.matter ? "" : "disabled"}>Open Matter</button> <button class="btn btn-primary btn-sm" data-cal-open-chat ${state.selected?.matter ? "" : "disabled"}>Open Secure Chat</button></div></footer>
		`);
		$root.find("[data-cal-service]").val(state.service || "");
		$root.find("[data-cal-status]").val(state.status || "");
		bind();
	}

	function bind() {
		$root.find("[data-cal-nav]").on("click", function () { const action = $(this).data("cal-nav"); if (action === "today") state.month = todayDate(); else state.month = new Date(state.month.getFullYear(), state.month.getMonth() + (action === "next" ? 1 : -1), 1); state.month.setDate(1); state.selected = null; load(); });
		$root.find("[data-cal-refresh]").on("click", load);
		$root.find("[data-cal-service], [data-cal-status]").on("change", function () { state.service = $root.find("[data-cal-service]").val(); state.status = $root.find("[data-cal-status]").val(); state.selected = null; load(); });
		$root.find("[data-cal-event]").on("click", function () { state.selected = state.events.find((event) => event.key === $(this).data("cal-event")); render(); });
		$root.find("[data-cal-open-matter]").on("click", () => frappe.set_route("Form", "LPO Matter", state.selected.matter));
		$root.find("[data-cal-open-chat]").on("click", async () => {
			const referenceDoctype = state.selected.job ? "LPO Job" : "LPO Matter";
			const referenceName = state.selected.job || state.selected.matter;
			const response = await frappe.call({ method: "lex.lex.page.lexocrates_chat.lexocrates_chat.get_or_create_contextual_channel", args: { reference_doctype: referenceDoctype, reference_name: referenceName } });
			frappe.set_route("lexocrates-chat", { channel: response.message?.name });
		});
	}

	async function load() {
		const bounds = monthBounds();
		frappe.dom.freeze(__("Loading Master Calendar…"));
		try {
			const response = await frappe.call({ method: "lex.master_calendar.get_master_calendar", args: { ...bounds, service: state.service || null, status: state.status || null } });
			state.events = response.message?.events || []; state.summary = response.message?.summary || {}; state.services = response.message?.services || [];
			render();
		} catch (error) { frappe.msgprint({ title: __("Calendar unavailable"), message: error.message || error, indicator: "red" }); }
		finally { frappe.dom.unfreeze(); }
	}

	page.set_secondary_action(__("Refresh"), load);
	load();
};
