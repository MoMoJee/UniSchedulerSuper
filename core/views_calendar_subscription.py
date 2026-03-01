"""
views_calendar_subscription.py
日历订阅接口 — 提供符合 RFC 5545 / Apple Calendar 标准的 iCalendar Feed

功能：
- 通过 URL 查询参数 token 鉴权（Apple 日历不支持自定义 HTTP Header）
- 输出 VEVENT 组件：日程（原生）、带 due_date 的待办（特殊日程）、提醒（特殊日程）
- 待办和提醒均转为 VEVENT + VALARM，因为 Apple 日历订阅不显示 VTODO
- 完整 VTIMEZONE 支持（Asia/Shanghai）
- UID 稳定、RRULE 直通、状态映射

API:
  GET /api/calendar/feed/?token=<token>&type=all|events|todos|reminders

设计决策：
  - Apple 日历的 HTTP 订阅(webcal) 只解析 VEVENT，完全忽略 VTODO
  - 因此 Reminder 和 To do 均转为带 VALARM 的 VEVENT 以在 Apple 日历中可见
  - Reminder 的 RRule 机制与 Events 类似：有 is_main_reminder/is_instance/series_id/is_detached
    只发送主提醒 + 脱离实例，跳过系统生成的普通实例
  - To do 只发送带 due_date 的待办，无 due_date 的不发送
"""

import datetime
import json
from typing import List, Optional

from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from rest_framework.authtoken.models import Token

from icalendar import Calendar, Event, Todo, Timezone, TimezoneStandard, Alarm

from core.models import UserData
from logger import logger


# =====================================================
# 常量
# =====================================================

CALENDAR_PRODID = "-//UniSchedulerSuper//UniScheduler//ZH"
CALENDAR_NAME = "UniScheduler"
TIMEZONE_ID = "Asia/Shanghai"
UID_DOMAIN = "unischeduler"
DEFAULT_REFRESH_HOURS = 1
REMINDER_DURATION_MINUTES = 5  # 提醒/待办转 VEVENT 的统一时长
TODO_DURATION_MINUTES = 5      # 待办转 VEVENT 的统一时长


# =====================================================
# 辅助函数
# =====================================================

def _authenticate_by_token(token_key: str):
    """
    通过 URL 查询参数中的 token 查找用户。

    Returns:
        User 对象，或 None（token 无效）
    """
    try:
        token_obj = Token.objects.select_related("user").get(key=token_key)
        return token_obj.user
    except Token.DoesNotExist:
        return None


def _build_vtimezone() -> Timezone:
    """
    构建 Asia/Shanghai 时区定义（Apple Calendar 强制要求）。
    中国大陆自 1991 年起不实行夏令时，只需 STANDARD 一段。
    """
    tz = Timezone()
    tz.add("TZID", TIMEZONE_ID)

    std = TimezoneStandard()
    std.add("DTSTART", datetime.datetime(1970, 1, 1, 0, 0, 0))
    std.add("TZOFFSETFROM", datetime.timedelta(hours=8))
    std.add("TZOFFSETTO", datetime.timedelta(hours=8))
    std.add("TZNAME", "CST")
    tz.add_component(std)

    return tz


def _parse_dt(value: str) -> Optional[datetime.datetime]:
    """
    将项目中存储的时间字符串解析为 datetime 对象。
    兼容 ISO 格式（带 T 或不带 T）。
    """
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _parse_date(value: str) -> Optional[datetime.date]:
    """
    将日期字符串（YYYY-MM-DD）解析为 date 对象。
    """
    if not value:
        return None
    try:
        # 可能是 datetime 字符串，取 date 部分
        dt = datetime.datetime.fromisoformat(value)
        return dt.date()
    except (ValueError, TypeError):
        pass
    try:
        return datetime.date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _dt_to_utc(dt: datetime.datetime) -> datetime.datetime:
    """
    将 naive datetime（视为 Asia/Shanghai）转换为 UTC。
    """
    if dt.tzinfo is not None:
        # 已有 tz，直接转 UTC
        return dt.astimezone(datetime.timezone.utc)
    # 视为北京时间 +08:00
    return dt.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=8))).astimezone(datetime.timezone.utc)


def _map_event_status(status: str) -> str:
    """Event status → iCalendar STATUS"""
    mapping = {
        "confirmed": "CONFIRMED",
        "tentative": "TENTATIVE",
        "cancelled": "CANCELLED",
    }
    return mapping.get(status, "CONFIRMED")


def _map_todo_status(status: str) -> str:
    """To do / Reminder status → iCalendar STATUS"""
    mapping = {
        "pending": "NEEDS-ACTION",
        "in-progress": "IN-PROCESS",
        "completed": "COMPLETED",
        "cancelled": "CANCELLED",
        # reminder 专用
        "active": "NEEDS-ACTION",
        "dismissed": "CANCELLED",
        "snoozed": "NEEDS-ACTION",
    }
    return mapping.get(status, "NEEDS-ACTION")


def _map_priority(importance: str, urgency: str) -> int:
    """
    importance × urgency → iCalendar PRIORITY (1-9, 0=undefined)
    """
    imp = importance.lower() if importance else ""
    urg = urgency.lower() if urgency else ""

    if imp == "important" and urg == "urgent":
        return 1
    elif imp == "important" and urg == "not-urgent":
        return 3
    elif imp == "not-important" and urg == "urgent":
        return 5
    elif imp == "not-important" and urg == "not-urgent":
        return 9
    return 0  # 未定义


def _map_reminder_priority(priority: str) -> int:
    """
    Reminder priority → iCalendar PRIORITY
    """
    mapping = {
        "critical": 1,
        "high": 2,
        "normal": 5,
        "low": 7,
        "debug": 9,
    }
    return mapping.get(priority, 5)


# =====================================================
# iCalendar 组件构建
# =====================================================

def _should_include_event(event: dict) -> bool:
    """
    判断某个 event 是否应包含在日历订阅 Feed 中。

    规则：
    - 主日程 (is_main_event=True)：✅ 发送（带 RRULE，Apple 自行展开实例）
    - 生成的实例 (is_main_event=False, is_recurring=True, is_detached=False)：❌ 跳过
    - 脱离的实例 (is_detached=True)：✅ 发送（作为独立 VEVENT，带 RECURRENCE-ID）
    - 普通非重复日程：✅ 发送
    """
    is_recurring = event.get("is_recurring", False)
    is_main_event = event.get("is_main_event", False)
    is_detached = event.get("is_detached", False)

    if is_detached:
        # 脱离的实例 → 发送为独立例外事件
        return True

    if is_recurring and not is_main_event:
        # RRule 系统生成的普通实例 → 跳过，Apple 根据主事件的 RRULE 自行展开
        return False

    # 主日程 或 普通非重复日程 → 发送
    return True


def _build_vevent(event: dict, group_map: Optional[dict] = None) -> Optional[Event]:
    """将项目 Event 数据转换为 iCalendar VEVENT 组件"""
    start = _parse_dt(event.get("start", ""))
    end = _parse_dt(event.get("end", ""))
    if not start:
        return None

    is_detached = event.get("is_detached", False)
    series_id = event.get("series_id", "")

    ve = Event()

    # UID — 脱离实例需要与原主日程共享同一系列的 UID 前缀
    # 这样 Apple 才能识别它是某个重复系列的例外
    if is_detached and series_id:
        # 脱离实例的 UID 使用 series_id，让 Apple 关联到原系列
        ve.add("UID", f"evt-series-{series_id}@{UID_DOMAIN}")
        # RECURRENCE-ID — 标识这个实例替换了系列中的哪一次
        recurrence_id = event.get("recurrence_id", "")
        if recurrence_id:
            rec_dt = _parse_rrule_datetime(recurrence_id)
            if rec_dt:
                ve.add("RECURRENCE-ID", rec_dt, parameters={"TZID": TIMEZONE_ID})
    elif event.get("is_main_event", False) and series_id:
        # 主日程的 UID 使用 series_id，保证系列稳定
        ve.add("UID", f"evt-series-{series_id}@{UID_DOMAIN}")
    else:
        ve.add("UID", f"evt-{event['id']}@{UID_DOMAIN}")

    # SUMMARY — 若事件属于某个日程组，则在标题前添加 [组名] 标识
    title = event.get("title", "（无标题）")
    if group_map:
        gid = event.get("groupID", "")
        if gid and gid in group_map:
            title = f"[{group_map[gid]}] {title}"
    ve.add("SUMMARY", title)

    # DTSTAMP — 必填，取 last_modified 或当前时间
    dtstamp = _parse_dt(event.get("last_modified", ""))
    ve.add("DTSTAMP", _dt_to_utc(dtstamp) if dtstamp else _dt_to_utc(datetime.datetime.now()))

    # DTSTART / DTEND — 带时区
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

    # RRULE — 仅主日程输出（脱离实例不需要 RRULE）
    if not is_detached:
        rrule_str = event.get("rrule", "")
        if rrule_str:
            ve.add("RRULE", _parse_rrule_to_dict(rrule_str))

    return ve


def _parse_rrule_datetime(val: str) -> Optional[datetime.datetime]:
    """
    解析 RRULE 中的日期时间值，如 "20260301T120000Z" 或 "20260301"。
    """
    val = val.strip()
    try:
        if val.endswith("Z"):
            val = val[:-1]
            dt = datetime.datetime.strptime(val, "%Y%m%dT%H%M%S")
            return dt.replace(tzinfo=datetime.timezone.utc)
        elif "T" in val:
            return datetime.datetime.strptime(val, "%Y%m%dT%H%M%S")
        else:
            return datetime.datetime.strptime(val, "%Y%m%d")
    except (ValueError, TypeError):
        return None


# RRULE 中需要作为 datetime 处理的参数名
_RRULE_DATE_KEYS = {"UNTIL"}
# RRULE 中需要作为 int 处理的参数名
_RRULE_INT_KEYS = {"COUNT", "INTERVAL"}


def _parse_rrule_to_dict(rrule_str: str) -> dict:
    """
    将 "FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=10" 格式的 RRULE 字符串
    解析为 icalendar 库 vRecur 需要的 dict 格式。
    
    注意：UNTIL 等日期参数必须转为 datetime 对象，否则 icalendar 序列化会报错。
    """
    result = {}
    # 去掉可能的 "RRULE:" 前缀
    if rrule_str.upper().startswith("RRULE:"):
        rrule_str = rrule_str[6:]
    
    for part in rrule_str.split(";"):
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        key = key.strip().upper()

        if key in _RRULE_DATE_KEYS:
            # UNTIL → datetime 对象
            dt = _parse_rrule_datetime(val)
            if dt:
                result[key] = dt
        elif key in _RRULE_INT_KEYS:
            # COUNT / INTERVAL → int
            try:
                result[key] = int(val)
            except ValueError:
                result[key] = val.strip()
        elif "," in val:
            # 逗号分隔的值 → 列表（如 BYDAY=MO,WE,FR）
            result[key] = [v.strip() for v in val.split(",")]
        else:
            result[key] = val.strip()
    return result


def _build_valarm(description: str = "提醒") -> Alarm:
    """
    构建 VALARM 组件，在事件开始时触发通知。
    """
    alarm = Alarm()
    alarm.add("ACTION", "DISPLAY")
    alarm.add("DESCRIPTION", description)
    alarm.add("TRIGGER", datetime.timedelta(0))  # 事件开始时触发
    return alarm


def _build_vevent_from_todo(todo: dict, group_map: Optional[dict] = None) -> Optional[Event]:
    """
    将带有 due_date 的 Todo 转换为 VEVENT + VALARM。
    
    Apple 日历订阅不显示 VTODO，因此待办转为带提醒的特殊日程。
    - 标题前缀 [待办]
    - 时长固定 5 分钟
    - 附带 VALARM 在事件开始时弹出提醒
    - 不带 due_date 的待办不发送（由 feed 视图过滤）
    """
    due_str = todo.get("due_date", "")
    if not due_str:
        return None

    # 解析 due_date —— 可能是 "2026-03-01" 或 "2026-03-01T14:00:00"
    due_dt = _parse_dt(due_str)
    if due_dt is None:
        return None

    # 若为纯日期格式（时分秒全为0），则设置默认时间 09:00
    if due_dt.hour == 0 and due_dt.minute == 0 and due_dt.second == 0:
        # 检查原始字符串是否不含 T，确认确实是纯日期
        if "T" not in due_str:
            due_dt = due_dt.replace(hour=9, minute=0, second=0)

    ve = Event()
    ve.add("UID", f"todo-{todo['id']}@{UID_DOMAIN}")
    # SUMMARY — [待办] 固定前缀；若属于某日程组，追加 [组名]
    todo_title = todo.get('title', '（无标题）')
    if group_map:
        gid = todo.get("groupID", "")
        if gid and gid in group_map:
            todo_title = f"{todo_title} [{group_map[gid]}]"
    ve.add("SUMMARY", f"[待办] {todo_title}")

    # DTSTAMP
    dtstamp = _parse_dt(todo.get("last_modified", "")) or _parse_dt(todo.get("created_at", ""))
    ve.add("DTSTAMP", _dt_to_utc(dtstamp) if dtstamp else _dt_to_utc(datetime.datetime.now()))

    # DTSTART / DTEND — 固定 5 分钟时长
    ve.add("DTSTART", due_dt, parameters={"TZID": TIMEZONE_ID})
    ve.add("DTEND", due_dt + datetime.timedelta(minutes=TODO_DURATION_MINUTES),
           parameters={"TZID": TIMEZONE_ID})

    # DESCRIPTION
    desc = todo.get("description", "")
    if desc:
        ve.add("DESCRIPTION", desc)

    # VALARM — 事件开始时弹出提醒
    ve.add_component(_build_valarm(f"待办提醒：{todo.get('title', '')}"))

    return ve


def _should_include_reminder(reminder: dict) -> bool:
    """
    判断某个 Reminder 是否应包含在日历订阅 Feed 中。
    
    Reminder 的 RRule 机制与 Events 类似：
    - 主提醒 (is_main_reminder=True)：✅ 发送（带 RRULE，Apple 自行展开）
    - 生成的实例 (is_main_reminder=False, is_instance=True, is_detached=False)：❌ 跳过
    - 脱离的实例 (is_detached=True)：✅ 发送
    - 普通非重复提醒：✅ 发送
    """
    is_detached = reminder.get("is_detached", False)
    if is_detached:
        return True

    is_recurring = reminder.get("is_recurring", False)
    is_main_reminder = reminder.get("is_main_reminder", False)
    is_instance = reminder.get("is_instance", False)

    if is_recurring and not is_main_reminder:
        # RRule 系统生成的普通实例 → 跳过
        return False
    if is_instance and not is_main_reminder:
        # 额外安全检查：is_instance=True 标记的也跳过
        return False

    return True


def _build_vevent_from_reminder(reminder: dict) -> Optional[Event]:
    """
    将 Reminder 转换为 VEVENT + VALARM。
    
    Apple 日历订阅不显示 VTODO，因此提醒转为带 VALARM 的特殊日程。
    - 标题前缀 [提醒]
    - 时长固定 5 分钟
    - 附带 VALARM 在事件开始时弹出提醒
    - 不关心 priority/status 等无法映射的属性
    """
    trigger_time = _parse_dt(reminder.get("trigger_time", ""))
    if not trigger_time:
        return None

    is_detached = reminder.get("is_detached", False)
    is_main_reminder = reminder.get("is_main_reminder", False)
    series_id = reminder.get("series_id", "")

    ve = Event()

    # UID — 与 Events 相同策略：同一重复系列共享 UID
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

    # DESCRIPTION
    content = reminder.get("content", "")
    if content:
        ve.add("DESCRIPTION", content)

    # RRULE — 仅主提醒输出（脱离实例不需要 RRULE）
    if not is_detached:
        rrule_str = reminder.get("rrule", "")
        if rrule_str:
            ve.add("RRULE", _parse_rrule_to_dict(rrule_str))

    # VALARM — 事件开始时弹出提醒
    ve.add_component(_build_valarm(f"提醒：{reminder.get('title', '')}"))

    return ve


# =====================================================
# 主视图函数
# =====================================================

@csrf_exempt
@require_GET
def calendar_feed(request):
    """
    日历订阅 Feed 接口
    
    GET /api/calendar/feed/?token=<token>&type=all|events|todos|reminders
    
    无需 Session 登录，通过 URL 查询参数 token 鉴权。
    返回符合 RFC 5545 / Apple Calendar 标准的 iCalendar 文件。
    """
    # ========== 鉴权 ==========
    token_key = request.GET.get("token", "").strip()
    if not token_key:
        return HttpResponseBadRequest("Missing 'token' parameter.")

    user = _authenticate_by_token(token_key)
    if user is None:
        return HttpResponseForbidden("Invalid token.")

    # ========== 参数解析 ==========
    feed_type = request.GET.get("type", "all").lower()
    if feed_type not in ("all", "events", "todos", "reminders"):
        return HttpResponseBadRequest("Invalid 'type' parameter. Use: all, events, todos, reminders")

    include_events = feed_type in ("all", "events")
    include_todos = feed_type in ("all", "todos")
    include_reminders = feed_type in ("all", "reminders")

    # ========== 加载日程组映射（group_id -> group_name） ==========
    group_map: dict = {}
    try:
        groups_data = UserData.objects.get(user=user, key="events_groups")
        groups = json.loads(groups_data.value)
        if isinstance(groups, list):
            group_map = {g["id"]: g["name"] for g in groups if g.get("id") and g.get("name")}
    except UserData.DoesNotExist:
        pass
    except Exception as e:
        logger.warning(f"Calendar feed - failed to load events_groups for user {user.username}: {e}")

    # ========== 构建日历 ==========
    cal = Calendar()
    cal.add("PRODID", CALENDAR_PRODID)
    cal.add("VERSION", "2.0")
    cal.add("CALSCALE", "GREGORIAN")
    cal.add("METHOD", "PUBLISH")
    cal.add("X-WR-CALNAME", f"{CALENDAR_NAME} - {user.username}")
    cal.add("X-WR-TIMEZONE", TIMEZONE_ID)
    cal.add("X-PUBLISHED-TTL", f"PT{DEFAULT_REFRESH_HOURS}H")
    cal.add("REFRESH-INTERVAL;VALUE=DURATION", f"PT{DEFAULT_REFRESH_HOURS}H")

    # 时区定义
    cal.add_component(_build_vtimezone())

    component_count = 0

    # ========== VEVENT（日程） ==========
    if include_events:
        try:
            events_data = UserData.objects.get(user=user, key="events")
            events = json.loads(events_data.value)
            if isinstance(events, list):
                for event in events:
                    # 只发送主日程 + 脱离实例 + 普通日程
                    # 跳过 RRule 系统生成的普通实例（Apple 根据 RRULE 自行展开）
                    if not _should_include_event(event):
                        continue
                    ve = _build_vevent(event, group_map)
                    if ve:
                        cal.add_component(ve)
                        component_count += 1
        except UserData.DoesNotExist:
            pass
        except Exception as e:
            logger.error(f"Calendar feed - failed to load events for user {user.username}: {e}")

    # ========== VEVENT — 待办（带 due_date 的转为特殊日程 + VALARM） ==========
    if include_todos:
        try:
            todos_data = UserData.objects.get(user=user, key="todos")
            todos = json.loads(todos_data.value)
            if isinstance(todos, list):
                for todo in todos:
                    # 只发送带 due_date 的待办
                    if not todo.get("due_date"):
                        continue
                    ve = _build_vevent_from_todo(todo, group_map)
                    if ve:
                        cal.add_component(ve)
                        component_count += 1
        except UserData.DoesNotExist:
            pass
        except Exception as e:
            logger.error(f"Calendar feed - failed to load todos for user {user.username}: {e}")

    # ========== VEVENT — 提醒（转为特殊日程 + VALARM） ==========
    if include_reminders:
        try:
            reminders_data = UserData.objects.get(user=user, key="reminders")
            reminders = json.loads(reminders_data.value)
            if isinstance(reminders, list):
                for reminder in reminders:
                    # 只发送主提醒 + 脱离实例 + 普通提醒
                    # 跳过 RRule 系统生成的普通实例
                    if not _should_include_reminder(reminder):
                        continue
                    ve = _build_vevent_from_reminder(reminder)
                    if ve:
                        cal.add_component(ve)
                        component_count += 1
        except UserData.DoesNotExist:
            pass
        except Exception as e:
            logger.error(f"Calendar feed - failed to load reminders for user {user.username}: {e}")

    logger.info(f"Calendar feed generated for user {user.username}: type={feed_type}, components={component_count}")

    # ========== 响应 ==========
    response = HttpResponse(
        cal.to_ical(),
        content_type="text/calendar; charset=utf-8",
    )
    response["Content-Disposition"] = 'inline; filename="unischeduler.ics"'
    # 缓存控制：允许私有缓存 5 分钟，方便浏览器但不被 CDN 缓存
    response["Cache-Control"] = "private, max-age=300"
    return response
