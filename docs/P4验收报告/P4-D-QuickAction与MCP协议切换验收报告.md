# P4-D Quick Action 与 MCP 协议切换验收报告

> 验收日期：2026-07-12  
> 结论：通过。允许进入 P4-E。

## 完成内容

- Quick Action 为每次实际工具调用注入独立 `tool_call_id`，并携带 `planner_source=quick_action`、任务 request ID 与独立 session；不借用聊天回滚资格。
- MCP stdio 与 HTTP 均复用 unified Planner tools/application adapter，按 transport 注入 source、request ID、tool call ID 与隔离 session。
- MCP HTTP 用户只来自当前请求 Bearer token；禁止退回 stdio 全局用户，避免跨 transport、跨用户污染。
- ASGI 请求结束后重置 user/source/request 上下文；stdio 调用同样显式建立调用上下文。
- Quick Action 与 MCP 的 Planner 写入保持 `reversible=False`，因此有审计 ChangeSet，但不创建 Agent 聊天 rollback snapshot。

## 测试结果

| 范围 | 结果 |
|---|---|
| P4-D Quick Action/MCP 定向用例 | 4/4 通过 |
| P4-D 时全量 `core.tests + agent_service.tests` | 104/104 通过 |
| Django system check | 0 issue |
| 进程退出状态 | 0 |

关键断言：同一 Quick Action 内多个工具调用具有不同 tool call ID；Quick Action Planner 写入零 rollback snapshot；MCP stdio 创建走 application service；MCP HTTP 缺少/无效请求身份时不会读取 stdio 用户；两个 transport 都不会产生聊天回滚快照。

## P4-E 实际规划

1. internal attachment 对 normalized cohort 改用 Planner application/query，并在创建附件时固化不可变 snapshot。
2. 增加 rollback window rotate/close API；history 返回服务端 floor、window 与逐条 `can_rollback`。
3. WebSocket Agent 工具上下文绑定 active window、真实 tool call 和所属用户消息索引，使 P4-B 快照能够按消息恢复。
4. `rollback/to-message` 改走新 snapshot coordinator；旧窗口、切走会话和升级前历史统一返回 410。
5. 前端移除 localStorage 的授权职责；会话切换关闭旧窗口、切回建立新 floor，刷新复用当前 active window。

