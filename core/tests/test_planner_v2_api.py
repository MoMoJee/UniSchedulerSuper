"""Planner v2 只读 API 必须使用 normalized occurrence ref 且无写副作用。"""

import hashlib
from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    CalendarCollectionVersion,
    CalendarEvent,
    CollaborativeCalendarGroup,
    EventOccurrenceOverride,
    EventRecurrenceSeries,
    EventShareGroup,
    GroupMembership,
    PlannerChangeSet,
    PlannerCohortAssignment,
    PlannerMigrationState,
    UserData,
)


@override_settings(PLANNER_STORAGE_MODE='normalized')
class PlannerV2ApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='planner-v2-user', password='test-password')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.start = timezone.make_aware(datetime(2026, 3, 1, 9, 0))
        self.end = self.start + timedelta(hours=1)

    def _mark_verified(self):
        source = UserData.objects.create(user=self.user, key='events', value='[]')
        PlannerMigrationState.objects.create(
            user=self.user,
            source_key='events',
            source_row_id=source.id,
            source_checksum=hashlib.sha256(b'[]').hexdigest(),
            status=PlannerMigrationState.STATUS_VERIFIED,
        )
        PlannerCohortAssignment.objects.create(
            user=self.user,
            storage_mode=PlannerCohortAssignment.MODE_NORMALIZED,
            entrypoints={'api_v2': {'mode': 'normalized'}},
        )

    def test_unverified_user_cannot_read_normalized_v2_projection(self):
        response = self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-04')

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'planner_normalized_read_not_enabled')

    def test_bootstrap_exposes_each_entrypoint_decision_without_business_writes(self):
        self._mark_verified()
        before = (CalendarEvent.objects.count(), PlannerChangeSet.objects.count())

        response = self.client.get('/api/v2/planner/bootstrap/')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['entrypoints']['api_v2']['mode'], 'normalized')
        self.assertEqual(response.json()['entrypoints']['web_calendar']['mode'], 'legacy')
        self.assertEqual(before, (CalendarEvent.objects.count(), PlannerChangeSet.objects.count()))

    def test_normalized_home_does_not_initialize_legacy_calendar_business_rows(self):
        self._mark_verified()
        assignment = PlannerCohortAssignment.objects.get(user=self.user)
        assignment.entrypoints['web_calendar'] = {'mode': 'normalized'}
        assignment.save(update_fields=['entrypoints'])
        self.client.force_login(self.user)

        response = self.client.get('/home/')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(UserData.objects.get(user=self.user, key='events').value, '[]')
        self.assertFalse(
            UserData.objects.filter(
                user=self.user, key__in=['events_groups', 'events_rrule_series', 'rrule_series_storage']
            ).exists()
        )

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

    def test_unbounded_series_expands_each_requested_future_window_without_row_growth(self):
        self._mark_verified()
        created = self.client.post(
            '/api/v2/events/',
            {
                'title': '无限日程',
                'start': '2026-07-13T10:00:00+08:00',
                'end': '2026-07-13T11:00:00+08:00',
                'recurrence': {'rrule': 'FREQ=DAILY;INTERVAL=1'},
            },
            format='json',
        )
        self.assertEqual(created.status_code, 201, created.content)
        counts_before = (CalendarEvent.objects.count(), EventRecurrenceSeries.objects.count())

        july = self.client.get('/api/v2/events/occurrences/?from=2026-07-13&to=2026-07-20')
        november = self.client.get('/api/v2/events/occurrences/?from=2026-11-01&to=2026-11-08')
        next_year = self.client.get('/api/v2/events/occurrences/?from=2027-07-13&to=2027-07-20')

        self.assertEqual(july.json()['count'], 7)
        self.assertEqual(november.json()['count'], 7)
        self.assertEqual(next_year.json()['count'], 7)
        self.assertEqual(counts_before, (CalendarEvent.objects.count(), EventRecurrenceSeries.objects.count()))

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

    def test_conflict_detector_reuses_occurrence_window_and_half_open_boundaries(self):
        self._mark_verified()
        CalendarEvent.objects.create(
            user=self.user, event_id='first', title='第一项', start_at=self.start, end_at=self.end
        )
        CalendarEvent.objects.create(
            user=self.user,
            event_id='overlap',
            title='冲突项',
            start_at=self.start + timedelta(minutes=30),
            end_at=self.end + timedelta(minutes=30),
        )
        CalendarEvent.objects.create(
            user=self.user,
            event_id='adjacent',
            title='相邻不冲突',
            start_at=self.end + timedelta(minutes=30),
            end_at=self.end + timedelta(hours=1),
        )

        response = self.client.get('/api/v2/events/conflicts/?from=2026-03-01&to=2026-03-02')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['count'], 1)
        ids = {item['occurrence_ref']['entity_id'] for item in response.json()['conflicts'][0]['items']}
        self.assertEqual(ids, {'first', 'overlap'})

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

    def test_recurrence_occurrence_and_full_series_can_detach_without_materializing_future_slots(self):
        self._mark_verified()
        created = self.client.post(
            '/api/v2/events/',
            {
                'title': '重复课程',
                'start': '2026-03-01T09:00:00+08:00',
                'end': '2026-03-01T10:00:00+08:00',
                'recurrence': {'rrule': 'FREQ=DAILY;COUNT=3'},
            },
            format='json',
        )
        master_id = created.json()['event']['event_id']
        refs = self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-05').json()['occurrences']

        detached = self.client.patch(
            f'/api/v2/events/{master_id}/',
            {
                'scope': 'single',
                'expected_version': refs[1]['occurrence_ref']['source_version'],
                'occurrence_ref': refs[1]['occurrence_ref'],
                'detach': True,
                'title': '独立补课',
            },
            format='json',
        )
        self.assertEqual(detached.status_code, 200, detached.content)
        self.assertNotEqual(detached.json()['event_id'], master_id)
        self.assertEqual(CalendarEvent.objects.filter(user=self.user).count(), 2)
        self.assertEqual(EventOccurrenceOverride.objects.get().kind, EventOccurrenceOverride.KIND_CANCELLED)

        current = self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-05').json()['occurrences']
        master_ref = next(item['occurrence_ref'] for item in current if item['occurrence_ref']['entity_id'] == master_id)
        detached_all = self.client.patch(
            f'/api/v2/events/{master_id}/',
            {
                'scope': 'all',
                'expected_version': master_ref['source_version'],
                'recurrence': None,
            },
            format='json',
        )
        self.assertEqual(detached_all.status_code, 200, detached_all.content)
        self.assertIsNotNone(EventRecurrenceSeries.objects.get(master_event__event_id=master_id).deleted_at)
        self.assertEqual(CalendarEvent.objects.filter(user=self.user).count(), 2)

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
        self.assertEqual(future.status_code, 422)
        self.assertEqual(future.json()['code'], 'invalid_scope')

    def test_this_and_future_split_creates_child_lineage_and_truncates_parent(self):
        self._mark_verified()
        create = self.client.post(
            '/api/v2/events/',
            {
                'title': '每日同步',
                'start': '2026-03-01T09:00:00+08:00',
                'end': '2026-03-01T10:00:00+08:00',
                'recurrence': {'rrule': 'FREQ=DAILY;COUNT=4'},
            },
            format='json',
        )
        event_id = create.json()['event']['event_id']
        occurrences = self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-06').json()['occurrences']
        anchor = occurrences[2]['occurrence_ref']

        split = self.client.patch(
            f'/api/v2/events/{event_id}/',
            {
                'scope': 'this_and_future',
                'expected_version': anchor['source_version'],
                'occurrence_ref': anchor,
                'title': '每日同步（新阶段）',
            },
            format='json',
        )
        after = self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-06').json()['occurrences']
        parent = EventRecurrenceSeries.objects.get(master_event__event_id=event_id)
        child = EventRecurrenceSeries.objects.exclude(pk=parent.pk).get()

        self.assertEqual(split.status_code, 200, split.content)
        self.assertEqual(parent.rrule_canonical, 'COUNT=2;FREQ=DAILY')
        self.assertEqual(child.parent_series_id, parent.id)
        self.assertEqual(child.split_recurrence_id, anchor['recurrence_id'])
        self.assertEqual([item['title'] for item in after], ['每日同步', '每日同步', '每日同步（新阶段）', '每日同步（新阶段）'])

    def test_finite_and_unbounded_series_cover_single_all_and_future_delete_scopes(self):
        self._mark_verified()
        for label, rule, initial_count in (
            ('finite', 'FREQ=DAILY;COUNT=6', 6),
            ('infinite', 'FREQ=DAILY', 10),
        ):
            with self.subTest(rule=label):
                # 每个作用域使用独立系列，避免前一项删除改变后一项的输入。
                series = []
                for scope in ('single', 'this_and_future', 'all'):
                    created = self.client.post(
                        '/api/v2/events/',
                        {
                            'title': f'{label}-{scope}',
                            'start': '2026-03-01T09:00:00+08:00',
                            'end': '2026-03-01T10:00:00+08:00',
                            'recurrence': {'rrule': rule},
                        },
                        format='json',
                    )
                    self.assertEqual(created.status_code, 201, created.content)
                    series.append(created.json()['event']['event_id'])

                def occurrences(event_id):
                    data = self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-11').json()
                    return [item for item in data['occurrences'] if item['occurrence_ref']['entity_id'] == event_id]

                single_before = occurrences(series[0])
                target = single_before[2]['occurrence_ref']
                deleted = self.client.delete(
                    f'/api/v2/events/{series[0]}/',
                    {'scope': 'single', 'expected_version': target['source_version'], 'occurrence_ref': target},
                    format='json',
                )
                self.assertEqual(deleted.status_code, 200, deleted.content)
                self.assertEqual(len(occurrences(series[0])), initial_count - 1)

                future_before = occurrences(series[1])
                anchor = future_before[2]['occurrence_ref']
                deleted = self.client.delete(
                    f'/api/v2/events/{series[1]}/',
                    {'scope': 'this_and_future', 'expected_version': anchor['source_version'], 'occurrence_ref': anchor},
                    format='json',
                )
                self.assertEqual(deleted.status_code, 200, deleted.content)
                self.assertEqual(len(occurrences(series[1])), 2)

                all_before = occurrences(series[2])
                deleted = self.client.delete(
                    f'/api/v2/events/{series[2]}/',
                    {
                        'scope': 'all',
                        'expected_version': all_before[0]['occurrence_ref']['source_version'],
                        'occurrence_ref': all_before[0]['occurrence_ref'],
                    },
                    format='json',
                )
                self.assertEqual(deleted.status_code, 200, deleted.content)
                self.assertEqual(occurrences(series[2]), [])

    def test_scope_edit_matrix_covers_single_all_time_shift_and_future_fields(self):
        self._mark_verified()
        for label, rule, expected_count in (
            ('finite', 'FREQ=DAILY;COUNT=5', 5),
            ('infinite', 'FREQ=DAILY', 7),
        ):
            with self.subTest(rule=label):
                created = self.client.post(
                    '/api/v2/events/',
                    {
                        'title': f'{label}-scope-edit',
                        'description': 'original',
                        'start': '2026-03-01T09:00:00+08:00',
                        'end': '2026-03-01T10:00:00+08:00',
                        'recurrence': {'rrule': rule},
                    },
                    format='json',
                )
                event_id = created.json()['event']['event_id']

                def occurrences():
                    data = self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-08').json()
                    return [item for item in data['occurrences'] if item['occurrence_ref']['entity_id'] == event_id]

                rows = occurrences()
                target = rows[1]['occurrence_ref']
                patched = self.client.patch(
                    f'/api/v2/events/{event_id}/',
                    {
                        'scope': 'single', 'expected_version': target['source_version'],
                        'occurrence_ref': target, 'description': 'single-only',
                    },
                    format='json',
                )
                self.assertEqual(patched.status_code, 200, patched.content)
                self.assertEqual([item['description'] for item in occurrences()].count('single-only'), 1)

                rows = occurrences()
                ref = rows[0]['occurrence_ref']
                patched = self.client.patch(
                    f'/api/v2/events/{event_id}/',
                    {
                        'scope': 'all', 'expected_version': ref['source_version'], 'occurrence_ref': ref,
                        'description': 'all-events',
                        'start': '2026-03-01T10:30:00+08:00',
                        'end': '2026-03-01T12:00:00+08:00',
                    },
                    format='json',
                )
                self.assertEqual(patched.status_code, 200, patched.content)
                rows = occurrences()
                self.assertEqual(len(rows), expected_count)
                self.assertEqual(rows[1]['description'], 'single-only')
                self.assertTrue(all(item['description'] == 'all-events' for index, item in enumerate(rows) if index != 1))
                local_tz = timezone.get_fixed_timezone(480)
                self.assertTrue(all(datetime.fromisoformat(item['start']).astimezone(local_tz).strftime('%H:%M') == '10:30' for item in rows))
                self.assertTrue(all(datetime.fromisoformat(item['end']).astimezone(local_tz).strftime('%H:%M') == '12:00' for item in rows))

                anchor = rows[2]['occurrence_ref']
                patched = self.client.patch(
                    f'/api/v2/events/{event_id}/',
                    {
                        'scope': 'this_and_future', 'expected_version': anchor['source_version'],
                        'occurrence_ref': anchor, 'description': 'future-events',
                        'override_policy': 'map_by_ordinal',
                    },
                    format='json',
                )
                self.assertEqual(patched.status_code, 200, patched.content)
                data = self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-08').json()['occurrences']
                matching = [item for item in data if item['title'] == f'{label}-scope-edit']
                self.assertEqual([item['description'] for item in matching[:2]], ['all-events', 'single-only'])
                self.assertTrue(all(item['description'] == 'future-events' for item in matching[2:]))

    def test_future_rule_transitions_cover_custom_rule_and_stop_repeating(self):
        self._mark_verified()
        created = self.client.post(
            '/api/v2/events/',
            {
                'title': '规则切分', 'start': '2026-03-01T09:00:00+08:00',
                'end': '2026-03-01T10:00:00+08:00',
                'recurrence': {'rrule': 'FREQ=DAILY;COUNT=6'},
            }, format='json',
        )
        event_id = created.json()['event']['event_id']
        rows = self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-10').json()['occurrences']
        anchor = rows[2]['occurrence_ref']
        split = self.client.patch(
            f'/api/v2/events/{event_id}/',
            {
                'scope': 'this_and_future', 'expected_version': anchor['source_version'],
                'occurrence_ref': anchor, 'title': '改为每周',
                'recurrence': {'rrule': 'FREQ=WEEKLY;COUNT=2'},
                'override_policy': 'keep_as_single',
            }, format='json',
        )
        self.assertEqual(split.status_code, 200, split.content)
        all_rows = self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-20').json()['occurrences']
        self.assertEqual([item['title'] for item in all_rows], ['规则切分', '规则切分', '改为每周', '改为每周'])

        child_id = split.json()['event_id']
        child_rows = [item for item in all_rows if item['occurrence_ref']['entity_id'] == child_id]
        stop_anchor = child_rows[1]['occurrence_ref']
        stopped = self.client.patch(
            f'/api/v2/events/{child_id}/',
            {
                'scope': 'this_and_future', 'expected_version': stop_anchor['source_version'],
                'occurrence_ref': stop_anchor, 'title': '最后一次', 'recurrence': None,
                'override_policy': 'discard_with_audit',
            }, format='json',
        )
        self.assertEqual(stopped.status_code, 200, stopped.content)
        final_rows = self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-20').json()['occurrences']
        self.assertEqual([item['title'] for item in final_rows], ['规则切分', '规则切分', '改为每周', '最后一次'])

    def test_future_time_shift_maps_existing_override_by_ordinal_without_extra_occurrence(self):
        self._mark_verified()
        created = self.client.post(
            '/api/v2/events/',
            {
                'title': '时间切分', 'start': '2026-03-01T09:00:00+08:00',
                'end': '2026-03-01T10:00:00+08:00', 'recurrence': {'rrule': 'FREQ=DAILY;COUNT=6'},
            }, format='json',
        )
        event_id = created.json()['event']['event_id']
        rows = self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-09').json()['occurrences']
        override_ref = rows[3]['occurrence_ref']
        modified = self.client.patch(
            f'/api/v2/events/{event_id}/',
            {
                'scope': 'single', 'expected_version': override_ref['source_version'],
                'occurrence_ref': override_ref, 'description': '保留的例外',
            }, format='json',
        )
        self.assertEqual(modified.status_code, 200, modified.content)
        rows = self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-09').json()['occurrences']
        anchor = rows[2]['occurrence_ref']
        split = self.client.patch(
            f'/api/v2/events/{event_id}/',
            {
                'scope': 'this_and_future', 'expected_version': anchor['source_version'],
                'occurrence_ref': anchor, 'start': '2026-03-03T10:00:00+08:00',
                'end': '2026-03-03T11:00:00+08:00', 'override_policy': 'map_by_ordinal',
            }, format='json',
        )
        self.assertEqual(split.status_code, 200, split.content)
        after = self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-09').json()['occurrences']
        self.assertEqual(len(after), 6)
        local_tz = timezone.get_fixed_timezone(480)
        hours = [datetime.fromisoformat(item['start']).astimezone(local_tz).strftime('%H:%M') for item in after]
        self.assertEqual(hours, ['09:00', '09:00', '10:00', '10:00', '10:00', '10:00'])
        exception = next(item for item in after if item['description'] == '保留的例外')
        self.assertEqual(datetime.fromisoformat(exception['start']).astimezone(local_tz).strftime('%m-%d %H:%M'), '03-04 10:00')

    def test_single_event_can_attach_recurrence_and_all_scope_can_change_boundedness(self):
        self._mark_verified()
        created = self.client.post(
            '/api/v2/events/',
            {'title': '单次转重复', 'start': '2026-03-01T09:00:00+08:00', 'end': '2026-03-01T10:00:00+08:00'},
            format='json',
        )
        event_id = created.json()['event']['event_id']
        attached = self.client.patch(
            f'/api/v2/events/{event_id}/',
            {'scope': 'all', 'expected_version': 1, 'recurrence': {'rrule': 'FREQ=DAILY;COUNT=3'}},
            format='json',
        )
        self.assertEqual(attached.status_code, 200, attached.content)
        rows = self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-10').json()['occurrences']
        self.assertEqual(len(rows), 3)

        ref = rows[0]['occurrence_ref']
        unbounded = self.client.patch(
            f'/api/v2/events/{event_id}/',
            {
                'scope': 'all', 'expected_version': ref['source_version'],
                'occurrence_ref': ref, 'recurrence': {'rrule': 'FREQ=DAILY'},
            }, format='json',
        )
        self.assertEqual(unbounded.status_code, 200, unbounded.content)
        rows = self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-10').json()['occurrences']
        self.assertEqual(len(rows), 9)

        ref = rows[0]['occurrence_ref']
        bounded = self.client.patch(
            f'/api/v2/events/{event_id}/',
            {
                'scope': 'all', 'expected_version': ref['source_version'],
                'occurrence_ref': ref, 'recurrence': {'rrule': 'FREQ=DAILY;COUNT=2'},
            }, format='json',
        )
        self.assertEqual(bounded.status_code, 200, bounded.content)
        self.assertEqual(
            self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-10').json()['count'],
            2,
        )

    def test_event_share_relations_can_be_created_replaced_and_read_from_v2(self):
        self._mark_verified()
        group = CollaborativeCalendarGroup.objects.create(
            share_group_id='owned-group', share_group_name='我的分享组', owner=self.user, share_group_color='#123456'
        )
        GroupMembership.objects.create(share_group=group, user=self.user, role='owner', member_color='#654321')
        created = self.client.post(
            '/api/v2/events/',
            {
                'title': '可分享重复日程', 'start': '2026-03-01T09:00:00+08:00',
                'end': '2026-03-01T10:00:00+08:00', 'recurrence': {'rrule': 'FREQ=DAILY;COUNT=2'},
                'share_group_ids': ['owned-group'],
            }, format='json',
        )
        self.assertEqual(created.status_code, 201, created.content)
        event_id = created.json()['event']['event_id']
        self.assertTrue(EventShareGroup.objects.filter(event__event_id=event_id, share_group=group).exists())
        shared = self.client.get('/api/v2/share-groups/owned-group/occurrences/?from=2026-03-01&to=2026-03-04')
        self.assertEqual(shared.status_code, 200, shared.content)
        self.assertEqual(shared.json()['count'], 2)
        self.assertEqual(shared.json()['current_user_id'], self.user.id)
        self.assertTrue(shared.json()['members'])

        ref = shared.json()['occurrences'][0]['occurrence_ref']
        replaced = self.client.patch(
            f'/api/v2/events/{event_id}/',
            {'scope': 'all', 'expected_version': ref['source_version'], 'share_group_ids': []},
            format='json',
        )
        self.assertEqual(replaced.status_code, 200, replaced.content)
        self.assertFalse(EventShareGroup.objects.filter(event__event_id=event_id).exists())
        self.assertEqual(
            self.client.get('/api/v2/share-groups/owned-group/occurrences/?from=2026-03-01&to=2026-03-04').json()['count'],
            0,
        )

    @override_settings(PLANNER_STORAGE_MODE='shadow')
    def test_shadow_cohort_can_read_but_cannot_write_and_rejection_has_no_side_effects(self):
        self._mark_verified()
        event = CalendarEvent.objects.create(
            user=self.user,
            event_id='shadow-event',
            title='影子读取',
            start_at=self.start,
            end_at=self.end,
        )
        counts_before = {
            'events': CalendarEvent.objects.count(),
            'changesets': PlannerChangeSet.objects.count(),
            'collections': CalendarCollectionVersion.objects.count(),
        }

        read = self.client.get('/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-02')
        write = self.client.patch(
            f'/api/v2/events/{event.event_id}/',
            {'scope': 'all', 'expected_version': 1, 'title': '不应写入'},
            format='json',
        )

        self.assertEqual(read.status_code, 200, read.content)
        self.assertEqual(write.status_code, 409, write.content)
        self.assertEqual(write.json()['code'], 'planner_normalized_write_not_enabled')
        self.assertEqual(
            counts_before,
            {
                'events': CalendarEvent.objects.count(),
                'changesets': PlannerChangeSet.objects.count(),
                'collections': CalendarCollectionVersion.objects.count(),
            },
        )

    def test_shared_occurrences_use_membership_and_normalized_relationship_join(self):
        self._mark_verified()
        owner = User.objects.create_user(username='planner-share-owner', password='test-password')
        group = CollaborativeCalendarGroup.objects.create(
            share_group_id='shared-1', share_group_name='项目组', owner=owner, share_group_color='#102030'
        )
        GroupMembership.objects.create(share_group=group, user=self.user, member_color='#445566')
        GroupMembership.objects.create(share_group=group, user=owner, role='owner', member_color='#abcdef')
        event = CalendarEvent.objects.create(
            user=owner, event_id='shared-event', title='共享评审', start_at=self.start, end_at=self.end
        )
        EventShareGroup.objects.create(event=event, share_group=group)

        response = self.client.get('/api/v2/share-groups/shared-1/occurrences/?from=2026-03-01&to=2026-03-02')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['count'], 1)
        item = response.json()['occurrences'][0]
        self.assertEqual(item['occurrence_ref']['entity_id'], 'shared-event')
        self.assertEqual(item['owner_username'], 'planner-share-owner')
        self.assertEqual(item['member_color'], '#abcdef')
        self.assertTrue(item['read_only'])

    def test_normalized_course_import_is_atomic_and_never_writes_legacy_userdata(self):
        self._mark_verified()
        assignment = PlannerCohortAssignment.objects.get(user=self.user)
        assignment.entrypoints['course_import'] = {'mode': 'normalized'}
        assignment.save(update_fields=['entrypoints'])
        payload = {
            'courses': [
                {
                    'name': '离散数学',
                    'first_start': '2026-03-02T08:00:00+08:00',
                    'first_end': '2026-03-02T09:30:00+08:00',
                    'rrule': 'FREQ=WEEKLY;COUNT=2',
                }
            ]
        }

        response = self.client.post('/api/import/confirm/', payload, format='json')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['imported_count'], 1)
        self.assertEqual(CalendarEvent.objects.filter(user=self.user, title='离散数学').count(), 1)
        self.assertEqual(UserData.objects.get(user=self.user, key='events').value, '[]')

        repeated = self.client.post('/api/import/confirm/', payload, format='json')
        self.assertEqual(repeated.status_code, 200, repeated.content)
        self.assertEqual(repeated.json()['imported_count'], 0)
        self.assertEqual(CalendarEvent.objects.filter(user=self.user, title='离散数学').count(), 1)

        invalid = {
            'courses': [
                {
                    'name': '应回滚课程',
                    'first_start': '2026-03-03T08:00:00+08:00',
                    'first_end': '2026-03-03T09:00:00+08:00',
                },
                {'name': '坏课程', 'first_start': '', 'first_end': ''},
            ]
        }
        failed = self.client.post('/api/import/confirm/', invalid, format='json')
        self.assertEqual(failed.status_code, 422, failed.content)
        self.assertFalse(CalendarEvent.objects.filter(user=self.user, title='应回滚课程').exists())
