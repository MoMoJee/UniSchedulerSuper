# P6-D 全停机生产切换验收报告

> 日期：2026-07-13  
> 结论：停机演练与生产切换全部通过，可启动服务进入 P6-E 观察期。

## 停机与备份

- 确认 8080 无监听，且没有命令行指向本项目的 Python/Daphne 进程。
- 一致备份：`backups/p6-cutover-20260713/db-pre-p6.sqlite3`。
- 切换前活动库、备份、演练副本 SHA256 均为 `0D0EFC88B516A3B026674B14F70496B795C8F71B4B512DB8D9EEAC8FB2489531`。
- 备份与演练副本均 `integrity_check=ok`、`foreign_key_check=[]`。

## 副本演练

使用 `UNISCHEDULER_DB_PATH=backups/p6-cutover-20260713/db-rehearsal.sqlite3` 完整执行：

1. `migrate --plan` 仅包含 `core.0013`；apply 成功。
2. archive manifest 对 P6-C 基线 verify 成功并 seal。
3. 五个 SQLite trigger、ORM/raw/compat 防写和配置 key 写入验证全部通过。
4. CalDAV 隔离写烟雾：207/201/200/204/412/204，清理后八类计数精确恢复，legacy checksum 不变。
5. 34 个非隔离账号 migration 与 recurrence parity 均为 0 diff。

演练副本最终仍为 `integrity_check=ok`、外键 0 行。

## 生产切换

- `core.0013_planner_legacy_write_guard` apply 成功。
- archive seal 成功；aggregate SHA256 `B0F73F505DB17D15FF1E857E41E4DC9F2E62ED3F166735B1F698D7472125CF0D`。
- `verify_no_legacy_planner_write --strict` 通过。
- guard 开启后 CalDAV 写烟雾完整通过、清理精确、legacy unchanged。
- `check`、schema drift、178 项全量测试、strict migration/recurrence、identity、collection version、direct access 全部通过。
- MoMoJee 停机只读 smoke：bootstrap/event/todo/reminder/feed 均 200，CalDAV 207；五个 quarantine 均 423；smoke 零写入。
- 最终活动库：36,159,488 bytes，SHA256 `16CF7978BB2C05108A0BD449733887343EF49259B6A4B79AFBC7E9B3A2669E44`，integrity ok、外键 0 行。

## 数据计数

生产只读门禁记录：User 39、UserData 303、Event 912、Todo 50、Reminder 29。CalDAV 隔离 smoke 前后 User/Token/UserData/Event/Series/CollectionVersion/CalendarChange/ChangeSet 八类计数完全一致。

## 回退材料

服务启动前的原库备份、已迁移演练副本、逐行 archive manifest、迁移/parity/identity/version 报告均已保留。若启动后发现一致性问题，应先停服务并保留当前故障库，不以旧备份覆盖 P6 后新写入。
