"""Planner 正规化迁移期的 cohort 准入判定。"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth.models import User

from core.models import PlannerCohortAssignment, PlannerMigrationIssue, PlannerMigrationState
from core.planner.legacy import LegacyPlannerDataError, LegacyPlannerRepository


@dataclass(frozen=True)
class PlannerStorageDecision:
    """一次入口判定的无副作用结果。"""

    requested_mode: str
    effective_mode: str
    reason: str


class PlannerRolloutPolicy:
    """禁止未校验用户或半切换入口使用 normalized 存储。"""

    MODES = frozenset({'legacy', 'shadow', 'normalized'})
    ENTRYPOINT_API_V2 = 'api_v2'
    ENTRYPOINT_WEB_CALENDAR = 'web_calendar'
    ENTRYPOINT_WEB_TODO = 'web_todo'
    ENTRYPOINT_WEB_REMINDER = 'web_reminder'
    ENTRYPOINT_WEB_SEARCH = 'web_search'
    ENTRYPOINT_WEB_SHARE = 'web_share'
    ENTRYPOINT_COURSE_IMPORT = 'course_import'

    @classmethod
    def can_read_normalized(cls, user: User, entrypoint: str) -> PlannerStorageDecision:
        """只读 normalized 投影允许 shadow/normalized，仍完整执行 cohort 判定。"""
        return cls.decide(user, entrypoint)

    @classmethod
    def can_write_normalized(cls, user: User, entrypoint: str) -> PlannerStorageDecision:
        """调用方必须仅在 effective_mode=normalized 时执行 command。"""
        return cls.decide(user, entrypoint)

    @classmethod
    def decide(cls, user: User, entrypoint: str) -> PlannerStorageDecision:
        global_mode = str(getattr(settings, 'PLANNER_STORAGE_MODE', 'legacy')).lower()
        if global_mode not in cls.MODES:
            return PlannerStorageDecision(global_mode, 'legacy', 'invalid_global_mode')
        if global_mode == 'legacy':
            return PlannerStorageDecision(global_mode, 'legacy', 'global_legacy')

        assignment = PlannerCohortAssignment.objects.filter(user=user, deleted_at__isnull=True).first()
        if assignment is None:
            return PlannerStorageDecision(global_mode, 'legacy', 'user_not_assigned')
        if entrypoint not in assignment.entrypoints:
            return PlannerStorageDecision(global_mode, 'legacy', 'entrypoint_not_assigned')
        if assignment.storage_mode == 'legacy':
            return PlannerStorageDecision(global_mode, 'legacy', 'assignment_legacy')
        if not cls.is_verified_clean(user):
            return PlannerStorageDecision(global_mode, 'legacy', 'migration_not_verified_clean')
        if global_mode == 'shadow' or assignment.storage_mode == 'shadow':
            return PlannerStorageDecision(global_mode, 'shadow', 'verified_shadow_assignment')
        return PlannerStorageDecision(global_mode, 'normalized', 'verified_normalized_assignment')

    @staticmethod
    def is_verified_clean(user: User) -> bool:
        states = list(PlannerMigrationState.objects.filter(user=user))
        if not states or any(state.status != PlannerMigrationState.STATUS_VERIFIED for state in states):
            return False
        if PlannerMigrationIssue.objects.filter(user=user, is_resolved=False).exists():
            return False
        states_by_key = {state.source_key: state for state in states}
        try:
            for key in LegacyPlannerRepository.PLANNER_KEYS:
                payload = LegacyPlannerRepository.read(user, key)
                state = states_by_key.get(key)
                if payload is None:
                    if state is not None:
                        return False
                    continue
                if (
                    state is None
                    or state.source_row_id != payload.source_row_id
                    or state.source_checksum != payload.checksum
                ):
                    return False
        except LegacyPlannerDataError:
            return False
        return True
