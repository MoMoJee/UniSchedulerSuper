import hashlib
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from langchain_core.messages import AIMessage, HumanMessage
from rest_framework.test import APIClient

from agent_service.models import AgentRollbackWindow, AgentSession
from agent_service.rollback_windows import AgentRollbackWindowService
from core.models import (
    CalendarEvent, PlannerChangeSet, PlannerCohortAssignment, PlannerMigrationState,
    PlannerRollbackSnapshot, UserData,
)
from core.planner.application import PlannerApplicationService
from core.planner.context import PlannerExecutionContext
from core.planner.rollout import PlannerRolloutPolicy


@override_settings(PLANNER_STORAGE_MODE='normalized')
class AgentRollbackWindowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='window-api-user', password='test-password')
        source = UserData.objects.create(user=self.user, key='events', value='[]')
        PlannerMigrationState.objects.create(
            user=self.user, source_key='events', source_row_id=source.id,
            source_checksum=hashlib.sha256(b'[]').hexdigest(),
            status=PlannerMigrationState.STATUS_VERIFIED,
        )
        PlannerCohortAssignment.objects.create(
            user=self.user, storage_mode=PlannerCohortAssignment.MODE_NORMALIZED,
            entrypoints={
                PlannerRolloutPolicy.ENTRYPOINT_AGENT: {'mode': 'normalized'},
                PlannerRolloutPolicy.ENTRYPOINT_API_V2: {'mode': 'normalized'},
            },
        )
        self.first = AgentSession.objects.create(
            user=self.user, session_id=f'user_{self.user.id}_first', name='first'
        )
        self.second = AgentSession.objects.create(
            user=self.user, session_id=f'user_{self.user.id}_second', name='second'
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_rotate_is_idempotent_and_only_one_user_window_remains_active(self):
        first = AgentRollbackWindowService.rotate(
            user=self.user, session_id=self.first.session_id,
            floor_message_index=3, activation_token='first-token',
        )
        repeated = AgentRollbackWindowService.rotate(
            user=self.user, session_id=self.first.session_id,
            floor_message_index=99, activation_token='first-token',
        )
        self.assertEqual(first.pk, repeated.pk)
        second = AgentRollbackWindowService.rotate(
            user=self.user, session_id=self.second.session_id,
            floor_message_index=8, activation_token='second-token',
        )
        first.refresh_from_db()
        self.assertEqual(first.status, AgentRollbackWindow.STATUS_CLOSED)
        self.assertEqual(second.status, AgentRollbackWindow.STATUS_ACTIVE)
        self.assertEqual(AgentRollbackWindow.objects.filter(user=self.user, status='active').count(), 1)
        reopened = AgentRollbackWindowService.rotate(
            user=self.user, session_id=self.first.session_id,
            floor_message_index=11, activation_token='return-token',
        )
        second.refresh_from_db()
        self.assertEqual(second.status, AgentRollbackWindow.STATUS_CLOSED)
        self.assertEqual(reopened.generation, 2)
        self.assertEqual(reopened.floor_message_index, 11)

    def test_ensure_active_repairs_missing_window_and_refresh_preserves_it(self):
        window = AgentRollbackWindowService.ensure_active(
            user=self.user, session_id=self.first.session_id, floor_message_index=6
        )
        refreshed = AgentRollbackWindowService.ensure_active(
            user=self.user, session_id=self.first.session_id, floor_message_index=99
        )
        self.assertEqual(refreshed.pk, window.pk)
        self.assertEqual(refreshed.generation, 1)
        self.assertEqual(refreshed.floor_message_index, 6)

        switched = AgentRollbackWindowService.ensure_active(
            user=self.user, session_id=self.second.session_id, floor_message_index=4
        )
        window.refresh_from_db()
        self.assertEqual(window.status, AgentRollbackWindow.STATUS_CLOSED)
        self.assertEqual(switched.floor_message_index, 4)

    @patch('agent_service.agent_graph.app')
    def test_history_exposes_server_floor_and_per_message_permission(self, mocked_app):
        window = AgentRollbackWindowService.rotate(
            user=self.user, session_id=self.first.session_id,
            floor_message_index=2, activation_token='history-token',
        )
        mocked_app.get_state.return_value = SimpleNamespace(values={'messages': [
            HumanMessage(content='旧消息', id='h0'), AIMessage(content='旧回复', id='a1'),
            HumanMessage(content='新消息', id='h2'), AIMessage(content='新回复', id='a3'),
        ]})
        response = self.client.get('/api/agent/history/', {'session_id': self.first.session_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['rollback_window']['window_id'], str(window.window_id))
        users = [item for item in response.data['messages'] if item['role'] == 'user']
        self.assertFalse(users[0]['can_rollback'])
        self.assertTrue(users[1]['can_rollback'])

    @patch('agent_service.agent_graph.app')
    def test_history_creates_missing_server_window_at_current_message_end(self, mocked_app):
        mocked_app.get_state.return_value = SimpleNamespace(values={'messages': [
            HumanMessage(content='历史消息', id='h0'), AIMessage(content='历史回复', id='a1'),
        ]})
        response = self.client.get('/api/agent/history/', {'session_id': self.first.session_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['rollback_window']['floor_message_index'], 2)
        window = AgentRollbackWindow.objects.get(user=self.user, status='active')
        self.assertEqual(window.session.session_id, self.first.session_id)
        self.assertFalse(response.data['messages'][0]['can_rollback'])

    @patch('agent_service.agent_graph.app')
    def test_message_without_planner_tool_can_still_be_rolled_back(self, mocked_app):
        AgentRollbackWindowService.ensure_active(
            user=self.user, session_id=self.first.session_id, floor_message_index=2
        )
        mocked_app.get_state.return_value = SimpleNamespace(values={'messages': [
            HumanMessage(content='旧', id='h0'), AIMessage(content='回复', id='a1'),
            HumanMessage(content='普通聊天', id='h2'), AIMessage(content='普通回复', id='a3'),
        ]})
        response = self.client.post('/api/agent/rollback/to-message/', {
            'session_id': self.first.session_id, 'message_index': 2,
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['rolled_back_transactions'], 0)
        self.assertTrue(mocked_app.update_state.called)

    @patch('agent_service.agent_graph.app')
    def test_closed_or_pre_floor_message_is_rejected_with_410(self, mocked_app):
        AgentRollbackWindowService.rotate(
            user=self.user, session_id=self.first.session_id,
            floor_message_index=2, activation_token='expired-token',
        )
        mocked_app.get_state.return_value = SimpleNamespace(values={'messages': [
            HumanMessage(content='旧消息', id='h0'), AIMessage(content='回复', id='a1'),
        ]})
        response = self.client.post('/api/agent/rollback/to-message/', {
            'session_id': self.first.session_id, 'message_index': 0,
        }, format='json')
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.data['code'], 'rollback_window_expired')
        self.assertFalse(mocked_app.update_state.called)

    @patch('agent_service.agent_graph.app')
    def test_message_rollback_restores_new_snapshot_and_clears_cache(self, mocked_app):
        window = AgentRollbackWindowService.rotate(
            user=self.user, session_id=self.first.session_id,
            floor_message_index=2, activation_token='rollback-token',
        )
        start = timezone.make_aware(datetime(2026, 3, 1, 9))
        context = PlannerExecutionContext(
            user=self.user, source='websocket_agent', entrypoint=PlannerRolloutPolicy.ENTRYPOINT_AGENT,
            session_id=self.first.session_id, tool_call_id='call-1', message_index=2,
            rollback_window_id=str(window.window_id), reversible=True,
        )
        result = PlannerApplicationService.create_event(
            context, {'title': '待回滚', 'start': start.isoformat(), 'end': (start + timedelta(hours=1)).isoformat()},
            range_start=start, range_end=start + timedelta(hours=1),
        )
        mocked_app.get_state.return_value = SimpleNamespace(values={'messages': [
            HumanMessage(content='旧', id='h0'), AIMessage(content='回复', id='a1'),
            HumanMessage(content='创建', id='h2'), AIMessage(content='完成', id='a3'),
        ]})
        response = self.client.post('/api/agent/rollback/to-message/', {
            'session_id': self.first.session_id, 'message_index': 2,
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['rolled_back_transactions'], 1)
        event = CalendarEvent.objects.get(event_id=result['event']['event_id'])
        self.assertIsNotNone(event.deleted_at)
        self.assertTrue(mocked_app.update_state.called)

    def test_legacy_steps_endpoints_are_gone(self):
        self.assertEqual(self.client.post('/api/agent/rollback/preview/', {}, format='json').status_code, 410)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post('/api/agent/rollback/', {}, format='json').status_code, 410)

    def test_tool_node_binds_active_window_and_human_message_index(self):
        from agent_service.agent_graph import create_tool_node_with_permission_check

        window = AgentRollbackWindowService.rotate(
            user=self.user, session_id=self.first.session_id,
            floor_message_index=0, activation_token='tool-node-token',
        )
        node = create_tool_node_with_permission_check()
        state = {
            'active_tools': ['create_item'],
            'messages': [
                HumanMessage(content='创建日程', id='human-0'),
                AIMessage(content='', tool_calls=[{
                    'id': 'agent-tool-1', 'name': 'create_item', 'args': {
                        'item_type': 'event', 'title': '工具节点日程',
                        'start': '2026-03-01T09:00:00+08:00',
                        'end': '2026-03-01T10:00:00+08:00',
                    },
                }]),
            ],
        }
        result = node(state, {'configurable': {
            'user': self.user, 'thread_id': self.first.session_id,
            'active_tools': ['create_item'],
        }})
        self.assertIn('创建成功', result['messages'][0].content)
        transaction = window.transactions.get(tool_call_id='agent-tool-1')
        self.assertEqual(transaction.message_index, 0)
        self.assertEqual(transaction.source, 'websocket_agent')
        self.assertTrue(PlannerRollbackSnapshot.objects.filter(rollback_window=window).exists())

    @patch('agent_service.agent_graph.app')
    def test_conflicting_later_write_returns_409_without_removing_messages(self, mocked_app):
        window = AgentRollbackWindowService.rotate(
            user=self.user, session_id=self.first.session_id,
            floor_message_index=2, activation_token='conflict-token',
        )
        start = timezone.make_aware(datetime(2026, 3, 1, 9))
        base = PlannerApplicationService.create_event(
            PlannerExecutionContext(
                user=self.user, source='websocket_agent', entrypoint=PlannerRolloutPolicy.ENTRYPOINT_AGENT,
                session_id=self.first.session_id, tool_call_id='seed', reversible=False,
            ),
            {'title': '原始', 'start': start.isoformat(), 'end': (start + timedelta(hours=1)).isoformat()},
            range_start=start, range_end=start + timedelta(hours=1),
        )
        event = CalendarEvent.objects.get(event_id=base['event']['event_id'])
        PlannerApplicationService.patch_event(
            PlannerExecutionContext(
                user=self.user, source='websocket_agent', entrypoint=PlannerRolloutPolicy.ENTRYPOINT_AGENT,
                session_id=self.first.session_id, tool_call_id='agent-edit', message_index=2,
                rollback_window_id=str(window.window_id), reversible=True,
            ), event.event_id, {'description': 'Agent'}, scope='all', occurrence_ref=None,
            expected_version=event.version,
        )
        event.refresh_from_db()
        PlannerApplicationService.patch_event(
            PlannerExecutionContext(
                user=self.user, source='web_v2', entrypoint=PlannerRolloutPolicy.ENTRYPOINT_API_V2
            ), event.event_id, {'title': '网页后改'}, scope='all', occurrence_ref=None,
            expected_version=event.version,
        )
        mocked_app.get_state.return_value = SimpleNamespace(values={'messages': [
            HumanMessage(content='旧', id='h0'), AIMessage(content='回复', id='a1'),
            HumanMessage(content='修改', id='h2'), AIMessage(content='完成', id='a3'),
        ]})
        response = self.client.post('/api/agent/rollback/to-message/', {
            'session_id': self.first.session_id, 'message_index': 2,
        }, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'rollback_conflict')
        self.assertFalse(mocked_app.update_state.called)
        self.assertEqual(PlannerChangeSet.objects.get(tool_call_id='agent-edit').rollback_status, 'available')
