# RRule 编辑操作指南

本文档描述日程（Events）和提醒（Reminders）中重复规则（RRule）相关的编辑操作。

## 1. 概述

对于重复项目（日程/提醒），编辑操作需要指定**编辑范围**（edit_scope），决定修改影响哪些实例。

### 1.1 关键概念

| 概念 | 说明 |
|------|------|
| `series_id` | 系列ID，重复项目系列的唯一标识。同一系列的所有实例共享此ID |
| `event_id` / `reminder_id` | 单个实例的ID |
| `rrule` | 重复规则字符串，如 `FREQ=DAILY;COUNT=10` |
| `edit_scope` | 编辑范围，决定操作影响哪些实例 |
| `from_time` | 起始时间，用于 `from_time` 范围 |

### 1.2 编辑范围（edit_scope）

| 范围 | 说明 | 适用场景 |
|------|------|---------|
| `single` | 仅当前实例 | 将单个实例从系列独立出来，单独修改 |
| `all` | 整个系列 | 修改系列中所有实例（不改变时间） |
| `future` / `from_this` | 此实例及之后 | 修改指定实例及之后的所有实例 |
| `from_time` | 指定时间及之后 | 从某时间点开始修改（需配合 `from_time` 参数） |

---

## 2. 日程（Events）操作

### 2.1 API 端点

- **批量编辑**: `POST /api/events/bulk-edit/`
- **删除**: `POST /get_calendar/delete_event/`

### 2.2 编辑操作参数

#### 2.2.1 编辑整个系列 (edit_scope="all")

```json
{
    "event_id": "实例ID",
    "series_id": "系列ID",
    "operation": "edit",
    "edit_scope": "all",
    "title": "新标题",
    "description": "新描述",
    "importance": "important",
    "urgency": "urgent"
}
```

**说明**: 
- `event_id` 可以是系列中任意一个实例的ID
- 修改会应用到系列中所有实例
- 不会改变各实例的时间

#### 2.2.2 编辑单个实例 (edit_scope="single")

```json
{
    "event_id": "实例ID",
    "series_id": "系列ID",
    "operation": "edit",
    "edit_scope": "single",
    "title": "独立修改的标题",
    "description": "此实例已独立"
}
```

**说明**:
- 将指定实例从系列中分离，成为独立日程
- 该实例的 `series_id` 被清除
- 原系列其他实例会添加 `EXDATE` 参数，排除该日期
- 修改后该实例不再随系列变化

#### 2.2.3 编辑此实例及之后 (edit_scope="future")

```json
{
    "event_id": "实例ID",
    "series_id": "系列ID",
    "operation": "edit",
    "edit_scope": "future",
    "title": "更新的标题",
    "rrule": "FREQ=WEEKLY;INTERVAL=1;COUNT=5"
}
```

**说明**:
- 修改指定实例及其之后的所有实例
- 如果不提供 `rrule`：仅修改属性，实例仍在原系列
- 如果提供 `rrule`：
  - 原系列在此处截断（添加 UNTIL）
  - 从此实例开始创建新系列，使用新规则

#### 2.2.4 从指定时间开始编辑 (edit_scope="from_time")

```json
{
    "event_id": "实例ID",
    "series_id": "系列ID",
    "operation": "edit",
    "edit_scope": "from_time",
    "from_time": "2025-01-15T10:00:00",
    "title": "更新的标题",
    "rrule": "FREQ=WEEKLY;INTERVAL=1;COUNT=5"
}
```

**说明**:
- 从 `from_time` 指定的时间点开始查找实例
- 以找到的第一个实例为起点，应用修改

### 2.3 删除操作参数

#### 2.3.1 删除单个实例

```json
{
    "eventId": "实例ID",
    "delete_scope": "single"
}
```

#### 2.3.2 删除整个系列

```json
{
    "eventId": "实例ID",
    "series_id": "系列ID",
    "delete_scope": "all"
}
```

#### 2.3.3 删除此实例及之后

```json
{
    "eventId": "实例ID",
    "series_id": "系列ID",
    "delete_scope": "future"
}
```

---

## 3. 提醒（Reminders）操作

### 3.1 API 端点

- **批量编辑/删除**: `POST /api/reminders/bulk-edit/`

### 3.2 编辑操作参数

#### 3.2.1 编辑整个系列 (edit_scope="all")

```json
{
    "operation": "edit",
    "reminder_id": "实例ID",
    "series_id": "系列ID",
    "edit_scope": "all",
    "title": "新标题",
    "content": "新内容",
    "priority": "high"
}
```

#### 3.2.2 编辑单个实例 (edit_scope="single")

```json
{
    "operation": "edit",
    "reminder_id": "实例ID",
    "series_id": "系列ID",
    "edit_scope": "single",
    "title": "独立的标题",
    "content": "此实例已独立",
    "priority": "low",
    "rrule": ""
}
```

**说明**: 独立实例需要传 `rrule: ""` 清除重复规则

#### 3.2.3 编辑此实例及之后 (edit_scope="from_this")

```json
{
    "operation": "edit",
    "reminder_id": "实例ID",
    "series_id": "系列ID",
    "edit_scope": "from_this",
    "title": "更新的标题",
    "content": "此实例及之后已更新",
    "priority": "low"
}
```

#### 3.2.4 修改重复规则 (edit_scope="from_time")

```json
{
    "operation": "edit",
    "reminder_id": "实例ID",
    "series_id": "系列ID",
    "edit_scope": "from_time",
    "from_time": "2025-01-15T10:00:00",
    "rrule": "FREQ=WEEKLY;BYDAY=MO,WE,FR",
    "title": "新规则的标题"
}
```

**说明**:
- 从 `from_time` 开始使用新的重复规则
- 旧系列在此处截断
- 创建新系列使用新规则

### 3.3 删除操作参数

#### 3.3.1 删除整个系列

```json
{
    "operation": "delete",
    "reminder_id": "实例ID",
    "series_id": "系列ID",
    "edit_scope": "all"
}
```

#### 3.3.2 删除此实例及之后

```json
{
    "operation": "delete",
    "reminder_id": "实例ID",
    "series_id": "系列ID",
    "edit_scope": "from_this"
}
```

---

## 4. Agent 工具参数映射

### 4.1 update_item 工具参数

```python
update_item(
    identifier: str,                    # 必需：项目标识（#序号/UUID/标题）
    item_type: Optional[str] = None,    # 可选：显式指定类型
    
    # 编辑范围（对重复项目生效）
    edit_scope: str = "single",         # "single" | "all" | "future" | "from_time"
    from_time: Optional[str] = None,    # edit_scope="from_time" 时必需
    
    # 通用参数
    title: Optional[str] = None,
    description: Optional[str] = None,
    repeat: Optional[str] = None,       # 新重复规则（简化格式）
    clear_repeat: bool = False,         # 清除重复规则
    
    # 日程专用
    start: Optional[str] = None,
    end: Optional[str] = None,
    event_group: Optional[str] = None,
    importance: Optional[str] = None,
    urgency: Optional[str] = None,
    shared_to_groups: Optional[List[str]] = None,
    ddl: Optional[str] = None,
    
    # 待办专用
    due_date: Optional[str] = None,
    priority: Optional[str] = None,
    status: Optional[str] = None,
    
    # 提醒专用
    trigger_time: Optional[str] = None,
    content: Optional[str] = None,
    priority: Optional[str] = None,
)
```

#### edit_scope 说明

| 值 | 说明 | 使用场景 |
|----|------|---------|
| `single` | 仅当前实例 | 修改单个日程，如果是重复日程则从系列独立出来 |
| `all` | 整个系列 | 批量修改所有重复实例（不改变各实例时间） |
| `future` | 此实例及之后 | 修改选中的及后续所有实例，可配合新 repeat 创建新系列 |
| `from_time` | 从指定时间开始 | 需配合 from_time 参数，从该时间点开始修改 |

### 4.2 delete_item 工具参数

```python
delete_item(
    identifier: str,                    # 必需：项目标识
    item_type: Optional[str] = None,    # 可选：显式指定类型
    delete_scope: str = "single",       # "single" | "all" | "future"
)
```

#### delete_scope 说明

| 值 | 说明 |
|----|------|
| `single` | 仅删除当前实例 |
| `all` | 删除整个重复系列 |
| `future` | 删除此实例及之后的所有实例 |

### 4.3 使用示例

```python
# 1. 修改单个日程标题
update_item(identifier="#1", title="新标题")

# 2. 修改整个重复系列的标题
update_item(identifier="#1", edit_scope="all", title="系列新标题")

# 3. 从某个实例开始修改重复规则
update_item(
    identifier="#1", 
    edit_scope="future", 
    title="新规则日程",
    repeat="每周一三五;COUNT=10"
)

# 4. 删除整个重复系列
delete_item(identifier="#1", delete_scope="all")

# 5. 删除此实例及之后
delete_item(identifier="#1", delete_scope="future")
```

### 4.4 edit_scope 值对照（内部转换）

| Agent 参数值 | Events API | Reminders API |
|--------------|------------|---------------|
| `single` | single | single |
| `all` | all | all |
| `future` | future | from_this |
| `from_time` | from_time | from_time |

---

## 5. 实现注意事项

### 5.1 Events 批量编辑

Events 使用 `POST /api/events/bulk-edit/` 端点，需要：
- `event_id`: 目标实例ID
- `series_id`: 系列ID（可从实例获取）
- `operation`: "edit" 或 "delete"
- `edit_scope`: 编辑范围

### 5.2 Reminders 批量编辑

Reminders 使用 `POST /api/reminders/bulk-edit/` 端点，参数类似但字段名不同：
- `reminder_id` 而不是 `event_id`

### 5.3 获取 series_id

对于重复项目，可以从实例中获取 `series_id`：
```python
event = EventService.get_event_by_id(user, event_id)
series_id = event.get('series_id')
```

### 5.4 非重复项目

对于非重复项目，`edit_scope` 参数会被忽略，直接进行简单编辑。

---

## 6. 测试场景

### 6.1 创建并编辑重复日程

```
用户: 创建一个每天早上9点的晨会，重复10次
Agent: create_item(item_type="event", title="晨会", start="09:00", repeat="每天;COUNT=10")

用户: 把晨会改成每2天一次
Agent: update_item(identifier="晨会", edit_scope="all", repeat="每2天;COUNT=10")

用户: 只修改下周一那次晨会的标题为"重要晨会"
Agent: update_item(identifier="晨会", edit_scope="single", title="重要晨会")

用户: 从下周开始，晨会改成每周一三五
Agent: update_item(identifier="晨会", edit_scope="future", repeat="每周一三五")

用户: 删除所有晨会
Agent: delete_item(identifier="晨会", delete_scope="all")
```

### 6.2 创建并编辑重复提醒

```
用户: 每天下午6点提醒我下班打卡，持续一个月
Agent: create_item(item_type="reminder", title="下班打卡", trigger_time="18:00", repeat="每天;UNTIL=一个月后")

用户: 把提醒改成每周工作日（周一到周五）
Agent: update_item(identifier="下班打卡", edit_scope="all", repeat="每周一二三四五")
```

### 6.3 边界测试

| 测试项 | 预期行为 |
|--------|---------|
| 对非重复项目使用 edit_scope="all" | 应忽略 edit_scope，正常编辑 |
| edit_scope="from_time" 但不提供 from_time | 应报错或回退到 "single" |
| 修改 repeat 但 edit_scope="single" | 应创建独立日程，使用新 repeat |
| clear_repeat=True 且 edit_scope="all" | 应删除整个系列的重复规则 |

---

## 7. 常见问题

### Q1: 为什么 edit_scope="future" 没有生效？

**检查项**:
1. 确认项目有 `series_id`（是重复项目）
2. 检查是否正确传递了 `series_id` 给 API
3. 确认 API 返回成功

### Q2: 如何判断一个项目是否为重复项目？

检查项目是否有 `rrule` 字段：
```python
is_recurring = bool(item.get('rrule'))
```

### Q3: 编辑后新系列的 series_id 是什么？

使用 `edit_scope="future"` 且提供新 `rrule` 时，会创建新系列。新系列的 `series_id` 是新生成的 UUID。

### Q4: repeat 参数支持哪些格式？

参见 `RepeatParser` 支持的格式：
- 基础: `每天`, `每周`, `每月`, `每年`
- 带间隔: `每2天`, `每隔3周`
- 带星期: `每周一三五`, `每2周一三五`
- 带限制: `每天;COUNT=10`, `每周;UNTIL=2025-12-31`
- 混合: `每2天;COUNT=5`
