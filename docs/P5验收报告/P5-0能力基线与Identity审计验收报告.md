# P5-0 能力基线、Identity 审计与测试隔离验收报告

> 验收日期：2026-07-13  
> 结论：通过。允许进入 P5-A。

## 1. 实施结果

- 新增只读 `audit_planner_ical_identity`，审计 normalized Event/series、legacy `caldav_uid`、拟议 canonical UID/resource name 和冲突。
- 新增 `caldav_service.tests.test_p5_baseline`，用 Django 临时数据库与临时 Token 固化 discovery、home/collection、GET、权限、只读 reminders、未实现 sync-collection 和读取无副作用。
- 现有 `tests/test_caldav*.py` 继续作为显式 live 联调脚本；P5 自动验收不依赖 localhost、生产 token 或生产数据库。
- 将 identity 审计命令加入 direct UserData access 的离线工具白名单；运行时 Planner bypass 仍为零。

## 2. 当前能力与缺口基线

已冻结的既有能力：Basic Token/密码、Token/Bearer、well-known/root/principal/home、default/group/reminders、PROPFIND、calendar-multiget、calendar-query、GET/PUT/DELETE、reminders 只读、MKCALENDAR 403、sync-collection 501 且不宣称支持。

确认的 P5 缺口：

- Feed 与 CalDAV 读取 legacy repository。
- CalDAV PUT 仍直接写兼容 UserData、调用旧 RRule manager 并预生成 instance。
- calendar-query 未使用 normalized expander。
- parser/builder 重复且缺少 normalized RDATE/EXDATE/DATE 等往返。
- ETag/CTag 仍依赖秒级 `last_modified`。

## 3. Identity 数据审计

报告：`logs/p5-ical-identity-before-20260713.json`

| 项目 | 结果 |
|---|---:|
| active CalendarEvent | 899 |
| active EventRecurrenceSeries | 75 |
| legacy 显式 caldav_uid | 14 |
| 非法 legacy events 行 | 0 |
| 调整 canonical policy 后 UID 冲突 | 0 |
| 调整 canonical policy 后 resource name 冲突 | 0 |

审计最初发现 MoMoJee 有两条不同业务记录会被旧 CalDAV 派生成相同 UID：一个普通 Web Event ID 为 `bc23…`，另一个旧 CalDAV 回写 Event ID/UID 为 `bc23…@unischeduler`。两条记录分组不同，不能擅自合并。

P5-A 最终 identity policy 因此确定为：

1. 显式 legacy `caldav_uid` 原样保留。
2. 普通 Web 单次 Event 使用 Feed 已公开的 `evt-{event_id}@unischeduler`。
3. 单次 Event href 继续使用原 event ID 或显式 legacy resource name。
4. series 使用显式 UID，缺失时使用 `evt-series-{series_id}@unischeduler`；href 使用 `evt-series-{series_id}`。

该策略保留全部 899 条 Event，不合并/删除数据，且拟议 UID/resource 均无冲突。

## 4. 自动化与数据验证

| 命令/范围 | 结果 |
|---|---|
| `manage.py check` | 0 issue |
| `makemigrations --check --dry-run` | No changes detected |
| `core.tests + agent_service.tests` | 139/139 通过 |
| P5 hermetic CalDAV baseline | 4/4 通过 |
| direct UserData access | planner bypass 0；14 条均为明确非 Planner 配置路径 |
| MoMoJee strict 2020–2035 | 0 diff |
| MoMoJee recurrence parity 2020–2035 | 0 diff |
| DB baseline | 35,389,440 bytes |
| DB SHA256 | `037DBB4ED4D612A35788EC248A0BE3BBBB035EEEADA0267B496726E800037B28` |

P5 baseline 测试连续执行 PROPFIND/GET，legacy events checksum 不变，证明基线读取无业务写入。

## 5. P5-A 实际规划

1. 为单次 Event 增加 immutable `ical_uid`/`caldav_resource_name`，为 series 增加 immutable resource name。
2. 以本报告锁定的 policy 做可逆 schema/data migration；迁移前后运行 identity audit。
3. 新增纯 `core/planner/ical.py`，覆盖 Event、series、RDATE/EXDATE、override、DATE/TZID、Todo/Reminder Feed 投影。
4. 用 table-driven round-trip 和无数据库访问测试作为 P5-A 阻断门槛。

P5-A 不切换 Feed/CalDAV 流量；切流分别属于 P5-B/P5-C/P5-D。
