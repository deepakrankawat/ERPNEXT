const PROVIDERS = ["OpenAI", "Google Gemini", "Anthropic"];
const PROVIDER_META = {
	OpenAI: {
		keyField: "openai_api_key",
		modelsField: "openai_available_models",
		defaultField: "openai_default_model",
		placeholder: "sk-proj-...",
	},
	"Google Gemini": {
		keyField: "gemini_api_key",
		modelsField: "gemini_available_models",
		defaultField: "gemini_default_model",
		placeholder: "AIzaSy...",
	},
	Anthropic: {
		keyField: "anthropic_api_key",
		modelsField: "anthropic_available_models",
		defaultField: "anthropic_default_model",
		placeholder: "sk-ant-...",
	},
};
const ROUTES = [
	["estimation_credential", "estimation_provider", "estimation_model"],
	["job_chat_credential", "job_chat_provider", "job_chat_model"],
	["document_analysis_credential", "document_analysis_provider", "document_analysis_model"],
	["qa_review_credential", "qa_review_provider", "qa_review_model"],
	["intake_credential", "intake_provider", "intake_model"],
];

frappe.ui.form.on("LPO AI Settings", {
	refresh(frm) {
		sync_model_options(frm);
		sync_credential_options(frm);
		render_status_indicators(frm);
		frm.add_custom_button(__("Test All Enabled Providers"), () => test_all_connections(frm), __("Diagnostics"));
		frm.add_custom_button(__("Manage API Credentials"), () => manage_credentials_dialog(frm), __("Diagnostics"));
		frm.add_custom_button(__("Open Model Registry"), () => frappe.set_route("List", "LPO AI Model Registry"), __("Diagnostics"));
	},

	open_model_registry_btn() {
		frappe.set_route("List", "LPO AI Model Registry");
	},

	job_chat_provider: sync_model_options,
	estimation_provider: sync_model_options,
	document_analysis_provider: sync_model_options,
	qa_review_provider: sync_model_options,
	intake_provider: sync_model_options,
	job_chat_credential: route_credential_changed,
	estimation_credential: route_credential_changed,
	document_analysis_credential: route_credential_changed,
	qa_review_credential: route_credential_changed,
	intake_credential: route_credential_changed,
	default_credential: sync_default_provider_from_credential,
	add_provider_credential_btn: (frm) => show_named_credential_dialog(frm),
	verify_all_credentials_btn: (frm) => test_all_named_credentials(frm),

	test_openai_btn: (frm) => test_provider(frm, "OpenAI"),
	update_openai_key_btn: (frm) => show_api_key_dialog(frm, "OpenAI"),
	fetch_openai_models_btn: (frm) => discover_provider(frm, "OpenAI"),

	test_gemini_btn: (frm) => test_provider(frm, "Google Gemini"),
	update_gemini_key_btn: (frm) => show_api_key_dialog(frm, "Google Gemini"),
	fetch_gemini_models_btn: (frm) => discover_provider(frm, "Google Gemini"),

	test_anthropic_btn: (frm) => test_provider(frm, "Anthropic"),
	update_anthropic_key_btn: (frm) => show_api_key_dialog(frm, "Anthropic"),
	fetch_anthropic_models_btn: (frm) => discover_provider(frm, "Anthropic"),
});

function provider_models(frm, provider) {
	const meta = PROVIDER_META[provider];
	return (frm.doc[meta.modelsField] || "")
		.split(",")
		.map((value) => value.trim())
		.filter(Boolean);
}

function sync_model_options(frm) {
	for (const provider of PROVIDERS) {
		const meta = PROVIDER_META[provider];
		const models = provider_models(frm, provider);
		frm.set_df_property(meta.defaultField, "options", ["", ...models].join("\n"));
	}
	for (const [, providerField, modelField] of ROUTES) {
		const provider = frm.doc[providerField];
		const models = provider ? provider_models(frm, provider) : [];
		frm.set_df_property(modelField, "options", ["", ...models].join("\n"));
		if (frm.doc[modelField] && !models.includes(frm.doc[modelField])) {
			frm.set_value(modelField, "");
		}
	}
}

function credential_rows(frm) {
	return (frm.doc.provider_credentials || []).map((row) => ({
		name: row.credential_name,
		provider: row.provider,
		enabled: Boolean(row.enabled),
		defaultModel: row.default_model,
		models: (row.available_models || "").split(",").map((value) => value.trim()).filter(Boolean),
		status: row.verification_status || "",
	}));
}

function sync_credential_options(frm) {
	const rows = credential_rows(frm);
	const enabledNames = rows.filter((row) => row.enabled).map((row) => row.name);
	frm.set_df_property("default_credential", "options", ["", ...enabledNames].join("\n"));
	for (const [credentialField] of ROUTES) {
		frm.set_df_property(credentialField, "options", ["", ...enabledNames].join("\n"));
		if (frm.doc[credentialField] && !enabledNames.includes(frm.doc[credentialField])) {
			frm.set_value(credentialField, "");
		}
	}
}

function route_credential_changed(frm, _cdt, _cdn) {
	for (const [credentialField, providerField, modelField] of ROUTES) {
		const credentialName = frm.doc[credentialField];
		if (!credentialName) continue;
		const credential = credential_rows(frm).find((row) => row.name === credentialName);
		if (!credential) continue;
		frm.set_value(providerField, credential.provider);
		frm.set_df_property(modelField, "options", ["", ...credential.models].join("\n"));
		frm.set_value(modelField, credential.defaultModel || credential.models[0] || "");
	}
}

function sync_default_provider_from_credential(frm) {
	const credential = credential_rows(frm).find((row) => row.name === frm.doc.default_credential);
	if (credential) frm.set_value("default_provider", credential.provider);
}

function render_status_indicators(frm) {
	for (const [provider, meta] of Object.entries(PROVIDER_META)) {
		const prefix = meta.modelsField.replace("_available_models", "");
		const statusField = `${prefix}_status`;
		const status = frm.doc[statusField] || __("Not configured");
		const active = status.toLowerCase().includes("active");
		frm.set_df_property(
			statusField,
			"description",
			`<span class="indicator ${active ? "green" : "orange"}">${frappe.utils.escape_html(provider)}: ${frappe.utils.escape_html(status)}</span>`
		);
	}
}

async function discover_provider(frm, provider) {
	const response = await frappe.call({
		method: "lex.lex.doctype.lpo_ai_settings.lpo_ai_settings.fetch_provider_models",
		args: { provider, verify_limit: 3 },
		freeze: true,
		freeze_message: __("Discovering and live-testing compatible {0} models...", [provider]),
	});
	show_diagnostic(provider, response.message || {});
	await frm.reload_doc();
}

async function test_provider(frm, provider) {
	const meta = PROVIDER_META[provider];
	const response = await frappe.call({
		method: "lex.lex.doctype.lpo_ai_settings.lpo_ai_settings.test_ai_provider_connection",
		args: { provider, model: frm.doc[meta.defaultField] || null },
		freeze: true,
		freeze_message: __("Running live {0} endpoint test...", [provider]),
	});
	const result = response.message || {};
	if (result.error_type === "MISSING_KEY") {
		show_api_key_dialog(frm, provider);
		return;
	}
	show_diagnostic(provider, result);
	await frm.reload_doc();
}

async function test_all_connections(frm) {
	for (const provider of PROVIDERS) {
		const meta = PROVIDER_META[provider];
		const enabled = Boolean(frm.doc[`enable_${meta.keyField.split("_")[0]}`]);
		const hasStatus = (frm.doc[`${meta.keyField.split("_")[0]}_status`] || "").toLowerCase().includes("active");
		if (!enabled && !hasStatus) continue;
		const response = await frappe.call({
			method: "lex.lex.doctype.lpo_ai_settings.lpo_ai_settings.test_ai_provider_connection",
			args: { provider, model: frm.doc[meta.defaultField] || null },
			freeze: false,
		});
		show_diagnostic(provider, response.message || {});
	}
	await frm.reload_doc();
}

function show_named_credential_dialog(frm, existingName = "") {
	const existing = credential_rows(frm).find((row) => row.name === existingName);
	const dialog = new frappe.ui.Dialog({
		title: existing ? __("Replace API Credential: {0}", [existing.name]) : __("Add Named API Credential"),
		fields: [
			{ fieldname: "credential_name", fieldtype: "Data", label: __("Credential Name"), default: existing?.name || "", reqd: 1, description: __("Example: OpenAI Production, Gemini Estimation, Claude QA") },
			{ fieldname: "provider", fieldtype: "Select", label: __("Provider"), options: PROVIDERS.join("\n"), default: existing?.provider || "OpenAI", reqd: 1 },
			{ fieldname: "api_key", fieldtype: "Password", label: __("API Key"), reqd: 1, description: __("The key is transmitted only to this Frappe server, live-tested, and then stored encrypted.") },
			{ fieldtype: "Section Break", label: __("Optional Provider Configuration") },
			{ fieldname: "base_url", fieldtype: "Data", label: __("API Base URL"), description: __("Leave blank to use the official provider endpoint.") },
			{ fieldname: "priority", fieldtype: "Int", label: __("Fallback Priority"), default: 10, reqd: 1 },
			{ fieldtype: "Column Break" },
			{ fieldname: "organization_id", fieldtype: "Data", label: __("OpenAI Organization ID") },
			{ fieldname: "project_id", fieldtype: "Data", label: __("OpenAI Project ID") },
		],
		primary_action_label: __("Verify & Save Encrypted"),
		primary_action: async (values) => {
			if (!values.api_key || values.api_key.startsWith("*")) {
				frappe.msgprint(__("Enter a valid live API key."));
				return;
			}
			dialog.get_primary_btn().prop("disabled", true);
			try {
				const response = await frappe.call({
					method: "lex.lex.doctype.lpo_ai_settings.lpo_ai_settings.save_provider_credential",
					args: values,
					freeze: true,
					freeze_message: __("Discovering models and live-testing credential..."),
				});
				show_diagnostic(values.provider, response.message || {});
				if (response.message?.status === "success") dialog.hide();
				await frm.reload_doc();
			} finally {
				dialog.get_primary_btn().prop("disabled", false);
			}
		},
	});
	dialog.show();
}

async function test_all_named_credentials(frm) {
	const enabled = credential_rows(frm).filter((row) => row.enabled);
	if (!enabled.length) {
		frappe.msgprint(__("No enabled named API credential is configured."));
		return;
	}
	const results = [];
	for (const credential of enabled) {
		const response = await frappe.call({
			method: "lex.lex.doctype.lpo_ai_settings.lpo_ai_settings.test_provider_credential",
			args: { credential_name: credential.name },
			freeze: false,
		});
		results.push(response.message || {});
	}
	frappe.msgprint({
		title: __("Named Credential Diagnostics"),
		message: results.map((result) => {
			const ok = result.status === "success";
			return `<div class="mb-2"><span class="indicator ${ok ? "green" : "red"}">${frappe.utils.escape_html(result.credential_name || result.provider || "")}</span> ${frappe.utils.escape_html(result.message || result.status || "")}</div>`;
		}).join(""),
		indicator: results.every((row) => row.status === "success") ? "green" : "orange",
	});
	await frm.reload_doc();
}

function manage_credentials_dialog(frm) {
	const rows = credential_rows(frm);
	if (!rows.length) {
		show_named_credential_dialog(frm);
		return;
	}
	const dialog = new frappe.ui.Dialog({
		title: __("Manage Named API Credentials"),
		fields: [
			{ fieldname: "credential_name", fieldtype: "Select", label: __("Credential"), options: rows.map((row) => row.name).join("\n"), reqd: 1 },
			{ fieldname: "action", fieldtype: "Select", label: __("Action"), options: "Test Connection\nEnable\nDisable\nReplace Key\nRemove", default: "Test Connection", reqd: 1 },
		],
		primary_action_label: __("Continue"),
		primary_action: async (values) => {
			dialog.hide();
			if (values.action === "Replace Key") {
				show_named_credential_dialog(frm, values.credential_name);
				return;
			}
			if (values.action === "Remove") {
				frappe.confirm(__("Permanently remove this named credential and its encrypted key?"), async () => {
					await frappe.call({ method: "lex.lex.doctype.lpo_ai_settings.lpo_ai_settings.remove_provider_credential", args: { credential_name: values.credential_name } });
					await frm.reload_doc();
				});
				return;
			}
			const method = values.action === "Test Connection"
				? "test_provider_credential"
				: "set_provider_credential_enabled";
			const args = { credential_name: values.credential_name };
			if (method === "set_provider_credential_enabled") args.enabled = values.action === "Enable" ? 1 : 0;
			const response = await frappe.call({ method: `lex.lex.doctype.lpo_ai_settings.lpo_ai_settings.${method}`, args, freeze: true });
			show_diagnostic(values.credential_name, response.message || {});
			await frm.reload_doc();
		},
	});
	dialog.show();
}

function show_api_key_dialog(frm, provider) {
	const meta = PROVIDER_META[provider];
	const dialog = new frappe.ui.Dialog({
		title: __("Set / Change {0} API Key", [provider]),
		fields: [{
			fieldname: "api_key",
			fieldtype: "Password",
			label: __("New {0} API Key", [provider]),
			reqd: 1,
			placeholder: meta.placeholder,
			description: __("The key is saved only after model discovery and a successful live endpoint test."),
		}],
		primary_action_label: __("Verify & Save Securely"),
		primary_action: async (values) => {
			const key = (values.api_key || "").trim();
			if (!key || key.length < 6 || key.startsWith("*")) {
				frappe.msgprint(__("Please enter a valid live API key."));
				return;
			}
			dialog.hide();
			await save_provider_key(frm, provider, key);
		},
		secondary_action_label: __("Remove Saved Key"),
		secondary_action: () => {
			dialog.hide();
			frappe.confirm(__("Remove the saved API key and disable {0}?", [provider]), () => save_provider_key(frm, provider, "CLEAR_KEY"));
		},
	});
	dialog.show();
}

async function save_provider_key(frm, provider, apiKey) {
	const response = await frappe.call({
		method: "lex.lex.doctype.lpo_ai_settings.lpo_ai_settings.save_provider_api_key",
		args: { provider, api_key: apiKey },
		freeze: true,
		freeze_message: apiKey === "CLEAR_KEY"
			? __("Removing {0} key...", [provider])
			: __("Discovering models, testing endpoint, and encrypting {0} key...", [provider]),
	});
	show_diagnostic(provider, response.message || {});
	await frm.reload_doc();
}

function show_diagnostic(provider, result) {
	const success = result.status === "success";
	const details = [result.message];
	if (result.model) details.push(__("Model: {0}", [result.model]));
	if (result.latency_ms !== undefined) details.push(__("Latency: {0} ms", [result.latency_ms]));
	if (result.discovered_count !== undefined) details.push(__("Discovered: {0}; verified: {1}", [result.discovered_count, result.verified_count || 0]));
	frappe.msgprint({
		title: success ? __("{0} verified", [provider]) : __("{0} diagnostic failed", [provider]),
		message: details.filter(Boolean).map((line) => frappe.utils.escape_html(String(line))).join("<br>"),
		indicator: success ? "green" : "red",
	});
}
