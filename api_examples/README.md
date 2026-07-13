# UniScheduler API 示例

本目录以 2026-07-13 的 P1–P6 接口代码为准。Planner（日程、个人日程组、待办、提醒、共享日程读取）只演示 `/api/v2/`；旧 Planner V1 URL 已返回 `410 Gone`，不会再读写封存的 JSON。

## 文件

| 文件 | 内容 |
|---|---|
| `QUICKSTART.md` | 最短可运行流程 |
| `API_REFERENCE.md` | 当前契约、字段、禁止规则、错误码和 V1 迁移表 |
| `README_QUICK_ACTION.md` | Quick Action、语音输入与 Planner V2 关系 |
| `client.py` | 示例共用的 Token 客户端 |
| `example_events_api.py` | Event 创建、窗口读取、single 修改、all 删除 |
| `example_eventgroups_api.py` | 个人 Event Group CRUD |
| `example_todos_api.py` | Todo CRUD 与 Todo→Event 原子转换 |
| `example_reminders_api.py` | 重复 Reminder、occurrence action 与 scope |
| `example_quick_action_api.py` | Quick Action 文字/音频、同步/异步 |
| `simple_quick_action_test.py` | 最短只读 Quick Action smoke |
| `example_parser_api.py` | 公开语音转文字 |
| `example_calendar_protocols.py` | Feed 与 CalDAV 只读发现 smoke |
| `test_token_auth.py` | Token + Planner V2 只读 smoke |

## 运行

PowerShell：

```powershell
$env:UNISCHEDULER_BASE_URL = 'http://127.0.0.1:8000'
$env:UNISCHEDULER_USERNAME = 'your-user'
$env:UNISCHEDULER_PASSWORD = 'your-password'

.venv\Scripts\python.exe api_examples\test_token_auth.py
.venv\Scripts\python.exe api_examples\example_events_api.py
.venv\Scripts\python.exe api_examples\example_calendar_protocols.py
```

不要把真实账号、密码或 Token 写回示例文件。外部客户端使用 `Authorization: Token <token>`；浏览器 Session 写请求仍需 CSRF。

## 最重要的 V2 规则

- Event/Reminder 的无限 RRULE 只保存主对象和规则，必须用有界 `from`/`to` 展开；不得期待服务端返回“全部实例”。
- `occurrence.id` 仅是列表 key，写入重复实例必须原样回传 `occurrence_ref`。
- PATCH/DELETE/Todo 转换必须带最新 `expected_version`；过期版本返回 `409 version_conflict`，客户端应重新读取，不能盲重试。
- scope 只有 `single`、`all`、`this_and_future`。后两者对重复系列有专门约束，详见接口参考。
- V2 字段使用 `group_id`、`trigger`、`due`、`recurrence: {rrule: ...}`；旧字段 `groupID`、`trigger_time`、`due_date`、顶层 `rrule` 不会兼容转换，而会返回 `422 unsupported_field`。
- V1 端点返回 `410 planner_v1_api_retired`。这不是临时错误；重试不会成功，也不会修改任何数据。

完整说明见 [API_REFERENCE.md](API_REFERENCE.md)。

**文档版本：2.0.0｜最后更新：2026-07-13**
