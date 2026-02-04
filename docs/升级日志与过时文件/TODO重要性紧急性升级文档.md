# TODO 重要性紧急性升级文档

## 📅 升级日期
2025年11月5日

## 🎯 升级目标
将 TODO 的重要性/紧急性参数从三档制升级为二档制，与 Events 保持一致，并统一界面交互方式。

## 📋 升级内容

### 1. 数据模型升级

#### 修改文件：`core/models.py`

**修改前（三档制）：**
```python
"importance": {
    "type": str,
    "nullable": False,
    "default": "medium",  # critical|high|medium|low
},
"urgency": {
    "type": str,
    "nullable": False,
    "default": "normal",  # urgent|normal|not-urgent
},
```

**修改后（二档制）：**
```python
"importance": {
    "type": str,
    "nullable": False,
    "default": "",  # important|not-important (与Events保持一致)
},
"urgency": {
    "type": str,
    "nullable": False,
    "default": "",  # urgent|not-urgent (与Events保持一致)
},
```

#### 变更说明
| 维度 | 旧值 | 新值 |
|------|------|------|
| **重要性** | critical / high / medium / low | important / not-important |
| **紧急性** | urgent / normal / not-urgent | urgent / not-urgent |

---

### 2. 前端界面升级

#### 修改文件：`core/templates/home_new.html`

#### 2.1 创建 TODO 模态框（createTodoModal）

**修改前（下拉选择框）：**
```html
<div class="col-md-6">
    <label for="newTodoImportance" class="form-label">重要性</label>
    <select class="form-select" id="newTodoImportance">
        <option value="low">低</option>
        <option value="medium" selected>中</option>
        <option value="high">高</option>
    </select>
</div>

<div class="col-md-6">
    <label for="newTodoUrgency" class="form-label">紧急性</label>
    <select class="form-select" id="newTodoUrgency">
        <option value="low">低</option>
        <option value="normal" selected>普通</option>
        <option value="high">高</option>
    </select>
</div>
```

**修改后（2x2 矩阵按钮）：**
```html
<div class="col-12">
    <label class="form-label">重要性 / 紧急性</label>
    <div class="importance-urgency-matrix">
        <div class="matrix-row">
            <button type="button" class="matrix-button important-urgent" 
                    data-importance="important" data-urgency="urgent"
                    onclick="setImportanceUrgency('important', 'urgent', this)">
                重要紧急
            </button>
            <button type="button" class="matrix-button important-not-urgent" 
                    data-importance="important" data-urgency="not-urgent"
                    onclick="setImportanceUrgency('important', 'not-urgent', this)">
                重要不紧急
            </button>
        </div>
        <div class="matrix-row">
            <button type="button" class="matrix-button not-important-urgent" 
                    data-importance="not-important" data-urgency="urgent"
                    onclick="setImportanceUrgency('not-important', 'urgent', this)">
                不重要紧急
            </button>
            <button type="button" class="matrix-button not-important-not-urgent" 
                    data-importance="not-important" data-urgency="not-urgent"
                    onclick="setImportanceUrgency('not-important', 'not-urgent', this)">
                不重要不紧急
            </button>
        </div>
    </div>
    <input type="hidden" id="newTodoImportance">
    <input type="hidden" id="newTodoUrgency">
</div>
```

#### 2.2 编辑 TODO 模态框（editTodoModal）

同样的修改应用到编辑模态框，字段 ID 去掉 "new" 前缀：
- `todoImportance` (隐藏字段)
- `todoUrgency` (隐藏字段)

---

### 3. JavaScript 代码升级

#### 3.1 修改文件：`core/static/js/todo-manager.js`

##### 更新优先级类名映射

**修改前：**
```javascript
getPriorityClass(importance) {
    const priorityMap = {
        'critical': 'high-priority',
        'high': 'high-priority',
        'medium': 'medium-priority',
        'low': 'low-priority'
    };
    return priorityMap[importance] || 'medium-priority';
}
```

**修改后（四象限分类）：**
```javascript
getPriorityClass(importance, urgency) {
    // 根据四象限分类
    if (importance === 'important' && urgency === 'urgent') {
        return 'high-priority';  // 重要紧急
    } else if (importance === 'important' && urgency === 'not-urgent') {
        return 'medium-priority';  // 重要不紧急
    } else if (importance === 'not-important' && urgency === 'urgent') {
        return 'medium-priority';  // 不重要紧急
    } else {
        return 'low-priority';  // 不重要不紧急
    }
}
```

##### 更新优先级图标

**修改前：**
```javascript
getPriorityIcon(importance, urgency) {
    if (importance === 'critical' || (importance === 'high' && urgency === 'urgent')) {
        return '🔴';
    } else if (importance === 'high' || urgency === 'urgent') {
        return '🟡';
    } else if (importance === 'low') {
        return '🟢';
    }
    return '🔵';
}
```

**修改后（四象限图标）：**
```javascript
getPriorityIcon(importance, urgency) {
    // 根据四象限分类
    if (importance === 'important' && urgency === 'urgent') {
        return '🔴';  // 重要紧急 - 红色
    } else if (importance === 'important' && urgency === 'not-urgent') {
        return '🟡';  // 重要不紧急 - 黄色
    } else if (importance === 'not-important' && urgency === 'urgent') {
        return '🟠';  // 不重要紧急 - 橙色
    } else {
        return '🟢';  // 不重要不紧急 - 绿色
    }
}
```

##### 更新元素创建调用

**修改前：**
```javascript
div.className = `todo-item ${this.getPriorityClass(todo.importance)}`;
```

**修改后：**
```javascript
div.className = `todo-item ${this.getPriorityClass(todo.importance, todo.urgency)}`;
```

#### 3.2 修改文件：`core/static/js/modal-manager.js`

##### 扩展 setImportanceUrgency 方法支持 TODO

**修改前：**
```javascript
setImportanceUrgency(importance, urgency, mode = 'create') {
    const prefix = mode === 'create' ? 'newEvent' : 'event';
    const modalId = mode === 'create' ? 'createEventModal' : 'editEventModal';
    // ...
}
```

**修改后（支持 4 种模式）：**
```javascript
setImportanceUrgency(importance, urgency, mode = 'create') {
    // 确定前缀和模态框ID
    let prefix, modalId;
    
    if (mode === 'create') {
        prefix = 'newEvent';
        modalId = 'createEventModal';
    } else if (mode === 'edit') {
        prefix = 'event';
        modalId = 'editEventModal';
    } else if (mode === 'createTodo') {
        prefix = 'newTodo';
        modalId = 'createTodoModal';
    } else if (mode === 'editTodo') {
        prefix = 'todo';
        modalId = 'editTodoModal';
    }
    // ...
}
```

##### 更新 openEditTodoModal 方法

**修改前（设置下拉框值）：**
```javascript
document.getElementById('todoImportance').value = todo.importance;
document.getElementById('todoUrgency').value = todo.urgency;
```

**修改后（设置矩阵按钮选中状态）：**
```javascript
// 设置重要性紧急性矩阵按钮选中状态
this.setImportanceUrgency(
    todo.importance || '',
    todo.urgency || '',
    'editTodo'
);
```

---

## 📊 四象限优先级映射

### 优先级分类规则

| 重要性 | 紧急性 | CSS类名 | 图标 | 说明 |
|--------|--------|---------|------|------|
| important | urgent | `high-priority` | 🔴 | 最高优先级 - 重要紧急 |
| important | not-urgent | `medium-priority` | 🟡 | 中优先级 - 重要不紧急 |
| not-important | urgent | `medium-priority` | 🟠 | 中优先级 - 不重要紧急 |
| not-important | not-urgent | `low-priority` | 🟢 | 低优先级 - 不重要不紧急 |

### 四象限矩阵

```
         │  urgent  │ not-urgent
─────────┼──────────┼────────────
important│    🔴    │    🟡
         │  立即做  │  计划做
─────────┼──────────┼────────────
not-imp. │    🟠    │    🟢
         │  授权做  │  不做/少做
```

---

## 🎨 UI/UX 改进

### 1. 视觉一致性
- ✅ TODO 和 Events 使用相同的 2x2 矩阵按钮布局
- ✅ 相同的按钮样式和交互反馈
- ✅ 统一的颜色编码和图标系统

### 2. 交互优化
- ✅ 点击矩阵按钮即可设置重要性和紧急性
- ✅ 按钮有选中状态反馈（`.selected` 类）
- ✅ 可点击已选中的按钮取消选择
- ✅ 同一模态框内只能选中一个按钮

### 3. 用户体验
- 简化操作步骤：从 2 次下拉选择 → 1 次按钮点击
- 更直观的四象限划分，符合时间管理理论
- 与 Events 统一的操作习惯，降低学习成本

---

## 🔄 数据迁移

### 旧数据兼容性

如果数据库中存在旧的 TODO 数据，可能需要进行数据迁移：

#### 迁移映射规则

**重要性（Importance）：**
```
critical → important
high     → important
medium   → not-important
low      → not-important
```

**紧急性（Urgency）：**
```
urgent     → urgent
normal     → not-urgent
not-urgent → not-urgent
```

#### 示例迁移脚本（伪代码）

```python
# 在 Django shell 中执行
from core.models import UserData

for user_data in UserData.objects.all():
    todos = user_data.get_value('todos', [])
    
    for todo in todos:
        # 迁移重要性
        old_importance = todo.get('importance', 'medium')
        if old_importance in ['critical', 'high']:
            todo['importance'] = 'important'
        else:
            todo['importance'] = 'not-important'
        
        # 迁移紧急性
        old_urgency = todo.get('urgency', 'normal')
        if old_urgency == 'urgent':
            todo['urgency'] = 'urgent'
        else:
            todo['urgency'] = 'not-urgent'
    
    user_data.set_value('todos', todos)
    user_data.save()
```

**注意：** 实际迁移前请备份数据库！

---

## 🧪 测试清单

### 功能测试

#### 1. 创建 TODO
- [ ] 点击"重要紧急"按钮，隐藏字段正确设置为 `important` 和 `urgent`
- [ ] 点击"重要不紧急"按钮，隐藏字段正确设置
- [ ] 点击"不重要紧急"按钮，隐藏字段正确设置
- [ ] 点击"不重要不紧急"按钮，隐藏字段正确设置
- [ ] 创建后 TODO 显示正确的优先级图标和颜色
- [ ] 数据保存到后端正确

#### 2. 编辑 TODO
- [ ] 打开编辑对话框时，矩阵按钮显示当前选中状态
- [ ] 可以切换到其他按钮
- [ ] 保存后更新正确
- [ ] 列表中的 TODO 图标和颜色正确更新

#### 3. 显示测试
- [ ] 🔴 重要紧急的 TODO 显示为红色高优先级
- [ ] 🟡 重要不紧急的 TODO 显示为黄色中优先级
- [ ] 🟠 不重要紧急的 TODO 显示为橙色中优先级
- [ ] 🟢 不重要不紧急的 TODO 显示为绿色低优先级

#### 4. 边界情况
- [ ] 没有设置重要性/紧急性的旧 TODO 能正常显示
- [ ] 空值处理正确
- [ ] 多次切换按钮选择正常工作

---

## 📝 变更文件清单

### 后端文件
1. ✅ `core/models.py` - TODO 数据模型定义

### 前端文件
2. ✅ `core/templates/home_new.html` - 创建和编辑 TODO 模态框界面
3. ✅ `core/static/js/todo-manager.js` - TODO 管理器逻辑
4. ✅ `core/static/js/modal-manager.js` - 模态框管理器

### 同步文件
5. ✅ `staticfiles/js/todo-manager.js`
6. ✅ `staticfiles/js/modal-manager.js`

---

## 🎯 与 Events 对比

### 完全一致的部分
| 特性 | Events | TODO |
|------|--------|------|
| **重要性值** | important / not-important | ✅ 一致 |
| **紧急性值** | urgent / not-urgent | ✅ 一致 |
| **UI 控件** | 2x2 矩阵按钮 | ✅ 一致 |
| **交互方式** | 点击按钮设置 | ✅ 一致 |
| **视觉反馈** | .selected 类 | ✅ 一致 |
| **隐藏字段** | xxxImportance / xxxUrgency | ✅ 一致 |

### 实现细节差异
| 方面 | Events | TODO |
|------|--------|------|
| **优先级计算** | 直接影响日历显示颜色 | 影响 TODO 列表项颜色 |
| **图标使用** | 在事件卡片上显示 | 在 TODO 列表左侧显示 |
| **CSS 类名** | event-xxx | todo-item xxx-priority |

---

## 🚀 升级效果

### 用户收益
1. **操作更简单** - 一次点击设置两个维度
2. **界面更统一** - Events 和 TODO 使用相同交互
3. **认知更清晰** - 四象限分类符合时间管理理论
4. **视觉更直观** - 颜色和图标清晰表达优先级

### 技术收益
1. **代码复用** - 共用 setImportanceUrgency 函数
2. **维护简化** - 统一的数据模型和逻辑
3. **扩展性好** - 易于添加新功能
4. **一致性强** - 减少用户和开发者的困惑

---

## 📚 相关文档
- Events 重要性紧急性实现：`core/static/js/modal-manager.js` line 2173
- 四象限矩阵样式：已在 Events 中定义，TODO 复用相同 CSS
- 时间管理理论参考：艾森豪威尔矩阵（Eisenhower Matrix）

---

## 🎉 升级完成

TODO 功能已成功升级为与 Events 一致的二档制重要性/紧急性系统！

刷新页面后：
1. 创建新 TODO 时使用 2x2 矩阵按钮
2. 编辑现有 TODO 时看到正确的选中状态
3. TODO 列表显示符合四象限的优先级图标和颜色

**版本**: v20251105-001 (TODO Importance/Urgency Upgrade)
