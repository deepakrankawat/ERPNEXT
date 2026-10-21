(function () {
	// Adds a "Use Company Name" checkbox to the New Email / Reply composer.
	// Unchecked (default): From shows the sending user's own name, same as
	// stock Frappe. Checked: From shows the company name instead, because
	// client-facing replies from shared mailboxes (hr@, sales@, support@)
	// should read as coming from "Lexocrates", not from whichever employee
	// happens to be logged in.
	const COMPANY_NAME = "Lexocrates";
	const FIELD_NAME = "lex_use_company_name";

	const patch = () => {
		const Composer = window.frappe?.views?.CommunicationComposer;
		if (!Composer) return false;
		if (Composer.__lexocrates_sender_name_patched) return true;

		const originalGetFields = Composer.prototype.get_fields;
		Composer.prototype.get_fields = function () {
			const fields = originalGetFields.apply(this, arguments);

			// get_fields() is what populates this.user_email_accounts (only
			// done when the user has >=1 enabled-outgoing account, i.e. only
			// when a "From" field exists at all) -- read it after calling
			// the original, not before.
			if (!this.user_email_accounts || !this.user_email_accounts.length) {
				return fields;
			}

			const checkbox = {
				label: __("Use Company Name ({0})", [COMPANY_NAME]),
				fieldtype: "Check",
				fieldname: FIELD_NAME,
				default: 0,
				description: __("Show \"{0}\" instead of your own name in the From address", [
					COMPANY_NAME,
				]),
			};

			const copy_index = fields.findIndex((df) => df.fieldname === "send_me_a_copy");
			if (copy_index === -1) {
				fields.push(checkbox);
			} else {
				fields.splice(copy_index + 1, 0, checkbox);
			}

			return fields;
		};

		// sender_full_name is built inline from frappe.user.full_name() right
		// where the email is dispatched, not read back off form_values, so
		// swapping that one lookup for the duration of the call is the
		// smallest patch that reaches it without re-implementing send_email.
		const originalSendEmail = Composer.prototype.send_email;
		Composer.prototype.send_email = function (btn, form_values, ...rest) {
			const useCompanyName = this.dialog?.get_value(FIELD_NAME);
			if (!useCompanyName) {
				return originalSendEmail.apply(this, arguments);
			}

			const originalFullName = frappe.user.full_name;
			frappe.user.full_name = () => COMPANY_NAME;
			try {
				return originalSendEmail.apply(this, arguments);
			} finally {
				frappe.user.full_name = originalFullName;
			}
		};

		Composer.__lexocrates_sender_name_patched = true;
		return true;
	};

	if (!patch()) {
		const timer = setInterval(() => {
			if (patch()) clearInterval(timer);
		}, 250);
		setTimeout(() => clearInterval(timer), 30000);
	}
})();
