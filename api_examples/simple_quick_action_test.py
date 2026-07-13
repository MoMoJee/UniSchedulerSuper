"""Minimal synchronous Quick Action example."""

from client import authenticated_client


def main() -> None:
    client = authenticated_client()
    result = client.json(
        "POST",
        "/api/agent/quick-action/",
        json={"text": "查询未来七天的日程，不要创建或修改任何数据", "sync": True, "timeout": 30},
        timeout=45,
    )
    print(result)


if __name__ == "__main__":
    main()
