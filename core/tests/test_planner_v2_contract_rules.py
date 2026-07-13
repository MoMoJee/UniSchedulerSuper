"""HTTP-only Planner V2 rules that clients may rely on."""

import hashlib

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.models import PlannerCohortAssignment, PlannerMigrationState, UserData


@override_settings(PLANNER_STORAGE_MODE="normalized")
class PlannerV2ContractRuleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="v2-contract", password="test-password")
        source = UserData.objects.create(user=self.user, key="events", value="[]")
        PlannerMigrationState.objects.create(
            user=self.user, source_key="events", source_row_id=source.id,
            source_checksum=hashlib.sha256(b"[]").hexdigest(),
            status=PlannerMigrationState.STATUS_VERIFIED,
        )
        PlannerCohortAssignment.objects.create(
            user=self.user, storage_mode=PlannerCohortAssignment.MODE_NORMALIZED,
            entrypoints={"api_v2": {"mode": "normalized"}},
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_entity_endpoints_reject_unknown_fields_instead_of_silent_success(self):
        cases = (
            ("/api/v2/groups/", {"name": "组", "colour": "#fff"}),
            ("/api/v2/todos/", {"title": "待办", "due_date": "2026-07-14"}),
            ("/api/v2/reminders/", {"title": "提醒", "trigger": "2026-07-14T09:00:00+08:00", "rrule": "FREQ=DAILY"}),
        )
        for path, body in cases:
            with self.subTest(path=path):
                response = self.client.post(path, body, format="json")
                self.assertEqual(response.status_code, 422, response.content)
                self.assertEqual(response.json()["code"], "unsupported_field")

    def test_event_all_scope_can_shift_clock_but_not_series_start_date(self):
        created = self.client.post(
            "/api/v2/events/",
            {
                "title": "日期边界", "start": "2026-07-13T10:00:00+08:00",
                "end": "2026-07-13T11:00:00+08:00",
                "recurrence": {"rrule": "FREQ=DAILY;COUNT=3"},
            }, format="json",
        ).json()["event"]

        clock_shift = self.client.patch(
            f"/api/v2/events/{created['event_id']}/",
            {
                "scope": "all", "expected_version": created["recurrence"]["source_version"],
                "start": "2026-07-13T12:00:00+08:00", "end": "2026-07-13T13:00:00+08:00",
            }, format="json",
        )
        self.assertEqual(clock_shift.status_code, 200, clock_shift.content)

        date_shift = self.client.patch(
            f"/api/v2/events/{created['event_id']}/",
            {
                "scope": "all", "expected_version": clock_shift.json()["source_version"],
                "start": "2026-07-14T12:00:00+08:00", "end": "2026-07-14T13:00:00+08:00",
            }, format="json",
        )
        self.assertEqual(date_shift.status_code, 422, date_shift.content)
        self.assertEqual(date_shift.json()["code"], "series_date_change_forbidden")
