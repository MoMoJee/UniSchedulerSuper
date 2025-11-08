# Token 认证 Request.body 错误修复

## 问题描述

在浏览器中编辑日程时报错：
```
更新失败: 更新事件失败: You cannot access body after reading from request's data stream
```

## 根本原因

当视图函数使用 `@api_view` 装饰器后，Django REST Framework 会将 request 对象包装成 `rest_framework.request.Request` 类型。这个类型的特点是：

1. **数据访问方式不同**：
   - 普通 Django: 使用 `json.loads(request.body)` 读取请求体
   - DRF Request: 使用 `request.data` 访问已解析的数据

2. **不能重复读取**：
   - 一旦通过 `request.data` 访问了数据，就不能再访问 `request.body`
   - 反之亦然

3. **错误触发场景**：
   - `@api_view` 装饰器可能在内部先访问了 `request.data`
   - 然后代码中又尝试 `json.loads(request.body)`
   - 导致抛出异常：`You cannot access body after reading from request's data stream`

## 解决方案

### 1. 修改委托函数装饰器

将委托函数改为使用 `@api_view`：

```python
# 修改前
@permission_classes([IsAuthenticated])
@csrf_exempt
def update_events(request):
    return update_events_impl(request)

# 修改后
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_events(request):
    return update_events_impl(request)
```

### 2. 修改实现函数的数据访问方式

将所有 `json.loads(request.body)` 改为兼容两种方式：

```python
# 修改前
data = json.loads(request.body)

# 修改后
data = request.data if hasattr(request, 'data') else json.loads(request.body)
```

### 3. 修复 UserData.get_or_initialize 调用

DRF 的 Request 对象不能直接传给需要 Django HttpRequest 的函数：

```python
# 添加辅助函数（已在 views_events.py 中定义）
def get_django_request(request):
    """获取原生的 Django HttpRequest 对象"""
    from rest_framework.request import Request as DRFRequest
    if isinstance(request, DRFRequest):
        return request._request
    return request

# 使用方式
django_request = get_django_request(request)
user_events_data, created, result = UserData.get_or_initialize(
    django_request, new_key="events", data=[]
)
```

## 修复的文件

### core/views.py
- ✅ `update_events()` - 添加 `@api_view(['POST'])`

### core/views_events.py
- ✅ `update_events_impl()` - 使用 `request.data`，添加 `get_django_request()`
- ✅ `delete_event_impl()` - 使用 `request.data`，添加 `get_django_request()`
- ✅ `bulk_edit_events_impl()` - 修改装饰器，使用 `request.data`，添加 `get_django_request()`
- ✅ `create_event_impl()` - 已在之前修复

## 验证方法

### 1. 浏览器测试（Session 认证）
1. 登录系统
2. 创建一个日程
3. 尝试编辑该日程
4. 确认不再出现 "You cannot access body" 错误

### 2. API 测试（Token 认证）
```python
import requests

# 获取 Token
response = requests.post(
    "http://localhost:8000/api/auth/login/",
    json={"username": "your_username", "password": "your_password"}
)
token = response.json()['token']

# 测试更新日程
response = requests.post(
    "http://localhost:8000/get_calendar/update_events/",
    json={
        "eventId": "some-event-id",
        "title": "更新后的标题",
        "newStart": "2025-11-10T10:00:00",
        "newEnd": "2025-11-10T12:00:00"
    },
    headers={"Authorization": f"Token {token}"}
)
print(response.json())
```

## 兼容性说明

修复后的代码同时支持：
- ✅ **浏览器 Session 认证**：使用 Cookie 进行身份验证
- ✅ **API Token 认证**：使用 `Authorization: Token xxx` 进行身份验证
- ✅ **向后兼容**：如果 request 对象没有 `data` 属性（旧的 Django HttpRequest），仍然使用 `json.loads(request.body)`

## 最佳实践

### 对于新的 API 端点

1. **使用 `@api_view` 装饰器**：
   ```python
   @api_view(['POST', 'GET'])
   @permission_classes([IsAuthenticated])
   def my_view(request):
       data = request.data  # 自动解析 JSON
   ```

2. **访问请求数据**：
   - 使用 `request.data` 而不是 `json.loads(request.body)`
   - `request.data` 支持 JSON、form-data、multipart 等多种格式

3. **访问原生 request**：
   - 如果需要传给只接受 HttpRequest 的函数，使用 `get_django_request(request)`

### 对于现有的视图函数

如果视图函数同时被：
- 浏览器（Session 认证）
- API 客户端（Token 认证）

调用，则使用兼容写法：
```python
data = request.data if hasattr(request, 'data') else json.loads(request.body)
```

## 相关文档

- [Django REST Framework - Requests](https://www.django-rest-framework.org/api-guide/requests/)
- [Django REST Framework - Authentication](https://www.django-rest-framework.org/api-guide/authentication/)
- [Token认证实施总结](./Token认证实施总结.md)
- [API_TOKEN_使用指南](./API_TOKEN_使用指南.md)
