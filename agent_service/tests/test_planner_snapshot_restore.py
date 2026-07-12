import hashlib
from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from agent_service.models import AgentRollbackWindow, AgentSession, AgentTransaction
from agent_service.rollback_windows import AgentRollbackWindowService
from core.models import (
    CalendarEvent, EventGroup, EventOccurrenceOverride, EventRecurrenceSeries,
    PlannerChangeSet, PlannerCohortAssignment, PlannerMigrationState,
    PlannerRollbackSnapshot, ReminderOccurrenceState, Todo, UserData,
)
from core.planner.application import PlannerApplicationService
from core.planner.context import PlannerExecutionContext
from core.planner.rollout import PlannerRolloutPolicy
from core.planner.snapshots import PlannerRollbackConflict, PlannerRollbackCoordinator


@override_settings(PLANNER_STORAGE_MODE='normalized')
class PlannerSnapshotRestoreTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='snapshot-user', password='test-password')
        source = UserData.objects.create(user=self.user, key='events', value='[]')
        PlannerMigrationState.objects.create(
            user=self.user, source_key='events', source_row_id=source.id,
            source_checksum=hashlib.sha256(b'[]').hexdigest(),
            status=PlannerMigrationState.STATUS_VERIFIED,
        )
        PlannerCohortAssignment.objects.create(
            user=self.user, storage_mode=PlannerCohortAssignment.MODE_NORMALIZED,
            entrypoints={
                PlannerRolloutPolicy.ENTRYPOINT_API_V2: {'mode': 'normalized'},
                PlannerRolloutPolicy.ENTRYPOINT_AGENT: {'mode': 'normalized'},
            },
        )
        self.session = AgentSession.objects.create(
            user=self.user, session_id=f'user_{self.user.id}_snapshot', name='snapshot'
        )
        self.window = AgentRollbackWindowService.rotate(
            user=self.user, session_id=self.session.session_id,
            floor_message_index=4, activation_token='activation-1',
        )
        self.start = timezone.make_aware(datetime(2026, 3, 1, 9))
        self.end = self.start + timedelta(hours=1)

    def context(self, tool_call_id: str, *, message_index: int = 4, reversible: bool = True):
        return PlannerExecutionContext(
            user=self.user, source='websocket_agent',
            entrypoint=PlannerRolloutPolicy.ENTRYPOINT_AGENT,
            session_id=self.session.session_id, tool_call_id=tool_call_id,
            message_index=message_index, rollback_window_id=str(self.window.window_id),
            reversible=reversible,
        )

    def create_event(self, tool_call_id='create-1', *, recurrence=None, reversible=True):
        payload = {'title': '原始日程', 'start': self.start.isoformat(), 'end': self.end.isoformat()}
        if recurrence is not None:
            payload['recurrence'] = {'rrule': recurrence}
        return PlannerApplicationService.create_event(
            self.context(tool_call_id, reversible=reversible), payload,
            range_start=self.start, range_end=self.end,
        )

    def test_non_reversible_context_does_not_create_snapshot(self):
        self.create_event(reversible=False)
        self.assertEqual(PlannerRollbackSnapshot.objects.count(), 0)
        self.assertEqual(AgentTransaction.objects.count(), 0)

    def test_create_snapshot_is_compressed_and_rollback_restores_absence(self):
        result = self.create_event()
        event = CalendarEvent.objects.get(event_id=result['event']['event_id'])
        created_version = event.version
        snapshot = PlannerRollbackSnapshot.objects.get()
        self.assertLess(len(bytes(snapshot.payload)), snapshot.uncompressed_size)
        self.assertEqual(snapshot.change_set.rollback_status, 'available')

        PlannerRollbackCoordinator.rollback_tool_call(self.context('rollback-request'), 'create-1')

        event.refresh_from_db()
        self.assertIsNotNone(event.deleted_at)
        self.assertGreater(event.version, created_version)
        self.assertFalse(PlannerRollbackSnapshot.objects.exists())
        transaction = AgentTransaction.objects.get(tool_call_id='create-1')
        self.assertTrue(transaction.is_rolled_back)
        self.assertEqual(transaction.state, 'rolled_back')

    def test_all_patch_and_single_override_restore_business_projection(self):
        result = self.create_event('seed', recurrence='FREQ=DAILY;COUNT=5', reversible=False)
        event_id = result['event']['event_id']
        event = CalendarEvent.objects.get(event_id=event_id)
        series = EventRecurrenceSeries.objects.get(master_event=event)
        ref = {
            'entity_type': 'event', 'entity_id': event_id, 'series_id': series.series_id,
            'recurrence_id': '20260302T090000', 'source_version': max(event.version, series.version),
        }
        PlannerApplicationService.patch_event(
            self.context('single-edit'), event_id, {'description': '仅这一次'},
            scope='single', occurrence_ref=ref, expected_version=ref['source_version'],
        )
        self.assertEqual(EventOccurrenceOverride.objects.filter(series=series, deleted_at__isnull=True).count(), 1)

        PlannerRollbackCoordinator.rollback_tool_call(self.context('rollback-request'), 'single-edit')

        self.assertEqual(EventOccurrenceOverride.objects.filter(series=series, deleted_at__isnull=True).count(), 0)
        event.refresh_from_db()
        self.assertEqual(event.description, '')

        previous_version = max(event.version, EventRecurrenceSeries.objects.get(master_event=event).version)
        PlannerApplicationService.patch_event(
            self.context('all-edit'), event_id,
            {'title': '整个系列', 'start': self.start.replace(hour=10).isoformat(), 'end': self.end.replace(hour=11).isoformat()},
            scope='all', occurrence_ref=None, expected_version=previous_version,
        )
        event.refresh_from_db()
        self.assertEqual(event.title, '整个系列')
        PlannerRollbackCoordinator.rollback_tool_call(self.context('rollback-request'), 'all-edit')
        event.refresh_from_db()
        self.assertEqual(event.title, '原始日程')
        self.assertEqual(event.start_at, self.start)

    def test_future_split_rollback_restores_parent_and_removes_child(self):
        result = self.create_event('seed', recurrence='FREQ=DAILY;COUNT=5', reversible=False)
        event = CalendarEvent.objects.get(event_id=result['event']['event_id'])
        series = EventRecurrenceSeries.objects.get(master_event=event)
        original_rule = series.rrule_canonical
        ref = {
            'entity_type': 'event', 'entity_id': event.event_id, 'series_id': series.series_id,
            'recurrence_id': '20260303T090000', 'source_version': max(event.version, series.version),
        }
        changed = PlannerApplicationService.patch_event(
            self.context('future-split'), event.event_id, {'description': '未来'},
            scope='this_and_future', occurrence_ref=ref,
            expected_version=ref['source_version'],
        )
        child_id = changed['event_id']
        self.assertNotEqual(child_id, event.event_id)

        PlannerRollbackCoordinator.rollback_tool_call(self.context('rollback-request'), 'future-split')

        series.refresh_from_db()
        self.assertEqual(series.rrule_canonical, original_rule)
        self.assertIsNone(series.deleted_at)
        child = CalendarEvent.objects.get(event_id=child_id)
        self.assertIsNotNone(child.deleted_at)

    def test_todo_convert_and_reminder_occurrence_state_are_restorable(self):
        todo_result = PlannerApplicationService.create_todo(
            self.context('todo-seed', reversible=False), {'title': '待转换'}
        )
        todo_id = todo_result['todo']['todo_id']
        converted = PlannerApplicationService.convert_todo(
            self.context('todo-convert'), todo_id,
            {'start': self.start.isoformat(), 'end': self.end.isoformat()}, expected_version=1,
        )
        PlannerRollbackCoordinator.rollback_tool_call(self.context('rollback-request'), 'todo-convert')
        todo = Todo.objects.get(todo_id=todo_id)
        self.assertEqual(todo.status, 'pending')
        self.assertIsNone(todo.converted_to_event_id)
        self.assertIsNotNone(CalendarEvent.objects.get(event_id=converted['event_id']).deleted_at)

        reminder = PlannerApplicationService.create_reminder(
            self.context('reminder-seed', reversible=False),
            {'title': '重复提醒', 'trigger': self.start.isoformat(), 'recurrence': {'rrule': 'FREQ=DAILY;COUNT=3'}},
        )['reminder']
        ref = {
            'entity_type': 'reminder', 'entity_id': reminder['reminder_id'],
            'series_id': reminder['recurrence']['series_id'], 'recurrence_id': '20260301T090000',
            'source_version': reminder['recurrence']['source_version'],
        }
        PlannerApplicationService.act_on_reminder_occurrence(
            self.context('reminder-complete'),
            {'occurrence_ref': ref, 'expected_version': ref['source_version'], 'action': 'complete'},
        )
        self.assertEqual(ReminderOccurrenceState.objects.filter(deleted_at__isnull=True).count(), 1)
        PlannerRollbackCoordinator.rollback_tool_call(self.context('rollback-request'), 'reminder-complete')
        self.assertEqual(ReminderOccurrenceState.objects.filter(deleted_at__isnull=True).count(), 0)

    def test_external_write_after_agent_command_causes_atomic_conflict(self):
        result = self.create_event('seed', reversible=False)
        event_id = result['event']['event_id']
        event = CalendarEvent.objects.get(event_id=event_id)
        PlannerApplicationService.patch_event(
            self.context('agent-edit'), event_id, {'description': 'Agent 修改'},
            scope='all', occurrence_ref=None, expected_version=event.version,
        )
        event.refresh_from_db()
        PlannerApplicationService.patch_event(
            PlannerExecutionContext(
                user=self.user, source='web_v2', entrypoint=PlannerRolloutPolicy.ENTRYPOINT_API_V2
            ),
            event_id, {'title': 'Web 后续修改'}, scope='all', occurrence_ref=None,
            expected_version=event.version,
        )

        with self.assertRaises(PlannerRollbackConflict):
            PlannerRollbackCoordinator.rollback_tool_call(self.context('rollback-request'), 'agent-edit')
        event.refresh_from_db()
        self.assertEqual(event.title, 'Web 后续修改')
        self.assertEqual(event.description, 'Agent 修改')
        self.assertEqual(PlannerChangeSet.objects.get(tool_call_id='agent-edit').rollback_status, 'available')

    def test_rotating_window_expires_and_physically_deletes_old_snapshots(self):
        self.create_event('window-edit')
        self.assertTrue(PlannerRollbackSnapshot.objects.exists())
        new_window = AgentRollbackWindowService.rotate(
            user=self.user, session_id=self.session.session_id,
            floor_message_index=8, activation_token='activation-2',
        )
        self.window.refresh_from_db()
        self.assertEqual(self.window.status, AgentRollbackWindow.STATUS_CLOSED)
        self.assertEqual(new_window.generation, 2)
        self.assertFalse(PlannerRollbackSnapshot.objects.exists())
        self.assertEqual(PlannerChangeSet.objects.get(tool_call_id='window-edit').rollback_status, 'expired')

    def test_group_delete_with_items_restores_group_and_members(self):
        group = PlannerApplicationService.create_group(
            self.context('group-seed', reversible=False), {'name': '工作'}
        )['group']
        event = PlannerApplicationService.create_event(
            self.context('group-event-seed', reversible=False),
            {
                'title': '组内日程', 'start': self.start.isoformat(), 'end': self.end.isoformat(),
                'group_id': group['group_id'],
            },
            range_start=self.start, range_end=self.end,
        )['event']
        PlannerApplicationService.delete_group(
            self.context('group-delete'), group['group_id'], group['version'], delete_items=True
        )
        self.assertIsNotNone(EventGroup.objects.get(group_id=group['group_id']).deleted_at)
        self.assertIsNotNone(CalendarEvent.objects.get(event_id=event['event_id']).deleted_at)

        PlannerRollbackCoordinator.rollback_tool_call(self.context('rollback-request'), 'group-delete')

        restored_group = EventGroup.objects.get(group_id=group['group_id'])
        restored_event = CalendarEvent.objects.get(event_id=event['event_id'])
        self.assertIsNone(restored_group.deleted_at)
        self.assertIsNone(restored_event.deleted_at)
        self.assertEqual(restored_event.group_id, restored_group.pk)

    def test_failed_or_below_floor_command_leaves_no_snapshot_or_transaction(self):
        result = self.create_event('seed', reversible=False)
        event = CalendarEvent.objects.get(event_id=result['event']['event_id'])
        baseline = (PlannerRollbackSnapshot.objects.count(), AgentTransaction.objects.count())
        with self.assertRaises(Exception):
            PlannerApplicationService.patch_event(
                self.context('invalid-edit'), event.event_id, {'start': 'not-a-time'},
                scope='all', occurrence_ref=None, expected_version=event.version,
            )
        self.assertEqual(baseline, (PlannerRollbackSnapshot.objects.count(), AgentTransaction.objects.count()))

        with self.assertRaisesRegex(Exception, 'rollback window'):
            PlannerApplicationService.patch_event(
                self.context('below-floor', message_index=3), event.event_id, {'title': '不应写入'},
                scope='all', occurrence_ref=None, expected_version=event.version,
            )
        event.refresh_from_db()
        self.assertEqual(event.title, '原始日程')
