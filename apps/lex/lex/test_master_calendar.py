from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from lex.master_calendar import _alert_state, _event, _within


class TestMasterCalendar(FrappeTestCase):
	def test_date_window_is_inclusive(self):
		self.assertTrue(_within(nowdate(), nowdate(), nowdate()))
		self.assertFalse(_within(add_days(nowdate(), 1), nowdate(), nowdate()))

	def test_alert_states_prioritize_at_risk_and_due_dates(self):
		self.assertEqual(_alert_state(add_days(nowdate(), -1)), "overdue")
		self.assertEqual(_alert_state(add_days(nowdate(), 1)), "due_soon")
		self.assertEqual(_alert_state(add_days(nowdate(), 30)), "scheduled")
		self.assertEqual(_alert_state(add_days(nowdate(), 30), "At Risk"), "overdue")

	def test_event_keeps_matter_and_job_context_for_calendar_chat(self):
		event = _event(
			key="control:TEST", date=nowdate(), kind="SOP Control", title="Deadline: Test Job",
			matter="MATTER-TEST", matter_title="Test Matter", job="LPOJ-TEST", job_title="Test Job",
			service="Litigation Support", status="Verified", control="Court order",
		)
		self.assertEqual(event["matter"], "MATTER-TEST")
		self.assertEqual(event["job"], "LPOJ-TEST")
		self.assertEqual(event["alert"], "due_soon")
