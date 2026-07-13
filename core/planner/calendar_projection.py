"""normalized Planner 到 Feed/CalDAV iCalendar DTO 的只读投影。"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Prefetch, Q

from core.models import (
    Reminder,
    ReminderOccurrenceState,
    ReminderRecurrenceSeries,
    Todo,
)
from core.planner.ical import IcalEventResource, IcalOverride
from core.planner.repository import EventDefinitionProjection, PlannerRepository


class NormalizedCalendarProjectionService:
    """只读构建协议 DTO；不写业务表、不展开并存储 occurrence。"""

    @classmethod
    def event_resources(cls, user, *, feed_titles: bool = False) -> list[IcalEventResource]:
        return [cls._event_resource(item, feed_titles=feed_titles) for item in PlannerRepository.list_all_event_definitions(user)]

    @classmethod
    def todo_feed_resources(cls, user) -> list[IcalEventResource]:
        queryset = Todo.objects.filter(user=user, deleted_at__isnull=True).filter(
            Q(due_at__isnull=False) | Q(due_date__isnull=False)
        ).select_related('group').order_by('due_at', 'due_date', 'id')
        results = []
        for todo in queryset:
            start = todo.due_at
            if start is None:
                start = datetime.combine(todo.due_date, time(hour=9), tzinfo=ZoneInfo(todo.tzid))
            title = f"[待办] {todo.title}"
            if todo.group:
                title = f"[待办] [{todo.group.name}] {todo.title}"
            results.append(IcalEventResource(
                entity_id=todo.todo_id,
                ical_uid=f"todo-{todo.todo_id}@unischeduler",
                resource_name=f"todo-{todo.todo_id}",
                title=title,
                description=todo.description,
                start=start,
                end=start + timedelta(minutes=5),
                tzid=todo.tzid,
                updated_at=todo.updated_at,
                version=todo.version,
                revision_token=f't{todo.version}',
                include_status=False,
                alarm_description=f"待办：{todo.title}",
            ))
        return results

    @classmethod
    def reminder_resources(cls, user, *, feed_titles: bool = True) -> list[IcalEventResource]:
        reminders = Reminder.objects.filter(user=user, deleted_at__isnull=True).select_related().order_by(
            'trigger_at', 'trigger_date', 'id'
        )
        results = []
        for reminder in reminders:
            series = ReminderRecurrenceSeries.objects.filter(
                master_reminder=reminder, deleted_at__isnull=True
            ).prefetch_related('rdates', 'exdates', Prefetch(
                'occurrence_states', queryset=ReminderOccurrenceState.objects.filter(deleted_at__isnull=True)
            )).first()
            start = reminder.trigger_at
            if start is None:
                start = datetime.combine(reminder.trigger_date, time(hour=9), tzinfo=ZoneInfo(reminder.tzid))
            uid = f"rem-{reminder.reminder_id}@unischeduler"
            resource_name = f"rem-{reminder.reminder_id}"
            rrule = ""
            rdates = ()
            exdates = ()
            overrides = ()
            version = reminder.version
            series_id = ""
            if series is not None:
                series_id = series.series_id
                uid = series.ical_uid or f"rem-series-{series.series_id}@unischeduler"
                resource_name = f"rem-series-{series.series_id}"
                rrule = series.rrule_canonical or series.rrule
                rdates = tuple(item.starts_at or item.starts_date for item in series.rdates.all())
                exdates = tuple(item.recurrence_id for item in series.exdates.all())
                version = max(version, series.version)
                overrides = tuple(cls._reminder_override(item, start) for item in series.occurrence_states.all())
            return_title = f"[提醒] {reminder.title}" if feed_titles else reminder.title
            results.append(IcalEventResource(
                entity_id=reminder.reminder_id,
                ical_uid=uid,
                resource_name=resource_name,
                title=return_title,
                description=reminder.content,
                start=start,
                end=start + timedelta(minutes=5),
                tzid=reminder.tzid,
                updated_at=reminder.updated_at,
                version=version,
                revision_token=(
                    f'r{reminder.version}-s{series.version}-o'
                    + ','.join(f'{item.recurrence_id}:{item.version}' for item in series.occurrence_states.all())
                    if series is not None else f'r{reminder.version}'
                ),
                series_id=series_id,
                rrule=rrule,
                rdates=tuple(item for item in rdates if item is not None),
                exdates=exdates,
                overrides=overrides,
                include_status=False,
                alarm_description=f"提醒：{reminder.title}",
            ))
        return results

    @staticmethod
    def _event_resource(projection: EventDefinitionProjection, *, feed_titles: bool) -> IcalEventResource:
        event = projection.event
        start = event.start_date if event.is_all_day else event.start_at
        end = event.end_date if event.is_all_day else event.end_at
        title = event.title
        if feed_titles and event.group:
            title = f"[{event.group.name}] {title}"
        if projection.recurrence is None:
            return IcalEventResource(
                entity_id=event.event_id, ical_uid=event.ical_uid,
                resource_name=event.caldav_resource_name, title=title,
                start=start, end=end, tzid=event.tzid, is_all_day=event.is_all_day,
                description=event.description, location=event.location, status=event.status,
                updated_at=event.updated_at, version=event.version,
                revision_token=f'e{event.version}',
            )
        series = event.recurrence_series
        overrides = tuple(
            IcalOverride(
                recurrence_id=item.recurrence_id,
                kind=item.kind,
                patch=item.patch,
                effective_start=item.effective_start,
                effective_end=item.effective_end,
                version=item.version,
            )
            for item in projection.overrides
        )
        return IcalEventResource(
            entity_id=event.event_id, ical_uid=series.ical_uid,
            resource_name=series.caldav_resource_name, title=title,
            start=start, end=end, tzid=event.tzid, is_all_day=event.is_all_day,
            description=event.description, location=event.location, status=event.status,
            updated_at=max(event.updated_at, series.updated_at),
            version=max(event.version, series.version), series_id=series.series_id,
            revision_token=(
                f'e{event.version}-s{series.version}-o'
                + ','.join(f'{item.recurrence_id}:{item.version or 0}' for item in projection.overrides)
            ),
            rrule=series.rrule_canonical or series.rrule,
            rdates=projection.recurrence.rdates,
            exdates=tuple(sorted(projection.recurrence.exdates)),
            overrides=overrides,
        )

    @staticmethod
    def _reminder_override(state: ReminderOccurrenceState, master_start: datetime) -> IcalOverride:
        kind = 'cancelled' if state.status in {'dismissed', 'completed', 'cancelled'} else 'modified'
        effective_start = state.effective_trigger_at
        return IcalOverride(
            recurrence_id=state.recurrence_id,
            kind=kind,
            patch=state.patch,
            effective_start=effective_start,
            effective_end=effective_start + timedelta(minutes=5) if effective_start else None,
            version=state.version,
        )
