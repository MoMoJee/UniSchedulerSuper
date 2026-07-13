# P6 Legacy 停写、只读归档与最终验收发布方案

> 文档日期：2026-07-13  
> 状态：P5 已完成；P6-0 至 P6-D 与 P6-E 上线烟雾于 2026-07-13 通过，连续 7 天观察进行中；P6-F 未满足时间/后续版本前置，禁止提前执行。  
> 阶段目标：关闭核心 Planner legacy 写入和运行时 fallback，完成全用户切换、只读归档、最终全链路验收与安全清理。  
> 数据边界：`UserData` 仍可承载未迁移的配置类 key；P6 只封闭 Planner 核心 key 与旧共享日历 JSON 投影。

## 1. P6 完成后的系统状态

P6 完成时，系统只有一个 Planner 业务事实源：normalized ORM。

```text
Web / API / Search / Share / Import
Agent / Quick Action / MCP / Attachments
Feed / CalDAV / Reminder delivery
                    │
                    ▼
       PlannerApplicationService / command / query
                    │
                    ▼
             normalized Planner tables

legacy UserData Planner rows ──> 只读归档，不参与运行时业务
PlannerLegacyIdMap          ──> 保留一个明确发布周期
```

P6 不删除整个 `core_userdata` 表。以下配置类数据仍可按现有模块使用 UserData，例如 UI 设置、Agent 配置、token 用量等；它们不属于本次 Planner 停写范围。

## 2. 停写范围与用户处置

### 2.1 核心 Planner legacy key

至少包括：

```text
events
todos
reminders
events_groups
events_rrule_series
rrule_series_storage
```

实际实施以 P6-0 静态/数据库审计清单为准。任何别名、临时 recurrence key 或历史 Planner key 必须被归类，不能遗漏在白名单外继续写入。

`GroupCalendarData.events_data` 也属于旧复制投影：P6 后不得由任何业务写入口更新；共享读取只走 normalized membership/join。

### 2.2 用户分类

P6-0 将数据库用户分为三类：

| 类别 | 条件 | 处理 |
|---|---|---|
| verified clean | 所有实际存在的 source key 已 verified、无 unresolved issue | 批量登记全部 normalized entrypoint，进入 P6 |
| active repaired | MoMoJee；已完成 100% 修复、strict/parity 为零 | 作为生产主验收用户，必须保持正常使用 |
| retired quarantine | User1、test_user、User15、User21、User22 | 按用户已确认决定不修复；保留只读源数据，Planner 入口明确拒绝，不得 fallback 写 legacy |

retired quarantine 账号仍可登录和使用不依赖 Planner 的功能，但 event/todo/reminder/group、Feed、CalDAV、Planner Agent Tool 等入口返回稳定、可诊断的迁移隔离错误。不得用默认值覆盖坏数据，也不得为让请求“成功”而重新打开 legacy 写入。

除上述五个已确认无用测试账号外，任何其他 unresolved 用户都会阻塞 P6，不得自动归入 quarantine。

### 2.3 所有入口清单

P6 必须覆盖并审计：

- `api_v2`、`web_calendar`、`web_todo`、`web_reminder`、`web_search`、`web_share`、`course_import`。
- `agent_planner`、`quick_action_planner`、`mcp_planner`、`internal_attachment`。
- P5 新增的 `calendar_feed`、`caldav_read`、`caldav_write`。
- Reminder scheduler/delivery、全局搜索、冲突查询、分享组版本更新和 rollback restore 的内部入口。
- 所有旧 URL compatibility adapter。

“前端已经不用”不等于可以保留旧写实现；只要 URL、task、tool 或内部函数仍可到达，就必须委托 normalized application service 或明确拒绝。

## 3. P6 的硬性技术约束

### 3.1 normalized 不允许 fallback

- 全局 `PLANNER_STORAGE_MODE` 为 normalized。
- verified clean 用户的所有入口只能读写 normalized。
- repository/query/command 出错时返回明确错误，禁止 catch 后读取 legacy。
- legacy/shadow 只用于离线验证命令，不再是生产业务模式。
- cohort 判断不再依赖“失败就走 legacy”的默认分支。
- `PlannerRolloutPolicy.is_verified_clean()` 不再在每个业务请求中读取 `LegacyPlannerRepository` 复算 source checksum；P6 cutover 将已验证 source manifest/hash 封存到 migration/cohort 状态，运行时只读该准入状态，完整 checksum 复验只由离线管理命令执行。

### 3.2 只读归档

P6 cutover 时保留原 `UserData` Planner 行、source checksum、`PlannerMigrationState`、`PlannerMigrationIssue` 和 `PlannerLegacyIdMap`。

归档要求：

1. 记录每行 user/key/source row id/bytes/SHA256，不在报告中输出正文或 token。
2. 应用层 `LegacyPlannerRepository` 只能被 migration/verification/archive 工具导入；运行时模块禁止导入。
3. `PlannerUserDataCompat` 的 Planner 写方法删除或固定抛出 `LegacyPlannerWriteForbidden`。
4. 为 SQLite 增加 Planner key 的 INSERT/UPDATE/DELETE 防写 trigger，或提供同等级数据库级保护；配置类 key 不受影响。
5. 防写 trigger 的异常必须被测试并转为可诊断错误，不得吞掉后继续业务响应成功。
6. 归档最少保留一个明确发布周期；本文定义为 P6 cutover 后至少一个后续生产版本且连续 7 天全链路无未解释问题。

### 3.3 兼容 adapter

旧 Web/API URL 可以保留，但其内部必须：

```text
legacy-shaped request
    -> 参数/ID/occurrence ref 适配
    -> PlannerApplicationService
    -> legacy-shaped response（如仍需兼容）
```

不得：

- 读 `UserData` 后自己过滤；
- 调旧 `EventService`/`ReminderService`/`TodoService` 的 JSON 分支；
- 伪造 request 调 View；
- 调用旧 `EventsRRuleManager` 或 `IntegratedReminderManager` 预生成实例；
- 更新 `GroupCalendarData.events_data`；
- normalized 失败后双写/补写 legacy。

### 3.4 版本、回滚和历史

- P4 的短期 before-snapshot 回滚机制继续使用，不恢复 P4 前旧 reversion 历史。
- P6 删除 runtime legacy 后，当前有效 Agent rollback window 仍能恢复 normalized aggregate。
- rollback 会创建新的单调版本/collection change，不能恢复旧 version/token。
- Legacy archive 不是回滚引擎，任何 API 不得直接把归档 JSON 覆盖回业务表。

## 4. 分阶段实施、测试与验收

每阶段在 `docs/P6验收报告/` 写独立报告。P6 涉及生产切换，报告必须包含数据库 SHA256、命令参数、用户分类统计、自动测试通过数和所有人工 smoke 结果。

### P6-0：最终入口、用户与数据基线审计

实施：

1. 枚举所有 Planner UserData/GroupCalendarData 读写、旧 services、旧 RRule manager、runtime legacy repository import。
2. 枚举所有用户 migration state/issues/cohort/entrypoint。
3. 对全部 verified clean 用户执行 strict/parity；单独输出五个 retired quarantine。
4. 记录 Planner legacy 行数、bytes、checksum；记录 normalized 实体/series/override/state/relation/change 数量。
5. 固化 P1–P5 全量测试和真实 smoke 基线。

测试：审计命令重复执行零写入；数据库用户分类互斥且覆盖全部用户；报告不含敏感正文。

验收：每个 runtime 读写点有“改 normalized / 删除 / 只允许离线工具”归属；不存在未决活跃用户。

### P6-A：全 verified 用户 cohort 提升与 quarantine 固化

实施：

1. 新增批量 cohort promote 命令，默认 dry-run，只选择 verified clean 用户。
2. 为所有真实入口登记 normalized；禁止只登记 Web 而漏 Feed/CalDAV/Agent。
3. 将 User1、test_user、User15、User21、User22 固化为 retired quarantine，保存用户确认原因和时间。
4. 对隔离账号的所有 Planner 入口使用统一错误码，不暴露 issue 详情。

测试：选择器、dry-run/apply、重复 apply 幂等；缺 state/unresolved issue 用户绝不提升；五个隔离账号零写入。

验收：所有非 quarantine 且有 Planner 数据的活跃用户均为 normalized；cohort 报告不存在部分入口。

### P6-B：运行时 legacy 路径关闭

实施：

1. 将仍可达的旧 URL adapter 改为 application service，或删除无调用入口。
2. 删除 core/services、CalDAV、Feed、Agent/附件中的 runtime Planner legacy import。
3. 将 rollout 准入由逐请求 legacy checksum 扫描改为 cutover 时封存的 verified manifest 状态。
4. 共享读取改 join，删除 `sync_group_calendar_data` 的 `events_data` 写路径。
5. Reminder worker 和课程导入确认只用 normalized command/query。
6. 将 direct access 审计升级为 CI fail gate。

测试：所有旧 URL 的 CRUD/scope/错误契约；静态 import/AST 审计；故障时不 fallback；P1–P5 全量回归。

验收：runtime whitelist 以外的 Planner legacy read/write 均为零；所有兼容 URL 仍有明确测试或返回 410/404。

### P6-C：数据库防写、归档和验证工具

实施：

1. 增加 `LegacyPlannerWriteForbidden` 与应用层 guard。
2. 增加 SQLite Planner key 防写 trigger，覆盖 INSERT/UPDATE/DELETE。
3. 实现 archive manifest、checksum verify 和只读导出工具。
4. 保留 `PlannerLegacyIdMap`；禁止删除 migration issue/state。
5. 为未来清理实现 dry-run，当前阶段不删除归档正文。

测试：ORM、raw SQL、legacy compat、旧 service 分别尝试写核心 key均失败；配置类 UserData 仍可写；archive verify 可重复。

验收：数据库级防写有效；业务测试没有依赖关闭 trigger；归档 manifest 与活动库逐行 checksum 一致。

### P6-D：全停机生产切换

实施：严格按第 7 节操作，先在数据库副本完整演练，再对生产执行。

测试：备份可独立打开；migration/trigger/cohort apply；strict/parity；全套自动化；MoMoJee 全入口 smoke；quarantine 拒绝。

验收：启动服务前所有阻断门槛通过；任何失败保持停机并按阶段回退。

### P6-E：全应用验收与观察期

实施：恢复服务后执行第 5 节矩阵；连续观察至少 7 天或跨过一个后续生产版本。

监控：

- legacy write blocked 次数（预期 0；测试请求单列）。
- normalized application 错误率和 P95 query time。
- SQLite `database is locked`/busy timeout。
- Event/Reminder series、override/state 数量与增长率。
- Feed 生成错误、CalDAV 4xx/5xx、412 比例与异常客户端路径。
- rollback conflict/410、Reminder delivery 重试。

验收：无未解释 legacy write、无数据 parity 差异、无持续 5xx/锁错误；用户手工验收通过。

### P6-F：保留期结束后的 adapter/旧投影清理

前置：P6-E 满足至少一个后续版本和连续 7 天无未解释问题，且另有离线备份。

实施：

1. 删除 legacy runtime adapter 和旧 Planner services/RRule backend 的不可达代码。
2. 删除 `GroupCalendarData.events_data` 业务字段或将其改为明确废弃字段，按 migration 清空。
3. `PlannerLegacyIdMap` 和只读 UserData 归档是否删除，需另行人工批准；默认继续保留离线备份，不在 P6 自动删除。
4. 更新后端数据模型、服务层、API、README 和运维文档中仍把 UserData 当 Planner 主存储的过时描述。
5. 重新运行全部验收和数据库压缩评估；只有确有空间收益且有足够磁盘时才使用 `VACUUM INTO`。

测试：死代码/导入审计、migration、恢复演练、全量回归、备份 checksum。

验收：仓库与文档不再把 legacy Planner 当运行时能力；离线恢复材料仍完整。

## 5. P6 最终应用测试矩阵

### 5.1 Event

| 场景 | 必测动作 |
|---|---|
| 单次 | create/read/patch/delete、跨时区/全天、group move、share |
| 系列 | finite/infinite 创建；读取零增长；修改规则/时刻 |
| scope | single/all/this_and_future 的 edit/delete/drag |
| 稀疏状态 | RDATE、EXDATE、modified/cancelled override、split lineage |
| 并发 | stale expected_version、两个客户端同时更新、rollback 后重试 |
| 入口交叉 | Web、旧 URL、Agent、Quick、MCP、Feed、CalDAV 相互可见 |

### 5.2 Todo

- create/list/search/patch/complete/delete。
- status、四象限、due date/datetime、group、tag、dependency 和环拒绝。
- Todo→Event 原子转换、失败零部分写入、Agent rollback。
- Feed 仅输出有 due 的 Todo VEVENT+VALARM；CalDAV 不出现 VTODO。

### 5.3 Reminder

- 单次↔重复转换、RRULE 替换、single/all/this_and_future 编辑/删除。
- snooze/complete/dismiss、advance trigger、occurrence state、delivery lease/幂等。
- 日历、左侧筛选、详情、编辑框、Agent/search/attachment 同步刷新。
- Feed 和只读 CalDAV reminders collection；PUT/DELETE 固定 403。

### 5.4 Share、Group、Search、Import

- event group CRUD、颜色/默认、删除组时事件归属。
- share group owner/member、成员颜色、只读他人事件、跨周/月窗口。
- 不读取/更新 `GroupCalendarData.events_data`；分享结果来自 join。
- search 分页、默认窗口、自定义窗口、无限 occurrence、共享只读 ref。
- 课程导入重复规则、失败原子性、重复导入幂等策略。

### 5.5 Agent、Quick Action、MCP、附件、回滚

- 三入口 event/todo/reminder CRUD、scope、search、conflict、group/share。
- cache `#N`、更新/删除/回滚失效、跨 user/session 拒绝。
- 内部附件 master/occurrence、首次发送、回滚重发、源删除后快照可读。
- 当前回滚窗口内 create/override/split/convert/snooze 可恢复；旧窗口 410。
- Quick/MCP 不借用聊天回滚资格；stdio/HTTP 身份一致。

### 5.6 Feed 与 CalDAV

完整执行 P5 矩阵，并额外断言防写 trigger 开启时正常 CalDAV write 仍成功（因为只写 normalized），legacy checksum 始终不变。

### 5.7 数据、并发和非功能

| 范围 | 断言 |
|---|---|
| DB integrity | `integrity_check=ok`、foreign key 无行 |
| migration | `makemigrations --check --dry-run` 无漂移 |
| strict/parity | 所有 verified 用户零 diff；五个 quarantine 明确排除 |
| legacy | 核心 key checksum/bytes 不变；blocked runtime write=0 |
| 存储 | 无限系列重复读取不增长；snapshot 关闭窗口后清理 |
| 并发 | 无 lost update；锁错误可重试且无部分提交 |
| 权限 | 所有用户查询在 DB 层限定 user；跨用户 ref 不泄露 |
| 日志 | 不含 token/password/附件正文/完整 ICS；错误带 request correlation 信息 |
| 性能 | 典型月视图、搜索、Feed、calendar-query 与 P6-0 基线比较，无未解释显著退化 |

## 6. 自动化、手工与验收证据要求

### 6.1 自动化命令

实际实施可按测试模块拆分，但最终至少执行：

```powershell
$env:DISABLE_EXTERNAL_MCP='1'
.venv\Scripts\python.exe manage.py check
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.venv\Scripts\python.exe manage.py test core.tests agent_service.tests caldav_service.tests
.venv\Scripts\python.exe manage.py verify_planner_migration --strict --from 2020-01-01 --to 2035-01-01
.venv\Scripts\python.exe manage.py verify_recurrence_parity --sample all --strict --from 2020-01-01 --to 2035-01-01
.venv\Scripts\python.exe manage.py report_planner_direct_userdata_access --output logs/p6-direct-userdata.json
```

计划新增：

```powershell
.venv\Scripts\python.exe manage.py audit_planner_p6_readiness --output logs/p6-readiness.json
.venv\Scripts\python.exe manage.py promote_verified_planner_cohorts --dry-run --all-entrypoints --output logs/p6-cohort-dry-run.json
.venv\Scripts\python.exe manage.py promote_verified_planner_cohorts --apply --all-entrypoints --output logs/p6-cohort-apply.json
.venv\Scripts\python.exe manage.py audit_legacy_planner_archive --output logs/p6-archive-manifest.json
.venv\Scripts\python.exe manage.py verify_no_legacy_planner_write --strict --output logs/p6-no-legacy-write.json
.venv\Scripts\python.exe manage.py verify_planner_release --strict --output logs/p6-release-verify.json
```

### 6.2 手工验收

必须用 MoMoJee 执行：

1. Web Event/Todo/Reminder 的普通和重复 CRUD/scope。
2. 分享组、筛选、搜索、课程导入。
3. Agent 自然语言 CRUD、附件首发/回滚重发、当前会话回滚。
4. Quick Action 和 MCP 各一次真实读写。
5. Apple Feed 刷新；Apple CalDAV 与另一类客户端交叉编辑。
6. 浏览器刷新、重连、切会话后数据和回滚窗口正确。

涉及大量删除或复杂 series split 的组合仍在隔离用户/数据库副本执行，不使用 MoMoJee 生产业务记录做破坏性穷举。

### 6.3 证据

每份 P6 报告至少包含：

- commit/worktree 状态和实际改动文件。
- 测试命令、用例数、通过/失败/跳过数。
- DB 文件大小、SHA256、integrity/foreign key。
- 用户分类和 cohort entrypoint 统计（不含敏感正文）。
- legacy archive checksum before/after。
- strict/parity/identity/collection version 报告路径。
- 手工客户端、动作、预期与实际结果。
- 任何白名单、跳过项及批准依据。

“页面看起来正常”不能替代数据库、协议和并发断言。

## 7. P6-D 全停机生产操作流程

### 7.1 发布前

1. 在生产数据库副本完整演练 P6-0 至 P6-D；保存用时和所需磁盘。
2. 确认 P5-F 已通过，P5 文档/报告/Changelog 完整。
3. 运行 P6 readiness；确认只有五个批准的 retired quarantine。
4. 准备旧代码、当前代码、数据库备份和启动命令；确认恢复责任人和路径。

### 7.2 停机与备份

1. 停止 Daphne/Web、Reminder worker、Quick Action、MCP、定时任务和 CalDAV/Feed。
2. 确认没有持有数据库的应用进程和后台任务。
3. 创建一致数据库备份，计算源/备份 SHA256；独立打开备份。
4. 执行 integrity/foreign key、实体计数、legacy manifest、strict/parity、P5 identity/version 基线。

### 7.3 迁移与切换

1. `migrate --plan` 后执行 migration（含防写 guard/trigger）。
2. cohort promote 先 dry-run；人工核对用户和全 entrypoint 后 apply。
3. 固化五个 quarantine；验证其 Planner 请求被拒绝且 legacy checksum 不变。
4. 执行 direct access、no-legacy-write、archive、strict/parity、identity/version verify。
5. 在仍停机时运行全套自动化或部署专用验收套件。

### 7.4 启动顺序

1. 先启动 Web/ASGI，不启动外部 worker。
2. 使用隔离用户和 MoMoJee 执行只读 smoke。
3. 执行一个 Event、Todo、Reminder 的可清理写入与读取；核对 legacy checksum 不变。
4. 启动 Reminder worker，验证一次投递/lease。
5. 启动 Quick Action/MCP，验证身份和 Planner operation。
6. 恢复 CalDAV/Feed 客户端，检查 4xx/5xx/412。
7. 全部通过后恢复对外访问。

### 7.5 发布后检查点

- T+15 分钟：错误/锁/legacy blocked/Feed/CalDAV。
- T+2 小时：重复检查计数、series/override/state 增长和关键 UI。
- T+24 小时：Reminder delivery、订阅刷新、客户端同步。
- 连续 7 天：每日检查日志和 archive checksum；完成 P6-E 报告。

项目不要求高可用，但任何检查点发现数据一致性问题时应立即重新停机。

## 8. 回退策略

### 8.1 尚未开放真实流量

停机、恢复 P6 前数据库备份和旧代码，重新执行 integrity/foreign key 后再启动。此时不存在需要保留的 P6 后用户写入。

### 8.2 已开放真实流量

优先停服务并修复/回滚代码，保留 normalized 数据库；不得直接恢复旧备份覆盖用户在 P6 后产生的新写入。

只有证明 normalized 数据已经不可恢复，且用户明确接受丢弃 P6 后写入时，才能恢复备份。执行前必须另存当前故障库和日志。

### 8.3 局部功能异常

- Agent/Quick/MCP 异常：禁用对应工具类别，不回落 legacy。
- Feed/CalDAV 异常：临时返回维护错误或只关闭协议入口，不回落 legacy。
- Reminder worker 异常：停止 worker，Web Planner 保持可用。
- quarantine 误分类：保持停机并人工修正 cohort；不能临时打开 legacy write。

## 9. P6 完成定义

P6 功能 cutover 完成必须满足：

1. 所有 verified clean 用户的全部 Planner entrypoint 均为 normalized；MoMoJee 全功能可用。
2. User1、test_user、User15、User21、User22 按批准策略隔离，未修复、未默认覆盖、未产生 legacy 新写入。
3. 所有 runtime Planner 入口零 legacy read/write/fallback；旧 URL 只作 normalized adapter 或明确拒绝。
4. 核心 Planner UserData key 和 `GroupCalendarData.events_data` 业务写入为零，并有数据库级防写。
5. legacy archive manifest/checksum 完整，`PlannerLegacyIdMap` 至少保留一个发布周期。
6. P1–P5 全量自动化、P6 矩阵、strict/parity、identity/version、DB integrity/foreign key 全通过。
7. Web、Agent、Quick、MCP、附件、回滚、Feed、CalDAV、Reminder delivery 的真实 smoke 全通过。
8. 观察期无未解释 legacy blocked、持续 5xx、锁错误、数据增长或 parity 差异。
9. 后端规范和 README 已更新，不再声明 UserData 是 Event/Todo/Reminder 的事实源。
10. P6-0 至 P6-E 验收报告和 Changelog 齐全。

P6-F 清理完成还需满足：

1. 已跨至少一个后续生产版本且连续 7 天稳定。
2. 旧 runtime adapter/RRule backend/共享 JSON 投影代码已经删除或不可达。
3. 离线备份和恢复演练通过；任何 archive/LegacyIdMap 删除均另有人工批准。
4. 清理后重新通过上述全部门槛。

## 10. 文档更新清单

P6-F 必须同步修订：

```text
docs/后端开发规范/数据模型规范.md
docs/后端开发规范/服务层规范.md
docs/后端开发规范/API接口规范.md
docs/后端开发规范/认证与权限规范.md
docs/核心日程正规化与RRule引擎升级方案.md（状态/完成记录）
docs/Planner正规化升级进展与下一阶段计划.md
docs/UserData拆表数据库升级方案.md（标注旧编号已被新方案覆盖）
README.md 及部署/数据库说明
```

其中服务层规范中旧 `MockRequest + UserData + reversion + 预生成 instance` 示例必须删除，改为 `PlannerExecutionContext + PlannerApplicationService + normalized command/query + P4 snapshot`。

## 11. 与旧计划的关系

《UserData拆表数据库升级方案》的旧 P6“Agent rollback”已由当前 P4 完成；本项目现行总计划中的 P6 是“停止 legacy 写入”。本文以《核心日程正规化与 RRule 引擎升级方案》P6 为准，并结合当前 P1–P4 实际状态和已确认的五个 retired quarantine 用户给出最终操作规范。
