frappe.pages["lexpoint-estimator"].on_page_load = (wrapper) => {
	wrapper.lexpoint_estimator = new LexPointEstimatorPage(wrapper);
};

frappe.pages["lexpoint-estimator"].on_page_show = (wrapper) => {
	wrapper.lexpoint_estimator?.show();
};

class LexPointEstimatorPage {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.api = "lex.lex.page.lexpoint_estimator.lexpoint_estimator";
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("LexPoint Estimator"),
			single_column: true,
		});
		this.page.set_secondary_action(__("Refresh"), () => this.load(), "refresh");
		this.page.add_inner_button(__("Test Estimation AI"), () => this.test_ai_connection(), __("AI"));
		this.$root = $("<div class='lex-estimator'></div>").appendTo(this.page.main);
		this.render_loading();
		this.load();
	}

	show() {
		if (!this.bootstrap) this.load();
	}

	async load() {
		try {
			const response = await frappe.call({ method: `${this.api}.get_estimator_bootstrap` });
			this.bootstrap = response.message || {};
			this.render();
		} catch (error) {
			this.$root.html(`<div class="alert alert-danger">${__("Unable to load the estimator.")}</div>`);
		}
	}

	render_loading() {
		this.$root.html(`<div class="text-muted lex-estimator__loading">${__("Loading secure estimator…")}</div>`);
	}

	render() {
		const data = this.bootstrap;
		const aiRoute = data.ai_route || {};
		const serviceOptions = (data.service_types || []).map((item) =>
			`<option value="${this.escape(item)}" ${item === "Contract Review" ? "selected" : ""}>${this.escape(item)}</option>`
		).join("");
		const priorityOptions = (data.priorities || []).map((item) =>
			`<option value="${this.escape(item)}" ${item === "Medium" ? "selected" : ""}>${this.escape(item)}</option>`
		).join("");
		const jurisdictionOptions = (data.jurisdictions || []).map((item) =>
			`<option value="${this.escape(item)}" ${item === "India" ? "selected" : ""}>${this.escape(item)}</option>`
		).join("");
		const extensions = (data.allowed_extensions || []).join(",");
		const maxMB = Math.round((data.max_upload_bytes || 0) / 1024 / 1024);

		this.$root.html(`
			<div class="lex-estimator__notice alert alert-info">
				<div>${frappe.utils.icon("info", "sm")}</div>
				<div><strong>${__("Independent internal preview")}</strong><br>${this.escape(data.disclaimer || "")}</div>
			</div>
			<div class="lex-estimator__grid">
				<section class="form-dashboard-section lex-estimator__card">
					<div class="lex-estimator__card-head">
						<div><h4>${__("Upload and estimate")}</h4><p class="text-muted">${__("The source stays private and is security-scanned before analysis.")}</p></div>
						<div class="lex-estimator__ai-status"><span class="indicator-pill ${data.ai_enabled ? "green" : "orange"}">${data.ai_enabled ? __("LPO AI connected") : __("Formula fallback")}</span><small class="text-muted">${this.escape(aiRoute.message || "")}</small></div>
					</div>
					<form class="lex-estimator__form">
						<div class="form-group lex-estimator__wide">
							<label class="control-label reqd">${__("Document")}</label>
							<div class="lex-estimator__dropzone">
								<input class="form-control lex-estimator__file" type="file" accept="${extensions}" required>
								<small class="text-muted">${__("PDF, DOCX, TXT or CSV · private multipart upload · configured capacity {0} MB", [maxMB])}</small>
								<div class="progress lex-estimator__progress hidden"><div class="progress-bar" role="progressbar" style="width:0%"></div></div>
							</div>
						</div>
						<div class="form-group"><label class="control-label reqd">${__("Service type")}</label><select class="form-control" name="service_type">${serviceOptions}</select></div>
						<div class="form-group"><label class="control-label reqd">${__("Jurisdiction")}</label><input class="form-control" name="jurisdiction" list="lex-estimator-jurisdictions" value="India" maxlength="140" required><datalist id="lex-estimator-jurisdictions">${jurisdictionOptions}</datalist></div>
						<div class="form-group"><label class="control-label reqd">${__("Priority")}</label><select class="form-control" name="priority">${priorityOptions}</select></div>
						<div class="form-group lex-estimator__wide"><label class="control-label">${__("Expected outcome")}</label><input class="form-control" name="expected_outcome" maxlength="1000" placeholder="${__("Example: Contract risk review with clause comments")}"></div>
						<div class="form-group lex-estimator__wide"><label class="control-label">${__("Instructions / assumptions")}</label><textarea class="form-control" name="detailed_instructions" rows="4" maxlength="10000" placeholder="${__("Add scope, review depth, special risks, or delivery assumptions.")}"></textarea></div>
						<label class="lex-estimator__check lex-estimator__wide"><input type="checkbox" name="use_ai" ${data.ai_enabled ? "checked" : ""}> <span>${__("Use governed AI for evidence classification when configured")}</span></label>
						<div class="lex-estimator__actions lex-estimator__wide"><button class="btn btn-primary lex-estimator__submit" type="submit">${__("Estimate LexPoints & Price")}</button><span class="text-muted">${__("No client or commercial workflow will be triggered.")}</span></div>
					</form>
				</section>
				<section class="form-dashboard-section lex-estimator__card lex-estimator__result-card">
					<div class="lex-estimator__empty">
						<div class="lex-estimator__empty-icon">${frappe.utils.icon("scan", "xl")}</div>
						<h4>${__("Estimate result")}</h4>
						<p class="text-muted">${__("Upload a document to see indicative LexPoints, price, delivery time, and calculation factors.")}</p>
					</div>
				</section>
			</div>
			<section class="form-dashboard-section lex-estimator__card lex-estimator__history">
				<div class="lex-estimator__card-head"><div><h4>${__("My recent checks")}</h4><p class="text-muted">${__("Private audit history; these are not client quotes.")}</p></div><a class="btn btn-default btn-sm" href="/app/lpo-standalone-estimate">${__("View all")}</a></div>
				<div class="lex-estimator__history-body"></div>
			</section>
		`);
		this.render_history(data.recent_estimates || []);
		this.$root.find(".lex-estimator__form").on("submit", (event) => this.submit(event));
	}

	async test_ai_connection() {
		const response = await frappe.call({
			method: `${this.api}.test_estimation_ai_connection`,
			freeze: true,
			freeze_message: __("Testing the LPO AI estimation route…"),
		});
		const result = response.message || {};
		frappe.msgprint({
			title: result.status === "success" ? __("Estimation AI connected") : __("Estimation AI unavailable"),
			indicator: result.status === "success" ? "green" : "orange",
			message: [result.message, result.provider && `${__("Provider")}: ${result.provider}`, result.model && `${__("Model")}: ${result.model}`, result.credential_name && `${__("Credential")}: ${result.credential_name}`]
				.filter(Boolean).map((item) => this.escape(item)).join("<br>"),
		});
		await this.load();
	}

	async submit(event) {
		event.preventDefault();
		const form = event.currentTarget;
		const file = this.$root.find(".lex-estimator__file")[0]?.files?.[0];
		if (!file) return frappe.msgprint(__("Select a document first."));
		if (file.size > (this.bootstrap.max_upload_bytes || 0)) {
			return frappe.msgprint(__("This file exceeds the current site capacity. An administrator can raise Max File Size in System Settings."));
		}
		const $button = this.$root.find(".lex-estimator__submit");
		const $progress = this.$root.find(".lex-estimator__progress").removeClass("hidden");
		const $bar = $progress.find(".progress-bar").css("width", "0%");
		$button.prop("disabled", true).text(__("Uploading…"));
		try {
			const values = Object.fromEntries(new FormData(form).entries());
			const result = await this.upload_file(file, values, form.elements.use_ai.checked, (percent) => {
				$bar.css("width", `${percent}%`);
				$button.text(percent < 100 ? __("Uploading {0}%", [percent]) : __("Scanning and estimating…"));
			});
			if (result) {
				this.render_result(result);
				frappe.show_alert({ message: __("Standalone estimate completed"), indicator: "green" });
				const fresh = await frappe.call({ method: `${this.api}.get_estimator_bootstrap` });
				this.bootstrap.recent_estimates = fresh.message?.recent_estimates || [];
				this.render_history(this.bootstrap.recent_estimates);
			}
		} catch (error) {
			frappe.msgprint({ title: __("Upload failed"), indicator: "red", message: this.escape(error.message || __("The document could not be uploaded.")) });
		} finally {
			$button.prop("disabled", false).text(__("Estimate LexPoints & Price"));
			$progress.addClass("hidden");
			$bar.css("width", "0%");
		}
	}

	upload_file(file, values, useAI, onProgress) {
		return new Promise((resolve, reject) => {
			const xhr = new XMLHttpRequest();
			const payload = new FormData();
			payload.append("file", file, file.name);
			payload.append("is_private", "1");
			payload.append("folder", "Home/Attachments");
			payload.append("method", `${this.api}.upload_standalone_estimate_file`);
			payload.append("service_type", values.service_type || "Other");
			payload.append("jurisdiction", values.jurisdiction || "India");
			payload.append("priority", values.priority || "Medium");
			payload.append("expected_outcome", values.expected_outcome || "");
			payload.append("detailed_instructions", values.detailed_instructions || "");
			payload.append("use_ai", useAI ? "1" : "0");
			xhr.open("POST", "/api/method/upload_file", true);
			xhr.setRequestHeader("Accept", "application/json");
			xhr.setRequestHeader("X-Frappe-CSRF-Token", frappe.csrf_token);
			xhr.upload.onprogress = (event) => {
				if (event.lengthComputable) onProgress(Math.min(100, Math.round(event.loaded / event.total * 100)));
			};
			xhr.onload = () => {
				let response = {};
				try { response = JSON.parse(xhr.responseText || "{}"); } catch (error) { /* handled below */ }
				if (xhr.status >= 200 && xhr.status < 300 && response.message) return resolve(response.message);
				if (xhr.status === 413) return reject(new Error(__("The reverse proxy rejected this file as too large.")));
				const serverMessage = this.extract_server_message(response);
				reject(new Error(serverMessage || __("Server returned HTTP {0}.", [xhr.status])));
			};
			xhr.onerror = () => reject(new Error(__("Network error during upload. Please retry.")));
			xhr.send(payload);
		});
	}

	extract_server_message(response) {
		try {
			const messages = JSON.parse(response._server_messages || "[]");
			return messages.map((item) => JSON.parse(item).message).filter(Boolean).join("<br>");
		} catch (error) {
			return response.exception || response._error_message || "";
		}
	}

	render_result(result) {
		const price = window.format_currency
			? format_currency(result.estimated_price, result.currency)
			: `${this.escape(result.currency)} ${Number(result.estimated_price || 0).toFixed(2)}`;
		const review = result.requires_human_review
			? `<span class="indicator-pill orange">${__("Human review recommended")}</span>`
			: `<span class="indicator-pill green">${__("Confidence passed")}</span>`;
		const aiRoute = result.analysis_provider
			? `${this.escape(result.analysis_provider)} · ${this.escape(result.analysis_model || "")}`
			: __("Deterministic formula");
		this.$root.find(".lex-estimator__result-card").html(`
			<div class="lex-estimator__card-head"><div><h4>${__("Indicative estimate")}</h4><p class="text-muted">${this.escape(result.file_name)}</p></div>${review}</div>
			<div class="lex-estimator__metrics">
				<div><span>${__("LexPoints")}</span><strong>${this.escape(result.estimated_lexpoints)}</strong></div>
				<div><span>${__("Indicative price")}</span><strong>${price}</strong></div>
				<div><span>${__("Delivery")}</span><strong>${this.escape(result.delivery_hours)} ${__("hours")}</strong></div>
			</div>
			<div class="lex-estimator__details">
				<div><span>${__("Recommended service")}</span><strong>${this.escape(result.recommended_service)}</strong></div>
				<div><span>${__("Document type")}</span><strong>${this.escape(result.detected_document_type)}</strong></div>
				<div><span>${__("Complexity")}</span><strong>${this.escape(result.complexity_score)}/100 · ${this.escape(result.complexity_classification)}</strong></div>
				<div><span>${__("Risk / reviewer")}</span><strong>${this.escape(result.risk_level)} · ${this.escape(result.reviewer_level)}</strong></div>
				<div><span>${__("Evidence")}</span><strong>${this.escape(result.page_count)} ${__("pages")} · ${this.escape(result.word_count)} ${__("words")}</strong></div>
				<div><span>${__("Method")}</span><strong>${this.escape(result.estimate_source)} · ${this.escape(result.confidence)}%</strong></div>
				<div><span>${__("AI route")}</span><strong>${aiRoute}</strong></div>
			</div>
			<div class="lex-estimator__explanation"><strong>${__("Why this estimate")}</strong><p>${this.escape(result.explanation || result.analysis_note || "")}</p></div>
			<div class="lex-estimator__result-actions"><a class="btn btn-default btn-sm" href="${this.escape(result.route)}">${__("Open audit record")}</a><span class="text-muted">${__("Preview only — no quote or payment record created")}</span></div>
		`);
	}

	render_history(rows) {
		const $body = this.$root.find(".lex-estimator__history-body");
		if (!rows.length) {
			$body.html(`<div class="lex-estimator__history-empty text-muted">${__("No standalone estimates yet.")}</div>`);
			return;
		}
		$body.html(`<div class="table-responsive"><table class="table table-hover"><thead><tr><th>${__("Document")}</th><th>${__("Service")}</th><th>${__("LexPoints")}</th><th>${__("Price")}</th><th>${__("Method")}</th><th></th></tr></thead><tbody>${rows.map((row) => {
			const price = window.format_currency ? format_currency(row.estimated_price, row.currency) : `${row.currency || ""} ${Number(row.estimated_price || 0).toFixed(2)}`;
			const runAI = row.estimate_source !== "AI-Assisted Formula"
				? `<button class="btn btn-primary btn-xs lex-estimator__rerun-ai" type="button" data-estimate="${this.escape(row.name)}">${__("Run LPO AI")}</button>`
				: "";
			return `<tr><td><strong>${this.escape(row.file_name || row.estimate_title)}</strong><br><small class="text-muted">${this.escape(frappe.datetime.str_to_user(row.requested_on))}</small></td><td>${this.escape(row.recommended_service || "—")}</td><td>${this.escape(row.estimated_lexpoints || "—")}</td><td>${price}</td><td>${this.escape(row.estimate_source || "—")}</td><td><div class="lex-estimator__row-actions">${runAI}<a class="btn btn-default btn-xs" href="${this.escape(row.route)}">${__("Open")}</a></div></td></tr>`;
		}).join("")}</tbody></table></div>`);
		$body.find(".lex-estimator__rerun-ai").on("click", (event) => {
			this.rerun_with_ai(event.currentTarget.dataset.estimate, event.currentTarget);
		});
	}

	async rerun_with_ai(estimate, button) {
		const $button = $(button);
		$button.prop("disabled", true).text(__("Running AI…"));
		try {
			const response = await frappe.call({
				method: `${this.api}.rerun_estimate_with_ai`,
				args: { estimate },
				freeze: true,
				freeze_message: __("Classifying the existing document through LPO AI…"),
			});
			if (response.message) {
				this.render_result(response.message);
				frappe.show_alert({ message: __("AI-assisted estimate completed"), indicator: "green" });
			}
			const fresh = await frappe.call({ method: `${this.api}.get_estimator_bootstrap` });
			this.bootstrap = fresh.message || this.bootstrap;
			this.render_history(this.bootstrap.recent_estimates || []);
		} catch (error) {
			frappe.msgprint({
				title: __("AI estimation failed"),
				indicator: "red",
				message: this.escape(error.message || __("The document could not be re-estimated.")),
			});
		} finally {
			$button.prop("disabled", false).text(__("Run LPO AI"));
		}
	}

	escape(value) {
		return frappe.utils.escape_html(String(value ?? ""));
	}
}
