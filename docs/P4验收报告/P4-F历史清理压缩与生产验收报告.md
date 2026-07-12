# P4-F 历史清理、压缩与生产验收报告

> 验收日期：2026-07-12  
> 结论：通过。P4-0 至 P4-F 全部完成，可以进入 P5。

## 生产执行结果

- 停机检查未发现运行中的 Web/ASGI/MCP 项目进程。
- P4 前数据库备份：`backups/p4-20260712/db-pre-p4.sqlite3`，2,423,275,520 bytes；源与备份 SHA256 均为 `BE1CC376852D83E761C6B1191B85D6673C6CFE041F862941ECFAD841CB46DA6A`。
- 备份独立执行 `PRAGMA integrity_check=ok`、`foreign_key_check=0`。
- 已在当前数据库应用 `agent_service.0028` 与 `core.0011`；migration drift 为 0。
- MoMoJee 已在保留原 cohort 时间的前提下增加 `agent_planner`、`quick_action_planner`、`mcp_planner`、`internal_attachment` 四个 normalized 入口。
- cleanup dry-run 精确选择 42,259 个 Version、2,041 条 agent_service legacy transaction、34 条 core transaction、24 条旧 ChangeSet payload，估算序列化载荷 2,357,097,648 bytes。
- cleanup apply 删除上述 Version/旧事务以及 17,213 个 orphan Revision；当前 UserData 业务行、normalized 业务表、migration state/issue、legacy ID map 和 cohort assignment 的 checksum/计数均未改变。
- 24 条 P3 normalized ChangeSet 被压缩为轻量审计：before/after payload 均为空，保留 48 个 affected ref；不再具有旧回滚能力。
- 重复 cleanup apply 选择项全部为 0，证明幂等。
- `VACUUM INTO` 独立生成 32,083,968 bytes 新库；业务 checksum 与清理后源库同为 `6f29d1821b2d9c2851c58ab7376893b64ee870b5b215af5be021855b3a9e35d0`。
- 压缩库 SHA256 为 `354EB60A72FC23984EAD314CCA97A87905287EABDFB0FA40AAA9B0FE089E0377`，完整复验后已替换活动 `db.sqlite3`；活动库相对 P4 前缩小约 98.68%。
- 未压缩的清理后库保存在 `backups/p4-20260712/db-post-cleanup-unvacuumed.sqlite3`，未覆盖原始 P4 前备份。

## 数据校验说明

首次 P1–P3 基线发现 MoMoJee 7 项、yewei 3 项表面差异，经核查并非迁移损坏：

- MoMoJee 的 2 个 reminder 已在 normalized cohort 后通过 ChangeSet 标记 completed；5 个 recurrence 槽属于 cohort 后系列修改/删除。
- yewei 的 3 个 Todo 是 legacy 本地日期 `2026-02-12` 与 normalized UTC `2026-02-11T16:00:00Z` 的同一时间语义，旧 verifier 直接比较 date/datetime 导致误报。

verifier 已改为：日期与本地午夜 datetime 等价；只有目标 `updated_at` 晚于 cohort cutover 且存在 ChangeSet affected-ref 证据时，才作为 post-cutover evolution 跳过，并在报告中显式列出。最终全用户 32/32 strict 与 recurrence parity 均为 0 diff；清理后 MoMoJee 单用户复验也为 0 diff。

## 最终测试与验收矩阵

| 项目 | 结果 |
|---|---|
| `core.tests + agent_service.tests` | 124/124 通过 |
| rollback window + cleanup strict 定向 | 15/15 通过 |
| P4-D Quick Action/MCP 扩展定向 | 7/7 通过 |
| 删除旧回滚死代码后定向回归 | 7/7 通过 |
| cleanup dry-run/apply/repeat/strict 自动化 | 3/3 通过 |
| 全用户 migration strict | 32 用户，0 diff |
| 全用户 recurrence parity 2020–2035 | 32 用户，0 diff |
| SQLite integrity/foreign key | `ok` / 0 violation |
| Planner UserData reversion Version | 0 |
| 旧 `Before:` Agent Revision | 0 |
| legacy agent_service/core transaction | 0 / 0 |
| orphan Revision | 0 |
| Django check / migration drift | 0 issue / No changes detected |
| JS `node --check` | 通过 |
| `git diff --check` | 通过，仅 CRLF 提示 |
| P4 入口 reversion 静态依赖 | 0 文件 |

生产复验时活动库为 33,894,400 bytes；用户在清理后新增的 1 个 Event、1 个 Todo 以及界面设置版本均被保留。当前共有 84 个非 orphan Revision、2,500 个 Version，其中 42 个 UserData Version 全部为 `user_interface_settings`（约 86KB），Planner UserData Version 和旧 `Before:` Agent Revision 均为 0。当前有 1 个 active rollback window、0 个 snapshot；只有窗口内实际执行 Planner 命令后才产生短期压缩 snapshot，切走即过期删除。

## 410 回滚问题补充验收

用户在未重启/旧静态资源组合下进入新对话时，前端没有调用新增的 rollback-window rotate API，后端因此找不到 active window，并按安全策略返回 410。原实现把窗口建立的正确性错误地放在新版前端生命周期上，自动化只覆盖了显式 rotate 后的回滚，所以未能发现该组合。

修复后窗口由后端兜底：WebSocket 建连成功读取消息数后，以当前消息末尾作为 floor 创建缺失窗口；history API 对空会话用 floor=0、对已有会话用 `len(messages)` 补建；已有同会话窗口在刷新时保持原 floor/generation，不会扩大可回滚范围；切到另一会话会关闭旧窗口并删除其 snapshot。由此，升级前消息仍不可回滚，而窗口建立后的普通聊天和 Planner 工具消息均可回滚。

MoMoJee 失败会话 `user_1_ce9d7bea` 已用认证 history 请求验证：HTTP 200，服务端在已有 2 条消息的末尾建立 generation=1 窗口，旧消息 `can_rollback=false`，下一条消息开始具备回滚资格。对应自动化覆盖缺失窗口修复、刷新幂等、切换关闭、普通聊天零事务回滚、Planner 工具事务回滚、过期 410 与冲突 409。

## P4 完成判定

1. normalized WebSocket Agent、Quick Action、MCP stdio/HTTP 与 internal attachment 均经统一 application service。
2. Quick Action/MCP 只有审计，无聊天回滚 snapshot；Agent 仅在服务端 active window 内可回滚。
3. 旧 steps/core rollback URL 均只保留 410 响应，旧 reversion 执行代码已删除。
4. 前端 localStorage 不再决定授权；切换、切回、刷新与直接 API 的权限由后端一致执行。
5. 旧回滚大载荷已清理，压缩库完成独立校验并投入使用。

因此 P4 完成定义全部满足，下一阶段为 P5 iCalendar mapper、Feed、CalDAV PUT/DELETE/REPORT、ETag 与 collection change。
