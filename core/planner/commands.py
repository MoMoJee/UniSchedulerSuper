"""Planner v2 event 命令服务。

本模块是 normalized event 写入的唯一入口。它不理解 legacy JSON，也绝不为
重复事件预生成 CalendarEvent 实例；单次 recurrence 操作只写稀疏 override。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping
from uuid import uuid4

from dateutil.rrule import rruleset, rrulestr
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import (
    CalendarChange,
    CalendarCollectionVersion,
    CalendarEvent,
    CollaborativeCalendarGroup,
    EventGroup,
    EventOccurrenceOverride,
    EventReminderLink,
    EventRecurrenceExDate,
    EventRecurrenceRDate,
    EventRecurrenceSeries,
    EventRecurrenceSplitReview,
    EventShareGroup,
    EventTag,
    PlannerChangeSet,
)
from core.planner.recurrence.codec import InvalidRRuleError, PlannerTimeCodec, PlannerTimeError, canonicalize_rrule
from core.planner.repository import PlannerNotFoundError, PlannerRepository
from logger import logger


class PlannerCommandError(ValueError):
    """可安全返回给 v2 客户端的 command 参数/状态错误。"""

    def __init__(self, message: str, *, code: str = 'invalid_command'):
        super().__init__(message)
        self.code = code


class PlannerCommandVersionConflict(PlannerCommandError):
    """客户端的 source_version 已过期。"""

    def __init__(self, message: str = '对象已被其他操作修改，请刷新后重试'):
        super().__init__(message, code='version_conflict')


class PlannerCommandService:
    """对 CalendarEvent / EventRecurrenceSeries 的原子版本化命令。"""

    _PATCHABLE_FIELDS = frozenset({'title', 'description', 'location', 'status', 'importance', 'urgency', 'ddl_at'})

    @classmethod
    @transaction.atomic
    def create_event(
        cls,
        user: User,
        payload: Mapping[str, Any],
        *,
        event_id: str | None = None,
    ) -> CalendarEvent:
        event_fields, recurrence_payload = cls._event_fields_from_payload(user, payload, creating=True)
        if event_id is not None:
            if not isinstance(event_id, str) or not event_id.strip() or len(event_id) > 100:
                raise PlannerCommandError('event_id 格式无效', code='invalid_event_id')
            event_fields['event_id'] = event_id.strip()
        event = CalendarEvent.objects.create(user=user, **event_fields)
        if 'share_group_ids' in payload:
            cls._replace_share_groups(user, event, payload['share_group_ids'])
        if recurrence_payload is not None:
            cls._create_series(user, event, recurrence_payload)
        cls._record_change(user, event, command_type='event.create', before={}, after=cls._snapshot(event))
        return event

    @classmethod
    @transaction.atomic
    def patch_event(
        cls,
        user: User,
        event_id: str,
        payload: Mapping[str, Any],
        *,
        scope: str,
        occurrence_ref: Mapping[str, Any] | None,
        expected_version: int,
    ) -> CalendarEvent:
        event = cls._locked_event(user, event_id)
        series = cls._locked_series(event)
        if scope == 'this_and_future':
            if series is None:
                raise PlannerCommandError('非重复 event 不支持 this_and_future', code='invalid_scope')
            cls._require_source_version(expected_version, event, series)
            recurrence_id = cls._require_occurrence_ref(event, series, occurrence_ref)
            cls._ensure_recurrence_slot(series, recurrence_id)
            return cls._split_event(
                user,
                event,
                series,
                recurrence_id,
                payload,
                override_policy=str(payload.get('override_policy') or ''),
            )
        if series is None:
            if scope not in {'single', 'all'}:
                raise PlannerCommandError('非重复 event 仅支持 single 或 all scope', code='invalid_scope')
            cls._require_source_version(expected_version, event)
            before = cls._snapshot(event)
            fields, recurrence_payload = cls._event_fields_from_payload(user, payload, current=event)
            cls._apply_event_fields(event, fields)
            event.bump_version(update_fields=fields.keys())
            if 'share_group_ids' in payload:
                cls._replace_share_groups(user, event, payload['share_group_ids'])
            attached_series = cls._create_series(user, event, recurrence_payload) if recurrence_payload is not None else None
            cls._record_change(
                user,
                event,
                command_type='event.attach_recurrence' if attached_series else 'event.patch',
                before=before,
                after=cls._snapshot(event, attached_series),
            )
            return event

        if scope == 'all':
            cls._require_source_version(expected_version, event, series)
            before = cls._snapshot(event, series)
            fields, recurrence_payload = cls._event_fields_from_payload(user, payload, current=event)
            cls._apply_event_fields(event, fields)
            detach_recurrence = 'recurrence' in payload and payload.get('recurrence') is None
            if fields or detach_recurrence:
                event.bump_version(update_fields=fields.keys())
            if detach_recurrence:
                series.soft_delete(expected_version=series.version)
            elif recurrence_payload is not None:
                cls._update_series(series, event, recurrence_payload)
            elif any(key in fields for key in {'start_at', 'end_at', 'start_date', 'end_date', 'tzid', 'is_all_day'}):
                cls._rewrite_series_for_master_time(series, event)
            if 'share_group_ids' in payload:
                cls._replace_share_groups(user, event, payload['share_group_ids'])
                if not fields and not detach_recurrence:
                    event.bump_version(update_fields=[])
            command_type = 'event.detach_recurrence_all' if detach_recurrence else 'event.patch_all'
            cls._record_change(user, event, command_type=command_type, before=before, after=cls._snapshot(event, series))
            return event

        if scope != 'single':
            raise PlannerCommandError('scope 必须是 single、all 或 this_and_future', code='invalid_scope')
        recurrence_id = cls._require_occurrence_ref(event, series, occurrence_ref)
        override = EventOccurrenceOverride.objects.select_for_update().filter(series=series, recurrence_id=recurrence_id).first()
        cls._require_source_version(expected_version, event, series, override)
        if override is not None and override.kind == EventOccurrenceOverride.KIND_CANCELLED:
            raise PlannerCommandError('已取消的 occurrence 不能直接修改', code='occurrence_not_found')
        cls._ensure_recurrence_slot(series, recurrence_id)
        if 'share_group_ids' in payload:
            raise PlannerCommandError('single occurrence 不支持独立分享关系', code='unsupported_relation_scope')
        before = cls._snapshot(event, series, override)
        detach = payload.get('detach') is True
        clean_payload = {key: value for key, value in payload.items() if key != 'detach'}
        patch, effective_values = cls._override_values_from_payload(user, event, clean_payload)
        if detach:
            if override is None:
                override = EventOccurrenceOverride.objects.create(
                    series=series,
                    recurrence_id=recurrence_id,
                    kind=EventOccurrenceOverride.KIND_MODIFIED,
                    patch=patch,
                    **effective_values,
                )
            else:
                override.patch = {**override.patch, **patch}
                cls._apply_override_effective_values(override, effective_values)
                override.bump_version(update_fields={'patch', *effective_values.keys()})
            detached = cls._detach_override_as_single(user, event, series, override)
            override.kind = EventOccurrenceOverride.KIND_CANCELLED
            override.patch = {}
            override.bump_version(update_fields={'kind', 'patch'})
            cls._record_change(
                user,
                detached,
                command_type='event.detach_occurrence',
                before=before,
                after=cls._snapshot(detached, series, override),
            )
            return detached
        if not patch and not effective_values:
            raise PlannerCommandError('single scope 至少需要一个可修改字段', code='empty_patch')
        if override is None:
            override = EventOccurrenceOverride(series=series, recurrence_id=recurrence_id, kind=EventOccurrenceOverride.KIND_MODIFIED)
            override.patch = patch
            cls._apply_override_effective_values(override, effective_values)
            override.save()
        else:
            override.patch = {**override.patch, **patch}
            cls._apply_override_effective_values(override, effective_values)
            override.bump_version(update_fields={'patch', *effective_values.keys()})
        cls._record_change(
            user,
            event,
            command_type='event.patch_single',
            before=before,
            after=cls._snapshot(event, series, override),
        )
        return event

    @classmethod
    @transaction.atomic
    def delete_event(
        cls,
        user: User,
        event_id: str,
        *,
        scope: str,
        occurrence_ref: Mapping[str, Any] | None,
        expected_version: int,
    ) -> CalendarEvent:
        event = cls._locked_event(user, event_id)
        series = cls._locked_series(event)
        if scope == 'this_and_future':
            if series is None:
                raise PlannerCommandError('非重复 event 不支持 this_and_future', code='invalid_scope')
            cls._require_source_version(expected_version, event, series)
            recurrence_id = cls._require_occurrence_ref(event, series, occurrence_ref)
            cls._ensure_recurrence_slot(series, recurrence_id)
            cls._truncate_series_from(user, event, series, recurrence_id)
            return event
        if series is None:
            if scope not in {'single', 'all'}:
                raise PlannerCommandError('非重复 event 仅支持 single 或 all scope', code='invalid_scope')
            cls._require_source_version(expected_version, event)
            before = cls._snapshot(event)
            event.soft_delete(expected_version=event.version)
            cls._record_change(user, event, command_type='event.delete', before=before, after=cls._snapshot(event))
            return event
        if scope == 'all':
            cls._require_source_version(expected_version, event, series)
            before = cls._snapshot(event, series)
            event.soft_delete(expected_version=event.version)
            series.soft_delete(expected_version=series.version)
            cls._record_change(user, event, command_type='event.delete_all', before=before, after=cls._snapshot(event, series))
            return event
        if scope != 'single':
            raise PlannerCommandError('scope 必须是 single、all 或 this_and_future', code='invalid_scope')
        recurrence_id = cls._require_occurrence_ref(event, series, occurrence_ref)
        override = EventOccurrenceOverride.objects.select_for_update().filter(series=series, recurrence_id=recurrence_id).first()
        cls._require_source_version(expected_version, event, series, override)
        cls._ensure_recurrence_slot(series, recurrence_id)
        before = cls._snapshot(event, series, override)
        if override is None:
            EventOccurrenceOverride.objects.create(
                series=series,
                recurrence_id=recurrence_id,
                kind=EventOccurrenceOverride.KIND_CANCELLED,
            )
        elif override.kind != EventOccurrenceOverride.KIND_CANCELLED:
            override.kind = EventOccurrenceOverride.KIND_CANCELLED
            override.patch = {}
            override.effective_start_at = None
            override.effective_end_at = None
            override.effective_start_date = None
            override.effective_end_date = None
            override.bump_version(
                update_fields={
                    'kind', 'patch', 'effective_start_at', 'effective_end_at', 'effective_start_date', 'effective_end_date'
                }
            )
        cls._record_change(user, event, command_type='event.delete_single', before=before, after=cls._snapshot(event, series))
        return event

    @classmethod
    def source_version(cls, event: CalendarEvent, occurrence_ref: Mapping[str, Any] | None = None) -> int:
        """返回客户端下次 command 应携带的 source_version。"""
        # 删除响应仍需报告刚刚软删除的 series 版本，因此这里不排除 tombstone。
        series = EventRecurrenceSeries.objects.filter(master_event=event).first()
        objects: list[Any] = [event]
        if series is not None:
            objects.append(series)
            recurrence_id = occurrence_ref.get('recurrence_id') if isinstance(occurrence_ref, Mapping) else None
            if isinstance(recurrence_id, str):
                override = EventOccurrenceOverride.objects.filter(series=series, recurrence_id=recurrence_id).first()
                if override is not None:
                    objects.append(override)
        return max(item.version for item in objects)

    @classmethod
    def _split_event(
        cls,
        user: User,
        event: CalendarEvent,
        series: EventRecurrenceSeries,
        recurrence_id: str,
        payload: Mapping[str, Any],
        *,
        override_policy: str,
    ) -> CalendarEvent:
        future_overrides = list(
            EventOccurrenceOverride.objects.select_for_update()
            .filter(series=series, recurrence_id__gte=recurrence_id, deleted_at__isnull=True)
            .order_by('recurrence_id')
        )
        recurrence_specified = 'recurrence' in payload
        custom_recurrence = recurrence_specified and payload.get('recurrence') is not None
        detach_future = recurrence_specified and payload.get('recurrence') is None
        if future_overrides and override_policy not in {'keep_as_single', 'discard_with_audit', 'map_by_ordinal'}:
            raise PlannerCommandError('未来 override 存在，必须选择归属策略', code='recurrence_split_requires_override_policy')
        if custom_recurrence and future_overrides and override_policy == 'map_by_ordinal':
            raise PlannerCommandError('修改规则时不能证明 ordinal 映射，请选择其他策略', code='recurrence_split_requires_override_policy')
        if detach_future and override_policy == 'map_by_ordinal':
            raise PlannerCommandError('取消未来重复时不能映射 override', code='recurrence_split_requires_override_policy')

        slot = PlannerTimeCodec.parse_recurrence_id(recurrence_id, tzid=series.tzid)
        duration = cls._event_duration(event)
        child = CalendarEvent(
            user=user,
            group=event.group,
            title=event.title,
            description=event.description,
            location=event.location,
            status=event.status,
            importance=event.importance,
            urgency=event.urgency,
            ddl_at=event.ddl_at,
            tzid=event.tzid,
            is_all_day=event.is_all_day,
            metadata={**event.metadata, 'split_from_series_id': series.series_id, 'split_recurrence_id': recurrence_id},
        )
        if event.is_all_day:
            child.start_date = slot
            child.end_date = slot + duration
        else:
            slot_utc = PlannerTimeCodec.to_utc(slot, tzid=series.tzid)
            child.start_at = slot_utc
            child.end_at = slot_utc + duration
        clean_payload = {key: value for key, value in payload.items() if key != 'override_policy'}
        fields, recurrence_payload = cls._event_fields_from_payload(user, clean_payload, current=child)
        cls._apply_event_fields(child, fields)
        child.save()

        parent_parts = cls._rrule_parts(series.rrule_canonical or series.rrule)
        kept_count = cls._count_slots_before(series, recurrence_id)
        remaining_count = None
        if 'COUNT' in parent_parts:
            remaining_count = max(int(parent_parts['COUNT']) - kept_count, 1)
        derived_child_parts = dict(parent_parts)
        if remaining_count is not None:
            derived_child_parts['COUNT'] = str(remaining_count)
        derived_child_rule = ';'.join(f'{key}={value}' for key, value in sorted(derived_child_parts.items()))
        if recurrence_payload is None and not detach_future:
            recurrence_payload = {'rrule': derived_child_rule}
        child_series = None
        if not detach_future:
            child_series = cls._create_series(user, child, recurrence_payload)
            child_series.parent_series = series
            child_series.split_recurrence_id = recurrence_id
            child_series.save(update_fields={'parent_series', 'split_recurrence_id', 'updated_at'})

        if child_series is not None and not custom_recurrence:
            for item in list(series.rdates.filter(recurrence_id__gte=recurrence_id)):
                EventRecurrenceRDate.objects.get_or_create(
                    series=child_series,
                    recurrence_id=item.recurrence_id,
                    defaults={'starts_at': item.starts_at, 'starts_date': item.starts_date},
                )
            for item in list(series.exdates.filter(recurrence_id__gte=recurrence_id)):
                EventRecurrenceExDate.objects.get_or_create(
                    series=child_series, recurrence_id=item.recurrence_id, defaults={'source': item.source}
                )

        if override_policy == 'map_by_ordinal':
            for override in future_overrides:
                override.series = child_series
                override.bump_version(update_fields={'series'})
        elif override_policy == 'keep_as_single':
            for override in future_overrides:
                if child_series is not None:
                    EventRecurrenceExDate.objects.get_or_create(
                        series=child_series,
                        recurrence_id=override.recurrence_id,
                        defaults={'source': 'split_keep_as_single'},
                    )
                if override.kind == EventOccurrenceOverride.KIND_MODIFIED:
                    cls._detach_override_as_single(user, event, series, override)
                override.soft_delete(expected_version=override.version)
        else:
            for override in future_overrides:
                override.soft_delete(expected_version=override.version)

        if child_series is not None and not custom_recurrence:
            original_child_start = slot if event.is_all_day else slot_utc
            effective_child_start = child.start_date if child.is_all_day else child.start_at
            cls._shift_series_occurrence_keys(
                child_series,
                effective_child_start - original_child_start,
                old_tzid=series.tzid,
                new_tzid=child_series.tzid,
            )

        cls._truncate_parent_rule(event, series, kept_count)
        cls._copy_event_relations(event, child)
        if 'share_group_ids' in payload:
            cls._replace_share_groups(user, child, payload['share_group_ids'])
        cls._record_change(
            user,
            child,
            command_type='event.split_this_and_future',
            before=cls._snapshot(event, series),
            after=cls._snapshot(child, child_series),
        )
        return child

    @classmethod
    def _truncate_series_from(cls, user: User, event: CalendarEvent, series: EventRecurrenceSeries, recurrence_id: str) -> None:
        kept_count = cls._count_slots_before(series, recurrence_id)
        for override in EventOccurrenceOverride.objects.select_for_update().filter(
            series=series, recurrence_id__gte=recurrence_id, deleted_at__isnull=True
        ):
            override.soft_delete(expected_version=override.version)
        cls._truncate_parent_rule(event, series, kept_count)
        cls._record_change(
            user, event, command_type='event.delete_this_and_future',
            before={'series_id': series.series_id, 'recurrence_id': recurrence_id},
            after=cls._snapshot(event, series),
        )

    @classmethod
    def _truncate_parent_rule(cls, event: CalendarEvent, series: EventRecurrenceSeries, kept_count: int) -> None:
        if kept_count <= 0:
            event.soft_delete(expected_version=event.version)
            series.soft_delete(expected_version=series.version)
            return
        parts = cls._rrule_parts(series.rrule_canonical or series.rrule)
        parts.pop('UNTIL', None)
        parts['COUNT'] = str(kept_count)
        rule = ';'.join(f'{key}={value}' for key, value in sorted(parts.items()))
        dtstart = series.dtstart_at or series.dtstart_date
        series.rrule = rule
        series.rrule_canonical = canonicalize_rrule(rule, dtstart=dtstart, tzid=series.tzid)
        series.sequence += 1
        series.bump_version(update_fields={'rrule', 'rrule_canonical', 'sequence'})

    @classmethod
    def _count_slots_before(cls, series: EventRecurrenceSeries, recurrence_id: str) -> int:
        dtstart = series.dtstart_at or series.dtstart_date
        anchor = PlannerTimeCodec.parse_recurrence_id(recurrence_id, tzid=series.tzid)
        is_all_day = isinstance(dtstart, date) and not isinstance(dtstart, datetime)
        rule_start = PlannerTimeCodec.recurrence_datetime(dtstart, tzid=series.tzid)
        anchor_dt = PlannerTimeCodec.recurrence_datetime(anchor, tzid=series.tzid)
        if is_all_day:
            rule_start = rule_start.replace(tzinfo=None)
            anchor_dt = anchor_dt.replace(tzinfo=None)
        rule = rrulestr(series.rrule_canonical or series.rrule, dtstart=rule_start)
        return len([item for item in rule.between(rule_start, anchor_dt, inc=True) if item < anchor_dt])

    @staticmethod
    def _event_duration(event: CalendarEvent) -> timedelta:
        start = event.start_date if event.is_all_day else event.start_at
        end = event.end_date if event.is_all_day else event.end_at
        if start is None or end is None or end <= start:
            raise PlannerCommandError('event 时间范围非法', code='invalid_time_range')
        return end - start

    @staticmethod
    def _rrule_parts(rule: str) -> dict[str, str]:
        return {
            key.upper(): value
            for component in rule.removeprefix('RRULE:').split(';')
            if '=' in component
            for key, value in [component.split('=', 1)]
        }

    @classmethod
    def _detach_override_as_single(
        cls,
        user: User,
        master: CalendarEvent,
        series: EventRecurrenceSeries,
        override: EventOccurrenceOverride,
    ) -> CalendarEvent:
        start = override.effective_start_at or override.effective_start_date
        end = override.effective_end_at or override.effective_end_date
        if start is None:
            start = PlannerTimeCodec.parse_recurrence_id(override.recurrence_id, tzid=series.tzid)
        if end is None:
            end = start + cls._event_duration(master)
        patch = override.patch
        detached = CalendarEvent.objects.create(
            user=user, group=master.group, title=str(patch.get('title', master.title)),
            description=str(patch.get('description', master.description)), location=str(patch.get('location', master.location)),
            status=str(patch.get('status', master.status)), importance=str(patch.get('importance', master.importance)),
            urgency=str(patch.get('urgency', master.urgency)), ddl_at=master.ddl_at, tzid=master.tzid,
            is_all_day=master.is_all_day,
            start_at=start if isinstance(start, datetime) else None,
            end_at=end if isinstance(end, datetime) else None,
            start_date=start if isinstance(start, date) and not isinstance(start, datetime) else None,
            end_date=end if isinstance(end, date) and not isinstance(end, datetime) else None,
            metadata={'detached_from_series_id': series.series_id, 'recurrence_id': override.recurrence_id},
        )
        cls._copy_event_relations(master, detached)
        return detached

    @staticmethod
    def _copy_event_relations(source: CalendarEvent, target: CalendarEvent) -> None:
        EventTag.objects.bulk_create(
            [EventTag(event=target, tag=item.tag, normalized_tag=item.normalized_tag) for item in source.tag_links.all()],
            ignore_conflicts=True,
        )
        EventReminderLink.objects.bulk_create(
            [EventReminderLink(event=target, reminder=item.reminder) for item in source.reminder_links.all()],
            ignore_conflicts=True,
        )
        EventShareGroup.objects.bulk_create(
            [EventShareGroup(event=target, share_group=item.share_group) for item in source.share_links.all()],
            ignore_conflicts=True,
        )

    @classmethod
    def _locked_event(cls, user: User, event_id: str) -> CalendarEvent:
        event = CalendarEvent.objects.select_for_update().filter(user=user, event_id=event_id, deleted_at__isnull=True).first()
        if event is None:
            raise PlannerNotFoundError(f'未找到 event: {event_id}')
        return event

    @staticmethod
    def _locked_series(event: CalendarEvent) -> EventRecurrenceSeries | None:
        return EventRecurrenceSeries.objects.select_for_update().filter(master_event=event, deleted_at__isnull=True).first()

    @classmethod
    def _event_fields_from_payload(
        cls,
        user: User,
        payload: Mapping[str, Any],
        *,
        creating: bool = False,
        current: CalendarEvent | None = None,
    ) -> tuple[dict[str, Any], Mapping[str, Any] | None]:
        if not isinstance(payload, Mapping):
            raise PlannerCommandError('请求体必须是 JSON object')
        known = cls._PATCHABLE_FIELDS | {
            'title', 'start', 'end', 'is_all_day', 'tzid', 'group_id', 'recurrence', 'share_group_ids'
        }
        unknown = set(payload) - known
        if unknown:
            raise PlannerCommandError(f'不支持的 event 字段: {", ".join(sorted(unknown))}', code='unsupported_field')
        if creating and (not isinstance(payload.get('title'), str) or not payload['title'].strip()):
            raise PlannerCommandError('title 为必填且不能是空字符串', code='invalid_title')
        fields: dict[str, Any] = {}
        for field in cls._PATCHABLE_FIELDS:
            if field in payload:
                value = payload[field]
                if field == 'ddl_at':
                    fields[field] = None if value is None else PlannerTimeCodec.to_utc(PlannerTimeCodec.parse_value(value, allow_date=False))
                elif not isinstance(value, str):
                    raise PlannerCommandError(f'{field} 必须是字符串', code='invalid_field')
                else:
                    fields[field] = value.strip() if field == 'title' else value
        tzid = payload.get('tzid', current.tzid if current else PlannerTimeCodec.DEFAULT_TZID)
        if not isinstance(tzid, str) or not tzid:
            raise PlannerCommandError('tzid 必须是非空字符串', code='invalid_timezone')
        PlannerTimeCodec.get_timezone(tzid)
        if 'tzid' in payload or creating:
            fields['tzid'] = tzid
        is_all_day = payload.get('is_all_day', current.is_all_day if current else False)
        if not isinstance(is_all_day, bool):
            raise PlannerCommandError('is_all_day 必须是布尔值', code='invalid_time_range')
        if 'is_all_day' in payload or creating:
            fields['is_all_day'] = is_all_day
        has_start, has_end = 'start' in payload, 'end' in payload
        if creating and (not has_start or not has_end):
            raise PlannerCommandError('start 与 end 为必填', code='invalid_time_range')
        if has_start != has_end:
            raise PlannerCommandError('start 与 end 必须同时提供', code='invalid_time_range')
        if has_start:
            start, end = cls._parse_event_range(payload['start'], payload['end'], is_all_day=is_all_day, tzid=tzid)
            if is_all_day:
                fields.update({'start_date': start, 'end_date': end, 'start_at': None, 'end_at': None})
            else:
                fields.update({'start_at': start, 'end_at': end, 'start_date': None, 'end_date': None})
        elif current is not None and 'is_all_day' in payload and is_all_day != current.is_all_day:
            raise PlannerCommandError('切换全天类型时必须同时提供 start 与 end', code='invalid_time_range')
        if 'group_id' in payload:
            group_id = payload['group_id']
            if group_id is None:
                fields['group'] = None
            elif isinstance(group_id, str) and group_id:
                group = EventGroup.objects.filter(user=user, group_id=group_id, deleted_at__isnull=True).first()
                if group is None:
                    raise PlannerCommandError('未找到指定 event group', code='group_not_found')
                fields['group'] = group
            else:
                raise PlannerCommandError('group_id 必须是字符串或 null', code='invalid_group')
        recurrence = payload.get('recurrence') if 'recurrence' in payload else None
        if recurrence is not None and not isinstance(recurrence, Mapping):
            raise PlannerCommandError('recurrence 必须是 object', code='invalid_recurrence')
        return fields, recurrence

    @staticmethod
    def _replace_share_groups(user: User, event: CalendarEvent, raw_ids: Any) -> None:
        if not isinstance(raw_ids, list) or any(not isinstance(item, str) or not item for item in raw_ids):
            raise PlannerCommandError('share_group_ids 必须是非空字符串数组', code='invalid_share_groups')
        ids = list(dict.fromkeys(raw_ids))
        allowed = list(
            CollaborativeCalendarGroup.objects.filter(share_group_id__in=ids)
            .filter(Q(owner=user) | Q(memberships__user=user))
            .distinct()
        )
        if len(allowed) != len(ids):
            raise PlannerCommandError('包含不存在或无权访问的分享组', code='share_group_forbidden')
        EventShareGroup.objects.filter(event=event).delete()
        EventShareGroup.objects.bulk_create(
            [EventShareGroup(event=event, share_group=group) for group in allowed]
        )

    @staticmethod
    def _parse_event_range(start_value: Any, end_value: Any, *, is_all_day: bool, tzid: str) -> tuple[date | datetime, date | datetime]:
        start = PlannerTimeCodec.parse_value(start_value, tzid=tzid, allow_date=is_all_day)
        end = PlannerTimeCodec.parse_value(end_value, tzid=tzid, allow_date=is_all_day)
        if is_all_day:
            if isinstance(start, datetime) or isinstance(end, datetime):
                raise PlannerCommandError('全天 event 的 start/end 必须是 DATE', code='invalid_time_range')
        else:
            if not isinstance(start, datetime) or not isinstance(end, datetime):
                raise PlannerCommandError('定时 event 的 start/end 必须是 DATE-TIME', code='invalid_time_range')
            start, end = PlannerTimeCodec.to_utc(start, tzid=tzid), PlannerTimeCodec.to_utc(end, tzid=tzid)
        if end <= start:
            raise PlannerCommandError('end 必须晚于 start', code='invalid_time_range')
        return start, end

    @classmethod
    def _create_series(cls, user: User, event: CalendarEvent, payload: Mapping[str, Any]) -> EventRecurrenceSeries:
        definition = cls._validated_recurrence_payload(event, payload)
        series = EventRecurrenceSeries.objects.create(
            user=user,
            master_event=event,
            series_id=str(payload.get('series_id') or uuid4()),
            ical_uid=str(payload.get('ical_uid') or f'{event.event_id}@planner.local'),
            rrule=definition['rrule'],
            rrule_canonical=definition['rrule_canonical'],
            dtstart_at=event.start_at,
            dtstart_date=event.start_date,
            tzid=event.tzid,
        )
        cls._replace_series_dates(series, definition)
        return series

    @classmethod
    def _update_series(cls, series: EventRecurrenceSeries, event: CalendarEvent, payload: Mapping[str, Any]) -> None:
        definition = cls._validated_recurrence_payload(event, payload)
        series.rrule = definition['rrule']
        series.rrule_canonical = definition['rrule_canonical']
        series.dtstart_at = event.start_at
        series.dtstart_date = event.start_date
        series.tzid = event.tzid
        series.sequence += 1
        series.bump_version(update_fields={'rrule', 'rrule_canonical', 'dtstart_at', 'dtstart_date', 'tzid', 'sequence'})
        cls._replace_series_dates(series, definition)

    @classmethod
    def _rewrite_series_for_master_time(cls, series: EventRecurrenceSeries, event: CalendarEvent) -> None:
        old_dtstart = series.dtstart_date if event.is_all_day else series.dtstart_at
        dtstart = event.start_date if event.is_all_day else event.start_at
        if dtstart is None or old_dtstart is None:
            raise PlannerCommandError('event 缺少 DTSTART', code='invalid_time_range')
        delta = dtstart - old_dtstart
        cls._shift_series_occurrence_keys(series, delta, old_tzid=series.tzid, new_tzid=event.tzid)
        try:
            canonical = canonicalize_rrule(series.rrule, dtstart=dtstart, tzid=event.tzid)
        except InvalidRRuleError as exc:
            raise PlannerCommandError(str(exc), code='invalid_rrule') from exc
        series.rrule_canonical = canonical
        series.dtstart_at = event.start_at
        series.dtstart_date = event.start_date
        series.tzid = event.tzid
        series.sequence += 1
        series.bump_version(update_fields={'rrule_canonical', 'dtstart_at', 'dtstart_date', 'tzid', 'sequence'})

    @classmethod
    def _shift_series_occurrence_keys(
        cls,
        series: EventRecurrenceSeries,
        delta: timedelta,
        *,
        old_tzid: str,
        new_tzid: str,
    ) -> None:
        """系列整体平移时同步稀疏关系的 RECURRENCE-ID 与显式生效时间。"""
        if not delta:
            return

        def shifted_id(value: str) -> str:
            slot = PlannerTimeCodec.parse_recurrence_id(value, tzid=old_tzid)
            return PlannerTimeCodec.format_recurrence_id(slot + delta, tzid=new_tzid)

        # 两阶段改键，避免日期平移后与同表相邻行的唯一约束瞬时冲突。
        collections = (
            list(series.overrides.select_for_update().filter(deleted_at__isnull=True)),
            list(series.exdates.select_for_update().all()),
            list(series.rdates.select_for_update().all()),
            list(series.split_reviews.select_for_update().filter(deleted_at__isnull=True)),
        )
        remaps: list[tuple[Any, str]] = []
        for objects in collections:
            for item in objects:
                remaps.append((item, shifted_id(item.recurrence_id)))
                item.recurrence_id = f'tmp-{uuid4()}'
                item.save(update_fields={'recurrence_id'})

        for item, recurrence_id in remaps:
            item.recurrence_id = recurrence_id
            update_fields = {'recurrence_id'}
            if isinstance(item, EventOccurrenceOverride):
                if item.effective_start_at is not None:
                    item.effective_start_at += delta
                    item.effective_end_at += delta
                    update_fields.update({'effective_start_at', 'effective_end_at'})
                elif item.effective_start_date is not None:
                    item.effective_start_date += delta
                    item.effective_end_date += delta
                    update_fields.update({'effective_start_date', 'effective_end_date'})
                item.bump_version(update_fields=update_fields)
                continue
            if isinstance(item, EventRecurrenceRDate):
                if item.starts_at is not None:
                    item.starts_at += delta
                    update_fields.add('starts_at')
                elif item.starts_date is not None:
                    item.starts_date += delta
                    update_fields.add('starts_date')
            item.save(update_fields=update_fields)

    @classmethod
    def _validated_recurrence_payload(cls, event: CalendarEvent, payload: Mapping[str, Any]) -> dict[str, Any]:
        allowed = {'rrule', 'rdates', 'exdates', 'series_id', 'ical_uid'}
        unknown = set(payload) - allowed
        if unknown:
            raise PlannerCommandError(f'不支持的 recurrence 字段: {", ".join(sorted(unknown))}', code='unsupported_field')
        dtstart = event.start_date if event.is_all_day else event.start_at
        if dtstart is None:
            raise PlannerCommandError('重复 event 缺少 DTSTART', code='invalid_time_range')
        try:
            canonical = canonicalize_rrule(str(payload.get('rrule', '')), dtstart=dtstart, tzid=event.tzid)
        except InvalidRRuleError as exc:
            raise PlannerCommandError(str(exc), code='invalid_rrule') from exc
        rdates = cls._parse_recurrence_dates(payload.get('rdates', []), event)
        exdates = cls._parse_recurrence_dates(payload.get('exdates', []), event)
        return {'rrule': str(payload['rrule']).strip(), 'rrule_canonical': canonical, 'rdates': rdates, 'exdates': exdates}

    @classmethod
    def _parse_recurrence_dates(cls, values: Any, event: CalendarEvent) -> list[date | datetime]:
        if not isinstance(values, list):
            raise PlannerCommandError('rdates/exdates 必须是数组', code='invalid_recurrence')
        parsed: list[date | datetime] = []
        for value in values:
            item = PlannerTimeCodec.parse_value(value, tzid=event.tzid, allow_date=event.is_all_day)
            if event.is_all_day:
                if isinstance(item, datetime):
                    raise PlannerCommandError('全天 recurrence 日期必须是 DATE', code='invalid_recurrence')
            else:
                if not isinstance(item, datetime):
                    raise PlannerCommandError('定时 recurrence 日期必须是 DATE-TIME', code='invalid_recurrence')
                item = PlannerTimeCodec.to_utc(item, tzid=event.tzid)
            parsed.append(item)
        return parsed

    @staticmethod
    def _replace_series_dates(series: EventRecurrenceSeries, definition: Mapping[str, Any]) -> None:
        EventRecurrenceRDate.objects.filter(series=series).delete()
        EventRecurrenceExDate.objects.filter(series=series).delete()
        for value in definition['rdates']:
            recurrence_id = PlannerTimeCodec.format_recurrence_id(value, tzid=series.tzid)
            EventRecurrenceRDate.objects.create(
                series=series,
                recurrence_id=recurrence_id,
                starts_at=value if isinstance(value, datetime) else None,
                starts_date=value if isinstance(value, date) and not isinstance(value, datetime) else None,
            )
        for value in definition['exdates']:
            EventRecurrenceExDate.objects.create(
                series=series,
                recurrence_id=PlannerTimeCodec.format_recurrence_id(value, tzid=series.tzid),
            )

    @classmethod
    def _override_values_from_payload(
        cls, user: User, event: CalendarEvent, payload: Mapping[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        fields, recurrence = cls._event_fields_from_payload(user, payload, current=event)
        if recurrence is not None:
            raise PlannerCommandError('single scope 不允许修改 recurrence 规则', code='invalid_scope')
        disallowed = {'is_all_day', 'tzid', 'ddl_at'} & set(fields)
        if disallowed:
            raise PlannerCommandError('single scope 不允许修改全天类型、时区或 ddl_at', code='invalid_scope')
        effective: dict[str, Any] = {}
        if 'start_at' in fields:
            effective = {'effective_start_at': fields.pop('start_at'), 'effective_end_at': fields.pop('end_at')}
            fields.pop('start_date', None)
            fields.pop('end_date', None)
        elif 'start_date' in fields:
            effective = {'effective_start_date': fields.pop('start_date'), 'effective_end_date': fields.pop('end_date')}
            fields.pop('start_at', None)
            fields.pop('end_at', None)
        fields.pop('group', None)
        if 'group_id' in payload:
            fields['group_id'] = payload['group_id']
        fields.pop('is_all_day', None)
        fields.pop('tzid', None)
        return fields, effective

    @staticmethod
    def _apply_event_fields(event: CalendarEvent, fields: Mapping[str, Any]) -> None:
        for name, value in fields.items():
            setattr(event, name, value)

    @staticmethod
    def _apply_override_effective_values(override: EventOccurrenceOverride, values: Mapping[str, Any]) -> None:
        for name, value in values.items():
            setattr(override, name, value)

    @classmethod
    def _require_occurrence_ref(
        cls, event: CalendarEvent, series: EventRecurrenceSeries, occurrence_ref: Mapping[str, Any] | None
    ) -> str:
        if not isinstance(occurrence_ref, Mapping):
            raise PlannerCommandError('single scope 必须提供 occurrence_ref', code='occurrence_not_found')
        if occurrence_ref.get('entity_id') != event.event_id or occurrence_ref.get('series_id') != series.series_id:
            raise PlannerCommandError('occurrence_ref 不属于目标 event/series', code='occurrence_not_found')
        recurrence_id = occurrence_ref.get('recurrence_id')
        if not isinstance(recurrence_id, str) or not recurrence_id:
            raise PlannerCommandError('occurrence_ref 缺少 recurrence_id', code='occurrence_not_found')
        return recurrence_id

    @staticmethod
    def _require_source_version(expected_version: int, *objects: Any) -> None:
        actual = max(item.version for item in objects if item is not None)
        if expected_version != actual:
            raise PlannerCommandVersionConflict(f'版本冲突: expected={expected_version}, actual={actual}')

    @classmethod
    def _ensure_recurrence_slot(cls, series: EventRecurrenceSeries, recurrence_id: str) -> None:
        event = series.master_event
        try:
            slot = PlannerTimeCodec.parse_recurrence_id(recurrence_id, tzid=series.tzid)
            is_all_day = event.is_all_day
            if is_all_day != (isinstance(slot, date) and not isinstance(slot, datetime)):
                raise PlannerCommandError('recurrence_id 类型与 series DTSTART 不一致', code='recurrence_id_not_in_series')
            slot_value = PlannerTimeCodec.recurrence_datetime(slot, tzid=series.tzid)
            rule_start = PlannerTimeCodec.recurrence_datetime(series.dtstart_date if is_all_day else series.dtstart_at, tzid=series.tzid)
            if is_all_day:
                rule_start = rule_start.replace(tzinfo=None)
                slot_value = slot_value.replace(tzinfo=None)
            recurrence_set = rruleset()
            recurrence_set.rrule(rrulestr(series.rrule_canonical or series.rrule, dtstart=rule_start))
            for rdate in series.rdates.all():
                value = rdate.starts_date if is_all_day else rdate.starts_at
                if value is not None:
                    recurrence_set.rdate(PlannerTimeCodec.recurrence_datetime(value, tzid=series.tzid).replace(tzinfo=None) if is_all_day else PlannerTimeCodec.to_local(value, tzid=series.tzid))
            if recurrence_set.after(slot_value - timedelta(seconds=1), inc=True) != slot_value:
                raise PlannerCommandError('recurrence_id 不属于该 series', code='recurrence_id_not_in_series')
            if series.exdates.filter(recurrence_id=recurrence_id).exists():
                raise PlannerCommandError('recurrence_id 已被 EXDATE 排除', code='recurrence_id_not_in_series')
        except (PlannerTimeError, ValueError, TypeError) as exc:
            if isinstance(exc, PlannerCommandError):
                raise
            raise PlannerCommandError('recurrence_id 不属于该 series', code='recurrence_id_not_in_series') from exc

    @staticmethod
    def _snapshot(event: CalendarEvent, series: EventRecurrenceSeries | None = None, override: EventOccurrenceOverride | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {'event': {'event_id': event.event_id, 'version': event.version, 'deleted_at': event.deleted_at.isoformat() if event.deleted_at else None}}
        if series is not None:
            result['series'] = {'series_id': series.series_id, 'version': series.version, 'deleted_at': series.deleted_at.isoformat() if series.deleted_at else None}
        if override is not None:
            result['override'] = {'recurrence_id': override.recurrence_id, 'kind': override.kind, 'version': override.version}
        return result

    @classmethod
    def _record_change(
        cls, user: User, event: CalendarEvent, *, command_type: str, before: dict[str, Any], after: dict[str, Any]
    ) -> None:
        collection, _ = CalendarCollectionVersion.objects.select_for_update().get_or_create(
            user=user,
            collection_type='event',
            collection_id='default',
        )
        collection.version += 1
        collection.sync_token = str(uuid4())
        collection.save(update_fields={'version', 'sync_token', 'updated_at'})
        CalendarChange.objects.create(
            collection=collection,
            token=collection.version,
            resource_type='event',
            resource_public_id=event.event_id,
            action=(
                CalendarChange.ACTION_DELETE
                if event.deleted_at
                else CalendarChange.ACTION_CREATE
                if command_type == 'event.create'
                else CalendarChange.ACTION_UPDATE
            ),
            etag=f'event:{event.event_id}:{event.version}',
        )
        PlannerChangeSet.objects.create(
            user=user,
            command_type=command_type,
            before_payload=before,
            after_payload=after,
        )
