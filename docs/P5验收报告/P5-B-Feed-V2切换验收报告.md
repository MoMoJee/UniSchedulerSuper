# P5-B Feed V2 切换验收报告

> 验收日期：2026-07-13  
> 结论：通过

## 实施结果

- `calendar_feed` 已成为独立 rollout entrypoint；MoMoJee 已开启 normalized 模式。
- Feed 业务响应改为 `PlannerApplicationService -> NormalizedCalendarProjectionService -> core/planner/ical.py`。
- Event、重复 Event、稀疏 override/cancellation、带期限 Todo、单次/重复 Reminder 共用唯一 iCalendar mapper。
- 尚未开启 entrypoint 的用户仍保持旧响应，P6 再移除兼容分支；normalized 构建失败不会静默回退 legacy。
- 访问日志对 query token、Authorization 和其他敏感 query 字段执行脱敏。

## 自动化验收

执行并通过：Django system check（0 issue）、migration drift（无）、P5-B Feed 专项 4/4、日志脱敏专项 1/1、P5 mapper/identity/CalDAV 基线联合回归 18/18。

覆盖范围：

1. `all/events/todos/reminders` 四种输出 profile；
2. 缺 token 400、错 token 403、错 type 400；
3. normalized 数据存在、legacy JSON 含污染条目时，只输出 normalized；
4. RRULE、组名前缀、Unicode/转义文本、VALARM；
5. 无期限 Todo 不进入 Feed；
6. 连续四种 Feed 读取后 Event/series/Todo/Reminder 行数、版本、更新时间以及 legacy source 均不变化；
7. 未切换用户仍保持兼容响应；
8. token 不再出现在访问日志明文中。

## MoMoJee 实库验收

- 响应：HTTP 200，320446 bytes。
- VEVENT：712；含 RRULE master：25；VALARM：19。
- 请求前后计数完全一致：Event 705、Event series 34、Todo 45、Reminder 19、UserData 20。
- 结论：真实大数据 Feed 可解析，且读路径零业务写入。

## 验收结论

P5-B 的功能、隔离、只读性和安全日志要求均满足，允许进入 P5-C CalDAV 只读 façade。
