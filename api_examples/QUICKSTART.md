# UniScheduler API 快速开始指南

5 分钟快速上手 UniScheduler API！

## 🎯 第一步：启动服务

```bash
cd D:\PROJECTS\UniSchedulerSuper
python manage.py runserver
```

看到类似输出表示成功：
```
Starting development server at http://127.0.0.1:8000/
```

## 🔐 第二步：创建用户（首次使用）

打开新的命令行窗口：

```bash
cd D:\PROJECTS\UniSchedulerSuper
python manage.py shell
```

在 Python shell 中执行：

```python
from django.contrib.auth.models import User
User.objects.create_user('api_demo_user', password='demo_password_123')
exit()
```

## 🚀 第三步：运行示例

选择一个示例运行：

```bash
# Events 示例 - 日程管理
python api_examples/example_events_api.py

# Event Groups 示例 - 日程分组
python api_examples/example_eventgroups_api.py

# TODOs 示例 - 待办事项
python api_examples/example_todos_api.py

# Reminders 示例 - 提醒功能
python api_examples/example_reminders_api.py

# Quick Action 示例 - AI 智能操作（需要配置 LLM）
python api_examples/example_quick_action_api.py

# 语音转文字 示例（无需登录）
python api_examples/example_parser_api.py
```

## 💻 第四步：编写你的第一个 API 调用

创建文件 `my_first_api_call.py`：

```python
import requests

# 1. 登录获取 Token
response = requests.post(
    "http://127.0.0.1:8000/api/auth/login/",
    json={
        "username": "api_demo_user",
        "password": "demo_password_123"
    }
)

token = response.json()['token']
print(f"✓ 获取 Token 成功: {token[:30]}...")

# 2. 使用 Token 创建日程
from datetime import datetime, timedelta

tomorrow = datetime.now() + timedelta(days=1)

response = requests.post(
    "http://127.0.0.1:8000/api/events/create/",
    headers={
        "Authorization": f"Token {token}",
        "Content-Type": "application/json"
    },
    json={
        "title": "我的第一个日程",
        "start": tomorrow.strftime("%Y-%m-%dT10:00:00"),
        "end": tomorrow.strftime("%Y-%m-%dT11:00:00"),
        "description": "通过 API 创建的日程"
    }
)

if response.status_code == 200:
    print("✓ 日程创建成功！")
    print(f"  ID: {response.json()['event']['id']}")
else:
    print(f"✗ 创建失败: {response.status_code}")
    print(f"  {response.text}")
```

运行：

```bash
python my_first_api_call.py
```

## 🎉 完成！

你已经成功：
- ✅ 启动了 UniScheduler 服务
- ✅ 创建了 API 用户
- ✅ 获取了认证 Token
- ✅ 创建了第一个日程

## 🎙️ 快速体验语音转文字（无需登录）

语音转文字接口对外开放，不需要任何 Token：

```python
import requests

with open("your_audio.wav", "rb") as f:
    response = requests.post(
        "http://127.0.0.1:8000/api/agent/speech-to-text/",
        files={"audio": ("audio.wav", f, "audio/wav")}
    )

print(response.json())
# {’success’: True, ’text’: ’识别到的文字’, ’duration_seconds’: 3.2, ’provider’: ’baidu’}
```

也可以直接运行脿乾包含的示例脚本（自动生成很短的合成音频）：

```bash
python api_examples/example_parser_api.py
```

## 🤖 快速体验 Quick Action（需要 Token）

AI 接受自然语言，自动创建/修改日程和待办：

```python
import requests

token = "..."  # 充填你的 Token
response = requests.post(
    "http://127.0.0.1:8000/api/agent/quick-action/",
    headers={"Authorization": f"Token {token}"},
    json={"text": "明天下午三点开会，讨论项目进度", "sync": True}
)
print(response.json()["result"]["message"])
# ✅ 已创建新日程：明日 15:00-16:00「开会」
```

## 📚 下一步

1. **浏览更多示例**：查看 `api_examples/` 目录下的完整示例
2. **阅读文档**：查看 `api_examples/README.md` 了解所有功能
3. **Quick Action 详细说明**：查看 `api_examples/README_QUICK_ACTION.md`
4. **完整 API 参考**：查看 `api_examples/API_REFERENCE.md`

## 🔥 常用代码片段

### 获取 Token（复用）

```python
def get_token(username, password):
    response = requests.post(
        "http://127.0.0.1:8000/api/auth/login/",
        json={"username": username, "password": password}
    )
    return response.json()['token']

# 使用
token = get_token("api_demo_user", "demo_password_123")
```

### 创建请求头（复用）

```python
def get_headers(token):
    return {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json"
    }

# 使用
headers = get_headers(token)
response = requests.get("http://127.0.0.1:8000/api/events/", headers=headers)
```

### 创建日程（模板）

```python
event_data = {
    "title": "日程标题",
    "start": "2024-12-25T10:00:00",
    "end": "2024-12-25T11:00:00",
    "description": "日程描述",
    "importance": "high",  # low/medium/high
    "urgency": "normal"    # low/normal/high
}

response = requests.post(
    "http://127.0.0.1:8000/api/events/create/",
    headers=get_headers(token),
    json=event_data
)
```

### 创建待办（模板）

```python
todo_data = {
    "title": "待办标题",
    "description": "待办描述",
    "due_date": "2024-12-25",
    "importance": "high",
    "urgency": "high"
}

response = requests.post(
    "http://127.0.0.1:8000/api/todos/create/",
    headers=get_headers(token),
    json=todo_data
)
```

### 创建提醒（模板）

```python
reminder_data = {
    "title": "提醒标题",
    "reminder_time": "2024-12-25T09:00:00",
    "description": "提醒描述",
    "reminder_type": "notification"  # notification/email/sms
}

response = requests.post(
    "http://127.0.0.1:8000/api/reminders/create/",
    headers=get_headers(token),
    json=reminder_data
)
```

## 🆘 遇到问题？

### Token 获取失败
- 检查用户名密码是否正确
- 确认用户已创建
- **注意**：语音转文字接口 `/api/agent/speech-to-text/` 无需 Token，可直接调用

### 连接失败
- 确认 Django 服务已启动
- 检查端口 8000 是否可用

### API 返回 404
- 确认 URL 路径正确
- 查看 Django 控制台日志

### 语音识别失败（422）
- 确认 `config/api_keys.json` 中语音服务配置正确且 `enabled: true`
- 修改配置后需**重启 Django 服务**（配置仅启动时读取一次）
- 如果只用本地模型，确认已安装：`pip install faster-whisper`

---

**开始你的 API 之旅吧！** 🚀
