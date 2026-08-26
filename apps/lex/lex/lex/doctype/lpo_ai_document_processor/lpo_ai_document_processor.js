// Copyright (c) 2026, Lexocrates and contributors
// For license information, please see license.txt

frappe.ui.form.on("LPO AI Document Processor", {
	refresh(frm) {
		if (frm.is_new()) return;
		configure_ai_credential_field(frm);

		// Add custom buttons
		frm.add_custom_button(__("Extract Text"), () => {
			frappe.call({
				method: "lex.ai_document_engine.extract_job_document_text",
				args: { job_id: frm.doc.job, file_url: frm.doc.source_file },
				freeze: true,
				freeze_message: __("Extracting text and structure..."),
				callback: (r) => {
					if (r.message?.status === "success") {
						frappe.show_alert({ message: __("Text extracted ({0} words)", [r.message.word_count]), indicator: "green" });
						frm.reload_doc();
					}
				}
			});
		}, __("Actions"));

		frm.add_custom_button(__("Run AI Pipeline"), () => {
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
						label: __("Pipeline Focus / Custom Instructions"),
						placeholder: __("e.g. Focus specifically on indemnities, liability caps, and termination penalties.")
					}
				],
				primary_action_label: __("Run Pipeline"),
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
							job_id: frm.doc.job,
							service_codes: services,
							custom_instructions: values.instructions,
							credential_name: frm.doc.ai_credential || null,
						},
						freeze: true,
						freeze_message: __("Executing AI Pipeline across document..."),
						callback: (r) => {
							if (r.message?.status === "success") {
								frappe.show_alert({
									message: __("AI Pipeline completed ({0} tokens consumed)", [r.message.total_tokens]),
									indicator: "green"
								});
								frm.reload_doc();
							}
						}
					});
				}
			});
			dialog.show();
		}, __("Actions"));

		frm.add_custom_button(__("Complete & Export Document"), () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Advanced Deliverable Export"),
				size: "large",
				fields: processor_export_fields(frm),
				primary_action_label: __("Generate PDF / DOCX"),
				primary_action: (values) => {
					dialog.get_primary_btn().prop("disabled", true);
					frappe.call({
						method: "lex.ai_document_engine.complete_job_document",
						args: {
							job_id: frm.doc.job,
							final_text: frm.doc.final_output_text,
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
							if (r.message?.status === "success") {
								dialog.hide();
								show_processor_export_result(frm, r.message);
								frm.reload_doc();
							}
						},
						always: () => dialog.get_primary_btn().prop("disabled", false),
					});
				}
			});
			dialog.show();
		}, __("Actions"));

		if (frm.doc.final_output_pdf) {
			frm.add_custom_button(__("Download Protected PDF"), () => {
				const url = `/api/method/lex.pdf_watermark.download_watermarked_pdf?file_url=${encodeURIComponent(frm.doc.final_output_pdf)}`;
				window.open(url, "_blank", "noopener");
			}, __("Deliverables"));
		}
		if (frm.doc.final_output_docx) {
			frm.add_custom_button(__("Download DOCX"), () => window.open(frm.doc.final_output_docx, "_blank", "noopener"), __("Deliverables"));
		}
		frm.add_custom_button(__("Export History"), () => {
			frappe.set_route("List", "LPO AI Document Export", { job: frm.doc.job });
		}, __("Deliverables"));

		render_document_studio(frm);
	}
});

function processor_export_fields(frm) {
	return [
		{
			fieldtype: "HTML",
			fieldname: "export_help",
			options: `<div class="alert alert-info mb-3"><strong>${__("Advanced native export")}</strong><br>${__("Both is recommended: a locked PDF for delivery and an editable DOCX for further controlled work.")}</div>`,
		},
		{ fieldtype: "Section Break", label: __("Output") },
		{ fieldname: "output_format", fieldtype: "Select", label: __("Output Format"), options: "PDF\nDOCX\nBoth", default: "Both", reqd: 1 },
		{ fieldtype: "Column Break" },
		{ fieldname: "document_title", fieldtype: "Data", label: __("Document Title"), default: frm.doc.job || __("Legal Operations Deliverable"), reqd: 1 },
		{ fieldtype: "Section Break", label: __("Layout & Branding") },
		{ fieldname: "document_style", fieldtype: "Select", label: __("Document Style"), options: "Legal Professional\nExecutive Brief\nPlain", default: "Legal Professional", reqd: 1 },
		{ fieldname: "page_size", fieldtype: "Select", label: __("Page Size"), options: "A4\nLetter", default: "A4", reqd: 1 },
		{ fieldtype: "Column Break" },
		{ fieldname: "confidentiality_label", fieldtype: "Select", label: __("Confidentiality Label"), options: "Privileged & Confidential\nConfidential\nInternal Use Only\nNone", default: "Privileged & Confidential", reqd: 1 },
		{ fieldtype: "Section Break", label: __("Document Controls") },
		{ fieldname: "include_cover_page", fieldtype: "Check", label: __("Include Cover Page"), default: 1 },
		{ fieldname: "include_metadata", fieldtype: "Check", label: __("Include Job / Matter Metadata"), default: 1 },
		{ fieldtype: "Column Break" },
		{ fieldname: "include_page_numbers", fieldtype: "Check", label: __("Include Page Numbers"), default: 1 },
		{ fieldtype: "Section Break", label: __("Delivery Workflow") },
		{ fieldname: "job_status", fieldtype: "Select", label: __("Set Job Status"), options: "Ready for Delivery\nQA Review\nCompleted", default: "Ready for Delivery", reqd: 1 },
		{ fieldtype: "Column Break" },
		{ fieldname: "notes", fieldtype: "Small Text", label: __("Completion Notes"), default: "Final deliverable approved by operational analyst via AI Document Studio." },
	];
}

function show_processor_export_result(frm, result) {
	const buttons = [];
	if (result.pdf_download_url || result.pdf_file_url) buttons.push(`<a class="btn btn-primary" href="${encodeURI(result.pdf_download_url || result.pdf_file_url)}" target="_blank" rel="noopener">${__("Download Protected PDF")}</a>`);
	if (result.docx_file_url) buttons.push(`<a class="btn btn-default" href="${encodeURI(result.docx_file_url)}" target="_blank" rel="noopener">${__("Download DOCX")}</a>`);
	const dialog = new frappe.ui.Dialog({
		title: __("Deliverable Generated"),
		fields: [{ fieldtype: "HTML", fieldname: "result", options: `<div class="text-center py-4"><div class="indicator-pill green mb-3">${__("Version {0}.0 secured", [result.export_version])}</div><p>${frappe.utils.escape_html(result.message || "")}</p><div class="d-flex justify-content-center flex-wrap gap-2">${buttons.join("")}</div></div>` }],
		primary_action_label: __("View Export History"),
		primary_action: () => {
			dialog.hide();
			frappe.set_route("List", "LPO AI Document Export", { job: frm.doc.job });
		},
	});
	dialog.show();
}

function render_document_studio(frm) {
	const $wrapper = frm.fields_dict.document_studio_html?.$wrapper;
	if (!$wrapper) return;
	$wrapper.empty();

	const extracted = frappe.utils.escape_html(frm.doc.extracted_text || "(No document text extracted yet. Click 'Extract Text' above or upload a file.)");
	const final_out = frappe.utils.escape_html(frm.doc.final_output_text || "");

	const html = `
		<div class="ai-doc-studio" style="border:1px solid #cbd5e1; border-radius:8px; overflow:hidden; margin:15px 0; background:#f8fafc; font-family:var(--font-stack);">
			<div style="background:#0f172a; color:#fff; padding:12px 18px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
				<div style="display:flex; align-items:center; gap:8px;">
					<span style="font-size:18px;">📄</span>
					<strong style="font-size:15px; color:#fff;">AI Document Transformation Studio</strong>
					<span style="background:rgba(56,189,248,0.2); color:#38bdf8; border:1px solid rgba(56,189,248,0.4); padding:2px 8px; border-radius:999px; font-size:11px; font-weight:600;">
						${frm.doc.status || "Draft"}
					</span>
				</div>
				<div style="font-size:12px; color:#94a3b8;">
					<span>Words: <strong>${frm.doc.word_count || 0}</strong></span> |
					<span>Characters: <strong>${frm.doc.char_count || 0}</strong></span> |
					<span>Language: <strong>${frm.doc.detected_language || "English"}</strong></span>
				</div>
			</div>

			<div style="display:grid; grid-template-columns: 1fr 1fr; gap:15px; padding:15px;">
				<!-- Left: Source Document Panel -->
				<div style="background:#fff; border:1px solid #e2e8f0; border-radius:6px; padding:14px; display:flex; flex-direction:column; max-height:480px;">
					<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; padding-bottom:8px; border-bottom:1px solid #f1f5f9;">
						<strong style="font-size:13px; color:#1e293b;">📥 Source Document Context</strong>
						<span style="font-size:11px; color:#64748b;">${frm.doc.source_file ? frm.doc.source_file : "Inline Text"}</span>
					</div>
					<div style="flex:1; overflow-y:auto; font-size:12.5px; line-height:1.6; color:#334155; white-space:pre-wrap; background:#f8fafc; padding:12px; border-radius:4px; border:1px solid #f1f5f9;">${extracted}</div>
				</div>

				<!-- Right: Quick AI Services & Output -->
				<div style="background:#fff; border:1px solid #e2e8f0; border-radius:6px; padding:14px; display:flex; flex-direction:column; max-height:480px;">
					<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; padding-bottom:8px; border-bottom:1px solid #f1f5f9;">
						<strong style="font-size:13px; color:#1e293b;">⚡ Quick AI Service Launch</strong>
						<span style="font-size:11px; color:#64748b;">System User Execution</span>
					</div>
					<div style="display:flex; flex-wrap:wrap; gap:6px; margin-bottom:12px;">
						<button class="btn btn-xs btn-default btn-doc-service" data-code="SUMMARIZE" style="font-size:11px; font-weight:600;">📑 Summarize</button>
						<button class="btn btn-xs btn-default btn-doc-service" data-code="RISK_ANALYSIS" style="font-size:11px; font-weight:600;">⚠️ Risk Audit</button>
						<button class="btn btn-xs btn-default btn-doc-service" data-code="EXTRACT_METADATA" style="font-size:11px; font-weight:600;">📊 Key Data</button>
						<button class="btn btn-xs btn-default btn-doc-service" data-code="REDRAFT_POLISH" style="font-size:11px; font-weight:600;">✍️ Redraft</button>
						<button class="btn btn-xs btn-default btn-doc-service" data-code="COMPLIANCE_CHECK" style="font-size:11px; font-weight:600;">🛡️ Compliance</button>
						<button class="btn btn-xs btn-primary btn-doc-service" data-code="CUSTOM_PROMPT" style="font-size:11px; font-weight:600; background:#0284c7; border-color:#0284c7;">💬 Custom Prompt</button>
					</div>

					<div style="flex:1; overflow-y:auto; font-size:12.5px; line-height:1.6; color:#1e293b; white-space:pre-wrap; background:#f8fafc; padding:12px; border-radius:4px; border:1px solid #f1f5f9;" id="studio-ai-output-box">${final_out || "(Click any AI service above or run a pipeline to generate document analysis and deliverables.)"}</div>
				</div>
			</div>
		</div>
	`;

	$wrapper.html(html);

	$wrapper.find(".btn-doc-service").on("click", function() {
		const service_code = $(this).data("code");
		if (service_code === "CUSTOM_PROMPT") {
			prompt_custom_service(frm, service_code);
		} else {
			frappe.call({
				method: "lex.ai_document_engine.process_job_document_service",
				args: {
					job_id: frm.doc.job,
					service_code: service_code,
					credential_name: frm.doc.ai_credential || null,
				},
				freeze: true,
				freeze_message: __("Executing AI Document Service ({0})...", [service_code]),
				callback: (r) => {
					if (r.message?.status === "success") {
						frappe.show_alert({
							message: __("Service {0} completed ({1} tokens)", [r.message.service_code, r.message.tokens_consumed]),
							indicator: "green"
						});
						frm.reload_doc();
					}
				}
			});
		}
	});
}

function prompt_custom_service(frm, service_code) {
	const dialog = new frappe.ui.Dialog({
		title: __("Custom AI Document Prompt"),
		fields: [
			{
				fieldname: "instructions",
				fieldtype: "Long Text",
				label: __("Prompt Directive"),
				reqd: 1,
				placeholder: __("e.g. Translate section 3 to French, verify confidentiality obligations, and highlight non-standard liabilities.")
			}
		],
		primary_action_label: __("Execute AI"),
		primary_action: (values) => {
			dialog.hide();
			frappe.call({
				method: "lex.ai_document_engine.process_job_document_service",
				args: {
					job_id: frm.doc.job,
					service_code: service_code,
					custom_instructions: values.instructions,
					credential_name: frm.doc.ai_credential || null,
				},
				freeze: true,
				freeze_message: __("Executing Custom AI Prompt on document..."),
				callback: (r) => {
					if (r.message?.status === "success") {
						frappe.show_alert({
							message: __("AI transformation completed ({0} tokens)", [r.message.tokens_consumed]),
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

async function configure_ai_credential_field(frm) {
	try {
		const response = await frappe.call({
			method: "lex.lex.doctype.lpo_ai_settings.lpo_ai_settings.get_ai_provider_config",
			freeze: false,
		});
		const config = response.message || {};
		const names = (config.credentials || [])
			.filter((item) => item.enabled && item.has_key && item.models?.length)
			.map((item) => item.credential_name);
		frm.set_df_property("ai_credential", "options", ["", ...names].join("\n"));
		frm.set_df_property(
			"ai_credential",
			"description",
			__("Blank uses central Document AI route: {0}", [config.routes?.document_analysis || config.default_credential || config.default_provider || "Not configured"]),
		);
	} catch (_) {
		frm.set_df_property("ai_credential", "description", __("Open LPO AI Settings to configure a verified Document AI credential."));
	}
}
