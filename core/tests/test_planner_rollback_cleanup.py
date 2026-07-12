import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import reversion
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone
from reversion.models import Revision, Version

from agent_service.models import AgentTransaction as AgentServiceTransaction
from core.models import AgentTransaction as CoreAgentTransaction
from core.models import CalendarEvent, PlannerChangeSet, UserData
from core.planner.rollback_cleanup import business_checksum


class PlannerRollbackCleanupCommandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='cleanup-user')
        self.userdata = UserData.objects.create(user=self.user, key='events', value='[]')
        start = timezone.make_aware(datetime(2026, 3, 1, 9))
        self.event = CalendarEvent.objects.create(
            user=self.user, title='保留业务日程', start_at=start,
            end_at=start + timedelta(hours=1), is_all_day=False,
        )
        with reversion.create_revision():
            self.userdata.value = '[{"id":"legacy"}]'
            self.userdata.save(update_fields=['value'])
            self.event.description = '旧快照中的描述'
            self.event.save(update_fields=['description'])
            reversion.set_comment('Before: cleanup test')
        self.revision = Revision.objects.latest('pk')
        CoreAgentTransaction.objects.create(
            session_id='legacy-core', revision=self.revision,
            action_type='update_event', description='legacy',
        )
        AgentServiceTransaction.objects.create(
            session_id='legacy-service', user=self.user, revision_id=self.revision.pk,
            action_type='update_event', source='legacy_agent',
        )
        self.cutover = (timezone.now() + timedelta(minutes=1)).isoformat()
        self.change_set = PlannerChangeSet.objects.create(
            user=self.user, command_type='event.patch_all',
            before_payload={'event': {'event_id': self.event.event_id}},
            after_payload={'event': {'event_id': self.event.event_id, 'version': 2}},
            rollback_status='available',
        )

    def report_path(self, name):
        return str(Path(tempfile.gettempdir()) / name)

    def test_dry_run_is_read_only_and_reports_exact_selection(self):
        checksum_before, _ = business_checksum()
        version_count = Version.objects.count()
        output = self.report_path('planner-cleanup-dry-run.json')
        call_command(
            'cleanup_legacy_planner_rollback', '--dry-run',
            '--cutover', self.cutover, '--output', output,
        )
        report = json.loads(Path(output).read_text(encoding='utf-8'))
        self.assertEqual(report['mode'], 'dry-run')
        self.assertEqual(report['selection']['agent_service_legacy_transactions'], 1)
        self.assertEqual(report['selection']['core_transactions'], 1)
        self.assertGreaterEqual(report['selection']['versions'], 2)
        self.assertEqual(Version.objects.count(), version_count)
        self.assertEqual(business_checksum()[0], checksum_before)

    def test_apply_is_idempotent_and_preserves_current_business_rows(self):
        checksum_before, counts_before = business_checksum()
        first = self.report_path('planner-cleanup-apply-1.json')
        second = self.report_path('planner-cleanup-apply-2.json')
        call_command(
            'cleanup_legacy_planner_rollback', '--apply',
            '--cutover', self.cutover, '--output', first,
        )
        self.assertTrue(UserData.objects.filter(pk=self.userdata.pk).exists())
        self.assertTrue(CalendarEvent.objects.filter(pk=self.event.pk).exists())
        self.assertEqual(CoreAgentTransaction.objects.count(), 0)
        self.assertEqual(AgentServiceTransaction.objects.count(), 0)
        self.assertEqual(
            Version.objects.filter(content_type=ContentType.objects.get_for_model(UserData)).count(), 0
        )
        self.assertEqual(business_checksum(), (checksum_before, counts_before))
        self.change_set.refresh_from_db()
        self.assertEqual(self.change_set.before_payload, {})
        self.assertEqual(self.change_set.after_payload, {})
        self.assertEqual(self.change_set.affected_refs, [{'type': 'event', 'id': self.event.event_id}])
        self.assertEqual(self.change_set.rollback_status, 'not_reversible')
        call_command(
            'cleanup_legacy_planner_rollback', '--apply',
            '--cutover', self.cutover, '--output', second,
        )
        repeated = json.loads(Path(second).read_text(encoding='utf-8'))
        self.assertEqual(repeated['selection']['versions'], 0)
        self.assertEqual(sum(repeated['deleted'].values()), 0)

    def test_verify_strict_passes_after_apply(self):
        call_command('cleanup_legacy_planner_rollback', '--apply', '--cutover', self.cutover)
        call_command('verify_planner_rollback_storage', '--strict')

    def test_verify_strict_allows_post_cutover_non_planner_userdata_history(self):
        call_command('cleanup_legacy_planner_rollback', '--apply', '--cutover', self.cutover)
        settings_row = UserData.objects.create(
            user=self.user, key='user_interface_settings', value='{}'
        )
        with reversion.create_revision():
            settings_row.value = '{"theme":"dark"}'
            settings_row.save(update_fields=['value'])

        call_command('verify_planner_rollback_storage', '--strict')

    def test_verify_strict_rejects_post_cutover_planner_userdata_history(self):
        call_command('cleanup_legacy_planner_rollback', '--apply', '--cutover', self.cutover)
        with reversion.create_revision():
            self.userdata.value = '[{"id":"new-legacy-write"}]'
            self.userdata.save(update_fields=['value'])

        with self.assertRaisesMessage(CommandError, 'P4 rollback storage strict 验证失败'):
            call_command('verify_planner_rollback_storage', '--strict')
