"""正规化 Planner 模型的隔离数据库测试。"""

from datetime import datetime

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from core.models import CalendarEvent, EventGroup, PlannerLegacyIdMap, Todo, TodoDependency


class PlannerModelTests(TestCase):
    """验证公开 ID、关系和数据库约束。"""

    def setUp(self):
        self.user = User.objects.create_user(username='planner-model-user', password='test-password')
        self.group = EventGroup.objects.create(user=self.user, group_id='group-1', name='学习')

    def test_public_ids_are_unique_per_user_and_legacy_ids_are_mapped_explicitly(self):
        event = CalendarEvent.objects.create(
            user=self.user,
            event_id='event-1',
            group=self.group,
            title='设计评审',
            start_at=timezone.make_aware(datetime(2026, 3, 1, 9, 0)),
            end_at=timezone.make_aware(datetime(2026, 3, 1, 10, 0)),
        )
        mapping = PlannerLegacyIdMap.objects.create(
            user=self.user,
            entity_type='event',
            legacy_id='legacy-event-1',
            entity_id=event.event_id,
        )

        self.assertEqual(mapping.entity_id, 'event-1')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CalendarEvent.objects.create(
                    user=self.user,
                    event_id='event-1',
                    title='重复公开 ID',
                    start_at=timezone.make_aware(datetime(2026, 3, 2, 9, 0)),
                    end_at=timezone.make_aware(datetime(2026, 3, 2, 10, 0)),
                )

    def test_todo_dependency_forbids_self_reference(self):
        todo = Todo.objects.create(user=self.user, todo_id='todo-1', title='整理资料')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TodoDependency.objects.create(todo=todo, depends_on=todo)
