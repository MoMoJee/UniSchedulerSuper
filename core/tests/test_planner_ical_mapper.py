from datetime import date, datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from core.planner.ical import (
    ICalendarMappingError,
    IcalEventResource,
    IcalOverride,
    decode_event_resource,
    encode_event_resource,
    encode_feed_calendar,
)


class PlannerICalendarMapperTests(SimpleTestCase):
    def resource(self, **overrides):
        values = {
            "entity_id": "event-1",
            "ical_uid": "evt-event-1@unischeduler",
            "resource_name": "event-1",
            "title": "中文,分号;与换行\n测试",
            "description": "反斜线\\和换行\n内容",
            "location": "博文 402",
            "status": "confirmed",
            "start": datetime(2026, 7, 13, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
            "end": datetime(2026, 7, 13, 11, tzinfo=ZoneInfo("Asia/Shanghai")),
            "updated_at": datetime(2026, 7, 13, 1, tzinfo=timezone.utc),
            "version": 3,
        }
        values.update(overrides)
        return IcalEventResource(**values)

    def test_timed_event_round_trip_preserves_identity_text_time_and_status(self):
        encoded = encode_event_resource(self.resource(status="tentative"))
        parsed = decode_event_resource(encoded)
        self.assertEqual(parsed.uid, "evt-event-1@unischeduler")
        self.assertEqual(parsed.master.title, "中文,分号;与换行\n测试")
        self.assertEqual(parsed.master.description, "反斜线\\和换行\n内容")
        self.assertEqual(parsed.master.start.isoformat(), "2026-07-13T10:00:00+08:00")
        self.assertEqual(parsed.master.end.isoformat(), "2026-07-13T11:00:00+08:00")
        self.assertEqual(parsed.master.tzid, "Asia/Shanghai")
        self.assertEqual(parsed.master.status, "tentative")
        self.assertEqual(parsed.master.sequence, 3)

    def test_all_day_round_trip_preserves_date_type(self):
        parsed = decode_event_resource(encode_event_resource(self.resource(
            start=date(2026, 7, 13), end=date(2026, 7, 15), is_all_day=True,
        )))
        self.assertTrue(parsed.master.is_all_day)
        self.assertEqual(parsed.master.start, date(2026, 7, 13))
        self.assertEqual(parsed.master.end, date(2026, 7, 15))

    def test_rrule_rdate_exdate_and_sparse_overrides_round_trip(self):
        resource = self.resource(
            series_id="series-1",
            rrule="FREQ=WEEKLY;COUNT=5;BYDAY=MO,WE",
            rdates=(datetime(2026, 7, 17, 10, tzinfo=ZoneInfo("Asia/Shanghai")),),
            exdates=("20260715T100000",),
            overrides=(
                IcalOverride(
                    recurrence_id="20260720T100000",
                    patch={"title": "仅此修改"},
                    effective_start=datetime(2026, 7, 20, 12, tzinfo=ZoneInfo("Asia/Shanghai")),
                    effective_end=datetime(2026, 7, 20, 13, tzinfo=ZoneInfo("Asia/Shanghai")),
                    version=4,
                ),
                IcalOverride(recurrence_id="20260722T100000", kind="cancelled", version=5),
            ),
        )
        parsed = decode_event_resource(encode_event_resource(resource))
        self.assertIn("FREQ=WEEKLY", parsed.master.rrule)
        self.assertEqual(len(parsed.master.rdates), 1)
        self.assertEqual(len(parsed.master.exdates), 1)
        self.assertEqual(len(parsed.overrides), 2)
        self.assertEqual(parsed.overrides[0].recurrence_id.isoformat(), "2026-07-20T10:00:00+08:00")
        self.assertEqual(parsed.overrides[0].start.isoformat(), "2026-07-20T12:00:00+08:00")
        self.assertEqual(parsed.overrides[1].status, "cancelled")

    def test_duration_is_accepted_but_dtend_plus_duration_is_rejected(self):
        duration_only = b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:duration@example\r
SUMMARY:Duration\r
DTSTART;TZID=Asia/Shanghai:20260713T100000\r
DURATION:PT1H\r
END:VEVENT\r
END:VCALENDAR\r
"""
        parsed = decode_event_resource(duration_only)
        self.assertEqual((parsed.master.end - parsed.master.start).total_seconds(), 3600)
        invalid = duration_only.replace(b"DURATION:PT1H", b"DTEND;TZID=Asia/Shanghai:20260713T110000\r\nDURATION:PT1H")
        with self.assertRaisesRegex(ICalendarMappingError, "同时包含"):
            decode_event_resource(invalid)

    def test_multiple_uids_or_missing_master_are_rejected(self):
        payload = encode_event_resource(self.resource())
        second = payload.replace(b"UID:evt-event-1@unischeduler", b"UID:other@unischeduler", 1)
        combined = payload.replace(b"END:VCALENDAR", second.split(b"BEGIN:VEVENT", 1)[1].split(b"END:VCALENDAR", 1)[0] + b"END:VCALENDAR")
        with self.assertRaises(ICalendarMappingError):
            decode_event_resource(combined)

    def test_feed_contains_publish_metadata_timezone_and_alarm(self):
        reminder = self.resource(
            entity_id="rem-1", ical_uid="rem-rem-1@unischeduler", resource_name="rem-rem-1",
            title="[提醒] 喝水", alarm_description="提醒：喝水",
        )
        text = encode_feed_calendar(name="UniScheduler - test", reminders=(reminder,)).decode()
        self.assertIn("METHOD:PUBLISH", text)
        self.assertIn("X-WR-CALNAME:UniScheduler - test", text)
        self.assertIn("BEGIN:VTIMEZONE", text)
        self.assertIn("BEGIN:VALARM", text)

    def test_mapper_has_no_orm_dependency(self):
        with patch("django.db.backends.utils.CursorWrapper._execute", side_effect=AssertionError("unexpected DB access")):
            encode_event_resource(self.resource())
