# JS 模块规范

> 现行版本：2026-07-13。前端采用无构建步骤的原生 ES6 Class；Planner 数据由 `planner-v2-client.js` 统一适配。

## 1. 模块与初始化

- 文件名使用 `kebab-case`，Class 使用 `PascalCase`，方法和字段使用 `camelCase`；内部成员以 `_` 前缀。
- 构造函数只初始化状态和 DOM 引用；网络、订阅和事件监听放入 `init()`。
- 全局模块实例挂在 `window`，调用前用可选链或存在性判断。
- 依赖顺序为：主题/设置 → modal/PlannerV2Client → Event/Group/Todo/Reminder → Agent/Quick Action。

```javascript
window.plannerV2Client = new PlannerV2Client();
await window.plannerV2Client.ready;
window.eventManager = new EventManager();
window.eventManager.init();
```

## 2. Planner 数据流

`PlannerV2Client` 是页面 Planner mode 的权威入口：它 bootstrap cohort、封装 CSRF/同源凭据、将 V2 occurrence 映射给 FullCalendar，并保留 `occurrence_ref` 与 `source_version`。

- 新代码使用其 `request()`、`jsonOptions()`、`fetchCalendar()`、`create/patch/delete` 等方法，或写同等 V2 adapter。
- 不得根据本地缓存、自行判断 cohort 或添加旧 URL fallback。
- 日程、提醒列表刷新必须使用有限时间窗口；异步响应返回时确认其窗口 key 仍是当前可见窗口。
- UI 的 `id` 不是可写资源 ID。重复操作必须通过服务端给出的 `occurrence_ref`。

## 3. 状态与缓存

- 服务端响应是资源和版本的权威来源；写入成功后合并返回对象或刷新当前窗口。
- `localStorage` 只保存轻量 UI 偏好、当前 Agent session ID 或可恢复摘要。不得持久化完整附件、base64、LLM snapshot、Planner occurrence/ref 或敏感 token。
- 大对象保存在模块内存。刷新后需要完整信息时调用 `/api/agent/history/`、`/api/agent/context-visualization/` 或相应 V2 只读接口。
- 对 `QuotaExceededError` 降级为内存，不影响当前渲染。

## 4. 异步与错误

所有请求使用 `async/await` + `try/catch`。写操作使用提交锁；读取使用 `_inFlightFetchKey` 或 `AbortController` 避免旧响应覆盖新窗口。

```javascript
async loadEvents(start, end) {
    const key = `${start.toISOString()}|${end.toISOString()}`;
    if (this._inFlightFetchKey === key) return;
    this._inFlightFetchKey = key;
    try {
        const result = await window.plannerV2Client.fetchCalendar(start, end);
        if (this._inFlightFetchKey !== key) return;
        this.applyCalendarResult(result);
    } finally {
        if (this._inFlightFetchKey === key) this._inFlightFetchKey = null;
    }
}
```

业务错误必须根据 `error.code` 区分版本冲突、410、422、423；不要把所有错误显示为“网络断开”。用户可见提示使用既有 Toast/Alert，生产代码不保留大量 `console.log()`。

## 5. DOM 与安全

- 缓存高频元素引用；监听器集中在 `init()` / `setupEventListeners()`，可选元素用 `?.addEventListener()`。
- 使用 `textContent` 或可信模板构造用户输入；禁止把原始用户文本拼入 `innerHTML`。
- 内联事件仅用于既有模板兼容场景；新增交互优先用事件监听器。
- 不用 `document.write` 注入 CDN 或脚本。

## 6. 静态资源与模块间协作

每次修改 JS/CSS 后更新模板版本号并按部署需要收集静态文件。模块间调用先验证实例存在，例如 `window.eventManager?.loadEvents()`；不要跨模块直接修改对方的内部数组，应调用公开刷新/应用方法。
