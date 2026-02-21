# UniSchedulerSuper - 智能日程管理系统

[![Python Version](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Django Version](https://img.shields.io/badge/django-5.1.8-green.svg)](https://www.djangoproject.com/)
[![License](https://img.shields.io/badge/license-MIT-orange.svg)](LICENSE)

基于 Django + LangGraph 的全功能 Web 日程管理系统，支持日程/提醒/待办管理、群组协作，并内置 AI Agent 对话助手。

---

## 核心特性

- **日程管理** — 单次与重复日程，完整 RRule（RFC 5545）支持（FREQ/INTERVAL/COUNT/UNTIL/BYDAY/EXDATE）
- **提醒系统** — 多优先级、延迟提醒、重复提醒，与日程/待办双向关联
- **待办事项** — 艾森豪威尔四象限法，支持依赖关系与预估时长
- **群组协作** — 多人共享日程，版本号增量同步，三级权限管理
- **AI Agent 助手** — LangGraph 驱动，WebSocket 实时对话，支持自然语言创建/查询日程、附件理解（OCR）、联网搜索
- **多模型支持** — 用户可绑定自有 API Key，系统级模型兜底，运行时切换
- **iCalendar 导入** — 兼容 Google Calendar / Outlook / Apple Calendar 导出格式
- **双认证** — Session（网页端）+ Token（API 端），提供详细 API 文档接口
- **附件系统** — 支持图片/文档上传，OCR 文字识别（Tesseract / EasyOCR）

---

## 技术栈

| 层次 | 技术 |
|------|------|
| **后端框架** | Django 5.1.8 + Django REST Framework |
| **AI Agent** | LangGraph + LangChain (ChatOpenAI compatible) |
| **WebSocket** | Django Channels + Daphne (ASGI) |
| **数据库** | SQLite（默认）/ PostgreSQL / MySQL |
| **LLM 多模型** | OpenAI / DeepSeek / Moonshot / MiniMax / Anthropic |
| **联网搜索** | Tavily |
| **MCP 工具** | langchain-mcp-adapters |
| **前端日历** | FullCalendar 6.x |
| **前端 UI** | Bootstrap 5 + 原生 JS |
| **加密存储** | AES-256-GCM（用户 API Key）|
| **日志** | concurrent_log_handler（轮转日志）|

---

## 项目结构

```
UniSchedulerSuper/
 core/                          # 核心业务：日程、提醒、待办、群组协作
    models.py                  # UserData / 群组模型 / DATA_SCHEMA 验证
    views_events.py            # EventsRRuleManager（RRule 引擎集成）
    views_reminder.py          # 提醒管理（含重复提醒）
    views_share_groups.py      # 群组协作 + 版本同步
    views_import_events.py     # iCalendar 导入
    views_token.py             # API Token 管理
    static/                    # CSS / JS（event-manager.js 等）
    templates/                 # HTML 模板（FullCalendar 主页等）

 agent_service/                 # AI Agent 服务（LangGraph）
    agent_graph.py             # Agent 图定义、工具注册、模型初始化
    consumers.py               # WebSocket Consumer
    tools/                     # Agent 工具集（日程操作、搜索等）
    attachment_handler.py      # 附件处理（OCR、图片理解）
    context_optimizer.py       # 上下文优化（Token 压缩）
    context_summarizer.py      # 长对话摘要
    quick_action_agent.py      # 快捷操作 Agent
    mcp_tools.py               # MCP 工具集成
    models.py                  # 对话记录 / 内存 / 事务模型

 config/                        # 配置管理
    api_keys_manager.py        # API Key 读取（系统模型 + 第三方服务）
    api_keys.json              # 实际配置（不入库，见 .gitignore）
    api_keys.example.json      # 配置模板
    email_manager.py           # 邮件服务配置
    email.json                 # 邮件配置（不入库）
    encryption.py              # AES-256-GCM 加密工具

 UniSchedulerSuper/             # Django 项目配置
    settings.py
    urls.py
    asgi.py                    # ASGI 入口（Channels WebSocket）
    wsgi.py

 api_examples/                  # API 调用示例代码
    example_events_api.py
    example_reminders_api.py
    example_todos_api.py
    example_eventgroups_api.py
    README.md                  # API 完整文档

 docs/                          # 设计文档
 rrule_engine.py                # RRule 重复规则引擎
 integrated_reminder_manager.py # 集成提醒管理器
 logger.py                      # 日志配置
 requirements.txt
 manage.py
```

---

## 快速开始

### 环境要求

- Python 3.12+
- Windows 10/11 或 Linux

### 安装

```bash
# 克隆项目
git clone https://github.com/MoMoJee/UniSchedulerSuper.git
cd UniSchedulerSuper

# 创建虚拟环境
python -m venv .venv

# 激活（Windows PowerShell）
.venv\Scripts\activate
# 激活（Linux / macOS）
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

> **说明**：`easyocr` 体积约 1 GB，如不需要高精度 OCR 可跳过，系统会自动降级使用 Tesseract。

### 配置

#### 1. 邮件服务（可选）

系统默认运行在**测试模式**，注册无需验证码，找回密码时验证码直接显示在页面上，无需邮件配置。如需真实邮件：

```bash
cp config/email.example.json config/email.json
# 编辑 email.json，填入 SMTP 配置
```

#### 2. AI Agent 模型配置（可选）

如需使用 AI 对话助手，配置系统模型：

```bash
cp config/api_keys.example.json config/api_keys.json
# 编辑 api_keys.json，在 system_models 字段中填入模型信息
```

`system_models` 配置示例：

```json
{
  "system_models": {
    "system_deepseek": {
      "model_name": "deepseek-chat",
      "base_url": "https://api.deepseek.com/v1",
      "api_key": "sk-...",
      "enabled": true
    }
  }
}
```

> 支持任何 OpenAI Compatible 接口。用户也可以在账户设置中绑定自己的 API Key，优先于系统模型。未配置任何模型时项目仍可正常启动，仅 AI 对话功能不可用。

如果要使用更多丰富的功能，可以参照 config/api_keys.example.json 配置其他服务，如百度云 OCR 和文档解析，以及更多 MCP 服务等

### 初始化数据库

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 启动服务

**开发模式**（不支持 WebSocket）：

```bash
python manage.py runserver
```

**推荐：Daphne ASGI**（支持 WebSocket 与 AI Agent 实时对话）：

```bash
# 收集静态文件（首次运行）
python manage.py collectstatic --noinput

# 启动
daphne -b 0.0.0.0 -p 8080 UniSchedulerSuper.asgi:application
```

### 访问

| 地址 | 说明 |
|------|------|
| `http://127.0.0.1:8000/` | Web 主界面 |
| `http://127.0.0.1:8000/admin/` | Django 管理后台 |
| `http://127.0.0.1:8000/agent/` | AI Agent 对话界面 |

---

## API 使用

系统提供完整的 RESTful API，支持 Token 认证。

### 获取 Token

```python
import requests

res = requests.post("http://127.0.0.1:8000/api/auth/login/", json={
    "username": "your_username",
    "password": "your_password"
})
token = res.json()["token"]
```

或通过 Web 界面 设置-我的-API Token 管理获取 token

### 主要端点

| 模块 | 端点前缀 |
|------|----------|
| 日程 | `/api/events/` |
| 提醒 | `/api/reminders/` |
| 待办 | `/api/todos/` |
| 日程组 | `/api/eventgroups/` |
| 群组协作 | `/api/share-groups/` |
| Token 管理 | `/api/token/` |

完整 API 文档与可运行示例：[api_examples/README.md](api_examples/README.md)

---

## AI Agent

Agent 基于 LangGraph 实现，通过 WebSocket 提供实时流式对话。

**内置工具**：
- 日程/提醒/待办的增删改查
- 联网搜索（Tavily）
- 附件理解（OCR + 图片分析）
- MCP 工具（可扩展）

**模型选择优先级**：用户自有 Key > 系统配置模型 > `DisabledLLM`（降级占位，返回提示信息）

**上下文管理**：自动压缩长对话，超出窗口时触发摘要，保持上下文连贯。

---

## 许可证

[MIT License](LICENSE)
