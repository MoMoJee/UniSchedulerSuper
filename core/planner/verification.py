"""legacy 与 normalized Planner 旁路投影的只读一致性校验。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from django.contrib.auth.models import User

from core.models import (
    CalendarEvent,
    EventGroup,
    EventRecurrenceSeries,
    PlannerLegacyIdMap,
    PlannerMigrationState,
    Reminder,
    ReminderRecurrenceSeries,
    Todo,
)
from core.planner.legacy import LegacyPlannerDataError, LegacyPlannerRepository
from core.planner.migration import LIST_SOURCE_KEYS, SOURCE_KEYS, PlannerLegacyMigration
from core.planner.recurrence.codec import PlannerTimeCodec
from core.planner.recurrence.expander import RecurrenceExpander
from core.planner.repository import PlannerRepository


@dataclass(frozen=True)
class VerificationDifference:
    """单个可机读差异，不回显 legacy 完整正文。"""

    category: str
    code: str
    source_key: str
    legacy_id: str = ''
    series_id: str = ''
    detail: dict[str, Any] = field(default_factory=dict)


class PlannerMigrationVerifier:
    """逐用户检查 mapping、普通实体和 recurrence occurrence 集。"""

    def __init__(self, user: User, *, range_start: datetime, range_end: datetime):
        if range_start.tzinfo is None or range_end.tzinfo is None or range_start >= range_end:
            raise ValueError('校验窗口必须是递增的 aware datetime')
        self.user = user
        self.range_start = range_start
        self.range_end = range_end
        self.payloads = {}
        self.differences: list[VerificationDifference] = []

    def verify(self, *, recurrence_only: bool = False) -> dict[str, Any]:
        self._load_sources()
        self._verify_states()
        if not recurrence_only:
            self._verify_groups()
            self._verify_todos()
            self._verify_reminders()
            self._verify_single_events()
        self._verify_event_recurrences()
        self._verify_reminder_recurrences()
        return {
            'user_id': self.user.id,
            'username': self.user.username,
            'range': {'from': self.range_start.isoformat(), 'to': self.range_end.isoformat()},
            'difference_count': len(self.differences),
            'cohort_eligible': not self.differences,
            'differences': [
                {
                    'category': item.category,
                    'code': item.code,
                    'source_key': item.source_key,
                    'legacy_id': item.legacy_id,
                    'series_id': item.series_id,
                    'detail': item.detail,
                }
                for item in self.differences
            ],
        }

    def _load_sources(self) -> None:
        for key in SOURCE_KEYS:
            try:
                payload = LegacyPlannerRepository.read(self.user, key)
            except LegacyPlannerDataError as exc:
                self._diff('source', 'source_unreadable', key, detail={'error': str(exc)})
                continue
            if payload is None:
                continue
            expected = list if key in LIST_SOURCE_KEYS else dict
            if not isinstance(payload.value, expected):
                self._diff('source', 'source_type_invalid', key, detail={'actual': type(payload.value).__name__})
                continue
            self.payloads[key] = payload

    def _verify_states(self) -> None:
        for key, payload in self.payloads.items():
            state = PlannerMigrationState.objects.filter(user=self.user, source_key=key).first()
            if state is None:
                self._diff('state', 'migration_state_missing', key)
            elif state.source_checksum != payload.checksum:
                self._diff('state', 'source_checksum_changed', key, detail={'source_row_id': payload.source_row_id})

    def _verify_groups(self) -> None:
        for row in self._items('events_groups'):
            legacy_id = self._id(row)
            target = EventGroup.objects.filter(user=self.user, group_id=legacy_id).first()
            if target is None:
                self._diff('entity', 'normalized_target_missing', 'events_groups', legacy_id=legacy_id)
                continue
            self._field_equal('events_groups', legacy_id, 'name', row.get('name') or '', target.name)
            self._field_equal('events_groups', legacy_id, 'description', row.get('description') or '', target.description)
            self._field_equal('events_groups', legacy_id, 'color', row.get('color') or '#3498db', target.color)

    def _verify_todos(self) -> None:
        for row in self._items('todos'):
            legacy_id = self._id(row)
            target = Todo.objects.filter(user=self.user, todo_id=legacy_id).first()
            if target is None:
                self._diff('entity', 'normalized_target_missing', 'todos', legacy_id=legacy_id)
                continue
            self._field_equal('todos', legacy_id, 'title', row.get('title') or '', target.title)
            self._field_equal('todos', legacy_id, 'description', row.get('description') or '', target.description)
            self._field_equal('todos', legacy_id, 'status', row.get('status') or 'pending', target.status)
            expected_due = self._temporal(row.get('due_date'), allow_empty=True)
            actual_due = target.due_at or target.due_date
            self._temporal_equal('todos', legacy_id, 'due_date', expected_due, actual_due)

    def _verify_reminders(self) -> None:
        recurring = {id(row) for rows in self._recurring_groups(self._items('reminders')).values() for row in rows}
        for row in self._items('reminders'):
            if id(row) in recurring:
                continue
            legacy_id = self._id(row)
            target = Reminder.objects.filter(user=self.user, reminder_id=legacy_id).first()
            if target is None:
                self._diff('entity', 'normalized_target_missing', 'reminders', legacy_id=legacy_id)
                continue
            self._field_equal('reminders', legacy_id, 'title', row.get('title') or '', target.title)
            self._field_equal('reminders', legacy_id, 'content', row.get('content') or '', target.content)
            self._field_equal('reminders', legacy_id, 'status', row.get('status') or 'active', target.status)
            self._temporal_equal('reminders', legacy_id, 'trigger_time', self._temporal(row.get('trigger_time')), target.trigger_at or target.trigger_date)

    def _verify_single_events(self) -> None:
        recurring = {id(row) for rows in self._recurring_groups(self._items('events')).values() for row in rows}
        for row in self._items('events'):
            if id(row) in recurring:
                continue
            legacy_id = self._id(row)
            target = CalendarEvent.objects.filter(user=self.user, event_id=legacy_id).first()
            if target is None:
                self._diff('entity', 'normalized_target_missing', 'events', legacy_id=legacy_id)
                continue
            self._field_equal('events', legacy_id, 'title', row.get('title') or '', target.title)
            self._field_equal('events', legacy_id, 'description', row.get('description') or '', target.description)
            self._temporal_equal('events', legacy_id, 'start', self._temporal(row.get('start')), target.start_at or target.start_date)
            self._temporal_equal('events', legacy_id, 'end', self._temporal(row.get('end')), target.end_at or target.end_date)

    def _verify_event_recurrences(self) -> None:
        for series_id, rows in self._recurring_groups(self._items('events')).items():
            series = EventRecurrenceSeries.objects.filter(user=self.user, series_id=series_id).select_related('master_event').first()
            if series is None:
                self._diff('recurrence', 'normalized_series_missing', 'events', series_id=series_id)
                continue
            try:
                definition = PlannerRepository._to_recurrence_definition(series)
            except ValueError as exc:
                self._diff('recurrence', 'normalized_series_unreadable', 'events', series_id=series_id, detail={'error': str(exc)})
                continue
            for row in rows:
                legacy_id = self._id(row)
                mapping = PlannerLegacyIdMap.objects.filter(user=self.user, entity_type='event', legacy_id=legacy_id).first()
                if mapping is None:
                    self._diff('mapping', 'legacy_id_map_missing', 'events', legacy_id=legacy_id, series_id=series_id)
                    continue
                legacy_start = self._temporal(row.get('start'))
                legacy_end = self._temporal(row.get('end'))
                if not isinstance(legacy_start, datetime) or not isinstance(legacy_end, datetime):
                    self._diff('recurrence', 'legacy_occurrence_time_invalid', 'events', legacy_id=legacy_id, series_id=series_id)
                    continue
                occurrences = RecurrenceExpander.expand(
                    definition,
                    range_start=legacy_start - timedelta(days=2),
                    range_end=legacy_end + timedelta(days=2),
                    overrides=tuple(PlannerRepository._to_override(item) for item in series.overrides.all()),
                )
                recurrence_id = mapping.recurrence_id or PlannerTimeCodec.format_recurrence_id(legacy_start, tzid=series.tzid)
                matched = next((item for item in occurrences if item.ref.recurrence_id == recurrence_id), None)
                if matched is None:
                    self._diff('recurrence', 'occurrence_slot_missing', 'events', legacy_id=legacy_id, series_id=series_id, detail={'recurrence_id': recurrence_id})
                    continue
                self._temporal_equal('events', legacy_id, 'start', legacy_start, matched.start, series_id=series_id)
                self._temporal_equal('events', legacy_id, 'end', legacy_end, matched.end, series_id=series_id)
                self._field_equal('events', legacy_id, 'title', row.get('title') or '', matched.payload.get('title', ''), series_id=series_id)

    def _verify_reminder_recurrences(self) -> None:
        for series_id, rows in self._recurring_groups(self._items('reminders')).items():
            series = ReminderRecurrenceSeries.objects.filter(user=self.user, series_id=series_id).select_related('master_reminder').first()
            if series is None:
                self._diff('recurrence', 'normalized_series_missing', 'reminders', series_id=series_id)
                continue
            # reminder 没有独立 ORM repository，构造等价的 definition。
            master = series.master_reminder
            dtstart = series.dtstart_at or series.dtstart_date
            if not isinstance(dtstart, datetime):
                self._diff('recurrence', 'normalized_series_unreadable', 'reminders', series_id=series_id)
                continue
            from core.planner.recurrence.expander import RecurrenceDefinition

            definition = RecurrenceDefinition(
                entity_type='reminder',
                entity_id=master.reminder_id,
                series_id=series.series_id,
                dtstart=dtstart,
                duration=timedelta(seconds=1),
                rrule=series.rrule_canonical or series.rrule,
                tzid=series.tzid,
                source_version=max(master.version, series.version),
                payload={'title': master.title, 'content': master.content, 'status': master.status},
                exdates=frozenset(item.recurrence_id for item in series.exdates.all()),
            )
            for row in rows:
                legacy_id = self._id(row)
                mapping = PlannerLegacyIdMap.objects.filter(user=self.user, entity_type='reminder', legacy_id=legacy_id).first()
                legacy_time = self._temporal(row.get('trigger_time'))
                if mapping is None or not isinstance(legacy_time, datetime):
                    self._diff('mapping', 'legacy_id_map_missing', 'reminders', legacy_id=legacy_id, series_id=series_id)
                    continue
                occurrences = RecurrenceExpander.expand(
                    definition,
                    range_start=legacy_time - timedelta(days=2),
                    range_end=legacy_time + timedelta(days=2),
                )
                recurrence_id = mapping.recurrence_id or PlannerTimeCodec.format_recurrence_id(legacy_time, tzid=series.tzid)
                matched = next((item for item in occurrences if item.ref.recurrence_id == recurrence_id), None)
                if matched is None:
                    self._diff('recurrence', 'occurrence_slot_missing', 'reminders', legacy_id=legacy_id, series_id=series_id)
                    continue
                self._temporal_equal('reminders', legacy_id, 'trigger_time', legacy_time, matched.start, series_id=series_id)
                self._field_equal('reminders', legacy_id, 'title', row.get('title') or '', matched.payload.get('title', ''), series_id=series_id)

    def _items(self, key: str) -> list[dict[str, Any]]:
        payload = self.payloads.get(key)
        if payload is None:
            return []
        return [item for item in payload.value if isinstance(item, dict)]

    @staticmethod
    def _recurring_groups(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        return PlannerLegacyMigration._recurring_groups(rows)

    @staticmethod
    def _id(row: dict[str, Any]) -> str:
        return str(row.get('id') or '').strip()

    @staticmethod
    def _temporal(value: Any, *, allow_empty: bool = False) -> date | datetime | None:
        if value in (None, ''):
            return None if allow_empty else None
        parsed = PlannerTimeCodec.parse_value(value)
        return PlannerTimeCodec.to_utc(parsed) if isinstance(parsed, datetime) else parsed

    def _field_equal(self, source_key: str, legacy_id: str, field: str, expected: Any, actual: Any, *, series_id: str = '') -> None:
        if expected != actual:
            self._diff('field', 'field_mismatch', source_key, legacy_id=legacy_id, series_id=series_id, detail={'field': field})

    def _temporal_equal(self, source_key: str, legacy_id: str, field: str, expected: date | datetime | None, actual: date | datetime | None, *, series_id: str = '') -> None:
        if expected != actual:
            self._diff('field', 'temporal_mismatch', source_key, legacy_id=legacy_id, series_id=series_id, detail={'field': field})

    def _diff(self, category: str, code: str, source_key: str, *, legacy_id: str = '', series_id: str = '', detail: dict[str, Any] | None = None) -> None:
        item = VerificationDifference(category, code, source_key, legacy_id, series_id, detail or {})
        if item not in self.differences:
            self.differences.append(item)
