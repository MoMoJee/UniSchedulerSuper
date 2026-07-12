# P4-B 压缩快照与回滚内核验收报告

> 验收日期：2026-07-12  
> 结论：通过。允许进入 P4-C。

## 完成内容

- 新增服务端 `AgentRollbackWindow`、短期 `PlannerRollbackSnapshot` 及统一 AgentTransaction 的 P4 关联字段。
- 新增两份 schema migration：`agent_service.0028`、`core.0011`。
- 新增 allowlist aggregate serializer、canonical business hash、zlib-json-v1、SHA256 校验和恢复器。
- Application Service 仅在可信 `reversible=True` context 下原子记录 snapshot/ChangeSet/AgentTransaction；普通 Web/QA/MCP 不生成 snapshot。
- 新增 rollback coordinator：after hash preflight、冲突整体拒绝、业务状态恢复、version/collection token 单调递增。
- window rotate 会关闭旧 generation 并物理删除旧 snapshot payload。

## 测试结果

| 范围 | 结果 |
|---|---|
| P4-B snapshot/restore 定向测试 | 9/9 通过 |
| P4-B 时全量 core + agent_service | 95/95 通过 |
| Django check | 0 issue |
| migration drift | No changes detected |
| migrate plan | 仅 0028/0011 预期操作 |

覆盖 create/absence、single override、all 时间与标题、future split、Todo→Event、Reminder occurrence state、Group+成员项、外部后续写 conflict、window rotate、失败/低于 floor 零写入。压缩 payload 小于原始 canonical JSON；rollback 后 snapshot 删除。

## 验收结论

操作前投影可恢复；技术版本不倒退；外部后续写返回 conflict 且零部分恢复；业务命令、snapshot、ChangeSet、AgentTransaction 位于同一原子事务。P4-B 不清理生产旧历史，符合阶段边界。

