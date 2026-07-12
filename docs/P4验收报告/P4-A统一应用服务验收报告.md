# P4-A Execution Context 与统一应用服务验收报告

> 验收日期：2026-07-12  
> 结论：通过。允许进入 P4-B。

## 1. 完成内容

- 新增可信、不可变 `PlannerExecutionContext`，限制 source、entrypoint、session、tool call 和 reversible 组合。
- 新增 `PlannerApplicationService` 与稳定 access error；不接收 HTTP Request、不调用 View、不构造 MockRequest。
- Event definition/occurrence/conflict/search/create/patch/delete，Group、Todo、Reminder、Reminder occurrence action、Share occurrence 全部形成统一 use case。
- 所有 Planner V2 View 改成协议适配层并委托 application service；View 不再直接调用 repository/entity/command service。
- rollout policy 增加 `agent_planner`、`quick_action_planner`、`mcp_planner`、`internal_attachment` 入口常量；本阶段尚未切 Agent 流量。

## 2. 测试结果

| 范围 | 结果 |
|---|---|
| P4-A 新增 context/application tests | 5/5 通过 |
| P4-A + Planner V2 API 定向矩阵 | 28/28 通过 |
| `core.tests + agent_service.tests` | 86/86 通过 |
| Django check | 0 issue |
| migration drift | No changes detected |
| Python compile | application/context/view 全部通过 |
| `git diff --check` | 通过，仅有既有 LF/CRLF 提示 |

新增断言覆盖：

- 非 WebSocket source 不能伪造 `reversible=True`。
- shadow application write 被 gate 拒绝且 CalendarEvent/ChangeSet 零写入。
- 直接 service 与 HTTP adapter 创建产生相同 public contract 和 command type。
- 跨用户 event ref 无法写入且原对象不变。
- V2 occurrence View 确实委托 application service。

## 3. 验收标准对照

1. **同一 command 经 Web 和 service 领域结果一致**：通过。
2. **跨用户、错误 cohort、shadow write 拒绝且零写入**：通过。
3. **应用服务是唯一 use-case 层**：通过；V2 View 已移除直接 service/repository 调用。
4. **不接受 MockRequest、不调用 View**：源码审计通过。
5. **现有 P1–P3 无回归**：86/86 通过。

## 4. P4-B 实际规划

P4-B 将按以下顺序实现，避免先改 Agent tools 后才补回滚：

1. 新增 `AgentRollbackWindow`、`PlannerRollbackSnapshot` 和统一后的 AgentTransaction 关联字段；生成 schema migration。
2. 建立 allowlist aggregate serializer、zlib/checksum 和 restore engine，先覆盖 Event 全 scope，再覆盖 Todo/Reminder/Group。
3. Application Service 在可信 reversible context 下包裹命令并原子写 snapshot/ChangeSet/AgentTransaction；普通 Web/QA/MCP 不生成 rollback payload。
4. 新增 window open/rotate/close domain service；P4-E 才接 UI API。
5. 新增 rollback coordinator，执行 current-hash preflight、逆序 snapshot restore、version/collection 单调递增和 cache invalidation hook。
6. 使用故障注入、并发冲突和复杂 recurrence 矩阵验收；本阶段不删除任何生产旧历史。

