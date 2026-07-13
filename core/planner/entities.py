"""Planner v2 Todo、Reminder 与 EventGroup 的 normalized query/command。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping
from uuid import uuid4

from dateutil.rrule import rrulestr
from django.contrib.auth.models import User
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from core.models import (
    CalendarChange,
    CalendarCollectionVersion,
    CalendarEvent,
    EventGroup,
    PlannerChangeSet,
    Reminder,
    ReminderOccurrenceState,
    ReminderRecurrenceExDate,
    ReminderRecurrenceRDate,
    ReminderRecurrenceSeries,
    Todo,
    TodoDependency,
    TodoTag,
)
from core.planner.commands import PlannerCommandError, PlannerCommandService, PlannerCommandVersionConflict
from core.planner.calendar_changes import CalendarCollectionChangeWriter
from core.planner.recurrence.codec import InvalidRRuleError, PlannerTimeCodec, canonicalize_rrule
from core.planner.recurrence.expander import Occurrence, OccurrenceOverride, OccurrenceRef, RecurrenceDefinition, RecurrenceExpander
from logger import logger


def serialize_group(group: EventGroup) -> dict[str, Any]:
    return {
        'group_id': group.group_id,
        'version': group.version,
        'name': group.name,
        'description': group.description,
        'color': group.color,
        'group_type': group.group_type,
        'default_importance': group.default_importance,
        'default_urgency': group.default_urgency,
        'default_duration_seconds': group.default_duration_seconds,
        'working_hours': group.working_hours,
    }


def serialize_todo(todo: Todo) -> dict[str, Any]:
    return {
        'entity_type': 'todo',
        'todo_id': todo.todo_id,
        'version': todo.version,
        'title': todo.title,
        'description': todo.description,
        'status': todo.status,
        'importance': todo.importance,
        'urgency': todo.urgency,
        'priority_score': todo.priority_score,
        'estimated_duration_seconds': todo.estimated_duration_seconds,
        'group_id': todo.group.group_id if todo.group else None,
        'due': (todo.due_at or todo.due_date).isoformat() if (todo.due_at or todo.due_date) else None,
        'tags': [link.tag for link in todo.tag_links.all()],
        'dependencies': [link.depends_on.todo_id for link in todo.dependency_links.all()],
        'converted_to_event_id': todo.converted_to_event.event_id if todo.converted_to_event else None,
    }


def serialize_reminder(reminder: Reminder) -> dict[str, Any]:
    recurrence = ReminderRecurrenceSeries.objects.filter(master_reminder=reminder, deleted_at__isnull=True).first()
    return {
        'entity_type': 'reminder',
        'reminder_id': reminder.reminder_id,
        'version': reminder.version,
        'title': reminder.title,
        'content': reminder.content,
        'priority': reminder.priority,
        'status': reminder.status,
        'tzid': reminder.tzid,
        'trigger': (reminder.trigger_at or reminder.trigger_date).isoformat() if (reminder.trigger_at or reminder.trigger_date) else None,
        'snooze_until': reminder.snooze_until.isoformat() if reminder.snooze_until else None,
        'notification_sent_at': reminder.notification_sent_at.isoformat() if reminder.notification_sent_at else None,
        'recurrence': None if recurrence is None else {
            'series_id': recurrence.series_id,
            'rrule': recurrence.rrule_canonical or recurrence.rrule,
            'tzid': recurrence.tzid,
            'source_version': max(reminder.version, recurrence.version),
        },
    }


class PlannerEntityQueryService:
    @staticmethod
    def list_groups(user: User) -> list[EventGroup]:
        return list(EventGroup.objects.filter(user=user, deleted_at__isnull=True).order_by('name', 'id'))

    @staticmethod
    def list_todos(user: User, *, status_value: str = '', group_id: str = '') -> list[Todo]:
        queryset = Todo.objects.filter(user=user, deleted_at__isnull=True).select_related('group', 'converted_to_event').prefetch_related(
            'tag_links', 'dependency_links__depends_on'
        )
        if status_value:
            queryset = queryset.filter(status=status_value)
        if group_id:
            queryset = queryset.filter(group__group_id=group_id)
        return list(queryset.order_by('due_at', 'due_date', 'id'))

    @staticmethod
    def list_reminders(user: User) -> list[Reminder]:
        return list(Reminder.objects.filter(user=user, deleted_at__isnull=True).order_by('trigger_at', 'trigger_date', 'id'))

    @classmethod
    def list_reminder_occurrences(cls, user: User, *, range_start: datetime, range_end: datetime) -> list[Occurrence]:
        results: list[Occurrence] = []
        singles = Reminder.objects.filter(
            user=user, deleted_at__isnull=True,
        ).filter(
            Q(recurrence_series__isnull=True) | Q(recurrence_series__deleted_at__isnull=False)
        ).filter(Q(trigger_at__gte=range_start, trigger_at__lt=range_end) | Q(trigger_date__gte=range_start.date(), trigger_date__lt=range_end.date()))
        for reminder in singles:
            start = reminder.trigger_at or reminder.trigger_date
            if start is None:
                continue
            end = start + (timedelta(seconds=1) if isinstance(start, datetime) else timedelta(days=1))
            results.append(
                Occurrence(
                    ref=OccurrenceRef('reminder', reminder.reminder_id, '', '', start, reminder.version),
                    start=start,
                    end=end,
                    payload={'title': reminder.title, 'content': reminder.content, 'status': reminder.status, 'priority': reminder.priority},
                    is_override=False,
                )
            )
        series_rows = ReminderRecurrenceSeries.objects.filter(
            user=user, deleted_at__isnull=True, master_reminder__deleted_at__isnull=True
        ).select_related('master_reminder').prefetch_related('exdates', 'rdates', 'occurrence_states')
        for series in series_rows:
            master = series.master_reminder
            dtstart = series.dtstart_at or series.dtstart_date
            if dtstart is None:
                continue
            definition = RecurrenceDefinition(
                entity_type='reminder', entity_id=master.reminder_id, series_id=series.series_id,
                dtstart=dtstart,
                duration=timedelta(seconds=1) if isinstance(dtstart, datetime) else timedelta(days=1),
                rrule=series.rrule_canonical or series.rrule, tzid=series.tzid,
                source_version=max(master.version, series.version),
                payload={'title': master.title, 'content': master.content, 'status': master.status, 'priority': master.priority},
                rdates=tuple((item.starts_at or item.starts_date) for item in series.rdates.all() if (item.starts_at or item.starts_date)),
                exdates=frozenset(item.recurrence_id for item in series.exdates.all()),
            )
            overrides = []
            for state in series.occurrence_states.filter(deleted_at__isnull=True):
                patch = {**state.patch, 'status': state.status}
                effective = state.effective_trigger_at
                overrides.append(
                    OccurrenceOverride(
                        recurrence_id=state.recurrence_id,
                        kind='cancelled' if state.status in {'dismissed', 'cancelled'} else 'modified',
                        patch=patch,
                        effective_start=effective,
                        effective_end=effective + timedelta(seconds=1) if effective else None,
                        version=state.version,
                    )
                )
            results.extend(RecurrenceExpander.expand(definition, range_start=range_start, range_end=range_end, overrides=overrides))
        return sorted(results, key=lambda item: PlannerTimeCodec.recurrence_datetime(item.start))


class PlannerEntityCommandService:
    @classmethod
    @transaction.atomic
    def create_group(cls, user: User, payload: Mapping[str, Any]) -> EventGroup:
        name = str(payload.get('name') or '').strip()
        if not name:
            raise PlannerCommandError('name 为必填', code='invalid_group')
        group = EventGroup.objects.create(
            user=user,
            name=name,
            description=str(payload.get('description') or ''),
            color=str(payload.get('color') or '#3498db'),
            group_type=str(payload.get('group_type') or 'other'),
            default_importance=str(payload.get('default_importance') or ''),
            default_urgency=str(payload.get('default_urgency') or ''),
            default_duration_seconds=payload.get('default_duration_seconds'),
            working_hours=payload.get('working_hours') or {},
        )
        cls._record(user, 'group', group.group_id, group.version, 'group.create', CalendarChange.ACTION_CREATE)
        return group

    @classmethod
    @transaction.atomic
    def patch_group(cls, user: User, group_id: str, payload: Mapping[str, Any], expected_version: int) -> EventGroup:
        group = EventGroup.objects.select_for_update().filter(user=user, group_id=group_id, deleted_at__isnull=True).first()
        if group is None:
            raise PlannerCommandError('未找到 group', code='group_not_found')
        cls._require_version(group, expected_version)
        allowed = {'name', 'description', 'color', 'group_type', 'default_importance', 'default_urgency', 'default_duration_seconds', 'working_hours'}
        fields = set(payload) & allowed
        if not fields:
            raise PlannerCommandError('没有可修改字段', code='empty_patch')
        for field in fields:
            setattr(group, field, payload[field])
        group.bump_version(update_fields=fields)
        cls._record(user, 'group', group.group_id, group.version, 'group.patch', CalendarChange.ACTION_UPDATE)
        return group

    @classmethod
    @transaction.atomic
    def delete_group(cls, user: User, group_id: str, expected_version: int, *, delete_items: bool = False) -> EventGroup:
        group = EventGroup.objects.select_for_update().filter(user=user, group_id=group_id, deleted_at__isnull=True).first()
        if group is None:
            raise PlannerCommandError('未找到 group', code='group_not_found')
        cls._require_version(group, expected_version)
        affected_events = list(
            CalendarEvent.objects.filter(user=user, group=group, deleted_at__isnull=True)
            .select_related('recurrence_series')
        )
        if delete_items:
            now = timezone.now()
            CalendarEvent.objects.filter(user=user, group=group, deleted_at__isnull=True).update(deleted_at=now, version=models.F('version') + 1)
            Todo.objects.filter(user=user, group=group, deleted_at__isnull=True).update(deleted_at=now, version=models.F('version') + 1)
        else:
            CalendarEvent.objects.filter(user=user, group=group).update(group=None)
            Todo.objects.filter(user=user, group=group).update(group=None)
        group.soft_delete(expected_version=group.version)
        for event in affected_events:
            series = getattr(event, 'recurrence_series', None)
            resource_name = (
                series.caldav_resource_name
                if series is not None and series.deleted_at is None
                else event.caldav_resource_name
            )
            CalendarCollectionChangeWriter.record(
                user, collection_id=group_id, resource_type='event',
                resource_public_id=resource_name,
                action=CalendarChange.ACTION_DELETE, etag=f'event:{resource_name}:{event.version + 1}',
            )
            if not delete_items:
                CalendarCollectionChangeWriter.record(
                    user, collection_id='default', resource_type='event',
                    resource_public_id=resource_name,
                    action=CalendarChange.ACTION_CREATE, etag=f'event:{resource_name}:{event.version}',
                )
        cls._record(user, 'group', group.group_id, group.version, 'group.delete', CalendarChange.ACTION_DELETE)
        return group

    @classmethod
    @transaction.atomic
    def create_todo(cls, user: User, payload: Mapping[str, Any]) -> Todo:
        title = str(payload.get('title') or '').strip()
        if not title:
            raise PlannerCommandError('title 为必填', code='invalid_title')
        due_at, due_date, tzid = cls._parse_optional_temporal(payload.get('due'), payload.get('tzid'))
        todo = Todo.objects.create(
            user=user, title=title, description=str(payload.get('description') or ''),
            status=str(payload.get('status') or 'pending'), importance=str(payload.get('importance') or ''),
            urgency=str(payload.get('urgency') or ''), priority_score=int(payload.get('priority_score') or 0),
            estimated_duration_seconds=payload.get('estimated_duration_seconds'), tzid=tzid,
            due_at=due_at, due_date=due_date, group=cls._group(user, payload.get('group_id')),
        )
        cls._replace_todo_relations(user, todo, payload)
        cls._record(user, 'todo', todo.todo_id, todo.version, 'todo.create', CalendarChange.ACTION_CREATE)
        return todo

    @classmethod
    @transaction.atomic
    def patch_todo(cls, user: User, todo_id: str, payload: Mapping[str, Any], expected_version: int) -> Todo:
        todo = cls._todo(user, todo_id, lock=True)
        cls._require_version(todo, expected_version)
        scalar = {'title', 'description', 'status', 'importance', 'urgency', 'priority_score', 'estimated_duration_seconds'}
        fields = set(payload) & scalar
        for field in fields:
            setattr(todo, field, payload[field])
        if 'group_id' in payload:
            todo.group = cls._group(user, payload.get('group_id'))
            fields.add('group')
        if 'due' in payload:
            todo.due_at, todo.due_date, todo.tzid = cls._parse_optional_temporal(payload.get('due'), payload.get('tzid') or todo.tzid)
            fields.update({'due_at', 'due_date', 'tzid'})
        relations_changed = cls._replace_todo_relations(user, todo, payload)
        if fields or relations_changed:
            todo.bump_version(update_fields=fields)
        cls._record(user, 'todo', todo.todo_id, todo.version, 'todo.patch', CalendarChange.ACTION_UPDATE)
        return todo

    @classmethod
    @transaction.atomic
    def delete_todo(cls, user: User, todo_id: str, expected_version: int) -> Todo:
        todo = cls._todo(user, todo_id, lock=True)
        cls._require_version(todo, expected_version)
        todo.soft_delete(expected_version=todo.version)
        cls._record(user, 'todo', todo.todo_id, todo.version, 'todo.delete', CalendarChange.ACTION_DELETE)
        return todo

    @classmethod
    @transaction.atomic
    def convert_todo(cls, user: User, todo_id: str, payload: Mapping[str, Any], expected_version: int) -> tuple[Todo, CalendarEvent]:
        todo = cls._todo(user, todo_id, lock=True)
        cls._require_version(todo, expected_version)
        if todo.converted_to_event_id:
            raise PlannerCommandError('todo 已转换为 event', code='todo_already_converted')
        event_payload = {
            'title': payload.get('title') or todo.title,
            'description': payload.get('description', todo.description),
            'importance': todo.importance,
            'urgency': todo.urgency,
            'group_id': payload.get('group_id') or (todo.group.group_id if todo.group else None),
            'start': payload.get('start'),
            'end': payload.get('end'),
            'is_all_day': bool(payload.get('is_all_day', False)),
            'tzid': payload.get('tzid') or todo.tzid,
        }
        if payload.get('recurrence') is not None:
            event_payload['recurrence'] = payload['recurrence']
        event = PlannerCommandService.create_event(user, event_payload)
        todo.converted_to_event = event
        todo.status = 'completed'
        todo.bump_version(update_fields={'converted_to_event', 'status'})
        cls._record(user, 'todo', todo.todo_id, todo.version, 'todo.convert', CalendarChange.ACTION_UPDATE)
        return todo, event

    @classmethod
    @transaction.atomic
    def create_reminder(cls, user: User, payload: Mapping[str, Any]) -> Reminder:
        title = str(payload.get('title') or '').strip()
        if not title:
            raise PlannerCommandError('title 为必填', code='invalid_title')
        trigger_at, trigger_date, tzid = cls._parse_optional_temporal(payload.get('trigger'), payload.get('tzid'))
        if trigger_at is None and trigger_date is None:
            raise PlannerCommandError('trigger 为必填', code='invalid_time_range')
        reminder = Reminder.objects.create(
            user=user, title=title, content=str(payload.get('content') or ''),
            priority=str(payload.get('priority') or 'normal'), status=str(payload.get('status') or 'active'),
            tzid=tzid, trigger_at=trigger_at, trigger_date=trigger_date,
        )
        recurrence = payload.get('recurrence')
        if recurrence is not None:
            if not isinstance(recurrence, Mapping):
                raise PlannerCommandError('recurrence 必须是 object', code='invalid_recurrence')
            dtstart = trigger_at or trigger_date
            try:
                canonical = canonicalize_rrule(str(recurrence.get('rrule') or ''), dtstart=dtstart, tzid=tzid)
            except InvalidRRuleError as exc:
                raise PlannerCommandError(str(exc), code='invalid_rrule') from exc
            ReminderRecurrenceSeries.objects.create(
                user=user, series_id=str(recurrence.get('series_id') or uuid4()), master_reminder=reminder,
                ical_uid=str(recurrence.get('ical_uid') or f'{reminder.reminder_id}@planner.local'),
                rrule=str(recurrence['rrule']), rrule_canonical=canonical,
                dtstart_at=trigger_at, dtstart_date=trigger_date, tzid=tzid,
            )
        cls._record(user, 'reminder', reminder.reminder_id, reminder.version, 'reminder.create', CalendarChange.ACTION_CREATE)
        return reminder

    @classmethod
    @transaction.atomic
    def patch_reminder(cls, user: User, reminder_id: str, payload: Mapping[str, Any], expected_version: int) -> Reminder:
        return cls.patch_reminder_scope(
            user, reminder_id, payload, expected_version,
            scope=str(payload.get('scope') or 'all'),
            occurrence_ref=payload.get('occurrence_ref'),
        )

    @classmethod
    @transaction.atomic
    def delete_reminder(cls, user: User, reminder_id: str, expected_version: int) -> Reminder:
        return cls.delete_reminder_scope(user, reminder_id, expected_version, scope='all', occurrence_ref=None)

    @classmethod
    @transaction.atomic
    def patch_reminder_scope(
        cls, user: User, reminder_id: str, payload: Mapping[str, Any], expected_version: int,
        *, scope: str, occurrence_ref: Mapping[str, Any] | None,
    ) -> Reminder:
        reminder = cls._reminder(user, reminder_id, lock=True)
        series = cls._reminder_series(reminder)
        if series is None:
            if scope not in {'single', 'all'}:
                raise PlannerCommandError('非重复 reminder 仅支持 single 或 all scope', code='invalid_scope')
            cls._require_version(reminder, expected_version)
            fields = cls._apply_reminder_master_fields(reminder, payload)
            recurrence = payload.get('recurrence') if 'recurrence' in payload else None
            if fields or recurrence is not None:
                reminder.bump_version(update_fields=fields)
            if recurrence is not None:
                cls._create_reminder_series(user, reminder, recurrence)
            cls._record(user, 'reminder', reminder.reminder_id, reminder.version,
                        'reminder.attach_recurrence' if recurrence is not None else 'reminder.patch',
                        CalendarChange.ACTION_UPDATE)
            return reminder

        if scope == 'all':
            cls._require_reminder_source_version(expected_version, reminder, series)
            old_trigger = reminder.trigger_at or reminder.trigger_date
            fields = cls._apply_reminder_master_fields(reminder, payload)
            new_trigger = reminder.trigger_at or reminder.trigger_date
            if 'trigger' in payload and cls._local_date(old_trigger, reminder.tzid) != cls._local_date(new_trigger, reminder.tzid):
                raise PlannerCommandError('all scope 只允许修改提醒时刻，不允许修改系列起始日期', code='series_date_change_forbidden')
            recurrence_specified = 'recurrence' in payload
            recurrence = payload.get('recurrence')
            if fields or recurrence_specified:
                reminder.bump_version(update_fields=fields)
            if recurrence_specified and recurrence is None:
                series.soft_delete(expected_version=series.version)
            elif recurrence_specified:
                cls._update_reminder_series(series, reminder, recurrence)
            elif 'trigger' in payload:
                cls._rewrite_reminder_series_time(series, reminder, old_trigger)
            cls._record(user, 'reminder', reminder.reminder_id, reminder.version,
                        'reminder.patch_all', CalendarChange.ACTION_UPDATE)
            return reminder

        recurrence_id = cls._require_reminder_occurrence_ref(reminder, series, occurrence_ref)
        state = ReminderOccurrenceState.objects.select_for_update().filter(
            series=series, recurrence_id=recurrence_id, deleted_at__isnull=True
        ).first()
        cls._require_reminder_source_version(expected_version, reminder, series, state)
        cls._ensure_reminder_slot(series, recurrence_id)
        if scope == 'this_and_future':
            return cls._split_reminder(user, reminder, series, recurrence_id, payload)
        if scope != 'single':
            raise PlannerCommandError('scope 必须是 single、all 或 this_and_future', code='invalid_scope')
        if 'recurrence' in payload:
            raise PlannerCommandError('single occurrence 不支持修改 recurrence', code='unsupported_relation_scope')
        patch = {key: payload[key] for key in {'title', 'content', 'priority'} if key in payload}
        effective = None
        if 'trigger' in payload:
            effective, trigger_date, _ = cls._parse_optional_temporal(payload['trigger'], payload.get('tzid') or reminder.tzid)
            if effective is None or trigger_date is not None:
                raise PlannerCommandError('Reminder occurrence trigger 必须是 DATE-TIME', code='invalid_time_range')
        if not patch and effective is None and 'status' not in payload:
            raise PlannerCommandError('single scope 至少需要一个可修改字段', code='empty_patch')
        if state is None:
            state = ReminderOccurrenceState.objects.create(
                series=series, recurrence_id=recurrence_id,
                status=str(payload.get('status') or 'active'), patch=patch,
                effective_trigger_at=effective,
            )
        else:
            state.patch = {**state.patch, **patch}
            if effective is not None:
                state.effective_trigger_at = effective
            if 'status' in payload:
                state.status = str(payload['status'])
            state.bump_version(update_fields={'patch', 'effective_trigger_at', 'status'})
        cls._record(user, 'reminder', reminder.reminder_id, state.version,
                    'reminder.patch_single', CalendarChange.ACTION_UPDATE)
        return reminder

    @classmethod
    @transaction.atomic
    def delete_reminder_scope(
        cls, user: User, reminder_id: str, expected_version: int,
        *, scope: str, occurrence_ref: Mapping[str, Any] | None,
    ) -> Reminder:
        reminder = cls._reminder(user, reminder_id, lock=True)
        series = cls._reminder_series(reminder)
        if series is None:
            if scope not in {'single', 'all'}:
                raise PlannerCommandError('非重复 reminder 不支持 future scope', code='invalid_scope')
            cls._require_version(reminder, expected_version)
            reminder.soft_delete(expected_version=reminder.version)
            cls._record(user, 'reminder', reminder.reminder_id, reminder.version, 'reminder.delete', CalendarChange.ACTION_DELETE)
            return reminder
        recurrence_id = None
        state = None
        if scope != 'all':
            recurrence_id = cls._require_reminder_occurrence_ref(reminder, series, occurrence_ref)
            state = ReminderOccurrenceState.objects.select_for_update().filter(
                series=series, recurrence_id=recurrence_id, deleted_at__isnull=True
            ).first()
        cls._require_reminder_source_version(expected_version, reminder, series, state)
        if scope == 'all':
            reminder.soft_delete(expected_version=reminder.version)
            series.soft_delete(expected_version=series.version)
            command = 'reminder.delete_all'
        elif scope == 'this_and_future':
            cls._ensure_reminder_slot(series, recurrence_id)
            cls._truncate_reminder_series(reminder, series, recurrence_id)
            command = 'reminder.delete_this_and_future'
        elif scope == 'single':
            cls._ensure_reminder_slot(series, recurrence_id)
            if state is None:
                ReminderOccurrenceState.objects.create(
                    series=series, recurrence_id=recurrence_id, status='cancelled'
                )
            else:
                state.status = 'cancelled'
                state.patch = {}
                state.bump_version(update_fields={'status', 'patch'})
            command = 'reminder.delete_single'
        else:
            raise PlannerCommandError('scope 必须是 single、all 或 this_and_future', code='invalid_scope')
        cls._record(user, 'reminder', reminder.reminder_id, reminder.version, command, CalendarChange.ACTION_DELETE)
        return reminder

    @classmethod
    @transaction.atomic
    def act_on_reminder_occurrence(cls, user: User, payload: Mapping[str, Any]) -> dict[str, Any]:
        ref = payload.get('occurrence_ref')
        if not isinstance(ref, Mapping):
            raise PlannerCommandError('occurrence_ref 为必填', code='occurrence_not_found')
        reminder = cls._reminder(user, str(ref.get('entity_id') or ''), lock=True)
        action = str(payload.get('action') or '')
        if action not in {'complete', 'dismiss', 'snooze', 'mark_sent', 'reset'}:
            raise PlannerCommandError('不支持的 reminder action', code='invalid_action')
        expected_version = int(payload.get('expected_version') or 0)
        series = ReminderRecurrenceSeries.objects.select_for_update().filter(master_reminder=reminder, deleted_at__isnull=True).first()
        if series is None:
            cls._require_version(reminder, expected_version)
            if action == 'complete': reminder.status = 'completed'
            elif action == 'dismiss': reminder.status = 'dismissed'
            elif action == 'snooze': reminder.snooze_until = cls._required_datetime(payload.get('snooze_until'), reminder.tzid)
            elif action == 'mark_sent': reminder.notification_sent_at = timezone.now()
            else:
                reminder.status = 'active'
                reminder.snooze_until = None
            reminder.bump_version(update_fields={'status', 'snooze_until', 'notification_sent_at'})
            cls._record(user, 'reminder', reminder.reminder_id, reminder.version, f'reminder.{action}', CalendarChange.ACTION_UPDATE)
            return {'reminder_id': reminder.reminder_id, 'source_version': reminder.version, 'action': action}
        if ref.get('series_id') != series.series_id or not ref.get('recurrence_id'):
            raise PlannerCommandError('occurrence_ref 不属于 reminder series', code='occurrence_not_found')
        state, _ = ReminderOccurrenceState.objects.select_for_update().get_or_create(
            series=series, recurrence_id=str(ref['recurrence_id'])
        )
        actual = max(reminder.version, series.version, state.version)
        if expected_version != actual:
            raise PlannerCommandVersionConflict(f'版本冲突: expected={expected_version}, actual={actual}')
        if action == 'complete': state.status = 'completed'
        elif action == 'dismiss': state.status = 'dismissed'
        elif action == 'snooze':
            state.status = 'snoozed'
            state.snooze_until = cls._required_datetime(payload.get('snooze_until'), reminder.tzid)
            state.effective_trigger_at = state.snooze_until
        elif action == 'mark_sent': state.notification_sent_at = state.notification_sent_at or timezone.now()
        else:
            state.status = 'active'
            state.snooze_until = None
            state.effective_trigger_at = None
        state.bump_version(update_fields={'status', 'snooze_until', 'effective_trigger_at', 'notification_sent_at'})
        cls._record(user, 'reminder', reminder.reminder_id, state.version, f'reminder.{action}_occurrence', CalendarChange.ACTION_UPDATE)
        return {'reminder_id': reminder.reminder_id, 'series_id': series.series_id, 'recurrence_id': state.recurrence_id, 'source_version': max(reminder.version, series.version, state.version), 'action': action}

    @classmethod
    def _apply_reminder_master_fields(cls, reminder: Reminder, payload: Mapping[str, Any]) -> set[str]:
        fields = set(payload) & {'title', 'content', 'priority', 'status'}
        if 'title' in fields and not str(payload['title']).strip():
            raise PlannerCommandError('title 不能为空', code='invalid_title')
        for field in fields:
            setattr(reminder, field, str(payload[field]))
        if 'trigger' in payload:
            reminder.trigger_at, reminder.trigger_date, reminder.tzid = cls._parse_optional_temporal(
                payload['trigger'], payload.get('tzid') or reminder.tzid
            )
            if reminder.trigger_at is None and reminder.trigger_date is None:
                raise PlannerCommandError('trigger 不能为空', code='invalid_time_range')
            fields.update({'trigger_at', 'trigger_date', 'tzid'})
        return fields

    @classmethod
    def _create_reminder_series(
        cls, user: User, reminder: Reminder, recurrence: Mapping[str, Any]
    ) -> ReminderRecurrenceSeries:
        if not isinstance(recurrence, Mapping):
            raise PlannerCommandError('recurrence 必须是 object', code='invalid_recurrence')
        dtstart = reminder.trigger_at or reminder.trigger_date
        try:
            canonical = canonicalize_rrule(str(recurrence.get('rrule') or ''), dtstart=dtstart, tzid=reminder.tzid)
        except InvalidRRuleError as exc:
            raise PlannerCommandError(str(exc), code='invalid_rrule') from exc
        return ReminderRecurrenceSeries.objects.create(
            user=user, master_reminder=reminder,
            series_id=str(recurrence.get('series_id') or uuid4()),
            ical_uid=str(recurrence.get('ical_uid') or f'{reminder.reminder_id}@planner.local'),
            rrule=str(recurrence['rrule']), rrule_canonical=canonical,
            dtstart_at=reminder.trigger_at, dtstart_date=reminder.trigger_date, tzid=reminder.tzid,
        )

    @classmethod
    def _update_reminder_series(
        cls, series: ReminderRecurrenceSeries, reminder: Reminder, recurrence: Mapping[str, Any]
    ) -> None:
        if not isinstance(recurrence, Mapping):
            raise PlannerCommandError('recurrence 必须是 object', code='invalid_recurrence')
        dtstart = reminder.trigger_at or reminder.trigger_date
        try:
            canonical = canonicalize_rrule(str(recurrence.get('rrule') or ''), dtstart=dtstart, tzid=reminder.tzid)
        except InvalidRRuleError as exc:
            raise PlannerCommandError(str(exc), code='invalid_rrule') from exc
        series.rrule = str(recurrence['rrule'])
        series.rrule_canonical = canonical
        series.dtstart_at = reminder.trigger_at
        series.dtstart_date = reminder.trigger_date
        series.tzid = reminder.tzid
        series.sequence += 1
        series.bump_version(update_fields={
            'rrule', 'rrule_canonical', 'dtstart_at', 'dtstart_date', 'tzid', 'sequence'
        })

    @classmethod
    def _rewrite_reminder_series_time(
        cls, series: ReminderRecurrenceSeries, reminder: Reminder, old_trigger: date | datetime
    ) -> None:
        new_trigger = reminder.trigger_at or reminder.trigger_date
        delta = new_trigger - old_trigger
        states = list(series.occurrence_states.select_for_update().filter(deleted_at__isnull=True))
        exdates = list(series.exdates.select_for_update().all())
        rdates = list(series.rdates.select_for_update().all())
        for row in [*states, *exdates, *rdates]:
            old_slot = PlannerTimeCodec.parse_recurrence_id(row.recurrence_id, tzid=series.tzid)
            row.recurrence_id = PlannerTimeCodec.format_recurrence_id(old_slot + delta, tzid=reminder.tzid)
            if isinstance(row, ReminderOccurrenceState) and row.effective_trigger_at:
                row.effective_trigger_at += delta
                row.snooze_until = row.snooze_until + delta if row.snooze_until else None
                row.bump_version(update_fields={'recurrence_id', 'effective_trigger_at', 'snooze_until'})
            else:
                if hasattr(row, 'starts_at') and row.starts_at:
                    row.starts_at += delta
                row.save()
        try:
            canonical = canonicalize_rrule(series.rrule, dtstart=new_trigger, tzid=reminder.tzid)
        except InvalidRRuleError as exc:
            raise PlannerCommandError(str(exc), code='invalid_rrule') from exc
        series.rrule_canonical = canonical
        series.dtstart_at = reminder.trigger_at
        series.dtstart_date = reminder.trigger_date
        series.tzid = reminder.tzid
        series.sequence += 1
        series.bump_version(update_fields={
            'rrule_canonical', 'dtstart_at', 'dtstart_date', 'tzid', 'sequence'
        })

    @classmethod
    def _split_reminder(
        cls, user: User, reminder: Reminder, series: ReminderRecurrenceSeries,
        recurrence_id: str, payload: Mapping[str, Any],
    ) -> Reminder:
        slot = PlannerTimeCodec.parse_recurrence_id(recurrence_id, tzid=series.tzid)
        slot_utc = PlannerTimeCodec.to_utc(slot, tzid=series.tzid) if isinstance(slot, datetime) else None
        child = Reminder.objects.create(
            user=user, title=reminder.title, content=reminder.content, priority=reminder.priority,
            status=reminder.status, tzid=reminder.tzid,
            trigger_at=slot_utc, trigger_date=slot if not isinstance(slot, datetime) else None,
        )
        clean_payload = {key: value for key, value in payload.items() if key not in {'scope', 'occurrence_ref'}}
        fields = cls._apply_reminder_master_fields(child, clean_payload)
        if fields:
            child.bump_version(update_fields=fields)

        kept_count = cls._count_reminder_slots_before(series, recurrence_id)
        parts = cls._rrule_parts(series.rrule_canonical or series.rrule)
        remaining_count = max(int(parts['COUNT']) - kept_count, 1) if 'COUNT' in parts else None
        child_parts = dict(parts)
        if remaining_count is not None:
            child_parts['COUNT'] = str(remaining_count)
        derived_rule = ';'.join(f'{key}={value}' for key, value in sorted(child_parts.items()))
        recurrence_specified = 'recurrence' in clean_payload
        recurrence = clean_payload.get('recurrence') if recurrence_specified else {'rrule': derived_rule}
        future_states = list(series.occurrence_states.select_for_update().filter(
            recurrence_id__gte=recurrence_id, deleted_at__isnull=True
        ))
        if recurrence_specified and recurrence is not None and future_states:
            raise PlannerCommandError(
                '未来 occurrence state 存在，修改 RRULE 前需先清理状态',
                code='recurrence_split_requires_override_policy',
            )
        child_series = cls._create_reminder_series(user, child, recurrence) if recurrence is not None else None
        if child_series:
            child_series.parent_series = series
            child_series.split_recurrence_id = recurrence_id
            child_series.save(update_fields={'parent_series', 'split_recurrence_id', 'updated_at'})
            for state in future_states:
                state.series = child_series
                state.bump_version(update_fields={'series'})
            for item in list(series.exdates.filter(recurrence_id__gte=recurrence_id)):
                ReminderRecurrenceExDate.objects.get_or_create(
                    series=child_series, recurrence_id=item.recurrence_id,
                    defaults={'source': item.source},
                )
            for item in list(series.rdates.filter(recurrence_id__gte=recurrence_id)):
                ReminderRecurrenceRDate.objects.get_or_create(
                    series=child_series, recurrence_id=item.recurrence_id,
                    defaults={'starts_at': item.starts_at, 'starts_date': item.starts_date},
                )
        else:
            for state in future_states:
                state.soft_delete(expected_version=state.version)
        cls._truncate_reminder_parent(reminder, series, kept_count)
        cls._record(user, 'reminder', child.reminder_id, child.version,
                    'reminder.split_this_and_future', CalendarChange.ACTION_UPDATE)
        return child

    @classmethod
    def _truncate_reminder_series(
        cls, reminder: Reminder, series: ReminderRecurrenceSeries, recurrence_id: str
    ) -> None:
        kept_count = cls._count_reminder_slots_before(series, recurrence_id)
        for state in series.occurrence_states.select_for_update().filter(
            recurrence_id__gte=recurrence_id, deleted_at__isnull=True
        ):
            state.soft_delete(expected_version=state.version)
        cls._truncate_reminder_parent(reminder, series, kept_count)

    @classmethod
    def _truncate_reminder_parent(
        cls, reminder: Reminder, series: ReminderRecurrenceSeries, kept_count: int
    ) -> None:
        if kept_count <= 0:
            reminder.soft_delete(expected_version=reminder.version)
            series.soft_delete(expected_version=series.version)
            return
        parts = cls._rrule_parts(series.rrule_canonical or series.rrule)
        parts.pop('UNTIL', None)
        parts['COUNT'] = str(kept_count)
        rule = ';'.join(f'{key}={value}' for key, value in sorted(parts.items()))
        series.rrule = rule
        series.rrule_canonical = canonicalize_rrule(
            rule, dtstart=series.dtstart_at or series.dtstart_date, tzid=series.tzid
        )
        series.sequence += 1
        series.bump_version(update_fields={'rrule', 'rrule_canonical', 'sequence'})

    @classmethod
    def _count_reminder_slots_before(cls, series: ReminderRecurrenceSeries, recurrence_id: str) -> int:
        dtstart = series.dtstart_at or series.dtstart_date
        anchor = PlannerTimeCodec.parse_recurrence_id(recurrence_id, tzid=series.tzid)
        rule_start = PlannerTimeCodec.recurrence_datetime(dtstart, tzid=series.tzid)
        anchor_dt = PlannerTimeCodec.recurrence_datetime(anchor, tzid=series.tzid)
        rule = rrulestr(series.rrule_canonical or series.rrule, dtstart=rule_start)
        return len([item for item in rule.between(rule_start, anchor_dt, inc=True) if item < anchor_dt])

    @staticmethod
    def _rrule_parts(rule: str) -> dict[str, str]:
        return {
            key.upper(): value for component in rule.removeprefix('RRULE:').split(';')
            if '=' in component for key, value in [component.split('=', 1)]
        }

    @classmethod
    def _ensure_reminder_slot(cls, series: ReminderRecurrenceSeries, recurrence_id: str) -> None:
        anchor = PlannerTimeCodec.parse_recurrence_id(recurrence_id, tzid=series.tzid)
        anchor_dt = PlannerTimeCodec.recurrence_datetime(anchor, tzid=series.tzid)
        rule_start = PlannerTimeCodec.recurrence_datetime(
            series.dtstart_at or series.dtstart_date, tzid=series.tzid
        )
        rule = rrulestr(series.rrule_canonical or series.rrule, dtstart=rule_start)
        if not rule.between(anchor_dt, anchor_dt, inc=True):
            raise PlannerCommandError('occurrence 不属于 reminder series', code='occurrence_not_found')

    @staticmethod
    def _require_reminder_occurrence_ref(
        reminder: Reminder, series: ReminderRecurrenceSeries,
        occurrence_ref: Mapping[str, Any] | None,
    ) -> str:
        if not isinstance(occurrence_ref, Mapping):
            raise PlannerCommandError('occurrence_ref 为必填', code='occurrence_not_found')
        if str(occurrence_ref.get('entity_id') or '') != reminder.reminder_id \
                or str(occurrence_ref.get('series_id') or '') != series.series_id:
            raise PlannerCommandError('occurrence_ref 不属于 reminder series', code='occurrence_not_found')
        recurrence_id = str(occurrence_ref.get('recurrence_id') or '')
        if not recurrence_id:
            raise PlannerCommandError('recurrence_id 为必填', code='occurrence_not_found')
        return recurrence_id

    @staticmethod
    def _require_reminder_source_version(expected: int, *objects: Any) -> None:
        actual = max(item.version for item in objects if item is not None)
        if expected != actual:
            raise PlannerCommandVersionConflict(f'版本冲突: expected={expected}, actual={actual}')

    @staticmethod
    def _local_date(value: date | datetime, tzid: str) -> date:
        return PlannerTimeCodec.to_local(value, tzid=tzid).date() if isinstance(value, datetime) else value

    @staticmethod
    def _reminder_series(reminder: Reminder) -> ReminderRecurrenceSeries | None:
        return ReminderRecurrenceSeries.objects.select_for_update().filter(
            master_reminder=reminder, deleted_at__isnull=True
        ).first()

    @staticmethod
    def _required_datetime(value: Any, tzid: str) -> datetime:
        parsed = PlannerTimeCodec.parse_value(value, tzid=tzid, allow_date=False)
        return PlannerTimeCodec.to_utc(parsed, tzid=tzid)

    @classmethod
    def _parse_optional_temporal(cls, value: Any, tzid: str | None) -> tuple[datetime | None, date | None, str]:
        zone = str(tzid or PlannerTimeCodec.DEFAULT_TZID)
        PlannerTimeCodec.get_timezone(zone)
        if value in (None, ''):
            return None, None, zone
        parsed = PlannerTimeCodec.parse_value(value, tzid=zone)
        if isinstance(parsed, datetime):
            return PlannerTimeCodec.to_utc(parsed, tzid=zone), None, zone
        return None, parsed, zone

    @staticmethod
    def _group(user: User, group_id: Any) -> EventGroup | None:
        if group_id in (None, ''):
            return None
        group = EventGroup.objects.filter(user=user, group_id=str(group_id), deleted_at__isnull=True).first()
        if group is None:
            raise PlannerCommandError('group 不存在或不属于当前用户', code='group_not_found')
        return group

    @staticmethod
    def _todo(user: User, todo_id: str, *, lock: bool = False) -> Todo:
        queryset = Todo.objects.filter(user=user, todo_id=todo_id, deleted_at__isnull=True).select_related('group')
        if lock: queryset = queryset.select_for_update()
        todo = queryset.first()
        if todo is None: raise PlannerCommandError('未找到 todo', code='todo_not_found')
        return todo

    @staticmethod
    def _reminder(user: User, reminder_id: str, *, lock: bool = False) -> Reminder:
        queryset = Reminder.objects.filter(user=user, reminder_id=reminder_id, deleted_at__isnull=True)
        if lock: queryset = queryset.select_for_update()
        reminder = queryset.first()
        if reminder is None: raise PlannerCommandError('未找到 reminder', code='reminder_not_found')
        return reminder

    @classmethod
    def _replace_todo_relations(cls, user: User, todo: Todo, payload: Mapping[str, Any]) -> bool:
        changed = False
        if 'tags' in payload:
            changed = True
            tags = payload['tags']
            if not isinstance(tags, list): raise PlannerCommandError('tags 必须是数组', code='invalid_tags')
            TodoTag.objects.filter(todo=todo).delete()
            for tag in tags:
                text = str(tag).strip()
                if text: TodoTag.objects.get_or_create(todo=todo, normalized_tag=text.casefold(), defaults={'tag': text})
        if 'dependencies' in payload:
            changed = True
            dependencies = payload['dependencies']
            if not isinstance(dependencies, list): raise PlannerCommandError('dependencies 必须是数组', code='invalid_dependencies')
            targets = list(Todo.objects.filter(user=user, todo_id__in=dependencies, deleted_at__isnull=True))
            if len(targets) != len(set(map(str, dependencies))):
                raise PlannerCommandError('dependency 不存在或跨用户', code='invalid_dependencies')
            if any(target.pk == todo.pk for target in targets):
                raise PlannerCommandError('todo 不能依赖自身', code='todo_dependency_cycle')
            for target in targets:
                if cls._dependency_reaches(target, todo):
                    raise PlannerCommandError('todo dependency 形成环', code='todo_dependency_cycle')
            TodoDependency.objects.filter(todo=todo).delete()
            TodoDependency.objects.bulk_create([TodoDependency(todo=todo, depends_on=target) for target in targets])
        return changed

    @staticmethod
    def _dependency_reaches(start: Todo, target: Todo) -> bool:
        pending = [start.pk]
        seen = set()
        while pending:
            current = pending.pop()
            if current == target.pk: return True
            if current in seen: continue
            seen.add(current)
            pending.extend(TodoDependency.objects.filter(todo_id=current).values_list('depends_on_id', flat=True))
        return False

    @staticmethod
    def _require_version(obj: Any, expected: int) -> None:
        if expected != obj.version:
            raise PlannerCommandVersionConflict(f'版本冲突: expected={expected}, actual={obj.version}')

    @staticmethod
    def _record(user: User, resource_type: str, resource_id: str, version: int, command: str, action: str) -> None:
        collection, _ = CalendarCollectionVersion.objects.select_for_update().get_or_create(
            user=user, collection_type=resource_type, collection_id='default'
        )
        collection.version += 1
        collection.sync_token = str(uuid4())
        collection.save(update_fields={'version', 'sync_token', 'updated_at'})
        CalendarChange.objects.create(
            collection=collection, token=collection.version, resource_type=resource_type,
            resource_public_id=resource_id, action=action, etag=f'{resource_type}:{resource_id}:{version}'
        )
        if resource_type == 'reminder':
            CalendarCollectionChangeWriter.record(
                user, collection_id='reminders', resource_type='reminder',
                resource_public_id=resource_id, action=action,
                etag=f'reminder:{resource_id}:{version}',
            )
        PlannerChangeSet.objects.create(user=user, command_type=command, after_payload={resource_type: {'id': resource_id, 'version': version}})
