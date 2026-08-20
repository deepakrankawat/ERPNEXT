frappe.ui.form.on('Customer', {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__('Add Interaction Note'), function() {
				frappe.new_doc('Customer Interaction Note', {
					customer: frm.doc.name,
					customer_name: frm.doc.customer_name
				});
			}, __('Custom Actions'));
		}
	}
});
