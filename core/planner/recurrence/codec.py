"""Planner 时间与 RRULE 的纯解析、校验和规范化工具。"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import rrulestr


class PlannerTimeError(ValueError):
    """Planner 时间值不符合契约。"""


class InvalidRRuleError(ValueError):
    """RRULE 不符合受支持 RFC 5545 子集。"""


class PlannerTimeCodec:
    """保留 DATE、TZID 和 UTC 语义的时间编解码器。"""

    DEFAULT_TZID: Final[str] = 'Asia/Shanghai'
    _ICAL_DATE_RE: Final[re.Pattern[str]] = re.compile(r'^\d{8}$')
    _ISO_DATE_RE: Final[re.Pattern[str]] = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    _ICAL_DATETIME_RE: Final[re.Pattern[str]] = re.compile(r'^\d{8}T\d{6}Z?$')

    @classmethod
    def get_timezone(cls, tzid: str | None = None) -> ZoneInfo:
        """返回可用时区，非法 TZID 以明确异常终止而不是静默回退。"""
        try:
            return ZoneInfo(tzid or cls.DEFAULT_TZID)
        except ZoneInfoNotFoundError as exc:
            raise PlannerTimeError(f'未知时区: {tzid}') from exc

    @classmethod
    def parse_value(
        cls,
        value: str | date | datetime,
        *,
        tzid: str | None = None,
        allow_date: bool = True,
    ) -> date | datetime:
        """解析 legacy ISO 或 RFC 5545 basic 时间，并补齐浮动时间的 TZID。"""
        if isinstance(value, datetime):
            return cls.ensure_aware(value, tzid=tzid)
        if isinstance(value, date):
            if not allow_date:
                raise PlannerTimeError('此字段不允许 DATE 类型')
            return value
        if not isinstance(value, str) or not value.strip():
            raise PlannerTimeError('时间值必须是非空字符串、date 或 datetime')

        raw = value.strip()
        if cls._ICAL_DATE_RE.fullmatch(raw):
            if not allow_date:
                raise PlannerTimeError('此字段不允许 DATE 类型')
            return datetime.strptime(raw, '%Y%m%d').date()
        # datetime.fromisoformat('2026-03-01') 会返回午夜 datetime；这里必须
        # 先识别 ISO DATE，保留 RFC 5545 全天 event 的 DATE 语义。
        if cls._ISO_DATE_RE.fullmatch(raw):
            if not allow_date:
                raise PlannerTimeError('此字段不允许 DATE 类型')
            return date.fromisoformat(raw)
        if cls._ICAL_DATETIME_RE.fullmatch(raw):
            if raw.endswith('Z'):
                return datetime.strptime(raw, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
            return cls.ensure_aware(datetime.strptime(raw, '%Y%m%dT%H%M%S'), tzid=tzid)

        try:
            parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        except ValueError:
            try:
                parsed_date = date.fromisoformat(raw)
            except ValueError as exc:
                raise PlannerTimeError(f'无法解析时间值: {value}') from exc
            if not allow_date:
                raise PlannerTimeError('此字段不允许 DATE 类型')
            return parsed_date
        return cls.ensure_aware(parsed, tzid=tzid)

    @classmethod
    def ensure_aware(cls, value: datetime, *, tzid: str | None = None) -> datetime:
        """将浮动 datetime 解释为指定时区的墙上时间。"""
        if value.tzinfo is None:
            return value.replace(tzinfo=cls.get_timezone(tzid))
        return value

    @classmethod
    def to_utc(cls, value: datetime, *, tzid: str | None = None) -> datetime:
        """转换为数据库使用的 aware UTC。"""
        return cls.ensure_aware(value, tzid=tzid).astimezone(timezone.utc)

    @classmethod
    def to_local(cls, value: datetime, *, tzid: str | None = None) -> datetime:
        """转换为 recurrence 计算使用的本地墙上时间。"""
        return cls.ensure_aware(value, tzid=tzid).astimezone(cls.get_timezone(tzid))

    @classmethod
    def format_recurrence_id(cls, value: date | datetime, *, tzid: str | None = None) -> str:
        """用原 DTSTART 槽位生成稳定 RECURRENCE-ID。"""
        if isinstance(value, datetime):
            return cls.to_local(value, tzid=tzid).strftime('%Y%m%dT%H%M%S')
        return value.strftime('%Y%m%d')

    @classmethod
    def parse_recurrence_id(cls, value: str, *, tzid: str | None = None) -> date | datetime:
        """按 RECURRENCE-ID 的 DATE/DATE-TIME 类型解析槽位。"""
        return cls.parse_value(value, tzid=tzid, allow_date=True)

    @classmethod
    def recurrence_datetime(cls, value: date | datetime, *, tzid: str | None = None) -> datetime:
        """将 DATE 或 DATE-TIME 转为本地的计算 datetime。"""
        if isinstance(value, datetime):
            return cls.to_local(value, tzid=tzid)
        return datetime.combine(value, time.min, tzinfo=cls.get_timezone(tzid))


_ALLOWED_RRULE_KEYS: Final[frozenset[str]] = frozenset(
    {
        'FREQ',
        'INTERVAL',
        'COUNT',
        'UNTIL',
        'WKST',
        'BYSECOND',
        'BYMINUTE',
        'BYHOUR',
        'BYDAY',
        'BYMONTHDAY',
        'BYYEARDAY',
        'BYWEEKNO',
        'BYMONTH',
        'BYSETPOS',
    }
)
_FREQUENCIES: Final[frozenset[str]] = frozenset(
    {'SECONDLY', 'MINUTELY', 'HOURLY', 'DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'}
)
_INTEGER_LIST_KEYS: Final[frozenset[str]] = frozenset(
    {'BYSECOND', 'BYMINUTE', 'BYHOUR', 'BYMONTHDAY', 'BYYEARDAY', 'BYWEEKNO', 'BYMONTH', 'BYSETPOS'}
)
_WEEKDAY_RE: Final[re.Pattern[str]] = re.compile(r'^[+-]?\d{0,2}(MO|TU|WE|TH|FR|SA|SU)$')
_WEEKDAY_VALUES: Final[frozenset[str]] = frozenset({'MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'})


def canonicalize_rrule(
    rrule: str,
    *,
    dtstart: date | datetime,
    tzid: str | None = None,
) -> str:
    """校验并 canonicalize 单条 RFC 5545 RRULE。"""
    if not isinstance(rrule, str) or not rrule.strip():
        raise InvalidRRuleError('RRULE 不能为空')

    raw = rrule.strip()
    if raw.upper().startswith('RRULE:'):
        raw = raw[6:]
    if raw.endswith(';'):
        raw = raw[:-1]
    if not raw:
        raise InvalidRRuleError('RRULE 不能为空')

    parts: dict[str, str] = {}
    for component in raw.split(';'):
        if '=' not in component:
            raise InvalidRRuleError(f'RRULE 缺少键值分隔符: {component}')
        key, value = component.split('=', 1)
        key = key.strip().upper()
        value = value.strip().upper()
        if key not in _ALLOWED_RRULE_KEYS:
            raise InvalidRRuleError(f'不支持的 RRULE 字段: {key}')
        if not value:
            raise InvalidRRuleError(f'RRULE 字段不能为空: {key}')
        if key in parts:
            raise InvalidRRuleError(f'RRULE 字段重复: {key}')
        parts[key] = value

    frequency = parts.get('FREQ')
    if frequency not in _FREQUENCIES:
        raise InvalidRRuleError('RRULE 必须包含受支持的 FREQ')
    if 'COUNT' in parts and 'UNTIL' in parts:
        raise InvalidRRuleError('COUNT 与 UNTIL 不可同时出现')

    for key in ('COUNT', 'INTERVAL'):
        if key in parts:
            try:
                numeric = int(parts[key])
            except ValueError as exc:
                raise InvalidRRuleError(f'{key} 必须是整数') from exc
            if numeric <= 0:
                raise InvalidRRuleError(f'{key} 必须大于 0')
            parts[key] = str(numeric)

    if 'WKST' in parts and parts['WKST'] not in _WEEKDAY_VALUES:
        raise InvalidRRuleError('WKST 必须是合法星期值')
    if 'BYDAY' in parts:
        values = _canonicalize_list(parts['BYDAY'])
        if not all(_WEEKDAY_RE.fullmatch(value) for value in values):
            raise InvalidRRuleError('BYDAY 包含非法值')
        parts['BYDAY'] = ','.join(values)
    for key in _INTEGER_LIST_KEYS:
        if key in parts:
            values = _canonicalize_list(parts[key])
            try:
                normalized = sorted({int(value) for value in values})
            except ValueError as exc:
                raise InvalidRRuleError(f'{key} 必须是整数列表') from exc
            if any(value == 0 for value in normalized) and key in {'BYMONTHDAY', 'BYYEARDAY', 'BYWEEKNO', 'BYSETPOS'}:
                raise InvalidRRuleError(f'{key} 不允许 0')
            parts[key] = ','.join(str(value) for value in normalized)

    is_all_day = isinstance(dtstart, date) and not isinstance(dtstart, datetime)
    if 'UNTIL' in parts:
        parts['UNTIL'] = _canonicalize_until(parts['UNTIL'], is_all_day=is_all_day, tzid=tzid)

    canonical = ';'.join(f'{key}={parts[key]}' for key in sorted(parts))
    _validate_with_dateutil(canonical, dtstart=dtstart, tzid=tzid, is_all_day=is_all_day)
    return canonical


def _canonicalize_list(value: str) -> list[str]:
    values = [part.strip().upper() for part in value.split(',') if part.strip()]
    if not values:
        raise InvalidRRuleError('RRULE 列表不能为空')
    return sorted(set(values))


def _canonicalize_until(value: str, *, is_all_day: bool, tzid: str | None) -> str:
    parsed = PlannerTimeCodec.parse_value(value, tzid=tzid, allow_date=True)
    if is_all_day:
        if isinstance(parsed, datetime):
            raise InvalidRRuleError('DATE DTSTART 的 UNTIL 必须为 DATE')
        return parsed.strftime('%Y%m%d')
    if not isinstance(parsed, datetime):
        raise InvalidRRuleError('DATE-TIME DTSTART 的 UNTIL 必须为 DATE-TIME')
    return PlannerTimeCodec.to_utc(parsed, tzid=tzid).strftime('%Y%m%dT%H%M%SZ')


def _validate_with_dateutil(
    rrule: str,
    *,
    dtstart: date | datetime,
    tzid: str | None,
    is_all_day: bool,
) -> None:
    try:
        if is_all_day:
            validation_start = datetime.combine(dtstart, time.min)
        else:
            validation_start = PlannerTimeCodec.ensure_aware(dtstart, tzid=tzid)
        rrulestr(rrule, dtstart=validation_start)
    except (TypeError, ValueError) as exc:
        raise InvalidRRuleError(f'RRULE 无法展开: {exc}') from exc
