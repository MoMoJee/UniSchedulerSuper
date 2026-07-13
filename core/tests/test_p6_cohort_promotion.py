import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings

from core.models import PlannerCohortAssignment, PlannerMigrationIssue, PlannerMigrationState, UserData
from core.planner.rollout import PlannerRolloutPolicy


@override_settings(PLANNER_STORAGE_MODE='normalized')
class P6CohortPromotionTests(TestCase):
    def _run(self, *flags):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        output = Path(directory.name) / 'cohort.json'
        call_command('promote_verified_planner_cohorts', '--all-entrypoints', *flags, output=str(output), stdout=StringIO())
        return json.loads(output.read_text(encoding='utf-8'))

    def test_dry_run_is_zero_write_and_apply_is_idempotent(self):
        user = User.objects.create_user('clean-empty')
        report = self._run('--dry-run')
        self.assertEqual(report['summary']['promote_count'], 1)
        self.assertFalse(PlannerCohortAssignment.objects.exists())
        self._run('--apply')
        assignment = PlannerCohortAssignment.objects.get(user=user)
        version = assignment.version
        self.assertEqual(set(assignment.entrypoints), set(PlannerRolloutPolicy.ALL_ENTRYPOINTS))
        self.assertEqual(PlannerRolloutPolicy.decide(user, PlannerRolloutPolicy.ENTRYPOINT_AGENT).effective_mode, 'normalized')
        self._run('--apply')
        assignment.refresh_from_db()
        self.assertEqual(assignment.version, version)

    def test_unexpected_issue_blocks_promotion(self):
        user = User.objects.create_user('unexpected-user')
        state = PlannerMigrationState.objects.create(user=user, source_key='events', status='quarantined')
        PlannerMigrationIssue.objects.create(user=user, state=state, source_key='events', code='bad')
        with self.assertRaisesMessage(Exception, '存在未决用户'):
            self._run('--apply')
        self.assertFalse(PlannerCohortAssignment.objects.exists())
