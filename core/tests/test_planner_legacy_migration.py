"""P2 legacy→normalized 旁路迁移命令的隔离测试。"""

import json
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from core.models import (
    CalendarEvent,
    EventGroup,
    EventRecurrenceSeries,
    EventRecurrenceExDate,
    EventReminderLink,
    EventTag,
    PlannerLegacyIdMap,
    PlannerMigrationIssue,
    PlannerMigrationState,
    Reminder,
    Todo,
    TodoReminderLink,
    TodoTag,
    UserData,
)


class PlannerLegacyMigrationCommandTests(TestCase):
    """默认计划只读；apply 仅创建正规化旁路投影。"""

    def setUp(self):
        self.user = User.objects.create_user(username='planner-migration-user', password='test-password')

    def _put(self, key, value):
        UserData.objects.create(user=self.user, key=key, value=json.dumps(value))

    def _run(self, *args):
        output = StringIO()
        call_command('migrate_planner_legacy', '--user-id', self.user.id, *args, stdout=output)
        return json.loads(output.getvalue())

    def test_dry_run_reports_plan_without_creating_normalized_rows(self):
        self._put('events_groups', [{'id': 'group-1', 'name': '学习', 'color': '#123456'}])
        self._put('todos', [{'id': 'todo-1', 'title': '整理资料', 'groupID': 'group-1', 'priority_score': 2}])
        self._put('reminders', [])
        self._put('events', [])

        report = self._run('--dry-run')

        self.assertFalse(report['apply'])
        self.assertEqual(report['cohort_eligible_user_count'], 1)
        self.assertEqual(EventGroup.objects.count(), 0)
        self.assertEqual(Todo.objects.count(), 0)
        self.assertEqual(PlannerMigrationState.objects.count(), 0)

    def test_dry_run_quarantines_unparseable_data_before_any_apply_attempt(self):
        self._put('events_groups', [])
        self._put('todos', [])
        self._put('reminders', [])
        self._put('events', [{'id': 'broken-event', 'title': '损坏日程', 'start': 'not-a-date', 'end': '2026-03-01T10:00'}])

        report = self._run('--dry-run')

        user_report = report['users'][0]
        self.assertFalse(user_report['cohort_eligible'])
        self.assertIn('event_time_invalid', [item['code'] for item in user_report['issues']])
        self.assertEqual(CalendarEvent.objects.count(), 0)

    def test_apply_imports_regular_entities_relations_and_is_idempotent(self):
        self._put('events_groups', [{'id': 'group-1', 'name': '学习', 'color': '#123456'}])
        self._put(
            'todos',
            [{
                'id': 'todo-1', 'title': '整理资料', 'description': '归档', 'groupID': 'group-1',
                'due_date': '2026-03-02', 'priority_score': 2, 'tags': ['论文'], 'linked_reminders': ['rem-1'],
            }],
        )
        self._put(
            'reminders',
            [{
                'id': 'rem-1', 'title': '提醒提交', 'content': '今晚前', 'trigger_time': '2026-03-01T08:00',
                'priority': 'high', 'linked_event_id': 'event-1', 'linked_todo_id': 'todo-1',
                'advance_triggers': [{'time_before': '15m', 'priority': 'high', 'message': '提前提醒'}],
            }],
        )
        self._put(
            'events',
            [{
                'id': 'event-1', 'title': '论文讨论', 'start': '2026-03-01T09:00', 'end': '2026-03-01T10:00',
                'groupID': 'group-1', 'tags': ['论文'], 'linked_reminders': ['rem-1'],
                'future_field': {'must_keep': True},
            }],
        )

        report = self._run('--apply')

        self.assertTrue(report['apply'])
        self.assertEqual(report['cohort_eligible_user_count'], 1)
        self.assertEqual(EventGroup.objects.count(), 1)
        self.assertEqual(Todo.objects.count(), 1)
        self.assertEqual(Reminder.objects.count(), 1)
        event = CalendarEvent.objects.get(event_id='event-1')
        self.assertEqual(event.metadata['legacy_unknown_fields']['future_field'], {'must_keep': True})
        self.assertEqual(EventTag.objects.count(), 1)
        self.assertEqual(TodoTag.objects.count(), 1)
        self.assertEqual(EventReminderLink.objects.count(), 1)
        self.assertEqual(TodoReminderLink.objects.count(), 1)
        self.assertEqual(PlannerLegacyIdMap.objects.count(), 4)
        self.assertEqual(PlannerMigrationIssue.objects.count(), 0)

        repeated = self._run('--apply')
        self.assertEqual(repeated['users'][0]['skipped'], 'source_checksum_unchanged')
        self.assertEqual(CalendarEvent.objects.count(), 1)

    def test_apply_reduces_a_simple_recurrence_to_master_series_and_id_maps(self):
        self._put('events_groups', [])
        self._put('todos', [])
        self._put('reminders', [])
        self._put(
            'events',
            [
                {
                    'id': 'event-master', 'title': '晨会', 'start': '2026-03-01T09:00', 'end': '2026-03-01T10:00',
                    'series_id': 'series-1', 'rrule': 'FREQ=DAILY;COUNT=2', 'is_recurring': True,
                    'is_main_event': True,
                },
                {
                    'id': 'event-instance', 'title': '晨会', 'start': '2026-03-02T09:00', 'end': '2026-03-02T10:00',
                    'series_id': 'series-1', 'rrule': 'FREQ=DAILY;COUNT=2', 'is_recurring': True,
                    'is_main_event': False, 'rrule_generated': True,
                },
            ],
        )
        self._put(
            'events_rrule_series',
            {'segments': [{'uid': 'series-1', 'sequence': 1, 'rrule_str': 'FREQ=DAILY;COUNT=2', 'dtstart': '2026-03-01T09:00', 'exdates': []}]},
        )

        report = self._run('--apply')

        self.assertEqual(report['cohort_eligible_user_count'], 1)
        self.assertEqual(CalendarEvent.objects.count(), 1)
        self.assertEqual(EventRecurrenceSeries.objects.count(), 1)
        mapped = PlannerLegacyIdMap.objects.get(user=self.user, entity_type='event', legacy_id='event-instance')
        self.assertEqual(mapped.series_id, 'series-1')
        self.assertEqual(mapped.recurrence_id, '20260302T090000')
        self.assertEqual(PlannerMigrationIssue.objects.count(), 0)

        output = StringIO()
        call_command(
            'verify_planner_migration',
            '--user-id',
            self.user.id,
            '--from',
            '2026-03-01',
            '--to',
            '2026-03-04',
            stdout=output,
        )
        verification = json.loads(output.getvalue())
        self.assertEqual(verification['difference_count'], 0)

        output = StringIO()
        call_command(
            'verify_recurrence_parity',
            '--sample',
            'all',
            '--user-id',
            self.user.id,
            '--from',
            '2026-03-01',
            '--to',
            '2026-03-04',
            stdout=output,
        )
        parity = json.loads(output.getvalue())
        self.assertEqual(parity['difference_count'], 0)

    def test_inline_exdate_and_count_until_are_normalized_only_when_observed_occurrences_match(self):
        self._put('events_groups', [])
        self._put('todos', [])
        self._put('reminders', [])
        self._put(
            'events',
            [
                {
                    'id': 'event-master', 'title': '晨会', 'start': '2026-03-01T09:00', 'end': '2026-03-01T10:00',
                    'series_id': 'series-legacy-rule',
                    'rrule': 'FREQ=DAILY;COUNT=3;UNTIL=20260302T090000;EXDATE=2026-03-02T09:00:00',
                    'is_recurring': True, 'is_main_event': True,
                },
                {
                    'id': 'event-instance', 'title': '晨会', 'start': '2026-03-03T09:00', 'end': '2026-03-03T10:00',
                    'series_id': 'series-legacy-rule', 'is_recurring': True, 'is_main_event': False,
                },
            ],
        )

        report = self._run('--apply')

        self.assertEqual(report['cohort_eligible_user_count'], 1)
        series = EventRecurrenceSeries.objects.get(series_id='series-legacy-rule')
        self.assertEqual(series.rrule_canonical, 'COUNT=3;FREQ=DAILY')
        self.assertEqual(
            list(EventRecurrenceExDate.objects.filter(series=series).values_list('recurrence_id', flat=True)),
            ['20260302T090000'],
        )

    def test_complete_event_without_legacy_id_uses_stable_synthetic_id(self):
        self._put('events_groups', [])
        self._put('todos', [])
        self._put('reminders', [])
        self._put('events', [{'title': '无旧 ID 日程', 'start': '2026-03-01T09:00', 'end': '2026-03-01T10:00'}])

        report = self._run('--apply')

        self.assertEqual(report['cohort_eligible_user_count'], 1)
        event = CalendarEvent.objects.get()
        self.assertTrue(event.event_id.startswith('legacy-events-'))
        self.assertTrue(event.metadata['legacy_unknown_fields']['_planner_synthetic_id'])
        self.assertEqual(PlannerLegacyIdMap.objects.get(entity_type='event').legacy_id, event.event_id)

    def test_dry_run_detects_missing_share_group_before_apply(self):
        self._put('events_groups', [])
        self._put('todos', [])
        self._put('reminders', [])
        self._put(
            'events',
            [{
                'id': 'shared-event', 'title': '共享日程', 'start': '2026-03-01T09:00', 'end': '2026-03-01T10:00',
                'shared_to_groups': ['share_group_missing'],
            }],
        )

        report = self._run('--dry-run')

        self.assertFalse(report['users'][0]['cohort_eligible'])
        self.assertIn('share_group_reference_missing', [item['code'] for item in report['users'][0]['issues']])

    def test_apply_records_quarantine_without_importing_business_rows(self):
        self._put('events_groups', [])
        self._put('todos', [])
        self._put('reminders', [])
        self._put('events', [{'id': 'broken-event', 'title': '损坏日程', 'start': 'bad-time', 'end': '2026-03-01T10:00'}])

        report = self._run('--apply', '--skip-quarantined', '--record-quarantined')

        self.assertTrue(report['users'][0]['quarantine_recorded'])
        self.assertEqual(CalendarEvent.objects.count(), 0)
        state = PlannerMigrationState.objects.get(user=self.user, source_key='events')
        self.assertEqual(state.status, PlannerMigrationState.STATUS_QUARANTINED)
        self.assertEqual(PlannerMigrationIssue.objects.filter(user=self.user, source_key='events').count(), 1)
