# Planner 正规化升级进展与下一阶段计划

> 更新日期：2026-07-11  
> 对应设计：[核心日程正规化与 RRule 引擎升级方案](./核心日程正规化与RRule引擎升级方案.md)  
> 当前阶段：P0 完成；P1-A（基础设施与契约）进行中。  
> 当前存储模式：legacy JSON 为唯一业务事实源；normalized 表仅作为空的旁路结构，未切换流量。

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
| `core/management/commands/` | audit 与相同副本去重命令 | P0 审计、证据保留和安全处置 |

隔离测试期间，Agent 图不再在导入期访问真实 MCP；MCP 配置日志也不再输出 URL（避免泄漏 query 中的密钥）。

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

### P1-A：补齐领域契约与安全门禁

目标：让新模型、时间语义、legacy 原始读取和迁移入口具备稳定契约，但不改变现有功能行为。

1. 完成 `core/planner/repository.py`。
   - 提供 normalized model 的只读 query DTO，以及批量预取 event series、RDATE、EXDATE、override 的接口。
   - 将 ORM 行转换为 `RecurrenceDefinition` / `OccurrenceOverride`，使后续查询只调用同一展开器。
   - 实现业务版本校验 helper；不在此阶段暴露 HTTP 命令接口。

2. 扩展 recurrence 契约测试。
   - 覆盖 WEEKLY 多 BYDAY、MONTHLY 月末/负 BYMONTHDAY、YEARLY、COUNT、UNTIL、WKST、RDATE、EXDATE。
   - 增加 `single` override、cancelled override、移动 occurrence、跨窗口事件、all-day 与 America/New_York DST 测试。
   - 新增“连续读取 10,000 个窗口不增加任何 Planner 行”的 ORM 级测试。

3. 补齐模型约束和管理能力。
   - 校验 event/todo/reminder 与 user、group、share group 的同用户关系。
   - 为 todo dependency 增加服务层环检测接口。
   - 明确软删除、version 增加和 CalendarCollectionVersion 递增的公共 helper。

4. 实现调用面门禁。
   - 新增 `report_planner_direct_userdata_access` 管理命令，按模块列出 `UserData.objects`、`get_or_initialize()`、`set_value()` 直接访问。
   - 将 legacy repository、migration command、明确白名单和非 Planner 配置 key 区分报告。

验收：codec/expander/model/repository 测试通过；新 recurrence 代码无写库副作用；调用面报告可复跑。

### P1-B：保持行为不变地收敛 legacy 调用入口

目标：尚不读写 normalized 表，只把旧 JSON 访问集中到 `LegacyPlannerRepository`，消除 view/service/CalDAV 各自解析 JSON 的分叉。

改造顺序：

1. `core/services/event_service.py`、`todo_service.py`、`reminder_service.py`。
2. `core/views_events.py`、`views_reminder.py`、todo 相关 `views.py`。
3. `views_share_groups.py`、`views_import_events.py`、`views_calendar_subscription.py`。
4. `agent_service/tools/`、`agent_service/parsers/internal_parser.py`。
5. `caldav_service/views/`。

每一批改造均需满足：原 API JSON shape 不变、未知字段不丢失、隔离回归测试通过、没有引入 normalized 写入。

验收：核心 Planner 调用的直接 `UserData` 访问仅保留在 legacy adapter、审计/迁移 command 与已登记白名单。

### P2：历史迁移、差异校验与 cohort 开关

目标：在新旧双轨校验期内，将数据复制到 normalized 表并证明语义一致；仍不默认切换用户流量。

1. 实现管理命令：

```powershell
.venv\Scripts\python.exe manage.py migrate_planner_legacy --dry-run --user-id <id>
.venv\Scripts\python.exe manage.py migrate_planner_legacy --apply --batch-size 50
.venv\Scripts\python.exe manage.py verify_planner_migration --strict --from 2020-01-01 --to 2035-01-01
.venv\Scripts\python.exe manage.py verify_recurrence_parity --sample all --from 2020-01-01 --to 2035-01-01
```

2. 迁移顺序：EventGroup → 非重复 Todo/Reminder/Event → tags/links/share links → recurrence series → sparse exception/state → legacy ID map。
3. 对每个 series 用 legacy 规则和 normalized expander 在固定窗口比较 occurrence 的 recurrence_id、start/end、标题、状态、group、分享关系和 override 类型。
4. 无法一一解释的预生成实例、规则段边界或未来 override 写入 `PlannerMigrationIssue`，该用户不得进入 normalized cohort。
5. 加入仅迁移期开关：`PLANNER_STORAGE_MODE`、`PLANNER_DIFF_ASSERT`、`PLANNER_LEGACY_FALLBACK`、`PLANNER_CALDAV_NORMALIZED`；开关必须按 user cohort/入口记录。

验收：每个进入 cohort 的 user 无未解释 semantic diff；无限 recurrence 读取不产生普通 instance 行。

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
.venv\Scripts\python.exe -m unittest core.tests.test_planner_time_codec core.tests.test_recurrence_expander
```

运行命令时可设置 `DISABLE_EXTERNAL_MCP=1`，确保维护、迁移和验证进程不在导入期连接外部 MCP 服务。
