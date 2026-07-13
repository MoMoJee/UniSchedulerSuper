# 后端开发规范 · 索引

> 现行版本：2026-07-13。Planner 已完成 P1–P6：normalized ORM 与 `PlannerApplicationService` 是唯一事实源；legacy Planner JSON 只读归档且由数据库 guard 防写。

## 规范目录

| 文档 | 使用范围 |
|---|---|
| [API 接口规范](./API接口规范.md) | URL、V2 契约、错误码、cohort 与 adapter 边界 |
| [数据模型规范](./数据模型规范.md) | normalized Planner、RRule、版本、共享、archive |
| [服务层规范](./服务层规范.md) | `PlannerExecutionContext`、Application Service、事务与快照 |
| [认证与权限规范](./认证与权限规范.md) | Session、DRF Token、CalDAV Basic、资源隔离 |
| [日志与错误处理规范](./日志与错误处理规范.md) | 日志、可观测性、稳定错误响应 |
| [Agent 服务规范](./Agent服务规范.md) | WebSocket、工具、Quick Action、MCP、附件与回滚窗口 |

## 项目边界

```
core/            normalized Planner ORM、V2 HTTP、Feed、cohort/legacy guard
core/planner/    application、command/query、RRULE、iCalendar、snapshot
agent_service/   LangGraph、WebSocket、Quick Action、附件、会话/回滚窗口
caldav_service/  有限 CalDAV protocol adapter
file_service/    文件存储与解析
```

## 必备规则

- 新 Planner 代码必须走 `PlannerExecutionContext → PlannerApplicationService → normalized command/query`。
- `/api/v2/` 是唯一 Planner REST 写入口；V1 URL 已固定 410，禁止兼容回写。
- 所有 V2 写命令必须验证 `expected_version`；所有 occurrence 查询必须使用有界 `[from, to)`。
- `UserData` 仅可承载配置、用量摘要等非 Planner 兼容数据。Planner `events/todos/reminders/events_groups` 等 key 不得读写。
- Planner 回滚使用短期压缩 aggregate snapshot，不使用全量 `django-reversion` JSON 历史。
- 日志使用 `from logger import logger`，密钥和 Token 不入日志、不硬编码。
