import base64
import hashlib

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token

from core.models import (
    CalendarEvent, EventGroup, EventOccurrenceOverride, EventRecurrenceExDate,
    EventRecurrenceRDate, EventRecurrenceSeries, PlannerCohortAssignment,
    PlannerMigrationState, PlannerRollbackSnapshot, UserData,
)


def _auth(username, token):
    return 'Basic ' + base64.b64encode(f'{username}:{token}'.encode()).decode()


def _ics(uid, *, summary='CalDAV 事件', start='20260713T100000', end='20260713T110000', extra=''):
    return f'''BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//P5 Test//EN\r
BEGIN:VEVENT\r
UID:{uid}\r
DTSTART;TZID=Asia/Shanghai:{start}\r
DTEND;TZID=Asia/Shanghai:{end}\r
SUMMARY:{summary}\r
DESCRIPTION:正文\r
LOCATION:房间\r
{extra}END:VEVENT\r
END:VCALENDAR\r
'''.encode()


@override_settings(PLANNER_STORAGE_MODE='normalized')
class CalDAVNormalizedWriteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='caldav-write', password='password')
        token = Token.objects.create(user=self.user)
        self.auth = _auth(self.user.username, token.key)
        self.source = UserData.objects.create(user=self.user, key='events', value='[]')
        PlannerMigrationState.objects.create(
            user=self.user, source_key='events', source_row_id=self.source.id,
            source_checksum=hashlib.sha256(b'[]').hexdigest(), status=PlannerMigrationState.STATUS_VERIFIED,
        )
        PlannerCohortAssignment.objects.create(
            user=self.user, storage_mode=PlannerCohortAssignment.MODE_NORMALIZED,
            entrypoints={
                'caldav_read': {'mode': 'normalized'},
                'caldav_write': {'mode': 'normalized'},
            },
        )
        self.group = EventGroup.objects.create(user=self.user, name='目标组')

    def request(self, method, path, body=b'', **headers):
        return self.client.generic(
            method, path, data=body,
            content_type=headers.pop('content_type', 'text/calendar; charset=utf-8'),
            HTTP_AUTHORIZATION=self.auth, **headers,
        )

    def test_create_preconditions_update_group_move_and_delete(self):
        path = f'/caldav/{self.user.username}/default/client-resource.ics'
        response = self.request('PUT', path, _ics('client-uid@example.test'), HTTP_IF_NONE_MATCH='*')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response['Location'], path)
        event = CalendarEvent.objects.get(user=self.user, deleted_at__isnull=True)
        self.assertEqual(event.ical_uid, 'client-uid@example.test')
        self.assertEqual(event.caldav_resource_name, 'client-resource')
        first_etag = response['ETag']
        self.assertEqual(UserData.objects.get(pk=self.source.pk).value, '[]')
        self.assertEqual(PlannerRollbackSnapshot.objects.count(), 0)

        repeated = self.request('PUT', path, _ics('client-uid@example.test'), HTTP_IF_NONE_MATCH='*')
        self.assertEqual(repeated.status_code, 412)
        event.refresh_from_db()
        version_before = event.version
        stale = self.request('PUT', path, _ics('client-uid@example.test', summary='不应写入'), HTTP_IF_MATCH='"stale"')
        self.assertEqual(stale.status_code, 412)
        event.refresh_from_db()
        self.assertEqual(event.version, version_before)

        moved_path = f'/caldav/{self.user.username}/{self.group.group_id}/client-resource.ics'
        updated = self.request(
            'PUT', moved_path,
            _ics('client-uid@example.test', summary='移动后标题', start='20260713T120000', end='20260713T130000'),
            HTTP_IF_MATCH=first_etag,
        )
        self.assertEqual(updated.status_code, 204)
        self.assertEqual(updated['Location'], moved_path)
        event.refresh_from_db()
        self.assertEqual(event.group, self.group)
        self.assertEqual(event.title, '移动后标题')
        self.assertNotEqual(updated['ETag'], first_etag)
        self.assertEqual(self.request('GET', path).status_code, 404)
        self.assertEqual(self.request('GET', moved_path).status_code, 200)

        identity_change = self.request('PUT', moved_path, _ics('changed@example.test'), HTTP_IF_MATCH=updated['ETag'])
        self.assertEqual(identity_change.status_code, 409)
        self.assertEqual(self.request('DELETE', moved_path, HTTP_IF_MATCH='"stale"').status_code, 412)
        self.assertEqual(self.request('DELETE', moved_path, HTTP_IF_MATCH=updated['ETag']).status_code, 204)
        event.refresh_from_db()
        self.assertIsNotNone(event.deleted_at)
        self.assertEqual(self.request('GET', moved_path).status_code, 404)

    def test_recurrence_rdate_exdate_and_sparse_overrides_are_one_atomic_resource(self):
        uid = 'series-client@example.test'
        body = f'''BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//P5 Test//EN\r
BEGIN:VEVENT\r
UID:{uid}\r
DTSTART;TZID=Asia/Shanghai:20260713T100000\r
DTEND;TZID=Asia/Shanghai:20260713T110000\r
SUMMARY:重复系列\r
RRULE:FREQ=DAILY;COUNT=5\r
RDATE;TZID=Asia/Shanghai:20260720T100000\r
EXDATE;TZID=Asia/Shanghai:20260715T100000\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:{uid}\r
RECURRENCE-ID;TZID=Asia/Shanghai:20260714T100000\r
DTSTART;TZID=Asia/Shanghai:20260714T120000\r
DTEND;TZID=Asia/Shanghai:20260714T130000\r
SUMMARY:修改实例\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:{uid}\r
RECURRENCE-ID;TZID=Asia/Shanghai:20260716T100000\r
DTSTART;TZID=Asia/Shanghai:20260716T100000\r
DTEND;TZID=Asia/Shanghai:20260716T110000\r
SUMMARY:重复系列\r
STATUS:CANCELLED\r
END:VEVENT\r
END:VCALENDAR\r
'''.encode()
        path = f'/caldav/{self.user.username}/default/series-resource.ics'
        response = self.request('PUT', path, body, HTTP_IF_NONE_MATCH='*')
        self.assertEqual(response.status_code, 201)
        series = EventRecurrenceSeries.objects.get(user=self.user, deleted_at__isnull=True)
        self.assertEqual(series.ical_uid, uid)
        self.assertEqual(series.caldav_resource_name, 'series-resource')
        self.assertEqual(EventRecurrenceRDate.objects.filter(series=series).count(), 1)
        self.assertEqual(EventRecurrenceExDate.objects.filter(series=series).count(), 1)
        self.assertEqual(EventOccurrenceOverride.objects.filter(series=series).count(), 2)
        returned = self.request('GET', path)
        text = returned.content.decode()
        self.assertIn('RECURRENCE-ID', text)
        self.assertIn('STATUS:CANCELLED', text)
        self.assertIn('RDATE', text)
        self.assertIn('EXDATE', text)

    def test_this_and_future_component_uses_v2_series_split(self):
        uid = 'future-split@example.test'
        path = f'/caldav/{self.user.username}/default/future-resource.ics'
        created = self.request(
            'PUT', path,
            _ics(uid, summary='原系列', extra='RRULE:FREQ=DAILY;COUNT=5\r\n'),
            HTTP_IF_NONE_MATCH='*',
        )
        self.assertEqual(created.status_code, 201)
        update = f'''BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//P5 Test//EN\r
BEGIN:VEVENT\r
UID:{uid}\r
DTSTART;TZID=Asia/Shanghai:20260713T100000\r
DTEND;TZID=Asia/Shanghai:20260713T110000\r
SUMMARY:原系列\r
RRULE:FREQ=DAILY;COUNT=5\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:{uid}\r
RECURRENCE-ID;RANGE=THISANDFUTURE;TZID=Asia/Shanghai:20260715T100000\r
DTSTART;TZID=Asia/Shanghai:20260715T120000\r
DTEND;TZID=Asia/Shanghai:20260715T130000\r
SUMMARY:未来改时\r
END:VEVENT\r
END:VCALENDAR\r
'''.encode()
        response = self.request('PUT', path, update, HTTP_IF_MATCH=created['ETag'])
        self.assertEqual(response.status_code, 204)
        active_events = CalendarEvent.objects.filter(user=self.user, deleted_at__isnull=True)
        active_series = EventRecurrenceSeries.objects.filter(user=self.user, deleted_at__isnull=True)
        self.assertEqual(active_events.count(), 2)
        self.assertEqual(active_series.count(), 2)
        child = active_series.exclude(caldav_resource_name='future-resource').select_related('master_event').get()
        self.assertEqual(child.master_event.title, '未来改时')
        self.assertEqual(child.parent_series.caldav_resource_name, 'future-resource')
        self.assertEqual(child.split_recurrence_id, '20260715T100000')
        self.assertEqual(EventOccurrenceOverride.objects.count(), 0)

    def test_invalid_resource_is_fully_rolled_back_and_readonly_is_zero_write(self):
        before = (CalendarEvent.objects.count(), EventRecurrenceSeries.objects.count())
        invalid = _ics(
            'range@example.test', extra=(
                'RRULE:FREQ=DAILY;COUNT=3\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\n'
                'UID:range@example.test\r\n'
                'RECURRENCE-ID;RANGE=THISANDFUTURE;TZID=Asia/Shanghai:20260714T100000\r\n'
                'DTSTART;TZID=Asia/Shanghai:20260714T120000\r\n'
                'DTEND;TZID=Asia/Shanghai:20260714T130000\r\nSUMMARY:future\r\n'
            ),
        )
        response = self.request(
            'PUT', f'/caldav/{self.user.username}/default/range-resource.ics', invalid,
            HTTP_IF_NONE_MATCH='*',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual((CalendarEvent.objects.count(), EventRecurrenceSeries.objects.count()), before)

        reminder_path = f'/caldav/{self.user.username}/reminders/nope.ics'
        self.assertEqual(self.request('PUT', reminder_path, _ics('readonly@example.test')).status_code, 403)
        self.assertEqual(self.request('DELETE', reminder_path).status_code, 403)
        self.assertEqual((CalendarEvent.objects.count(), EventRecurrenceSeries.objects.count()), before)
        oversized = b'x' * (512 * 1024 + 1)
        self.assertEqual(
            self.request('PUT', f'/caldav/{self.user.username}/default/large.ics', oversized).status_code,
            413,
        )
