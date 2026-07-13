import base64
import hashlib

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from icalendar import Calendar
from rest_framework.authtoken.models import Token

from core.models import (
    CalendarChange, CalendarEvent, EventRecurrenceSeries, PlannerCohortAssignment,
    PlannerMigrationState, UserData,
)
from core.planner.commands import PlannerCommandService


@override_settings(PLANNER_STORAGE_MODE='normalized')
class P5CrossoverMatrixTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='p5-cross', password='secret-password')
        self.token = Token.objects.create(user=self.user)
        source = UserData.objects.create(user=self.user, key='events', value='[]')
        PlannerMigrationState.objects.create(
            user=self.user, source_key='events', source_row_id=source.id,
            source_checksum=hashlib.sha256(b'[]').hexdigest(), status='verified',
        )
        PlannerCohortAssignment.objects.create(
            user=self.user, storage_mode='normalized',
            entrypoints={
                'api_v2': {'mode': 'normalized'}, 'calendar_feed': {'mode': 'normalized'},
                'caldav_read': {'mode': 'normalized'}, 'caldav_write': {'mode': 'normalized'},
            },
        )
        encoded = base64.b64encode(f'{self.user.username}:{self.token.key}'.encode()).decode()
        self.basic = f'Basic {encoded}'

    def request(self, method, path, body=b'', auth=None, **headers):
        return self.client.generic(
            method, path, data=body, content_type=headers.pop('content_type', 'text/calendar'),
            HTTP_AUTHORIZATION=auth or self.basic, **headers,
        )

    def test_web_to_caldav_and_caldav_to_feed_share_one_fact_source(self):
        web_event = PlannerCommandService.create_event(self.user, {
            'title': 'Web 创建', 'start': '2026-07-13T09:00:00+08:00',
            'end': '2026-07-13T10:00:00+08:00',
        })
        web_get = self.request(
            'GET', f'/caldav/{self.user.username}/default/{web_event.caldav_resource_name}.ics'
        )
        self.assertEqual(web_get.status_code, 200)
        self.assertIn('Web 创建', web_get.content.decode())

        body = '''BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Cross//EN\r
BEGIN:VEVENT\r
UID:cross-caldav@example.test\r
DTSTART;TZID=Asia/Shanghai:20260714T100000\r
DTEND;TZID=Asia/Shanghai:20260714T110000\r
SUMMARY:CalDAV 创建\r
RRULE:FREQ=DAILY\r
END:VEVENT\r
END:VCALENDAR\r
'''.encode()
        created = self.request(
            'PUT', f'/caldav/{self.user.username}/default/cross-resource.ics', body,
            HTTP_IF_NONE_MATCH='*',
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(CalendarEvent.objects.filter(user=self.user, deleted_at__isnull=True).count(), 2)
        self.assertEqual(EventRecurrenceSeries.objects.filter(user=self.user, deleted_at__isnull=True).count(), 1)
        feed = self.client.get('/api/calendar/feed/', {'token': self.token.key, 'type': 'events'})
        self.assertEqual(feed.status_code, 200)
        parsed = Calendar.from_ical(feed.content)
        summaries = {str(item.get('SUMMARY')) for item in parsed.walk() if item.name == 'VEVENT'}
        self.assertEqual(summaries, {'Web 创建', 'CalDAV 创建'})
        recurring = next(item for item in parsed.walk() if item.name == 'VEVENT' and str(item.get('SUMMARY')) == 'CalDAV 创建')
        self.assertEqual(recurring.get('RRULE').to_ical(), b'FREQ=DAILY')

    def test_all_day_and_infinite_series_have_no_materialized_occurrences(self):
        all_day = '''BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:all-day@example.test\r
DTSTART;VALUE=DATE:20260713\r
DTEND;VALUE=DATE:20260714\r
SUMMARY:全天无限系列\r
RRULE:FREQ=MONTHLY;BYDAY=MO\r
END:VEVENT\r
END:VCALENDAR\r
'''.encode()
        response = self.request(
            'PUT', f'/caldav/{self.user.username}/default/all-day-resource.ics', all_day,
            HTTP_IF_NONE_MATCH='*',
        )
        self.assertEqual(response.status_code, 201)
        event = CalendarEvent.objects.get(user=self.user, deleted_at__isnull=True)
        self.assertTrue(event.is_all_day)
        self.assertEqual(event.start_date.isoformat(), '2026-07-13')
        self.assertEqual(CalendarEvent.objects.count(), 1)
        self.assertEqual(EventRecurrenceSeries.objects.count(), 1)
        for _ in range(100):
            self.assertEqual(self.request('GET', f'/caldav/{self.user.username}/default/all-day-resource.ics').status_code, 200)
        self.assertEqual(CalendarEvent.objects.count(), 1)
        self.assertEqual(EventRecurrenceSeries.objects.count(), 1)
        self.assertEqual(CalendarChange.objects.filter(collection__collection_type='caldav').count(), 1)

    def test_basic_password_token_and_bearer_auth_are_equivalent(self):
        event = PlannerCommandService.create_event(self.user, {
            'title': 'Auth', 'start': '2026-07-13T09:00:00+08:00',
            'end': '2026-07-13T10:00:00+08:00',
        })
        path = f'/caldav/{self.user.username}/default/{event.caldav_resource_name}.ics'
        password = base64.b64encode(f'{self.user.username}:secret-password'.encode()).decode()
        for auth in (f'Basic {password}', f'Token {self.token.key}', f'Bearer {self.token.key}'):
            with self.subTest(auth=auth.split()[0]):
                self.assertEqual(self.request('GET', path, auth=auth).status_code, 200)
