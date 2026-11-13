from __future__ import annotations

import unittest
from datetime import datetime, timezone

import frappe

from lex.email_campaign_scheduler import _dispatch_key, scheduled_datetime_utc


class TestTimedEmailCampaignScheduler(unittest.TestCase):
	def test_india_campaign_time_converts_to_utc(self):
		campaign = frappe._dict({"start_date": "2026-01-15", "start_time": "09:00:00", "time_zone": "Asia/Kolkata"})
		entry = frappe._dict({"send_after_days": 0, "send_at_time": None})
		self.assertEqual(
			scheduled_datetime_utc(campaign, entry),
			datetime(2026, 1, 15, 3, 30, tzinfo=timezone.utc),
		)

	def test_country_timezones_apply_daylight_saving(self):
		cases = (
			("Europe/London", datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)),
			("America/Toronto", datetime(2026, 7, 10, 13, 0, tzinfo=timezone.utc)),
			("America/Los_Angeles", datetime(2026, 7, 10, 16, 0, tzinfo=timezone.utc)),
		)
		for zone, expected in cases:
			with self.subTest(zone=zone):
				campaign = frappe._dict({"start_date": "2026-07-10", "start_time": "09:00:00", "time_zone": zone})
				entry = frappe._dict({"send_after_days": 0, "send_at_time": None})
				self.assertEqual(scheduled_datetime_utc(campaign, entry), expected)

	def test_schedule_row_time_overrides_campaign_time_and_day(self):
		campaign = frappe._dict({"start_date": "2026-01-15", "start_time": "09:00:00", "time_zone": "Asia/Kolkata"})
		entry = frappe._dict({"send_after_days": 2, "send_at_time": "18:45:00"})
		self.assertEqual(
			scheduled_datetime_utc(campaign, entry),
			datetime(2026, 1, 17, 13, 15, tzinfo=timezone.utc),
		)

	def test_dispatch_key_is_stable_per_campaign_schedule(self):
		self.assertEqual(_dispatch_key("MAIL-CAMP-1", "row-1"), _dispatch_key("MAIL-CAMP-1", "row-1"))
		self.assertNotEqual(_dispatch_key("MAIL-CAMP-1", "row-1"), _dispatch_key("MAIL-CAMP-1", "row-2"))

	@unittest.mock.patch("lex.lex.doctype.ai_email_template.ai_email_template.generate_email_for_lead")
	def test_ai_campaign_content_generation(self, mock_gen):
		from lex.email_campaign_scheduler import _generate_ai_campaign_content, _resolve_ai_email_template

		mock_gen.return_value = {
			"subject": "AI Customized Subject for Reliance",
			"body": "<p>AI Customized Body</p>",
		}
		template = frappe._dict({
			"name": "Standard Pitch",
			"subject": "Default Subject {{ name }}",
			"response_": "Default Body",
			"custom_use_ai_template": 1,
			"custom_ai_email_template": "AI Pitch",
		})
		with unittest.mock.patch("frappe.db.exists", return_value=True):
			ai_tmpl = _resolve_ai_email_template(template)
			self.assertEqual(ai_tmpl, "AI Pitch")
			subj, body = _generate_ai_campaign_content("LEAD-001", ai_tmpl, template, {"name": "LEAD-001"})
			self.assertEqual(subj, "AI Customized Subject for Reliance")
			self.assertEqual(body, "<p>AI Customized Body</p>")
