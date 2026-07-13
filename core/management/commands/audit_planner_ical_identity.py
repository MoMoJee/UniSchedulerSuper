"""只读审计 Planner normalized/legacy iCalendar identity。"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import CalendarEvent, EventRecurrenceSeries, UserData


UID_DOMAIN = "unischeduler"


class Command(BaseCommand):
    help = "只读审计 Event/series 的 iCalendar UID、CalDAV resource name 与 legacy caldav_uid。"

    def add_arguments(self, parser):
        parser.add_argument("--output", help="可选 JSON 输出路径。")

    @staticmethod
    def _legacy_identity_map() -> tuple[dict[tuple[int, str], str], list[dict]]:
        identities: dict[tuple[int, str], str] = {}
        invalid_rows: list[dict] = []
        for row in UserData.objects.filter(key="events").select_related("user").order_by("user_id", "id"):
            try:
                payload = json.loads(row.value)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                invalid_rows.append({"user": row.user.username, "source_row_id": row.id, "error": str(exc)})
                continue
            if not isinstance(payload, list):
                invalid_rows.append({"user": row.user.username, "source_row_id": row.id, "error": "events_not_list"})
                continue
            for item in payload:
                if not isinstance(item, dict) or not item.get("id") or not item.get("caldav_uid"):
                    continue
                identities[(row.user_id, str(item["id"]))] = str(item["caldav_uid"])
        return identities, invalid_rows

    def handle(self, *args, **options):
        legacy, invalid_rows = self._legacy_identity_map()
        event_fields = {field.name for field in CalendarEvent._meta.get_fields()}
        series_fields = {field.name for field in EventRecurrenceSeries._meta.get_fields()}
        has_event_identity = {"ical_uid", "caldav_resource_name"} <= event_fields
        has_series_resource = "caldav_resource_name" in series_fields

        events = []
        event_mismatches = []
        proposed_pairs = []
        for event in CalendarEvent.objects.select_related("user").filter(deleted_at__isnull=True).order_by("user_id", "event_id"):
            legacy_uid = legacy.get((event.user_id, event.event_id), "")
            # 普通 Web Event 沿用 HTTP Feed 已公开的 evt- UID；显式
            # caldav_uid 原样保留。旧 CalDAV 的无前缀派生规则会与
            # CalDAV 回写生成的 ``<id>@unischeduler`` 资源发生碰撞。
            proposed_uid = legacy_uid or f"evt-{event.event_id}@{UID_DOMAIN}"
            proposed_resource = legacy_uid or event.event_id
            actual_uid = getattr(event, "ical_uid", "") if has_event_identity else ""
            actual_resource = getattr(event, "caldav_resource_name", "") if has_event_identity else ""
            proposed_pairs.append((event.user_id, proposed_uid, proposed_resource))
            if legacy_uid or (has_event_identity and (actual_uid != proposed_uid or actual_resource != proposed_resource)):
                detail = {
                    "user": event.user.username,
                    "event_id": event.event_id,
                    "legacy_caldav_uid": legacy_uid,
                    "proposed_ical_uid": proposed_uid,
                    "proposed_resource_name": proposed_resource,
                    "actual_ical_uid": actual_uid,
                    "actual_resource_name": actual_resource,
                }
                events.append(detail)
                if has_event_identity and (actual_uid != proposed_uid or actual_resource != proposed_resource):
                    event_mismatches.append(detail)

        series = []
        series_mismatches = []
        series_pairs = []
        for item in EventRecurrenceSeries.objects.select_related("user", "master_event").filter(
            deleted_at__isnull=True
        ).order_by("user_id", "series_id"):
            legacy_uid = legacy.get((item.user_id, item.master_event.event_id), "")
            proposed_uid = legacy_uid or f"evt-series-{item.series_id}@{UID_DOMAIN}"
            proposed_resource = legacy_uid or f"evt-series-{item.series_id}"
            actual_resource = getattr(item, "caldav_resource_name", "") if has_series_resource else ""
            series_pairs.append((item.user_id, proposed_uid, proposed_resource))
            if item.ical_uid != proposed_uid or actual_resource != proposed_resource:
                detail = {
                    "user": item.user.username,
                    "series_id": item.series_id,
                    "master_event_id": item.master_event.event_id,
                    "legacy_caldav_uid": legacy_uid,
                    "actual_ical_uid": item.ical_uid,
                    "proposed_ical_uid": proposed_uid,
                    "actual_resource_name": actual_resource,
                    "proposed_resource_name": proposed_resource,
                }
                series.append(detail)
                series_mismatches.append(detail)

        uid_counts = Counter((user_id, uid) for user_id, uid, _ in proposed_pairs + series_pairs)
        resource_counts = Counter((user_id, resource) for user_id, _, resource in proposed_pairs + series_pairs)
        report = {
            "generated_at": timezone.now().isoformat(),
            "phase": "P5-0/P5-A",
            "schema": {
                "calendar_event_identity_fields_present": has_event_identity,
                "event_series_resource_field_present": has_series_resource,
            },
            "summary": {
                "active_event_count": len(proposed_pairs),
                "active_series_count": len(series_pairs),
                "legacy_caldav_uid_count": len(legacy),
                "event_identity_attention_count": len(events),
                "event_identity_mismatch_count": len(event_mismatches),
                "series_identity_attention_count": len(series),
                "series_identity_mismatch_count": len(series_mismatches),
                "proposed_uid_conflict_count": sum(count > 1 for count in uid_counts.values()),
                "proposed_resource_conflict_count": sum(count > 1 for count in resource_counts.values()),
                "invalid_legacy_row_count": len(invalid_rows),
            },
            "proposed_uid_conflicts": [
                {"user_id": key[0], "ical_uid": key[1], "count": count}
                for key, count in uid_counts.items() if count > 1
            ],
            "proposed_resource_conflicts": [
                {"user_id": key[0], "resource_name": key[1], "count": count}
                for key, count in resource_counts.items() if count > 1
            ],
            "events_requiring_attention": events,
            "series_requiring_attention": series,
            "invalid_legacy_rows": invalid_rows,
            "legacy_manifest_sha256": hashlib.sha256(
                json.dumps(sorted((user_id, event_id, uid) for (user_id, event_id), uid in legacy.items()), ensure_ascii=False).encode("utf-8")
            ).hexdigest(),
        }
        serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        output = options.get("output")
        if output:
            path = Path(output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialized + "\n", encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"P5 iCalendar identity 审计已写入: {path}"))
            return
        self.stdout.write(serialized)
