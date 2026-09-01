frappe.ui.form.on("LPO Job", {
	setup(frm) {
		frm.set_query("engagement", () => ({
			filters: { status: ["in", ["Draft", "Active"]] },
		}));
	},

	refresh(frm) {
		if (frm.is_new()) return;

		if (frm.doc.engagement) {
			frm.add_custom_button(__("Parent Matter"), () => {
				frappe.set_route("Form", "LPO Matter", frm.doc.engagement);
			}, __("View"));
		}
		if (frm.doc.intake_estimate) {
			frm.add_custom_button(__("Intake AI Estimate"), () => {
				frappe.set_route("Form", "LPO AI Document Estimate", frm.doc.intake_estimate);
			}, __("View"));
		}
		if (
			frm.doc.work_intake &&
			frm.doc.job_status === "Draft" &&
			(
				frappe.session.user === "Administrator" ||
				["System Manager", "LPO_Admin", "LPO_Manager"].some((role) => frappe.user.has_role(role))
			)
		) {
			frm.add_custom_button(__("Estimate Price & LexPoints"), () => {
				open_system_job_estimator(frm);
			}, __("Commercial")).addClass("btn-primary");
		}

		// AI Document Processing Suite for System Users
		frm.add_custom_button(__("Open AI Document Studio"), () => {
			open_job_ai_document_studio(frm);
		}, __("AI Document"));

		frm.add_custom_button(__("Run Multi-Service Pipeline"), () => {
			prompt_job_pipeline(frm);
		}, __("AI Document"));

		frm.add_custom_button(__("Finalize & Deliver Document"), () => {
			prompt_finalize_delivery(frm);
		}, __("AI Document"));
	},
});

async function open_system_job_estimator(frm) {
	const response = await frappe.call({
		method: "lex.work_intake.get_system_job_estimation_context",
		args: { job: frm.doc.name },
		freeze: true,
		freeze_message: __("Loading governed estimation context..."),
	});
	const context = response.message || {};
	if (!context.sla_accepted) {
		frappe.msgprint({
			title: __("SLA acceptance required"),
			message: __("The client must review and accept the SLA before a System User can upload a pricing document."),
			indicator: "orange",
		});
		return;
	}

	const accept = (context.allowed_extensions || []).join(",");
	const dialog = new frappe.ui.Dialog({
		title: __("AI Cost & LexPoint Estimate — {0}", [context.job_title || frm.doc.name]),
		size: "large",
		fields: [
			{
				fieldname: "estimate_context",
				fieldtype: "HTML",
				options: `
					<div class="alert alert-info mb-3">
						<strong>${__("Governed commercial estimation")}</strong><br>
						${__("The document is stored privately, security-scanned, and used only to calculate scope, price, delivery time and LexPoints. General legal AI analysis is not run by this action.")}
					</div>
					<div class="small text-muted mb-3">
						${__("Existing Job documents")}: <strong>${Number(context.document_count || 0)}</strong>
						· ${__("Clean")}: <strong>${Number(context.clean_document_count || 0)}</strong>
						· ${__("Current estimate")}: <strong>${frappe.utils.escape_html(context.current_estimate || __("None"))}</strong>
					</div>`,
			},
			{
				fieldname: "detailed_instructions",
				fieldtype: "Small Text",
				label: __("Detailed scope and instructions"),
				reqd: 1,
				default: context.detailed_instructions || frm.doc.task_description || "",
				description: __("At least 20 characters. These instructions become part of the auditable estimate evidence."),
			},
			{
				fieldname: "document_upload",
				fieldtype: "HTML",
				options: `
					<label class="control-label">${__("Add source document (optional when an existing clean document is available)")}</label>
					<input id="lex-system-estimate-file" type="file" class="form-control" accept="${frappe.utils.escape_html(accept)}">
					<p class="help-box small text-muted mt-2">${__("Allowed: PDF, DOC, DOCX, TXT, CSV, JPG and PNG. Maximum 10 MB.")}</p>`,
			},
		],
		primary_action_label: __("Upload, Scan & Estimate"),
		primary_action: async (values) => {
			const file = dialog.$wrapper.find("#lex-system-estimate-file")[0]?.files?.[0] || null;
			if (!file && !Number(context.document_count || 0)) {
				frappe.msgprint(__("Choose a document because this Job has no existing source documents."));
				return;
			}
			if (file && file.size > Number(context.max_upload_bytes || 10 * 1024 * 1024)) {
				frappe.msgprint(__("The document must not exceed 10 MB."));
				return;
			}
			dialog.disable_primary_action();
			try {
				const content = file ? await read_estimation_file(file) : null;
				const result = (await frappe.call({
					method: "lex.work_intake.estimate_system_job",
					args: {
						job: frm.doc.name,
						detailed_instructions: values.detailed_instructions,
						filename: file?.name || null,
						content,
					},
					freeze: true,
					freeze_message: __("Uploading securely, scanning and generating the governed estimate..."),
				})).message;
				dialog.hide();
				frappe.msgprint({
					title: __("Estimate generated"),
					indicator: result.low_confidence ? "orange" : "green",
					message: `
						<p><strong>${__("Required LexPoints")}:</strong> ${Number(result.required_lexpoints || 0)}</p>
						<p><strong>${__("Fixed quote")}:</strong> ${frappe.utils.escape_html(result.currency || "")} ${Number(result.quoted_amount || 0).toFixed(2)}</p>
						<p><strong>${__("Delivery timeline")}:</strong> ${Number(result.delivery_timeline_hours || 0)} ${__("hours")}</p>
						<p><strong>${__("Method")}:</strong> ${frappe.utils.escape_html(result.estimate_method || "")}</p>
						<p><strong>${__("Next status")}:</strong> ${frappe.utils.escape_html(result.pricing_approval_status || result.quote_status || "")}</p>`,
				});
				await frm.reload_doc();
			} finally {
				dialog.enable_primary_action();
			}
		},
	});
	dialog.show();
}

function read_estimation_file(file) {
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => resolve(reader.result);
		reader.onerror = () => reject(reader.error || new Error(__("Could not read the selected document.")));
		reader.readAsDataURL(file);
	});
}

function open_job_ai_document_studio(frm) {
	frappe.call({
		method: "lex.ai_document_engine.get_job_document_studio_context",
		args: { job_id: frm.doc.name },
		freeze: true,
		freeze_message: __("Loading AI Document Studio..."),
		callback: (r) => {
			if (!r.message) return;
			const ctx = r.message;
			show_studio_dialog(frm, ctx);
		}
	});
}

function show_studio_dialog(frm, ctx) {
	const job = ctx.job;
	const matter = ctx.matter;
	const processor = ctx.processor;
	const services = ctx.services || [];

	const extracted_text = processor.extracted_text || "(No document text extracted yet. Please attach a file or type content.)";
	const current_output = processor.final_output_text || "";

	const dialog = new frappe.ui.Dialog({
		title: __("📄 AI Document Processing Studio — {0}", [job.job_title || job.name]),
		size: "extra-large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "studio_html",
			}
		],
		primary_action_label: __("Save as Delivery Document & Finalize"),
		primary_action: () => {
			const final_text = dialog.$wrapper.find("#studio-editable-output").val() || "";
			if (!final_text.trim()) {
				frappe.msgprint(__("Deliverable output is empty. Run an AI service first or write your deliverable text."));
				return;
			}
			show_advanced_export_dialog(frm, final_text, dialog);
		}
	});

	const html = `
		<div class="job-doc-studio" style="font-family:var(--font-stack); background:#f8fafc; border-radius:8px; border:1px solid #e2e8f0; overflow:hidden;">
			<!-- Header -->
			<div style="background:#0f172a; color:#ffffff; padding:12px 18px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
				<div>
					<strong style="font-size:14px; color:#fff;">Matter:</strong> <span style="color:#cbd5e1;">${frappe.utils.escape_html(matter.matter_title || "LPO Matter")}</span> |
					<strong style="font-size:14px; color:#fff;">Job:</strong> <span style="color:#38bdf8;">${frappe.utils.escape_html(job.job_title)}</span>
				</div>
				<div style="font-size:12px; color:#94a3b8; display:flex; gap:12px; align-items:center;">
					<span>Words: <strong style="color:#fff;" id="studio-word-count">${processor.word_count || 0}</strong></span>
					<span style="background:rgba(2,132,199,0.25); color:#38bdf8; border:1px solid rgba(56,189,248,0.4); padding:2px 8px; border-radius:999px; font-weight:600;">
						⚡ Tokens Used: ${job.ai_tokens_used || 0} / ${job.ai_token_budget || 1000}
					</span>
				</div>
			</div>

			<!-- Dual-Pane Workspace -->
			<div style="display:grid; grid-template-columns: 1fr 1.2fr; gap:14px; padding:14px;">
				<!-- Left: Source Document Panel -->
				<div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:12px; display:flex; flex-direction:column; max-height:460px;">
					<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; padding-bottom:6px; border-bottom:1px solid #f1f5f9;">
						<strong style="font-size:13px; color:#1e293b;">📥 Source Document</strong>
						<button class="btn btn-xs btn-default" id="btn-reextract-doc" style="font-size:11px;">🔄 Extract / Refresh Text</button>
					</div>
					<textarea id="studio-source-doc-text" class="form-control" style="flex:1; font-size:12px; line-height:1.5; resize:none; background:#f8fafc; font-family:monospace;" placeholder="${__("Paste document text or click refresh to extract from attached source document...")}">${frappe.utils.escape_html(processor.extracted_text || "")}</textarea>
				</div>

				<!-- Right: AI Services & Output Editor -->
				<div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:12px; display:flex; flex-direction:column; max-height:460px;">
					<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; padding-bottom:6px; border-bottom:1px solid #f1f5f9;">
						<strong style="font-size:13px; color:#1e293b;">⚡ Apply AI Services</strong>
						<span style="font-size:11px; color:#0284c7; font-weight:600;">System User Mode</span>
					</div>

					<!-- Quick Services Ribbon -->
					<div style="display:flex; flex-wrap:wrap; gap:5px; margin-bottom:10px;">
						<button class="btn btn-xs btn-default btn-launch-srv" data-code="SUMMARIZE" style="font-size:11px; font-weight:600;">📑 Summarize</button>
						<button class="btn btn-xs btn-default btn-launch-srv" data-code="RISK_ANALYSIS" style="font-size:11px; font-weight:600;">⚠️ Risk Audit</button>
						<button class="btn btn-xs btn-default btn-launch-srv" data-code="EXTRACT_METADATA" style="font-size:11px; font-weight:600;">📊 Key Entities</button>
						<button class="btn btn-xs btn-default btn-launch-srv" data-code="REDRAFT_POLISH" style="font-size:11px; font-weight:600;">✍️ Redraft</button>
						<button class="btn btn-xs btn-default btn-launch-srv" data-code="TRANSLATE" style="font-size:11px; font-weight:600;">🌐 Translate</button>
						<button class="btn btn-xs btn-default btn-launch-srv" data-code="COMPLIANCE_CHECK" style="font-size:11px; font-weight:600;">🛡️ Compliance</button>
						<button class="btn btn-xs btn-primary btn-launch-srv" data-code="CUSTOM_PROMPT" style="font-size:11px; font-weight:600; background:#0284c7; border-color:#0284c7;">💬 Custom Prompt</button>
					</div>

					<!-- Output Editor -->
					<div style="flex:1; display:flex; flex-direction:column;">
						<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
							<label style="font-size:11.5px; font-weight:700; color:#475569; margin:0;">📝 AI Deliverable Editor (Markdown):</label>
							<button class="btn btn-xs btn-link p-0 text-muted" id="btn-clear-output" style="font-size:11px;">Clear</button>
						</div>
						<textarea id="studio-editable-output" class="form-control" style="flex:1; font-size:12.5px; line-height:1.5; resize:none; background:#ffffff; border-color:#cbd5e1;" placeholder="${__("AI service results will appear here. You can edit and format this deliverable before saving.")}">${frappe.utils.escape_html(current_output)}</textarea>
					</div>
				</div>
			</div>
		</div>
	`;

	dialog.fields_dict.studio_html.$wrapper.html(html);
	dialog.show();

	// Attach Event Handlers
	dialog.$wrapper.find("#btn-reextract-doc").on("click", function() {
		frappe.call({
			method: "lex.ai_document_engine.extract_job_document_text",
			args: { job_id: frm.doc.name },
			freeze: true,
			freeze_message: __("Extracting text from Job source document..."),
			callback: (res) => {
				if (res.message?.status === "success") {
					dialog.$wrapper.find("#studio-source-doc-text").val(res.message.extracted_text || "");
					dialog.$wrapper.find("#studio-word-count").text(res.message.word_count || 0);
					frappe.show_alert({ message: __("Text extracted ({0} words)", [res.message.word_count]), indicator: "green" });
				}
			}
		});
	});

	dialog.$wrapper.find("#btn-clear-output").on("click", function() {
		dialog.$wrapper.find("#studio-editable-output").val("");
	});

	dialog.$wrapper.find(".btn-launch-srv").on("click", function() {
		const code = $(this).data("code");
		if (code === "CUSTOM_PROMPT" || code === "TRANSLATE" || code === "REDRAFT_POLISH") {
			prompt_parameterized_service(frm, dialog, code);
		} else {
			execute_studio_service(frm, dialog, code);
		}
	});
}

function execute_studio_service(frm, dialog, service_code, custom_instructions = "") {
	const source_text = dialog.$wrapper.find("#studio-source-doc-text").val() || "";
	frappe.call({
		method: "lex.ai_document_engine.process_job_document_service",
		args: {
			job_id: frm.doc.name,
			service_code: service_code,
			custom_instructions: custom_instructions,
		},
		freeze: true,
		freeze_message: __("Executing AI Service: {0}...", [service_code]),
		callback: (res) => {
			if (res.message?.status === "success") {
				const current = dialog.$wrapper.find("#studio-editable-output").val() || "";
				const new_text = res.message.output_text || "";
				const combined = current.trim() ? `${current}\n\n---\n\n### ⚡ ${res.message.service_name}\n\n${new_text}` : new_text;
				dialog.$wrapper.find("#studio-editable-output").val(combined);
				frappe.show_alert({
					message: __("Service {0} completed ({1} tokens)", [res.message.service_code, res.message.tokens_consumed]),
					indicator: "green"
				});
			}
		}
	});
}

function prompt_parameterized_service(frm, dialog, service_code) {
	let prompt_title = __("Custom AI Prompt");
	let label = __("Enter your prompt / directive:");
	let placeholder = __("e.g. Focus on indemnities, liability caps, and termination penalties.");

	if (service_code === "TRANSLATE") {
		prompt_title = __("Translate Legal Document");
		label = __("Target Language & Instructions:");
		placeholder = __("e.g. Hindi (formal legal Hindi with English technical terms in brackets)");
	} else if (service_code === "REDRAFT_POLISH") {
		prompt_title = __("Redraft & Enhance Clauses");
		label = __("Redrafting Goal / Stance:");
		placeholder = __("e.g. Make indemnity clause mutual and cap total liability to 12 months fees.");
	}

	const prompt_diag = new frappe.ui.Dialog({
		title: prompt_title,
		fields: [
			{
				fieldname: "instructions",
				fieldtype: "Long Text",
				label: label,
				reqd: 1,
				placeholder: placeholder,
			}
		],
		primary_action_label: __("Execute AI"),
		primary_action: (values) => {
			prompt_diag.hide();
			execute_studio_service(frm, dialog, service_code, values.instructions);
		}
	});
	prompt_diag.show();
}

function prompt_job_pipeline(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Execute Multi-Service AI Pipeline"),
		fields: [
			{
				fieldname: "services",
				fieldtype: "MultiCheck",
				label: __("Select Services to Chain"),
				options: [
					{ label: "Executive Summarization (SUMMARIZE)", value: "SUMMARIZE", checked: 1 },
					{ label: "Risk & Clause Analysis (RISK_ANALYSIS)", value: "RISK_ANALYSIS", checked: 1 },
					{ label: "Key Metadata & Entities (EXTRACT_METADATA)", value: "EXTRACT_METADATA", checked: 1 },
					{ label: "SOP & Compliance Audit (COMPLIANCE_CHECK)", value: "COMPLIANCE_CHECK", checked: 0 },
				],
				reqd: 1,
			},
			{
				fieldname: "instructions",
				fieldtype: "Small Text",
				label: __("Custom Focus / Directives"),
				placeholder: __("e.g. Pay special attention to clause 14 warranties and payment schedules.")
			}
		],
		primary_action_label: __("Run AI Pipeline"),
		primary_action: (values) => {
			const services = values.services;
			if (!services || !services.length) {
				frappe.msgprint(__("Select at least one service."));
				return;
			}
			dialog.hide();
			frappe.call({
				method: "lex.ai_document_engine.run_job_document_pipeline",
				args: {
					job_id: frm.doc.name,
					service_codes: services,
					custom_instructions: values.instructions,
				},
				freeze: true,
				freeze_message: __("Running AI Pipeline across document..."),
				callback: (r) => {
					if (r.message?.status === "success") {
						frappe.show_alert({
							message: __("Pipeline completed ({0} tokens consumed)", [r.message.total_tokens]),
							indicator: "green"
						});
						frm.reload_doc();
					}
				}
			});
		}
	});
	dialog.show();
}

function prompt_finalize_delivery(frm) {
	frappe.call({
		method: "lex.ai_document_engine.get_job_document_studio_context",
		args: { job_id: frm.doc.name },
		callback: (res) => {
			const processor = res.message?.processor || {};
			const initial_text = processor.final_output_text || "";

			const dialog = new frappe.ui.Dialog({
				title: __("Finalize Deliverable & Complete Document"),
				fields: [
					{
						fieldname: "final_text",
						fieldtype: "Long Text",
						label: __("Deliverable Content (Markdown / Text)"),
						default: initial_text,
						reqd: 1,
					},
					...advanced_export_fields(frm),
				],
				primary_action_label: __("Generate Secure Deliverable"),
				primary_action: (values) => {
					submit_advanced_export(frm, values.final_text, values, dialog);
				}
			});
			dialog.show();
		}
	});
}

function show_advanced_export_dialog(frm, final_text, source_dialog) {
	const dialog = new frappe.ui.Dialog({
		title: __("Advanced Deliverable Export"),
		size: "large",
		fields: advanced_export_fields(frm),
		primary_action_label: __("Generate PDF / DOCX"),
		primary_action: (values) => submit_advanced_export(frm, final_text, values, dialog, source_dialog),
	});
	dialog.show();
}

function advanced_export_fields(frm) {
	return [
		{
			fieldtype: "HTML",
			fieldname: "export_help",
			options: `<div class="alert alert-info mb-3">
				<strong>${__("Advanced native export")}</strong><br>
				${__("Generate a branded, versioned and private legal deliverable. Both is recommended so the client receives a locked PDF and an editable DOCX copy.")}
			</div>`,
		},
		{ fieldtype: "Section Break", label: __("Output") },
		{
			fieldname: "output_format",
			fieldtype: "Select",
			label: __("Output Format"),
			options: "PDF\nDOCX\nBoth",
			default: "Both",
			reqd: 1,
			description: __("Both creates one PDF and one editable DOCX under the same version."),
		},
		{ fieldtype: "Column Break" },
		{
			fieldname: "document_title",
			fieldtype: "Data",
			label: __("Document Title"),
			default: frm.doc.job_title || frm.doc.name,
			reqd: 1,
		},
		{ fieldtype: "Section Break", label: __("Layout & Branding") },
		{
			fieldname: "document_style",
			fieldtype: "Select",
			label: __("Document Style"),
			options: "Legal Professional\nExecutive Brief\nPlain",
			default: "Legal Professional",
			reqd: 1,
		},
		{
			fieldname: "page_size",
			fieldtype: "Select",
			label: __("Page Size"),
			options: "A4\nLetter",
			default: "A4",
			reqd: 1,
		},
		{ fieldtype: "Column Break" },
		{
			fieldname: "confidentiality_label",
			fieldtype: "Select",
			label: __("Confidentiality Label"),
			options: "Privileged & Confidential\nConfidential\nInternal Use Only\nNone",
			default: "Privileged & Confidential",
			reqd: 1,
		},
		{ fieldtype: "Section Break", label: __("Document Controls") },
		{ fieldname: "include_cover_page", fieldtype: "Check", label: __("Include Cover Page"), default: 1 },
		{ fieldname: "include_metadata", fieldtype: "Check", label: __("Include Job / Matter Metadata"), default: 1 },
		{ fieldtype: "Column Break" },
		{ fieldname: "include_page_numbers", fieldtype: "Check", label: __("Include Page Numbers"), default: 1 },
		{ fieldtype: "Section Break", label: __("Delivery Workflow") },
		{
			fieldname: "job_status",
			fieldtype: "Select",
			label: __("Set Job Status"),
			options: "Ready for Delivery\nQA Review\nCompleted",
			default: "Ready for Delivery",
			reqd: 1,
		},
		{ fieldtype: "Column Break" },
		{
			fieldname: "notes",
			fieldtype: "Small Text",
			label: __("Delivery Notes"),
			default: "AI deliverable generated and verified by " + frappe.session.user,
		},
	];
}

function submit_advanced_export(frm, final_text, values, dialog, source_dialog = null) {
	if (!(final_text || "").trim()) {
		frappe.msgprint(__("Deliverable content cannot be empty."));
		return;
	}
	dialog.get_primary_btn().prop("disabled", true);
	frappe.call({
		method: "lex.ai_document_engine.complete_job_document",
		args: {
			job_id: frm.doc.name,
			final_text,
			update_job_status: values.job_status,
			completion_notes: values.notes,
			output_format: values.output_format,
			document_title: values.document_title,
			page_size: values.page_size,
			document_style: values.document_style,
			confidentiality_label: values.confidentiality_label,
			include_cover_page: values.include_cover_page ? 1 : 0,
			include_metadata: values.include_metadata ? 1 : 0,
			include_page_numbers: values.include_page_numbers ? 1 : 0,
		},
		freeze: true,
		freeze_message: __("Generating and securing PDF / DOCX deliverables..."),
		callback: (r) => {
			if (r.message?.status !== "success") return;
			dialog.hide();
			source_dialog?.hide();
			show_export_result(frm, r.message);
			frm.reload_doc();
		},
		always: () => dialog.get_primary_btn().prop("disabled", false),
	});
}

function show_export_result(frm, result) {
	const links = [];
	if (result.pdf_download_url || result.pdf_file_url) {
		links.push(`<a class="btn btn-primary" href="${encodeURI(result.pdf_download_url || result.pdf_file_url)}" target="_blank" rel="noopener">${__("Download Protected PDF")}</a>`);
	}
	if (result.docx_file_url) {
		links.push(`<a class="btn btn-default" href="${encodeURI(result.docx_file_url)}" target="_blank" rel="noopener">${__("Download DOCX")}</a>`);
	}
	const dialog = new frappe.ui.Dialog({
		title: __("Deliverable Generated"),
		fields: [{
			fieldtype: "HTML",
			fieldname: "result",
			options: `<div class="text-center py-4">
				<div class="indicator-pill green mb-3">${__("Version {0}.0 secured", [result.export_version])}</div>
				<p>${frappe.utils.escape_html(result.message || "")}</p>
				<div class="d-flex justify-content-center flex-wrap gap-2">${links.join("")}</div>
			</div>`,
		}],
		primary_action_label: __("View Export History"),
		primary_action: () => {
			dialog.hide();
			frappe.set_route("List", "LPO AI Document Export", { job: frm.doc.name });
		},
	});
	dialog.show();
}
