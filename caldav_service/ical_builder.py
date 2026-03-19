"""
CalDAV iCalendar 构建器

将内部 event/todo/reminder dict 转换为 RFC 5545 iCalendar 文本。
复用 core.views_calendar_subscription 中的辅助函数。
"""

import datetime
from typing import Optional

from icalendar import Calendar, Event, Timezone, TimezoneStandard, Alarm

# 从现有订阅模块复用常量和辅助函数
from core.views_calendar_subscription import (
    CALENDAR_PRODID,
    TIMEZONE_ID,
    UID_DOMAIN,
    REMINDER_DURATION_MINUTES,
    _build_vtimezone,
    _parse_dt,
    _dt_to_utc,
    _map_event_status,
    _parse_rrule_to_dict,
    _parse_rrule_datetime,
    _build_valarm,
    _should_include_reminder,
)


def build_single_event_ical(event: dict) -> bytes:
    """
    将单个 event dict 构建为完整的 iCalendar 文本（包含 VCALENDAR 包装）。
    用于 CalDAV GET 响应。
    """
    cal = Calendar()
    cal.add("PRODID", CALENDAR_PRODID)
    cal.add("VERSION", "2.0")
    cal.add("CALSCALE", "GREGORIAN")
    cal.add_component(_build_vtimezone())

    ve = _build_caldav_vevent(event)
    if ve:
        cal.add_component(ve)

    return cal.to_ical()


def _build_caldav_vevent(event: dict) -> Optional[Event]:
    """
    将 event dict 转换为 VEVENT 组件。
    与订阅 Feed 不同，CalDAV 版本不添加 [组名] 前缀。
    """
    start = _parse_dt(event.get("start", ""))
    end = _parse_dt(event.get("end", ""))
    if not start:
        return None

    is_detached = event.get("is_detached", False)
    series_id = event.get("series_id", "")

    ve = Event()

    # UID — 如果有 caldav_uid（CalDAV 客户端写入时保存的）则原样返回
    caldav_uid = event.get('caldav_uid')
    if is_detached and series_id:
        ve.add("UID", caldav_uid or f"evt-series-{series_id}@{UID_DOMAIN}")
        recurrence_id = event.get("recurrence_id", "")
        if recurrence_id:
            rec_dt = _parse_rrule_datetime(recurrence_id)
            if rec_dt:
                ve.add("RECURRENCE-ID", rec_dt, parameters={"TZID": TIMEZONE_ID})
    elif event.get("is_main_event", False) and series_id:
        ve.add("UID", caldav_uid or f"evt-series-{series_id}@{UID_DOMAIN}")
    elif caldav_uid:
        ve.add("UID", caldav_uid)
    else:
        ve.add("UID", f"{event['id']}@{UID_DOMAIN}")

    # SUMMARY
    ve.add("SUMMARY", event.get("title", ""))

    # DTSTAMP
    dtstamp = _parse_dt(event.get("last_modified", ""))
    ve.add("DTSTAMP", _dt_to_utc(dtstamp) if dtstamp else _dt_to_utc(datetime.datetime.now()))

    # DTSTART / DTEND
    ve.add("DTSTART", start, parameters={"TZID": TIMEZONE_ID})
    if end:
        ve.add("DTEND", end, parameters={"TZID": TIMEZONE_ID})

    # LAST-MODIFIED
    if dtstamp:
        ve.add("LAST-MODIFIED", _dt_to_utc(dtstamp))

    # DESCRIPTION
    desc = event.get("description", "")
    if desc:
        ve.add("DESCRIPTION", desc)

    # LOCATION
    location = event.get("location", "")
    if location:
        ve.add("LOCATION", location)

    # STATUS
    status = event.get("status", "confirmed")
    ve.add("STATUS", _map_event_status(status))

    # RRULE — 仅主日程
    if not is_detached:
        rrule_str = event.get("rrule", "")
        if rrule_str:
            ve.add("RRULE", _parse_rrule_to_dict(rrule_str))

    return ve


def get_event_uid(event: dict) -> str:
    """
    获取事件的文件名 UID（不含 @domain 后缀），用作 .ics 文件名。
    对于 CalDAV 客户端创建的事件，直接使用事件 id（即客户端提供的 UID），
    确保 UID 往返一致，避免客户端看到不同 UID 导致重复。
    """
    is_detached = event.get("is_detached", False)
    series_id = event.get("series_id", "")

    if is_detached and series_id:
        return f"evt-series-{series_id}"
    elif event.get("is_main_event", False) and series_id:
        return f"evt-series-{series_id}"
    else:
        return event['id']


# =====================================================
# Reminder → iCalendar
# =====================================================

def build_single_reminder_ical(reminder: dict) -> bytes:
    """
    将单个 reminder dict 构建为完整的 iCalendar 文本。
    提醒转为带 VALARM 的 VEVENT（CalDAV 标准不支持独立提醒）。
    """
    cal = Calendar()
    cal.add("PRODID", CALENDAR_PRODID)
    cal.add("VERSION", "2.0")
    cal.add("CALSCALE", "GREGORIAN")
    cal.add_component(_build_vtimezone())

    ve = _build_caldav_vevent_from_reminder(reminder)
    if ve:
        cal.add_component(ve)

    return cal.to_ical()


def _build_caldav_vevent_from_reminder(reminder: dict) -> Optional[Event]:
    """将 reminder dict 转为 VEVENT + VALARM（与订阅 Feed 逻辑一致）。"""
    trigger_time = _parse_dt(reminder.get("trigger_time", ""))
    if not trigger_time:
        return None

    is_detached = reminder.get("is_detached", False)
    is_main_reminder = reminder.get("is_main_reminder", False)
    series_id = reminder.get("series_id", "")

    ve = Event()

    # UID
    if is_detached and series_id:
        ve.add("UID", f"rem-series-{series_id}@{UID_DOMAIN}")
        recurrence_id = reminder.get("recurrence_id", "")
        if recurrence_id:
            rec_dt = _parse_rrule_datetime(recurrence_id)
            if rec_dt:
                ve.add("RECURRENCE-ID", rec_dt, parameters={"TZID": TIMEZONE_ID})
    elif is_main_reminder and series_id:
        ve.add("UID", f"rem-series-{series_id}@{UID_DOMAIN}")
    else:
        ve.add("UID", f"rem-{reminder['id']}@{UID_DOMAIN}")

    ve.add("SUMMARY", f"[提醒] {reminder.get('title', '（无标题）')}")

    # DTSTAMP
    dtstamp = _parse_dt(reminder.get("last_modified", "")) or _parse_dt(reminder.get("created_at", ""))
    ve.add("DTSTAMP", _dt_to_utc(dtstamp) if dtstamp else _dt_to_utc(datetime.datetime.now()))

    # DTSTART / DTEND — 固定 5 分钟时长
    ve.add("DTSTART", trigger_time, parameters={"TZID": TIMEZONE_ID})
    ve.add("DTEND", trigger_time + datetime.timedelta(minutes=REMINDER_DURATION_MINUTES),
           parameters={"TZID": TIMEZONE_ID})

    # LAST-MODIFIED
    if dtstamp:
        ve.add("LAST-MODIFIED", _dt_to_utc(dtstamp))

    # DESCRIPTION
    content = reminder.get("content", "")
    if content:
        ve.add("DESCRIPTION", content)

    # RRULE — 仅主提醒
    if not is_detached:
        rrule_str = reminder.get("rrule", "")
        if rrule_str:
            ve.add("RRULE", _parse_rrule_to_dict(rrule_str))

    # VALARM
    ve.add_component(_build_valarm(f"提醒：{reminder.get('title', '')}"))

    return ve


def get_reminder_uid(reminder: dict) -> str:
    """获取提醒的 UID（不含 @domain），用作 .ics 文件名。"""
    is_detached = reminder.get("is_detached", False)
    series_id = reminder.get("series_id", "")

    if is_detached and series_id:
        return f"rem-series-{series_id}"
    elif reminder.get("is_main_reminder", False) and series_id:
        return f"rem-series-{series_id}"
    else:
        return f"rem-{reminder['id']}"


def should_include_reminder(reminder: dict) -> bool:
    """判断提醒是否应在 CalDAV 中暴露（复用订阅 Feed 逻辑）。"""
    return _should_include_reminder(reminder)
