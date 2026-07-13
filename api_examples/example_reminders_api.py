"""Planner V2 recurring Reminder scope and action example."""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from client import authenticated_client


TZ8 = timezone(timedelta(hours=8))


def main() -> None:
    client = authenticated_client()
    trigger = (datetime.now(TZ8) + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    reminder = client.json(
        "POST",
        "/api/v2/reminders/",
        json={
            "title": "API 示例重复提醒",
            "content": "脚本结束时会清理",
            "trigger": trigger.isoformat(),
            "tzid": "Asia/Shanghai",
            "priority": "normal",
            "recurrence": {"rrule": "FREQ=DAILY;COUNT=3"},
        },
    )["reminder"]
    reminder_id = reminder["reminder_id"]
    print("created:", reminder)

    query = urlencode({
        "from": (trigger - timedelta(days=1)).isoformat(),
        "to": (trigger + timedelta(days=5)).isoformat(),
    })

    def rows():
        return [
            item for item in client.json("GET", f"/api/v2/reminders/?{query}")["occurrences"]
            if item["occurrence_ref"]["entity_id"] == reminder_id
        ]

    target = rows()[1]["occurrence_ref"]
    client.json(
        "PATCH",
        f"/api/v2/reminders/{reminder_id}/",
        json={
            "scope": "single",
            "occurrence_ref": target,
            "expected_version": target["source_version"],
            "content": "仅第二次 occurrence 的内容",
        },
    )
    print("patched single occurrence")

    action_ref = rows()[0]["occurrence_ref"]
    action = client.json(
        "POST",
        "/api/v2/reminders/occurrences/action/",
        json={
            "action": "complete",
            "occurrence_ref": action_ref,
            "expected_version": action_ref["source_version"],
        },
    )
    print("completed occurrence:", action)

    fresh = rows()[0]["occurrence_ref"]
    deleted = client.json(
        "DELETE",
        f"/api/v2/reminders/{reminder_id}/",
        json={"scope": "all", "expected_version": fresh["source_version"]},
    )
    print("deleted series:", deleted)


if __name__ == "__main__":
    main()
