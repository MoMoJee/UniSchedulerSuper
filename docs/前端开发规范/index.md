# 前端开发规范 · 索引

> UniSchedulerSuper 前端开发规范，基于项目现有代码约定整理。  
> 最后更新：2026-04-27

---

## 规范文档目录

| 文档 | 内容摘要 |
|------|---------|
| [JS 模块规范](./JS模块规范.md) | ES6 Class 组织方式、全局暴露、模块间通信 |
| [模板与 CDN 规范](./模板与CDN规范.md) | Django 模板结构、`_cdn_init.html`、静态文件版本号 |
| [样式规范](./样式规范.md) | Bootstrap 5 使用约定、CSS 自定义属性（主题变量）、深色模式 |
| [API 调用规范](./API调用规范.md) | `fetch` 格式、CSRF Token、错误处理 |
| [WebSocket 通信规范](./WebSocket通信规范.md) | Agent Chat WebSocket 协议、重连、消息处理 |

---

## 技术栈速查

| 层次 | 技术 |
|------|------|
| 渲染引擎 | Django 模板（服务端渲染） |
| UI 框架 | Bootstrap 5.1.3 |
| 图标库 | Font Awesome 6.0.0 |
| 日历组件 | FullCalendar（本地 `static/` 加载） |
| 数学公式 | MathJax 3.2.2 |
| JS 语言级别 | ES6（Class / async-await / 箭头函数） |
| 构建工具 | **无**（原生 JS，直接 `<script src>`） |
| CDN 策略 | BootCDN（国内）/ jsDelivr（国际）双轨竞速 |

---

## 页面 JS 模块清单

| 文件 | 全局实例名 | 职责 |
|------|-----------|------|
| `theme-manager.js` | `window.themeManager` | 主题切换（亮/暗/自定义） |
| `settings-manager.js` | `window.settingsManager` | 用户设置持久化 |
| `event-manager.js` | `window.eventManager` | 日程 CRUD + FullCalendar 集成 |
| `todo-manager.js` | `window.todoManager` | 待办 CRUD + 四象限视图 |
| `reminder-manager.js` | `window.reminderManager` | 提醒 CRUD |
| `modal-manager.js` | `window.modalManager` | 弹窗状态管理 |
| `group-manager.js` | `window.groupManager` | 日历分组管理 |
| `rrule-manager.js` | `window.rruleManager` | 重复事件规则 UI |
| `share-groups.js` | `window.shareGroupsManager` | 分享组 |
| `agent-chat.js` | `window.agentChat` | Agent WebSocket 对话 |
| `agent-config.js` | `window.agentConfig` | Agent 配置面板 |
| `agent-skills.js` | `window.agentSkills` | Agent 技能管理 |
| `quick-action.js` | `window.quickAction` | 快速操作 |
| `panel-resizer.js` | `window.panelResizer` | 面板拖拽调整 |

---

## 必备开发约定

### 1. CSRF Token 获取

模板注入全局变量（在 `<script>` 块中）：
```html
<script>
    window.CSRF_TOKEN = '{{ csrf_token }}';
</script>
```

JS 模块中使用：
```javascript
headers: { 'X-CSRFToken': window.CSRF_TOKEN }
```

### 2. 全局数据注入

后端渲染的初始数据通过模板注入 `window` 全局变量：
```html
<script>
    window.events_groups = {{ events_groups|safe }};
    window.CSRF_TOKEN = '{{ csrf_token }}';
</script>
```
**禁止**在 JS 模块中硬编码用户数据或配置。

### 3. 模块间调用

各模块实例挂载到 `window` 上，模块间通过 `window.xxx` 调用：
```javascript
// 安全调用（先检查实例存在）
if (window.eventManager) {
    window.eventManager.loadEvents();
}
```

### 4. 静态文件版本号

所有自定义静态文件引用加版本号查询参数，格式 `?v=YYYYMMDD-NNN`：
```html
<script src="{% static 'js/event-manager.js' %}?v=20260312-002"></script>
```
每次修改文件后，需同步更新模板中的版本号，触发浏览器缓存刷新。

### 5. 收集静态文件

每次修改静态文件内容后，运行命令
```bash
python manage.py collectstatic --noinput
```
