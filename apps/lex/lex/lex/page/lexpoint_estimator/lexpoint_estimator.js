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
						<span class="indicator-pill ${data.ai_enabled ? "green" : "gray"}">${data.ai_enabled ? __("AI classification available") : __("Formula mode")}</span>
					</div>
					<form class="lex-estimator__form">
						<div class="form-group lex-estimator__wide">
							<label class="control-label reqd">${__("Document")}</label>
							<div class="lex-estimator__dropzone">
								<input class="form-control lex-estimator__file" type="file" accept="${extensions}" required>
								<small class="text-muted">${__("PDF, DOCX, TXT or CSV · private · maximum {0} MB", [maxMB])}</small>
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

	async submit(event) {
		event.preventDefault();
		const form = event.currentTarget;
		const file = this.$root.find(".lex-estimator__file")[0]?.files?.[0];
		if (!file) return frappe.msgprint(__("Select a document first."));
		if (file.size > (this.bootstrap.max_upload_bytes || 0)) {
			return frappe.msgprint(__("The document is larger than the permitted upload limit."));
		}
		const $button = this.$root.find(".lex-estimator__submit");
		$button.prop("disabled", true).text(__("Scanning and estimating…"));
		try {
			const content = await this.read_file(file);
			const values = Object.fromEntries(new FormData(form).entries());
			const response = await frappe.call({
				method: `${this.api}.estimate_document`,
				args: {
					filename: file.name,
					content,
					service_type: values.service_type,
					jurisdiction: values.jurisdiction,
					priority: values.priority,
					expected_outcome: values.expected_outcome,
					detailed_instructions: values.detailed_instructions,
					use_ai: form.elements.use_ai.checked ? 1 : 0,
				},
				freeze: true,
				freeze_message: __("Security scanning and calculating the estimate…"),
			});
			if (response.message) {
				this.render_result(response.message);
				frappe.show_alert({ message: __("Standalone estimate completed"), indicator: "green" });
				const fresh = await frappe.call({ method: `${this.api}.get_estimator_bootstrap` });
				this.bootstrap.recent_estimates = fresh.message?.recent_estimates || [];
				this.render_history(this.bootstrap.recent_estimates);
			}
		} finally {
			$button.prop("disabled", false).text(__("Estimate LexPoints & Price"));
		}
	}

	render_result(result) {
		const price = window.format_currency
			? format_currency(result.estimated_price, result.currency)
			: `${this.escape(result.currency)} ${Number(result.estimated_price || 0).toFixed(2)}`;
		const review = result.requires_human_review
			? `<span class="indicator-pill orange">${__("Human review recommended")}</span>`
			: `<span class="indicator-pill green">${__("Confidence passed")}</span>`;
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
			return `<tr><td><strong>${this.escape(row.file_name || row.estimate_title)}</strong><br><small class="text-muted">${this.escape(frappe.datetime.str_to_user(row.requested_on))}</small></td><td>${this.escape(row.recommended_service || "—")}</td><td>${this.escape(row.estimated_lexpoints || "—")}</td><td>${price}</td><td>${this.escape(row.estimate_source || "—")}</td><td><a class="btn btn-default btn-xs" href="${this.escape(row.route)}">${__("Open")}</a></td></tr>`;
		}).join("")}</tbody></table></div>`);
	}

	read_file(file) {
		return new Promise((resolve, reject) => {
			const reader = new FileReader();
			reader.onload = () => resolve(reader.result);
			reader.onerror = reject;
			reader.readAsDataURL(file);
		});
	}

	escape(value) {
		return frappe.utils.escape_html(String(value ?? ""));
	}
}
