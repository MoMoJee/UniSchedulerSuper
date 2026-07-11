"""迁移期唯一允许理解 legacy Planner JSON 的适配层。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from django.contrib.auth.models import User

from core.models import UserData
from logger import logger


class LegacyPlannerDataError(ValueError):
    """legacy Planner 源数据不可被无损读取。"""


@dataclass(frozen=True)
class LegacyPlannerPayload:
    """保留源行身份和校验和的只读 JSON 快照。"""

    user_id: int
    key: str
    source_row_id: int
    checksum: str
    value: Any


class LegacyPlannerRepository:
    """不经 DATA_SCHEMA 重建、不改写 legacy JSON 的只读访问入口。"""

    PLANNER_KEYS = frozenset(
        {
            'events',
            'todos',
            'reminders',
            'events_groups',
            'events_rrule_series',
            'rrule_series_storage',
        }
    )

    @classmethod
    def read(cls, user: User, key: str, *, expected_type: type | None = None) -> LegacyPlannerPayload | None:
        """读取唯一源行；重复 key 或非法 JSON 必须显式终止迁移。"""
        if key not in cls.PLANNER_KEYS:
            raise LegacyPlannerDataError(f'不是 Planner legacy key: {key}')

        rows = list(UserData.objects.filter(user=user, key=key).order_by('id')[:2])
        if not rows:
            return None
        if len(rows) > 1:
            logger.warning(f'用户 {user.username} 的 Planner legacy key 重复: {key}')
            raise LegacyPlannerDataError(f'重复 legacy key: {key}')

        row = rows[0]
        raw_value = row.value or ''
        try:
            value = json.loads(raw_value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise LegacyPlannerDataError(f'legacy key JSON 非法: {key}') from exc
        if expected_type is not None and not isinstance(value, expected_type):
            raise LegacyPlannerDataError(f'legacy key 类型错误: {key}')

        return LegacyPlannerPayload(
            user_id=user.id,
            key=key,
            source_row_id=row.id,
            checksum=hashlib.sha256(raw_value.encode('utf-8')).hexdigest(),
            value=value,
        )

    @classmethod
    def read_list(cls, user: User, key: str) -> LegacyPlannerPayload | None:
        """读取列表型 Planner key，并保留未知字段。"""
        return cls.read(user, key, expected_type=list)

    @classmethod
    def read_events(cls, user: User) -> LegacyPlannerPayload | None:
        """读取 legacy events。"""
        return cls.read_list(user, 'events')

    @classmethod
    def read_todos(cls, user: User) -> LegacyPlannerPayload | None:
        """读取 legacy todos。"""
        return cls.read_list(user, 'todos')

    @classmethod
    def read_reminders(cls, user: User) -> LegacyPlannerPayload | None:
        """读取 legacy reminders。"""
        return cls.read_list(user, 'reminders')

    @classmethod
    def read_groups(cls, user: User) -> LegacyPlannerPayload | None:
        """读取 legacy events_groups。"""
        return cls.read_list(user, 'events_groups')

    @classmethod
    def get_list_for_update(cls, user: User, key: str):
        """在调用方事务中读取或初始化列表型 key，供兼容写路径集中使用。"""
        if key not in cls.PLANNER_KEYS:
            raise LegacyPlannerDataError(f'不是 Planner legacy key: {key}')
        rows = list(UserData.objects.select_for_update().filter(user=user, key=key).order_by('id')[:2])
        if len(rows) > 1:
            logger.warning(f'用户 {user.username} 的 Planner legacy key 重复: {key}')
            raise LegacyPlannerDataError(f'重复 legacy key: {key}')
        if not rows:
            row = UserData.objects.create(user=user, key=key, value='[]')
            return row, []

        row = rows[0]
        try:
            value = json.loads(row.value or '')
        except (TypeError, json.JSONDecodeError) as exc:
            raise LegacyPlannerDataError(f'legacy key JSON 非法: {key}') from exc
        if not isinstance(value, list):
            raise LegacyPlannerDataError(f'legacy key 类型错误: {key}')
        return row, value

    @staticmethod
    def replace_list(row: UserData, value: list) -> None:
        """原样序列化列表，不执行 DATA_SCHEMA 重建或丢弃未知字段。"""
        if not isinstance(value, list):
            raise LegacyPlannerDataError('写入 legacy Planner 数据时必须提供 list')
        row.value = json.dumps(value)
        row.save(update_fields=['value'])
