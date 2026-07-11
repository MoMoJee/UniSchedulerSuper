# 核心日程正规化与 RRule 引擎升级方案

> 状态：调研和实施设计完成，尚未开始改表。  
> 范围：`events`、`reminders`、`todos`、日程组、共享日程、Web UI/REST、全局搜索、Agent/Quick Action/MCP、附件内部元素、iCalendar 订阅、CalDAV 和 Agent 回滚。  
> 核心决策：停止把重复实例作为业务事实存储；重复日程只保存主对象、规则和稀疏例外，按请求时间窗展开。

---

## 1. 目标与边界

本升级同时解决两个独立但耦合的问题。

1. 将 `core_userdata.value` 中的 `events`、`reminders`、`todos` 及其关系拆为正规 ORM 表，消除整包 JSON 读改写、缺少索引、并发覆盖和整包 reversion 快照。
2. 用统一的 RFC 5545 recurrence 模型替换“主对象 + 大量预生成实例 + 另一份规则段 JSON”的双重事实源。无限规则不再占用线性增长的存储。

本方案不把“前端展开”理解为把规则正确性下放给浏览器：

- 前端负责日历视图的可视区渲染和交互预览。
- 后端保留同一纯函数展开器，用于写入校验、搜索、冲突检测、提醒触发、CalDAV `calendar-query`、Feed 和自动化测试。
- 两端使用同一 RFC 5545 语义和同一组契约用例；前端不能自行用字符串加减日期推算重复规则。

非目标：

1. 不迁移 LangGraph checkpoint SQLite 数据库。
2. 不把所有 `UserData` 配置类 key 一次拆完；本期只移除核心业务实体对它的依赖。
3. 不在本期强制提供 CalDAV `VTODO` 写入。现有 CalDAV 只支持 `VEVENT`，提醒日历只读；该行为必须明确保留并测试。
4. 不在没有数据校验、灰度和回滚能力的情况下删除 legacy JSON。

---

## 2. 调研结论

### 2.1 当前事实源和数据库问题

主库是 SQLite `db.sqlite3`，Django 配置位于 `UniSchedulerSuper/settings.py:110-118`，连接创建时开启 WAL 和 30 秒 busy timeout（`core/apps.py:8-18`）。核心业务数据仍主要在：

```text
core_userdata(id, user_id, key, value TEXT)
```

`UserData` 的定义和整包序列化位置见 `core/models.py:1317-1476`。它没有 `(user_id, key)` 唯一约束，`get_or_initialize()` 使用 `.get()` 后 `.create()`，并发初始化可能重复；数据库中已经存在重复 key。`events` 单条 JSON 曾达到约 1.18 MB，且 `core_userdata` 只有 `user_id` 索引。

当前 JSON schema 是声明而非可靠数据库约束：

- events：`core/models.py:31-164`
- todos：`core/models.py:166-245`
- reminders：`core/models.py:247-336`
- `events_rrule_series` / `rrule_series_storage`：`core/models.py:991-1119`

特别危险的是 `get_events_impl()` 调用了 `get_value(check=True)`（`core/views_events.py:1247`）；校验器只重新构造 schema 中声明的字段（`core/models.py:1516-1537`），可能删除 CalDAV 的 `caldav_uid`、历史兼容字段和未来扩展字段。

### 2.2 当前调用面

| 功能 | 当前读取/写入 | 主要问题 |
|---|---|---|
| Web 日程 | `/get_calendar/events/`、`/events/create_event/`、`/api/events/bulk-edit/` | 读接口会补实例并写库；所有更新整包覆盖 |
| Web 提醒 | `/api/reminders/*` | GET 会补实例；提醒状态、snooze、规则和实例混在同一数组 |
| Web 待办 | `/api/todos/*` | 普通 CRUD 全量 JSON；转换日程同时改两个 JSON |
| Web 全局搜索 | `home.html:4416-4911` | 打开搜索时下载全部 events/reminders/todos/files/每个共享组，再在浏览器过滤 |
| 日程组/共享 | `events_groups` JSON、`GroupCalendarData.events_data` JSON | 分享日程被复制为第二份 JSON 投影 |
| Service | `core/services/event_service.py`、`todo_service.py`、`reminder_service.py` | Service 仍直接操作 `UserData`，`EventService.bulk_edit` 甚至伪造 HTTP request 再调用 view |
| Agent | unified/legacy planner tools | 搜索和写入依赖 Service 的 JSON 列表；搜索缓存只保存 UUID，无法表达虚拟 occurrence |
| Agent 附件 | `agent_service/parsers/internal_parser.py:75-350` | 按 ID 遍历整份 JSON，附件选择器无法引用按需展开的 occurrence |
| CalDAV | `caldav_service/views/base.py`、`event.py` | 既绕过 Service 又直接改 JSON；重复 PUT 依赖预生成实例 |
| 订阅 Feed | `core/views_calendar_subscription.py` | 输出主事件/脱离实例，但仍从 JSON 读取 |

以下功能必须纳入迁移完成定义，不能因改表遗漏：

- 日程组、颜色、DDL、重要/紧急、地点、状态、标签、关联提醒。
- todo 的状态、四象限、预计时长、依赖、关联提醒、转换为日程。
- reminder 的优先级、延后、完成/忽略、提前提醒、通知发送状态、与 event/todo 的链接。
- 分享组、成员颜色、只读他人日程、组版本检查。
- 课程导入（`core/views_import_events.py`）和旧 ICS 导出。
- WebSocket Agent、Quick Action、MCP、搜索缓存、回滚、附件内部快照。
- HTTP Feed、CalDAV discovery/PROPFIND/REPORT/GET/PUT/DELETE、ETag/CTag。

### 2.3 Web UI 的当前数据流

`EventManager.fetchEvents()` 以当前 FullCalendar 可视区向 `/get_calendar/events/?start=&end=` 请求，但服务端先读取和补全所有重复实例，再在 Python 过滤范围（`core/static/js/event-manager.js:628-752`，`core/views_events.py:1253-1337`）。提醒也按视图区间请求，随后被转为 30 分钟的日历事件。待办和提醒列表分别在浏览器再筛选和排序。

目前的交互把预生成行的 UUID 当作“某一次 occurrence”的身份：

- 拖拽重复事件会传递 `event.id`，并弹出 `single/future/all` 范围选择（`event-manager.js:956-1167`）。
- 单次修改通过向原系列写 EXDATE、清空该行 `series_id`、保存 `original_series_id` 的方式脱离（`core/views_events.py:2040-2138`）。
- 全局搜索加载所有对象后在浏览器做标题、描述、时间、组和分享组过滤（`home.html:4508-4747`）。

目标系统必须把 occurrence 身份从“预生成 UUID”改为稳定复合键：

```text
OccurrenceRef = {
  entity_type: "event" | "reminder",
  entity_id: master public id,
  series_id: recurrence series public id,
  recurrence_id: RFC 5545 原始 DTSTART 槽位,
  occurrence_start: 当前实际展示开始时间,
  source_version: integer
}
```

对于单次 event/todo/reminder，`series_id` 和 `recurrence_id` 为 `null`，`entity_id` 即稳定业务 ID。前端不再把虚拟 occurrence 当成可持久化 event row。

### 2.4 Agent、MCP 和附件现状

活跃 Agent 接口是 `search_items`、`create_item`、`update_item`、`delete_item`、`complete_todo`、日程组/分享组读取和冲突分析（`agent_service/tools/unified_planner_tools.py:182-1495`）。它们通过三个 Service 读取整表 JSON，并以 `#N`、UUID 或标题解析对象。

需要一并修复的耦合：

1. `search_items` 对 events 只比较存储的 `start`，不具备从主规则搜索未来 occurrence 的能力（`unified_planner_tools.py:271-367`）。
2. Agent cache 只以 UUID 映射 `#N`；重复 occurrence 必须改为缓存完整 `OccurrenceRef`，不能把多个 occurrence 压成同一个 master UUID。
3. 更新成功后当前 cache 不刷新，旧标题可能继续被解析（见 `unified_planner_tools.py:721-1002` 与 delete 分支）。
4. `ReminderService.update_reminder()` 对非空 `rrule` 不生效，Agent 的普通 reminder 改规则路径实际失效（`core/services/reminder_service.py:70-113`）。
5. 附件内部元素按 JSON `id` 遍历；迁移后必须走查询服务，且附件内容仍应保存当时的 `internal_snapshot`，以保持历史消息稳定。
6. `@agent_transaction` 当前仅保存六个 JSON blob 的操作前 reversion 版本，且不在一个数据库事务内（`agent_service/utils.py:37-109`）。新模型不能继续依赖该机制。

MCP 复用 unified tools，HTTP 和 stdio 路径都必须同时适配；不能只修 WebSocket Agent。

### 2.5 CalDAV 和 Feed 现状

CalDAV 当前只有 VEVENT：默认日历、每个日程组日历和只读 reminders 日历。todos 不在 CalDAV 中；HTTP Feed 把有 `due_date` 的 todo 和 reminder 转为带 `VALARM` 的 VEVENT（`core/views_calendar_subscription.py:361-502`）。

已有的正确方向是 CalDAV/Feed 只暴露主事件与脱离例外，不暴露普通预生成实例（`core/views_calendar_subscription.py:190-213`，`caldav_service/views/base.py:173-186`）。但内部仍依赖预生成行。

关键协议缺口：

- CalDAV parser 没有解析 `EXDATE`、`RDATE`、`DURATION`、`SEQUENCE`、全天日期和 `RECURRENCE-ID;RANGE=THISANDFUTURE`（`caldav_service/ical_parser.py:151-208`）。
- 代码把 `EXDATE` 拼进 `RRULE` 字符串，这不符合 RFC 5545 属性模型。
- `calendar-query` 按主行 `start/end` 比较，没有展开 RRULE；一个早于查询窗口开始的无限系列会被漏掉（`caldav_service/views/calendar.py:205-291`）。
- ETag 以秒精度 `last_modified` 计算，无法可靠检测同秒修改；没有 sync-token/sync-collection。
- `EventObjectView` 多处直接写 `UserData`（`caldav_service/views/event.py:162-776`），普通更新与重复更新不在同一领域服务中。

---

## 3. 当前 RRule 模式与根因

### 3.1 现在有三套重复逻辑

1. `rrule_engine.py`：`RRuleSeries` 保存 `RRuleSegment(uid, sequence, rrule_str, dtstart, until, exdates)`，用 `dateutil.rruleset` 生成时间点。
2. `EventsRRuleManager`：把上述引擎绑定到 `events_rrule_series` JSON，并把时间点复制成 event JSON 行；GET 时按频率补库存。
3. `IntegratedReminderManager` 和 `views_reminder.py`：既调用通用引擎，也保留另一套手写 DAILY/WEEKLY/MONTHLY 生成和补库逻辑。

运行时 segment 的序列化字段是 `uid/sequence/rrule_str/dtstart/until/exdates/created_at`（`rrule_engine.py:23-61`），但 `DATA_SCHEMA` 声明的是 `id/rrule/dtstart/until/count/original_data`（`core/models.py:991-1119`）。这意味着 schema 校验有破坏规则段数据的风险。

### 3.2 预生成导致的具体问题

1. 无限制 DAILY/WEEKLY/MONTHLY 每次创建和 GET 都可能生成更多记录；时间越久，存储、同步、reversion 和共享复制越大。
2. `UNTIL` 系列常只预生成一个窗口，后续又被“有 UNTIL 不自动补全”的分支跳过，Web 端会不完整。
3. 同一规则同时存在主 event 的 `rrule`、每个预生成行的 `rrule`、规则段 JSON、可能拼入的 EXDATE，四处可能不一致。
4. “仅此”编辑、单次删除、此及以后改规则分别修改行、EXDATE、UNTIL、series_id、main 标记和规则段；一次失败即可留下半系列。
5. “此及以后”不是简单把未来预生成行批量改字段：规则变更后应分割规则历史、保留过去例外、处理未来例外归属，并保证 iCalendar UID/RECURRENCE-ID 语义。
6. 当前代码对复杂规则、时区和 COUNT/UNTIL 的处理分散；多个分支通过 `datetime - timedelta(days=1)` 或字符串替换规则，无法覆盖多 BYDAY、月末、DST、DATE 类型等情况。

### 3.3 升级后的原则

1. RFC 5545 的 `RRULE`、`RDATE`、`EXDATE`、`RECURRENCE-ID` 是不同属性，禁止互相拼接。
2. 不保存“正常生成的 occurrence”；只保存主对象和发生过人为/系统状态变化的稀疏记录。
3. `recurrence_id` 永远表示原规则槽位，不因移动 occurrence 的实际开始时间改变。
4. “此及以后改规则”以**分裂成新的系列**实现，而不是在一个 series 内追加自定义 segment。新旧系列用 lineage 关联。
5. 所有写操作只调用一个 `RecurrenceCommandService`；views、CalDAV、Agent、MCP 不得再自行推算规则或批量改实例。
6. 展开器必须是无副作用纯函数。GET、搜索和 CalDAV REPORT 不得为了“补库存”写数据库。

---

## 4. 目标数据模型

### 4.1 通用约定

- 每个新表使用内部 `BigAutoField`，同时保留不可变公开业务 ID：`event_id`、`todo_id`、`reminder_id`、`group_id`、`series_id`，均为 `UUIDField` 或兼容历史异常值的 `CharField`。
- 历史 `id='1'`、第三方 UID 等不应强制转换失败。迁移期使用 `legacy_id` / `LegacyPlannerIdMap` 保留映射；新创建对象使用 UUID。
- 所有时间统一由 `PlannerTimeCodec` 解析。数据库存 aware UTC `DateTimeField`，另存 `tzid` 用于 recurrence 的墙上时间语义；旧 API 的 naive Asia/Shanghai 字符串仅由 compatibility adapter 输出。
- event 必须支持 `is_all_day`、`start_date/end_date`（RFC 5545 end exclusive）和 timed `start_at/end_at`。全天、浮动时间、TZID 不得再被静默压成午夜 Asia/Shanghai。
- 核心表使用 `version` 单调递增，所有写入校验 `If-Match` / expected version。SQLite WAL 不足以消除业务层 lost update。
- `metadata JSONField` 只容纳低频、已命名的兼容扩展；不再把查询字段放入 JSON。
- event/todo/reminder 使用软删除，外部同步与审计可看到 tombstone；真正物理清理按保留期任务执行。

### 4.2 非重复业务实体

| 模型 | 必须字段 | 关系、约束和索引 |
|---|---|---|
| `EventGroup` | `user`, `group_id`, `name`, `description`, `color`, default_*、`working_hours`, `version` | `UNIQUE(user, group_id)`；`(user, name)`；event group FK 为 `SET_NULL` |
| `CalendarEvent` | `user`, `event_id`, `group`, title/description/location/status、timed/all-day 时间字段、importance/urgency/ddl、`version`、软删除字段 | `UNIQUE(user, event_id)`；`(user,start_at,end_at)`、`(user,group,start_at)`、`(user,status,start_at)` |
| `Todo` | `user`, `todo_id`, `group`, title/description、due 时间/日期、estimated_duration、importance/urgency/status/priority_score、`version` | `UNIQUE(user, todo_id)`；`(user,status,due_at)`、`(user,group,due_at)` |
| `Reminder` | `user`, `reminder_id`, title/content、base trigger、priority/status、snooze、notification 字段、linked event/todo、`version` | `UNIQUE(user, reminder_id)`；`(user,status,trigger_at)`；链接以 FK 表达 |

关系表：

| 模型 | 作用 |
|---|---|
| `EventTag`、`TodoTag` | 规范化 tags，`UNIQUE(parent, normalized_tag)` |
| `TodoDependency` | `todo -> depends_on` 自关联，禁止 self reference；服务层检测循环 |
| `EventReminderLink`、`TodoReminderLink` | 双向关联，不再靠两个字符串列表维持一致 |
| `EventShareGroup` | `CalendarEvent -> CollaborativeCalendarGroup`；替代 `shared_to_groups` JSON |
| `ReminderAdvanceTrigger` | `time_before_seconds`、priority、message、是否已发送；每个提醒独立记录 |
| `PlannerLegacyIdMap` | `user/type/legacy_id -> event/todo/reminder/series/recurrence_id`；只用于旧 API、旧 Agent cache、旧链接迁移 |

`converted_from_todo` / `converted_to_event` 改为显式 nullable FK，并保留其 legacy ID 映射。todo 转换和 event 创建必须在一个 `transaction.atomic()` 中。

### 4.3 Event recurrence

`CalendarEvent` 只存单次 event 或 recurrence master。重复实例没有 `CalendarEvent` 行。

| 模型 | 字段和用途 |
|---|---|
| `EventRecurrenceSeries` | `series_id`、`master_event OneToOne`、`ical_uid`、`rrule`、`dtstart`、`tzid`、`sequence`、`parent_series nullable`、`split_recurrence_id nullable`、`version`、软删除。`ical_uid` 在同一 user 内唯一且永久稳定。 |
| `EventRecurrenceRDate` | `series`、`recurrence_id` / `starts_at`；显式补充 occurrence。 |
| `EventRecurrenceExDate` | `series`、`recurrence_id`、source；仅表示 RFC `EXDATE`，`UNIQUE(series, recurrence_id)`。 |
| `EventOccurrenceOverride` | `series`、`recurrence_id`、`kind=modified|cancelled`、`patch JSONField`、`effective_start_at/effective_end_at`（查询加速）、`version`、软删除。`UNIQUE(series, recurrence_id)`。 |
| `EventRecurrenceSplitReview` | 可选的迁移/改规则安全表；存无法自动映射的未来 override，未处理前阻止分裂提交。 |

`patch` 只保存明确覆盖的字段及其存在性，例如 `{"title":"新标题","start_at":"..."}`。它不能使用“空字符串表示未提供”的旧约定。`effective_*` 是由主对象和 patch 计算的查询投影，不能替代 patch 的语义。

必要约束：

```text
EventRecurrenceSeries.master_event.user == series.user
EventOccurrenceOverride.recurrence_id 的类型必须与 series DTSTART 一致
modified override 有有效的实际时间范围；cancelled override 不可同时有内容 patch
parent_series 只允许同一 user；split_recurrence_id 必填时 parent_series 必填
```

### 4.4 Reminder recurrence 与通知状态

提醒也不预生成未来 reminder 行，但不能丢失“某一次已发送、完成、忽略或延后”的状态。

| 模型 | 用途 |
|---|---|
| `ReminderRecurrenceSeries` | 与 Event series 对称：main reminder、`series_id`、`ical_uid`（若作为 Feed/CalDAV 资源）、rrule/dtstart/tzid/lineage/version。 |
| `ReminderRecurrenceRDate`、`ReminderRecurrenceExDate` | RFC 规则补充/排除。 |
| `ReminderOccurrenceState` | 仅在某次 occurrence 被发送、snooze、完成、忽略、取消或人工覆盖时创建；键为 `(series, recurrence_id)`。保存 effective trigger、status、snooze_until、notification_sent_at、delivery lease、patch 和 version。 |
| `ReminderDeliveryAttempt` | 可选审计表，记录投递请求、结果、失败和重试；不把状态塞回主 reminder。 |

通知 worker 每次只展开 `now - grace` 到 `now + lookahead` 的窗口，查询 `ReminderOccurrenceState` 排除已处理/已租约的 occurrence，然后用唯一键和短事务领取。它绝不为未来一年先写 365 行。单次 reminder 仍直接使用 `Reminder` 的状态字段，重复 reminder 的某次状态写入 `ReminderOccurrenceState`。

### 4.5 共享日程和同步版本

`EventShareGroup` 是唯一关系事实源。`GroupCalendarData.events_data` 不再由业务写入；它在迁移期仅作为 legacy cache 和校验输入。

新增：

| 模型 | 用途 |
|---|---|
| `ShareGroupCalendarVersion` | 每个分享组一个单调 `version`、`updated_at`，替代把完整 events JSON 复制到 `group_calendar_data`。 |
| `CalendarCollectionVersion` | owner 默认日历、每个 EventGroup、reminders collection 的版本和 sync token 序列。 |
| `CalendarChange` | collection、token/version、resource type/id、action、etag、时间；支持 CalDAV `sync-collection` 和删除 tombstone。 |

查询分享组日程时直接 join owner event、share link、membership 和成员颜色；返回只读标记。若某天仍需要缓存，缓存必须是可丢失的投影，不能成为写入源。

---

## 5. 新 RRule 引擎

### 5.1 模块边界

新增 `core/planner/recurrence/`，禁止继续让 view 继承 reminder manager：

```text
codec.py        RFC 5545 parse/canonicalize/validate，处理 TZID、DATE、UTC、floating
expander.py     纯函数：series + range + rdate/exdate/overrides -> OccurrenceRef[]
commands.py     create/update/delete/split/detach 的原子写命令
repository.py   ORM 读取、行级版本检查、批量预取
caldav.py       VEVENT <-> domain recurrence mapping
legacy.py       迁移期 JSON import/export，仅此处可理解旧字段
```

`python-dateutil` 继续作为服务端规范展开器；允许 RFC 5545 常用字段：`FREQ`、`INTERVAL`、`COUNT`、`UNTIL`、`WKST`、`BYSECOND`、`BYMINUTE`、`BYHOUR`、`BYDAY`（含序号）、`BYMONTHDAY`、`BYYEARDAY`、`BYWEEKNO`、`BYMONTH`、`BYSETPOS`。拒绝 dateutil 私有扩展（例如 `BYEASTER`）并返回结构化 422，不能静默降级为另一条规则。

### 5.2 规则规范化

写入前必须：

1. 从 DTSTART 的日期类型决定 DATE 或 DATE-TIME recurrence。
2. 使用系列 `tzid` 在本地墙上时间解析 RRULE；数据库时间可为 UTC，但 recurrence 计算不能先把墙上时间丢失。
3. 规范化键名大写、键排序、重复项去重，并保存 `rrule_canonical`。
4. 校验 `COUNT` 与 `UNTIL` 不同时出现；校验 UNTIL 类型与 DTSTART 匹配。
5. 将 iCalendar 的 `EXDATE` / `RDATE` 拆入对应表，不允许留在 rrule 字符串。
6. 为导入的未知但可保留 iCalendar 属性使用受控 `ical_metadata`，并在返回时 round-trip；未知属性不得通过 `DATA_SCHEMA` 丢弃。

### 5.3 纯展开算法

给定 series 和 `[range_start, range_end)`：

1. 用 master DTSTART + canonical RRULE 创建 `rruleset`。
2. 加入 RDATE，移除 EXDATE。
3. 仅生成与时间窗相交的 base occurrence，设置不可变 `recurrence_id`。
4. 批量读取该窗内 override/state，取消 occurrence 删除，modified occurrence 用 patch 合成实际属性和时间。
5. 避免 base 与 RDATE、override 重复，按实际开始排序，带出 `OccurrenceRef`。
6. 对跨窗长 event 使用 `effective_end > range_start AND effective_start < range_end`；不能只按开始时间过滤。

展开器不读写数据库，不补库，不依赖当前时间；“now”必须由调用者显式传入，才能可靠测试。

### 5.4 写操作语义

所有 API、Agent 和 CalDAV 均转成以下 command，command 内执行 `transaction.atomic()`、expected version 校验、审计、collection version 递增和 cache invalidation。

| 操作 | 单次对象 | recurrence `single` | recurrence `all` | recurrence `this_and_future` |
|---|---|---|---|---|
| 编辑字段 | 更新本行 | 建/改 `modified` override | 更新 master；原 override 保留 | 截断父 series，创建 child series 和新 master |
| 删除 | 软删除本行 | 建 `cancelled` override 或 EXDATE | 软删除 master + series | 以 occurrence 边界截断父 series |
| 取消重复 | 不适用 | 将当前 override/occurrence 变单次 event | master 改单次，审计旧 series | 父截断，当前 occurrence 变单次，后续按用户策略处理 |
| 修改规则 | 转为新 series | 禁止隐式修改当前一条规则；要求“此及以后” | 重写当前 master RRULE | 创建 child series，不改写历史系列 |

“此及以后”精确流程：

1. 客户端必须传入旧规则中的 `recurrence_id`，而不是实际移动后的 `start` 或旧预生成 UUID。
2. 展开器确认该 recurrence slot 存在且未取消，计算父系列截至该 slot 前的结束边界；对 COUNT 规则计算保留 occurrence 数，对 UNTIL 规则规范化为正确的上界。
3. 父 series 保留 `< recurrence_id` 的历史，创建 `child_series(parent_series, split_recurrence_id)`，child 的 DTSTART、RRULE 和模板来自用户本次输入。
4. 该 slot 由 child master 表示；之后 occurrence 由 child 规则生成。旧 master、旧 UID、旧 CalDAV resource 保持稳定。
5. 父 series 之前的 EXDATE/override 原样保留。边界之后已有 override 不能悄悄丢失：默认返回 `409 recurrence_split_requires_override_policy`，UI/Agent 必须选择 `keep_as_single`、`discard_with_audit` 或在引擎明确可一一映射时 `map_by_ordinal`。
6. 全部行、links、collection version 和 audit 在一个事务提交；任何失败不产生半截断系列。

这比当前“改数百条预生成 JSON 行，再尝试重建规则段”的逻辑小得多，并且与第三方客户端常见的“截断旧 master + 创建新 master”流程直接对应。

---

## 6. Web API 与前端升级

### 6.1 新的领域 API

保留旧 URL 作为短期 compatibility adapter，新增版本化 API，避免在旧 JSON shape 上叠加更多含义。

| API | 用途 |
|---|---|
| `GET /api/v2/planner/definitions?from=&to=` | 前端日历拿单次对象、event/reminder master、规则、RDATE/EXDATE、窗口内 override/state 和 collection version；不返回预生成实例。 |
| `GET /api/v2/planner/occurrences?types=&from=&to=` | 后端展开的只读投影，供 Agent、搜索、冲突检测、CalDAV、提醒 worker 和不具备前端规则库的客户端。 |
| `POST /api/v2/events/`、`PATCH /api/v2/events/{id}`、`DELETE /api/v2/events/{id}` | 请求体显式 `scope`、`series_id`、`recurrence_id`、`expected_version`。 |
| `POST /api/v2/reminders/occurrences/{ref}/action` | 对某次重复提醒执行 snooze/complete/dismiss/mark-sent，写 `ReminderOccurrenceState`。 |
| `GET /api/v2/search` | 服务器端搜索和 occurrence 窗口过滤，替代浏览器全量下载。 |
| `GET /api/v2/calendar/changes?cursor=` | Web/移动端增量刷新；CalDAV 使用同一 collection change log。 |

统一错误码：`409 version_conflict`、`409 recurrence_split_requires_override_policy`、`422 invalid_rrule`、`422 recurrence_id_not_in_series`、`404 occurrence_not_found`。旧接口可保持历史成功 JSON，但不得继续依赖 materialized UUID。

### 6.2 前端渲染

前端应引入固定版本的 `rrule` 与 FullCalendar RRule plugin，放入受版本管理的静态资源或经过项目 CDN 初始化，不在运行时从不固定 URL 注入。当前 FullCalendar 仅接收已展开 event，不能假设已有 recurrence plugin。

渲染流程：

1. FullCalendar `events(info)` 请求 definitions，范围使用 `info.start/info.end` 加一段小 buffer。
2. 纯前端 adapter 将 master + `rrule/rdate/exdate/overrides` 展开为当前窗口 occurrence；单次对象直接加入。
3. 每个虚拟 FullCalendar event 的 `id` 使用编码后的 `OccurrenceRef`，例如 `occ:event:{series_id}:{recurrence_id}`；`extendedProps` 保存完整 ref 和 `source_version`。
4. `eventClick`、drag/drop、resize、删除和编辑不再提交虚拟 `id`，而提交 `{event_id, series_id, recurrence_id, scope, expected_version}`。
5. 成功写入后刷新该范围 definitions；不在本地手写“把未来 20 行加 offset”的乐观逻辑。

保留现有 UI 的 `single/all/future` 选择，但文案和协议统一为：

```text
仅此一次        -> single
整个系列        -> all
此及以后        -> this_and_future
从指定 occurrence -> recurrence_id / this_and_future 的明确锚点
```

拖拽单次 occurrence 是 `modified override`；拖拽“此及以后”是 split command。创建/编辑对话框仍可生成常用 RRULE，但解析器要能显示并保留第三方客户端创建的完整受支持规则，不得只解析 DAILY/WEEKLY/MONTHLY 的子集后覆盖原规则。

### 6.3 搜索和冲突检测

当前全局搜索下载所有数据并在浏览器过滤，数据增长后不可接受，也无法正确找到无限系列未来 occurrence。改为：

1. 在 SQLite 使用 FTS5 虚表或受控 search index 索引 event master、override patch、todo、reminder 的标题/正文；不为每个正常 occurrence 建索引。
2. `/api/v2/search` 先筛选文本候选 master，再对请求时间窗展开 recurrence，最后合并 todo/reminder/共享权限过滤。
3. 搜索结果对重复项返回 `OccurrenceRef`，点击直接打开那个 occurrence 的详情/编辑 scope UI。
4. 全局搜索仍保留类型、日程组、分享组、过去/今天/本周/本月/未来筛选；筛选由服务端执行，浏览器只呈现分页结果。
5. `check_schedule_conflicts` 使用同一 occurrence query service 展开范围后检测，不读取只存 master 的数组。共享日程必须以只读 ref 返回。

### 6.4 待办和提醒 UI

- Todo 列表、四象限、分组筛选、状态筛选、拖入日历和转换为 event 均直接查询 `Todo` 表；todo 不因本次升级获得 recurrence。
- Reminder 列表显示 master/单次对象及当前筛选窗口的虚拟 occurrence。完成、忽略、snooze 仅作用于该 `recurrence_id`，不会错误地把整个无限系列状态改成 completed。
- `notification_sent` 从当前前端占位接口迁到真实 occurrence state / delivery attempt；浏览器通知仍可保留，但后端必须具备幂等标记。

---

## 7. Service、Agent、附件和回滚

### 7.1 Service 收敛

新 service 不接收伪造 HTTP request，不调用 view：

```text
PlannerQueryService.list_definitions(user, range)
PlannerQueryService.list_occurrences(user, filters, range)
PlannerCommandService.create_event(...)
PlannerCommandService.patch_event(..., scope, occurrence_ref, expected_version)
PlannerCommandService.delete_event(...)
PlannerCommandService.convert_todo_to_event(...)
PlannerCommandService.act_on_reminder_occurrence(...)
```

旧 `EventService` / `TodoService` / `ReminderService` 在过渡期可成为薄 adapter，随后删除。禁止 `EventService.bulk_edit()` 用 `APIRequestFactory` 调用 `bulk_edit_events_impl()` 的循环依赖。

### 7.2 Agent 工具契约

`search_items` 改为调用 `PlannerQueryService.list_occurrences()`：

- 有时间范围时精确展开该范围。
- 无时间范围时明确默认窗口，例如过去 30 天到未来 90 天，并在工具输出中说明；不能把无限系列的所有 occurrence 返回给 LLM。
- 缓存项格式改为 `{type, entity_id, series_id, recurrence_id, version, title}`，`#N` 解析必须验证 user、类型和版本。
- `update_item/delete_item` 对 recurrence result 强制显式 scope；模型未指定时工具返回澄清错误，不猜测 whole series。
- 写成功后更新/失效 cache；回滚后清该会话 cache。

MCP、Quick Action、WebSocket 和 legacy tools 均只调用上述 service。MCP 固定 session cache ID 可以保留，但 cache 的 owner 必须参与所有查询。

### 7.3 附件内部元素

`InternalElementParser` 和 `/api/agent/attachments/internal-*` 改为：

```text
get_internal_item(user, type, entity_id, series_id=None, recurrence_id=None)
list_attachable_items(user, type, query, range, cursor)
```

对虚拟 recurrence occurrence 生成文本时，展示“原 series + 本次 occurrence + 是否 override”；保存的 SessionAttachment 仍冻结 `internal_snapshot`，因此源对象后来变化或删除不会改写历史对话。

### 7.4 事务和回滚

每次 Planner command：

1. `transaction.atomic()` 包住 version 校验、所有领域行、关系行、CalendarChange、审计和 AgentTransaction。
2. 使用 `reversion.create_revision()` 对新模型做粒度版本；不要再对完整 UserData JSON 快照。
3. 写一个 `PlannerChangeSet`，只记录本命令触及对象的 before/after public IDs、版本和必要 payload，供精确回滚和排障。
4. Agent transaction 保存 `user`、`session_id`、`tool_call_id`、changeset/reversion revision；回滚必须按 user + session + tool call 过滤。
5. 回滚后重建 collection version、清 search cache、处理附件 soft delete、恢复 SessionTodo、摘要和 token snapshot。

这同时修复首次创建时旧 `UserData` key 尚不存在、无法进入 pre-operation snapshot 的问题。

---

## 8. CalDAV、订阅 Feed 和 iCalendar

### 8.1 单一映射层

新增 `core/planner/ical.py`，HTTP Feed 与 CalDAV builder/parser 共用，禁止两个模块各自拼 UID 和 RRULE。统一规则：

- 单次 event：一个 VEVENT，一个稳定 UID。
- recurrence series：一个 master VEVENT（UID、DTSTART、DTEND/DURATION、RRULE、RDATE、EXDATE）加所有 sparse override VEVENT（同 UID、RECURRENCE-ID、必要时 STATUS:CANCELLED）。
- 全部 `RECURRENCE-ID` 使用原始槽位和原 TZID/DATE 类型，实际移动时间写在 override DTSTART/DTEND。
- `SEQUENCE` 从 series version 映射；`DTSTAMP/LAST-MODIFIED` 使用精确更新时间。
- `ical_uid` 从 CalDAV 导入时原样保存；Web 创建生成稳定 UID，订阅 Feed 与 CalDAV 使用同一规则，修复当前 `evt-` 与非 `evt-` 不一致。

### 8.2 CalDAV 写入

CalDAV view 只负责鉴权、HTTP 状态和 XML/iCal 编解码，所有 PUT/DELETE 调用 Planner command。

必须支持或明确拒绝：

| iCalendar 输入 | 目标行为 |
|---|---|
| UID、SUMMARY、DESCRIPTION、LOCATION、STATUS | 映射到 master/override 标准字段 |
| DTSTART/DTEND/DURATION、TZID、DATE | 用 `PlannerTimeCodec` 保留时区/全天语义 |
| RRULE | canonicalize 后写 series |
| RDATE / EXDATE | 写正规关系表，GET 必须再输出 |
| RECURRENCE-ID | 写/更新 one occurrence override；DELETE 单次用 cancelled override 或 EXDATE |
| `RECURRENCE-ID;RANGE=THISANDFUTURE` | 调用 split command；若客户端走“先截断旧 UID、再 PUT 新 UID”，通过 CalDAV import transaction/lineage correlation 保持等价 |
| SEQUENCE / If-Match / If-None-Match | 映射 expected version，冲突返回 412 |
| VTODO | 本期返回明确 501/403，不误解析为 VEVENT |

提醒 collection 保持只读；todo 保持不在 CalDAV collection 中。HTTP Feed 继续把 todo/reminder 输出为 VEVENT+VALARM，保证 Apple 订阅兼容。

### 8.3 查询和增量同步

- `calendar-query` 调用 occurrence expander，以 master 早于窗口也能返回的方式筛选。
- ETag 使用不可逆 resource public ID + 单调 version，不能只使用秒级 `last_modified`。
- CTag/同步 token 使用 `CalendarCollectionVersion`。
- 增加 `sync-collection` REPORT 和 `CalendarChange` tombstone；如果本期不实现，则不得在 DAV capability 中宣称支持。
- PROPFIND、multiget、GET 对一个 recurrence series 只暴露一个 resource href，不再依赖“预生成实例去重”。

---

## 9. 数据迁移策略

### 9.1 前置保护

1. 用 SQLite online backup API 或停写窗口下的一致性备份，不要逐个复制 WAL/SHM 文件作为唯一备份。
2. 运行审计 command，记录每个 `(user,key)` 的源行、checksum、行数、重复 key、异常时间、重复 series、未知字段。
3. 先人工决策并处理重复 `(user,key)`，不能在有重复 source 时执行 `.get()` 迁移。
4. 迁移前创建 staging 数据库副本并演练；生产迁移 command 默认 dry-run，写入必须显式 `--apply`。
5. 为每个 user/key 写 `PlannerMigrationState` 和 `PlannerMigrationIssue`，不允许将不能无损解释的数据悄悄跳过。

### 9.2 迁移顺序

1. 新建模型、约束、admin、repository、codec、纯 expander 和 audit commands，但不切换任何读写。
2. 将所有直接 `UserData` 调用先改到 legacy repository，保证行为不变；包括 views、Service、CalDAV、Feed、share group、Agent、attachment parser、课程导入。
3. 迁移 `EventGroup`、todo、reminder、event 及关系；普通非重复项可一对一导入。
4. 对每个 recurrence series 做语义迁移和 verification，不把预生成 instance 当成永久目标行。
5. 在 legacy source 为主的阶段，中央 repository 双写/影子投影到新表并做差异报告；任何调用点不得绕过 repository。
6. 切换一个 user cohort 的**全部** Planner readers/writers 到新表，legacy JSON 只读保留。不要让一部分读取旧预生成行、另一部分写新 series。
7. 切 Web/Agent/Feed/共享，最后单独切 CalDAV PUT/DELETE；保留快速 feature flag 回退到 legacy repository。
8. 连续稳定期后停止核心 `UserData` 写入，归档 JSON 和 `PlannerLegacyIdMap`，再做物理清理计划。

### 9.3 recurrence 迁移算法

对每个 legacy `series_id`：

1. 收集主 event、同 series 普通行、`is_detached` 行、`original_series_id` 行、`events_rrule_series` 中运行时 segments、字符串内 EXDATE 和 reminder storage 的 exceptions。
2. 优先以 main event + 实际运行时 segment 数据建立 canonical series；若历史 segment 表示规则变化，则按 segment 边界转换为有 lineage 的多个新 series，而不是强行塞入一条 rrule。
3. 在覆盖所有已存 instance 的历史/未来窗口内，用旧规则展开 expected slots。
4. 与 legacy 普通实例比较：完全等价的实例不迁移为行；显式 EXDATE、缺失且能证明是删除的槽位迁移为 EXDATE；字段/时间不同的实例迁移为 override；无法判断的差异写 `PlannerMigrationIssue`，该 user 不可切换。
5. 将 legacy instance UUID 写到 `PlannerLegacyIdMap -> (series_id, recurrence_id)`，保证旧前端请求、Agent cache、reminder link 和附件引用在兼容期仍可解析。
6. 对 reminder 同样迁移规则和 sparse state；`notification_sent`、snooze、completed/dismissed 的实例转为 `ReminderOccurrenceState`，不再生成“普通未来 reminder 行”。
7. 输出新旧在固定窗口的 occurrence diff：数量、recurrence_id、实际开始/结束、title、status、group、分享关系、override 类型。只有预生成库存本身的消失可白名单；语义差异不可白名单。

### 9.4 兼容开关

```text
PLANNER_STORAGE_MODE=legacy | shadow | normalized
PLANNER_DIFF_ASSERT=false | log | fail_non_production
PLANNER_LEGACY_FALLBACK=true | false
PLANNER_CALDAV_NORMALIZED=false | true
```

切换必须按 user cohort、入口和日期记录。开关只存在迁移期，最终删除，不能留下永久双事实源。

---

## 10. 测试方案

### 10.1 原则

现有 `tests/test_caldav*.py` 多数是硬编码 localhost/token 的 live script，有的在 import 时请求真实服务，不能作为隔离回归测试。保留为开发 smoke script，但必须改造/新增为 Django `TestCase`、`TransactionTestCase` 和 Channels 测试，使用临时数据库、临时 user/token、固定时钟。

所有自动测试不得使用仓库中的真实 token、用户名或生产 SQLite。

### 10.2 单元测试

| 套件 | 覆盖 |
|---|---|
| `test_planner_time_codec.py` | naive Shanghai、UTC、offset、TZID、DATE、all-day、DST（至少 America/New_York）、非法格式 |
| `test_recurrence_expander.py` | DAILY/WEEKLY/MONTHLY/YEARLY、INTERVAL、多个 BYDAY、月末/负 BYMONTHDAY、序号 BYDAY、COUNT、UNTIL、WKST、RDATE、EXDATE、跨窗 event |
| `test_recurrence_overrides.py` | modified/cancelled、移动 occurrence、主对象字段更新后 patch 合并、同 recurrence_id 去重 |
| `test_recurrence_split.py` | this-and-future、重复分裂、COUNT 截断、UNTIL 截断、未来 override 需要 policy、父子 lineage |
| `test_reminder_occurrence_state.py` | 仅一次完成/忽略/snooze、delivery 幂等、租约重试、不预生成未来 state |
| `test_planner_models.py` | 唯一约束、软删、版本冲突、关系 FK、todo 依赖环、event/todo 转换原子性 |
| `test_ical_mapping.py` | RRULE/RDATE/EXDATE round trip、RECURRENCE-ID、UID 稳定、all-day、TZID、DURATION、未知属性保留 |

每个 recurrence 测试都要断言：连续调用读取/展开不会新增 event/reminder/occurrence 行；无限 DAILY 规则在读取 10,000 个窗口后，持久化记录数仍等于 master + 稀疏例外/state。

### 10.3 前端契约和 UI 测试

1. 用固定 fixture 生成 `definitions` JSON；浏览器端 rrule adapter 与服务端 expander 在同一时间窗的 `{recurrence_id,start,end}` 集合必须完全相同。
2. FullCalendar 月/周/日/两日/列表视图切换，验证 master 早于窗口的无限系列仍显示。
3. 拖拽 single 只发送 occurrence ref；拖拽 this-and-future 创建 child series；all 只更新 master。
4. 日程过滤、提醒筛选、todo 四象限、分组颜色、共享只读、全局搜索点击 occurrence、移动端布局均需 E2E 覆盖。
5. 全局搜索不能再发全量 events/reminders/todos 请求；断言只请求分页 `/api/v2/search`。

推荐 Playwright 驱动浏览器 E2E；若项目不引入 Node 测试栈，至少用 Django `LiveServerTestCase` + Playwright 独立 runner。所有 selector 使用稳定 `data-testid`，不要依赖中文文案。

### 10.4 REST 和 service 集成测试

每个场景同时验证数据库状态、API JSON 和 range occurrence 输出：

```text
1. 创建/修改/删除单次 event、todo、reminder。
2. todo -> event：两个表和链接在同一事务一致；失败时均不改变。
3. 创建无限 daily series：只出现一个 master 和一个 series。
4. 删除一个 occurrence：生成 EXDATE/cancelled override，下一次 GET 不会复活。
5. 修改一个 occurrence：只生成一个 override，其他 occurrence 继承 master 更新。
6. 修改 this-and-future：父/子系列、边界、UID、历史和 policy 正确。
7. 同一 expected_version 并发 PATCH：一个成功、一个 409；没有 lost update。
8. event/reminder 链接、tags、todo dependencies、share links、软删除和 restore。
9. 课程导入规则、旧创建/更新 URL compatibility、旧 JSON export adapter。
10. range query 包含跨窗 event，且不会写数据库。
```

### 10.5 Agent、Quick Action、MCP 和附件测试

| 范围 | 必测行为 |
|---|---|
| Unified tools | 搜索未来无限 occurrence，`#N` 指向 occurrence ref，single/all/this-and-future 写入正确 |
| Legacy tools | 在兼容期正确委托 service，不直接访问 UserData |
| Cache | 更新后标题/ref 刷新，删除/回滚后失效，跨 user/session 不可解析 |
| Conflict analyzer | 指定范围展开后检测 recurrence 与共享日程冲突 |
| WebSocket | 工具 mutation 后前端刷新，tool_call_id 可回滚，session 归属校验 |
| Quick Action | 统一工具、tool_call_id 透传、timeout、任务记录和回滚 |
| MCP | stdio/HTTP 均以当前 user 执行，search/write recurrence ref 正确，拒绝无效 token |
| Attachments | 选取 master 和 occurrence、保存 immutable snapshot、源删除后历史附件仍可读 |

Agent rollback 特别测试：创建 series、修改单次 override、split series、todo 转 event、snooze reminder occurrence 后分别回滚，验证只撤销目标 command，search cache/附件/SessionTodo 同步恢复。

### 10.6 CalDAV 和 Feed 测试

用 Django 测试 client 的 `generic("PROPFIND", ...)` / `generic("REPORT", ...)` 编写 hermetic 测试；真实 iOS/Thunderbird 测试作为最终手工验收。

| 场景 | 断言 |
|---|---|
| discovery/auth | `.well-known`、principal、home、Basic/Token/Bearer、拒绝未认证 |
| collection | default/group/reminder collection、ETag/CTag/version、PROPFIND 不重复 href |
| master | CalDAV PUT 无限 RRULE 后 DB 只有 master/series；GET 输出 RRULE |
| EXDATE/RDATE | PUT/GET round-trip，EXDATE occurrence 不再展示/生成 |
| only this | 多 VEVENT PUT 生成同 UID + RECURRENCE-ID override |
| this and future | RANGE 参数或 iOS 两 PUT 序列正确形成父/子 series |
| query | master DTSTART 早于窗口仍在 `calendar-query` 出现 |
| concurrency | If-Match 旧 ETag 返回 412；同秒两次更新 ETag 仍变化 |
| delete | master DELETE 删除整个 series；单 occurrence cancellation 按 RFC 输入处理 |
| reminders/todos | reminder CalDAV PUT/DELETE 保持 403；todo 不意外出现在 CalDAV；Feed 仍输出 todo/reminder VEVENT+VALARM |
| sync | sync-token 增量含 create/update/delete tombstone（实现后） |

### 10.7 迁移校验命令

实现以下管理命令，默认只读或 `--dry-run`：

```powershell
.venv\Scripts\python.exe manage.py audit_planner_legacy --output logs/planner-audit.json
.venv\Scripts\python.exe manage.py migrate_planner_legacy --dry-run --user-id 42
.venv\Scripts\python.exe manage.py migrate_planner_legacy --apply --batch-size 50
.venv\Scripts\python.exe manage.py verify_planner_migration --strict --from 2020-01-01 --to 2035-01-01
.venv\Scripts\python.exe manage.py verify_recurrence_parity --sample all --from 2020-01-01 --to 2035-01-01
.venv\Scripts\python.exe manage.py report_planner_direct_userdata_access
```

`verify_planner_migration` 至少验证：业务 ID 集合、普通对象字段、关系表、软删除、系列数量、每个窗口的 occurrence 集、RDATE/EXDATE/override、提醒状态、分享关系、CalDAV UID 和 legacy ID mapping。失败输出可机读 JSON，包含 user、source row、series 和 field diff，不输出密钥。

### 10.8 阶段执行命令

在新增测试后，实施者可按以下顺序执行：

```powershell
.venv\Scripts\python.exe manage.py check
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.venv\Scripts\python.exe manage.py migrate --plan
.venv\Scripts\python.exe manage.py test core.tests agent_service.tests caldav_service.tests
.venv\Scripts\python.exe manage.py test tests.test_planner_time_codec tests.test_recurrence_expander tests.test_recurrence_split
.venv\Scripts\python.exe manage.py test tests.test_planner_api tests.test_planner_agent tests.test_planner_caldav
```

现有 hard-coded live scripts 只能在隔离开发数据库、临时 token、显式 `RUN_LIVE_CALDAV_TESTS=1` 时运行，不能在 CI 或共享数据上直接执行。

---

## 11. 实施分期与验收

### P0：基线和风险修复

- 完成一致备份、审计、重复 UserData key 处置。
- 固化当前 API/CalDAV/Agent 行为为隔离测试。
- 修复或隔离 Agent rollback 的 user/session 归属问题、Quick Action tool_call_id 缺失、MCP HTTP 鉴权缺口；它们会影响迁移验证可信度。

验收：审计报告可复跑；没有测试使用真实 token；基线测试通过。

### P1：模型、codec、expander 和 legacy repository

- 新建正规表、关系表、version/change/audit 表。
- 实现纯 codec/expander 与完整 unit tests。
- 所有旧调用先通过 legacy repository，功能不变。

验收：`rg "UserData\.objects|set_value\(|get_or_initialize" core agent_service caldav_service` 的核心业务调用只剩 legacy adapter、迁移 command 和明确白名单。

### P2：历史迁移和语义校验

- dry-run、batch import、series classification、legacy ID map、issues quarantine。
- 对每用户/series 运行 occurrence parity。

验收：没有未解释 semantic diff；有 issue 的用户不进入切换 cohort。

### P3：Web/REST/搜索/共享切换

- 上线 v2 definitions/occurrences/search/command APIs。
- 前端接入 rrule adapter 和 occurrence refs；旧 URL 变 adapter。
- 用 join 查询替代共享 `events_data` 写入。

验收：日历、提醒、todo、搜索、群组和课程导入在 normalized cohort 工作；无限 series 不随读取增长。

### P4：Agent、附件、回滚切换

- 所有 tool、cache、conflict、attachment parser、Quick Action、MCP 只走 Planner services。
- 引入 ChangeSet 回滚，并验证 WebSocket/MCP/Quick Action。

验收：所有 scope 写入和回滚通过，附件历史稳定。

### P5：Feed 和 CalDAV 切换

- 统一 iCal mapper，CalDAV read/write/query 改用 recurrence service。
- 接入 version ETag、collection change；按实际实现决定是否宣称 sync-collection。

验收：自动 CalDAV 矩阵通过，并完成至少 iOS/macOS、Thunderbird/DAVx5 各一类手工交叉编辑。

### P6：停止 legacy 写入

- 关闭 shadow/legacy writes，保留只读归档和 mapping 至少一个明确发布周期。
- 监控错误率、query 时间、SQLite lock、series/override 数量、CalDAV 412、迁移差异。
- 期满后删除核心 JSON adapter 和 `GroupCalendarData.events_data` 写路径。

验收：核心业务 `UserData` 写入为零；全量测试、迁移校验和恢复演练通过。

---

## 12. 发布门槛和禁止项

上线 normalized recurrence 前必须全部满足：

1. 无限规则连续读取不创建普通 instance 行。
2. 所有 `single/all/this_and_future` 操作有可重复、原子、可回滚的测试。
3. 前端、服务端、CalDAV 对同一 fixture 的 occurrence 集一致。
4. 旧 CalDAV UID、HTTP Feed UID、业务 UUID、附件引用和 Agent `#N` 兼容路径已验证。
5. 搜索、冲突检测和提醒投递对 recurrence 使用时间窗展开，而不是扫描物化库存。
6. 任何新的业务代码不直接读写 `UserData`、`GroupCalendarData.events_data` 或 `rrule_engine.py` 旧存储后端。
7. 任何数据无法无损迁移时，保持 legacy source 并生成 issue；禁止“默认值覆盖后继续切换”。

以下做法明确禁止：

- 只把 JSON 列表拆为 event rows，但继续保存所有无限 occurrence。
- 为兼容旧前端，在新模型旁永久双写两套 recurrence 真相。
- 把 `EXDATE` 拼进 RRULE 字符串。
- 用 `start - 1 day` 处理所有规则截断，或用预生成行 UUID 作为 recurrence identity。
- 将 CalDAV、Agent 或 view 的重复规则推算各自复制一份。
- 在 GET/REPORT/搜索请求中为了补实例写业务数据。

---

## 13. 建议的第一批实现提交

按依赖关系，首批可执行工作应是：

1. 添加 Planner ORM 模型、migration state/issue、legacy ID map 和 admin，不切流量。
2. 添加 `PlannerTimeCodec`、纯 `RecurrenceExpander` 与 table-driven recurrence tests。
3. 添加 legacy repository，并逐个替换所有 core/Agent/CalDAV/Feed 直接 JSON 调用。
4. 添加 audit/migrate/verify/parity management commands，在数据库副本上完成一次演练。
5. 定义并实现 v2 definitions/occurrences/command 契约，再改 FullCalendar 的 occurrence adapter。

只有第 1-4 项证明历史数据可无损解释后，才进入 Web/Agent/CalDAV 写入口切换。这样可以避免在现有数千个预生成实例和复杂边界上边改 schema 边猜语义。
