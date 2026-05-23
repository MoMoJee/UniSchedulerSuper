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

### 7.1 LLM 请求快照

`AgentSession.last_llm_request_snapshot` 用于前端“上下文构建详情”。它保存最近一次用户请求对应的父子快照结构：

- 父级表示一次用户消息触发的完整 Agent 调用。
- `child_snapshots` 表示该用户请求内每一轮 LLM 调用。
- 是否属于同一父级由最近一条 `HumanMessage` 的 `parent_message_index` 判断。
- 父级 `token_stats` 必须聚合所有子调用的 `input_cache_miss_tokens`、`input_cache_hit_tokens`、`output_tokens`。
- 子级快照保留该轮真实上下文和该轮真实 token，用于排查工具循环。
- 后端接口 `/api/agent/context-visualization/` 必须能返回 `llm_request` 作为前端刷新后的兜底数据源。

注意：快照可能包含完整工具定义和长上下文，前端不得把完整快照长期写入 `localStorage`。

---

## 8. 主 Agent KV Cache 与 Provider 适配规范

主 WebSocket Agent 的上下文构建必须遵守“稳定前缀优先”的约定。真实长会话中，工具权限、Skill 池、对话风格通常近似恒定，应让这些内容稳定排在前面；秒级时间、当前轮附件、临时运行状态必须贴近对应用户消息，避免污染 provider 的 system/tool 前缀缓存。

### 8.1 消息构建规则

- `build_system_prompt()` 不得包含秒级时间戳、当前轮附件、临时请求 ID 等每轮变化内容。
- 当前时间写入 `HumanMessage.additional_kwargs['runtime_context']`，由 `OutboundMessageMaterializer` 在调用 LLM 前前缀到 user 内容。
- 附件上下文写入 `HumanMessage.additional_kwargs['attachments_context']`，历史中完整保留，直到现有压缩策略触发。
- 不要在最新 user 消息前插入 runtime `SystemMessage`。DeepSeek 在开启 `tools` 时会把 system/tool 区域作为特殊前置 prompt 处理，interleaved `SystemMessage` 会显著降低缓存命中。
- 压缩、换 provider、切换多模态能力都视为新的缓存纪元，可以接受下一轮重建缓存。

### 8.2 Provider 适配规则

- Provider 差异统一通过 `ProviderProfile`、`ProviderNameMapper`、`OutboundMessageMaterializer` 和 `extract_llm_usage()` 处理。
- DeepSeek 的稳定 user id 通过 `extra_body.user_id` 传递，格式为 `unischeduler-u{user.id}-{feature}`，例如 `-main-agent`、`-skill-selector`、`-session-namer`。
- 主 Agent、Skill Selector、会话命名器、摘要器、记忆优化器、Quick Action、冲突分析器等不同 LLM 功能调用应使用不同 suffix，避免 provider 侧缓存命名空间互相干扰。
- 工具 schema 继续通过 OpenAI-compatible `tools` 字段发送，不要为了缓存改成 system prompt 文本。
- 如果 provider 对 tool name / message name 有更严格约束，必须通过 `ProviderNameMapper` 做双向映射，工具执行前还原内部名称。

### 8.3 多模态切换规则

- Checkpoint 保存 canonical history，不保存某个 provider 专用的图片块格式。
- 多模态模型出站时必须发送 provider 支持的图片块，并确保图片 base64 可用。
- 非多模态模型出站时不得包含 `image_url` / `image` 块；图片必须 OCR 后以文本进入请求，OCR 失败要显式暴露，不得静默当作空内容。
- 模型切换时优先保证请求正确性，不以 KV Cache 命中为目标。

### 8.4 缓存观测规则

- token 统计必须记录 `input_cache_hit_tokens`、`input_cache_miss_tokens`、`cached_tokens`、`cache_hit_tokens`、`cache_miss_tokens`、`cache_hit_ratio`、`cache_source`。
- DeepSeek usage path 优先读取 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`，兼容 `prompt_tokens_details.cached_tokens`。
- Kimi/Moonshot usage path 读取 `usage.cached_tokens`，并派生 `input_cache_miss_tokens = input_tokens - cached_tokens`。
- 调试缓存问题时同时记录最终 messages hash、tools hash、provider 参数 hash、tool count 和 provider profile。不要只根据 LangGraph state 推断 provider 实际请求。

### 8.5 Provider Style 配置规则

- system model 必须通过 `style` 引用 `config/api_keys.json` 顶层 `provider_styles`。
- `provider_styles` 统一描述 request、thinking、usage、billing 四类 provider 差异。
- `ProviderProfile` 是 Agent 内部唯一展开视图，调用方读取 `style_name`、`thinking`、`usage_paths`、`billing_keys` 和展开后的 `image_block_style/tool_name_style`。
- 旧字段 `provider_style/cache_usage_style/thinking_param_style/message_format_style/image_block_style/tool_name_style` 仅作兼容回退，命中时必须 WARNING。
- 无显式 `style` 时只能按 `provider/model_name` 推断，并必须 WARNING，避免静默依赖模型名。

### 8.6 用量计费规则

- `extract_llm_usage()` 输出结构是 usage、计费、快照、明细落库的共同数据源。
- 内部计费只读取 `input_cache_miss_tokens`、`input_cache_hit_tokens`、`output_tokens`。
- `cost_per_1k_input_cache_hit` 对 system model 必须显式配置；旧 `cost_per_1k_input` 只能兼容映射为 `cost_per_1k_input_cache_miss`，命中时必须 WARNING。
- `update_token_usage()` 优先接收完整 `usage_info` dict；旧 positional 签名仅为短期兼容，命中时必须 WARNING。
- 请求级明细写入 `AgentUsageRecord`；`UserData.agent_token_usage` 只保存月度累计、模型累计和历史摘要。
- 日志和 diagnostics 不得记录 API Key、Bearer Token、完整请求正文或完整用户消息正文。
