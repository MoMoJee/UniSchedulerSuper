## 🚀 **Events RRule功能升级计划文档**

### **总体升级策略**

1. **模块化架构**: 创建专用的`core/views_events.py`模块
2. **RRule引擎复用**: 直接使用现有的RRule引擎和IntegratedReminderManager
3. **数据结构适配**: 基于现有Events数据模型扩展
4. **前端界面升级**: 在现有日历界面添加RRule支持

### **第三步：后端升级计划**

#### **3.1 创建Events专用模块**
- **目标文件**: `core/views_events.py`
- **迁移函数**:
  - ✅ `get_events()` → `get_events_impl()`
  - ✅ `create_event()` → `create_event_impl()`
  - ✅ `update_events()` → `update_events_impl()`  
  - ✅ `delete_event()` → `delete_event_impl()`
  - ⏳ `create_events_group()` → `create_events_group_impl()`
  - ⏳ `update_event_group()` → `update_event_group_impl()`
  - ⏳ `delete_event_groups()` → `delete_event_groups_impl()`
  - ⏳ `import_events()` → `import_events_impl()`
  - ⏳ `get_outport_calendar()` → `get_outport_calendar_impl()`
  - ⏳ `check_modified_events()` → `check_modified_events_impl()`
  - ⏳ `convert_todo_to_event()` → `convert_todo_to_event_impl()`

#### **3.2 创建Events RRule管理器** ✅
- **已完成**: `EventsRRuleManager`类创建
- **主要功能**:
  - ✅ 继承并适配`IntegratedReminderManager`
  - ✅ 实现Events特有的RRule处理逻辑
  - ✅ 处理Events时间跨度（start/end vs trigger_time）
  - ✅ 管理Events的系列关系（series_id）
  - ✅ 新增`modify_recurring_event()`方法
  - ✅ 新增`generate_event_instances()`方法

#### **3.3 RRule功能增强** ✅

##### **3.3.1 create_event_impl() 升级** ✅
```python
def create_event_impl(request):
    """创建事件 - 支持RRule重复"""
    # ✅ 原有逻辑保持
    # ✅ 检测rrule参数
    # ✅ 如果有rrule：
        # ✅ 创建重复事件系列
        # ✅ 生成初始实例
        # ✅ 设置series_id
    # ✅ 如果无rrule：
        # ✅ 创建单个事件
```

##### **3.3.2 update_events_impl() 升级** ✅
```python
def update_events_impl(request):
    """更新事件 - 支持RRule修改"""
    # ✅ 原有逻辑保持
    # ✅ 检测rrule_change_scope参数
    # ✅ 支持修改范围：
        # ✅ single: 仅修改当前实例
        # ✅ all: 修改整个系列
        # ✅ future: 从当前开始修改
        # ✅ from_time: 从指定时间修改
```

##### **3.3.3 delete_event_impl() 升级** ✅
```python
def delete_event_impl(request):
    """删除事件 - 支持RRule删除"""
    # ✅ 原有逻辑保持
    # ✅ 检测delete_scope参数
    # ✅ 支持删除范围
        # ✅ single: 仅删除当前实例
        # ✅ all: 删除整个系列
        # ✅ future: 删除此及之后的实例
```

##### **3.3.4 新增RRule专用API** ✅
```python
def bulk_edit_events_impl(request):
    """✅ 批量编辑重复事件"""
    
def convert_recurring_to_single_impl(request):
    """✅ 将重复事件转换为单次事件"""
    
def split_event_series_impl(request):
    """✅ 分离事件系列"""
```

#### **3.4 数据结构适配** ✅

##### **3.4.1 Events数据扩展** ✅
```python
event = {
    # 现有字段
    "id": str,
    "title": str,
    "start": str,
    "end": str,
    "description": str,
    # ✅ RRule扩展字段已实现
    "rrule": str,           # RRule规则
    "series_id": str,       # 系列ID
    "is_recurring": bool,   # 是否重复
    "is_main_event": bool,  # 是否主事件
    "recurrence_id": str,   # 重复实例ID
    "parent_event_id": str, # 父事件ID
    "is_exception": bool,   # 是否例外实例
    "original_start": str,  # 例外实例的原始时间
}
```

##### **3.4.2 Events Manager适配** ✅
```python
class EventsRRuleManager(IntegratedReminderManager):
    """✅ Events专用的RRule管理器"""
    
    def create_recurring_event(self, event_data, rrule):
        """✅ 创建重复事件"""
        
    def process_event_data(self, events):
        """✅ 处理事件数据，生成RRule实例"""
        
    def modify_recurring_event(self, events, series_id, from_time, new_rrule):
        """✅ 修改重复事件规则"""
        
    def generate_event_instances(self, main_event, start_date, end_date):
        """✅ 生成事件实例"""
```

### **第四步：前端升级计划**

#### **4.1 日历界面RRule支持**

##### **4.1.1 事件创建界面升级**
- **文件**: home.html
- **新增功能**:
  - RRule规则选择器（日/周/月/年重复）
  - 自定义重复间隔设置
  - 重复结束条件（日期/次数/永不）
  - 例外日期设置

##### **4.1.2 事件编辑界面升级**
- **新增功能**:
  - 重复事件编辑范围选择
  - 系列拆分功能
  - 单实例分离功能

##### **4.1.3 事件删除确认升级**
- **新增功能**:
  - 删除范围选择（仅此次/全部/此及之后）
  - 重复事件删除预览

#### **4.2 JavaScript模块升级**

##### **4.2.1 event-manager.js 升级**
```javascript
class EventManager {
    // 现有功能
    + createRecurringEvent(eventData, rrule)
    + updateRecurringEvent(eventId, scope, updates)
    + deleteRecurringEvent(eventId, scope)
    + showRecurrenceOptions(event)
    + handleRecurrenceEdit(event, scope)
}
```

##### **4.2.2 新增RRule组件**
```javascript
// rrule-selector.js
class RRuleSelector {
    + renderRRuleUI()
    + parseRRuleFromForm()
    + displayRRuleHumanReadable()
}

// recurring-event-modal.js  
class RecurringEventModal {
    + showEditScopeDialog()
    + showDeleteScopeDialog()
    + handleScopeSelection()
}
```

#### **4.3 UI/UX设计升级**

##### **4.3.1 重复事件视觉标识**
- 重复事件图标显示
- 系列事件颜色统一
- 主事件vs实例区分

##### **4.3.2 交互流程优化**
- 重复事件创建向导
- 编辑范围选择对话框
- 删除确认对话框

### **实施优先级**

#### **阶段一：基础RRule支持**
1. 创建`core/views_events.py`模块
2. 迁移核心Events函数 
3. 基础RRule创建功能
4. 简单前端RRule选择器

#### **阶段二：完整RRule管理**
1. 完整的Events RRule管理器
2. 复杂编辑和删除功能
3. 批量操作支持
4. 高级前端交互

#### **阶段三：增强功能**
1. 事件系列管理
2. 例外处理
3. 导入导出RRule支持
4. 性能优化