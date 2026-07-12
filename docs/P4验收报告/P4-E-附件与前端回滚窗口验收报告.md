# P4-E 附件与前端回滚窗口验收报告

> 验收日期：2026-07-12  
> 结论：通过。允许进入 P4-F。

## 完成内容

- internal attachment 的 event/todo/reminder 列表、解析和快照对 normalized cohort 统一委托 `PlannerApplicationService`；不展开无限 recurrence，不读取 legacy Planner JSON。
- `SessionAttachment.internal_snapshot` 在绑定时固化规范化 master/series 的不可变快照；源对象之后软删除仍可使用 `parsed_text` 与 snapshot 展示历史附件。
- 新增 rollback window rotate/close API；一次激活会关闭该用户其他 active window、使 ChangeSet 过期并物理删除压缩 snapshot。
- history 返回 window ID、generation、服务端 floor 和逐条 `can_rollback`；前端不再从 localStorage 读取或保存回滚授权。
- 页面刷新复用已存在 active window；切走关闭旧窗口；切回以当前消息末尾创建新 generation/floor，旧资格不会恢复。
- WebSocket Agent ToolNode 将真实 tool call ID、active window ID 和最近 HumanMessage 索引注入 Planner context，因此只有当前窗口内的 Agent 写入创建 P4 snapshot。
- `rollback/to-message` 按消息索引倒序恢复新 snapshot；外部后续写返回 409，旧窗口/升级前历史返回 410。旧 steps API 和旧 `core/views_rollback.py` 路径均固定返回 410。
- 回滚成功后继续同步清理 search cache、附件、会话 TODO、摘要与 token snapshot。

## 测试结果

| 范围 | 结果 |
|---|---|
| P4-E rollback window + attachment 定向用例 | 9/9 通过 |
| P4-E 时全量 `core.tests + agent_service.tests` | 113/113 通过 |
| JavaScript 语法检查 `node --check` | 通过 |
| localStorage 回滚授权残留扫描 | 0 处 |
| Django system check | 0 issue |
| migration drift | No changes detected |
| `git diff --check` | 通过（仅换行提示） |

关键断言：activation token 重试幂等；任一用户仅一个 active window；切回旧会话生成更高 generation 且 floor 等于当前末尾；history 中 floor 前后消息分别不可/可回滚；直接 API 绕过 UI 仍返回 410；冲突返回 409 且未调用消息删除；ToolNode 实际产生 window-bound snapshot；消息回滚恢复业务投影；normalized 附件保持 legacy JSON 原值；源删除后附件 snapshot 与 parsed text 不变。

## P4-F 实际规划

1. 新增 legacy rollback 清理命令，支持 dry-run/apply/重复 apply；删除旧 UserData reversion Version/Revision、旧两套 AgentTransaction 和升级前不可恢复历史，保留业务 UserData 当前行。
2. 新增清理后验证命令，输出旧历史残留、新 snapshot/window 状态、业务实体计数、SQLite integrity/foreign key 与数据库大小。
3. 增加清理命令自动化测试：范围精确、幂等、业务 checksum 不变、旧请求 410、新窗口回滚仍可用。
4. 对当前数据库先备份并记录 SHA256，执行 migrate、before/dry-run/apply/after 报告；再对数据库副本执行安全压缩演练并比较业务 checksum。
5. 完成 MoMoJee P4 入口 assignment、全量 P1-P4 回归、入口审计 after 报告和 Changelog；所有门槛通过后再判定 P4 完成。

