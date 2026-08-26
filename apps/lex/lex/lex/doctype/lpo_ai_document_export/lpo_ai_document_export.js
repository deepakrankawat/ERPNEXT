frappe.ui.form.on("LPO AI Document Export", {
	refresh(frm) {
		if (frm.doc.file_url) {
			const is_pdf = String(frm.doc.export_format || "").toUpperCase() === "PDF"
				|| String(frm.doc.file_url).toLowerCase().split("?")[0].endsWith(".pdf");
			frm.add_custom_button(is_pdf ? __("Download Protected PDF") : __("Open Export"), () => {
				const url = is_pdf
					? `/api/method/lex.pdf_watermark.download_watermarked_pdf?file_url=${encodeURIComponent(frm.doc.file_url)}`
					: frm.doc.file_url;
				window.open(url, "_blank", "noopener");
			});
		}
	},
});
