frappe.ui.form.on("LPO Matter", {
	refresh(frm) {
		if (frm.is_new() || ["Completed", "Closed"].includes(frm.doc.status)) return;

		frm.add_custom_button(__("LPO Job"), () => {
			frappe.new_doc("LPO Job", {
				engagement: frm.doc.name,
				customer: frm.doc.customer,
			});
		}, __("Create"));

		if (frm.doc.billing_method === "Quoted Price" && frm.doc.quote_status !== "Approved") {
			frm.add_custom_button(__("Approve Quote"), () => {
				frappe.prompt([
					{ fieldname: "quoted_amount", fieldtype: "Currency", label: __("Quoted Amount"), default: frm.doc.quoted_amount, reqd: 1 },
					{ fieldname: "notes", fieldtype: "Small Text", label: __("Decision Notes") },
				], (values) => frappe.call({
					method: "lex.lex.doctype.lpo_matter.lpo_matter.decide_quote",
					args: { matter: frm.doc.name, decision: "Approved", ...values },
					freeze: true,
				}).then(() => frm.reload_doc()), __("Approve Matter Quote"));
			}, __("Commercial"));
		}

		if (frm.doc.billing_method === "LexPack" && frm.doc.funding_status !== "Funded") {
			frm.add_custom_button(__("Reserve LexPoints"), () => frappe.call({
				method: "lex.lex.doctype.lpo_matter.lpo_matter.reserve_matter_funding",
				args: { matter: frm.doc.name, idempotency_key: `matter-funding:${frm.doc.name}:${frm.doc.modified}` },
				freeze: true,
			}).then(() => frm.reload_doc()), __("Commercial"));
		}

		if (frm.doc.status === "Draft") {
			frm.add_custom_button(__("Activate Matter"), () => {
				frm.set_value("status", "Active");
				frm.save();
			}, __("Status"));
		}

		// Conflict Check Actions
		frm.add_custom_button(__("Run Conflict Check"), () => {
			frappe.call({
				method: "lex.conflict_check.run_conflict_check",
				args: { matter_name: frm.doc.name, trigger_reason: "Manual Desk Screening" },
				freeze: true,
				freeze_message: __("Screening parties for potential conflicts..."),
			}).then((r) => {
				frappe.show_alert({
					message: __("Conflict check completed: {0} ({1} matches)", [r.message.status, r.message.match_count]),
					indicator: r.message.match_count ? "orange" : "green",
				}, 5);
				frm.reload_doc();
			});
		}, __("Conflict"));

		if (frm.doc.latest_conflict_event) {
			frm.add_custom_button(__("Review Conflict Matches"), () => {
				frappe.prompt([
					{
						fieldname: "decision",
						fieldtype: "Select",
						label: __("Review Decision"),
						options: "Cleared\nEscalated",
						default: "Cleared",
						reqd: 1,
					},
					{
						fieldname: "reason",
						fieldtype: "Small Text",
						label: __("Decision Reason / Clearance Notes"),
						reqd: 1,
					},
				], (values) => {
					frappe.call({
						method: "lex.conflict_check.record_conflict_decision",
						args: {
							event_name: frm.doc.latest_conflict_event,
							decision: values.decision,
							reason: values.reason,
						},
						freeze: true,
					}).then(() => {
						frappe.show_alert({ message: __("Decision recorded: {0}", [values.decision]), indicator: "green" });
						frm.reload_doc();
					});
				}, __("Record Conflict Decision"));
			}, __("Conflict"));
		}

		frm.add_custom_button(__("Matter Acceptance"), () => {
			frappe.prompt([
				{
					fieldname: "status",
					fieldtype: "Select",
					label: __("Acceptance Status"),
					options: "Pending\nAccepted\nDeclined\nOn Hold",
					default: frm.doc.matter_acceptance_status || "Pending",
					reqd: 1,
				},
				{
					fieldname: "notes",
					fieldtype: "Small Text",
					label: __("Acceptance / Restriction Notes"),
				},
			], (values) => {
				frappe.call({
					method: "lex.conflict_check.record_matter_acceptance",
					args: {
						matter_name: frm.doc.name,
						status: values.status,
						notes: values.notes,
					},
					freeze: true,
				}).then(() => {
					frappe.show_alert({ message: __("Matter acceptance updated: {0}", [values.status]), indicator: "green" });
					frm.reload_doc();
				});
			}, __("Record Matter Acceptance"));
		}, __("Conflict"));
	},
});
