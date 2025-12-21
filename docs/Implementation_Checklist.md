# UniScheduler Agent 升级实施清单

本文档基于 `docs/Agent_Integration_Plan.md`，用于追踪开发进度。

## Phase 1: 后端基础建设 (Backend Foundation)

### 1.1 应用与模型配置
- [ ] **App 配置**: 确认 `agent_service` 已注册到 `INSTALLED_APPS`。
- [ ] **数据库模型**:
    - [ ] 确认 `UserMemory` 和 `MemoryItem` 模型定义 (`agent_service/models.py`)。
    - [ ] 执行 `makemigrations` 和 `migrate`。
- [ ] **状态存储**: 确认 `agent_service/checkpoints/` 目录存在。

### 1.2 Service Layer 重构 (核心业务抽离)
将业务逻辑从 View 中剥离，改为纯 Python 函数，供 View 和 Agent 共用。
- [ ] **Event Service**:
    - [ ] 创建 `core/services/event_service.py`。
    - [ ] 迁移 `create_event`, `update_event`, `delete_event`, `get_events` 逻辑。
- [ ] **Todo Service**:
    - [ ] 创建 `core/services/todo_service.py`。
    - [ ] 迁移 `create_todo`, `update_todo`, `delete_todo`, `get_todos` 逻辑。
- [ ] **Reminder Service**:
    - [ ] 创建 `core/services/reminder_service.py`。
    - [ ] 迁移提醒相关逻辑。

## Phase 2: Agent 核心实现 (Agent Core)

### 2.1 工具封装 (Tool Wrappers)
- [x] **回滚装饰器**:
    - [x] 创建 `agent_service/utils.py`。
    - [x] 实现 `@agent_transaction` 装饰器 (自动记录 Revision 和 AgentTransaction)。
- [x] **Planner Tools**:
    - [x] 创建 `agent_service/tools/planner_tools.py`。
    - [x] 封装 Service 函数为 LangChain Tools，并应用 `@agent_transaction`。
- [x] **Memory Tools**:
    - [x] 创建 `agent_service/tools/memory_tools.py` (CRUD UserMemory)。
- [x] **MCP Tools**:
    - [x] 完善 `agent_service/mcp_tools.py`，确保异步转同步逻辑稳定。

### 2.2 LangGraph 构建
- [x] **State 定义**: 定义 `AgentState` (messages, next, active_experts)。
- [x] **Supervisor 节点**: 实现路由逻辑 (支持 `active_experts` 过滤)。
- [x] **Worker 节点**:
    - [x] Planner Agent (绑定 Planner Tools)。
    - [x] Map Agent (绑定 MCP Tools)。
    - [x] Chat Agent (绑定 Memory Tools + 联网)。
- [x] **Graph 组装**: 连接节点，配置 `MemorySaver` Checkpointer。
- [x] **基本测试**: 验证对话、工具调用、路由功能正常。

## Phase 3: API 与通信 (API & Communication)

### 3.1 WebSocket 升级
- [x] **Consumer 改造** (`agent_service/consumers.py`):
    - [x] 解析 URL 参数 `active_experts`。
    - [x] 实现 Context Injection (注入 `user` 到 `config`)。
    - [x] 实现心跳 (Ping/Pong) 和错误处理。
    - [ ] 实现 Planner 互斥锁 (可选，简单版可先跳过)。
- [x] **ASGI 配置** (`UniSchedulerSuper/asgi.py`):
    - [x] 配置 ProtocolTypeRouter (HTTP + WebSocket)
    - [x] 配置 AuthMiddlewareStack
- [x] **路由配置** (`agent_service/routing.py`):
    - [x] `ws/agent/` 基础版
    - [x] `ws/agent/stream/` 流式版
- ⚠️ **注意**: 需要安装 `daphne` 才能在生产环境运行

### 3.2 REST API 实现
- [x] **Session 管理**:
    - [x] `GET /api/agent/sessions/` - 列出用户会话
    - [x] `POST /api/agent/sessions/create/` - 新建会话
- [x] **历史与回滚**:
    - [x] `GET /api/agent/history/` - 获取会话历史
    - [x] `POST /api/agent/rollback/preview/` - 预览回滚
    - [x] `POST /api/agent/rollback/` - 执行回滚
- [x] **其他 API**:
    - [x] `GET /api/agent/experts/` - 获取可用专家列表
    - [x] `GET /api/agent/health/` - 健康检查

### 3.3 持久化 Checkpointer
- [ ] 把当前的 MemorySaver 换成 SQLite/PostgreSQL
- ⚠️ **当前状态**: 使用 MemorySaver，重启后会话丢失

## Phase 4: 前端集成 (Frontend Integration)

### 4.1 UI 组件
- [ ] **引入 DeepChat**: 在 `base.html` 或 `home.html` 中引入 JS 库。
- [ ] **侧边栏容器**: 添加 Bootstrap Offcanvas 结构。
- [ ] **悬浮按钮**: 添加触发按钮。

### 4.2 交互逻辑
- [ ] **初始化**: 页面加载时连接 WebSocket。
- [ ] **消息处理**: 处理流式 Token、Tool Call 显示、Adaptive Cards。
- [ ] **会话管理**: 实现“新会话”按钮，处理 Session ID 存储。
- [ ] **专家开关**: 添加 UI 允许用户选择启用的专家。

## Phase 5: 测试与验证
- [ ] **单元测试**: 测试 Service Layer 函数。
- [ ] **集成测试**: 测试 WebSocket 连接和 Agent 对话。
- [ ] **回滚测试**: 验证创建->撤销流程。

## Phase 6: 配置管理与用户自定义 (高级功能)

### 6.1 用户级配置模型
- [ ] **创建 UserAgentConfig 模型**:
    - [ ] API Provider 配置 (OpenAI/DeepSeek/Claude/本地模型)
    - [ ] API Key 加密存储
    - [ ] 模型选择 (gpt-4, deepseek-chat, etc.)
    - [ ] Temperature 等参数配置
- [ ] **创建 UserExpertConfig 模型**:
    - [ ] 用户自定义专家列表
    - [ ] 每个专家的 System Prompt
    - [ ] 工具绑定配置 (可选择启用/禁用特定工具)

### 6.2 MCP 服务器管理
- [ ] **创建 MCPServerConfig 模型**:
    - [ ] 用户级 MCP 服务器配置
    - [ ] 支持添加/删除/编辑 MCP 服务器
    - [ ] 每个服务器的认证信息 (API Key, Token)
- [ ] **动态加载机制**:
    - [ ] 根据用户配置动态初始化 MCP Client
    - [ ] 缓存用户的 MCP Tools 列表

### 6.3 Graph 动态构建
- [ ] **工厂模式重构**:
    - [ ] 实现 `AgentGraphFactory.create_for_user(user)` 方法
    - [ ] 根据用户配置动态绑定 LLM
    - [ ] 根据用户配置动态构建专家节点
- [ ] **配置验证**:
    - [ ] API Key 有效性测试
    - [ ] MCP 服务器连接测试
    - [ ] 配置更新热重载

### 6.4 前端配置界面
- [ ] **设置页面**:
    - [ ] LLM 配置表单 (Provider, API Key, Model)
    - [ ] 专家管理界面 (启用/禁用, 自定义 Prompt)
    - [ ] MCP 服务器管理界面
- [ ] **配置测试工具**:
    - [ ] API Key 测试按钮
    - [ ] MCP 连接测试
    - [ ] 专家对话测试

### 6.5 安全性
- [ ] **敏感信息加密**:
    - [ ] 使用 Django 的 `cryptography` 加密 API Keys
    - [ ] 环境变量作为主密钥
- [ ] **权限管理**:
    - [ ] 用户只能查看/修改自己的配置
    - [ ] 管理员可查看所有用户配置（仅用于故障排查）
