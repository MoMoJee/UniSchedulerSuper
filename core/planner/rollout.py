"""Planner 正规化迁移期的 cohort 准入判定。"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth.models import User

from core.models import PlannerCohortAssignment, PlannerMigrationIssue, PlannerMigrationState


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
    ENTRYPOINT_AGENT = 'agent_planner'
    ENTRYPOINT_QUICK_ACTION = 'quick_action_planner'
    ENTRYPOINT_MCP = 'mcp_planner'
    ENTRYPOINT_INTERNAL_ATTACHMENT = 'internal_attachment'
    ENTRYPOINT_CALENDAR_FEED = 'calendar_feed'
    ENTRYPOINT_CALDAV_READ = 'caldav_read'
    ENTRYPOINT_CALDAV_WRITE = 'caldav_write'
    ALL_ENTRYPOINTS = (
        ENTRYPOINT_API_V2,
        ENTRYPOINT_WEB_CALENDAR,
        ENTRYPOINT_WEB_TODO,
        ENTRYPOINT_WEB_REMINDER,
        ENTRYPOINT_WEB_SEARCH,
        ENTRYPOINT_WEB_SHARE,
        ENTRYPOINT_COURSE_IMPORT,
        ENTRYPOINT_AGENT,
        ENTRYPOINT_QUICK_ACTION,
        ENTRYPOINT_MCP,
        ENTRYPOINT_INTERNAL_ATTACHMENT,
        ENTRYPOINT_CALENDAR_FEED,
        ENTRYPOINT_CALDAV_READ,
        ENTRYPOINT_CALDAV_WRITE,
    )
    BROWSER_ENTRYPOINTS = (
        ENTRYPOINT_API_V2,
        ENTRYPOINT_WEB_CALENDAR,
        ENTRYPOINT_WEB_TODO,
        ENTRYPOINT_WEB_REMINDER,
        ENTRYPOINT_WEB_SEARCH,
        ENTRYPOINT_WEB_SHARE,
        ENTRYPOINT_COURSE_IMPORT,
    )

    @classmethod
    def browser_entrypoint_payload(cls, user: User) -> dict[str, dict[str, object]]:
        """Return the single source of truth used by both HTML and bootstrap API."""
        decisions = {name: cls.decide(user, name) for name in cls.BROWSER_ENTRYPOINTS}
        return {
            name: {
                'mode': decision.effective_mode,
                'reason': decision.reason,
                'can_read_normalized': decision.effective_mode in {'shadow', 'normalized'},
                'can_write_normalized': decision.effective_mode == 'normalized',
            }
            for name, decision in decisions.items()
        }

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
            return PlannerStorageDecision(global_mode, 'blocked', 'user_not_assigned')
        if str((assignment.metadata or {}).get('p6_disposition', '')).startswith('retired-test-data'):
            return PlannerStorageDecision(global_mode, 'quarantined', 'retired_quarantine')
        if entrypoint not in assignment.entrypoints:
            return PlannerStorageDecision(global_mode, 'blocked', 'entrypoint_not_assigned')
        if assignment.storage_mode == 'legacy':
            return PlannerStorageDecision(global_mode, 'blocked', 'assignment_legacy')
        if not cls.is_verified_clean(user):
            return PlannerStorageDecision(global_mode, 'blocked', 'migration_not_verified_clean')
        if global_mode == 'shadow' or assignment.storage_mode == 'shadow':
            return PlannerStorageDecision(global_mode, 'shadow', 'verified_shadow_assignment')
        return PlannerStorageDecision(global_mode, 'normalized', 'verified_normalized_assignment')

    @staticmethod
    def is_verified_clean(user: User) -> bool:
        """Runtime admission uses sealed cohort state and never reads legacy JSON."""
        assignment = PlannerCohortAssignment.objects.filter(user=user, deleted_at__isnull=True).first()
        manifest = (assignment.metadata or {}).get('p6_cutover_manifest') if assignment else None
        if manifest:
            if manifest.get('schema') != 1 or not isinstance(manifest.get('sources'), list):
                return False
            return not PlannerMigrationIssue.objects.filter(user=user, is_resolved=False).exists()
        states = list(PlannerMigrationState.objects.filter(user=user))
        if not states or any(state.status != PlannerMigrationState.STATUS_VERIFIED for state in states):
            # Users with no legacy source are clean and may start directly on V2.
            return not states and not PlannerMigrationIssue.objects.filter(user=user, is_resolved=False).exists()
        if PlannerMigrationIssue.objects.filter(user=user, is_resolved=False).exists():
            return False
        return True
