# UniScheduler Agent 功能清单与集成方案

本文档基于现有的 `LangGraph` 架构及未来的多智能体（Multi-Agent）规划，详细列出了 Agent 的功能清单及前端集成思路，旨在为正式版开发提供指导。

## 1. 核心架构概述

我们将采用 **"Supervisor-Worker" (主管-专家)** 的分层架构，并结合 **Handoff (接管)** 模式。

*   **Supervisor (总管)**: **纯路由角色 (Pure Router)**。
    *   **职责**: 仅负责意图识别和任务分发，**不直接与用户对话**。
    *   **路由策略**: 
        *   **Handoff (接管)**: 识别出特定意图后，将控制权完全移交给专家。
        *   **Hub-and-Spoke (中转)**: 当专家 A 需要专家 B 的数据时（如日程专家需要地图数据），由主管负责中间的数据传递，专家之间不直接通信。
    *   **闲聊处理**: 遇到“你好”等通用对话，路由给 **ChatAgent**。
*   **Workers (专家)**: 专注于特定领域的 Agent。
*   **Shared Memory (共享记忆)**: 所有 Agent 共享同一套用户画像（Core Profile）和长期记忆（Memories）。

---

## 2. 功能清单 (Feature List)

### 2.1 基础对话与记忆能力 (Base Capabilities)
| 功能点 | 描述 | 当前状态 | 实现方式 |
| :--- | :--- | :--- | :--- |
| **多轮对话** | 支持上下文连贯的自然语言交互。 | ✅ 已测试 | `LangGraph` 状态管理 (`messages` 列表) |
| **自动总结** | 对话过长时自动生成摘要，防止 Token 溢出。 | ✅ 已测试 | `summarize_conversation` 节点 |
| **核心画像 (Core Profile)** | 自动提取并维护用户的常用信息（如姓名、职业、作息习惯）。 | ✅ 已测试 | `store` (Namespace: `users/{id}`, Key: `core`) |
| **细节记忆 (Memories)** | 自动存储并检索用户的具体偏好和过往经历。 | ✅ 已测试 | `store` + `search_memory` 工具 |
| **动态工具选择** | 根据用户意图动态加载相关工具，减少 Token 消耗。 | 未测试 (Router) | `select_tools_node` (未来升级为 Supervisor) |

### 2.3 辅助工具与通用能力 (Utilities & Shared Capabilities)

对于记忆搜索、网络搜索、对话总结等通用能力，不建议绑定给单一专家，而是采用 **"混合挂载" (Hybrid Mounting)** 策略。

| 工具/能力 | 归属策略 | 理由 |
| :--- | :--- | :--- |
| **记忆搜索 (search_memory)** | **全局共享 (Global)** | 几乎所有专家都需要上下文。日程专家需查偏好，闲聊专家需查经历。应默认挂载给所有 Worker。 |
| **网络搜索 (Web Search)** | **按需挂载 (On-Demand)** | 全局挂载 |
| **对话总结 (Summarization)** | **系统级节点 (System Node)** | 不属于任何 Agent。作为 Graph 中的独立节点，在每轮对话结束或 Token 阈值触发时自动运行。 |
| **当前时间 (Current Time)** | **系统提示词 (System Prompt)** | 直接注入到所有 Agent 的 System Prompt 中，无需作为工具调用。 |

#### 🤖 聊天专家 (Chat Agent)
*   **工具**: 联网搜索、记忆搜索。
*   **特性**: 
    1. **人格化 (Persona)**: 支持用户自定义人格（如“严厉的教练”、“温柔的管家”）。所有专家（包括日程、地图等）在回复时都必须遵循这一统一的人格设定，**严禁**使用“我是您的日程专家”这类机械的开场白，需保持角色的一致性和沉浸感。
    2. **兜底对话**: 只有当主管判断用户意图不属于特定业务领域时，才路由至此进行通用对话。

#### 📅 综合计划专家 (Planner Agent)
*   **职责**: 统一管理用户的时间与任务。这是最核心的业务专家，整合了日程、提醒、待办三类高频交互场景，辅以日程组（event_group）相关操作。
*   **设计理由**: 用户常在一次对话中混合操作（如“安排下午会议并提醒我带电脑”），合并可避免频繁的 Agent 切换，保证上下文连贯。
*   **工具集 (基于现有 API)**:
    *   **Calendar (日程)**:
        *   `get_events`: 获取日程列表。
        *   `create_event`: 创建日程（支持单个和重复）。
        *   `update_events`: 更新日程信息。
        *   `bulk_edit_events`: 批量编辑重复日程。
    *   **Event Groups (日程组)**:
        *   `get_events`: 获取日程列表接口也会同步附上日程组列表
        *   `create_events_group`: 创建日程组。
        *   `update_events_group`: 更新日程组信息。
        *   `delete_event_groups`: 删除日程组。
    *   **Reminder (提醒)**:
        *   `get_reminders`: 获取提醒列表。
        *   `create_reminder`: 创建提醒。
        *   `update_reminder`: 更新提醒内容。
        *   `update_reminder_status`: 更新状态（完成/忽略/延后）。
        *   `delete_reminder`: 删除提醒。
        *   `bulk_edit_reminders`: 批量编辑重复提醒。
    *   **Todo (待办)**:
        *   `get_todos`: 获取待办列表。
        *   `create_todo`: 创建待办事项。
        *   `update_todo`: 更新待办内容。
        *   `delete_todo`: 删除待办。
        *   `convert_todo_to_event`: 将待办转化为日程。
    *   **Share Groups (共享协作)（尚未完成接口测试）**:
        *   `get_my_share_groups`: 获取我的共享群组。
        *   `create_share_group`: 创建共享群组。
        *   `join_share_group`: 加入共享群组。
        *   `get_share_group_events`: 获取群组内的日程。
*   **应对策略**: 为防止工具过多导致模型混淆，需在 System Prompt 中严格定义三者边界：
    *   *Calendar*: 占用具体时间段 (Time Span)。
    *   *Reminder*: 特定时间点触发 (Time Point)。
    *   *Todo*: 任务列表，无强制时间属性 (Task List)。

#### 🗺️ 地图专家 (Map Agent)
*   **职责**: 提供地理位置服务、路径规划服务、出行规划服务等，例如用户说“明天我要去上海旅游，帮我安排”，那么地图专家先获取用户地址（可以从记忆）、查询交通方式、获取具体安排，然后交给综合计划专家
*   **工具**:
    *   `amap_search`: 地点搜索（基于高德 MCP）。
    *   `amap_weather`: 天气查询。
    *   `amap_route`: 路线规划。
    *   等十几个工具，全部从 MCP 服务器获取
    *   获取用户地区，可以从用户设置里面获取，也可以向用户发起询问（并同步修改地区设置）
*   **特性**: 能够理解“公司”、“家”等语义地址（需结合记忆专家）。

#### 🧠 记忆专家 (Memory Agent)
*   **职责**: 主动管理和检索用户记忆。注意，其功能与其他专家都可用的记忆查询功能不同，记忆专家主攻用户明确提到”记忆”相关操作的任务
*   **工具**:
    *   `search_memory`: 深度搜索过往记忆。
    *   `update_profile`: 手动修正用户画像。
    *   …… 
*   **特性**: 当 Supervisor 发现用户在询问“我以前去过哪里”时调用，可以修正、编辑、新建记忆等。

---

## 3. 前端集成方案 (Frontend Integration)

### 3.1 通信协议
*   **WebSocket**: 使用 WebSocket 实现全双工通信，支持流式输出（打字机效果）。

### 3.2 数据格式 (JSON)

**客户端发送:**
```json
{
  "type": "user_message",
  "content": "帮我看看明天下午有没有空，我想去健身",
  "session_id": "uuid-v4"
}
```

**服务端返回 (流式):**

1.  **思考中 (Status)**:
    ```json
    { "type": "status", "content": "正在查询日程..." }
    ```
2.  **工具调用 (Tool Call - 可选展示)**:
    ```json
    { "type": "tool_start", "tool": "check_availability", "input": "2025-12-14 14:00-18:00" }
    ```
3.  **文本块 (Token Stream)**:
    ```json
    { "type": "content_block", "content": "明天" }
    { "type": "content_block", "content": "下午" }
    { "type": "content_block", "content": "2点到4点" }
    { "type": "content_block", "content": "有空。" }
    ```
4.  **结束 (End)**:
    ```json
    { "type": "end" }
    ```

5.  **错误 (Error)**:
    ```json
    { "type": "error", "code": "TOKEN_EXPIRED", "message": "登录已过期，请刷新页面。" }
    ```

**连接保活与重连 (Keep-alive & Reconnect):**
*   **心跳**: 客户端每 30 秒发送 `{ "type": "ping" }`，服务端回复 `{ "type": "pong" }`。
*   **重连**: WebSocket 断开后，客户端应采用指数退避算法（Exponential Backoff）尝试重连。若重连失败超过 3 次，提示用户手动刷新。

### 3.3 UI 组件设计 (UI Component)

采用 **DeepChat** Web Component 集成到现有页面中（当前只做了一个占位的框框，没有实际功能）。

1.  **组件选型**: [DeepChat](https://deepchat.dev/)
    *   **优势**: 开箱即用，支持 Markdown、代码高亮、流式输出、WebSocket 连接。
    *   **集成**: 通过 CDN 引入 JS，使用 `<deep-chat>` 标签。

2.  **布局集成**:
    *   使用 **Bootstrap 5 Offcanvas** 组件作为侧边栏容器。
    *   在 `home.html` (或 `base.html`) 中添加悬浮按钮触发 Offcanvas。
    *   DeepChat 组件填充 Offcanvas Body，高度设为 100%。

3.  **交互式卡片 (Adaptive Cards)**:
    *   利用 DeepChat 的 `htmlResponse` 特性渲染自定义 HTML 卡片（如日程预览卡片）。
    *   当 Agent 返回特定结构数据时，前端将其转换为 HTML 字符串传给 DeepChat。
    *   当 Agent 需要确认操作（如删除日程）时，渲染 "确认/取消" 按钮。

### 3.4 API 接口定义 (API Endpoints)

为了支持前端交互，后端需提供以下接口：

#### 1. WebSocket (实时通信)
*   **URL**: `/ws/agent/chat/`
*   **功能**: 双向通信，发送用户指令，接收流式回复。
*   **鉴权**: 复用 Django Session (浏览器环境) 或 Token (App 环境)。
*   **连接参数**: `?session_id=xxx&active_experts=planner,map` (可选，用于指定会话和启用的专家)

#### 2. HTTP API (RESTful)

| 方法 | URL | 功能 | 参数/Body |
| :--- | :--- | :--- | :--- |
| **GET** | `/api/agent/sessions/` | 获取用户的会话列表 | - |
| **POST** | `/api/agent/sessions/` | 创建新会话 (清除快照) | `{ "name": "..." }` |
| **GET** | `/api/agent/history/` | 获取指定会话历史 | `?session_id=xxx` |
| **POST** | `/api/agent/rollback/preview/` | 预览回滚操作 | `{ "session_id": "..." }` |
| **POST** | `/api/agent/rollback/` | 执行回滚操作 | `{ "session_id": "...", "target_timestamp": "..." }` |
| **GET** | `/api/agent/memory/` | 查看用户画像 (Debug) | - |

*   **注意**: 切换 Session 或修改 `active_experts` 前，前端应调用 `/api/agent/sessions/` 创建新会话或明确提示用户快照将失效。

---

## 4. 后端架构与数据库实施 (Backend Architecture & Database Implementation)

### 4.1 数据库策略 (Database Strategy)

鉴于项目当前使用 SQLite 且暂无升级需求，我们将采用 **"分离存储，统一管理"** 的策略。

1.  **业务数据 (Business Data)**:
    *   **存储**: `db.sqlite3` (现有 Django 默认数据库)。
    *   **内容**: 用户信息、日程、提醒、待办、群组等核心业务数据。
    *   **变更**: 无需变更，保持现状。

2.  **Agent 状态 (Agent State / Checkpoints)**:
    *   **存储**: `agent_checkpoints.sqlite` (新增独立 SQLite 文件)。
    *   **内容**: LangGraph 的会话状态、历史消息快照。
    *   **理由**: Agent 状态读写极其频繁（每生成一个 Token 都可能触发写入），将其与业务数据库物理隔离，可避免锁竞争，提高性能。
    *   **实现**: 使用 `langgraph.checkpoint.sqlite.SqliteSaver` 连接到独立文件。

3.  **长期记忆 (Long-term Memory)**:
    *   **存储**: `db.sqlite3` (并入业务数据库)。
    *   **内容**: 用户画像 (Core Profile)、细节记忆 (Memories)。
    *   **实现**: 在 `agent_service` 应用下新增 `UserMemory` 模型。
    *   **理由**: 记忆数据与用户强关联，且读写频率低于状态数据，适合利用 Django ORM 进行管理（如 Admin 后台查看、关联查询）。

### 4.2 文件结构重组 (File Structure Reorganization)

为了支持多智能体架构，需对 `agent_service` 和 `core` 进行重构，引入 **Service Layer (服务层)** 模式。

**建议方案**: 废弃旧的 `ai_chatting`，将 Agent 相关的业务逻辑（如记忆模型、WebSocket 路由）全部整合进现有的 `agent_service` 文件夹，并将其升级为一个标准的 Django App。

```text
UniSchedulerSuper/
├── agent_service/              # [Upgrade] 升级为 Django App
│   ├── migrations/             # [New] 数据库迁移文件
│   ├── models.py               # [New] 定义 UserMemory 等模型
│   ├── apps.py                 # [New] App 配置
│   ├── admin.py                # [New] Admin 后台注册
│   ├── checkpoints/            # 存放 agent_checkpoints.sqlite
│   ├── tools/                  # 工具定义层 (Tool Wrappers)
│   │   ├── __init__.py
│   │   ├── planner_tools.py    # 综合计划专家工具 (封装 core.services)
│   │   ├── map_tools.py        # 地图专家工具 (封装 MCP Client)
│   │   └── memory_tools.py     # 记忆专家工具 (封装 ORM 操作)
│   ├── graph.py                # LangGraph 定义
│   └── ...
├── core/
│   ├── services/               # [New] 业务逻辑层 (Service Layer)
│   │   ├── __init__.py
│   │   ├── event_service.py    # 从 views_events.py 抽离的纯逻辑
│   │   ├── todo_service.py     # 从 views.py 抽离的纯逻辑
│   │   └── ...

│   ├── views.py                # 视图层 (仅负责 HTTP 请求/响应，调用 services)
│   └── ...
└── ...
```

### 4.3 综合计划专家工具实现细节 (Planner Agent Implementation)

**核心原则**: Agent **不应** 通过 HTTP 请求调用自身 API（避免死锁和性能损耗），而应直接调用 Python 函数。

1.  **第一步：抽离业务逻辑 (Refactor Views)**
    *   将 `core/views.py` 中关于创建日程、查询待办等逻辑，剥离 `request` 对象，提取为纯 Python 函数放入 `core/services/`。
    *   *Example*: `create_event(request)` -> `EventService.create_event(user, title, start_time, ...)`

2.  **第二步：封装工具 (Wrap Tools)**
    *   在 `agent_service/tools/planner_tools.py` 中，使用 `@tool` 或 `StructuredTool` 包装上述 Service 函数。
    *   **Schema 定义**: 必须为每个工具定义精确的 Pydantic 参数模型，以便 LLM 准确填充参数。

3.  **第三步：挂载 (Mount)**
    *   在 `Planner Agent` 的节点中，通过 `bind_tools` 加载这些本地 Python 工具。

4.  **关键机制：用户身份注入 (Context Injection)**
    *   **问题**: 前端用户不应手动提供 Token，Agent 工具需要知道当前操作的是哪个用户。
    *   **方案**: 利用 LangChain `RunnableConfig` 进行隐式传递。
    *   **流程**:
        1.  **Consumer**: 在 WebSocket 接收消息时，从 `scope["user"]` 获取用户对象。
        2.  **Invoke**: 调用 LangGraph 时，将用户对象放入 `config={"configurable": {"user": user}}`。
        3.  **Tool**: 工具函数参数中包含 `config: RunnableConfig`，LangChain 会自动注入配置，且**不暴露给 LLM**。
        4.  **Service**: 工具内部从 config 提取 user，调用 Service 层方法。

5.  **关键机制：操作回滚 (Transaction Rollback)**
    *   **目标**: 允许用户撤销 Agent 的任意操作（如误删日程、错误创建）。
    *   **实现**:
        *   **装饰器**: 创建 `@agent_transaction(action_type)` 装饰器，包裹所有写操作工具。
        *   **记录**: 装饰器自动开启 `reversion.create_revision()`，并在操作完成后创建 `AgentTransaction` 记录，关联 `session_id` 和 `Revision`。
        *   **恢复**: 完善 `views_rollback.py`，修复“撤销删除”逻辑（即恢复被删除的对象），并提供 API 供前端调用。

6.  **关键机制：并发控制与状态管理 (Concurrency & State Management)**
    *   **专家选择 (Expert Selection)**:
        *   允许用户在前端自定义启用的专家（如仅开启聊天，关闭规划）。
        *   Supervisor 根据 `active_experts` 列表动态过滤路由。
    *   **Planner 互斥锁 (Planner Mutex)**:
        *   允许用户多端登录，也允许多个 Agent 实例同时存在。
        *   **限制**: 同一用户同一时刻只能有一个 **开启了综合规划专家 (Planner)** 的 Agent 在运行。
        *   **实现**: 使用 Redis 或数据库锁，在 WebSocket 连接建立时检查。若检测到冲突，强制下线旧连接或拒绝新连接（针对 Planner 功能）。
    *   **回滚快照生命周期 (Snapshot Lifecycle)**:
        *   **原则**: 回滚快照 (`AgentTransaction`) 仅在当前 Session 有效。
        *   **失效场景**: 当用户 **切换 Session** 或 **修改 Planner 开关状态** 时，旧的快照将失效（无法再回滚之前的操作）。
        *   **交互**: 在执行上述操作前，前端必须弹出警告：“切换会话/修改配置将导致之前的操作无法撤销，是否继续？”

### 4.4 MCP 服务集成 (MCP Integration)

地图专家 (Map Agent) 依赖外部 MCP 服务来获取地理信息。

1.  **客户端配置**:
    *   使用 `langchain_mcp_adapters.client.MultiServerMCPClient` 连接多个 MCP 服务。
    *   **高德地图服务 (Remote SSE)**:
        *   URL: `https://mcp.amap.com/sse?key=...`
        *   Transport: `sse` (Server-Sent Events)
    *   **本地服务 (Local Stdio)**:
        *   Command: `python agent_service/mcp_server.py`
        *   Transport: `stdio` (标准输入输出)

2.  **工具加载与转换**:
    *   **异步加载**: MCP Client 默认提供异步工具 (`async def`)。
    *   **同步转换**: 由于 LangGraph 节点通常同步运行，需使用 `async_to_sync_tool` 包装器将 MCP 工具转换为同步函数，利用 `asyncio.run` 或 `concurrent.futures` 在独立线程中执行。
    *   **生命周期**: 在 Django 启动时或首次调用时初始化 Client，并缓存工具列表以提高性能。

---

## 5. 后端实现路线图 (Roadmap)

### Phase 1: 基础整合 (Current)
*   [x] 完成 `LangGraph` 基础构建。
*   [x] 实现 `Memory Store` (Core + Details)。
*   [x] 实现 `select_tools` 简单路由。
*   [ ] **Action**: 完善 WebSocket Consumer，打通前后端。

### Phase 2: 架构升级 (Supervisor-Worker)
*   [ ] **Refactor**: 实施 Service Layer 重构，抽离业务逻辑。
*   [ ] **Database**: 配置 `SqliteSaver` 和 `UserMemory` 模型。
*   [ ] **Agent**: 拆分 `Supervisor` 和 `Planner/Map/Chat` 专家。

### Phase 3: 体验优化
*   [ ] 引入 Vector Store (如 Chroma/FAISS) 替换简单的文本匹配记忆搜索。
*   [ ] 增加前端交互式卡片支持。

