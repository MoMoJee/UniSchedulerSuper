# WebSocket 通信规范

> 现行版本：2026-07-13。本文描述浏览器 Agent WebSocket；它使用 Django Session Cookie 认证，不是 REST Token API 的替代品。

## 1. 连接

```text
wss://host/ws/agent/?session_id=<sessionId>&active_tools=<comma-separated-tools>
```

- 页面在 HTTPS 下使用 `wss:`，本地 HTTP 使用 `ws:`。
- `session_id` 省略时后端使用该用户默认会话 ID；新会话应先经 REST `POST /api/agent/sessions/create/` 创建。
- `active_tools` 省略时使用后端默认工具；传空字符串表示明确不启用工具。
- 当前 ASGI 使用 `AuthMiddlewareStack` 的浏览器 Session 认证。不要在 URL 中传 REST Token，也不要假设 `Authorization` header 可被浏览器 WebSocket 设置；外部自动化应使用 REST/MCP 接口，或先实现专门的 WS Token middleware。

## 2. 客户端消息

```json
{"type":"message","content":"帮我安排明天上午的会议","attachment_ids":[12,15]}
{"type":"ping"}
{"type":"stop"}
{"type":"continue"}
{"type":"check_status"}
```

`content` 不能为空。`attachment_ids` 必须来自服务端附件接口或历史恢复数据；不得伪造内部日程附件内容。正在处理上一条消息时禁用发送按钮。

## 3. 服务端事件

| type | 含义 |
|---|---|
| `connected` | 连接已建立，含 `session_id`、`active_tools`、`message_count`、会话命名状态 |
| `processing` / `stream_start` | 开始生成 |
| `stream_chunk` | 增量文本 |
| `stream_end` / `finished` | 本轮完成；以最终完整内容为准 |
| `tool_call` / `tool_result` | 工具开始与结果 |
| `naming_start` / `naming_end` | 自动命名状态 |
| `summarizing_start` / `summarizing_end` | 历史摘要状态 |
| `status_response` | `check_status` 的恢复信息 |
| `pong` / `info` / `stopped` / `error` | 心跳、提示、停止或错误 |

前端必须容忍新增字段/事件；未知事件记录开发诊断但不能使连接崩溃。

## 4. 连接与恢复

- 非主动关闭可有限次数退避重连；切换会话、页面卸载、用户主动关闭时不重连。
- 重连后发送 `check_status`，再调用 `GET /api/agent/history/?session_id=` 重建消息、附件与 rollback window；流式事件不是持久化历史。
- 不将完整会话、附件或 LLM snapshot 写入 `localStorage`。只可保存当前 session ID 和轻量 UI 状态。

## 5. 回滚窗口

连接时服务端确保当前会话存在 active rollback window。历史返回的每条用户消息包含 `can_rollback`，只有该标记为真时显示按钮。

点击回滚调用：

```json
POST /api/agent/rollback/to-message/
{"session_id":"...","message_index":42}
```

成功后重新请求 history 和相关 Planner V2 数据；回填消息内容及附件后，用户重新发送时必须传回恢复后的 `attachment_ids`。返回 410 表示窗口已过期、关闭或旧历史不支持，返回 409 表示相关 Planner 对象被后续修改，二者都不能通过重试绕过。

## 6. UI 状态

`isConnected`、`isProcessing`、`isStreamingActive`、`sessionId`、`activeTools`、`rollbackWindow` 应由事件和 history 响应共同维护。收到 `error`、断开或回滚完成时必须解除发送/停止按钮的中间状态，避免页面长期显示“无法连接”或“处理中”。
