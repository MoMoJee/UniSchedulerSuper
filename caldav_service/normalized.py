"""normalized CalDAV HTTP 只读适配；XML/HTTP 留在协议层。"""

from __future__ import annotations

from datetime import datetime, timezone
import xml.etree.ElementTree as ET

from django.http import HttpResponse

from caldav_service.xml_utils import (
    add_propstat, add_response, caldav, cs, dav, get_local_name, get_prop, ical,
    make_multistatus, parse_xml_body, set_text_prop, serialize_xml,
)
from core.planner.application import PlannerApplicationService
from core.planner.caldav import (
    CalDAVCollectionNotFound, CalDAVIdentityConflict, CalDAVPreconditionFailed,
    CalDAVResourceNotFound,
)
from core.planner.commands import PlannerCommandError
from core.planner.context import PlannerExecutionContext
from core.planner.ical import ICalendarMappingError, decode_event_resource
from core.planner.rollout import PlannerRolloutPolicy


class CalDAVPlannerAccessDenied(PermissionError):
    def __init__(self, decision):
        self.decision = decision
        super().__init__('Planner CalDAV access is unavailable for this account.')


def normalized_read_context(user):
    decision = PlannerRolloutPolicy.can_read_normalized(user, PlannerRolloutPolicy.ENTRYPOINT_CALDAV_READ)
    if decision.effective_mode not in {'shadow', 'normalized'}:
        from django.conf import settings
        if str(getattr(settings, 'PLANNER_STORAGE_MODE', 'legacy')).lower() != 'legacy':
            raise CalDAVPlannerAccessDenied(decision)
        return None
    return PlannerExecutionContext(user=user, source='caldav', entrypoint=PlannerRolloutPolicy.ENTRYPOINT_CALDAV_READ)


def normalized_write_context(user):
    decision = PlannerRolloutPolicy.can_write_normalized(user, PlannerRolloutPolicy.ENTRYPOINT_CALDAV_WRITE)
    if decision.effective_mode != 'normalized':
        from django.conf import settings
        if str(getattr(settings, 'PLANNER_STORAGE_MODE', 'legacy')).lower() != 'legacy':
            raise CalDAVPlannerAccessDenied(decision)
        return None
    return PlannerExecutionContext(user=user, source='caldav', entrypoint=PlannerRolloutPolicy.ENTRYPOINT_CALDAV_WRITE)


def home_propfind(context, username: str, depth: str) -> HttpResponse:
    if depth == 'infinity':
        return HttpResponse('Depth infinity is not supported.', status=403)
    root = make_multistatus()
    response = add_response(root, f'/caldav/{username}/')
    prop = get_prop(add_propstat(response))
    resource_type = ET.SubElement(prop, dav('resourcetype'))
    ET.SubElement(resource_type, dav('collection'))
    set_text_prop(prop, dav('displayname'), 'UniScheduler')
    principal = ET.SubElement(prop, dav('current-user-principal'))
    set_text_prop(principal, dav('href'), f'/caldav/principals/{username}/')
    if depth != '0':
        for collection in PlannerApplicationService.list_calendar_collections(context):
            _add_collection(root, context, username, collection)
    return _xml(root)


def collection_propfind(context, username: str, collection_id: str, depth: str) -> HttpResponse:
    if depth == 'infinity':
        return HttpResponse('Depth infinity is not supported.', status=403)
    try:
        collections = PlannerApplicationService.list_calendar_collections(context)
        collection = next(item for item in collections if item.collection_id == collection_id)
        resources = PlannerApplicationService.list_calendar_resources(context, collection_id=collection_id)
    except (StopIteration, CalDAVCollectionNotFound):
        return HttpResponse(status=404)
    root = make_multistatus()
    _add_collection(root, context, username, collection)
    if depth != '0':
        for resource in resources:
            _add_resource(root, username, collection_id, resource, include_data=False)
    return _xml(root)


def collection_report(context, username: str, collection_id: str, body: bytes) -> HttpResponse:
    if not body:
        return HttpResponse(status=400)
    try:
        root = parse_xml_body(body)
    except ET.ParseError:
        return HttpResponse('Malformed XML.', status=400)
    report_type = get_local_name(root.tag)
    if report_type not in {'calendar-multiget', 'calendar-query'}:
        return HttpResponse(status=501)
    try:
        if report_type == 'calendar-multiget':
            all_resources = PlannerApplicationService.list_calendar_resources(context, collection_id=collection_id)
            by_name = {item.resource_name: item for item in all_resources}
            response_root = make_multistatus()
            for href_node in root.iter(dav('href')):
                href = (href_node.text or '').strip()
                resource_name = href.rstrip('/').rsplit('/', 1)[-1].removesuffix('.ics')
                resource = by_name.get(resource_name)
                if resource is None:
                    response = add_response(response_root, href)
                    add_propstat(response, status='HTTP/1.1 404 Not Found')
                else:
                    _add_resource(response_root, username, collection_id, resource, include_data=True, href=href)
            return _xml(response_root)
        range_start, range_end = _time_range(root)
        resources = PlannerApplicationService.list_calendar_resources(
            context, collection_id=collection_id, range_start=range_start, range_end=range_end
        ) if range_start and range_end else PlannerApplicationService.list_calendar_resources(
            context, collection_id=collection_id
        )
        response_root = make_multistatus()
        for resource in resources:
            _add_resource(response_root, username, collection_id, resource, include_data=True)
        return _xml(response_root)
    except CalDAVCollectionNotFound:
        return HttpResponse(status=404)


def event_get(context, collection_id: str, resource_name: str, *, if_none_match: str = '') -> HttpResponse:
    try:
        resource = PlannerApplicationService.get_calendar_resource(
            context, collection_id=collection_id, resource_name=resource_name
        )
    except (CalDAVCollectionNotFound, CalDAVResourceNotFound):
        return HttpResponse('Event not found.', status=404)
    if if_none_match in {'*', resource.etag}:
        response = HttpResponse(status=304)
        response['ETag'] = resource.etag
        return response
    response = HttpResponse(resource.calendar_data, content_type='text/calendar; charset=utf-8')
    response['ETag'] = resource.etag
    return response


def event_put(
    context, username: str, collection_id: str, resource_name: str, body: bytes,
    *, if_match: str = '', if_none_match: str = '',
) -> HttpResponse:
    try:
        parsed = decode_event_resource(body)
        result = PlannerApplicationService.apply_caldav_event_resource(
            context, collection_id=collection_id, resource_name=resource_name,
            parsed_object=parsed, if_match=if_match, if_none_match=if_none_match,
        )
    except ICalendarMappingError as exc:
        return HttpResponse(f'Invalid iCalendar data: {exc}', status=400)
    except CalDAVPreconditionFailed:
        return HttpResponse(status=412)
    except CalDAVIdentityConflict as exc:
        return HttpResponse(str(exc), status=409)
    except CalDAVCollectionNotFound:
        return HttpResponse(status=404)
    except PermissionError:
        return HttpResponse('Calendar is read-only.', status=403)
    except PlannerCommandError as exc:
        return HttpResponse(str(exc), status=400)
    response = HttpResponse(result.calendar_data if result.created else b'', status=201 if result.created else 204)
    response['ETag'] = result.etag
    response['Location'] = f'/caldav/{username}/{result.collection_id}/{result.resource_name}.ics'
    return response


def event_delete(context, collection_id: str, resource_name: str, *, if_match: str = '') -> HttpResponse:
    try:
        PlannerApplicationService.delete_caldav_event_resource(
            context, collection_id=collection_id, resource_name=resource_name, if_match=if_match
        )
    except CalDAVPreconditionFailed:
        return HttpResponse(status=412)
    except (CalDAVCollectionNotFound, CalDAVResourceNotFound):
        return HttpResponse(status=404)
    except PermissionError:
        return HttpResponse('Calendar is read-only.', status=403)
    except PlannerCommandError as exc:
        return HttpResponse(str(exc), status=400)
    return HttpResponse(status=204)


def _add_collection(root, context, username, collection) -> None:
    response = add_response(root, f'/caldav/{username}/{collection.collection_id}/')
    prop = get_prop(add_propstat(response))
    resource_type = ET.SubElement(prop, dav('resourcetype'))
    ET.SubElement(resource_type, dav('collection'))
    ET.SubElement(resource_type, caldav('calendar'))
    set_text_prop(prop, dav('displayname'), collection.display_name)
    set_text_prop(prop, ical('calendar-color'), collection.color)
    set_text_prop(
        prop, cs('getctag'),
        PlannerApplicationService.get_calendar_collection_version(
            context, collection_id=collection.collection_id
        ),
    )
    supported = ET.SubElement(prop, caldav('supported-calendar-component-set'))
    ET.SubElement(supported, caldav('comp'), {'name': 'VEVENT'})
    report_set = ET.SubElement(prop, dav('supported-report-set'))
    for report_name in ('calendar-multiget', 'calendar-query'):
        supported_report = ET.SubElement(report_set, dav('supported-report'))
        report = ET.SubElement(supported_report, dav('report'))
        ET.SubElement(report, caldav(report_name))


def _add_resource(root, username, collection_id, resource, *, include_data: bool, href: str | None = None) -> None:
    canonical_href = href or f'/caldav/{username}/{collection_id}/{resource.resource_name}.ics'
    response = add_response(root, canonical_href)
    prop = get_prop(add_propstat(response))
    set_text_prop(prop, dav('getetag'), resource.etag)
    set_text_prop(prop, dav('getcontenttype'), 'text/calendar; charset=utf-8')
    ET.SubElement(prop, dav('resourcetype'))
    if include_data:
        set_text_prop(prop, caldav('calendar-data'), resource.calendar_data.decode('utf-8'))


def _time_range(root):
    for node in root.iter(caldav('time-range')):
        try:
            start = _caldav_datetime(node.get('start', ''))
            end = _caldav_datetime(node.get('end', ''))
            return start, end
        except ValueError:
            return None, None
    return None, None


def _caldav_datetime(value: str) -> datetime:
    if not value:
        raise ValueError('missing time range')
    if value.endswith('Z'):
        return datetime.strptime(value, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
    return datetime.strptime(value, '%Y%m%dT%H%M%S').replace(tzinfo=timezone.utc)


def _xml(root) -> HttpResponse:
    return HttpResponse(serialize_xml(root), content_type='application/xml; charset=utf-8', status=207)
