from typing import Optional, List
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from core.services.event_service import EventService
from core.services.todo_service import TodoService
from core.services.reminder_service import ReminderService
from agent_service.utils import agent_transaction

# ==========================================
# Event Tools
# ==========================================

@tool
def get_events(config: RunnableConfig) -> str:
    """
    获取用户的所有日程列表。
    """
    user = config.get("configurable", {}).get("user")
    if not user: return "Error: User not found in context."
    
    try:
        events = EventService.get_events(user)
        if not events:
            return "当前没有日程。"
        
        # 格式化输出
        result = "您的日程如下:\n"
        for event in events:
            result += f"- [{event.get('start')} - {event.get('end')}] {event.get('title')} (ID: {event.get('id')})\n"
        return result
    except Exception as e:
        return f"获取日程失败: {str(e)}"

@tool
@agent_transaction(action_type="create_event")
def create_event(title: str, start: str, end: str, description: str = "", importance: str = "", urgency: str = "", rrule: str = "", config: RunnableConfig = None) -> str:
    """
    创建一个新的日程。
    Args:
        title: 日程标题
        start: 开始时间 (YYYY-MM-DDTHH:MM)
        end: 结束时间 (YYYY-MM-DDTHH:MM)
        description: 描述 (可选)
        importance: 重要性 (important/not-important) (可选)
        urgency: 紧急程度 (urgent/not-urgent) (可选)
        rrule: 重复规则 (例如: FREQ=DAILY;COUNT=5) (可选)
    """
    user = config.get("configurable", {}).get("user")
    if not user: return "Error: User not found in context."
    
    try:
        event = EventService.create_event(
            user, title, start, end, 
            description=description, 
            importance=importance, 
            urgency=urgency, 
            rrule=rrule
        )
        return f"日程 '{title}' 创建成功。"
    except Exception as e:
        return f"创建失败: {str(e)}"

@tool
@agent_transaction(action_type="update_event")
def update_event(event_id: str, title: str = None, start: str = None, end: str = None, description: str = None, config: RunnableConfig = None) -> str:
    """
    更新现有的日程。
    Args:
        event_id: 日程ID
        title: 新标题 (可选)
        start: 新开始时间 (可选)
        end: 新结束时间 (可选)
        description: 新描述 (可选)
    """
    user = config.get("configurable", {}).get("user")
    if not user: return "Error: User not found in context."
    
    try:
        EventService.update_event(
            user, event_id, 
            title=title, start=start, end=end, description=description
        )
        return f"日程已更新。"
    except Exception as e:
        return f"更新失败: {str(e)}"

@tool
@agent_transaction(action_type="delete_event")
def delete_event(event_id: str, delete_scope: str = "single", config: RunnableConfig = None) -> str:
    """
    删除日程。
    Args:
        event_id: 日程ID
        delete_scope: 删除范围 (single: 仅此一次, all: 所有重复, future: 此及将来)
    """
    user = config.get("configurable", {}).get("user")
    if not user: return "Error: User not found in context."
    
    try:
        EventService.delete_event(user, event_id, delete_scope=delete_scope)
        return f"日程已删除。"
    except Exception as e:
        return f"删除失败: {str(e)}"

# ==========================================
# Todo Tools
# ==========================================

@tool
def get_todos(config: RunnableConfig) -> str:
    """获取待办事项列表"""
    user = config.get("configurable", {}).get("user")
    if not user: return "Error: User not found."
    
    try:
        todos = TodoService.get_todos(user)
        if not todos: return "当前没有待办事项。"
        
        result = "您的待办事项:\n"
        for todo in todos:
            status = "[x]" if todo.get('status') == 'completed' else "[ ]"
            result += f"{status} {todo.get('title')} (Due: {todo.get('due_date')}) (ID: {todo.get('id')})\n"
        return result
    except Exception as e:
        return f"获取失败: {str(e)}"

@tool
@agent_transaction(action_type="create_todo")
def create_todo(title: str, description: str = "", due_date: str = "", config: RunnableConfig = None) -> str:
    """创建待办事项"""
    user = config.get("configurable", {}).get("user")
    if not user: return "Error: User not found."
    
    try:
        TodoService.create_todo(user, title, description=description, due_date=due_date)
        return f"待办事项 '{title}' 创建成功。"
    except Exception as e:
        return f"创建失败: {str(e)}"

@tool
@agent_transaction(action_type="update_todo")
def update_todo(todo_id: str, title: str = None, status: str = None, config: RunnableConfig = None) -> str:
    """更新待办事项 (标题或状态)"""
    user = config.get("configurable", {}).get("user")
    if not user: return "Error: User not found."
    
    try:
        TodoService.update_todo(user, todo_id, title=title, status=status)
        return f"待办事项已更新。"
    except Exception as e:
        return f"更新失败: {str(e)}"

@tool
@agent_transaction(action_type="delete_todo")
def delete_todo(todo_id: str, config: RunnableConfig = None) -> str:
    """删除待办事项"""
    user = config.get("configurable", {}).get("user")
    if not user: return "Error: User not found."
    
    try:
        TodoService.delete_todo(user, todo_id)
        return f"待办事项已删除。"
    except Exception as e:
        return f"删除失败: {str(e)}"

# ==========================================
# Reminder Tools
# ==========================================

@tool
def get_reminders(config: RunnableConfig) -> str:
    """获取提醒列表"""
    user = config.get("configurable", {}).get("user")
    if not user: return "Error: User not found."
    
    try:
        reminders = ReminderService.get_reminders(user)
        if not reminders: return "当前没有提醒。"
        
        result = "您的提醒:\n"
        for r in reminders:
            result += f"- {r.get('trigger_time')}: {r.get('title')} (ID: {r.get('id')})\n"
        return result
    except Exception as e:
        return f"获取失败: {str(e)}"

@tool
@agent_transaction(action_type="create_reminder")
def create_reminder(title: str, trigger_time: str, content: str = "", rrule: str = "", config: RunnableConfig = None) -> str:
    """创建提醒"""
    user = config.get("configurable", {}).get("user")
    if not user: return "Error: User not found."
    
    try:
        ReminderService.create_reminder(user, title, content=content, trigger_time=trigger_time, rrule=rrule)
        return f"提醒 '{title}' 创建成功。"
    except Exception as e:
        return f"创建失败: {str(e)}"

@tool
@agent_transaction(action_type="delete_reminder")
def delete_reminder(reminder_id: str, config: RunnableConfig = None) -> str:
    """删除提醒"""
    user = config.get("configurable", {}).get("user")
    if not user: return "Error: User not found."
    
    try:
        ReminderService.delete_reminder(user, reminder_id)
        return f"提醒已删除。"
    except Exception as e:
        return f"删除失败: {str(e)}"
