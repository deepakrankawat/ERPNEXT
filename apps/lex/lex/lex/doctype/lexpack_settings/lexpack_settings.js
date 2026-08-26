frappe.ui.form.on("LexPack Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Test Configuration"), () => test_razorpay_configuration(frm), __("Razorpay"));
		if (frappe.session.user === "Administrator" || frappe.user.has_role("CEO")) {
			const enabled = Boolean(frm.doc.auto_approve_ai_pricing);
			frm.add_custom_button(
				enabled ? __("Disable AI Estimate Auto-Approval") : __("Enable AI Estimate Auto-Approval"),
				() => change_ai_auto_approval(frm, !enabled),
				__("AI Estimate Policy"),
			);
		}
		refresh_razorpay_readiness(frm);
	},
	after_save(frm) {
		refresh_razorpay_readiness(frm);
	},
});

async function change_ai_auto_approval(frm, enabled) {
	const action = enabled ? __("enable") : __("disable");
	const confirmed = await new Promise((resolve) => {
		frappe.confirm(
			enabled
				? __("Enable automatic approval only for completed, high-confidence AI-assisted estimates? Eligible quotes will open client funding immediately.")
				: __("Disable AI estimate auto-approval? New eligible estimates will require individual CEO approval."),
			() => resolve(true),
			() => resolve(false),
		);
	});
	if (!confirmed) return;
	const { message } = await frappe.call({
		method: "lex.lex.doctype.lexpack_settings.lexpack_settings.set_ai_estimate_auto_approval",
		args: { enabled: enabled ? 1 : 0 },
		freeze: true,
		freeze_message: __(`Recording CEO policy decision to ${action} auto-approval...`),
	});
	frappe.show_alert({ message: message?.message || __("Policy updated."), indicator: enabled ? "green" : "orange" }, 8);
	await frm.reload_doc();
}

async function refresh_razorpay_readiness(frm) {
	if (!frm.fields_dict.readiness_html) return;
	try {
		const { message: status } = await frappe.call("lex.lexpack.get_razorpay_status");
		render_razorpay_readiness(frm, status || {});
	} catch (error) {
		frm.fields_dict.readiness_html.$wrapper.html(
			`<div class="alert alert-danger">${frappe.utils.escape_html(error.message || __("Unable to read Razorpay status."))}</div>`,
		);
	}
}

async function test_razorpay_configuration(frm) {
	if (frm.is_dirty()) {
		await frm.save();
	}
	const button = frm.custom_buttons[__("Test Configuration")];
	button?.prop("disabled", true);
	try {
		const { message: result } = await frappe.call({
			method: "lex.lexpack.test_razorpay_configuration",
			freeze: true,
			freeze_message: __("Testing Razorpay authentication without creating a charge..."),
		});
		const indicator = result?.ok ? "green" : "red";
		frappe.show_alert({ message: result?.message || __("Razorpay test finished."), indicator }, 8);
		await frm.reload_doc();
	} finally {
		button?.prop("disabled", false);
	}
}

function render_razorpay_readiness(frm, status) {
	const escape = frappe.utils.escape_html;
	const ready = Boolean(status.payment_enabled);
	const configured = Boolean(status.configured);
	const label = ready ? __("Checkout Active") : configured ? __("Ready, Not Enabled") : __("Setup Incomplete");
	const color = ready ? "green" : configured ? "orange" : "red";
	const issues = (status.issues || []).map((issue) => `<li>${escape(issue)}</li>`).join("");
	const events = (status.required_webhook_events || []).map((event) => `<code>${escape(event)}</code>`).join(", ");
	frm.fields_dict.readiness_html.$wrapper.html(`
		<div class="frappe-card" style="padding: var(--padding-md); margin-bottom: var(--margin-sm);">
			<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
				<span class="indicator-pill ${color}">${escape(label)}</span>
				<strong>${escape(status.mode || "Test")} ${__("Mode")}</strong>
			</div>
			<div class="text-muted small">
				${__("Credentials")}: ${status.credentials_ready ? __("Ready") : __("Incomplete")} ·
				${__("Webhook")}: ${status.webhook_ready ? __("Ready") : __("Incomplete")} ·
				${__("Accounting")}: ${status.accounting_ready ? __("Ready") : __("Incomplete")}
			</div>
			${issues ? `<ul class="text-danger small" style="margin:10px 0">${issues}</ul>` : ""}
			<div class="small"><b>${__("Webhook URL")}:</b> <code>${escape(status.webhook_url || "")}</code></div>
			<div class="small"><b>${__("Events")}:</b> ${events}</div>
		</div>
	`);
}
