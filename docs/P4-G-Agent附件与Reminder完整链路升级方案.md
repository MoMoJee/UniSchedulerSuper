# P4-G Agent 附件与 Reminder 完整链路升级方案

> 编制日期：2026-07-13  
> 范围：Agent 内部实体/文件附件、消息回滚重发、normalized Reminder CRUD/recurrence scope、日历与侧栏投影。  
> 目标：消除“UI 看见但 Agent/后端没有”“写入成功但某个 UI 投影仍旧”“重复系列只展开一处”的分叉状态。
> 状态：已实施并通过验收；实际结果见 `docs/P4验收报告/P4-G-Agent附件与Reminder完整链路验收报告.md`。

## 1. 已复现/已确认问题与根因

### 1.1 内部日程附件 UI 有磁贴但 Agent 看不到

FullCalendar 中重复日程和重复提醒使用 `event:<entity>:series:<series>:recurrence:<rid>` 形式的客户端 occurrence ID。`event-manager.js` 拖入 Agent 时把这个复合 ID 当成 master `event_id/reminder_id` 发送，而 `PlannerApplicationService.get_attachment_item` 只按 master ID 查询，因此 `/api/agent/attachments/internal/` 返回创建失败。

`agent-chat.js#getFormattedAttachmentContent` 没有检查 HTTP 状态，也没有把单个附件失败传播给发送流程；`sendMessage` 仍按原前端选择数组渲染磁贴并发送不含 `attachment_ids` 的 WebSocket 消息，于是形成“用户看见附件，Agent 实际没有附件”。单次 Event、侧栏 Todo/Reminder 使用 master ID，可能正常；重复 occurrence 必然存在风险。

### 1.2 文件/图片附件回滚后重发丢失

回滚当前消息时，`AttachmentHandler.soft_delete_by_rollback` 把目标消息及之后的附件全部标为 `is_deleted=True`。前端随后把原磁贴数据恢复到发送框，并保留旧 `sa_id`。再次发送时不创建新记录，WebSocket 后端却按 `is_deleted=False` 查询，因此得到空附件集合并静默降级为纯文本。

正确生命周期应区分：

- 目标用户消息自己的附件：撤回后变回 pending，保留原文件、解析结果和 immutable internal snapshot，可直接重发；
- 目标消息之后被删除的其他消息附件：继续软删除，不能全部塞回发送框；
- 旧会话/跨用户附件 ID：必须拒绝，不能静默忽略。

### 1.3 单次 Reminder 无法转为重复 Reminder

normalized 前端 `ReminderManager.updateReminder` 即使表单生成了 `rrule`，PATCH payload 也完全不包含 `recurrence`。后端 `PlannerEntityCommandService.patch_reminder` 同样只修改 master 标量和 trigger，不会创建 `ReminderRecurrenceSeries`。因此保存返回成功，但对象仍是单次提醒。

### 1.4 重复 Reminder 编辑后日历详情仍显示旧值

当前系统有两份 UI 投影：侧栏 `reminderManager.reminders` 读取 master definitions，日历读取窗口 occurrences。编辑成功后 `loadReminders -> applyFilters -> calendar.refetchEvents` 与调用方额外的 `refetchEvents` 会并发重复刷新；`event-manager` 又在相同窗口请求 in-flight 时以空数组成功返回。详情点击读取 FullCalendar 旧 event 的 `reminderData`，编辑按钮却读取已经刷新的 master 数组，因此出现“详情旧、编辑表单新”。

此外，重复系列编辑的 normalized 分支明确硬编码拒绝 `single/from_this/from_time`，all 分支也丢弃 `rrule`。提示“新版重复提醒的单次/未来范围编辑尚未开放”不是操作错误，而是 P3 只实现了 Reminder occurrence 状态动作，未实现 Reminder recurrence command scope。

### 1.5 左侧 Reminder 筛选只显示一个重复提醒

`/api/v2/reminders/` 不带窗口时返回 master definitions。侧栏直接渲染 definitions，所以每个重复系列只显示 master 一行；中央日历带 `from/to` 请求 occurrences，因而能正确展开 RRULE。这不是 RRULE 引擎失败，而是两个 UI 使用了不同查询语义。

### 1.6 同链路的其他风险

1. 内部附件创建失败、附件格式化失败、WebSocket 附件查询为空均会静默降级，缺少端到端一致性断言。
2. `mark_sent` 只按 ID 更新，未同时约束 user/session/pending 状态。
3. 重复 Reminder 侧栏没有 occurrence_ref，导致“仅此/此后”无法确定锚点和 source_version。
4. Reminder master version 与 series/source version 混用，规则更新存在错误的乐观锁版本。
5. 修改过的静态文件版本号未全部更新，浏览器可能继续使用旧附件/回滚代码。

## 2. 目标调用链

### 2.1 附件发送

```text
UI 选择 master 或 occurrence
  -> 前端携带 entity_id + 可选 occurrence_ref
  -> POST internal attachment，服务端验证 user/session/ref
  -> 固化 immutable snapshot + parsed_text，返回 SessionAttachment DTO
  -> 前端只使用服务端返回 DTO 渲染磁贴
  -> WebSocket 发送 attachment_ids
  -> Consumer 严格验证数量、归属、session、pending/active
  -> HumanMessage.additional_kwargs 固化 ids/metadata/context
  -> Outbound materializer 将实体/文档文本或图片块送入模型
```

任一步失败都中止发送并恢复输入内容，不允许生成“假磁贴”。Todo、Reminder、Event 使用同一合同。

### 2.2 附件回滚重发

```text
rollback target user message
  -> 恢复 Planner snapshot / 删除消息
  -> target message attachments: requeue(message_index=null, sent_at=null, active)
  -> later message attachments: soft delete
  -> rollback response 返回 authoritative requeued DTO
  -> 前端用 DTO 恢复发送框
  -> resend 复用 active pending sa_id
```

### 2.3 Reminder command scope

统一使用 `occurrence_ref + expected_version + scope`：

- 非重复 Reminder：`single/all` 都修改 master；传 `recurrence` 时允许单次转重复。
- `all`：修改 master 与整个 series；时间只允许改变时刻，不允许意外改变系列起始日期；允许更新/移除 RRULE。
- `single`：写入稀疏 `ReminderOccurrenceState.patch/effective_trigger_at`，不改变其他 occurrence。
- `this_and_future`：在锚点截断父 series，创建带 lineage 的 child master/series，并迁移未来 occurrence states；规则改变时重新规范化 RRULE。
- delete 的 `single/all/this_and_future` 与 edit 使用相同锚点语义。

## 3. 分步实施与验收标准

### G1：附件合同与错误可见化

实施：

1. internal attachment API 接受可选 `occurrence_ref`；服务端从 ref 取得 master entity ID，并用 occurrence 的有效时间/override 内容生成快照。
2. 前端 FullCalendar 拖拽传 `extendedProps.occurrence_ref`，不再传复合 client ID 充当 master ID。
3. `getFormattedAttachmentContent` 返回完整服务端 DTO；非 2xx、数量不一致、任何附件创建失败均抛错。
4. `sendMessage` 在附件解析成功前不清空输入/选择；失败则不写 UI、不发 WebSocket。
5. Consumer 对 user/session/未删除附件进行等量验证，拒绝缺失 ID。
6. format API 同样要求 user/session/active pending/ID 等量一致，避免格式化成功后才在 WebSocket 阶段发现旧附件 ID。

测试：Event/Todo/Reminder master；三类 recurrence occurrence；不存在、跨用户、跨 session、重复 ID；API 失败时 WebSocket 零发送。

验收：UI 磁贴数 = SessionAttachment 数 = HumanMessage metadata 数 = 模型上下文数；任何不一致均为显式错误。

### G2：附件回滚重发状态机

实施：新增 `requeue_target_and_delete_later` 原子操作；rollback response 返回目标消息附件 DTO；前端只用响应恢复，不再信任 DOM 中的旧 ID。

测试：文档、图片、Event/Todo/Reminder；一条消息多附件；回滚后重发；目标之后还有多条附件消息；重复回滚；跨会话。

验收：回滚后目标附件为 active pending，后来附件为 deleted；重发后同一 ID 重新绑定新 message_index，Agent 再次收到相同文本/图片上下文。

### G3：Reminder recurrence command scope

实施：扩展 application/view/command service 的 patch/delete 合同；实现 attach recurrence、all、single override、this-and-future split；返回新的 source_version 和 definition。

测试：

- 单次转有限/无限重复；重复转单次；修改 RRULE；
- single/all/this_and_future × title/content/priority/time；
- all 改时刻允许、改日期拒绝；
- COUNT/UNTIL/无限系列 split；已有 occurrence state 的迁移；
- 版本冲突 409、无效 ref 404/400、事务失败零部分写入。

验收：固定窗口 occurrence 集与期望完全一致，父子 lineage/COUNT 正确，所有写入只有 application service 一条路径。

### G4：Reminder 前端统一引用与刷新

实施：

1. `planner-v2-client` 增加 Reminder patch/delete scope 方法。
2. 侧栏 normalized 模式按筛选窗口读取 occurrences，并和 definitions 合并；每行保留 occurrence_ref、definition、series_id。
3. all 编辑从 definition 发起；single/future 从选中的 occurrence_ref 发起。
4. 移除硬编码“尚未开放”分支。
5. 写成功后只调用一个 `refreshReminderViews`：先刷新 definitions/侧栏 occurrences，再 await 日历事件源 refetch；去除并发空数组降级。
6. 详情弹窗始终读取本次 occurrence payload，不从另一份 master cache 拼旧值。
7. FullCalendar 相同窗口的并发读取共享同一个 Promise，不再用 `successCallback([])` 跳过重复请求；Reminder 侧栏渲染不再隐式触发第二次日历刷新。

测试：今天/周/月/季度/年筛选；single/recurring 类型；日历点击详情；侧栏点击详情；保存后标题、内容、时间、RRULE 在两处同步更新。

验收：相同 occurrence 在侧栏和日历的 title/content/time/status/source_version 一致；一次写操作只触发一次有效刷新。

### G5：静态资源与完整回归

实施：更新 `home.html` 中所有修改 JS 的 `?v=20260713-NNN`，执行 collectstatic；补充 Changelog 和验收报告。

测试：Django check、migration drift、全部 core/agent tests、JS syntax、git diff check、MoMoJee strict/parity、浏览器真实 UI smoke。

验收：自动化全绿；浏览器不再复现本方案第 1 节问题；Planner legacy JSON 零新增。

## 4. 数据与兼容策略

- 不改写已有 Reminder 业务数据；新增行为基于现有 normalized 表和 lineage 字段。
- 不迁移旧附件；现有已软删除附件保持原状态。新状态机只作用于升级后的回滚。
- legacy cohort 继续走旧 Reminder API；normalized cohort 只走 v2 application service。
- 不恢复 P4 前回滚历史；所有 rollback window 规则保持不变。

## 5. 完成定义

只有以下条件同时满足才算 P4-G 完成：

1. Event/Todo/Reminder/文件/图片附件首发和回滚重发均能进入模型上下文。
2. 前端不能在服务端附件创建失败时显示已发送磁贴。
3. 单次 Reminder 可转重复；重复 Reminder 的 single/all/this-and-future 编辑删除均可用。
4. Reminder 侧栏按 RRULE 展开 occurrence，且与中央日历一致。
5. 写后详情、编辑表单、侧栏、日历不存在新旧数据分叉。
6. 自动化、生产只读校验和浏览器验收全部通过，文档与 Changelog 完成。

## 6. 实施中追加问题

### 6.1 本地验收服务必须使用 ASGI

普通 Django HTTP `runserver` 在当前依赖组合下不会承接 Channels WebSocket，`/ws/agent/` 会被当作 HTTP GET 并返回 404。验收及部署必须使用 Daphne/其他 ASGI server 启动 `UniSchedulerSuper.asgi:application`。该问题不属于 Agent Consumer 业务回归，但会让整个 Agent 面板显示“已断开”。

### 6.2 新建日程短暂不显示

FullCalendar 初始化期间可能对同一窗口触发并发 event-source callback。旧去重逻辑让后到的调用立即 `successCallback([])`，空结果可能覆盖先到的有效结果；Reminder 的 `applyFilters()` 又会触发额外 refetch，扩大了竞态窗口。现改为相同窗口共享请求结果，并由显式的 `refreshReminderViews()` 统一刷新。MoMoJee 浏览器实测创建临时日程在 2.791 秒内完成写入、窗口查询和可见渲染，随后已通过 v2 application service 删除。
