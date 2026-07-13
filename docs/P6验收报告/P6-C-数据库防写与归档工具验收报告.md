# P6-C 数据库防写与归档工具验收报告

> 日期：2026-07-13  
> 结论：代码与测试库验收通过；生产启用按 P6-D 停机流程执行。

## 实施

- 新增 `PlannerLegacyWriteGuard` 单例控制记录和 migration `0013`。
- SQLite trigger 覆盖核心 Planner key 的 INSERT/UPDATE/DELETE，以及 `GroupCalendarData.events_data` 非空 INSERT/内容 UPDATE。
- `LegacyPlannerRepository`/`PlannerUserDataCompat` 在 guard 开启时统一抛出 `LegacyPlannerWriteForbidden`。
- 新增 `audit_legacy_planner_archive`，逐行记录 user/key/source id/bytes/SHA256，并对分享组旧投影做 checksum；支持重复 verify 和 seal。
- 新增 `verify_no_legacy_planner_write`，验证 trigger、ORM/raw SQL/compat 拦截和配置 key 可写。
- P5 CalDAV smoke 改为使用 sealed empty manifest 的隔离账号，不再创建/删除 Planner legacy 行，因而可在 trigger 开启后执行。

## 测试结果

```text
makemigrations --check --dry-run: No changes detected
test_p6_legacy_write_guard: 2/2 passed
archive create + independent verify: checksum match
full suite discovered: 178
```

数据库专项覆盖：ORM insert/update/delete、raw SQL insert、compat initialize 全部失败；`ui_settings` create/update/delete 正常；normalized Event command 在 trigger 开启时成功。全量回归中只出现新增离线命令未登记静态审计白名单的门禁失败，已将两条命令登记为离线 archive/verification 工具；业务用例无失败。P6-D 在生产 migration/封存后会重跑完整 178 项并以该次结果作为最终门禁。

## 归档基线

`logs/p6-archive-preseal.json` 与 `logs/p6-archive-preseal-verify.json` 的 aggregate checksum 一致；报告只含标识、长度与 hash，不含 legacy 正文或凭据。生产库尚未在本小阶段启用 guard，避免越过 P6-D 的备份/演练顺序。
