# P5-A iCalendar Identity Migration 与统一 Mapper 验收报告

> 验收日期：2026-07-13  
> 结论：通过。允许进入 P5-B。

## 实施结果

- `CalendarEvent` 新增 immutable `ical_uid`、`caldav_resource_name` 及 per-user unique constraints。
- `EventRecurrenceSeries` 新增 immutable `caldav_resource_name`；series canonical UID 收敛为显式 legacy UID 或 `evt-series-{series_id}@unischeduler`。
- `CalendarEvent.save()` 与 series save/command 为所有 P5 后新对象补齐稳定 identity。
- migration `core.0012_planner_ical_identity` 根据只读 legacy `caldav_uid` 回填；旧 series UID 保存于 metadata，可做 reverse migration。
- 新增纯 `core/planner/ical.py`；模块不查 ORM、不接收 HTTP request。
- mapper 支持 master + sparse override、DATE/DATE-TIME、TZID、DURATION、RRULE/RDATE/EXDATE、RECURRENCE-ID、SEQUENCE、VALARM、文本转义和严格非法输入拒绝。

## 数据迁移

- P5 前一致备份：`backups/p5-20260713/db-pre-p5.sqlite3`
- 备份 SHA256：`86A2A73FE02723D99D4C824339D9FA19326D37F873284D1BCCA82329B9851E57`
- 备份 integrity：`ok`；foreign key 无违规。
- migration plan 仅包含三个 identity 字段、数据回填和三个 unique constraint；apply 成功。

迁移后 identity 审计：

| 项目 | 结果 |
|---|---:|
| active Event | 899 |
| active series | 75 |
| legacy caldav_uid | 14，全部匹配 |
| Event identity mismatch | 0 |
| Series identity mismatch | 0 |
| UID conflict | 0 |
| resource conflict | 0 |
| invalid legacy row | 0 |

## 测试结果

| 范围 | 结果 |
|---|---|
| Mapper + baseline 定向 | 11/11 通过 |
| identity model/constraint 新增 | 3/3 通过 |
| `core.tests + agent_service.tests + caldav_service.tests` | 153/153 通过 |
| Django check | 0 issue |
| migration drift | No changes detected |
| DB integrity/foreign key | ok / 0 |
| MoMoJee strict | 0 diff |
| MoMoJee recurrence parity 2020–2035 | 0 diff |

关键断言：

- 普通 Event 与 series identity 永久稳定，更新标题不改变 UID/href。
- per-user 重复 UID/resource 被数据库拒绝。
- mapper round-trip 保留中文、换行、时间类型、时区、recurrence 与 override。
- mapper 测试拦截 DB cursor，编码过程零 ORM 访问。
- P5 migration 没有创建、合并或删除业务 Event/series。

## P5-B 实际规划

1. 增加 normalized Feed projection，将 Event definition、Todo due、Reminder definition/state 转成统一 DTO。
2. `calendar_feed` 使用 `calendar_feed` rollout entrypoint 与 Planner application，不读取 legacy 业务投影。
3. 保留 URL token、四种 type、headers、VTIMEZONE、标题分组前缀和 VALARM。
4. 新增 Feed 全类型、recurrence、权限、特殊文本、读取零增长和 legacy checksum 测试。
