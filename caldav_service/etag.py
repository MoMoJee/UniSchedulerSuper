"""
ETag / CTag 计算工具

- ETag：事件级别，用于缓存和冲突检测
- CTag：日历集合级别，用于判断集合是否有变化
"""

import hashlib


def compute_event_etag(event: dict) -> str:
    """基于 id + last_modified 计算事件 ETag。"""
    raw = f"{event.get('id', '')}:{event.get('last_modified', '')}"
    return f'"{hashlib.sha256(raw.encode()).hexdigest()[:32]}"'


def compute_calendar_ctag(events: list) -> str:
    """
    取所有事件中 last_modified 的最大值 + 事件数量作为 CTag。
    任何增删改都会使 CTag 变化。
    """
    if not events:
        return '"empty-0"'
    latest = max((e.get('last_modified', '') for e in events), default='')
    raw = f"{latest}:{len(events)}"
    return f'"{hashlib.sha256(raw.encode()).hexdigest()[:32]}"'
