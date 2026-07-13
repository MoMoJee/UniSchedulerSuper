"""Read-only Calendar Feed and CalDAV discovery smoke example."""

from __future__ import annotations

import base64
from xml.etree import ElementTree

import requests

from client import BASE_URL, USERNAME, authenticated_client


PROPFIND_BODY = b'''<?xml version="1.0" encoding="utf-8"?>
<D:propfind xmlns:D="DAV:"><D:prop><D:displayname/><D:resourcetype/></D:prop></D:propfind>'''


def main() -> None:
    client = authenticated_client()
    token = client.session.headers["Authorization"].removeprefix("Token ")

    feed = requests.get(
        f"{BASE_URL}/api/calendar/feed/",
        params={"token": token, "type": "all"},
        timeout=30,
    )
    feed.raise_for_status()
    if "BEGIN:VCALENDAR" not in feed.text:
        raise RuntimeError("Feed response is not an iCalendar document")
    print("feed:", feed.status_code, feed.headers.get("Content-Type"), len(feed.content), "bytes")

    auth = base64.b64encode(f"{USERNAME}:{token}".encode()).decode()
    home = requests.request(
        "PROPFIND",
        f"{BASE_URL}/caldav/{USERNAME}/",
        headers={
            "Authorization": f"Basic {auth}",
            "Depth": "1",
            "Content-Type": "application/xml; charset=utf-8",
        },
        data=PROPFIND_BODY,
        timeout=30,
    )
    home.raise_for_status()
    ElementTree.fromstring(home.content)
    print("caldav home:", home.status_code, home.headers.get("Content-Type"), len(home.content), "bytes")


if __name__ == "__main__":
    main()
