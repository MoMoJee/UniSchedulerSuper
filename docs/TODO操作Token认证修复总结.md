# TODO 操作 Token 认证修复总结

## 修复日期
2024-12-XX

## 问题描述
TODO 相关的 CRUD 操作无法使用 Token 认证方式访问，只能通过浏览器 Session 认证访问。

## 根本原因
1. **缺少 DRF 装饰器**：TODO 相关函数使用 `@csrf_exempt` 装饰器，而不是 DRF 的 `@api_view` 和 `@permission_classes`
2. **Request 对象不兼容**：直接传递 DRF Request 对象给 `UserData.get_or_initialize()`，该方法需要原生 Django HttpRequest
3. **数据获取方式不兼容**：直接使用 `request.body`，没有处理 DRF 的 `request.data`

## 修复方案

### 1. 导入 get_django_request 辅助函数
在 `core/views.py` 中添加从 `views_events` 导入：
```python
from .views_events import (
    get_events_impl,
    create_event_impl,
    delete_event_impl,
    update_events_impl,
    get_django_request  # 新增
)
```

### 2. 修改的函数列表
修改了以下 5 个 TODO 相关函数：

#### (1) get_todos
- **位置**：`core/views.py` line 840
- **变更**：
  - 添加 `@api_view(['GET'])` 装饰器
  - 添加 `@permission_classes([IsAuthenticated])` 装饰器
  - 添加 `django_request = get_django_request(request)`
  - 使用 `django_request` 调用 `UserData.get_or_initialize()`

#### (2) create_todo
- **位置**：`core/views.py` line 856
- **变更**：
  - 添加 `@api_view(['POST'])` 装饰器
  - 添加 `@permission_classes([IsAuthenticated])` 装饰器
  - 添加 `django_request = get_django_request(request)`
  - 使用 `django_request` 调用 `UserData.get_or_initialize()`
  - 添加数据兼容处理：
    ```python
    data = request.data if hasattr(request, 'data') else json.loads(request.body)
    ```

#### (3) update_todo
- **位置**：`core/views.py` line 902
- **变更**：
  - 添加 `@api_view(['POST'])` 装饰器
  - 添加 `@permission_classes([IsAuthenticated])` 装饰器
  - 添加 `django_request = get_django_request(request)`
  - 使用 `django_request` 调用 `UserData.get_or_initialize()`
  - 添加数据兼容处理

#### (4) delete_todo
- **位置**：`core/views.py` line 947
- **变更**：
  - 添加 `@api_view(['POST'])` 装饰器
  - 添加 `@permission_classes([IsAuthenticated])` 装饰器
  - 添加 `django_request = get_django_request(request)`
  - 使用 `django_request` 调用 `UserData.get_or_initialize()`
  - 添加数据兼容处理

#### (5) convert_todo_to_event
- **位置**：`core/views.py` line 979
- **变更**：
  - 添加 `@api_view(['POST'])` 装饰器
  - 添加 `@permission_classes([IsAuthenticated])` 装饰器
  - 添加 `django_request = get_django_request(request)`
  - 使用 `django_request` 调用 `UserData.get_or_initialize()` (两次调用，todos 和 events)
  - 添加数据兼容处理

## 测试结果

### API 测试（Token 认证）
创建了测试脚本 `test_todo_operations.py`，测试结果：

```
✓ 获取 TODO 列表: 通过
✓ 创建 TODO: 通过
✓ 更新 TODO: 通过
✓ 转换 TODO 为 Event: 通过
✓ 删除 TODO: 通过

全部通过！(5/5)
```

### API 端点
- **获取列表**：`GET /api/todos/` ✅
- **创建 TODO**：`POST /api/todos/create/` ✅
- **更新 TODO**：`POST /api/todos/update/` ✅
- **删除 TODO**：`POST /api/todos/delete/` ✅
- **转换为 Event**：`POST /api/todos/convert/` ✅

### Token 认证方式
```bash
# 1. 获取 Token
POST http://127.0.0.1:8000/api/auth/login/
{
  "username": "your_username",
  "password": "your_password"
}

# 2. 使用 Token 访问 API
Headers:
  Authorization: Token your_token_here
  Content-Type: application/json
```

## 技术说明

### get_django_request 函数
该辅助函数定义在 `core/views_events.py` line 24：
```python
def get_django_request(request):
    """从 DRF Request 中提取原生 Django HttpRequest"""
    if hasattr(request, '_request'):
        return request._request
    return request
```

### 数据兼容性处理
```python
# 兼容 DRF Request 和原生 Django Request
data = request.data if hasattr(request, 'data') else json.loads(request.body)
```

## 完整修复模式总结

### Events 操作（已完成 ✅）
- 9/9 测试通过
- 支持 Token + Session 双认证

### Reminders 操作（已完成 ✅）
- 6/6 API 测试通过
- 浏览器操作正常
- 支持 Token + Session 双认证

### TODOs 操作（已完成 ✅）
- 5/5 测试通过
- 支持 Token + Session 双认证

## 参考文档
- 事件编辑修复文档：`docs/升级日志与过时文件/编辑模态框修复说明.md`
- Reminder API 修复：之前的对话记录
- DRF 官方文档：https://www.django-rest-framework.org/

## 验证清单
- [x] 所有 TODO 函数添加 @api_view 装饰器
- [x] 所有 TODO 函数添加 @permission_classes([IsAuthenticated]) 装饰器
- [x] 所有 TODO 函数使用 get_django_request() 提取原生 request
- [x] 所有 TODO 函数的 UserData 调用使用 django_request
- [x] 所有 TODO 函数处理 request.data 兼容性
- [x] 导入 get_django_request 到 views.py
- [x] 创建 TODO API 测试脚本
- [x] 运行测试并验证全部通过（5/5）
- [x] Token 认证正常工作
- [x] Session 认证（浏览器）正常工作

## 注意事项
1. **保持一致性**：Events、Reminders、TODOs 三类操作现在都使用相同的认证模式
2. **向后兼容**：修复后同时支持 Token（API）和 Session（浏览器）两种认证方式
3. **安全性**：使用 DRF 的 IsAuthenticated 权限类确保只有认证用户可访问
4. **可维护性**：使用统一的 get_django_request() 辅助函数简化代码

## 后续建议
1. 考虑将所有使用 @csrf_exempt 的旧代码逐步迁移到 DRF 模式
2. 统一 API 响应格式（目前 Events 和 TODOs 使用不同的字段名）
3. 添加更多的 API 文档和使用示例
4. 考虑添加集成测试覆盖浏览器操作场景
