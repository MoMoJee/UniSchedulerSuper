# 重复日程DDL日期问题修复

## 问题描述

**Bug现象：**
- 同一系列的所有重复日程，ddl字段的值完全相同，都是第一个日程的ddl
- 例如：
  - 第一个日程：end="2025-10-14T19:00:00"，ddl="2025-10-14T19:00:00" ✅
  - 最后一个日程：end="2025-11-02T19:00:00"，ddl="2025-10-14T19:00:00" ❌（错误）

**期望行为：**
- 每个重复日程的ddl日期应该是**该日程自己的end日期**
- 时间点是统一设定的（从主事件继承）
- 例如：
  - 第一个日程：end="2025-10-14T19:00:00"，ddl="2025-10-14T19:00:00" ✅
  - 最后一个日程：end="2025-11-02T19:00:00"，ddl="2025-11-02T19:00:00" ✅（正确）

---

## 根本原因

**代码位置：** `core/views_events.py` 中有**四个**生成实例的方法都存在问题

1. **`_generate_event_instances()`** - 主要的实例生成方法（行号 ~775）
2. **`generate_event_instances()`** - 使用RRule引擎的生成方法（行号 ~497）
3. **`_generate_event_instances_fallback()`** - 回退方法，包含三个频率类型：
   - FREQ=DAILY（行号 ~589）
   - FREQ=WEEKLY（行号 ~632）
   - FREQ=MONTHLY（行号 ~711）

**问题代码（以 `_generate_event_instances` 为例）：**
```python
for instance_time in instances:
    instance_start = instance_time.strftime("%Y-%m-%dT%H:%M:%S")
    instance_end = (instance_time + duration).strftime("%Y-%m-%dT%H:%M:%S")
    
    if instance_start not in existing_times:
        new_event = main_event.copy()  # 🔴 直接复制主事件，包括ddl
        new_event.update({
            'id': str(uuid.uuid4()),
            'start': instance_start,
            'end': instance_end,
            'is_main_event': False,
            ...
        })
        # ddl字段没有更新，保持主事件的值
```

**问题分析：**
1. `main_event.copy()` 会复制主事件的所有字段，包括 `ddl`
2. 后续的 `update()` 只更新了 `id`、`start`、`end` 等字段，没有更新 `ddl`
3. 结果：所有实例的ddl都等于主事件的ddl（第一个日程的完整日期时间）

---

## 解决方案

### 修复逻辑

在**所有**生成实例的方法中，都需要重新计算ddl：
1. 从主事件的ddl中**提取时间部分**（HH:MM:SS）
2. 从当前实例的end中**提取日期部分**（YYYY-MM-DD）
3. **组合**成新的ddl（YYYY-MM-DD + T + HH:MM:SS）

### 修复的方法列表

✅ **1. `_generate_event_instances()`** - 主要实例生成方法
✅ **2. `generate_event_instances()`** - RRule引擎生成方法  
✅ **3. `_generate_event_instances_fallback()` - FREQ=DAILY**
✅ **4. `_generate_event_instances_fallback()` - FREQ=WEEKLY**
✅ **5. `_generate_event_instances_fallback()` - FREQ=MONTHLY**

### 修复后代码示例

**文件：** `core/views_events.py`（行号 ~715-745）

```python
new_events = []
for instance_time in instances:
    instance_start = instance_time.strftime("%Y-%m-%dT%H:%M:%S")
    instance_end = (instance_time + duration).strftime("%Y-%m-%dT%H:%M:%S")
    
    if instance_start not in existing_times:
        new_event = main_event.copy()
        
        # ✅ 处理ddl：提取时间部分，与当前实例的end日期组合
        instance_ddl = ''
        if main_event.get('ddl'):
            try:
                # 从主事件的ddl中提取时间部分（HH:MM:SS）
                main_ddl = main_event['ddl']
                if 'T' in main_ddl:
                    ddl_time_part = main_ddl.split('T')[1]  # 例如："19:00:00"
                    # 从instance_end中提取日期部分
                    instance_end_date = instance_end.split('T')[0]  # 例如："2025-11-02"
                    # 组合：当前实例的日期 + 主事件ddl的时间
                    instance_ddl = f"{instance_end_date}T{ddl_time_part}"
                else:
                    instance_ddl = main_event['ddl']
            except Exception as e:
                logger.warning(f"Failed to generate ddl for instance: {e}")
                instance_ddl = ''
        
        new_event.update({
            'id': str(uuid.uuid4()),
            'start': instance_start,
            'end': instance_end,
            'ddl': instance_ddl,  # ✅ 使用计算后的ddl
            'is_main_event': False,
            'recurrence_id': instance_start,
            'parent_event_id': main_event['id'],
            'last_modified': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        new_events.append(new_event)
```

---

## 数据流示例

### 输入（主事件）
```json
{
  "id": "main-event-uuid",
  "title": "测试重复",
  "start": "2025-10-14T18:00:00",
  "end": "2025-10-14T19:00:00",
  "ddl": "2025-10-14T19:00:00",  // 主事件的ddl
  "rrule": "FREQ=DAILY;INTERVAL=1",
  "is_main_event": true,
  "series_id": "series-uuid"
}
```

### 处理过程

**生成第1个实例（10-15）：**
```python
instance_end = "2025-10-15T19:00:00"
ddl_time_part = "19:00:00"              # 从主事件ddl提取
instance_end_date = "2025-10-15"        # 从instance_end提取
instance_ddl = "2025-10-15T19:00:00"    # 组合
```

**生成第2个实例（10-16）：**
```python
instance_end = "2025-10-16T19:00:00"
ddl_time_part = "19:00:00"              # 从主事件ddl提取
instance_end_date = "2025-10-16"        # 从instance_end提取
instance_ddl = "2025-10-16T19:00:00"    # 组合
```

**生成最后实例（11-02）：**
```python
instance_end = "2025-11-02T19:00:00"
ddl_time_part = "19:00:00"              # 从主事件ddl提取
instance_end_date = "2025-11-02"        # 从instance_end提取
instance_ddl = "2025-11-02T19:00:00"    # 组合 ✅
```

### 输出（生成的实例）
```json
[
  {
    "id": "instance-1-uuid",
    "start": "2025-10-15T18:00:00",
    "end": "2025-10-15T19:00:00",
    "ddl": "2025-10-15T19:00:00",  // ✅ 使用自己的日期
    "is_main_event": false,
    "series_id": "series-uuid"
  },
  {
    "id": "instance-2-uuid",
    "start": "2025-10-16T18:00:00",
    "end": "2025-10-16T19:00:00",
    "ddl": "2025-10-16T19:00:00",  // ✅ 使用自己的日期
    "is_main_event": false,
    "series_id": "series-uuid"
  },
  ...
  {
    "id": "instance-last-uuid",
    "start": "2025-11-02T18:00:00",
    "end": "2025-11-02T19:00:00",
    "ddl": "2025-11-02T19:00:00",  // ✅ 使用自己的日期（而非10-14）
    "is_main_event": false,
    "series_id": "series-uuid"
  }
]
```

---

## 边界情况处理

### 1. 主事件没有ddl
```python
if main_event.get('ddl'):  # ✅ 检查ddl存在
    # 提取和组合逻辑
else:
    instance_ddl = ''  # ✅ 实例的ddl也为空
```

### 2. ddl格式异常（无'T'分隔符）
```python
if 'T' in main_ddl:
    # 正常提取时间部分
else:
    instance_ddl = main_event['ddl']  # ✅ 回退：直接使用主事件ddl
```

### 3. 解析异常
```python
try:
    # 提取和组合逻辑
except Exception as e:
    logger.warning(f"Failed to generate ddl for instance: {e}")
    instance_ddl = ''  # ✅ 异常情况下置空
```

---

## 测试验证

### 测试步骤

1. **创建重复日程并设置ddl**
   - 创建每日重复日程，时间18:00-19:00
   - 设置ddl为19:00（时间点）
   - 保存并刷新页面

2. **检查数据库中的日程实例**
   ```python
   # 在Django shell中
   from core.models import UserData
   events = UserData.objects.get(key='events').get_value()
   
   # 筛选同一系列的日程
   series_id = "目标系列ID"
   series_events = [e for e in events if e.get('series_id') == series_id]
   
   # 检查每个日程的ddl
   for event in sorted(series_events, key=lambda x: x['start']):
       print(f"Start: {event['start']}")
       print(f"End:   {event['end']}")
       print(f"DDL:   {event['ddl']}")
       print(f"Match: {event['end'] == event['ddl']}")  # 应该为True
       print("---")
   ```

3. **验证预期结果**
   - ✅ 每个日程的ddl日期 = 该日程的end日期
   - ✅ 所有日程的ddl时间 = 统一设定的时间点（19:00:00）
   - ✅ ddl格式：YYYY-MM-DDT19:00:00

### 预期输出示例
```
Start: 2025-10-14T18:00:00
End:   2025-10-14T19:00:00
DDL:   2025-10-14T19:00:00
Match: True
---
Start: 2025-10-15T18:00:00
End:   2025-10-15T19:00:00
DDL:   2025-10-15T19:00:00
Match: True
---
Start: 2025-11-02T18:00:00
End:   2025-11-02T19:00:00
DDL:   2025-11-02T19:00:00
Match: True
---
```

---

## 相关代码文件

| 文件路径 | 修改方法 | 行号（大约） | 说明 |
|---------|---------|------------|------|
| `core/views_events.py` | `_generate_event_instances()` | ~775 | 主要的实例生成方法 |
| `core/views_events.py` | `generate_event_instances()` | ~497 | 使用RRule引擎生成实例 |
| `core/views_events.py` | `_generate_event_instances_fallback()` DAILY | ~589 | 每日重复的回退逻辑 |
| `core/views_events.py` | `_generate_event_instances_fallback()` WEEKLY | ~632 | 每周重复的回退逻辑 |
| `core/views_events.py` | `_generate_event_instances_fallback()` MONTHLY | ~711 | 每月重复的回退逻辑 |

**总计修改：** 5处生成实例的代码，全部添加了ddl重新计算逻辑

---

## 关联问题

此修复是重复日程功能系列修复的一部分：

1. ✅ **EXDATE机制** - 防止已编辑的单个实例被重新生成
2. ✅ **主日程转移** - 删除/编辑第一个实例时，自动提升下一个为主事件
3. ✅ **DDL验证** - 拖拽/编辑时，end不能超过ddl
4. ✅ **DDL UI控制** - 重复日程的ddl只能选择时间点，日期锁定为end
5. ✅ **DDL参数传递** - 前端→后端正确传递ddl参数
6. ✅ **DDL日期生成** - 每个实例的ddl使用自己的日期（本次修复）

---

## 修复日期
2025-10-14

## 修复人员
GitHub Copilot

## 验证状态
⏳ 待用户测试验证
