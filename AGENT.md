# UniSchedulerSuper 开发指引

UniSchedulerSuper 是 Django + LangGraph 的日程管理系统。Planner 已完成 P1–P6 升级：日程、待办、提醒、日程组、重复规则、分享关系和 Agent Planner 写入的唯一事实源均为 normalized ORM，不再是 `UserData` JSON。

## 开始工作前

- 后端任务先读 [后端开发规范](docs/后端开发规范/index.md)。
- 前端任务先读 [前端开发规范](docs/前端开发规范/index.md)。
- API 调用与示例以 [api_examples/API_REFERENCE.md](api_examples/API_REFERENCE.md) 为准；不要依据历史 View 或旧示例推断接口。
- 修改静态资源后更新模板中的 `?v=YYYYMMDD-NNN`，并执行 `python manage.py collectstatic --noinput`（部署环境需要时）。

## 当前架构

```
core/
  models.py                 # normalized Planner ORM、cohort、legacy archive guard
  planner/                  # application、command/query、RRULE、iCalendar、snapshot/rollback
  views_planner_v2.py       # /api/v2/ Planner HTTP adapter
  views_planner_legacy.py   # Planner V1 固定 410 tombstone
agent_service/
  tools/planner_application_adapter.py  # Agent Planner → Application Service
  consumers.py              # /ws/agent/ WebSocket
  views_quick_action.py     # Quick Action
  models.py                 # AgentSession、AgentRollbackWindow、AgentTransaction
caldav_service/             # CalDAV 协议 adapter（有限能力，走 Application Service）
mcp_server.py               # MCP thin adapter（走 unified planner tools）
```

## Planner 强制约束

1. 新的 Web、Agent、Quick Action、MCP、附件、Feed、CalDAV Planner 功能必须构造 `PlannerExecutionContext`，调用 `PlannerApplicationService`；不得直接调用 View、伪造 request、或直接读写 Planner `UserData`。
2. Planner HTTP 接口只能使用 `/api/v2/`。`/get_calendar/events/`、`/events/create_event/`、旧 `/api/todos/`、旧 `/api/reminders/` 等 V1 路径已封存；认证后固定返回 `410 planner_v1_api_retired`，不得新增 fallback。
3. V2 写命令必须携带 `expected_version`（或兼容 `If-Match`）。重复项的 `single` / `future` 操作必须携带完整 `occurrence_ref`，查询必须传明确且有限的 `[from, to)`。
4. V2 不接受未知字段；应返回稳定的 `422 unsupported_field`。不要通过删除字段、重试或回退旧接口掩盖客户端错误。
5. `PlannerCohortAssignment` 决定入口可否使用 normalized 数据；`blocked` / `quarantined` 必须保持 V2 的稳定 409/423 响应，不能回落 legacy。

## Agent 回滚约束

- 只有当前 WebSocket Agent 会话的有效 `AgentRollbackWindow` 内、且本次更新后创建的 Planner 操作可回滚。
- Planner 写命令由 `PlannerSnapshotRecorder` 生成压缩聚合 before-snapshot，回滚前校验 after hash；发生后续修改时必须返回冲突，不得覆盖。
- 切换会话或关闭窗口会删除短期 Planner snapshot。旧 `django-reversion` Planner 历史和 `/api/agent/rollback/` 的 steps 协议已停用并返回 410。
- `@agent_transaction` 只可用于非 Planner 的旧兼容事务；不得把它用于新的 Planner 工具。

## 通用约束

- 日志唯一入口：`from logger import logger`；不得自行创建 `logging.getLogger(...)`。
- 不硬编码密钥、Token、密码或生产地址；使用配置管理和环境变量。
- 正规化 Planner 写入由 Application Service 在事务中处理版本、快照和 collection version；不要为其额外包 legacy `reversion` / `UserData` 快照。
- Agent 工具第一个业务参数保持 `config: RunnableConfig`，并从 `configurable` 读取用户与调用上下文。
- JS 不使用 `document.write` 加载 CDN；用户数据不得以未转义文本直接注入模板。
- 代码注释使用中文；变更完成后执行与影响范围相称的测试、`python manage.py check` 和迁移检查。

## 常用命令

```powershell
.venv\Scripts\python.exe manage.py test
.venv\Scripts\python.exe manage.py check
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
daphne -b 0.0.0.0 -p 8000 UniSchedulerSuper.asgi:application
```
