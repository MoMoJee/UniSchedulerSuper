"""Planner normalized 表的只读查询投影与版本辅助逻辑。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from django.contrib.auth.models import User
from django.db.models import Prefetch, Q

from core.models import (
    CalendarEvent,
    EventOccurrenceOverride,
    EventRecurrenceExDate,
    EventRecurrenceRDate,
    EventRecurrenceSeries,
)
from core.planner.recurrence.expander import (
    Occurrence,
    OccurrenceOverride,
    OccurrenceRef,
    RecurrenceDefinition,
    RecurrenceExpander,
)


class PlannerNotFoundError(LookupError):
    """当前用户范围内不存在目标 Planner 对象。"""


class PlannerVersionConflictError(ValueError):
    """写命令的 expected_version 与当前版本不一致。"""


@dataclass(frozen=True)
class EventDefinitionProjection:
    """单次 event 或 recurrence master 的查询投影。"""

    event: CalendarEvent
    recurrence: RecurrenceDefinition | None
    overrides: tuple[OccurrenceOverride, ...]


class PlannerRepository:
    """唯一读取 normalized Planner ORM 的基础 repository。"""

    @classmethod
    def get_event(cls, user: User, event_id: str, *, include_deleted: bool = False) -> CalendarEvent:
        """按公开 event_id 读取用户自己的 event。"""
        queryset = CalendarEvent.objects.filter(user=user, event_id=event_id).select_related('group')
        if not include_deleted:
            queryset = queryset.filter(deleted_at__isnull=True)
        event = queryset.first()
        if event is None:
            raise PlannerNotFoundError(f'未找到 event: {event_id}')
        return event

    @classmethod
    def require_event_version(cls, event: CalendarEvent, expected_version: int | None) -> None:
        """将模型版本错误转换为领域错误，供后续 command/API 统一映射 409。"""
        try:
            event.require_expected_version(expected_version)
        except ValueError as exc:
            raise PlannerVersionConflictError(str(exc)) from exc

    @classmethod
    def list_event_definitions(
        cls,
        user: User,
        *,
        range_start: datetime,
        range_end: datetime,
        event_ids: set[str] | None = None,
    ) -> list[EventDefinitionProjection]:
        """返回与窗口相关的单次 event 和全部可展开 recurrence master。"""
        cls._validate_range(range_start, range_end)
        singles_queryset = CalendarEvent.objects.filter(user=user, deleted_at__isnull=True, recurrence_series__isnull=True)
        if event_ids is not None:
            singles_queryset = singles_queryset.filter(event_id__in=event_ids)
        singles = list(
            singles_queryset
            .filter(cls._event_overlap_filter(range_start, range_end))
            .select_related('group')
            .prefetch_related('share_links__share_group')
            .order_by('start_at', 'start_date', 'id')
        )
        projections = [EventDefinitionProjection(event=event, recurrence=None, overrides=()) for event in singles]

        series_queryset = (
            EventRecurrenceSeries.objects.filter(user=user, deleted_at__isnull=True, master_event__deleted_at__isnull=True)
            .select_related('master_event', 'master_event__group')
            .prefetch_related(
                'master_event__share_links__share_group',
                Prefetch('rdates', queryset=EventRecurrenceRDate.objects.order_by('recurrence_id')),
                Prefetch('exdates', queryset=EventRecurrenceExDate.objects.order_by('recurrence_id')),
                Prefetch(
                    'overrides',
                    queryset=EventOccurrenceOverride.objects.filter(deleted_at__isnull=True).order_by('recurrence_id'),
                ),
            )
            .order_by('master_event__start_at', 'master_event__start_date', 'id')
        )
        if event_ids is not None:
            series_queryset = series_queryset.filter(master_event__event_id__in=event_ids)
        for series in series_queryset:
            definition = cls._to_recurrence_definition(series)
            overrides = tuple(cls._to_override(item) for item in series.overrides.all())
            projections.append(
                EventDefinitionProjection(
                    event=series.master_event,
                    recurrence=definition,
                    overrides=overrides,
                )
            )
        return projections

    @classmethod
    def list_all_event_definitions(cls, user: User) -> list[EventDefinitionProjection]:
        """返回用户全部 active Event 定义，供 Feed/CalDAV collection 使用。"""
        singles = list(
            CalendarEvent.objects.filter(user=user, deleted_at__isnull=True)
            .filter(Q(recurrence_series__isnull=True) | Q(recurrence_series__deleted_at__isnull=False))
            .select_related('group')
            .prefetch_related('share_links__share_group')
            .order_by('start_at', 'start_date', 'id')
        )
        projections = [EventDefinitionProjection(event=event, recurrence=None, overrides=()) for event in singles]
        series_queryset = (
            EventRecurrenceSeries.objects.filter(user=user, deleted_at__isnull=True, master_event__deleted_at__isnull=True)
            .select_related('master_event', 'master_event__group')
            .prefetch_related(
                'master_event__share_links__share_group',
                Prefetch('rdates', queryset=EventRecurrenceRDate.objects.order_by('recurrence_id')),
                Prefetch('exdates', queryset=EventRecurrenceExDate.objects.order_by('recurrence_id')),
                Prefetch(
                    'overrides',
                    queryset=EventOccurrenceOverride.objects.filter(deleted_at__isnull=True).order_by('recurrence_id'),
                ),
            )
            .order_by('master_event__start_at', 'master_event__start_date', 'id')
        )
        for series in series_queryset:
            projections.append(EventDefinitionProjection(
                event=series.master_event,
                recurrence=cls._to_recurrence_definition(series),
                overrides=tuple(cls._to_override(item) for item in series.overrides.all()),
            ))
        return projections

    @classmethod
    def list_event_occurrences(
        cls,
        user: User,
        *,
        range_start: datetime,
        range_end: datetime,
        event_ids: set[str] | None = None,
    ) -> list[Occurrence]:
        """从 normalized 表读取并纯展开 event occurrence，不产生任何写入。"""
        projections = cls.list_event_definitions(
            user, range_start=range_start, range_end=range_end, event_ids=event_ids
        )
        occurrences: list[Occurrence] = []
        for projection in projections:
            if projection.recurrence is None:
                single = cls._single_occurrence(projection.event)
                if cls._occurrence_overlaps(single, range_start, range_end):
                    occurrences.append(single)
                continue
            occurrences.extend(
                RecurrenceExpander.expand(
                    projection.recurrence,
                    range_start=range_start,
                    range_end=range_end,
                    overrides=projection.overrides,
                )
            )
        return sorted(occurrences, key=lambda item: cls._occurrence_start(item))

    @staticmethod
    def search_event_candidate_ids(user: User, query: str) -> set[str]:
        """先在数据库筛 master/override 文本，再仅展开候选 series。"""
        if not query:
            return set(
                CalendarEvent.objects.filter(user=user, deleted_at__isnull=True).values_list('event_id', flat=True)
            )
        master_ids = CalendarEvent.objects.filter(user=user, deleted_at__isnull=True).filter(
            Q(title__icontains=query) | Q(description__icontains=query) | Q(location__icontains=query)
        ).values_list('event_id', flat=True)
        # SQLite JSON 会把非 ASCII 转义，JSONField icontains 无法可靠匹配中文。
        # override 本身是稀疏行，受控扫描其 patch 后仍只展开命中的 master。
        override_ids = {
            override.series.master_event.event_id
            for override in EventOccurrenceOverride.objects.filter(
                series__user=user, deleted_at__isnull=True
            ).select_related('series__master_event')
            if query.casefold() in ' '.join(str(value) for value in override.patch.values()).casefold()
        }
        return set(master_ids) | override_ids

    @classmethod
    def _to_recurrence_definition(cls, series: EventRecurrenceSeries) -> RecurrenceDefinition:
        event = series.master_event
        dtstart = series.dtstart_at or series.dtstart_date
        if dtstart is None:
            raise ValueError(f'重复系列缺少 DTSTART: {series.series_id}')
        return RecurrenceDefinition(
            entity_type='event',
            entity_id=event.event_id,
            series_id=series.series_id,
            dtstart=dtstart,
            duration=cls._event_duration(event),
            rrule=series.rrule_canonical or series.rrule,
            tzid=series.tzid,
            source_version=max(event.version, series.version),
            payload=cls._event_payload(event),
            rdates=tuple(cls._rdate_value(item) for item in series.rdates.all()),
            exdates=frozenset(item.recurrence_id for item in series.exdates.all()),
        )

    @classmethod
    def _to_override(cls, override: EventOccurrenceOverride) -> OccurrenceOverride:
        effective_start = override.effective_start_at or override.effective_start_date
        effective_end = override.effective_end_at or override.effective_end_date
        return OccurrenceOverride(
            recurrence_id=override.recurrence_id,
            kind=override.kind,
            patch=override.patch,
            effective_start=effective_start,
            effective_end=effective_end,
            version=override.version,
        )

    @classmethod
    def _single_occurrence(cls, event: CalendarEvent) -> Occurrence:
        start, end = cls._event_range(event)
        return Occurrence(
            ref=OccurrenceRef(
                entity_type='event',
                entity_id=event.event_id,
                series_id='',
                recurrence_id='',
                occurrence_start=start,
                source_version=event.version,
            ),
            start=start,
            end=end,
            payload=cls._event_payload(event),
            is_override=False,
        )

    @staticmethod
    def _rdate_value(rdate: EventRecurrenceRDate) -> datetime | date:
        value = rdate.starts_at or rdate.starts_date
        if value is None:
            raise ValueError(f'RDATE 缺少时间: {rdate.recurrence_id}')
        return value

    @staticmethod
    def _event_payload(event: CalendarEvent) -> dict[str, Any]:
        return {
            'title': event.title,
            'description': event.description,
            'location': event.location,
            'status': event.status,
            'importance': event.importance,
            'urgency': event.urgency,
            'group_id': event.group.group_id if event.group else '',
            'is_all_day': event.is_all_day,
        }

    @classmethod
    def _event_range(cls, event: CalendarEvent) -> tuple[datetime | date, datetime | date]:
        if event.is_all_day:
            if event.start_date is None or event.end_date is None:
                raise ValueError(f'全天 event 缺少日期范围: {event.event_id}')
            return event.start_date, event.end_date
        if event.start_at is None or event.end_at is None:
            raise ValueError(f'定时 event 缺少时间范围: {event.event_id}')
        return event.start_at, event.end_at

    @classmethod
    def _event_duration(cls, event: CalendarEvent) -> timedelta:
        start, end = cls._event_range(event)
        duration = end - start
        if duration <= timedelta(0):
            raise ValueError(f'event 时长非法: {event.event_id}')
        return duration

    @staticmethod
    def _event_overlap_filter(range_start: datetime, range_end: datetime) -> Q:
        return (
            Q(is_all_day=False, start_at__lt=range_end, end_at__gt=range_start)
            | Q(is_all_day=True, start_date__lt=range_end.date(), end_date__gt=range_start.date())
        )

    @classmethod
    def _occurrence_overlaps(cls, occurrence: Occurrence, range_start: datetime, range_end: datetime) -> bool:
        start = cls._occurrence_start(occurrence)
        end = cls._occurrence_end(occurrence)
        return end > range_start and start < range_end

    @staticmethod
    def _occurrence_start(occurrence: Occurrence) -> datetime:
        if isinstance(occurrence.start, datetime):
            return occurrence.start
        return datetime.combine(occurrence.start, datetime.min.time(), tzinfo=range_timezone(occurrence))

    @staticmethod
    def _occurrence_end(occurrence: Occurrence) -> datetime:
        if isinstance(occurrence.end, datetime):
            return occurrence.end
        return datetime.combine(occurrence.end, datetime.min.time(), tzinfo=range_timezone(occurrence))

    @staticmethod
    def _validate_range(range_start: datetime, range_end: datetime) -> None:
        if range_start.tzinfo is None or range_end.tzinfo is None:
            raise ValueError('查询窗口必须使用 aware datetime')
        if range_start >= range_end:
            raise ValueError('range_start 必须早于 range_end')


def range_timezone(occurrence: Occurrence):
    """全天 occurrence 以默认 Planner 时区参与区间比较。"""
    from zoneinfo import ZoneInfo

    return ZoneInfo('Asia/Shanghai')
