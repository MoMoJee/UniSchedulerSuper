# Planner 工具系统性优化方案

> 创建日期: 2025-12-29  
> 状态: 设计阶段

## 📋 问题分析

### 当前痛点

| 问题 | 现状 | 影响 |
|------|------|------|
| **UUID 依赖** | 修改/删除 events/reminder/todo 必须提供完整 UUID | Agent 需先查询再操作，增加多轮对话 |
| **日程组 UUID** | 创建日程时需填入 groupID（UUID格式） | Agent 难以知道用户的日程组 ID |
| **分散的查询工具** | get_events, get_todos, get_reminders 三个独立工具 | 无法统一筛选，效率低 |
| **参数冗余** | 编辑时即使只改一个字段，也需要传递所有参数 | 容易出错，增加 token 消耗 |
| **RRule 空值歧义** | rrule="" 可能被误判为"清空重复规则" | 导致意外删除重复设置 |
| **时间筛选复杂** | 只能用标准时间格式，无预置快捷选项 | Agent 需要计算时间范围 |

---

## 🎯 优化目标

1. **统一查询接口**: 合并三个查询工具，支持类型筛选
2. **智能标识符**: 支持编号(#1)、名称、UUID 三种引用方式
3. **日程组名称映射**: 自动建立名称→UUID 映射
4. **会话级缓存**: 查询结果建立编号映射，支持回滚清除
5. **增量编辑**: 只传需要修改的字段，区分"不变"和"清空"
6. **时间快捷筛选**: 预置今天/昨天/本周/本月等快捷选项

---

## 🏗️ 架构设计

### 1. 新增数据模型

```python
# agent_service/models.py

class SearchResultCache(models.Model):
    """
    搜索结果缓存 - 存储编号到UUID的映射
    支持会话级别存储和回滚同步清除
    """
    session = models.ForeignKey(AgentSession, on_delete=models.CASCADE, related_name='search_caches')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    # 缓存的结果类型
    result_type = models.CharField(max_length=20, help_text="event/todo/reminder")
    
    # 编号 → UUID 映射 (JSON)
    # 格式: {"#1": "uuid-xxx", "#2": "uuid-yyy", ...}
    index_mapping = models.JSONField(default=dict)
    
    # 名称 → UUID 映射 (JSON) - 用于模糊匹配
    # 格式: {"会议": "uuid-xxx", "工作日程": "uuid-yyy", ...}
    title_mapping = models.JSONField(default=dict)
    
    # 最后一次查询的原始结果（用于展示）
    last_results = models.JSONField(default=list)
    
    # 关联的检查点ID（用于回滚同步）
    checkpoint_id = models.CharField(max_length=100, blank=True, default="")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['session', 'result_type']


class EventGroupCache(models.Model):
    """
    日程组名称缓存
    自动建立名称→UUID映射，减少用户输入复杂度
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='event_group_caches')
    
    # 名称 → UUID 映射
    # 格式: {"工作": "uuid-xxx", "个人": "uuid-yyy", ...}
    name_mapping = models.JSONField(default=dict)
    
    # UUID → 名称 反向映射（用于展示）
    uuid_mapping = models.JSONField(default=dict)
    
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "日程组缓存"
```

### 2. 统一查询工具设计

```python
# agent_service/tools/unified_search_tool.py

用户调用:
update_item("#1", "event", title="新标题", start="...")

↓ 工具层（接收所有可能参数）
{
  title: "新标题",
  start: "...",
  due_date: UNSET_VALUE,  // 未传递
  trigger_time: UNSET_VALUE,
  ...
}

↓ ParamAdapter.adapt_params("event", ...)
{
  title: "新标题",
  start: "..."
  // 自动过滤掉 due_date, trigger_time 等不支持参数
}

↓ 服务层
EventService.update_event(user, uuid, title="新标题", start="...")@tool("search_items")
def search_items(
    item_type: str = "all",           # "event" | "todo" | "reminder" | "all"
    group_name: str = "",             # 日程组名称（仅 event/todo）
    time_range: str = "",             # 时间范围
    title_contains: str = "",         # 标题包含
    description_contains: str = "",   # 描述包含
    config: RunnableConfig = None
) -> str:
    """
    统一搜索工具 - 搜索日程、待办事项、提醒
    
    Args:
        item_type: 搜索类型
            - "event": 仅日程
            - "todo": 仅待办事项
            - "reminder": 仅提醒
            - "all": 全部类型
        
        group_name: 日程组名称筛选（仅对 event/todo 有效）
            - 示例: "工作", "个人", "学习"
            - reminder 没有日程组归属
        
        time_range: 时间范围筛选
            快捷选项:
            - "today": 今天
            - "yesterday": 昨天
            - "tomorrow": 明天
            - "this_week": 本周
            - "next_week": 下周
            - "this_month": 本月
            - "next_month": 下月
            标准格式:
            - "2025-01-15": 指定日期
            - "2025-01-15,2025-01-20": 日期范围
        
        title_contains: 标题关键词搜索
        description_contains: 描述关键词搜索
    
    Returns:
        格式化的搜索结果，每条结果带有编号(#1, #2...)
        编号可用于后续的编辑/删除操作
    
    Examples:
        - search_items(item_type="event", time_range="today")
        - search_items(item_type="todo", group_name="工作")
        - search_items(title_contains="会议")
        - search_items(item_type="reminder", time_range="this_week")
    """
```

### 3. 智能标识符解析

```python
# agent_service/tools/identifier_resolver.py

class IdentifierResolver:
    """
    智能标识符解析器
    支持多种引用方式解析为 UUID
    """
    
    def resolve(self, identifier: str, item_type: str, session, user) -> Optional[str]:
        """
        解析标识符为 UUID
        
        Args:
            identifier: 标识符，支持以下格式：
                - "#1", "#2": 编号引用（从最近查询结果）
                - "550e8400-e29b-41d4...": 完整 UUID
                - "会议": 标题匹配
            item_type: "event" | "todo" | "reminder"
            session: 当前会话
            user: 当前用户
        
        Returns:
            解析后的 UUID，找不到返回 None
        """
        # 1. 检查是否是编号格式 (#N)
        if identifier.startswith('#'):
            return self._resolve_by_index(identifier, item_type, session)
        
        # 2. 检查是否是 UUID 格式
        if self._is_uuid(identifier):
            return identifier
        
        # 3. 按标题模糊匹配
        return self._resolve_by_title(identifier, item_type, session, user)
    
    def _resolve_by_index(self, index_str: str, item_type: str, session) -> Optional[str]:
        """从会话缓存中按编号解析"""
        cache = SearchResultCache.objects.filter(
            session=session,
            result_type=item_type
        ).first()
        
        if cache and cache.index_mapping:
            return cache.index_mapping.get(index_str)
        return None
```

### 4. 增量编辑设计 + 参数兼容层

#### 问题：三种类型参数差异

| 参数名 | Event | Todo | Reminder | 说明 |
|--------|-------|------|----------|------|
| title | ✅ | ✅ | ✅ | 通用 |
| description | ✅ | ✅ | ❌ | Todo 和 Event 有 |
| content | ❌ | ❌ | ✅ | Reminder 特有 |
| start / end | ✅ | ❌ | ❌ | Event 特有 |
| due_date | ❌ | ✅ | ❌ | Todo 特有 |
| trigger_time | ❌ | ❌ | ✅ | Reminder 特有 |
| estimated_duration | ❌ | ✅ | ❌ | Todo 特有 |
| importance | ✅ | ✅ | ❌ | Event 和 Todo |
| urgency | ✅ | ✅ | ❌ | Event 和 Todo |
| groupID | ✅ | ✅ | ❌ | Event 和 Todo |
| rrule | ✅ | ❌ | ✅ | Event 和 Reminder |
| ddl | ✅ | ❌ | ❌ | Event 特有 |
| shared_to_groups | ✅ | ❌ | ❌ | Event 特有 |
| priority | ❌ | ❌ | ✅ | Reminder 特有 |
| status | ❌ | ✅ | ✅ | Todo 和 Reminder |
| update_scope | ✅ | ❌ | ❌ | Event 重复编辑 |

#### 解决方案：参数适配器

```python
# 核心思想：使用特殊标记区分"不传递"和"清空"

# 方案：使用 UNSET 哨兵值
class UNSET:
    """表示参数未设置（区别于 None 或空字符串）"""
    pass

UNSET_VALUE = UNSET()

# 参数映射表
PARAM_MAPPING = {
    "event": {
        "common": ["title", "description", "importance", "urgency"],
        "time": ["start", "end", "ddl"],
        "group": "groupID",
        "repeat": "rrule",
        "special": ["shared_to_groups", "update_scope"]
    },
    "todo": {
        "common": ["title", "description", "importance", "urgency", "status"],
        "time": ["due_date", "estimated_duration"],
        "group": "groupID",
        "repeat": None
    },
    "reminder": {
        "common": ["title", "content", "priority", "status"],
        "time": ["trigger_time"],
        "group": None,
        "repeat": "rrule"
    }
}

class ParamAdapter:
    """参数适配器 - 将统一参数转换为各类型特定参数"""
    
    @staticmethod
    def adapt_params(item_type: str, **kwargs) -> dict:
        """
        转换统一参数为特定类型的参数
        
        Args:
            item_type: "event" | "todo" | "reminder"
            **kwargs: 统一的参数字典
        
        Returns:
            适配后的参数字典（只包含该类型支持的参数）
        """
        adapted = {}
        
        if item_type == "event":
            # Event 参数映射
            if "title" in kwargs and kwargs["title"] is not UNSET_VALUE:
                adapted["title"] = kwargs["title"]
            if "description" in kwargs and kwargs["description"] is not UNSET_VALUE:
                adapted["description"] = kwargs["description"]
            if "start" in kwargs and kwargs["start"] is not UNSET_VALUE:
                adapted["start"] = kwargs["start"]
            if "end" in kwargs and kwargs["end"] is not UNSET_VALUE:
                adapted["end"] = kwargs["end"]
            if "importance" in kwargs and kwargs["importance"] is not UNSET_VALUE:
                adapted["importance"] = kwargs["importance"]
            if "urgency" in kwargs and kwargs["urgency"] is not UNSET_VALUE:
                adapted["urgency"] = kwargs["urgency"]
            if "group_id" in kwargs and kwargs["group_id"] is not UNSET_VALUE:
                adapted["groupID"] = kwargs["group_id"]  # 注意大小写
            if "rrule" in kwargs and kwargs["rrule"] is not UNSET_VALUE:
                adapted["rrule"] = kwargs["rrule"]
            if "ddl" in kwargs and kwargs["ddl"] is not UNSET_VALUE:
                adapted["ddl"] = kwargs["ddl"]
            if "shared_to_groups" in kwargs and kwargs["shared_to_groups"] is not UNSET_VALUE:
                adapted["shared_to_groups"] = kwargs["shared_to_groups"]
            if "update_scope" in kwargs:
                adapted["update_scope"] = kwargs["update_scope"]
                
        elif item_type == "todo":
            # Todo 参数映射
            if "title" in kwargs and kwargs["title"] is not UNSET_VALUE:
                adapted["title"] = kwargs["title"]
            if "description" in kwargs and kwargs["description"] is not UNSET_VALUE:
                adapted["description"] = kwargs["description"]
            if "due_date" in kwargs and kwargs["due_date"] is not UNSET_VALUE:
                adapted["due_date"] = kwargs["due_date"]
            if "estimated_duration" in kwargs and kwargs["estimated_duration"] is not UNSET_VALUE:
                adapted["estimated_duration"] = kwargs["estimated_duration"]
            if "importance" in kwargs and kwargs["importance"] is not UNSET_VALUE:
                adapted["importance"] = kwargs["importance"]
            if "urgency" in kwargs and kwargs["urgency"] is not UNSET_VALUE:
                adapted["urgency"] = kwargs["urgency"]
            if "group_id" in kwargs and kwargs["group_id"] is not UNSET_VALUE:
                adapted["groupID"] = kwargs["group_id"]
            if "status" in kwargs and kwargs["status"] is not UNSET_VALUE:
                adapted["status"] = kwargs["status"]
                
        elif item_type == "reminder":
            # Reminder 参数映射
            if "title" in kwargs and kwargs["title"] is not UNSET_VALUE:
                adapted["title"] = kwargs["title"]
            if "content" in kwargs and kwargs["content"] is not UNSET_VALUE:
                adapted["content"] = kwargs["content"]
            if "trigger_time" in kwargs and kwargs["trigger_time"] is not UNSET_VALUE:
                adapted["trigger_time"] = kwargs["trigger_time"]
            if "priority" in kwargs and kwargs["priority"] is not UNSET_VALUE:
                adapted["priority"] = kwargs["priority"]
            if "status" in kwargs and kwargs["status"] is not UNSET_VALUE:
                adapted["status"] = kwargs["status"]
            if "rrule" in kwargs and kwargs["rrule"] is not UNSET_VALUE:
                adapted["rrule"] = kwargs["rrule"]
        
        return adapted

@tool("update_item")
def update_item(
    identifier: str,                    # 支持 #1, UUID, 或标题
    item_type: str,                     # "event" | "todo" | "reminder"
    
    # 通用字段
    title: str = UNSET_VALUE,
    description: str = UNSET_VALUE,     # event, todo
    content: str = UNSET_VALUE,         # reminder
    importance: str = UNSET_VALUE,      # event, todo
    urgency: str = UNSET_VALUE,         # event, todo
    status: str = UNSET_VALUE,          # todo, reminder
    
    # 时间字段
    start: str = UNSET_VALUE,           # event
    end: str = UNSET_VALUE,             # event
    due_date: str = UNSET_VALUE,        # todo
    trigger_time: str = UNSET_VALUE,    # reminder
    estimated_duration: str = UNSET_VALUE,  # todo
    ddl: str = UNSET_VALUE,             # event
    
    # 分类字段
    group_name: str = UNSET_VALUE,      # event, todo (自动转为 groupID)
    priority: str = UNSET_VALUE,        # reminder
    
    # 重复规则
    rrule: str = UNSET_VALUE,           # event, reminder
    clear_rrule: bool = False,          # 显式清除重复
    
    # Event 特有
    shared_to_groups: list = UNSET_VALUE,
    update_scope: str = "single",       # single/all/future
    
    config: RunnableConfig = None
) -> str:
    """
    智能编辑工具 - 只需传递要修改的字段
    
    关键特性：
    - 未传递的参数不会被修改（保持原值）
    - 传递空字符串表示清空该字段
    - rrule 特殊处理：使用 clear_rrule=True 显式清除重复规则
    - 自动参数适配：根据类型使用对应的参数名
    
    Args:
        identifier: 目标标识符，支持:
            - "#1": 最近查询结果的第1条
            - "550e8400-...": 完整 UUID
            - "明天的会议": 按标题匹配
        
        item_type: 项目类型 ("event"/"todo"/"reminder")
        
        # 通用字段
        title: 新标题（不传=保持原值，""=清空）
        description: 新描述 (event, todo)
        content: 新内容 (reminder)
        importance/urgency: 重要性/紧急性 (event, todo)
        status: 状态 (todo, reminder)
        
        # 时间字段
        start/end: 事件时间 (event)
        due_date: 待办截止日期 (todo)
        trigger_time: 提醒触发时间 (reminder)
        estimated_duration: 预计时长 (todo)
        ddl: 截止时间 (event)
        
        # 分类字段
        group_name: 日程组名称（自动解析为 UUID，仅 event/todo）
        priority: 优先级 (reminder)
        
        # 重复规则
        rrule: 新的重复规则 (event, reminder)
            - 不传: 保持原有规则
            - "FREQ=WEEKLY;COUNT=4": 设置新规则
            - 注意: 不要传空字符串清除规则
        
        clear_rrule: 是否清除重复规则
            - True: 显式清除重复规则，将重复日程转为单次
            - False: 不清除（默认）
        
        # Event 特有
        shared_to_groups: 共享到群组
        update_scope: 编辑范围（仅对重复事件有效）
            - "single": 仅此一次
            - "all": 所有重复
            - "future": 此及将来
    
    Examples:
        - update_item("#1", "event", title="新标题")  # 只改标题
        - update_item("#2", "todo", status="completed")  # 只改状态
        - update_item("会议", "event", start="2025-01-15T14:00")  # 只改时间
        - update_item("#1", "event", clear_rrule=True)  # 取消重复
    """
    user = config.get("configurable", {}).get("user")
    if not user:
        return "Error: User not found."
    
    session = config.get("configurable", {}).get("thread_id")
    if not session:
        return "Error: Session not found."
    
    try:
        # 1. 解析标识符为 UUID
        resolver = IdentifierResolver()
        session_obj = AgentSession.objects.filter(session_id=session).first()
        uuid = resolver.resolve(identifier, item_type, session_obj, user)
        
        if not uuid:
            return f"❌ 无法找到匹配的 {item_type}: {identifier}"
        
        # 2. 处理日程组名称 → UUID
        group_id = UNSET_VALUE
        if group_name is not UNSET_VALUE and group_name:
            from agent_service.tools.event_group_service import EventGroupService
            group_id = EventGroupService.resolve_group_name(user, group_name)
            if not group_id:
                return f"❌ 未找到日程组: {group_name}"
        
        # 3. 处理 clear_rrule 标记
        if clear_rrule:
            rrule = ""  # 设置为空字符串
            # 添加内部标记
            _clear_rrule = True
        else:
            _clear_rrule = False
        
        # 4. 构建参数字典
        params = {
            "title": title,
            "description": description,
            "content": content,
            "importance": importance,
            "urgency": urgency,
            "status": status,
            "start": start,
            "end": end,
            "due_date": due_date,
            "trigger_time": trigger_time,
            "estimated_duration": estimated_duration,
            "ddl": ddl,
            "group_id": group_id,
            "priority": priority,
            "rrule": rrule,
            "shared_to_groups": shared_to_groups,
            "update_scope": update_scope,
            "_clear_rrule": _clear_rrule
        }
        
        # 5. 使用参数适配器转换
        adapted_params = ParamAdapter.adapt_params(item_type, **params)
        
        # 6. 调用对应的服务层方法
        if item_type == "event":
            from core.services.event_service import EventService
            EventService.update_event(user, uuid, **adapted_params)
            return f"✅ 日程已更新"
        elif item_type == "todo":
            from core.services.todo_service import TodoService
            TodoService.update_todo(user, uuid, **adapted_params)
            return f"✅ 待办事项已更新"
        elif item_type == "reminder":
            from core.services.reminder_service import ReminderService
            ReminderService.update_reminder(user, uuid, **adapted_params)
            return f"✅ 提醒已更新"
        else:
            return f"❌ 不支持的类型: {item_type}"
            
    except Exception as e:
        logger.exception(f"更新失败: {e}")
        return f"❌ 更新失败: {str(e)}"
```
```

### 5. 回滚同步机制 ⚠️ 集成现有实现

**现状分析**：
- ✅ 项目已实现完整的回滚机制（`agent_service/views_api.py` 中的 `rollback_to_message`）
- ✅ 已有 TODO 回滚同步（`agent_service/tools/todo_tools.py` 中的 `rollback_todos`）
- ✅ 使用 django-reversion 保存快照，支持精确回滚

**集成方案**：在现有 `rollback_to_message` 函数中添加缓存清理

```python
# agent_service/views_api.py - 修改 rollback_to_message 函数

# 在执行回滚前，清除相关缓存
from agent_service.tools.cache_manager import CacheManager

# ... 现有回滚逻辑 ...

# 新增：清除搜索结果缓存
try:
    CacheManager.clear_session_cache(session_id)
    logger.info(f"已清除会话 {session_id} 的搜索缓存")
except Exception as e:
    logger.warning(f"清除缓存失败（不影响回滚）: {e}")

# ... 继续现有的 TODO 回滚逻辑 ...
todo_rolled_back = rollback_todos(session_id, cp_for_todo)
```

**缓存管理器实现**：

```python
# agent_service/tools/cache_manager.py (新建文件)

from agent_service.models import AgentSession, SearchResultCache
from logger import logger

class CacheManager:
    """缓存管理器 - 处理回滚同步"""
    
    @staticmethod
    def clear_session_cache(session_id: str):
        """清除会话的所有搜索缓存（在回滚时调用）"""
        try:
            session = AgentSession.objects.filter(session_id=session_id).first()
            if session:
                deleted_count = SearchResultCache.objects.filter(session=session).delete()[0]
                logger.info(f"[Cache] 已清除会话 {session_id} 的 {deleted_count} 条搜索缓存")
        except Exception as e:
            logger.error(f"[Cache] 清除缓存失败: {e}")
```

---

## 📊 时间范围解析

```python
# agent_service/tools/time_parser.py

from datetime import datetime, timedelta
from typing import Tuple, Optional

class TimeRangeParser:
    """时间范围解析器"""
    
    PRESETS = {
        'today': lambda: (
            datetime.now().replace(hour=0, minute=0, second=0),
            datetime.now().replace(hour=23, minute=59, second=59)
        ),
        'yesterday': lambda: (
            (datetime.now() - timedelta(days=1)).replace(hour=0, minute=0, second=0),
            (datetime.now() - timedelta(days=1)).replace(hour=23, minute=59, second=59)
        ),
        'tomorrow': lambda: (
            (datetime.now() + timedelta(days=1)).replace(hour=0, minute=0, second=0),
            (datetime.now() + timedelta(days=1)).replace(hour=23, minute=59, second=59)
        ),
        'this_week': lambda: TimeRangeParser._get_week_range(0),
        'next_week': lambda: TimeRangeParser._get_week_range(1),
        'last_week': lambda: TimeRangeParser._get_week_range(-1),
        'this_month': lambda: TimeRangeParser._get_month_range(0),
        'next_month': lambda: TimeRangeParser._get_month_range(1),
        'last_month': lambda: TimeRangeParser._get_month_range(-1),
    }
    
    @classmethod
    def parse(cls, time_range: str) -> Tuple[Optional[datetime], Optional[datetime]]:
        """
        解析时间范围
        
        Args:
            time_range: 时间范围字符串
        
        Returns:
            (start_time, end_time) 元组
        """
        if not time_range:
            return (None, None)
        
        # 检查预置选项
        if time_range.lower() in cls.PRESETS:
            return cls.PRESETS[time_range.lower()]()
        
        # 检查是否是日期范围 "2025-01-15,2025-01-20"
        if ',' in time_range:
            parts = time_range.split(',')
            start = datetime.fromisoformat(parts[0].strip())
            end = datetime.fromisoformat(parts[1].strip())
            return (start, end.replace(hour=23, minute=59, second=59))
        
        # 单个日期
        try:
            date = datetime.fromisoformat(time_range)
            return (
                date.replace(hour=0, minute=0, second=0),
                date.replace(hour=23, minute=59, second=59)
            )
        except:
            return (None, None)
    
    @staticmethod
    def _get_week_range(offset: int) -> Tuple[datetime, datetime]:
        """获取周范围"""
        today = datetime.now()
        # 本周一
        start_of_week = today - timedelta(days=today.weekday())
        # 加上偏移
        start_of_week += timedelta(weeks=offset)
        end_of_week = start_of_week + timedelta(days=6)
        
        return (
            start_of_week.replace(hour=0, minute=0, second=0),
            end_of_week.replace(hour=23, minute=59, second=59)
        )
    
    @staticmethod
    def _get_month_range(offset: int) -> Tuple[datetime, datetime]:
        """获取月范围"""
        today = datetime.now()
        # 计算目标月份
        month = today.month + offset
        year = today.year
        while month > 12:
            month -= 12
            year += 1
        while month < 1:
            month += 12
            year -= 1
        
        # 月初
        start = datetime(year, month, 1)
        # 月末
        if month == 12:
            end = datetime(year + 1, 1, 1) - timedelta(seconds=1)
        else:
            end = datetime(year, month + 1, 1) - timedelta(seconds=1)
        
        return (start, end)
```

---

## 🔧 实现步骤

### Phase 1: 基础设施 (优先级: 高)

1. **创建数据模型**
   - [ ] `SearchResultCache` 模型
   - [ ] `EventGroupCache` 模型
   - [ ] 数据库迁移

2. **实现基础工具类**
   - [ ] `TimeRangeParser` 时间解析器
   - [ ] `IdentifierResolver` 标识符解析器
   - [ ] `CacheManager` 缓存管理器

### Phase 2: 统一查询工具 (优先级: 高)

3. **实现 search_items 工具**
   - [ ] 合并 get_events, get_todos, get_reminders 逻辑
   - [ ] 实现类型筛选
   - [ ] 实现时间范围筛选
   - [ ] 实现日程组筛选
   - [ ] 实现文本搜索
   - [ ] 自动建立编号映射并缓存

4. **实现日程组缓存**
   - [ ] 自动获取并缓存日程组
   - [ ] 名称→UUID 双向映射
   - [ ] 缓存更新机制

### Phase 3: 智能编辑工具 (优先级: 高)

5. **实现 update_item 工具**
   - [ ] UNSET 哨兵值机制
   - [ ] 标识符解析
   - [ ] 增量更新逻辑
   - [ ] rrule 特殊处理 (clear_rrule 参数)
   - [ ] 日程组名称自动解析

6. **实现 delete_item 工具**
   - [ ] 标识符解析
   - [ ] 删除范围选项
   - [ ] 确认机制（可选）

### Phase 4: 回滚集成 (优先级: 中)

7. **集成回滚机制**
   - [ ] 在回滚时清除相关缓存
   - [ ] 与 AgentTransaction 集成
   - [ ] 测试回滚场景

### Phase 5: 兼容与迁移 (优先级: 中)

8. **保留旧工具兼容**
   - [ ] 旧工具标记为 deprecated
   - [ ] 内部调用新工具
   - [ ] 逐步迁移

---

## 📝 工具函数签名总结

### 新增工具

| 工具名 | 功能 | 关键参数 |
|--------|------|----------|
| `search_items` | 统一搜索 | item_type, group_name, time_range, title_contains |
| `update_item` | 智能编辑 | identifier, item_type, 各字段(UNSET机制), clear_rrule |
| `delete_item` | 智能删除 | identifier, item_type, delete_scope |
| `get_event_groups` | 获取日程组 | (无参数，自动缓存) |

### 废弃工具 (保留兼容)

| 工具名 | 替代方案 |
|--------|----------|
| `get_events` | `search_items(item_type="event")` |
| `get_todos` | `search_items(item_type="todo")` |
| `get_reminders` | `search_items(item_type="reminder")` |
| `update_event` | `update_item(item_type="event")` |
| `update_todo` | `update_item(item_type="todo")` |
| `delete_event` | `delete_item(item_type="event")` |
| `delete_todo` | `delete_item(item_type="todo")` |
| `delete_reminder` | `delete_item(item_type="reminder")` |

---

## 🔍 RRule 空值处理方案

### 问题分析

当前 `rrule=""` 在服务层可能被误判为"清空重复规则"：

```python
# core/services/event_service.py
if rrule is not None:  # 问题：rrule="" 也会进入这里
    target_event['rrule'] = rrule
```

### 解决方案

1. **工具层**: 使用 `clear_rrule=True` 显式参数
2. **服务层**: 区分 `None`（不修改）、`""`（清空）、`"FREQ=..."` (设置)

```python
# 工具层
@tool("update_item")
def update_item(..., rrule: str = UNSET_VALUE, clear_rrule: bool = False, ...):
    # 构建更新参数
    updates = {}
    
    if clear_rrule:
        # 显式清除重复规则
        updates['rrule'] = ""
        updates['_clear_rrule'] = True  # 标记
    elif rrule is not UNSET_VALUE:
        # 设置新规则
        updates['rrule'] = rrule
    # else: 不传递 rrule，保持原值

# 服务层修改
def update_event(..., rrule=None, _clear_rrule=False, ...):
    if _clear_rrule:
        # 明确要清除
        target_event['rrule'] = ''
        target_event['is_recurring'] = False
        # ... 清除其他重复相关字段
    elif rrule is not None and rrule != '':
        # 设置新规则
        target_event['rrule'] = rrule
    # else: rrule 为 None 或空字符串但非显式清除，保持原值
```

---

## 📋 测试用例

### 1. 统一搜索

```python
# 测试用例 1: 搜索今天的日程
search_items(item_type="event", time_range="today")
# 期望: 返回今天的所有日程，带编号

# 测试用例 2: 搜索工作组的待办
search_items(item_type="todo", group_name="工作")
# 期望: 返回工作组下的所有待办

# 测试用例 3: 全类型关键词搜索
search_items(title_contains="会议")
# 期望: 返回标题包含"会议"的所有事项
```

### 2. 编号引用

```python
# 先搜索
search_items(item_type="event", time_range="today")
# 返回: #1 会议, #2 午餐, #3 运动

# 使用编号编辑
update_item("#1", "event", title="重要会议")
# 期望: 成功修改第一条日程的标题

# 使用编号删除
delete_item("#2", "event")
# 期望: 成功删除第二条日程
```

### 3. 增量编辑

```python
# 只修改标题
update_item("#1", "event", title="新标题")
# 期望: 只有标题被修改，其他字段保持不变

# 清除重复规则
update_item("#1", "event", clear_rrule=True)
# 期望: 重复规则被清除，日程变为单次

# 修改日程组
update_item("#1", "event", group_name="个人")
# 期望: 日程组改为"个人"组（自动解析UUID）
```

---

## ⚠️ 注意事项

1. **缓存一致性**: 任何修改/删除操作后，需要使相关缓存失效
2. **并发安全**: 多个请求同时修改缓存时的冲突处理
3. **回滚完整性**: 回滚时必须同步清除缓存，避免编号指向错误的对象
4. **性能考虑**: 日程组缓存应该有 TTL，避免频繁查询数据库
5. **向后兼容**: 旧工具在过渡期内保持可用

---

## 📅 实施计划

| 阶段 | 内容 | 预计时间 |
|------|------|----------|
| Phase 1 | 数据模型 + 基础工具类 | 1 天 |
| Phase 2 | 统一查询工具 | 1 天 |
| Phase 3 | 智能编辑工具 | 1 天 |
| Phase 4 | 回滚集成 | 0.5 天 |
| Phase 5 | 测试 + 兼容迁移 | 0.5 天 |

**总计: 约 4 天**

---

## 📁 文件结构

```
agent_service/
├── tools/
│   ├── __init__.py                    # 工具导出
│   ├── planner_tools.py               # 原有工具（保留兼容）
│   ├── unified_planner_tools.py       # 🆕 新版统一工具
│   ├── identifier_resolver.py         # 🆕 标识符解析器
│   ├── time_parser.py                 # 🆕 时间范围解析器
│   ├── cache_manager.py               # 🆕 缓存管理器
│   ├── event_group_service.py         # 🆕 日程组服务
│   ├── memory_tools.py
│   ├── memory_tools_v2.py
│   └── todo_tools.py
├── models.py                          # 📝 新增模型
├── agent_graph.py                     # 📝 工具注册更新
└── ...
```

---

## 🔌 agent_graph.py 集成

```python
# agent_service/agent_graph.py

# 导入新的统一工具
from agent_service.tools.unified_planner_tools import (
    search_items,
    create_item,
    update_item, 
    delete_item,
    get_event_groups,
    UNIFIED_PLANNER_TOOLS
)

# 更新工具注册表
PLANNER_TOOLS_V2 = {
    "search_items": search_items,
    "create_item": create_item,
    "update_item": update_item,
    "delete_item": delete_item,
    "get_event_groups": get_event_groups,
}

# 合并到总工具集（保留旧工具兼容）
ALL_TOOLS = {
    **PLANNER_TOOLS,      # 旧版（deprecated，保留兼容）
    **PLANNER_TOOLS_V2,   # 新版（推荐）
    **MEMORY_TOOLS, 
    **TODO_TOOLS_MAP, 
    **MCP_TOOLS
}

# 更新工具分类
TOOL_CATEGORIES = {
    "planner": {
        "display_name": "日程管理",
        "description": "管理日程、待办、提醒",
        "tools": list(PLANNER_TOOLS_V2.keys()),  # 使用新工具
        "legacy_tools": list(PLANNER_TOOLS.keys())  # 旧工具标记
    },
    # ...
}
```

---

## 🎨 创建工具设计

### create_item 工具

```python
@tool("create_item")
@agent_transaction(action_type="create_item")
def create_item(
    item_type: str,                     # "event" | "todo" | "reminder"
    title: str,                         # 标题（必填）
    
    # 时间相关（根据类型不同）
    start: str = "",                    # 开始时间 (event)
    end: str = "",                      # 结束时间 (event)
    due_date: str = "",                 # 截止日期 (todo)
    trigger_time: str = "",             # 触发时间 (reminder)
    
    # 通用字段
    description: str = "",              # 描述
    content: str = "",                  # 内容 (reminder)
    
    # 分类相关
    group_name: str = "",               # 日程组名称（自动解析为UUID）
    importance: str = "",               # 重要性
    urgency: str = "",                  # 紧急性
    
    # 重复规则
    rrule: str = "",                    # RRule 规则
    repeat: str = "",                   # 🆕 简化重复描述（自动转为 rrule）
    
    config: RunnableConfig = None
) -> str:
    """
    统一创建工具 - 创建日程、待办事项或提醒
    
    Args:
        item_type: 创建类型
            - "event": 日程
            - "todo": 待办事项  
            - "reminder": 提醒
        
        title: 标题（必填）
        
        start/end: 事件的开始和结束时间（仅 event 需要）
            格式: "YYYY-MM-DDTHH:MM" 或自然语言如 "明天下午3点"
        
        due_date: 待办截止日期（仅 todo）
        trigger_time: 提醒触发时间（仅 reminder）
        
        description: 详细描述
        content: 提醒内容（仅 reminder）
        
        group_name: 日程组名称
            - 示例: "工作", "个人"
            - 系统会自动查找对应的 UUID
            - 如果不存在，可以选择自动创建（需确认）
        
        importance: 重要性 ("important" / "not-important")
        urgency: 紧急性 ("urgent" / "not-urgent")
        
        rrule: 标准 RRule 规则
            示例: "FREQ=WEEKLY;BYDAY=MO,WE,FR"
        
        repeat: 简化重复描述（可选，会自动转为 rrule）
            - "每天": FREQ=DAILY
            - "每周": FREQ=WEEKLY
            - "每周一三五": FREQ=WEEKLY;BYDAY=MO,WE,FR
            - "每月": FREQ=MONTHLY
            - "工作日": FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR
    
    Examples:
        - create_item("event", "团队会议", start="明天上午10点", end="明天上午11点", group_name="工作")
        - create_item("todo", "完成报告", due_date="下周五", importance="important")
        - create_item("reminder", "吃药提醒", trigger_time="每天早上8点", repeat="每天")
    """
```

---

## 🔄 简化重复规则解析

```python
# agent_service/tools/repeat_parser.py

class RepeatParser:
    """简化重复描述 → RRule 转换器"""
    
    SIMPLE_PATTERNS = {
        "每天": "FREQ=DAILY",
        "每周": "FREQ=WEEKLY",
        "每月": "FREQ=MONTHLY",
        "每年": "FREQ=YEARLY",
        "工作日": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
        "周末": "FREQ=WEEKLY;BYDAY=SA,SU",
    }
    
    WEEKDAY_MAP = {
        "周一": "MO", "周二": "TU", "周三": "WE",
        "周四": "TH", "周五": "FR", "周六": "SA", "周日": "SU",
        "星期一": "MO", "星期二": "TU", "星期三": "WE",
        "星期四": "TH", "星期五": "FR", "星期六": "SA", "星期日": "SU",
    }
    
    @classmethod
    def parse(cls, repeat_str: str) -> str:
        """
        将简化描述转为 RRule
        
        Examples:
            - "每天" → "FREQ=DAILY"
            - "每周一三五" → "FREQ=WEEKLY;BYDAY=MO,WE,FR"
            - "每月15号" → "FREQ=MONTHLY;BYMONTHDAY=15"
            - "每周，共4次" → "FREQ=WEEKLY;COUNT=4"
        """
        if not repeat_str:
            return ""
        
        # 1. 检查简单模式
        if repeat_str in cls.SIMPLE_PATTERNS:
            return cls.SIMPLE_PATTERNS[repeat_str]
        
        # 2. 解析"每周X"模式
        if repeat_str.startswith("每周"):
            days = repeat_str[2:]  # 去掉"每周"
            byday = []
            for day_name, day_code in cls.WEEKDAY_MAP.items():
                if day_name in days:
                    byday.append(day_code)
            if byday:
                return f"FREQ=WEEKLY;BYDAY={','.join(byday)}"
        
        # 3. 解析"每月X号"模式
        import re
        month_day_match = re.search(r'每月(\d+)号', repeat_str)
        if month_day_match:
            day = month_day_match.group(1)
            return f"FREQ=MONTHLY;BYMONTHDAY={day}"
        
        # 4. 解析次数限制
        count_match = re.search(r'共(\d+)次', repeat_str)
        base_rrule = ""
        for pattern, rrule in cls.SIMPLE_PATTERNS.items():
            if pattern in repeat_str:
                base_rrule = rrule
                break
        
        if count_match and base_rrule:
            count = count_match.group(1)
            return f"{base_rrule};COUNT={count}"
        
        # 5. 无法解析，返回原字符串（让服务层处理或报错）
        return repeat_str
```

---

## 🧪 完整测试场景

### 场景 1: 日程查询与编辑

```
用户: 看看我今天有什么日程

Agent 调用: search_items(item_type="event", time_range="today")

返回:
📅 今天的日程 (3 项):
#1 [09:00-10:00] 晨会 (工作组)
#2 [14:00-15:00] 产品评审 (工作组)
#3 [18:00-19:00] 健身 (个人组)

---

用户: 把第2个改到下午3点

Agent 调用: update_item("#2", "event", start="2025-01-15T15:00", end="2025-01-15T16:00")

返回:
✅ 已更新日程 "产品评审"
- 时间: 14:00-15:00 → 15:00-16:00
```

### 场景 2: 跨类型搜索

```
用户: 搜索所有包含"报告"的事项

Agent 调用: search_items(title_contains="报告")

返回:
🔍 搜索结果 (共 4 项):

📅 日程:
#1 [01-20 14:00] 年度报告会议

📋 待办:
#2 完成季度报告 (截止: 01-25)
#3 审核项目报告 (截止: 01-22)

⏰ 提醒:
#4 [01-19 09:00] 提交报告提醒
```

### 场景 3: 使用日程组名称创建

```
用户: 帮我在"学习"组创建一个日程，明天下午学习Python，2小时

Agent 调用: 
create_item(
    item_type="event",
    title="学习Python",
    start="2025-01-16T14:00",
    end="2025-01-16T16:00",
    group_name="学习"
)

返回:
✅ 日程创建成功
- 标题: 学习Python
- 时间: 2025-01-16 14:00 - 16:00
- 日程组: 学习
```

### 场景 4: 取消重复规则

```
用户: 把#1这个日程的重复取消掉

Agent 调用: update_item("#1", "event", clear_rrule=True, edit_scope="all")

返回:
✅ 已取消重复规则
- 日程 "晨会" 已从每日重复改为单次日程
- 已删除未来 15 个重复实例
```

---

## ⚡ 性能优化

1. **懒加载日程组**: 只在需要时加载日程组映射
2. **缓存 TTL**: 日程组缓存 5 分钟过期
3. **批量操作**: 编辑多条时使用事务
4. **索引优化**: SearchResultCache 添加复合索引

```python
class SearchResultCache(models.Model):
    # ...
    class Meta:
        unique_together = ['session', 'result_type']
        indexes = [
            models.Index(fields=['session', 'updated_at']),
            models.Index(fields=['checkpoint_id']),
        ]
```

---

## 🔧 详细实施步骤

### Phase 1: 基础设施 (预计 1 天)

**1.1 创建数据模型** 
- [ ] 在 `agent_service/models.py` 添加 `SearchResultCache` 模型
- [ ] 在 `agent_service/models.py` 添加 `EventGroupCache` 模型  
- [ ] 运行 `python manage.py makemigrations`
- [ ] 运行 `python manage.py migrate`

**1.2 实现基础工具类**
- [ ] `agent_service/tools/time_parser.py` - TimeRangeParser
- [ ] `agent_service/tools/identifier_resolver.py` - IdentifierResolver
- [ ] `agent_service/tools/cache_manager.py` - CacheManager
- [ ] `agent_service/tools/param_adapter.py` - ParamAdapter (含 UNSET)
- [ ] `agent_service/tools/repeat_parser.py` - RepeatParser
- [ ] `agent_service/tools/event_group_service.py` - EventGroupService

### Phase 2: 服务层修改 (预计 0.5 天)

**2.1 修改 Event Service**
```python
# core/services/event_service.py

@staticmethod
def update_event(..., _clear_rrule=False, ...):
    # 添加 _clear_rrule 参数处理逻辑
```

**2.2 修改 Reminder Service**
```python
# core/services/reminder_service.py

@staticmethod
def update_reminder(..., _clear_rrule=False, ...):
    # 添加 _clear_rrule 参数处理逻辑
```

### Phase 3: 统一工具实现 (预计 1.5 天)

**3.1 实现 search_items**
- [ ] 创建 `agent_service/tools/unified_planner_tools.py`
- [ ] 实现 `search_items` 函数
  - 类型筛选 (event/todo/reminder/all)
  - 时间范围筛选（使用 TimeRangeParser）
  - 日程组筛选（使用 EventGroupService）
  - 文本搜索（标题、描述）
  - 编号生成与缓存（使用 SearchResultCache）
  - 格式化输出

**3.2 实现 create_item**
- [ ] 参数适配（使用 ParamAdapter）
- [ ] 日程组名称解析
- [ ] 简化重复规则解析（使用 RepeatParser）
- [ ] 调用对应的 Service 层
- [ ] 添加 @agent_transaction 装饰器

**3.3 实现 update_item**
- [ ] 标识符解析（使用 IdentifierResolver）
- [ ] UNSET 哨兵值处理
- [ ] 参数适配（使用 ParamAdapter）
- [ ] clear_rrule 特殊处理
- [ ] 日程组名称解析
- [ ] 调用对应的 Service 层
- [ ] 添加 @agent_transaction 装饰器

**3.4 实现 delete_item**
- [ ] 标识符解析
- [ ] 删除范围选项 (single/all/future)
- [ ] 调用对应的 Service 层
- [ ] 添加 @agent_transaction 装饰器

**3.5 实现 get_event_groups**
- [ ] 获取用户日程组列表
- [ ] 缓存名称映射
- [ ] 格式化输出

### Phase 4: 回滚集成 (预计 0.5 天)

**4.1 修改回滚函数**
```python
# agent_service/views_api.py

@api_view(['POST'])
def rollback_to_message(request):
    # ... 现有代码 ...
    
    # 🆕 添加缓存清理
    from agent_service.tools.cache_manager import CacheManager
    try:
        CacheManager.clear_session_cache(session_id)
        logger.info(f"已清除会话 {session_id} 的搜索缓存")
    except Exception as e:
        logger.warning(f"清除缓存失败（不影响回滚）: {e}")
    
    # ... 现有的 TODO 回滚逻辑 ...
```

### Phase 5: 工具注册 (预计 0.5 天)

**5.1 更新 agent_graph.py**
```python
# agent_service/agent_graph.py

# 导入新工具
from agent_service.tools.unified_planner_tools import (
    search_items, create_item, update_item, delete_item, get_event_groups
)

# 新工具字典
PLANNER_TOOLS_V2 = {
    "search_items": search_items,
    "create_item": create_item,
    "update_item": update_item,
    "delete_item": delete_item,
    "get_event_groups": get_event_groups,
}

# 合并到总工具集
ALL_TOOLS = {
    **PLANNER_TOOLS,      # 旧版（保留兼容）
    **PLANNER_TOOLS_V2,   # 新版
    **MEMORY_TOOLS,
    **TODO_TOOLS_MAP,
    **MCP_TOOLS
}

# 更新工具分类
TOOL_CATEGORIES["planner"]["tools"] = list(PLANNER_TOOLS_V2.keys())
TOOL_CATEGORIES["planner"]["legacy_tools"] = list(PLANNER_TOOLS.keys())
```

### Phase 6: 测试与优化 (预计 1 天)

**6.1 单元测试**
- [ ] 时间解析器测试
- [ ] 标识符解析器测试
- [ ] 参数适配器测试
- [ ] 重复规则解析器测试

**6.2 集成测试**
- [ ] 统一搜索功能测试
- [ ] 编号引用测试
- [ ] 增量编辑测试
- [ ] 日程组名称映射测试
- [ ] 回滚同步测试

**6.3 性能优化**
- [ ] 数据库索引验证
- [ ] 缓存 TTL 调优
- [ ] 大数据量测试

---

## ✅ 验收标准

1. **功能完整性**
   - ✅ 支持统一搜索（类型、时间、日程组、文本）
   - ✅ 支持编号引用 (#1, #2...)
   - ✅ 支持日程组名称自动解析
   - ✅ 支持增量编辑（只传修改字段）
   - ✅ 支持 clear_rrule 显式清除重复
   - ✅ 回滚时自动清除缓存

2. **性能要求**
   - ✅ 搜索响应时间 < 500ms
   - ✅ 编辑响应时间 < 300ms
   - ✅ 缓存命中率 > 80%

3. **兼容性**
   - ✅ 旧工具继续可用
   - ✅ 现有 API 不受影响
   - ✅ 数据库迁移无损

---

## 📋 两个关键问题的解决方案总结

### 问题 1: 回滚同步机制

**结论**: 集成现有实现，不重写

- ✅ 现有的回滚机制已完善（`rollback_to_message`）
- ✅ 已支持 TODO 回滚同步（`rollback_todos`）
- 🆕 只需在现有回滚函数中添加 **搜索缓存清理** 逻辑
- 实现方式：调用 `CacheManager.clear_session_cache(session_id)`

### 问题 2: 参数差异兼容

**结论**: 使用参数适配器 + UNSET 哨兵值

| 类型 | 独有参数 | 处理方式 |
|------|----------|----------|
| Event | start, end, ddl, shared_to_groups | ParamAdapter 自动过滤 |
| Todo | due_date, estimated_duration, status | ParamAdapter 自动过滤 |
| Reminder | content, trigger_time, priority | ParamAdapter 自动过滤 |

**核心机制**：
1. 工具层接受所有可能的参数（使用 UNSET_VALUE 作默认值）
2. ParamAdapter 根据 item_type 过滤出该类型支持的参数
3. 只有非 UNSET_VALUE 的参数才会被传递给服务层
4. 服务层按现有逻辑处理（`if param is not None: ...`）

---

**总预计时间**: 约 5 天

**当前状态**: 方案已确认，等待实施
