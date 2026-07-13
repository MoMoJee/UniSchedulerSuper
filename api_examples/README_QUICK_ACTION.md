# Quick Action API

Quick Action 接受自然语言或音频，异步运行 Agent。P4 之后，它不再重写 Event/Todo/Reminder 数据库操作，而是通过统一 Planner application service 写 normalized 表；因此它与 Web V2、MCP、CalDAV 共享 ID、RRULE、scope、版本冲突和权限规则。

## 创建任务

`POST /api/agent/quick-action/`，需要 Token 或 Session 认证。

JSON 文字输入：

```json
{"text":"查询未来七天日程，不要修改数据","sync":true,"timeout":30}
```

音频输入使用 `multipart/form-data`：`audio` 文件、`sync=true|false`、`timeout=30`。文字和音频必须二选一；不能同时存在，也不能都缺少。

| 约束 | 结果 |
|---|---|
| `text` 超过 1000 字符 | `400 TEXT_TOO_LONG` |
| 音频超过 15MB或格式不支持 | `400` 对应音频错误码 |
| 语音超过 60 秒/全部识别器失败 | `422` |
| 同时传 text 与 audio | `400 AMBIGUOUS_INPUT` |

异步创建通常返回 `201` 和 `task_id`；同步完成返回 `200`。同步超时不表示后台一定取消，仍应按 `task_id` 查询最终状态。

## 查询、列表和取消

| 方法 | 路径 | 规则 |
|---|---|---|
| GET | `/api/agent/quick-action/<task_id>/` | 只能读取当前用户任务；`?wait=true` 最多长轮询约 30 秒 |
| GET | `/api/agent/quick-action/list/` | `limit` 最大 100；支持 offset/status/days |
| DELETE | `/api/agent/quick-action/<task_id>/cancel/` | 只能取消 `pending`，processing/terminal 不能取消 |

客户端必须同时检查 HTTP 状态、任务 `status` 和 `result_type`：

- `action_completed`：Agent 已完成其选择的操作；仍应检查每个 tool result。
- `need_clarification`：没有安全执行歧义操作，需要用户补充。
- `error`：不应假设产生了写入。

## 与 Planner/回滚的边界

- Quick Action 不能绕过 normalized cohort、跨用户资源权限、`expected_version` 或 recurrence scope 规则。
- 工具成功后，Web V2 读取应立即可见；失败时禁止 fallback 到 legacy JSON。
- Quick Action/MCP 不自动获得聊天消息回滚资格。Agent UI 的消息回滚只对当前会话当前 rollback window 内、由该消息产生的 snapshot 有效。
- 附件必须先创建/恢复为有效 session attachment，再随消息发送；回滚后的附件不能只在 UI 中复用旧展示对象。

## 运行示例

```powershell
.venv\Scripts\python.exe api_examples\example_quick_action_api.py
.venv\Scripts\python.exe api_examples\example_quick_action_api.py --async-mode
.venv\Scripts\python.exe api_examples\example_quick_action_api.py --audio path\to\voice.wav
```

默认指令为只读查询。传入创建/修改指令会真实写入当前账号。

**文档版本：2.0.0｜最后更新：2026-07-13**
