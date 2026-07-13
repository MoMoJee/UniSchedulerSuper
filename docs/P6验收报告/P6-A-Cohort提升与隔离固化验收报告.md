# P6-A Cohort 提升与隔离固化验收报告

> 日期：2026-07-13  
> 结论：通过，可进入 P6-B。

## 实施

- 新增 `promote_verified_planner_cohorts`，默认 dry-run，只有 `--apply --all-entrypoints` 才写入。
- 封存每个账号的 P6 source manifest（key、row id、既有 verified checksum 与 aggregate SHA256），运行时 cohort 判定不再读取 legacy JSON 或逐请求复算 checksum。
- 为 34 个 verified clean 账号登记全部 14 个 entrypoint 为 normalized。
- 为五个批准的退役测试账号登记全部 14 个 entrypoint 为 quarantined，并固化 `retired-test-data-user-approved-2026-07-13` 处置；issue 保持 unresolved，未修复也未覆盖原数据。
- 全局 normalized 模式的未登记/部分登记用户改为 `blocked`，不再自动 fallback legacy。

## 测试和生产结果

```text
test_p6_cohort_promotion + test_planner_rollout: 4/4 passed
dry-run: users=39, promote=34, quarantine=5, blocking=0
apply: passed
second apply: passed; automated assertion confirms assignment version unchanged
post-apply readiness --strict: passed
```

生产 cohort：39 条；34 normalized、5 legacy-storage-but-quarantined；每条恰好 14 个 entrypoint，部分入口账号为 0。legacy archive 行数、bytes 与逐行 checksum 均与 P6-0 相同。

## 验收结论

选择器会阻止缺失 verified state 或出现任何非批准 unresolved issue 的账号；dry-run 零写入、apply 原子且幂等。五个隔离账号没有执行业务写入，全部准入状态可由稳定 disposition 识别。
