# P6-E 上线烟雾与观察期启动报告

> 上线时间：2026-07-13 14:56（Asia/Shanghai）  
> 当前结论：技术上线烟雾通过；连续 7 天观察期已开始，尚不能宣告 P6-E/F 完成。

## 在线验收

- Daphne 在 `127.0.0.1:8080` 正常监听；以 `PYTHONUTF8=1` 启动，消除了 Windows 重定向日志对 emoji 的 GBK 编码错误。
- 真实 socket：MoMoJee bootstrap/event/feed 为 200，CalDAV PROPFIND 为 207。
- Agent WebSocket：HTTP 101，首帧 `connected`，ping 返回 `pong`，close code 1000。
- 隔离账号在线写烟雾：Event 201、Todo 201、重复 Reminder 201、读 200、CalDAV PUT 201/DELETE 204；清理后 User/UserData/Event/Todo/Reminder 计数精确恢复，archive checksum 不变。
- 服务日志未出现 500、Traceback、SQLite lock 或 `P6_LEGACY_*` guard 命中。

## 真实浏览器（MoMoJee）

- 页面 bootstrap 后 `data-planner-storage-mode=normalized`。
- 待办列表显示 44 项；提醒侧栏显示重复 master 1 项；周历显示该规则展开的 3 个窗口内 occurrence。
- 日历、待办、提醒加载完成；Agent 状态从重启瞬间的未连接恢复为“已连接”。
- 在服务稳定后再次完整 reload：normalized、Agent 已连接、Event/Reminder/Todo 均显示，reload 时间点之后新增 console error/warn 为 0。
- 浏览器技能用于验证现有登录会话的真实 UI 状态；没有对 MoMoJee 业务记录做创建或删除，在线写矩阵由隔离账号完成。

## 自动化与数据门禁

- `check`、schema drift、178/178 全量测试通过。
- 34 个非隔离账号 migration/recurrence parity 均 0 diff。
- MoMoJee identity、14 个 collection version、Feed/CalDAV、direct access 全部通过。
- 五个 retired quarantine 的 V2 状态均为 423。
- release verify 的所有检查为 true，且只读 smoke 零写入。

## 观察期

从 2026-07-13 14:56 起每日重复：

1. `verify_planner_release --strict`、`verify_no_legacy_planner_write --strict`。
2. archive manifest verify、integrity/foreign key。
3. 检查 500、SQLite locked/busy、legacy guard、rollback 410/conflict、Reminder delivery、Feed/CalDAV 4xx/5xx/412。
4. 检查 Event/Reminder series、override/state 和 ChangeSet 增长是否可解释。

最早连续 7 天门槛为 2026-07-20 14:56；P6-F 还必须跨过至少一个后续生产版本。当前不得删除旧 adapter、archive、`PlannerLegacyIdMap` 或 `GroupCalendarData.events_data` 字段。
