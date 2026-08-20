(() => {
	const form = document.getElementById("lex-invitation-form");
	const result = document.getElementById("lex-auth-result");
	const token = new URLSearchParams(window.location.search).get("token");
	const show = (message, type) => { result.className = type; result.textContent = message; };
	if (!token) { form.hidden = true; show("This activation link is incomplete.", "error"); return; }
	form.addEventListener("submit", async (event) => {
		event.preventDefault();
		if (form.password.value !== form.confirm_password.value) { show("Passwords do not match.", "error"); return; }
		const button = form.querySelector("button"); button.disabled = true;
		try { const response = await frappe.call({ method: "lex.portal_management.accept_portal_invitation", args: { token, password: form.password.value } }); form.hidden = true; show("Portal access activated. Redirecting to login…", "success"); setTimeout(() => { window.location.href = `/login?redirect-to=${encodeURIComponent(response.message.redirect)}`; }, 900); }
		catch (error) { show(error.message || String(error), "error"); }
		finally { button.disabled = false; }
	});
})();
