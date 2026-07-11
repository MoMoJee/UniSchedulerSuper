# Planner 正规化升级进展与下一阶段计划

> 更新日期：2026-07-11  
> 对应设计：[核心日程正规化与 RRule 引擎升级方案](./核心日程正规化与RRule引擎升级方案.md)  
> 当前阶段：P0、P1-A、P1-B、P2 完成；已进入 P3（v2 definitions/occurrences/command/search API 与入口适配）。
> 当前存储模式：legacy JSON 仍为唯一业务事实源；normalized 表已建立经严格校验的 shadow 投影，但尚未承接任何业务流量。

---

## 1. 当前状态与已完成事项

### 1.1 数据安全与审计

已在执行任何 schema 变更前使用 SQLite online backup API 生成一致性备份：

```text
backup/20260711/planner_pre_upgrade_20260711_035600.sqlite3
```

随后执行 `audit_planner_legacy`。审计初始结果为 37 位用户、158 条 Planner legacy 源行、1 个重复 key、0 个非法 JSON。

唯一重复项是 user 44 的两个 `reminders` 源行，内容均为字节级相同的空数组 `[]`。已按以下安全流程处理：

1. 使用 `resolve_planner_legacy_duplicates --user-id 44 --key reminders` dry-run 确认保留行 519、待删除行 520。
2. 显式执行 `--apply`，仅删除该完全重复副本。
3. 再次审计，结果为 37 位用户、157 条源行、0 个重复 key、0 个非法 JSON。

任何内容不同、类型异常或 JSON 非法的重复项，resolver 均会拒绝自动处理并要求写入迁移 issue；不得以默认值覆盖。

### 1.2 已应用的 schema 迁移

`core.0009_planner_normalized_foundation` 已应用。它只创建新表、索引和约束，**没有导入或删除正常的 events/todos/reminders 业务数据**。

当前实际仍保留在 `core_userdata` 的 legacy key：

```text
events / todos / reminders / events_groups /
events_rrule_series / rrule_series_storage
```

### 1.3 已落地的领域基础设施

| 模块 | 已实现能力 | 当前用途 |
|---|---|---|
| `core/models.py` | EventGroup、CalendarEvent、Todo、Reminder、关系表、event/reminder recurrence、migration state/issue、ChangeSet、collection change 模型 | 建立旁路数据结构，尚未承载业务读写 |
| `core/planner/recurrence/codec.py` | `PlannerTimeCodec`、RFC 5545 RRULE 规范化与校验 | 统一 DATE、TZID、UTC、UNTIL、受支持 RRULE 字段语义 |
| `core/planner/recurrence/expander.py` | 纯 `RecurrenceExpander` | 对时间窗展开 RRULE/RDATE/EXDATE/稀疏 override；无数据库副作用 |
| `core/planner/legacy.py` | `LegacyPlannerRepository` | 原样读取 legacy JSON，不经 `DATA_SCHEMA` 重建，保护 `caldav_uid` 和未知字段 |
| `core/planner/repository.py` | `PlannerRepository` | 从 normalized ORM 构建 definitions/occurrences 查询投影，并使用同一纯展开器 |
| `core/management/commands/` | audit 与相同副本去重命令 | P0 审计、证据保留和安全处置 |

隔离测试期间，Agent 图不再在导入期访问真实 MCP；MCP 配置日志也不再输出 URL（避免泄漏 query 中的密钥）。

本轮还新增了 `report_planner_direct_userdata_access` 调用面报告。`TodoService`、`ReminderService` 的 Planner 列表直接访问数均为 0；`EventService` 的 events 主列表已收敛，仅保留一处既有 `user_preference` 配置读取。三个 Service 的 Planner 列表读写均通过 `LegacyPlannerRepository`，写入在 `transaction.atomic()` 与 `reversion` 上下文内进行，并保留未知 JSON 字段。

Todo 的五个 Web 入口（列表、创建、更新、删除、转换为日程）也已收敛到上述 Service/repository 路径。其中“转换为日程”在同一 `transaction.atomic()` 中锁定并写入 `todos` 与 `events` 两个 legacy 列表；旧 URL、请求字段和响应 JSON 保持不变。

P1-B 的其余旧入口已通过窄兼容层 `PlannerUserDataCompat` 收敛：events/reminders、共享日程组、日历订阅、Agent parser/tool、CalDAV event 读写均仅在 Planner key 上走该层。兼容层保留原 `get_or_initialize`、`objects.get/get_or_create`、`get_value/set_value` 调用形状，但不会触发旧 `DATA_SCHEMA` 的重建/字段投影；非 Planner 配置 key 仍委托原 `UserData` 行为。

Calendar subscription 与 CalDAV 基础读取改为直接调用 `LegacyPlannerRepository` 的只读投影；Agent 回滚快照也通过 repository 取得 `events/todos/reminders`、规则段和 `outport_calendar_data` 源行。由此避免工具、Feed、CalDAV 在各自模块重复解析或重写 Planner JSON。

最终调用面报告保存为 `logs/planner-direct-userdata-access-20260711-p1b.json`：144 个结构性命中中，14 个为已标识的 Agent 配置/用量或 `user_preference` 访问（不属于 Planner 实体），`planner_bypass_count = 0`。剩余 Planner 存取仅位于 legacy adapter、审计/去重命令、模型定义或已登记兼容入口。

P2 已新增三条管理命令：`migrate_planner_legacy`（默认 dry-run，只有 `--apply` 才写旁路表）、`verify_planner_migration`（实体/mapping/时间字段/occurrence 只读校验）和 `verify_recurrence_parity`（只比较 recurrence occurrence 集）。`core.0010_planner_cohort_assignment` 已应用到当前数据库；它只创建 cohort 记录表，不导入或修改任何 Planner 业务数据。`PlannerRolloutPolicy` 也已建立按用户、入口和启用时间记录 cohort 的安全门禁；全局开关或 assignment 任一条件不满足时，策略强制回退到 legacy。当前业务入口尚未接入该策略。

2026-07-11 已完成副本与生产 shadow 导入：先由 SQLite online backup API 创建独立副本并运行 `--apply --skip-quarantined`，再执行两条 `--strict` 校验；副本中 31 位有 Planner 源数据的用户均为 0 实体差异、0 recurrence 差异。随后将同一 shadow 投影写入生产库，生产 `verify_planner_migration --only-imported --strict --mark-verified` 与 `verify_recurrence_parity --only-imported --strict` 同样均为 0 差异。生产当前有 31 位 verified 用户、6 位 quarantine 用户和 2 位没有任何 Planner source 行的用户；legacy JSON 未被改写，也没有切换任何业务读取流量。

兼容导入会把旧式 `RRULE;EXDATE=...` 拆为 RFC 的 RRULE + EXDATE 关系行；同时出现 `COUNT` 与 `UNTIL` 时只在已物化 occurrence 集能唯一证明一个候选规则等价时才规范化。完整但缺少 legacy ID 的项目使用 `source_row_id + list index` 生成确定性兼容 ID 并保留 metadata；缺 `end`、时间/标题类型损坏、无法唯一解释的 COUNT/UNTIL 和不存在的 share group 均保留为 issue。`--record-quarantined` 已在生产记录 6 位隔离用户的 state/issue，但没有导入这些用户的任何业务投影。

---

## 2. 不可突破的阶段边界

在 P2 的 migration/parity 验收通过前，必须持续遵守：

1. legacy JSON 是唯一业务事实源；新表不能被现有 Web、Agent、MCP、CalDAV 或 Feed 写入。
2. `RecurrenceExpander` 只能作为纯函数调用；GET、REPORT、搜索不能为了补实例而写数据库。
3. 任何真实 occurrence 的身份必须由 `{entity_id, series_id, recurrence_id}` 表示，不能继续设计依赖预生成行 UUID 的新接口。
4. `RRULE`、`RDATE`、`EXDATE`、`RECURRENCE-ID` 分表表达，禁止把 EXDATE 拼回 RRULE 字符串。
5. 无法解释的 legacy 数据必须进入 `PlannerMigrationIssue`；禁止自动“修复”为默认值后继续切换。

---

## 3. 下一步详细工作计划

### P1-A：领域契约与安全门禁（已完成）

已完成 normalized repository、版本/软删除基础、纯展开器 ORM 测试和调用面门禁；没有改变现有功能行为。

1. 完成 `core/planner/repository.py`。
   - 提供 normalized model 的只读 query DTO，以及批量预取 event series、RDATE、EXDATE、override 的接口。
   - 将 ORM 行转换为 `RecurrenceDefinition` / `OccurrenceOverride`，使后续查询只调用同一展开器。
   - 实现业务版本校验 helper；不在此阶段暴露 HTTP 命令接口。

2. 已建立 recurrence 基础契约测试。
   - 已覆盖 COUNT、UNTIL、RDATE、EXDATE、modified/cancelled override、跨窗口、all-day 和 America/New_York DST。
   - MONTHLY/YEARLY、WKST、负 BYMONTHDAY、序号 BYDAY 与 10,000 窗口压力测试作为 P1-B/P2 的持续测试项。

3. 已补齐基础模型管理能力。
   - 已提供 event 版本校验、软删除和版本递增 helper。
   - 跨 user 关系校验、todo dependency 环检测和 collection version 递增将随对应 command service 一起实现。

4. 实现调用面门禁。
   - 新增 `report_planner_direct_userdata_access` 管理命令，按模块列出 `UserData.objects`、`get_or_initialize()`、`set_value()` 直接访问。
   - 将 legacy repository、migration command、明确白名单和非 Planner 配置 key 区分报告。

验收：codec/expander/model/repository 测试通过；新 recurrence 代码无写库副作用；调用面报告可复跑。

### P1-B：保持行为不变地收敛 legacy 调用入口（已完成）

目标：尚不读写 normalized 表，只把旧 JSON 访问集中到 `LegacyPlannerRepository`，消除 view/service/CalDAV 各自解析 JSON 的分叉。

改造顺序：

1. `core/services/event_service.py`、`todo_service.py`、`reminder_service.py`。
2. `core/views_events.py`、`views_reminder.py`、todo 相关 `views.py`。
3. `views_share_groups.py`、`views_import_events.py`、`views_calendar_subscription.py`。
4. `agent_service/tools/`、`agent_service/parsers/internal_parser.py`。
5. `caldav_service/views/`。

每一批改造均需满足：原 API JSON shape 不变、未知字段不丢失、隔离回归测试通过、没有引入 normalized 写入。

验收结果：核心 Planner 调用的直接 `UserData` 访问仅保留在 legacy adapter、审计/迁移 command 与兼容 facade；调用面报告 `planner_bypass_count = 0`。全量 `core.tests` 34 项、`manage.py check`、`makemigrations --check --dry-run` 均通过。

### P2：历史迁移、差异校验与 cohort 开关（已完成）

目标：在新旧双轨校验期内，将数据复制到 normalized 表并证明语义一致；仍不默认切换用户流量。

1. 已实现管理命令：

```powershell
.venv\Scripts\python.exe manage.py migrate_planner_legacy --dry-run --user-id <id>
.venv\Scripts\python.exe manage.py migrate_planner_legacy --apply --batch-size 50
.venv\Scripts\python.exe manage.py verify_planner_migration --strict --from 2020-01-01 --to 2035-01-01
.venv\Scripts\python.exe manage.py verify_recurrence_parity --sample all --from 2020-01-01 --to 2035-01-01
```

`migrate_planner_legacy` 对普通 event/todo/reminder、日程组、tags、reminder links、todo dependencies、分享关系、提前提醒和单规则段 recurrence 建立旁路投影及 `PlannerLegacyIdMap`。重复规则的正常预生成实例不会写成普通新 event/reminder 行；只保留 master、series、显式 EXDATE 和已发生状态。多规则段、非法 RRule、无法确定 occurrence slot、缺失历史 ID、目标冲突或精度损失均生成 issue 并使用户隔离。

2. 迁移顺序：EventGroup → 非重复 Todo/Reminder/Event → tags/links/share links → recurrence series → sparse exception/state → legacy ID map。
3. 对每个 series 用 legacy 规则和 normalized expander 在固定窗口比较 occurrence 的 recurrence_id、start/end、标题、状态、group、分享关系和 override 类型。
4. 无法一一解释的预生成实例、规则段边界或未来 override 写入 `PlannerMigrationIssue`，该用户不得进入 normalized cohort。
5. 加入仅迁移期开关：`PLANNER_STORAGE_MODE`、`PLANNER_DIFF_ASSERT`、`PLANNER_LEGACY_FALLBACK`、`PLANNER_CALDAV_NORMALIZED`；开关必须按 user cohort/入口记录。

验收结果：命令默认只读/dry-run；apply 按用户单事务、checksum 幂等，测试覆盖普通实体、关系、unknown field 保留、单规则段 recurrence、ID map、旧式 EXDATE、可证明等价的 COUNT/UNTIL、缺 ID 兼容、隔离审计与 verifier/parity。P2-C cohort 门禁已实现但尚未被业务入口消费。通过验证的用户可以在 P3 的入口适配代码完成后才显式登记 shadow cohort；6 位 quarantine 用户继续保持 legacy-only，直到单独处置 issue。

P3-A 已新增仅限 verified 用户调用的 v2 读取接口：`GET /api/v2/events/definitions/?from=&to=` 与 `GET /api/v2/events/occurrences/?from=&to=`。前者输出 event definition、series、RRULE、RDATE/EXDATE 摘要和 source version；后者按半开窗口纯展开，并返回稳定的 `occurrence_ref = {entity_id, series_id, recurrence_id, occurrence_start, source_version}`。接口不回退读取 legacy、不物化正常 occurrence，也未接入现有 FullCalendar；因此旧 Web 路径仍保持无行为变化。P3-B 将补齐 versioned command/search 契约，再决定 cohort 入口适配。

---

## 4. 后续切换顺序

P2 通过后才依次进行：

1. P3：v2 definitions/occurrences/command/search API、FullCalendar occurrence ref、共享日程 join 查询。
2. P4：Agent、Quick Action、MCP、附件解析、PlannerChangeSet 精确回滚。
3. P5：统一 iCalendar mapper、Feed、CalDAV PUT/DELETE/REPORT、ETag 与 collection change。
4. P6：关闭 legacy 写入，保留只读归档与 legacy ID mapping 一个明确发布周期后再清理。

每一阶段都必须具备 feature flag 回退路径；不得出现部分入口读 legacy、另一部分入口写 normalized series 的混合状态。

---

## 5. 已验证命令

```powershell
.venv\Scripts\python.exe manage.py check
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.venv\Scripts\python.exe manage.py test core.tests.test_planner_models core.tests.test_planner_legacy_repository
.venv\Scripts\python.exe manage.py test core.tests
.venv\Scripts\python.exe -m unittest core.tests.test_planner_time_codec core.tests.test_recurrence_expander
.venv\Scripts\python.exe manage.py report_planner_direct_userdata_access --output logs/planner-direct-userdata-access-20260711-p1b.json
.venv\Scripts\python.exe manage.py migrate_planner_legacy --dry-run --output logs/planner-migration-dry-run-20260711-p2a.json
.venv\Scripts\python.exe manage.py verify_planner_migration --strict --from 2020-01-01 --to 2035-01-01
.venv\Scripts\python.exe manage.py verify_recurrence_parity --sample all --strict --from 2020-01-01 --to 2035-01-01
.venv\Scripts\python.exe manage.py verify_planner_migration --strict --mark-verified --user-id <id>
.venv\Scripts\python.exe manage.py set_planner_cohort --user-id <id> --mode shadow --entrypoint web --note "staging parity passed"
```

运行命令时可设置 `DISABLE_EXTERNAL_MCP=1`，确保维护、迁移和验证进程不在导入期连接外部 MCP 服务。
