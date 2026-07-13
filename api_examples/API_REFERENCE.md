# UniScheduler API 参考（P6 / Planner V2）

本文以 `core/urls.py`、`core/views_planner_v2.py`、Planner command/entity service、Agent 与 CalDAV 代码为准。时间示例均为 ISO 8601；建议显式携带时区偏移或 `tzid`。

## 1. 认证与通用契约

### Token

`POST /api/auth/login/`

```json
{"username":"name","password":"password"}
```

成功返回 `token`。后续请求：

```http
Authorization: Token <token>
Content-Type: application/json
```

除 Feed 的 URL Token、CalDAV Basic Auth 和公开 Speech-to-Text 外，本文接口均需认证。浏览器 Session 的非安全方法还需 CSRF；外部 Token 客户端不需要 CSRF。

### Planner cohort

`GET /api/v2/planner/bootstrap/` 返回各入口准入状态。V2 读写不会 fallback legacy：

| HTTP / code | 含义 |
|---|---|
| 409 `planner_normalized_read_not_enabled` | 当前用户/入口不能读 normalized |
| 409 `planner_normalized_write_not_enabled` | 可读但不能写，或入口未准入 |
| 423 `planner_retired_quarantine` | 历史测试账号已隔离 |

客户端不能在这些错误后改调 V1；应停止并联系管理员修复 cohort。

### 时间窗与身份

- 所有 occurrence 窗口为半开区间 `[from, to)`；`from < to`。
- Event definitions、Event occurrences、conflicts、search、shared occurrences 的 `from`/`to` 均必填。
- Reminder：不带窗口列 master definitions；只要带了任一边界，就必须同时提供两者，并返回 occurrences。
- 无限 RRULE 只能按窗口读取。服务端不物化普通重复实例，重复读取不会增加实体行。
- `event_id`、`todo_id`、`reminder_id`、`group_id`、`series_id` 均是不透明字符串，不应转整数。
- occurrence 响应中的复合 `id` 仅供 UI key 使用；写命令使用 `occurrence_ref.entity_id` 和完整 `occurrence_ref`。

### 并发

所有 PATCH、DELETE、Todo→Event 转换和 Reminder occurrence action 都必须携带最新 `expected_version`。Event/Group/Todo/Reminder 资源写入也可用 `If-Match` 传整数版本，但 body 优先。

- 缺失、非整数或 `<1`：`422 expected_version_required`。
- 版本过期：`409 version_conflict`。
- 收到冲突后重新 GET；不能用旧版本自动循环重试。

### 严格字段

V2 不接受 V1 别名或未知字段。拼错字段返回 `422 unsupported_field`，不会“成功但忽略”。例如：

| 错误旧字段 | V2 字段 |
|---|---|
| `groupID` | `group_id` |
| `shared_to_groups` | `share_group_ids` |
| `ddl` | `ddl_at` |
| `due_date` | `due` |
| `trigger_time` | `trigger` |
| 顶层 `rrule` | `recurrence: {"rrule": "..."}` |
| `eventId` / body `id` | URL 中的资源 ID |

## 2. Event

### 路由

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/v2/events/definitions/?from=...&to=...` | 读取 master/series 定义 |
| GET | `/api/v2/events/occurrences/?from=...&to=...` | 窗口展开日历实例 |
| GET | `/api/v2/events/conflicts/?from=...&to=...` | 半开区间重叠检测 |
| POST | `/api/v2/events/` | 创建单次或 recurrence master |
| PATCH | `/api/v2/events/<event_id>/` | 按 scope 修改 |
| DELETE | `/api/v2/events/<event_id>/` | 按 scope 删除 |

### 创建字段

```json
{
  "title": "每周例会",
  "description": "项目同步",
  "location": "A201",
  "status": "confirmed",
  "importance": "important",
  "urgency": "not-urgent",
  "start": "2026-07-13T10:00:00+08:00",
  "end": "2026-07-13T11:00:00+08:00",
  "is_all_day": false,
  "tzid": "Asia/Shanghai",
  "group_id": null,
  "ddl_at": null,
  "share_group_ids": [],
  "recurrence": {"rrule": "FREQ=WEEKLY;COUNT=10", "rdates": [], "exdates": []}
}
```

规则：

- `title`、`start`、`end` 必填；title 不能为空，end 必须晚于 start。
- `start`/`end` 必须同时出现。定时 Event 必须是 DATE-TIME；全天 Event 必须 `is_all_day=true` 且使用 `YYYY-MM-DD` DATE。
- 切换全天类型时必须同时提供 start/end。
- `tzid` 必须是有效 IANA 时区。
- `group_id` 必须属于当前用户，或为 `null`；跨用户/不存在返回 `group_not_found`。
- `share_group_ids` 必须是去重前可验证的非空字符串数组，且用户必须是 owner/member；single occurrence 不能独立改变分享关系。
- RRULE 使用 RFC 5545 内容，不带 `RRULE:` 也可；不能把 `EXDATE` 拼进 RRULE，使用 recurrence 的 `exdates` 数组。
- 定时 series 的 rdates/exdates 必须为 DATE-TIME，全天 series 必须为 DATE。

创建成功为 `201`，返回 `event` definition；它不是全部 occurrences。

### occurrence_ref

```json
{
  "entity_id": "event-public-id",
  "series_id": "series-public-id",
  "recurrence_id": "20260713T100000",
  "occurrence_start": "2026-07-13T02:00:00+00:00",
  "source_version": 3
}
```

单次 Event 的 `series_id`/`recurrence_id` 为 null，但仍可使用 definition 的 `version` 写入。

### scope

| scope | occurrence_ref | 行为/禁止规则 |
|---|---|---|
| `single` | 重复系列必填 | 写稀疏 override；可改标题、描述、位置、状态、重要性、紧急度、group、起止时间；不能改 recurrence、全天类型、tzid、ddl_at、分享关系 |
| `all` | 可省略 | 修改 master/整系列；可改每天的时刻，但不能把系列起始日期移动到另一自然日；否则 `series_date_change_forbidden` |
| `this_and_future` | 必填 | 截断父系列并建立子系列；非重复 Event 禁止 |

`this_and_future` 在未来已有 override 或更换 RRULE 时，可能要求 `override_policy`：

- `map_by_ordinal`：按序号映射未来例外；不能证明映射时拒绝。
- `keep_as_single`：把无法映射的未来例外保留成独立项。
- `discard_with_audit`：明确丢弃并留审计记录。

缺策略返回 `409 recurrence_split_requires_override_policy`。不要在客户端猜默认值。

删除使用相同 scope：single 取消这一 occurrence；this_and_future 截断；all 软删除整个资源。

## 3. 个人 Event Group

| 方法 | 路径 |
|---|---|
| GET/POST | `/api/v2/groups/` |
| PATCH/DELETE | `/api/v2/groups/<group_id>/` |

可写字段：`name`、`description`、`color`、`group_type`、`default_importance`、`default_urgency`、`default_duration_seconds`、`working_hours`。name 必填且同一用户唯一。

PATCH/DELETE 要 `expected_version`。DELETE 可传 `delete_items`：

- `false`：Event/Todo 脱离该组但保留。
- `true`：组内 Event/Todo 一并软删除。

不存在的组不能静默成功。

## 4. Todo

| 方法 | 路径 |
|---|---|
| GET/POST | `/api/v2/todos/` |
| PATCH/DELETE | `/api/v2/todos/<todo_id>/` |
| POST | `/api/v2/todos/<todo_id>/convert/` |

GET 可按 `status`、`group_id` 精确筛选。

创建/更新字段：`title`、`description`、`status`、`importance`、`urgency`、`priority_score`、`estimated_duration_seconds`、`tzid`、`due`、`group_id`、`tags`、`dependencies`。

- `title` 创建时必填。
- `due` 接受 DATE 或 DATE-TIME；`null`/空值可清空。不要发送 `due_date`。
- tags/dependencies 必须是数组。
- dependency 必须属于同一用户，不能依赖自身、不能形成环；否则 `invalid_dependencies` 或 `todo_dependency_cycle`。
- Todo 当前不支持 recurrence。

转换请求：

```json
{
  "expected_version": 2,
  "start": "2026-07-14T14:00:00+08:00",
  "end": "2026-07-14T15:00:00+08:00",
  "tzid": "Asia/Shanghai",
  "is_all_day": false
}
```

转换在一个事务中创建 Event，并把 Todo 标为 completed、关联 `converted_to_event_id`。同一 Todo 不能再次转换；返回 `todo_already_converted`。失败不得产生半个 Event。

## 5. Reminder

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/api/v2/reminders/` | 无窗口读 definitions；有 from/to 读 occurrences；POST 创建 |
| PATCH/DELETE | `/api/v2/reminders/<reminder_id>/` | scope 命令 |
| POST | `/api/v2/reminders/occurrences/action/` | complete/dismiss/snooze/mark_sent/reset |

创建/更新字段：`title`、`content`、`priority`、`status`、`tzid`、`trigger`、`recurrence`。

```json
{
  "title": "喝水",
  "trigger": "2026-07-13T10:00:00+08:00",
  "tzid": "Asia/Shanghai",
  "priority": "normal",
  "recurrence": {"rrule": "FREQ=DAILY"}
}
```

- 创建必须有非空 title 和 trigger。
- 单次 Reminder 可用 `scope=all` + recurrence object 转为重复。
- 重复 Reminder 用 `scope=all` + `recurrence:null` 转为单次。
- `single` 只改一个 occurrence，不能改 recurrence。
- `all` 可改每天的提醒时刻，但不能移动系列起始日期；否则 `series_date_change_forbidden`。
- `this_and_future` 必须提供 occurrence_ref；若未来 occurrence state 存在且同时改 RRULE，返回 `409 recurrence_split_requires_override_policy`，需先明确处理状态。

Action：

```json
{
  "action": "snooze",
  "occurrence_ref": {"entity_id":"...","series_id":"...","recurrence_id":"...","source_version":4},
  "expected_version": 4,
  "snooze_until": "2026-07-13T10:30:00+08:00"
}
```

- action 只允许 `complete`、`dismiss`、`snooze`、`mark_sent`、`reset`。
- snooze 必须提供 DATE-TIME `snooze_until`。
- 对重复 Reminder，必须操作具体 occurrence，不能只传 master ID。

## 6. Search、冲突与共享读取

`GET /api/v2/search/?q=...&types=event,todo,reminder&from=...&to=...&page=1&page_size=50`

- types 仅允许 event/todo/reminder。
- page ≥ 1，page_size 为 1–100。
- 结果跨类型，仍使用各自的实体/occurrence identity。

`GET /api/v2/share-groups/<share_group_id>/occurrences/?from=...&to=...`

- 必须是 owner 或 member；否则 403 `share_group_forbidden`。
- 他人 Event 带 `read_only:true`，不能用自己的身份修改。
- 数据来自 normalized EventShareGroup join，不来自旧 `GroupCalendarData.events_data`。

分享组成员管理仍使用 `/api/share-groups/...` 的 create/join/leave/delete/update/members/update-member-color 端点；旧 `/api/share-groups/<id>/events/` 已停用，见第 11 节。

## 7. Calendar Feed

`GET /api/calendar/feed/?token=<DRF-token>&type=all|events|todos|reminders`

- 为兼容订阅客户端，Token 在 URL 中；必须按凭据处理，禁止记录/转发完整 URL。
- 缺 token：400；无效 token：403；非法 type：400。
- 返回 `text/calendar`。重复系列输出 master RRULE 与稀疏例外，不展开无限实例。
- Todo 仅有 due 时进入 Feed；Reminder/Todo 为兼容 Apple 订阅会投影为 VEVENT/VALARM。
- Feed 只读，不能反向写入。

## 8. CalDAV 适配边界

服务根 `/caldav/`，使用 HTTP Basic Auth：username 为 Django 用户名，password 推荐 DRF Token，也可账号密码。

支持项目原有能力的 V2 适配，不宣称完整 CalDAV：

- OPTIONS、PROPFIND（root/principal/home/collection/resource）。
- REPORT：`calendar-multiget`、`calendar-query`；不支持的 report 返回 403/明确错误。
- GET/HEAD 单个 `.ics`。
- default/个人 Event Group collection 的 Event resource PUT/DELETE。
- reminders collection 只读；PUT/DELETE 固定 403。
- 不允许客户端 MKCALENDAR；collection 本身不能 PUT/DELETE。
- 单个 PUT body 最大 512KB，一个资源只允许一个 UID；不能借 PUT 改 UID/resource identity。

并发：新建用 `If-None-Match: *`；更新/删除必须用最新 ETag 的 `If-Match`。过期或目标已存在返回 412。跨 collection 移动仍保持统一 normalized identity/collection change。

## 9. Quick Action、Agent 附件和回滚

Quick Action 端点和输入约束见 `README_QUICK_ACTION.md`。它、聊天 Agent Tool 与 MCP 均委托统一 application service，不是另一套数据库 API。

Agent 附件相关 HTTP 端点位于 `/api/agent/attachments/`：

- 可附加 Event/Todo/Reminder master 或带完整 occurrence_ref 的具体 occurrence。
- 内部元素按发送时 snapshot 进入消息；源删除后历史消息仍可读 snapshot。
- 文件/图片回滚到输入框后，重新发送前必须恢复有效 attachment 记录，不能只复用 UI 卡片 ID。
- 附件必须属于当前用户和 session，跨用户/session ID 拒绝。

Agent 回滚：

- 仅当前会话当前 rollback window 内、切换/新建对话之后的消息可回滚。
- P4 前历史和已关闭窗口返回 410；不会恢复旧 reversion 历史。
- snapshot restore 会产生新的单调 version；回滚后继续写前必须重新读取。
- 旧 `/api/agent/rollback/preview/` 与步骤式 `/api/agent/rollback/` 返回 410；当前消息目标使用 `/api/agent/rollback/to-message/`。

## 10. Speech-to-Text

`POST /api/agent/speech-to-text/`，公开接口，multipart 字段 `audio`。

- 最大 15MB、60秒。
- 支持 wav/mp3/ogg/flac/webm/aac/m4a/amr。
- 缺字段/格式/大小问题为 400；识别链失败通常为 422。
- 公开不等于无限制可信：客户端仍应限流，不能把 provider 字段当稳定业务枚举。

## 11. Planner V1 的预期后果与迁移表

P6 已封存 legacy Planner JSON。下列旧 URL 在认证通过后统一返回：

```json
{
  "error": "Planner V1 API 已停用；legacy Planner 归档已封存且禁止读写。",
  "code": "planner_v1_api_retired",
  "requested_path": "/api/todos/create/",
  "replacement": {"method": "POST", "path": "/api/v2/todos/"}
}
```

HTTP 为 `410 Gone`。未认证请求仍先返回 401/403。后果是确定性的：

- 请求体不会被转换、排队或部分执行。
- legacy 归档和 normalized 表都不会发生业务写入。
- GET 也不会返回旧快照；410 不能靠重试恢复。
- 客户端必须读取 `replacement` 并按 V2 字段、版本和 scope 重新构造请求。
- 旧但从未注册的 `/get_calendar/delete_event/` 保持 404，不应依赖。

| V1 URL | V2 替代 |
|---|---|
| GET `/get_calendar/events/` | GET `/api/v2/events/occurrences/?from=&to=` |
| POST `/events/create_event/` | POST `/api/v2/events/` |
| POST `/get_calendar/update_events/` | PATCH `/api/v2/events/<event_id>/` |
| POST `/api/events/bulk-edit/` | PATCH/DELETE `/api/v2/events/<event_id>/` + scope |
| GET `/api/events/groups/` | GET `/api/v2/groups/` |
| POST `/get_calendar/create_events_group/` | POST `/api/v2/groups/` |
| POST `/get_calendar/update_events_group/` | PATCH `/api/v2/groups/<group_id>/` |
| POST `/get_calendar/delete_event_groups/` | DELETE `/api/v2/groups/<group_id>/` |
| GET/POST `/api/todos/` | GET/POST `/api/v2/todos/` |
| POST `/api/todos/create/` | POST `/api/v2/todos/` |
| POST `/api/todos/update/` | PATCH `/api/v2/todos/<todo_id>/` |
| POST `/api/todos/delete/` | DELETE `/api/v2/todos/<todo_id>/` |
| POST `/api/todos/convert/` | POST `/api/v2/todos/<todo_id>/convert/` |
| GET/POST `/api/reminders/` | GET/POST `/api/v2/reminders/` |
| POST `/api/reminders/create/` | POST `/api/v2/reminders/` |
| POST `/api/reminders/update/` | PATCH `/api/v2/reminders/<reminder_id>/` |
| POST `/api/reminders/bulk-edit/` | PATCH/DELETE `/api/v2/reminders/<reminder_id>/` + scope |
| POST `/api/reminders/delete/` | DELETE `/api/v2/reminders/<reminder_id>/` |
| POST update-status/snooze/dismiss/complete/mark-sent | POST `/api/v2/reminders/occurrences/action/` |
| POST `/api/reminders/convert-to-single/` | PATCH reminder，`scope=all, recurrence=null` |
| pending/maintain | 窗口 GET；不再有“预生成/维护实例”命令 |
| GET `/api/share-groups/<id>/events/` | GET `/api/v2/share-groups/<id>/occurrences/?from=&to=` |

## 12. 错误处理

| HTTP | 常见含义 |
|---|---|
| 400 | 查询边界/基础请求格式错误 |
| 401/403 | 未认证、无资源权限 |
| 404 | normalized 资源不存在 |
| 409 | version conflict、cohort 状态或需显式 override policy |
| 410 | 已废弃 API/回滚窗口永久不可用 |
| 422 | 领域字段、时间、RRULE、scope、关系约束错误 |
| 423 | retired quarantine 账号 |
| 500 | 未预期服务端错误；不应被客户端当参数错误重试 |

错误响应优先解析稳定 `code`，自然语言 `error` 仅用于展示。网络超时也不能证明写入失败；对非幂等 POST 应先重新读取或查询任务状态，避免重复创建。

**文档版本：2.0.0｜最后更新：2026-07-13**
