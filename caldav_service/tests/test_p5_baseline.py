import base64
import hashlib
import json

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token

from core.models import PlannerMigrationState, UserData


def basic_auth(username: str, password: str) -> str:
    value = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {value}"


@override_settings(PLANNER_STORAGE_MODE="legacy")
class CalDAVP5BaselineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="caldav-baseline", password="test-password")
        self.token = Token.objects.create(user=self.user)
        self.auth = basic_auth(self.user.username, self.token.key)
        self.event = {
            "id": "event-1",
            "title": "基线日程",
            "start": "2026-07-13T10:00",
            "end": "2026-07-13T11:00",
            "description": "baseline",
            "location": "room",
            "status": "confirmed",
            "last_modified": "2026-07-13 09:00:00",
            "groupID": "",
        }
        UserData.objects.create(user=self.user, key="events", value=json.dumps([self.event]))
        UserData.objects.create(user=self.user, key="events_groups", value="[]")
        UserData.objects.create(user=self.user, key="reminders", value="[]")

    def request(self, method: str, path: str, body=b"", **headers):
        return self.client.generic(
            method,
            path,
            data=body,
            content_type=headers.pop("content_type", "application/xml; charset=utf-8"),
            HTTP_AUTHORIZATION=self.auth,
            **headers,
        )

    def test_discovery_home_and_resource_get_are_hermetic(self):
        root = self.request("PROPFIND", "/caldav/", HTTP_DEPTH="0")
        self.assertEqual(root.status_code, 207)
        self.assertIn(f"/caldav/principals/{self.user.username}/", root.content.decode())

        home = self.request("PROPFIND", f"/caldav/{self.user.username}/", HTTP_DEPTH="1")
        self.assertEqual(home.status_code, 207)
        payload = home.content.decode()
        self.assertIn(f"/caldav/{self.user.username}/default/", payload)
        self.assertIn(f"/caldav/{self.user.username}/reminders/", payload)

        resource = self.request("GET", f"/caldav/{self.user.username}/default/event-1.ics")
        self.assertEqual(resource.status_code, 200)
        self.assertIn("SUMMARY", resource.content.decode())
        self.assertTrue(resource.headers["ETag"].startswith('"'))

    def test_auth_cross_user_and_readonly_reminder_contract(self):
        unauthenticated = self.client.generic("PROPFIND", "/caldav/", HTTP_DEPTH="0")
        self.assertEqual(unauthenticated.status_code, 401)
        self.assertIn("WWW-Authenticate", unauthenticated.headers)

        other = User.objects.create_user(username="caldav-other", password="test-password")
        forbidden = self.request("PROPFIND", f"/caldav/{other.username}/", HTTP_DEPTH="0")
        self.assertEqual(forbidden.status_code, 403)

        denied = self.request(
            "PUT",
            f"/caldav/{self.user.username}/reminders/rem-1.ics",
            body=b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
            content_type="text/calendar; charset=utf-8",
        )
        self.assertEqual(denied.status_code, 403)

    def test_supported_reports_are_frozen_and_sync_collection_is_rejected(self):
        home = self.request("PROPFIND", f"/caldav/{self.user.username}/", HTTP_DEPTH="1")
        text = home.content.decode()
        self.assertIn("calendar-multiget", text)
        self.assertIn("calendar-query", text)
        self.assertNotIn("sync-collection", text)

        report = self.request(
            "REPORT",
            f"/caldav/{self.user.username}/default/",
            body=(
                b'<?xml version="1.0" encoding="utf-8"?>'
                b'<D:sync-collection xmlns:D="DAV:"><D:sync-token/></D:sync-collection>'
            ),
        )
        self.assertEqual(report.status_code, 501)

    def test_baseline_read_requests_do_not_modify_legacy_or_normalized_storage(self):
        source = UserData.objects.get(user=self.user, key="events")
        before = hashlib.sha256(source.value.encode()).hexdigest()
        for _ in range(3):
            self.request("PROPFIND", f"/caldav/{self.user.username}/default/", HTTP_DEPTH="1")
            self.request("GET", f"/caldav/{self.user.username}/default/event-1.ics")
        source.refresh_from_db()
        self.assertEqual(hashlib.sha256(source.value.encode()).hexdigest(), before)
