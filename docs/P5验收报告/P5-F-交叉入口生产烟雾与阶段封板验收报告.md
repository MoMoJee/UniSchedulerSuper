# P5-F 交叉入口、生产烟雾与阶段封板验收报告

> 验收日期：2026-07-13  
> 结论：通过；P5-0 至 P5-F 的代码、迁移、自动化与停机数据库烟雾验收已完成。

## 实施结果

- 增加 Web/CalDAV/Feed 交叉可见性、无限重复只读零增长和 Basic/Token/Bearer 鉴权矩阵。
- 增加 `run_p5_caldav_smoke` 隔离生产烟雾命令，覆盖 PROPFIND、create、GET、update、stale ETag 412 与 delete，并在结束后清除临时用户。
- 将烟雾命令明确登记为离线验证工具；运行时 Planner `UserData` 绕过数为 0。
- MoMoJee 的 Feed/CalDAV read/write entrypoint 已全部切换 normalized；identity、collection version 与迁移 parity 门禁均通过。

## 自动化证据

```text
manage.py test core.tests agent_service.tests caldav_service.tests
Found 171 test(s); Ran 171 tests; OK; 0 failed; 0 skipped

report_planner_direct_userdata_access
finding_count=146
out_of_planner_scope_count=14
planner_bypass_count=0

test_p5_crossover_matrix
3/3 passed
```

交叉矩阵验证：Web 写入可由 CalDAV 读取、CalDAV 写入可由 Feed 读取；全天无限系列反复读取 100 次实体/series/override 数量不增长；Basic token、Basic password、Token 和 Bearer 均遵守既有鉴权契约。

## 停机生产数据库验收

- `run_p5_caldav_smoke`：PROPFIND 207、create 201、GET 200、update 204、stale 412、delete 204。
- 烟雾前后精确计数一致：User 39、Token 20、UserData 303、CalendarEvent 912、Series 86、CalendarCollectionVersion 17、CalendarChange 79、PlannerChangeSet 91。
- `verify_planner_migration --strict --user-id 1`：`difference_count=0`。
- `audit_planner_ical_identity`：mismatch/conflict/invalid 均为 0；14 个 attention 项是被明确保留的历史 CalDAV UID。
- `verify_calendar_collection_versions --strict --username MoMoJee`：14 个 collection，0 issue。
- 活动库与发布前备份均为 `integrity_check=ok`、`foreign_key_check=[]`。
- 发布前备份：`backups/p5-final-20260713/db-pre-p5f.sqlite3`，SHA256 `4EE5BC6CA6FC74620029DB4936B4F57447C967A54478BF2FC5194766FDD1802A`。

## 验收边界

协议行为已用 Apple/Thunderbird 所需的 discovery、collection、REPORT、ETag 和系列写入工作流自动化覆盖；当前环境没有外部 Apple/Thunderbird 实机，因此不虚报物理客户端人工结果。服务恢复后的真实客户端刷新列入 P6-E 观察清单，不影响 P5 后端适配门禁。

## 阶段结论

P5 的 Feed 与 CalDAV 运行路径已统一到 normalized Planner application/query/command 和共享 iCalendar mapper；legacy checksum 在写入烟雾中保持不变，可进入 P6 最终停写与归档阶段。
