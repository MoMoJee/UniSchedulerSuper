# DDL参数传递和UI交互完整修复文档

## 修复日期
2025-10-14

## 问题总结

### 问题1：ddl控件状态未正确清除
**症状**：编辑重复日程后，关闭模态框再打开非重复日程，ddl控件仍保持time类型
**原因**：关闭模态框时未重置ddl控件类型

### 问题2：切换重复/非重复模式时ddl值被清空
**症状**：点击两次"重复日程"复选框，ddl值消失
**原因**：`updateDdlInputType`在切换类型时未保留原值

### 问题3：创建和编辑重复日程时ddl未保存
**症状**：数据库中ddl字段为空
**原因**：
1. 后端`create_event_impl`优先使用auto_ddl设置，忽略了请求中的ddl
2. 后端`bulk_edit_events_impl`过滤掉了空字符串的ddl

## 修复方案

### 一、前端UI修复

#### 1. 关闭模态框时重置ddl控件类型

**文件**：`core/static/js/modal-manager.js`
**方法**：`closeAllModals()`

```javascript
closeAllModals() {
    // 清理自定义控件
    this.cleanupCustomControls();
    
    // 重置ddl控件类型为默认（下次打开时会根据日程类型重新设置）
    const creatEventDdl = document.getElementById('creatEventDdl');
    const eventDdl = document.getElementById('eventDdl');
    if (creatEventDdl) creatEventDdl.type = 'datetime-local';
    if (eventDdl) eventDdl.type = 'datetime-local';
    
    // ...其他清理代码
}
```

**效果**：每次关闭模态框，ddl控件恢复为datetime-local类型，下次打开时会根据实际日程类型重新设置。

#### 2. 切换控件类型时保留ddl值

**文件**：`core/static/js/modal-manager.js`
**方法**：`updateDdlInputType(mode, rruleStr)`

**修改前逻辑**：
```javascript
if (isRecurring) {
    ddlInput.type = 'time';
    if (ddlInput.value) {
        const t = ddlInput.value.split('T')[1] || ddlInput.value;
        ddlInput.value = t.length > 5 ? t.substring(0, 5) : t;
    }
} else {
    ddlInput.type = 'datetime-local';  // ❌ 直接切换，值丢失
}
```

**修改后逻辑**：
```javascript
const currentType = ddlInput.type;
const currentValue = ddlInput.value;

if (isRecurring) {
    if (currentType !== 'time') {
        // 从 datetime-local 切换到 time，保留时间部分
        if (currentValue) {
            const timePart = currentValue.split('T')[1] || currentValue;
            ddlInput.type = 'time';
            ddlInput.value = timePart.substring(0, 5);
        } else {
            ddlInput.type = 'time';
        }
    }
} else {
    if (currentType !== 'datetime-local') {
        // 从 time 切换到 datetime-local，拼接end日期
        if (currentValue && endInput && endInput.value) {
            const endDate = endInput.value.split('T')[0];
            const timePart = currentValue.substring(0, 5);
            ddlInput.type = 'datetime-local';
            ddlInput.value = `${endDate}T${timePart}`;
        } else {
            ddlInput.type = 'datetime-local';
        }
    }
}
```

**效果**：
- **重复→普通**：保留时间（如"18:30"），拼接end日期变为"2025-10-14T18:30"
- **普通→重复**：保留时间部分"18:30"，丢弃日期部分
- **重复→重复**或**普通→普通**：值不变

### 二、后端参数处理修复

#### 1. 创建事件时ddl处理

**文件**：`core/views_events.py`
**方法**：`create_event_impl()`

**修改前逻辑**：
```python
# 根据用户设置处理DDL
if user_preference.get("auto_ddl", False):
    event_data['ddl'] = data.get('ddl', '')
else:
    event_data['ddl'] = ''  # ❌ 忽略请求中的ddl
```

**修改后逻辑**：
```python
# 处理DDL - 如果用户传了ddl就使用，否则根据用户设置决定
ddl_from_request = data.get('ddl', '')
if ddl_from_request:
    # 用户明确设置了ddl，直接使用
    event_data['ddl'] = ddl_from_request
elif user_preference.get("auto_ddl", False):
    # 用户未设置ddl，但启用了auto_ddl，使用end时间
    event_data['ddl'] = data.get('end', '')
else:
    # 用户未设置ddl，且未启用auto_ddl
    event_data['ddl'] = ''
```

**效果**：优先使用请求中的ddl值，auto_ddl设置仅作为默认行为。

#### 2. 编辑事件时ddl处理

**文件**：`core/views_events.py`
**方法**：`bulk_edit_events_impl()`

**修改前逻辑**：
```python
updates = {k: v for k, v in updates.items() 
           if v is not None and (v != '' or k in ['title', 'description'])}
# ❌ ddl为空字符串时被过滤掉
```

**修改后逻辑**：
```python
updates = {k: v for k, v in updates.items() 
           if v is not None and (v != '' or k in ['title', 'description', 'ddl'])}
# ✓ 允许ddl为空字符串（表示清除截止时间）
```

**效果**：允许通过传递空字符串来清除ddl，同时保留非空ddl值。

### 三、调试日志增强

#### 前端日志

**创建事件**：
```javascript
console.log('[CREATE EVENT] Raw eventData from form:', eventData);
console.log('[CREATE EVENT] Converted eventData (UTC):', eventData);
```

#### 后端日志

**编辑事件**：
```python
logger.info(f"[DEBUG] ddl from request: {data.get('ddl')}, type: {type(data.get('ddl'))}")
logger.info(f"[DEBUG] Filtered updates: {updates}")
```

## 数据流验证

### 创建重复日程（有ddl）

1. **前端表单**：
   - 勾选"重复日程"
   - end: `2025-10-14T14:00`
   - ddl: `18:30` (type="time")

2. **getEventFormData**：
   - 检测到重复日程
   - 拼接：`ddl = "2025-10-14T18:30"`

3. **handleCreateEvent**：
   - 转UTC：`ddl = "2025-10-14T10:30:00.000Z"`

4. **后端create_event_impl**：
   - `ddl_from_request = "2025-10-14T10:30:00.000Z"`
   - 保存到event_data

5. **数据库**：
   - ✅ ddl正确保存

### 编辑重复日程（修改ddl）

1. **前端打开**：
   - 检测rrule存在
   - ddl控件切换为time
   - 显示原时间：`18:30`

2. **用户修改**：
   - 改为：`20:00`

3. **getEventFormData**：
   - 拼接：`ddl = "2025-10-14T20:00"`

4. **handleUpdateEvent**：
   - 转UTC：`ddl = "2025-10-14T12:00:00.000Z"`

5. **后端bulk_edit_events_impl**：
   - updates包含ddl（不被过滤）
   - 更新事件

6. **数据库**：
   - ✅ ddl更新成功

### 切换重复/非重复（保留ddl）

**场景1：重复→普通→重复**

1. 原重复日程，ddl="18:30" (time类型)
2. 取消重复：
   - end="2025-10-14T14:00"
   - ddl变为"2025-10-14T18:30" (datetime-local类型)
3. 再勾选重复：
   - ddl变回"18:30" (time类型)
   - ✅ 时间保留

**场景2：普通→重复→普通**

1. 原普通日程，ddl="2025-10-15T20:00"
2. 勾选重复：
   - ddl变为"20:00" (time类型)
3. 取消重复：
   - end="2025-10-14T14:00"
   - ddl变为"2025-10-14T20:00"
   - ✅ 时间保留，日期跟随end

## 测试场景

### 场景1：创建重复日程并设置ddl
1. 打开创建模态框
2. 勾选"重复日程"
3. 设置end为"2025-10-15 14:00"
4. 设置ddl为"18:00"
5. 保存
6. **验证**：数据库中ddl应为"2025-10-15T18:00"（或UTC等价值）

### 场景2：编辑重复日程的ddl
1. 打开已有重复日程
2. ddl显示为time类型，值为"18:00"
3. 修改为"20:00"
4. 保存
5. **验证**：数据库中ddl更新为新时间

### 场景3：切换重复/非重复保留ddl
1. 打开编辑模态框
2. 原ddl="18:30"
3. 点击"重复日程"复选框（切换）
4. 再点击一次（切换回来）
5. **验证**：ddl值仍为"18:30"

### 场景4：关闭模态框后打开另一日程
1. 编辑一个重复日程（ddl为time类型）
2. 按ESC关闭
3. 打开一个非重复日程
4. **验证**：ddl为datetime-local类型

### 场景5：清除ddl
1. 编辑日程，清空ddl字段
2. 保存
3. **验证**：数据库中ddl为空字符串

## 技术要点

### 1. 控件类型切换时的值保留
- 检查当前类型，避免重复设置
- 提取时间/日期部分，按需拼接
- 确保格式正确（time: "HH:MM", datetime-local: "YYYY-MM-DDTHH:MM"）

### 2. 后端参数优先级
- 用户明确设置 > 用户偏好 > 默认值
- ddl允许为空（清除截止时间）

### 3. 调试策略
- 前端：打印原始表单数据和转换后数据
- 后端：打印请求参数和过滤后更新字典
- 对比：确保每个环节数据正确传递

## 相关文件

- `core/static/js/modal-manager.js` - 前端UI和数据处理
- `core/views_events.py` - 后端参数接收和保存
- `core/重复日程截止时间功能修复文档.md` - 前期修复文档

## 总结

本次修复解决了ddl参数在创建和编辑重复日程时的传递和保存问题：

1. **UI状态管理**：关闭模态框时正确重置，避免状态残留
2. **值保留逻辑**：切换重复/非重复时智能保留时间部分
3. **参数传递**：优先使用用户设置的ddl，而非auto_ddl配置
4. **后端处理**：允许ddl为空字符串，支持清除操作

所有问题均已修复，ddl功能现在完全正常工作。
