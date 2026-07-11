"""normalized Planner repository 的 ORM 查询与无副作用测试。"""

from datetime import datetime, timedelta
from io import StringIO
import json

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.models import (
    CalendarEvent,
    EventOccurrenceOverride,
    EventRecurrenceExDate,
    EventRecurrenceSeries,
)
from core.planner.repository import PlannerRepository, PlannerVersionConflictError


class PlannerRepositoryTests(TestCase):
    """验证 repository 只读查询、窗口展开与版本门禁。"""

    def setUp(self):
        self.user = User.objects.create_user(username='planner-repository-user', password='test-password')
        self.start = timezone.make_aware(datetime(2026, 3, 1, 9, 0))
        self.end = self.start + timedelta(hours=1)

    def test_normalized_query_expands_sparse_recurrence_without_creating_rows(self):
        single = CalendarEvent.objects.create(
            user=self.user,
            event_id='single-event',
            title='单次会议',
            start_at=self.start,
            end_at=self.end,
        )
        master = CalendarEvent.objects.create(
            user=self.user,
            event_id='series-master',
            title='每日站会',
            start_at=self.start,
            end_at=self.end,
        )
        series = EventRecurrenceSeries.objects.create(
            user=self.user,
            series_id='series-1',
            master_event=master,
            ical_uid='series-1@example.test',
            rrule='FREQ=DAILY;COUNT=3',
            rrule_canonical='COUNT=3;FREQ=DAILY',
            dtstart_at=self.start,
            tzid='Asia/Shanghai',
        )
        EventRecurrenceExDate.objects.create(series=series, recurrence_id='20260302T090000')
        EventOccurrenceOverride.objects.create(
            series=series,
            recurrence_id='20260303T090000',
            kind='modified',
            patch={'title': '改期站会'},
            effective_start_at=self.start + timedelta(days=2, hours=2),
            effective_end_at=self.end + timedelta(days=2, hours=2),
        )
        counts_before = {
            'events': CalendarEvent.objects.count(),
            'series': EventRecurrenceSeries.objects.count(),
            'overrides': EventOccurrenceOverride.objects.count(),
        }

        occurrences = PlannerRepository.list_event_occurrences(
            self.user,
            range_start=self.start,
            range_end=self.start + timedelta(days=4),
        )

        self.assertEqual(
            [(item.ref.entity_id, item.ref.recurrence_id, item.payload['title']) for item in occurrences],
            [
                ('single-event', '', '单次会议'),
                ('series-master', '20260301T090000', '每日站会'),
                ('series-master', '20260303T090000', '改期站会'),
            ],
        )
        self.assertEqual(counts_before['events'], CalendarEvent.objects.count())
        self.assertEqual(counts_before['series'], EventRecurrenceSeries.objects.count())
        self.assertEqual(counts_before['overrides'], EventOccurrenceOverride.objects.count())
        self.assertEqual(single.event_id, occurrences[0].ref.entity_id)

    def test_version_gate_and_soft_delete_use_the_model_version(self):
        event = CalendarEvent.objects.create(
            user=self.user,
            event_id='versioned-event',
            title='版本测试',
            start_at=self.start,
            end_at=self.end,
        )

        PlannerRepository.require_event_version(event, 1)
        with self.assertRaises(PlannerVersionConflictError):
            PlannerRepository.require_event_version(event, 2)
        event.soft_delete(expected_version=1)
        event.refresh_from_db()

        self.assertIsNotNone(event.deleted_at)
        self.assertEqual(event.version, 2)

    def test_direct_userdata_report_marks_legacy_adapter_and_existing_call_sites(self):
        output = StringIO()

        call_command('report_planner_direct_userdata_access', stdout=output)
        report = json.loads(output.getvalue())
        findings = {(item['file'], item['whitelisted']) for item in report['findings']}

        self.assertIn(('core/planner/legacy.py', True), findings)
        self.assertIn(('core/services/event_service.py', False), findings)
        self.assertGreater(report['summary']['non_whitelisted_count'], 0)
