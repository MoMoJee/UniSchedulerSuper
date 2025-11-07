# 自动DDL功能说明

## 📋 功能概述

**版本**: v20251102-004  
**日期**: 2025-11-02  
**功能**: 自动将日程截止时间(DDL)设置为结束时间

## ✨ 功能描述

当用户在日历上创建新日程时,系统可以自动将日程的截止时间(DDL)设置为日程的结束时间。这个功能可以通过用户设置进行开启或关闭。

### 触发场景

自动DDL功能在以下情况下触发:

1. **拖动选择时间**: 在日历上拖动鼠标选择时间段创建日程
2. **点击空白区域**: 点击日历空白处创建日程(使用默认时长)

### 行为逻辑

- ✅ **初始设置**: 仅在打开创建日程模态框时,将DDL自动填充为结束时间
- ✅ **后续修改**: 用户在模态框中修改结束时间后,DDL不会自动跟随变化
- ✅ **用户可控**: 用户可以在设置中开启/关闭此功能
- ✅ **默认启用**: 如果用户未设置,默认启用自动DDL功能

## 🎯 实现细节

### 1. 前端设置存储 (home_new.html)

#### 页面加载时加载设置
```javascript
// 在DOMContentLoaded时立即加载用户设置到全局变量
loadUserSettingsToGlobal();

function loadUserSettingsToGlobal() {
    fetch('/get_calendar/user_settings/', {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => response.json())
    .then(settings => {
        window.userSettings = settings;
        console.log('✅ 用户设置已加载:', window.userSettings);
    })
    .catch(error => {
        // 加载失败时使用默认值
        window.userSettings = {
            auto_ddl: true,  // 默认启用
            show_weekends: true,
            calendar_view_default: 'dayGridMonth'
        };
    });
}
```

#### 保存设置时更新全局变量
```javascript
function saveUserSettings() {
    const settings = {
        auto_ddl: safeGetChecked('autoDdl', true),
        // ... 其他设置
    };
    
    fetch('/get_calendar/user_settings/', {
        method: 'POST',
        body: JSON.stringify(settings)
    })
    .then(data => {
        // 更新全局变量
        window.userSettings = settings;
        console.log('✅ 全局设置已更新');
    });
}
```

### 2. 创建日程时应用设置 (modal-manager.js)

```javascript
openCreateEventModal(startStr, endStr) {
    // 设置开始和结束时间
    document.getElementById('newEventStart').value = startStr;
    document.getElementById('newEventEnd').value = endStr;
    
    // 根据用户设置决定是否自动填充DDL
    const autoDdlEnabled = !window.userSettings || window.userSettings.auto_ddl !== false;
    
    if (autoDdlEnabled) {
        // 自动填充DDL为结束时间
        document.getElementById('creatEventDdl').value = endStr;
        console.log('自动DDL已启用: 截止时间已设置为结束时间', endStr);
    } else {
        // 保持DDL为空
        document.getElementById('creatEventDdl').value = '';
        console.log('自动DDL已禁用: 截止时间留空');
    }
}
```

### 3. 用户设置界面 (home_new.html)

设置位置: **设置 → 日程偏好**

```html
<div class="form-check form-switch">
    <input class="form-check-input" type="checkbox" id="autoDdl" checked>
    <label class="form-check-label" for="autoDdl">
        自动将日程结束时间设置为截止时间
    </label>
</div>
<small class="text-muted">
    在创建新日程时,自动将截止时间(DDL)设置为日程结束时间。
    你仍然可以在创建时手动修改。
</small>
```

### 4. 后端数据存储 (models.py)

设置存储在 `user_preference` 的 `auto_ddl` 字段:

```python
"user_preference": {
    "type": dict,
    "items": {
        "auto_ddl": {
            "type": bool,
            "nullable": True,
            "default": True,  # 默认启用
        },
        # ... 其他设置
    }
}
```

### 5. 后端API (views.py)

```python
@login_required
def user_settings(request):
    if request.method == 'GET':
        # 返回用户设置
        user_pref, created, result = UserData.get_or_initialize(
            request=request,
            new_key='user_preference'
        )
        settings = user_pref.get_value()
        return JsonResponse(settings)
    
    elif request.method == 'POST':
        # 保存用户设置
        data = json.loads(request.body)
        user_pref.set_value(data)
        return JsonResponse({'status': 'success'})
```

## 📝 使用说明

### 开启/关闭自动DDL

1. 点击右上角用户头像
2. 选择"设置"
3. 切换到"日程偏好"标签
4. 勾选/取消"自动将日程结束时间设置为截止时间"
5. 点击"保存设置"

### 使用场景示例

#### 场景1: 启用自动DDL
1. ✅ 设置已开启
2. 在日历上拖动选择 "14:00 - 16:00"
3. 打开创建模态框
4. **结果**: DDL自动填充为 "16:00"
5. 用户可以修改DDL为其他时间

#### 场景2: 禁用自动DDL
1. ❌ 设置已关闭
2. 在日历上拖动选择 "14:00 - 16:00"
3. 打开创建模态框
4. **结果**: DDL保持为空
5. 用户需要手动填写DDL

## 🔍 技术要点

### 1. 默认值处理
```javascript
// 兼容三种情况:
// 1. 设置未加载 (window.userSettings 不存在)
// 2. 设置为 undefined
// 3. 设置显式为 false

const autoDdlEnabled = !window.userSettings || window.userSettings.auto_ddl !== false;
```

### 2. 时序控制
- 页面加载时立即加载设置到全局变量
- 创建日程时读取全局变量决定行为
- 保存设置时同步更新全局变量

### 3. 向后兼容
- 如果用户从未设置过,默认启用(保持旧行为)
- 如果设置加载失败,默认启用(容错处理)

## ✅ 测试清单

- [ ] 页面加载后 `window.userSettings` 包含正确的设置
- [ ] 启用自动DDL时,创建日程DDL自动填充
- [ ] 禁用自动DDL时,创建日程DDL保持为空
- [ ] 保存设置后立即生效(无需刷新页面)
- [ ] 设置加载失败时使用默认值(启用)
- [ ] 拖动选择时间创建日程测试
- [ ] 点击空白创建日程测试

## 📊 相关文件

### 前端文件
- `core/templates/home_new.html` - 设置UI和加载逻辑
- `core/static/js/modal-manager.js` - 创建日程逻辑

### 后端文件
- `core/views.py` - 设置API接口
- `core/models.py` - 数据模型定义

### 文档文件
- `docs/自动DDL功能说明.md` - 本文档

## 🎉 版本历史

- **v20251102-004**: 完整实现自动DDL功能
  - ✅ 添加全局设置存储
  - ✅ 创建日程时根据设置决定行为
  - ✅ 设置保存/加载逻辑
  - ✅ 默认值和容错处理
  - ✅ 完整文档

## 💡 未来改进

1. **智能DDL建议**: AI根据任务类型智能建议DDL
2. **DDL模板**: 为不同类型的任务设置默认DDL偏移
3. **DDL提醒**: 接近DDL时自动创建提醒
4. **DDL统计**: 显示DDL完成率和逾期情况

---

**最后更新**: 2025-11-02  
**维护者**: UniSchedulerSuper 开发团队
