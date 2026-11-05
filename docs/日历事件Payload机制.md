# 日历事件可扩展 Payload 机制

> 状态：首期实现（Planner V2 / normalized ORM）。分支：`feature/event-payload`。
> 本文同时是统一注册名表、schema 维护说明和客户端接入契约。

## 1. 目标与边界

每个 `CalendarEvent` 可携带一个可选的 `payload`，用于让不同软件在**不修改核心日历模型**的前提下附加自己的扩展数据。Key 是统一维护的注册名，Value 是该注册名对应的负载：

```json
{
  "event_id": "evt-...",
  "title": "每周例会",
  "start": "2026-05-01T01:00:00+00:00",
  "end": "2026-05-01T02:00:00+00:00",
  "payload": {
    "org.uss.scheduler": {
      "format": "json",
      "data": {"source": "web", "kind": "sync"},
      "version": 1
    },
    "com.acme.notes": {
      "format": "json",
      "data": {"thread_id": "t-42", "labels": ["work"]}
    }
  }
}
```

首期明确：

- 只支持 **map/dict** 形式，不支持数组形式；Key 在整个事件内唯一。
- 核心系统只做结构、大小、格式和已注册 schema 的基础校验，不解释任何注册方的业务字段。
- 核心日历 UI、iCalendar Feed 和 CalDAV 资源**不展示、不导出** Payload；它们是 USS API 的扩展数据。
- 未知注册名、未知格式原样保留；某个 Key 的数据不会影响其他 Key 或基础日历功能。
- 不实现复杂权限、加密、跨软件协商；Payload 与事件同属一个用户资源，沿用事件本身的鉴权。

## 2. 数据结构

`CalendarEvent.payload` 是 normalized ORM 的 `JSONField`，默认 `{}`。

```
payload: dict[str, PayloadEntry]

PayloadEntry = {
    "format": "json",    # 必填，小写 token，例如 json、xml、yaml
    "data": {...},       # 必填，任意合法 JSON 值；具体语义由注册方定义
    "version": 1         # 可选，正整数；给注册方做 Payload 版本迁移用
}
```

规则：

| 项目 | 规则 |
|---|---|
| `payload` 本身 | 必须是 JSON object；`null` 等价于 `{}` |
| Key | 非空字符串，建议域名倒序；允许 `A-Z a-z 0-9 . _ -`，首尾必须是字母或数字；最长 128 字符（可配置） |
| Entry | 只允许 `format`、`data`、`version` 三个字段，其他字段返回 `422 payload_entry_invalid` |
| `format` | 非空字符串，归一化为小写；允许 `json`、`xml`、`yaml` 等 token；未知格式透传 |
| `data` | 必须存在且可序列化为 JSON；未知格式不尝试解析 |
| `version` | 可选正整数（`true`/`false`、`0`、负数均拒绝）；当前只保存，不参与 schema 选择 |
| 空数据 | 创建/更新时省略 `payload` 或传 `{}`，事件仍正常可用 |

数组形式（例如 `[{key, format, data}]`）本期不实现。若未来需要传输层数组，应在客户端/协议层转换后再写入同一个 map，不改变服务端事实源。

## 3. 统一注册名表

注册名使用稳定、全局可辨识的命名，推荐域名倒序，例如 `org.uss.scheduler`、`com.example.calendar`。注册名表与 schema 均在代码仓库中维护：

- 注册表：`core/planner/payloads.py` 的 `_PAYLOAD_REGISTRATIONS`
- schema：`core/planner/payload_schemas/*.json`

当前登记：

| 注册名 | 归属方 | 说明 | 格式 | Schema | Schema 版本 |
|---|---|---|---|---|---|
| `org.uss.scheduler` | UniSchedulerSuper | USS 保留的日程扩展负载；首期要求 `data` 为 JSON object | `json` | `core/planner/payload_schemas/org.uss.scheduler.json` | 1 |

未登记的 Key 不报错、不丢弃，按原值保存和返回；核心不会对其做 schema 校验。不同软件只读取自己注册名下的数据，不应解析其他 Key。

### 新增注册名流程

1. 在 `_PAYLOAD_REGISTRATIONS` 增加 `PayloadRegistration`：
   - `key`：注册名；
   - `owner`：归属方；
   - `description`：用途说明；
   - `formats`：该注册方声明支持的格式（当前用于决定是否执行 JSON Schema 校验）；
   - `schema_filename`：可选；需要可选校验时提供；
   - `schema_version`：schema 版本。
2. 如需校验，在 `core/planner/payload_schemas/` 新增 JSON Schema 文件。
3. 更新本文第 3 节的登记表。
4. 在 `core/tests/test_planner_event_payload.py` 增加该注册名的正常/异常用例。
5. 通过代码评审和迁移检查；注册表变更本身不需要数据库迁移。

命名要求：注册名必须全局唯一；建议由归属方使用自己控制的域名倒序，避免抢占他人命名空间。改名视为破坏性变更，应保留旧 Key 的读取兼容或提供数据迁移脚本，不得静默重命名。

## 4. schema 校验

已注册 Key 且 `format` 在 `formats` 中时，服务端使用对应 JSON Schema 校验 `data`：

- 校验失败：拒绝写入，返回 `422 payload_schema_violation`，消息包含首个/前几个错误路径。
- 未注册 Key：跳过 schema 校验，透传。
- 已注册 Key 但使用未声明格式：跳过 schema 校验，透传（例如注册方尚未支持的 `xml`）。
- schema 是可选能力；没有 `schema_filename` 的注册名只做结构/大小校验。

内置校验器支持 JSON Schema 的常用子集：`type`、`properties`、`required`、`additionalProperties`、`patternProperties`、`items`、`enum`、`const`、`allOf`/`anyOf`/`oneOf`/`not`、字符串/数值/数组/对象数量与边界、本地 `#/$defs` 与 `#/definitions` 引用。`format`（date-time、email 等）只作为文档，不做语义校验，避免引入额外依赖。

校验失败策略采用“拒绝写入”，避免无效扩展数据进入事实源。未知 Key/未知格式仍按 Issue 的兼容性要求透传保留。

## 5. 查询与写入行为

### 写入

- `POST /api/v2/events/`：可携带一个或多个注册名的 Payload。
- `PATCH /api/v2/events/<event_id>/`：仅 `scope=all` 可写 `payload`；写入是**整体替换**该事件的 payload map，不自动合并旧 Key。客户端需先读取再提交完整 map，或明确只提交期望保留的 Key。
- `PATCH` 的 `scope=single` / `this_and_future` 携带 `payload` 返回 `422 payload_scope_not_supported`。
- `payload: {}` 或 `payload: null` 清空全部扩展数据。
- 重复系列：Payload 属于 master，所有 occurrence 继承；`this_and_future` 分裂出的新 master 和 `single` detach 出的独立事件都会复制原 master 的 Payload。

### 查询

以下事件读取接口默认返回 `payload`：

- `GET /api/v2/events/definitions/`
- `GET /api/v2/events/occurrences/`
- `GET /api/v2/events/conflicts/`
- `GET /api/v2/search/`（`entity_type=event` 的结果）
- `GET /api/v2/share-groups/<share_group_id>/occurrences/`

可通过查询参数关闭：

```
?include_payload=0
```

接受 `0/1`、`false/true`、`no/yes`（大小写不敏感）。其他值返回 `422 invalid_include_payload`。

`include_payload=0` 时响应中不出现 `payload` 字段；默认/显式开启时，无扩展数据的事件返回 `"payload": {}`，便于客户端保持稳定结构。

### 示例

创建：

```http
POST /api/v2/events/
Content-Type: application/json

{
  "title": "带扩展数据的例会",
  "start": "2026-05-01T09:00:00+08:00",
  "end": "2026-05-01T10:00:00+08:00",
  "payload": {
    "org.uss.scheduler": {
      "format": "json",
      "data": {"source": "web"}
    },
    "com.acme.notes": {
      "format": "json",
      "data": {"thread_id": "t-42"}
    }
  }
}
```

更新（`scope=all`，整体替换）：

```http
PATCH /api/v2/events/<event_id>/
Content-Type: application/json

{
  "expected_version": 2,
  "scope": "all",
  "payload": {
    "com.acme.notes": {
      "format": "json",
      "data": {"thread_id": "t-43"},
      "version": 2
    }
  }
}
```

查询并关闭 Payload：

```http
GET /api/v2/events/occurrences/?from=2026-05-01&to=2026-05-02&include_payload=0
```

## 6. 基础限制

默认限制如下，可通过 settings / 环境变量覆盖：

| 限制 | 默认值 | settings | 环境变量 |
|---|---:|---|---|
| 注册名数量 | 16 | `PLANNER_EVENT_PAYLOAD_MAX_KEYS` | `PLANNER_EVENT_PAYLOAD_MAX_KEYS` |
| 总大小 | 64 KiB | `PLANNER_EVENT_PAYLOAD_MAX_TOTAL_BYTES` | `PLANNER_EVENT_PAYLOAD_MAX_TOTAL_BYTES` |
| 单个 Key 大小 | 32 KiB | `PLANNER_EVENT_PAYLOAD_MAX_ENTRY_BYTES` | `PLANNER_EVENT_PAYLOAD_MAX_ENTRY_BYTES` |
| Key 长度 | 128 字符 | `PLANNER_EVENT_PAYLOAD_MAX_KEY_LENGTH` | `PLANNER_EVENT_PAYLOAD_MAX_KEY_LENGTH` |

大小按 UTF-8、minified JSON（`ensure_ascii=False`）计算。超限返回 `422 payload_too_large`，不会部分写入。

## 7. 错误码

| code | HTTP | 含义 |
|---|---:|---|
| `invalid_payload` | 422 | `payload` 不是 JSON object |
| `payload_key_invalid` | 422 | Key 为空、超长或字符不合法 |
| `payload_entry_invalid` | 422 | Entry 结构、`format`、`data`、`version` 不合法 |
| `invalid_payload_data` | 422 | `data` 无法序列化为合法 JSON |
| `payload_too_large` | 422 | Key 数量、总大小或单 Key 大小超限 |
| `payload_schema_violation` | 422 | 已注册 Key 的 `data` 不符合 schema |
| `payload_scope_not_supported` | 422 | 在 `single`/`this_and_future` scope 写 Payload |

上述错误均在事务内发生，事件不会产生半写入；其他注册名和基础日历字段不受影响。

## 8. 兼容性

- 旧客户端忽略 `payload` 字段即可；不发送时事件行为与之前完全一致。
- 不支持 Payload 的客户端读取到该字段时应忽略，不应因未知 Key 报错。
- 未知注册名、未知格式不会被核心拒绝或清洗。
- Feed/CalDAV 首期不导出 Payload；通过 CalDAV 写入的事件 `payload` 为空 map。
- Agent/MCP/Quick Action 通过 Application Service 读取事件时，默认结果中同样携带 `payload`；工具若不使用可忽略。

## 9. 待讨论项的当前决策

| 待讨论 | 当前决策 |
|---|---|
| map 还是数组 | 首期只支持 map；数组仅作为未来传输层备选 |
| 查询默认返回还是显式请求 | 默认返回，`include_payload=0` 可关闭 |
| schema 校验失败策略 | 已注册 Key 拒绝写入（422）；未知 Key/格式透传 |
| 大小限制 | 16 Key / 64 KiB / 32 KiB / 128 字符，可配置 |
| 注册名维护流程 | 代码注册表 + JSON Schema 文件 + 本文登记表，走代码评审 |
| Payload 版本与迁移 | Entry 可选 `version`，当前只保存不分支；schema 使用注册表当前版本，后续可扩展 `schema_versions` 或迁移脚本 |

## 10. 测试

主要覆盖位于 `core/tests/test_planner_event_payload.py`：

- 两个注册名同时存在且互不干扰；
- 无 Payload 事件的创建、查询、更新；
- 未知注册名/未知格式透传；
- 查询 `include_payload` 开关；
- 已注册 schema 失败无副作用；
- Key 数量、单 Key/总大小、Key 长度限制；
- 重复 series 的 occurrence 继承与 scope 限制；
- JSON Schema 校验器子集。
