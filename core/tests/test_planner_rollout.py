"""P2-C cohort 准入必须默认回退 legacy。"""

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from core.models import PlannerCohortAssignment, PlannerMigrationIssue, PlannerMigrationState
from core.planner.rollout import PlannerRolloutPolicy


class PlannerRolloutPolicyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='planner-rollout-user', password='test-password')

    @override_settings(PLANNER_STORAGE_MODE='normalized')
    def test_normalized_mode_requires_assignment_verified_states_and_clean_issues(self):
        decision = PlannerRolloutPolicy.decide(self.user, 'web')
        self.assertEqual(decision.effective_mode, 'legacy')
        self.assertEqual(decision.reason, 'user_not_assigned')

        PlannerMigrationState.objects.create(
            user=self.user,
            source_key='events',
            status=PlannerMigrationState.STATUS_VERIFIED,
            source_checksum='checksum',
        )
        PlannerCohortAssignment.objects.create(
            user=self.user,
            storage_mode=PlannerCohortAssignment.MODE_NORMALIZED,
            entrypoints={'web': {'enabled_at': '2026-07-11T00:00:00+00:00', 'mode': 'normalized'}},
        )
        decision = PlannerRolloutPolicy.decide(self.user, 'web')
        self.assertEqual(decision.effective_mode, 'normalized')

        PlannerMigrationIssue.objects.create(user=self.user, source_key='events', code='unresolved')
        decision = PlannerRolloutPolicy.decide(self.user, 'web')
        self.assertEqual(decision.effective_mode, 'legacy')
        self.assertEqual(decision.reason, 'migration_not_verified_clean')
