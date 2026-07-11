"""复杂 legacy 入口使用的 PlannerUserDataCompat 回归测试。"""

import json

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import UserData
from core.planner.legacy import PlannerUserDataCompat


class MockRequest:
    def __init__(self, user):
        self.user = user


class PlannerUserDataCompatTests(TestCase):
    """验证旧调用形状不会重新套用 DATA_SCHEMA。"""

    def setUp(self):
        self.user = User.objects.create_user(username='planner-compat-user', password='test-password')
        self.request = MockRequest(self.user)

    def test_existing_planner_row_preserves_unknown_fields_even_with_check(self):
        UserData.objects.create(
            user=self.user,
            key='events',
            value=json.dumps([{'id': 'event-1', 'future_field': {'keep': True}}]),
        )

        row, created, _ = PlannerUserDataCompat.get_or_initialize(self.request, 'events')
        value = row.get_value(check=True)
        row.set_value(value, check=True)

        self.assertFalse(created)
        stored = json.loads(UserData.objects.get(user=self.user, key='events').value)
        self.assertEqual(stored[0]['future_field'], {'keep': True})

    def test_missing_rule_storage_uses_dict_default(self):
        row, created, _ = PlannerUserDataCompat.get_or_initialize(self.request, 'rrule_series_storage')

        self.assertTrue(created)
        self.assertEqual(row.get_value(), {})

    def test_objects_get_or_create_returns_a_planner_record_for_group_list(self):
        row, created = PlannerUserDataCompat.objects.get_or_create(
            user=self.user,
            key='events_groups',
            defaults={'value': '[]'},
        )
        row.set_value([{'id': 'group-1', 'future_field': {'keep': True}}], check=True)

        self.assertTrue(created)
        self.assertEqual(row.get_value(check=True)[0]['future_field'], {'keep': True})
