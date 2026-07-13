"""Authentication and read-only Planner V2 smoke test.

This is a runnable smoke script, not a Django unit test.  Credentials are read
from environment variables; no password is stored in the repository.
"""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from client import authenticated_client


def main() -> None:
    client = authenticated_client()
    print("token login: OK")
    print("verify:", client.json("GET", "/api/auth/token/verify/"))
    print("bootstrap:", client.json("GET", "/api/v2/planner/bootstrap/"))

    now = datetime.now(timezone.utc)
    query = urlencode({"from": now.isoformat(), "to": (now + timedelta(days=31)).isoformat()})
    print("events:", client.json("GET", f"/api/v2/events/occurrences/?{query}")["count"])
    print("todos:", client.json("GET", "/api/v2/todos/")["count"])
    print("reminders:", client.json("GET", "/api/v2/reminders/")["count"])


if __name__ == "__main__":
    main()
