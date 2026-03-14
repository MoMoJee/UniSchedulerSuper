"""
检查点管理器 (Checkpoint Manager)

功能：
1. 创建和管理检查点
2. 支持恢复到指定检查点
3. 增量回滚 N 步
4. 清理过期检查点

Author: Agent Service
Created: 2026-03-13
"""

import datetime
import json
import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from django.contrib.auth.models import User

from agent_service.models import AgentSession, AgentTransaction, SearchResultCache

from logger import logger

# ==========================================
# 数据类定义
# ==========================================

@dataclass
class CheckpointInfo:
    """检查点信息"""
    checkpoint_id: str
    session_id: str
    created_at: datetime.datetime
    message_count: int
    description: str = ""
    is_named: bool = False  # 是否是命名检查点


@dataclass
class RollbackResult:
    """回滚结果"""
    success: bool
    rolled_back_count: int = 0
    message: str = ""
    affected_items: List[Dict[str, Any]] = field(default_factory=list)


# ==========================================
# 检查点管理器
# ==========================================

class CheckpointManager:
    """
    检查点管理器

    用于管理 Agent 会话的状态快照，支持：
    - 手动创建检查点
    - 自动创建检查点（每次工具调用后）
    - 恢复到指定检查点
    - 增量回滚
    """

    # 检查点 ID 前缀
    CHECKPOINT_PREFIX = "ckpt_"

    # 最大检查点数量
    MAX_CHECKPOINTS = 50

    def __init__(self, session: AgentSession, user: User):
        """
        初始化检查点管理器

        Args:
            session: AgentSession 实例
            user: Django User 实例
        """
        self.session = session
        self.user = user

    def create_checkpoint(
        self,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        is_named: bool = False
    ) -> str:
        """
        创建检查点

        Args:
            description: 检查点描述
            metadata: 额外元数据
            is_named: 是否是命名检查点

        Returns:
            checkpoint_id
        """
        checkpoint_id = self._generate_checkpoint_id()

        try:
            # 保存状态快照（如果需要）
            # 这里可以扩展为保存完整的 AgentState

            # 记录检查点创建日志
            logger.info(
                f"[CheckpointManager] 创建检查点: session={self.session.session_id}, "
                f"checkpoint={checkpoint_id}, description={description[:50]}"
            )

            return checkpoint_id
        except Exception as e:
            logger.error(f"[CheckpointManager] 创建检查点失败: {e}")
            return ""

    def restore_checkpoint(self, checkpoint_id: str) -> bool:
        """
        恢复到指定检查点

        Args:
            checkpoint_id: 检查点 ID

        Returns:
            是否恢复成功
        """
        try:
            # 1. 获取检查点信息
            # 2. 恢复 AgentState
            # 3. 清理后续检查点
            # 4. 清理相关的 SearchResultCache

            logger.info(
                f"[CheckpointManager] 恢复检查点: session={self.session.session_id}, "
                f"checkpoint={checkpoint_id}"
            )

            # 清理后续检查点
            self._cleanup_checkpoints_after(checkpoint_id)

            return True
        except Exception as e:
            logger.error(f"[CheckpointManager] 恢复检查点失败: {e}")
            return False

    def list_checkpoints(
        self,
        include_unnamed: bool = True,
        limit: int = 20
    ) -> List[CheckpointInfo]:
        """
        列出会话的检查点

        Args:
            include_unnamed: 是否包含未命名检查点
            limit: 返回数量限制

        Returns:
            检查点列表
        """
        # TODO: 从 AgentStateSnapshot 加载检查点列表
        return []

    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """
        删除指定检查点

        Args:
            checkpoint_id: 检查点 ID

        Returns:
            是否删除成功
        """
        try:
            # 删除相关的状态快照
            from agent_service.models import AgentStateSnapshot

            AgentStateSnapshot.objects.filter(
                session=self.session,
                checkpoint_id=checkpoint_id
            ).delete()

            logger.info(
                f"[CheckpointManager] 删除检查点: session={self.session.session_id}, "
                f"checkpoint={checkpoint_id}"
            )
            return True
        except Exception as e:
            logger.error(f"[CheckpointManager] 删除检查点失败: {e}")
            return False

    def incremental_rollback(self, steps: int) -> RollbackResult:
        """
        增量回滚 N 步

        Args:
            steps: 回滚步数

        Returns:
            回滚结果
        """
        if steps <= 0:
            return RollbackResult(
                success=False,
                message="回滚步数必须大于 0"
            )

        try:
            # 1. 获取最近的 N 个 AgentTransaction
            transactions = AgentTransaction.objects.filter(
                session_id=self.session.session_id,
                is_rolled_back=False,
                reversible=True
            ).order_by('-created_at')[:steps]

            if not transactions.exists():
                return RollbackResult(
                    success=False,
                    message="没有可回滚的操作"
                )

            # 2. 逆序执行撤销操作
            affected_items = []
            for trans in reversed(transactions):
                # 执行撤销
                success = self._rollback_transaction(trans)
                if success:
                    trans.is_rolled_back = True
                    trans.save(update_fields=['is_rolled_back'])
                    affected_items.append({
                        'type': trans.action_type,
                        'tool_type': trans.tool_type,
                        'status': 'rolled_back'
                    })

            # 3. 清理相关的 SearchResultCache
            self._cleanup_search_cache()

            return RollbackResult(
                success=True,
                rolled_back_count=len(affected_items),
                message=f"成功回滚 {len(affected_items)} 步操作",
                affected_items=affected_items
            )
        except Exception as e:
            logger.error(f"[CheckpointManager] 增量回滚失败: {e}")
            return RollbackResult(
                success=False,
                message=f"回滚失败: {str(e)}"
            )

    def _rollback_transaction(self, transaction: AgentTransaction) -> bool:
        """
        回滚单个事务

        Args:
            transaction: AgentTransaction 实例

        Returns:
            是否成功
        """
        try:
            # 根据 action_type 执行对应的回滚逻辑
            action_type = transaction.action_type

            # 从 metadata 中获取回滚所需的信息
            rollback_info = transaction.rollback_metadata or {}

            # 通用回滚逻辑
            if action_type.startswith('create_'):
                # 创建操作 → 删除
                target_id = rollback_info.get('target_id')
                target_type = rollback_info.get('target_type', action_type.replace('create_', ''))

                if target_type == 'event':
                    return self._rollback_create_event(target_id)
                elif target_type == 'todo':
                    return self._rollback_create_todo(target_id)
                elif target_type == 'reminder':
                    return self._rollback_create_reminder(target_id)

            elif action_type.startswith('delete_'):
                # 删除操作 → 恢复（需要 django-reversion）
                revision_id = transaction.revision_id
                if revision_id:
                    return self._rollback_with_revision(revision_id)

            elif action_type.startswith('update_'):
                # 更新操作 → 恢复旧值
                return self._rollback_update(rollback_info)

            return True
        except Exception as e:
            logger.error(f"[CheckpointManager] 回滚事务失败: {e}")
            return False

    def _rollback_create_event(self, event_id: str) -> bool:
        """回滚创建事件"""
        try:
            from core.models import Event
            event = Event.objects.filter(id=event_id).first()
            if event:
                event.delete()
                logger.info(f"[CheckpointManager] 回滚创建事件: {event_id}")
                return True
        except Exception as e:
            logger.error(f"[CheckpointManager] 回滚创建事件失败: {e}")
        return False

    def _rollback_create_todo(self, todo_id: str) -> bool:
        """回滚创建待办"""
        try:
            from core.models import Todo
            todo = Todo.objects.filter(id=todo_id).first()
            if todo:
                todo.delete()
                logger.info(f"[CheckpointManager] 回滚创建待办: {todo_id}")
                return True
        except Exception as e:
            logger.error(f"[CheckpointManager] 回滚创建待办失败: {e}")
        return False

    def _rollback_create_reminder(self, reminder_id: str) -> bool:
        """回滚创建提醒"""
        try:
            from core.models import Reminder
            reminder = Reminder.objects.filter(id=reminder_id).first()
            if reminder:
                reminder.delete()
                logger.info(f"[CheckpointManager] 回滚创建提醒: {reminder_id}")
                return True
        except Exception as e:
            logger.error(f"[CheckpointManager] 回滚创建提醒失败: {e}")
        return False

    def _rollback_with_revision(self, revision_id: int) -> bool:
        """使用 django-reversion 回滚"""
        try:
            import reversion
            from reversion.models import Version

            version = Version.objects.get(revision_id=revision_id)
            version.revision.revert()
            logger.info(f"[CheckpointManager] 回滚到版本: {revision_id}")
            return True
        except Exception as e:
            logger.error(f"[CheckpointManager] django-reversion 回滚失败: {e}")
        return False

    def _rollback_update(self, rollback_info: Dict[str, Any]) -> bool:
        """回滚更新操作"""
        # TODO: 实现更新操作的回滚逻辑
        return True

    def _cleanup_checkpoints_after(self, checkpoint_id: str):
        """清理指定检查点之后的所有检查点"""
        try:
            from agent_service.models import AgentStateSnapshot

            # 获取目标检查点的创建时间
            target_snapshot = AgentStateSnapshot.objects.filter(
                session=self.session,
                checkpoint_id=checkpoint_id
            ).first()

            if target_snapshot:
                # 删除之后的检查点
                AgentStateSnapshot.objects.filter(
                    session=self.session,
                    created_at__gt=target_snapshot.created_at
                ).delete()

                logger.info(f"[CheckpointManager] 清理检查点: {checkpoint_id} 之后")
        except Exception as e:
            logger.warning(f"[CheckpointManager] 清理检查点失败: {e}")

    def _cleanup_search_cache(self):
        """清理搜索缓存"""
        try:
            SearchResultCache.objects.filter(session=self.session).delete()
            logger.info(f"[CheckpointManager] 清理搜索缓存: {self.session.session_id}")
        except Exception as e:
            logger.warning(f"[CheckpointManager] 清理搜索缓存失败: {e}")

    def _generate_checkpoint_id(self) -> str:
        """生成检查点 ID"""
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        return f"{self.CHECKPOINT_PREFIX}{timestamp}_{unique_id}"


# ==========================================
# 工具函数
# ==========================================

def record_tool_transaction(
    session: AgentSession,
    user: User,
    tool_name: str,
    tool_args: Dict[str, Any],
    result: Any,
    checkpoint_id: str = "",
    tool_type: str = 'native',
    tool_source: str = ""
) -> Optional[AgentTransaction]:
    """
    记录工具调用事务

    Args:
        session: AgentSession 实例
        user: Django User 实例
        tool_name: 工具名称
        tool_args: 工具参数
        result: 工具执行结果
        checkpoint_id: 检查点 ID
        tool_type: 工具类型
        tool_source: 工具来源

    Returns:
        AgentTransaction 实例
    """
    import hashlib
    import time

    start_time = time.time()

    logger.info(
        f"[CheckpointManager] 记录工具调用: "
        f"session={session.session_id}, "
        f"tool={tool_name}, "
        f"type={tool_type}, "
        f"source={tool_source}"
    )

    try:
        # 确定 action_type
        action_type = tool_name

        # 检查是否可回滚
        reversible = _is_reversible_action(tool_name, tool_args)
        logger.debug(f"[CheckpointManager] 可回滚: {reversible}")

        # 构建回滚元数据
        rollback_metadata = _build_rollback_metadata(tool_name, tool_args, result)

        # 创建事务记录
        transaction = AgentTransaction.objects.create(
            session_id=session.session_id,
            user=user,
            tool_type=tool_type,
            tool_source=tool_source or tool_name,
            action_type=action_type,
            description=f"调用工具 {tool_name}",
            checkpoint_id=checkpoint_id,
            reversible=reversible,
            rollback_metadata=rollback_metadata,
            metadata={
                'input': tool_args,
                'output': str(result)[:500] if result else '',
                'success': not isinstance(result, Exception)
            },
            status='success' if not isinstance(result, Exception) else 'error',
            duration_ms=int((time.time() - start_time) * 1000)
        )

        return transaction
    except Exception as e:
        logger.error(f"[CheckpointManager] 记录工具事务失败: {e}")
        return None


def _is_reversible_action(tool_name: str, tool_args: Dict[str, Any]) -> bool:
    """
    判断操作是否可回滚

    Args:
        tool_name: 工具名称
        tool_args: 工具参数

    Returns:
        是否可回滚
    """
    # 创建操作通常可回滚
    if tool_name.startswith('create_'):
        return True

    # 删除操作需要 django-reversion 支持
    if tool_name.startswith('delete_'):
        return True

    # 更新操作可回滚
    if tool_name.startswith('update_'):
        return True

    return False


def _build_rollback_metadata(
    tool_name: str,
    tool_args: Dict[str, Any],
    result: Any
) -> Dict[str, Any]:
    """
    构建回滚元数据

    Args:
        tool_name: 工具名称
        tool_args: 工具参数
        result: 工具执行结果

    Returns:
        回滚元数据
    """
    metadata = {}

    # 从结果中提取目标 ID
    if hasattr(result, 'get'):
        result_dict = result if isinstance(result, dict) else {}
        if 'id' in result_dict:
            metadata['target_id'] = result_dict['id']
        if 'uuid' in result_dict:
            metadata['target_id'] = result_dict['uuid']

    # 根据工具类型设置目标类型
    if tool_name.startswith('create_event'):
        metadata['target_type'] = 'event'
    elif tool_name.startswith('create_todo'):
        metadata['target_type'] = 'todo'
    elif tool_name.startswith('create_reminder'):
        metadata['target_type'] = 'reminder'

    # 保存原始参数（用于可能的恢复操作）
    metadata['original_args'] = tool_args

    return metadata
