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
from django.utils import timezone

from core.models import (
    CalendarChange,
    CalendarCollectionVersion,
    CalendarEvent,
    EventGroup,
    EventOccurrenceOverride,
    EventRecurrenceExDate,
    EventRecurrenceRDate,
    EventRecurrenceSeries,
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
    def create_event(cls, user: User, payload: Mapping[str, Any]) -> CalendarEvent:
        event_fields, recurrence_payload = cls._event_fields_from_payload(user, payload, creating=True)
        event = CalendarEvent.objects.create(user=user, **event_fields)
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
            raise PlannerCommandError(
                '此及以后需要先选择未来 override 的归属策略，当前 v2 命令不会进行不安全分裂',
                code='recurrence_split_requires_override_policy',
            )
        if series is None:
            if scope not in {'single', 'all'}:
                raise PlannerCommandError('非重复 event 仅支持 single 或 all scope', code='invalid_scope')
            cls._require_source_version(expected_version, event)
            before = cls._snapshot(event)
            fields, recurrence_payload = cls._event_fields_from_payload(user, payload, current=event)
            if recurrence_payload is not None:
                raise PlannerCommandError('单次 event 不能通过 PATCH 隐式创建 recurrence，请新建重复 event', code='recurrence_transition_unsupported')
            cls._apply_event_fields(event, fields)
            event.bump_version(update_fields=fields.keys())
            cls._record_change(user, event, command_type='event.patch', before=before, after=cls._snapshot(event))
            return event

        if scope == 'all':
            cls._require_source_version(expected_version, event, series)
            before = cls._snapshot(event, series)
            fields, recurrence_payload = cls._event_fields_from_payload(user, payload, current=event)
            cls._apply_event_fields(event, fields)
            if fields:
                event.bump_version(update_fields=fields.keys())
            if recurrence_payload is not None:
                cls._update_series(series, event, recurrence_payload)
            elif any(key in fields for key in {'start_at', 'end_at', 'start_date', 'end_date', 'tzid', 'is_all_day'}):
                cls._rewrite_series_for_master_time(series, event)
            cls._record_change(user, event, command_type='event.patch_all', before=before, after=cls._snapshot(event, series))
            return event

        if scope != 'single':
            raise PlannerCommandError('scope 必须是 single、all 或 this_and_future', code='invalid_scope')
        recurrence_id = cls._require_occurrence_ref(event, series, occurrence_ref)
        override = EventOccurrenceOverride.objects.select_for_update().filter(series=series, recurrence_id=recurrence_id).first()
        cls._require_source_version(expected_version, event, series, override)
        if override is not None and override.kind == EventOccurrenceOverride.KIND_CANCELLED:
            raise PlannerCommandError('已取消的 occurrence 不能直接修改', code='occurrence_not_found')
        cls._ensure_recurrence_slot(series, recurrence_id)
        before = cls._snapshot(event, series, override)
        patch, effective_values = cls._override_values_from_payload(user, event, payload)
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
            raise PlannerCommandError(
                '此及以后删除需要安全分裂策略，当前 v2 命令拒绝执行',
                code='recurrence_split_requires_override_policy',
            )
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
        known = cls._PATCHABLE_FIELDS | {'title', 'start', 'end', 'is_all_day', 'tzid', 'group_id', 'recurrence'}
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
        dtstart = event.start_date if event.is_all_day else event.start_at
        if dtstart is None:
            raise PlannerCommandError('event 缺少 DTSTART', code='invalid_time_range')
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
