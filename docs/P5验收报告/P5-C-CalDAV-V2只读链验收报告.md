# P5-C CalDAV V2 只读链验收报告

> 验收日期：2026-07-13  
> 结论：通过

## 实施结果

- 新增 `PlannerCalDAVQueryService`，并由 `PlannerApplicationService` 公开 collection/resource/get/query/version 五类只读用例。
- 已验证 cohort 的 Calendar Home、PROPFIND、calendar-multiget、calendar-query 和 resource GET 只读取 normalized 表并复用统一 mapper。
- default 只含无有效 group 的 Event；有效 group 独立成 collection；reminders 始终存在且只读；Todo 不进入 CalDAV。
- time-range 使用 Event/Reminder recurrence expander 判断实际 occurrence 相交，不再仅比较 master 时间。
- ETag 与 CTag 稳定；Depth infinity 403、畸形 XML 400、未知 collection 404、未知 report 501。

## 测试结果

- P5-C 专项：4/4 通过。
- 全量 `core.tests + agent_service.tests + caldav_service.tests`：162/162 通过。
- 覆盖 discovery/home、default/group/reminders、canonical href、RRULE/VALARM、稳定 ETag、multiget 单 href 404、跨窗口 recurrence query、协议错误及重复读取零写入。

## MoMoJee 实库验收

- 已开启 `caldav_read` normalized entrypoint。
- Home PROPFIND 与 default PROPFIND 均返回 207，可在真实数据规模下生成响应。
- 请求前后 Event 705、series 34、Todo 45、Reminder 19、UserData 20，完全一致。

## 结论

P5-C 达成文档验收标准，允许进入 P5-D 原子 PUT/DELETE。
