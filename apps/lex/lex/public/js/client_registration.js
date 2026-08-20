(() => {
	const requestForm = document.getElementById("lex-registration-form");
	const verifyForm = document.getElementById("lex-registration-verify");
	const result = document.getElementById("lex-auth-result");
	const verifyResult = document.getElementById("lex-verify-result");
	const token = new URLSearchParams(window.location.search).get("token");
	const activationToken = new URLSearchParams(window.location.search).get("activation");
	const show = (target, message, type) => {
		target.className = `lex-form-result ${type}`;
		target.setAttribute("role", type === "error" ? "alert" : "status");
		target.textContent = message;
	};
	const call = (method, args) => frappe.call({ method, args }).then((response) => response.message);
	const sectionConfig = [
		{
			key: "organization",
			required: ["organization_name", "organization_type", "country"],
		},
		{
			key: "administrator",
			required: ["primary_user_name", "designation", "email"],
		},
		{
			key: "billing",
			optional: true,
		},
	];

	const hasValue = (control) => String(control?.value || "").trim().length > 0;
	const isValid = (control) => hasValue(control) && control.checkValidity();
	const updateSectionIndicators = () => {
		let requiredComplete = 0;
		for (const config of sectionConfig) {
			const section = requestForm.querySelector(`[data-form-section="${config.key}"]`);
			const tracker = requestForm.querySelector(`[data-tracker-item="${config.key}"]`);
			const sectionStatus = section.querySelector(`[data-section-status="${config.key}"]`);
			const trackerStatus = tracker.querySelector("[data-tracker-status]");
			let state;
			let label;

			if (config.optional) {
				const added = [...section.querySelectorAll("input, select, textarea")].some(hasValue);
				state = added ? "complete" : "optional";
				label = added ? "Added" : "Optional";
			} else {
				const complete = config.required.every((name) => isValid(requestForm.elements[name]));
				state = complete ? "complete" : "incomplete";
				label = complete ? "Complete" : "Incomplete";
				if (complete) requiredComplete += 1;
			}

			section.dataset.state = state;
			tracker.dataset.state = state;
			sectionStatus.className = `lex-section-status ${state}`;
			sectionStatus.textContent = label;
			trackerStatus.textContent = label;
		}

		const requiredTotal = sectionConfig.filter((item) => !item.optional).length;
		const percent = Math.round((requiredComplete / requiredTotal) * 100);
		const status = document.getElementById("lex-completion-status");
		const percentLabel = document.getElementById("lex-completion-percent");
		const progress = document.getElementById("lex-completion-bar");
		status.textContent = `${requiredComplete} of ${requiredTotal} required sections complete`;
		percentLabel.textContent = `${percent}%`;
		progress.setAttribute("aria-valuenow", String(requiredComplete));
		progress.setAttribute("aria-valuetext", status.textContent);
		progress.querySelector("span").style.width = `${percent}%`;
	};

	for (const control of requestForm.querySelectorAll("input, select, textarea")) {
		control.addEventListener("input", updateSectionIndicators);
		control.addEventListener("change", updateSectionIndicators);
	}
	for (const button of requestForm.querySelectorAll("[data-section-target]")) {
		button.addEventListener("click", () => {
			const section = document.getElementById(button.dataset.sectionTarget);
			section.scrollIntoView({ block: "start" });
			section.querySelector("input, select, textarea")?.focus({ preventScroll: true });
		});
	}
	updateSectionIndicators();

	if (token || activationToken) {
		requestForm.hidden = true;
		verifyForm.hidden = false;
		const title = verifyForm.querySelector("h1");
		const intro = verifyForm.querySelector(".lex-frappe-page-head p");
		const passwordGroup = verifyForm.querySelector("[data-activation-password]");
		const submitButton = verifyForm.querySelector("button[type='submit']");
		if (activationToken) {
			title.textContent = "Activate Approved Organization";
			intro.textContent = "Create the primary administrator password and activate the approved Client workspace.";
			passwordGroup.hidden = false;
			verifyForm.password.required = true;
			submitButton.textContent = "Activate Client workspace";
		} else {
			title.textContent = "Verify Organization Email";
			intro.textContent = "Confirm the applicant email. Lexocrates will complete compliance review before account activation.";
			passwordGroup.hidden = true;
			verifyForm.password.required = false;
			submitButton.textContent = "Verify email";
		}
	}

	const modal = document.getElementById("lex-verification-modal");
	const modalCloseBtn = document.getElementById("lex-modal-close-btn");
	const modalDismissBtn = document.getElementById("lex-modal-dismiss-btn");
	const modalDirectLink = document.getElementById("lex-modal-direct-link");
	const modalBody = document.getElementById("lex-modal-body");

	const openModal = (url, emailAddress) => {
		if (!modal) return;
		if (url) {
			modalDirectLink.href = url;
			modalDirectLink.style.display = "inline-flex";
		} else {
			modalDirectLink.style.display = "none";
		}
		if (modalBody && emailAddress) {
			modalBody.innerHTML = `
				<p>A time-limited verification request has been created for <strong>${escapeHTML(emailAddress)}</strong>.</p>
				<p class="lex-modal-hint">We have sent a verification email to your address. Verification submits the organization for compliance review; it does not create an account.</p>
			`;
		}
		modal.hidden = false;
		modal.setAttribute("aria-hidden", "false");
	};

	const closeModal = () => {
		if (!modal) return;
		modal.hidden = true;
		modal.setAttribute("aria-hidden", "true");
	};

	const escapeHTML = (str) =>
		String(str || "")
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;");

	if (modalCloseBtn) modalCloseBtn.addEventListener("click", closeModal);
	if (modalDismissBtn) modalDismissBtn.addEventListener("click", closeModal);
	if (modal) {
		modal.addEventListener("click", (e) => {
			if (e.target === modal) closeModal();
		});
	}

	requestForm.addEventListener("submit", async (event) => {
		event.preventDefault();
		const button = requestForm.querySelector("button[type='submit']");
		button.disabled = true;
		button.textContent = "Sending…";
		try {
			const response = await call(
				"lex.portal_management.request_client_registration",
				Object.fromEntries(new FormData(requestForm)),
			);
			const userEmail = requestForm.elements["email"]?.value;
			show(
				result,
				"Check your email for the time-limited verification link. No Client was created before verification.",
				"success",
			);
			result.scrollIntoView({ behavior: "smooth", block: "center" });

			const vUrl = response?.verification_url || (response?.token ? `/client-registration?token=${response.token}` : null);
			openModal(vUrl, userEmail);
		} catch (error) {
			show(result, error.message || String(error), "error");
			result.scrollIntoView({ behavior: "smooth", block: "center" });
		} finally {
			button.disabled = false;
			button.textContent = "Send verification link";
		}
	});

	verifyForm.addEventListener("submit", async (event) => {
		event.preventDefault();
		const button = verifyForm.querySelector("button[type='submit']");
		button.disabled = true;
		try {
			if (activationToken) {
				const response = await call("lex.portal_management.activate_approved_registration", {
					token: activationToken,
					password: verifyForm.password.value,
				});
				show(verifyResult, "Client workspace activated. Redirecting to login…", "success");
				setTimeout(() => {
					window.location.href = `/login?redirect-to=${encodeURIComponent(response.redirect)}`;
				}, 900);
			} else {
				await call("lex.portal_management.verify_client_registration", { token });
				show(
					verifyResult,
					"Email verified. Your organization is pending KYC, conflict, sanctions, and commercial review. No account has been created yet.",
					"success",
				);
				button.hidden = true;
			}
		} catch (error) {
			show(verifyResult, error.message || String(error), "error");
		} finally {
			button.disabled = false;
		}
	});
})();
