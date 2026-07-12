"""legacy repository 必须无损读取且拒绝歧义源。"""

import json
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from core.models import PlannerCohortAssignment, UserData
from core.planner.legacy import LegacyPlannerDataError, LegacyPlannerRepository, LegacyPlannerWriteDisabled


class LegacyPlannerRepositoryTests(TestCase):
    """验证 repository 不触发 DATA_SCHEMA 重建或隐式初始化。"""

    def setUp(self):
        self.user = User.objects.create_user(username='legacy-repository-user', password='test-password')

    def test_read_preserves_unknown_fields_and_does_not_create_rows(self):
        UserData.objects.create(
            user=self.user,
            key='events',
            value=json.dumps([{'id': 'legacy-1', 'caldav_uid': 'external-uid', 'future_field': {'keep': True}}]),
        )

        payload = LegacyPlannerRepository.read_events(self.user)

        self.assertEqual(UserData.objects.filter(user=self.user, key='events').count(), 1)
        self.assertEqual(payload.value[0]['caldav_uid'], 'external-uid')
        self.assertEqual(payload.value[0]['future_field'], {'keep': True})

    def test_duplicate_source_key_is_an_explicit_error(self):
        UserData.objects.create(user=self.user, key='events', value='[]')
        UserData.objects.create(user=self.user, key='events', value='[]')

        with self.assertRaises(LegacyPlannerDataError):
            LegacyPlannerRepository.read_events(self.user)

    def test_audit_command_reports_duplicate_keys_without_rewriting_source_rows(self):
        UserData.objects.create(user=self.user, key='events', value='[]')
        UserData.objects.create(user=self.user, key='events', value='[]')
        output = StringIO()

        call_command('audit_planner_legacy', '--user-id', self.user.id, stdout=output)
        report = json.loads(output.getvalue())

        self.assertEqual(report['summary']['duplicate_key_count'], 1)
        self.assertEqual(UserData.objects.filter(user=self.user, key='events').count(), 2)

    def test_duplicate_resolver_only_deletes_identical_payloads_after_apply(self):
        first = UserData.objects.create(user=self.user, key='reminders', value='[]')
        second = UserData.objects.create(user=self.user, key='reminders', value='[]')
        dry_run_output = StringIO()

        call_command(
            'resolve_planner_legacy_duplicates',
            '--user-id',
            self.user.id,
            '--key',
            'reminders',
            stdout=dry_run_output,
        )
        self.assertEqual(UserData.objects.filter(id__in=[first.id, second.id]).count(), 2)

        call_command(
            'resolve_planner_legacy_duplicates',
            '--user-id',
            self.user.id,
            '--key',
            'reminders',
            '--apply',
            stdout=StringIO(),
        )
        self.assertEqual(UserData.objects.filter(user=self.user, key='reminders').count(), 1)

    def test_revision_snapshot_rows_are_limited_to_planner_and_export_keys(self):
        event = UserData.objects.create(user=self.user, key='events', value='[]')
        export = UserData.objects.create(user=self.user, key='outport_calendar_data', value='{}')
        UserData.objects.create(user=self.user, key='agent_config', value='{}')

        rows = LegacyPlannerRepository.get_rows_for_revision(
            self.user,
            ['events', 'outport_calendar_data'],
        )

        self.assertEqual([row.id for row in rows], [event.id, export.id])
        with self.assertRaises(LegacyPlannerDataError):
            LegacyPlannerRepository.get_rows_for_revision(self.user, ['agent_config'])

    def test_normalized_cohort_hard_blocks_legacy_planner_writes(self):
        row = UserData.objects.create(user=self.user, key='events', value='[]')
        PlannerCohortAssignment.objects.create(
            user=self.user,
            storage_mode=PlannerCohortAssignment.MODE_NORMALIZED,
            entrypoints={'web_calendar': {'mode': 'normalized'}},
        )

        with self.assertRaises(LegacyPlannerWriteDisabled):
            LegacyPlannerRepository.get_list_for_update(self.user, 'events')
        with self.assertRaises(LegacyPlannerWriteDisabled):
            LegacyPlannerRepository.replace_list(row, [{'id': 'must-not-write'}])

        row.refresh_from_db()
        self.assertEqual(row.value, '[]')
