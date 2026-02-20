# 📅 UniSchedulerSuper - 智能日程管理系统

[![Python Version](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Django Version](https://img.shields.io/badge/django-5.1.8-green.svg)](https://www.djangoproject.com/)
[![License](https://img.shields.io/badge/license-MIT-orange.svg)](LICENSE)

> 一个功能完整的 Web 日程管理系统，支持日程、提醒、待办事项管理，内置 RRule 重复规则引擎、群组协作功能和完整的 RESTful API。

---

## 📖 目录

- [项目概述](#项目概述)
- [核心特性](#核心特性)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [项目架构](#项目架构)
- [核心功能](#核心功能)
- [API 使用指南](#api-使用指南)
- [开发路线图](#开发路线图)

---

## 📋 项目概述

UniSchedulerSuper 是一个基于 Django 的现代化日程管理系统，旨在帮助个人和团队高效管理时间。系统提供直观的 Web 界面和完整的 API 接口，支持桌面、移动端和第三方应用集成。

### 为什么选择 UniSchedulerSuper？

- ✅ **完整的日程管理** - 支持单次和重复日程，内置 RRule 引擎
- ✅ **智能提醒系统** - 多种提醒类型，支持重复提醒和延迟提醒
- ✅ **待办事项管理** - 基于四象限法的优先级管理
- ✅ **群组协作** - 多人共享日程，实时同步更新
- ✅ **RESTful API** - 完整的 API 文档和示例代码
- ✅ **双认证支持** - Session（网页端）和 Token（API 端）
- ✅ **易于扩展** - 模块化设计，清晰的代码结构

---

## ✨ 核心特性

### 1. 日程管理 (Events)

- **单次日程** - 创建一次性活动和事件
- **重复日程** - 完整的 RRule 支持（每日/每周/每月/每年）
  - 支持 FREQ、INTERVAL、COUNT、UNTIL、BYDAY 等规则
  - 智能处理复杂重复模式（如"每月第二个星期一"）
  - 自动生成实例，懒加载机制
- **日程分组** - 按工作、学习、生活等分类管理
- **多维度分类** - 重要性（important/not-important）+ 紧急度（urgent/not-urgent）
- **批量编辑** - 支持编辑单个实例、整个系列、从某时间开始等模式
- **日程导入导出** - 支持 iCalendar 格式

### 2. 提醒管理 (Reminders)

- **多种提醒类型** - 通知、邮件、短信（可扩展）
- **重复提醒** - 支持与日程相同的 RRule 规则
- **灵活状态管理** - 活跃、已完成、已暂停、已忽略
- **延迟提醒** - 支持延后 15 分钟、1 小时、1 天等
- **优先级分级** - 从 critical 到 debug 五个级别

### 3. 待办事项 (TODOs)

- **四象限管理** - 基于艾森豪威尔矩阵的优先级管理
- **待办转日程** - 一键将待办转换为具体时间安排
- **预估时长** - 支持标注预估完成时间
- **依赖关系** - 支持待办之间的依赖（开发中）

### 4. 群组协作 (Share Groups)

- **多人协作** - 创建群组，邀请成员共享日程
- **权限管理** - 群主、管理员、普通成员三级权限
- **实时同步** - 版本检测机制，自动提示更新
- **只读共享** - 成员可查看但不能修改他人日程
- **成员颜色** - 每个成员可自定义颜色标识

### 5. API 支持

- **RESTful API** - 完整的 RESTful 接口设计
- **Token 认证** - 安全的 Token-based 认证机制
- **完整文档** - 详细的 API 文档和代码示例
- **示例代码** - 开箱即用的 Python 示例（见 `api_examples/`）

---

## 🛠️ 技术栈

### 后端

- **框架**: Django 5.1.8
- **API**: Django REST Framework 3.14.0
- **数据库**: SQLite（默认）/ PostgreSQL / MySQL（可选）
- **认证**: Session + Token 双认证
- **日志**: concurrent_log_handler

### 前端

- **日历组件**: FullCalendar 6.x
- **UI 框架**: Bootstrap 5 + 自定义 CSS
- **JavaScript**: 原生 JS + jQuery
- **Markdown 渲染**: marked.js + github-markdown-css

### 核心依赖

```
Django >= 5.1.8
djangorestframework >= 3.14.0
python-dateutil >= 2.8.0
icalendar
markdown
```

完整依赖见 [`requirements.txt`](requirements.txt)

---

## 🎯 项目亮点

### 1. 强大的 RRule 引擎

内置完整的 RRule 重复规则引擎，支持 iCalendar RFC 5545 标准：

- ✅ 自动查找符合条件的时间点（如"下一个周五"）
- ✅ 智能处理 EXDATE（例外日期）
- ✅ 支持 UNTIL 和 COUNT 限制
- ✅ 懒加载生成实例，性能优秀

**示例**：

```python
# 每月第二个星期一，持续 6 个月
"FREQ=MONTHLY;BYDAY=2MO;COUNT=6"

# 每周一、三、五，直到年底
"FREQ=WEEKLY;BYDAY=MO,WE,FR;UNTIL=20251231T235959"
```

### 2. 模块化设计

- **视图层分离**: `views.py`, `views_events.py`, `views_reminder.py`, `views_share_groups.py`, `views_token.py`
- **清晰的职责划分**: 每个模块专注于特定功能
- **Schema 驱动**: `DATA_SCHEMA` 定义数据验证规则，自动初始化

### 3. 群组协作的创新设计

采用"标签 + 汇总"模式，而非传统的"复制数据"模式：

```
用户A编辑日程 → 添加 shared_to_groups: ["group_work"]
    ↓
触发同步 sync_group_calendar_data()
    ↓
查询群组所有成员，提取带该标签的日程
    ↓
汇总到 GroupCalendarData（带版本号）
    ↓
用户B轮询检测版本变化 → 自动刷新
```

**优势**:
- ✅ 数据不冗余，只存一份
- ✅ 实时同步，编辑立即生效
- ✅ 版本控制，前端智能感知更新

### 4. 完整的 API 生态

提供完整的 API 调用示例（`api_examples/` 目录）：

- ✅ `example_events_api.py` - 日程管理
- ✅ `example_eventgroups_api.py` - 日程组管理  
- ✅ `example_reminders_api.py` - 提醒管理
- ✅ `example_todos_api.py` - 待办事项管理

每个示例都可以直接运行，并包含详细注释。

---

## 🚀 快速开始

### 系统要求

- **Python**: 3.12 或更高版本（推荐 3.12）
- **操作系统**: Windows 10/11 Ubuntu
- **内存**: 至少 2GB RAM

### 安装步骤

#### 1. 克隆项目

```bash
git clone https://github.com/MoMoJee/UniSchedulerSuper.git
cd UniSchedulerSuper
```

#### 2. 创建虚拟环境（推荐）

**Windows (PowerShell)**:
```powershell
python -m venv .venv
.venv\Scripts\activate
```


#### 3. 安装依赖
```bash
pip install -r requirements.txt
```

**可能遇到的问题**：

如果遇到 `OSError: [WinError 126] 找不到指定的模块` 错误（通常与 PyTorch 相关），请安装 **Microsoft Visual C++ Redistributable**：

- 下载地址: https://aka.ms/vs/16/release/vc_redist.x64.exe
- 安装后重启命令行

#### 4. 配置邮件服务（可选）

系统默认运行在**测试模式**，无需配置邮件即可使用。如需启用真实邮件发送（用户注册验证码、密码重置），请参考：

- **详细配置指南**: [docs/邮件服务配置指南.md](docs/邮件服务配置指南.md)
- **快速配置**: 
  ```bash
  cd config
  cp email.example.json email.json
  # 编辑 email.json，填入您的 SMTP 配置
  ```

**测试模式特性**：
- ✅ 验证码显示在网页上（无需邮件）
- ✅ 适合开发环境和快速测试
- ✅ 页面会显示黄色提示横幅

#### 5. 数据库迁移

```bash
python manage.py makemigrations
python manage.py migrate
```

#### 6. 创建管理员账户

```bash
python manage.py createsuperuser
```

按提示输入用户名、邮箱（可选）和密码。

**示例**:
```
Username: admin
Email address: admin@example.com
Password: ******
Password (again): ******
Superuser created successfully.
```

#### 7. 收集静态文件（仅在使用 daphne 的情况下需要）

```bash
python manage.py collectstatic --noinput
```

#### 8. 启动服务器
注意，使用 manage.py runserver 的时候，部分功能可能会不可用

```bash
python manage.py runserver
```

或使用 daphne（推荐） :

```bash
daphne -b 0.0.0.0 -p 8080 UniSchedulerSuper.asgi:application
```

**自定义地址和端口（默认开发服务器，daphne 同理不赘述）**:
```bash
# 本地访问（默认）
python manage.py runserver 127.0.0.1:8000

# 局域网访问
python manage.py runserver 0.0.0.0:8000

# 自定义端口
python manage.py runserver x.x.x.x:xxxx
```

#### 9. 访问应用

- **Web 界面**: http://127.0.0.1:8000/
- **管理后台**: http://127.0.0.1:8000/admin/
- **API 文档**: 见 [API 使用指南](api_examples/README.md)

### 快速验证

#### 测试 Web 界面

1. 打开浏览器访问 http://127.0.0.1:8000/
2. 注册新用户或使用管理员账户登录
3. 进入主页面，尝试创建第一个日程

#### 测试 API

使用 `api_examples/` 中的示例代码：

```bash
# 测试日程 API
python api_examples/example_events_api.py

# 测试提醒 API
python api_examples/example_reminders_api.py

# 测试待办 API
python api_examples/example_todos_api.py
```

**注意**：运行示例代码前，请修改文件顶部的用户名和密码配置。

---

## 🏗️ 项目架构

### 项目目录结构

```
UniSchedulerSuper/
├── core/                          # 核心应用（日程、提醒、待办、群组）
│   ├── models.py                  # 数据模型定义
│   ├── views.py                   # 主视图（用户认证、账户管理）
│   ├── views_events.py            # 日程管理视图（RRule 引擎）
│   ├── views_reminder.py          # 提醒管理视图
│   ├── views_share_groups.py      # 群组协作视图
│   ├── views_import_events.py     # 外部日历导入
│   ├── views_token.py             # API Token 管理
│   ├── forms.py                   # 表单定义（注册、登录）
│   ├── urls.py                    # URL 路由配置
│   ├── admin.py                   # Django Admin 配置
│   ├── static/                    # 静态资源
│   │   ├── css/                   # 样式文件
│   │   ├── js/                    # JavaScript 文件
│   │   │   ├── event-manager.js   # 日程管理核心逻辑
│   │   │   ├── reminder-manager.js # 提醒管理核心逻辑
│   │   │   └── todo-manager.js    # 待办管理核心逻辑
│   │   └── about.md               # 关于页面 Markdown
│   ├── templates/                 # HTML 模板
│   │   ├── index.html             # FullCalendar 主页面
│   │   ├── login.html             # 登录页面
│   │   ├── register.html          # 注册页面
│   │   ├── account.html           # 账户设置页面
│   │   └── ...
│   └── migrations/                # 数据库迁移文件
│
├── ai_chatting/                   # AI 聊天助手模块
│   ├── models.py                  # 聊天记录模型
│   ├── views.py                   # 聊天视图
│   ├── ai_responder.py            # AI 响应引擎
│   ├── urls.py                    # 路由配置
│   └── templates/                 # 聊天界面模板
│
├── planner/                       # AI 规划助手模块
│   ├── models.py                  # 规划数据模型
│   ├── views.py                   # 规划视图
│   ├── ChattingCore.py            # 对话核心逻辑
│   ├── AI_search.py               # AI 搜索功能
│   ├── LLMFunctions.py            # 大语言模型函数
│   ├── searcher.py                # 搜索引擎
│   └── templates/                 # 规划界面模板
│
├── UniSchedulerSuper/             # Django 项目配置
│   ├── settings.py                # 项目设置（数据库、中间件、应用配置）
│   ├── urls.py                    # 全局 URL 路由
│   ├── wsgi.py                    # WSGI 部署配置
│   └── asgi.py                    # ASGI 部署配置
│
├── api_examples/                  # API 使用示例代码
│   ├── example_events_api.py      # 日程 API 示例
│   ├── example_reminders_api.py   # 提醒 API 示例
│   ├── example_todos_api.py       # 待办 API 示例
│   ├── example_eventgroups_api.py # 群组 API 示例
│   ├── test_token_auth.py         # Token 认证测试
│   ├── README.md                  # API 示例文档
│   └── QUICKSTART.md              # 快速入门指南
│
├── docs/                          # 项目文档
│   ├── API_TOKEN_使用指南.md      # Token 认证详细说明
│   ├── 群组协作功能升级方案.md     # 群组功能设计文档
│   ├── Phase1-数据库模型实施完成.md
│   ├── Phase2-后端核心功能实施完成.md
│   └── Phase3-前端UI实施完成.md
│
├── utils/                         # 工具模块
│   └── utils.py                   # 通用工具函数
│
├── logs/                          # 应用日志目录
│   └── application.log.*          # 日志文件（轮转）
│
├── default_files/                 # 默认配置文件
│   ├── AI_setting.json            # AI 设置模板
│   ├── events.json                # 日程数据模板
│   └── planner.json               # 规划数据模板
│
├── manage.py                      # Django 管理脚本
├── app.py                         # 应用入口（可选）
├── rrule_engine.py                # RRule 重复规则引擎
├── integrated_reminder_manager.py # 集成提醒管理器
├── logger.py                      # 日志配置
├── requirements.txt               # Python 依赖列表
├── db.sqlite3                     # SQLite 数据库（默认）
└── README.md                      # 项目说明文档
```

### 核心组件说明

#### 1. Core 组件（核心日程管理）

**职责**：负责日程、提醒、待办事项和群组协作的核心功能。

**主要模块**：

- **models.py** - 数据模型层
  - `UserData`: 用户数据键值存储，支持 `events`、`reminders`、`todos`、`eventgroups` 等数据类型
  - `CollaborativeCalendarGroup`: 协作日程组模型
  - `GroupMembership`: 群组成员关系
  - `GroupCalendarData`: 群组聚合日程数据（version 控制实时同步）
  - `PasswordResetCode`: 密码重置验证码
  - `DATA_SCHEMA`: 数据验证模式，自动校验 JSON 数据格式

- **views.py** - 主视图控制器
  - 用户认证：`login_view()`, `register_view()`, `logout_view()`
  - 账户管理：`change_username()`, `change_password()`
  - 密码重置：`password_reset_request()`, `password_reset_confirm()`
  - 功能委托：将具体业务逻辑委托给专门的视图模块

- **views_events.py** - 日程管理引擎
  - `EventsRRuleManager` 类：封装日程管理逻辑
    - `get_events_impl()`: 获取日程（支持 RRule 展开）
    - `create_event_impl()`: 创建单次/重复日程
    - `update_event_impl()`: 更新日程（支持 this/thisAndFollowing 模式）
    - `delete_event_impl()`: 删除日程（支持 EXDATE 标记）
    - `bulk_edit_events_impl()`: 批量编辑日程
  - RRule 支持：FREQ、INTERVAL、COUNT、UNTIL、BYDAY、EXDATE
  - 懒加载机制：仅在请求时间范围内生成重复实例

- **views_reminder.py** - 提醒管理
  - `get_reminders()`: 获取提醒列表（自动生成缺失实例）
  - `create_reminder()`: 创建单次/重复提醒
  - `update_reminder()`: 更新提醒
  - `delete_reminder()`: 删除提醒（支持 EXDATE）
  - `bulk_edit_reminders()`: 批量编辑提醒
  - 支持：到期提醒、延迟提醒、重复提醒

- **views_share_groups.py** - 群组协作
  - `create_share_group()`: 创建协作群组
  - `add_group_member()`: 添加群组成员
  - `sync_group_calendar_data()`: 同步群组日程数据
  - `get_share_group_events()`: 获取群组日程（带 version 版本控制）
  - 版本检测机制：前端对比 version，增量拉取数据

- **views_token.py** - API Token 管理
  - `generate_token()`: 生成 API Token
  - `revoke_token()`: 撤销 Token
  - `list_tokens()`: 列出用户所有 Token
  - Token 认证：基于 Django 的 `Token` 模型，支持 RESTful API

- **views_import_events.py** - 外部日历导入
  - 支持 iCalendar 格式导入
  - 自动解析 `.ics` 文件
  - 转换为系统内部日程格式

**数据流**：
```
用户请求 → views.py（路由分发）→ 专门视图模块 → models.py（数据持久化）→ 返回响应
                                 ↓
                          EventsRRuleManager（日程展开）
                          ReminderManager（提醒生成）
                          GroupSyncManager（群组同步）
```

#### 2. AI Chatting 组件（AI 聊天助手）(当前弃用中)

**职责**：提供 AI 驱动的聊天交互功能，帮助用户通过对话管理日程。

**主要模块**：

- **models.py**: 聊天记录数据模型
- **ai_responder.py**: AI 响应生成引擎
- **views.py**: 聊天视图和消息处理
- **templates/**: 聊天界面模板

**与 Core 组件的关系**：
- 可调用 Core 组件的 API 创建/查询日程
- 独立的聊天数据存储
- 通过 NLP 解析用户意图，转换为日程操作

#### 3. Planner 组件（AI 规划助手）（当前弃用中）

**职责**：基于 AI 的智能规划功能，为用户提供日程建议和优化。

**主要模块**：

- **ChattingCore.py**: 对话核心逻辑
- **AI_search.py**: AI 搜索功能
- **LLMFunctions.py**: 大语言模型集成函数
- **searcher.py**: 搜索引擎实现
- **models.py**: 规划数据模型
- **views.py**: 规划视图

**与 Core 组件的关系**：
- 读取 Core 组件中的日程数据进行分析
- 生成智能规划建议
- 可通过 API 回写优化后的日程

#### 4. RRule 引擎（rrule_engine.py）

**职责**：独立的重复规则引擎，基于 RFC 5545 标准。

**核心功能**：
- 解析 RRule 字符串（如 `FREQ=WEEKLY;BYDAY=MO,WE,FR`）
- 生成重复实例（懒加载，仅生成请求范围内的实例）
- 处理 EXDATE（排除日期）
- 计算 UNTIL/COUNT 终止条件

**使用场景**：
- 在 `views_events.py` 中被 `EventsRRuleManager` 调用
- 在 `views_reminder.py` 中处理重复提醒
- 支持复杂重复模式（如"每月最后一个周五"）

#### 5. 集成提醒管理器（integrated_reminder_manager.py）

**职责**：整合提醒系统，提供统一的提醒管理接口。

**核心功能**：
- 整合日程提醒和独立提醒
- 提醒触发逻辑
- 延迟提醒处理
- 提醒通知分发

**与 Core 组件的关系**：
- 被 `views_reminder.py` 调用
- 读取 `UserData` 中的 `reminders` 数据
- 可扩展为邮件/短信提醒

### 数据流架构

```
┌─────────────────────────────────────────────────────────────┐
│                         前端层                               │
│  (FullCalendar UI + JavaScript Event/Reminder/TODO Managers) │
└───────────────┬─────────────────────────────────────────────┘
                │ HTTP/JSON
                ↓
┌─────────────────────────────────────────────────────────────┐
│                         URL 路由层                           │
│            (UniSchedulerSuper/urls.py + core/urls.py)        │
└───────────────┬─────────────────────────────────────────────┘
                │
                ↓
┌─────────────────────────────────────────────────────────────┐
│                         视图层                               │
│  ┌─────────────┬──────────────┬─────────────┬─────────────┐ │
│  │  views.py   │ views_events │views_reminder│views_share  │ │
│  │  (认证/账户)│  (日程管理)  │  (提醒管理)  │_groups.py   │ │
│  │             │              │              │ (群组协作)  │ │
│  └─────────────┴──────────────┴─────────────┴─────────────┘ │
└───────────────┬─────────────────────────────────────────────┘
                │
                ↓
┌─────────────────────────────────────────────────────────────┐
│                       业务逻辑层                             │
│  ┌──────────────────┬──────────────────┬─────────────────┐  │
│  │ EventsRRuleManager│ ReminderManager │ GroupSyncManager│  │
│  │  (RRule 引擎集成) │  (提醒生成逻辑) │  (版本控制同步) │  │
│  └──────────────────┴──────────────────┴─────────────────┘  │
│                      ↓                                       │
│           rrule_engine.py (重复规则解析)                     │
│           integrated_reminder_manager.py (提醒整合)          │
└───────────────┬─────────────────────────────────────────────┘
                │
                ↓
┌─────────────────────────────────────────────────────────────┐
│                         数据模型层                           │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  UserData (key-value 存储 + DATA_SCHEMA 验证)           ││
│  │    - events: 日程数据                                   ││
│  │    - reminders: 提醒数据                                ││
│  │    - todos: 待办数据                                    ││
│  │    - eventgroups: 日程分组                              ││
│  ├─────────────────────────────────────────────────────────┤│
│  │  CollaborativeCalendarGroup (群组协作)                  ││
│  │  GroupMembership (成员关系)                             ││
│  │  GroupCalendarData (聚合数据 + version 版本控制)        ││
│  └─────────────────────────────────────────────────────────┘│
└───────────────┬─────────────────────────────────────────────┘
                │
                ↓
┌─────────────────────────────────────────────────────────────┐
│                     数据持久化层                             │
│              SQLite / PostgreSQL / MySQL                     │
└─────────────────────────────────────────────────────────────┘
```

### 认证架构

```
┌─────────────┬─────────────┐
│  Web 端用户 │  API 用户   │
└──────┬──────┴──────┬──────┘
       │             │
       ↓             ↓
┌──────────┐  ┌─────────────┐
│ Session  │  │   Token     │
│ 认证     │  │   认证      │
│ (Cookie) │  │ (Header)    │
└─────┬────┘  └──────┬──────┘
      │              │
      └──────┬───────┘
             ↓
      ┌─────────────┐
      │ Django      │
      │ Authentication│
      │ Middleware  │
      └──────┬──────┘
             ↓
       @login_required
       @token_required
             ↓
         视图处理
```

**认证方式说明**：

1. **Session 认证**（Web 界面）
   - 用户通过登录页面输入用户名/密码
   - Django 验证后创建 Session Cookie
   - 后续请求携带 Cookie 自动认证
   - 装饰器：`@login_required`

2. **Token 认证**（API 调用）
   - 用户通过 `/api/token/generate/` 获取 Token
   - API 请求在 Header 中携带 `Authorization: Token <your_token>`
   - 服务器验证 Token 有效性
   - 装饰器：`@token_required`

### 设计模式

#### 1. 工厂模式

在 `views_events.py` 和 `views_reminder.py` 中使用工厂函数：

```python
def get_events_manager(request):
    """工厂函数：返回 EventsRRuleManager 实例"""
    return EventsRRuleManager(request)

def get_reminder_manager(request):
    """工厂函数：返回 ReminderManager 实例"""
    return ReminderManager(request)
```

**好处**：
- 统一对象创建逻辑
- 便于扩展（如未来支持多租户）
- 提高代码可测试性

#### 2. 委托模式

`views.py` 将具体业务逻辑委托给专门模块：

```python
# views.py
def get_events(request):
    """获取日程（委托给 views_events.py）"""
    from .views_events import get_events_impl
    return get_events_impl(request)
```

**好处**：
- 保持 `views.py` 简洁
- 职责分离，易于维护
- 降低模块耦合度

#### 3. Schema 驱动验证

通过 `DATA_SCHEMA` 自动验证数据格式：

```python
# models.py
DATA_SCHEMA = {
    'events': {...},  # 日程数据结构
    'reminders': {...},  # 提醒数据结构
    'todos': {...},  # 待办数据结构
}

# 保存时自动校验
def save(self, *args, **kwargs):
    validate_data(self.key, self.value, DATA_SCHEMA)
    super().save(*args, **kwargs)
```

**好处**：
- 统一数据格式
- 防止脏数据入库
- 自动生成 API 文档

---

## 🎯 核心功能

### 1. 日程管理 (Events)

日程管理是系统的核心功能，支持单次日程和基于 RRule 标准的重复日程。

#### 1.1 基本日程属性

```json
{
  "id": "evt_1234567890",
  "title": "团队周会",
  "start": "2025-11-13 14:00:00",
  "end": "2025-11-13 15:00:00",
  "description": "讨论项目进度和下周计划",
  "importance": "important",       // important|not-important
  "urgency": "urgent",              // urgent|not-urgent
  "groupID": "work_group_id",
  "location": "会议室 A",
  "status": "confirmed",            // confirmed|tentative|cancelled
  "tags": ["工作", "会议"],
  "linked_reminders": ["reminder_1", "reminder_2"],
  "shared_to_groups": ["share_group_1"]
}
```

#### 1.2 重复日程 (RRule 支持)

**支持的重复规则**：

- `FREQ`: 重复频率（DAILY|WEEKLY|MONTHLY|YEARLY）
- `INTERVAL`: 间隔（如每 2 周）
- `COUNT`: 重复次数（如重复 10 次）
- `UNTIL`: 终止日期（如 2025-12-31）
- `BYDAY`: 星期几（如 MO,WE,FR 表示周一、周三、周五）
- `BYMONTHDAY`: 每月的第几天
- `BYSETPOS`: 位置（如第二个星期一）
- `EXDATE`: 排除日期（删除特定实例）

**示例 1：每周一、三、五重复**
```json
{
  "title": "晨练",
  "start": "2025-11-13 06:30:00",
  "end": "2025-11-13 07:30:00",
  "rrule": "FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=20",
  "is_recurring": true,
  "is_main_event": true
}
```

**示例 2：每月最后一个周五**
```json
{
  "title": "月度总结会",
  "start": "2025-11-29 15:00:00",
  "end": "2025-11-29 17:00:00",
  "rrule": "FREQ=MONTHLY;BYDAY=-1FR;UNTIL=2026-12-31",
  "is_recurring": true
}
```

#### 1.3 日程操作

**创建日程**：
- **Web 界面**：点击日历空白处，填写日程表单
- **API 调用**：`POST /api/events/create/`

**编辑日程**：
- **单次日程**：直接修改
- **重复日程**：支持三种编辑模式
  - `this`：仅修改当前实例（生成分离实例）
  - `thisAndFollowing`：修改当前及后续实例（拆分系列）
  - `all`：修改整个系列

**删除日程**：
- **单次日程**：直接删除
- **重复日程**：
  - 删除单个实例：添加到 `EXDATE` 字段
  - 删除系列：删除主事件

**批量编辑**：
- `POST /api/events/bulk-edit/`
- 支持同时修改多个日程的属性

#### 1.4 日程组 (Event Groups)

将日程按类型分组管理：

```json
{
  "id": "group_work",
  "name": "工作",
  "description": "工作相关的日程",
  "color": "#FF5722",
  "type": "work"  // work|personal|study|health|social|other
}
```

**用途**：
- 按颜色区分日程类型
- 批量显示/隐藏某类日程
- 统计分析（如本周工作时间占比）

### 2. 提醒管理 (Reminders)

提醒系统支持独立提醒和重复提醒，帮助用户按时完成任务。

#### 2.1 基本提醒属性

```json
{
  "id": "rem_1234567890",
  "title": "买菜",
  "content": "晚上回家路上买菜：西红柿、鸡蛋、青菜",
  "trigger_time": "2025-11-13 18:00:00",
  "priority": "normal",  // critical|high|normal|low|debug
  "status": "active",    // active|dismissed|snoozed
  "linked_event_id": "",
  "linked_todo_id": ""
}
```

#### 2.2 提醒优先级

| 优先级 | 说明 | 使用场景 |
|--------|------|----------|
| `critical` | 紧急重要 | 截止日期、重要会议 |
| `high` | 高优先级 | 重要任务、约会 |
| `normal` | 普通 | 日常提醒 |
| `low` | 低优先级 | 非紧急事项 |
| `debug` | 调试用 | 开发测试 |

#### 2.3 提醒状态管理

- **active**：待触发状态
- **dismissed**：已忽略（用户主动关闭）
- **snoozed**：延迟提醒（设置 `snooze_until` 字段）

**延迟提醒示例**：
```json
{
  "id": "rem_123",
  "title": "开会",
  "status": "snoozed",
  "snooze_until": "2025-11-13 14:55:00"  // 5分钟后再提醒
}
```

#### 2.4 重复提醒

与日程类似，提醒也支持 RRule 重复规则：

**示例：每天早上 8 点提醒吃药**
```json
{
  "title": "吃药提醒",
  "trigger_time": "2025-11-13 08:00:00",
  "rrule": "FREQ=DAILY;COUNT=30",
  "priority": "high"
}
```

#### 2.5 提醒与日程/待办关联

通过 `linked_event_id` 和 `linked_todo_id` 关联：

```json
{
  "title": "会议提前 15 分钟提醒",
  "trigger_time": "2025-11-13 13:45:00",
  "linked_event_id": "evt_meeting_123",
  "priority": "high"
}
```

**自动生成提醒**：
- 创建日程时可同时创建提醒
- 日程的 `linked_reminders` 字段记录关联的提醒 ID

### 3. 待办事项 (TODOs)

基于艾森豪威尔矩阵（四象限法）的待办管理系统。

#### 3.1 基本待办属性

```json
{
  "id": "todo_1234567890",
  "title": "完成项目文档",
  "description": "撰写 README 和 API 文档",
  "importance": "important",      // important|not-important
  "urgency": "urgent",            // urgent|not-urgent
  "status": "pending",            // pending|in-progress|completed|cancelled
  "due_date": "2025-11-15",
  "estimated_duration": "3h",     // 预估耗时
  "groupID": "work_group",
  "priority_score": 0.85,         // AI 计算的优先级分数 (0-1)
  "tags": ["文档", "项目"],
  "dependencies": ["todo_123"],   // 依赖的待办 ID
  "linked_reminders": ["rem_456"]
}
```

#### 3.2 四象限法分类

| 象限 | importance | urgency | 说明 | 建议处理方式 |
|------|-----------|---------|------|--------------|
| 第一象限 | important | urgent | 紧急且重要 | 立即处理 |
| 第二象限 | important | not-urgent | 重要不紧急 | 计划处理 |
| 第三象限 | not-important | urgent | 紧急不重要 | 委托处理 |
| 第四象限 | not-important | not-urgent | 不紧急不重要 | 减少处理 |

**可视化展示**：
- Web 界面提供四象限视图
- 按象限自动分组显示待办事项

#### 3.3 待办状态流转

```
pending (待处理)
    ↓
in-progress (进行中)
    ↓
completed (已完成)

任意状态 → cancelled (已取消)
```

#### 3.4 依赖管理

通过 `dependencies` 字段建立待办之间的依赖关系：

```json
{
  "id": "todo_2",
  "title": "部署项目",
  "dependencies": ["todo_1"],  // 必须先完成 todo_1
  "status": "pending"
}
```

**依赖检查**：
- 前置待办未完成时，系统提示无法开始
- 可用于项目管理中的任务拆解

### 4. 群组协作 (Share Groups)

多人共享日程，支持团队协作和家庭日程管理。

#### 4.1 群组模型

**CollaborativeCalendarGroup** - 协作日程组
```python
{
  "id": "share_group_123",
  "name": "开发团队",
  "description": "技术部开发组的共享日程",
  "owner": User对象,
  "created_at": "2025-11-01 10:00:00"
}
```

**GroupMembership** - 成员关系
```python
{
  "group": CollaborativeCalendarGroup对象,
  "user": User对象,
  "role": "member",  // owner|admin|member
  "joined_at": "2025-11-01 10:05:00"
}
```

**GroupCalendarData** - 聚合日程数据
```python
{
  "group": CollaborativeCalendarGroup对象,
  "aggregated_events": [...],  // 所有成员共享的日程
  "version": 15,               // 版本号（递增）
  "last_updated": "2025-11-13 14:30:00"
}
```

#### 4.2 日程分享流程

**1. 创建群组**
```python
POST /api/share-groups/create/
{
  "name": "家庭日程",
  "description": "家庭成员共享日程"
}
```

**2. 添加成员**
```python
POST /api/share-groups/{group_id}/add-member/
{
  "username": "family_member"
}
```

**3. 分享日程到群组**
```python
# 创建或编辑日程时指定
{
  "title": "家庭聚餐",
  "shared_to_groups": ["share_group_123"]
}
```

#### 4.3 实时同步机制

**版本控制**：
- 每次群组日程变更，`GroupCalendarData.version` 递增
- 前端定期轮询，对比本地 version 与服务器 version
- 版本不一致时拉取最新数据

**增量更新流程**：
```
前端请求 → 携带当前 version
    ↓
服务器对比版本
    ↓
version 一致 → 返回 304 Not Modified
version 不一致 → 返回最新数据 + 新 version
    ↓
前端更新日历视图
```

**API 示例**：
```python
GET /api/share-groups/{group_id}/events/?version=15

# 响应
{
  "status": "success",
  "version": 15,  // 版本未变
  "needs_update": false
}

# 或者
{
  "status": "success",
  "version": 17,  // 版本已更新
  "needs_update": true,
  "events": [...]
}
```

#### 4.4 权限管理

| 角色 | 权限 |
|------|------|
| `owner` | 群组所有者，可删除群组、管理成员 |
| `admin` | 管理员，可添加/移除成员 |
| `member` | 普通成员，可查看和分享日程 |

**操作权限**：
- 分享日程：所有成员
- 添加成员：owner 和 admin
- 删除群组：仅 owner
- 退出群组：所有成员（owner 需先转移所有权）

#### 4.5 使用场景

**场景 1：团队项目管理**
- 创建"开发团队"群组
- 成员分享各自的工作日程
- 避免会议时间冲突
- 了解团队成员的工作安排

**场景 2：家庭日程协调**
- 创建"家庭"群组
- 共享孩子的课外活动、家庭聚会
- 协调家务分工时间
- 规划家庭旅行

**场景 3：课程学习小组**
- 创建"学习小组"群组
- 共享课程时间、作业截止日期
- 安排小组讨论时间
- 共享学习资源和提醒

### 5. 外部日历导入

支持导入标准 iCalendar (.ics) 格式的日程。

#### 5.1 导入流程

**Web 界面**：
1. 进入"导入日程"页面
2. 上传 `.ics` 文件
3. 预览导入内容
4. 选择目标日程组
5. 确认导入

**API 调用**：
```python
POST /api/events/import/
Content-Type: multipart/form-data

{
  "file": <ics_file>,
  "target_group_id": "group_123"
}
```

#### 5.2 支持的 iCalendar 字段

- `SUMMARY` → `title`
- `DTSTART` → `start`
- `DTEND` → `end`
- `DESCRIPTION` → `description`
- `LOCATION` → `location`
- `RRULE` → `rrule`
- `EXDATE` → 自动处理排除日期

#### 5.3 兼容性

支持从以下服务导出的日历：
- Google Calendar
- Microsoft Outlook
- Apple Calendar
- 任何符合 RFC 5545 标准的日历应用

### 6. 数据管理特性

#### 6.1 数据验证 (DATA_SCHEMA)

所有数据写入前自动验证格式：

```python
# 自动校验字段类型、必填项、默认值
UserData.objects.write(
    user=request.user,
    key="events",
    data=[...]  # 自动验证是否符合 events schema
)
```

**验证内容**：
- 字段类型（str, int, bool, list, dict）
- 必填字段（nullable=False）
- 默认值自动填充
- 嵌套结构验证（如 list 中的 items）

#### 6.2 批量操作

**批量编辑日程**：
```python
POST /api/events/bulk-edit/
{
  "event_ids": ["evt_1", "evt_2", "evt_3"],
  "updates": {
    "groupID": "new_group_id",
    "importance": "important"
  }
}
```

**批量编辑提醒**：
```python
POST /api/reminders/bulk-edit/
{
  "reminder_ids": ["rem_1", "rem_2"],
  "updates": {
    "priority": "high"
  }
}
```

#### 6.3 数据导出

**导出为 JSON**：
```python
GET /api/events/export/?format=json&start=2025-11-01&end=2025-11-30
```

**导出为 iCalendar**：
```python
GET /api/events/export/?format=ics&start=2025-11-01&end=2025-11-30
```

### 7. 前端集成 (FullCalendar)

#### 7.1 核心前端文件

- **event-manager.js** - 日程管理逻辑
  - 日程 CRUD 操作
  - RRule 重复日程处理
  - 拖拽编辑支持
  - 群组筛选

- **reminder-manager.js** - 提醒管理逻辑
  - 提醒创建和编辑
  - 延迟提醒处理
  - 提醒通知

- **todo-manager.js** - 待办管理逻辑
  - 四象限视图
  - 状态流转
  - 依赖检查

#### 7.2 FullCalendar 配置

```javascript
var calendar = new FullCalendar.Calendar(calendarEl, {
  initialView: 'dayGridMonth',
  headerToolbar: {
    left: 'prev,next today',
    center: 'title',
    right: 'dayGridMonth,timeGridWeek,timeGridDay'
  },
  events: '/api/events/get/',  // 动态加载日程
  editable: true,
  selectable: true,
  eventDrop: handleEventDrop,  // 拖拽编辑
  eventResize: handleEventResize,
  select: handleDateSelect  // 创建新日程
});
```

#### 7.3 用户交互

**创建日程**：
- 点击日历空白处 → 弹出表单
- 填写标题、时间、重复规则
- 提交后自动刷新日历

**编辑日程**：
- 拖拽调整时间
- 点击日程 → 弹出详情/编辑表单
- 重复日程提供编辑模式选择

**筛选显示**：
- 按日程组筛选
- 按标签筛选
- 按优先级筛选

---

## 🔌 API 使用指南

UniScheduler 提供完整的 RESTful API，支持所有核心功能的编程访问。

### 认证方式

系统支持两种认证方式：

| 认证方式 | 使用场景 | 认证方法 |
|---------|---------|---------|
| **Session** | Web 界面 | Cookie 自动认证 |
| **Token** | API 调用 | Header: `Authorization: Token <token>` |

**获取 Token**：
```python
import requests

response = requests.post("http://127.0.0.1:8000/api/auth/login/", json={
    "username": "your_username",
    "password": "your_password"
})
token = response.json()['token']
```

### 主要 API 端点

| 功能模块 | 主要端点 | 说明 |
|---------|---------|------|
| **日程** | `/api/events/` | 日程 CRUD、RRule 重复、批量编辑 |
| **提醒** | `/api/reminders/` | 提醒 CRUD、重复提醒、状态管理 |
| **待办** | `/api/todos/` | 待办 CRUD、转换为日程 |
| **日程组** | `/api/eventgroups/` | 日程分组管理 |
| **群组协作** | `/api/share-groups/` | 群组创建、成员管理、日程同步 |
| **Token 管理** | `/api/token/` | Token 生成、撤销、列表 |

### 完整 API 文档

详细的 API 使用说明、示例代码和故障排查，请参考：

📘 **[api_examples/README.md](api_examples/README.md)** - 完整 API 使用指南

该文档包含：
- ✅ 所有 API 端点的详细说明
- ✅ 完整的 Python 示例代码（开箱即用）
- ✅ 典型使用场景示例
- ✅ 认证流程详解
- ✅ 故障排查指南

**快速体验 API**：
```bash
# 运行日程 API 示例
python api_examples/example_events_api.py

# 运行提醒 API 示例
python api_examples/example_reminders_api.py

# 运行待办 API 示例
python api_examples/example_todos_api.py

# 运行日程组 API 示例
python api_examples/example_eventgroups_api.py
```

> **提示**：运行示例前，请先修改文件顶部的 `USERNAME` 和 `PASSWORD` 配置。

### 更多文档

- 📄 [API_TOKEN_使用指南.md](docs/API_TOKEN_使用指南.md) - Token 认证详细说明
- 📄 [群组协作功能升级方案.md](docs/群组协作功能升级方案.md) - 群组功能设计文档
- 📄 [QUICKSTART.md](api_examples/QUICKSTART.md) - API 快速入门

---

## 🚧 开发路线图

以下是计划中的功能改进和新增特性：

### 🤖 1. AI Agent 式的助手功能

**目标**：打造智能化的日程助手，通过自然语言交互帮助用户管理时间。

**计划功能**：
- 📝 自然语言创建日程：*"明天下午3点开会，提醒我提前15分钟准备"*
- 🔍 智能日程查询：*"这周我有哪些重要会议？"*
- 💡 智能建议：根据历史数据推荐最佳会议时间
- 📊 时间分析：自动生成时间使用报告
- ⚡ 冲突检测：主动提醒日程冲突并提供解决方案
- 🎯 任务优先级推荐：基于四象限法的智能优先级建议

**技术方案**：
- 集成大语言模型（LLM）进行自然语言理解
- 扩展现有的 `ai_chatting` 和 `planner` 组件
- 实现上下文记忆功能，提供连贯的对话体验

---

### ⏱️ 2. 计时器与番茄钟工具

**目标**：帮助用户更好地管理时间，提高专注力和工作效率。

**计划功能**：
- 🍅 **番茄钟计时器**
  - 标准 25 分钟工作 + 5 分钟休息模式
  - 自定义工作/休息时长
  - 自动记录完成的番茄钟数量
  - 与待办事项关联，自动记录任务耗时
  
- ⏲️ **正计时/倒计时器**
  - 简单的计时工具
  - 支持后台运行
  - 时间到达时弹出提醒
  
- 📈 **时间统计**
  - 每日/周/月番茄钟统计
  - 任务耗时分析
  - 工作效率可视化报表

**界面位置**：
- 顶部工具栏添加计时器图标
- 点击展开计时器浮窗
- 支持最小化到工具栏显示倒计时

---

### 🔔 3. 顶部工具栏迫近提醒功能增强

**目标**：让用户随时了解即将到来的日程和待办，不错过重要事项。

**计划功能**：
- 🚨 **智能提醒展示**
  - 顶部工具栏显示即将到来的日程数量（如"3个即将开始"）
  - 鼠标悬停显示详细列表
  - 点击跳转到对应日程
  
- ⏰ **多时间维度提醒**
  - 1小时内：红色高亮
  - 3小时内：橙色提示
  - 今日剩余：蓝色标记
  - 未来3天：灰色预览
  
- 📊 **丰富的显示内容**
  - 日程标题 + 开始时间
  - 重要紧急标识（图标或颜色）
  - 日程组标签（用对应颜色）
  - 倒计时显示（如"还有 25 分钟"）
  
- 🔄 **实时更新**
  - 每分钟自动刷新倒计时
  - 新增/修改日程立即更新提醒列表

**界面设计**：
```
┌─────────────────────────────────────────┐
│ 🏠 日历  |  🔔(3) ▼  |  ⏱️  |  👤 用户 │
│         └──────────┬─────────────────┘  │
│                    │ 1小时内 (2)        │
│                    │ • 15:00 团队会议 🔴│
│                    │ • 16:30 项目评审 🟡│
│                    │ 今日剩余 (1)       │
│                    │ • 18:00 健身 🔵    │
└────────────────────┴────────────────────┘
```

---

### 🎨 4. 自定义确认对话框

**目标**：提升用户体验，统一 UI 风格，提供更友好的交互提示。

**计划功能**：
- 🗑️ **删除确认**
  - 替换浏览器原生 `confirm()` 弹窗
  - 显示被删除项的详细信息
  - 重复日程删除时提供选项（仅当前/整个系列）
  
- ⚠️ **操作确认**
  - 批量操作前的二次确认
  - 重要数据修改提示
  - 不可撤销操作警告
  
- ✅ **成功/错误提示**
  - Toast 轻提示（右上角淡入淡出）
  - 操作成功的简洁反馈
  - 错误信息的详细说明

**设计规范**：
- 自定义 Modal 组件（覆盖层 + 卡片式对话框）
- 统一的色彩方案（成功-绿色、警告-橙色、危险-红色）
- 支持键盘操作（Enter 确认、Esc 取消）
- 动画效果（淡入淡出、轻微缩放）

**示例**：
```html
<!-- 删除确认 -->
┌─────────────────────────────┐
│  ⚠️  确认删除               │
│                             │
│  确定要删除日程             │
│  "团队周会" 吗？            │
│                             │
│  [ 取消 ]    [ 确认删除 ]   │
└─────────────────────────────┘
```

---

### 📊 5. 日程块视觉增强（重要紧急标识）

**目标**：在 2 日视图和周视图中，通过视觉元素快速区分日程的优先级。

**计划功能**：
- 📍 **左侧竖条标识**
  - 在日程块左边缘添加 4px 宽的彩色竖条
  - 根据重要性和紧急度显示不同颜色
  
- 🎨 **颜色编码**

  | 重要性 | 紧急度 | 竖条颜色 | 说明 |
  |-------|-------|---------|------|
  | 重要 | 紧急 | 🔴 红色 | 立即处理 |
  | 重要 | 不紧急 | 🟡 黄色 | 计划处理 |
  | 不重要 | 紧急 | 🟠 橙色 | 委托处理 |
  | 不重要 | 不紧急 | 🟢 绿色 | 减少处理 |

- 📐 **视觉效果**
  - 竖条高度与日程块一致
  - 支持渐变效果（可选）
  - 鼠标悬停时高亮显示
  
**示例效果**：
```
┌──┬─────────────────────────┐
│🔴│ 15:00-16:00            │
│  │ 团队周会                │
│  │ 会议室 A                │
└──┴─────────────────────────┘

┌──┬─────────────────────────┐
│🟡│ 10:00-12:00            │
│  │ 项目规划                │
│  │ 线上会议                │
└──┴─────────────────────────┘
```

---

### 🔄 6. API 数据更新后自动刷新/锁定界面

**目标**：解决多标签页或多用户协作时的数据同步问题，保证数据一致性。

**计划功能**：
- 🔍 **变更检测**
  - 定期轮询服务器数据版本号
  - 检测当前用户的日程数据是否被其他设备/用户修改
  - 群组日程的实时同步检测（已实现版本控制机制）
  
- 🔄 **自动刷新策略**
  - **模式 1：自动刷新**
    - 检测到数据变更，立即刷新日历视图
    - 显示 Toast 提示："日程已更新"
    - 适用于非编辑状态
  
  - **模式 2：锁定提示**
    - 用户正在编辑日程时检测到变更
    - 锁定界面，显示警告："数据已被修改，请刷新后再编辑"
    - 提供"放弃编辑并刷新"或"覆盖保存"选项
    - 防止数据冲突和丢失
  
- ⚡ **实时同步**
  - 利用现有的 `GroupCalendarData.version` 机制
  - 扩展到个人日程的版本控制
  - WebSocket 支持（可选，未来考虑）

**用户体验**：
```
┌─────────────────────────────────────┐
│  ℹ️  数据已更新                       │
│                                     │
│  您的日程数据已在其他设备上被修改      │
│                                     │
│  [ 查看变更 ]    [ 立即刷新 ]        │
└─────────────────────────────────────┘

或（编辑冲突时）

┌─────────────────────────────────────┐
│  ⚠️  编辑冲突                       │
│                                     │
│  此日程已被其他用户修改，             │
│  继续保存可能覆盖最新数据。           │
│                                     │
│  [ 放弃编辑 ]    [ 强制保存 ]        │
└─────────────────────────────────────┘
```

---

### 📅 实施优先级

根据功能复杂度和用户价值，建议的实施顺序：

1. **优先级 P0（高优先级）**
   - ✅ 自定义确认对话框（提升用户体验）
   - ✅ 日程块视觉增强（快速改进，效果显著）
   - ✅ 顶部工具栏迫近提醒（核心功能增强）

2. **优先级 P1（中优先级）**
   - 🔄 API 数据自动刷新/锁定（保证数据一致性）
   - ⏱️ 计时器与番茄钟（独立功能模块）

3. **优先级 P2（长期目标）**
   - 🤖 AI Agent 助手（需要 LLM 集成，工作量较大）

---

### 🤝 贡献

欢迎对以上功能提出建议或直接贡献代码！

- 📝 提交功能建议：[创建 Issue](https://github.com/MoMoJee/UniSchedulerSuper/issues)
- 💻 贡献代码：Fork 项目后提交 Pull Request
- 📧 联系开发者：通过项目主页获取联系方式

---

## 📄 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

---

**感谢使用 UniSchedulerSuper！** 🎉

如有问题或建议，欢迎通过 [Issues](https://github.com/MoMoJee/UniSchedulerSuper/issues) 反馈。

---

