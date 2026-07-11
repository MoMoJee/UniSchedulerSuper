"""Planner v2 只读 API 必须使用 normalized occurrence ref 且无写副作用。"""

from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    CalendarCollectionVersion,
    CalendarEvent,
    EventOccurrenceOverride,
    EventRecurrenceSeries,
    PlannerChangeSet,
    PlannerMigrationState,
)


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

    def test_create_and_patch_single_event_use_versioned_normalized_command(self):
        self._mark_verified()
        create = self.client.post(
            '/api/v2/events/',
            {
                'title': '架构评审',
                'description': '先看 ADR',
                'start': '2026-03-01T09:00:00+08:00',
                'end': '2026-03-01T10:00:00+08:00',
            },
            format='json',
        )

        self.assertEqual(create.status_code, 201, create.content)
        event_id = create.json()['event']['event_id']
        patch = self.client.patch(
            f'/api/v2/events/{event_id}/',
            {'scope': 'all', 'expected_version': 1, 'title': '架构评审（已确认）'},
            format='json',
        )
        event = CalendarEvent.objects.get(event_id=event_id)

        self.assertEqual(patch.status_code, 200, patch.content)
        self.assertEqual(event.title, '架构评审（已确认）')
        self.assertEqual(event.version, 2)
        self.assertEqual(CalendarCollectionVersion.objects.get(user=self.user).version, 2)
        self.assertEqual(PlannerChangeSet.objects.filter(user=self.user).count(), 2)

    def test_create_all_day_event_returns_its_definition(self):
        self._mark_verified()

        create = self.client.post(
            '/api/v2/events/',
            {'title': '全天培训', 'is_all_day': True, 'start': '2026-03-01', 'end': '2026-03-02'},
            format='json',
        )

        self.assertEqual(create.status_code, 201, create.content)
        self.assertTrue(create.json()['event']['is_all_day'])
        self.assertEqual(create.json()['event']['start'], '2026-03-01')

    def test_recurrence_single_patch_writes_sparse_override_and_search_returns_ref(self):
        self._mark_verified()
        create = self.client.post(
            '/api/v2/events/',
            {
                'title': '每周项目同步',
                'start': '2026-03-01T09:00:00+08:00',
                'end': '2026-03-01T10:00:00+08:00',
                'recurrence': {'rrule': 'FREQ=DAILY;COUNT=3'},
            },
            format='json',
        )
        self.assertEqual(create.status_code, 201, create.content)
        event_id = create.json()['event']['event_id']
        occurrence_response = self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-05')
        second_ref = occurrence_response.json()['occurrences'][1]['occurrence_ref']
        count_before = CalendarEvent.objects.count()

        patch = self.client.patch(
            f'/api/v2/events/{event_id}/',
            {
                'scope': 'single',
                'expected_version': second_ref['source_version'],
                'occurrence_ref': second_ref,
                'title': '项目同步（仅此一次）',
            },
            format='json',
        )
        search = self.client.get('/api/v2/search/?q=仅此一次&from=2026-03-01&to=2026-03-05')

        self.assertEqual(patch.status_code, 200, patch.content)
        self.assertEqual(CalendarEvent.objects.count(), count_before)
        self.assertEqual(EventOccurrenceOverride.objects.filter(kind='modified').count(), 1)
        self.assertEqual(search.status_code, 200, search.content)
        self.assertEqual(search.json()['total'], 1)
        self.assertEqual(search.json()['results'][0]['occurrence_ref']['recurrence_id'], second_ref['recurrence_id'])
        self.assertEqual(patch.json()['source_version'], 1)

    def test_recurrence_single_delete_cancels_only_target_occurrence(self):
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
        occurrences = self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-04').json()['occurrences']
        target_ref = occurrences[0]['occurrence_ref']

        deleted = self.client.delete(
            '/api/v2/events/event-master/',
            {'scope': 'single', 'expected_version': target_ref['source_version'], 'occurrence_ref': target_ref},
            format='json',
        )
        remaining = self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-04').json()

        self.assertEqual(deleted.status_code, 200, deleted.content)
        self.assertEqual(EventOccurrenceOverride.objects.filter(kind='cancelled').count(), 1)
        self.assertEqual(remaining['count'], 1)

    def test_write_rejects_unverified_and_stale_or_future_scope(self):
        denied = self.client.post(
            '/api/v2/events/',
            {'title': '不应写入', 'start': '2026-03-01T09:00:00+08:00', 'end': '2026-03-01T10:00:00+08:00'},
            format='json',
        )
        self.assertEqual(denied.status_code, 409)

        self._mark_verified()
        event = CalendarEvent.objects.create(user=self.user, event_id='single', title='单次', start_at=self.start, end_at=self.end, version=2)
        stale = self.client.patch('/api/v2/events/single/', {'scope': 'all', 'expected_version': 1, 'title': '冲突'}, format='json')
        future = self.client.patch(
            '/api/v2/events/single/',
            {'scope': 'this_and_future', 'expected_version': event.version, 'title': '不支持'},
            format='json',
        )

        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()['code'], 'version_conflict')
        self.assertEqual(future.status_code, 409)
        self.assertEqual(future.json()['code'], 'recurrence_split_requires_override_policy')
