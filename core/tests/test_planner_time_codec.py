"""PlannerTimeCodec 的契约测试。"""

import unittest
from datetime import date, datetime, timezone

from core.planner.recurrence.codec import (
    InvalidRRuleError,
    PlannerTimeCodec,
    PlannerTimeError,
    canonicalize_rrule,
)


class PlannerTimeCodecTests(unittest.TestCase):
    """验证 DATE、TZID、UTC 和 RRULE 的边界语义。"""

    def test_naive_iso_is_interpreted_in_requested_timezone(self):
        value = PlannerTimeCodec.parse_value('2026-03-20T09:30', tzid='Asia/Shanghai')

        self.assertEqual(value.utcoffset().total_seconds(), 8 * 3600)
        self.assertEqual(PlannerTimeCodec.to_utc(value), datetime(2026, 3, 20, 1, 30, tzinfo=timezone.utc))

    def test_utc_and_date_values_preserve_their_types(self):
        utc_value = PlannerTimeCodec.parse_value('20260320T013000Z')
        date_value = PlannerTimeCodec.parse_value('20260320')

        self.assertEqual(utc_value, datetime(2026, 3, 20, 1, 30, tzinfo=timezone.utc))
        self.assertEqual(date_value, date(2026, 3, 20))
        self.assertEqual(PlannerTimeCodec.format_recurrence_id(date_value), '20260320')

    def test_dst_wall_clock_time_is_not_converted_before_recurrence_calculation(self):
        value = PlannerTimeCodec.parse_value('2026-03-08T09:00', tzid='America/New_York')

        self.assertEqual(value.hour, 9)
        self.assertEqual(value.utcoffset().total_seconds(), -4 * 3600)

    def test_invalid_timezone_and_time_are_explicit_errors(self):
        with self.assertRaises(PlannerTimeError):
            PlannerTimeCodec.parse_value('2026-03-20T09:00', tzid='Invalid/Timezone')
        with self.assertRaises(PlannerTimeError):
            PlannerTimeCodec.parse_value('not-a-time')

    def test_rrule_is_canonicalized_and_rejects_private_extensions(self):
        canonical = canonicalize_rrule(
            'freq=weekly;byday=we,mo,mo;interval=02',
            dtstart=datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(canonical, 'BYDAY=MO,WE;FREQ=WEEKLY;INTERVAL=2')
        with self.assertRaises(InvalidRRuleError):
            canonicalize_rrule('FREQ=YEARLY;BYEASTER=1', dtstart=date(2026, 1, 1))
        with self.assertRaises(InvalidRRuleError):
            canonicalize_rrule('FREQ=DAILY;COUNT=2;UNTIL=20260320', dtstart=date(2026, 3, 1))

    def test_timed_until_is_normalized_to_utc_and_all_day_until_stays_date(self):
        timed = canonicalize_rrule(
            'FREQ=DAILY;UNTIL=20260320T090000',
            dtstart=datetime(2026, 3, 1, 9, tzinfo=PlannerTimeCodec.get_timezone('Asia/Shanghai')),
            tzid='Asia/Shanghai',
        )
        all_day = canonicalize_rrule('FREQ=DAILY;UNTIL=20260320', dtstart=date(2026, 3, 1))

        self.assertEqual(timed, 'FREQ=DAILY;UNTIL=20260320T010000Z')
        self.assertEqual(all_day, 'FREQ=DAILY;UNTIL=20260320')
