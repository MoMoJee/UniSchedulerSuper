# P5 Feed 与 CalDAV V2 适配升级详细方案

> 文档日期：2026-07-13  
> 状态：P5-0 至 P5-F 已于 2026-07-13 全部实施并通过自动化与停机数据库验收。  
> 前置条件：P1–P4（含 P4-G）已经完成并通过验收。  
> 实施边界：适配现有 HTTP iCalendar Feed 与现有 CalDAV 功能到 normalized Planner V2；不以“完整实现 CalDAV 协议”为目标。

实施进度：P5-0 至 P5-F 已于 2026-07-13 通过验收；各阶段报告位于 `docs/P5验收报告/`，下一阶段为 P6。

## 1. 阶段目标与最终决策

P5 只解决两个问题：

1. `core/views_calendar_subscription.py` 不再从 legacy Planner JSON 读取，改为从 normalized Planner 查询并输出与现有订阅兼容的 iCalendar Feed。
2. `caldav_service` 的 discovery、读取、查询和 VEVENT 写入改用 Planner V2 application/query/command，不再直接读写 `UserData`、调用旧 View、预生成 recurrence instance 或自行修改 RRULE。

P5 必须遵守以下架构约束：

```text
HTTP Feed View ─┐
                ├─> PlannerApplicationService / calendar query façade
CalDAV View ────┘                 │
                                  ├─> normalized repository + expander
                                  ├─> Planner command（原子写入）
                                  └─> core/planner/ical.py（纯映射）
```

- Feed 与 CalDAV 共享同一个 iCalendar mapper、UID policy、时间 codec 和 recurrence 表达。
- CalDAV View 只处理认证、路径、HTTP 前置条件、XML/iCalendar 编解码与状态码。
- View 不直接写 ORM，不循环调用多个 HTTP API，不调用 legacy `EventService`，不复制 recurrence 算法。
- CalDAV 写入不获得 Agent 聊天回滚权限；它仍写正常 ChangeSet、版本和 collection change，并由数据库事务保证原子性。
- 读取、PROPFIND、REPORT、GET 和 Feed 生成必须无副作用。

## 2. 范围冻结：保留什么，不实现什么

### 2.1 P5 必须保留并适配的既有功能

| 能力 | P5 要求 |
|---|---|
| HTTP Feed URL | 保留 `GET /api/calendar/feed/?token=<token>&type=<all|events|todos|reminders>` |
| Feed 鉴权 | 保留 URL query token；缺少 token 为 400，无效 token 为 403 |
| Feed events | 输出 VEVENT；支持普通、重复 master、稀疏 override/cancellation |
| Feed todos | 仅输出有 due 的 Todo，转为 5 分钟 VEVENT + VALARM |
| Feed reminders | 转为 5 分钟 VEVENT + VALARM；重复提醒按 RRULE 展示 |
| CalDAV 鉴权 | 保留 Basic（用户名 + Token 或密码）、`Token`、`Bearer` |
| 服务发现 | 保留 `/.well-known/caldav`、`/caldav/`、principal、calendar-home-set |
| 日历集合 | 保留 default、每个 event group、始终存在的只读 reminders 集合 |
| 读取 | 保留 PROPFIND、calendar-multiget、calendar-query、GET |
| 写入 | 保留 VEVENT PUT create/update 和 DELETE；包括现有 Apple 客户端的系列编辑工作流 |
| 并发 | `If-Match`、`If-None-Match: *` 必须映射到 V2 单调版本并返回 412 |
| 只读提醒 | reminders collection 的 PUT/DELETE 固定拒绝，且拒绝时零写入 |
| 管理型方法 | MKCALENDAR 继续 403；PROPPATCH 只能保留当前无业务写入的兼容响应 |

### 2.2 明确不纳入 P5 的协议扩展

以下能力不因本次升级而新增：

- VTODO 的 CalDAV 读写；Todo 仍只存在于 HTTP Feed 的 VEVENT+VALARM 投影。
- CardDAV、Free/Busy、日历邀请/调度、ACL、共享 CalDAV collection。
- 客户端创建/删除/重命名日历集合；event group 仍由 UniScheduler 管理。
- LOCK/UNLOCK、COPY/MOVE、MKCOL、完整 WebDAV dead properties。
- 完整 `sync-collection` 增量协议。
- 任意时区数据库或对所有第三方 CalDAV 客户端的兼容承诺。

若 P5 没有实现 `sync-collection`，则：

1. `DAV`、`supported-report-set` 和其他 capability 响应不得宣称支持它；
2. 收到该 REPORT 时稳定返回 501；
3. 内部仍维护 `CalendarCollectionVersion`/`CalendarChange`，用于 CTag、审计和未来升级，而不是伪装协议已经实现。

## 3. 当前实现审计与必须消除的缺口

当前代码并未满足 P5：

| 文件/模块 | 当前行为 | P5 处理 |
|---|---|---|
| `core/views_calendar_subscription.py` | 直接读取 `LegacyPlannerRepository`，自带一套 builder/UID/RRULE 逻辑 | 改为 normalized query + 统一 mapper |
| `caldav_service/views/base.py` | 所有 loader 读取 legacy events/groups/todos/reminders | 删除 Planner legacy loader；改用协议 application façade |
| `caldav_service/views/event.py` | PUT 多处分支直接写兼容 UserData、调用旧 View manager、预生成实例 | 用一个原子 calendar-object command 替换全部分支 |
| `caldav_service/views/calendar.py` | `calendar-query` 按主行 start/end 过滤 | 使用 recurrence expander 判断窗口相交 |
| `caldav_service/ical_builder.py` / `ical_parser.py` | 与 Feed 重复实现；缺少 RDATE/EXDATE、DATE、DURATION 等完整往返 | 收敛到 `core/planner/ical.py` |
| `caldav_service/etag.py` | 以秒级 `last_modified` 和数量计算哈希 | 改用 immutable resource identity + 单调 version |
| `CalendarCollectionVersion` | command 已写 default event 版本，但 group move/多个 CalDAV collection 尚未形成完整语义 | P5 统一 collection change writer |
| `tests/test_caldav*.py` | 主要是需要真实服务、真实 token 的联调脚本 | 保留为显式 live smoke；新增 Django 隔离测试 |

P5-0 必须生成一份当前 capability 与行为基线。没有基线报告不得改写 CalDAV 路由。

## 4. 统一 iCalendar 领域映射

### 4.1 模块职责

新增 `core/planner/ical.py`，只接受 DTO/dataclass，不接收 Django request、不查 ORM、不写数据库：

```text
encode_event_resource(master, series, rdates, exdates, overrides) -> VCALENDAR bytes
decode_event_resource(bytes) -> ParsedCalendarObject
encode_feed(items, profile) -> VCALENDAR bytes
encode_todo_feed_item(todo) -> VEVENT + VALARM
encode_reminder_feed_item(reminder definition/state) -> VEVENT + VALARM
```

建议 DTO：

```text
CalendarObjectIdentity { resource_name, ical_uid, entity_id, series_id? }
ParsedCalendarObject   { uid, master, overrides, method?, unknown_metadata }
ParsedEventComponent   { recurrence_id?, range?, fields, recurrence }
```

mapper 必须复用 `PlannerTimeCodec` 和现有 canonical RRULE 工具。任何 RRULE 截断、series split、EXDATE 写入都由 command service 完成，不由 mapper 推算。

### 4.2 属性映射

| iCalendar | Planner V2 | 要求 |
|---|---|---|
| UID | immutable iCalendar identity | 导入值原样保留；同一 resource 内所有 VEVENT UID 必须一致 |
| SUMMARY | title | Unicode、空值策略固定 |
| DESCRIPTION | description/content | 正确转义换行、逗号、分号和反斜线 |
| LOCATION | location | Event 支持；Reminder/Todo Feed 不伪造业务字段 |
| STATUS | event status | CONFIRMED/TENTATIVE/CANCELLED 双向映射 |
| DTSTART/DTEND | start/end 或 trigger/due | 保留 DATE、TZID、UTC/offset 语义 |
| DURATION | 计算 end | 与 DTEND 同时出现时拒绝；不保存两套真相 |
| RRULE | series.rrule/canonical | 规范化后写入，输出不得拼入 EXDATE |
| RDATE | recurrence rdate rows | DATE/DATE-TIME 类型与 DTSTART 一致 |
| EXDATE | recurrence exdate rows | 正常 occurrence 不再展示；可往返 |
| RECURRENCE-ID | sparse override slot | 永远使用原始槽位，不随 effective time 移动 |
| `RANGE=THISANDFUTURE` | split command | 仅作为系列分裂输入，不在 View 中手改 UNTIL |
| SEQUENCE | series/resource version | 每次可见修改单调增加 |
| DTSTAMP/LAST-MODIFIED | 精确 updated timestamp | 输出 UTC；不得用请求时刻制造无意义变化 |

### 4.3 UID 与 href 兼容迁移

P5 必须把“iCalendar UID”和“CalDAV href 文件名”拆开，二者都必须不可变，但不要求文本相同。

实施时补齐单次 Event 的持久化 iCalendar identity，并为单次 Event/series 保存或稳定推导 `caldav_resource_name`：

1. CalDAV 导入过且 legacy `caldav_uid` 存在：canonical UID 原样保留。
2. 已有 recurrence series：沿用 `EventRecurrenceSeries.ical_uid`，不得重新生成。
3. Web 创建的已有单次 Event：以 P5-0 确认的既有 CalDAV UID 规则回填；href 保持当前客户端已见过的文件名。
4. 新建 Event：创建时一次性写 immutable UID/resource name；后续标题、时间、分组和 series scope 修改均不得改变它。
5. legacy href/UID 只作为查找 alias；成功解析后响应 canonical href，不能产生第二条业务 Event。

由于当前 Feed 与 CalDAV 对部分 Web 单次 Event 的 UID 前缀并不一致，P5-0 必须输出冲突清单并锁定唯一 canonical policy。2026-07-13 实际审计发现，MoMoJee 中一个普通 Web Event 与一条旧 CalDAV 回写 Event 会被旧 CalDAV 派生为同一个无前缀 UID，因此不能继续优先使用该规则。P5 实施采用：显式 legacy `caldav_uid` 原样保留；普通 Web 单次 Event 使用 Feed 已公开的 `evt-{event_id}@unischeduler`；CalDAV href 文件名继续保持原值。这样不会合并两条字段/分组不同的业务记录，并消除跨 resource UID 冲突。该一次性收敛必须做 CalDAV 全量刷新测试；如客户端保留旧 UID，发布说明要求移除并重新添加账户，不能长期保留两个 UID 投影。

### 4.4 recurrence resource 形态

- 单次 Event：一个 href，一个 VCALENDAR，内含一个 VEVENT。
- 重复系列：一个 href，一个 master VEVENT 加零到多个 sparse override VEVENT。
- modified override：相同 UID + RECURRENCE-ID + effective DTSTART/DTEND + patch 后字段。
- cancelled occurrence：相同 UID + RECURRENCE-ID + `STATUS:CANCELLED`，同时保证 V2 occurrence 查询不返回活动实例。
- 普通展开 occurrence 不落库、不产生 href、不出现在 PROPFIND 列表。
- series split 后父/子系列各是独立 resource；lineage 留在内部，不伪造相同 UID 的两个 master。

## 5. Planner 协议应用层

### 5.1 新入口与切换策略

在 `PlannerRolloutPolicy` 增加：

```text
calendar_feed
caldav_read
caldav_write
```

三者分开登记，避免“只读已经验证”被误当作“写入可以切换”。

- normalized Feed/CalDAV 禁止因异常静默回落到 legacy 数据。P5 允许现有 cohort 准入门禁只读核对 source checksum；该读取只能决定是否准入，不能参与业务响应，P6 将连同运行时门禁读取一起关闭。
- shadow 阶段允许同时构建 legacy 与 normalized 只读投影并比较，但业务响应仍只能选择一个明确事实源。
- `caldav_write` 只有 normalized 模式；不存在 legacy dual-write。
- 未通过 migration strict/parity 的用户不得开启这些入口。

### 5.2 读取 façade

增加只读 use cases：

```text
list_calendar_collections(context)
list_calendar_resources(context, collection_id)
get_calendar_resource(context, collection_id, resource_name)
query_calendar_resources(context, collection_id, range)
get_calendar_collection_version(context, collection_id)
build_calendar_feed(context, feed_type)
```

集合语义：

- `default`：无 group 或 group 已不存在的 Event；不是所有 Event 的重复汇总。
- `<group_id>`：只包含该用户该 group 的 Event。
- `reminders`：只读 Reminder 投影，集合即使为空也存在。
- Todo 不出现在任何 CalDAV collection。
- 不存在、已软删除或不属于用户的 group 必须返回 404，不能伪装为空集合。

### 5.3 写入 façade

增加一个原子 use case：

```text
apply_caldav_event_resource(
    context,
    collection_id,
    resource_name,
    parsed_object,
    precondition,
) -> CalendarObjectWriteResult
```

该 use case 在一个 `transaction.atomic()` 中完成：

1. 锁定 collection version 与目标 identity。
2. 校验 UID/href、owner、collection、If-Match/If-None-Match。
3. 新建或更新 master。
4. 对比并写 RDATE、EXDATE、modified/cancelled override。
5. 对 RANGE 或 Apple 的“截断旧资源 + 创建新资源”序列调用 split command。
6. 更新 Event/series/override version、受影响的旧/新 collection version 和 CalendarChange。
7. 写轻量 ChangeSet/audit；不创建聊天 rollback snapshot。
8. 任一步失败整体回滚。

禁止 View 依次调用多个 `patch_event` 后拼凑成功响应，因为中间失败会产生半系列。

### 5.4 collection version/change 语义

建立统一 writer：

```text
record_calendar_change(user, collection_id, resource, action, etag)
```

要求：

- Event create：目标 collection +1，写 create change。
- Event update：当前 collection +1，写 update change。
- Event group move：旧 collection 写 delete tombstone，新 collection 写 create；两边均 +1。
- Event delete：原 collection 写 delete tombstone。
- series override/RDATE/EXDATE 修改：所属 resource ETag、collection CTag 均变化。
- Reminder 业务修改：reminders collection CTag 变化，即使 CalDAV 本身只读。
- rollback 恢复：受影响 collection 仍生成新版本；版本绝不倒退。

P5 不对外开放 sync-collection，但 CalendarChange 的 token 唯一、连续、可审计，为未来实现留出正确基础。

## 6. HTTP/CalDAV 协议行为表

### 6.1 鉴权与权限

| 场景 | 状态/断言 |
|---|---|
| 无认证访问 `/caldav/` | 401 + `WWW-Authenticate` + DAV |
| `/.well-known/caldav` 未认证探测 | 保持当前兼容响应，且不得泄露用户名/集合 |
| Basic Token/密码、Token、Bearer | 合法时映射同一 user |
| 用户 A 访问用户 B 路径 | 403，响应不泄露资源是否存在 |
| 无效/禁用用户 | 401/403，零 Planner 查询或写入 |
| Feed token | 只从 query 取；日志不得记录 token；响应 `private`、禁止 CDN 公共缓存 |

### 6.2 方法与状态码

| 请求 | 成功 | 失败要求 |
|---|---|---|
| OPTIONS | 200 | `Allow` 只列当前资源真正支持的方法 |
| PROPFIND | 207 | Depth infinity 拒绝；畸形 XML 400 |
| REPORT multiget/query | 207 | 单 href 不存在返回该 response 404；不支持 report 501 |
| GET resource | 200 + ETag | 不存在 404；可选条件命中 304 |
| PUT create | 201 + Location + ETag | 无 UID/多 UID/UID 冲突/非法时间 400 或 409；超大 413 |
| PUT update | 204 + 新 ETag | stale If-Match 412；解析/领域失败零部分写入 |
| DELETE | 204 | stale If-Match 412；不存在 404 |
| reminder PUT/DELETE | — | 403，零写入 |
| MKCALENDAR | — | 403 |
| sync-collection | — | 501 且 capability 不宣称 |
| VTODO PUT | — | 501 或 415，测试锁定唯一行为 |

## 7. 分阶段实施、测试与验收

每阶段结束必须在 `docs/P5验收报告/` 写独立报告，记录代码范围、命令、通过数、失败数、生产数据只读校验和下一阶段调整。前一阶段未达到验收标准不得继续。

### P5-0：能力基线、数据身份审计与测试隔离

实施：

1. 生成现有路由、方法、DAV capability、状态码、collection 和 UID/href 基线。
2. 审计 normalized Event/series 与 legacy `caldav_uid` 的对应；输出缺失、重复、跨表冲突。
3. 将现有 `tests/test_caldav*.py` 标记为 `RUN_LIVE_CALDAV_TESTS=1` 才运行的联调脚本。
4. 新增 Django TestCase 基线，使用临时用户/token/数据库，不访问 localhost 和生产库。
5. 冻结至少一份 Apple 客户端及一份标准 CalDAV 客户端实际请求 fixture，必须脱敏。

测试：基线 discovery/auth/collection/GET/PUT/DELETE；审计命令重复执行零写入；fixture 不含真实 token。

验收：所有现有能力都有测试归属；UID 冲突全部解释；没有自动测试在 import 时访问网络。

### P5-A：identity migration 与统一 mapper

实施：

1. 增加缺失的 immutable iCalendar identity/resource name 字段和约束。
2. 实现 backfill dry-run/apply/verify；任何冲突进入 issue，不自动覆盖。
3. 实现 `core/planner/ical.py` 与 DTO。
4. 原 parser/builder 改薄 wrapper 或删除，禁止继续维护第二套映射。

测试：属性 round-trip、UID/href、DATE/TZID/UTC/DURATION、RRULE/RDATE/EXDATE、override/cancel、转义/折行、非法 VCALENDAR。

验收：同一业务 resource 连续编码字节语义稳定；解析后再编码的业务投影等价；mapper 零数据库访问。

### P5-B：HTTP Feed 切换

实施：

1. `calendar_feed` 用 normalized application/query + mapper。
2. 保留 URL、type、鉴权、Content-Type、Content-Disposition、VTIMEZONE、刷新提示和私有缓存语义。
3. events/todos/reminders 使用有界查询或 definition 查询，不读取 legacy JSON。
4. shadow 期间生成结构化 diff：比较 UID、组件类型、时间、RRULE、VALARM，不比较无意义序列化顺序。

测试：四种 type、普通/全天/重复/override Event、有 due/无 due Todo、普通/重复 Reminder、中文/换行/长文本、空数据、无效 token、读取零增长。

验收：Feed 对照矩阵零未解释差异；Apple Calendar 可订阅并完成至少两次刷新；normalized 路径不使用 legacy 内容构建业务投影，也不产生 legacy 写入，唯一允许项是现有 rollout checksum 准入检查。

### P5-C：CalDAV discovery、读取与查询切换

实施：

1. root/principal/home/collection 读取 normalized collection query。
2. PROPFIND 列表每个 series 只返回一个 href。
3. GET/multiget 使用统一 mapper 输出 master + sparse overrides。
4. calendar-query 使用 recurrence expander 判断窗口相交。
5. 未实现的 capability 从 DAV/property 响应中删除。

测试：Depth 0/1、default/group/reminders、空集合、未知/删除 group、多 href 200/404、有限/无限系列跨窗口、移动 override 跨窗口、全天跨日、畸形 XML、跨用户。

验收：一个早于查询窗口开始的无限系列仍能命中；连续 REPORT 不新增任何 Planner 行；Apple/标准客户端均能完成发现和全量读取。

### P5-D：CalDAV VEVENT 写入切换

实施：

1. 实现原子 calendar-object application command。
2. PUT create/update、DELETE 全部删除 legacy/UserData/旧 View manager 分支。
3. 支持普通、有限/无限 RRULE、RDATE/EXDATE、modified/cancelled override 和现有 Apple future edit 序列。
4. group collection 写入映射到 Event.group；提醒/VTODO 保持拒绝。

测试：单次和系列 CRUD、single/all/future、group move、Web↔CalDAV 交叉编辑、失败注入、并发写、重复 UID/href、只读集合。

验收：CalDAV 写后 Web、Search、Agent 读取结果一致；无限系列仅 master+series+稀疏记录；失败无半系列；legacy Planner JSON checksum 不变。

### P5-E：ETag、CTag、collection change 与协议收口

实施：

1. resource ETag 改为 immutable identity + 单调 source version。
2. CTag 改为 `CalendarCollectionVersion.version`。
3. 补齐 default/group/reminders 的所有 change 触发和 group move tombstone。
4. 校正 OPTIONS、Allow、supported-report-set 和错误 mapper。

测试：同秒连续修改 ETag 仍变化；stale If-Match 412；创建前 `If-None-Match:*`；group move 两集合变化；rollback 后版本单调；未支持 report 不宣称。

验收：版本/ETag 不依赖秒级时间；每个业务 mutation 的 change 数量与集合影响完全匹配；协议 capability 审计零虚假声明。

### P5-F：停机切换、真实客户端与全量验收

实施：按第 9 节执行备份、迁移、identity backfill、cohort entrypoint 和服务切换。

测试：P1–P4 全量回归、P5 自动矩阵、MoMoJee strict/parity、Feed Apple 实机、Apple CalDAV 与 Thunderbird 或 DAVx5 两类客户端交叉编辑。

验收：第 11 节完成定义全部满足，形成 P5-F 报告后才允许进入 P6。

## 8. P5 完整测试矩阵

| 范围 | 必测场景 | 核心断言 |
|---|---|---|
| Mapper identity | Web/legacy CalDAV/新导入 UID、alias、href | UID/href 稳定且不重复创建 |
| 时间 | TZID、Z、offset、DATE、跨日、月末、DST fixture | 类型和时刻往返一致 |
| recurrence | DAILY/WEEKLY/MONTHLY/YEARLY、COUNT/UNTIL、BYDAY、RDATE/EXDATE | 与 expander occurrence 集一致 |
| override | modified、moved、cancelled、多个 override | RECURRENCE-ID 使用原槽位 |
| Feed event | 单次/有限/无限/override/all-day | VEVENT、UID、RRULE 正确 |
| Feed Todo | due date/datetime、无 due、各种 status | 仅有 due 输出，带 VALARM |
| Feed Reminder | 单次/重复/状态/稀疏 state | VEVENT+VALARM，普通实例不物化 |
| Feed filtering | all/events/todos/reminders/非法 type | 组件集合准确，非法为 400 |
| Discovery | well-known/root/principal/home | 路径、href、认证头、207 正确 |
| Collections | default/group/reminders/空/删除 group | 隔离、颜色、名称、只读能力正确 |
| PROPFIND | Depth 0/1/infinity、property subset | 无重复 href，非法 Depth 拒绝 |
| Multiget | 混合存在/不存在 href、series | 每 href 独立 propstat，数据完整 |
| Calendar-query | 普通相交、早启动无限系列、移动 override | 窗口命中与 expander 一致 |
| GET | 单次/series/提醒、条件缓存 | 内容、ETag、404/304 正确 |
| PUT create | 单次/all-day/series/RDATE/EXDATE | 201、一个 resource、无预生成行 |
| PUT update | 字段/时刻/规则/override/future split | 204、Web 投影一致、版本增加 |
| DELETE | 单次/master series/stale version | 204/412，collection tombstone 正确 |
| 并发 | 两个相同 ETag 更新、create race | 仅一个成功，无 lost update |
| 原子性 | parser/command/change 之间故障注入 | 所有表与版本零部分变化 |
| 权限 | 无认证、跨用户、错误 collection、read-only | 401/403/404 固定且不泄露数据 |
| 安全 | 超大 body、恶意 XML、非法折行、日志脱敏 | 400/413，无 token/body 泄漏 |
| 交叉入口 | Web/Agent/MCP 创建后 CalDAV；CalDAV 后 Web/Feed | 同一事实源、同一 occurrence 语义 |
| 无副作用 | 重复 Feed/GET/REPORT 100 次 | Event/series/override/state/change 行数不增长 |

建议新增：

```text
core/tests/test_planner_ical_mapper.py
core/tests/test_calendar_feed_v2.py
core/tests/test_calendar_identity_migration.py
caldav_service/tests/test_discovery.py
caldav_service/tests/test_collections.py
caldav_service/tests/test_reports.py
caldav_service/tests/test_event_resource_read.py
caldav_service/tests/test_event_resource_write.py
caldav_service/tests/test_recurrence_write.py
caldav_service/tests/test_preconditions_versions.py
caldav_service/tests/test_feed_caldav_crossover.py
```

自动测试必须使用 Django `TestCase`/`TransactionTestCase` 的临时库和固定时钟；live 脚本只能在隔离账号、临时 token、显式环境变量下运行。

## 9. 生产操作流程

项目允许停机，因此 P5-F 使用简单、强校验的全停机切换：

1. 停止 Daphne/Web、提醒 worker、Quick Action、MCP 和所有 CalDAV/Feed 流量。
2. 使用 SQLite online backup API 或停写后的安全复制生成 P5 前备份；记录文件大小与 SHA256。
3. 对活动库和备份分别执行 `PRAGMA integrity_check`、`PRAGMA foreign_key_check`。
4. 执行 P1–P4 全用户 strict/parity，保存 JSON 基线。
5. 执行 `migrate --plan`，人工核对后执行 migration。
6. 运行 iCalendar identity backfill dry-run，核对重复 UID、href、legacy alias；无未解释 issue 后才 apply。
7. 先开启 `calendar_feed`、`caldav_read`，运行自动化和只读 live smoke。
8. 对隔离测试用户开启 `caldav_write`，完成 PUT/DELETE/series 矩阵并清理测试数据。
9. 对 MoMoJee 开启三个 P5 entrypoint，完成真实 Feed/CalDAV 客户端交叉验收。
10. 重新执行 strict/parity、identity verify、collection version verify、legacy checksum。
11. 启动其他服务，观察应用日志后恢复对外访问。

计划新增的管理命令（名称可在实现时按项目命名规范微调，但能力不可省略）：

```powershell
.venv\Scripts\python.exe manage.py audit_planner_ical_identity --output logs/p5-ical-identity-before.json
.venv\Scripts\python.exe manage.py backfill_planner_ical_identity --dry-run --output logs/p5-ical-backfill-dry-run.json
.venv\Scripts\python.exe manage.py backfill_planner_ical_identity --apply --output logs/p5-ical-backfill-apply.json
.venv\Scripts\python.exe manage.py verify_planner_ical_identity --strict --output logs/p5-ical-identity-after.json
.venv\Scripts\python.exe manage.py verify_calendar_collection_versions --strict --output logs/p5-collection-version.json
.venv\Scripts\python.exe manage.py audit_caldav_capabilities --output logs/p5-caldav-capabilities.json
```

## 10. 失败回退

- migration/backfill 前失败：保持停机，修复后重跑；数据库不变。
- backfill 后、开放写流量前失败：恢复 P5 前数据库和旧代码。
- 仅 Feed/只读异常：关闭对应 P5 entrypoint，保持服务停机或返回明确维护错误；不得对 normalized 用户回落读取已过时 legacy 数据。
- 开放 CalDAV 写后失败：先停 CalDAV 写；保留 normalized 写入结果，修复代码后继续。除非业务数据已证明损坏，否则不恢复旧备份覆盖新写入。
- 如果验收阶段尚未对真实用户开放且数据只来自测试账号，可恢复备份并重新演练。
- 任何回退都不得重新启用 CalDAV 直接写 UserData 的旧路径。

## 11. P5 完成定义

只有以下条件同时满足，P5 才算完成：

1. Feed 与 CalDAV 共用 `core/planner/ical.py`；不存在第二套业务 UID/RRULE/override 映射。
2. normalized 用户的 Feed、CalDAV read/write 全链路不使用 legacy Planner JSON 构建业务数据且零 legacy 写入；P6 前仅允许 rollout checksum 准入检查这一项审计白名单。
3. CalDAV View 不调用旧 View、旧 Service、MockRequest 或自行写 ORM/RRule。
4. HTTP Feed 的 events/todos/reminders 和四种 type 保持可用。
5. default/group/reminders collection 与原功能一致；reminders 仍只读，Todo/VTODO 不意外进入 CalDAV。
6. 普通、有限/无限系列、RDATE/EXDATE、modified/cancelled override、Apple future edit 的自动矩阵通过。
7. calendar-query 与 V2 expander 结果一致；所有读取均无副作用、无限系列零存储增长。
8. ETag/CTag 使用单调版本；stale If-Match 稳定 412；group move 的两个 collection 均变化。
9. 未实现的 CalDAV 能力没有被 OPTIONS/DAV/PROPFIND 宣称。
10. Apple Feed、Apple CalDAV，以及 Thunderbird 或 DAVx5 至少两类真实客户端完成 discovery、读取和交叉编辑验收。
11. P1–P4 回归、MoMoJee strict/parity、identity verify、DB integrity/foreign key 和 legacy checksum 全部通过。
12. P5-0 至 P5-F 每阶段验收报告、生产日志和 Changelog 齐全。

## 12. 预计修改范围

```text
core/planner/ical.py                         # 新增统一 mapper
core/planner/application.py                  # Feed/CalDAV use cases
core/planner/context.py                      # 新 source/entrypoint
core/planner/commands.py                     # 原子 calendar-object command/identity
core/planner/repository.py                   # collection/resource/query projection
core/planner/rollout.py                      # 三个 P5 entrypoint
core/models.py + migration                   # identity/约束（按 P5-0 审计结果）
core/views_calendar_subscription.py          # 薄 HTTP Feed adapter
caldav_service/views/base.py
caldav_service/views/calendar_home.py
caldav_service/views/calendar.py
caldav_service/views/event.py
caldav_service/ical_builder.py                # 删除或降为兼容 wrapper
caldav_service/ical_parser.py                 # 删除或降为兼容 wrapper
caldav_service/etag.py
core/management/commands/*p5*.py
core/tests/test_planner_ical_mapper.py
core/tests/test_calendar_feed_v2.py
caldav_service/tests/*.py
```

## 13. 与旧文档的优先级

本文细化并覆盖《UserData拆表数据库升级方案》中旧 P5/P6 编号及“CalDAV 全协议扩展”的过时描述；P4 回滚已经完成，不在本阶段重做。本文仍受《核心日程正规化与 RRule 引擎升级方案》的单一 mapper、单一 command、稀疏 recurrence 和禁止 legacy fallback 原则约束。
