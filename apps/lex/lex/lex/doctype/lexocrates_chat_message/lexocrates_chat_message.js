frappe.ui.form.on("Lexocrates Chat Message", {
	refresh(frm) {
		frm.disable_save();
		frm.set_intro(
			__("This message is part of the legal operations audit trail. Use the Lexocrates Chat page to participate in the conversation."),
			"blue"
		);
	},
});
