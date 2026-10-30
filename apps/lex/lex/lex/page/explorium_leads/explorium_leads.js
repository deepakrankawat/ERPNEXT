frappe.pages["explorium-leads"].on_page_load = (wrapper) => {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Explorium B2B Prospecting & Leads",
		single_column: true,
	});
	wrapper.explorium_leads = new ExploriumLeadsPage(page);
};

const DEFAULT_COMPANY_FILTERS = {
	filters: {
		country_code: { values: ["CA"] },
		company_size: { values: ["11-50", "51-200"] },
		linkedin_category: { values: ["law practice", "legal services", "alternative dispute resolution", "outsourcing and offshoring consulting"] },
		website_keywords: { values: ["law firm", "lawyers", "legal counsel", "litigation", "corporate law", "legal process outsourcing", "contract lifecycle management"] },
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
		// Company State & Pagination
		this.companies = [];
		this.selectedCompanyIds = new Set();
		this.companyPage = 1;
		this.companyPageSize = 25;
		this.companyTotalPages = 1;
		this.companyTotalResults = 0;

		// People State & Pagination
		this.prospects = [];
		this.selectedProspectsMap = new Map(); // Keyed by prospect_id to preserve selection across pages!
		this.peoplePage = 1;
		this.peoplePageSize = 25;
		this.peopleTotalPages = 1;
		this.peopleTotalResults = 0;

		this.statusInfo = null;
		this.init();
	}

	init() {
		this.page.set_primary_action(__("Reset Search"), () => this.resetFilters(), "octicon octicon-sync");
		this.page.add_button(__("Configure API Key"), () => this.showKeyConfigDialog());
		this.loadStatus();
	}

	loadStatus() {
		frappe.call({
			method: "lex.explorium.get_explorium_status",
			callback: (r) => {
				this.statusInfo = r.message || {};
				this.render();
			}
		});
	}

	esc(value) {
		return frappe.utils.escape_html(value == null ? "" : String(value));
	}

	render() {
		const st = this.statusInfo || {};
		const isConfigured = Boolean(st.is_configured);

		this.page.body.html(`
			<div class="explorium-leads" style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
				<!-- Top Status & Cost Guard Banner -->
				<div class="card" style="border: 1px solid #e2e8f0; border-radius: 12px; padding: 18px 24px; margin-bottom: 20px; background: #ffffff; box-shadow: 0 1px 3px rgba(0,0,0,0.03);">
					<div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
						<div>
							<h4 style="margin: 0; font-size: 18px; font-weight: 700; color: #0f172a;">
								⚡ Explorium B2B Lead Generator
							</h4>
							<p style="margin: 4px 0 0 0; font-size: 13px; color: #64748b;">
								Browse up to 499+ records with 0-credit free preview & pagination. Credits are spent only when contact details are unlocked.
							</p>
						</div>
						<div style="display: flex; align-items: center; gap: 10px;">
							<span class="badge ${isConfigured ? 'badge-success' : 'badge-warning'}" style="padding: 6px 12px; font-size: 12px; border-radius: 20px;">
								● ${isConfigured ? `API Key Active (${this.esc(st.masked_key)})` : 'Demo / Sandbox Mode (.env ready)'}
							</span>
						</div>
					</div>

					<!-- Pricing Transparency Strip -->
					<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-top: 16px; padding-top: 14px; border-top: 1px solid #f1f5f9;">
						<div style="background: #f8fafc; border-radius: 8px; padding: 10px 14px; border: 1px solid #e2e8f0;">
							<span style="font-size: 11px; font-weight: 700; color: #059669; text-transform: uppercase;">Step 1: Company Search</span>
							<div style="font-size: 15px; font-weight: 700; color: #0f172a; margin-top: 2px;">0 Credits (100% Free)</div>
							<span style="font-size: 11px; color: #64748b;">Browse pages up to 499 companies</span>
						</div>
						<div style="background: #f8fafc; border-radius: 8px; padding: 10px 14px; border: 1px solid #e2e8f0;">
							<span style="font-size: 11px; font-weight: 700; color: #059669; text-transform: uppercase;">Step 2: People Search</span>
							<div style="font-size: 15px; font-weight: 700; color: #0f172a; margin-top: 2px;">0 Credits (100% Free)</div>
							<span style="font-size: 11px; color: #64748b;">Browse pages up to 499 decision-makers</span>
						</div>
						<div style="background: #f0fdf4; border-radius: 8px; padding: 10px 14px; border: 1px solid #86efac;">
							<span style="font-size: 11px; font-weight: 700; color: #15803d; text-transform: uppercase;">Step 3: Contact Unlock</span>
							<div style="font-size: 15px; font-weight: 700; color: #166534; margin-top: 2px;">1 Credit per Lead</div>
							<span style="font-size: 11px; color: #15803d;">Verified Work Email + Phone</span>
						</div>
					</div>
				</div>

				<!-- Step 1: Find Companies -->
				<div class="card" style="border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; margin-bottom: 20px; background: #ffffff;">
					<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
						<h5 style="margin: 0; font-size: 16px; font-weight: 700; color: #0f172a;">1. Find Target Companies <span style="font-size: 12px; color: #059669; font-weight: 600;">(Free Preview)</span></h5>
						<button class="btn btn-xs btn-default" id="toggle-advanced-company-json">⚙ Advanced JSON View</button>
					</div>

					<!-- Visual Filters Form -->
					<div id="company-visual-filters" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin-bottom: 14px;">
						<div class="form-group" style="margin: 0;">
							<label style="font-size: 12px; font-weight: 600; color: #475569;">Target Country</label>
							<select class="form-control form-control-sm" id="cf-country">
								<option value="CA" selected>🇨🇦 Canada</option>
								<option value="US">🇺🇸 United States</option>
								<option value="GB">🇬🇧 United Kingdom</option>
								<option value="AU">🇦🇺 Australia</option>
								<option value="IN">🇮🇳 India</option>
							</select>
						</div>

						<div class="form-group" style="margin: 0;">
							<label style="font-size: 12px; font-weight: 600; color: #475569;">Company Headcount</label>
							<select class="form-control form-control-sm" id="cf-size">
								<option value="11-50,51-200" selected>11 - 200 Employees (Mid-Market)</option>
								<option value="1-10">1 - 10 (Boutique / Startup)</option>
								<option value="201-500,500+">201+ Employees (Enterprise)</option>
								<option value="all">All Sizes</option>
							</select>
						</div>

						<div class="form-group" style="margin: 0;">
							<label style="font-size: 12px; font-weight: 600; color: #475569;">Industry / Practice Area</label>
							<select class="form-control form-control-sm" id="cf-category">
								<option value="legal" selected>Legal Services & Law Practice</option>
								<option value="consulting">Outsourcing & Management Consulting</option>
								<option value="tech">Corporate & Technology</option>
							</select>
						</div>

						<div class="form-group" style="margin: 0;">
							<label style="font-size: 12px; font-weight: 600; color: #475569;">Keywords / Niche</label>
							<input type="text" class="form-control form-control-sm" id="cf-keywords" value="litigation, corporate law, legal ops, contract review" placeholder="e.g. litigation, compliance" />
						</div>
					</div>

					<div class="form-group" id="company-json-container" style="display: none;">
						<label style="font-size: 12px; font-weight: 600; color: #475569;">Custom Raw Filter JSON</label>
						<textarea class="form-control" id="ex-company-filters" rows="6" style="font-family: monospace; font-size: 12px;"></textarea>
					</div>

					<div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;">
						<div style="display: flex; align-items: center; gap: 12px;">
							<button class="btn btn-primary btn-sm" id="ex-search-companies">🔍 Search Companies (0 Credits)</button>
							<span class="text-muted small" id="ex-company-status"></span>
						</div>
						<div style="display: flex; align-items: center; gap: 8px;">
							<label style="font-size: 12px; color: #64748b; margin: 0;">Page Size:</label>
							<select class="form-control form-control-sm" id="cf-page-size" style="width: 80px; display: inline-block;">
								<option value="25" ${this.companyPageSize === 25 ? 'selected' : ''}>25</option>
								<option value="50" ${this.companyPageSize === 50 ? 'selected' : ''}>50</option>
								<option value="100" ${this.companyPageSize === 100 ? 'selected' : ''}>100</option>
							</select>
						</div>
					</div>

					<div id="ex-company-results" style="margin-top: 16px;"></div>
				</div>

				<!-- Step 2: Find People -->
				<div class="card" style="border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; margin-bottom: 20px; background: #ffffff;">
					<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
						<h5 style="margin: 0; font-size: 16px; font-weight: 700; color: #0f172a;">2. Find People & Decision-Makers <span style="font-size: 12px; color: #059669; font-weight: 600;">(Free Preview)</span></h5>
						<button class="btn btn-xs btn-default" id="toggle-advanced-people-json">⚙ Advanced JSON View</button>
					</div>

					<div id="people-visual-filters" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin-bottom: 14px;">
						<div class="form-group" style="margin: 0;">
							<label style="font-size: 12px; font-weight: 600; color: #475569;">Seniority / Job Level</label>
							<select class="form-control form-control-sm" id="pf-level">
								<option value="c-suite,director,manager" selected>C-Suite, Directors & Managers</option>
								<option value="c-suite">C-Suite Only (GC, CEO, CLO)</option>
								<option value="director,manager">Directors & Practice Heads</option>
							</select>
						</div>

						<div class="form-group" style="margin: 0;">
							<label style="font-size: 12px; font-weight: 600; color: #475569;">Target Department</label>
							<select class="form-control form-control-sm" id="pf-department">
								<option value="legal,executive,business_development" selected>Legal, Executive & BD</option>
								<option value="legal">Legal & Compliance Only</option>
								<option value="operations">Operations & Procurement</option>
							</select>
						</div>
					</div>

					<div class="form-group" id="people-json-container" style="display: none;">
						<textarea class="form-control" id="ex-people-filters" rows="4" style="font-family: monospace; font-size: 12px;"></textarea>
					</div>

					<div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;">
						<div style="display: flex; align-items: center; gap: 12px;">
							<button class="btn btn-primary btn-sm" id="ex-search-people" disabled>Select companies first</button>
							<span class="text-muted small" id="ex-people-status"></span>
						</div>
						<div style="display: flex; align-items: center; gap: 8px;">
							<label style="font-size: 12px; color: #64748b; margin: 0;">Page Size:</label>
							<select class="form-control form-control-sm" id="pf-page-size" style="width: 80px; display: inline-block;">
								<option value="25" ${this.peoplePageSize === 25 ? 'selected' : ''}>25</option>
								<option value="50" ${this.peoplePageSize === 50 ? 'selected' : ''}>50</option>
								<option value="100" ${this.peoplePageSize === 100 ? 'selected' : ''}>100</option>
							</select>
						</div>
					</div>

					<div id="ex-people-results" style="margin-top: 16px;"></div>
				</div>

				<!-- Step 3: Add to Leads & Enrich Contacts -->
				<div class="card" style="border: 1px solid #86efac; border-radius: 12px; padding: 20px; background: #f0fdf4;">
					<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
						<div>
							<h5 style="margin: 0; font-size: 16px; font-weight: 700; color: #166534;">3. Unlock Verified Contacts & Create CRM Leads</h5>
							<p style="margin: 2px 0 0 0; font-size: 12px; color: #15803d;">
								Fetches verified business email & direct phone numbers. Exactly 1 credit per contact.
							</p>
						</div>
						<div id="cost-calculator-badge" style="font-size: 13px; font-weight: 700; color: #166534; background: #ffffff; padding: 6px 12px; border-radius: 8px; border: 1px solid #bbf7d0;">
							0 Leads selected across all pages (0 Credits)
						</div>
					</div>

					<button class="btn btn-success btn-sm" id="ex-add-leads" disabled>
						Select people first
					</button>

					<div id="ex-lead-results" style="margin-top: 16px;"></div>
				</div>
			</div>
		`);

		this.page.body.find("#ex-company-filters").val(JSON.stringify(DEFAULT_COMPANY_FILTERS, null, 2));
		this.page.body.find("#ex-people-filters").val(JSON.stringify(DEFAULT_PEOPLE_FILTERS, null, 2));

		this.attachEvents();
	}

	attachEvents() {
		this.page.body.find("#toggle-advanced-company-json").on("click", () => {
			this.page.body.find("#company-json-container").toggle();
		});

		this.page.body.find("#toggle-advanced-people-json").on("click", () => {
			this.page.body.find("#people-json-container").toggle();
		});

		this.page.body.find("#cf-page-size").on("change", (e) => {
			this.companyPageSize = parseInt($(e.target).val(), 10) || 25;
			this.companyPage = 1;
			if (this.companies.length) this.searchCompanies(1);
		});

		this.page.body.find("#pf-page-size").on("change", (e) => {
			this.peoplePageSize = parseInt($(e.target).val(), 10) || 25;
			this.peoplePage = 1;
			if (this.prospects.length) this.searchPeople(1);
		});

		this.page.body.find("#ex-search-companies").on("click", () => this.searchCompanies(1));
		this.page.body.find("#ex-search-people").on("click", () => this.searchPeople(1));
		this.page.body.find("#ex-add-leads").on("click", () => this.addToLeads());
	}

	buildCompanyFilters() {
		const jsonBox = this.page.body.find("#ex-company-filters");
		if (this.page.body.find("#company-json-container").is(":visible") && jsonBox.val().trim()) {
			try {
				const parsed = JSON.parse(jsonBox.val().trim());
				return parsed.filters || parsed;
			} catch (e) {}
		}

		const country = this.page.body.find("#cf-country").val() || "CA";
		const sizeVal = this.page.body.find("#cf-size").val();
		const sizes = sizeVal === "all" ? [] : sizeVal.split(",");
		const kwInput = this.page.body.find("#cf-keywords").val() || "";
		const keywords = kwInput.split(",").map(s => s.trim()).filter(Boolean);

		const f = {
			country_code: { values: [country] },
			has_website: { value: true },
		};
		if (sizes.length) f.company_size = { values: sizes };
		if (keywords.length) f.website_keywords = { values: keywords };
		f.linkedin_category = { values: ["law practice", "legal services", "alternative dispute resolution", "outsourcing and offshoring consulting"] };

		jsonBox.val(JSON.stringify({ filters: f }, null, 2));
		return f;
	}

	buildPeopleFilters() {
		const jsonBox = this.page.body.find("#ex-people-filters");
		if (this.page.body.find("#people-json-container").is(":visible") && jsonBox.val().trim()) {
			try {
				const parsed = JSON.parse(jsonBox.val().trim());
				return parsed.filters || parsed;
			} catch (e) {}
		}

		const levels = (this.page.body.find("#pf-level").val() || "c-suite,director,manager").split(",");
		const depts = (this.page.body.find("#pf-department").val() || "legal,executive,business_development").split(",");

		const f = {
			job_level: { values: levels },
			job_department: { values: depts },
		};
		jsonBox.val(JSON.stringify({ filters: f }, null, 2));
		return f;
	}

	searchCompanies(targetPage = 1) {
		this.companyPage = targetPage;
		const filters = this.buildCompanyFilters();
		const status = this.page.body.find("#ex-company-status");
		status.text(`Searching page ${this.companyPage} (0 credits)...`);

		frappe.call({
			method: "lex.explorium.search_businesses",
			args: {
				filters,
				page: this.companyPage,
				page_size: this.companyPageSize,
			},
			freeze: true,
			freeze_message: `Loading company page ${this.companyPage} (0 credits)...`,
		}).then((r) => {
			const res = r.message || {};
			this.companies = res.results || [];
			this.companyTotalResults = res.total_results || this.companies.length;
			this.companyTotalPages = res.total_pages || Math.ceil(this.companyTotalResults / this.companyPageSize) || 1;

			status.html(`✔ Total matching: <strong>${this.companyTotalResults}</strong> companies · Page <strong>${this.companyPage}</strong> of <strong>${this.companyTotalPages}</strong>`);
			this.renderCompanies();
			this.updatePeopleButton();
		}).catch(() => status.text("Company search failed."));
	}

	renderCompanies() {
		const container = this.page.body.find("#ex-company-results");
		if (!this.companies.length) {
			container.html('<p class="text-muted small">No target companies matched the current filters.</p>');
			return;
		}

		const startIdx = (this.companyPage - 1) * this.companyPageSize + 1;
		const endIdx = Math.min(this.companyPage * this.companyPageSize, this.companyTotalResults);

		const rows = this.companies.map((company) => {
			const isChecked = this.selectedCompanyIds.has(String(company.business_id));
			return `
				<tr style="${isChecked ? 'background: #eff6ff;' : ''}">
					<td style="width: 38px; text-align: center;">
						<input type="checkbox" class="ex-company-check" data-business-id="${this.esc(company.business_id)}" ${isChecked ? 'checked' : ''}>
					</td>
					<td>
						<strong>${this.esc(company.name || company.company_name)}</strong>
						<div class="text-muted small">${this.esc(company.industry || 'Legal Practice')}</div>
					</td>
					<td>
						${company.website ? `<a href="${this.esc(company.website)}" target="_blank" style="color:#0284c7;">${this.esc(company.domain || company.website)} ↗</a>` : '<span class="text-muted">-</span>'}
					</td>
					<td><span class="badge badge-light" style="font-size:12px;">${this.esc(company.number_of_employees_range || company.company_size || "Mid-size")}</span></td>
					<td>${this.esc(company.city ? `${company.city}, ` : '')}${this.esc(company.country_name || "")}</td>
				</tr>
			`;
		}).join("");

		// Pagination Bar HTML
		const paginationHtml = `
			<div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; background: #f8fafc; border-top: 1px solid #e2e8f0; font-size: 13px;">
				<div style="color: #64748b;">
					Showing <strong>${startIdx} - ${endIdx}</strong> of <strong>${this.companyTotalResults}</strong> companies
					${this.selectedCompanyIds.size ? `· <span class="badge badge-primary" style="font-size:12px;">${this.selectedCompanyIds.size} Selected</span>` : ''}
				</div>
				<div style="display: flex; align-items: center; gap: 8px;">
					<button class="btn btn-xs btn-default comp-prev-btn" ${this.companyPage <= 1 ? 'disabled' : ''}>
						◀ Previous
					</button>
					<span style="font-weight: 600; color: #0f172a;">
						Page ${this.companyPage} of ${this.companyTotalPages}
					</span>
					<button class="btn btn-xs btn-default comp-next-btn" ${this.companyPage >= this.companyTotalPages ? 'disabled' : ''}>
						Next ▶
					</button>
				</div>
			</div>
		`;

		container.html(`
			<div style="border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden;">
				<div class="table-responsive" style="max-height: 380px; overflow-y: auto;">
					<table class="table table-hover table-sm" style="margin: 0;">
						<thead style="background: #f8fafc; position: sticky; top: 0; z-index: 2;">
							<tr>
								<th style="width: 38px; text-align: center;">
									<input type="checkbox" id="select-page-companies">
								</th>
								<th>Company</th>
								<th>Website</th>
								<th>Size</th>
								<th>Location</th>
							</tr>
						</thead>
						<tbody>${rows}</tbody>
					</table>
				</div>
				${paginationHtml}
			</div>
		`);

		// Select all on current page
		container.find("#select-page-companies").on("change", (e) => {
			const checked = e.target.checked;
			container.find(".ex-company-check").each((_, el) => {
				const id = String(el.dataset.businessId);
				if (checked) this.selectedCompanyIds.add(id);
				else this.selectedCompanyIds.delete(id);
				$(el).prop("checked", checked);
			});
			this.renderCompanies();
			this.updatePeopleButton();
		});

		// Single Checkbox toggle (preserves in Set across all pages)
		container.find(".ex-company-check").on("change", (event) => {
			const id = String(event.currentTarget.dataset.businessId);
			if (event.currentTarget.checked) this.selectedCompanyIds.add(id);
			else this.selectedCompanyIds.delete(id);
			this.updatePeopleButton();
		});

		// Pagination button clicks
		container.find(".comp-prev-btn").on("click", () => {
			if (this.companyPage > 1) this.searchCompanies(this.companyPage - 1);
		});

		container.find(".comp-next-btn").on("click", () => {
			if (this.companyPage < this.companyTotalPages) this.searchCompanies(this.companyPage + 1);
		});
	}

	updatePeopleButton() {
		const button = this.page.body.find("#ex-search-people");
		const count = this.selectedCompanyIds.size;
		button.prop("disabled", count === 0);
		button.text(count ? `👥 Search Decision-Makers at ${count} selected companies (0 Credits)` : "Select companies first");
	}

	searchPeople(targetPage = 1) {
		this.peoplePage = targetPage;
		const filters = this.buildPeopleFilters();
		const status = this.page.body.find("#ex-people-status");
		status.text(`Searching decision-makers page ${this.peoplePage} (0 credits)...`);

		frappe.call({
			method: "lex.explorium.search_prospects",
			args: {
				business_ids: Array.from(this.selectedCompanyIds),
				filters,
				page: this.peoplePage,
				page_size: this.peoplePageSize,
			},
			freeze: true,
			freeze_message: `Loading decision-makers page ${this.peoplePage} (0 credits)...`,
		}).then((r) => {
			const res = r.message || {};
			this.prospects = res.results || [];
			this.peopleTotalResults = res.total_results || this.prospects.length;
			this.peopleTotalPages = res.total_pages || Math.ceil(this.peopleTotalResults / this.peoplePageSize) || 1;

			status.html(`✔ Total matching: <strong>${this.peopleTotalResults}</strong> decision-makers · Page <strong>${this.peoplePage}</strong> of <strong>${this.peopleTotalPages}</strong>`);
			this.renderPeople();
		}).catch(() => status.text("People search failed."));
	}

	renderPeople() {
		const container = this.page.body.find("#ex-people-results");
		if (!this.prospects.length) {
			container.html('<p class="text-muted small">No people matched the selected companies yet.</p>');
			this.updateAddButton();
			return;
		}

		const startIdx = (this.peoplePage - 1) * this.peoplePageSize + 1;
		const endIdx = Math.min(this.peoplePage * this.peoplePageSize, this.peopleTotalResults);

		const rows = this.prospects.map((prospect) => {
			const isInCrm = Boolean(prospect.is_in_crm);
			const pid = String(prospect.prospect_id);
			const isChecked = this.selectedProspectsMap.has(pid);

			return `
				<tr style="${isChecked ? 'background: #f0fdf4;' : (isInCrm ? 'background: #fffbeb;' : '')}">
					<td style="width: 38px; text-align: center;">
						<input type="checkbox" class="ex-prospect-check" data-prospect-id="${this.esc(pid)}" ${isChecked ? 'checked' : ''}>
					</td>
					<td>
						<strong>${this.esc(prospect.full_name)}</strong>
						${isInCrm ? `
							<span class="badge badge-warning" style="margin-left: 6px; font-size: 11px;">
								⚠️ Already in CRM (${this.esc(prospect.existing_lead_id || 'Lead')})
							</span>
						` : ''}
					</td>
					<td><span class="badge badge-info" style="font-size: 12px;">${this.esc(prospect.job_title || 'Counsel')}</span></td>
					<td>${this.esc(prospect.company_name)}</td>
					<td>${this.esc(prospect.city ? `${prospect.city}, ` : '')}${this.esc(prospect.country_name || "")}</td>
				</tr>
			`;
		}).join("");

		// People Pagination Bar HTML
		const paginationHtml = `
			<div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; background: #f8fafc; border-top: 1px solid #e2e8f0; font-size: 13px;">
				<div style="color: #64748b;">
					Showing <strong>${startIdx} - ${endIdx}</strong> of <strong>${this.peopleTotalResults}</strong> decision-makers
					${this.selectedProspectsMap.size ? `· <span class="badge badge-success" style="font-size:12px;">${this.selectedProspectsMap.size} Selected Total</span>` : ''}
				</div>
				<div style="display: flex; align-items: center; gap: 8px;">
					<button class="btn btn-xs btn-default ppl-prev-btn" ${this.peoplePage <= 1 ? 'disabled' : ''}>
						◀ Previous
					</button>
					<span style="font-weight: 600; color: #0f172a;">
						Page ${this.peoplePage} of ${this.peopleTotalPages}
					</span>
					<button class="btn btn-xs btn-default ppl-next-btn" ${this.peoplePage >= this.peopleTotalPages ? 'disabled' : ''}>
						Next ▶
					</button>
				</div>
			</div>
		`;

		container.html(`
			<div style="border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden;">
				<div class="table-responsive" style="max-height: 400px; overflow-y: auto;">
					<table class="table table-hover table-sm" style="margin: 0;">
						<thead style="background: #f8fafc; position: sticky; top: 0; z-index: 2;">
							<tr>
								<th style="width: 38px; text-align: center;">
									<input type="checkbox" id="select-page-prospects">
								</th>
								<th>Name & Status</th>
								<th>Role / Job Title</th>
								<th>Company</th>
								<th>Location</th>
							</tr>
						</thead>
						<tbody>${rows}</tbody>
					</table>
				</div>
				${paginationHtml}
			</div>
		`);

		// Select all on current page (only select those NOT in CRM to protect user credits)
		container.find("#select-page-prospects").on("change", (e) => {
			const checked = e.target.checked;
			this.prospects.forEach((p) => {
				const pid = String(p.prospect_id);
				if (checked) {
					if (!p.is_in_crm) this.selectedProspectsMap.set(pid, p);
				} else {
					this.selectedProspectsMap.delete(pid);
				}
			});
			this.renderPeople();
			this.updateAddButton();
		});

		// Single Checkbox toggle (preserves Map across all pages)
		container.find(".ex-prospect-check").on("change", (event) => {
			const pid = String(event.currentTarget.dataset.prospectId);
			const p = this.prospects.find(item => String(item.prospect_id) === pid);
			if (event.currentTarget.checked) {
				if (p) this.selectedProspectsMap.set(pid, p);
			} else {
				this.selectedProspectsMap.delete(pid);
			}
			this.updateAddButton();
		});

		// Pagination navigation
		container.find(".ppl-prev-btn").on("click", () => {
			if (this.peoplePage > 1) this.searchPeople(this.peoplePage - 1);
		});

		container.find(".ppl-next-btn").on("click", () => {
			if (this.peoplePage < this.peopleTotalPages) this.searchPeople(this.peoplePage + 1);
		});

		this.updateAddButton();
	}

	selectedProspects() {
		return Array.from(this.selectedProspectsMap.values());
	}

	updateAddButton() {
		const count = this.selectedProspectsMap.size;
		const button = this.page.body.find("#ex-add-leads");
		const badge = this.page.body.find("#cost-calculator-badge");

		button.prop("disabled", count === 0);
		if (count > 0) {
			const approxCost = `~₹${count * 6} ($${(count * 0.08).toFixed(2)})`;
			button.html(`🚀 Unlock Email/Phone & Create ${count} Leads (Spends <strong>${count} Credit${count === 1 ? '' : 's'}</strong>)`);
			badge.html(`<strong>${count}</strong> Leads Selected across all pages → Cost: <strong>${count} Credit${count === 1 ? '' : 's'}</strong> (${approxCost})`);
		} else {
			button.text("Select people first");
			badge.text("0 Leads selected across all pages (0 Credits)");
		}
	}

	addToLeads() {
		const selected = this.selectedProspects();
		if (!selected.length) return;

		const approxCost = `~₹${selected.length * 6} ($${(selected.length * 0.08).toFixed(2)})`;
		frappe.confirm(
			`Are you sure you want to unlock verified contact details (Email + Phone) for <strong>${selected.length} people</strong>?<br><br>
			• Credits spent: <strong>${selected.length} Explorium Credit${selected.length === 1 ? '' : 's'}</strong> (${approxCost})<br>
			• Action: Directly creates verified <strong>Leads</strong> in ERPNext CRM.`,
			() => {
				frappe.call({
					method: "lex.explorium.create_leads_from_prospects",
					args: { prospects: selected },
					freeze: true,
					freeze_message: `Enriching contact details for ${selected.length} prospects…`,
				}).then((r) => {
					const res = r.message || {};
					const link = (name) => `<a href="/app/lead/${encodeURIComponent(name)}" target="_blank" class="badge badge-success" style="font-size: 12px; margin: 2px;">✔ ${this.esc(name)}</a>`;
					
					let html = `
						<div class="alert alert-success" style="border-radius: 8px;">
							<strong>${this.esc(res.message || "Enrichment complete!")}</strong>
							<div style="margin-top: 8px;">
					`;

					if (res.created && res.created.length) {
						html += `<div style="margin-bottom: 6px;"><strong>Newly Created Leads:</strong> ${res.created.map(link).join(" ")}</div>`;
					}
					if (res.updated && res.updated.length) {
						html += `<div style="margin-bottom: 6px;"><strong>Updated Existing Leads:</strong> ${res.updated.map(link).join(" ")}</div>`;
					}
					if (res.skipped && res.skipped.length) {
						html += `<div class="text-muted small">Skipped: ${res.skipped.map(s => this.esc(s.name)).join(", ")}</div>`;
					}
					html += `</div></div>`;

					this.page.body.find("#ex-lead-results").html(html);
					this.selectedProspectsMap.clear();
					this.updateAddButton();
					this.renderPeople();
					frappe.show_alert({ message: __("{0} Leads successfully added to CRM!", [selected.length]), indicator: "green" });
				});
			}
		);
	}

	resetFilters() {
		this.selectedCompanyIds.clear();
		this.selectedProspectsMap.clear();
		this.companies = [];
		this.prospects = [];
		this.companyPage = 1;
		this.peoplePage = 1;
		this.render();
	}

	showKeyConfigDialog() {
		const st = this.statusInfo || {};
		const d = new frappe.ui.Dialog({
			title: __("Explorium API Key Configuration"),
			fields: [
				{
					fieldtype: "HTML",
					options: `
						<div class="alert alert-info">
							Explorium API key can be set in <code>.env</code> file:
							<br><code>EXPLORIUM_API_KEY=your_key_here</code>
							<br>or in <strong>Explorium Settings</strong> DocType.
						</div>
						<table class="table table-bordered table-sm">
							<tr><th>Variable</th><th>Current Status</th></tr>
							<tr><td>EXPLORIUM_API_KEY</td><td><code>${this.esc(st.masked_key || 'Not Set')}</code></td></tr>
							<tr><td>Configuration Source</td><td><code>${this.esc(st.source || '.env')}</code></td></tr>
						</table>
					`
				}
			],
			primary_action_label: __("Close"),
			primary_action: () => d.hide(),
		});
		d.show();
	}
}
