"""
统一 Planner 工具
提供简化的事件/待办/提醒操作接口

优化点：
1. 统一查询：search_items 替代 get_events/get_todos/get_reminders
2. 标识符解析：支持 #1, #2 (搜索结果索引)、UUID、标题匹配
3. 事件组映射：自动将组名转为 UUID
4. 增量编辑：只需传入要修改的参数
5. 重复规则：支持简化格式如 "每周一三五"
6. 会话缓存：搜索结果自动缓存，支持回滚同步
"""
import logging
from typing import Optional, Literal, List, Any
from datetime import datetime

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from core.services.event_service import EventService
from core.services.todo_service import TodoService
from core.services.reminder_service import ReminderService

from .time_parser import TimeRangeParser
from .param_adapter import UNSET_VALUE, ParamAdapter
from .identifier_resolver import IdentifierResolver
from .cache_manager import CacheManager
from .repeat_parser import RepeatParser
from .event_group_service import EventGroupService

from agent_service.utils import agent_transaction
from logger import logger


def _get_user_from_config(config: RunnableConfig):
    """从 RunnableConfig 中提取用户对象"""
    configurable = config.get("configurable", {})
    user = configurable.get("user")
    if not user:
        raise ValueError("未找到用户信息，请确保已登录")
    return user


def _get_session_id_from_config(config: RunnableConfig) -> Optional[str]:
    """从 RunnableConfig 中提取会话ID
    
    兼容两种键名：session_id 和 thread_id (thread_id 是 LangGraph 使用的标准键名)
    """
    configurable = config.get("configurable", {})
    # 优先使用 session_id，兼容 thread_id（LangGraph 标准）
    return configurable.get("session_id") or configurable.get("thread_id")


def _format_item_for_display(item: dict, index: int, item_type: str) -> str:
    """将单个项目格式化为显示字符串"""
    title = item.get('title', '未命名')
    item_id = item.get('id', 'N/A')
    
    if item_type == 'event':
        start = item.get('start', '')
        end = item.get('end', '')
        rrule = item.get('rrule', '')
        repeat_str = f" [重复: {RepeatParser.to_human_readable(rrule)}]" if rrule else ""
        return f"#{index} 【日程】{title}\n   时间: {start} ~ {end}{repeat_str}\n   ID: {item_id}"
    
    elif item_type == 'todo':
        status = item.get('status', 'pending')
        due_date = item.get('due_date', '')
        status_icon = "✓" if status == 'completed' else "○"
        due_str = f" | 截止: {due_date}" if due_date else ""
        return f"#{index} {status_icon}【待办】{title}{due_str}\n   ID: {item_id}"
    
    elif item_type == 'reminder':
        trigger_time = item.get('trigger_time', '')
        priority = item.get('priority', 'normal')
        rrule = item.get('rrule', '')
        repeat_str = f" [重复: {RepeatParser.to_human_readable(rrule)}]" if rrule else ""
        return f"#{index} 【提醒】{title}\n   触发: {trigger_time} | 优先级: {priority}{repeat_str}\n   ID: {item_id}"
    
    return f"#{index} {title}\n   ID: {item_id}"


def _format_items_list(items: List[dict], item_types: List[str]) -> str:
    """格式化项目列表"""
    if not items:
        return "未找到符合条件的项目"
    
    lines = []
    for i, (item, item_type) in enumerate(zip(items, item_types), 1):
        lines.append(_format_item_for_display(item, i, item_type))
    
    return "\n\n".join(lines)


@tool
def search_items(
    config: RunnableConfig,
    item_type: Literal["event", "todo", "reminder", "all"] = "all",
    keyword: Optional[str] = None,
    time_range: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20
) -> str:
    """
    统一搜索日程、待办、提醒
    
    Args:
        item_type: 类型过滤
            - "event": 只搜索日程
            - "to do": 只搜索待办
            - "reminder": 只搜索提醒
            - "all": 搜索所有类型
        keyword: 关键词搜索（标题/描述匹配）
        time_range: 时间范围，支持以下格式:
            - 预设: "today", "tomorrow", "this_week", "next_week", "this_month"
            - 中文: "今天", "明天", "本周", "下周", "本月"
            - 自定义: "2024-01-01 ~ 2024-01-31"
        status: 状态过滤
            - 待办: "pending", "completed", "all"
            - 提醒: "active", "snoozed", "dismissed", "all"
        limit: 返回数量上限，默认20
    
    Returns:
        格式化的搜索结果，每个结果有 #序号 可用于后续操作
    
    Examples:
        - search_items(item_type="event", time_range="this_week")
        - search_items(keyword="会议", item_type="all")
        - search_items(item_type="todo", status="pending")
    """
    user = _get_user_from_config(config)
    session_id = _get_session_id_from_config(config)
    
    results = []
    result_types = []
    
    # 解析时间范围
    start_time, end_time = None, None
    if time_range:
        parsed = TimeRangeParser.parse(time_range)
        if parsed:
            start_time, end_time = parsed
    
    # 搜索日程
    if item_type in ("event", "all"):
        events = EventService.get_events(user)
        for event in events:
            # 时间过滤
            if start_time and end_time:
                event_start = event.get('start', '')
                if event_start:
                    try:
                        event_dt = datetime.fromisoformat(event_start.replace('Z', '+00:00'))
                        event_dt = event_dt.replace(tzinfo=None)
                        if not (start_time <= event_dt <= end_time):
                            continue
                    except:
                        pass
            
            # 关键词过滤
            if keyword:
                title = event.get('title', '').lower()
                desc = event.get('description', '').lower()
                if keyword.lower() not in title and keyword.lower() not in desc:
                    continue
            
            results.append(event)
            result_types.append('event')
    
    # 搜索待办
    if item_type in ("todo", "all"):
        todos = TodoService.get_todos(user)
        for todo in todos:
            # 状态过滤
            if status and status != "all":
                if todo.get('status') != status:
                    continue
            
            # 时间过滤（使用 due_date）
            if start_time and end_time:
                due_date = todo.get('due_date', '')
                if due_date:
                    try:
                        due_dt = datetime.fromisoformat(due_date)
                        if not (start_time.date() <= due_dt.date() <= end_time.date()):
                            continue
                    except:
                        pass
            
            # 关键词过滤
            if keyword:
                title = todo.get('title', '').lower()
                desc = todo.get('description', '').lower()
                if keyword.lower() not in title and keyword.lower() not in desc:
                    continue
            
            results.append(todo)
            result_types.append('todo')
    
    # 搜索提醒
    if item_type in ("reminder", "all"):
        reminders = ReminderService.get_reminders(user)
        for reminder in reminders:
            # 状态过滤
            if status and status != "all":
                if reminder.get('status') != status:
                    continue
            
            # 时间过滤
            if start_time and end_time:
                trigger_time = reminder.get('trigger_time', '')
                if trigger_time:
                    try:
                        trigger_dt = datetime.fromisoformat(trigger_time.replace('Z', '+00:00'))
                        trigger_dt = trigger_dt.replace(tzinfo=None)
                        if not (start_time <= trigger_dt <= end_time):
                            continue
                    except:
                        pass
            
            # 关键词过滤
            if keyword:
                title = reminder.get('title', '').lower()
                content = reminder.get('content', '').lower()
                if keyword.lower() not in title and keyword.lower() not in content:
                    continue
            
            results.append(reminder)
            result_types.append('reminder')
    
    # 限制数量
    if len(results) > limit:
        results = results[:limit]
        result_types = result_types[:limit]
    
    # 保存到缓存
    if session_id and results:
        CacheManager.save_mixed_search_cache(session_id, results, result_types)
    
    # 格式化输出
    if not results:
        return "未找到符合条件的项目"
    
    output = _format_items_list(results, result_types)
    output += f"\n\n共找到 {len(results)} 个项目。使用 #序号 引用（如 update_item(identifier='#1', ...)）"
    
    return output


@tool
@agent_transaction(action_type="create_item")
def create_item(
    config: RunnableConfig,
    item_type: Literal["event", "todo", "reminder"],
    title: str,
    # 通用参数
    description: Optional[str] = None,
    # 日程参数
    start: Optional[str] = None,
    end: Optional[str] = None,
    event_group: Optional[str] = None,
    importance: Optional[str] = None,
    urgency: Optional[str] = None,
    shared_to_groups: Optional[List[str]] = None,
    ddl: Optional[str] = None,
    # 待办参数
    due_date: Optional[str] = None,
    priority: Optional[str] = None,
    # 提醒参数
    trigger_time: Optional[str] = None,
    content: Optional[str] = None,
    # 通用：重复规则
    repeat: Optional[str] = None
) -> str:
    """
    创建日程/待办/提醒
    
    Args:
        item_type: 类型
            - "event": 日程
            - "todo": 待办
            - "reminder": 提醒
        title: 标题（必填）
        
        # 通用参数
        description: 描述/备注
        repeat: 重复规则，支持简化格式:
            - "每天", "每周", "每月", "每年"
            - "每周一三五" → 自动转为 RRULE
            - "工作日", "周末"
            - 标准 RRULE 格式也支持
        
        # 日程专用
        start: 开始时间 (格式: "2024-01-15T09:00")
        end: 结束时间
        event_group: 事件组（支持名称或UUID，如 "工作" 会自动查找对应UUID）
        importance: 重要程度
        urgency: 紧急程度
        shared_to_groups: 分享到的群组列表
        ddl: 截止日期
        
        # 待办专用
        due_date: 截止日期 (格式: "2024-01-15")
        priority: 优先级 ("high", "medium", "low")
        
        # 提醒专用
        trigger_time: 触发时间 (格式: "2024-01-15T09:00")
        content: 提醒内容
        priority: 优先级 ("high", "normal", "low")
    
    Returns:
        创建成功的项目信息
    
    Examples:
        - create_item(item_type="event", title="周会", start="2024-01-15T14:00", end="2024-01-15T15:00", event_group="工作")
        - create_item(item_type="todo", title="写报告", due_date="2024-01-20", priority="high")
        - create_item(item_type="reminder", title="喝水", trigger_time="2024-01-15T10:00", repeat="每天")
    """
    user = _get_user_from_config(config)
    session_id = _get_session_id_from_config(config)
    
    # 解析重复规则
    rrule = ""
    if repeat:
        rrule = RepeatParser.parse(repeat)
    
    try:
        if item_type == "event":
            # 解析事件组
            group_id = ""
            if event_group:
                resolved = EventGroupService.resolve_group_name(user, event_group)
                if resolved:
                    group_id = resolved
                else:
                    return f"错误：未找到事件组 '{event_group}'。请先使用 get_event_groups 查看可用的事件组。"
            
            result = EventService.create_event(
                user=user,
                title=title,
                start=start or "",
                end=end or "",
                description=description or "",
                importance=importance or "",
                urgency=urgency or "",
                groupID=group_id,
                rrule=rrule,
                shared_to_groups=shared_to_groups,
                ddl=ddl or "",
                session_id=session_id
            )
            
            repeat_info = f"，重复规则: {RepeatParser.to_human_readable(rrule)}" if rrule else ""
            return f"✅ 日程创建成功！\n标题: {title}\n时间: {start} ~ {end}{repeat_info}\nID: {result.get('id')}"
        
        elif item_type == "todo":
            # To do 使用 importance/urgency 而不是 priority
            # 将 priority 映射到 importance
            importance_val = priority or "medium"
            
            result = TodoService.create_todo(
                user=user,
                title=title,
                description=description or "",
                due_date=due_date or "",
                importance=importance_val,
                session_id=session_id
            )
            
            due_info = f"\n截止: {due_date}" if due_date else ""
            return f"✅ 待办创建成功！\n标题: {title}{due_info}\n重要性: {importance_val}\nID: {result.get('id')}"
        
        elif item_type == "reminder":
            result = ReminderService.create_reminder(
                user=user,
                title=title,
                content=content or description or "",
                trigger_time=trigger_time or "",
                priority=priority or "normal",
                rrule=rrule,
                session_id=session_id
            )
            
            repeat_info = f"\n重复: {RepeatParser.to_human_readable(rrule)}" if rrule else ""
            return f"✅ 提醒创建成功！\n标题: {title}\n触发时间: {trigger_time}{repeat_info}\nID: {result.get('id')}"
        
        else:
            return f"错误：不支持的类型 '{item_type}'"
            
    except Exception as e:
        logger.error(f"创建项目失败: {e}", exc_info=True)
        return f"❌ 创建失败: {str(e)}"


@tool
@agent_transaction(action_type="update_item")
def update_item(
    config: RunnableConfig,
    identifier: str,
    # 可选：显式指定类型（如果不确定）
    item_type: Optional[Literal["event", "todo", "reminder"]] = None,
    # 通用参数
    title: Optional[str] = None,
    description: Optional[str] = None,
    # 日程参数
    start: Optional[str] = None,
    end: Optional[str] = None,
    event_group: Optional[str] = None,
    importance: Optional[str] = None,
    urgency: Optional[str] = None,
    shared_to_groups: Optional[List[str]] = None,
    ddl: Optional[str] = None,
    # 待办参数
    due_date: Optional[str] = None,
    priority: Optional[str] = None,
    status: Optional[str] = None,
    # 提醒参数
    trigger_time: Optional[str] = None,
    content: Optional[str] = None,
    # 重复规则
    repeat: Optional[str] = None,
    clear_repeat: bool = False
) -> str:
    """
    更新日程/待办/提醒（增量更新，只需传入要修改的字段）
    
    Args:
        identifier: 项目标识，支持多种格式:
            - "#1", "#2": 使用最近搜索结果的序号
            - UUID: 直接使用项目的UUID
            - "会议": 按标题模糊匹配
        item_type: 可选，显式指定类型（如果从缓存无法确定）
        
        # 通用参数（只传需要修改的）
        title: 新标题
        description: 新描述
        repeat: 新的重复规则（简化格式）
        clear_repeat: 如果为True，清除重复规则
        
        # 日程专用
        start: 新开始时间
        end: 新结束时间
        event_group: 新事件组
        importance: 新重要程度
        urgency: 新紧急程度
        shared_to_groups: 新分享群组列表
        ddl: 新截止日期
        
        # 待办专用
        due_date: 新截止日期
        priority: 新优先级
        status: 新状态 ("pending", "completed")
        
        # 提醒专用
        trigger_time: 新触发时间
        content: 新内容
        priority: 新优先级
    
    Returns:
        更新结果
    
    Examples:
        - update_item(identifier="#1", title="新标题")
        - update_item(identifier="#2", start="2024-01-16T10:00")
        - update_item(identifier="周会", event_group="重要")
    """
    user = _get_user_from_config(config)
    session_id = _get_session_id_from_config(config)
    
    # 解析标识符
    resolved = IdentifierResolver.resolve_with_type(
        identifier=identifier,
        session_id=session_id,
        user=user,
        preferred_type=item_type
    )
    
    if not resolved:
        return f"❌ 无法找到项目 '{identifier}'。请先使用 search_items 搜索，然后使用 #序号 引用。"
    
    item_uuid, resolved_type = resolved
    
    # 解析重复规则
    rrule = None
    if repeat:
        rrule = RepeatParser.parse(repeat)
    
    try:
        if resolved_type == "event":
            # 解析事件组
            group_id = None
            if event_group:
                resolved_group = EventGroupService.resolve_group_name(user, event_group)
                if resolved_group:
                    group_id = resolved_group
                else:
                    return f"错误：未找到事件组 '{event_group}'"
            
            result = EventService.update_event(
                user=user,
                event_id=item_uuid,
                title=title,
                start=start,
                end=end,
                description=description,
                importance=importance,
                urgency=urgency,
                groupID=group_id,
                rrule=rrule,
                shared_to_groups=shared_to_groups,
                ddl=ddl,
                session_id=session_id,
                _clear_rrule=clear_repeat
            )
            
            return f"✅ 日程更新成功！\n标题: {result.get('title')}\nID: {item_uuid}"
        
        elif resolved_type == "todo":
            # To do 使用 importance 而不是 priority
            result = TodoService.update_todo(
                user=user,
                todo_id=item_uuid,
                title=title,
                description=description,
                due_date=due_date,
                importance=priority,  # 映射 priority -> importance
                status=status,
                session_id=session_id
            )
            
            return f"✅ 待办更新成功！\n标题: {result.get('title')}\n状态: {result.get('status')}\nID: {item_uuid}"
        
        elif resolved_type == "reminder":
            result = ReminderService.update_reminder(
                user=user,
                reminder_id=item_uuid,
                title=title,
                content=content or description,
                trigger_time=trigger_time,
                priority=priority,
                status=status,
                rrule=rrule,
                session_id=session_id,
                _clear_rrule=clear_repeat
            )
            
            return f"✅ 提醒更新成功！\n标题: {result.get('title')}\nID: {item_uuid}"
        
        else:
            return f"错误：未知的项目类型 '{resolved_type}'"
            
    except Exception as e:
        logger.error(f"更新项目失败: {e}", exc_info=True)
        return f"❌ 更新失败: {str(e)}"


@tool
@agent_transaction(action_type="delete_item")
def delete_item(
    config: RunnableConfig,
    identifier: str,
    item_type: Optional[Literal["event", "todo", "reminder"]] = None,
    delete_scope: Literal["single", "all", "future"] = "single"
) -> str:
    """
    删除日程/待办/提醒
    
    Args:
        identifier: 项目标识，支持:
            - "#1", "#2": 使用最近搜索结果的序号
            - UUID: 直接使用项目的UUID
            - "会议": 按标题模糊匹配
        item_type: 可选，显式指定类型
        delete_scope: 删除范围（仅对重复日程有效）
            - "single": 仅删除这一个
            - "all": 删除整个系列
            - "future": 删除此次及之后的所有
    
    Returns:
        删除结果
    
    Examples:
        - delete_item(identifier="#1")
        - delete_item(identifier="#3", delete_scope="all")
    """
    user = _get_user_from_config(config)
    session_id = _get_session_id_from_config(config)
    
    # 解析标识符
    resolved = IdentifierResolver.resolve_with_type(
        identifier=identifier,
        session_id=session_id,
        user=user,
        preferred_type=item_type
    )
    
    if not resolved:
        return f"❌ 无法找到项目 '{identifier}'。请先使用 search_items 搜索，然后使用 #序号 引用。"
    
    item_uuid, resolved_type = resolved
    
    try:
        if resolved_type == "event":
            success = EventService.delete_event(
                user=user,
                event_id=item_uuid,
                delete_scope=delete_scope,
                session_id=session_id
            )
            if success:
                # 从缓存中移除
                CacheManager.invalidate_item(session_id, item_uuid)
                scope_text = {"single": "单个", "all": "整个系列", "future": "此次及之后"}.get(delete_scope, "")
                return f"✅ 日程删除成功！（{scope_text}）\nID: {item_uuid}"
            return f"❌ 日程删除失败"
        
        elif resolved_type == "todo":
            success = TodoService.delete_todo(
                user=user,
                todo_id=item_uuid,
                session_id=session_id
            )
            if success:
                CacheManager.invalidate_item(session_id, item_uuid)
                return f"✅ 待办删除成功！\nID: {item_uuid}"
            return f"❌ 待办删除失败"
        
        elif resolved_type == "reminder":
            success = ReminderService.delete_reminder(
                user=user,
                reminder_id=item_uuid,
                session_id=session_id
            )
            if success:
                CacheManager.invalidate_item(session_id, item_uuid)
                return f"✅ 提醒删除成功！\nID: {item_uuid}"
            return f"❌ 提醒删除失败"
        
        else:
            return f"错误：未知的项目类型 '{resolved_type}'"
            
    except Exception as e:
        logger.error(f"删除项目失败: {e}", exc_info=True)
        return f"❌ 删除失败: {str(e)}"


@tool
def get_event_groups(config: RunnableConfig) -> str:
    """
    获取用户的所有事件组列表
    
    用于在创建/更新日程时选择正确的事件组。
    
    Returns:
        事件组列表，包含名称和描述
    
    Examples:
        调用后返回:
        #1 工作 - 工作相关日程
        #2 个人 - 个人事务
        #3 学习 - 学习计划
    """
    user = _get_user_from_config(config)
    
    try:
        groups = EventGroupService.get_user_groups(user)
        
        if not groups:
            return "暂无事件组。系统会使用默认分组。"
        
        return EventGroupService.format_groups_for_display(groups)
        
    except Exception as e:
        logger.error(f"获取事件组失败: {e}", exc_info=True)
        return f"获取事件组失败: {str(e)}"


@tool
@agent_transaction(action_type="complete_todo")
def complete_todo(config: RunnableConfig, identifier: str) -> str:
    """
    快捷完成待办事项（标记为已完成）
    
    Args:
        identifier: 待办标识（#序号、UUID或标题）
    
    Returns:
        完成结果
    
    Examples:
        - complete_todo(identifier="#1")
        - complete_todo(identifier="写报告")
    """
    user = _get_user_from_config(config)
    session_id = _get_session_id_from_config(config)
    
    resolved = IdentifierResolver.resolve_with_type(
        identifier=identifier,
        session_id=session_id,
        user=user,
        preferred_type="todo"
    )
    
    if not resolved:
        return f"❌ 无法找到待办 '{identifier}'"
    
    item_uuid, resolved_type = resolved
    
    if resolved_type != "todo":
        return f"❌ '{identifier}' 不是待办事项（而是 {resolved_type}）"
    
    try:
        result = TodoService.update_todo(
            user=user,
            todo_id=item_uuid,
            status="completed",
            session_id=session_id
        )
        
        return f"✅ 待办已完成！\n标题: {result.get('title')}"
        
    except Exception as e:
        logger.error(f"完成待办失败: {e}", exc_info=True)
        return f"❌ 完成失败: {str(e)}"


# 导出的工具列表
UNIFIED_PLANNER_TOOLS = [
    search_items,
    create_item,
    update_item,
    delete_item,
    get_event_groups,
    complete_todo,
]
