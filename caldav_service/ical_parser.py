"""
CalDAV iCalendar 解析器

将客户端 PUT 上来的 iCalendar 文本解析为内部 event dict。
"""

import datetime
from typing import Optional

from icalendar import Calendar


_BEIJING_TZ = datetime.timezone(datetime.timedelta(hours=8))


def _to_beijing_str(dt) -> str:
    """将任意 datetime/date 转换为北京时间字符串。"""
    if isinstance(dt, datetime.datetime):
        if dt.tzinfo is not None:
            dt = dt.astimezone(_BEIJING_TZ)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(dt, datetime.date):
        return datetime.datetime.combine(dt, datetime.time(0, 0)).strftime("%Y-%m-%dT%H:%M:%S")
    return str(dt)


def _rrule_vrecur_to_str(vrecur) -> str:
    """将 icalendar vRecur 对象转换为 RRULE 字符串。"""
    parts = []
    for key, val in vrecur.items():
        key_upper = key.upper()
        if isinstance(val, list):
            str_vals = []
            for v in val:
                if isinstance(v, (datetime.datetime, datetime.date)):
                    str_vals.append(v.strftime("%Y%m%dT%H%M%SZ") if isinstance(v, datetime.datetime) else v.strftime("%Y%m%d"))
                else:
                    str_vals.append(str(v))
            parts.append(f"{key_upper}={','.join(str_vals)}")
        elif isinstance(val, (datetime.datetime, datetime.date)):
            if isinstance(val, datetime.datetime):
                parts.append(f"{key_upper}={val.strftime('%Y%m%dT%H%M%SZ')}")
            else:
                parts.append(f"{key_upper}={val.strftime('%Y%m%d')}")
        else:
            parts.append(f"{key_upper}={val}")
    return ";".join(parts)


def ical_to_event_dict(ical_text, existing_event: dict = None) -> dict:
    """
    将客户端上传的 iCalendar 文本解析为内部 event dict。
    若 existing_event 不为 None，则做 merge（保留内部专有字段）。

    Returns:
        event dict

    Raises:
        ValueError: 未找到 VEVENT
    """
    if isinstance(ical_text, bytes):
        ical_text_bytes = ical_text
    else:
        ical_text_bytes = ical_text.encode('utf-8')

    cal = Calendar.from_ical(ical_text_bytes)
    for component in cal.walk():
        if component.name == 'VEVENT':
            return _vevent_to_dict(component, existing_event)
    raise ValueError("No VEVENT found in iCalendar data")


def _vevent_to_dict(vevent, existing: Optional[dict]) -> dict:
    """将 VEVENT 组件转换为内部 event dict。"""
    result = existing.copy() if existing else {}

    # SUMMARY → title
    summary = vevent.get('SUMMARY')
    if summary is not None:
        result['title'] = str(summary)

    # DTSTART → start
    dtstart = vevent.get('DTSTART')
    if dtstart:
        dt = dtstart.dt
        if isinstance(dt, datetime.date) and not isinstance(dt, datetime.datetime):
            dt = datetime.datetime.combine(dt, datetime.time(0, 0))
        result['start'] = _to_beijing_str(dt)

    # DTEND → end
    dtend = vevent.get('DTEND')
    if dtend:
        dt = dtend.dt
        if isinstance(dt, datetime.date) and not isinstance(dt, datetime.datetime):
            dt = datetime.datetime.combine(dt, datetime.time(0, 0))
        result['end'] = _to_beijing_str(dt)

    # DESCRIPTION → description
    desc = vevent.get('DESCRIPTION')
    if desc is not None:
        result['description'] = str(desc)

    # LOCATION → location
    loc = vevent.get('LOCATION')
    if loc is not None:
        result['location'] = str(loc)

    # STATUS → status
    status = vevent.get('STATUS')
    if status:
        status_map = {
            'CONFIRMED': 'confirmed',
            'TENTATIVE': 'tentative',
            'CANCELLED': 'cancelled',
        }
        result['status'] = status_map.get(str(status).upper(), 'confirmed')

    # RRULE → rrule
    rrule = vevent.get('RRULE')
    if rrule:
        result['rrule'] = _rrule_vrecur_to_str(rrule)
    # 注意：如果客户端没发送 RRULE，不主动清除已有的 rrule

    result['last_modified'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return result


def extract_uid_from_ical(ical_text) -> Optional[str]:
    """从 iCalendar 文本中提取 UID。"""
    if isinstance(ical_text, str):
        ical_text = ical_text.encode('utf-8')
    cal = Calendar.from_ical(ical_text)
    for component in cal.walk():
        if component.name == 'VEVENT':
            uid = component.get('UID')
            if uid:
                return str(uid)
    return None
