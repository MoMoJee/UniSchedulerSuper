import base64
import hashlib

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token

from core.models import (
    CalendarEvent, EventGroup, EventRecurrenceSeries, PlannerCohortAssignment,
    PlannerMigrationState, Reminder, Todo, UserData,
)
from core.planner.commands import PlannerCommandService
from core.planner.entities import PlannerEntityCommandService


def _basic(username, password):
    return 'Basic ' + base64.b64encode(f'{username}:{password}'.encode()).decode()


@override_settings(PLANNER_STORAGE_MODE='normalized')
class CalDAVNormalizedReadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='caldav-v2', password='password')
        self.token = Token.objects.create(user=self.user)
        self.auth = _basic(self.user.username, self.token.key)
        source = UserData.objects.create(
            user=self.user, key='events', value='[{"id":"legacy-event","title":"LEGACY-NOT-VISIBLE"}]'
        )
        PlannerMigrationState.objects.create(
            user=self.user, source_key='events', source_row_id=source.id,
            source_checksum=hashlib.sha256(source.value.encode()).hexdigest(),
            status=PlannerMigrationState.STATUS_VERIFIED,
        )
        PlannerCohortAssignment.objects.create(
            user=self.user, storage_mode=PlannerCohortAssignment.MODE_NORMALIZED,
            entrypoints={'caldav_read': {'mode': 'normalized'}},
        )
        self.group = EventGroup.objects.create(user=self.user, name='课程组', color='#102030')
        self.default_event = PlannerCommandService.create_event(self.user, {
            'title': '默认事件', 'start': '2026-07-13T10:00:00+08:00',
            'end': '2026-07-13T11:00:00+08:00',
        })
        self.recurring = PlannerCommandService.create_event(self.user, {
            'title': '跨窗口重复事件', 'group_id': self.group.group_id,
            'start': '2026-07-01T09:00:00+08:00', 'end': '2026-07-01T10:00:00+08:00',
            'recurrence': {'rrule': 'FREQ=WEEKLY;COUNT=4'},
        })
        self.reminder = PlannerEntityCommandService.create_reminder(self.user, {
            'title': '重复提醒', 'trigger': '2026-07-08T12:00:00+08:00',
            'recurrence': {'rrule': 'FREQ=DAILY;COUNT=2'},
        })

    def request(self, method, path, body=b'', **headers):
        return self.client.generic(
            method, path, data=body,
            content_type=headers.pop('content_type', 'application/xml; charset=utf-8'),
            HTTP_AUTHORIZATION=self.auth, **headers,
        )

    def test_home_collection_get_and_identity_are_normalized(self):
        home = self.request('PROPFIND', f'/caldav/{self.user.username}/', HTTP_DEPTH='1')
        self.assertEqual(home.status_code, 207)
        text = home.content.decode()
        self.assertIn('/default/', text)
        self.assertIn(f'/{self.group.group_id}/', text)
        self.assertIn('/reminders/', text)
        self.assertNotIn('LEGACY-NOT-VISIBLE', text)
        self.assertNotIn('sync-collection', text)

        default = self.request('PROPFIND', f'/caldav/{self.user.username}/default/', HTTP_DEPTH='1')
        self.assertEqual(default.status_code, 207)
        self.assertIn(f'{self.default_event.caldav_resource_name}.ics', default.content.decode())
        self.assertNotIn(self.recurring.recurrence_series.caldav_resource_name, default.content.decode())

        group = self.request('PROPFIND', f'/caldav/{self.user.username}/{self.group.group_id}/', HTTP_DEPTH='1')
        self.assertEqual(group.status_code, 207)
        resource_name = self.recurring.recurrence_series.caldav_resource_name
        self.assertIn(f'{resource_name}.ics', group.content.decode())
        resource = self.request('GET', f'/caldav/{self.user.username}/{self.group.group_id}/{resource_name}.ics')
        self.assertEqual(resource.status_code, 200)
        self.assertIn('RRULE:FREQ=WEEKLY;COUNT=4', resource.content.decode())
        self.assertTrue(resource['ETag'].startswith('"'))
        self.assertEqual(
            self.request('GET', f'/caldav/{self.user.username}/{self.group.group_id}/{resource_name}.ics')['ETag'],
            resource['ETag'],
        )

    def test_multiget_query_uses_canonical_resources_and_recurrence_expander(self):
        resource_name = self.recurring.recurrence_series.caldav_resource_name
        existing_href = f'/caldav/{self.user.username}/{self.group.group_id}/{resource_name}.ics'
        missing_href = f'/caldav/{self.user.username}/{self.group.group_id}/missing.ics'
        body = f'''<C:calendar-multiget xmlns:C="urn:ietf:params:xml:ns:caldav" xmlns:D="DAV:">
          <D:href>{existing_href}</D:href><D:href>{missing_href}</D:href>
        </C:calendar-multiget>'''.encode()
        response = self.request('REPORT', f'/caldav/{self.user.username}/{self.group.group_id}/', body)
        self.assertEqual(response.status_code, 207)
        self.assertIn('跨窗口重复事件', response.content.decode())
        self.assertIn('404 Not Found', response.content.decode())

        query = b'''<C:calendar-query xmlns:C="urn:ietf:params:xml:ns:caldav">
          <C:filter><C:comp-filter name="VCALENDAR"><C:comp-filter name="VEVENT">
          <C:time-range start="20260708T000000Z" end="20260709T000000Z"/>
          </C:comp-filter></C:comp-filter></C:filter></C:calendar-query>'''
        response = self.request('REPORT', f'/caldav/{self.user.username}/{self.group.group_id}/', query)
        self.assertEqual(response.status_code, 207)
        self.assertIn('跨窗口重复事件', response.content.decode())

    def test_reminder_read_unknown_collection_and_protocol_errors(self):
        reminder_resource = f'rem-series-{self.reminder.recurrence_series.series_id}'
        response = self.request('GET', f'/caldav/{self.user.username}/reminders/{reminder_resource}.ics')
        self.assertEqual(response.status_code, 200)
        self.assertIn('RRULE:FREQ=DAILY;COUNT=2', response.content.decode())
        self.assertIn('VALARM', response.content.decode())
        self.assertEqual(
            self.request('PROPFIND', f'/caldav/{self.user.username}/unknown/', HTTP_DEPTH='0').status_code,
            404,
        )
        self.assertEqual(
            self.request('PROPFIND', f'/caldav/{self.user.username}/default/', HTTP_DEPTH='infinity').status_code,
            403,
        )
        self.assertEqual(
            self.request('REPORT', f'/caldav/{self.user.username}/default/', b'<broken').status_code,
            400,
        )
        unsupported = b'<D:sync-collection xmlns:D="DAV:"/>'
        self.assertEqual(
            self.request('REPORT', f'/caldav/{self.user.username}/default/', unsupported).status_code,
            501,
        )

    def test_all_read_methods_are_side_effect_free(self):
        models = [CalendarEvent, EventRecurrenceSeries, Todo, Reminder, UserData]
        before = [model.objects.count() for model in models]
        before_versions = list(CalendarEvent.objects.order_by('id').values_list('id', 'version', 'updated_at'))
        resource_name = self.default_event.caldav_resource_name
        for _ in range(2):
            self.request('PROPFIND', f'/caldav/{self.user.username}/', HTTP_DEPTH='1')
            self.request('PROPFIND', f'/caldav/{self.user.username}/default/', HTTP_DEPTH='1')
            self.request('GET', f'/caldav/{self.user.username}/default/{resource_name}.ics')
        self.assertEqual([model.objects.count() for model in models], before)
        self.assertEqual(
            list(CalendarEvent.objects.order_by('id').values_list('id', 'version', 'updated_at')),
            before_versions,
        )

