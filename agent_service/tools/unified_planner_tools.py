"""
统一 Planner 工具
提供简化的事件/待办/提醒操作接口

优化点：
1. 统一查询：search_items 替代 get_events/get_todos/get_reminders
2. 标识符解析：支持 #1, #2 (搜索结果索引)、#g1 (事件组)、#s1 (分享组)、UUID、标题匹配
3. 事件组映射：自动将组名转为 UUID
4. 增量编辑：只需传入要修改的参数
5. 重复规则：支持简化格式如 "每周一三五"
6. 会话缓存：搜索结果自动缓存，支持智能去重和回滚同步
"""
import logging
from typing import Optional, Literal, List, Any, Dict
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
from .share_group_service import ShareGroupService
from .conflict_analyzer import (
    detect_hard_conflicts,
    analyze_daily_density,
    get_user_personal_info,
    analyze_with_llm,
    format_hard_conflicts_report,
    format_density_report
)

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


def _format_item_for_display(
    item: dict, 
    index: int, 
    item_type: str, 
    is_shared: bool = False, 
    editable: bool = True,
    custom_index: Optional[str] = None,
    is_own_shared: bool = False
) -> str:
    """将单个项目格式化为显示字符串
    
    Args:
        item: 项目数据
        index: 序号（当 custom_index 为 None 时使用）
        item_type: 类型 (event/todo/reminder/shared_event)
        is_shared: 是否为分享组日程（他人的）
        editable: 是否可编辑
        custom_index: 自定义编号（如 "#5"），用于智能去重后的显示
        is_own_shared: 是否为用户自己创建的、被分享的日程
    """
    title = item.get('title', '未命名')
    item_id = item.get('id', 'N/A')
    
    # 确定显示的编号
    display_index = custom_index if custom_index else f"#{index}"
    
    # 构建标签
    if item_type == 'shared_event' or is_shared:
        # 他人的分享日程（只读）
        share_group_name = item.get('_share_group_name', '分享组')
        owner_name = item.get('_owner_username', '未知')
        tag = f"【分享日程·{share_group_name}·{owner_name}】"
        edit_hint = " [只读-他人日程]" if not editable else ""
    elif is_own_shared:
        # 用户自己的被分享日程（可编辑）
        share_group_name = item.get('_share_group_name', '')
        if share_group_name:
            tag = f"【日程·已分享到{share_group_name}】"
        else:
            tag = "【日程】"
        edit_hint = ""
    elif item_type == 'event':
        tag = "【日程】"
        edit_hint = ""
    else:
        tag = ""
        edit_hint = ""
    
    if item_type in ('event', 'shared_event') or is_shared:
        start = item.get('start', '')
        end = item.get('end', '')
        rrule = item.get('rrule', '')
        repeat_str = f" [重复: {RepeatParser.to_human_readable(rrule)}]" if rrule else ""
        return f"{display_index} {tag}{title}{edit_hint}\n   时间: {start} ~ {end}{repeat_str}\n   ID: {item_id}"
    
    elif item_type == 'todo':
        status = item.get('status', 'pending')
        due_date = item.get('due_date', '')
        status_icon = "✓" if status == 'completed' else "○"
        due_str = f" | 截止: {due_date}" if due_date else ""
        return f"{display_index} {status_icon}【待办】{title}{due_str}\n   ID: {item_id}"
    
    elif item_type == 'reminder':
        trigger_time = item.get('trigger_time', '')
        priority = item.get('priority', 'normal')
        rrule = item.get('rrule', '')
        repeat_str = f" [重复: {RepeatParser.to_human_readable(rrule)}]" if rrule else ""
        return f"{display_index} 【提醒】{title}\n   触发: {trigger_time} | 优先级: {priority}{repeat_str}\n   ID: {item_id}"
    
    return f"{display_index} {title}\n   ID: {item_id}"


def _format_items_list(
    items: List[dict], 
    item_types: List[str], 
    editables: Optional[List[bool]] = None,
    item_to_index: Optional[Dict[str, str]] = None,
    own_shared_flags: Optional[List[bool]] = None
) -> str:
    """格式化项目列表
    
    Args:
        items: 项目列表
        item_types: 类型列表
        editables: 可编辑标记列表
        item_to_index: UUID到编号的映射（来自智能去重缓存）
        own_shared_flags: 标记哪些是用户自己的被分享日程
    """
    if not items:
        return "未找到符合条件的项目"
    
    if editables is None:
        editables = [True] * len(items)
    
    if own_shared_flags is None:
        own_shared_flags = [False] * len(items)
    
    lines = []
    for i, (item, item_type, editable, is_own_shared) in enumerate(
        zip(items, item_types, editables, own_shared_flags), 1
    ):
        is_shared = item_type == 'shared_event'
        # 使用缓存中的编号（如果有的话）
        custom_index = None
        if item_to_index:
            item_uuid = item.get('id', '')
            if item_uuid and item_uuid in item_to_index:
                custom_index = item_to_index[item_uuid]
        lines.append(_format_item_for_display(
            item, i, item_type, 
            is_shared=is_shared, 
            editable=editable,
            custom_index=custom_index,
            is_own_shared=is_own_shared
        ))
    
    return "\n\n".join(lines)


@tool
def search_items(
    config: RunnableConfig,
    item_type: Literal["event", "todo", "reminder", "all"] = "all",
    keyword: Optional[str] = None,
    time_range: Optional[str] = None,
    status: Optional[str] = None,
    event_group: Optional[str] = None,
    share_groups: Optional[List[str]] = None,
    share_groups_only: bool = False,
    limit: int = 20
) -> str:
    """
    统一搜索日程、待办、提醒
    
    Args:
        item_type: 类型过滤
            - "event": 只搜索日程
            - "todo": 只搜索待办
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
        event_group: 日程组过滤（支持名称或UUID，仅对用户自己的日程生效）
        share_groups: 分享组列表（支持分享组名称或ID）
            - None（默认）: 返回用户自己的日程 + 所有分享组中他人的日程
            - ["工作组"]: 指定分享组
            - []（空列表）: 仅返回用户自己的日程，不包含分享组内容
        share_groups_only: 是否仅搜索分享组内容
            - False（默认）: 搜索用户自己的日程，并额外返回分享组中其他人的日程
            - True: 仅搜索分享组的日程（包括自己分享的），需配合share_groups参数使用
        limit: 返回数量上限，默认20，如果结果超出限制可增大此值
    
    Returns:
        格式化的搜索结果，每个结果有 #序号 可用于后续操作
        注意：分享组中他人的日程为只读，无法编辑
    
    Examples:
        - search_items(item_type="event", time_range="this_week")  # 搜索本周日程
        - search_items(keyword="会议", item_type="all")  # 关键词搜索
        - search_items(item_type="event", share_groups=[])  # 仅用户自己的日程
        - search_items(item_type="event", share_groups=["工作组"], share_groups_only=True)  # 仅搜索指定分享组
    """
    user = _get_user_from_config(config)
    session_id = _get_session_id_from_config(config)
    
    results = []
    result_types = []
    result_editables = []  # 记录每个结果是否可编辑
    
    # 解析时间范围
    start_time, end_time = None, None
    if time_range:
        parsed = TimeRangeParser.parse(time_range)
        if parsed:
            start_time, end_time = parsed
    
    # 解析事件组（支持 #g1 格式、UUID、名称）
    event_group_id = None
    if event_group:
        event_group_id = IdentifierResolver.resolve_event_group(event_group, user)
    
    # 解析分享组（支持 #s1 格式、名称或ID）
    # share_group_ids: None 表示获取所有分享组，[] 表示不获取任何分享组
    share_group_ids = None
    skip_share_groups = False
    if share_groups is not None:
        if len(share_groups) == 0:
            # 空列表表示不要分享组内容
            skip_share_groups = True
        else:
            share_group_ids = [
                IdentifierResolver.resolve_share_group(g, user) or g
                for g in share_groups
            ]
            share_group_ids = [g for g in share_group_ids if g]
            if not share_group_ids:
                # 指定了分享组但解析失败
                skip_share_groups = True
    
    # 收集用户自己的事件ID（用于去重）
    user_event_ids = set()
    
    # ===== 搜索用户自己的日程（非 share_groups_only 模式）=====
    if not share_groups_only:
        # 搜索日程
        if item_type in ("event", "all"):
            events = EventService.get_events(user)
            for event in events:
                # 事件组过滤（仅对用户自己的日程生效）
                if event_group_id:
                    if event.get('groupID') != event_group_id:
                        continue
                
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
                
                user_event_ids.add(event.get('id'))
                results.append(event)
                result_types.append('event')
                result_editables.append(True)
        
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
                result_editables.append(True)
        
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
                result_editables.append(True)
    
    # ===== 搜索分享组日程 =====
    shared_events = []
    total_shared_before_filter = 0  # 记录过滤前的分享组日程总数
    
    # 只有在不跳过分享组时才搜索
    if not skip_share_groups and (item_type in ("event", "all") or share_groups_only):
        # 获取分享组日程
        # exclude_own: 非 share_groups_only 模式下排除自己的日程避免重复
        all_shared_events = ShareGroupService.get_all_share_groups_events(
            user,
            share_group_ids=share_group_ids,
            exclude_own=not share_groups_only
        )
        
        for event in all_shared_events:
            event_id = event.get('id')
            
            # 去重检查（避免与用户自己的日程重复）
            if event_id in user_event_ids:
                continue
            
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
            
            # 注意：不对分享组日程进行 event_group 过滤，因为用户无法获取他人的 groupID
            
            shared_events.append(event)
    
    # 记录完整搜索结果数量（在截断之前）
    total_own_count = len(results)
    total_shared_count = len(shared_events)
    
    # 分离分享组中：用户自己的日程（可编辑）vs 他人的日程（不可编辑）
    own_shared_events = []  # 用户自己的被分享日程
    others_shared_events = []  # 他人的日程
    
    for event in shared_events:
        if event.get('is_own', False):
            own_shared_events.append(event)
        else:
            others_shared_events.append(event)
    
    # 处理 limit 限制
    displayed_own_count = total_own_count
    displayed_own_shared_count = len(own_shared_events)
    displayed_others_shared_count = len(others_shared_events)
    is_truncated = False
    
    # 计算可编辑项目总数（用户自己的日程 + 自己的被分享日程）
    total_editable = total_own_count + len(own_shared_events)
    
    # 优先显示可编辑的日程
    if total_editable > limit:
        # 先截断用户自己的日程
        if total_own_count > limit:
            results = results[:limit]
            result_types = result_types[:limit]
            result_editables = result_editables[:limit]
            displayed_own_count = limit
            own_shared_events = []
            displayed_own_shared_count = 0
        else:
            # 用户日程未超限，截断自己的被分享日程
            remaining = limit - displayed_own_count
            own_shared_events = own_shared_events[:remaining]
            displayed_own_shared_count = len(own_shared_events)
        is_truncated = True
        # 不显示他人的日程
        others_shared_events = []
        displayed_others_shared_count = 0
    else:
        # 可编辑项目未超限，计算他人日程可用配额
        others_limit = limit - total_editable
        if len(others_shared_events) > others_limit:
            others_shared_events = others_shared_events[:others_limit]
            displayed_others_shared_count = len(others_shared_events)
            is_truncated = True
    
    # 合并用户自己的被分享日程到可编辑结果中
    # 同时记录哪些是被分享日程（用于显示标记）
    own_shared_flags = [False] * len(results)  # 原有结果不是被分享的
    
    for event in own_shared_events:
        results.append(event)
        result_types.append('event')  # 用户自己的日程，类型为 event
        result_editables.append(True)  # 可编辑
        own_shared_flags.append(True)  # 标记为被分享的日程
    
    # 保存到缓存（所有可编辑的结果）- 使用智能去重
    item_to_index: Dict[str, str] = {}
    if session_id and results:
        success, stats = CacheManager.save_mixed_search_cache(session_id, results, result_types, user=user)
        if success:
            item_to_index = stats.get('item_to_index', {})
    
    # 格式化输出
    output_parts = []
    
    if results:
        output_parts.append(_format_items_list(
            results, result_types, result_editables, item_to_index, own_shared_flags
        ))
    
    # 添加他人的分享组日程（只读，不分配#代号）
    if others_shared_events:
        if output_parts:
            output_parts.append("\n\n" + "=" * 40)
        output_parts.append("📤 以下是分享组中他人的日程（只读，无法编辑，无#代号）：")
        
        # 格式化他人的日程，不使用#代号，使用 "-" 代替
        others_lines = []
        for event in others_shared_events:
            others_lines.append(_format_item_for_display(
                event, 0, 'shared_event', 
                is_shared=True, 
                editable=False,
                custom_index="-"  # 不分配#代号
            ))
        output_parts.append("\n\n".join(others_lines))
    
    # 计算显示和实际总数
    displayed_editable_count = len(results)  # 可编辑的项目数（含自己的被分享日程）
    displayed_others_count = displayed_others_shared_count
    displayed_total = displayed_editable_count + displayed_others_count
    actual_total = total_own_count + total_shared_count
    
    if displayed_total == 0:
        return "未找到符合条件的项目"
    
    output = "\n".join(output_parts)
    
    # 根据 item_type 确定类型名称
    type_name_map = {
        "event": "日程",
        "todo": "待办",
        "reminder": "提醒",
        "all": "项目"
    }
    item_type_name = type_name_map.get(item_type, "项目")
    
    # 构建统计信息
    if displayed_others_count > 0 or displayed_own_shared_count > 0:
        # 有分享组日程
        stats_parts = []
        if total_own_count > 0:
            stats_parts.append(f"{total_own_count} 个用户{item_type_name}")
        if displayed_own_shared_count > 0:
            stats_parts.append(f"{displayed_own_shared_count} 个自己的共享日程")
        if displayed_others_count > 0:
            stats_parts.append(f"{displayed_others_count} 个他人共享日程")
        
        if is_truncated:
            output += f"\n\n共找到 {', '.join(stats_parts)}，显示前 {displayed_total} 个"
            output += f"\n💡 提示：增大 limit 参数（当前为 {limit}）以获取完整结果"
        else:
            output += f"\n\n共找到 {', '.join(stats_parts)}"
        
        if displayed_editable_count > 0:
            output += f"\n✏️ 可编辑项目使用 #序号 引用（如 update_item(identifier='#1', ...)）"
        if displayed_others_count > 0:
            output += "\n⚠️ 他人的共享日程无#代号，无法编辑或删除"
    else:
        # 只有用户自己的结果
        if is_truncated:
            output += f"\n\n共找到 {total_own_count} 个用户{item_type_name}，显示前 {displayed_editable_count} 个"
            output += "。使用 #序号 引用（如 update_item(identifier='#1', ...)）"
            output += f"\n💡 提示：增大 limit 参数（当前为 {limit}）以获取完整结果"
        else:
            output += f"\n\n共找到 {total_own_count} 个用户{item_type_name}"
            output += "。使用 #序号 引用（如 update_item(identifier='#1', ...)）"
    
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
        shared_to_groups: 分享到的群组列表（支持群组名称或ID，如 ["工作协作组", "家庭日程"]）
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
            # 解析事件组（支持 #g1 格式、UUID、名称）
            group_id = ""
            if event_group:
                resolved = IdentifierResolver.resolve_event_group(event_group, user)
                if resolved:
                    group_id = resolved
                else:
                    return f"错误：未找到事件组 '{event_group}'。请先使用 get_event_groups 查看可用的事件组。"
            
            # 解析分享组（支持 #s1 格式、名称或ID）
            resolved_share_groups = None
            if shared_to_groups:
                resolved_share_groups = [
                    IdentifierResolver.resolve_share_group(g, user) or g
                    for g in shared_to_groups
                ]
                # 过滤掉未解析成功的
                resolved_share_groups = [g for g in resolved_share_groups if g]
                if not resolved_share_groups and shared_to_groups:
                    # 尝试列出可用的分享组
                    available = ShareGroupService.get_user_share_groups(user)
                    available_names = [g.get('share_group_name', '') for g in available]
                    return f"错误：未找到指定的分享组 {shared_to_groups}。可用的分享组有: {', '.join(available_names) if available_names else '无'}"
            
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
                shared_to_groups=resolved_share_groups,
                ddl=ddl or "",
                session_id=session_id
            )
            
            repeat_info = f"，重复规则: {RepeatParser.to_human_readable(rrule)}" if rrule else ""
            share_info = f"，已分享到: {', '.join(shared_to_groups)}" if shared_to_groups and resolved_share_groups else ""
            return f"✅ 日程创建成功！\n标题: {title}\n时间: {start} ~ {end}{repeat_info}{share_info}\nID: {result.get('id')}"
        
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
    # 编辑范围（对重复项目生效）
    edit_scope: Literal["single", "all", "future", "from_time"] = "single",
    from_time: Optional[str] = None,
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
    
    对于重复项目，可以指定编辑范围来控制修改影响哪些实例。
    
    Args:
        identifier: 项目标识，支持多种格式:
            - "#1", "#2": 使用最近搜索结果的序号
            - UUID: 直接使用项目的UUID
            - "会议": 按标题模糊匹配
        item_type: 可选，显式指定类型（如果从缓存无法确定）
        
        edit_scope: 编辑范围（对重复日程/提醒生效）
            - "single": 仅当前实例（从系列独立出来，不影响其他实例）
            - "all": 整个系列（修改所有实例，不改变各实例时间）
            - "future": 此实例及之后（修改选中的及后续所有实例）
            - "from_time": 从指定时间开始（需配合 from_time 参数）
        from_time: 当 edit_scope="from_time" 时必填，格式如 "2025-01-15T10:00"
        
        # 通用参数（只传需要修改的）
        title: 新标题
        description: 新描述
        repeat: 新的重复规则（简化格式，如 "每天;COUNT=10"）
        clear_repeat: 如果为True，清除重复规则，将重复项目变为单次
        
        # 日程专用
        start: 新开始时间
        end: 新结束时间
        event_group: 新事件组（名称或UUID）
        importance: 重要程度 ("important", "not-important", "")
        urgency: 紧急程度 ("urgent", "not-urgent", "")
        shared_to_groups: 分享群组列表（支持群组名称或ID，传空列表[]可清除分享）
        ddl: 截止日期
        
        # 待办专用
        due_date: 截止日期
        priority: 优先级 ("high", "medium", "low")
        status: 状态 ("pending", "completed")
        
        # 提醒专用
        trigger_time: 触发时间
        content: 提醒内容
        priority: 优先级 ("high", "normal", "low")
    
    Returns:
        更新结果
    
    Examples:
        # 简单修改（单个实例）
        - update_item(identifier="#1", title="新标题")
        
        # 修改整个重复系列
        - update_item(identifier="#1", edit_scope="all", title="系列新标题")
        
        # 修改此实例及之后，并更改重复规则
        - update_item(identifier="#1", edit_scope="future", repeat="每周一三五;COUNT=10")
    """
    user = _get_user_from_config(config)
    session_id = _get_session_id_from_config(config)
    
    # 验证 from_time 参数
    if edit_scope == "from_time" and not from_time:
        return "❌ 当 edit_scope='from_time' 时，必须提供 from_time 参数"
    
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
    elif clear_repeat:
        rrule = ""  # 显式清除
    
    try:
        if resolved_type == "event":
            # 解析事件组（支持 #g1 格式、UUID、名称）
            group_id = None
            if event_group:
                resolved_group = IdentifierResolver.resolve_event_group(event_group, user)
                if resolved_group:
                    group_id = resolved_group
                else:
                    return f"错误：未找到事件组 '{event_group}'"
            
            # 解析分享组（支持 #s1 格式、名称或ID）
            resolved_share_groups = None
            if shared_to_groups is not None:
                if shared_to_groups:  # 非空列表
                    resolved_share_groups = [
                        IdentifierResolver.resolve_share_group(g, user) or g
                        for g in shared_to_groups
                    ]
                    resolved_share_groups = [g for g in resolved_share_groups if g]
                    if not resolved_share_groups:
                        available = ShareGroupService.get_user_share_groups(user)
                        available_names = [g.get('share_group_name', '') for g in available]
                        return f"错误：未找到指定的分享组 {shared_to_groups}。可用的分享组有: {', '.join(available_names) if available_names else '无'}"
                else:  # 空列表，表示清除分享
                    resolved_share_groups = []
            
            # 检查是否是重复日程，决定使用哪个方法
            event = EventService.get_event_by_id(user, item_uuid)
            is_recurring = event and (event.get('is_recurring') or event.get('series_id'))
            
            if is_recurring and edit_scope != "single":
                # 使用批量编辑
                result = EventService.bulk_edit(
                    user=user,
                    event_id=item_uuid,
                    operation='edit',
                    edit_scope=edit_scope,
                    from_time=from_time,
                    title=title,
                    start=start,
                    end=end,
                    description=description,
                    importance=importance,
                    urgency=urgency,
                    groupID=group_id,
                    rrule=rrule,
                    ddl=ddl,
                    shared_to_groups=resolved_share_groups,
                    session_id=session_id
                )
                scope_desc = {"all": "整个系列", "future": "此实例及之后", "from_time": f"从 {from_time} 开始"}.get(edit_scope, edit_scope)
                return f"✅ 日程批量更新成功！\n范围: {scope_desc}\n更新数量: {result.get('updated_count', 'N/A')}"
            else:
                # 单个实例编辑（或非重复日程）
                if is_recurring and edit_scope == "single":
                    # 从系列独立出来
                    result = EventService.bulk_edit(
                        user=user,
                        event_id=item_uuid,
                        operation='edit',
                        edit_scope='single',
                        title=title,
                        start=start,
                        end=end,
                        description=description,
                        importance=importance,
                        urgency=urgency,
                        groupID=group_id,
                        rrule=rrule,
                        ddl=ddl,
                        shared_to_groups=resolved_share_groups,
                        session_id=session_id
                    )
                    return f"✅ 日程实例已独立并更新！\n（已从重复系列中分离）\nID: {item_uuid}"
                else:
                    # 普通编辑
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
                        shared_to_groups=resolved_share_groups,
                        ddl=ddl,
                        session_id=session_id,
                        _clear_rrule=clear_repeat
                    )
                    return f"✅ 日程更新成功！\n标题: {result.get('title')}\nID: {item_uuid}"
        
        elif resolved_type == "todo":
            # To do 不支持重复，直接更新
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
            # 检查是否是重复提醒
            reminder = ReminderService.get_reminder_by_id(user, item_uuid)
            is_recurring = reminder and (reminder.get('is_recurring') or reminder.get('series_id'))
            
            # 转换 edit_scope: Agent 使用 'future'，API 使用 'from_this'
            api_edit_scope = 'from_this' if edit_scope == 'future' else edit_scope
            
            if is_recurring and edit_scope != "single":
                # 使用批量编辑
                result = ReminderService.bulk_edit(
                    user=user,
                    reminder_id=item_uuid,
                    operation='edit',
                    edit_scope=api_edit_scope,
                    from_time=from_time,
                    title=title,
                    content=content or description,
                    trigger_time=trigger_time,
                    priority=priority,
                    status=status,
                    rrule=rrule,
                    session_id=session_id
                )
                scope_desc = {"all": "整个系列", "from_this": "此实例及之后", "from_time": f"从 {from_time} 开始"}.get(api_edit_scope, api_edit_scope)
                return f"✅ 提醒批量更新成功！\n范围: {scope_desc}\n更新数量: {result.get('updated_count', 'N/A')}"
            else:
                # 单个实例或非重复提醒
                if is_recurring and edit_scope == "single":
                    result = ReminderService.bulk_edit(
                        user=user,
                        reminder_id=item_uuid,
                        operation='edit',
                        edit_scope='single',
                        title=title,
                        content=content or description,
                        trigger_time=trigger_time,
                        priority=priority,
                        status=status,
                        rrule="",  # 清除重复规则以独立
                        session_id=session_id
                    )
                    return f"✅ 提醒实例已独立并更新！\n（已从重复系列中分离）\nID: {item_uuid}"
                else:
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
    
    对于重复项目，可以指定删除范围。
    
    Args:
        identifier: 项目标识，支持:
            - "#1", "#2": 使用最近搜索结果的序号
            - UUID: 直接使用项目的UUID
            - "会议": 按标题模糊匹配
        item_type: 可选，显式指定类型
        delete_scope: 删除范围（对重复日程/提醒生效）
            - "single": 仅删除这一个实例
            - "all": 删除整个重复系列
            - "future": 删除此实例及之后的所有实例
    
    Returns:
        删除结果
    
    Examples:
        # 删除单个
        - delete_item(identifier="#1")
        
        # 删除整个重复系列
        - delete_item(identifier="#3", delete_scope="all")
        
        # 删除此次及之后
        - delete_item(identifier="#2", delete_scope="future")
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
            # 检查是否是重复日程
            event = EventService.get_event_by_id(user, item_uuid)
            is_recurring = event and (event.get('is_recurring') or event.get('series_id'))
            
            if is_recurring and delete_scope != "single":
                # 使用批量删除
                result = EventService.bulk_edit(
                    user=user,
                    event_id=item_uuid,
                    operation='delete',
                    edit_scope=delete_scope,
                    session_id=session_id
                )
                CacheManager.invalidate_item(session_id, item_uuid)
                scope_text = {"all": "整个系列", "future": "此次及之后"}.get(delete_scope, "")
                return f"✅ 日程批量删除成功！（{scope_text}）\n删除数量: {result.get('deleted_count', 'N/A')}"
            else:
                # 单个删除
                success = EventService.delete_event(
                    user=user,
                    event_id=item_uuid,
                    delete_scope='single',
                    session_id=session_id
                )
                if success:
                    CacheManager.invalidate_item(session_id, item_uuid)
                    return f"✅ 日程删除成功！\nID: {item_uuid}"
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
            # 检查是否是重复提醒
            reminder = ReminderService.get_reminder_by_id(user, item_uuid)
            is_recurring = reminder and (reminder.get('is_recurring') or reminder.get('series_id'))
            
            # 转换 delete_scope: Agent 使用 'future'，API 使用 'from_this'
            api_delete_scope = 'from_this' if delete_scope == 'future' else delete_scope
            
            if is_recurring and delete_scope != "single":
                # 使用批量删除
                result = ReminderService.bulk_edit(
                    user=user,
                    reminder_id=item_uuid,
                    operation='delete',
                    edit_scope=api_delete_scope,
                    session_id=session_id
                )
                CacheManager.invalidate_item(session_id, item_uuid)
                scope_text = {"all": "整个系列", "from_this": "此次及之后"}.get(api_delete_scope, "")
                return f"✅ 提醒批量删除成功！（{scope_text}）"
            else:
                # 单个删除
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
    返回的编号使用 #g 前缀，与日程/待办/提醒的 # 编号区分。
    
    Returns:
        事件组列表，包含名称和描述
    
    Examples:
        调用后返回:
        #g1 工作 - 工作相关日程
        #g2 个人 - 个人事务
        #g3 学习 - 学习计划
        
        使用示例：
        - 创建日程并指定事件组: create_item(..., event_group='#g1')
        - 按事件组搜索: search_items(event_group='工作')
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
def get_share_groups(config: RunnableConfig) -> str:
    """
    获取用户所在的所有分享组列表
    
    用于查看可用的分享组，以便在创建/更新日程时设置 shared_to_groups 参数，
    或在搜索时使用 share_groups 参数筛选。
    返回的编号使用 #s 前缀，与日程/待办/提醒的 # 编号区分。
    
    Returns:
        分享组列表，包含名称、角色和成员数
    
    Examples:
        调用后返回:
        #s1 工作协作组 (群主, 5人)
        #s2 家庭日程 (成员, 3人)
        #s3 项目组 (管理员, 8人)
        
        使用示例：
        - 创建日程并分享: create_item(..., shared_to_groups=['#s1'])
        - 按分享组搜索: search_items(share_groups=['#s1'], share_groups_only=True)
    """
    user = _get_user_from_config(config)
    
    try:
        # 强制刷新以获取最新数据（用户可能刚加入/退出分享组）
        groups = ShareGroupService.get_user_share_groups(user, force_refresh=True)
        
        if not groups:
            return "暂无加入的分享组。可以创建或加入分享组后，与他人共享日程。"
        
        return ShareGroupService.format_share_groups_for_display(groups)
        
    except Exception as e:
        logger.error(f"获取分享组失败: {e}", exc_info=True)
        return f"获取分享组失败: {str(e)}"


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


@tool
def check_schedule_conflicts(
    config: RunnableConfig,
    time_range: str = "this_week",
    include_share_groups: bool = True,
    analysis_focus: Optional[List[Literal["conflicts", "density", "reasonability"]]] = None
) -> str:
    """
    智能日程冲突检查：结合算法检测和LLM分析，给出个性化的日程优化建议
    
    工作流程：
    1. 第一阶段：硬冲突检测（算法）- 找出时间重叠的事件
    2. 第二阶段：LLM智能分析 - 结合用户偏好，判断真实冲突并给出建议
    
    Args:
        time_range: 时间范围，支持：
            - 预设: "today", "tomorrow", "this_week", "next_week", "this_month"
            - 中文: "今天", "明天", "本周", "下周", "本月"
            - 自定义: "2024-01-15 ~ 2024-01-20"
        include_share_groups: 是否包含分享组日程（他人日程也会占用时间）
        analysis_focus: 分析重点，默认全部检查
            - "conflicts": 冲突真实性判断（有些事情可以同时进行）
            - "density": 工作密度分析（过载、缺少休息等）
            - "reasonability": 合理性审查（深夜会议、超长事件等）
    
    Returns:
        包含硬冲突检测结果和LLM智能分析的完整报告
    
    示例:
        check_schedule_conflicts(time_range="this_week")
        check_schedule_conflicts(time_range="2024-01-15 ~ 2024-01-20", analysis_focus=["conflicts"])
    """
    user = _get_user_from_config(config)
    session_id = _get_session_id_from_config(config)
    
    # 默认分析所有方面
    if analysis_focus is None:
        analysis_focus = ["conflicts", "density", "reasonability"]
    
    # 解析时间范围
    start_date, end_date = TimeRangeParser.parse(time_range)
    if not start_date or not end_date:
        return f"❌ 无法解析时间范围: {time_range}"
    
    time_range_display = f"{start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}"
    
    # 辅助函数：检查事件是否在时间范围内
    def event_in_range(event: dict) -> bool:
        from agent_service.tools.conflict_analyzer import parse_datetime
        event_start = parse_datetime(event.get('start', ''))
        event_end = parse_datetime(event.get('end', ''))
        if not event_start or not event_end:
            return False
        # 事件结束时间在范围开始之后，且事件开始时间在范围结束之前
        return event_end >= start_date and event_start <= end_date
    
    # ==========================================
    # 收集所有日程
    # ==========================================
    all_events = []
    event_index = 1
    
    # 1. 用户自己的日程
    try:
        user_events = EventService.get_events(user=user)
        
        # 过滤时间范围内的事件
        for event in user_events:
            if event_in_range(event):
                event['_index'] = event_index
                event['_editable'] = True
                event['_source'] = 'user'
                all_events.append(event)
                event_index += 1
            
    except Exception as e:
        logger.error(f"获取用户日程失败: {e}")
    
    # 2. 分享组日程（可选）
    if include_share_groups:
        try:
            share_groups = ShareGroupService.get_user_share_groups(user, force_refresh=True)
            
            for group in share_groups:
                group_id = group.get('share_group_id')  # 修复：正确的键名
                if not group_id:
                    logger.warning(f"[冲突检查] 跳过无 ID 的分享组: {group}")
                    continue
                    
                group_name = group.get('share_group_name', '未命名分享组')  # 修复：正确的键名
                
                # get_share_group_events 返回 (events, members) 元组
                shared_events, members = ShareGroupService.get_share_group_events(
                    user=user,
                    share_group_id=str(group_id)
                )
                
                # 创建成员ID到用户名的映射
                member_map = {m['user_id']: m['username'] for m in members}
                
                added_count = 0
                skipped_own = 0
                skipped_range = 0
                
                for event in shared_events:
                    # 跳过用户自己的日程（避免重复）
                    if event.get('is_own', False):
                        skipped_own += 1
                        continue
                    
                    # 过滤时间范围
                    if not event_in_range(event):
                        skipped_range += 1
                        continue
                    
                    # 添加所有者用户名
                    owner_id = event.get('owner_id') or event.get('user_id')
                    if owner_id:
                        event['_owner_username'] = member_map.get(owner_id, '未知用户')
                    
                    event['_index'] = event_index
                    event['_editable'] = False
                    event['_source'] = 'share_group'
                    event['_share_group_name'] = group_name
                    all_events.append(event)
                    added_count += 1
                    event_index += 1
                
        except Exception as e:
            logger.error(f"获取分享组日程失败: {e}")
    
    if not all_events:
        return f"📅 时间范围 {time_range_display} 内没有找到任何日程"
    
    # ==========================================
    # 第一阶段：硬冲突检测（算法）
    # ==========================================
    hard_conflicts = detect_hard_conflicts(all_events)
    daily_density = analyze_daily_density(all_events)
    
    # 统计日程数量
    user_event_count = sum(1 for e in all_events if e.get('_source') == 'user')
    others_event_count = sum(1 for e in all_events if e.get('_source') == 'share_group')
    
    # 构建报告头部
    output_parts = []
    output_parts.append(f"🔍 **智能日程冲突检查报告**")
    output_parts.append(f"时间范围: {time_range_display}")
    output_parts.append(f"分析日程: {len(all_events)} 个")
    output_parts.append(f"  - 用户自己的日程: {user_event_count} 个")
    if others_event_count > 0:
        output_parts.append(f"  - 分享组中他人日程: {others_event_count} 个")
    output_parts.append("")
    output_parts.append("━" * 40)
    output_parts.append("📋 **第一阶段：硬冲突检测（算法）**")
    output_parts.append("━" * 40)
    output_parts.append("")
    output_parts.append(format_hard_conflicts_report(hard_conflicts))
    
    # 添加工作密度概览
    output_parts.append("")
    output_parts.append("📊 **每日工作密度**")
    output_parts.append(format_density_report(daily_density))
    
    # ==========================================
    # 第二阶段：LLM 智能分析
    # ==========================================
    output_parts.append("")
    output_parts.append("━" * 40)
    output_parts.append("🤖 **第二阶段：智能分析（结合个人偏好）**")
    output_parts.append("━" * 40)
    output_parts.append("")
    
    # 获取用户个人偏好
    personal_info = get_user_personal_info(user)
    
    if personal_info:
        output_parts.append(f"📝 已加载 {len(personal_info)} 条个人偏好数据")
    else:
        output_parts.append("📝 暂无个人偏好数据（建议添加以获得更个性化的分析）")
    output_parts.append("")
    
    # 调用 LLM 分析
    try:
        # 转换为 List[str] 类型
        focus_list: List[str] = list(analysis_focus) if analysis_focus else []
        
        llm_analysis, token_info = analyze_with_llm(
            user=user,
            events=all_events,
            hard_conflicts=hard_conflicts,
            personal_info=personal_info,
            daily_density=daily_density,
            analysis_focus=focus_list
        )
        
        output_parts.append(llm_analysis)
        
        # 添加 Token 使用信息
        if token_info:
            output_parts.append("")
            output_parts.append("━" * 40)
            in_tokens = token_info.get('input_tokens', 0)
            out_tokens = token_info.get('output_tokens', 0)
            model_id = token_info.get('model_id', 'unknown')
            output_parts.append(f"📈 分析消耗: {in_tokens + out_tokens} tokens (模型: {model_id})")
            
    except Exception as e:
        logger.exception(f"LLM 分析失败: {e}")
        output_parts.append(f"⚠️ LLM 分析失败: {str(e)}")
        output_parts.append("请检查模型配置或稍后重试。")
    
    return "\n".join(output_parts)


# 导出的工具列表
UNIFIED_PLANNER_TOOLS = [
    search_items,
    create_item,
    update_item,
    delete_item,
    get_event_groups,
    get_share_groups,
    complete_todo,
    check_schedule_conflicts,
]
