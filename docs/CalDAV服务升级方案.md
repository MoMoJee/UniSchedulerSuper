# UniScheduler CalDAV 服务升级方案

> 文档日期：2026-03-18  
> 草稿状态：v1.0 初稿

---

## 目录

1. [背景与目标](#1-背景与目标)
2. [CalDAV 协议概览](#2-caldav-协议概览)
3. [项目现状分析](#3-项目现状分析)
4. [架构设计](#4-架构设计)
5. [URL 路由结构](#5-url-路由结构)
6. [认证方案](#6-认证方案)
7. [数据映射层](#7-数据映射层)
8. [ETag 与 CTag](#8-etag-与-ctag)
9. [各 HTTP 方法实现](#9-各-http-方法实现)
10. [RRule 与重复事件处理](#10-rrule-与重复事件处理)
11. [Calendar 与 Events Group 的对应关系](#11-calendar-与-events-group-的对应关系)
12. [分阶段实施计划](#12-分阶段实施计划)
13. [客户端兼容性说明](#13-客户端兼容性说明)
14. [安全考量](#14-安全考量)
15. [依赖清单](#15-依赖清单)

---

## 1. 背景与目标

### 1.1 现状

UniScheduler 已有**只读** iCalendar 订阅功能（`/api/calendar/feed/`），用户可以将自己的日程推送到 Apple 日历等外部客户端，但仅支持**单向只读**。

### 1.2 目标

引入 **CalDAV 协议**（RFC 4791），实现：

- 用户可在 **iOS/macOS "日历" App、Thunderbird Lightning、GNOME Calendar** 等任意 CalDAV 客户端中读取 UniScheduler 日程
- 用户可在第三方客户端中**创建、修改、删除**日程，变更实时同步回 UniScheduler
- 与现有只读订阅功能**共存**，不破坏已有接口

### 1.3 不在本次范围内

- **CardDAV**（联系人同步）
- **CalDav 共享日历**（多用户协作 CalDAV）
- **Free/Busy 查询**

---

## 2. CalDAV 协议概览

CalDAV（RFC 4791）建立在 WebDAV（RFC 4918）之上，WebDAV 又是 HTTP/1.1 的扩展。

### 2.1 核心 HTTP 方法

| 方法 | 用途 |
|------|------|
| `OPTIONS` | 客户端探测服务器支持的方法和功能 |
| `PROPFIND` | 查询资源属性（服务发现、日历列表、对象列表） |
| `REPORT` | 执行复杂查询（calendar-query、calendar-multiget、sync-collection） |
| `GET` | 获取单个 `.ics` 对象 |
| `PUT` | 创建或更新单个 `.ics` 对象 |
| `DELETE` | 删除单个 `.ics` 对象 |
| `MKCALENDAR` | 创建新的日历集合（可选） |

WebDAV 相关的方法 Django 原生不识别，需额外处理路由。

### 2.2 资源层次结构

```
/caldav/
└── principals/
    └── {username}/              ← 主体资源（Principal）
        └── (calendar-home-set)
/caldav/{username}/              ← 日历主目录（Calendar Home Set）
└── {calendar-id}/              ← 日历集合（Calendar Collection）
    ├── ctag / sync-token
    └── {event-uid}.ics         ← 日历对象资源（Calendar Object Resource）
```

### 2.3 服务发现流程（客户端视角）

1. 客户端访问 `/.well-known/caldav` → 307 重定向到 `/caldav/`
2. `PROPFIND /caldav/` → 返回 `current-user-principal` 属性
3. `PROPFIND /caldav/principals/{username}/` → 返回 `calendar-home-set` 属性
4. `PROPFIND /caldav/{username}/` depth=1 → 枚举所有日历集合
5. `PROPFIND /caldav/{username}/{calendar-id}/` → 枚举该日历中所有 `.ics` 资源（含 ETag）
6. `GET /caldav/{username}/{calendar-id}/{uid}.ics` → 获取具体事件

### 2.4 关键 XML 命名空间

```
DAV:                  → WebDAV 核心属性
urn:ietf:params:xml:ns:caldav  → CalDAV 属性
http://calendarserver.org/ns/  → Apple Calendar Server 扩展（CTag）
http://apple.com/ns/ical/      → Apple iCal 扩展（calendar-color 等）
```

---

## 3. 项目现状分析

### 3.1 数据模型特点

UniScheduler 使用 `UserData` 模型，所有用户数据以 **JSON 字符串**存储于 SQLite (`key=events` / `key=todos` 等)，而非每条事件单独一行 DB 记录。

这与 CalDAV 要求的"每个事件是一个可寻址资源"有差距，需要在视图层做**虚拟资源化**处理：

- 事件 URL = `/caldav/{username}/{calendar-id}/{event-id}.ics`
- 事件 `id` 字段（UUID）天然适合作为 .ics 文件名
- 无需改动底层 UserData 存储结构

### 3.2 已有基础

| 已有能力 | 可复用程度 |
|---------|-----------|
| `icalendar` 库（VEVENT 序列化） | ✅ 直接复用 |
| RRULE 解析 / 序列化辅助函数 | ✅ 直接复用（`views_calendar_subscription.py` 中的工具函数） |
| Token 认证机制（`rest_framework.authtoken`） | ✅ 可扩展为 Basic Auth |
| `EventService` / `ReminderService` / `TodoService` | ✅ 用于写操作 |
| `AgentTransaction` + `reversion` | ✅ 用于保证写操作可回滚 |

### 3.3 需要新增的能力

1. **WebDAV 方法路由**：Django 需要识别 PROPFIND / REPORT / MKCALENDAR
2. **XML 解析与生成**：PROPFIND 请求体 / 响应均为 XML
3. **HTTP Basic Auth**
4. **ETag / CTag 计算**
5. **iCalendar → 内部格式 转换（PUT 时解析客户端上传的 .ics）**

---

## 4. 架构设计

### 4.1 新增 Django App：`caldav_service`

```
caldav_service/
├── __init__.py
├── apps.py
├── urls.py
├── middleware.py          # WebDAV 方法注入中间件（可选）
├── auth.py               # HTTP Basic Auth 验证
├── xml_utils.py          # XML 构建/解析工具
├── etag.py               # ETag / CTag 计算
├── ical_parser.py        # iCal 文本 → 内部 dict（PUT 时使用）
├── ical_builder.py       # 内部 dict → iCal 文本（GET/REPORT 时使用，复用现有逻辑）
└── views/
    ├── __init__.py
    ├── wellknown.py       # /.well-known/caldav 重定向
    ├── principal.py       # /caldav/principals/{username}/
    ├── calendar_home.py   # /caldav/{username}/
    ├── calendar.py        # /caldav/{username}/{calendar-id}/
    └── event.py          # /caldav/{username}/{calendar-id}/{uid}.ics
```

### 4.2 与现有 core 的集成

```
core/
├── services/
│   ├── event_service.py     ← CalDAV 写操作调用这里
│   ├── reminder_service.py
│   └── todo_service.py
```

CalDAV 视图层**不直接操作 UserData**，而是通过 `core.services.*Service` 调用，保证数据一致性和日志记录。

---

## 5. URL 路由结构

在 `UniSchedulerSuper/urls.py`（主路由）中注册：

```python
# CalDAV 服务
path('.well-known/caldav', caldav_views.wellknown_redirect),
path('caldav/', include('caldav_service.urls')),
```

`caldav_service/urls.py`：

```python
urlpatterns = [
    # Principal
    path('principals/<str:username>/', views.principal.PrincipalView.as_view()),

    # Calendar Home Set
    path('<str:username>/', views.calendar_home.CalendarHomeView.as_view()),

    # Calendar Collection（每个 events_group 对应一个 Calendar）
    path('<str:username>/<str:calendar_id>/', views.calendar.CalendarCollectionView.as_view()),

    # Calendar Object Resource（单个事件）
    path('<str:username>/<str:calendar_id>/<str:event_uid>.ics', views.event.EventObjectView.as_view()),
]
```

### 5.1 默认日历

用户始终有一个 **"默认"日历**（`calendar_id="default"`），对应没有 `groupID` 的事件（或全量事件的汇总视图）。其余各个 `events_group` 各自对应一个日历集合。

---

## 6. 认证方案

### 6.1 客户端行为

| 客户端 | 认证方式 |
|-------|---------|
| iOS/macOS "日历" | HTTP Basic Auth（用户名 + 密码，或用户名 + Token） |
| Thunderbird | HTTP Basic Auth |
| DAVx⁵（Android） | HTTP Basic Auth |
| 通用 API 客户端 | Bearer Token（现有方式） |

### 6.2 实现方案

在 `caldav_service/auth.py` 实现 `get_user_from_request(request)` 函数：

```python
def get_user_from_request(request):
    """
    按优先级尝试多种认证方式：
    1. HTTP Basic Auth，密码字段接受明文密码 或 API Token
    2. Bearer Token（Authorization: Token <key>）
    返回 User 对象或 None
    """
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')

    if auth_header.startswith('Basic '):
        import base64
        credentials = base64.b64decode(auth_header[6:]).decode('utf-8')
        username, _, password = credentials.partition(':')
        # 方案A：当密码是 API Token 时
        try:
            token_obj = Token.objects.select_related('user').get(key=password)
            if token_obj.user.username == username:
                return token_obj.user
        except Token.DoesNotExist:
            pass
        # 方案B：普通密码认证
        user = authenticate(request, username=username, password=password)
        return user

    if auth_header.startswith('Token '):
        try:
            return Token.objects.select_related('user').get(key=auth_header[6:]).user
        except Token.DoesNotExist:
            return None

    return None
```

**安全说明**：
- 必须强制 HTTPS（在 Nginx/反向代理层配置），Basic Auth 在 HTTP 下是明文
- 建议在设置页增加"第三方日历密码"字段（专用 App Password），避免泄露主密码
- CalDAV 鉴权失败时返回 HTTP 401 + `WWW-Authenticate: Basic realm="UniScheduler CalDAV"`

---

## 7. 数据映射层

### 7.1 Events Group → Calendar

| UniScheduler | CalDAV |
|-------------|--------|
| `events_group.id` | `calendar_id`（URL 中的集合名） |
| `events_group.name` | `displayname` 属性 |
| `events_group.color` | `calendar-color`（Apple 扩展） |
| —（虚拟）| `"default"` 日历（包含所有事件） |

### 7.2 Event → VEVENT

| UniScheduler 字段 | iCalendar 属性 | 说明 |
|-----------------|---------------|------|
| `id` | `UID`（如 `evt-{id}@unischeduler`） | 稳定标识 |
| `title` | `SUMMARY` | |
| `start`, `end` | `DTSTART`, `DTEND` | 带 TZID=Asia/Shanghai |
| `description` | `DESCRIPTION` | |
| `location` | `LOCATION` | |
| `status` | `STATUS` | confirmed→CONFIRMED 等 |
| `rrule` | `RRULE` | 直接透传 |
| `last_modified` | `LAST-MODIFIED`, `DTSTAMP` | |
| `series_id` | UID 前缀 `evt-series-{series_id}` | 重复系列 |
| `recurrence_id` | `RECURRENCE-ID` | 脱离实例 |

与现有订阅功能使用**相同的映射逻辑**（可复用 `views_calendar_subscription.py` 中的辅助函数）。

### 7.3 iCal → Event（PUT 时反向解析）

客户端 PUT 上来的 iCalendar 文本需要解析回内部格式，`caldav_service/ical_parser.py` 负责：

```python
def ical_to_event_dict(ical_text: str, existing_event: dict = None) -> dict:
    """
    将客户端上传的 iCalendar 文本解析为内部 event dict。
    若 existing_event 不为 None，则做 merge（保留内部字段不被覆盖）。
    """
    cal = Calendar.from_ical(ical_text)
    for component in cal.walk():
        if component.name == 'VEVENT':
            return _vevent_to_dict(component, existing_event)
    raise ValueError("No VEVENT found in iCalendar data")

def _vevent_to_dict(vevent, existing: dict) -> dict:
    result = existing.copy() if existing else {}

    # SUMMARY → title
    result['title'] = str(vevent.get('SUMMARY', ''))

    # DTSTART / DTEND
    dtstart = vevent.get('DTSTART')
    if dtstart:
        dt = dtstart.dt
        if isinstance(dt, datetime.date) and not isinstance(dt, datetime.datetime):
            dt = datetime.datetime.combine(dt, datetime.time(0, 0))
        # 转换为北京时间字符串
        result['start'] = _to_beijing_str(dt)

    dtend = vevent.get('DTEND')
    if dtend:
        dt = dtend.dt
        if isinstance(dt, datetime.date) and not isinstance(dt, datetime.datetime):
            dt = datetime.datetime.combine(dt, datetime.time(0, 0))
        result['end'] = _to_beijing_str(dt)

    # DESCRIPTION → description
    desc = vevent.get('DESCRIPTION')
    if desc is not None:
        result['description'] = str(desc)

    # LOCATION → location
    loc = vevent.get('LOCATION')
    if loc is not None:
        result['location'] = str(loc)

    # STATUS → status
    status_map = {'CONFIRMED': 'confirmed', 'TENTATIVE': 'tentative', 'CANCELLED': 'cancelled'}
    status = vevent.get('STATUS')
    if status:
        result['status'] = status_map.get(str(status).upper(), 'confirmed')

    # RRULE → rrule
    rrule = vevent.get('RRULE')
    if rrule:
        result['rrule'] = _rrule_vrecur_to_str(rrule)

    result['last_modified'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return result
```

**注意**：客户端可能修改 RRULE 或发送 RECURRENCE-ID，这涉及重复事件的管理逻辑，需要调用 `EventsRRuleManager`（现有代码）。

---

## 8. ETag 与 CTag

### 8.1 ETag（事件级别）

用于客户端缓存验证和冲突检测（`If-Match` / `If-None-Match`）。

```python
# caldav_service/etag.py
import hashlib, json

def compute_event_etag(event: dict) -> str:
    """
    使用 last_modified + id 计算事件 ETag。
    若 last_modified 更新，ETag 自动变化。
    """
    raw = f"{event['id']}:{event.get('last_modified', '')}"
    return f'"{hashlib.md5(raw.encode()).hexdigest()}"'

def compute_todo_etag(todo: dict) -> str:
    raw = f"todo:{todo['id']}:{todo.get('last_modified', '')}"
    return f'"{hashlib.md5(raw.encode()).hexdigest()}"'
```

### 8.2 CTag（日历集合级别）

CTag 是 Apple Calendar Server 扩展，标识整个日历集合的版本。

```python
def compute_calendar_ctag(events: list) -> str:
    """
    取所有事件中 last_modified 的最大值作为 CTag。
    若有增删改，CTag 会变化，客户端触发重新同步。
    """
    if not events:
        return '"empty"'
    latest = max(e.get('last_modified', '') for e in events)
    return f'"{hashlib.md5(latest.encode()).hexdigest()}"'
```

**可选升级**：在 `UserData` 中为每个用户的每个日历维护一个专用的 `sync-token`（整型计数），每次写操作 +1。此方式更精确，支持 `sync-collection` REPORT。

---

## 9. 各 HTTP 方法实现

### 9.1 OPTIONS

返回所有支持的方法，告知客户端该资源支持 CalDAV：

```http
HTTP/1.1 200 OK
Allow: OPTIONS, GET, PUT, DELETE, PROPFIND, REPORT, MKCALENDAR
DAV: 1, 2, 3, calendar-access
```

### 9.2 PROPFIND — 服务发现

**Django 路由注意**：PROPFIND 不是标准 HTTP 方法，需要在视图的 `dispatch()` 中处理：

```python
class CalDAVBaseView(View):
    http_method_names = ['get', 'put', 'delete', 'options', 'propfind', 'report', 'mkcalendar']

    def dispatch(self, request, *args, **kwargs):
        method = request.method.lower()
        if method in self.http_method_names:
            handler = getattr(self, method, self.http_method_not_allowed)
        else:
            handler = self.http_method_not_allowed
        return handler(request, *args, **kwargs)
```

**或者**，使用 Django 中间件将自定义 HTTP 方法注入进来（更清晰）：

```python
# middleware.py
class WebDAVMethodMiddleware:
    """让 Django 的 request 对象能识别 WebDAV 自定义方法"""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Django 内部会将 method 设为大写字符串，
        # 对于 PROPFIND 等，只需确保 view 能正确 dispatch 即可。
        return self.get_response(request)
```

#### PROPFIND 响应示例（查询 principal）

```xml
<?xml version="1.0" encoding="utf-8"?>
<multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <response>
    <href>/caldav/principals/alice/</href>
    <propstat>
      <prop>
        <displayname>alice</displayname>
        <C:calendar-home-set>
          <href>/caldav/alice/</href>
        </C:calendar-home-set>
        <C:calendar-user-address-set>
          <href>mailto:alice@example.com</href>
        </C:calendar-user-address-set>
        <principal-URL>
          <href>/caldav/principals/alice/</href>
        </principal-URL>
      </prop>
      <status>HTTP/1.1 200 OK</status>
    </propstat>
  </response>
</multistatus>
```

HTTP 状态码：**207 Multi-Status**

#### PROPFIND 响应示例（枚举日历集合）

对 `/caldav/{username}/`（Depth: 1）：

```xml
<multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"
    xmlns:CS="http://calendarserver.org/ns/"
    xmlns:IC="http://apple.com/ns/ical/">
  <!-- 日历主目录本身 -->
  <response>
    <href>/caldav/alice/</href>
    <propstat>
      <prop>
        <resourcetype><collection/></resourcetype>
      </prop>
      <status>HTTP/1.1 200 OK</status>
    </propstat>
  </response>
  <!-- 各日历集合（每个 events_group 一个） -->
  <response>
    <href>/caldav/alice/work/</href>
    <propstat>
      <prop>
        <resourcetype>
          <collection/>
          <C:calendar/>
        </resourcetype>
        <displayname>工作</displayname>
        <IC:calendar-color>#FF5733FF</IC:calendar-color>
        <CS:getctag>"abc123"</CS:getctag>
        <C:supported-calendar-component-set>
          <C:comp name="VEVENT"/>
          <C:comp name="VTODO"/>
        </C:supported-calendar-component-set>
      </prop>
      <status>HTTP/1.1 200 OK</status>
    </propstat>
  </response>
  <!-- 默认日历 -->
  <response>
    <href>/caldav/alice/default/</href>
    ...
  </response>
</multistatus>
```

#### PROPFIND — 枚举事件列表（Depth: 1 on calendar collection）

返回集合中每个 `.ics` 文件的 `href` + `getetag`：

```xml
<multistatus>
  <response>
    <href>/caldav/alice/work/evt-uuid-001.ics</href>
    <propstat>
      <prop>
        <getetag>"etag-hash-001"</getetag>
        <getcontenttype>text/calendar; charset=utf-8</getcontenttype>
        <resourcetype/>
      </prop>
      <status>HTTP/1.1 200 OK</status>
    </propstat>
  </response>
  ...
</multistatus>
```

### 9.3 REPORT — 查询

客户端常用两种 REPORT：

**① `calendar-multiget`**：用 UID/href 批量抓取若干事件（提高效率）
**② `calendar-query`**：按时间范围过滤（`time-range`）

```python
def report(self, request, username, calendar_id):
    body = request.body
    root = ET.fromstring(body)
    report_name = root.tag.split('}')[-1] if '}' in root.tag else root.tag

    if report_name == 'calendar-multiget':
        return self._handle_calendar_multiget(request, root, username, calendar_id)
    elif report_name == 'calendar-query':
        return self._handle_calendar_query(request, root, username, calendar_id)
    elif report_name == 'sync-collection':
        return self._handle_sync_collection(request, root, username, calendar_id)
    else:
        return HttpResponse(status=400)
```

`sync-collection` 是高级功能，支持增量同步，Phase 2 可酌情实现。

### 9.4 GET — 获取单个事件

```python
def get(self, request, username, calendar_id, event_uid):
    user = self._authenticate(request)
    # ...
    event = self._find_event(user, calendar_id, event_uid)
    if event is None:
        return HttpResponse(status=404)

    ical_text = build_single_event_ical(event)
    etag = compute_event_etag(event)

    response = HttpResponse(ical_text, content_type='text/calendar; charset=utf-8')
    response['ETag'] = etag
    return response
```

### 9.5 PUT — 创建/更新事件

```python
def put(self, request, username, calendar_id, event_uid):
    user = self._authenticate(request)
    ical_text = request.body.decode('utf-8')

    # 判断是创建还是更新
    existing = self._find_event_by_uid(user, calendar_id, event_uid)

    # 冲突检测
    if_match = request.META.get('HTTP_IF_MATCH')
    if existing and if_match:
        current_etag = compute_event_etag(existing)
        if if_match != current_etag:
            return HttpResponse(status=412)  # Precondition Failed

    # 解析 iCal → 内部格式
    new_data = ical_to_event_dict(ical_text, existing_event=existing)
    new_data['groupID'] = self._calendar_id_to_group_id(user, calendar_id)

    if existing:
        EventService.update_event(user, event_id=existing['id'], **new_data)
        response = HttpResponse(status=204)
    else:
        new_data['id'] = event_uid  # 尽量保留客户端指定的 UID
        EventService.create_event(user, **new_data)
        response = HttpResponse(status=201)
        response['Location'] = f'/caldav/{username}/{calendar_id}/{event_uid}.ics'

    response['ETag'] = compute_event_etag(new_data)
    return response
```

**RRule 处理**：若客户端 PUT 的事件包含 `RRULE`，调用 `EventService` 的 RRule 创建流程（与现有逻辑一致）。若还包含 `RECURRENCE-ID`，说明是对特定实例的修改，需要调用"脱离操作"逻辑。

### 9.6 DELETE — 删除事件

```python
def delete(self, request, username, calendar_id, event_uid):
    user = self._authenticate(request)
    existing = self._find_event_by_uid(user, calendar_id, event_uid)
    if existing is None:
        return HttpResponse(status=404)

    # 冲突检测
    if_match = request.META.get('HTTP_IF_MATCH')
    if if_match and compute_event_etag(existing) != if_match:
        return HttpResponse(status=412)

    EventService.delete_event(user, event_id=existing['id'])
    return HttpResponse(status=204)
```

### 9.7 MKCALENDAR — 创建日历（Phase 3 可选）

对应在 UniScheduler 中创建 `events_group`，当客户端想新建日历时触发。

```python
def mkcalendar(self, request, username, calendar_id):
    # 从 XML body 解析 displayname / calendar-description
    # 调用 create_events_group 逻辑
    ...
    return HttpResponse(status=201)
```

---

## 10. RRule 与重复事件处理

### 10.1 读（GET/REPORT）

**只暴露主事件 + 脱离实例**，逻辑与现有 iCal Feed 一致（复用 `_should_include_event()`）：

- 主事件（`is_main_event=True`）：输出 VEVENT + RRULE，客户端自行展开
- 脱离实例（`is_detached=True`）：输出独立 VEVENT + RECURRENCE-ID
- 系统生成实例（`is_main_event=False, is_recurring=True`）：**跳过**

### 10.2 写（PUT）

客户端写操作有三种场景：

| 客户端 PUT 内容 | 含义 | 处理 |
|---------------|------|------|
| 含 RRULE，无 RECURRENCE-ID | 修改重复事件主体（标题/时间/规则） | 调用 `EventService.update_event()` 更新主事件；必要时重新生成实例 |
| 含 RECURRENCE-ID，无 RRULE | 修改序列中的某一次实例 | 调用"脱离操作"：将该实例标记为 `is_detached=True`，更新字段 |
| 无 RRULE，无 RECURRENCE-ID | 普通单次事件 | 正常 create/update |

> ⚠️ CalDAV 客户端删除重复事件时可能发送仅含 `EXDATE` 的 PUT，或直接 DELETE 某 RECURRENCE-ID 对应的实例——需要特殊处理。

---

## 11. Calendar 与 Events Group 的对应关系

| CalDAV 日历 `calendar_id` | 对应的 UniScheduler 内容 |
|--------------------------|----------------------|
| `default` | 所有事件（无 groupID 过滤）|
| `{group.id}` | 仅属于该 group 的事件（`event.groupID == group.id`） |

**用户获得的日历列表**：

```python
def get_user_calendars(user):
    calendars = [{'id': 'default', 'name': 'UniScheduler', 'color': '#4A90E2'}]
    groups = load_events_groups(user)
    for g in groups:
        calendars.append({'id': g['id'], 'name': g['name'], 'color': g.get('color', '#888888')})
    return calendars
```

---

## 12. 分阶段实施计划

### Phase 0：前置准备（预计 1 天）

- [ ] 创建 `caldav_service` Django App 骨架
- [ ] 在 `INSTALLED_APPS` 中注册，在主 URL 中挂载
- [ ] 编写 `auth.py`（Basic Auth 支持）
- [ ] 编写 `xml_utils.py`（XML 构建辅助函数）
- [ ] 编写 `etag.py`（ETag / CTag 计算）

### Phase 1：只读服务（预计 3-5 天）

- [ ] `/.well-known/caldav` 重定向
- [ ] `OPTIONS` 响应（所有 CalDAV 端点）
- [ ] `PROPFIND` — principal 服务发现
- [ ] `PROPFIND` — 日历主目录（列举日历集合）
- [ ] `PROPFIND` — 日历集合（列举事件，含 ETag）
- [ ] `GET` — 获取单个事件 `.ics`
- [ ] `REPORT` — `calendar-multiget`（批量获取）
- [ ] 与 iOS/macOS Calendar App、Thunderbird 基础连通性测试

**验收标准**：在 iOS 设置 → 日历账户 → 添加 CalDAV 账户后，能看到事件列表。

### Phase 2：写操作（预计 3-5 天）

- [ ] `PUT` — 创建事件（无 RRULE）
- [ ] `PUT` — 更新事件（无 RRULE）
- [ ] `DELETE` — 删除事件
- [ ] ETag 冲突检测（`If-Match`）
- [ ] `PUT` — 含 RRULE（重复事件创建/修改）
- [ ] `PUT` — 含 RECURRENCE-ID（脱离实例修改）
- [ ] VTODO 支持（Todos 读写）
- [ ] 全端到端写操作测试

**验收标准**：在第三方客户端中创建/修改/删除事件，UniScheduler Web 端能看到变化。

### Phase 3：进阶功能（可选，视需求）

- [ ] `REPORT` — `sync-collection`（增量同步，减少客户端全量请求）
- [ ] `MKCALENDAR` — 客户端创建新日历对应 UniScheduler 分组
- [ ] CTag 升级为持久化 sync-token（存入 UserData）
- [ ] Free/Busy 查询（`VFREEBUSY`）
- [ ] 专用 App Password（避免主密码泄露）
- [ ] 速率限制（防止客户端过频轮询）

---

## 13. 客户端兼容性说明

### iOS / macOS 日历

- 使用 `PROPFIND Depth: 0/1` + `calendar-multiget` 工作流
- 需要返回 `calendar-home-set` 才能完成账户配置
- 支持 VTODO（iOS 提醒事项）
- 颜色：读取 `http://apple.com/ns/ical/` 命名空间的 `calendar-color`

### Thunderbird Lightning / SOGo Connector

- 行为更接近标准 RFC 4791
- 使用 `calendar-query` 进行时间范围过滤

### DAVx⁵（Android）

- 完整 CalDAV + CardDAV 实现
- 需要正确返回 `current-user-principal`

### 共同要求

- 所有响应必须包含 `Content-Type: application/xml; charset=utf-8`（PROPFIND/REPORT 响应）
- PROPFIND Depth 必须正确处理（0 = 仅当前资源，1 = 当前 + 直接子资源，infinity 建议拒绝）
- 207 Multi-Status 是 PROPFIND/REPORT 的标准响应码

---

## 14. 安全考量

| 风险 | 缓解措施 |
|-----|---------|
| Basic Auth 凭据明文传输 | 强制 HTTPS，在 Nginx 层拒绝 HTTP |
| 主密码泄露 | Phase 3 增加专用 CalDAV App Password |
| 越权访问他人数据 | 视图层每次操作前验证 `username == request.user.username` |
| iCal 注入（DESCRIPTION 含恶意内容） | `icalendar` 库自动转义，输出时无风险；读取时不执行内容 |
| PUT 拒绝服务（超大 iCal 文件） | 限制 `Content-Length`（如不超过 512KB） |
| SSRF（ORGANIZER/URL 字段） | CalDAV 服务不主动发起外部请求，字段只存储不访问 |

---

## 15. 依赖清单

无需新增 Python 包，仅使用已在 `requirements.txt` 中的库：

| 库 | 用途 |
|----|------|
| `icalendar` | 解析/序列化 iCalendar 数据（已有） |
| `python-dateutil` | 日期解析（已有） |
| `djangorestframework` → `Token` | 认证令牌获取（已有） |
| `xml.etree.ElementTree` | 内置标准库，解析 WebDAV XML 请求体 |
| `hashlib` | ETag 计算，内置标准库 |
| `base64` | Basic Auth 解码，内置标准库 |

若需要更完整的 XML 命名空间支持（如 lxml），可选择性添加：
```
lxml>=4.9.0
```
但 `xml.etree.ElementTree` 对本场景已足够。

---

## 附录 A：WebDAV 方法在 Django 中的路由处理

Django 原生 `View` 类只在 `http_method_names` 中声明的方法才能被 `dispatch()` 识别。需要扩展：

```python
from django.views import View
from django.http import HttpResponse

class CalDAVView(View):
    # 扩展 Django 支持的方法列表
    http_method_names = View.http_method_names + [
        'propfind', 'proppatch', 'report', 'mkcalendar', 'mkcol', 'copy', 'move', 'lock', 'unlock'
    ]

    def propfind(self, request, *args, **kwargs):
        raise NotImplementedError

    def report(self, request, *args, **kwargs):
        raise NotImplementedError

    def mkcalendar(self, request, *args, **kwargs):
        return HttpResponse(status=403)  # 默认不允许客户端建日历
```

Django 的 `dispatch()` 使用 `request.method.lower()` 匹配处理函数，所以只要 `http_method_names` 包含对应小写名称即可。

---

## 附录 B：目录树（完整新增文件结构）

```
caldav_service/
├── __init__.py
├── apps.py                    # CaldavServiceConfig
├── urls.py                    # URL 路由
├── auth.py                    # 认证：Basic Auth + Token
├── xml_utils.py               # XML 构建/解析辅助
├── etag.py                    # ETag / CTag / SyncToken
├── ical_parser.py             # iCal 文本 → 内部 dict（PUT 解析）
├── ical_builder.py            # 内部 dict → iCal 文本（复用订阅逻辑）
└── views/
    ├── __init__.py
    ├── base.py                # CalDAVView 基类（认证、dispatch 扩展）
    ├── wellknown.py           # /.well-known/caldav → 重定向
    ├── principal.py           # /caldav/principals/{username}/
    ├── calendar_home.py       # /caldav/{username}/
    ├── calendar.py            # /caldav/{username}/{calendar-id}/
    └── event.py              # /caldav/{username}/{calendar-id}/{uid}.ics
```

主路由修改（`UniSchedulerSuper/urls.py`）：

```python
from django.urls import path, include, re_path
from caldav_service.views.wellknown import wellknown_redirect

urlpatterns = [
    # ... 现有路由 ...
    
    # CalDAV 服务
    re_path(r'^\.well-known/caldav$', wellknown_redirect),
    path('caldav/', include('caldav_service.urls')),
]
```

`caldav_service/urls.py`：

```python
from django.urls import path, re_path
from .views import principal, calendar_home, calendar, event

urlpatterns = [
    path('principals/<str:username>/', principal.PrincipalView.as_view()),
    path('<str:username>/', calendar_home.CalendarHomeView.as_view()),
    path('<str:username>/<str:calendar_id>/', calendar.CalendarView.as_view()),
    re_path(
        r'^(?P<username>[^/]+)/(?P<calendar_id>[^/]+)/(?P<event_uid>[^/]+)\.ics$',
        event.EventObjectView.as_view()
    ),
]
```
