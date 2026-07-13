# P4-G Agent 附件与 Reminder 完整链路验收报告

> 验收日期：2026-07-13  
> 结论：通过。用户报告的附件、回滚重发、Reminder recurrence/刷新、Agent 连接与新建日程延迟问题均已定位并修复。

## 根因与修复结果

### Agent 附件

1. FullCalendar 的重复实例 ID 是客户端复合 occurrence ID，旧拖拽逻辑却把它当 master ID 调 internal attachment API；API 失败后前端仍渲染磁贴并发送纯文本。现改为 master entity ID + occurrence_ref，失败会保留输入和附件选择并中止 WebSocket 发送。
2. 回滚曾把目标消息及以后附件全部软删除，再把已删除 sa_id 放回输入框；重发时 Consumer 查不到附件并静默降级。现目标消息附件退回 active pending，只有后续消息附件软删除，响应返回 authoritative DTO。
3. attachment format/Consumer/mark_sent 现在都校验 user、session、active pending 和 ID 等量；跨用户、跨会话、旧 ID、重复 ID 均被拒绝。
4. 附件 message_index 从错误的 `current_message_count + 2` 修正为实际 HumanMessage 的 `current_message_count`。

### Reminder

1. 旧 normalized PATCH 丢弃 rrule，后端也只写 master 标量，因此单次无法转重复。现 application/command/API/client 四层均传递 recurrence。
2. P3 只实现 occurrence 状态动作，single/future edit/delete 被前端硬编码拒绝。现实现 single sparse state、all series update、this_and_future lineage split，以及三种 delete scope。
3. 左侧列表原来读取 definitions，所以系列永远只有一条；现在按今天/周/月/季度/年/前90天至未来一年窗口读取 occurrences，并与 definition 合并。
4. 写后多处并发 refetch 会让详情读取旧 FullCalendar payload。现统一经过 `refreshReminderViews()`，详情使用点击 occurrence 的 payload/ref。
5. recurrence 取消后 OneToOne 软删除行仍存在，旧 singles 查询只判断 relation is null，导致 0 occurrence；现按“relation 不存在或 relation 已软删除”识别单次提醒。

### Agent 连接与日程即时刷新

- 临时验收进程使用普通 Django HTTP server，日志证明 `/ws/agent/` 连续返回 404。改用 Daphne 启动 `UniSchedulerSuper.asgi:application` 后，独立 ClientWebSocket 握手状态为 Open，Chrome 页面显示“已连接”。
- FullCalendar 同窗口并发读取旧逻辑会对第二个 callback 立即返回空数组，可能覆盖有效响应；Reminder filter 又会制造额外 refetch。现同窗口共享 Promise，侧栏渲染不再隐式刷新日历。
- MoMoJee 的“测试”事件在数据库与 occurrence API 中一直是即时可见，证明不是数据库延迟。修复后创建临时 `P4-G即时刷新验收-1032`，从点击创建到日历可见为 2.791 秒，随后已通过 v2 application service 删除。

## 自动化验收

| 范围 | 结果 |
|---|---|
| `core.tests + agent_service.tests` | 139/139 通过 |
| 新增附件/Reminder/rollback 定向 | 27/27 通过 |
| Django system check | 0 issue |
| migration drift | No changes detected |
| JS syntax：agent/event/reminder/modal/v2 client | 全部通过 |
| collectstatic | 已执行；最终变更已复制 |
| WebSocket 独立握手 | `Open` |
| Chrome 登录态页面 | Agent“已连接”；测试事件可见；新版控制台 0 error |
| 新建日程即时渲染 | 2.791 秒内可见 |
| MoMoJee strict migration verify | 0 diff |
| MoMoJee recurrence parity 2020–2035 | 0 diff |

新增测试具体覆盖：

- Event recurrence occurrence 附件使用 master ID 并固化有效 occurrence；Todo/Reminder master/occurrence 使用同一合同。
- pending 附件冻结进 HumanMessage additional_kwargs，模型上下文包含解析正文，message_index 精确绑定。
- format/Consumer 拒绝已发送、跨 session 和缺失附件；目标回滚附件 requeue，后续附件 soft-delete；rollback endpoint 返回恢复 DTO。
- Reminder 单次 attach recurrence、all 替换/移除 RRULE、single override、all 改时刻/拒绝改日期、this_and_future split/lineage/新规则、single/future delete、stale source_version 冲突和 v2 HTTP 合同。

## 数据影响

- 没有新增 migration，也没有批量改写既有 Planner/Reminder/附件数据。
- MoMoJee 原有“测试”事件未被删除或重建；只读核对显示其 normalized master/occurrence 一致。
- 浏览器即时刷新验收创建的唯一临时事件已按 v2 all scope 删除。
- 旧的已软删除附件不会被恢复；新状态机只对升级后的消息回滚生效。

## 运行要求

本地或生产运行含 Agent WebSocket 的完整站点时，必须使用 ASGI server，例如：

```powershell
.\.venv\Scripts\python.exe -m daphne -b 127.0.0.1 -p 8080 UniSchedulerSuper.asgi:application
```

普通 Django HTTP server 只适合不含 WebSocket 的有限调试，不能作为 Agent UI 验收或生产入口。
