"""P6 cutover constants and user classification shared by release tooling."""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth.models import User

from core.models import PlannerMigrationIssue, PlannerMigrationState, UserData
from core.planner.legacy import LegacyPlannerRepository


RETIRED_QUARANTINE_USERS = frozenset({'User1', 'test_user', 'User15', 'User21', 'User22'})
RETIRED_DISPOSITION = 'retired-test-data-user-approved-2026-07-13'


@dataclass(frozen=True)
class P6UserClassification:
    name: str
    reason: str
    source_key_count: int
    state_count: int
    unresolved_issue_count: int


def classify_p6_user(user: User) -> P6UserClassification:
    """Classify without changing migration state or reading legacy JSON bodies."""

    source_key_count = UserData.objects.filter(
        user=user,
        key__in=LegacyPlannerRepository.PLANNER_KEYS,
    ).count()
    states = list(PlannerMigrationState.objects.filter(user=user).only('status'))
    unresolved = PlannerMigrationIssue.objects.filter(user=user, is_resolved=False).count()
    if user.username in RETIRED_QUARANTINE_USERS:
        valid = unresolved > 0 and states and all(
            state.status == PlannerMigrationState.STATUS_QUARANTINED for state in states
        )
        return P6UserClassification(
            'retired_quarantine' if valid else 'blocking',
            'approved_retired_test_data' if valid else 'approved_quarantine_not_fully_recorded',
            source_key_count,
            len(states),
            unresolved,
        )
    if unresolved:
        return P6UserClassification('blocking', 'unexpected_unresolved_issue', source_key_count, len(states), unresolved)
    if source_key_count == 0 and not states:
        return P6UserClassification('verified_clean', 'empty_new_user', 0, 0, 0)
    if not states or any(state.status != PlannerMigrationState.STATUS_VERIFIED for state in states):
        return P6UserClassification('blocking', 'migration_state_not_verified', source_key_count, len(states), unresolved)
    if len(states) != source_key_count:
        return P6UserClassification('blocking', 'source_state_count_mismatch', source_key_count, len(states), unresolved)
    return P6UserClassification('verified_clean', 'verified_source_manifest', source_key_count, len(states), 0)
