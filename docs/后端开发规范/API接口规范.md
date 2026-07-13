# API 接口规范

> 现行版本：2026-07-13。Planner 的 HTTP、Agent、Quick Action、MCP、附件、Feed 与 CalDAV 最终调用 normalized `PlannerApplicationService`。旧 Planner URL 只能明确拒绝，不能读写 `UserData` 或 fallback legacy。

## 1. 路由边界

| 类型 | 前缀 | 说明 |
|---|---|---|
| Planner REST | `/api/v2/` | Event、Group、Todo、Reminder、Search、共享 occurrence |
| Agent | `/api/agent/` | 会话、回滚、附件、Quick Action、模型与记忆 |
| 认证 | `/api/auth/` | Session/Token 管理 |
| 分享组管理 | `/api/share-groups/` | 非 Planner ownership/membership 管理 |
| Feed | `/api/calendar/feed/` | 只读 iCalendar Feed |
| CalDAV | `/caldav/` | 有限 CalDAV adapter |
| Planner V1 | 旧 `/get_calendar/`、`/events/`、`/api/todos/`、`/api/reminders/` | 认证后 `410 planner_v1_api_retired` |

新 Planner REST 接口必须放在 `/api/v2/`。不要为旧客户端新建兼容写路径；替代路径放进 410 响应的 `replacement` 和 `api_examples` 迁移表。

## 2. Adapter 规则

V2 View 只做以下工作：认证、构造 `PlannerExecutionContext`、解析有限窗口/HTTP body、调用 Application Service、映射稳定错误码。禁止：

- 直接读写 Planner `UserData`；
- 伪造 Django request 或从 Agent/Quick/MCP 调用 HTTP View；
- 在 cohort 失败或异常时调用 legacy service；
- 在 View 中实现 RRule 展开、版本覆盖或 snapshot 逻辑。

普通接口使用 `@api_view` + `IsAuthenticated` + DRF `Response`。公开 Feed 和 CalDAV 在其 protocol adapter 中自行完成认证，仍必须构造可信 context。

## 3. Planner V2 契约

### 3.1 读取

| 方法与路径 | 规则 |
|---|---|
| `GET /api/v2/planner/bootstrap/` | 返回页面 entrypoint cohort 判定；不读取业务数据 |
| `GET /api/v2/events/occurrences/` | `from`、`to` 必填，半开 `[from,to)` |
| `GET /api/v2/events/definitions/` | 同上，返回 series/master 定义 |
| `GET /api/v2/events/conflicts/` | 同上，基于 occurrence 投影 |
| `GET /api/v2/groups/` | 当前用户日程组 |
| `GET /api/v2/todos/` | 可选 `status`、`group_id` |
| `GET /api/v2/reminders/` | 不带窗口返回定义；带 `from`、`to` 返回 occurrence |
| `GET /api/v2/search/` | 有界 `from/to`，`page>=1`，`1<=page_size<=100` |
| `GET /api/v2/share-groups/<id>/occurrences/` | 有界窗口和 membership 检查 |

### 3.2 写入

| 资源 | 创建 | 更新/删除 |
|---|---|---|
| Event | `POST /api/v2/events/` | `PATCH` / `DELETE /api/v2/events/<event_id>/` |
| Group | `POST /api/v2/groups/` | `PATCH` / `DELETE /api/v2/groups/<group_id>/` |
| Todo | `POST /api/v2/todos/` | `PATCH` / `DELETE /api/v2/todos/<todo_id>/` |
| Todo 转日程 | — | `POST /api/v2/todos/<todo_id>/convert/` |
| Reminder | `POST /api/v2/reminders/` | `PATCH` / `DELETE /api/v2/reminders/<reminder_id>/` |
| Reminder instance 状态 | — | `POST /api/v2/reminders/occurrences/action/` |

每个 PATCH/DELETE/convert/action 必须提供正整数 `expected_version`，body 优先，也兼容 `If-Match`。命令 body 必须是 JSON object；不支持的字段返回 422，不能静默丢弃。

Event create 由领域服务校验完整 payload；Group、Todo、Reminder 仅接受当前 adapter 白名单字段。字段详情、示例和旧字段映射以 [api_examples/API_REFERENCE.md](../../api_examples/API_REFERENCE.md) 为准，修改实现时必须同步更新该文档和契约测试。

### 3.3 重复项

- occurrence 不是可直接写入的资源；使用 `event_id/reminder_id` + `scope` + `occurrence_ref`。
- `single` 与 `future` 需要具体 occurrence 的 `recurrence_id`；`all` 针对 master/series。
- `scope=all` Event 不允许把系列 DTSTART 换到另一当地日期，返回 `422 series_date_change_forbidden`。
- 需要分裂时领域服务可要求 `override_policy`，返回 `409 recurrence_split_requires_override_policy`；协议层不得自行选择策略。
- 重复 Reminder 目前只开放系列内容的 `all` 修改；单次状态使用 action endpoint。

## 4. 响应和错误

成功响应直接按资源组织，如 `{event: ...}`、`{occurrences: [...], count: n}`、`{groups: [...]}`，不强制历史 `{status, data}` 包装。错误响应至少为：

```json
{"error": "可读错误", "code": "stable_machine_code"}
```

| 状态 | 典型 code / 含义 |
|---|---|
| 400 | JSON、时间窗口、分页等协议参数不合法 |
| 401 / 403 | 未认证、无权限、分享组禁止 |
| 404 | 资源不存在 |
| 409 | `version_conflict`、cohort 未准入、需要分裂策略 |
| 410 | `planner_v1_api_retired`、`rollback_legacy_unsupported`、`rollback_window_expired` |
| 422 | `unsupported_field`、RRULE/scope/领域规则不合法 |
| 423 | `planner_retired_quarantine` |
| 500 | 未预期服务错误；不暴露 traceback、Token 或内部模型细节 |

`PlannerApplicationAccessError`、`PlannerCommandVersionConflict`、`PlannerCommandError`、`PlannerNotFoundError` 必须由统一 mapper 转换；不把可预期业务拒绝包装成 500。

## 5. 命名、认证和安全

- URL 使用小写连字符；资源列表用复数；兼容性动作沿用项目现有的 `/create/`、`/rename/` 等形式，不在 Planner V2 增加新动词 URL。
- Session 浏览器写请求接受 CSRF；外部 REST 用 DRF Token。Token 不写入 URL，Feed 的 URL Token 是协议例外且必须只读。
- `request.user`/认证 context 是资源归属唯一来源；请求 body 的 user、username、owner 之类字段一律忽略或拒绝。
- 记录请求 ID、资源公开 ID、稳定错误 code 可用于诊断；不得记录密码、完整 Token、附件原文或完整 LLM 上下文。

## 6. 变更要求

新增或修改接口时必须同时：更新 URL/adapter、Application Service 契约、`api_examples/API_REFERENCE.md` 与可运行示例；添加正常、鉴权、版本冲突、错误字段、重复项和 cohort 的测试。变更模型时再执行迁移；纯文档或 adapter 规则变更不得伪造无意义迁移。
