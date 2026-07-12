"""无副作用的 recurrence 窗口展开器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping

from dateutil.rrule import rruleset, rrulestr

from .codec import PlannerTimeCodec, PlannerTimeError, canonicalize_rrule


@dataclass(frozen=True)
class OccurrenceRef:
    """虚拟 occurrence 的稳定复合引用。"""

    entity_type: str
    entity_id: str
    series_id: str
    recurrence_id: str
    occurrence_start: datetime | date
    source_version: int


@dataclass(frozen=True)
class OccurrenceOverride:
    """展开器所需的稀疏 override 投影。"""

    recurrence_id: str
    kind: str
    patch: Mapping[str, Any] = field(default_factory=dict)
    effective_start: datetime | date | None = None
    effective_end: datetime | date | None = None
    version: int | None = None


@dataclass(frozen=True)
class RecurrenceDefinition:
    """展开器的输入，不依赖 Django ORM 或当前时间。"""

    entity_type: str
    entity_id: str
    series_id: str
    dtstart: datetime | date
    duration: timedelta
    rrule: str
    tzid: str = PlannerTimeCodec.DEFAULT_TZID
    source_version: int = 1
    payload: Mapping[str, Any] = field(default_factory=dict)
    rdates: tuple[datetime | date, ...] = ()
    exdates: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Occurrence:
    """按窗口计算的只读 occurrence 投影。"""

    ref: OccurrenceRef
    start: datetime | date
    end: datetime | date
    payload: Mapping[str, Any]
    is_override: bool


class RecurrenceExpander:
    """使用 python-dateutil 的纯函数 recurrence 展开器。"""

    @classmethod
    def expand(
        cls,
        definition: RecurrenceDefinition,
        *,
        range_start: datetime,
        range_end: datetime,
        overrides: Iterable[OccurrenceOverride] = (),
    ) -> list[Occurrence]:
        """展开与半开区间相交的 occurrence，绝不产生任何持久化副作用。"""
        if definition.duration <= timedelta(0):
            raise PlannerTimeError('重复日程的 duration 必须大于 0')

        local_range_start = PlannerTimeCodec.to_local(range_start, tzid=definition.tzid)
        local_range_end = PlannerTimeCodec.to_local(range_end, tzid=definition.tzid)
        if local_range_start >= local_range_end:
            raise PlannerTimeError('range_start 必须早于 range_end')

        is_all_day = isinstance(definition.dtstart, date) and not isinstance(definition.dtstart, datetime)
        cls._validate_value_types(definition, overrides, is_all_day=is_all_day)
        canonical = canonicalize_rrule(definition.rrule, dtstart=definition.dtstart, tzid=definition.tzid)
        rule_start, query_start, query_end = cls._rule_window(
            definition,
            local_range_start,
            local_range_end,
            is_all_day=is_all_day,
        )
        recurrence_set = rruleset()
        recurrence_set.rrule(rrulestr(canonical, dtstart=rule_start))
        for rdate in definition.rdates:
            recurrence_set.rdate(cls._to_rule_datetime(rdate, definition.tzid, is_all_day=is_all_day))
        for recurrence_id in definition.exdates:
            recurrence_set.exdate(
                cls._to_rule_datetime(
                    PlannerTimeCodec.parse_recurrence_id(recurrence_id, tzid=definition.tzid),
                    definition.tzid,
                    is_all_day=is_all_day,
                )
            )

        override_by_id = {override.recurrence_id: override for override in overrides}
        seen_ids: set[str] = set()
        occurrences: list[Occurrence] = []
        lookback = definition.duration
        for slot in recurrence_set.between(query_start - lookback, query_end, inc=True):
            base_start = cls._from_rule_datetime(slot, definition.tzid, is_all_day=is_all_day)
            recurrence_id = PlannerTimeCodec.format_recurrence_id(base_start, tzid=definition.tzid)
            seen_ids.add(recurrence_id)
            override = override_by_id.get(recurrence_id)
            occurrence = cls._build_occurrence(definition, base_start, override, is_all_day=is_all_day)
            if occurrence and cls._overlaps(occurrence, local_range_start, local_range_end, definition.tzid):
                occurrences.append(occurrence)

        for recurrence_id, override in override_by_id.items():
            if recurrence_id in seen_ids or override.kind == 'cancelled':
                continue
            base_start = PlannerTimeCodec.parse_recurrence_id(recurrence_id, tzid=definition.tzid)
            occurrence = cls._build_occurrence(definition, base_start, override, is_all_day=is_all_day)
            if occurrence and cls._overlaps(occurrence, local_range_start, local_range_end, definition.tzid):
                occurrences.append(occurrence)

        return sorted(occurrences, key=lambda occurrence: cls._sort_key(occurrence.start, definition.tzid))

    @classmethod
    def _rule_window(
        cls,
        definition: RecurrenceDefinition,
        range_start: datetime,
        range_end: datetime,
        *,
        is_all_day: bool,
    ) -> tuple[datetime, datetime, datetime]:
        if is_all_day:
            rule_start = datetime.combine(definition.dtstart, datetime.min.time())
            return (
                rule_start,
                range_start.replace(tzinfo=None),
                range_end.replace(tzinfo=None),
            )
        return (
            PlannerTimeCodec.to_local(definition.dtstart, tzid=definition.tzid),
            range_start,
            range_end,
        )

    @classmethod
    def _to_rule_datetime(cls, value: date | datetime, tzid: str, *, is_all_day: bool) -> datetime:
        if is_all_day:
            if isinstance(value, datetime):
                return PlannerTimeCodec.to_local(value, tzid=tzid).replace(tzinfo=None)
            return datetime.combine(value, datetime.min.time())
        return PlannerTimeCodec.to_local(PlannerTimeCodec.recurrence_datetime(value, tzid=tzid), tzid=tzid)

    @classmethod
    def _from_rule_datetime(cls, value: datetime, tzid: str, *, is_all_day: bool) -> date | datetime:
        if is_all_day:
            return value.date()
        return PlannerTimeCodec.to_local(value, tzid=tzid)

    @classmethod
    def _build_occurrence(
        cls,
        definition: RecurrenceDefinition,
        base_start: date | datetime,
        override: OccurrenceOverride | None,
        *,
        is_all_day: bool,
    ) -> Occurrence | None:
        if override and override.kind == 'cancelled':
            return None
        if override and override.kind != 'modified':
            raise PlannerTimeError(f'未知 occurrence override 类型: {override.kind}')

        effective_start = override.effective_start if override and override.effective_start is not None else base_start
        effective_end = override.effective_end if override and override.effective_end is not None else cls._add_duration(
            base_start,
            definition.duration,
            tzid=definition.tzid,
            is_all_day=is_all_day,
        )
        if cls._sort_key(effective_start, definition.tzid) >= cls._sort_key(effective_end, definition.tzid):
            raise PlannerTimeError('occurrence override 的结束时间必须晚于开始时间')

        recurrence_id = PlannerTimeCodec.format_recurrence_id(base_start, tzid=definition.tzid)
        payload = dict(definition.payload)
        if override:
            payload.update(override.patch)
        override_version = override.version if override and override.version is not None else definition.source_version
        source_version = max(definition.source_version, override_version)
        ref = OccurrenceRef(
            entity_type=definition.entity_type,
            entity_id=definition.entity_id,
            series_id=definition.series_id,
            recurrence_id=recurrence_id,
            occurrence_start=effective_start,
            source_version=source_version,
        )
        return Occurrence(
            ref=ref,
            start=effective_start,
            end=effective_end,
            payload=payload,
            is_override=override is not None,
        )

    @classmethod
    def _add_duration(
        cls,
        value: date | datetime,
        duration: timedelta,
        *,
        tzid: str,
        is_all_day: bool,
    ) -> date | datetime:
        if is_all_day:
            return value + duration
        return PlannerTimeCodec.to_local(value, tzid=tzid) + duration

    @classmethod
    def _overlaps(cls, occurrence: Occurrence, range_start: datetime, range_end: datetime, tzid: str) -> bool:
        start = cls._sort_key(occurrence.start, tzid)
        end = cls._sort_key(occurrence.end, tzid)
        return end > range_start and start < range_end

    @classmethod
    def _sort_key(cls, value: date | datetime, tzid: str) -> datetime:
        return PlannerTimeCodec.recurrence_datetime(value, tzid=tzid)

    @classmethod
    def _validate_value_types(
        cls,
        definition: RecurrenceDefinition,
        overrides: Iterable[OccurrenceOverride],
        *,
        is_all_day: bool,
    ) -> None:
        """RFC 5545 要求 RDATE/EXDATE/RECURRENCE-ID 与 DTSTART 类型一致。"""

        def is_date_value(value: date | datetime) -> bool:
            return isinstance(value, date) and not isinstance(value, datetime)

        for value in definition.rdates:
            if is_date_value(value) != is_all_day:
                raise PlannerTimeError('RDATE 类型必须与 DTSTART 一致')
        for recurrence_id in definition.exdates:
            value = PlannerTimeCodec.parse_recurrence_id(recurrence_id, tzid=definition.tzid)
            if is_date_value(value) != is_all_day:
                raise PlannerTimeError('EXDATE 类型必须与 DTSTART 一致')
        for override in overrides:
            value = PlannerTimeCodec.parse_recurrence_id(override.recurrence_id, tzid=definition.tzid)
            if is_date_value(value) != is_all_day:
                raise PlannerTimeError('RECURRENCE-ID 类型必须与 DTSTART 一致')
            for effective in (override.effective_start, override.effective_end):
                if effective is not None and is_date_value(effective) != is_all_day:
                    raise PlannerTimeError('override 时间类型必须与 DTSTART 一致')
