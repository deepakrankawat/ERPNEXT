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
	},
});
