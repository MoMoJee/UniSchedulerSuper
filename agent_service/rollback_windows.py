"""Agent rollback window 的服务端生命周期。"""

from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from agent_service.models import AgentRollbackWindow, AgentSession
from core.models import PlannerChangeSet, PlannerRollbackSnapshot


class AgentRollbackWindowService:
    @staticmethod
    def _expire_window(window):
        change_set_ids = PlannerRollbackSnapshot.objects.filter(
            rollback_window=window
        ).values_list('change_set_id', flat=True)
        PlannerChangeSet.objects.filter(pk__in=change_set_ids, rollback_status='available').update(
            rollback_status='expired'
        )
        PlannerRollbackSnapshot.objects.filter(rollback_window=window).delete()

    @classmethod
    @transaction.atomic
    def ensure_active(cls, *, user, session_id: str, floor_message_index: int):
        """刷新/重连复用当前窗口；缺失时由后端以当前消息末尾建立窗口。"""
        active = AgentRollbackWindow.objects.select_for_update().filter(
            user=user,
            session__session_id=session_id,
            status=AgentRollbackWindow.STATUS_ACTIVE,
        ).first()
        if active is not None:
            return active
        return cls.rotate(
            user=user,
            session_id=session_id,
            floor_message_index=floor_message_index,
        )

    @classmethod
    @transaction.atomic
    def rotate(cls, *, user, session_id: str, floor_message_index: int, activation_token: str | None = None):
        if floor_message_index < 0:
            raise ValueError('floor_message_index 不能为负数')
        token = activation_token or str(uuid4())
        existing = AgentRollbackWindow.objects.filter(user=user, activation_token=token).first()
        if existing is not None:
            return existing
        session, _ = AgentSession.objects.get_or_create(
            user=user, session_id=session_id,
            defaults={'name': '新对话'},
        )
        session = AgentSession.objects.select_for_update().get(pk=session.pk)
        generation = (
            AgentRollbackWindow.objects.filter(user=user, session=session)
            .order_by('-generation').values_list('generation', flat=True).first() or 0
        ) + 1
        active_windows = AgentRollbackWindow.objects.select_for_update().filter(
            user=user, status=AgentRollbackWindow.STATUS_ACTIVE
        )
        for active in active_windows:
            active.status = AgentRollbackWindow.STATUS_CLOSED
            active.closed_at = timezone.now()
            active.save(update_fields={'status', 'closed_at'})
            cls._expire_window(active)
        return AgentRollbackWindow.objects.create(
            user=user, session=session, generation=generation,
            floor_message_index=floor_message_index, activation_token=token,
        )

    @classmethod
    @transaction.atomic
    def close(cls, *, user, session_id: str):
        windows = AgentRollbackWindow.objects.select_for_update().filter(
            user=user, session__session_id=session_id, status=AgentRollbackWindow.STATUS_ACTIVE
        )
        for window in windows:
            cls._expire_window(window)
            window.status = AgentRollbackWindow.STATUS_CLOSED
            window.closed_at = timezone.now()
            window.save(update_fields={'status', 'closed_at'})
