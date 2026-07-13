# P5-E 版本、并发与协议能力验收报告

> 验收日期：2026-07-13  
> 结论：通过

## 实施结果

- resource ETag 使用 immutable UID + Event/series/override 聚合版本指纹，不依赖秒级时间戳。
- collection CTag 直接使用 `CalendarCollectionVersion.version`；新增唯一 `CalendarCollectionChangeWriter`。
- Event create/update/delete、组移动、future split 和 Reminder mutation 均记录 CalDAV collection change。
- 组移动对旧 collection 写 delete tombstone、对新 collection 写 create，并分别增加版本。
- GET 支持 `If-None-Match` 304；OPTIONS/DAV/Allow 收敛到真实能力，不再宣称 WebDAV class 2/3、LOCK 或 sync-collection。
- 新增 collection version 初始化/严格校验与 capability 审计命令。

## 测试结果

- P5-E 版本专项：2/2 通过。
- P5-D+P5-E 联合：6/6 通过。
- 全量 `core.tests + agent_service.tests + caldav_service.tests`：168/168 通过。
- 连续同秒更新产生三个不同 ETag；304、stale 412、组移动双 collection 版本/tombstone、Reminder CTag、真实 Allow/DAV 均已断言。

## 生产校验

- capability audit：0 个虚假声明。
- MoMoJee normalized CalDAV collection 初始化：14 个（default、reminders、12 个有效 group）。
- collection version strict verify：0 issue。

## 结论

P5-E 达成版本、并发、change 审计与 capability 收口标准，进入 P5-F 停机/实库/全矩阵验收。
