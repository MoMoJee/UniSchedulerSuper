from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase

from UniSchedulerSuper.asgi import application


class FrontendWebSocketSmokeTests(TransactionTestCase):
    def test_authenticated_agent_websocket_connects_and_answers_ping(self):
        user = get_user_model().objects.create_user('frontend-ws-user', password='safe-test-password')
        self.client.force_login(user)
        session_id = self.client.cookies['sessionid'].value
        with (
            patch('agent_service.consumers.AgentConsumer._init_graph', new_callable=AsyncMock) as init_graph,
            patch('agent_service.consumers.get_async_app', new_callable=AsyncMock) as get_async_app,
            patch('agent_service.rollback_windows.AgentRollbackWindowService.ensure_active') as ensure_active,
            patch('agent_service.consumers.logger'),
        ):
            get_async_app.return_value = SimpleNamespace(
                aget_state=AsyncMock(return_value=SimpleNamespace(values={'messages': []}))
            )
            communicator = WebsocketCommunicator(
                application,
                '/ws/agent/?session_id=fr0-smoke&active_tools=',
                headers=[
                    (b'cookie', f'sessionid={session_id}'.encode()),
                    (b'origin', b'http://testserver'),
                ],
            )

            async def exercise_connection():
                try:
                    connected, _ = await communicator.connect()
                    self.assertTrue(connected)
                    self.assertEqual(
                        (await communicator.receive_json_from(timeout=5))['type'],
                        'connected',
                    )

                    await communicator.send_json_to({'type': 'ping'})
                    self.assertEqual(
                        (await communicator.receive_json_from(timeout=5))['type'],
                        'pong',
                    )
                finally:
                    await communicator.disconnect()

            async_to_sync(exercise_connection)()

            init_graph.assert_awaited_once()
            get_async_app.assert_awaited_once()
            ensure_active.assert_called_once()
