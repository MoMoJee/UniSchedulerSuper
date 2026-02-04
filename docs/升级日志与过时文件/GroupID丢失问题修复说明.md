# GroupID 丢失问题修复说明

## 问题描述

编辑事件时，`groupID` 字段从有值变成了空字符串，导致日程组信息丢失。

### 问题表现
```json
// 编辑前
{
  "id": "db94fa1e-b079-46a8-91af-e97d2fe6f5b1",
  "title": "测试日日日",
  "groupID": "eee89465-83a0-4886-b9e6-d17da6fd62fa",  // ✅ 有值
  ...
}

// 编辑后（只改了标题）
{
  "id": "db94fa1e-b079-46a8-91af-e97d2fe6f5b1",
  "title": "测试日日日",
  "groupID": "",  // ❌ 变成空字符串
  ...
}
```

## 根本原因

### 问题代码（修复前）

在 `bulk_edit_events_impl` 函数中：

```python
# 1. 构建 updates 字典
updates = {
    'title': data.get('title'),
    'description': data.get('description'),
    'importance': data.get('importance'),
    'urgency': data.get('urgency'),
    'start': data.get('start'),
    'end': data.get('end'),
    'rrule': data.get('rrule'),
    'groupID': data.get('groupID'),  # 如果前端没传，这里是 ""
    'ddl': data.get('ddl'),
}

# 2. 只过滤 None，但保留空字符串
updates = {k: v for k, v in updates.items() if v is not None}
# 结果: groupID: "" 被保留 ❌

# 3. 直接应用 updates
event.update(updates)  # 空字符串覆盖了原有的 groupID ❌
```

### 问题链

1. **前端**: 编辑模态框没有修改 groupID 时，传递 `groupID: ""`
2. **后端**: `data.get('groupID')` 返回 `""`（空字符串）
3. **过滤**: 只过滤了 `None`，空字符串 `""` 通过过滤
4. **应用**: `event.update(updates)` 用空字符串覆盖了原有的 groupID

## 修复方案

### 核心思路
**过滤掉空字符串**，防止它们覆盖原有数据。

但有例外：
- `title` 和 `description` **允许为空**（用户可能想清空标题或描述）
- 其他字段（如 `groupID`, `importance`, `urgency` 等）**不应该用空字符串覆盖**

### 修复代码

#### 1. 过滤 updates 字典（第1358行）

```python
# 过滤掉None值和空字符串（title/description除外，它们允许为空）
updates = {k: v for k, v in updates.items() 
           if v is not None and (v != '' or k in ['title', 'description'])}
```

#### 2. 在应用 updates 前再次过滤（所有 edit_scope 分支）

**Single 模式 - 重复事件**（第1573-1577行）：
```python
# 过滤掉空值，避免覆盖原有数据（title/description除外）
filtered_updates = {k: v for k, v in updates.items() 
                    if v != '' or k in ['title', 'description']}

event.update(filtered_updates)
```

**Single 模式 - 非重复事件**（第1602-1606行）：
```python
# 过滤掉空值，避免覆盖原有数据（title/description除外）
filtered_updates = {k: v for k, v in updates.items() 
                    if v != '' or k in ['title', 'description']}

event.update(filtered_updates)
```

**All 模式**（第1733-1738行）：
```python
# 只更新非时间字段，保持原有的start/end时间
# 同时过滤空字符串，避免覆盖原有数据（title/description除外）
update_data = {k: v for k, v in updates.items() 
               if k not in ['start', 'end'] and 
               (v != '' or k in ['title', 'description'])}
event.update(update_data)
```

**Future/From_time 模式 - RRule 未改变**（第1791-1796行）：
```python
# 对于非RRule修改，只更新非时间字段，保持原有的start/end时间
# 同时过滤空字符串，避免覆盖原有数据（title/description除外）
update_data = {k: v for k, v in updates.items() 
               if k not in ['rrule', 'start', 'end'] and 
               (v != '' or k in ['title', 'description'])}
event.update(update_data)
```

**Future/From_time 模式 - 其他情况**（第1893-1898行）：
```python
# 对于非RRule修改，排除start/end字段，保持原有时间
# 同时过滤空字符串，避免覆盖原有数据（title/description除外）
update_data = {k: v for k, v in updates.items() 
               if k not in ['start', 'end'] and 
               (v != '' or k in ['title', 'description'])}
event.update(update_data)
```

## 过滤逻辑说明

### 条件表达式
```python
v != '' or k in ['title', 'description']
```

### 逻辑表
| 字段 | 值 | 条件1: `v != ''` | 条件2: `k in [...]` | 结果 (OR) | 说明 |
|------|-----|-----------------|-------------------|----------|------|
| groupID | "" | False | False | **False** | ❌ 被过滤，不覆盖原值 |
| groupID | "abc" | True | False | **True** | ✅ 保留，更新为新值 |
| title | "" | False | True | **True** | ✅ 保留，允许清空标题 |
| title | "新标题" | True | True | **True** | ✅ 保留，更新标题 |
| importance | "" | False | False | **False** | ❌ 被过滤，不覆盖原值 |
| importance | "high" | True | False | **True** | ✅ 保留，更新优先级 |

## 测试验证

### 测试场景
1. ✅ 创建事件并指定日程组
2. ✅ 编辑事件，只修改标题，groupID 保持不变
3. ✅ 编辑事件，修改 groupID 到另一个组
4. ✅ 编辑事件，清空标题（title 允许为空）
5. ✅ 编辑事件，修改优先级但不指定 groupID

### 期望结果
```json
// 场景2: 编辑前
{
  "title": "原标题",
  "groupID": "group-123"
}

// 场景2: 只修改标题后
{
  "title": "新标题",
  "groupID": "group-123"  // ✅ 保持不变
}

// 场景3: 修改 groupID
{
  "title": "新标题",
  "groupID": "group-456"  // ✅ 更新为新组
}

// 场景4: 清空标题
{
  "title": "",  // ✅ 允许清空
  "groupID": "group-123"
}
```

## 修改位置总结

| 文件 | 函数 | 行数 | 修改内容 |
|------|------|------|----------|
| core/views_events.py | bulk_edit_events_impl | 1358 | 过滤 updates 字典 |
| core/views_events.py | bulk_edit_events_impl | 1573-1577 | Single 模式 - 重复事件 |
| core/views_events.py | bulk_edit_events_impl | 1602-1606 | Single 模式 - 非重复事件 |
| core/views_events.py | bulk_edit_events_impl | 1733-1738 | All 模式 |
| core/views_events.py | bulk_edit_events_impl | 1791-1796 | Future - RRule 未改变 |
| core/views_events.py | bulk_edit_events_impl | 1893-1898 | Future - 其他情况 |

## 相关问题

这个问题影响所有可能为空的字段：
- ✅ groupID
- ✅ importance  
- ✅ urgency
- ✅ ddl
- ✅ rrule

但不影响：
- ✅ title（允许为空）
- ✅ description（允许为空）
- ✅ start/end（被特殊处理，不在 update_data 中）

## 总结

修复后，所有编辑操作都会：
1. ✅ 过滤掉空字符串（title/description 除外）
2. ✅ 保留原有的 groupID、importance 等字段
3. ✅ 允许用户清空 title 和 description
4. ✅ 允许用户修改任何字段到新值

现在日程组功能应该完全正常了！🎉
