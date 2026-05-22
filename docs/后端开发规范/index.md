# 后端开发规范 · 索引

> UniSchedulerSuper 后端开发规范，基于项目现有代码约定整理。  
> 所有新功能开发、代码审查均应参照本规范。  
> 最后更新：2026-04-27

---

## 规范文档目录

| 文档 | 内容摘要 |
|------|---------|
| [数据模型规范](./数据模型规范.md) | `UserData` 存储模型、`DATA_SCHEMA` 结构、字段命名约定 |
| [API 接口规范](./API接口规范.md) | URL 设计、视图函数格式、请求/响应结构、参数校验 |
| [认证与权限规范](./认证与权限规范.md) | Token / Session 双轨认证、页面认证、CalDAV 认证 |
| [服务层规范](./服务层规范.md) | `services/` 层职责、`MockRequest` 模式、`reversion` 版本追踪 |
| [日志与错误处理规范](./日志与错误处理规范.md) | 统一日志 `logger`、错误响应格式、中间件请求日志 |
| [Agent 服务规范](./Agent服务规范.md) | WebSocket 协议、LangGraph 工具注册、快速操作、会话管理 |

---

## 技术栈速查

| 层次 | 技术 |
|------|------|
| Web 框架 | Django 5.x |
| REST API | Django REST Framework (DRF) |
| 实时通信 | Django Channels + Daphne (ASGI) |
| 数据库 | SQLite（`db.sqlite3`） |
| 版本控制 | django-reversion |
| AI Agent | LangGraph 1.x + LangChain |
| 认证 | DRF TokenAuthentication + SessionAuthentication |
| CalDAV | RFC 4791 自实现（`caldav_service/`） |
| 日志 | concurrent_log_handler 滚动写入 `logs/application.log` |

---

## 项目 App 结构

```
UniSchedulerSuper/        ← Django 项目配置（settings.py / urls.py / asgi.py）
core/                     ← 核心业务：日程 / 待办 / 提醒 / 用户认证 / 日历订阅
agent_service/            ← AI Agent：WebSocket 对话 / 工具调用 / 记忆管理
caldav_service/           ← CalDAV 服务（RFC 4791）
file_service/             ← 云文件存储与解析
config/                   ← 全局配置管理（API Key / 邮件 / 备案信息）
```

---

## 必备开发约定

### 1. 导入顺序
```python
# 标准库
import json, uuid, datetime

# Django / DRF
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes

# 第三方
import reversion

# 本项目
from logger import logger
from core.models import UserData
from core.utils.validators import validate_body
```

### 2. 全局 logger
所有模块统一使用项目根目录 `logger.py` 提供的 logger：
```python
from logger import logger

logger.info("操作成功")
logger.warning("可能有问题")
logger.error(f"出错：{str(e)}")
```
**禁止** 在模块内用 `logging.getLogger(__name__)` 单独创建 logger，保持日志格式统一。

### 3. 数据写操作必须包版本
所有改变 `UserData` 数据的操作必须包裹在 `reversion.create_revision()` 中：
```python
with reversion.create_revision():
    reversion.set_user(user)
    reversion.set_comment("Create event: ...")
    user_data.set_value(events)
    user_data.save()
```

### 4. 禁止硬编码配置
API Key、邮件密码、服务地址等敏感配置通过 `config/api_keys_manager.py`
或 `config/email_manager.py` 读取，禁止硬编码到代码中：
```python
from config.api_keys_manager import APIKeyManager
key = APIKeyManager.get_llm_key('deepseek')
```
