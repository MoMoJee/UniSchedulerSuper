# P6-B 运行时 Legacy 断路验收报告

> 日期：2026-07-13  
> 结论：通过运行态门禁，可进入 P6-C 数据库级防写。

## 实施

- normalized 全局模式下，未登记、部分登记、迁移不洁账号统一变为 `blocked`，不再返回可被调用方误解为 fallback 的 `legacy`。
- retired quarantine 在 V2 使用稳定 `planner_retired_quarantine`/HTTP 423；Feed、CalDAV、课程导入采用同一拒绝语义。
- Agent、Quick Action、MCP、内部附件和 Agent rollback 装饰器在 normalized 部署中始终进入 application gate；准入失败不再选择旧工具或旧快照。
- 前端 cohort client 将 quarantine/blocked 请求送往 V2 稳定拒绝，不选择遗留 UI API。
- Feed/CalDAV 的旧实现只允许全局显式 `PLANNER_STORAGE_MODE=legacy` 的离线兼容测试使用；生产 normalized 路径没有异常 fallback。

## 测试

```text
P6 no-fallback 专项：2/2 passed
rollout/feed 专项：8/8 passed
direct UserData gate：planner_bypass_count=0
P1–P5 + P6 全量：Found 176; Ran 176; OK; 0 skipped
```

专项测试在 legacy repository read 上安装强制异常，然后请求 quarantine 的 V2、Feed、CalDAV、课程导入与 Agent 路由；实际分别返回 423/显式 application gate，未触发异常，legacy 行内容保持不变。正常 normalized cohort 的 Event/Todo/Reminder、Agent/Quick/MCP、附件/回滚、Feed/CalDAV 全量回归通过。

## 保留边界

旧 adapter 源码目前仍为全局 `legacy` 模式的测试/恢复材料存在，但 normalized 生产状态不可达；其物理删除属于文档规定的 P6-F，并受“后续版本 + 连续 7 天”前置约束。P6-C 将再增加数据库 trigger，使即使误调用旧代码也无法写核心 key。
