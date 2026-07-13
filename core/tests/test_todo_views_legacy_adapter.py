"""Historical Todo URL compatibility is an explicit 410 tombstone."""

import json

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import UserData


class TodoViewsRetirementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="todo-v1-retired", password="test-password")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.archive = UserData.objects.create(
            user=self.user, key="todos",
            value=json.dumps([{"id": "legacy-todo", "future_field": {"keep": True}}]),
        )

    def test_todo_v1_crud_and_convert_are_gone_and_archive_is_unchanged(self):
        before = self.archive.value
        paths = (
            ("get", "/api/todos/"),
            ("post", "/api/todos/create/"),
            ("post", "/api/todos/update/"),
            ("post", "/api/todos/delete/"),
            ("post", "/api/todos/convert/"),
        )
        for method, path in paths:
            with self.subTest(path=path):
                response = getattr(self.client, method)(path, {}, format="json")
                self.assertEqual(response.status_code, 410, response.content)
                self.assertEqual(response.json()["code"], "planner_v1_api_retired")
        self.archive.refresh_from_db()
        self.assertEqual(self.archive.value, before)
