# UniScheduler API 使用示例

本目录包含完整的、开箱即用的 API 调用示例代码，展示如何使用 Token 认证方式调用 UniScheduler 的所有核心功能。

## 📁 文件结构

```
examples/
├── README.md                      # 本文件
├── example_events_api.py          # Events（日程）API 示例
├── example_eventgroups_api.py     # Event Groups（日程组）API 示例
├── example_todos_api.py           # TODOs（待办事项）API 示例
└── example_reminders_api.py       # Reminders（提醒）API 示例
```

## 🚀 快速开始

### 前置条件

1. **确保 Django 服务已启动**
   ```bash
   cd D:\PROJECTS\UniSchedulerSuper
   python manage.py runserver
   ```

2. **创建测试用户**（如果还没有）
   ```bash
   python manage.py shell
   ```
   
   在 Python shell 中执行：
   ```python
   from django.contrib.auth.models import User
   user = User.objects.create_user('api_demo_user', password='demo_password_123')
   print(f"用户创建成功: {user.username}")
   exit()
   ```

3. **安装 requests 库**（如果还没有）
   ```bash
   pip install requests
   ```

### 运行示例

每个示例都可以独立运行，直接执行即可：

```bash
# 运行 Events 示例
python api_examples/example_events_api.py

# 运行 Event Groups 示例
python api_examples/example_eventgroups_api.py

# 运行 TODOs 示例
python api_examples/example_todos_api.py

# 运行 Reminders 示例
python api_examples/example_reminders_api.py
```

## 📚 示例说明

### 1. Events API 示例 (`example_events_api.py`)

展示日程管理的所有操作，包括：

- ✅ **获取日程列表** - 查看所有日程
- ✅ **创建单个日程** - 创建一次性日程
- ✅ **创建重复日程** - 创建重复发生的日程（每周、每月等）
- ✅ **更新日程** - 修改日程信息
- ✅ **更新重复日程** - 更新所有重复实例
- ✅ **更新单次实例** - 只修改重复日程的某一次
- ✅ **转换为单次** - 将重复日程转换为独立日程
- ✅ **删除日程** - 删除单个日程
- ✅ **删除重复日程** - 删除重复日程的所有实例

**核心功能：**
- 支持重复日程（RRule）
- 支持重要性和紧急度分类
- 支持标签、参与者、位置等详细信息

### 2. Event Groups API 示例 (`example_eventgroups_api.py`)

展示日程组管理功能，包括：

- ✅ **获取日程组列表** - 查看所有分组
- ✅ **创建日程组** - 创建新的日程分类
- ✅ **更新日程组** - 修改分组信息（名称、颜色、描述）
- ✅ **删除日程组** - 删除分组（可选是否删除组内日程）
- ✅ **批量创建分组** - 一次性创建多个相关分组
- ✅ **日程组管理** - 完整的管理流程演示

**核心功能：**
- 用颜色区分不同类型的日程
- 支持工作、学习、个人等分类
- 删除分组时可选择是否保留组内日程

### 3. TODOs API 示例 (`example_todos_api.py`)

展示待办事项管理功能，包括：

- ✅ **获取待办列表** - 查看所有待办事项
- ✅ **创建待办** - 添加新的待办任务
- ✅ **更新待办** - 修改待办信息
- ✅ **完成待办** - 标记任务为完成
- ✅ **转换为日程** - 将待办转换为具体的日程安排
- ✅ **删除待办** - 删除待办任务
- ✅ **批量创建** - 一次性创建多个待办
- ✅ **工作流程** - 完整的任务管理流程
- ✅ **优先级管理** - 基于四象限法的优先级管理

**核心功能：**
- 支持重要性和紧急度两个维度
- 四象限时间管理方法
- 可转换为具体的日程安排

### 4. Reminders API 示例 (`example_reminders_api.py`)

展示提醒功能，包括：

- ✅ **获取提醒列表** - 查看所有提醒
- ✅ **创建提醒** - 创建新的提醒
- ✅ **创建重复提醒** - 创建每日/每周/每月重复提醒
- ✅ **更新提醒** - 修改提醒信息
- ✅ **更新状态** - 更改提醒状态
- ✅ **暂停提醒** - 稍后再提醒
- ✅ **完成提醒** - 标记为已完成
- ✅ **忽略提醒** - 忽略此次提醒
- ✅ **删除提醒** - 删除提醒
- ✅ **批量创建** - 创建多个提醒
- ✅ **工作流程** - 完整的提醒处理流程
- ✅ **每日提醒** - 设置每日固定时间的提醒

**核心功能：**
- 支持多种提醒类型（通知、邮件、短信）
- 支持重复提醒（每日、每周、每月、每年）
- 灵活的状态管理（待处理、已完成、已暂停、已忽略）

## 🔧 配置说明

每个示例文件的顶部都有配置区，可以根据需要修改：

```python
# ==================== 配置区 ====================
BASE_URL = "http://127.0.0.1:8000"  # 服务器地址
USERNAME = "api_demo_user"           # 用户名
PASSWORD = "demo_password_123"       # 密码
```

## 📖 示例函数说明

每个示例文件都包含多个独立的示例函数，你可以：

1. **运行完整示例**：直接运行文件，执行所有示例
   ```bash
   python api_examples/example_events_api.py
   ```

2. **单独运行某个示例**：导入并调用特定函数
   ```python
   from api_examples.example_events_api import *
   
   token = get_auth_token()
   example_create_single_event(token)
   ```

3. **在自己的代码中使用**：复制需要的函数到你的项目中

## 🎯 典型使用场景

### 场景 1: 创建日程并设置提醒

```python
from api_examples.example_events_api import get_auth_token, example_create_single_event
from api_examples.example_reminders_api import example_create_reminder
from datetime import datetime, timedelta

# 获取 Token
token = get_auth_token()

# 创建明天的会议日程
tomorrow = datetime.now() + timedelta(days=1)
event_id = example_create_single_event(token)

# 创建会议前 30 分钟的提醒
reminder_time = (tomorrow - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")
example_create_reminder(token, "会议提醒", reminder_time, "30分钟后有会议")
```

### 场景 2: 创建待办并转换为日程

```python
from api_examples.example_todos_api import *
from datetime import datetime, timedelta

token = get_auth_token()

# 创建待办
tomorrow = datetime.now() + timedelta(days=1)
todo_id = example_create_todo(
    token,
    "完成报告",
    "撰写月度工作报告",
    tomorrow.strftime("%Y-%m-%d"),
    "high",
    "high"
)

# 将待办转换为具体的日程
start_time = tomorrow.replace(hour=14, minute=0).strftime("%Y-%m-%dT%H:%M:%S")
end_time = tomorrow.replace(hour=16, minute=0).strftime("%Y-%m-%dT%H:%M:%S")
example_convert_todo_to_event(token, todo_id, start_time, end_time)
```

### 场景 3: 组织管理多个项目的日程

```python
from api_examples.example_eventgroups_api import *
from api_examples.example_events_api import *

token = get_auth_token()

# 为不同项目创建日程组
project_a_id = example_create_event_group(token, "项目A", "客户项目A", "#FF6B6B")
project_b_id = example_create_event_group(token, "项目B", "内部项目B", "#4ECDC4")

# 为每个项目创建日程...
# （将日程的 groupID 设置为对应的项目组 ID）
```

## 🔐 认证说明

所有 API 调用都使用 Token 认证：

1. **获取 Token**
   ```python
   response = requests.post(
       "http://127.0.0.1:8000/api/auth/login/",
       json={"username": "your_username", "password": "your_password"}
   )
   token = response.json()['token']
   ```

2. **使用 Token**
   ```python
   headers = {
       "Authorization": f"Token {token}",
       "Content-Type": "application/json"
   }
   
   response = requests.get(
       "http://127.0.0.1:8000/api/events/",
       headers=headers
   )
   ```

## 📝 API 端点列表

### Events (日程)
- `GET /get_calendar/events/` - 获取日程列表
- `POST /api/events/create/` - 创建单个日程
- `POST /api/events/update/` - 更新日程
- `POST /api/events/delete/` - 删除日程
- `POST /api/events/recurring/create/` - 创建重复日程
- `POST /api/events/recurring/update/` - 更新重复日程
- `POST /api/events/recurring/update-occurrence/` - 更新单次实例
- `POST /api/events/recurring/delete/` - 删除重复日程
- `POST /api/events/recurring/convert-to-single/` - 转换为单次日程

### Event Groups (日程组)
- `GET /get_calendar/events/` - 获取日程组列表（包含在响应中）
- `POST /get_calendar/create_events_group/` - 创建日程组
- `POST /get_calendar/update_events_group/` - 更新日程组
- `POST /get_calendar/delete_event_groups/` - 删除日程组

### TODOs (待办事项)
- `GET /api/todos/` - 获取待办列表
- `POST /api/todos/create/` - 创建待办
- `POST /api/todos/update/` - 更新待办
- `POST /api/todos/delete/` - 删除待办
- `POST /api/todos/convert/` - 转换为日程

### Reminders (提醒)
- `GET /api/reminders/` - 获取提醒列表
- `POST /api/reminders/create/` - 创建提醒
- `POST /api/reminders/update/` - 更新提醒
- `POST /api/reminders/update-status/` - 更新提醒状态
- `POST /api/reminders/delete/` - 删除提醒
- `POST /api/reminders/maintain/` - 维护提醒

## 💡 提示和最佳实践

1. **错误处理**：所有示例函数都包含基本的错误处理，实际使用时可以根据需要扩展

2. **日期格式**：
   - 日期：`YYYY-MM-DD`（如 `2024-12-25`）
   - 日期时间：`YYYY-MM-DDTHH:MM:SS`（如 `2024-12-25T14:30:00`）

3. **重要性和紧急度**：
   - 重要性：`low` / `medium` / `high`
   - 紧急度：`low` / `normal` / `high`

4. **重复规则**：参考 iCalendar RRule 标准
   - 频率：`DAILY` / `WEEKLY` / `MONTHLY` / `YEARLY`
   - 可以指定间隔、次数、截止日期等

5. **清理测试数据**：每个示例都在最后提供了清理功能，避免产生大量测试数据

## 🔍 故障排查

### 问题 1: 无法获取 Token

**错误信息**：`✗ 登录失败 (状态码: 401)`

**解决方法**：
1. 检查用户名和密码是否正确
2. 确认用户是否已创建
3. 查看配置区的 `USERNAME` 和 `PASSWORD`

### 问题 2: 连接失败

**错误信息**：`ConnectionError` 或 `Connection refused`

**解决方法**：
1. 确认 Django 服务已启动：`python manage.py runserver`
2. 检查 `BASE_URL` 配置是否正确
3. 确认端口 8000 没有被其他程序占用

### 问题 3: API 返回 404

**错误信息**：`✗ 创建失败: 404`

**解决方法**：
1. 确认 URL 路径是否正确
2. 检查 Django 的 `urls.py` 配置
3. 查看 Django 控制台的日志信息

## 📞 获取帮助

如果遇到问题：

1. 查看示例代码中的详细注释
2. 查看 Django 服务的控制台输出
3. 检查 `docs/` 目录下的相关文档：
   - `Token认证全面支持综合总结.md`
   - `TODO操作Token认证修复总结.md`
   - `EventGroup操作Token认证修复总结.md`

## 📄 许可证

这些示例代码是 UniScheduler 项目的一部分，遵循项目的许可证。

---

**最后更新**: 2024-12-XX  
**版本**: 1.0.0  
**作者**: UniScheduler Development Team
