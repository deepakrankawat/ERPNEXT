/* Lexocrates Senior & QA Workbench Side-by-Side Version Comparison (UI-004) */
frappe.provide('lexocrates.version_compare');

lexocrates.version_compare = {
	render_comparison_modal: function(doc_id, original_text, ai_draft_text, human_review_text, final_text) {
		let dialog = new frappe.ui.Dialog({
			title: __('Side-by-Side Document Version Comparison (UI-004)'),
			size: 'large',
			fields: [
				{
					fieldname: 'version_html',
					fieldtype: 'HTML',
				}
			]
		});

		let html = `
			<div class="lexocrates-comparison-container" style="display: flex; gap: 15px; overflow-x: auto; padding: 10px;">
				<div class="version-pane" style="flex: 1; min-width: 250px; background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 6px; padding: 12px;">
					<h5 style="color: #495057; font-weight: 600;">1. Original Client File</h5>
					<pre style="white-space: pre-wrap; font-size: 12px; max-height: 400px; overflow-y: auto;">${frappe.utils.escape_html(original_text || 'No text')}</pre>
				</div>
				<div class="version-pane" style="flex: 1; min-width: 250px; background: #f3f0ff; border: 1px solid #d0bfff; border-radius: 6px; padding: 12px;">
					<h5 style="color: #5f3dc4; font-weight: 600;">2. AI Generated Draft</h5>
					<pre style="white-space: pre-wrap; font-size: 12px; max-height: 400px; overflow-y: auto;">${frappe.utils.escape_html(ai_draft_text || 'No draft')}</pre>
				</div>
				<div class="version-pane" style="flex: 1; min-width: 250px; background: #e6fcf5; border: 1px solid #96f2d7; border-radius: 6px; padding: 12px;">
					<h5 style="color: #0ca678; font-weight: 600;">3. Human Senior Edit</h5>
					<pre style="white-space: pre-wrap; font-size: 12px; max-height: 400px; overflow-y: auto;">${frappe.utils.escape_html(human_review_text || 'In review')}</pre>
				</div>
				<div class="version-pane" style="flex: 1; min-width: 250px; background: #e7f5ff; border: 1px solid #a5d8ff; border-radius: 6px; padding: 12px;">
					<h5 style="color: #1971c2; font-weight: 600;">4. Approved Deliverable</h5>
					<pre style="white-space: pre-wrap; font-size: 12px; max-height: 400px; overflow-y: auto;">${frappe.utils.escape_html(final_text || 'Pending QA')}</pre>
				</div>
			</div>
		`;

		dialog.fields_dict.version_html.$wrapper.html(html);
		dialog.show();
	}
};
