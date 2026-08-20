from __future__ import annotations

import frappe
from frappe.utils import add_days, get_first_day, now_datetime, nowdate


CEO_MONITORING_BLOCK = "Lexocrates CEO Executive Monitoring Cockpit"

CEO_MONITORING_HTML = """
<section class="lex-ceo-dashboard" aria-live="polite">
	<div class="lex-ceo-loading" style="padding: 40px; text-align: center; color: #64748b; font-family: system-ui, -apple-system, sans-serif;">
		<div class="spinner-border text-primary" role="status" style="width: 3rem; height: 3rem;"></div>
		<div style="margin-top: 16px; font-weight: 600; font-size: 15px; color: #0f172a;">Connecting to ERPNext MariaDB for 100% Real Executive Metrics...</div>
	</div>
</section>
""".strip()

CEO_MONITORING_STYLE = """
.lex-ceo-dashboard {
	font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
	color: #0f172a;
	background-color: #f8fafc;
	border-radius: 16px;
	padding: 8px;
}
.lex-ceo-dashboard .card-panel {
	background: #ffffff;
	border: 1px solid #e2e8f0;
	border-radius: 12px;
	padding: 16px;
	box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
	height: 100%;
}
.lex-ceo-dashboard .card-title {
	font-size: 14px;
	font-weight: 700;
	color: #0f172a;
	margin: 0 0 12px 0;
	display: flex;
	align-items: center;
	justify-content: space-between;
}
.lex-ceo-dashboard .metric-card {
	background: #ffffff;
	border: 1px solid #e2e8f0;
	border-radius: 12px;
	padding: 12px 14px;
	box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
	display: flex;
	flex-direction: column;
	justify-content: space-between;
	height: 100%;
}
.lex-ceo-dashboard .metric-label {
	font-size: 11px;
	font-weight: 600;
	color: #64748b;
	text-transform: uppercase;
	letter-spacing: 0.5px;
}
.lex-ceo-dashboard .metric-val {
	font-size: 22px;
	font-weight: 800;
	color: #0f172a;
	margin: 4px 0;
}
.lex-ceo-dashboard .metric-sub {
	font-size: 11px;
	font-weight: 600;
	color: #64748b;
}
.lex-ceo-dashboard .badge-impact-high { background: #fef2f2; color: #dc2626; border: 1px solid #fee2e2; }
.lex-ceo-dashboard .badge-impact-medium { background: #fffbeb; color: #d97706; border: 1px solid #fef3c7; }
.lex-ceo-dashboard .badge-impact-low { background: #f0fdf4; color: #16a34a; border: 1px solid #dcfce7; }
.lex-ceo-dashboard .progress-thin { height: 6px; border-radius: 3px; background: #e2e8f0; }
.lex-ceo-dashboard table.table-sm th { background: #f8fafc; color: #64748b; font-size: 11px; font-weight: 700; text-transform: uppercase; border-top: none; }
.lex-ceo-dashboard table.table-sm td { font-size: 12px; vertical-align: middle; }
""".strip()

CEO_MONITORING_SCRIPT = r"""
const panel = root_element.querySelector(".lex-ceo-dashboard");

const escapeHtml = (val) => String(val ?? "")
	.replaceAll("&", "&amp;")
	.replaceAll("<", "&lt;")
	.replaceAll(">", "&gt;")
	.replaceAll('"', "&quot;")
	.replaceAll("'", "&#039;");

function fetchAndRender() {
	frappe.xcall("lex.persona_workspaces.get_ceo_dashboard_data").then(data => {
		renderCeoDashboard(data);
	}).catch(err => {
		panel.innerHTML = `<div class="alert alert-danger" style="border-radius:12px; margin:16px;">Error loading CEO Cockpit: ${escapeHtml(err.message || err)}</div>`;
	});
}

function renderCeoDashboard(d) {
	const m = d.metrics || {};
	const pipe = d.pipeline || {};
	const prio = d.priorities || {};
	const paList = d.practice_areas || [];
	const lawyers = d.lawyers || [];
	const bottlenecks = d.bottlenecks || [];
	const escalations = d.escalations || [];
	const fin = d.financials || {};

	panel.innerHTML = `
		<!-- Top Command Header Bar -->
		<div style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); border-radius: 14px; padding: 16px 20px; color: #fff; margin-bottom: 16px; box-shadow: 0 4px 14px rgba(15, 23, 42, 0.15); display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;">
			<div>
				<div style="display: flex; align-items: center; gap: 8px;">
					<span style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; padding: 4px 10px; border-radius: 20px; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; text-transform: uppercase;">100% Live DB Data</span>
					<span style="color: #94a3b8; font-size: 12px;">• Real-time MariaDB Operations Control Center</span>
				</div>
				<h2 style="margin: 6px 0 0 0; font-size: 22px; font-weight: 800; color: #ffffff; letter-spacing: -0.5px;">Operations & CEO Control Center ⭐️</h2>
				<p style="margin: 2px 0 0 0; font-size: 12px; color: #94a3b8;">Real live production, workload, capacity, SLAs, LexPacks and financial metrics.</p>
			</div>
			<div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
				<button class="btn btn-sm btn-manual-lexpack" style="background: #0284c7; color: #fff; border: none; font-weight: 600; border-radius: 8px; padding: 6px 14px;"><i class="fa fa-flash"></i> Manual Approve LexPack</button>
				<button class="btn btn-sm btn-refresh-ceo" style="background: rgba(255,255,255,0.1); color: #fff; border: 1px solid rgba(255,255,255,0.2); font-weight: 600; border-radius: 8px; padding: 6px 14px;"><i class="fa fa-refresh"></i> Live Refresh</button>
			</div>
		</div>

		<!-- 8 Real Metric Cards Strip -->
		<div class="row" style="margin-bottom: 16px;">
			<div class="col-md-3 col-sm-6" style="margin-bottom: 10px;">
				<div class="metric-card">
					<div style="display:flex; justify-content:space-between; align-items:center;">
						<span class="metric-label">Jobs In Progress</span>
						<span style="background:#eff6ff; color:#2563eb; padding:4px 8px; border-radius:6px; font-size:12px;">👤</span>
					</div>
					<div class="metric-val" style="color:#2563eb;">${m.jobs_in_progress ?? 0}</div>
					<div class="metric-sub">Active Jobs in Pipeline</div>
				</div>
			</div>
			<div class="col-md-3 col-sm-6" style="margin-bottom: 10px;">
				<div class="metric-card">
					<div style="display:flex; justify-content:space-between; align-items:center;">
						<span class="metric-label">Jobs Completed (Today)</span>
						<span style="background:#f0fdf4; color:#16a34a; padding:4px 8px; border-radius:6px; font-size:12px;">✅</span>
					</div>
					<div class="metric-val" style="color:#16a34a;">${m.jobs_completed_today ?? 0}</div>
					<div class="metric-sub">Completed on ${escapeHtml(new Date().toLocaleDateString())}</div>
				</div>
			</div>
			<div class="col-md-3 col-sm-6" style="margin-bottom: 10px;">
				<div class="metric-card">
					<div style="display:flex; justify-content:space-between; align-items:center;">
						<span class="metric-label">Jobs Due Today</span>
						<span style="background:#fffbeb; color:#d97706; padding:4px 8px; border-radius:6px; font-size:12px;">📅</span>
					</div>
					<div class="metric-val" style="color:#d97706;">${m.jobs_due_today ?? 0}</div>
					<div class="metric-sub">Due Target Today</div>
				</div>
			</div>
			<div class="col-md-3 col-sm-6" style="margin-bottom: 10px;">
				<div class="metric-card">
					<div style="display:flex; justify-content:space-between; align-items:center;">
						<span class="metric-label">SLA Compliance</span>
						<span style="background:#f0fdf4; color:#16a34a; padding:4px 8px; border-radius:6px; font-size:12px;">🛡️</span>
					</div>
					<div class="metric-val" style="color:#059669;">${m.sla_compliance ?? 100}%</div>
					<div class="metric-sub">On-Time Delivery Rate</div>
				</div>
			</div>
			<div class="col-md-3 col-sm-6" style="margin-bottom: 10px;">
				<div class="metric-card">
					<div style="display:flex; justify-content:space-between; align-items:center;">
						<span class="metric-label">SLA At Risk</span>
						<span style="background:#fef2f2; color:#dc2626; padding:4px 8px; border-radius:6px; font-size:12px;">⚠️</span>
					</div>
					<div class="metric-val" style="color:#dc2626;">${m.sla_at_risk ?? 0}</div>
					<div class="metric-sub">Due in next 4 hours</div>
				</div>
			</div>
			<div class="col-md-3 col-sm-6" style="margin-bottom: 10px;">
				<div class="metric-card">
					<div style="display:flex; justify-content:space-between; align-items:center;">
						<span class="metric-label">Avg. TAT (hrs)</span>
						<span style="background:#f3e8ff; color:#9333ea; padding:4px 8px; border-radius:6px; font-size:12px;">⏱️</span>
					</div>
					<div class="metric-val" style="color:#9333ea;">${m.avg_tat_hrs ?? 0}</div>
					<div class="metric-sub">Turnaround Time</div>
				</div>
			</div>
			<div class="col-md-3 col-sm-6" style="margin-bottom: 10px;">
				<div class="metric-card">
					<div style="display:flex; justify-content:space-between; align-items:center;">
						<span class="metric-label">AI Queue</span>
						<span style="background:#e0f2fe; color:#0284c7; padding:4px 8px; border-radius:6px; font-size:12px;">🤖</span>
					</div>
					<div class="metric-val" style="color:#0284c7;">${m.ai_queue ?? 0}</div>
					<div class="metric-sub">Jobs in AI Processing</div>
				</div>
			</div>
			<div class="col-md-3 col-sm-6" style="margin-bottom: 10px;">
				<div class="metric-card">
					<div style="display:flex; justify-content:space-between; align-items:center;">
						<span class="metric-label">Escalations</span>
						<span style="background:#ffedd5; color:#ea580c; padding:4px 8px; border-radius:6px; font-size:12px;">🚨</span>
					</div>
					<div class="metric-val" style="color:#ea580c;">${m.escalations ?? 0}</div>
					<div class="metric-sub">Open Compliance Issues</div>
				</div>
			</div>
		</div>

		<!-- Production Pipeline Overview & Category Breakdown Row -->
		<div class="row" style="margin-bottom: 16px;">
			<!-- Pipeline Stages Bar & Breakdown -->
			<div class="col-md-6" style="margin-bottom: 12px;">
				<div class="card-panel">
					<div class="card-title">
						<span>Production Pipeline Overview (Live DB)</span>
						<a href="/app/lpo-job" style="font-size:11px; font-weight:600; color:#0284c7;">View full pipeline →</a>
					</div>
					<div style="display: flex; align-items: center; justify-content: space-between; text-align: center; margin-bottom: 14px; background: #f8fafc; padding: 10px; border-radius: 10px; border: 1px solid #f1f5f9;">
						<div>
							<small style="color:#64748b; font-weight:600; display:block;">Intake</small>
							<span style="font-size:16px; font-weight:800; color:#0f172a;">${pipe.intakes_waiting ?? 0}</span>
						</div>
						<span style="color:#cbd5e1;">➔</span>
						<div>
							<small style="color:#64748b; font-weight:600; display:block;">AI Queue</small>
							<span style="font-size:16px; font-weight:800; color:#0284c7;">${m.ai_queue ?? 0}</span>
						</div>
						<span style="color:#cbd5e1;">➔</span>
						<div>
							<small style="color:#64748b; font-weight:600; display:block;">In Progress</small>
							<span style="font-size:16px; font-weight:800; color:#2563eb;">${m.jobs_in_progress ?? 0}</span>
						</div>
						<span style="color:#cbd5e1;">➔</span>
						<div>
							<small style="color:#64748b; font-weight:600; display:block;">Review</small>
							<span style="font-size:16px; font-weight:800; color:#d97706;">${pipe.review_count ?? 0}</span>
						</div>
						<span style="color:#cbd5e1;">➔</span>
						<div>
							<small style="color:#64748b; font-weight:600; display:block;">QA</small>
							<span style="font-size:16px; font-weight:800; color:#9333ea;">${pipe.jobs_pending_qa ?? 0}</span>
						</div>
						<span style="color:#cbd5e1;">➔</span>
						<div>
							<small style="color:#64748b; font-weight:600; display:block;">Delivery</small>
							<span style="font-size:16px; font-weight:800; color:#16a34a;">${pipe.jobs_delivered ?? 0}</span>
						</div>
					</div>
					<div class="progress" style="height: 10px; border-radius: 5px; overflow: hidden; background: #e2e8f0; display: flex;">
						<div style="width: ${pipe.intakes_waiting ? 15 : 0}%; background: #10b981;"></div>
						<div style="width: ${m.ai_queue ? 15 : 0}%; background: #0284c7;"></div>
						<div style="width: ${m.jobs_in_progress ? 30 : 0}%; background: #2563eb;"></div>
						<div style="width: ${pipe.review_count ? 15 : 0}%; background: #f59e0b;"></div>
						<div style="width: ${pipe.jobs_pending_qa ? 15 : 0}%; background: #8b5cf6;"></div>
						<div style="width: ${pipe.jobs_delivered ? 10 : 0}%; background: #16a34a;"></div>
					</div>
					<div style="display:flex; justify-content:space-between; margin-top:8px; font-size:11px; color:#64748b; font-weight:600;">
						<span>Total Active Jobs: <strong>${(m.jobs_in_progress ?? 0) + (pipe.intakes_waiting ?? 0) + (pipe.jobs_pending_qa ?? 0)}</strong></span>
						<span>Total Delivered: <strong>${pipe.jobs_delivered ?? 0}</strong></span>
					</div>
				</div>
			</div>

			<!-- Real Priorities & Practice Areas -->
			<div class="col-md-3" style="margin-bottom: 12px;">
				<div class="card-panel">
					<div class="card-title">Jobs by Priority (Live)</div>
					<div style="font-size:12px; margin-top:8px;">
						<div style="display:flex; justify-content:space-between; margin-bottom:8px; padding:6px 8px; background:#fef2f2; border-radius:6px; border:1px solid #fee2e2;">
							<span style="color:#dc2626; font-weight:700;">● High / Urgent</span>
							<strong style="color:#dc2626;">${prio.high ?? 0}</strong>
						</div>
						<div style="display:flex; justify-content:space-between; margin-bottom:8px; padding:6px 8px; background:#fffbeb; border-radius:6px; border:1px solid #fef3c7;">
							<span style="color:#d97706; font-weight:700;">● Medium</span>
							<strong style="color:#d97706;">${prio.medium ?? 0}</strong>
						</div>
						<div style="display:flex; justify-content:space-between; padding:6px 8px; background:#f0fdf4; border-radius:6px; border:1px solid #dcfce7;">
							<span style="color:#16a34a; font-weight:700;">● Low / Normal</span>
							<strong style="color:#16a34a;">${prio.low ?? 0}</strong>
						</div>
					</div>
				</div>
			</div>

			<div class="col-md-3" style="margin-bottom: 12px;">
				<div class="card-panel">
					<div class="card-title">LexPack & Financials (Live)</div>
					<div style="font-size:11px;">
						<div style="margin-bottom:8px; padding:8px; background:#f8fafc; border-radius:6px; border:1px solid #f1f5f9;">
							<small style="color:#64748b; font-weight:600; display:block;">Total Paid Revenue</small>
							<span style="font-size:18px; font-weight:800; color:#16a34a;">₹${(fin.total_revenue ?? 0).toLocaleString()}</span>
						</div>
						<div style="display:grid; grid-template-columns:1fr 1fr; gap:6px;">
							<div style="padding:6px; background:#f8fafc; border-radius:6px; border:1px solid #f1f5f9;">
								<small style="color:#64748b;">Total Clients</small><br><strong style="font-size:14px;">${fin.total_clients ?? 0}</strong>
							</div>
							<div style="padding:6px; background:#f8fafc; border-radius:6px; border:1px solid #f1f5f9;">
								<small style="color:#64748b;">Pending Reg.</small><br><strong style="font-size:14px; color:${fin.pending_registrations ? '#d97706':'#0f172a'};">${fin.pending_registrations ?? 0}</strong>
							</div>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Team Workload Overview & Bottlenecks & Escalations Row -->
		<div class="row" style="margin-bottom: 16px;">
			<!-- Real Lawyers Workload Table -->
			<div class="col-md-6" style="margin-bottom: 12px;">
				<div class="card-panel">
					<div class="card-title">
						<span>Team Workload Matrix (Real Users)</span>
						<a href="/app/user" style="font-size:11px; font-weight:600; color:#0284c7;">View team →</a>
					</div>
					<div class="table-responsive">
						<table class="table table-sm table-hover" style="margin:0;">
							<thead>
								<tr>
									<th>Associate / Lawyer</th>
									<th class="text-center">Active Jobs</th>
									<th class="text-center">In Progress</th>
									<th class="text-center">QA Review</th>
									<th class="text-center">Completed</th>
								</tr>
							</thead>
							<tbody>
								${lawyers.length ? lawyers.map(u => `
									<tr>
										<td>
											<div style="display:flex; align-items:center; gap:8px;">
												<div style="width:24px; height:24px; border-radius:50%; background:#e0f2fe; color:#0369a1; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:11px;">
													${escapeHtml((u.full_name || u.user_id)[0].toUpperCase())}
												</div>
												<span style="font-weight:600; color:#0f172a;">${escapeHtml(u.full_name || u.user_id)}</span>
											</div>
										</td>
										<td class="text-center"><span class="badge badge-${u.active_jobs ? 'primary':'light'}">${u.active_jobs ?? 0}</span></td>
										<td class="text-center"><span class="badge badge-info">${u.in_progress ?? 0}</span></td>
										<td class="text-center"><span class="badge badge-warning">${u.review ?? 0}</span></td>
										<td class="text-center"><span class="badge badge-success">${u.completed_jobs ?? 0}</span></td>
									</tr>
								`).join('') : `
									<tr><td colspan="5" class="text-center text-muted" style="padding:16px;">No active legal associates or assigned jobs recorded in database.</td></tr>
								`}
							</tbody>
						</table>
					</div>
				</div>
			</div>

			<!-- Production Bottlenecks Table -->
			<div class="col-md-3" style="margin-bottom: 12px;">
				<div class="card-panel">
					<div class="card-title">Production Bottlenecks</div>
					<table class="table table-sm" style="margin:0;">
						<thead>
							<tr>
								<th>Stage</th>
								<th>Pending</th>
								<th>Impact</th>
							</tr>
						</thead>
						<tbody>
							${bottlenecks.length ? bottlenecks.map(b => `
								<tr>
									<td><strong style="color:#0f172a;">${escapeHtml(b.stage)}</strong></td>
									<td class="font-weight-bold">${b.pending ?? 0}</td>
									<td><span class="badge badge-impact-${(b.impact || 'low').toLowerCase()}">${escapeHtml(b.impact)}</span></td>
								</tr>
							`).join('') : `
								<tr><td colspan="3" class="text-center text-muted">No bottlenecks found.</td></tr>
							`}
						</tbody>
					</table>
				</div>
			</div>

			<!-- Escalations Table -->
			<div class="col-md-3" style="margin-bottom: 12px;">
				<div class="card-panel">
					<div class="card-title">Real-time Escalations</div>
					<table class="table table-sm" style="margin:0;">
						<thead>
							<tr>
								<th>ID</th>
								<th>Type</th>
								<th>Status</th>
							</tr>
						</thead>
						<tbody>
							${escalations.length ? escalations.map(e => `
								<tr>
									<td><a href="/app/lpo-compliance-log/${e.id}" style="font-weight:700; color:#0284c7;">${escapeHtml(e.id)}</a></td>
									<td><small style="font-weight:600;">${escapeHtml(e.type)}</small></td>
									<td><span class="badge badge-${e.status === 'Open' ? 'danger' : 'info'}">${escapeHtml(e.status)}</span></td>
								</tr>
							`).join('') : `
								<tr><td colspan="3" class="text-center text-muted" style="padding:16px;">No open escalations in database.</td></tr>
							`}
						</tbody>
					</table>
				</div>
			</div>
		</div>

		<!-- Executive Quick Actions Grid -->
		<div class="row" style="margin-bottom: 12px;">
			<div class="col-md-12">
				<div class="card-panel">
					<div class="card-title">Executive Quick Actions</div>
					<div style="display:grid; grid-template-columns: repeat(8, 1fr); gap:8px; margin-top:4px;">
						<a href="/app/lpo-job/new" class="btn btn-default btn-xs" style="text-align:left; font-size:11px; padding:8px 10px; font-weight:600;"><i class="fa fa-plus text-primary"></i> Create Job</a>
						<a href="/app/lpo-job" class="btn btn-default btn-xs" style="text-align:left; font-size:11px; padding:8px 10px; font-weight:600;"><i class="fa fa-user text-info"></i> Assign Job</a>
						<a href="/app/lexocrates-work-intake" class="btn btn-default btn-xs" style="text-align:left; font-size:11px; padding:8px 10px; font-weight:600;"><i class="fa fa-upload text-warning"></i> Upload Doc</a>
						<a href="/app/lpo-job" class="btn btn-default btn-xs" style="text-align:left; font-size:11px; padding:8px 10px; font-weight:600;"><i class="fa fa-tasks text-success"></i> Job Board</a>
						<a href="/app/lpo-qa-review" class="btn btn-default btn-xs" style="text-align:left; font-size:11px; padding:8px 10px; font-weight:600;"><i class="fa fa-check-square-o text-purple"></i> QA Queue</a>
						<a href="/app/lexpack-purchase" class="btn btn-default btn-xs" style="text-align:left; font-size:11px; padding:8px 10px; font-weight:600;"><i class="fa fa-credit-card text-success"></i> LexPacks</a>
						<a href="/app/customer" class="btn btn-default btn-xs" style="text-align:left; font-size:11px; padding:8px 10px; font-weight:600;"><i class="fa fa-building text-primary"></i> Clients</a>
						<button class="btn btn-primary btn-xs btn-manual-lexpack" style="text-align:left; font-size:11px; padding:8px 10px; font-weight:700; background:#0284c7; border:none;"><i class="fa fa-flash"></i> Approve Pack</button>
					</div>
				</div>
			</div>
		</div>
	`;

	const refreshBtn = panel.querySelector(".btn-refresh-ceo");
	if (refreshBtn) {
		refreshBtn.addEventListener("click", () => {
			refreshBtn.disabled = true;
			refreshBtn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Refreshing...';
			fetchAndRender();
		});
	}

	const manualBtns = panel.querySelectorAll(".btn-manual-lexpack");
	manualBtns.forEach(btn => {
		btn.addEventListener("click", () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Manual LexPack Plan Approval"),
				fields: [
					{ fieldname: "client", fieldtype: "Link", options: "Customer", label: __("Customer / Client"), reqd: 1 },
					{ fieldname: "plan", fieldtype: "Link", options: "LexPack Plan", label: __("LexPack Plan"), reqd: 1 },
					{ fieldname: "approval_reason", fieldtype: "Small Text", label: __("Approval Reason / Remarks"), reqd: 1, description: __("Mandatory executive reason for manual approval & invoice generation.") },
					{ fieldname: "amount", fieldtype: "Currency", label: __("Paid Amount (Override Price)") },
					{ fieldname: "lexpoints", fieldtype: "Int", label: __("LexPoints Credited (Override Points)") },
					{ fieldname: "work_intake", fieldtype: "Link", options: "Lexocrates Work Intake", label: __("Link Work Intake (Optional)") },
					{ fieldname: "create_payment_entry", fieldtype: "Check", label: __("Create Payment Entry (Payment Received)"), default: 1 }
				],
				primary_action_label: __("Approve & Generate Invoice"),
				primary_action(values) {
					dialog.hide();
					frappe.xcall("lex.lexpack.manually_approve_lexpack_plan", values).then(res => {
						frappe.msgprint({
							title: __("LexPack Approved Successfully"),
							indicator: "green",
							message: res.message + `<br><br><a href="/app/sales-invoice/${res.sales_invoice}" class="btn btn-primary btn-xs">View Sales Invoice ${res.sales_invoice}</a>`
						});
						fetchAndRender();
					}).catch(err => {
						frappe.msgprint({
							title: __("Approval Failed"),
							indicator: "red",
							message: err.message || err
						});
					});
				}
			});
			dialog.show();
		});
	});
}

fetchAndRender();
""".strip()
