"""所有 Planner 协议入口共享的 use-case 层。

本模块不接收 HTTP request、不调用 View，也不自行实现 ORM/RRule 写算法。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Mapping

from core.models import (
    CalendarEvent, CollaborativeCalendarGroup, EventRecurrenceSeries, EventShareGroup,
    GroupMembership, Reminder, ReminderRecurrenceSeries, Todo,
)
from core.planner.commands import PlannerCommandService
from core.planner.context import PlannerExecutionContext
from core.planner.entities import (
    PlannerEntityCommandService,
    PlannerEntityQueryService,
    serialize_group,
    serialize_reminder,
    serialize_todo,
)
from core.planner.presentation import serialize_event_definition, serialize_occurrence
from core.planner.recurrence.codec import PlannerTimeCodec
from core.planner.repository import PlannerRepository
from core.planner.rollout import PlannerRolloutPolicy, PlannerStorageDecision
from core.planner.snapshots import PlannerSnapshotRecorder


class PlannerApplicationAccessError(PermissionError):
    def __init__(self, *, write: bool, decision: PlannerStorageDecision):
        self.code = (
            'planner_retired_quarantine'
            if decision.reason == 'retired_quarantine'
            else ("planner_normalized_write_not_enabled" if write else "planner_normalized_read_not_enabled")
        )
        self.decision = decision
        super().__init__(
            '该账号的历史 Planner 测试数据已隔离，当前入口不可用。'
            if decision.reason == 'retired_quarantine'
            else '当前用户或入口尚未获准访问 normalized Planner。'
        )


class PlannerApplicationService:
    """面向 Web/Agent/Quick Action/MCP/附件的统一 Planner 用例门面。"""

    @staticmethod
    def require_access(context: PlannerExecutionContext, *, write: bool = False) -> PlannerStorageDecision:
        decision = (
            PlannerRolloutPolicy.can_write_normalized(context.user, context.entrypoint)
            if write
            else PlannerRolloutPolicy.can_read_normalized(context.user, context.entrypoint)
        )
        allowed = {"normalized"} if write else {"shadow", "normalized"}
        if decision.effective_mode not in allowed:
            raise PlannerApplicationAccessError(write=write, decision=decision)
        return decision

    @staticmethod
    def _mutate(
        context: PlannerExecutionContext, *, command_type: str, resource_type: str,
        resource_id: str | None, operation, result_resource_id,
    ):
        return PlannerSnapshotRecorder.execute(
            context,
            command_type=command_type,
            resource_type=resource_type,
            resource_id=resource_id,
            operation=operation,
            result_resource_id=result_resource_id,
        )

    @classmethod
    def list_event_definitions(cls, context: PlannerExecutionContext, *, range_start: datetime, range_end: datetime) -> dict[str, Any]:
        cls.require_access(context)
        items = PlannerRepository.list_event_definitions(context.user, range_start=range_start, range_end=range_end)
        return {
            "range": {"from": range_start.isoformat(), "to": range_end.isoformat()},
            "definitions": [serialize_event_definition(item) for item in items],
            "count": len(items),
        }

    @classmethod
    def build_calendar_feed(cls, context: PlannerExecutionContext, *, feed_type: str) -> bytes:
        cls.require_access(context)
        if feed_type not in {'all', 'events', 'todos', 'reminders'}:
            from core.planner.commands import PlannerCommandError
            raise PlannerCommandError('不支持的 calendar feed type', code='invalid_feed_type')
        from core.planner.calendar_projection import NormalizedCalendarProjectionService
        from core.planner.ical import encode_feed_calendar
        include = lambda value: feed_type in {'all', value}
        return encode_feed_calendar(
            name=f'UniScheduler - {context.user.username}',
            events=NormalizedCalendarProjectionService.event_resources(context.user, feed_titles=True) if include('events') else (),
            todos=NormalizedCalendarProjectionService.todo_feed_resources(context.user) if include('todos') else (),
            reminders=NormalizedCalendarProjectionService.reminder_resources(context.user, feed_titles=True) if include('reminders') else (),
        )

    @classmethod
    def list_calendar_collections(cls, context: PlannerExecutionContext):
        cls.require_access(context)
        from core.planner.caldav import PlannerCalDAVQueryService
        return PlannerCalDAVQueryService.list_collections(context.user)

    @classmethod
    def list_calendar_resources(
        cls, context: PlannerExecutionContext, *, collection_id: str,
        range_start: datetime | None = None, range_end: datetime | None = None,
    ):
        cls.require_access(context)
        from core.planner.caldav import PlannerCalDAVQueryService
        return PlannerCalDAVQueryService.list_resources(
            context.user, collection_id, range_start=range_start, range_end=range_end
        )

    @classmethod
    def get_calendar_resource(cls, context: PlannerExecutionContext, *, collection_id: str, resource_name: str):
        cls.require_access(context)
        from core.planner.caldav import PlannerCalDAVQueryService
        return PlannerCalDAVQueryService.get_resource(context.user, collection_id, resource_name)

    @classmethod
    def get_calendar_collection_version(cls, context: PlannerExecutionContext, *, collection_id: str) -> str:
        cls.require_access(context)
        from core.planner.caldav import PlannerCalDAVQueryService
        return PlannerCalDAVQueryService.collection_ctag(context.user, collection_id)

    @classmethod
    def apply_caldav_event_resource(
        cls, context: PlannerExecutionContext, *, collection_id: str, resource_name: str,
        parsed_object, if_match: str = '', if_none_match: str = '',
    ):
        cls.require_access(context, write=True)
        from core.planner.caldav import PlannerCalDAVCommandService
        return cls._mutate(
            context,
            command_type='caldav.event.put', resource_type='event', resource_id=resource_name,
            operation=lambda: PlannerCalDAVCommandService.apply_event_resource(
                context.user, collection_id=collection_id, resource_name=resource_name,
                parsed=parsed_object, if_match=if_match, if_none_match=if_none_match,
            ),
            result_resource_id=lambda result: result.resource_name,
        )

    @classmethod
    def delete_caldav_event_resource(
        cls, context: PlannerExecutionContext, *, collection_id: str, resource_name: str,
        if_match: str = '',
    ) -> None:
        cls.require_access(context, write=True)
        from core.planner.caldav import PlannerCalDAVCommandService
        return cls._mutate(
            context,
            command_type='caldav.event.delete', resource_type='event', resource_id=resource_name,
            operation=lambda: PlannerCalDAVCommandService.delete_event_resource(
                context.user, collection_id=collection_id, resource_name=resource_name,
                if_match=if_match,
            ),
            result_resource_id=lambda result: resource_name,
        )

    @classmethod
    def list_event_occurrences(cls, context: PlannerExecutionContext, *, range_start: datetime, range_end: datetime) -> dict[str, Any]:
        cls.require_access(context)
        items = PlannerRepository.list_event_occurrences(context.user, range_start=range_start, range_end=range_end)
        share_ids_by_event: dict[str, list[str]] = {}
        for event_id, share_group_id in EventShareGroup.objects.filter(
            event__user=context.user,
            event__event_id__in={item.ref.entity_id for item in items},
            event__deleted_at__isnull=True,
        ).values_list("event__event_id", "share_group__share_group_id"):
            share_ids_by_event.setdefault(event_id, []).append(share_group_id)
        occurrences = []
        for item in items:
            serialized = serialize_occurrence(item)
            serialized["share_group_ids"] = share_ids_by_event.get(item.ref.entity_id, [])
            occurrences.append(serialized)
        return {
            "range": {"from": range_start.isoformat(), "to": range_end.isoformat()},
            "occurrences": occurrences,
            "count": len(items),
        }

    @classmethod
    def list_conflicts(cls, context: PlannerExecutionContext, *, range_start: datetime, range_end: datetime) -> dict[str, Any]:
        cls.require_access(context)
        occurrences = PlannerRepository.list_event_occurrences(context.user, range_start=range_start, range_end=range_end)
        normalized = []
        for occurrence in occurrences:
            start_value, end_value = occurrence.start, occurrence.end
            if isinstance(start_value, date) and not isinstance(start_value, datetime):
                start_value = datetime.combine(start_value, time.min, tzinfo=PlannerTimeCodec.get_timezone())
                end_value = datetime.combine(end_value, time.min, tzinfo=PlannerTimeCodec.get_timezone())
            normalized.append((PlannerTimeCodec.to_utc(start_value), PlannerTimeCodec.to_utc(end_value), occurrence))
        normalized.sort(key=lambda item: (item[0], item[1], item[2].ref.entity_id))
        active, conflicts = [], []
        for start_value, end_value, occurrence in normalized:
            active = [item for item in active if item[1] > start_value]
            for other_start, other_end, other in active:
                conflicts.append({
                    "overlap": {
                        "start": max(start_value, other_start).isoformat(),
                        "end": min(end_value, other_end).isoformat(),
                    },
                    "items": [serialize_occurrence(other), serialize_occurrence(occurrence)],
                })
            active.append((start_value, end_value, occurrence))
        return {"conflicts": conflicts, "count": len(conflicts)}

    @classmethod
    def create_event(cls, context: PlannerExecutionContext, payload: Mapping[str, Any], *, range_start: datetime, range_end: datetime) -> dict[str, Any]:
        cls.require_access(context, write=True)
        def operation():
            event = PlannerCommandService.create_event(context.user, payload)
            items = PlannerRepository.list_event_definitions(
                context.user, range_start=range_start - timedelta(days=1), range_end=range_end + timedelta(days=1)
            )
            item = next(item for item in items if item.event.pk == event.pk)
            return {"event": serialize_event_definition(item)}
        return cls._mutate(
            context, command_type='event.create', resource_type='event', resource_id=None,
            operation=operation, result_resource_id=lambda result: result['event']['event_id'],
        )

    @classmethod
    def patch_event(cls, context: PlannerExecutionContext, event_id: str, payload: Mapping[str, Any], *, scope: str, occurrence_ref: Mapping[str, Any] | None, expected_version: int) -> dict[str, Any]:
        cls.require_access(context, write=True)
        def operation():
            event = PlannerCommandService.patch_event(
                context.user, event_id, payload, scope=scope,
                occurrence_ref=occurrence_ref, expected_version=expected_version,
            )
            return {
                "event_id": event.event_id, "version": event.version,
                "source_version": PlannerCommandService.source_version(event, occurrence_ref), "scope": scope,
            }
        return cls._mutate(
            context, command_type=f'event.patch.{scope}', resource_type='event', resource_id=event_id,
            operation=operation, result_resource_id=lambda result: result['event_id'],
        )

    @classmethod
    def delete_event(cls, context: PlannerExecutionContext, event_id: str, *, scope: str, occurrence_ref: Mapping[str, Any] | None, expected_version: int) -> dict[str, Any]:
        cls.require_access(context, write=True)
        def operation():
            event = PlannerCommandService.delete_event(
                context.user, event_id, scope=scope,
                occurrence_ref=occurrence_ref, expected_version=expected_version,
            )
            return {
                "event_id": event.event_id, "version": event.version,
                "source_version": PlannerCommandService.source_version(event, occurrence_ref),
                "scope": scope, "deleted": True,
            }
        return cls._mutate(
            context, command_type=f'event.delete.{scope}', resource_type='event', resource_id=event_id,
            operation=operation, result_resource_id=lambda result: result['event_id'],
        )

    @classmethod
    def search_items(cls, context: PlannerExecutionContext, *, query: str, requested_types: set[str], range_start: datetime, range_end: datetime, page: int = 1, page_size: int = 50) -> dict[str, Any]:
        cls.require_access(context)
        if requested_types - {"event", "todo", "reminder"}:
            from core.planner.commands import PlannerCommandError
            raise PlannerCommandError("types 仅支持 event、todo、reminder", code="unsupported_search_type")
        if page < 1 or not 1 <= page_size <= 100:
            from core.planner.commands import PlannerCommandError
            raise PlannerCommandError("page 必须大于 0，page_size 必须在 1 到 100", code="invalid_pagination")
        folded = query.strip().casefold()
        event_ids = PlannerRepository.search_event_candidate_ids(context.user, folded) if "event" in requested_types else set()
        occurrences = PlannerRepository.list_event_occurrences(
            context.user, range_start=range_start, range_end=range_end, event_ids=event_ids,
        ) if "event" in requested_types else []
        if folded:
            occurrences = [
                item for item in occurrences
                if folded in " ".join(str(item.payload.get(field, "")) for field in ("title", "description", "location")).casefold()
            ]
        results = [serialize_occurrence(item) for item in occurrences]
        if "todo" in requested_types:
            for todo in PlannerEntityQueryService.list_todos(context.user):
                searchable = f"{todo.title} {todo.description}".casefold()
                due = todo.due_at or todo.due_date
                if isinstance(due, datetime):
                    due_in_range = range_start <= PlannerTimeCodec.to_utc(due) < range_end
                elif isinstance(due, date):
                    due_in_range = range_start.date() <= due < range_end.date()
                else:
                    due_in_range = True
                if due_in_range and (not folded or folded in searchable):
                    results.append(serialize_todo(todo))
        if "reminder" in requested_types:
            for item in PlannerEntityQueryService.list_reminder_occurrences(
                context.user, range_start=range_start, range_end=range_end
            ):
                searchable = f"{item.payload.get('title', '')} {item.payload.get('content', '')}".casefold()
                if not folded or folded in searchable:
                    results.append(serialize_occurrence(item))
        results.sort(key=lambda item: str(item.get("start") or item.get("due") or ""))
        total, offset = len(results), (page - 1) * page_size
        return {
            "range": {"from": range_start.isoformat(), "to": range_end.isoformat()},
            "query": folded,
            "types": sorted(requested_types),
            "page": page,
            "page_size": page_size,
            "total": total,
            "results": results[offset: offset + page_size],
        }

    @classmethod
    def list_groups(cls, context: PlannerExecutionContext) -> dict[str, Any]:
        cls.require_access(context)
        groups = PlannerEntityQueryService.list_groups(context.user)
        return {"groups": [serialize_group(item) for item in groups], "count": len(groups)}

    @classmethod
    def list_share_groups(cls, context: PlannerExecutionContext) -> dict[str, Any]:
        cls.require_access(context)
        owned = CollaborativeCalendarGroup.objects.filter(owner=context.user)
        joined = CollaborativeCalendarGroup.objects.filter(memberships__user=context.user)
        groups = (owned | joined).distinct().order_by('share_group_name', 'share_group_id')
        results = [
            {
                'share_group_id': group.share_group_id,
                'name': group.share_group_name,
                'description': group.share_group_description,
                'color': group.share_group_color,
                'owner_id': group.owner_id,
                'read_only': group.owner_id != context.user.id,
            }
            for group in groups
        ]
        return {'share_groups': results, 'count': len(results)}

    @classmethod
    def resolve_item(cls, context: PlannerExecutionContext, identifier: str, preferred_type: str | None = None) -> dict[str, Any] | None:
        cls.require_access(context)
        candidates = [preferred_type] if preferred_type else ['event', 'todo', 'reminder']
        for item_type in candidates:
            if item_type == 'event':
                item = CalendarEvent.objects.filter(
                    user=context.user, event_id=identifier, deleted_at__isnull=True
                ).first()
                if item:
                    series = EventRecurrenceSeries.objects.filter(master_event=item, deleted_at__isnull=True).first()
                    return {
                        'type': 'event', 'entity_id': item.event_id, 'title': item.title,
                        'source_version': max(item.version, series.version) if series else item.version,
                        'series_id': series.series_id if series else None,
                        'recurrence_id': None, 'occurrence_ref': None,
                    }
            elif item_type == 'todo':
                item = Todo.objects.filter(user=context.user, todo_id=identifier, deleted_at__isnull=True).first()
                if item:
                    return {'type': 'todo', 'entity_id': item.todo_id, 'title': item.title, 'source_version': item.version}
            elif item_type == 'reminder':
                item = Reminder.objects.filter(user=context.user, reminder_id=identifier, deleted_at__isnull=True).first()
                if item:
                    series = ReminderRecurrenceSeries.objects.filter(master_reminder=item, deleted_at__isnull=True).first()
                    return {
                        'type': 'reminder', 'entity_id': item.reminder_id, 'title': item.title,
                        'source_version': max(item.version, series.version) if series else item.version,
                        'series_id': series.series_id if series else None,
                        'recurrence_id': None, 'occurrence_ref': None,
                    }
        return None

    @classmethod
    def get_attachment_item(
        cls, context: PlannerExecutionContext, identifier: str, item_type: str,
        occurrence_ref: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """返回内部附件使用的、可持久化的规范化实体快照。"""
        cls.require_access(context)

        def encoded(value):
            return value.isoformat() if isinstance(value, (date, datetime)) else value

        if occurrence_ref is not None:
            if not isinstance(occurrence_ref, Mapping):
                return None
            if str(occurrence_ref.get('entity_id') or '') != identifier:
                return None
            recurrence_id = str(occurrence_ref.get('recurrence_id') or '')
            series_id = str(occurrence_ref.get('series_id') or '')
            if recurrence_id and series_id and item_type in {'event', 'reminder'}:
                from core.planner.recurrence.codec import PlannerTimeCodec
                anchor = PlannerTimeCodec.parse_recurrence_id(recurrence_id)
                anchor_dt = PlannerTimeCodec.recurrence_datetime(anchor)
                items = (
                    PlannerRepository.list_event_occurrences(
                        context.user, range_start=anchor_dt - timedelta(days=1),
                        range_end=anchor_dt + timedelta(days=2),
                    ) if item_type == 'event' else
                    PlannerEntityQueryService.list_reminder_occurrences(
                        context.user, range_start=anchor_dt - timedelta(days=1),
                        range_end=anchor_dt + timedelta(days=2),
                    )
                )
                occurrence = next((
                    item for item in items
                    if item.ref.entity_id == identifier
                    and item.ref.series_id == series_id
                    and item.ref.recurrence_id == recurrence_id
                ), None)
                if occurrence is None:
                    return None
                item = serialize_occurrence(occurrence)
                payload = occurrence.payload
                return {
                    'type': item_type, 'id': identifier,
                    'title': payload.get('title', ''),
                    'description': payload.get('description', ''),
                    'content': payload.get('content', ''),
                    'location': payload.get('location', ''),
                    'status': payload.get('status', ''),
                    'priority': payload.get('priority', ''),
                    'start': item['start'], 'end': item['end'],
                    'trigger_at': item['start'],
                    'version': item['occurrence_ref']['source_version'],
                    'series_id': series_id, 'recurrence_id': recurrence_id,
                    'occurrence_ref': item['occurrence_ref'],
                }

        if item_type == 'event':
            item = CalendarEvent.objects.filter(
                user=context.user, event_id=identifier, deleted_at__isnull=True
            ).first()
            if item is None:
                return None
            series = EventRecurrenceSeries.objects.filter(
                master_event=item, deleted_at__isnull=True
            ).first()
            return {
                'type': 'event', 'id': item.event_id, 'title': item.title,
                'description': item.description, 'location': item.location,
                'start': encoded(item.start_date if item.is_all_day else item.start_at),
                'end': encoded(item.end_date if item.is_all_day else item.end_at),
                'all_day': item.is_all_day, 'status': item.status,
                'importance': item.importance, 'urgency': item.urgency,
                'version': item.version, 'series_id': series.series_id if series else None,
                'rrule': series.rrule if series else '',
                'recurrence_timezone': series.tzid if series else '',
            }
        if item_type == 'todo':
            item = Todo.objects.filter(user=context.user, todo_id=identifier, deleted_at__isnull=True).first()
            if item is None:
                return None
            return {
                'type': 'todo', 'id': item.todo_id, 'title': item.title,
                'description': item.description, 'status': item.status,
                'due_date': encoded(item.due_date), 'due_at': encoded(item.due_at),
                'importance': item.importance, 'urgency': item.urgency,
                'estimated_duration_seconds': item.estimated_duration_seconds, 'version': item.version,
            }
        if item_type == 'reminder':
            item = Reminder.objects.filter(
                user=context.user, reminder_id=identifier, deleted_at__isnull=True
            ).first()
            if item is None:
                return None
            series = ReminderRecurrenceSeries.objects.filter(
                master_reminder=item, deleted_at__isnull=True
            ).first()
            return {
                'type': 'reminder', 'id': item.reminder_id, 'title': item.title,
                'content': item.content, 'status': item.status,
                'trigger_at': encoded(item.trigger_at), 'priority': item.priority,
                'version': item.version, 'series_id': series.series_id if series else None,
                'rrule': series.rrule if series else '',
                'recurrence_timezone': series.tzid if series else '',
            }
        return None

    @classmethod
    def list_attachment_items(
        cls, context: PlannerExecutionContext, item_type: str, search: str = ''
    ) -> list[dict[str, Any]]:
        """列出附件选择器需要的 master 实体，不展开 recurrence。"""
        cls.require_access(context)
        folded = search.strip().casefold()
        if item_type == 'event':
            items = CalendarEvent.objects.filter(user=context.user, deleted_at__isnull=True).order_by('start_at', 'start_date')
            return [
                {
                    'id': item.event_id, 'title': item.title, 'type': 'event',
                    'subtitle': f"{(item.start_date if item.is_all_day else item.start_at)} ~ {(item.end_date if item.is_all_day else item.end_at)}",
                }
                for item in items if not folded or folded in item.title.casefold()
            ]
        if item_type == 'todo':
            items = Todo.objects.filter(user=context.user, deleted_at__isnull=True).order_by('status', 'due_at', 'due_date')
            return [
                {'id': item.todo_id, 'title': item.title, 'type': 'todo', 'subtitle': item.status}
                for item in items if not folded or folded in item.title.casefold()
            ]
        if item_type == 'reminder':
            items = Reminder.objects.filter(user=context.user, deleted_at__isnull=True).order_by('trigger_at', 'trigger_date')
            return [
                {
                    'id': item.reminder_id, 'title': item.title, 'type': 'reminder',
                    'subtitle': str(item.trigger_at or item.trigger_date or ''),
                }
                for item in items if not folded or folded in item.title.casefold()
            ]
        return []

    @classmethod
    def create_group(cls, context: PlannerExecutionContext, payload: Mapping[str, Any]) -> dict[str, Any]:
        cls.require_access(context, write=True)
        return cls._mutate(
            context, command_type='group.create', resource_type='group', resource_id=None,
            operation=lambda: {"group": serialize_group(PlannerEntityCommandService.create_group(context.user, payload))},
            result_resource_id=lambda result: result['group']['group_id'],
        )

    @classmethod
    def patch_group(cls, context: PlannerExecutionContext, group_id: str, payload: Mapping[str, Any], expected_version: int) -> dict[str, Any]:
        cls.require_access(context, write=True)
        return cls._mutate(
            context, command_type='group.patch', resource_type='group', resource_id=group_id,
            operation=lambda: {"group": serialize_group(PlannerEntityCommandService.patch_group(context.user, group_id, payload, expected_version))},
            result_resource_id=lambda result: result['group']['group_id'],
        )

    @classmethod
    def delete_group(cls, context: PlannerExecutionContext, group_id: str, expected_version: int, *, delete_items: bool) -> dict[str, Any]:
        cls.require_access(context, write=True)
        return cls._mutate(
            context, command_type='group.delete', resource_type='group', resource_id=group_id,
            operation=lambda: {
                "group": serialize_group(PlannerEntityCommandService.delete_group(
                    context.user, group_id, expected_version, delete_items=delete_items
                )), "deleted": True,
            },
            result_resource_id=lambda result: result['group']['group_id'],
        )

    @classmethod
    def list_todos(cls, context: PlannerExecutionContext, *, status_value: str = "", group_id: str = "") -> dict[str, Any]:
        cls.require_access(context)
        todos = PlannerEntityQueryService.list_todos(context.user, status_value=status_value, group_id=group_id)
        return {"todos": [serialize_todo(item) for item in todos], "count": len(todos)}

    @classmethod
    def create_todo(cls, context: PlannerExecutionContext, payload: Mapping[str, Any]) -> dict[str, Any]:
        cls.require_access(context, write=True)
        def operation():
            todo = PlannerEntityCommandService.create_todo(context.user, payload)
            todo = next(item for item in PlannerEntityQueryService.list_todos(context.user) if item.pk == todo.pk)
            return {"todo": serialize_todo(todo)}
        return cls._mutate(
            context, command_type='todo.create', resource_type='todo', resource_id=None,
            operation=operation, result_resource_id=lambda result: result['todo']['todo_id'],
        )

    @classmethod
    def patch_todo(cls, context: PlannerExecutionContext, todo_id: str, payload: Mapping[str, Any], expected_version: int) -> dict[str, Any]:
        cls.require_access(context, write=True)
        return cls._mutate(
            context, command_type='todo.patch', resource_type='todo', resource_id=todo_id,
            operation=lambda: {"todo": serialize_todo(PlannerEntityCommandService.patch_todo(context.user, todo_id, payload, expected_version))},
            result_resource_id=lambda result: result['todo']['todo_id'],
        )

    @classmethod
    def delete_todo(cls, context: PlannerExecutionContext, todo_id: str, expected_version: int) -> dict[str, Any]:
        cls.require_access(context, write=True)
        return cls._mutate(
            context, command_type='todo.delete', resource_type='todo', resource_id=todo_id,
            operation=lambda: {"todo": serialize_todo(PlannerEntityCommandService.delete_todo(context.user, todo_id, expected_version)), "deleted": True},
            result_resource_id=lambda result: result['todo']['todo_id'],
        )

    @classmethod
    def convert_todo(cls, context: PlannerExecutionContext, todo_id: str, payload: Mapping[str, Any], expected_version: int) -> dict[str, Any]:
        cls.require_access(context, write=True)
        def operation():
            todo, event = PlannerEntityCommandService.convert_todo(context.user, todo_id, payload, expected_version)
            return {"todo": serialize_todo(todo), "event_id": event.event_id, "event_version": event.version}
        return cls._mutate(
            context, command_type='todo.convert', resource_type='todo', resource_id=todo_id,
            operation=operation, result_resource_id=lambda result: result['todo']['todo_id'],
        )

    @classmethod
    def list_reminders(cls, context: PlannerExecutionContext) -> dict[str, Any]:
        cls.require_access(context)
        items = PlannerEntityQueryService.list_reminders(context.user)
        return {"reminders": [serialize_reminder(item) for item in items], "count": len(items)}

    @classmethod
    def list_reminder_occurrences(cls, context: PlannerExecutionContext, *, range_start: datetime, range_end: datetime) -> dict[str, Any]:
        cls.require_access(context)
        items = PlannerEntityQueryService.list_reminder_occurrences(context.user, range_start=range_start, range_end=range_end)
        return {"occurrences": [serialize_occurrence(item) for item in items], "count": len(items)}

    @classmethod
    def create_reminder(cls, context: PlannerExecutionContext, payload: Mapping[str, Any]) -> dict[str, Any]:
        cls.require_access(context, write=True)
        return cls._mutate(
            context, command_type='reminder.create', resource_type='reminder', resource_id=None,
            operation=lambda: {"reminder": serialize_reminder(PlannerEntityCommandService.create_reminder(context.user, payload))},
            result_resource_id=lambda result: result['reminder']['reminder_id'],
        )

    @classmethod
    def patch_reminder(
        cls, context: PlannerExecutionContext, reminder_id: str, payload: Mapping[str, Any],
        expected_version: int, *, scope: str = 'all',
        occurrence_ref: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        cls.require_access(context, write=True)
        return cls._mutate(
            context, command_type='reminder.patch', resource_type='reminder', resource_id=reminder_id,
            operation=lambda: {"reminder": serialize_reminder(
                PlannerEntityCommandService.patch_reminder_scope(
                    context.user, reminder_id, payload, expected_version,
                    scope=scope, occurrence_ref=occurrence_ref,
                )
            )},
            result_resource_id=lambda result: result['reminder']['reminder_id'],
        )

    @classmethod
    def delete_reminder(
        cls, context: PlannerExecutionContext, reminder_id: str, expected_version: int,
        *, scope: str = 'all', occurrence_ref: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        cls.require_access(context, write=True)
        return cls._mutate(
            context, command_type='reminder.delete', resource_type='reminder', resource_id=reminder_id,
            operation=lambda: {"reminder": serialize_reminder(
                PlannerEntityCommandService.delete_reminder_scope(
                    context.user, reminder_id, expected_version,
                    scope=scope, occurrence_ref=occurrence_ref,
                )
            ), "deleted": True},
            result_resource_id=lambda result: result['reminder']['reminder_id'],
        )

    @classmethod
    def act_on_reminder_occurrence(cls, context: PlannerExecutionContext, payload: Mapping[str, Any]) -> dict[str, Any]:
        cls.require_access(context, write=True)
        ref = payload.get('occurrence_ref') if isinstance(payload, Mapping) else None
        reminder_id = str(ref.get('entity_id') or '') if isinstance(ref, Mapping) else ''
        return cls._mutate(
            context, command_type=f"reminder.{payload.get('action', 'action')}",
            resource_type='reminder', resource_id=reminder_id,
            operation=lambda: PlannerEntityCommandService.act_on_reminder_occurrence(context.user, payload),
            result_resource_id=lambda result: result['reminder_id'],
        )

    @classmethod
    def list_shared_occurrences(cls, context: PlannerExecutionContext, *, share_group_id: str, range_start: datetime, range_end: datetime) -> dict[str, Any]:
        cls.require_access(context)
        from core.planner.commands import PlannerCommandError
        group = CollaborativeCalendarGroup.objects.filter(share_group_id=share_group_id).first()
        if group is None:
            raise PlannerCommandError("共享组不存在", code="share_group_not_found")
        membership = GroupMembership.objects.filter(share_group=group, user=context.user).first()
        if group.owner_id != context.user.id and membership is None:
            raise PlannerApplicationAccessError(
                write=False,
                decision=PlannerStorageDecision("normalized", "forbidden", "share_group_forbidden"),
            )
        links = EventShareGroup.objects.filter(share_group=group, event__deleted_at__isnull=True).select_related("event__user")
        ids_by_owner, owners, event_meta = {}, {}, {}
        for link in links:
            ids_by_owner.setdefault(link.event.user_id, set()).add(link.event.event_id)
            owners[link.event.user_id] = link.event.user
            series = EventRecurrenceSeries.objects.filter(master_event=link.event, deleted_at__isnull=True).first()
            event_meta[link.event.event_id] = {
                "rrule": (series.rrule_canonical or series.rrule) if series else "",
                "series_id": series.series_id if series else None,
                "master_start": (link.event.start_date or link.event.start_at).isoformat(),
                "master_end": (link.event.end_date or link.event.end_at).isoformat(),
                "share_group_ids": list(link.event.share_links.values_list("share_group__share_group_id", flat=True)),
            }
        results = []
        for owner_id, event_ids in ids_by_owner.items():
            occurrences = PlannerRepository.list_event_occurrences(
                owners[owner_id], range_start=range_start, range_end=range_end, event_ids=event_ids
            )
            owner_membership = GroupMembership.objects.filter(share_group=group, user_id=owner_id).first()
            for occurrence in occurrences:
                item = serialize_occurrence(occurrence)
                item.update({
                    "read_only": owner_id != context.user.id,
                    "owner_id": owner_id,
                    "owner_username": owners[owner_id].username,
                    "member_color": owner_membership.member_color if owner_membership else group.share_group_color,
                    "share_group_id": group.share_group_id,
                    **event_meta[occurrence.ref.entity_id],
                })
                results.append(item)
        results.sort(key=lambda item: item["start"])
        members = [
            {"user_id": item.user_id, "username": item.user.username, "color": item.member_color}
            for item in GroupMembership.objects.filter(share_group=group).select_related("user")
        ]
        return {
            "occurrences": results,
            "count": len(results),
            "read_only": group.owner_id != context.user.id,
            "current_user_id": context.user.id,
            "members": members,
        }
