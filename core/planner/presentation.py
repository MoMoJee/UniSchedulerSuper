"""Planner v2 API 的稳定只读输出契约。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from core.planner.recurrence.expander import Occurrence
from core.planner.repository import EventDefinitionProjection


def serialize_event_definition(projection: EventDefinitionProjection) -> dict[str, Any]:
    """将 ORM 查询投影转换为前端/Agent 可复用的 v2 definition。"""
    event = projection.event
    start, end = _event_range(event)
    result = {
        'entity_type': 'event',
        'event_id': event.event_id,
        'version': event.version,
        'title': event.title,
        'description': event.description,
        'location': event.location,
        'status': event.status,
        'importance': event.importance,
        'urgency': event.urgency,
        'group_id': event.group.group_id if event.group else None,
        'is_all_day': event.is_all_day,
        'start': _serialize_temporal(start),
        'end': _serialize_temporal(end),
        'ddl_at': _serialize_temporal(event.ddl_at),
        'share_group_ids': [item.share_group.share_group_id for item in event.share_links.all()],
        'recurrence': None,
    }
    if projection.recurrence is not None:
        definition = projection.recurrence
        result['recurrence'] = {
            'series_id': definition.series_id,
            'rrule': definition.rrule,
            'tzid': definition.tzid,
            'dtstart': _serialize_temporal(definition.dtstart),
            'rdates': [_serialize_temporal(value) for value in definition.rdates],
            'exdates': sorted(definition.exdates),
            'override_count': len(projection.overrides),
            'source_version': definition.source_version,
        }
    return result


def serialize_occurrence(occurrence: Occurrence) -> dict[str, Any]:
    """输出 occurrence 与复合身份，禁止把虚拟 occurrence 当作实体行。"""
    ref = occurrence.ref
    return {
        'id': _occurrence_client_id(ref.entity_type, ref.entity_id, ref.series_id, ref.recurrence_id),
        'entity_type': ref.entity_type,
        'title': occurrence.payload.get('title', ''),
        'start': _serialize_temporal(occurrence.start),
        'end': _serialize_temporal(occurrence.end),
        'is_all_day': bool(occurrence.payload.get('is_all_day', False)),
        'description': occurrence.payload.get('description', ''),
        'content': occurrence.payload.get('content', ''),
        'priority': occurrence.payload.get('priority', ''),
        'location': occurrence.payload.get('location', ''),
        'status': occurrence.payload.get('status', ''),
        'importance': occurrence.payload.get('importance', ''),
        'urgency': occurrence.payload.get('urgency', ''),
        'group_id': occurrence.payload.get('group_id') or None,
        'is_override': occurrence.is_override,
        'occurrence_ref': {
            'entity_id': ref.entity_id,
            'series_id': ref.series_id or None,
            'recurrence_id': ref.recurrence_id or None,
            'occurrence_start': _serialize_temporal(ref.occurrence_start),
            'source_version': ref.source_version,
        },
    }


def _event_range(event):
    if event.is_all_day:
        return event.start_date, event.end_date
    return event.start_at, event.end_at


def _serialize_temporal(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _occurrence_client_id(entity_type: str, entity_id: str, series_id: str, recurrence_id: str) -> str:
    """仅作客户端列表 key；写命令必须使用 occurrence_ref。"""
    if not series_id:
        return f'{entity_type}:{entity_id}'
    return f'{entity_type}:{entity_id}:series:{series_id}:recurrence:{recurrence_id}'
