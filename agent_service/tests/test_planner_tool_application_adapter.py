import hashlib

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from reversion.models import Revision, Version

from agent_service.models import AgentSession, AgentTransaction, SearchResultCache
from agent_service.tools.planner_tools import create_event as legacy_create_event
from agent_service.tools.unified_planner_tools import (
    check_schedule_conflicts, create_item, delete_item, search_items, update_item,
)
from core.models import CalendarEvent, EventOccurrenceOverride, PlannerCohortAssignment, PlannerMigrationState, UserData
from core.planner.rollout import PlannerRolloutPolicy


@override_settings(PLANNER_STORAGE_MODE='normalized')
class PlannerToolApplicationAdapterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tool-app-user', password='test-password')
        self.legacy = UserData.objects.create(user=self.user, key='events', value='[]')
        PlannerMigrationState.objects.create(
            user=self.user, source_key='events', source_row_id=self.legacy.id,
            source_checksum=hashlib.sha256(b'[]').hexdigest(), status=PlannerMigrationState.STATUS_VERIFIED,
        )
        PlannerCohortAssignment.objects.create(
            user=self.user, storage_mode=PlannerCohortAssignment.MODE_NORMALIZED,
            entrypoints={PlannerRolloutPolicy.ENTRYPOINT_AGENT: {'mode': 'normalized'}},
        )
        self.session = AgentSession.objects.create(
            user=self.user, session_id=f'user_{self.user.id}_tools', name='tools'
        )
        self.config = {'configurable': {'user': self.user, 'thread_id': self.session.session_id}}

    def invoke(self, tool, **kwargs):
        return tool.invoke(kwargs, config=self.config)

    def test_normalized_unified_crud_never_writes_legacy_or_reversion(self):
        legacy_before = self.legacy.value
        revisions_before = Revision.objects.count()
        versions_before = Version.objects.count()
        created = self.invoke(
            create_item, item_type='event', title='Agent会议',
            start='2026-03-01T09:00:00+08:00', end='2026-03-01T10:00:00+08:00',
        )
        self.assertIn('创建成功', created)
        event = CalendarEvent.objects.get(title='Agent会议')

        searched = self.invoke(
            search_items, item_type='event', time_range='2026-03-01 ~ 2026-03-03', limit=20
        )
        self.assertIn('#1', searched)
        updated = self.invoke(update_item, identifier='#1', description='新版描述')
        self.assertIn('更新成功', updated)
        event.refresh_from_db()
        self.assertEqual(event.description, '新版描述')

        self.invoke(search_items, item_type='event', time_range='2026-03-01 ~ 2026-03-03', limit=20)
        deleted = self.invoke(delete_item, identifier='#1')
        self.assertIn('删除成功', deleted)
        event.refresh_from_db()
        self.assertIsNotNone(event.deleted_at)

        self.legacy.refresh_from_db()
        self.assertEqual(self.legacy.value, legacy_before)
        self.assertEqual(Revision.objects.count(), revisions_before)
        self.assertEqual(Version.objects.count(), versions_before)
        self.assertEqual(AgentTransaction.objects.count(), 0)

    def test_occurrence_cache_keeps_distinct_full_refs_and_single_edit(self):
        self.invoke(
            create_item, item_type='event', title='每日复习',
            start='2026-03-01T09:00:00+08:00', end='2026-03-01T10:00:00+08:00',
            repeat='FREQ=DAILY;COUNT=3',
        )
        output = self.invoke(
            search_items, item_type='event', time_range='2026-03-01 ~ 2026-03-05', limit=20
        )
        self.assertIn('#1', output)
        self.assertIn('#2', output)
        cache = SearchResultCache.objects.get(session=self.session)
        first, second = cache.index_mapping['#1'], cache.index_mapping['#2']
        self.assertEqual(first['entity_id'], second['entity_id'])
        self.assertNotEqual(first['recurrence_id'], second['recurrence_id'])
        self.assertTrue(first['occurrence_ref'])

        result = self.invoke(update_item, identifier='#2', description='只改第二次')
        self.assertIn('更新成功', result)
        override = EventOccurrenceOverride.objects.get(deleted_at__isnull=True)
        self.assertEqual(override.recurrence_id, second['recurrence_id'])
        self.assertEqual(override.patch['description'], '只改第二次')

    def test_legacy_named_tool_delegates_to_application_for_normalized_user(self):
        result = legacy_create_event.invoke(
            {
                'title': '旧工具名', 'start': '2026-03-02T09:00:00+08:00',
                'end': '2026-03-02T10:00:00+08:00',
            },
            config=self.config,
        )
        self.assertIn('创建成功', result)
        self.assertTrue(CalendarEvent.objects.filter(user=self.user, title='旧工具名').exists())
        self.legacy.refresh_from_db()
        self.assertEqual(self.legacy.value, '[]')

    def test_cache_is_bound_to_user_and_session(self):
        self.invoke(
            create_item, item_type='todo', title='私有待办', due_date='2026-03-02'
        )
        self.invoke(search_items, item_type='todo', time_range='2026-03-01 ~ 2026-03-05', limit=20)
        other = User.objects.create_user(username='other-tool-user')
        from agent_service.tools.cache_manager import CacheManager
        self.assertIsNone(CacheManager.get_normalized_ref(self.session.session_id, other, '#1', 'todo'))

    def test_conflict_tool_reuses_application_occurrence_query(self):
        for title in ('冲突A', '冲突B'):
            self.invoke(
                create_item, item_type='event', title=title,
                start='2026-03-01T09:00:00+08:00', end='2026-03-01T10:00:00+08:00',
            )
        result = self.invoke(check_schedule_conflicts, time_range='2026-03-01 ~ 2026-03-02')
        self.assertIn('发现 1 组冲突', result)

