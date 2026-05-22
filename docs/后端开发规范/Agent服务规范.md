# Agent 服务规范

> 本文档描述 UniSchedulerSuper `agent_service/` 的架构约定和开发规范。

---

## 1. 整体架构

Agent 服务基于 **LangGraph**（单 Agent + 多工具）模式构建：

```
前端 WebSocket ←→ consumers.py (AgentConsumer)
                        ↓
                  agent_graph.py (LangGraph StateGraph)
                        ↓
              ToolNode → tools/ 目录下的工具函数
                        ↓
              core/services/ (EventService / TodoService / ReminderService)
```

- WebSocket 连接由 `AgentConsumer`（`consumers.py`）管理。
- LangGraph `StateGraph` 定义 Agent 推理流程，通过 `SqliteSaver` 持久化对话状态。
- 每个工具函数对应一个业务操作，通过 `@tool` 装饰器注册。

---

## 2. 工具（Tool）注册规范

### 2.1 基本结构

```python
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from logger import logger

@tool
def create_item(
    config: RunnableConfig,
    item_type: Literal["event", "todo", "reminder"],
    title: str,
    start: Optional[str] = None,
    ...
) -> str:
    """
    创建日程/待办/提醒。
    
    工具描述会直接作为 LLM prompt 的一部分，必须准确、简洁。
    """
    user = _get_user_from_config(config)
    ...
    return "创建成功：{title}"  # 返回字符串，供 LLM 理解结果
```

**规则**：
- 第一个参数必须是 `config: RunnableConfig`，用于从中提取 `user` 和 `session_id`。
- 返回值为 `str`，LLM 将读取此字符串决定下一步行动。
- 函数 docstring 即工具描述，会直接传给 LLM，务必准确。

### 2.2 从 config 提取上下文

```python
def _get_user_from_config(config: RunnableConfig):
    configurable = config.get("configurable", {})
    user = configurable.get("user")
    if not user:
        raise ValueError("未找到用户信息，请确保已登录")
    return user

def _get_session_id_from_config(config: RunnableConfig) -> Optional[str]:
    configurable = config.get("configurable", {})
    # 兼容 session_id 和 thread_id（LangGraph 标准键名）
    return configurable.get("session_id") or configurable.get("thread_id")
```

### 2.3 支持事务回滚的工具

写操作工具必须使用 `@agent_transaction` 装饰器，在操作**前**保存快照：

```python
from agent_service.utils import agent_transaction

@tool
@agent_transaction(action_type="create_item")
def create_item(config: RunnableConfig, ...):
    ...
```

`@agent_transaction` 会在执行前创建 `reversion` 快照 + `AgentTransaction` 记录，  
支持通过 `/api/agent/rollback/` 回滚到任意历史状态。

---

## 3. 工具分组（TOOL_CATEGORIES）

所有工具按功能分组，在 `agent_graph.py` 中的 `TOOL_CATEGORIES` 字典注册：

| 分组 key | 显示名 | 工具 |
|---------|--------|------|
| `planner` | 日程管理 | `search_items`, `create_item`, `update_item`, `delete_item`, `check_schedule_conflicts`, `get_event_groups`, `get_share_groups`, `complete_todo` |
| `memory` | 记忆管理 | 个人信息、对话风格、工作流规则 CRUD |
| `todo` | 任务追踪 | Agent 会话级任务，非用户待办 |
| `search` | 网络搜索 | Tavily Web 搜索 |
| `flight` | 航班查询 | VariFlight MCP |
| `map` | 地图服务 | 高德 MCP |
| `train` | 火车票 | 12306 MCP |
| `skill` | 技能管理 | 用户自定义 Agent 技能 |
| `cloud_file` | 云文件 | 搜索/读取云端文件 |

新增工具时：
1. 在对应 `tools/` 文件中定义 `@tool` 函数
2. 在 `agent_graph.py` 中导入并添加到对应的工具字典
3. 在 `TOOL_CATEGORIES` 中补充 `tool_descriptions` 条目

---

## 4. WebSocket 通信协议

### 4.1 连接

```
ws://host/ws/agent/?session_id=<id>
Header: Authorization: Token <token>   或通过 Session Cookie
```

### 4.2 消息格式

**客户端 → 服务端：**
```json
{"type": "message", "content": "帮我创建一个明天早上9点的会议"}
{"type": "ping"}
{"type": "stop"}
{"type": "check_status"}
```

**服务端 → 客户端：**
```json
{"type": "stream_start"}
{"type": "stream_chunk", "content": "好的"}
{"type": "stream_end", "content": "完整消息", "finished": true}
{"type": "tool_call", "name": "create_item", "args": {...}}
{"type": "tool_result", "name": "create_item", "result": "创建成功"}
{"type": "error", "message": "错误信息"}
{"type": "pong"}
{"type": "stopped"}
{"type": "connected"}
```

### 4.3 AgentConsumer 关键约定

- `self.user` — 认证用户
- `self.session_id` — 当前对话会话 ID（也是 LangGraph `thread_id`）
- `self.active_tools` — 本次对话启用的工具列表
- `self.should_stop` — 停止标志，收到 `stop` 消息时置 True
- 流式输出：`stream_start` → 多个 `stream_chunk` → `stream_end`

---

## 5. 会话（Session）管理

| 接口 | 说明 |
|------|------|
| `GET /api/agent/sessions/` | 列出用户所有会话 |
| `POST /api/agent/sessions/create/` | 创建新会话 |
| `DELETE /api/agent/sessions/<id>/` | 删除会话 |
| `POST /api/agent/sessions/<id>/rename/` | 重命名会话 |

会话 ID 格式：`user_{user_id}_{uuid4_hex[:8]}`  
会话状态存储在 `AgentSession` Django 模型 + LangGraph SQLite checkpointer 双重持久化。

---

## 6. Quick Action（快速操作）

Quick Action 允许非对话方式快速触发 Agent 操作（如语音转文字后直接执行）：

```
POST /api/agent/quick-action/
Body: {"instruction": "...", "active_tools": ["planner"]}
Response: {"task_id": "<uuid>"}

GET /api/agent/quick-action/<task_id>/
Response: {"status": "completed", "result": "..."}
```

Quick Action 在独立线程中执行，不占用 WebSocket 连接。

---

## 7. 上下文优化

`context_optimizer.py` 负责在请求 LLM 前压缩上下文：

- `ConversationSummarizer`：超过阈值后自动总结历史对话
- `ToolMessageCompressor`：压缩过长的工具调用结果
- Token 计算：优先使用 LLM 返回的实际 token 数，回退到估算（`actual` > `tiktoken` > `estimate`）

Token 快照存储在 `AgentSession.token_snapshots`，用于上下文用量可视化。
