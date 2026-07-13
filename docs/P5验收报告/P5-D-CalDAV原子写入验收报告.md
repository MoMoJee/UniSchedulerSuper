# P5-D CalDAV 原子写入验收报告

> 验收日期：2026-07-13  
> 结论：通过

## 实施结果

- 新增单一事务 `PlannerCalDAVCommandService`；PUT/DELETE 经 application façade 调用 V2 command，不再在 normalized 链中写 UserData 或调用旧 View/EventService。
- 支持 create/update/delete、default/group move、持久 UID/href、RRULE、RDATE、EXDATE、modified/cancelled override。
- `RANGE=THISANDFUTURE` 映射到 V2 split command，产生父/子系列 lineage，不预生成普通 occurrence。
- 支持 `If-Match`、`If-None-Match:*`、UID 冻结、512KB body 上限、只读 reminders 拒绝和事务失败全回滚。
- read 已切换而 write 未开放时明确返回 503，禁止回落 legacy 写入。

## 测试结果

- P5-D 专项：4/4 通过。
- 全量 `core.tests + agent_service.tests + caldav_service.tests`：166/166 通过。
- 覆盖 201/204/404/409/412/413、同资源重复创建、stale ETag、组移动、删除、完整 recurrence resource 往返、future split、失败零部分写入、legacy checksum 不变、无聊天 rollback snapshot。

## 生产准入

- MoMoJee 的 `calendar_feed/caldav_read/caldav_write` 三个 P5 entrypoint 均已登记 normalized。
- 本阶段没有用 MoMoJee 创建测试业务事件；真实写入/清理演练统一在 P5-F 停机验收执行。

## 结论

P5-D 达成原子写入验收标准，进入 P5-E collection version/change 与协议能力收口。
