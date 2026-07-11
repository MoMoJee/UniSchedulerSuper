"""EventService 通过 legacy repository 兼容读写的回归测试。"""

import json

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import UserData
from core.services.event_service import EventService


class EventServiceLegacyAdapterTests(TestCase):
    """非重复日程路径必须保留 legacy JSON 的未知字段。"""

    def setUp(self):
        self.user = User.objects.create_user(username='event-service-user', password='test-password')

    def test_create_update_and_delete_preserve_existing_unknown_fields(self):
        UserData.objects.create(
            user=self.user,
            key='events',
            value=json.dumps([
                {
                    'id': 'legacy-event',
                    'title': '旧日程',
                    'start': '2026-03-01T09:00',
                    'end': '2026-03-01T10:00',
                    'future_field': {'keep': True},
                }
            ]),
        )

        created = EventService.create_event(
            self.user,
            '新日程',
            '2026-03-02T09:00',
            '2026-03-02T10:00',
        )
        updated = EventService.update_event(self.user, created['id'], title='已更新日程')

        stored = json.loads(UserData.objects.get(user=self.user, key='events').value)
        self.assertEqual(stored[0]['future_field'], {'keep': True})
        self.assertEqual(updated['title'], '已更新日程')
        self.assertTrue(EventService.delete_event(self.user, created['id']))
        self.assertEqual(EventService.get_events(self.user)[0]['id'], 'legacy-event')
