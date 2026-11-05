"""Planner V2 Event 扩展 Payload 的可运行示例。

演示两个注册名并存、默认查询返回、include_payload=0 关闭、scope=all 整体
替换，以及脚本结束时清理测试事件。
"""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from client import authenticated_client


TZ8 = timezone(timedelta(hours=8))


def iso(day_offset: int, hour: int) -> str:
    value = datetime.now(TZ8).replace(hour=hour, minute=0, second=0, microsecond=0)
    return (value + timedelta(days=day_offset)).isoformat()


def main() -> None:
    client = authenticated_client()
    start, end = iso(1, 14), iso(1, 15)
    window_start, window_end = iso(0, 0), iso(3, 0)
    query = urlencode({"from": window_start, "to": window_end})

    created = client.json(
        "POST",
        "/api/v2/events/",
        json={
            "title": "API V2 Payload 示例",
            "start": start,
            "end": end,
            "tzid": "Asia/Shanghai",
            "payload": {
                "org.uss.scheduler": {
                    "format": "json",
                    "data": {"source": "example", "kind": "demo"},
                },
                "com.example.calendar": {
                    "format": "json",
                    "data": {"external_id": "demo-42"},
                    "version": 1,
                },
            },
        },
    )
    event = created["event"]
    event_id = event["event_id"]
    print("created payload:", event["payload"])

    definitions = client.json("GET", f"/api/v2/events/definitions/?{query}")
    definition = next(item for item in definitions["definitions"] if item["event_id"] == event_id)
    print("definition payload:", definition["payload"])

    without_payload = client.json(
        "GET", f"/api/v2/events/occurrences/?{query}&include_payload=0"
    )
    occurrence = next(
        item for item in without_payload["occurrences"]
        if item["occurrence_ref"]["entity_id"] == event_id
    )
    assert "payload" not in occurrence
    print("include_payload=0 omitted payload")

    updated = client.json(
        "PATCH",
        f"/api/v2/events/{event_id}/",
        json={
            "scope": "all",
            "expected_version": event["version"],
            "payload": {
                "com.example.calendar": {
                    "format": "json",
                    "data": {"external_id": "demo-43"},
                    "version": 2,
                },
            },
        },
    )
    print("patched source_version:", updated["source_version"])

    fresh = client.json("GET", f"/api/v2/events/occurrences/?{query}&include_payload=1")
    current = next(
        item for item in fresh["occurrences"]
        if item["occurrence_ref"]["entity_id"] == event_id
    )
    print("occurrence payload after replace:", current["payload"])
    assert "org.uss.scheduler" not in current["payload"]

    deleted = client.json(
        "DELETE",
        f"/api/v2/events/{event_id}/",
        json={"scope": "all", "expected_version": current["occurrence_ref"]["source_version"]},
    )
    print("deleted:", deleted["event_id"])


if __name__ == "__main__":
    main()
