"""Planner V1 URLs fail deterministically and never touch archived data."""

import json

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import CalendarEvent, Reminder, Todo, UserData
from core.views_planner_legacy import LEGACY_PLANNER_REPLACEMENTS


class PlannerV1RetiredApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="v1-retired", password="test-password")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.archives = {
            key: UserData.objects.create(user=self.user, key=key, value=json.dumps([{"sentinel": key}]))
            for key in ("events", "events_groups", "todos", "reminders")
        }

    def test_every_retired_url_returns_stable_410_with_replacement_and_zero_writes(self):
        before_rows = (CalendarEvent.objects.count(), Todo.objects.count(), Reminder.objects.count())
        before_archive = {key: row.value for key, row in self.archives.items()}

        for path, replacement in LEGACY_PLANNER_REPLACEMENTS.items():
            with self.subTest(path=path):
                response = self.client.post(path, {}, format="json")
                self.assertEqual(response.status_code, 410, response.content)
                body = response.json()
                self.assertEqual(body["code"], "planner_v1_api_retired")
                self.assertEqual(body["requested_path"], path)
                self.assertEqual(body["replacement"], replacement)

        self.assertEqual(before_rows, (CalendarEvent.objects.count(), Todo.objects.count(), Reminder.objects.count()))
        self.assertEqual(
            before_archive,
            {key: UserData.objects.get(pk=row.pk).value for key, row in self.archives.items()},
        )

    def test_authentication_is_still_required(self):
        self.client.force_authenticate(user=None)
        response = self.client.get("/get_calendar/events/")
        self.assertIn(response.status_code, {401, 403})

    def test_legacy_shared_events_read_is_retired_with_windowed_v2_target(self):
        response = self.client.get("/api/share-groups/team-1/events/")
        self.assertEqual(response.status_code, 410, response.content)
        self.assertEqual(response.json()["code"], "planner_v1_api_retired")
        self.assertEqual(
            response.json()["replacement"]["path"],
            "/api/v2/share-groups/team-1/occurrences/",
        )
