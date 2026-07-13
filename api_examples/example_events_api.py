"""Planner V2 Event API runnable example.

Creates a finite series, exercises single/all scopes, then removes it.  The
example deliberately obtains ``occurrence_ref`` and ``source_version`` from a
fresh bounded read before each write.
"""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from client import authenticated_client


TZ8 = timezone(timedelta(hours=8))


def iso(day_offset: int, hour: int) -> str:
    value = datetime.now(TZ8).replace(hour=hour, minute=0, second=0, microsecond=0)
    return (value + timedelta(days=day_offset)).isoformat()


def occurrences(client, start: str, end: str) -> list[dict]:
    query = urlencode({"from": start, "to": end})
    return client.json("GET", f"/api/v2/events/occurrences/?{query}")["occurrences"]


def main() -> None:
    client = authenticated_client()
    start, end = iso(1, 10), iso(1, 11)
    window_start, window_end = iso(0, 0), iso(8, 0)

    created = client.json(
        "POST",
        "/api/v2/events/",
        json={
            "title": "API V2 示例系列",
            "description": "脚本结束时会清理",
            "start": start,
            "end": end,
            "tzid": "Asia/Shanghai",
            "recurrence": {"rrule": "FREQ=DAILY;COUNT=3"},
        },
    )
    event_id = created["event"]["event_id"]
    print("created:", created)

    rows = [
        item for item in occurrences(client, window_start, window_end)
        if item["occurrence_ref"]["entity_id"] == event_id
    ]
    target = rows[1]["occurrence_ref"]
    patched = client.json(
        "PATCH",
        f"/api/v2/events/{event_id}/",
        json={
            "scope": "single",
            "occurrence_ref": target,
            "expected_version": target["source_version"],
            "description": "只修改第二次 occurrence",
        },
    )
    print("patched single:", patched)

    fresh = next(
        item["occurrence_ref"] for item in occurrences(client, window_start, window_end)
        if item["occurrence_ref"]["entity_id"] == event_id
    )
    deleted = client.json(
        "DELETE",
        f"/api/v2/events/{event_id}/",
        json={"scope": "all", "expected_version": fresh["source_version"]},
    )
    print("deleted series:", deleted)


if __name__ == "__main__":
    main()
