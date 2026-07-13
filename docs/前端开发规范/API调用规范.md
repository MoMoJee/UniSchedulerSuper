# API 调用规范

> 现行版本：2026-07-13。Planner 页面只调用 `/api/v2/`，并由 `PlannerV2Client` 固定本页面会话的 cohort 状态。

## 1. 请求基线

同源浏览器请求使用 Cookie + CSRF；所有 Planner 请求先等待 `window.plannerV2Client.ready`：

```javascript
const payload = await window.plannerV2Client.request(
    '/api/v2/todos/',
    window.plannerV2Client.jsonOptions('POST', {
        title: '整理接口文档',
        due: '2026-07-14T10:00:00+08:00',
    }),
);
```

`request()` 会带 `credentials: 'same-origin'`、解析 JSON、并将非 2xx 转为包含 `status` 与 `code` 的异常。不要对 Planner 另写一套会绕过 bootstrap 的 fetch 包装器。

外部 REST 客户端使用 `Authorization: Token <token>`；它不依赖 CSRF 或浏览器 Cookie。

## 2. Cohort 与旧接口

页面初始化会请求 `/api/v2/planner/bootstrap/`，得到每个 browser entrypoint 的 `mode`、`can_read_normalized`、`can_write_normalized`。它是当前页面会话的唯一判定来源。

- bootstrap 成功后按 V2 正常请求。
- bootstrap 失败、`blocked` 或 `quarantined` 时保持 fail-closed，继续显示 V2 的稳定错误，不调用旧接口。
- `/get_calendar/events/`、`/events/create_event/`、旧 `/api/events/bulk-edit/`、旧 `/api/todos/*`、旧 `/api/reminders/*` 与旧分享组 events 路径均已封存；认证后返回 `410 planner_v1_api_retired`。410 不是网络故障，禁止重试或 fallback。

## 3. V2 读取规则

| 目的 | 路径 |
|---|---|
| 日程实例 | `GET /api/v2/events/occurrences/?from=&to=` |
| 日程定义/系列 | `GET /api/v2/events/definitions/?from=&to=` |
| 日程冲突 | `GET /api/v2/events/conflicts/?from=&to=` |
| 日程组 | `GET /api/v2/groups/` |
| 待办 | `GET /api/v2/todos/?status=&group_id=` |
| 提醒定义 | `GET /api/v2/reminders/` |
| 提醒实例 | `GET /api/v2/reminders/?from=&to=` |
| 搜索 | `GET /api/v2/search/?q=&types=&from=&to=&page=&page_size=` |
| 分享日程 | `GET /api/v2/share-groups/<id>/occurrences/?from=&to=` |

`from`、`to` 必须同时提供且 `from < to`。所有 occurrence 窗口都是半开区间 `[from, to)`；前端不得请求“全部日程”或为无限 RRULE 伪造无限上界。

列表中的复合 `id` 仅用于渲染。修改或删除时必须保存服务端返回的完整 `occurrence_ref`，包括 `entity_id`、`series_id`、`recurrence_id`、`source_version`。

## 4. V2 写入规则

- 创建：`POST /api/v2/events/`、`/groups/`、`/todos/`、`/reminders/`。
- 更新/删除：`PATCH` / `DELETE /api/v2/<resource>/<id>/`；`expected_version` 必填，也可用兼容 `If-Match`。
- 重复 Event/Reminder 的更新、删除附带 `scope`（`single`、`future`、`all`）和需要时的 `occurrence_ref`。
- Event 的 `scope=all` 可整体调整同一当地日期的时间；不能把系列起始日期移动到另一日。日期或规则自某实例开始变化使用 `future`。
- 当前重复 Reminder 的内容/规则编辑仅支持 `scope=all`；单次提醒状态操作走 `POST /api/v2/reminders/occurrences/action/`。
- 服务器只接受文档定义的字段。收到 `422 unsupported_field` 时修正调用方，不要删除未知字段后自动重试。

示例：

```javascript
const ref = event.extendedProps.occurrence_ref;
await window.plannerV2Client.request(
    `/api/v2/events/${encodeURIComponent(ref.entity_id)}/`,
    window.plannerV2Client.jsonOptions('PATCH', {
        title: '改后的标题',
        scope: 'single',
        occurrence_ref: ref,
        expected_version: ref.source_version,
    }),
);
```

## 5. 错误与刷新

V2 成功响应按资源返回，例如 `{event: ...}`、`{todo: ...}`、`{occurrences: [...]}`，不是统一 `{status, data}` 包装。错误至少包含 `error`，领域错误还包含 `code`。

| 状态 | 前端处理 |
|---|---|
| 401 / 403 | 提示登录失效或无权限，不重试 |
| 409 `version_conflict` | 重新拉取资源/窗口，让用户确认后再提交 |
| 409 cohort 未准入 | 停止写入，展示稳定错误 |
| 410 | 旧 API 或回滚窗口已失效，不 fallback |
| 422 | 字段、RRULE、scope 或业务规则错误，保留用户输入并提示修正 |
| 423 | 历史测试账号已隔离，不提供旧路径兜底 |
| 5xx / 网络超时 | 可提供显式“重试”操作，但不得重复提交未知是否成功的写命令 |

创建、编辑、拖拽和删除成功后，合并服务端返回的 version/ref，或重新读取当前窗口；不能只修改 FullCalendar/DOM 后等待定时刷新。异步 Agent/Quick Action 完成后同样需要刷新相关 V2 数据。

## 6. 防重复与超时

同一资源写入使用提交锁；锁的 key 至少包含资源 ID 与操作类型。读取可按 `[from,to)` key 去重，但窗口变化必须取消或忽略过期响应。

对可安全取消的读取可使用 `AbortController`。写请求超时后不要盲目自动重发：先刷新目标资源，依据 version 判断服务器是否已执行。

## 7. 文件和 Agent 附件

普通文件上传使用 `FormData`，不得手动设置 `Content-Type`。Agent 附件使用 `/api/agent/attachments/*`；发送 WebSocket `message` 时传服务端 attachment ID 列表。回滚后重新发送必须使用历史接口恢复的附件元数据/ID，不能仅凭前端磁贴文本重构。
