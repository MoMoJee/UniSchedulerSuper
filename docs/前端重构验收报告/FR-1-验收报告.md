# FR-1 类型化 API、DTO 映射、错误模型与查询核心验收报告

> 验收日期：2026-07-14  
> 结论：**通过**。React 入口仍保持 `FRONTEND_MODE=legacy` 默认值；本阶段没有对真实 Planner 数据发起写入，也没有变更任何 P1–P6 数据模型或接口语义。

## 1. 交付范围

| 领域 | 实现 | 关键约束 |
| --- | --- | --- |
| HTTP transport | `frontend/src/api/http.ts`、`errors.ts` | 同源绝对路径、Cookie、`X-CSRFToken`、`X-Request-ID`、JSON/FormData、`AbortSignal`、结构化 `ApiError`。取消不会被误报成网络错误。 |
| Planner V2 | `planner.ts`、`contracts.ts`、`mappers.ts` | 所有 Planner 路径均为 `/api/v2/...`；创建/更新/删除按动作命名；更新强制 `expected_version`，single/future 强制服务器 `occurrence_ref`。 |
| 范围语义 | `planner.ts` | 前端领域值是 `single / future / all`；发向既有 V2 后端时将 `future` 精确转换为 `this_and_future`，不改变服务端协议。 |
| DTO / domain | `contracts.ts`、`mappers.ts`、`files.ts`、`agent.ts` | Event/Todo/Reminder/Group/Share、File、Agent Session/Message/Attachment、Quick Action 的 wire shape 与 domain 映射被定义；组件后续只消费 camelCase/domain 字段。 |
| Agent / 文件 | `agent.ts`、`files.ts` | Agent WebSocket 用判别联合覆盖 known frame；未知 frame 仅在开发环境告警并安全忽略。附件保存可提交的 `resourceId`，而非仅展示名称。 |
| Query | `queryKeys.ts`、`queryClient.ts`、`queries.ts` | 统一 query key；401/403/409/410/422/423 不重试，mutation 默认不重试。 |
| 防回归 | `scripts/check-legacy-planner.mjs` | 扫描 `frontend/src`，拦截旧 Planner URL 与 `PlannerManager`。 |

## 2. DTO 字段对照

| 服务端 wire | 前端 domain/用途 | 迁移保护 |
| --- | --- | --- |
| `event_id`、`version`、`recurrence` | Event definition/occurrence；`occurrenceRef` | ID、版本、RRULE、series/recurrence identity 不丢失。 |
| `todo_id`、`version`、`due`、`tags` | Todo summary | 不把 `todo_id` 当成 Event ID。 |
| `reminder_id`、`version`、`trigger`、`recurrence` | Reminder summary | 单次/重复的版本和 RRULE 分开保留。 |
| `group_id` / `share_group_id`、`read_only` | Group / Share group | UI 只能提示；授权仍交由服务端。 |
| File `id`、`file_url`、`parse_status` | `FileRecord` | 保留文件服务真实 ID，不把文件名当资源引用。 |
| Attachment `id`、`type`、`resource_id`、`is_deleted` | `AgentAttachment` | 可重新发送的资源引用与显示标题分离。 |

## 3. 测试与结果

环境：Windows、Node `v22.20.0`、npm `10.9.3`、Python `3.11.9`（项目 `.venv`）。HTTP 单测以 MSW 拦截网络，未请求真实 Planner。

| 命令/用例 | 结果 | 覆盖 |
| --- | --- | --- |
| `npm run typecheck`、`npm run lint`、`npm run format:check` | 通过 | strict TS、零 lint warning、格式。 |
| `npm run check:legacy-planner` | 通过 | 新源代码没有 V1 Planner URL 或 `PlannerManager`。 |
| `npm run test:unit` | 通过，12 文件 / 26 用例 | V2 range、`expected_version`、single/future ref、future wire 转换、CSRF、422 details、409、取消、错误文案、retry、DTO、附件、未知 WS frame。 |
| `npm run build` | 通过 | production manifest 与 hash 资源生成。 |
| `npm audit --registry=https://registry.npmjs.org --audit-level=high` | 通过 | 0 vulnerabilities。 |
| `manage.py check` | 通过 | 0 issue。 |
| Django shell/static 测试 | 通过，8 用例 | 登录、CSRF、React/legacy 模板、manifest、React 子路由与 legacy 404。 |
| `manage.py collectstatic --noinput` | 通过 | React manifest 及资源可被 Django 收集。 |

MSW fixture 已覆盖：正常重复 occurrence（含 `occurrence_ref`）、非法 range、409 version conflict、422 field details、附件、partial/unknown WS frame。空列表、共享投影与更多领域读取 fixture 将在 FR-3 按真实只读 UI 增加；它们没有在本阶段伪装成已完成的业务功能。

## 4. 接口与安全结论

1. 没有新增后端 API，也没有替换 V2 语义；新增的是浏览器侧的类型化调用层。
2. `410` 一律显示“已封存”，不会 fallback 到 legacy client；`423` 保留锁定语义；`409` 不自动重试或覆盖。
3. Query key 已按 Planner、Agent、File 隔离，后续 mutation 必须按方案精确失效，不能通过整页刷新隐藏不同步。
4. `FRONTEND_MODE` 继续为 `legacy`，因此这些 client 尚未对生产用户暴露写入口。

## 5. 放行与下一步

FR-1 允许进入 FR-2；FR-2 已在同一轮完成。下一步为 **FR-3 Planner 只读投影**：使用本阶段 client 读取 V2 数据，先做日历/详情/共享对照，不开放 mutation。
