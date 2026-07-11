"""Todo HTTP 入口通过 TodoService/legacy repository 的回归测试。"""

import json

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import UserData


class TodoViewsLegacyAdapterTests(TestCase):
    """验证 URL、响应 JSON 和未知字段与旧接口兼容。"""

    def setUp(self):
        self.user = User.objects.create_user(username='todo-view-user', password='test-password')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_get_does_not_initialize_an_absent_legacy_key(self):
        response = self.client.get('/api/todos/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'todos': []})
        self.assertFalse(UserData.objects.filter(user=self.user, key='todos').exists())

    def test_http_crud_preserves_unknown_legacy_fields(self):
        UserData.objects.create(
            user=self.user,
            key='todos',
            value=json.dumps([{'id': 'legacy-todo', 'title': '旧待办', 'future_field': {'keep': True}}]),
        )

        create = self.client.post('/api/todos/create/', {'title': '新待办', 'description': '描述'}, format='json')
        self.assertEqual(create.status_code, 200)
        todo = create.json()['todo']

        update = self.client.post('/api/todos/update/', {'id': todo['id'], 'status': 'completed'}, format='json')
        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.json()['todo']['status'], 'completed')

        stored = json.loads(UserData.objects.get(user=self.user, key='todos').value)
        self.assertEqual(stored[0]['future_field'], {'keep': True})

        delete = self.client.post('/api/todos/delete/', {'id': todo['id']}, format='json')
        self.assertEqual(delete.status_code, 200)
        self.assertEqual(self.client.get('/api/todos/').json()['todos'][0]['id'], 'legacy-todo')

    def test_convert_locks_and_updates_todo_and_event_lists_together(self):
        UserData.objects.create(
            user=self.user,
            key='todos',
            value=json.dumps(
                [
                    {
                        'id': 'convert-todo',
                        'title': '待转换',
                        'description': '保留描述',
                        'importance': 'important',
                        'urgency': 'urgent',
                        'groupID': 'group-1',
                        'due_date': '2026-03-03',
                        'future_field': {'keep': True},
                    }
                ]
            ),
        )

        response = self.client.post(
            '/api/todos/convert/',
            {'id': 'convert-todo', 'start_time': '2026-03-02T09:00', 'end_time': '2026-03-02T10:00'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        event = response.json()['event']
        todos = json.loads(UserData.objects.get(user=self.user, key='todos').value)
        events = json.loads(UserData.objects.get(user=self.user, key='events').value)
        self.assertEqual(todos[0]['status'], 'converted')
        self.assertEqual(todos[0]['converted_to_event'], event['id'])
        self.assertEqual(todos[0]['future_field'], {'keep': True})
        self.assertEqual(events[0]['converted_from_todo'], 'convert-todo')
