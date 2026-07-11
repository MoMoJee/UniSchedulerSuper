# UserData 拆表数据库升级方案

> 目标：将 `core.UserData` 中的核心业务大 JSON 拆成可查询、可索引、可回滚、可维护的正规 Django ORM 表，同时保留必要的配置型 JSON 存储。  
> 状态：调研完成，待进入实现阶段。  
> 最后更新：2026-06-16

---

## 1. 背景与目标

当前项目的核心业务数据主要存储在 `core_userdata(user_id, key, value)` 中，`value` 是 JSON 文本。该模式支持早期快速迭代，但现在已经成为性能、并发、回滚和管理的主要瓶颈。

本次升级目标：

1. 将 `events`、`todos`、`reminders`、`events_groups`、RRule 存储等核心业务实体拆成正规表。
2. 将配置型、小体量、弱查询需求的数据迁移到独立 OneToOne JSONField 配置表，而不是继续放在大杂烩 `UserData` 中。
3. 统一所有读写入口，避免视图层、Agent 工具、CalDAV、MCP、订阅 Feed 各自直接解析 JSON。
4. 降低 SQLite 写放大和 `reversion_version` 膨胀，提升查询、筛选、同步和管理能力。
5. 为后续 PostgreSQL / MySQL 切换留出结构基础。

非目标：

1. 不在第一阶段重写全部前端协议。
2. 不一次性删除 `UserData`，必须经过兼容层、双读校验、备份和灰度切换。
3. 不迁移或暴露任何 API Key 明文。
4. 不把 LangGraph checkpoint 库合并进主库。

---

## 2. 必须遵守的开发规范

实施前必须先阅读并遵守：

| 规范 | 约束 |
|---|---|
| `AGENT.md` | 所有 `UserData` 写操作必须有 `reversion.create_revision()`；日志统一 `from logger import logger`；Agent 工具第一参数必须是 `config: RunnableConfig` |
| `docs/后端开发规范/index.md` | 后端任务总规范入口 |
| `docs/后端开发规范/数据模型规范.md` | 业务 ID 使用 UUID 字符串；新增 ORM 模型需注册 admin |
| `docs/后端开发规范/服务层规范.md` | Agent Tools 调用 `core/services/`，写操作必须可追踪 |
| `docs/后端开发规范/API接口规范.md` | 新接口使用 `/api/` 前缀，旧接口保持兼容 |
| `docs/后端开发规范/Agent服务规范.md` | 写工具必须使用 `@agent_transaction`，支持回滚 |
| `docs/后端开发规范/日志与错误处理规范.md` | 数据变更、CalDAV PUT/DELETE、Agent 操作必须记录日志，禁止记录密钥 |

本次升级新增约束：

1. 所有核心业务读写必须收敛到服务层或 repository 层，不允许新增直接 `UserData.objects.get(...).value` 调用。
2. 拆表后所有写操作必须处于 `transaction.atomic()` 内；需要回滚的业务同时进入 `reversion`。
3. 迁移期间必须保留可重复执行的数据校验命令，任何阶段不能只靠人工页面验证。
4. 迁移期间所有新模型必须保留旧 UUID 业务 ID 字段，禁止把自增主键暴露给前端或 CalDAV/MCP/Agent。
5. 配置型数据允许 JSONField，但必须从 `core_userdata` 移入命名明确的配置表。

---

## 3. 当前数据库现状

### 3.1 数据库文件

| 数据库 | 路径 | 用途 | 当前规模 |
|---|---|---|---:|
| 主库 | `db.sqlite3` | Django ORM、业务数据、reversion、Agent 元数据、文件元数据 | 约 967.5 MB |
| LangGraph checkpoint | `agent_service/checkpoints/agent_checkpoints.sqlite` | Agent 对话状态 checkpoint | 约 96.5 MB |
| 媒体文件 | `media/` | 上传文件、聊天附件、缩略图 | 文件系统 |

### 3.2 `core_userdata` 总体现状

| 指标 | 当前值 |
|---|---:|
| 总行数 | 251 |
| distinct key | 18 |
| distinct user_id | 32 |
| 无效 JSON | 0 |
| `(user,key)` 唯一约束 | 无 |
| 已发现重复 `(user,key)` | `ai_chatting` user 1 有 3 行；`reminders` user 44 有 2 行 |
| 未定义在 `DATA_SCHEMA` 的 key | `resources`, `test_1` |

### 3.3 当前 key 清单

| key | 实际行数 | 存量/形态 | 用途 | 处理建议 |
|---|---:|---:|---|---|
| `events` | 32 | 2444 个 event；单行最大约 1.18 MB | 核心日程 | 第一优先级拆表 |
| `events_groups` | 29 | 97 个 group | 个人日程组 | 与 events 同步拆表 |
| `events_rrule_series` | 7 | 122 个 segment | 日程重复规则存储 | 并入事件 recurrence 表 |
| `reminders` | 21 | 188 个 reminder | 核心提醒 | 第二优先级拆表 |
| `rrule_series_storage` | 19 | 5 个 segment | 提醒重复规则存储 | 并入提醒 recurrence 表 |
| `todos` | 20 | 46 个 todo | 核心待办 | 第二优先级拆表 |
| `planner` | 28 | dialogue/temp_events 等混合状态 | 旧 Agent planner 状态 | 拆分或淘汰 |
| `agent_token_usage` | 5 | 月度累计和额度 | Agent 用量汇总 | 拆 quota，明细保留 `AgentUsageRecord` |
| `agent_config` | 5 | 当前模型、自定义模型、密钥密文 | Agent 模型配置 | 拆表或迁配置表 |
| `agent_optimization_config` | 2 | 参数配置 | Agent 上下文优化 | 配置 JSONField |
| `user_preference` | 21 | 用户业务偏好 | 偏好配置 | 配置 JSONField |
| `user_interface_settings` | 18 | UI 状态、过滤器、布局 | 前端状态 | 配置 JSONField |
| `user_settings` | 11 | 旧视图状态 | 疑似废弃 | 合并到 UI 设置后清理 |
| `outport_calendar_data` | 1 | 已导出 UUID 和时间 | 导出状态 | 可保留配置表，未来多设备再拆 |
| `ai_chatting` | 15 | token_balance/nickname | 旧 AI 余额/昵称 | 若涉及权益则拆账户表 |
| `setting` | 8 | 旧 AI setting code | 疑似废弃 | 迁入 agent_config 或清理 |
| `resources` | 8 | 固定 Auditorium 测试资源 | 测试数据 | 清理或改静态 demo |
| `test_1` | 1 | `{}` | 测试残留 | 清理 |

---

## 4. 当前 UserData 定义与使用方式

### 4.1 定义方式

`core/models.py` 中通过 `DATA_SCHEMA` 描述合法 key 和 JSON 结构。`UserData` 模型定义如下：

```python
class UserData(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    key = models.CharField(max_length=100)
    value = models.TextField()
```

读写方法：

| 方法 | 行为 | 迁移影响 |
|---|---|---|
| `UserData.get_or_initialize(request, new_key, data=None)` | 查询用户 key，不存在则按 `DATA_SCHEMA` 创建 JSON 默认值 | 需要替换为兼容 repository，不允许继续作为业务源头 |
| `UserData.get_value(check=False)` | `json.loads(value)`，可选 schema 校验 | 迁移期可作为 legacy fallback |
| `UserData.set_value(data, check=False)` | `json.dumps(data)` 后整包保存 | 拆表后核心业务禁止继续使用 |
| 直接 `UserData.objects.get(...).value` | 绕过 schema 与方法 | 必须逐个消除 |

### 4.2 实际使用模式

当前典型流程：

1. 按 `user + key` 取一行 `UserData`。
2. 把 `value` JSON 解析成 list/dict。
3. 在 Python 内存中查找、过滤、修改元素。
4. 把完整 list/dict 再序列化写回同一行。

该模式的问题：

1. 单个日程修改会重写整个 `events` JSON。
2. 无法对 `start/end/status/groupID/shared_to_groups` 建索引。
3. 并发写容易互相覆盖。
4. `django-reversion` 对大 JSON 行做快照，导致版本库快速膨胀。
5. 回滚只能按整包 JSON 回滚，无法表达单条事件级别的审计。
6. CalDAV、Agent、MCP、订阅 Feed 都直接或间接依赖该 JSON 结构，调用面分散。

---

## 5. 调用面审查结果

### 5.1 核心读写入口

| 模块 | 入口 | key | 读写类型 | 风险 |
|---|---|---|---|---|
| `core/views.py` | `home` | `user_preference`, `events_groups`, `planner`, `rrule_series_storage` | 读/初始化/部分写 | GET 会写初始化数据 |
| `core/views.py` | `user_preferences`, `user_settings` | `user_preference` | 读写 | GET 中包含旧字段自动迁移写回 |
| `core/views.py` | `change_view` | `user_interface_settings` | 写 | 前端全量 JSON 写入 |
| `core/views.py` | `create/update/delete_events_group` | `events_groups`, `events` | 写 | 删除分组可联动删除日程，无事务/无 reversion |
| `core/views.py` | `import_events` | `events_groups`, `events` | 读写 | 老导入入口 |
| `core/views.py` | `get_outport_calendar`, `check_modified_events` | `outport_calendar_data`, `events` | 读写 | 增量导出状态依赖旧 UUID |
| `core/views.py` | todo CRUD / convert | `todos`, `events` | 读写删 | convert 同时写两个 key |
| `core/views_events.py` | event CRUD / bulk edit | `events`, `events_groups`, `events_rrule_series`, `planner` | 读写删 | 重复事件逻辑复杂，部分写入未被 reversion 正确包裹 |
| `core/views_reminder.py` | reminder CRUD / bulk edit / status | `reminders`, `rrule_series_storage` | 读写删 | 读取接口可能自动生成实例并写回 |
| `core/views_calendar_subscription.py` | calendar feed | `events_groups`, `events`, `todos`, `reminders` | 只读 | ICS 输出字段必须兼容 |
| `core/views_share_groups.py` | share group events/sync | `events` | 读 | `shared_to_groups` 是共享同步核心字段 |
| `caldav_service/views/*` | CalDAV PROPFIND/REPORT/GET/PUT/DELETE | `events`, `events_groups`, `reminders`, `todos` | 读写删 | 独立于普通 HTTP API 的日程写入口 |
| `agent_service/tools/*` | unified planner tools / legacy planner tools | `events`, `todos`, `reminders`, RRule key, `events_groups` | 读写删 | WebSocket、Quick Action、MCP 共同入口 |
| `agent_service/views_config_api.py` | Agent 配置/Token 配额 | `agent_config`, `agent_optimization_config`, `agent_token_usage` | 读写 | 密钥必须继续加密保存 |
| `agent_service/context_optimizer.py` | 模型读取/用量统计 | `agent_config`, `agent_optimization_config`, `agent_token_usage` | 读写 | 并发累计可能丢增量 |
| `agent_service/parsers/internal_parser.py` | 附件内部元素解析 | `events`, `todos`, `reminders` | 读 | 附件快照依赖旧业务 ID |
| `integrated_reminder_manager.py` | RRule backend | `rrule_series_storage`, `events_rrule_series` | 读写删 | 与 events/reminders 强耦合 |
| `mcp_server.py` | MCP planner tools | `events`, `todos`, `reminders`, `events_groups` | 读写删 | 通过 unified planner tools 间接调用 |

### 5.2 高风险点

| 风险 | 文件/入口 | 说明 | 处理要求 |
|---|---|---|---|
| 读接口写数据 | `get_events_impl`, `get_reminders`, `home`, `user_settings(GET)` | 自动生成实例或迁移旧字段时写回 | 拆表后必须明确标注副作用，测试 GET 幂等性 |
| 批量重复规则操作 | `bulk_edit_events_impl`, `bulk_edit_reminders`, CalDAV recurring PUT/DELETE | 处理 single/all/future/from_time、EXDATE、UNTIL、detached | 迁移前必须补回归测试 |
| 回滚表双轨 | `core.AgentTransaction` 与 `agent_service.AgentTransaction` | 新 Agent 写新表，旧 core rollback 读旧表；路由可能冲突 | 阶段 P0 必须确认并修复入口归属 |
| checkpoint 清理不完整 | `clear_session_checkpoints()` | 实际表为 `writes`，代码尝试删除 `checkpoint_writes` | 与本迁移分开修，但需纳入前置风险 |
| 直接 `json.loads(value)` | 多个 views/service/tool | 绕过 `get_value()` 和 schema | 必须通过 repository 替换 |
| 无 `(user,key)` 唯一约束 | `core_userdata` | 已有重复 key | 迁移前先治理重复数据 |
| 配置和业务混杂 | `planner`, `agent_token_usage`, `agent_config` | 历史包袱和正式数据混在一起 | 按用途分流迁移 |

---

## 6. 拆表设计原则

1. 保留旧 UUID 字符串作为业务主标识，例如 `event_id`、`todo_id`、`reminder_id`、`group_id`。
2. Django 自增主键只作为内部 pk，不暴露给前端/CalDAV/Agent/MCP。
3. 对常用查询字段建索引：`user`、`start/end`、`status`、`group`、`series_id`、`updated_at`、`is_deleted`。
4. 对 list 字段优先拆关联表；低频扩展字段可暂放 `metadata JSONField`。
5. 支持软删除，至少对 event/todo/reminder 保留 `is_deleted/deleted_at`，方便回滚、同步和审计。
6. 所有写操作使用 `transaction.atomic()`，涉及 Agent 回滚时同时使用 `reversion.create_revision()`。
7. 迁移期间保留 legacy adapter，允许旧接口继续返回原 JSON 格式。
8. 先迁服务层，再迁视图层；Agent、Quick Action、MCP 共用服务层，收益最大。
9. CalDAV 写入口必须单独验收，不能只测 Web API。

---

## 7. 目标表设计

### 7.1 日程组

建议新增模型：`core.EventGroup`

| 字段 | 类型 | 说明 |
|---|---|---|
| `user` | FK User | 所属用户 |
| `group_id` | CharField UUID | 旧 JSON 中的 `id`，业务唯一 |
| `name` | CharField | 名称 |
| `description` | TextField | 描述 |
| `color` | CharField | 颜色 |
| `type` | CharField | work/personal/study/health/social/other |
| `default_duration` | CharField | 默认时长 |
| `default_importance` | CharField | 默认重要性 |
| `default_urgency` | CharField | 默认紧急度 |
| `ai_priority` | FloatField | AI 优先级 |
| `auto_scheduling` | BooleanField | 是否允许自动调度 |
| `working_hours` | JSONField | 工作时间配置 |
| `created_at` | DateTimeField | 创建时间 |
| `updated_at` | DateTimeField | 更新时间 |

约束：

1. `UniqueConstraint(user, group_id)`。
2. `Index(user, name)`。
3. 删除分组时默认不物理删除事件，只将事件 group 置空；如旧接口传 `deleteEvents=true`，按旧语义批量软删除组内事件。

### 7.2 日程事件

建议新增模型：`core.CalendarEvent`

| 字段 | 类型 | 说明 |
|---|---|---|
| `user` | FK User | 所属用户 |
| `event_id` | CharField UUID | 旧 JSON `id` |
| `group` | FK EventGroup nullable | 对应旧 `groupID` |
| `title` | CharField | 标题 |
| `description` | TextField | 描述 |
| `start` | DateTimeField | 开始时间，统一存 aware datetime |
| `end` | DateTimeField | 结束时间 |
| `ddl` | DateTimeField nullable 或 CharField 兼容 | 截止时间 |
| `importance` | CharField | 重要性 |
| `urgency` | CharField | 紧急性 |
| `location` | CharField | 地点 |
| `status` | CharField | confirmed/tentative/cancelled |
| `last_modified` | DateTimeField | 旧字段兼容 |
| `created_at` | DateTimeField | 创建时间 |
| `updated_at` | DateTimeField | 更新时间 |
| `is_deleted` | BooleanField | 软删除 |
| `deleted_at` | DateTimeField nullable | 删除时间 |
| `metadata` | JSONField | 兼容扩展字段 |

重复事件字段建议放在主表中保留快速查询：

| 字段 | 类型 | 说明 |
|---|---|---|
| `rrule` | TextField | 当前事件持有的 RRule 字符串 |
| `series_id` | CharField indexed | 同系列共享 |
| `is_recurring` | BooleanField | 是否重复成员 |
| `is_main_event` | BooleanField | 是否主事件 |
| `is_detached` | BooleanField | 是否脱离实例 |
| `recurrence_id` | CharField | 原始时间槽 |
| `parent_event_id` | CharField | 主事件 ID |
| `original_series_id` | CharField | CalDAV 此及以后截断的原系列 |

约束和索引：

1. `UniqueConstraint(user, event_id)`。
2. `Index(user, start, end)`。
3. `Index(user, group, start)`。
4. `Index(user, series_id)`。
5. `Index(user, status, start)`。

### 7.3 日程附属关系

建议新增：

| 模型 | 用途 | 主要字段 |
|---|---|---|
| `EventTag` | tags 列表正规化 | `event`, `tag` |
| `EventReminderLink` | `linked_reminders` | `event`, `reminder_id`，后续可 FK Reminder |
| `EventShareGroupLink` | `shared_to_groups` | `event`, `share_group` 或 `share_group_id` |

注意：`shared_to_groups` 必须兼容现有 `CollaborativeCalendarGroup.share_group_id`。

### 7.4 日程重复规则

建议新增：

| 模型 | 用途 | 主要字段 |
|---|---|---|
| `EventRecurrenceSeries` | 系列主体 | `user`, `series_id`, `main_event`, `rrule`, `dtstart`, `is_active`, `metadata` |
| `EventRecurrenceSegment` | RRuleEngine segments | `series`, `segment_id`, `sequence`, `rrule`, `dtstart`, `until`, `count`, `exdates`, `original_data` |
| `EventRecurrenceException` | EXDATE / detached / modified | `series`, `exception_date`, `exception_type`, `event`, `new_data` |

迁移注意：

1. `events_rrule_series` 的实际字段与 `DATA_SCHEMA` 不完全一致，迁移脚本必须以实际数据为准。
2. 旧 `events` 中已经预生成了重复实例，第一阶段不要改成运行时展开，先保持预生成语义。
3. 后续可以再优化为主事件 + recurrence 查询展开，但不属于本次第一阶段目标。

### 7.5 待办

建议新增模型：`core.Todo`

| 字段 | 类型 | 说明 |
|---|---|---|
| `user` | FK User | 所属用户 |
| `todo_id` | CharField UUID | 旧 JSON `id` |
| `group` | FK EventGroup nullable | 旧 `groupID` |
| `title` | CharField | 标题 |
| `description` | TextField | 描述 |
| `importance` | CharField | 重要性 |
| `urgency` | CharField | 紧急性 |
| `status` | CharField | pending/in-progress/completed/cancelled/converted |
| `due_date` | DateTimeField nullable 或 CharField 兼容 | 截止时间 |
| `estimated_duration` | CharField | 预估耗时 |
| `priority_score` | FloatField | AI 优先级 |
| `created_at` | DateTimeField | 创建时间 |
| `last_modified` | DateTimeField | 旧字段兼容 |
| `updated_at` | DateTimeField | 更新时间 |
| `is_deleted` | BooleanField | 软删除 |
| `deleted_at` | DateTimeField nullable | 删除时间 |
| `metadata` | JSONField | 兼容扩展 |

建议新增：

| 模型 | 用途 |
|---|---|
| `TodoTag` | tags |
| `TodoDependency` | dependencies |
| `TodoReminderLink` | linked_reminders |

### 7.6 提醒

建议新增模型：`core.Reminder`

| 字段 | 类型 | 说明 |
|---|---|---|
| `user` | FK User | 所属用户 |
| `reminder_id` | CharField UUID | 旧 JSON `id` |
| `title` | CharField | 标题 |
| `content` | TextField | 内容 |
| `trigger_time` | DateTimeField | 触发时间 |
| `priority` | CharField | critical/high/normal/low/debug |
| `status` | CharField | active/dismissed/snoozed/completed 等兼容 |
| `snooze_until` | DateTimeField nullable | 延后到 |
| `notification_sent` | BooleanField | 是否已发送 |
| `linked_event` | FK CalendarEvent nullable | 旧 linked_event_id |
| `linked_todo` | FK Todo nullable | 旧 linked_todo_id |
| `rrule` | TextField | 重复规则 |
| `series_id` | CharField indexed | 系列 ID |
| `is_recurring` | BooleanField | 是否重复 |
| `is_main_reminder` | BooleanField | 是否主提醒 |
| `is_detached` | BooleanField | 是否脱离实例 |
| `created_at` | DateTimeField | 创建时间 |
| `last_modified` | DateTimeField | 旧字段兼容 |
| `updated_at` | DateTimeField | 更新时间 |
| `is_deleted` | BooleanField | 软删除 |
| `deleted_at` | DateTimeField nullable | 删除时间 |
| `metadata` | JSONField | 兼容扩展 |

建议新增：

| 模型 | 用途 |
|---|---|
| `ReminderAdvanceTrigger` | advance_triggers |
| `ReminderRecurrenceSeries` | 提醒重复系列 |
| `ReminderRecurrenceSegment` | `rrule_series_storage.segments` |
| `ReminderRecurrenceException` | exceptions |

### 7.7 用户配置类数据

建议新增：

| 模型 | 来源 key | 建议 |
|---|---|---|
| `UserPreference` | `user_preference` | OneToOne User + `data JSONField` |
| `UserInterfaceSettings` | `user_interface_settings`, `user_settings` | OneToOne User + `data JSONField` |
| `CalendarExportState` | `outport_calendar_data` | 当前可 OneToOne；未来多订阅再拆 device/feed 表 |
| `UserAgentConfig` | `agent_config` | OneToOne；当前模型、thinking 开关、last switch |
| `CustomAgentModel` | `agent_config.custom_models` | 若正式拆配置，存 provider/base_url/model_name/api_key 密文 |
| `UserAgentOptimizationConfig` | `agent_optimization_config` | OneToOne + JSONField |
| `UserAgentQuota` | `agent_token_usage` | monthly_credit/monthly_used/current_month；明细继续用 `AgentUsageRecord` |
| `UserAICreditAccount` | `ai_chatting` | 若余额有真实产品含义则拆账户表 |

### 7.8 Legacy 治理表

建议新增：

| 模型 | 用途 |
|---|---|
| `UserDataMigrationState` | 记录每个用户/每个 key 迁移状态、checksum、错误信息、迁移时间 |
| `UserDataLegacySnapshot` | 可选，保存迁移前压缩快照或 checksum，便于审计 |

迁移状态字段建议：

| 字段 | 说明 |
|---|---|
| `user` | 用户 |
| `key` | legacy key |
| `source_row_id` | 原 `core_userdata.id` |
| `source_checksum` | JSON checksum |
| `target_checksum` | ORM 导出回 JSON 后 checksum |
| `status` | pending/migrated/verified/failed/skipped |
| `error` | 错误信息 |
| `migrated_at` | 迁移时间 |
| `verified_at` | 验证时间 |

---

## 8. 兼容层设计

### 8.1 Repository 层

新增 `core/repositories/`，禁止业务继续直接操作 `UserData`。

建议文件：

| 文件 | 职责 |
|---|---|
| `core/repositories/events.py` | 日程读写、旧 JSON 导入导出、分组解析、共享同步辅助 |
| `core/repositories/todos.py` | 待办读写、旧 JSON 导入导出 |
| `core/repositories/reminders.py` | 提醒读写、旧 JSON 导入导出、重复提醒辅助 |
| `core/repositories/user_settings.py` | 偏好和 UI 配置 |
| `core/repositories/legacy_userdata.py` | 只读 fallback、checksum、迁移状态 |

Repository 必须提供两类接口：

```python
# 新内部接口，返回 ORM/domain 对象或 dict
EventRepository.list_events(user, filters=None)
EventRepository.create_event(user, data)
EventRepository.update_event(user, event_id, data)
EventRepository.delete_event(user, event_id, scope='single')

# 兼容接口，返回旧前端 JSON 格式
EventRepository.export_legacy_events(user) -> list[dict]
EventRepository.import_legacy_events(user, events: list[dict])
```

### 8.2 切换开关

迁移期需要 feature flag，建议使用 settings 或环境变量：

| 开关 | 默认 | 说明 |
|---|---|---|
| `USERDATA_TABLE_READ_ENABLED` | False | 是否从新表读 |
| `USERDATA_TABLE_WRITE_ENABLED` | False | 是否写新表 |
| `USERDATA_DUAL_WRITE_ENABLED` | False | 是否旧 JSON + 新表双写 |
| `USERDATA_DIFF_ASSERT_ENABLED` | False | 是否每次读时对比 legacy JSON 与新表导出 |
| `USERDATA_LEGACY_FALLBACK_ENABLED` | True | 新表读失败时是否回退 UserData |

阶段目标：

| 阶段 | 读 | 写 | 校验 |
|---|---|---|---|
| P1 | legacy | legacy | 只做扫描 |
| P2 | legacy | dual write | 后台 diff |
| P3 | new table | dual write | 请求级 diff |
| P4 | new table | new table | legacy 只读备份 |
| P5 | new table | new table | 删除 legacy 写路径 |

---

## 9. 迁移阶段计划

### P0：冻结范围与前置修复

目标：实现前不改数据结构，先确认可安全迁移。

任务：

- [ ] 备份 `db.sqlite3`、`db.sqlite3-wal`、`db.sqlite3-shm`、`agent_checkpoints.sqlite`。
- [ ] 记录当前 `core_userdata` key、行数、checksum、重复 `(user,key)`。
- [ ] 处理或记录重复 key：`ai_chatting` user 1、`reminders` user 44。
- [ ] 确认 `/api/agent/rollback/` 最终命中的路由，解决 core 旧回滚与 agent_service 新回滚冲突。
- [ ] 修复或记录 `clear_session_checkpoints()` 未清理 `writes` 表的问题。
- [ ] 建立 `UserData` 直接访问调用清单，作为后续逐项替换追踪表。

测试：

```powershell
.venv\Scripts\python.exe manage.py showmigrations
.venv\Scripts\python.exe manage.py check
.venv\Scripts\python.exe manage.py test tests.test_caldav tests.test_caldav_recurring tests.test_web_caldav_crossover
```

验收：

- [ ] 备份文件存在且可读。
- [ ] `core_userdata` 审计报告已生成。
- [ ] 回滚路由冲突有明确处理结论。
- [ ] 所有现有测试在未改结构前通过，作为基线。

### P1：新增模型和只读迁移工具

目标：新增 ORM 表，不改变生产读写行为。

任务：

- [ ] 新增 `EventGroup`, `CalendarEvent`, recurrence 相关模型。
- [ ] 新增 `Todo`, `Reminder` 及附属关系模型。
- [ ] 新增配置表和迁移状态表。
- [ ] 注册 admin。
- [ ] 编写 management command：`audit_userdata`、`migrate_userdata_to_tables --dry-run`、`verify_userdata_migration`。
- [ ] 所有命令默认只读或 dry-run，必须显式参数才写入。

测试：

```powershell
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.venv\Scripts\python.exe manage.py migrate --plan
.venv\Scripts\python.exe manage.py check
.venv\Scripts\python.exe manage.py audit_userdata --dry-run
.venv\Scripts\python.exe manage.py migrate_userdata_to_tables --dry-run
```

验收：

- [ ] 新模型迁移文件可审查。
- [ ] dry-run 能输出每个用户每个 key 的迁移计划。
- [ ] dry-run 不写任何业务表。
- [ ] admin 可查看新模型。

### P2：一次性历史数据迁移

目标：将 legacy JSON 导入新表，但系统仍从 `UserData` 读取。

任务：

- [ ] 迁移 `events_groups`。
- [ ] 迁移 `events`。
- [ ] 迁移 `events_rrule_series`。
- [ ] 迁移 `todos`。
- [ ] 迁移 `reminders`。
- [ ] 迁移 `rrule_series_storage`。
- [ ] 迁移配置型 key 到配置表。
- [ ] 写入 `UserDataMigrationState`。
- [ ] 对新表导出 legacy JSON，与原 JSON 做结构化 diff。

测试：

```powershell
.venv\Scripts\python.exe manage.py migrate_userdata_to_tables --keys events_groups,events,events_rrule_series --batch-size 100
.venv\Scripts\python.exe manage.py verify_userdata_migration --keys events_groups,events,events_rrule_series --strict
.venv\Scripts\python.exe manage.py migrate_userdata_to_tables --keys todos,reminders,rrule_series_storage --batch-size 100
.venv\Scripts\python.exe manage.py verify_userdata_migration --keys todos,reminders,rrule_series_storage --strict
```

验收：

- [ ] 每个 migrated key 都有 `verified` 状态。
- [ ] 新表行数与 legacy JSON 元素数一致或差异有白名单说明。
- [ ] 所有业务 ID 与 legacy UUID 一致。
- [ ] 事件共享关系 `shared_to_groups` 可还原。
- [ ] RRule segments/exceptions 可还原。

### P3：服务层双写

目标：所有新写入同时写 legacy `UserData` 和新表，读仍以 legacy 为准。

任务：

- [ ] 改造 `EventService` 使用 repository 双写。
- [ ] 改造 `TodoService` 使用 repository 双写。
- [ ] 改造 `ReminderService` 使用 repository 双写。
- [ ] 改造 `integrated_reminder_manager.UserDataStorageBackend` 或替换为 recurrence repository。
- [ ] 改造 Agent unified planner tools 和 legacy planner tools，确保仍走服务层。
- [ ] 改造 MCP server 间接调用链，无直接 UserData 新增写。
- [ ] 每次写后可选执行 legacy export diff，失败只记录 ERROR，不影响主流程，直到 P4 再严格。

测试：

```powershell
.venv\Scripts\python.exe manage.py test tests.test_caldav tests.test_caldav_recurring tests.test_multiget_series tests.test_web_then_phone_edit
.venv\Scripts\python.exe manage.py test tests.test_caldav_propagation tests.test_caldav_crossover tests.test_ios_simulation
.venv\Scripts\python.exe manage.py verify_userdata_migration --strict
```

手工 API 验收：

- [ ] 创建单次日程，legacy 与新表一致。
- [ ] 创建重复日程，主事件、实例、series、segment 一致。
- [ ] 编辑单次重复实例，detached 语义一致。
- [ ] 删除单个/全部/未来重复事件，legacy 与新表一致。
- [ ] 创建/更新/删除 todo 一致。
- [ ] 创建/更新/删除 reminder 一致。
- [ ] Agent WebSocket 创建/修改/删除日程可回滚。
- [ ] Quick Action 创建/修改/删除日程可回滚。
- [ ] MCP create/update/delete 结果一致。

### P4：普通 API 切换新表读

目标：Web/API/订阅 Feed 从新表读取，legacy 作为校验和 fallback。

任务：

- [ ] `get_events_impl` 改为 repository 新表读，返回旧 JSON 格式。
- [ ] `get_events_groups_impl` 改为新表读。
- [ ] todo/reminder 读取改为新表读。
- [ ] calendar feed 改为新表读。
- [ ] share group sync 改为新表读。
- [ ] internal attachment parser 改为新表读。
- [ ] 配置 API 按配置表读取。
- [ ] 开启请求级 diff，发现差异记录 `UserDataMigrationState`。

测试：

```powershell
.venv\Scripts\python.exe manage.py test tests.test_caldav tests.test_caldav_recurring tests.test_web_caldav_crossover
.venv\Scripts\python.exe manage.py test tests.test_count8 tests.test_truncation_boundary tests.test_crossover
.venv\Scripts\python.exe manage.py verify_userdata_migration --strict
```

手工页面验收：

- [ ] `/home/` 月/周/日视图加载正常。
- [ ] 日程筛选、分组颜色、拖拽修改正常。
- [ ] 待办四象限或列表视图正常。
- [ ] 提醒列表、延后、完成、忽略正常。
- [ ] 日历订阅 Feed 可被客户端读取。

### P5：CalDAV 切换新表读写

目标：CalDAV 全面使用新表，保持 iOS/macOS/Thunderbird 兼容。

任务：

- [ ] `CalDAVBaseView.load_events/load_events_groups/load_todos/load_reminders` 改 repository。
- [ ] `EventObjectView.put/delete` 改 repository。
- [ ] `_handle_create/_handle_recurring_put/_handle_rrule_truncation/_propagate_main_event_changes/_update_event_field` 统一迁移到服务层或 repository。
- [ ] 保持 `calendar_id='reminders'` 只读语义。
- [ ] CalDAV 写操作进入 `transaction.atomic()` 和 `reversion.create_revision()`。

测试：

```powershell
.venv\Scripts\python.exe manage.py test tests.test_caldav tests.test_caldav_auth tests.test_caldav_fixes
.venv\Scripts\python.exe manage.py test tests.test_caldav_recurring tests.test_caldav_propagation tests.test_multiget_series
.venv\Scripts\python.exe manage.py test tests.test_ios_simulation tests.test_web_then_phone_edit
```

手工 CalDAV 验收：

- [ ] iOS 添加 CalDAV 账户后能看到日历集合。
- [ ] iOS 创建事件，Web 端可见。
- [ ] Web 创建事件，iOS 可见。
- [ ] iOS 编辑重复事件“仅此事件”，Web 端语义正确。
- [ ] iOS 编辑重复事件“此及以后”，Web 端语义正确。
- [ ] iOS 删除重复事件单个实例，Web 端语义正确。
- [ ] reminders 日历保持只读。

### P6：Agent 回滚与 reversion 升级

目标：回滚不再依赖大 JSON 快照，而是可恢复新 ORM 对象。

任务：

- [ ] 更新 `agent_service.utils.agent_transaction`，快照新 ORM 对象或操作前状态。
- [ ] 明确废弃或合并 `core.AgentTransaction`。
- [ ] 确认 `/api/agent/rollback/` 只指向新实现。
- [ ] `rollback_to_message` 回滚新表对象、搜索缓存、附件、SessionTodo、摘要/token 快照。
- [ ] 确认 reversion 对新模型注册齐全。
- [ ] 保留旧 UserData rollback adapter，仅用于迁移前事务。

测试：

```powershell
.venv\Scripts\python.exe manage.py test tests.test_web_then_phone_edit tests.test_web_caldav_crossover
.venv\Scripts\python.exe manage.py verify_userdata_migration --strict
```

手工 Agent 验收：

- [ ] WebSocket Agent 创建 event 后回滚成功。
- [ ] WebSocket Agent 更新 recurring event 后回滚成功。
- [ ] Quick Action 创建 todo 后回滚成功。
- [ ] MCP 创建 reminder 后可通过 Agent 回滚链路恢复。
- [ ] 回滚后搜索缓存不会引用已删除对象。
- [ ] 回滚后附件软删除和恢复逻辑正常。

### P7：停写 UserData，清理 legacy

目标：核心业务不再写 `UserData`，只保留迁移前归档和少数未迁移 key。

任务：

- [ ] 关闭 `USERDATA_DUAL_WRITE_ENABLED`。
- [ ] 禁止核心业务调用 `UserData.set_value()` 写 `events/todos/reminders/events_groups/RRule key`。
- [ ] 为保留 key 加唯一约束或迁移后删除 `core_userdata` 依赖。
- [ ] 清理 `resources/test_1/setting/user_settings/planner.temp_events`。
- [ ] 更新 `docs/后端开发规范/数据模型规范.md`，将 UserData 从核心存储改为 legacy。
- [ ] 更新 README 中数据库说明。

测试：

```powershell
.venv\Scripts\python.exe manage.py check
.venv\Scripts\python.exe manage.py test
.venv\Scripts\python.exe manage.py verify_userdata_migration --strict --no-legacy-write
```

验收：

- [ ] `rg "UserData\.objects|set_value\(|get_or_initialize"` 只剩 legacy adapter、配置迁移或明确白名单。
- [ ] 新增业务代码不再引用 `UserData`。
- [ ] 核心业务功能全量通过。
- [ ] 生产备份和回滚文档完整。

---

## 10. 测试矩阵

### 10.1 自动测试

| 范围 | 命令 | 重点 |
|---|---|---|
| Django 健康检查 | `.venv\Scripts\python.exe manage.py check` | settings、模型、URL 基础检查 |
| 迁移检查 | `.venv\Scripts\python.exe manage.py makemigrations --check --dry-run` | 确认模型与迁移一致 |
| CalDAV 基础 | `.venv\Scripts\python.exe manage.py test tests.test_caldav tests.test_caldav_auth tests.test_caldav_fixes` | 鉴权、PROPFIND/REPORT/GET/PUT/DELETE |
| CalDAV 重复 | `.venv\Scripts\python.exe manage.py test tests.test_caldav_recurring tests.test_caldav_propagation tests.test_multiget_series` | 重复事件、传播、multi-get |
| iOS 模拟 | `.venv\Scripts\python.exe manage.py test tests.test_ios_simulation tests.test_web_then_phone_edit` | 手机与 Web 交叉编辑 |
| 边界 | `.venv\Scripts\python.exe manage.py test tests.test_truncation_boundary tests.test_count8 tests.test_crossover` | UNTIL/COUNT/跨端边界 |
| 全量 | `.venv\Scripts\python.exe manage.py test` | 阶段收口前必须跑 |

### 10.2 数据一致性测试

每个阶段必须执行：

```powershell
.venv\Scripts\python.exe manage.py audit_userdata --output logs/userdata_audit.json
.venv\Scripts\python.exe manage.py verify_userdata_migration --strict --output logs/userdata_verify.json
```

校验项：

| 数据 | 校验 |
|---|---|
| events | 数量、event_id 集合、start/end、groupID、series_id、shared_to_groups、status |
| event groups | group_id、名称、颜色、排序/默认字段 |
| recurrence | main event、instances、segments、exceptions、detached |
| todos | todo_id、status、due_date、dependencies、linked_reminders |
| reminders | reminder_id、trigger_time、status、rrule、notification_sent、linked_event/todo |
| configs | JSON checksum，敏感字段仍为密文 |

### 10.3 手工验收清单

| 场景 | 必测动作 |
|---|---|
| Web 日程 | 创建、编辑、拖拽、删除、分组、筛选、重复日程四种范围编辑 |
| Web 待办 | 创建、编辑、完成、删除、转日程 |
| Web 提醒 | 创建、延后、忽略、完成、重复提醒编辑/删除 |
| 分享群组 | 创建群组、加入、共享日程、成员颜色更新、版本号同步 |
| 日历订阅 | 获取 all/events/todos/reminders feed，导入客户端 |
| CalDAV | iOS/macOS/Thunderbird 至少一类客户端读写 |
| Agent WebSocket | 自然语言 CRUD、回滚到消息、附件内部元素引用 |
| Quick Action | 创建/更新/删除日程待办提醒，查询任务结果 |
| MCP | create/update/delete/search/complete_todo/get_event_groups |
| Admin | 新模型列表、搜索、过滤、只读字段展示 |

---

## 11. 调用点替换追踪表

迁移执行时，每改完一个调用点必须更新本表状态。

| 状态 | 含义 |
|---|---|
| TODO | 未开始 |
| WIP | 改造中 |
| DUAL | 已双写/双读校验 |
| NEW | 已切新表 |
| VERIFIED | 自动和手工测试通过 |

| 文件/模块 | 调用点 | key | 当前状态 | 验证命令/方式 |
|---|---|---|---|---|
| `core/models.py` | `UserData` legacy adapter | all | TODO | `rg "UserData" core agent_service caldav_service` |
| `core/views.py` | `home` | settings/groups/planner | TODO | 页面 `/home/` |
| `core/views.py` | `user_preferences/user_settings/change_view` | settings | TODO | 设置页面/API |
| `core/views.py` | event group CRUD | `events_groups`, `events` | TODO | 分组创建/删除联动 |
| `core/views.py` | todo CRUD/convert | `todos`, `events` | TODO | Todo API |
| `core/views_events.py` | event get/create/update/bulk | `events`, RRule | TODO | CalDAV/event tests |
| `core/views_reminder.py` | reminder get/create/update/delete/bulk/status | `reminders`, RRule | TODO | Reminder API |
| `core/views_calendar_subscription.py` | `calendar_feed` | events/todos/reminders | TODO | Feed 手工导入 |
| `core/views_share_groups.py` | group sync | `events.shared_to_groups` | TODO | 分享群组同步 |
| `core/services/event_service.py` | `EventService` | events/RRule | TODO | Agent tools |
| `core/services/todo_service.py` | `TodoService` | todos | TODO | Agent tools |
| `core/services/reminder_service.py` | `ReminderService` | reminders/RRule | TODO | Agent tools |
| `integrated_reminder_manager.py` | `UserDataStorageBackend` | RRule stores | TODO | 重复提醒测试 |
| `caldav_service/views/base.py` | loaders | events/groups/todos/reminders | TODO | CalDAV tests |
| `caldav_service/views/event.py` | PUT/DELETE helpers | events/RRule | TODO | iOS 模拟 |
| `agent_service/tools/unified_planner_tools.py` | planner tools | events/todos/reminders | TODO | WebSocket/Quick/MCP |
| `agent_service/tools/planner_tools.py` | legacy planner tools | events/todos/reminders | TODO | 工具启用后手工测 |
| `agent_service/tools/event_group_service.py` | group cache/resolve | events_groups | TODO | Agent get_event_groups |
| `agent_service/tools/share_group_service.py` | share group events | events | TODO | Agent get_share_groups |
| `agent_service/parsers/internal_parser.py` | attach internal item | events/todos/reminders | TODO | 附件内部元素 |
| `agent_service/views_config_api.py` | config/token APIs | agent config keys | TODO | Agent 设置页 |
| `agent_service/context_optimizer.py` | model/runtime/usage | agent config/token | TODO | Token 统计 |
| `agent_service/utils.py` | `agent_transaction` | tracked keys | TODO | Agent 回滚 |
| `mcp_server.py` | MCP wrappers | planner keys | TODO | MCP 手工调用 |
| `core/admin.py` | UserData admin | all | TODO | Admin 检查 |

---

## 12. 关键兼容语义

### 12.1 时间格式

旧 API 使用本地时间字符串：

| 字段 | 旧格式 |
|---|---|
| `events[].start/end` | `YYYY-MM-DDTHH:MM` |
| `todos[].due_date` | `YYYY-MM-DDTHH:MM` 或 `YYYY-MM-DD` |
| `reminders[].trigger_time` | `YYYY-MM-DDTHH:MM` |
| `last_modified` | `YYYY-MM-DD HH:MM:SS` |
| `recurrence_id` | `%Y%m%dT%H%M%S` |

新表建议存 aware datetime，但所有 legacy JSON/API/CalDAV 输出必须保持现有格式。

### 12.2 重复事件

必须保留：

1. 预生成实例语义。
2. `is_main_event` 主事件语义。
3. `series_id` 同系列共享。
4. `is_detached` 单次编辑实例。
5. `recurrence_id` 原始时间槽。
6. `original_series_id` CalDAV “此及以后”截断。
7. 删除范围：single/all/future/from_time。

### 12.3 分享群组

必须保留：

1. 事件的 `shared_to_groups` 语义。
2. `sync_group_calendar_data` 汇总所有成员共享事件到 `GroupCalendarData.events_data`。
3. `GroupCalendarData.version` 递增同步。
4. 成员颜色变更后重新汇总。

### 12.4 Agent 回滚

必须保留：

1. `@agent_transaction` 在写操作前保存可恢复状态。
2. `AgentTransaction.metadata.tool_call_id` 用于 `rollback_to_message` 精确匹配。
3. 回滚后清搜索缓存。
4. 回滚后处理附件软删除/恢复。
5. 回滚后同步 SessionTodo、摘要和 token 快照。

### 12.5 密钥配置

必须保留：

1. `agent_config.custom_models.*.api_key` 继续通过 `SecureKeyStorage` 加密。
2. API 返回继续掩码，不返回明文。
3. 日志、迁移报告、checksum 报告不得输出密钥明文。

---

## 13. 风险与回滚预案

| 风险 | 严重度 | 预防 | 回滚 |
|---|---|---|---|
| 新表迁移数据不一致 | 高 | strict diff、checksum、逐用户状态 | 关闭新表读，回退 legacy |
| CalDAV 重复事件语义回归 | 高 | 单独 P5、iOS 模拟测试 | CalDAV 入口回退 legacy repository |
| Agent 回滚失败 | 高 | P6 前保留旧 JSON 快照 | 关闭 Agent 写工具或回退 legacy 写 |
| 双写不一致 | 高 | 写后 diff、记录 MigrationState | 使用 legacy 重放修复新表 |
| 密钥泄露 | 高 | 禁止输出配置明文，checksum 脱敏 | 立即轮换密钥，清理日志 |
| SQLite 锁争用 | 中 | `transaction.atomic()` 控制粒度，避免长事务 | 分批迁移，降低 batch size |
| reversion 继续膨胀 | 中 | 新模型粒度快照，减少大 JSON 快照 | 清理旧版本需单独方案 |
| 测试数据污染 | 中 | 标记测试用户/测试 key | 白名单跳过或归档 |

---

## 14. 实施前置命令清单

每次阶段开始前执行：

```powershell
git status
git diff
.venv\Scripts\python.exe manage.py check
.venv\Scripts\python.exe manage.py showmigrations
```

每次涉及迁移前执行：

```powershell
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.venv\Scripts\python.exe manage.py migrate --plan
```

每次阶段结束后执行：

```powershell
.venv\Scripts\python.exe manage.py verify_userdata_migration --strict
.venv\Scripts\python.exe manage.py test tests.test_caldav tests.test_caldav_recurring tests.test_web_then_phone_edit
```

最终切换前执行：

```powershell
.venv\Scripts\python.exe manage.py test
```

---

## 15. 推荐实施顺序

推荐先做这 5 件事，不直接进入大规模改表：

1. 新增 `audit_userdata` 命令，固化当前调研结果，输出 key、行数、checksum、重复 key、unknown key。
2. 新增 repository 层，但第一版只包装 legacy `UserData`，不改变行为。
3. 修复 `/api/agent/rollback/` 路由冲突和 checkpoint `writes` 清理问题。
4. 新增 ORM 模型和 dry-run 迁移命令，不切读写。
5. 为 events/reminders 的重复规则补足自动测试，再开始双写。

---

## 16. 阶段进度记录

| 日期 | 阶段 | 负责人 | 变更摘要 | 测试命令 | 结果 | 后续问题 |
|---|---|---|---|---|---|---|
| 2026-06-16 | 调研 | OpenCode | 完成 UserData 数据、调用面、目标表、迁移阶段方案 | 只读调研、`showmigrations`、表统计 | 通过 | 待实现 P0 |
