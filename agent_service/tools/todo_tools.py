"""
会话级 TODO List 工具
支持跨对话、回滚同步、状态对照
"""
import json
from typing import Optional
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from agent_service.models import AgentSession, SessionTodoItem, SessionTodoSnapshot
from agent_service.utils import agent_transaction

from logger import logger


def _get_session_from_config(config: RunnableConfig):
    """从 config 中获取当前会话"""
    configurable = config.get("configurable", {})
    user = configurable.get("user")
    thread_id = configurable.get("thread_id")
    
    if not user:
        return None, None, "Error: 用户未登录"
    
    if not thread_id:
        return None, None, "Error: 未找到会话 ID"
    
    try:
        session = AgentSession.objects.filter(session_id=thread_id).first()
        if not session:
            # 尝试创建会话
            session, _ = AgentSession.get_or_create_session(user, thread_id)
        return session, user, None
    except Exception as e:
        return None, None, f"Error: 获取会话失败 - {str(e)}"


def _format_todo_list(todos, highlight_id=None) -> str:
    """格式化 TODO 列表"""
    if not todos:
        return "（无任务）"
    
    status_icons = {'pending': '☐', 'in_progress': '⏳', 'done': '✅'}
    lines = []
    for i, todo in enumerate(todos, 1):
        icon = status_icons.get(todo.status, '?')
        line = f"{i}. {icon} {todo.title}"
        if todo.id == highlight_id:
            line += "  ← 刚更新"
        lines.append(line)
    return "\n".join(lines)


def _save_snapshot_if_needed(session, checkpoint_id: Optional[str] = None):
    """在修改 TODO 前保存快照（如果需要）"""
    if not checkpoint_id:
        # 生成一个简单的检查点 ID
        import uuid
        checkpoint_id = f"auto_{uuid.uuid4().hex[:8]}"
    
    # 检查是否已有该检查点的快照
    existing = SessionTodoSnapshot.objects.filter(
        session=session,
        checkpoint_id=checkpoint_id
    ).first()
    
    if not existing:
        SessionTodoSnapshot.create_snapshot(session, checkpoint_id)
        logger.debug(f"[TODO] 已创建快照: {checkpoint_id}")
    
    return checkpoint_id


@tool
@agent_transaction(action_type="create_todo")
def create_todo(title: str, description: str = "", config: RunnableConfig = None) -> str:
    """
    创建当前会话的 TODO 项。用于追踪多步骤任务的进度。
    
    Args:
        title: TODO 标题
        description: 可选，详细描述
    
    Examples:
        - create_todo("查询明天的日程")
        - create_todo("创建会议日程", "需要确认时间和地点")
    """
    session, user, error = _get_session_from_config(config)
    if error:
        return error
    
    try:
        # 获取当前检查点 ID（如果有）
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")
        _save_snapshot_if_needed(session, checkpoint_id)
        
        # 获取当前最大 order
        max_order = SessionTodoItem.objects.filter(session=session).count()
        
        todo = SessionTodoItem.objects.create(
            session=session,
            user=user,
            title=title,
            description=description,
            status='pending',
            order=max_order + 1
        )
        
        # 获取当前所有 TODO
        all_todos = SessionTodoItem.objects.filter(session=session)
        
        result = f"✅ 已创建 TODO: {title}\n\n"
        result += f"📋 当前任务列表:\n{_format_todo_list(all_todos, todo.id)}"
        
        return result
    except Exception as e:
        logger.exception(f"[TODO] 创建失败: {e}")
        return f"❌ 创建 TODO 失败: {str(e)}"


@tool
@agent_transaction(action_type="update_todo_status")
def update_todo_status(todo_id: int, new_status: str, config: RunnableConfig = None) -> str:
    """
    更新 TODO 状态。返回"之前→之后"对照，帮助追踪任务进度。
    
    Args:
        todo_id: TODO 的 ID
        new_status: 新状态，可选值: "pending"(待处理), "in_progress"(进行中), "done"(已完成)
    
    返回格式:
        ✅ TODO #1 状态已更新
        【之前】pending: 查询日程
        【之后】in_progress: 查询日程
        
        📋 当前任务列表:
        1. ⏳ 查询日程  ← 刚更新
        2. ☐ 创建新日程
    """
    session, user, error = _get_session_from_config(config)
    if error:
        return error
    
    # 验证状态值
    valid_statuses = ['pending', 'in_progress', 'done']
    if new_status not in valid_statuses:
        return f"❌ 无效的状态值: {new_status}。可选值: {', '.join(valid_statuses)}"
    
    try:
        todo = SessionTodoItem.objects.filter(id=todo_id, session=session).first()
        if not todo:
            return f"❌ 未找到 ID 为 {todo_id} 的 TODO"
        
        # 保存快照
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")
        _save_snapshot_if_needed(session, checkpoint_id)
        
        old_status = todo.status
        old_icon = {'pending': '☐', 'in_progress': '⏳', 'done': '✅'}.get(old_status, '?')
        new_icon = {'pending': '☐', 'in_progress': '⏳', 'done': '✅'}.get(new_status, '?')
        
        todo.status = new_status
        todo.save()
        
        # 获取当前所有 TODO
        all_todos = SessionTodoItem.objects.filter(session=session)
        
        result = f"✅ TODO #{todo_id} 状态已更新\n"
        result += f"【之前】{old_icon} {old_status}: {todo.title}\n"
        result += f"【之后】{new_icon} {new_status}: {todo.title}\n\n"
        result += f"📋 当前任务列表:\n{_format_todo_list(all_todos, todo.id)}"
        
        return result
    except Exception as e:
        logger.exception(f"[TODO] 更新状态失败: {e}")
        return f"❌ 更新 TODO 状态失败: {str(e)}"


@tool
def get_session_todos(config: RunnableConfig = None) -> str:
    """
    获取当前会话的所有 TODO。查看任务列表和进度。
    """
    session, user, error = _get_session_from_config(config)
    if error:
        return error
    
    try:
        todos = SessionTodoItem.objects.filter(session=session)
        
        if not todos.exists():
            return "📋 当前会话暂无任务"
        
        # 统计
        pending_count = todos.filter(status='pending').count()
        in_progress_count = todos.filter(status='in_progress').count()
        done_count = todos.filter(status='done').count()
        
        result = f"📋 当前任务列表 (待处理: {pending_count}, 进行中: {in_progress_count}, 已完成: {done_count}):\n"
        result += _format_todo_list(todos)
        
        return result
    except Exception as e:
        logger.exception(f"[TODO] 获取列表失败: {e}")
        return f"❌ 获取 TODO 列表失败: {str(e)}"


@tool
@agent_transaction(action_type="clear_completed_todos")
def clear_completed_todos(config: RunnableConfig = None) -> str:
    """
    清除已完成的 TODO。保留未完成的任务。
    """
    session, user, error = _get_session_from_config(config)
    if error:
        return error
    
    try:
        # 保存快照
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")
        _save_snapshot_if_needed(session, checkpoint_id)
        
        completed = SessionTodoItem.objects.filter(session=session, status='done')
        count = completed.count()
        
        if count == 0:
            return "没有已完成的 TODO 需要清除"
        
        # 记录被清除的任务
        cleared_titles = [todo.title for todo in completed]
        completed.delete()
        
        # 获取剩余 TODO
        remaining = SessionTodoItem.objects.filter(session=session)
        
        result = f"✅ 已清除 {count} 个已完成的 TODO:\n"
        result += "\n".join([f"  - {title}" for title in cleared_titles])
        
        if remaining.exists():
            result += f"\n\n📋 剩余任务:\n{_format_todo_list(remaining)}"
        else:
            result += "\n\n📋 任务列表已清空"
        
        return result
    except Exception as e:
        logger.exception(f"[TODO] 清除失败: {e}")
        return f"❌ 清除已完成 TODO 失败: {str(e)}"


# ==========================================
# TODO 回滚辅助函数
# ==========================================

def rollback_todos(session_id: str, target_checkpoint: str) -> bool:
    """
    回滚 TODO 列表到指定检查点
    
    Args:
        session_id: 会话 ID
        target_checkpoint: 目标检查点 ID
        
    Returns:
        是否成功回滚
    """
    try:
        session = AgentSession.objects.filter(session_id=session_id).first()
        if not session:
            logger.warning(f"[TODO Rollback] 未找到会话: {session_id}")
            return False
        
        # 找到该检查点的快照
        snapshot = SessionTodoSnapshot.objects.filter(
            session=session,
            checkpoint_id=target_checkpoint
        ).first()
        
        if not snapshot:
            # 如果没有快照，说明该检查点时没有 TODO，清空列表
            logger.info(f"[TODO Rollback] 未找到检查点 {target_checkpoint} 的快照，清空 TODO 列表")
            SessionTodoItem.objects.filter(session=session).delete()
            return True
        
        # 恢复快照数据
        snapshot_todos = snapshot.get_todos_data()
        
        # 清空当前 TODO，重建快照状态
        SessionTodoItem.objects.filter(session=session).delete()
        
        for todo_data in snapshot_todos:
            # 移除 id 字段，让数据库生成新 id
            todo_data.pop('id', None)
            SessionTodoItem.objects.create(
                session=session,
                user=snapshot.user,
                **todo_data
            )
        
        # 删除该检查点之后的快照
        SessionTodoSnapshot.objects.filter(
            session=session,
            created_at__gt=snapshot.created_at
        ).delete()
        
        logger.info(f"[TODO Rollback] 已回滚到检查点 {target_checkpoint}，恢复 {len(snapshot_todos)} 个 TODO")
        return True
        
    except Exception as e:
        logger.exception(f"[TODO Rollback] 回滚失败: {e}")
        return False


def get_todos_for_frontend(session_id: str) -> list:
    """
    获取 TODO 列表供前端显示
    
    Args:
        session_id: 会话 ID
        
    Returns:
        TODO 列表（字典格式）
    """
    try:
        session = AgentSession.objects.filter(session_id=session_id).first()
        if not session:
            return []
        
        todos = SessionTodoItem.objects.filter(session=session)
        return [{
            'id': todo.id,
            'title': todo.title,
            'description': todo.description,
            'status': todo.status,
            'status_icon': todo.get_status_display_icon(),
            'order': todo.order,
            'created_at': todo.created_at.isoformat(),
            'updated_at': todo.updated_at.isoformat()
        } for todo in todos]
        
    except Exception as e:
        logger.exception(f"[TODO] 获取前端数据失败: {e}")
        return []


# ==========================================
# 导出工具列表
# ==========================================

TODO_TOOLS = [
    create_todo,
    update_todo_status,
    get_session_todos,
    clear_completed_todos,
]
