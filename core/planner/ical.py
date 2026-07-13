"""Planner V2 的唯一 RFC 5545/iCalendar 纯映射层。

本模块不接收 HTTP request、不查询 ORM、不写数据库。Feed 与 CalDAV 只能把
normalized projection 转成这里的 DTO，再调用编码/解析函数。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from icalendar import Alarm, Calendar, Event, Timezone, TimezoneStandard, vRecur

from core.planner.recurrence.codec import PlannerTimeCodec


PRODID = "-//UniSchedulerSuper//Planner V2//ZH"
DEFAULT_TZID = "Asia/Shanghai"
Temporal = date | datetime


class ICalendarMappingError(ValueError):
    """iCalendar resource 无法无损映射到 Planner V2。"""


@dataclass(frozen=True)
class IcalOverride:
    recurrence_id: str
    kind: str = "modified"
    patch: Mapping[str, Any] = field(default_factory=dict)
    effective_start: Temporal | None = None
    effective_end: Temporal | None = None
    version: int = 1


@dataclass(frozen=True)
class IcalEventResource:
    entity_id: str
    ical_uid: str
    resource_name: str
    title: str
    start: Temporal
    end: Temporal
    tzid: str = DEFAULT_TZID
    description: str = ""
    location: str = ""
    status: str = "confirmed"
    include_status: bool = True
    is_all_day: bool = False
    updated_at: datetime | None = None
    version: int = 1
    revision_token: str = ""
    series_id: str = ""
    rrule: str = ""
    rdates: tuple[Temporal, ...] = ()
    exdates: tuple[str, ...] = ()
    overrides: tuple[IcalOverride, ...] = ()
    alarm_description: str = ""


@dataclass(frozen=True)
class ParsedEventComponent:
    uid: str
    title: str
    start: Temporal
    end: Temporal
    tzid: str
    is_all_day: bool
    description: str = ""
    location: str = ""
    status: str = "confirmed"
    rrule: str = ""
    rdates: tuple[Temporal, ...] = ()
    exdates: tuple[Temporal, ...] = ()
    recurrence_id: Temporal | None = None
    recurrence_range: str = ""
    sequence: int = 0


@dataclass(frozen=True)
class ParsedCalendarObject:
    uid: str
    master: ParsedEventComponent
    overrides: tuple[ParsedEventComponent, ...]


def encode_event_resource(resource: IcalEventResource) -> bytes:
    """编码一个 CalDAV resource（master + sparse override）。"""
    _validate_resource(resource)
    calendar = _calendar(name=None, method=None)
    for component in build_event_components(resource):
        calendar.add_component(component)
    return calendar.to_ical()


def encode_feed_calendar(
    *,
    name: str,
    events: Iterable[IcalEventResource] = (),
    todos: Iterable[IcalEventResource] = (),
    reminders: Iterable[IcalEventResource] = (),
    refresh_hours: int = 1,
) -> bytes:
    """编码 Apple HTTP subscription 使用的 VCALENDAR。"""
    calendar = _calendar(name=name, method="PUBLISH")
    calendar.add("X-PUBLISHED-TTL", f"PT{refresh_hours}H")
    calendar.add("REFRESH-INTERVAL;VALUE=DURATION", f"PT{refresh_hours}H")
    for resource in (*tuple(events), *tuple(todos), *tuple(reminders)):
        _validate_resource(resource)
        for component in build_event_components(resource):
            calendar.add_component(component)
    return calendar.to_ical()


def build_event_components(resource: IcalEventResource) -> tuple[Event, ...]:
    master = _event_component(resource)
    overrides = tuple(_override_component(resource, item) for item in resource.overrides)
    return (master, *overrides)


def decode_event_resource(payload: bytes | str) -> ParsedCalendarObject:
    """解析单个 VEVENT resource；拒绝多 UID、多 master 和非法时间形状。"""
    try:
        calendar = Calendar.from_ical(payload)
    except Exception as exc:
        raise ICalendarMappingError(f"无法解析 VCALENDAR: {exc}") from exc
    components = [item for item in calendar.walk() if item.name == "VEVENT"]
    if not components:
        raise ICalendarMappingError("VCALENDAR 不包含 VEVENT")
    parsed = tuple(_parse_component(item) for item in components)
    uids = {item.uid for item in parsed}
    if "" in uids or len(uids) != 1:
        raise ICalendarMappingError("同一 resource 的所有 VEVENT 必须有且只有一个 UID")
    masters = [item for item in parsed if item.recurrence_id is None]
    if len(masters) != 1:
        raise ICalendarMappingError("同一 resource 必须恰好包含一个 master VEVENT")
    overrides = tuple(item for item in parsed if item.recurrence_id is not None)
    return ParsedCalendarObject(uid=next(iter(uids)), master=masters[0], overrides=overrides)


def _calendar(*, name: str | None, method: str | None) -> Calendar:
    calendar = Calendar()
    calendar.add("PRODID", PRODID)
    calendar.add("VERSION", "2.0")
    calendar.add("CALSCALE", "GREGORIAN")
    if method:
        calendar.add("METHOD", method)
    if name:
        calendar.add("X-WR-CALNAME", name)
        calendar.add("X-WR-TIMEZONE", DEFAULT_TZID)
    calendar.add_component(_vtimezone())
    return calendar


def _vtimezone() -> Timezone:
    value = Timezone()
    value.add("TZID", DEFAULT_TZID)
    standard = TimezoneStandard()
    standard.add("DTSTART", datetime(1970, 1, 1))
    standard.add("TZOFFSETFROM", timedelta(hours=8))
    standard.add("TZOFFSETTO", timedelta(hours=8))
    standard.add("TZNAME", "CST")
    value.add_component(standard)
    return value


def _event_component(resource: IcalEventResource) -> Event:
    event = Event()
    event.add("UID", resource.ical_uid)
    event.add("SUMMARY", resource.title)
    _add_times(event, resource.start, resource.end, resource.tzid, resource.is_all_day)
    event.add("DTSTAMP", _as_utc(resource.updated_at or datetime(1970, 1, 1, tzinfo=timezone.utc)))
    event.add("LAST-MODIFIED", _as_utc(resource.updated_at or datetime(1970, 1, 1, tzinfo=timezone.utc)))
    event.add("SEQUENCE", max(resource.version, 0))
    if resource.description:
        event.add("DESCRIPTION", resource.description)
    if resource.location:
        event.add("LOCATION", resource.location)
    if resource.include_status:
        event.add("STATUS", _encode_status(resource.status))
    if resource.rrule:
        event.add("RRULE", vRecur.from_ical(resource.rrule.removeprefix("RRULE:")))
    for value in resource.rdates:
        _add_recurrence_date(event, "RDATE", value, resource.tzid, resource.is_all_day)
    for recurrence_id in resource.exdates:
        value = PlannerTimeCodec.parse_recurrence_id(recurrence_id, tzid=resource.tzid)
        _add_recurrence_date(event, "EXDATE", value, resource.tzid, resource.is_all_day)
    if resource.alarm_description:
        event.add_component(_alarm(resource.alarm_description))
    return event


def _override_component(resource: IcalEventResource, override: IcalOverride) -> Event:
    recurrence_value = PlannerTimeCodec.parse_recurrence_id(override.recurrence_id, tzid=resource.tzid)
    is_all_day = isinstance(recurrence_value, date) and not isinstance(recurrence_value, datetime)
    if is_all_day != resource.is_all_day:
        raise ICalendarMappingError("RECURRENCE-ID 类型与 DTSTART 不一致")
    event = Event()
    event.add("UID", resource.ical_uid)
    _add_temporal(event, "RECURRENCE-ID", recurrence_value, resource.tzid, is_all_day)
    patch = dict(override.patch)
    start = override.effective_start or recurrence_value
    end = override.effective_end or (start + (resource.end - resource.start))
    _add_times(event, start, end, resource.tzid, resource.is_all_day)
    event.add("SUMMARY", str(patch.get("title", resource.title)))
    description = str(patch.get("description", resource.description))
    location = str(patch.get("location", resource.location))
    if description:
        event.add("DESCRIPTION", description)
    if location:
        event.add("LOCATION", location)
    status = "cancelled" if override.kind == "cancelled" else str(patch.get("status", resource.status))
    if resource.include_status:
        event.add("STATUS", _encode_status(status))
    event.add("SEQUENCE", max(resource.version, override.version, 0))
    event.add("DTSTAMP", _as_utc(resource.updated_at or datetime(1970, 1, 1, tzinfo=timezone.utc)))
    if resource.alarm_description and override.kind != "cancelled":
        event.add_component(_alarm(resource.alarm_description))
    return event


def _parse_component(component: Event) -> ParsedEventComponent:
    uid = str(component.get("UID", "")).strip()
    start = _decoded_temporal(component, "DTSTART", required=True)
    end = _decoded_temporal(component, "DTEND", required=False)
    duration = component.decoded("DURATION", None)
    if end is not None and duration is not None:
        raise ICalendarMappingError("VEVENT 不能同时包含 DTEND 和 DURATION")
    if end is None:
        if duration is None:
            end = start + (timedelta(days=1) if _is_date(start) else timedelta(0))
        else:
            end = start + duration
    is_all_day = _is_date(start)
    if is_all_day != _is_date(end):
        raise ICalendarMappingError("DTSTART/DTEND 类型不一致")
    if end <= start:
        raise ICalendarMappingError("DTEND 必须晚于 DTSTART")
    tzid = _component_tzid(component, "DTSTART") or DEFAULT_TZID
    recurrence_id = _decoded_temporal(component, "RECURRENCE-ID", required=False)
    recurrence_range = ""
    rec_property = component.get("RECURRENCE-ID")
    if rec_property is not None:
        recurrence_range = str(rec_property.params.get("RANGE", "")).upper()
    rrule = ""
    if component.get("RRULE") is not None:
        rrule = component.get("RRULE").to_ical().decode("utf-8")
    return ParsedEventComponent(
        uid=uid,
        title=str(component.get("SUMMARY", "")),
        start=start,
        end=end,
        tzid=tzid,
        is_all_day=is_all_day,
        description=str(component.get("DESCRIPTION", "")),
        location=str(component.get("LOCATION", "")),
        status=_decode_status(str(component.get("STATUS", "CONFIRMED"))),
        rrule=rrule,
        rdates=tuple(_property_temporals(component, "RDATE")),
        exdates=tuple(_property_temporals(component, "EXDATE")),
        recurrence_id=recurrence_id,
        recurrence_range=recurrence_range,
        sequence=int(component.get("SEQUENCE", 0)),
    )


def _property_temporals(component: Event, name: str) -> list[Temporal]:
    values: list[Temporal] = []
    for prop_name, prop in component.property_items():
        if prop_name != name:
            continue
        if hasattr(prop, "dts"):
            values.extend(item.dt for item in prop.dts)
        elif hasattr(prop, "dt"):
            values.append(prop.dt)
    return values


def _decoded_temporal(component: Event, name: str, *, required: bool) -> Temporal | None:
    value = component.decoded(name, None)
    if value is None:
        if required:
            raise ICalendarMappingError(f"VEVENT 缺少 {name}")
        return None
    if not isinstance(value, (date, datetime)):
        raise ICalendarMappingError(f"{name} 不是 DATE/DATE-TIME")
    return value


def _component_tzid(component: Event, name: str) -> str:
    value = component.get(name)
    if value is None:
        return ""
    tzid = value.params.get("TZID")
    if tzid:
        return str(tzid)
    decoded = component.decoded(name, None)
    if isinstance(decoded, datetime) and decoded.tzinfo is not None:
        return getattr(decoded.tzinfo, "key", "UTC") or "UTC"
    return ""


def _add_times(event: Event, start: Temporal, end: Temporal, tzid: str, is_all_day: bool) -> None:
    if is_all_day != _is_date(start) or is_all_day != _is_date(end):
        raise ICalendarMappingError("is_all_day 与 DTSTART/DTEND 类型不一致")
    _add_temporal(event, "DTSTART", start, tzid, is_all_day)
    _add_temporal(event, "DTEND", end, tzid, is_all_day)


def _add_temporal(event: Event, name: str, value: Temporal, tzid: str, is_all_day: bool) -> None:
    if is_all_day:
        event.add(name, value)
        return
    if not isinstance(value, datetime):
        raise ICalendarMappingError(f"{name} 必须是 DATE-TIME")
    zone = ZoneInfo(tzid)
    if value.tzinfo is None:
        value = value.replace(tzinfo=zone)
    else:
        value = value.astimezone(zone)
    event.add(name, value, parameters={"TZID": tzid})


def _add_recurrence_date(event: Event, name: str, value: Temporal, tzid: str, is_all_day: bool) -> None:
    if is_all_day != _is_date(value):
        raise ICalendarMappingError(f"{name} 类型与 DTSTART 不一致")
    _add_temporal(event, name, value, tzid, is_all_day)


def _alarm(description: str) -> Alarm:
    alarm = Alarm()
    alarm.add("ACTION", "DISPLAY")
    alarm.add("DESCRIPTION", description)
    alarm.add("TRIGGER", timedelta(0))
    return alarm


def _validate_resource(resource: IcalEventResource) -> None:
    if not resource.entity_id or not resource.ical_uid or not resource.resource_name:
        raise ICalendarMappingError("resource identity 不能为空")
    if resource.end <= resource.start:
        raise ICalendarMappingError("event end 必须晚于 start")
    if resource.is_all_day != _is_date(resource.start) or resource.is_all_day != _is_date(resource.end):
        raise ICalendarMappingError("全天类型与时间字段不一致")
    PlannerTimeCodec.get_timezone(resource.tzid)


def _is_date(value: Temporal) -> bool:
    return isinstance(value, date) and not isinstance(value, datetime)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo(DEFAULT_TZID))
    return value.astimezone(timezone.utc)


def _encode_status(value: str) -> str:
    return {"confirmed": "CONFIRMED", "tentative": "TENTATIVE", "cancelled": "CANCELLED"}.get(
        value.lower(), "CONFIRMED"
    )


def _decode_status(value: str) -> str:
    return {"CONFIRMED": "confirmed", "TENTATIVE": "tentative", "CANCELLED": "cancelled"}.get(
        value.upper(), "confirmed"
    )
