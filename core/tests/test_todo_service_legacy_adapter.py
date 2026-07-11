"""TodoService 通过 legacy repository 兼容读写的回归测试。"""

import json

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import UserData
from core.services.todo_service import TodoService


class TodoServiceLegacyAdapterTests(TestCase):
    """确保 Service 收敛后仍保留 legacy JSON 的未知字段。"""

    def setUp(self):
        self.user = User.objects.create_user(username='todo-service-user', password='test-password')

    def test_create_update_and_delete_preserve_existing_unknown_fields(self):
        UserData.objects.create(
            user=self.user,
            key='todos',
            value=json.dumps([{'id': 'legacy-todo', 'title': '旧待办', 'future_field': {'keep': True}}]),
        )

        created = TodoService.create_todo(self.user, '新待办', description='描述')
        updated = TodoService.update_todo(self.user, created['id'], status='completed')

        stored = json.loads(UserData.objects.get(user=self.user, key='todos').value)
        self.assertEqual(stored[0]['future_field'], {'keep': True})
        self.assertEqual(updated['status'], 'completed')
        self.assertTrue(TodoService.delete_todo(self.user, created['id']))
        self.assertEqual(TodoService.get_todos(self.user)[0]['id'], 'legacy-todo')

    def test_create_initializes_only_the_legacy_list_when_key_is_absent(self):
        created = TodoService.create_todo(self.user, '首个待办')

        stored = json.loads(UserData.objects.get(user=self.user, key='todos').value)
        self.assertEqual(stored, [created])
