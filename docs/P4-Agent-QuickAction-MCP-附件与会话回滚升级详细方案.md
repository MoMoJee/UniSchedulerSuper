# P4 Agent、Quick Action、MCP、附件与会话回滚升级详细方案

> 编制日期：2026-07-12  
> 前置条件：P1–P3 已完成，MoMoJee 已进入 normalized cohort。  
> 本文状态：实施基线。P4 的代码、迁移、测试和验收应按本文顺序执行。  
> 边界：P4 不切换 CalDAV、Feed/iCalendar；它们仍属于 P5。

实施进度：P4-0、P4-A、P4-B、P4-C、P4-D、P4-E、P4-F 已于 2026-07-12 全部验收通过；阶段报告位于 `docs/P4验收报告/`。P4 已完成，可以进入 P5。

## 1. P4 的最终决策

### 1.1 Agent Tool、Quick Action、MCP 不再实现数据库操作

P4 不让这些入口调用 Django View，也不让它们通过 HTTP 回环调用 `/api/v2/...`，更不允许分别复制 ORM/RRule/分享关系逻辑。目标调用链为：

```text
Web V2 View ──────────────┐
WebSocket Agent Tool ─────┤
Quick Action ─────────────┼─> PlannerApplicationService
MCP stdio / HTTP ─────────┤       ├─> PlannerQueryService
Internal Attachment ──────┘       ├─> PlannerCommandService
                                  ├─> PlannerSnapshotService
                                  └─> rollout / permission / cache / audit
```

各入口只负责自己的协议工作：认证、参数解析、LLM 友好输出、HTTP/MCP/WebSocket 响应。所有业务事实、权限、版本锁、重复规则、scope、分享关系和事务由同一应用服务处理。

具体约束：

1. `unified_planner_tools.py` 保留工具名称和 LLM 参数契约，但改成薄适配器。
2. `planner_tools.py` 旧工具在兼容期委托同一应用服务，不再调用旧 `EventService/TodoService/ReminderService` 的 JSON 实现。
3. Quick Action 继续复用同一组 unified tools，但必须逐个工具调用透传真实 `tool_call_id` 和 source。
4. `mcp_server.py` 的 stdio、streamable HTTP 仍可复用 unified tools，但必须构造相同的执行上下文；两种 transport 不允许出现不同业务实现。
5. V2 View 与工具不会互相调用；二者共同依赖应用服务，避免 HTTP 循环、伪造 Request 和错误码/异常语义漂移。

### 1.2 保留快照恢复，但不再保存整包 UserData 历史

P4 保留“操作前快照→恢复快照”的原理，不采用需要推导复杂逆操作的 undo command，也不引入长事务或事务型历史数据库。

新的快照是**本命令受影响 Planner 聚合的 before-snapshot**：例如修改一个重复实例，只保存对应 event、series、目标 override 及相关稀疏关系；split series 保存父/子系列边界和本次实际涉及的关系。它不会保存用户全部 events/todos/reminders JSON。

快照采用规范化 JSON 后压缩到 `BinaryField`，只在当前有效会话回滚窗口内存在。用户切换会话或创建新会话时，旧窗口立即关闭，其临时快照可立即物理删除；`PlannerChangeSet` 只保留很小的审计摘要、对象 ID、版本和 hash。

这仍是快照恢复：回滚器依据 before-snapshot 恢复业务状态，不计算“把这条规则反向修改回去”的逆操作。

### 1.3 旧回滚历史不迁移

P4 cutover 以前的 `AgentTransaction`、与旧 Agent rollback 关联的 reversion 历史，以及旧 `UserData` 版本历史不转成新快照，按停机清理流程直接删除。

前端不显示“旧版本不可回滚”的兼容提示。若用户或旧客户端直接请求回滚旧消息，后端返回：

```json
{
  "code": "rollback_legacy_unsupported",
  "message": "该操作不属于当前可回滚窗口"
}
```

建议 HTTP 状态为 `410 Gone`。P4 之后新产生、且属于当前有效回滚窗口的操作才允许执行回滚。

## 2. 当前代码与存储审计

### 2.1 当前调用问题

- `agent_service/tools/unified_planner_tools.py` 通过旧 `EventService/TodoService/ReminderService` 读取、修改整份 JSON，并自行解析重复 scope。
- `search_items` 只能缓存普通 UUID，不能稳定区分同一 series 的不同虚拟 occurrence。
- conflict analyzer 再次读取并自行筛选 events，未复用 P3 occurrence query。
- Quick Action 以 `task_id` 充当 thread/session，但循环执行工具时没有把每个 LLM `tool_call_id` 放入 RunnableConfig。
- MCP stdio/HTTP 复用 unified tool 是正确方向，但当前复用的是 legacy service，因此只是把重复数据库逻辑间接暴露出去。
- `InternalElementParser` 仍通过 legacy UserData 按 ID 遍历，不能表达 occurrence ref。

### 2.2 当前回滚问题

项目同时存在两套同名模型：

- `core.AgentTransaction`：一对一关联 `Revision`；旧 `core/views_rollback.py` 使用。
- `agent_service.AgentTransaction`：保存裸 `revision_id`；当前 Agent API 使用。

`@agent_transaction` 在工具执行前将六个完整 UserData key 加入 reversion，然后在 reversion 块之外执行真正的业务写入。它存在以下问题：

1. 每次只改一条日程，也可能重复保存用户全部 events 和 recurrence JSON。
2. 快照创建、业务写入和 AgentTransaction 记录不在同一 `transaction.atomic()` 中。
3. `revision_id` 通过“查询用户最新 Revision”取得，存在并发串号风险。
4. 前端通过 `localStorage rollback_base_<session>` 限制回滚，后端没有等强度的 rollback window 校验。
5. 两套 `/api/agent/rollback` 实现的字段、模型和恢复算法不一致。

### 2.3 生产数据库只读统计（2026-07-12）

| 项目 | 当前值 |
|---|---:|
| `db.sqlite3` 文件 | 2,423,267,328 bytes |
| `reversion_revision` | 17,252 行 |
| `reversion_version` | 44,714 行 |
| `serialized_data` 总长度 | 2,357,939,142 bytes |
| 其中 `core.UserData` version | 40,811 行 / 2,356,328,928 bytes |
| `Before: ...` Agent revision | 1,979 revisions / 22,512 versions / 951,259,970 bytes |
| `agent_service.AgentTransaction` | 2,041 行 |
| `core.AgentTransaction` | 34 行 |
| 当前 `PlannerChangeSet` | 24 行，before/after 合计约 8 KB |

最大单条 `UserData.events` version 已达到约 1.34 MB。删除 Version 行后 SQLite 文件不会自动缩小，生产清理必须包含安全的数据库重建/压缩步骤。

## 3. P4 目标架构

### 3.1 统一执行上下文

新增不可变 `PlannerExecutionContext`，由所有协议入口构造：

```python
@dataclass(frozen=True)
class PlannerExecutionContext:
    user: User
    source: Literal[
        "web_v2", "websocket_agent", "quick_action",
        "mcp_stdio", "mcp_http", "internal_attachment"
    ]
    entrypoint: str
    session_id: str = ""
    tool_call_id: str = ""
    request_id: str = ""
    message_index: int | None = None
    rollback_window_id: str = ""
    reversible: bool = False
```

所有字段由可信入口生成，不接受 LLM 在普通工具参数中自行填写 `user/session/source/reversible`。

### 3.2 PlannerApplicationService

应用服务提供面向调用面的用例，而不是 HTTP handler：

```text
search_items(context, filters, range, cursor)
get_item(context, occurrence_ref/entity_ref)
create_item(context, item_type, payload)
patch_item(context, ref, scope, payload, expected_version, override_policy)
delete_item(context, ref, scope, expected_version, override_policy)
complete_todo(context, ref, expected_version)
convert_todo_to_event(context, ref, payload, expected_version)
act_on_reminder_occurrence(context, ref, action, expected_version)
list_groups(context)
list_share_groups(context)
check_conflicts(context, range, candidate)
```

职责：

1. 用 rollout policy 校验对应 entrypoint；normalized 用户绝不回落写 legacy JSON。
2. 调用 P3 已有 query/command，不重复 ORM 操作和 recurrence 推算。
3. 写操作统一执行权限、expected version、scope、override policy、审计和 cache invalidation。
4. Web V2 只把领域异常映射成 HTTP；Agent/Quick Action/MCP 只把同一异常映射成协议友好文本/结构。
5. legacy cohort 暂由显式 `LegacyPlannerApplicationAdapter` 兼容，直至 P6；适配器是唯一允许进入 legacy repository 的工具路径。

### 3.3 occurrence ref 与 `#N` cache

缓存项升级为：

```json
{
  "type": "event",
  "entity_id": "event-id",
  "series_id": "series-id",
  "recurrence_id": "20260713T020000Z",
  "source_version": 7,
  "title": "测试",
  "owner_id": 1
}
```

规则：

- `#N` 解析必须同时验证 user、session、type 和版本。
- occurrence 搜索必须带有限窗口；默认窗口固定为过去 30 天到未来 90 天，并在工具输出中说明。
- recurrence occurrence 的 update/delete 必须显式 scope；未指定就返回澄清错误，不能猜 all。
- 写成功后清除或更新涉及 ref；回滚后清空当前 session cache。
- MCP 固定 cache session 可以保留，但 key 必须包含 user 和 transport session，禁止跨用户复用。

## 4. 新会话回滚窗口

### 4.1 必须保持的产品语义

1. 只允许回滚用户进入当前 Agent 会话后新发送的消息所触发的 Planner 操作。
2. 用户切换到其他历史会话时，离开的会话之前所有操作永久失去回滚资格。
3. 用户再切回该会话时，以当前消息末尾建立新的 rollback floor；早期消息不会重新变成可回滚。
4. 创建新会话会关闭旧会话窗口，新会话从消息 0 开始新窗口。
5. 页面刷新不等于切换会话，不应无故关闭当前窗口。
6. 后端是最终权限判断者；前端基准索引只能用于显示，不能作为安全边界。

### 4.2 数据模型

新增 `AgentRollbackWindow`：

| 字段 | 用途 |
|---|---|
| `window_id` | UUID public ID |
| `user/session` | 强归属关系 |
| `generation` | 每次重新进入会话递增 |
| `floor_message_index` | 此索引之前一律不可回滚 |
| `status` | active/closed |
| `opened_at/closed_at` | 生命周期 |
| `activation_token` | 前端实际切换操作的幂等 token |

同一 user/session 只允许一个 active window。切换接口在一个事务里关闭旧窗口并创建新 generation。

统一 `agent_service.AgentTransaction`，新增：

- `change_set` FK；
- `rollback_window` FK；
- `tool_call_id` 独立唯一字段，不再只藏 metadata；
- `message_index`、`source`、`state`；
- 移除 `revision_id` 依赖。

`core.AgentTransaction` 停用并删除，`core/views_rollback.py` 旧入口移除或固定返回 `410 rollback_legacy_unsupported`。

### 4.3 快照与审计分离

保留 `PlannerChangeSet` 作为长期小型审计记录，只存：

- user/source/session/tool_call/command；
- 受影响 public IDs；
- before/after version 与 canonical hash；
- rollback 状态和时间；
- collection token。

新增一对一 `PlannerRollbackSnapshot`，只为 `reversible=True` 的 WebSocket Agent command 创建：

| 字段 | 用途 |
|---|---|
| `change_set` | 所属命令 |
| `schema_version` | 快照反序列化版本 |
| `codec` | `zlib-json-v1`，不依赖外部服务 |
| `payload` | 压缩后的 before-snapshot BinaryField |
| `payload_sha256` | 完整性验证 |
| `uncompressed_size` | 审计和限额 |
| `expires_at` | 窗口关闭/过期清理 |

长期 audit 与临时恢复 payload 分表后，关闭窗口可以删除大字段而不丢失操作摘要。

### 4.4 快照范围

快照服务使用模型白名单和稳定 public ID，不序列化任意 Django model：

| 命令 | before-snapshot 最小范围 |
|---|---|
| event create | `exists=false` 标记；创建后对象摘要 |
| event patch/delete all | event、series、EXDATE/RDATE、overrides、split review、tags、reminder/share links |
| event single | event/series 标识、目标 recurrence override 或“不存在”标记 |
| event this-and-future | 父 aggregate、边界后的 sparse rows、将创建的 child absence marker |
| todo CRUD/convert | todo、dependency、tag、reminder links；转换 event absence marker |
| reminder master | reminder、series、EXDATE、occurrence states、links |
| reminder occurrence action | master 标识和目标 `ReminderOccurrenceState` |
| group/relation mutation | 目标 group 与实际改变的 relation rows |

即使一个 series 有许多稀疏 override，也只保存该 aggregate；不保存用户其他日程，更不展开正常 recurrence occurrence。

### 4.5 写命令流程

每个可回滚 Planner command 在同一个 `transaction.atomic()` 内：

1. 校验 execution context、active rollback window、message/tool call 归属。
2. `select_for_update()` 锁定 aggregate 与 collection version。
3. 生成 mutation plan 和 SnapshotSpec。
4. 序列化并压缩 before-snapshot，计算 hash。
5. 执行 P3 command、关系修改、CalendarChange 和 cache invalidation 标记。
6. 记录 after versions/hash、PlannerChangeSet、AgentTransaction 和 snapshot。
7. 一起 commit；任一步失败则快照、业务写入和事务记录全部回滚。

不允许装饰器在业务函数外部猜测“用户最新 revision”。

### 4.6 回滚流程

`POST /api/agent/rollback/to-message/` 改由 `PlannerRollbackCoordinator` 执行：

1. 校验 user/session、当前 active window 和 `message_index >= floor_message_index`。
2. 只收集该窗口、该消息以后、未回滚且具有新 snapshot schema 的 tool calls。
3. 按最新到最旧排序，并在写事务开始前完成全量 preflight。
4. 锁定所有受影响 aggregate；比较当前 hash/version 与每条 changeset 的 after 链。
5. 若存在来自 Web、MCP、Quick Action 或其他会话的后续修改，整体返回 `409 rollback_conflict`，不覆盖新数据、不做部分恢复。
6. 在一个数据库事务中按逆时间顺序恢复 before-snapshot 的业务字段/关系。业务状态恢复，但技术 version 和 collection token继续单调递增，不能倒退 ETag。
7. created-before-absent 的对象恢复为业务不可见状态；优先软删除，避免破坏已产生的外键审计。
8. 写 rollback ChangeSet，标记原事务 rolled_back，清 session cache。
9. 软删除目标消息之后的 SessionAttachment，恢复 SessionTodo/summary/token snapshot 的对应会话状态。
10. 截断 LangGraph 消息/checkpoint；成功后 finalize。若独立 checkpointer 写入失败，记录可重试的 coordinator 状态并保留 snapshot，不重复恢复 Planner 数据。

回滚是幂等的：相同 rollback request 重试只完成未 finalize 的步骤。

### 4.7 Quick Action 与 MCP 的回滚边界

Quick Action 和 MCP 没有“当前浏览器 Agent 对话消息”的可靠语义，因此 P4 中：

- 它们必须写 PlannerChangeSet 审计，但默认 `reversible=False`，不创建临时 rollback snapshot。
- 它们的操作不能被 `/api/agent/rollback/to-message/` 回滚。
- Quick Action 的 `task_id/tool_call_id` 和 MCP 的 transport session/request ID 仍须完整透传，以支持审计、幂等和冲突定位。
- 未来若要给 Quick Action 增加独立任务回滚，应建立单独的 task rollback window，不能冒充聊天 session；这不属于本次 P4。

这样既保留用户指定的聊天会话回滚逻辑，也不会让外部 MCP 客户端获得跨会话恢复权限。

## 5. Agent、Quick Action、MCP 具体改造

### 5.1 Unified tools

- `search_items` 使用统一 search/query，支持 event/todo/reminder、共享权限和 recurrence occurrence。
- `create_item/update_item/delete_item/complete_todo` 只组装 command DTO。
- `future` 映射为 `this_and_future`；必须显式提供 override policy。
- 删除工具内对 `EventService.bulk_edit()`、旧 RRule parser 结果批量写 JSON 的调用。
- 结果统一返回 public ID/ref/version；LLM 文本由 presenter 生成。

### 5.2 WebSocket Agent

- Consumer/ToolNode 为每次调用注入 user、session、message index、tool_call_id、rollback window。
- 同一用户消息内多个 tool call 各有独立 snapshot；回滚消息时按 reverse order 一次性恢复。
- mutation 成功事件携带 `planner_changed=true` 和 collection token，前端据此刷新日历/待办/提醒。

### 5.3 Quick Action

- 修复当前 config 仅包含 task ID、缺少真实 tool_call_id 的问题。
- 每次循环为具体 tool call 创建新的 execution context。
- 多工具任务可以逐命令 commit；任务取消只阻止尚未开始的 command，不假装回滚已经成功的命令。
- 任务结果记录 public ref 和 changeset ID，不存整个业务对象快照。

### 5.4 MCP stdio/HTTP

- 两种 transport 使用同一 context factory 和 application service。
- stdio 从启动 token 绑定 user；HTTP 每个 request 验证 Bearer/Token，禁止退回全局 stdio user。
- 不接受参数中的 user ID 覆盖认证 user。
- MCP search 返回可复用的结构化 ref；write 必须携带 ref/scope/version。
- 无效 token、跨用户 ref、过期 cache、版本冲突分别返回稳定 MCP error code。

### 5.5 Group、share 与 conflict

- event group/share group 查询使用 normalized repository 和 membership join。
- conflict analyzer 复用同一时间窗 occurrence query，不再读取全部 legacy events 后本地展开。
- shared event 只读 ref 在 Agent/MCP 中也必须拒绝写入。

## 6. 内部附件升级

`InternalElementParser` 改用：

```text
get_internal_item(context, type, entity_ref/occurrence_ref)
list_attachable_items(context, type, query, range, cursor)
```

要求：

1. event occurrence 附件同时保存 master、series、recurrence ID、effective 时间和 override 状态。
2. `SessionAttachment.internal_snapshot` 在发送消息时冻结；源对象后续修改、删除或 series split 不改变历史消息。
3. internal reference 用于权限检查和“查看当前对象”，snapshot 用于历史展示，两者不可混用。
4. rollback 删除消息时继续软删除相应 attachment；恢复未 finalize 的 rollback 时必须幂等。
5. 附件列表查询有窗口、分页和 owner 权限，不遍历整个 UserData。

## 7. 旧回滚历史清理与生产迁移

### 7.1 新增管理命令

```powershell
.venv\Scripts\python.exe manage.py audit_planner_rollback_storage --output logs/p4-rollback-storage-before.json
.venv\Scripts\python.exe manage.py cleanup_legacy_planner_rollback --dry-run --output logs/p4-rollback-cleanup-dry-run.json
.venv\Scripts\python.exe manage.py cleanup_legacy_planner_rollback --apply --cutover <ISO8601> --output logs/p4-rollback-cleanup-apply.json
.venv\Scripts\python.exe manage.py verify_planner_rollback_storage --strict --output logs/p4-rollback-storage-after.json
```

清理命令必须按 ID 集合删除，不能用模糊 comment 作为唯一依据。清理范围：

1. 两套旧 AgentTransaction 全部历史行。
2. 它们引用的 Revision/Version。
3. cutover 前所有 `core.UserData` reversion Version；当前 UserData 业务行不删除。
4. cutover 前仅用于旧 Planner rollback 的 normalized model Version。
5. 删除失去全部 Version 的 orphan Revision。
6. P3 migration/cohort 报告、业务 normalized rows、PlannerLegacyIdMap 和验证日志不删除。

### 7.2 停机发布顺序

该项目允许完全停机，因此采用简单、可验证的发布：

1. 停止 Web、ASGI、Quick Action worker、MCP server、提醒 worker 和 CalDAV 写入口。
2. 复制数据库并计算 SHA256；确认备份可独立打开。
3. 执行 `PRAGMA integrity_check`、`PRAGMA foreign_key_check` 和 P1–P3 strict/parity 基线。
4. `migrate --plan`，再执行 schema migration。
5. 部署 P4，但先关闭 Planner Agent mutation flag；执行隔离账号和 MoMoJee 只读 smoke。
6. 开启一个测试账号的 P4 mutation，跑完整 Agent/Quick Action/MCP/rollback 矩阵。
7. 开启 MoMoJee P4 Agent entrypoint；确认不再产生 legacy UserData Version。
8. 执行 rollback cleanup dry-run，人工核对数量/字节/ID 范围。
9. 执行 cleanup apply。
10. 使用 `VACUUM INTO` 生成新的压缩数据库文件，而不是在唯一生产文件上直接冒险；对新文件重新执行 integrity/foreign-key/count/checksum 验证后再停机替换。
11. 启动服务，完成浏览器、Quick Action、MCP stdio/HTTP smoke。

仅执行 DELETE 不会减小 SQLite 文件，因此第 10 步是释放磁盘空间的必要步骤。执行 `VACUUM INTO` 前应确认有足够空间同时容纳旧库、备份和新库。

### 7.3 失败回退

- cleanup 前发现问题：关闭 P4 Agent mutation，修复代码后重试；normalized 用户不得回落写 legacy JSON。
- cleanup 后发现问题：停机并恢复 P4 前数据库备份，而不是尝试重建已删除的旧 Revision。
- P4 上线后单个 Planner tool 异常：禁用 planner tool category，保留普通聊天和只读工具。
- 旧回滚历史一旦清理，不提供兼容恢复接口；这是本方案明确接受的 cutover 行为。

## 8. 分阶段实施步骤、测试和验收

### P4-0：基线审计与契约冻结

实施：

1. 固化 unified tools、Quick Action、MCP 和 rollback 的当前工具名/参数/错误输出。
2. 生成 direct UserData/reversion/AgentTransaction/附件 parser 调用面报告。
3. 加入 rollback storage 审计命令，只读输出数量和估算字节。

测试：现有 Agent/Quick Action/MCP smoke；审计命令对测试库可重复、零写入。

验收：列出所有 Planner 入口；不存在未归类的工具或 rollback URL；生产审计数字写入日志。

### P4-A：Execution Context 与 Application Service

实施：

1. 新增 context、application service、DTO、presenter 和稳定异常码。
2. 将 V2 View 逐步改为调用 application service，证明它不是 Agent 专用旁路。
3. 完成 normalized/legacy backend policy；normalized 禁止 legacy fallback。

测试：同一 command 经 Web adapter 和直接 service 的领域结果一致；跨用户、错误 entrypoint、stale version 全部拒绝且零写入。

验收：应用服务是唯一 use-case 层；不接受 MockRequest，不调用 View。

### P4-B：压缩快照与回滚内核

实施：

1. 新增 rollback window/snapshot 模型，统一 AgentTransaction。
2. 建立 allowlist serializer、压缩/checksum、restore 和 conflict preflight。
3. command 在同一原子事务中写业务、ChangeSet、AgentTransaction 和 snapshot。
4. 实现 coordinator 幂等状态机和 cache/attachment/session side effects。

测试：创建 series、single override、all shift、future split、delete、todo 转 event、reminder snooze/complete、share relation 分别回滚；故障注入验证任一步失败零部分写入。

验收：恢复后的业务投影与操作前一致；version/token 单调；并发后续写导致 409 而非覆盖。

### P4-C：Agent Tool 与 cache/conflict 切换

实施：替换 unified/legacy planner tools、identifier resolver、cache manager、group/share service、conflict analyzer。

测试：默认和自定义时间窗、无限 recurrence、`#N` occurrence ref、single/all/future、只读共享、缓存失效、跨 session/user。

验收：normalized Agent 路径零 legacy UserData 读写；工具内无 ORM/RRule 写算法。

### P4-D：Quick Action 与 MCP 切换

实施：修复 per-tool `tool_call_id`；stdio/HTTP context/auth；统一 error/result mapper。

测试：Quick Action 多工具/取消/超时；MCP 两种 transport 的 search/create/update/delete、recurrence ref、无效 token、跨用户、版本冲突。

验收：三入口产生相同领域结果；Quick Action/MCP 不创建聊天 rollback snapshot。

### P4-E：附件与前端回滚窗口

实施：internal parser/query 切换；新增 window rotate/close API；history 响应由服务端返回 floor/can_rollback；前端 localStorage 降为显示缓存。

测试：切走后旧消息 API 直接回滚返回 410；切回不恢复资格；刷新保留当前窗口；旧附件 snapshot 稳定；源删除后仍可读历史附件。

验收：UI 与直接 API 权限一致；不存在只靠隐藏按钮保护的旧操作。

### P4-F：历史清理、压缩与生产验收

实施：按第 7 节停机流程执行；保存 before/dry-run/apply/after 四类报告和数据库 SHA256。

测试：新库 integrity/foreign key；P1–P3 78 项回归；P4 全矩阵；MoMoJee strict/parity；切换前后业务实体/occurrence checksum 一致。

验收：旧 rollback 请求统一 410；新窗口回滚可用；数据库显著缩小；新 Agent 操作不再增长 UserData reversion Version。

## 9. P4 测试矩阵

| 范围 | 必测场景 | 验收断言 |
|---|---|---|
| Application service | Web/Agent/QA/MCP 同一 create/patch/delete | 领域结果、版本和 ChangeSet 一致 |
| Search | event/todo/reminder、共享、无限系列、跨窗口 | 有限展开，ref 完整，读取零增长 |
| Scope | single/all/this-and-future × finite/unbounded | 与 P3 API 语义完全一致 |
| Cache | `#N`、过期版本、删除、rollback、跨 user/session | 错误引用被拒绝，不串用户 |
| Agent | 一条消息多个工具、失败重试、stop | tool_call 精确记录，成功命令可按消息回滚 |
| Quick Action | 多轮工具、取消、超时、重复 task | 不复制业务实现，审计/幂等正确 |
| MCP | stdio/HTTP、无效 token、跨用户 ref | 同一 service，认证 user 不可覆盖 |
| Rollback window | 新会话、切换、切回、刷新、双请求 | floor 由服务端执行，旧操作永久失效 |
| Snapshot | create/absence、复杂 split、relations、state | 操作前投影恢复，hash 正确 |
| Conflict | 回滚前被 Web/MCP 再修改 | 409 且零部分恢复 |
| Attachments | master/occurrence、删除源、rollback message | immutable snapshot 始终可读 |
| Storage | 100 次小修改、10 次复杂 split、关闭窗口 | 增量与受影响 aggregate 成正比；关闭后 payload 删除 |
| Cleanup | dry-run/apply/重复 apply/VACUUM INTO | 幂等、业务 checksum 不变、磁盘空间释放 |

建议增加至少以下测试模块：

```text
agent_service/tests/test_planner_application_service.py
agent_service/tests/test_planner_tool_contract.py
agent_service/tests/test_quick_action_planner.py
agent_service/tests/test_mcp_planner_stdio.py
agent_service/tests/test_mcp_planner_http.py
agent_service/tests/test_agent_rollback_window.py
agent_service/tests/test_planner_snapshot_restore.py
agent_service/tests/test_internal_attachment_parser.py
core/tests/test_planner_rollback_cleanup.py
tests/js/agent-rollback-window.test.js
```

## 10. 预计文件改动

新增或重点修改：

```text
core/planner/application.py
core/planner/context.py
core/planner/snapshots.py
core/planner/rollback.py
core/planner/commands.py
core/planner/entities.py
core/models.py
agent_service/models.py
agent_service/utils.py
agent_service/tools/unified_planner_tools.py
agent_service/tools/planner_tools.py
agent_service/tools/cache_manager.py
agent_service/tools/identifier_resolver.py
agent_service/tools/conflict_analyzer.py
agent_service/tools/event_group_service.py
agent_service/tools/share_group_service.py
agent_service/quick_action_agent.py
agent_service/consumers.py
agent_service/views_api.py
agent_service/parsers/internal_parser.py
mcp_server.py
core/static/js/agent-chat.js
core/management/commands/audit_planner_rollback_storage.py
core/management/commands/cleanup_legacy_planner_rollback.py
core/management/commands/verify_planner_rollback_storage.py
```

旧 `core/views_rollback.py`、`core.AgentTransaction` 和旧 service 的 Planner JSON 写逻辑在完成 compatibility 清点后移除；不能同时保留两个可工作的 rollback engine。

## 11. P4 完成定义

只有同时满足以下条件才进入 P5：

1. WebSocket Agent、Quick Action、MCP stdio/HTTP、conflict、cache、group/share、internal attachment 全部只走 Planner application/query/command。
2. normalized 用户通过上述入口零 legacy Planner UserData 读写；没有伪造 Request、调用 View 或工具自写 ORM/RRule。
3. single/all/this-and-future、Todo、Reminder occurrence 和复杂 relation 的 snapshot rollback 全矩阵通过。
4. 会话切换规则由后端 rollback window 强制执行；旧历史和非当前窗口请求稳定返回 410。
5. Quick Action/MCP 审计完整，但不能借用聊天回滚权限。
6. 旧 rollback 历史已按批准范围清理，数据库经过安全压缩和完整性复验，业务 checksum/parity 零差异。
7. 新快照大小只与本命令受影响 aggregate 有关，关闭回滚窗口后临时 payload 被删除。
8. P1–P3 全量回归、P4 自动化和真实入口 smoke 全部通过，文档与 Changelog 完成。

## 12. 对原总体方案的修订说明

《核心日程正规化与 RRule 引擎升级方案》7.4 中“对新模型使用 reversion 粒度版本”的方向，经当前生产库容量审计后由本文细化并修订：

- 继续使用操作前快照恢复的产品原理；
- 不再依赖 django-reversion 为每次 Agent Planner 操作持久保存模型历史链；
- 使用受影响聚合的、schema-versioned、压缩且随 rollback window 到期删除的 before-snapshot；
- PlannerChangeSet 保留轻量审计，snapshot 承担短期恢复，两者分离。

本文是 P4 实施时更具体且优先的规范。P5 的 CalDAV/Feed 历史处理不得提前混入 P4。

## 13. 实施完成补充：rollback window 服务端兜底

P4-F 后的真实 UI 验证暴露出：若浏览器仍运行升级前静态资源，前端不会调用新增的 window rotate API，所有回滚都会因缺少 active window 返回 410。为消除前端版本对权限正确性的依赖，最终实现增加以下约束：

1. WebSocket 建连必须先可靠取得当前消息数，再由服务端 `ensure_active` 补建或复用窗口；读取失败时拒绝建立 floor=0 的不安全窗口。
2. history API 同样补建缺失窗口，floor 固定为请求当时的消息末尾；升级前/切换前消息不会因此重新获得权限。
3. 同一会话刷新只复用当前 generation；切到其他会话仍通过 rotate 关闭原窗口并销毁 snapshot。
4. 普通对话消息的回滚不要求存在 Planner transaction；Planner snapshot 只负责恢复实际发生的日程副作用。
5. 客户端 rotate 保留为主动生命周期信号，但不再是系统正确性的唯一条件。

最终 `core.tests + agent_service.tests` 124/124 通过，生产库 storage strict 通过；P4-0 至 P4-F 完成定义不变且全部满足。
