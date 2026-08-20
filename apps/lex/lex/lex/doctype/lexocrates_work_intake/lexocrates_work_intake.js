frappe.ui.form.on("Lexocrates Work Intake", {
	refresh(frm) {
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
		__("Approve {0} {1} for {2} LexPoints on {3}? The client will be able to pay as soon as you confirm.", [
			frm.doc.currency, frm.doc.quoted_amount, frm.doc.required_lexpoints, frm.doc.intake_title,
		]),
		() => proceed(null)
	);
}

function show_quote_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Issue Confirmed Work Quote"),
		fields: [
			{ fieldname: "required_lexpoints", label: __("Required LexPoints"), fieldtype: "Int", reqd: 1, default: frm.doc.required_lexpoints || 1 },
			{ fieldname: "quoted_amount", label: __("Fixed Quote"), fieldtype: "Currency", reqd: 1, default: frm.doc.quoted_amount || 1, options: "currency" },
			{ fieldname: "currency", label: __("Currency"), fieldtype: "Data", read_only: 1, default: frm.doc.currency },
			{ fieldname: "delivery_timeline_hours", label: __("Delivery Timeline (Hours)"), fieldtype: "Int", reqd: 1, default: frm.doc.delivery_timeline_hours || 24 },
			{ fieldname: "scope_summary", label: __("Confirmed Scope"), fieldtype: "Small Text", reqd: 1, default: frm.doc.scope_summary || "" },
			{ fieldname: "review_notes", label: __("Operations Review Notes"), fieldtype: "Small Text", default: frm.doc.operations_review_notes || "" },
		],
		primary_action_label: __("Issue Quote"),
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
