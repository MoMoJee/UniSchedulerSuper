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
    REVISION_KEYS = PLANNER_KEYS | frozenset({'outport_calendar_data'})

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
    def get_rows_for_revision(cls, user: User, keys: list[str]):
        """取得可交给 django-reversion 的源行快照。

        Agent 回滚需要模型实例而非 JSON 投影；查询仍集中在本适配层，
        以免工具层重新依赖 UserData 的存储细节。
        """
        unexpected_keys = set(keys) - cls.REVISION_KEYS
        if unexpected_keys:
            raise LegacyPlannerDataError(f'不是 Planner legacy key: {sorted(unexpected_keys)}')
        return list(UserData.objects.filter(user=user, key__in=keys).order_by('id'))

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

    @staticmethod
    def replace_value(row: UserData, value: Any) -> None:
        """原样序列化任意 Planner JSON 值，用于规则段等 dict 型 legacy key。"""
        row.value = json.dumps(value)
        row.save(update_fields=['value'])


class PlannerUserDataRecord:
    """迁移期 UserData 兼容包装；Planner key 永不触发 DATA_SCHEMA 重建。"""

    def __init__(self, row: UserData):
        self._row = row

    @property
    def user(self):
        return self._row.user

    @property
    def key(self):
        return self._row.key

    @property
    def id(self):
        return self._row.id

    @property
    def value(self):
        return self._row.value

    @value.setter
    def value(self, value):
        self._row.value = value

    def get_value(self, check=False):
        """忽略 check，避免以旧 schema 投影丢弃未知字段。"""
        try:
            return json.loads(self._row.value or '')
        except (TypeError, json.JSONDecodeError) as exc:
            raise LegacyPlannerDataError(f'legacy key JSON 非法: {self._row.key}') from exc

    def set_value(self, value, check=False):
        """保持旧方法签名，但总是执行原样序列化。"""
        LegacyPlannerRepository.replace_value(self._row, value)

    def save(self, *args, **kwargs):
        """兼容显式 save 调用。"""
        return self._row.save(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._row, name)


class PlannerUserDataCompat:
    """复杂 legacy 入口使用的窄兼容 facade；仅 Planner key 走 repository。"""

    DEFAULT_VALUES = {
        'events': [],
        'todos': [],
        'reminders': [],
        'events_groups': [],
        'events_rrule_series': {},
        'rrule_series_storage': {},
    }

    @classmethod
    def get_or_initialize(cls, request, new_key, data=None):
        """兼容旧返回形状，拒绝重复源行且不重建 Planner 字段。"""
        if new_key not in LegacyPlannerRepository.PLANNER_KEYS:
            return UserData.get_or_initialize(request, new_key, data)
        if not request.user.is_authenticated:
            return None, False, {'status': 'error', 'message': 'User is not authenticated.'}

        rows = list(UserData.objects.filter(user=request.user, key=new_key).order_by('id')[:2])
        if len(rows) > 1:
            logger.warning(f'用户 {request.user.username} 的 Planner legacy key 重复: {new_key}')
            return None, False, {'status': 'error', 'message': f'重复 legacy key: {new_key}'}
        if rows:
            return PlannerUserDataRecord(rows[0]), False, {'status': 'success', 'message': f'Key <{new_key}> already exists.'}

        initial_value = cls.DEFAULT_VALUES[new_key] if data is None else data
        row = UserData.objects.create(user=request.user, key=new_key, value=json.dumps(initial_value))
        return PlannerUserDataRecord(row), True, {'status': 'success', 'message': f'Key <{new_key}> added successfully.'}


class PlannerUserDataObjectsCompat:
    """只覆盖复杂旧入口实际使用的 get/get_or_create，其他 key 委托原 manager。"""

    def get_or_create(self, *args, **kwargs):
        key = kwargs.get('key')
        user = kwargs.get('user')
        if key not in LegacyPlannerRepository.PLANNER_KEYS or user is None:
            return UserData.objects.get_or_create(*args, **kwargs)

        rows = list(UserData.objects.filter(user=user, key=key).order_by('id')[:2])
        if len(rows) > 1:
            raise LegacyPlannerDataError(f'重复 legacy key: {key}')
        if rows:
            return PlannerUserDataRecord(rows[0]), False
        defaults = kwargs.get('defaults') or {}
        raw_value = defaults.get('value', json.dumps(PlannerUserDataCompat.DEFAULT_VALUES[key]))
        row = UserData.objects.create(user=user, key=key, value=raw_value)
        return PlannerUserDataRecord(row), True

    def get(self, *args, **kwargs):
        row = UserData.objects.get(*args, **kwargs)
        if row.key in LegacyPlannerRepository.PLANNER_KEYS:
            return PlannerUserDataRecord(row)
        return row

    def __getattr__(self, name):
        return getattr(UserData.objects, name)


PlannerUserDataCompat.objects = PlannerUserDataObjectsCompat()
