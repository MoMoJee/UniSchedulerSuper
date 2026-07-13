from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from core.models import CalendarEvent, EventRecurrenceSeries
from core.planner.commands import PlannerCommandService


class PlannerICalendarIdentityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ical-identity-user", password="test-password")

    def test_direct_event_save_assigns_stable_identity(self):
        start = timezone.make_aware(datetime(2026, 7, 13, 10))
        event = CalendarEvent.objects.create(
            user=self.user, event_id="event-1", title="测试", start_at=start,
            end_at=start + timedelta(hours=1), is_all_day=False,
        )
        self.assertEqual(event.ical_uid, "evt-event-1@unischeduler")
        self.assertEqual(event.caldav_resource_name, "event-1")
        event.title = "修改"
        event.save(update_fields={"title"})
        event.refresh_from_db()
        self.assertEqual(event.ical_uid, "evt-event-1@unischeduler")
        self.assertEqual(event.caldav_resource_name, "event-1")

    def test_command_assigns_distinct_series_identity(self):
        event = PlannerCommandService.create_event(self.user, {
            "title": "重复",
            "start": "2026-07-13T10:00:00+08:00",
            "end": "2026-07-13T11:00:00+08:00",
            "recurrence": {"series_id": "series-1", "rrule": "FREQ=DAILY;COUNT=2"},
        }, event_id="event-1")
        series = EventRecurrenceSeries.objects.get(master_event=event)
        self.assertEqual(event.ical_uid, "evt-event-1@unischeduler")
        self.assertEqual(series.ical_uid, "evt-series-series-1@unischeduler")
        self.assertEqual(series.caldav_resource_name, "evt-series-series-1")

    def test_per_user_uid_and_resource_constraints_reject_duplicates(self):
        start = timezone.make_aware(datetime(2026, 7, 13, 10))
        CalendarEvent.objects.create(
            user=self.user, event_id="event-1", ical_uid="external@uid", caldav_resource_name="external-resource",
            title="一", start_at=start, end_at=start + timedelta(hours=1), is_all_day=False,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            CalendarEvent.objects.create(
                user=self.user, event_id="event-2", ical_uid="external@uid", caldav_resource_name="other-resource",
                title="二", start_at=start, end_at=start + timedelta(hours=1), is_all_day=False,
            )
