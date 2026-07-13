import base64
import hashlib

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token

from core.models import (
    CalendarChange, CalendarCollectionVersion, EventGroup, PlannerCohortAssignment,
    PlannerMigrationState, UserData,
)
from core.planner.entities import PlannerEntityCommandService


@override_settings(PLANNER_STORAGE_MODE='normalized')
class CalDAVVersionContractTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='caldav-version')
        token = Token.objects.create(user=self.user)
        value = base64.b64encode(f'{self.user.username}:{token.key}'.encode()).decode()
        self.auth = f'Basic {value}'
        source = UserData.objects.create(user=self.user, key='events', value='[]')
        PlannerMigrationState.objects.create(
            user=self.user, source_key='events', source_row_id=source.id,
            source_checksum=hashlib.sha256(b'[]').hexdigest(),
            status=PlannerMigrationState.STATUS_VERIFIED,
        )
        PlannerCohortAssignment.objects.create(
            user=self.user, storage_mode='normalized',
            entrypoints={'caldav_read': {'mode': 'normalized'}, 'caldav_write': {'mode': 'normalized'}},
        )
        self.group = EventGroup.objects.create(user=self.user, name='版本组')

    def request(self, method, path, body=b'', **headers):
        return self.client.generic(
            method, path, data=body, content_type='text/calendar; charset=utf-8',
            HTTP_AUTHORIZATION=self.auth, **headers,
        )

    @staticmethod
    def body(summary):
        return f'''BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Version Test//EN\r
BEGIN:VEVENT\r
UID:stable-version-uid@example.test\r
DTSTART;TZID=Asia/Shanghai:20260713T100000\r
DTEND;TZID=Asia/Shanghai:20260713T110000\r
SUMMARY:{summary}\r
END:VEVENT\r
END:VCALENDAR\r
'''.encode()

    def test_etag_collection_versions_move_tombstone_and_conditional_get(self):
        default_path = f'/caldav/{self.user.username}/default/version-resource.ics'
        created = self.request('PUT', default_path, self.body('v1'), HTTP_IF_NONE_MATCH='*')
        self.assertEqual(created.status_code, 201)
        etag1 = created['ETag']
        default = CalendarCollectionVersion.objects.get(
            user=self.user, collection_type='caldav', collection_id='default'
        )
        self.assertEqual(default.version, 1)
        first_change = default.changes.get()
        self.assertEqual(first_change.action, CalendarChange.ACTION_CREATE)
        self.assertEqual(first_change.resource_public_id, 'version-resource')
        self.assertEqual(first_change.etag, etag1)

        cached = self.request('GET', default_path, HTTP_IF_NONE_MATCH=etag1)
        self.assertEqual(cached.status_code, 304)
        self.assertEqual(cached['ETag'], etag1)

        second = self.request('PUT', default_path, self.body('v2'), HTTP_IF_MATCH=etag1)
        third = self.request('PUT', default_path, self.body('v3'), HTTP_IF_MATCH=second['ETag'])
        self.assertEqual((second.status_code, third.status_code), (204, 204))
        self.assertEqual(len({etag1, second['ETag'], third['ETag']}), 3)
        default.refresh_from_db()
        self.assertEqual(default.version, 3)

        group_path = f'/caldav/{self.user.username}/{self.group.group_id}/version-resource.ics'
        moved = self.request('PUT', group_path, self.body('v4'), HTTP_IF_MATCH=third['ETag'])
        self.assertEqual(moved.status_code, 204)
        default.refresh_from_db()
        group_version = CalendarCollectionVersion.objects.get(
            user=self.user, collection_type='caldav', collection_id=self.group.group_id
        )
        self.assertEqual(default.version, 4)
        self.assertEqual(group_version.version, 1)
        self.assertEqual(default.changes.order_by('-token').first().action, CalendarChange.ACTION_DELETE)
        self.assertEqual(group_version.changes.get().action, CalendarChange.ACTION_CREATE)
        self.assertEqual(group_version.changes.get().etag, moved['ETag'])

    def test_reminder_ctag_and_capabilities_are_truthful(self):
        PlannerEntityCommandService.create_reminder(self.user, {
            'title': '版本提醒', 'trigger': '2026-07-13T12:00:00+08:00'
        })
        reminder_version = CalendarCollectionVersion.objects.get(
            user=self.user, collection_type='caldav', collection_id='reminders'
        )
        self.assertEqual(reminder_version.version, 1)

        collection_options = self.request('OPTIONS', f'/caldav/{self.user.username}/default/')
        self.assertEqual(collection_options.status_code, 200)
        self.assertNotIn('PUT', collection_options['Allow'])
        self.assertNotIn('DELETE', collection_options['Allow'])
        self.assertEqual(collection_options['DAV'], '1, calendar-access')
        reminder_options = self.request('OPTIONS', f'/caldav/{self.user.username}/reminders/x.ics')
        self.assertEqual(reminder_options['Allow'], 'OPTIONS, GET, HEAD')

