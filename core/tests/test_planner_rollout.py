"""Cohort admission and P6 sealed-manifest runtime behavior."""

import hashlib

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from core.models import PlannerCohortAssignment, PlannerMigrationIssue, PlannerMigrationState, UserData
from core.planner.rollout import PlannerRolloutPolicy


class PlannerRolloutPolicyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='planner-rollout-user', password='test-password')

    @override_settings(PLANNER_STORAGE_MODE='normalized')
    def test_normalized_mode_requires_assignment_verified_states_and_clean_issues(self):
        decision = PlannerRolloutPolicy.decide(self.user, 'web')
        self.assertEqual(decision.effective_mode, 'blocked')
        self.assertEqual(decision.reason, 'user_not_assigned')

        source = UserData.objects.create(user=self.user, key='events', value='[]')
        PlannerMigrationState.objects.create(
            user=self.user,
            source_key='events',
            status=PlannerMigrationState.STATUS_VERIFIED,
            source_row_id=source.id,
            source_checksum=hashlib.sha256(b'[]').hexdigest(),
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
        self.assertEqual(decision.effective_mode, 'blocked')
        self.assertEqual(decision.reason, 'migration_not_verified_clean')

    @override_settings(PLANNER_STORAGE_MODE='normalized')
    def test_runtime_admission_does_not_rescan_legacy_checksum(self):
        source = UserData.objects.create(user=self.user, key='events', value='[]')
        PlannerMigrationState.objects.create(
            user=self.user,
            source_key='events',
            status=PlannerMigrationState.STATUS_VERIFIED,
            source_row_id=source.id,
            source_checksum=hashlib.sha256(b'[]').hexdigest(),
        )
        PlannerCohortAssignment.objects.create(
            user=self.user,
            storage_mode=PlannerCohortAssignment.MODE_NORMALIZED,
            entrypoints={'web_calendar': {'mode': 'normalized'}},
        )
        self.assertEqual(PlannerRolloutPolicy.decide(self.user, 'web_calendar').effective_mode, 'normalized')

        source.value = '[{"id":"new-legacy-write"}]'
        source.save(update_fields=['value'])

        decision = PlannerRolloutPolicy.decide(self.user, 'web_calendar')
        self.assertEqual(decision.effective_mode, 'normalized')
        self.assertEqual(decision.reason, 'verified_normalized_assignment')
