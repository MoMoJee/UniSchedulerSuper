"""经用户确认的、checksum 锁定的 legacy Planner 修复清单。

修复只作用于迁移内存副本，绝不改写 UserData 源行。源 checksum 变化时规则
自动失效并拒绝套用，避免把一次性判断扩散到其他用户或未来数据。
"""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from typing import Any

from core.planner.recurrence.codec import PlannerTimeCodec


MOMOJEE_EVENTS_CHECKSUM = '14ecb36118495a52513c4265014eaa2895829c66df04ed3d54e02d335d59b9ba'
MOMOJEE_MISSING_END_EVENT_ID = '13a0bda8-7ef0-49db-88cf-4fad16d2351f'
MOMOJEE_DELETED_SHARE_EVENT_ID = '45d3eed2-957a-423a-99ff-5bfc7a01c165'
MOMOJEE_DELETED_SHARE_GROUP_ID = 'share_group_ba0f68b98d7a'
MOMOJEE_DELETED_SHARE_GROUP_IDS = frozenset(
    {
        MOMOJEE_DELETED_SHARE_GROUP_ID,
        'share_group_b24c1a748e6d',
        'share_group_81acc54279b7',
        'share_group_6523a574804c',
        'share_group_ddf22df46d04',
        'share_group_5a017e3c96aa',
    }
)


def apply_legacy_repairs(*, username: str, source_key: str, checksum: str, row: dict[str, Any]) -> dict[str, Any]:
    """返回修复后的行副本；不匹配 manifest 时原样复制。"""
    repaired = deepcopy(row)
    if username != 'MoMoJee' or source_key != 'events' or checksum != MOMOJEE_EVENTS_CHECKSUM:
        return repaired

    legacy_id = str(repaired.get('id') or '')
    repairs = list(repaired.get('_planner_migration_repairs') or [])
    if legacy_id == MOMOJEE_MISSING_END_EVENT_ID and repaired.get('end') in (None, ''):
        # 旧 Web 创建器的明确定义默认时长为一小时；保留原始缺失事实和采用的
        # 兼容规则，避免将推导值伪装成原始数据。
        start = PlannerTimeCodec.parse_value(repaired.get('start'), allow_date=False)
        repaired['end'] = (start + timedelta(hours=1)).replace(tzinfo=None).isoformat(timespec='seconds')
        repairs.append(
            {
                'code': 'missing_end_default_duration',
                'legacy_value': None,
                'duration_seconds': 3600,
                'basis': 'legacy_web_default_duration',
            }
        )
    share_ids = list(repaired.get('shared_to_groups') or [])
    removed_share_ids = sorted(set(share_ids) & MOMOJEE_DELETED_SHARE_GROUP_IDS)
    if removed_share_ids:
        repaired['shared_to_groups'] = [item for item in share_ids if item not in MOMOJEE_DELETED_SHARE_GROUP_IDS]
        for share_group_id in removed_share_ids:
            repairs.append(
                {
                    'code': 'deleted_share_group_reference',
                    'share_group_id': share_group_id,
                    'basis': 'missing_collaborative_group_tombstone',
                }
            )
    if repairs:
        repaired['_planner_migration_repairs'] = repairs
    return repaired
