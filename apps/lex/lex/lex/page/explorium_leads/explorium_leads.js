frappe.pages["explorium-leads"].on_page_load = (wrapper) => {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Explorium Leads",
		single_column: true,
	});
	wrapper.explorium_leads = new ExploriumLeadsPage(page);
};

const DEFAULT_COMPANY_FILTERS = {
	filters: {
		country_code: { values: ["CA"] },
		company_size: { values: ["11-50", "51-200"] },
		linkedin_category: { values: ["law practice", "legal services", "alternative dispute resolution", "outsourcing and offshoring consulting"] },
		website_keywords: { values: ["law firm", "lawyers", "attorneys", "solicitors", "legal counsel", "litigation", "corporate law", "legal process outsourcing", "LPO", "legal outsourcing", "ediscovery", "document review", "contract lifecycle management", "legal support services", "paralegal services"] },
		has_website: { value: true },
	},
};

const DEFAULT_PEOPLE_FILTERS = {
	filters: {
		job_level: { values: ["c-suite", "director", "manager"] },
		job_department: { values: ["legal", "executive", "business_development"] },
	},
};

class ExploriumLeadsPage {
	constructor(page) {
		this.page = page;
		this.companies = [];
		this.selectedCompanyIds = new Set();
		this.prospects = [];
		this.render();
	}

	esc(value) {
		return frappe.utils.escape_html(value == null ? "" : String(value));
	}

	render() {
		this.page.body.html(`
			<div class="explorium-leads">
				<div class="alert alert-info">
					Company and people search runs in free preview mode — it costs no Explorium credits.
					Credits are spent only when you click <strong>Add Selected to Leads</strong>, which looks up
					real contact details for the people you pick.
				</div>

				<div class="frappe-card" style="padding: 16px; margin-bottom: 16px;">
					<h5>1. Find companies</h5>
					<div class="form-group">
						<label>Filters (Explorium filter JSON)</label>
						<textarea class="form-control" id="ex-company-filters" rows="8" style="font-family: monospace; font-size: 12px;"></textarea>
					</div>
					<button class="btn btn-primary btn-sm" id="ex-search-companies">Search companies (free preview)</button>
					<span class="text-muted small" id="ex-company-status" style="margin-left: 10px;"></span>
					<div id="ex-company-results" style="margin-top: 14px;"></div>
				</div>

				<div class="frappe-card" style="padding: 16px; margin-bottom: 16px;">
					<h5>2. Find people at selected companies</h5>
					<div class="form-group">
						<label>Filters (Explorium filter JSON)</label>
						<textarea class="form-control" id="ex-people-filters" rows="6" style="font-family: monospace; font-size: 12px;"></textarea>
					</div>
					<button class="btn btn-primary btn-sm" id="ex-search-people" disabled>Select companies first</button>
					<span class="text-muted small" id="ex-people-status" style="margin-left: 10px;"></span>
					<div id="ex-people-results" style="margin-top: 14px;"></div>
				</div>

				<div class="frappe-card" style="padding: 16px;">
					<h5>3. Add to Leads</h5>
					<button class="btn btn-success btn-sm" id="ex-add-leads" disabled>Select people first</button>
					<div id="ex-lead-results" style="margin-top: 14px;"></div>
				</div>
			</div>
		`);

		this.page.body.find("#ex-company-filters").val(JSON.stringify(DEFAULT_COMPANY_FILTERS, null, 2));
		this.page.body.find("#ex-people-filters").val(JSON.stringify(DEFAULT_PEOPLE_FILTERS, null, 2));

		this.page.body.find("#ex-search-companies").on("click", () => this.searchCompanies());
		this.page.body.find("#ex-search-people").on("click", () => this.searchPeople());
		this.page.body.find("#ex-add-leads").on("click", () => this.addToLeads());
	}

	parseFilters(selector) {
		const raw = this.page.body.find(selector).val();
		try {
			const parsed = JSON.parse(raw || "{}");
			return parsed.filters || parsed;
		} catch (error) {
			frappe.msgprint({ title: "Invalid filter JSON", message: error.message, indicator: "red" });
			return null;
		}
	}

	searchCompanies() {
		const filters = this.parseFilters("#ex-company-filters");
		if (!filters) return;
		const status = this.page.body.find("#ex-company-status");
		status.text("Searching…");
		frappe.call({
			method: "lex.explorium.search_businesses",
			args: { filters, page: 1, page_size: 50 },
			freeze: true,
		}).then((r) => {
			this.companies = (r.message && r.message.results) || [];
			this.selectedCompanyIds = new Set();
			status.text(`${this.companies.length} shown (of ${(r.message && r.message.total_results) || 0} matching)`);
			this.renderCompanies();
			this.updatePeopleButton();
		}).catch(() => status.text("Search failed."));
	}

	renderCompanies() {
		const container = this.page.body.find("#ex-company-results");
		if (!this.companies.length) {
			container.html('<p class="text-muted">No companies matched yet.</p>');
			return;
		}
		const rows = this.companies.map((company) => `
			<tr>
				<td><input type="checkbox" class="ex-company-check" data-business-id="${this.esc(company.business_id)}"></td>
				<td>${this.esc(company.name || company.company_name)}</td>
				<td>${this.esc(company.website || company.domain || "")}</td>
				<td>${this.esc(company.number_of_employees_range || company.company_size || "")}</td>
				<td>${this.esc(company.country_name || "")}</td>
			</tr>
		`).join("");
		container.html(`
			<table class="table table-bordered table-sm">
				<thead><tr><th></th><th>Company</th><th>Website</th><th>Size</th><th>Country</th></tr></thead>
				<tbody>${rows}</tbody>
			</table>
		`);
		container.find(".ex-company-check").on("change", (event) => {
			const id = event.currentTarget.dataset.businessId;
			if (event.currentTarget.checked) this.selectedCompanyIds.add(id);
			else this.selectedCompanyIds.delete(id);
			this.updatePeopleButton();
		});
	}

	updatePeopleButton() {
		const button = this.page.body.find("#ex-search-people");
		const count = this.selectedCompanyIds.size;
		button.prop("disabled", count === 0);
		button.text(count ? `Search people at ${count} selected companies` : "Select companies first");
	}

	searchPeople() {
		const filters = this.parseFilters("#ex-people-filters");
		if (!filters) return;
		const status = this.page.body.find("#ex-people-status");
		status.text("Searching…");
		frappe.call({
			method: "lex.explorium.search_prospects",
			args: { business_ids: Array.from(this.selectedCompanyIds), filters, page: 1, page_size: 50 },
			freeze: true,
		}).then((r) => {
			this.prospects = (r.message && r.message.results) || [];
			status.text(`${this.prospects.length} shown (of ${(r.message && r.message.total_results) || 0} matching)`);
			this.renderPeople();
		}).catch(() => status.text("Search failed."));
	}

	renderPeople() {
		const container = this.page.body.find("#ex-people-results");
		if (!this.prospects.length) {
			container.html('<p class="text-muted">No people matched yet.</p>');
			this.page.body.find("#ex-add-leads").prop("disabled", true).text("Select people first");
			return;
		}
		const rows = this.prospects.map((prospect, index) => `
			<tr>
				<td><input type="checkbox" class="ex-prospect-check" data-index="${index}" checked></td>
				<td>${this.esc(prospect.full_name)}</td>
				<td>${this.esc(prospect.job_title)}</td>
				<td>${this.esc(prospect.company_name)}</td>
				<td>${this.esc(prospect.city)}</td>
			</tr>
		`).join("");
		container.html(`
			<table class="table table-bordered table-sm">
				<thead><tr><th></th><th>Name</th><th>Job title</th><th>Company</th><th>City</th></tr></thead>
				<tbody>${rows}</tbody>
			</table>
		`);
		container.find(".ex-prospect-check").on("change", () => this.updateAddButton());
		this.updateAddButton();
	}

	selectedProspects() {
		const checked = this.page.body.find(".ex-prospect-check:checked").toArray().map((el) => parseInt(el.dataset.index, 10));
		return checked.map((index) => this.prospects[index]);
	}

	updateAddButton() {
		const count = this.selectedProspects().length;
		const button = this.page.body.find("#ex-add-leads");
		button.prop("disabled", count === 0);
		button.text(count ? `Add ${count} selected to Leads (spends ${count} credit${count === 1 ? "" : "s"})` : "Select people first");
	}

	addToLeads() {
		const selected = this.selectedProspects();
		if (!selected.length) return;
		frappe.confirm(
			`This looks up real contact details for ${selected.length} people, spending ${selected.length} Explorium credit${selected.length === 1 ? "" : "s"}. Continue?`,
			() => {
				frappe.call({
					method: "lex.explorium.create_leads_from_prospects",
					args: { prospects: selected },
					freeze: true,
					freeze_message: "Enriching contact details and creating Leads…",
				}).then((r) => {
					const result = r.message || {};
					const link = (name) => `<a href="/app/lead/${encodeURIComponent(name)}" target="_blank">${this.esc(name)}</a>`;
					const parts = [];
					if (result.created && result.created.length) parts.push(`<p><strong>Created:</strong> ${result.created.map(link).join(", ")}</p>`);
					if (result.updated && result.updated.length) parts.push(`<p><strong>Updated:</strong> ${result.updated.map(link).join(", ")}</p>`);
					if (result.skipped && result.skipped.length) parts.push(`<p><strong>Skipped (no email found):</strong> ${result.skipped.map((s) => this.esc(s.name)).join(", ")}</p>`);
					this.page.body.find("#ex-lead-results").html(parts.join("") || '<p class="text-muted">Nothing added.</p>');
				});
			}
		);
	}
}
