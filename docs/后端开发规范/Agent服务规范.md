# Agent 服务规范

> 现行版本：2026-07-13。Agent、Quick Action、MCP 和内部附件已在 P4/P5/P6 统一到 normalized Planner Application Service；Planner 工具不得再重写数据库 CRUD 或调用旧 View。

## 1. 架构边界

```text
Browser WebSocket → AgentConsumer → LangGraph → Planner tool adapter
Quick Action      → quick_action_agent      → Planner tool adapter
MCP stdio / HTTP  → mcp_server thin wrapper → unified planner tool
内部附件          → internal_parser         → PlannerApplicationService
                                      ↓
                  PlannerExecutionContext → PlannerApplicationService
```

LangGraph 图负责对话、工具选择、流式事件、模型配置和会话 checkpoint；Planner adapter 只负责自然语言参数、查询缓存和调用上下文，Planner 领域规则只在 `core/planner/` 实现。

## 2. 工具规范

工具第一参数保持 `config: RunnableConfig`。从 `config['configurable']` 读取 `user`、`thread_id/session_id`、`tool_call_id`、`request_id`、`planner_source`、`planner_entrypoint`，再由 `build_context()` 生成不可被模型输入覆盖的 `PlannerExecutionContext`。

```python
@tool
def create_item(config: RunnableConfig, item_type: str, title: str, ...) -> str:
    context = build_context(config)
    return create_normalized(config, item_type=item_type, title=title, ...)
```

规则：

- 工具 docstring 是模型契约，应说明类型、时间格式、重复项限制和返回语义。
- Planner 工具必须调用 `PlannerApplicationService`；不得调用 HTTP View、`core/services/*`、`UserData` 或旧 RRule manager。
- 写入必须使用服务端解析出的 `source_version` / `occurrence_ref`；不允许模型提供任意实体 ID 后盲写。
- 共享日程是只读；工具应在展示层标注，不能绕过 membership 写入。
- `@agent_transaction` 不能装饰新 Planner 工具。它仅保留给非 Planner 的旧兼容事务。

## 3. Agent Planner 查询缓存

搜索结果可在会话范围内映射为 `#序号`，但缓存只能辅助解析：

- 缓存必须保存 normalized `entity_id`、`occurrence_ref` 与 `source_version`；
- 更新/删除后失效对应缓存；
- 遇到版本冲突或找不到引用时重新搜索，不得猜测 ID；
- 不把共享只读结果当作自己的可编辑资源。

## 4. WebSocket 协议与会话

端点为 `/ws/agent/?session_id=<id>&active_tools=<comma-list>`，由 Channels `AuthMiddlewareStack` 使用浏览器 Session 认证。当前 Consumer 的客户端消息是 `message`（可带 `attachment_ids`）、`ping`、`stop`、`continue`、`check_status`；详细事件见前端 WebSocket 规范。

连接成功时服务端会确保当前会话存在一个 `AgentRollbackWindow`，并返回 `connected`（含 `session_id`、`active_tools`、消息数量）。刷新连接复用当前窗口；创建或切换会话会建立/关闭相应窗口。

会话历史、附件元数据和回滚资格必须从 `GET /api/agent/history/?session_id=` 恢复，前端本地缓存不是真实来源。

## 5. 回滚规则

- 只允许回滚当前会话、当前有效窗口、且在窗口 floor 之后的用户消息。
- `POST /api/agent/rollback/to-message/` 先恢复 eligible Planner snapshots，再截断 LangGraph checkpoint 与会话附属状态。
- 若目标消息早于窗口、窗口已关闭或 snapshot 已清理，返回 `410 rollback_window_expired` / `rollback_legacy_unsupported`。
- 若 Agent 写入后被其他入口修改，after hash 不匹配，返回 409；禁止强行覆盖。
- `/api/agent/rollback/preview/`、`/api/agent/rollback/` 以及 core 的旧 rollback URL 均为 410 tombstone。更新前的 reversion 历史不支持迁移或回滚。

## 6. 附件

- 外部文件附件经上传/云盘附件 endpoint 创建，内部日程、待办、提醒附件通过 `attachments/internal/` 和 normalized serializer 获取。
- 用户消息必须同时保存可渲染附件元数据与供模型消费的附件上下文；回滚并重新发送时应由服务端恢复 attachment IDs/metadata，不能只依赖 DOM 磁贴。
- 多模态模型可获得图片块；非多模态模型必须得到 OCR/文本结果或显式失败说明，不能静默丢弃。

## 7. Quick Action 与 MCP

Quick Action 使用 `/api/agent/quick-action/` 创建任务，随后查询 `/api/agent/quick-action/<task_id>/`、取消或列出历史。它是独立执行路径，不属于 WebSocket 回滚窗口，Planner 写入同样走 Application Service 并做 cohort/版本校验。

`mcp_server.py` 是 thin wrapper：stdio 使用启动 Token 的固定用户，HTTP 每个请求必须独立 Bearer/URL Token 认证；不得在 HTTP 请求中回退到 stdio 用户。MCP 只实现项目当前暴露的日程工具和 P5 定义的协议能力，不承诺完整 CalDAV 或任意旧 Planner API。

## 8. 上下文、Provider 与用量

- 固定工具权限、Skill 池和风格放在稳定前缀；当前时间、附件和临时上下文紧贴当前 `HumanMessage`。
- provider 差异通过 `ProviderProfile`、`ProviderNameMapper`、`OutboundMessageMaterializer`、`extract_llm_usage()` 处理；不得把 provider 专有图片或工具格式写回 canonical checkpoint。
- 请求级用量写 `AgentUsageRecord`；`UserData.agent_token_usage` 仅存月度/模型累计与摘要。
- 日志和 diagnostics 不记录 API Key、Bearer Token、完整请求正文或完整用户消息正文。
