"""CalDAV 只读协议 façade；只返回 normalized Planner 投影。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256

from django.db import transaction

from core.models import (
    CalendarChange, CalendarCollectionVersion, CalendarEvent, EventGroup, EventOccurrenceOverride,
    EventRecurrenceSeries,
)
from core.planner.calendar_projection import NormalizedCalendarProjectionService
from core.planner.commands import PlannerCommandError, PlannerCommandService
from core.planner.entities import PlannerEntityQueryService
from core.planner.ical import IcalEventResource, ParsedCalendarObject, ParsedEventComponent, encode_event_resource
from core.planner.recurrence.codec import PlannerTimeCodec
from core.planner.repository import PlannerRepository


class CalDAVCollectionNotFound(LookupError):
    pass


class CalDAVResourceNotFound(LookupError):
    pass


class CalDAVPreconditionFailed(ValueError):
    pass


class CalDAVIdentityConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CalendarCollectionProjection:
    collection_id: str
    display_name: str
    color: str
    read_only: bool = False


@dataclass(frozen=True, slots=True)
class CalendarResourceProjection:
    collection_id: str
    resource: IcalEventResource
    etag: str

    @property
    def resource_name(self) -> str:
        return self.resource.resource_name

    @property
    def calendar_data(self) -> bytes:
        return encode_event_resource(self.resource)


@dataclass(frozen=True, slots=True)
class CalendarObjectWriteResult:
    created: bool
    moved: bool
    collection_id: str
    resource_name: str
    etag: str
    calendar_data: bytes


class PlannerCalDAVQueryService:
    @classmethod
    def list_collections(cls, user) -> list[CalendarCollectionProjection]:
        results = [CalendarCollectionProjection('default', 'UniScheduler', '#4A90E2FF')]
        for group in EventGroup.objects.filter(user=user, deleted_at__isnull=True).order_by('name', 'id'):
            results.append(CalendarCollectionProjection(
                group.group_id, group.name, cls._rgba(group.color or '#888888')
            ))
        results.append(CalendarCollectionProjection('reminders', '提醒', '#FF6B6BFF', read_only=True))
        return results

    @classmethod
    def get_collection(cls, user, collection_id: str) -> CalendarCollectionProjection:
        for collection in cls.list_collections(user):
            if collection.collection_id == collection_id:
                return collection
        raise CalDAVCollectionNotFound(collection_id)

    @classmethod
    def list_resources(
        cls, user, collection_id: str, *, range_start: datetime | None = None,
        range_end: datetime | None = None,
    ) -> list[CalendarResourceProjection]:
        collection = cls.get_collection(user, collection_id)
        resources = cls._reminder_resources(user) if collection.read_only else cls._event_resources(user, collection_id)
        if range_start is not None or range_end is not None:
            if range_start is None or range_end is None or range_end <= range_start:
                return []
            if collection.read_only:
                ids = {
                    item.ref.entity_id for item in PlannerEntityQueryService.list_reminder_occurrences(
                        user, range_start=range_start, range_end=range_end
                    )
                }
            else:
                ids = {
                    item.ref.entity_id for item in PlannerRepository.list_event_occurrences(
                        user, range_start=range_start, range_end=range_end
                    )
                }
            resources = [item for item in resources if item.entity_id in ids]
        return [cls._wrap(collection_id, item) for item in resources]

    @classmethod
    def get_resource(cls, user, collection_id: str, resource_name: str) -> CalendarResourceProjection:
        normalized_name = resource_name.removesuffix('.ics')
        for resource in cls.list_resources(user, collection_id):
            if normalized_name in {resource.resource_name, resource.resource.ical_uid}:
                return resource
        raise CalDAVResourceNotFound(normalized_name)

    @classmethod
    def collection_ctag(cls, user, collection_id: str) -> str:
        collection = cls.get_collection(user, collection_id)
        raw_resources = (
            cls._reminder_resources(user) if collection.read_only
            else cls._event_resources(user, collection.collection_id)
        )
        version = CalendarCollectionVersion.objects.filter(
            user=user, collection_type='caldav', collection_id=collection.collection_id
        ).values_list('version', flat=True).first() or 0
        return f'"caldav-{collection.collection_id}-{version}"'

    @staticmethod
    def _event_resources(user, collection_id: str) -> list[IcalEventResource]:
        projections = PlannerRepository.list_all_event_definitions(user)
        if collection_id == 'default':
            projections = [
                item for item in projections
                if item.event.group_id is None or item.event.group.deleted_at is not None
            ]
        else:
            projections = [
                item for item in projections
                if item.event.group_id is not None and item.event.group.group_id == collection_id
                and item.event.group.deleted_at is None
            ]
        return [NormalizedCalendarProjectionService._event_resource(item, feed_titles=False) for item in projections]

    @staticmethod
    def _reminder_resources(user) -> list[IcalEventResource]:
        return NormalizedCalendarProjectionService.reminder_resources(user, feed_titles=False)

    @staticmethod
    def _wrap(collection_id: str, resource: IcalEventResource) -> CalendarResourceProjection:
        raw = f'{resource.ical_uid}:{resource.revision_token or resource.version}'
        etag = f'"{sha256(raw.encode()).hexdigest()[:32]}"'
        return CalendarResourceProjection(collection_id, resource, etag)

    @staticmethod
    def _rgba(color: str) -> str:
        value = color if color.startswith('#') else f'#{color}'
        return f'{value}FF' if len(value) == 7 else value


class PlannerCalDAVCommandService:
    """一个 CalDAV resource 对应一个事务；View 不拼装 ORM 写步骤。"""

    @classmethod
    @transaction.atomic
    def apply_event_resource(
        cls, user, *, collection_id: str, resource_name: str,
        parsed: ParsedCalendarObject, if_match: str = '', if_none_match: str = '',
    ) -> CalendarObjectWriteResult:
        collection = PlannerCalDAVQueryService.get_collection(user, collection_id)
        change_pk_before = CalendarChange.objects.filter(
            collection__user=user, collection__collection_type='caldav'
        ).order_by('-pk').values_list('pk', flat=True).first() or 0
        if collection.read_only:
            raise PermissionError('reminders collection is read-only')
        if not resource_name or len(resource_name) > 255 or '/' in resource_name:
            raise CalDAVIdentityConflict('invalid resource name')
        event, series = cls._find_event(user, resource_name, lock=True)
        created = event is None
        moved = False
        if created:
            if if_match:
                raise CalDAVPreconditionFailed('If-Match target does not exist')
            if cls._uid_exists(user, parsed.uid):
                raise CalDAVIdentityConflict('UID already belongs to another resource')
            payload = cls._master_payload(parsed.master, collection_id)
            event = PlannerCommandService.create_event(user, payload)
            series = EventRecurrenceSeries.objects.select_for_update().filter(
                master_event=event, deleted_at__isnull=True
            ).first()
            initial_resource_name = series.caldav_resource_name if series is not None else event.caldav_resource_name
            if series is None:
                event.ical_uid = parsed.uid
                event.caldav_resource_name = resource_name
                event.save(update_fields={'ical_uid', 'caldav_resource_name', 'updated_at'})
            else:
                series.ical_uid = parsed.uid
                series.caldav_resource_name = resource_name
                series.save(update_fields={'ical_uid', 'caldav_resource_name', 'updated_at'})
            CalendarChange.objects.filter(
                pk__gt=change_pk_before, collection__user=user,
                collection__collection_type='caldav', resource_public_id=initial_resource_name,
            ).update(resource_public_id=resource_name)
            if any(item.recurrence_range == 'THISANDFUTURE' for item in parsed.overrides):
                raise PlannerCommandError(
                    'RANGE=THISANDFUTURE requires an existing series', code='unsupported_range'
                )
            cls._replace_overrides(event, series, parsed.overrides)
        else:
            old_collection = cls._event_collection(event)
            moved = old_collection != collection_id
            current = PlannerCalDAVQueryService.get_resource(user, old_collection, resource_name)
            if if_none_match == '*':
                raise CalDAVPreconditionFailed('If-None-Match target already exists')
            if if_match and if_match != '*' and if_match != current.etag:
                raise CalDAVPreconditionFailed('ETag mismatch')
            canonical_uid = series.ical_uid if series is not None else event.ical_uid
            canonical_resource_name = resource_name
            if parsed.uid != canonical_uid:
                raise CalDAVIdentityConflict('UID is immutable')
            range_overrides = [item for item in parsed.overrides if item.recurrence_range == 'THISANDFUTURE']
            if len(range_overrides) > 1:
                raise PlannerCommandError('a resource may contain only one THISANDFUTURE split', code='unsupported_range')
            expected_version = PlannerCommandService.source_version(event)
            event = PlannerCommandService.patch_event(
                user, event.event_id, cls._master_payload(parsed.master, collection_id),
                scope='all', occurrence_ref=None, expected_version=expected_version,
            )
            series = EventRecurrenceSeries.objects.select_for_update().filter(
                master_event=event, deleted_at__isnull=True
            ).first()
            if series is None:
                event.ical_uid = canonical_uid
                event.caldav_resource_name = canonical_resource_name
                event.save(update_fields={'ical_uid', 'caldav_resource_name', 'updated_at'})
            else:
                series.ical_uid = canonical_uid
                series.caldav_resource_name = canonical_resource_name
                series.save(update_fields={'ical_uid', 'caldav_resource_name', 'updated_at'})
            cls._replace_overrides(
                event, series,
                tuple(item for item in parsed.overrides if item.recurrence_range != 'THISANDFUTURE'),
            )
            if range_overrides:
                if series is None:
                    raise PlannerCommandError('THISANDFUTURE requires recurrence', code='unsupported_range')
                split = range_overrides[0]
                split_payload = {
                    'title': split.title or event.title,
                    'description': split.description,
                    'location': split.location,
                    'status': split.status,
                    'start': cls_temporal(split.start),
                    'end': cls_temporal(split.end),
                    'is_all_day': split.is_all_day,
                    'tzid': split.tzid,
                    'override_policy': 'discard_with_audit',
                }
                PlannerCommandService.patch_event(
                    user, event.event_id, split_payload,
                    scope='this_and_future',
                    occurrence_ref={
                        'entity_id': event.event_id,
                        'series_id': series.series_id,
                        'recurrence_id': PlannerTimeCodec.format_recurrence_id(
                            split.recurrence_id, tzid=series.tzid
                        ),
                    },
                    expected_version=PlannerCommandService.source_version(event),
                )
        event.refresh_from_db()
        series = EventRecurrenceSeries.objects.filter(master_event=event, deleted_at__isnull=True).first()
        final_collection = cls._event_collection(event)
        final_name = series.caldav_resource_name if series else event.caldav_resource_name
        resource = PlannerCalDAVQueryService.get_resource(user, final_collection, final_name)
        CalendarChange.objects.filter(
            pk__gt=change_pk_before, collection__user=user,
            collection__collection_type='caldav', resource_public_id=resource.resource_name,
        ).update(etag=resource.etag)
        return CalendarObjectWriteResult(
            created=created, moved=moved, collection_id=final_collection,
            resource_name=resource.resource_name, etag=resource.etag,
            calendar_data=resource.calendar_data,
        )

    @classmethod
    @transaction.atomic
    def delete_event_resource(
        cls, user, *, collection_id: str, resource_name: str, if_match: str = '',
    ) -> None:
        collection = PlannerCalDAVQueryService.get_collection(user, collection_id)
        if collection.read_only:
            raise PermissionError('reminders collection is read-only')
        event, series = cls._find_event(user, resource_name, lock=True)
        if event is None or cls._event_collection(event) != collection_id:
            raise CalDAVResourceNotFound(resource_name)
        current = PlannerCalDAVQueryService.get_resource(user, collection_id, resource_name)
        if if_match and if_match != '*' and if_match != current.etag:
            raise CalDAVPreconditionFailed('ETag mismatch')
        PlannerCommandService.delete_event(
            user, event.event_id, scope='all', occurrence_ref=None,
            expected_version=PlannerCommandService.source_version(event),
        )

    @staticmethod
    def _master_payload(master: ParsedEventComponent, collection_id: str) -> dict:
        payload = {
            'title': master.title or '(无标题)',
            'description': master.description,
            'location': master.location,
            'status': master.status,
            'start': cls_temporal(master.start),
            'end': cls_temporal(master.end),
            'is_all_day': master.is_all_day,
            'tzid': master.tzid,
            'group_id': None if collection_id == 'default' else collection_id,
            'recurrence': None,
        }
        if master.rrule:
            payload['recurrence'] = {
                'rrule': master.rrule,
                'rdates': [cls_temporal(value) for value in master.rdates],
                'exdates': [cls_temporal(value) for value in master.exdates],
            }
        return payload

    @classmethod
    def _replace_overrides(cls, event, series, overrides: tuple[ParsedEventComponent, ...]) -> None:
        if overrides and series is None:
            raise PlannerCommandError('single event cannot contain RECURRENCE-ID', code='invalid_recurrence')
        if series is None:
            return
        EventOccurrenceOverride.objects.filter(series=series).delete()
        for component in overrides:
            recurrence_id = PlannerTimeCodec.format_recurrence_id(component.recurrence_id, tzid=series.tzid)
            kind = (
                EventOccurrenceOverride.KIND_CANCELLED
                if component.status == 'cancelled' else EventOccurrenceOverride.KIND_MODIFIED
            )
            patch = {}
            for key, value, current in (
                ('title', component.title, event.title),
                ('description', component.description, event.description),
                ('location', component.location, event.location),
                ('status', component.status, event.status),
            ):
                if value != current and not (key == 'status' and kind == EventOccurrenceOverride.KIND_CANCELLED):
                    patch[key] = value
            values = {'series': series, 'recurrence_id': recurrence_id, 'kind': kind, 'patch': patch}
            if kind != EventOccurrenceOverride.KIND_CANCELLED:
                if event.is_all_day:
                    values.update(effective_start_date=component.start, effective_end_date=component.end)
                else:
                    values.update(
                        effective_start_at=PlannerTimeCodec.to_utc(component.start, tzid=series.tzid),
                        effective_end_at=PlannerTimeCodec.to_utc(component.end, tzid=series.tzid),
                    )
            EventOccurrenceOverride.objects.create(**values)
        if overrides:
            series.bump_version(update_fields=[])

    @staticmethod
    def _find_event(user, resource_name: str, *, lock: bool):
        event_query = CalendarEvent.objects.filter(
            user=user, caldav_resource_name=resource_name, deleted_at__isnull=True
        )
        series_query = EventRecurrenceSeries.objects.filter(
            user=user, caldav_resource_name=resource_name, deleted_at__isnull=True,
            master_event__deleted_at__isnull=True,
        ).select_related('master_event')
        if lock:
            event_query = event_query.select_for_update()
            series_query = series_query.select_for_update()
        series = series_query.first()
        if series is not None:
            return series.master_event, series
        event = event_query.first()
        return event, None

    @staticmethod
    def _uid_exists(user, uid: str) -> bool:
        return (
            CalendarEvent.objects.filter(user=user, ical_uid=uid).exists()
            or EventRecurrenceSeries.objects.filter(user=user, ical_uid=uid).exists()
        )

    @staticmethod
    def _event_collection(event) -> str:
        return event.group.group_id if event.group_id and event.group.deleted_at is None else 'default'


def cls_temporal(value: date | datetime) -> str:
    return value.isoformat()
