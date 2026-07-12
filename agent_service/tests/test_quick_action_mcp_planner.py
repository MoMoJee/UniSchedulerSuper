import hashlib
import time
from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from langchain_core.messages import AIMessage
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from reversion.models import Revision

import mcp_server
from agent_service.models import AgentTransaction, QuickActionTask
from agent_service.quick_action_agent import clear_task_cancellation, is_task_cancelled, tool_node_wrapper
from core.models import CalendarEvent, PlannerCohortAssignment, PlannerMigrationState, PlannerRollbackSnapshot, UserData
from core.planner.rollout import PlannerRolloutPolicy


@override_settings(PLANNER_STORAGE_MODE='normalized')
class QuickActionMcpPlannerTests(TestCase):
    def verified_user(self, username: str, entrypoint: str):
        user = User.objects.create_user(username=username, password='test-password')
        source = UserData.objects.create(user=user, key='events', value='[]')
        PlannerMigrationState.objects.create(
            user=user, source_key='events', source_row_id=source.id,
            source_checksum=hashlib.sha256(b'[]').hexdigest(), status=PlannerMigrationState.STATUS_VERIFIED,
        )
        PlannerCohortAssignment.objects.create(
            user=user, storage_mode=PlannerCohortAssignment.MODE_NORMALIZED,
            entrypoints={entrypoint: {'mode': 'normalized'}},
        )
        return user, source

    def test_quick_action_injects_per_call_context_and_is_not_chat_reversible(self):
        user, legacy = self.verified_user('quick-user', PlannerRolloutPolicy.ENTRYPOINT_QUICK_ACTION)
        task = QuickActionTask.objects.create(user=user, input_text='创建会议')
        call_id = 'qa-call-1'
        state = {
            'user': user, 'task_id': str(task.task_id),
            'messages': [AIMessage(content='', tool_calls=[{
                'id': call_id, 'name': 'create_item', 'args': {
                    'item_type': 'event', 'title': 'Quick会议',
                    'start': '2026-03-01T09:00:00+08:00', 'end': '2026-03-01T10:00:00+08:00',
                },
            }])],
            'tool_calls_log': [],
        }
        revisions = Revision.objects.count()
        result = tool_node_wrapper(state)

        self.assertIn('创建成功', result['messages'][0].content)
        self.assertTrue(CalendarEvent.objects.filter(user=user, title='Quick会议').exists())
        legacy.refresh_from_db()
        self.assertEqual(legacy.value, '[]')
        self.assertEqual(Revision.objects.count(), revisions)
        self.assertEqual(PlannerRollbackSnapshot.objects.count(), 0)
        self.assertEqual(AgentTransaction.objects.count(), 0)
        self.assertEqual(result['messages'][0].tool_call_id, call_id)

    def test_mcp_stdio_wrapper_uses_normalized_application_and_fixed_user_session(self):
        user, legacy = self.verified_user('mcp-stdio-user', PlannerRolloutPolicy.ENTRYPOINT_MCP)
        mcp_server._stdio_user = user
        mcp_server._current_user_var.set(None)
        mcp_server._current_transport_var.set('mcp_stdio')
        mcp_server._current_request_id_var.set('stdio')
        created = async_to_sync(mcp_server.create_item)(
            item_type='event', title='MCP stdio',
            start='2026-03-01T09:00:00+08:00', end='2026-03-01T10:00:00+08:00',
        )
        self.assertIn('创建成功', created)
        config = mcp_server._build_config(user)['configurable']
        self.assertEqual(config['planner_source'], 'mcp_stdio')
        self.assertEqual(config['session_id'], f'mcp_stdio_{user.id}_stdio')
        legacy.refresh_from_db()
        self.assertEqual(legacy.value, '[]')
        self.assertFalse(PlannerRollbackSnapshot.objects.exists())

    def test_http_never_falls_back_to_stdio_user_and_sessions_are_isolated(self):
        stdio, _ = self.verified_user('stdio-fallback-user', PlannerRolloutPolicy.ENTRYPOINT_MCP)
        http, _ = self.verified_user('http-user', PlannerRolloutPolicy.ENTRYPOINT_MCP)
        mcp_server._stdio_user = stdio
        mcp_server._current_transport_var.set('mcp_http')
        mcp_server._current_user_var.set(None)
        with self.assertRaisesRegex(ValueError, '缺少独立认证用户'):
            mcp_server._get_current_user()

        mcp_server._current_user_var.set(http)
        mcp_server._current_request_id_var.set('client-session-1')
        first = mcp_server._build_config(http)['configurable']
        mcp_server._current_request_id_var.set('client-session-2')
        second = mcp_server._build_config(http)['configurable']
        self.assertNotEqual(first['session_id'], second['session_id'])
        self.assertEqual(first['planner_source'], 'mcp_http')
        self.assertEqual(mcp_server._get_current_user(), http)

    def test_mcp_token_resolution_rejects_invalid_and_binds_valid_user(self):
        user, _ = self.verified_user('mcp-token-user', PlannerRolloutPolicy.ENTRYPOINT_MCP)
        token = Token.objects.create(user=user)
        mcp_server._token_user_cache.clear()
        self.assertIsNone(mcp_server._resolve_user_from_token('invalid-token'))
        self.assertEqual(mcp_server._resolve_user_from_token(token.key), user)

    def test_mcp_stdio_search_update_delete_recurrence_uses_same_refs(self):
        user, legacy = self.verified_user('mcp-crud-user', PlannerRolloutPolicy.ENTRYPOINT_MCP)
        mcp_server._stdio_user = user
        mcp_server._current_user_var.set(None)
        mcp_server._current_transport_var.set('mcp_stdio')
        mcp_server._current_request_id_var.set('crud')
        async_to_sync(mcp_server.create_item)(
            item_type='event', title='MCP重复',
            start='2026-03-01T09:00:00+08:00', end='2026-03-01T10:00:00+08:00',
            repeat='FREQ=DAILY;COUNT=3',
        )
        searched = async_to_sync(mcp_server.search_items)(
            item_type='event', keyword='MCP重复', time_range='2026-03-01 ~ 2026-03-05'
        )
        self.assertIn('#2', searched)
        updated = async_to_sync(mcp_server.update_item)(
            identifier='#2', item_type='event', edit_scope='single', description='只改第二次'
        )
        self.assertIn('更新成功', updated)
        async_to_sync(mcp_server.search_items)(
            item_type='event', keyword='MCP重复', time_range='2026-03-01 ~ 2026-03-05'
        )
        deleted = async_to_sync(mcp_server.delete_item)(
            identifier='#1', item_type='event', delete_scope='all'
        )
        self.assertIn('删除成功', deleted)
        legacy.refresh_from_db()
        self.assertEqual(legacy.value, '[]')
        self.assertFalse(PlannerRollbackSnapshot.objects.exists())

    @patch('agent_service.views_quick_action.execute_quick_action_sync')
    def test_quick_action_sync_timeout_marks_task_without_snapshot(self, execute):
        user, _ = self.verified_user('quick-timeout-user', PlannerRolloutPolicy.ENTRYPOINT_QUICK_ACTION)
        execute.side_effect = lambda *args: (time.sleep(0.1) or {
            'type': 'action_completed', 'message': 'late', 'tool_calls': [], 'tokens': {},
        })
        client = APIClient()
        client.force_authenticate(user)
        response = client.post('/api/agent/quick-action/', {
            'text': '超时测试', 'sync': True, 'timeout': 0,
        }, format='json')
        self.assertEqual(response.status_code, 408)
        task = QuickActionTask.objects.get(user=user)
        self.assertEqual(task.status, 'timeout')
        self.assertFalse(PlannerRollbackSnapshot.objects.exists())
        clear_task_cancellation(str(task.task_id))

    def test_quick_action_pending_task_can_be_cancelled(self):
        user, _ = self.verified_user('quick-cancel-user', PlannerRolloutPolicy.ENTRYPOINT_QUICK_ACTION)
        task = QuickActionTask.objects.create(user=user, input_text='取消测试')
        client = APIClient()
        client.force_authenticate(user)
        response = client.delete(f'/api/agent/quick-action/{task.task_id}/cancel/')
        self.assertEqual(response.status_code, 200)
        task.refresh_from_db()
        self.assertTrue(task.result['cancelled'])
        self.assertTrue(is_task_cancelled(str(task.task_id)))
        clear_task_cancellation(str(task.task_id))
