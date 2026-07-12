"""纯 recurrence 展开器的表驱动契约测试。"""

import unittest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from core.planner.recurrence.expander import (
    OccurrenceOverride,
    RecurrenceDefinition,
    RecurrenceExpander,
)
from core.planner.recurrence.codec import PlannerTimeError


SHANGHAI = ZoneInfo('Asia/Shanghai')


def at(day: int, hour: int = 9) -> datetime:
    """构造固定的上海时区测试时间。"""
    return datetime(2026, 3, day, hour, tzinfo=SHANGHAI)


class RecurrenceExpanderTests(unittest.TestCase):
    """确认窗口展开不会物化实例，并保留 sparse 例外语义。"""

    def setUp(self):
        self.definition = RecurrenceDefinition(
            entity_type='event',
            entity_id='event-1',
            series_id='series-1',
            dtstart=at(1),
            duration=timedelta(hours=1),
            rrule='FREQ=DAILY;COUNT=4',
            payload={'title': '晨会'},
            source_version=3,
        )

    def test_daily_series_is_expanded_only_for_the_requested_window(self):
        occurrences = RecurrenceExpander.expand(
            self.definition,
            range_start=at(2),
            range_end=at(4),
        )

        self.assertEqual([item.ref.recurrence_id for item in occurrences], ['20260302T090000', '20260303T090000'])
        self.assertEqual([item.start for item in occurrences], [at(2), at(3)])
        self.assertTrue(all(item.ref.source_version == 3 for item in occurrences))

    def test_rdate_exdate_and_override_are_merged_without_duplicate_occurrences(self):
        definition = RecurrenceDefinition(
            **{
                **self.definition.__dict__,
                'rdates': (at(5),),
                'exdates': frozenset({'20260303T090000'}),
            }
        )
        override = OccurrenceOverride(
            recurrence_id='20260302T090000',
            kind='modified',
            effective_start=at(2, 11),
            effective_end=at(2, 12),
            patch={'title': '改期晨会'},
            version=5,
        )

        occurrences = RecurrenceExpander.expand(
            definition,
            range_start=at(1),
            range_end=at(6),
            overrides=(override,),
        )

        self.assertEqual([item.ref.recurrence_id for item in occurrences], ['20260301T090000', '20260302T090000', '20260304T090000', '20260305T090000'])
        self.assertEqual(occurrences[1].start, at(2, 11))
        self.assertEqual(occurrences[1].payload['title'], '改期晨会')
        self.assertEqual(occurrences[1].ref.source_version, 5)

    def test_cancelled_occurrence_never_reappears_on_later_reads(self):
        cancelled = OccurrenceOverride(recurrence_id='20260302T090000', kind='cancelled')
        first = RecurrenceExpander.expand(
            self.definition,
            range_start=at(1),
            range_end=at(5),
            overrides=(cancelled,),
        )
        second = RecurrenceExpander.expand(
            self.definition,
            range_start=at(1),
            range_end=at(5),
            overrides=(cancelled,),
        )

        self.assertEqual([item.ref.recurrence_id for item in first], ['20260301T090000', '20260303T090000', '20260304T090000'])
        self.assertEqual(first, second)

    def test_cross_window_event_is_returned_even_when_its_start_is_before_the_window(self):
        definition = RecurrenceDefinition(
            entity_type='event',
            entity_id='event-cross-window',
            series_id='series-cross-window',
            dtstart=at(1, 9),
            duration=timedelta(hours=3),
            rrule='FREQ=DAILY;COUNT=1',
        )

        occurrences = RecurrenceExpander.expand(
            definition,
            range_start=at(1, 10),
            range_end=at(1, 11),
        )

        self.assertEqual(len(occurrences), 1)
        self.assertEqual(occurrences[0].start, at(1, 9))

    def test_all_day_date_recurrence_keeps_date_recurrence_ids(self):
        definition = RecurrenceDefinition(
            entity_type='event',
            entity_id='event-all-day',
            series_id='series-all-day',
            dtstart=date(2026, 3, 1),
            duration=timedelta(days=1),
            rrule='FREQ=DAILY;COUNT=2',
        )

        occurrences = RecurrenceExpander.expand(
            definition,
            range_start=at(1),
            range_end=at(4),
        )

        self.assertEqual([item.ref.recurrence_id for item in occurrences], ['20260301', '20260302'])
        self.assertEqual([item.start for item in occurrences], [date(2026, 3, 1), date(2026, 3, 2)])

    def test_dst_occurrences_keep_the_original_wall_clock_hour(self):
        new_york = ZoneInfo('America/New_York')
        definition = RecurrenceDefinition(
            entity_type='event',
            entity_id='event-dst',
            series_id='series-dst',
            dtstart=datetime(2026, 3, 7, 9, tzinfo=new_york),
            duration=timedelta(hours=1),
            rrule='FREQ=DAILY;COUNT=3',
            tzid='America/New_York',
        )

        occurrences = RecurrenceExpander.expand(
            definition,
            range_start=datetime(2026, 3, 7, 0, tzinfo=new_york),
            range_end=datetime(2026, 3, 10, 0, tzinfo=new_york),
        )

        self.assertEqual([item.start.hour for item in occurrences], [9, 9, 9])
        self.assertEqual([item.start.utcoffset().total_seconds() for item in occurrences], [-5 * 3600, -4 * 3600, -4 * 3600])

    def test_monthly_yearly_and_complex_by_rules_expand_expected_slots(self):
        monthly = RecurrenceDefinition(
            entity_type='event', entity_id='monthly', series_id='monthly',
            dtstart=date(2026, 1, 31), duration=timedelta(days=1),
            rrule='FREQ=MONTHLY;COUNT=3;BYMONTHDAY=-1',
        )
        yearly = RecurrenceDefinition(
            entity_type='event', entity_id='yearly', series_id='yearly',
            dtstart=date(2026, 1, 1), duration=timedelta(days=1),
            rrule='FREQ=YEARLY;COUNT=2;BYMONTH=3;BYDAY=1MO',
        )

        monthly_result = RecurrenceExpander.expand(
            monthly,
            range_start=datetime(2026, 1, 1, tzinfo=SHANGHAI),
            range_end=datetime(2027, 1, 1, tzinfo=SHANGHAI),
        )
        yearly_result = RecurrenceExpander.expand(
            yearly,
            range_start=at(1).replace(month=1),
            range_end=at(1).replace(year=2028, month=1),
        )

        self.assertEqual([item.start for item in monthly_result], [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)])
        self.assertEqual([item.start for item in yearly_result], [date(2026, 3, 2), date(2027, 3, 1)])

    def test_rdate_exdate_and_override_types_must_match_dtstart(self):
        with self.assertRaises(PlannerTimeError):
            RecurrenceExpander.expand(
                RecurrenceDefinition(
                    **{**self.definition.__dict__, 'rdates': (date(2026, 3, 5),)}
                ),
                range_start=at(1),
                range_end=at(6),
            )
        with self.assertRaises(PlannerTimeError):
            RecurrenceExpander.expand(
                RecurrenceDefinition(
                    **{**self.definition.__dict__, 'exdates': frozenset({'20260302'})}
                ),
                range_start=at(1),
                range_end=at(6),
            )

    def test_ten_thousand_slot_rule_only_returns_requested_window(self):
        large = RecurrenceDefinition(
            entity_type='event', entity_id='large', series_id='large',
            dtstart=date(2000, 1, 1), duration=timedelta(days=1),
            rrule='FREQ=DAILY;COUNT=10000',
        )

        occurrences = RecurrenceExpander.expand(
            large,
            range_start=datetime(2027, 5, 1, tzinfo=SHANGHAI),
            range_end=datetime(2027, 5, 4, tzinfo=SHANGHAI),
        )

        self.assertEqual([item.start for item in occurrences], [date(2027, 5, 1), date(2027, 5, 2), date(2027, 5, 3)])
