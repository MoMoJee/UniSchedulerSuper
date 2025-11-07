# GroupID字段名大小写不一致问题修复

## 问题描述

### 症状
- 创建日程时可以正常指定日程组
- 编辑日程时,日程组选项总是变成空(无论修改什么字段)
- 无法操作日程组选项为空的日程

### 根本原因
前端代码中存在字段名不一致的问题:

1. **`getEventDataFromForm()` 函数**(line 2141)返回的对象使用 `groupID`(大写ID):
   ```javascript
   groupID: document.getElementById(`${prefix}GroupId`).value
   ```

2. **但在使用时**(line 972, 1012)却使用了 `groupId`(小写id):
   ```javascript
   groupID: eventData.groupId  // ❌ groupId 是 undefined!
   eventData.groupId           // ❌ groupId 是 undefined!
   ```

3. 结果导致传递给后端的 `groupID` 始终是 `undefined`,经过后端的空字符串过滤逻辑处理后,虽然不会覆盖原值,但由于 `undefined` 会被 `data.get('groupID')` 转换为 `None`,最终还是导致了问题。

## 问题分析

### 数据流追踪

#### 创建日程(正常)
```
表单 → getEventDataFromForm() → {groupID: "123"}
     → createEvent() → 后端 → 保存成功 ✓
```

#### 编辑日程(错误)
```
表单 → getEventDataFromForm() → {groupID: "123"}
     → 使用 eventData.groupId → undefined
     → 传给后端 {groupID: undefined}
     → data.get('groupID') → None
     → 过滤后 updates 中没有 groupID
     → event.update() 时 groupID 保持原值
     
问题: 虽然不会覆盖,但这不是期望的行为!
```

### 为什么创建时正常?

查看创建日程的代码,直接使用了正确的字段名:
```javascript
// core/static/js/modal-manager.js handleCreateEvent()
const eventData = this.getEventDataFromForm('create');
await eventManager.createEvent(
    this.toUTC(eventData.start),
    this.toUTC(eventData.end),
    eventData.title,
    eventData.description,
    eventData.importance,
    eventData.urgency,
    eventData.groupID,  // ✓ 正确使用 groupID
    eventData.ddl ? this.toUTC(eventData.ddl) : '',
    eventData.rrule
);
```

### 为什么编辑时出错?

编辑日程有两个路径,都使用了错误的字段名:

1. **批量编辑路径**(line 972):
   ```javascript
   const updateData = {
       groupID: eventData.groupId,  // ❌ 应该是 groupID
       // ...
   };
   ```

2. **普通更新路径**(line 1012):
   ```javascript
   await eventManager.updateEvent(
       // ...
       eventData.groupId,  // ❌ 应该是 groupID
       // ...
   );
   ```

## 修复方案

### 修改文件
`core/static/js/modal-manager.js`

### 修改位置

#### 修改1: 批量编辑路径(line 972)
```javascript
// 修改前
const updateData = {
    title: eventData.title,
    description: eventData.description,
    importance: eventData.importance,
    urgency: eventData.urgency,
    start: this.toUTC(eventData.start),
    end: this.toUTC(eventData.end),
    groupID: eventData.groupId,  // ❌ 错误
    ddl: eventData.ddl ? this.toUTC(eventData.ddl) : ''
};

// 修改后
const updateData = {
    title: eventData.title,
    description: eventData.description,
    importance: eventData.importance,
    urgency: eventData.urgency,
    start: this.toUTC(eventData.start),
    end: this.toUTC(eventData.end),
    groupID: eventData.groupID,  // ✓ 正确
    ddl: eventData.ddl ? this.toUTC(eventData.ddl) : ''
};
```

#### 修改2: 普通更新路径(line 1012)
```javascript
// 修改前
const success = await eventManager.updateEvent(
    this.currentEventId,
    this.toUTC(eventData.start),
    this.toUTC(eventData.end),
    eventData.title,
    eventData.description,
    eventData.importance,
    eventData.urgency,
    eventData.groupId,  // ❌ 错误
    eventData.ddl ? this.toUTC(eventData.ddl) : '',
    eventData.rrule
);

// 修改后
const success = await eventManager.updateEvent(
    this.currentEventId,
    this.toUTC(eventData.start),
    this.toUTC(eventData.end),
    eventData.title,
    eventData.description,
    eventData.importance,
    eventData.urgency,
    eventData.groupID,  // ✓ 正确
    eventData.ddl ? this.toUTC(eventData.ddl) : '',
    eventData.rrule
);
```

### 后端调试增强

在 `core/views_events.py` 的 `bulk_edit_events_impl` 函数中添加调试日志(line 1361-1362):

```python
logger.info(f"[DEBUG] groupID from request: {data.get('groupID')}, type: {type(data.get('groupID'))}")
logger.info(f"[DEBUG] Filtered updates: {updates}")
```

## 验证测试

### 测试步骤
1. 刷新页面,确保加载最新的JavaScript代码
2. 创建一个日程并指定日程组(如"工作")
3. 编辑该日程,只修改标题
4. 保存后检查:
   - 日程组选项仍然显示"工作" ✓
   - 日程的颜色保持不变 ✓
   - 后台日志显示正确的groupID值 ✓

### 预期结果
- ✅ 编辑任何字段时,groupID不会丢失
- ✅ 可以编辑日程组为空的日程
- ✅ 可以在编辑时修改日程组
- ✅ 日志中显示正确的groupID值和类型

## 技术总结

### JavaScript对象属性访问规则
- 对象属性名是大小写敏感的
- 访问不存在的属性返回 `undefined`
- `undefined` 在传递给后端时可能变成 `null` 或空字符串

### 命名规范建议
1. 在同一个代码库中保持统一的命名风格
2. 前端和后端的字段名应该完全一致
3. 使用TypeScript可以在编译时发现这类错误

### 相关改进
本次修复是在之前修复"空字符串覆盖问题"的基础上进行的。完整的修复链:

1. **第一阶段**: 过滤空字符串,防止覆盖原值
   - 位置: `bulk_edit_events_impl` 多个分支
   - 逻辑: `v != '' or k in ['title', 'description']`

2. **第二阶段**: 修复字段名大小写,确保值正确传递(本次修复)
   - 位置: `modal-manager.js` line 972, 1012
   - 从: `eventData.groupId` → 到: `eventData.groupID`

两个阶段共同确保groupID字段的完整性。

## 修复日期
2025-10-13
