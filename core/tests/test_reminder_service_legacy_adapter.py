"""ReminderService 通过 legacy repository 兼容读写的回归测试。"""

import json

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import UserData
from core.services.reminder_service import ReminderService


class ReminderServiceLegacyAdapterTests(TestCase):
    """非重复提醒路径必须保留 legacy JSON 的未知字段。"""

    def setUp(self):
        self.user = User.objects.create_user(username='reminder-service-user', password='test-password')

    def test_create_update_and_delete_preserve_existing_unknown_fields(self):
        UserData.objects.create(
            user=self.user,
            key='reminders',
            value=json.dumps([{'id': 'legacy-reminder', 'title': '旧提醒', 'future_field': {'keep': True}}]),
        )

        created = ReminderService.create_reminder(self.user, '新提醒', content='内容', trigger_time='2026-03-01T09:00')
        updated = ReminderService.update_reminder(self.user, created['id'], status='dismissed')

        stored = json.loads(UserData.objects.get(user=self.user, key='reminders').value)
        self.assertEqual(stored[0]['future_field'], {'keep': True})
        self.assertEqual(updated['status'], 'dismissed')
        self.assertTrue(ReminderService.delete_reminder(self.user, created['id']))
        self.assertEqual(ReminderService.get_reminders(self.user)[0]['id'], 'legacy-reminder')

    def test_create_initializes_only_the_legacy_list_when_key_is_absent(self):
        created = ReminderService.create_reminder(self.user, '首个提醒')

        stored = json.loads(UserData.objects.get(user=self.user, key='reminders').value)
        self.assertEqual(stored, [created])

    def test_recurring_create_keeps_using_existing_rrule_storage_compatibility_path(self):
        created = ReminderService.create_reminder(
            self.user,
            '重复提醒',
            trigger_time='2026-03-01T09:00',
            rrule='FREQ=DAILY;COUNT=2',
        )

        reminders = ReminderService.get_reminders(self.user)
        self.assertTrue(created['is_recurring'])
        self.assertEqual(created['rrule'], 'FREQ=DAILY;COUNT=2')
        self.assertTrue(any(item.get('id') == created['id'] for item in reminders))
        self.assertTrue(UserData.objects.filter(user=self.user, key='rrule_series_storage').exists())
