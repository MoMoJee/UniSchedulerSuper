"""以只读方式审计 legacy Planner JSON 数据。"""

import hashlib
import json
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count
from django.utils import timezone

from core.models import UserData


PLANNER_KEYS = (
    "events",
    "todos",
    "reminders",
    "events_groups",
    "events_rrule_series",
    "rrule_series_storage",
)


class Command(BaseCommand):
    help = "只读审计 legacy Planner UserData，输出重复 key、JSON 错误与数据摘要。"

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, help="只审计指定用户。")
        parser.add_argument("--output", help="可选 JSON 报告路径；未传时输出至标准输出。")

    def handle(self, *args, **options):
        user_id = options.get("user_id")
        queryset = UserData.objects.filter(key__in=PLANNER_KEYS).order_by("user_id", "key", "id")
        if user_id is not None:
            queryset = queryset.filter(user_id=user_id)

        duplicate_query = (
            queryset.values("user_id", "key")
            .annotate(row_count=Count("id"))
            .filter(row_count__gt=1)
            .order_by("user_id", "key")
        )

        rows = []
        invalid_json = []
        key_counts = Counter()
        user_ids = set()

        for row in queryset.iterator(chunk_size=200):
            raw_value = row.value or ""
            record = {
                "user_id": row.user_id,
                "key": row.key,
                "source_row_id": row.id,
                "sha256": hashlib.sha256(raw_value.encode("utf-8")).hexdigest(),
                "byte_length": len(raw_value.encode("utf-8")),
            }
            try:
                parsed = json.loads(raw_value)
            except (TypeError, json.JSONDecodeError) as exc:
                record["json_type"] = None
                record["item_count"] = None
                record["json_error"] = str(exc)
                invalid_json.append(record.copy())
            else:
                record["json_type"] = type(parsed).__name__
                record["item_count"] = len(parsed) if isinstance(parsed, (list, dict)) else None

            rows.append(record)
            key_counts[row.key] += 1
            user_ids.add(row.user_id)

        report = {
            "generated_at": timezone.now().isoformat(),
            "scope": {"user_id": user_id, "keys": list(PLANNER_KEYS)},
            "summary": {
                "user_count": len(user_ids),
                "source_row_count": len(rows),
                "duplicate_key_count": len(duplicate_query),
                "invalid_json_count": len(invalid_json),
                "rows_by_key": dict(sorted(key_counts.items())),
            },
            "duplicate_keys": list(duplicate_query),
            "invalid_json": invalid_json,
            "source_rows": rows,
        }
        serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)

        output = options.get("output")
        if output:
            path = Path(output)
            if path.exists() and path.is_dir():
                raise CommandError(f"输出路径不能是目录: {path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialized + "\n", encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"审计完成: {path}"))
            return

        self.stdout.write(serialized)
