"""
冲突分析服务
提供日程冲突检测和 LLM 智能分析功能
"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Tuple
from logger import logger


# ==========================================
# 日期时间解析工具
# ==========================================

def parse_datetime(dt_str: str) -> Optional[datetime]:
    """解析日期时间字符串"""
    if not dt_str:
        return None
    
    # 支持多种格式
    formats = [
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M:%S.%f',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%dT%H:%M:%S.%fZ',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M',  # ISO 8601 without seconds
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M',
        '%Y-%m-%d',
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(dt_str.replace('+00:00', 'Z').rstrip('Z'), fmt.rstrip('Z'))
        except ValueError:
            continue
    
    logger.warning(f"无法解析日期时间: {dt_str}")
    return None


def format_datetime_for_display(dt: datetime) -> str:
    """格式化日期时间用于显示"""
    return dt.strftime('%Y-%m-%d %H:%M')


def get_weekday_name(dt: datetime) -> str:
    """获取星期名称"""
    weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    return weekdays[dt.weekday()]


# ==========================================
# 硬冲突检测算法
# ==========================================

def detect_hard_conflicts(events: List[dict]) -> List[dict]:
    """
    检测时间重叠的硬冲突（纯算法，不依赖 LLM）
    
    副作用：会在成功解析的事件上添加 _parsed_start 和 _parsed_end 字段
    
    Args:
        events: 事件列表，每个事件包含 id, title, start, end 等字段
    
    Returns:
        冲突列表，每个冲突包含:
        - conflict_id: 冲突编号
        - events: 冲突的两个事件
        - overlap_duration: 重叠时长（分钟）
        - overlap_period: 重叠时段
    """
    if len(events) < 2:
        return []
    
    # 解析时间，并直接修改原始事件（添加 _parsed_* 字段）
    parsed_events = []
    for event in events:
        # 跳过已解析的事件
        if '_parsed_start' in event and '_parsed_end' in event:
            parsed_events.append(event)
            continue
            
        start = parse_datetime(event.get('start', ''))
        end = parse_datetime(event.get('end', ''))
        
        if start and end and end > start:
            # 直接修改原始事件，添加解析结果
            event['_parsed_start'] = start
            event['_parsed_end'] = end
            parsed_events.append(event)
    
    # 按开始时间排序
    sorted_events = sorted(parsed_events, key=lambda e: e['_parsed_start'])
    
    conflicts = []
    conflict_id = 1
    
    for i, event1 in enumerate(sorted_events):
        start1 = event1['_parsed_start']
        end1 = event1['_parsed_end']
        
        for event2 in sorted_events[i + 1:]:
            start2 = event2['_parsed_start']
            end2 = event2['_parsed_end']
            
            # 检查时间重叠
            if start2 < end1:
                overlap_start = max(start1, start2)
                overlap_end = min(end1, end2)
                overlap_minutes = int((overlap_end - overlap_start).total_seconds() / 60)
                
                if overlap_minutes > 0:
                    conflicts.append({
                        'conflict_id': conflict_id,
                        'events': [
                            {k: v for k, v in event1.items() if not k.startswith('_parsed')},
                            {k: v for k, v in event2.items() if not k.startswith('_parsed')}
                        ],
                        'overlap_duration': overlap_minutes,
                        'overlap_period': {
                            'start': format_datetime_for_display(overlap_start),
                            'end': format_datetime_for_display(overlap_end)
                        }
                    })
                    conflict_id += 1
            else:
                # 已排序，后面的不会再重叠
                break
    
    return conflicts


# ==========================================
# 工作密度分析
# ==========================================

def analyze_daily_density(events: List[dict]) -> Dict[str, dict]:
    """
    分析每日工作密度
    
    Args:
        events: 事件列表
    
    Returns:
        按日期分组的密度分析结果
    """
    # 按日期分组
    daily_events: Dict[str, List[dict]] = {}
    
    for event in events:
        # 优先使用已解析的时间（避免重复解析）
        if '_parsed_start' in event:
            start = event['_parsed_start']
        else:
            start = parse_datetime(event.get('start', ''))
            
        if start:
            date_str = start.strftime('%Y-%m-%d')
            if date_str not in daily_events:
                daily_events[date_str] = []
            daily_events[date_str].append(event)
    
    # 分析每一天
    results = {}
    for date_str, day_events in daily_events.items():
        total_minutes = 0
        event_count = len(day_events)
        
        for event in day_events:
            # 优先使用已解析的时间
            if '_parsed_start' in event and '_parsed_end' in event:
                start = event['_parsed_start']
                end = event['_parsed_end']
            else:
                start = parse_datetime(event.get('start', ''))
                end = parse_datetime(event.get('end', ''))
                
            if start and end:
                duration = (end - start).total_seconds() / 60
                total_minutes += duration
        
        total_hours = total_minutes / 60
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        weekday = get_weekday_name(date_obj)
        
        # 评估负载
        if total_hours > 10:
            load_level = 'overload'
            load_emoji = '🔴'
            load_text = '过载'
        elif total_hours > 8:
            load_level = 'high'
            load_emoji = '🟠'
            load_text = '较高'
        elif total_hours > 6:
            load_level = 'normal'
            load_emoji = '🟢'
            load_text = '正常'
        else:
            load_level = 'light'
            load_emoji = '🔵'
            load_text = '轻松'
        
        results[date_str] = {
            'date': date_str,
            'weekday': weekday,
            'event_count': event_count,
            'total_hours': round(total_hours, 1),
            'load_level': load_level,
            'load_emoji': load_emoji,
            'load_text': load_text,
            'events': day_events
        }
    
    return results


# ==========================================
# 获取用户个人偏好
# ==========================================

def get_user_personal_info(user) -> List[dict]:
    """获取用户个人偏好数据"""
    from agent_service.models import UserPersonalInfo
    
    try:
        personal_info_qs = UserPersonalInfo.objects.filter(
            user=user
        ).order_by('key')
        
        return [
            {
                'key': info.key,
                'value': info.value,
                'description': info.description or ''
            }
            for info in personal_info_qs
        ]
    except Exception as e:
        logger.error(f"获取个人偏好失败: {e}")
        return []


# ==========================================
# 构建 LLM 分析提示词
# ==========================================

def build_analysis_prompt(
    events: List[dict],
    hard_conflicts: List[dict],
    personal_info: List[dict],
    daily_density: Dict[str, dict],
    analysis_focus: List[str]
) -> str:
    """构建详细的分析提示词"""
    
    prompt_parts = []
    
    # 1. 用户个人偏好
    prompt_parts.append("# 用户个人信息与偏好\n")
    if personal_info:
        for info in personal_info:
            desc_part = f" ({info['description']})" if info['description'] else ""
            prompt_parts.append(f"- **{info['key']}**: {info['value']}{desc_part}")
    else:
        prompt_parts.append("（暂无个人偏好数据，请基于常规标准分析）")
    
    # 2. 时间段内所有日程（分类显示）
    prompt_parts.append("\n\n# 待分析的日程安排\n")
    
    # 分离用户自己的日程和别人的日程
    user_events = [e for e in events if e.get('_source') == 'user']
    others_events = [e for e in events if e.get('_source') == 'share_group']
    
    logger.info(f"[冲突分析] 构建提示词: 总共 {len(events)} 个日程, 用户日程 {len(user_events)} 个, 分享组日程 {len(others_events)} 个")
    
    if user_events:
        prompt_parts.append("## 用户自己的日程（可编辑）\n")
        for event in user_events:
            event_str = _format_event_for_analysis(event)
            prompt_parts.append(event_str)
    
    if others_events:
        prompt_parts.append("\n## 分享组中他人的日程（只读）\n")
        for event in others_events:
            event_str = _format_event_for_analysis(event)
            prompt_parts.append(event_str)
    
    # 3. 硬冲突列表
    prompt_parts.append("\n\n# 检测到的硬冲突（时间重叠）\n")
    if hard_conflicts:
        for conflict in hard_conflicts:
            e1, e2 = conflict['events']
            prompt_parts.append(
                f"**冲突 {conflict['conflict_id']}**: "
                f"#{e1.get('_index', '?')} 《{e1.get('title', '未命名')}》 与 "
                f"#{e2.get('_index', '?')} 《{e2.get('title', '未命名')}》 "
                f"在 {conflict['overlap_period']['start']} ~ {conflict['overlap_period']['end']} "
                f"重叠 {conflict['overlap_duration']} 分钟"
            )
    else:
        prompt_parts.append("✅ 未检测到时间重叠")
    
    # 4. 工作密度预分析
    prompt_parts.append("\n\n# 每日工作密度统计\n")
    for date_str, density in sorted(daily_density.items()):
        prompt_parts.append(
            f"- **{date_str} ({density['weekday']})**: "
            f"{density['event_count']} 个事件，总时长 {density['total_hours']} 小时 "
            f"{density['load_emoji']} {density['load_text']}"
        )
    
    # 5. 分析任务
    prompt_parts.append("\n\n# 分析任务\n")
    prompt_parts.append("请根据用户的日程安排和个人偏好，进行以下分析：\n")
    
    if 'conflicts' in analysis_focus:
        prompt_parts.append("""
## 1. 冲突真实性判断
对于每个硬冲突，请判断：
- **是否真的冲突**：有些事情可以同时进行（如听音乐+工作、通勤+学习播客）
- **冲突严重程度**：critical（完全冲突）/ high（需要调整）/ medium（可协调）/ low（伪冲突）
- **原因**：结合事件性质和用户偏好说明
- **建议**：具体的解决方案，包含时间建议

**重要提示**：
- 如果冲突涉及他人的只读日程（标记为"只读"），无法修改该日程，只能建议调整用户自己的日程
- 如果冲突是用户自己的两个日程，可以建议调整任一日程

输出格式示例：
```
冲突1: 真实冲突 [HIGH]
- 涉及: 用户日程 + 他人只读日程
- 原因: 两个都是需要全神贯注的会议
- 建议: 【只能调整用户日程】将 #X《用户的会议》推迟到 15:30，或改到次日上午
```
""")
    
    if 'density' in analysis_focus:
        prompt_parts.append("""
## 2. 工作密度分析
对于标记为"较高"或"过载"的日期，请分析：
- 具体的问题点（如连续工作无休息、缺少午餐时间等）
- 结合用户偏好评估（如用户提到的工作时长偏好）
- 给出具体的优化建议

""")
    
    if 'reasonability' in analysis_focus:
        prompt_parts.append("""
## 3. 合理性审查
检查以下问题：
- 深夜或凌晨的事件（结合用户作息习惯）
- 超长事件（>4小时无休息）
- 周末工作（结合用户工作生活平衡偏好）
- 其他不符合用户习惯的安排

对每个问题，说明原因并给出具体建议。
""")
    
    # 6. 输出要求
    prompt_parts.append("""
---

# 输出要求
1. 使用清晰的 Markdown 格式
2. 每条建议要具体、可执行（包含 #序号、具体时间）
3. 优先级排序：critical > high > medium > low
4. 结合用户个人偏好给出个性化建议
5. 对于只读日程（他人分享），说明无法修改但可以调整自己的安排
6. 在最后给出一个简洁的总结和优先处理事项

请开始分析：
""")
    
    return "\n".join(prompt_parts)


def _format_event_for_analysis(event: dict) -> str:
    """格式化单个事件供 LLM 分析"""
    index = event.get('_index', '?')
    title = event.get('title', '未命名')
    start = event.get('start', '')
    end = event.get('end', '')
    description = event.get('description', '')
    share_group = event.get('_share_group_name', '')
    owner = event.get('_owner_username', '')
    editable = event.get('_editable', True)
    source = event.get('_source', 'user')
    
    # 构建标题行
    if source == 'share_group':
        parts = [f"**#{index}** 《{title}》 [他人日程]"]
    else:
        parts = [f"**#{index}** 《{title}》"]
    
    parts.append(f"  - 时间: {start} ~ {end}")
    
    if description:
        # 截断过长的描述
        desc = description[:100] + '...' if len(description) > 100 else description
        parts.append(f"  - 描述: {desc}")
    
    if share_group:
        parts.append(f"  - 来源: 分享组「{share_group}」")
        if owner:
            parts.append(f"  - 创建者: {owner}")
    
    if not editable:
        parts.append(f"  - ⚠️ **只读**（他人日程，无法修改，只能调整自己的安排）")
    else:
        parts.append(f"  - ✏️ 可编辑")
    
    return "\n".join(parts)


# ==========================================
# LLM 智能分析
# ==========================================

def analyze_with_llm(
    user,
    events: List[dict],
    hard_conflicts: List[dict],
    personal_info: List[dict],
    daily_density: Dict[str, dict],
    analysis_focus: List[str]
) -> Tuple[str, dict]:
    """
    调用 LLM 进行智能分析
    
    Args:
        user: Django User 对象
        events: 事件列表
        hard_conflicts: 硬冲突列表
        personal_info: 个人偏好列表
        daily_density: 每日密度分析
        analysis_focus: 分析重点
    
    Returns:
        (分析结果文本, token使用信息)
    """
    from langchain_openai import ChatOpenAI
    from agent_service.agent_graph import get_user_llm
    from agent_service.context_optimizer import (
        get_current_model_config, update_token_usage
    )
    
    # 构建提示词
    prompt = build_analysis_prompt(
        events, hard_conflicts, personal_info, daily_density, analysis_focus
    )
    
    # 获取用户配置的 LLM
    try:
        user_llm = get_user_llm(
            user,
            provider_user_id_suffix="-conflict-analyzer",
        )
        current_model_id, _ = get_current_model_config(user)
    except Exception as e:
        logger.error(f"获取用户 LLM 配置失败: {e}")
        return f"无法获取 LLM 配置: {e}", {}
    
    # 系统提示词
    system_prompt = """你是一位专业的日程分析师，擅长：
1. 识别真实的时间冲突（考虑事件性质，有些事情可以同时进行）
2. 评估工作负荷和时间安排的合理性
3. 结合用户个人偏好给出个性化建议

你的分析要客观、实用，建议要具体、可执行（包含 #序号 和具体时间）。
使用清晰的 Markdown 格式输出。"""
    
    try:
        # 调用 LLM
        from langchain_core.messages import SystemMessage, HumanMessage
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt)
        ]
        
        response = user_llm.invoke(messages)
        
        # 获取 Token 使用量
        input_tokens = 0
        output_tokens = 0
        
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            usage = response.usage_metadata
            if isinstance(usage, dict):
                input_tokens = usage.get('input_tokens', 0) or usage.get('prompt_tokens', 0)
                output_tokens = usage.get('output_tokens', 0) or usage.get('completion_tokens', 0)
            else:
                input_tokens = getattr(usage, 'input_tokens', 0) or getattr(usage, 'prompt_tokens', 0)
                output_tokens = getattr(usage, 'output_tokens', 0) or getattr(usage, 'completion_tokens', 0)
        
        # 回退：从 response_metadata 获取
        if not input_tokens and hasattr(response, 'response_metadata'):
            metadata = response.response_metadata
            usage = metadata.get('token_usage') or metadata.get('usage') or {}
            input_tokens = usage.get('prompt_tokens', 0) or usage.get('input_tokens', 0)
            output_tokens = usage.get('completion_tokens', 0) or usage.get('output_tokens', 0)
        
        # 如果仍无法获取，使用估算
        if input_tokens == 0:
            input_tokens = int(len(prompt) / 2.5)
        if output_tokens == 0:
            output_tokens = int(len(response.content) / 2.5) if hasattr(response, 'content') else 50
        
        # 更新 Token 统计（自动计费）
        if input_tokens > 0 or output_tokens > 0:
            update_token_usage(user, input_tokens, output_tokens, current_model_id)
        
        token_info = {
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'model_id': current_model_id
        }
        
        # 提取分析结果文本
        if hasattr(response, 'content'):
            content = response.content
            if isinstance(content, str):
                analysis_result = content
            elif isinstance(content, list):
                # 如果是列表（多个内容块），提取文本部分
                text_parts = []
                for item in content:
                    if isinstance(item, str):
                        text_parts.append(item)
                    elif isinstance(item, dict) and 'text' in item:
                        text_parts.append(item['text'])
                analysis_result = "\n".join(text_parts)
            else:
                analysis_result = str(content)
        else:
            analysis_result = str(response)
        
        return analysis_result, token_info
        
    except Exception as e:
        logger.exception(f"LLM 分析失败: {e}")
        return f"LLM 分析失败: {e}", {}


# ==========================================
# 格式化冲突报告
# ==========================================

def format_hard_conflicts_report(conflicts: List[dict]) -> str:
    """格式化硬冲突检测报告"""
    if not conflicts:
        return "✅ 未检测到时间重叠"
    
    lines = [f"检测到 {len(conflicts)} 个时间重叠：\n"]
    
    for conflict in conflicts:
        e1, e2 = conflict['events']
        idx1 = e1.get('_index', '?')
        idx2 = e2.get('_index', '?')
        title1 = e1.get('title', '未命名')
        title2 = e2.get('title', '未命名')
        
        lines.append(f"【冲突{conflict['conflict_id']}】#{idx1}《{title1}》 vs #{idx2}《{title2}》")
        lines.append(f"  重叠时段: {conflict['overlap_period']['start']} ~ {conflict['overlap_period']['end']} ({conflict['overlap_duration']}分钟)")
        lines.append("")
    
    return "\n".join(lines)


def format_density_report(daily_density: Dict[str, dict]) -> str:
    """格式化工作密度报告"""
    if not daily_density:
        return "无工作密度数据"
    
    lines = []
    for date_str, density in sorted(daily_density.items()):
        lines.append(
            f"{density['load_emoji']} **{date_str} ({density['weekday']})**: "
            f"{density['event_count']} 个事件，共 {density['total_hours']} 小时 - {density['load_text']}"
        )
    
    return "\n".join(lines)
