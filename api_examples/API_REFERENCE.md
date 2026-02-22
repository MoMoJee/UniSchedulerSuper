# UniScheduler API 接口文档

> **版本**: 1.6.3  
> **基础地址**: `http://127.0.0.1:8000`（开发环境）  
> **更新日期**: 2026-02-22

---

## 目录

1. [认证机制](#认证机制)
2. [通用响应格式](#通用响应格式)
3. [Events API - 日程管理](#events-api---日程管理)
4. [Event Groups API - 日程分组](#event-groups-api---日程分组)
5. [TODOs API - 待办事项](#todos-api---待办事项)
6. [Reminders API - 提醒](#reminders-api---提醒)
7. [Quick Action API - 智能操作](#quick-action-api---智能操作)
8. [Speech-to-Text API - 语音转文字](#speech-to-text-api---语音转文字)
9. [错误码参考](#错误码参考)

---

## 认证机制

除语音转文字接口（后期会提供更多的 parser 接口）外，所有 API 需要 Token 认证。

### 获取 Token

**POST** `/api/auth/login/`

**请求体：**
```json
{
  "username": "your_username",
  "password": "your_password"
}
```

**成功响应（200）：**
```json
{
  "token": "9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b",
  "user_id": 1,
  "username": "your_username"
}
```

**失败响应（401）：**
```json
{
  "error": "用户名或密码错误"
}
```

### 使用 Token

在请求头中携带：

```
Authorization: Token 9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b
```

Python 示例：
```python
headers = {
    "Authorization": f"Token {token}",
    "Content-Type": "application/json"
}
```

---

## 通用响应格式

### 成功响应

大多数接口返回业务数据直接包裹在响应体中，HTTP 状态码为 `200`。

### 错误响应

```json
{
  "error": "错误描述",
  "error_code": "ERROR_CODE_STRING"
}
```

### 分页响应

支持分页的列表接口：
```json
{
  "count": 100,
  "limit": 20,
  "offset": 0,
  "results": [...]
}
```

---

## Events API - 日程管理

### 获取日程列表（含日程组）

**GET** `/get_calendar/events/`

**请求头：** `Authorization: Token <token>`

**响应（200）：**
```json
{
  "events": [
    {
      "id": 1,
      "title": "团队会议",
      "start": "2026-02-10T14:00:00",
      "end": "2026-02-10T15:00:00",
      "importance": "important",
      "urgency": "urgent",
      "groupID": "2",
      "is_recurring": false
    }
  ],
  "events_groups": [
    { "id": 1, "name": "工作", "color": "#FF6B6B", "description": "..." }
  ]
}
```

> 注意：日程组列表（`events_groups`）与日程列表（`events`）在同一响应中返回，无需单独请求。

---

### 创建日程

**POST** `/events/create_event/`

**请求体：**
```json
{
  "title": "团队会议",
  "start": "2026-02-10T14:00:00",
  "end": "2026-02-10T15:00:00",
  "description": "讨论项目进度",
  "importance": "important",
  "urgency": "urgent",
  "groupID": "1",
  "ddl": "",
  "rrule": ""
}
```

**字段说明：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `title` | string | ✅ | 日程标题 |
| `start` | string | ✅ | 开始时间（ISO 8601，如 `2026-02-10T14:00:00`） |
| `end` | string | ✅ | 结束时间（ISO 8601） |
| `description` | string | ❌ | 描述 |
| `importance` | string | ❌ | 重要性：`important` / `not-important` |
| `urgency` | string | ❌ | 紧急度：`urgent` / `not-urgent` |
| `groupID` | string | ❌ | 日程组 ID（字符串形式） |
| `ddl` | string | ❌ | 截止时间（ISO 8601），空字符串表示无 |
| `rrule` | string | ❌ | RFC 5545 重复规则，空字符串表示单次日程 |

**成功响应（200）：**
```json
{
  "event": {
    "id": 42,
    "series_id": null,
    "title": "团队会议",
    "start": "2026-02-10T14:00:00",
    "end": "2026-02-10T15:00:00"
  }
}
```

> 重复日程创建后，响应中 `event.series_id` 为系列 ID，`event.id` 为第一个实例的 ID。

---

### 更新日程

**POST** `/get_calendar/update_events/`

**请求体：**
```json
{
  "eventId": 42,
  "title": "更新后的标题",
  "start": "2026-02-10T15:00:00",
  "end": "2026-02-10T16:00:00",
  "description": "更新后的描述",
  "importance": "not-important",
  "urgency": "not-urgent"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `eventId` | integer | ✅ | 要更新的日程 ID |
| `title` | string | ❌ | 新标题 |
| `start` | string | ❌ | 新开始时间 |
| `end` | string | ❌ | 新结束时间 |
| `description` | string | ❌ | 新描述 |
| `importance` | string | ❌ | `important` / `not-important` |
| `urgency` | string | ❌ | `urgent` / `not-urgent` |
| `rrule` | string | ❌ | 新增/修改重复规则（**注意末尾不要加分号**） |

> 如需将单次日程转换为重复日程，只需增加 `rrule` 字段即可。

---

### 删除日程

**POST** `/get_calendar/delete_event/`

**请求体：**
```json
{
  "eventId": 42,
  "delete_scope": "single"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `eventId` | integer | ✅ | 要删除的日程 ID |
| `delete_scope` | string | ✅ | `single`（仅此实例）/ `all`（整个系列） |
| `series_id` | integer | ❌ | 系列 ID（`delete_scope=all` 时需要提供） |

---

### 批量编辑重复日程

**POST** `/api/events/bulk-edit/`

用于对重复日程系列进行精细化编辑或删除。

**请求体公共字段：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `operation` | string | ✅ | `edit`（编辑）或 `delete`（删除） |
| `event_id` | integer | ✅ | 目标日程实例 ID |
| `series_id` | integer | ✅ | 系列 ID |
| `edit_scope` | string | ✅ | `all`（全部）/ `single`（仅此实例）/ `future`（此后所有）/ `from_time`（指定时间后） |

**编辑时额外字段：** `title`、`description`、`importance`、`urgency`、`rrule`（修改重复规则会创建新系列并截断旧系列）

**`edit_scope` 行为说明：**

| 值 | 行为 |
|----|------|
| `all` | 更新系列中所有实例 |
| `single` | 将指定实例从系列中独立出来，单独修改 |
| `future` | 修改指定 `event_id` 及以后的所有实例 |
| `from_time` | 从 `from_time` 时间点之后创建新系列（需同时提供 `from_time` 字段，ISO 8601） |

---

## Event Groups API - 日程分组

### 获取日程组列表

日程组通过 **GET** `/get_calendar/events/` 接口返回，日程组数据在响应的 `events_groups` 字段中，与日程列表一同返回，无单独的列表接口。

---

### 创建日程组

**POST** `/get_calendar/create_events_group/`

**请求体：**
```json
{
  "name": "个人",
  "description": "个人生活日程",
  "color": "#4ECDC4"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | 组名称 |
| `description` | string | ❌ | 描述 |
| `color` | string | ❌ | 十六进制颜色值（如 `#FF6B6B`） |

> ⚠️ 服务端对创建失败不会报错，建议创建后调用 `GET /get_calendar/events/` 验证结果。

---

### 更新日程组

**POST** `/get_calendar/update_events_group/`

**请求体：**
```json
{
  "groupID": 3,
  "title": "新组名",
  "description": "新描述",
  "color": "#4ECDC4"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `groupID` | integer | ✅ | 日程组 ID |
| `title` | string | ❌ | 新组名 |
| `description` | string | ❌ | 新描述 |
| `color` | string | ❌ | 新颜色 |

> ⚠️ 服务端对不存在的 ID 不会报错，建议更新后验证结果。

---

### 删除日程组

**POST** `/get_calendar/delete_event_groups/`

**请求体：**
```json
{
  "groupIds": [3, 5],
  "deleteEvents": false
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `groupIds` | array[integer] | ✅ | 要删除的日程组 ID 列表（支持批量） |
| `deleteEvents` | boolean | ❌ | 是否同时删除组内所有日程（默认 `false`） |

> ⚠️ 服务端对不存在的 ID 不会报错，建议删除后验证结果。

---

## TODOs API - 待办事项

### 获取待办列表

**GET** `/api/todos/`

**响应（200）：**
```json
{
  "todos": [
    {
      "id": 1,
      "title": "完成报告",
      "description": "月度工作报告",
      "due_date": "2026-02-15",
      "importance": "important",
      "urgency": "urgent",
      "status": "pending",
      "created_at": "2026-02-01T10:00:00"
    }
  ]
}
```

---

### 创建待办

**POST** `/api/todos/create/`

**请求体：**
```json
{
  "title": "完成报告",
  "description": "月度工作报告",
  "due_date": "2026-02-15",
  "estimated_duration": 30,
  "importance": "important",
  "urgency": "urgent",
  "groupID": ""
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `title` | string | ✅ | 待办标题 |
| `description` | string | ❌ | 详细描述 |
| `due_date` | string (YYYY-MM-DD) | ❌ | 截止日期 |
| `estimated_duration` | integer | ❌ | 预计耗时（分钟） |
| `importance` | string | ❌ | `important` / `not-important` |
| `urgency` | string | ❌ | `urgent` / `not-urgent` |
| `groupID` | string | ❌ | 关联日程组 ID，可为空字符串 |

**成功响应（200）：**
```json
{
  "todo": { "id": 10 }
}
```

---

### 更新待办

**POST** `/api/todos/update/`

**请求体：**
```json
{
  "id": 10,
  "title": "新标题",
  "importance": "not-important"
}
```

所有字段中 `id` 为必填，其余字段均为可选，与创建时字段相同。

---

### 将待办转换为日程

**POST** `/api/todos/convert/`

**请求体：**
```json
{
  "id": 10,
  "start_time": "2026-02-15T14:00:00",
  "end_time": "2026-02-15T16:00:00"
}
```

**成功响应（200）：**
```json
{
  "event": { "id": 42 }
}
```

> 转换后原待办状态变为 `converted`，如需删除请手动调用删除接口。

---

### 删除待办

**POST** `/api/todos/delete/`

**请求体：**
```json
{
  "id": 10
}
```

---

## Reminders API - 提醒

### 获取提醒列表

**GET** `/api/reminders/`

**响应（200）：**
```json
{
  "reminders": [
    {
      "id": 1,
      "title": "喝水提醒",
      "trigger_time": "2026-02-10T10:00:00",
      "content": "记得喝水",
      "priority": "normal",
      "status": "active"
    }
  ]
}
```

> 时间字段名为 `trigger_time`（非 `reminder_time`）；类型字段为 `priority`（非 `reminder_type`）。

---

### 创建提醒

**POST** `/api/reminders/create/`

**请求体：**
```json
{
  "title": "会议提醒",
  "trigger_time": "2026-02-10T13:30:00",
  "content": "30分钟后有团队会议",
  "priority": "normal",
  "rrule": ""
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `title` | string | ✅ | 提醒标题 |
| `trigger_time` | string | ✅ | 触发时间（ISO 8601，如 `2026-02-10T13:30:00`） |
| `content` | string | ❌ | 提醒内容 |
| `priority` | string | ❌ | 优先级：`low` / `medium` / `high` / `critical` |
| `rrule` | string | ❌ | 重复规则（RFC 5545），空字符串表示单次提醒 |

---

### 更新提醒（单次或将单次转为重复）

**POST** `/api/reminders/update/`

**请求体：**
```json
{
  "id": 5,
  "title": "新标题",
  "priority": "high",
  "status": "completed"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | integer | ✅ | 提醒 ID |
| `title` / `content` / `trigger_time` / `priority` / `status` / `rrule` | - | ❌ | 要更新的字段 |
| `rrule_change_scope` | string | ❌ | 将单次提醒转为重复提醒时填 `"all"` |

> ⚠️ 此接口仅适用于**单次提醒**的更新，或将单次提醒转为重复提醒。**复杂的重复提醒编辑**请使用 `/api/reminders/bulk-edit/`。对重复提醒单例使用此接口会导致未知后果。

---

### 更新提醒状态

**POST** `/api/reminders/update-status/`

**请求体：**
```json
{
  "id": 5,
  "status": "snoozed_15m",
  "snooze_until": "2026-02-10T11:00:00"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | integer | ✅ | 提醒 ID |
| `status` | string | ✅ | 参见下方状态值说明 |
| `snooze_until` | string | ❌ | 延后到的时间（status 为 `snoozed_custom` 时使用） |

**`status` 可选值：**

| 值 | 说明 |
|----|------|
| `active` | 重新激活（已暂停/忽略后恢复） |
| `completed` | 标记为已完成 |
| `dismissed` | 忽略此次提醒 |
| `snoozed_15m` | 延后 15 分钟 |
| `snoozed_1h` | 延后 1 小时 |
| `snoozed_1d` | 延后 1 天 |
| `snoozed_custom` | 延后到自定义时间（需同时提供 `snooze_until`） |

---

### 批量编辑重复提醒

**POST** `/api/reminders/bulk-edit/`

用于对重复提醒系列进行精细化编辑或删除，支持多种作用范围。

**请求体公共字段：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `operation` | string | ✅ | `edit`（编辑）或 `delete`（删除） |
| `reminder_id` | integer | ✅ | 目标提醒实例 ID |
| `series_id` | integer | ✅ | 系列 ID |
| `edit_scope` | string | ✅ | `single` / `all` / `from_this` / `from_time` |

**`edit_scope` 行为：**

| 值 | 行为 |
|----|------|
| `single` | 将该实例从系列中独立出来（单独修改，不影响其他实例） |
| `all` | 修改/删除整个系列的所有实例 |
| `from_this` | 修改/删除该实例及之后的所有实例 |
| `from_time` | 从指定 `from_time`（ISO 8601）开始，创建新系列并截断旧系列 |

---

### 删除提醒

**POST** `/api/reminders/delete/`

> ⚠️ 使用 HTTP **POST**（不是 DELETE），ID 放在请求体中。

**请求体：**
```json
{
  "id": 5
}
```

> 此接口仅适用于单次提醒。重复提醒系列删除请使用 `/api/reminders/bulk-edit/`（`operation: "delete"`）。

---

## Quick Action API - 智能操作

基于 LangGraph 状态机的 AI 智能操作接口，接受自然语言指令，自动执行日程/待办操作。

> **认证要求**: 需要 Token  
> **输入方式**: 文字（JSON）或音频文件（multipart/form-data），二选一

---

### 创建快速操作任务

**POST** `/api/agent/quick-action/`

#### 文字输入（JSON）

**Content-Type**: `application/json`

```json
{
  "text": "明天下午三点开会，讨论项目进度",
  "sync": false,
  "timeout": 30
}
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `text` | string | ✅* | — | 自然语言指令（最多1000字符）。与 `audio` 二选一 |
| `sync` | boolean | ❌ | `false` | `true` 同步等待结果，`false` 异步返回 task_id |
| `timeout` | integer | ❌ | `30` | 同步模式最大等待时长（秒） |

#### 音频输入（multipart/form-data）

**Content-Type**: `multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `audio` | file | ✅* | 音频文件，≤60s，≤15MB。与 `text` 二选一 |
| `sync` | string | ❌ | 表单字段，`"true"` 或 `"false"` |
| `timeout` | string | ❌ | 表单字段，超时秒数字符串 |

**支持音频格式**: `wav` / `mp3` / `ogg` / `flac` / `webm` / `aac` / `m4a` / `amr`

> ⚠️ `text` 和 `audio` 不可同时提供，也不可都不提供，否则返回 400 错误。

#### 响应（异步模式，**201**）

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "input_type": "text",
  "created_at": "2026-02-10T14:00:00"
}
```

#### 响应（同步模式，200）

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "success",
  "result_type": "action_completed",
  "input_type": "audio",
  "result": {
    "message": "✅ 已创建新日程：明天 15:00-16:00「开会」",
    "tool_calls": [
      {
        "tool": "create_event",
        "args": { "title": "开会", "start": "2026-02-11T15:00:00", "end": "2026-02-11T16:00:00" },
        "result": { "event_id": 42 }
      }
    ]
  },
  "execution_time_ms": 1872,
  "tokens": {
    "input": 280,
    "output": 94,
    "cost": 0.0023,
    "model": "gpt-4o-mini"
  }
}
```

#### 错误响应

| HTTP 状态码 | 响应 `code` 字段 | 场景 |
|------------|-------------|------|
| 400 | `AMBIGUOUS_INPUT` | 同时提供了 `text` 和 `audio` |
| 400 | `EMPTY_INPUT` | `text` 和 `audio` 均未提供 |
| 400 | `TEXT_TOO_LONG` | 文字超过1000字符 |
| 400 | `UNSUPPORTED_AUDIO_FORMAT` | 音频格式不支持 |
| 400 | `AUDIO_TOO_LARGE` | 音频超过15MB |
| 422 | `SPEECH_RECOGNITION_FAILED` | 语音识别全部失败（百度 + 本地均不可用） |
| 422 | `EMPTY_SPEECH_RESULT` | 识别成功但结果为空（无法理解语音内容） |

---

### 查询任务状态

**GET** `/api/agent/quick-action/<task_id>/`

**查询参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `wait` | boolean | `true` 启用长轮询（最多等 30 秒），避免频繁轮询 |

**响应（200）：**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "success",
  "result_type": "action_completed",
  "result": { "message": "✅ 已创建新日程...", "tool_calls": [] },
  "input_text": "明天下午三点开会",
  "input_type": "text",
  "execution_time_ms": 1872,
  "created_at": "2026-02-10T14:00:00",
  "completed_at": "2026-02-10T14:00:02"
}
```

**任务状态值：**

| 状态 | 说明 |
|------|------|
| `pending` | 等待执行 |
| `processing` | 执行中 |
| `success` | 执行成功 |
| `failed` | 执行失败 |
| `timeout` | 同步模式超时 |

---

### 获取历史任务列表

**GET** `/api/agent/quick-action/list/`

**查询参数：**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `limit` | integer | 20 | 返回数量（最大100） |
| `offset` | integer | 0 | 偏移量 |
| `status` | string | — | 按状态筛选 |
| `days` | integer | 7 | 查最近 N 天 |

**响应（200）：**
```json
{
  "count": 42,
  "limit": 20,
  "offset": 0,
  "tasks": [
    {
      "task_id": "550e8400-...",
      "status": "success",
      "result_type": "action_completed",
      "input_text": "明天下午三点开会",
      "input_type": "text",
      "created_at": "2026-02-10T14:00:00",
      "execution_time_ms": 1872,
      "result_preview": "✅ 已创建新日程..."
    }
  ]
}
```

---

### 取消任务

**DELETE** `/api/agent/quick-action/<task_id>/cancel/`

只能取消状态为 `pending` 的任务。

**响应（200）：**
```json
{
  "message": "任务已取消"
}
```

**失败（400）：**
```json
{
  "error": "只能取消待执行的任务",
  "current_status": "processing"
}
```

---

### 结果类型说明

| `result_type` | 含义 | 建议处理 |
|--------------|------|----------|
| `action_completed` | 操作已成功执行 | 直接展示 `result.message` |
| `need_clarification` | 找到多个匹配项，需用户澄清 | 展示提示，引导用户补充说明 |
| `error` | 操作无法完成 | 展示错误信息，提示用户修改指令 |

---

## Speech-to-Text API - 语音转文字

独立的语音识别接口，**无需任何认证**。

---

### 语音转文字

**POST** `/api/agent/speech-to-text/`

**认证**: 无需（`AllowAny`）  
**Content-Type**: `multipart/form-data`

**请求字段：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `audio` | file | ✅ | 音频文件 |

**限制：**
- 最大文件大小：15 MB
- 最大音频时长：60 秒
- 支持格式：`wav` / `mp3` / `ogg` / `flac` / `webm` / `aac` / `m4a` / `amr`

**成功响应（200）：**
```json
{
  "success": true,
  "text": "明天下午三点开会",
  "duration_seconds": 3.2,
  "provider": "baidu",
  "filename": "voice.wav"
}
```

| 字段 | 说明 |
|------|------|
| `text` | 识别到的文字 |
| `duration_seconds` | 音频时长（秒） |
| `provider` | 识别来源：`baidu` 或 `faster_whisper` |
| `filename` | 上传的文件名 |

**错误响应（无 `error_code` 字段）：**

| HTTP 状态码 | 触发场景 |
|------------|---------|
| 400 | 缺少 `audio` 字段 |
| 400 | 不支持的音频格式 |
| 400 | 文件超过 15MB |
| 422 | 识别失败（含超过60s、识别引擎异常等） |
| 500 | 服务器内部错误 |

**curl 示例：**
```bash
curl -X POST http://127.0.0.1:8000/api/agent/speech-to-text/ \
  -F "audio=@/path/to/voice.wav"
```

**Python 示例：**
```python
import requests

with open("voice.wav", "rb") as f:
    resp = requests.post(
        "http://127.0.0.1:8000/api/agent/speech-to-text/",
        files={"audio": ("voice.wav", f, "audio/wav")}
    )

data = resp.json()
if data["success"]:
    print(f"识别结果: {data['text']}")
    print(f"时长: {data['duration_seconds']}s，来源: {data['provider']}")
else:
    print(f"识别失败: {resp.status_code} - {data.get('error')}")
```

---

### 识别降级链

系统按以下优先级自动选择识别方式：

```
百度 VOP pro_api（Bearer Token 认证）
    ↓ 失败或不可用
faster-whisper tiny（本地 CPU 推理）
    ↓ 失败
返回 422 错误
```

**配置位置**: `config/api_keys.json` → `speech_services`

> ⚠️ 修改 `api_keys.json` 后必须重启 Django 服务，配置仅在进程启动时加载一次。

---

## 错误码参考

### 通用错误

| HTTP 状态码 | 说明 |
|------------|------|
| 400 | 请求参数错误 |
| 401 | 未认证或 Token 无效 |
| 403 | 无权限访问该资源 |
| 404 | 资源不存在 |
| 405 | HTTP 方法不允许 |
| 500 | 服务器内部错误 |

### Quick Action 专属错误码

错误响应中，错误码字段名为 **`code`**（不是 `error_code`）。

| `code` | HTTP | 说明 | 解决方法 |
|-------------|------|------|----------|
| `AMBIGUOUS_INPUT` | 400 | 同时提供文字和音频 | 二选一 |
| `EMPTY_INPUT` | 400 | 未提供任何输入 | 添加 `text` 或 `audio` |
| `TEXT_TOO_LONG` | 400 | 文字 > 1000字符 | 压缩文字长度 |
| `UNSUPPORTED_AUDIO_FORMAT` | 400 | 不支持的音频格式 | 使用 wav/mp3/ogg 等 |
| `AUDIO_TOO_LARGE` | 400 | 音频 > 15MB | 压缩或剪短音频 |
| `SPEECH_RECOGNITION_FAILED` | 422 | 语音识别全部失败 | 检查服务配置，重启服务 |
| `EMPTY_SPEECH_RESULT` | 422 | 识别结果为空 | 检查音频内容是否包含语音 |

### Speech-to-Text 专属错误码

语音转文字接口的错误响应内容为 `{ "success": false, "error": "错误描述" }`，无字符串错误码字段。

| HTTP 状态码 | 触发条件 | 解决方法 |
|------------|-------------|----------|
| 400 | 缺少 `audio` 字段 | 使用 `multipart/form-data` 上传 |
| 400 | 音频格式不支持 | 使用 wav/mp3/ogg/flac 等 |
| 400 | 文件 > 15MB | 压缩或分割文件 |
| 422 | 识别失败（含超过60秒、识别引擎异常等） | 检查语音服务配置 |
| 500 | 内部异常 | 查看服务器日志 |

---

*文档版本 1.6.3 | 最后更新 2026-02-22*
