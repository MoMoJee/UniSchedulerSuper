"""Quick Action text/audio, sync/async contract examples.

Quick Action is an Agent entrypoint.  Its Planner tools delegate to the same
normalized application service as Planner V2; callers must not assume that a
successful task always mutated data, and should inspect ``result_type`` and the
tool results.
"""

import argparse
import time
from pathlib import Path

from client import authenticated_client


TERMINAL = {"success", "failed", "cancelled"}


def submit_text(client, text: str, *, sync: bool) -> dict:
    return client.json(
        "POST", "/api/agent/quick-action/",
        json={"text": text, "sync": sync, "timeout": 30}, timeout=45,
    )


def submit_audio(client, path: Path, *, sync: bool) -> dict:
    with path.open("rb") as stream:
        return client.json(
            "POST", "/api/agent/quick-action/",
            files={"audio": (path.name, stream)},
            data={"sync": str(sync).lower(), "timeout": "30"}, timeout=45,
        )


def wait_for_task(client, task_id: str) -> dict:
    while True:
        payload = client.json("GET", f"/api/agent/quick-action/{task_id}/?wait=true", timeout=40)
        if payload.get("status") in TERMINAL:
            return payload
        time.sleep(0.5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", default="查询未来七天的日程，不要修改数据")
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--async-mode", action="store_true")
    args = parser.parse_args()

    client = authenticated_client()
    result = (
        submit_audio(client, args.audio, sync=not args.async_mode)
        if args.audio else submit_text(client, args.text, sync=not args.async_mode)
    )
    if args.async_mode:
        result = wait_for_task(client, result["task_id"])
    print(result)
    print("recent tasks:", client.json("GET", "/api/agent/quick-action/list/?limit=5"))


if __name__ == "__main__":
    main()
