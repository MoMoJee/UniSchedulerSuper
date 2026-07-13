# API 接口规范

> P6 现行规则（2026-07-13）：Planner Web/API/Agent/Quick/MCP/附件/Feed/CalDAV 统一调用 normalized application service。旧 URL 若保留，只能做 V2 adapter 或明确拒绝；不得直接读写 Planner `UserData`、伪造 request 调 View 或在错误时 fallback legacy。

> 本文档描述 UniSchedulerSuper 后端 REST API 的设计约定。

---

## 1. URL 设计

### 1.1 路由前缀约定

| 类型 | 前缀 | 示例 |
|------|------|------|
| REST API（新） | `/api/` | `/api/events/bulk-edit/` |
| Agent API | `/api/agent/` | `/api/agent/sessions/` |
| 文件服务 API | `/api/files/` | `/api/files/upload/` |
| 页面视图 | 无前缀 | `/home/`, `/user_login/` |
| 认证 API | `/api/auth/` | `/api/auth/login/` |
| 日历订阅 | `/api/calendar/` | `/api/calendar/feed/` |
| 遗留路由 | `/get_calendar/` | `/get_calendar/events/`（逐步迁移） |

> **迁移原则**：新增接口统一使用 `/api/` 前缀，旧 `/get_calendar/` 路由保持兼容但不新增。

### 1.2 URL 命名风格

- 使用小写 + 连字符：`/api/personal-info/`（而非下划线 `personal_info`）
- 操作型 URL 以动词结尾：`/sessions/create/`、`/sessions/<id>/rename/`
- 删除操作：`DELETE` 方法 **或** POST `/sessions/<id>/delete/`（兼顾简单客户端）
- 列表/详情复数命名：`/api/agent/sessions/`

---

## 2. 视图函数规范

### 2.1 标准视图装饰器组合

**REST API（需登录认证）：**
```python
@api_view(['POST'])
@permission_classes([IsAuthenticated])
@validate_body({
    'title': {'type': str, 'required': True, 'comment': '标题'},
    'start': {'type': str, 'required': True, 'comment': '开始时间 YYYY-MM-DDTHH:MM'},
    'group_id': {'type': str, 'required': False, 'default': '', 'alias': 'groupID'},
})
def create_event_impl(request):
    data = request.validated_data
    ...
```

**公开 API（无需登录）：**
```python
@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def api_login(request):
    ...
```

**页面视图：**
```python
@login_required
def home(request):
    return render(request, 'home.html', context)
```

### 2.2 视图函数命名

- 实现函数（被 `views.py` 包装调用）：`xxx_impl`，如 `get_events_impl`、`create_event_impl`
- Agent 直接暴露的视图：直接命名，如 `list_sessions`、`create_session`
- 内部辅助函数：下划线前缀，如 `_sync_groups_after_edit`

### 2.3 `get_django_request` 兼容层

DRF `Request` 与 Django `HttpRequest` 在某些场合不互通，统一用辅助函数：
```python
def get_django_request(request):
    from rest_framework.request import Request as DRFRequest
    if isinstance(request, DRFRequest):
        return request._request
    return request
```
调用 `UserData.get_or_initialize` 时必须传入原生 `HttpRequest`，通过此函数转换。

---

## 3. 参数校验：`@validate_body`

### 3.1 Schema 字段说明

```python
@validate_body({
    'field_name': {
        'type': str,            # 期望类型，支持 str/int/float/bool/list/dict
        'required': True,       # 是否必填，默认 False
        'default': '',          # 可选，未传时使用的默认值
        'choices': ['a', 'b'],  # 可选，枚举值白名单
        'alias': 'fieldName',   # 可选，前端使用的别名字段名
        'synonyms': ['ctx'],    # 可选，严格模式下提示相似字段名
        'comment': '字段说明',   # 可选，用于错误提示
    },
})
```

校验通过后，参数从 `request.validated_data` 读取（已完成类型转换和别名映射）。

### 3.2 校验模式

- 默认开启**严格模式**（`strict=True`）：请求体包含 schema 外未定义字段时返回 400。
- 未提供 required 字段→400；类型不匹配→400；choices 不在列表→400。

### 3.3 alias 用法示例

前端传 `groupID`，后端变量用 `group_id`：
```python
'group_id': {'type': str, 'alias': 'groupID', 'required': False, 'default': ''}
# 前端 POST: {"groupID": "xxx"}
# 后端读: data['group_id']  => "xxx"
```

---

## 4. 响应格式规范

### 4.1 成功响应

项目中存在两种返回格式，按场景选择：

**DRF `Response`（agent_service、新接口）：**
```python
return Response({'items': data, 'count': len(data)})          # 200 OK
return Response({'token': ..., 'user_id': ...})               # 登录成功
return Response({'error': '...'}, status=status.HTTP_400_BAD_REQUEST)
```

**Django `JsonResponse`（core 旧接口）：**
```python
return JsonResponse({'events': events, 'events_groups': groups})
return JsonResponse({'status': 'error', 'message': '...'}, status=400)
return JsonResponse({'status': 'error', 'message': '...'}, status=500)
```

> **规则**：同一 App 内保持格式一致。`agent_service` 全部用 `Response`；  
> `core` 中新接口也优先用 `Response`，旧接口保持 `JsonResponse` 向后兼容。

### 4.2 错误响应标准

| HTTP 状态码 | 场景 | 响应体 |
|------------|------|--------|
| 400 | 参数错误 / 校验失败 | `{'error': '...'}`  或  `{'status': 'error', 'message': '...'}` |
| 401 | 未认证 | `{'error': '用户名或密码错误'}` |
| 403 | 无权限 | DRF 自动处理 |
| 404 | 资源不存在 | `{'status': 'error', 'message': 'Event not found'}` |
| 405 | 方法不允许 | `{'status': 'error', 'message': 'Invalid request method'}` |
| 500 | 服务器错误 | `{'status': 'error', 'message': 'xxx: <str(e)>'}` |

### 4.3 禁止事项

- 禁止在 500 响应中暴露完整 traceback 到前端。
- 禁止 `except: pass`，500 必须 `logger.error(f"...: {str(e)}")`。

---

## 5. URL 路由注册规范

每个 App 拥有独立的 `urls.py`，在主 `UniSchedulerSuper/urls.py` 中 `include`：

```python
path('', include('core.urls')),
path('api/agent/', include('agent_service.urls')),
path('api/files/', include('file_service.urls')),
path('caldav/', include('caldav_service.urls')),
```

路由文件必须设置 `app_name`（命名空间）：
```python
app_name = 'agent_service'
urlpatterns = [
    path('sessions/', views_api.list_sessions, name='list_sessions'),
    ...
]
```

---

## 6. 视图文件拆分规范

当 views.py 功能复杂时，按领域拆分为多个 views_xxx.py：

| 文件 | 职责 |
|------|------|
| `views.py` | 页面视图 + 聚合入口（调用 `_impl` 函数） |
| `views_events.py` | 日程 CRUD + RRule 逻辑 |
| `views_reminder.py` | 提醒 CRUD |
| `views_token.py` | Token 认证 API |
| `views_share_groups.py` | 分享组 |
| `views_calendar_subscription.py` | 日历订阅 Feed |

`views.py` 通过 `from .views_events import create_event_impl` 方式统一导出，  
前端调用统一走 `views.py` 中的包装函数。
