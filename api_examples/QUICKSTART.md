# UniScheduler API 快速开始

## 1. 启动服务并配置凭据

```powershell
.venv\Scripts\python.exe manage.py runserver

$env:UNISCHEDULER_BASE_URL = 'http://127.0.0.1:8000'
$env:UNISCHEDULER_USERNAME = 'your-user'
$env:UNISCHEDULER_PASSWORD = 'your-password'
```

账号必须已进入 normalized cohort。若 V2 返回 `409 planner_normalized_*_not_enabled`，这是服务端准入配置问题，不能改用 V1 绕过。

## 2. 先运行只读 smoke

```powershell
.venv\Scripts\python.exe api_examples\test_token_auth.py
```

它会验证 Token、读取 cohort bootstrap，并在一个明确时间窗内读取 Event occurrence。

## 3. 第一个 V2 Event

```python
import requests

base = "http://127.0.0.1:8000"
token = requests.post(
    f"{base}/api/auth/login/",
    json={"username": "your-user", "password": "your-password"},
).json()["token"]
headers = {"Authorization": f"Token {token}"}

created = requests.post(
    f"{base}/api/v2/events/",
    headers=headers,
    json={
        "title": "接口示例",
        "start": "2026-07-14T10:00:00+08:00",
        "end": "2026-07-14T11:00:00+08:00",
        "tzid": "Asia/Shanghai",
        "recurrence": {"rrule": "FREQ=WEEKLY;COUNT=4"},
    },
)
created.raise_for_status()
event = created.json()["event"]

rows = requests.get(
    f"{base}/api/v2/events/occurrences/",
    headers=headers,
    params={"from": "2026-07-01", "to": "2026-09-01"},
)
rows.raise_for_status()
print(rows.json())
```

创建返回的是 definition；日历显示应读取 occurrences。`from`/`to` 是半开窗口 `[from, to)`，必须同时提供。

## 4. 修改必须携带版本

```python
ref = rows.json()["occurrences"][0]["occurrence_ref"]
response = requests.patch(
    f"{base}/api/v2/events/{ref['entity_id']}/",
    headers=headers,
    json={
        "scope": "single",
        "occurrence_ref": ref,
        "expected_version": ref["source_version"],
        "description": "仅修改这一回",
    },
)
response.raise_for_status()
```

写下一次之前重新读取。不要缓存旧 `source_version`，不要用 occurrence 的复合 `id` 代替 `entity_id`。

## 5. 运行其他示例

```powershell
.venv\Scripts\python.exe api_examples\example_eventgroups_api.py
.venv\Scripts\python.exe api_examples\example_todos_api.py
.venv\Scripts\python.exe api_examples\example_reminders_api.py
.venv\Scripts\python.exe api_examples\example_quick_action_api.py
.venv\Scripts\python.exe api_examples\example_parser_api.py path\to\audio.wav
```

Event/Group/Todo/Reminder 示例会创建测试数据，并在正常完成时清理。中途终止可能留下带“API 示例”标题的数据，请在 UI 或 V2 API 中清理。

**文档版本：2.0.0｜最后更新：2026-07-13**
