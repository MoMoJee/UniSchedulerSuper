# P4-C Agent Tool、cache/conflict 与群组切换验收报告

> 验收日期：2026-07-12  
> 结论：通过。允许进入 P4-D。

## 完成内容

- unified Planner tools 在 agent cohort 为 shadow/normalized 时统一进入 application adapter；legacy cohort 保留原 adapter。
- 旧命名 `planner_tools.py` 对 normalized 用户也委托同一 adapter，不再写 legacy JSON。
- `@agent_transaction` 对 normalized/shadow Planner 跳过六份完整 UserData reversion；可回滚 payload 由 P4-B 原子快照负责。
- SearchResultCache 保存 entity/series/recurrence/source version/occurrence ref，并按 user+session 读取。
- search 使用有限 occurrence query，默认窗口过去 30 天至未来 90 天并在输出中说明。
- update/delete 对重复 occurrence 使用完整 ref；future 映射 `this_and_future`，普通规则保持使用 `map_by_ordinal`。
- group/share/conflict 进入 application/query；他人共享 occurrence 只读且不分配可写 #N。

## 测试结果

| 范围 | 结果 |
|---|---|
| P4-C normalized tool tests | 5/5 通过 |
| P4-C 时全量 core + agent_service | 100/100 通过 |
| Django check | 0 issue |
| migration drift | No changes detected |
| `git diff --check` | 通过 |

关键断言：normalized unified CRUD 全程保持 legacy `UserData.events` 原值；Revision/Version 零增长；旧工具名委托 normalized；无限/有限 occurrence 的 #N 保留不同 recurrence ID；single 只写目标 override；cache 跨 user/session 不可解析；conflict 工具复用 application occurrence query。

## P4-D 实际规划

1. Quick Action 为每个 tool call 注入 `planner_source=quick_action`、真实 tool_call_id、request/task ID；保持 `reversible=False`。
2. MCP context factory 区分 stdio/HTTP，注入 source/request/transport session，HTTP 不得回退 stdio global user。
3. 两种 MCP transport 使用同一 unified tools/application adapter；稳定验证认证、跨用户 ref 和版本冲突。
4. 增加不调用真实 LLM/外部服务的 hermetic Quick Action tool-node 和 MCP wrapper 测试。

