import hashlib
from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import CalendarEvent, PlannerChangeSet, PlannerCohortAssignment, PlannerMigrationState, UserData
from core.planner.application import PlannerApplicationAccessError, PlannerApplicationService
from core.planner.context import PlannerExecutionContext
from core.planner.repository import PlannerNotFoundError
from core.planner.rollout import PlannerRolloutPolicy


@override_settings(PLANNER_STORAGE_MODE="normalized")
class PlannerApplicationServiceTests(TestCase):
    def _verified_user(self, username: str, *, mode: str = "normalized") -> User:
        user = User.objects.create_user(username=username, password="test-password")
        source = UserData.objects.create(user=user, key="events", value="[]")
        PlannerMigrationState.objects.create(
            user=user,
            source_key="events",
            source_row_id=source.id,
            source_checksum=hashlib.sha256(b"[]").hexdigest(),
            status=PlannerMigrationState.STATUS_VERIFIED,
        )
        PlannerCohortAssignment.objects.create(
            user=user,
            storage_mode=mode,
            entrypoints={"api_v2": {"mode": mode}},
        )
        return user

    def _context(self, user: User) -> PlannerExecutionContext:
        return PlannerExecutionContext(
            user=user,
            source="web_v2",
            entrypoint=PlannerRolloutPolicy.ENTRYPOINT_API_V2,
            request_id="test-request",
        )

    def test_context_rejects_untrusted_reversible_sources(self):
        user = self._verified_user("context-user")
        with self.assertRaisesRegex(ValueError, "WebSocket Agent"):
            PlannerExecutionContext(
                user=user,
                source="mcp_http",
                entrypoint=PlannerRolloutPolicy.ENTRYPOINT_MCP,
                session_id="mcp-1",
                tool_call_id="call-1",
                reversible=True,
            )

    def test_application_gate_rejects_shadow_write_without_side_effects(self):
        user = self._verified_user("shadow-app-user", mode="shadow")
        before = (CalendarEvent.objects.count(), PlannerChangeSet.objects.count())
        with self.assertRaises(PlannerApplicationAccessError) as caught:
            PlannerApplicationService.create_event(
                self._context(user),
                {
                    "title": "不可写",
                    "start": "2026-03-01T09:00:00+08:00",
                    "end": "2026-03-01T10:00:00+08:00",
                },
                range_start=timezone.make_aware(datetime(2026, 3, 1, 9)),
                range_end=timezone.make_aware(datetime(2026, 3, 1, 10)),
            )
        self.assertEqual(caught.exception.code, "planner_normalized_write_not_enabled")
        self.assertEqual(before, (CalendarEvent.objects.count(), PlannerChangeSet.objects.count()))

    def test_direct_application_and_http_adapter_use_same_command_contract(self):
        direct_user = self._verified_user("direct-app-user")
        http_user = self._verified_user("http-app-user")
        start = timezone.make_aware(datetime(2026, 3, 1, 9))
        end = start + timedelta(hours=1)
        payload = {"title": "统一用例", "start": start.isoformat(), "end": end.isoformat()}

        direct = PlannerApplicationService.create_event(
            self._context(direct_user), payload, range_start=start, range_end=end
        )
        client = APIClient()
        client.force_authenticate(http_user)
        response = client.post("/api/v2/events/", payload, format="json")

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["event"]["title"], direct["event"]["title"])
        self.assertEqual(response.json()["event"]["start"], direct["event"]["start"])
        self.assertEqual(response.json()["event"]["end"], direct["event"]["end"])
        self.assertEqual(
            list(PlannerChangeSet.objects.filter(user=direct_user).values_list("command_type", flat=True)),
            ["event.create"],
        )
        self.assertEqual(
            list(PlannerChangeSet.objects.filter(user=http_user).values_list("command_type", flat=True)),
            ["event.create"],
        )

    def test_application_never_allows_cross_user_event_write(self):
        owner = self._verified_user("app-owner")
        attacker = self._verified_user("app-attacker")
        start = timezone.make_aware(datetime(2026, 3, 1, 9))
        event = CalendarEvent.objects.create(
            user=owner, event_id="private-event", title="私有", start_at=start, end_at=start + timedelta(hours=1)
        )
        with self.assertRaises(PlannerNotFoundError):
            PlannerApplicationService.patch_event(
                self._context(attacker), event.event_id, {"title": "越权"},
                scope="all", occurrence_ref=None, expected_version=event.version,
            )
        event.refresh_from_db()
        self.assertEqual(event.title, "私有")

    def test_v2_occurrence_view_delegates_to_application_service(self):
        user = self._verified_user("delegation-user")
        client = APIClient()
        client.force_authenticate(user)
        expected = {
            "range": {"from": "a", "to": "b"},
            "occurrences": [],
            "count": 0,
        }
        with patch.object(PlannerApplicationService, "list_event_occurrences", return_value=expected) as delegated:
            response = client.get("/api/v2/events/occurrences/?from=2026-03-01&to=2026-03-02")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        delegated.assert_called_once()

