frappe.ui.form.on("Lexocrates Work Intake", {
	refresh(frm) {
		if (
			!frm.is_new() &&
			frm.doc.job &&
			!["Payment Pending", "Funded"].includes(frm.doc.funding_status) &&
			(
				frappe.session.user === "Administrator" ||
				["System Manager", "LPO_Admin", "LPO_Manager"].some((role) => frappe.user.has_role(role))
			)
		) {
			frm.add_custom_button(__("Open Job Cost Estimator"), () => {
				frappe.set_route("Form", "LPO Job", frm.doc.job);
			}, __("Intake"));
		}
		if (!frm.is_new() && ["Security Review", "Analysis Pending"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Run Secure Analysis"), async () => {
				await frappe.call({
					method: "lex.work_intake.analyze_documents",
					args: { intake: frm.doc.name },
					freeze: true,
					freeze_message: __("Extracting and analyzing clean documents..."),
				});
				await frm.reload_doc();
			}, __("Intake"));
		}
		if (!frm.is_new() && ["Operations Review", "Analysis Pending", "Quote Ready", "Pending CEO Approval"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Issue Reviewed Quote"), () => show_quote_dialog(frm), __("Intake"));
		}
		if (!frm.is_new() && frm.doc.pricing_approval_status === "Pending CEO Approval" && frappe.user.has_role("CEO")) {
			frm.add_custom_button(__("Approve Pricing"), () => decide_pricing(frm, "Approved"), __("Pricing Approval"))
				.addClass("btn-primary");
			frm.add_custom_button(__("Reject Pricing"), () => decide_pricing(frm, "Rejected"), __("Pricing Approval"));
		}
	},
});

function decide_pricing(frm, decision) {
	const proceed = (notes) => frappe.call({
		method: "lex.work_intake.approve_quote_pricing",
		args: { intake: frm.doc.name, decision, notes },
		freeze: true,
		freeze_message: __("Recording pricing decision..."),
	}).then(() => {
		frappe.show_alert({
			message: decision === "Approved" ? __("Pricing approved; the client can now pay.") : __("Pricing rejected; sent back to Operations Review."),
			indicator: decision === "Approved" ? "green" : "orange",
		});
		frm.reload_doc();
	});

	if (decision === "Rejected") {
		frappe.prompt(
			{ fieldname: "notes", label: __("Reason for rejection"), fieldtype: "Small Text", reqd: 1 },
			(values) => proceed(values.notes),
			__("Reject Pricing"),
			__("Reject")
		);
		return;
	}
	frappe.confirm(
		__("Approve the confirmed fixed price of {0} {1} on {2}? The client will be able to pay as soon as you confirm.", [
			frm.doc.currency, frm.doc.quoted_amount, frm.doc.intake_title,
		]),
		() => proceed(null)
	);
}

function show_quote_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Recalculate Confirmed Work Quote"),
		fields: [
			{ fieldtype: "HTML", options: `<div class="alert alert-info">${__("The server recalculates this Job from exact native PDF pages and its selected fixed-rate service. Price and Legal Capacity cannot be entered manually.")}</div>` },
			{ fieldname: "review_notes", label: __("Operations Review Notes"), fieldtype: "Small Text", default: frm.doc.operations_review_notes || "" },
		],
		primary_action_label: __("Recalculate Quote"),
		primary_action: async (values) => {
			dialog.disable_primary_action();
			try {
				await frappe.call({
					method: "lex.work_intake.issue_quote",
					args: { intake: frm.doc.name, ...values },
					freeze: true,
				});
				dialog.hide();
				frappe.show_alert({ message: __("Reviewed quote issued to the client"), indicator: "green" });
				await frm.reload_doc();
			} finally {
				dialog.enable_primary_action();
			}
		},
	});
	dialog.show();
}
