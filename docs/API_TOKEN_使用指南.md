# 🔐 UniSchedulerSuper API Token 认证使用指南

## 📋 目录
- [概述](#概述)
- [快速开始](#快速开始)
- [获取Token](#获取token)
- [使用Token调用API](#使用token调用api)
- [Token管理](#token管理)
- [常见问题](#常见问题)

---

## 概述

UniSchedulerSuper 现在支持两种认证方式：

1. **Session 认证**（网页端）- 传统的 Cookie/Session 方式，适用于浏览器
2. **Token 认证**（API端）- 基于 Token 的认证，适用于：
   - 移动应用
   - 桌面客户端
   - 第三方程序调用
   - 自动化脚本

---

## 快速开始

### 方式一：使用用户名密码获取 Token

```bash
# 请求
POST http://your-domain.com/api/auth/login/
Content-Type: application/json

{
    "username": "your_username",
    "password": "your_password"
}

# 响应
{
    "token": "9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b",
    "user_id": 1,
    "username": "your_username",
    "email": "your@email.com",
    "created": false
}
```

### 方式二：在网页端管理页面获取

1. 登录网站
2. 访问 `http://your-domain.com/token-management/`
3. 复制显示的 Token

---

## 获取Token

### 1. API 登录获取 Token

**端点：** `POST /api/auth/login/`

**请求体：**
```json
{
    "username": "用户名",
    "password": "密码"
}
```

**响应示例：**
```json
{
    "token": "9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b",
    "user_id": 1,
    "username": "admin",
    "email": "admin@example.com",
    "created": false
}
```

**Python 示例：**
```python
import requests

response = requests.post(
    'http://your-domain.com/api/auth/login/',
    json={
        'username': 'your_username',
        'password': 'your_password'
    }
)

data = response.json()
token = data['token']
print(f"Your token: {token}")
```

### 2. 已登录用户获取 Token

**端点：** `GET /api/auth/token/`

**需要认证：** 是（Session 或 Token）

**响应示例：**
```json
{
    "token": "9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b",
    "user_id": 1,
    "username": "admin",
    "created": false
}
```

---

## 使用Token调用API

### HTTP Header 格式

在所有 API 请求中添加 Authorization header：

```
Authorization: Token 9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b
```

### 示例：获取日程列表

#### Python (requests)

```python
import requests

token = "9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b"
headers = {
    'Authorization': f'Token {token}'
}

# 获取日程
response = requests.get(
    'http://your-domain.com/get_calendar/events/',
    headers=headers
)

events = response.json()
print(events)
```

#### JavaScript (fetch)

```javascript
const token = "9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b";

fetch('http://your-domain.com/get_calendar/events/', {
    headers: {
        'Authorization': `Token ${token}`
    }
})
.then(response => response.json())
.then(data => console.log(data));
```

#### cURL

```bash
curl -H "Authorization: Token 9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b" \
     http://your-domain.com/get_calendar/events/
```

#### Python (更完整的示例)

```python
import requests

class UniSchedulerClient:
    def __init__(self, base_url, token):
        self.base_url = base_url
        self.headers = {
            'Authorization': f'Token {token}',
            'Content-Type': 'application/json'
        }
    
    def get_events(self):
        """获取所有日程"""
        response = requests.get(
            f'{self.base_url}/get_calendar/events/',
            headers=self.headers
        )
        return response.json()
    
    def create_event(self, event_data):
        """创建新日程"""
        response = requests.post(
            f'{self.base_url}/events/create_event/',
            json=event_data,
            headers=self.headers
        )
        return response.json()
    
    def get_reminders(self):
        """获取所有提醒"""
        response = requests.get(
            f'{self.base_url}/api/reminders/',
            headers=self.headers
        )
        return response.json()
    
    def create_reminder(self, reminder_data):
        """创建新提醒"""
        response = requests.post(
            f'{self.base_url}/api/reminders/create/',
            json=reminder_data,
            headers=self.headers
        )
        return response.json()

# 使用示例
client = UniSchedulerClient(
    base_url='http://your-domain.com',
    token='9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b'
)

# 获取日程
events = client.get_events()
print(f"共有 {len(events['events'])} 个日程")

# 创建日程
new_event = client.create_event({
    'title': '团队会议',
    'start': '2025-11-08T14:00:00',
    'end': '2025-11-08T15:00:00',
    'description': '讨论Q4规划',
    'importance': 'important',
    'urgency': 'urgent',
    'groupID': '1'
})
print(f"创建日程成功: {new_event}")
```

---

## Token管理

### 1. 验证 Token

**端点：** `GET /api/auth/token/verify/`

**Headers：**
```
Authorization: Token your_token_here
```

**响应示例：**
```json
{
    "valid": true,
    "user_id": 1,
    "username": "admin",
    "email": "admin@example.com"
}
```

### 2. 刷新 Token

**端点：** `POST /api/auth/token/refresh/`

**Headers：**
```
Authorization: Token old_token_here
```

**响应示例：**
```json
{
    "token": "new_token_string_here",
    "message": "Token 已刷新"
}
```

⚠️ **注意：** 旧 Token 会立即失效

### 3. 删除 Token

**端点：** `DELETE /api/auth/token/delete/`

**Headers：**
```
Authorization: Token your_token_here
```

**响应示例：**
```json
{
    "message": "Token 已删除"
}
```

### 4. API 登出

**端点：** `POST /api/auth/logout/`

**Headers：**
```
Authorization: Token your_token_here
```

**响应示例：**
```json
{
    "message": "登出成功"
}
```

---

## 可用的 API 端点

### 认证相关
- `POST /api/auth/login/` - 登录获取 Token
- `POST /api/auth/logout/` - 登出删除 Token
- `GET /api/auth/token/` - 获取当前 Token
- `POST /api/auth/token/refresh/` - 刷新 Token
- `GET /api/auth/token/verify/` - 验证 Token
- `DELETE /api/auth/token/delete/` - 删除 Token

### 日程相关
- `GET /get_calendar/events/` - 获取所有日程
- `POST /events/create_event/` - 创建日程
- `POST /get_calendar/update_events/` - 更新日程
- `POST /get_calendar/delete_event/` - 删除日程
- `POST /api/events/bulk-edit/` - 批量编辑日程

### 提醒相关
- `GET /api/reminders/` - 获取所有提醒
- `POST /api/reminders/create/` - 创建提醒
- `POST /api/reminders/update/` - 更新提醒
- `POST /api/reminders/delete/` - 删除提醒
- `POST /api/reminders/bulk-edit/` - 批量编辑提醒

### 待办相关
- `GET /api/todos/` - 获取所有待办
- `POST /api/todos/create/` - 创建待办
- `POST /api/todos/update/` - 更新待办
- `POST /api/todos/delete/` - 删除待办

### 用户设置
- `GET /get_calendar/user_settings/` - 获取用户设置
- `POST /get_calendar/user_settings/` - 更新用户设置

---

## 常见问题

### Q1: Token 会过期吗？

**A:** 目前 DRF Token 不会自动过期。如果需要过期机制，可以考虑使用 JWT（Simple JWT）方案。

### Q2: 一个用户可以有多个 Token 吗？

**A:** 不可以。每个用户只有一个 Token。刷新 Token 会使旧的失效。

### Q3: Token 泄露了怎么办？

**A:** 立即访问 Token 管理页面刷新或删除 Token，或调用刷新 API。

### Q4: 如何同时支持网页和 API 访问？

**A:** 系统已经配置了双认证：
- 网页端自动使用 Session 认证
- API 调用使用 Token 认证
- 两者互不干扰

### Q5: Token 存储在哪里？

**A:** Token 存储在数据库的 `authtoken_token` 表中。

### Q6: 如何在移动应用中使用？

**A:**
```python
# 1. 登录获取 Token
token = login_and_get_token(username, password)

# 2. 保存到本地存储（安全存储）
save_to_secure_storage('api_token', token)

# 3. 后续请求都带上 Token
headers = {'Authorization': f'Token {token}'}
```

---

## 安全建议

1. ✅ **使用 HTTPS** - 在生产环境必须使用 HTTPS 传输 Token
2. ✅ **安全存储** - 不要在代码中硬编码 Token
3. ✅ **定期刷新** - 定期刷新 Token 提高安全性
4. ✅ **权限控制** - Token 拥有用户的完整权限，请妥善保管
5. ❌ **不要分享** - 不要将 Token 分享给他人或提交到代码仓库

---

## 更新日志

### 2025-11-08
- ✨ 初始版本
- ✅ 添加 DRF Token 认证支持
- ✅ 创建 Token 管理页面
- ✅ 提供完整的 Token API 端点

---

## 技术支持

如有问题，请联系开发团队或提交 Issue。

**项目地址：** https://github.com/MoMoJee/UniSchedulerSuper
