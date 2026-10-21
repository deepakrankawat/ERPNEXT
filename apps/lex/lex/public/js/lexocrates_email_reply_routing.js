(function () {
	window.lexocratesEmailReplyRoutingVersion = "20261009-1";

	// Stock Frappe's CommunicationComposer.get_signature() always resolves the
	// "From" account via Email Account.default_outgoing (currently Info) the
	// moment it's called without an explicit sender -- which is exactly how
	// it's called on every composer open (see set_values() -> set_content()).
	// That silently rewrites a reply to a sales@/hr@/support@ thread so it
	// goes back out as info@ instead. The rule we actually want: whichever
	// mailbox a message came in on is the mailbox the reply goes out on --
	// sales stays sales, hr stays hr, support stays support. Info is only
	// ever the fallback for brand-new mail with no thread to anchor on.
	const patch = () => {
		const Composer = window.frappe?.views?.CommunicationComposer;
		if (!Composer) return false;
		if (Composer.__lexocrates_reply_routing_patched) return true;

		const originalSetValues = Composer.prototype.set_values;
		Composer.prototype.set_values = async function (...args) {
			if (this.is_a_reply && this.last_email?.email_account) {
				const account = (frappe.boot.email_accounts || []).find(
					(a) => a.email_account === this.last_email.email_account
				);
				if (account && this.user_email_accounts?.includes(account.email_id)) {
					this.sender = account.email_id;
				}
			}
			return originalSetValues.apply(this, args);
		};

		const originalGetSignature = Composer.prototype.get_signature;
		Composer.prototype.get_signature = function (sender_email) {
			// set_values() above (and the dialog field itself) may already hold
			// the correct thread account by the time this runs -- prefer that
			// over letting the original fall through to default_outgoing.
			if (!sender_email) {
				sender_email = this.dialog?.get_value("sender") || "";
			}
			return originalGetSignature.call(this, sender_email);
		};

		Composer.__lexocrates_reply_routing_patched = true;
		return true;
	};

	if (!patch()) {
		const timer = setInterval(() => {
			if (patch()) clearInterval(timer);
		}, 250);
		setTimeout(() => clearInterval(timer), 30000);
	}
})();
