"""Planner v2 只读 API 必须使用 normalized occurrence ref 且无写副作用。"""

from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import CalendarEvent, EventRecurrenceSeries, PlannerMigrationState


class PlannerV2ApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='planner-v2-user', password='test-password')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.start = timezone.make_aware(datetime(2026, 3, 1, 9, 0))
        self.end = self.start + timedelta(hours=1)

    def _mark_verified(self):
        PlannerMigrationState.objects.create(
            user=self.user,
            source_key='events',
            source_checksum='verified-source',
            status=PlannerMigrationState.STATUS_VERIFIED,
        )

    def test_unverified_user_cannot_read_normalized_v2_projection(self):
        response = self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-04')

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'planner_normalized_not_verified')

    def test_occurrences_return_stable_composite_ref_without_writes(self):
        self._mark_verified()
        master = CalendarEvent.objects.create(
            user=self.user,
            event_id='event-master',
            title='每日站会',
            start_at=self.start,
            end_at=self.end,
        )
        EventRecurrenceSeries.objects.create(
            user=self.user,
            series_id='series-1',
            master_event=master,
            ical_uid='series-1@example.test',
            rrule='FREQ=DAILY;COUNT=2',
            rrule_canonical='COUNT=2;FREQ=DAILY',
            dtstart_at=self.start,
        )
        count_before = CalendarEvent.objects.count()

        response = self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-04')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['count'], 2)
        self.assertEqual(payload['occurrences'][0]['occurrence_ref']['entity_id'], 'event-master')
        self.assertEqual(payload['occurrences'][0]['occurrence_ref']['series_id'], 'series-1')
        self.assertEqual(payload['occurrences'][0]['occurrence_ref']['recurrence_id'], '20260301T090000')
        self.assertEqual(CalendarEvent.objects.count(), count_before)

    def test_definitions_return_series_metadata_and_validate_range(self):
        self._mark_verified()
        event = CalendarEvent.objects.create(
            user=self.user,
            event_id='event-master',
            title='每日站会',
            start_at=self.start,
            end_at=self.end,
        )
        EventRecurrenceSeries.objects.create(
            user=self.user,
            series_id='series-1',
            master_event=event,
            ical_uid='series-1@example.test',
            rrule='FREQ=DAILY;COUNT=2',
            rrule_canonical='COUNT=2;FREQ=DAILY',
            dtstart_at=self.start,
        )

        response = self.client.get('/api/v2/events/definitions/?from=2026-03-01&to=2026-03-04')
        invalid = self.client.get('/api/v2/events/definitions/?from=2026-03-04&to=2026-03-01')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['definitions'][0]['recurrence']['series_id'], 'series-1')
        self.assertEqual(invalid.status_code, 400)
