# JS 模块规范

> 本文档描述 UniSchedulerSuper 前端 JavaScript 代码的组织规范。

---

## 1. 模块化模式

### 1.1 ES6 Class 单文件模块

每个功能域对应一个 `.js` 文件，包含一个 ES6 Class：

```javascript
/**
 * 事件管理模块
 * 负责日程 CRUD + FullCalendar 集成
 */
class EventManager {
    constructor() {
        this.calendar = null;
        this.events = [];
        this.groups = [];
        // 状态标记
        this._inFlightFetchKey = null;
    }

    init() {
        this.initCalendar();
        this.setupEventListeners();
    }

    // 私有方法使用下划线前缀
    _parseRangeDate(s) { ... }
}
```

**规则**：
- 文件名 `kebab-case`，Class 名 `PascalCase`，方法名 `camelCase`。
- 私有/内部方法以 `_` 开头，如 `_parseRangeDate`、`_inFlightFetchKey`。
- 构造函数只做状态初始化，I/O 操作放在 `init()` 方法。
- 不使用 ES Modules（`import/export`），无构建步骤，直接 `<script src>` 加载。

### 1.2 全局暴露

所有模块实例挂载到 `window` 对象，在 HTML 底部实例化：

```html
<script>
    // 初始化顺序：依赖项先于依赖者
    window.themeManager    = new ThemeManager();
    window.settingsManager = new SettingsManager();
    window.modalManager    = new ModalManager();
    window.eventManager    = new EventManager();
    window.todoManager     = new TodoManager();
    window.reminderManager = new ReminderManager();
    window.agentChat       = new AgentChat({{ user.id }}, window.CSRF_TOKEN);

    // 统一调用 init()
    window.themeManager.init();
    window.settingsManager.init();
    ...
</script>
```

### 1.3 初始化顺序依赖

各模块存在隐式依赖，必须按以下顺序初始化：

```
ThemeManager → SettingsManager → PanelResizer
                    ↓
ModalManager → EventManager → RRuleManager
                    ↓
             TodoManager、ReminderManager、GroupManager
                    ↓
             AgentChat（依赖 CSRF_TOKEN 和 userId）
```

---

## 2. 模块间通信

### 2.1 通过 `window.xxx` 调用

模块间调用统一通过 `window` 全局实例，**调用前先检查实例是否存在**：

```javascript
// ✅ 正确：防御性调用
if (window.eventManager) {
    window.eventManager.loadEvents();
}

// ✅ 正确：内联事件处理
<button onclick="if(window.rruleManager) window.rruleManager.updateFrequencyOptions('edit');">

// ❌ 错误：直接调用未经检查的全局变量
eventManager.loadEvents();
```

### 2.2 通过 `settingsManager` 共享状态

用户偏好设置（视图模式、过滤器、面板宽度等）通过 `SettingsManager` 持久化：

```javascript
// 读取设置
const savedMode = window.settingsManager?.settings?.todoViewMode || 'list';

// 通知设置变更（settingsManager 负责防抖和保存）
if (window.settingsManager) {
    window.settingsManager.onTodoFilterChange('priorities', selectedValues);
}
```

---

## 3. 异步操作规范

### 3.1 使用 async/await

所有 API 调用使用 `async/await`，配合 `try/catch` 处理错误：

```javascript
async loadTodos() {
    try {
        const response = await fetch('/api/todos/');
        const data = await response.json();
        this.todos = data.todos || [];
        this.renderTodos();
    } catch (error) {
        console.error('加载待办失败:', error);
    }
}
```

### 3.2 防止重复请求

通过状态标记防止同一时间内的重复 fetch：

```javascript
class EventManager {
    constructor() {
        this._inFlightFetchKey = null;  // 格式: "startISO|endISO"
    }

    async loadEvents(start, end) {
        const fetchKey = `${start}|${end}`;
        if (this._inFlightFetchKey === fetchKey) return; // 防并发重复
        this._inFlightFetchKey = fetchKey;
        try {
            ...
        } finally {
            this._inFlightFetchKey = null;
        }
    }
}
```

---

## 4. DOM 操作规范

### 4.1 元素引用缓存

构造函数中缓存频繁使用的 DOM 元素（`AgentChat` 的做法）：

```javascript
constructor() {
    this.messagesContainer = document.getElementById('agentMessages');
    this.inputField = document.getElementById('agentInput');
    this.sendBtn = document.getElementById('agentSendBtn');
}
```

### 4.2 事件监听器管理

事件监听器在 `init()` 或专属 `setupEventListeners()` 方法中集中注册：

```javascript
init() {
    this.setupEventListeners();
}

setupEventListeners() {
    document.addEventListener('click', (e) => { ... });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') this.closeAllModals();
    });
    document.getElementById('someBtn')?.addEventListener('click', () => { ... });
}
```

**注意**：使用可选链 `?.addEventListener` 防止元素不存在时报错。

---

## 5. 错误处理与日志

### 5.1 console 使用

- `console.error()` — 网络请求失败、数据解析错误等真实错误
- `console.warn()` — 非关键异常降级处理
- `console.log()` — **仅在开发调试阶段使用**，生产代码应清理（注释掉或删除）

### 5.2 用户可见错误提示

```javascript
// Bootstrap Toast 或 Alert（根据场景选择）
function showError(message) {
    // 优先使用页面已有的 toast 组件
    const toastEl = document.getElementById('errorToast');
    if (toastEl) {
        toastEl.querySelector('.toast-body').textContent = message;
        new bootstrap.Toast(toastEl).show();
    } else {
        alert(message);  // 降级处理
    }
}
```

---

## 6. 拖拽与触摸支持

- 拖拽（DnD）使用原生 HTML5 `draggable` + `dragover/drop` 事件。
- 移动端触摸滑动手势在 `calendar-touch-swipe.js` 中实现，基于 `touchstart/touchend`。
- FullCalendar 日历的触摸事件由该模块负责，不在各业务模块中重复处理。
