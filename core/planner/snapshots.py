"""P4 临时 aggregate before-snapshot、压缩和恢复。"""

from __future__ import annotations

import hashlib
import json
import zlib
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable
from uuid import UUID, uuid4

from django.apps import apps
from django.db import models, transaction
from django.utils import timezone

from agent_service.models import AgentRollbackWindow, AgentTransaction
from core.models import CalendarCollectionVersion, PlannerChangeSet, PlannerRollbackSnapshot
from core.planner.context import PlannerExecutionContext


MODEL_LABELS = (
    'core.EventGroup', 'core.CalendarEvent', 'core.Todo', 'core.Reminder',
    'core.EventRecurrenceSeries', 'core.ReminderRecurrenceSeries',
    'core.EventTag', 'core.TodoTag', 'core.TodoDependency',
    'core.EventReminderLink', 'core.TodoReminderLink', 'core.EventShareGroup',
    'core.ReminderAdvanceTrigger', 'core.EventRecurrenceRDate', 'core.EventRecurrenceExDate',
    'core.EventOccurrenceOverride', 'core.EventRecurrenceSplitReview',
    'core.ReminderRecurrenceRDate', 'core.ReminderRecurrenceExDate',
    'core.ReminderOccurrenceState', 'core.ReminderDeliveryAttempt',
)
RESTORE_ORDER = {label: index for index, label in enumerate(MODEL_LABELS)}
TECHNICAL_FIELDS = {'version', 'created_at', 'updated_at'}


class PlannerSnapshotError(RuntimeError):
    code = 'planner_snapshot_error'


class PlannerRollbackConflict(PlannerSnapshotError):
    code = 'rollback_conflict'


def _model(label: str):
    app_label, model_name = label.split('.', 1)
    return apps.get_model(app_label, model_name)


def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        return {'$type': 'datetime', 'value': value.isoformat()}
    if isinstance(value, date):
        return {'$type': 'date', 'value': value.isoformat()}
    if isinstance(value, UUID):
        return {'$type': 'uuid', 'value': str(value)}
    if isinstance(value, Decimal):
        return {'$type': 'decimal', 'value': str(value)}
    if isinstance(value, bytes):
        return {'$type': 'bytes', 'value': value.hex()}
    if isinstance(value, dict):
        return {str(key): _encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode(item) for item in value]
    if isinstance(value, dict):
        kind = value.get('$type')
        if kind == 'datetime': return datetime.fromisoformat(value['value'])
        if kind == 'date': return date.fromisoformat(value['value'])
        if kind == 'uuid': return UUID(value['value'])
        if kind == 'decimal': return Decimal(value['value'])
        if kind == 'bytes': return bytes.fromhex(value['value'])
        return {key: _decode(item) for key, item in value.items()}
    return value


def _serialize_instance(instance) -> dict[str, Any]:
    fields = {}
    for field in instance._meta.concrete_fields:
        if field.primary_key:
            continue
        name = field.attname if field.is_relation else field.name
        fields[name] = _encode(getattr(instance, name))
    return {'model': instance._meta.label, 'pk': instance.pk, 'fields': fields}


def _row_key(row: dict[str, Any]) -> str:
    return f"{row['model']}:{row['pk']}"


def _canonical_hash(rows: list[dict[str, Any]]) -> str:
    logical = []
    for row in rows:
        logical.append({
            'model': row['model'], 'pk': row['pk'],
            'fields': {key: value for key, value in row['fields'].items() if key not in TECHNICAL_FIELDS},
        })
    raw = json.dumps(sorted(logical, key=_row_key), ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _user_querysets(user):
    filters = {
        'core.EventGroup': {'user': user}, 'core.CalendarEvent': {'user': user},
        'core.Todo': {'user': user}, 'core.Reminder': {'user': user},
        'core.EventRecurrenceSeries': {'user': user}, 'core.ReminderRecurrenceSeries': {'user': user},
        'core.EventTag': {'event__user': user}, 'core.TodoTag': {'todo__user': user},
        'core.TodoDependency': {'todo__user': user}, 'core.EventReminderLink': {'event__user': user},
        'core.TodoReminderLink': {'todo__user': user}, 'core.EventShareGroup': {'event__user': user},
        'core.ReminderAdvanceTrigger': {'reminder__user': user},
        'core.EventRecurrenceRDate': {'series__user': user}, 'core.EventRecurrenceExDate': {'series__user': user},
        'core.EventOccurrenceOverride': {'series__user': user}, 'core.EventRecurrenceSplitReview': {'series__user': user},
        'core.ReminderRecurrenceRDate': {'series__user': user}, 'core.ReminderRecurrenceExDate': {'series__user': user},
        'core.ReminderOccurrenceState': {'series__user': user},
        'core.ReminderDeliveryAttempt': {'occurrence_state__series__user': user},
    }
    return {label: _model(label)._base_manager.filter(**filters[label]) for label in MODEL_LABELS}


def _all_keys(user) -> set[str]:
    result = set()
    for label, queryset in _user_querysets(user).items():
        result.update(f'{label}:{pk}' for pk in queryset.values_list('pk', flat=True))
    return result


def _rows_for_keys(user, keys: set[str]) -> list[dict[str, Any]]:
    by_model: dict[str, list[int]] = {}
    for key in keys:
        label, raw_pk = key.rsplit(':', 1)
        by_model.setdefault(label, []).append(int(raw_pk))
    rows = []
    querysets = _user_querysets(user)
    for label, pks in by_model.items():
        rows.extend(_serialize_instance(item) for item in querysets[label].filter(pk__in=pks))
    return sorted(rows, key=_row_key)


def _aggregate_keys(user, resource_type: str, resource_id: str | None) -> set[str]:
    if not resource_id:
        return set()
    querysets = _user_querysets(user)
    keys = set()

    def add(label: str, queryset):
        keys.update(f'{label}:{pk}' for pk in queryset.values_list('pk', flat=True))

    if resource_type == 'event':
        events = querysets['core.CalendarEvent'].filter(event_id=resource_id)
        add('core.CalendarEvent', events)
        event_pks = list(events.values_list('pk', flat=True))
        series = querysets['core.EventRecurrenceSeries'].filter(master_event_id__in=event_pks)
        add('core.EventRecurrenceSeries', series)
        series_pks = list(series.values_list('pk', flat=True))
        for label in ('core.EventTag', 'core.EventReminderLink', 'core.EventShareGroup'):
            add(label, querysets[label].filter(event_id__in=event_pks))
        for label in ('core.EventRecurrenceRDate', 'core.EventRecurrenceExDate', 'core.EventOccurrenceOverride', 'core.EventRecurrenceSplitReview'):
            add(label, querysets[label].filter(series_id__in=series_pks))
    elif resource_type == 'todo':
        todos = querysets['core.Todo'].filter(todo_id=resource_id)
        add('core.Todo', todos)
        pks = list(todos.values_list('pk', flat=True))
        for label in ('core.TodoTag', 'core.TodoDependency', 'core.TodoReminderLink'):
            add(label, querysets[label].filter(todo_id__in=pks))
    elif resource_type == 'reminder':
        reminders = querysets['core.Reminder'].filter(reminder_id=resource_id)
        add('core.Reminder', reminders)
        pks = list(reminders.values_list('pk', flat=True))
        series = querysets['core.ReminderRecurrenceSeries'].filter(master_reminder_id__in=pks)
        add('core.ReminderRecurrenceSeries', series)
        series_pks = list(series.values_list('pk', flat=True))
        add('core.ReminderAdvanceTrigger', querysets['core.ReminderAdvanceTrigger'].filter(reminder_id__in=pks))
        add(
            'core.ReminderDeliveryAttempt',
            querysets['core.ReminderDeliveryAttempt'].filter(occurrence_state__series_id__in=series_pks),
        )
        for label in ('core.ReminderRecurrenceRDate', 'core.ReminderRecurrenceExDate', 'core.ReminderOccurrenceState'):
            add(label, querysets[label].filter(series_id__in=series_pks))
    elif resource_type == 'group':
        groups = querysets['core.EventGroup'].filter(group_id=resource_id)
        add('core.EventGroup', groups)
        group_pks = list(groups.values_list('pk', flat=True))
        for event_id in querysets['core.CalendarEvent'].filter(group_id__in=group_pks).values_list('event_id', flat=True):
            keys.update(_aggregate_keys(user, 'event', event_id))
        for todo_id in querysets['core.Todo'].filter(group_id__in=group_pks).values_list('todo_id', flat=True):
            keys.update(_aggregate_keys(user, 'todo', todo_id))
    return keys


def _restore_row(row: dict[str, Any]) -> None:
    model = _model(row['model'])
    values = {key: _decode(value) for key, value in row['fields'].items()}
    current = model._base_manager.filter(pk=row['pk']).first()
    current_version = getattr(current, 'version', 0) if current is not None else 0
    for key in ('created_at', 'updated_at'):
        values.pop(key, None)
    snapshot_version = int(values.pop('version', 0) or 0)
    if current is None:
        current = model(pk=row['pk'])
    for key, value in values.items():
        setattr(current, key, value)
    if hasattr(current, 'version'):
        current.version = max(current_version, snapshot_version) + 1
    current.save(force_insert=current._state.adding)


class PlannerSnapshotRecorder:
    @classmethod
    @transaction.atomic
    def execute(
        cls,
        context: PlannerExecutionContext,
        *,
        command_type: str,
        resource_type: str,
        resource_id: str | None,
        operation: Callable[[], Any],
        result_resource_id: Callable[[Any], str | None],
    ) -> Any:
        if not context.reversible:
            return operation()
        window = AgentRollbackWindow.objects.select_for_update().filter(
            window_id=context.rollback_window_id,
            user=context.user,
            session__session_id=context.session_id,
            status=AgentRollbackWindow.STATUS_ACTIVE,
        ).first()
        if window is None or context.message_index is None or context.message_index < window.floor_message_index:
            raise PlannerSnapshotError('当前命令不属于有效 rollback window')
        if AgentTransaction.objects.filter(
            user=context.user, rollback_window=window, tool_call_id=context.tool_call_id
        ).exists():
            raise PlannerSnapshotError('tool_call_id 已记录，拒绝重复执行')

        before_keys = _all_keys(context.user)
        aggregate_before_keys = _aggregate_keys(context.user, resource_type, resource_id)
        before_rows = _rows_for_keys(context.user, aggregate_before_keys)
        result = operation()
        final_resource_id = result_resource_id(result) or resource_id
        after_all_keys = _all_keys(context.user)
        created_keys = after_all_keys - before_keys
        tracked_keys = aggregate_before_keys | created_keys | _aggregate_keys(context.user, resource_type, final_resource_id)
        after_rows = _rows_for_keys(context.user, tracked_keys)
        payload_object = {
            'schema_version': 1,
            'resource_type': resource_type,
            'resource_id': resource_id,
            'before_rows': before_rows,
            'created_keys': sorted(created_keys),
            'tracked_keys': sorted(tracked_keys),
        }
        raw = json.dumps(payload_object, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        compressed = zlib.compress(raw, level=9)
        change_set = PlannerChangeSet.objects.create(
            user=context.user,
            session_id=context.session_id,
            tool_call_id=context.tool_call_id,
            command_type=f'agent.{command_type}',
            source=context.source,
            affected_refs=[{'type': resource_type, 'id': final_resource_id}],
            before_hash=_canonical_hash(before_rows),
            after_hash=_canonical_hash(after_rows),
            rollback_status='available',
        )
        PlannerRollbackSnapshot.objects.create(
            change_set=change_set,
            rollback_window=window,
            payload=compressed,
            payload_sha256=hashlib.sha256(raw).hexdigest(),
            uncompressed_size=len(raw),
        )
        AgentTransaction.objects.create(
            session_id=context.session_id,
            user=context.user,
            action_type=command_type,
            description=f'Planner {command_type}',
            change_set_id=change_set.pk,
            rollback_window=window,
            tool_call_id=context.tool_call_id,
            message_index=context.message_index,
            source=context.source,
            state='applied',
            metadata={'affected_refs': change_set.affected_refs},
        )
        return result

    @staticmethod
    def decode(snapshot: PlannerRollbackSnapshot) -> dict[str, Any]:
        raw = zlib.decompress(bytes(snapshot.payload))
        if hashlib.sha256(raw).hexdigest() != snapshot.payload_sha256:
            raise PlannerSnapshotError('rollback snapshot checksum 不匹配')
        return json.loads(raw.decode('utf-8'))


class PlannerRollbackCoordinator:
    @classmethod
    @transaction.atomic
    def rollback_to_message(
        cls, context: PlannerExecutionContext, message_index: int
    ) -> list[PlannerChangeSet]:
        window = AgentRollbackWindow.objects.select_for_update().filter(
            window_id=context.rollback_window_id, user=context.user,
            session__session_id=context.session_id, status=AgentRollbackWindow.STATUS_ACTIVE,
        ).first()
        if window is None or message_index < window.floor_message_index:
            raise PlannerSnapshotError('rollback window 已失效或消息早于当前回滚起点')
        tool_call_ids = list(
            AgentTransaction.objects.select_for_update().filter(
                user=context.user, rollback_window=window,
                message_index__gte=message_index, state='applied', is_rolled_back=False,
            ).order_by('-created_at', '-pk').values_list('tool_call_id', flat=True)
        )
        return [cls.rollback_tool_call(context, tool_call_id) for tool_call_id in tool_call_ids]

    @classmethod
    @transaction.atomic
    def rollback_tool_call(cls, context: PlannerExecutionContext, tool_call_id: str) -> PlannerChangeSet:
        window = AgentRollbackWindow.objects.select_for_update().filter(
            window_id=context.rollback_window_id, user=context.user,
            session__session_id=context.session_id, status=AgentRollbackWindow.STATUS_ACTIVE,
        ).first()
        if window is None:
            raise PlannerSnapshotError('rollback window 已失效')
        agent_transaction = AgentTransaction.objects.select_for_update().filter(
            user=context.user, rollback_window=window, tool_call_id=tool_call_id,
            state='applied', is_rolled_back=False,
        ).first()
        if agent_transaction is None:
            raise PlannerSnapshotError('未找到可回滚的新版本操作')
        change_set = PlannerChangeSet.objects.select_for_update().get(
            pk=agent_transaction.change_set_id, user=context.user,
            session_id=context.session_id, tool_call_id=tool_call_id,
            rollback_status='available',
        )
        snapshot = PlannerRollbackSnapshot.objects.select_for_update().get(change_set=change_set, rollback_window=window)
        payload = PlannerSnapshotRecorder.decode(snapshot)
        current_rows = _rows_for_keys(context.user, set(payload['tracked_keys']))
        if _canonical_hash(current_rows) != change_set.after_hash:
            raise PlannerRollbackConflict('对象在 Agent 操作后又被修改，拒绝覆盖新数据')

        for key in sorted(payload['created_keys'], key=lambda item: RESTORE_ORDER.get(item.rsplit(':', 1)[0], 999), reverse=True):
            label, raw_pk = key.rsplit(':', 1)
            model = _model(label)
            instance = model._base_manager.filter(pk=int(raw_pk)).first()
            if instance is None:
                continue
            if hasattr(instance, 'deleted_at'):
                instance.deleted_at = timezone.now()
                update_fields = ['deleted_at']
                if hasattr(instance, 'version'):
                    instance.version += 1
                    update_fields.append('version')
                instance.save(update_fields=update_fields)
            else:
                instance.delete()

        for row in sorted(payload['before_rows'], key=lambda item: RESTORE_ORDER.get(item['model'], 999)):
            _restore_row(row)

        for collection in CalendarCollectionVersion.objects.select_for_update().filter(user=context.user):
            collection.version += 1
            collection.sync_token = str(uuid4())
            collection.save(update_fields={'version', 'sync_token', 'updated_at'})
        change_set.rollback_status = 'reverted'
        change_set.is_reverted = True
        change_set.reverted_at = timezone.now()
        change_set.save(update_fields={'rollback_status', 'is_reverted', 'reverted_at', 'updated_at'})
        agent_transaction.state = 'rolled_back'
        agent_transaction.is_rolled_back = True
        agent_transaction.save(update_fields={'state', 'is_rolled_back'})
        snapshot.delete()
        return change_set
