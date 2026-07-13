# 前端开发规范 · 索引

> 现行版本：2026-07-14。Planner 已完成 P6 切换；前端现代化已完成 FR-0 工程基座，浏览器端日程、待办、提醒与日程组必须使用 normalized Planner V2。

## 规范目录

| 文档 | 使用范围 |
|---|---|
| [API 调用规范](./API调用规范.md) | V2 请求、并发版本、cohort、错误处理、附件上传 |
| [JS 模块规范](./JS模块规范.md) | 原生 JS 模块、初始化、PlannerV2Client、刷新一致性 |
| [WebSocket 通信规范](./WebSocket通信规范.md) | Agent 会话、附件、流式状态、回滚窗口 |
| [模板与 CDN 规范](./模板与CDN规范.md) | 模板注入、CDN 与静态资源缓存版本 |
| [样式规范](./样式规范.md) | Bootstrap、主题变量与 Agent 用量可视化 |
| [React 工程与构建规范](./React工程与构建规范.md) | Vite 工程、Django manifest、入口开关、质量命令与发布回退 |

## 当前前端边界

- Planner 唯一入口是 `/api/v2/`；先由 `planner-v2-client.js` 调用 `/api/v2/planner/bootstrap/` 固定当前页面会话的 cohort 状态。
- 所有 Planner 请求通过 `window.plannerV2Client.request()` 或同等的 V2 包装器发送；不得新增旧 `/get_calendar/`、`/events/create_event/`、`/api/todos/` 或 `/api/reminders/` 调用。
- 旧路径返回 410 是产品预期，不得重试、静默降级或回退到 legacy JSON。
- 时间范围读取必须有有限 `from`、`to`，使用半开区间 `[from, to)`；重复项编辑必须保留服务端返回的 `occurrence_ref` 与 `source_version`。
- Agent UI 的历史、回滚资格、附件元数据以服务端 `/api/agent/history/` 为权威；`localStorage` 只能作体验缓存。

## 技术栈速查

| 层次 | 技术 |
|---|---|
| 渲染（过渡期） | Django Template + 原生 ES6 Class（默认 legacy）与 React + TypeScript + Vite（FR-0 就绪） |
| UI | Bootstrap 5、FullCalendar 6、Font Awesome |
| 实时对话 | Django Channels WebSocket |
| Planner 客户端 | `planner-v2-client.js` + `/api/v2/` |
| 构建 | 原生静态资源直接加载；React 使用 Vite hash bundle + Django manifest |

## 基础约定

1. 修改静态文件后同步更新模板 `?v=YYYYMMDD-NNN`，生产部署执行 `collectstatic`。
2. 先等待 `window.plannerV2Client.ready`，再发起 Planner 调用；bootstrap 失败时保持 fail-closed，不调用旧接口。
3. 所有写请求携带 CSRF；外部 Token 客户端使用 `Authorization: Token <token>` 且不依赖 Cookie。
4. 页面状态必须以服务端响应为准。创建、编辑、删除成功后合并服务端返回值或重新加载当前有限窗口，不能只修改本地对象。
5. React 代码只能放在 `frontend/`，通过 `FRONTEND_MODE=react` 显式启用；在 FR-8 默认切换前，`legacy` 仍是默认入口。React 不得调用原生 manager 或 legacy Planner API。
