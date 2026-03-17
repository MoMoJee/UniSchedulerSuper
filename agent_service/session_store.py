"""
会话状态存储封装器 (Session Store)

作为 LangGraph checkpointer 的轻量级补充：
- 提供显式的状态快照管理（基于 AgentSession.state_snapshot 字段）
- 与 ContextBuilder 配合使用
- 支持检查点历史

状态快照存储格式（AgentSession.state_snapshot JSON 字段）:
{
    "latest": {
        "checkpoint_id": "...",
        "phase": "executing",
        "active_skills": [1, 2],
        "focus_files": [],
        "accumulated_findings": [],
        "pending_tasks": [],
        "tool_results_summary": [],
        "metadata": {},
        "created_at": "2026-..."
    },
    "history": [...]  // 最多保留 10 个历史版本
}

Author: Agent Service
Created: 2026-03-14
Updated: 2026-03-15 - 修复死代码：移除对不存在模型(AgentStateSnapshot/MessagePart)的依赖，
                       改为使用 AgentSession.state_snapshot JSONField 存储快照数据
"""

import datetime
from typing import Dict, List, Optional, Any

from django.contrib.auth.models import User

from agent_service.models import AgentSession

from logger import logger

# 单个会话最多保留的历史快照数量
_MAX_SNAPSHOT_HISTORY = 10


class SessionStore:
    """
    会话状态存储封装器

    提供显式的状态管理，与 LangGraph checkpointer 配合使用：
    - 状态快照管理（基于 AgentSession.state_snapshot JSONField）
    - 检查点历史（最多 10 个历史版本）

    注意：目前作为 LangGraph checkpointer 的补充，不完全替换。
    """

    def __init__(self, session: AgentSession):
        self.session = session

    def save_state_snapshot(
        self,
        checkpoint_id: str,
        phase: str = 'idle',
        active_skills: List[int] = None,
        focus_files: List[str] = None,
        accumulated_findings: List[str] = None,
        pending_tasks: List[str] = None,
        tool_results_summary: List[Dict] = None,
        metadata: Dict = None
    ) -> bool:
        """
        保存状态快照到 AgentSession.state_snapshot 字段。

        新快照成为 latest，旧 latest 被推入 history（最多保留 10 个）。

        Args:
            checkpoint_id: 检查点 ID
            phase: 当前任务阶段 (idle / planning / executing / done)
            active_skills: 激活的技能 ID 列表
            focus_files: 关注的文件路径列表
            accumulated_findings: 累积发现
            pending_tasks: 待处理任务
            tool_results_summary: 工具结果摘要
            metadata: 额外元数据

        Returns:
            是否保存成功
        """
        try:
            new_snapshot = {
                'checkpoint_id': checkpoint_id,
                'phase': phase or 'idle',
                'active_skills': active_skills or [],
                'focus_files': focus_files or [],
                'accumulated_findings': accumulated_findings or [],
                'pending_tasks': pending_tasks or [],
                'tool_results_summary': tool_results_summary or [],
                'metadata': metadata or {},
                'created_at': datetime.datetime.now().isoformat(),
            }

            current = self.session.state_snapshot or {}
            history = list(current.get('history', []))

            # 将旧的 latest 推入历史
            if current.get('latest'):
                history.append(current['latest'])
                if len(history) > _MAX_SNAPSHOT_HISTORY:
                    history = history[-_MAX_SNAPSHOT_HISTORY:]

            self.session.state_snapshot = {
                'latest': new_snapshot,
                'history': history,
            }
            self.session.save(update_fields=['state_snapshot'])

            logger.info(
                f"[SessionStore] 保存状态快照: session={self.session.session_id}, "
                f"checkpoint={checkpoint_id}, phase={phase}"
            )
            return True
        except Exception as e:
            logger.error(f"[SessionStore] 保存状态快照失败: {e}")
            return False

    def load_latest_snapshot(self) -> Optional[Dict[str, Any]]:
        """
        加载最新的状态快照。

        Returns:
            状态快照字典，如果没有则返回 None
        """
        try:
            current = self.session.state_snapshot or {}
            return current.get('latest') or None
        except Exception as e:
            logger.warning(f"[SessionStore] 加载状态快照失败: {e}")
            return None

    def list_snapshots(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        列出最近的快照（latest + history，按时间倒序）。

        Args:
            limit: 返回数量限制

        Returns:
            快照列表，每项仅包含 checkpoint_id / phase / active_skills / created_at
        """
        try:
            current = self.session.state_snapshot or {}
            all_snapshots = []

            if current.get('latest'):
                all_snapshots.append(current['latest'])
            all_snapshots.extend(reversed(current.get('history', [])))

            return [
                {
                    'checkpoint_id': s.get('checkpoint_id', ''),
                    'phase': s.get('phase', 'idle'),
                    'active_skills': s.get('active_skills', []),
                    'created_at': s.get('created_at', ''),
                }
                for s in all_snapshots[:limit]
            ]
        except Exception as e:
            logger.warning(f"[SessionStore] 列出快照失败: {e}")
            return []

    def clear_snapshots(self) -> bool:
        """
        清空所有状态快照（回滚到初始状态时调用）。

        Returns:
            是否清空成功
        """
        try:
            self.session.state_snapshot = {}
            self.session.save(update_fields=['state_snapshot'])
            logger.info(f"[SessionStore] 清空状态快照: session={self.session.session_id}")
            return True
        except Exception as e:
            logger.error(f"[SessionStore] 清空状态快照失败: {e}")
            return False


# ==========================================
# 工具函数
# ==========================================

def get_or_create_session_store(session_id: str, user: User) -> Optional[SessionStore]:
    """
    获取会话存储实例。

    Args:
        session_id: 会话 ID
        user: Django User 实例

    Returns:
        SessionStore 实例，如果会话不存在则返回 None
    """
    session = AgentSession.objects.filter(session_id=session_id).first()
    if session:
        return SessionStore(session)
    return None


def update_phase(session_id: str, user: User, phase: str) -> bool:
    """
    快速更新当前任务阶段。

    Args:
        session_id: 会话 ID
        user: Django User 实例
        phase: 新阶段名称

    Returns:
        是否更新成功
    """
    store = get_or_create_session_store(session_id, user)
    if store:
        checkpoint_id = f"phase_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        return store.save_state_snapshot(checkpoint_id, phase=phase)
    return False


def load_state_snapshot(session: AgentSession) -> Optional[Dict[str, Any]]:
    """
    读取会话最新状态快照（供可视化/调试使用）。

    Args:
        session: AgentSession 实例

    Returns:
        latest 快照字典，不存在时返回 None
    """
    try:
        snapshot = (session.state_snapshot or {}).get('latest')
        if snapshot:
            logger.debug(
                f"[SessionStore] load_state_snapshot: session={session.session_id}, "
                f"phase={snapshot.get('phase', 'idle')}, checkpoint={snapshot.get('checkpoint_id', '')}"
            )
        else:
            logger.debug(f"[SessionStore] load_state_snapshot: session={session.session_id}, snapshot=empty")
        return snapshot
    except Exception as e:
        logger.warning(f"[SessionStore] load_state_snapshot 失败: {e}")
        return None
