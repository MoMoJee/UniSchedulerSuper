你是 **UniSchedulerSuper**（USS，智能日程管理系统）的专属全栈开发智能体。

项目是一个基于 Django + LangGraph 的 AI 日程助手，支持日历/待办/提醒管理、CalDAV 协议、Agent 实时对话。

---

## 项目结构速览

```
UniSchedulerSuper/
├── core/                    ← 主业务 Django App（Events / Todos / Reminders / 认证）
│   ├── models.py            ← UserData 核心模型（所有用户数据在此）
│   ├── services/            ← 业务逻辑层（EventService / TodoService / ReminderService）
│   ├── utils/validators.py  ← @validate_body 装饰器
│   ├── views*.py            ← API 视图（按功能拆分多文件）
│   ├── urls.py              ← URL 路由注册
│   ├── templates/           ← Django 模板（home.html / _cdn_init.html 等）
│   └── static/              ← 静态文件（css/ / js/ 模块）
├── agent_service/           ← LangGraph Agent
│   ├── agent_graph.py       ← 工具注册表（TOOL_CATEGORIES / 工具字典）
│   ├── consumers.py         ← WebSocket Consumer（AgentConsumer）
│   ├── tools/               ← 工具函数（@tool + @agent_transaction）
│   ├── models.py            ← AgentSession / AgentTransaction
│   └── urls.py
├── caldav_service/          ← CalDAV RFC 4791 实现
│   └── views/               ← PROPFIND/REPORT/GET/PUT/DELETE 处理器
├── config/                  ← 全局配置、API 密钥管理
├── logger.py                ← ProjectLogger 单例（全局唯一日志入口）
├── docs/
│   ├── 后端开发规范/         ← 后端规范文档（开发前先读）
│   └── 前端开发规范/         ← 前端规范文档（开发前先读）
└── manage.py
```

---

## 开发规范

**开始任何开发任务前，先读对应的索引文档，再按需深入子规范**：

- 后端任务：先读 `docs/后端开发规范/index.md`（含完整子文档目录）
- 前端任务：先读 `docs/前端开发规范/index.md`（含完整子文档目录）

规范文档可能随项目进展更新，执行任务前先读最新版。

---

## 关键命令

```powershell
# 启动开发服务器（项目根目录，已激活 .venv）
daphne -b 0.0.0.0 -p 8000 UniSchedulerSuper.asgi:application

# 数据库迁移
python manage.py makemigrations && python manage.py migrate

# 使用虚拟环境（必须）
.venv\Scripts\python.exe
```

---

## 必须始终遵守的约束

```python
# ✅ 日志：唯一合法导入方式
from logger import logger
# ❌ 禁止
import logging; logging.getLogger(...)
```

- **绝不硬编码密钥 / API Token**（用 `config/api_keys_manager.py`）
- **所有 UserData 写操作必须包在 `reversion.create_revision()` 中**
- **`DATA_SCHEMA` 中的 `dict` 默认值只写 `{}`，不写 `{key: val}`**（防可变默认值 Bug）
- **Agent 工具第一参数必须是 `config: RunnableConfig`**
- **JS 模块禁止使用 `document.write` 注入 CDN**（详见前端规范）
- **静态文件每次修改后必须更新模板中的版本号**（格式 `?v=YYYYMMDD-NNN`）
- **注释必须用中文撰写**