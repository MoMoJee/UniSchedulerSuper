"""Planner V2 Todo CRUD and Todo-to-Event conversion example."""

from datetime import datetime, timedelta, timezone

from client import authenticated_client


TZ8 = timezone(timedelta(hours=8))


def main() -> None:
    client = authenticated_client()
    due = (datetime.now(TZ8) + timedelta(days=2)).replace(hour=18, minute=0, second=0, microsecond=0)
    todo = client.json(
        "POST",
        "/api/v2/todos/",
        json={
            "title": "API 示例待办",
            "description": "演示 version 并发控制",
            "due": due.isoformat(),
            "tzid": "Asia/Shanghai",
            "importance": "important",
            "urgency": "not-urgent",
            "tags": ["api", "example"],
        },
    )["todo"]
    print("created:", todo)

    todo = client.json(
        "PATCH",
        f"/api/v2/todos/{todo['todo_id']}/",
        json={"expected_version": todo["version"], "status": "completed"},
    )["todo"]
    print("updated:", todo)

    # 另建一个待办演示原子转换；同一 todo 不能转换两次。
    convertible = client.json("POST", "/api/v2/todos/", json={"title": "待转换示例"})["todo"]
    start = due.replace(hour=14)
    converted = client.json(
        "POST",
        f"/api/v2/todos/{convertible['todo_id']}/convert/",
        json={
            "expected_version": convertible["version"],
            "start": start.isoformat(),
            "end": (start + timedelta(hours=1)).isoformat(),
            "tzid": "Asia/Shanghai",
        },
    )
    print("converted:", converted)

    client.json(
        "DELETE", f"/api/v2/todos/{todo['todo_id']}/",
        json={"expected_version": todo["version"]},
    )
    converted_todo = converted["todo"]
    client.json(
        "DELETE", f"/api/v2/todos/{converted_todo['todo_id']}/",
        json={"expected_version": converted_todo["version"]},
    )
    client.json(
        "DELETE", f"/api/v2/events/{converted['event_id']}/",
        json={"scope": "all", "expected_version": converted["event_version"]},
    )


if __name__ == "__main__":
    main()
