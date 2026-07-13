import hashlib
from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from icalendar import Calendar
from rest_framework.authtoken.models import Token

from core.models import (
    CalendarEvent,
    EventGroup,
    EventRecurrenceSeries,
    PlannerCohortAssignment,
    PlannerMigrationState,
    Reminder,
    Todo,
    UserData,
)
from core.planner.commands import PlannerCommandService
from core.planner.entities import PlannerEntityCommandService


@override_settings(PLANNER_STORAGE_MODE="normalized")
class CalendarFeedV2Tests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="feed-v2", password="secret")
        self.token = Token.objects.create(user=self.user)
        source = UserData.objects.create(
            user=self.user,
            key="events",
            value='[{"id":"legacy-only","title":"不得进入V2 Feed"}]',
        )
        PlannerMigrationState.objects.create(
            user=self.user,
            source_key="events",
            source_row_id=source.id,
            source_checksum=hashlib.sha256(source.value.encode()).hexdigest(),
            status=PlannerMigrationState.STATUS_VERIFIED,
        )
        PlannerCohortAssignment.objects.create(
            user=self.user,
            storage_mode=PlannerCohortAssignment.MODE_NORMALIZED,
            entrypoints={"calendar_feed": {"mode": "normalized"}},
        )
        self.group = EventGroup.objects.create(user=self.user, name="课程", color="#123456")
        self.single = PlannerCommandService.create_event(self.user, {
            "title": "单次课程",
            "description": "第一行\n第二行,分号;反斜线\\",
            "location": "教学楼",
            "group_id": self.group.group_id,
            "start": "2026-07-13T10:00:00+08:00",
            "end": "2026-07-13T11:00:00+08:00",
        })
        self.series_master = PlannerCommandService.create_event(self.user, {
            "title": "重复课程",
            "start": "2026-07-14T09:00:00+08:00",
            "end": "2026-07-14T10:00:00+08:00",
            "recurrence": {"rrule": "FREQ=WEEKLY;COUNT=3"},
        })
        self.todo = PlannerEntityCommandService.create_todo(self.user, {
            "title": "有期限待办",
            "description": "todo body",
            "group_id": self.group.group_id,
            "due": "2026-07-15T12:00:00+08:00",
        })
        PlannerEntityCommandService.create_todo(self.user, {"title": "无期限待办"})
        self.reminder = PlannerEntityCommandService.create_reminder(self.user, {
            "title": "喝水",
            "content": "reminder body",
            "trigger": "2026-07-16T14:00:00+08:00",
            "recurrence": {"rrule": "FREQ=DAILY;COUNT=2"},
        })

    def _feed(self, feed_type="all"):
        return self.client.get(
            "/api/calendar/feed/",
            {"token": self.token.key, "type": feed_type},
        )

    @staticmethod
    def _events(response):
        calendar = Calendar.from_ical(response.content)
        return [item for item in calendar.walk() if item.name == "VEVENT"]

    def test_all_feed_uses_only_normalized_sources_and_shared_mapper(self):
        response = self._feed()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, max-age=300")
        events = self._events(response)
        summaries = {str(item.get("SUMMARY")) for item in events}
        self.assertIn("[课程] 单次课程", summaries)
        self.assertIn("重复课程", summaries)
        self.assertIn("[待办] [课程] 有期限待办", summaries)
        self.assertIn("[提醒] 喝水", summaries)
        self.assertNotIn("不得进入V2 Feed", response.content.decode())
        self.assertNotIn("无期限待办", response.content.decode())
        recurring = next(item for item in events if str(item.get("SUMMARY")) == "重复课程")
        reminder = next(item for item in events if str(item.get("SUMMARY")) == "[提醒] 喝水")
        self.assertEqual(recurring.get("RRULE").to_ical(), b"FREQ=WEEKLY;COUNT=3")
        self.assertEqual(reminder.get("RRULE").to_ical(), b"FREQ=DAILY;COUNT=2")
        self.assertEqual(len(reminder.subcomponents), 1)
        self.assertEqual(reminder.subcomponents[0].name, "VALARM")

    def test_feed_type_filters_cover_all_profiles(self):
        expected = {
            "events": {"[课程] 单次课程", "重复课程"},
            "todos": {"[待办] [课程] 有期限待办"},
            "reminders": {"[提醒] 喝水"},
        }
        for feed_type, summaries in expected.items():
            with self.subTest(feed_type=feed_type):
                response = self._feed(feed_type)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    {str(item.get("SUMMARY")) for item in self._events(response)},
                    summaries,
                )

    def test_feed_read_is_side_effect_free(self):
        tracked = [CalendarEvent, EventRecurrenceSeries, Todo, Reminder]
        before_counts = [model.objects.count() for model in tracked]
        before_versions = list(CalendarEvent.objects.order_by("id").values_list("id", "version", "updated_at"))
        source_before = UserData.objects.get(user=self.user, key="events").value
        for feed_type in ("all", "events", "todos", "reminders"):
            self.assertEqual(self._feed(feed_type).status_code, 200)
        self.assertEqual([model.objects.count() for model in tracked], before_counts)
        self.assertEqual(
            list(CalendarEvent.objects.order_by("id").values_list("id", "version", "updated_at")),
            before_versions,
        )
        self.assertEqual(UserData.objects.get(user=self.user, key="events").value, source_before)

    def test_auth_parameters_and_unassigned_user_cannot_fallback(self):
        self.assertEqual(self.client.get("/api/calendar/feed/").status_code, 400)
        self.assertEqual(self.client.get("/api/calendar/feed/", {"token": "bad"}).status_code, 403)
        self.assertEqual(self._feed("unknown").status_code, 400)

        legacy_user = User.objects.create_user(username="feed-legacy")
        legacy_token = Token.objects.create(user=legacy_user)
        UserData.objects.create(user=legacy_user, key="events", value="[]")
        response = self.client.get("/api/calendar/feed/", {"token": legacy_token.key, "type": "events"})
        self.assertEqual(response.status_code, 503)
