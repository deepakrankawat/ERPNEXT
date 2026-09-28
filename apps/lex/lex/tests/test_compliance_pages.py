from pathlib import Path
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
WWW = APP_ROOT / "www"


class TestCompliancePages(unittest.TestCase):
	def test_required_public_pages_and_footer_links_exist(self):
		pages = {
			"terms-and-conditions.html": ["Terms &amp; Conditions", "CAD", "USD", "INR", "30 days"],
			"privacy-policy.html": ["Privacy Policy", "PCI-DSS", "Grievance Officer", "Digital Personal Data Protection Act"],
			"refund-cancellation-policy.html": ["Refund, Return &amp; Cancellation Policy", "24 to 48 business hours", "5 to 7 business days"],
			"contact-us.html": ["Contact Us", "support@lexocrates.com", "302041", "compliance-contact-form"],
		}
		for filename, expected in pages.items():
			content = (WWW / filename).read_text()
			for text in expected:
				self.assertIn(text, content, f"{filename} is missing {text!r}")

		footer = (APP_ROOT / "templates/includes/compliance_footer.html").read_text()
		for route in ("/terms-and-conditions", "/privacy-policy", "/refund-cancellation-policy", "/contact-us"):
			self.assertIn(route, footer)

	def test_card_data_disclosure_is_explicit(self):
		privacy = (WWW / "privacy-policy.html").read_text()
		self.assertIn("We do not store or process complete credit/debit card numbers or CVV on our servers.", privacy)

	def test_no_fake_phone_number_is_published(self):
		for filename in ("contact-us.html", "privacy-policy.html"):
			content = (WWW / filename).read_text()
			self.assertNotIn("+91-XXXXXXXXXX", content)
			self.assertNotIn("tel:", content)

	def test_sales_manager_notification_is_installed_and_used(self):
		installer = (APP_ROOT / "install.py").read_text()
		endpoint = (APP_ROOT / "compliance_pages.py").read_text()
		self.assertIn("Lexocrates Website Contact - Sales Notification", installer)
		self.assertIn('"role": "Sales Manager"', endpoint)
		self.assertIn("frappe.sendmail(", endpoint)
		self.assertIn("sales@lexocrates.com", endpoint)


if __name__ == "__main__":
	unittest.main()
