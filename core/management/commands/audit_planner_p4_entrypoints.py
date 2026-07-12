"""静态盘点 P4 Planner 调用面及其遗留依赖。"""

import json
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.planner.p4_contract import P4_ENTRYPOINT_INVENTORY


PATTERNS = {
    "legacy_services": re.compile(r"\b(?:EventService|TodoService|ReminderService)\b"),
    "legacy_repository": re.compile(r"\b(?:LegacyPlannerRepository|PlannerUserDataCompat)\b"),
    "direct_userdata": re.compile(r"\bUserData\b"),
    "reversion": re.compile(r"\breversion\b|\bRevision\b|\bVersion\b"),
    "agent_transaction": re.compile(r"\bAgentTransaction\b|@agent_transaction"),
    "application_service": re.compile(r"\bPlannerApplicationService\b"),
}


class Command(BaseCommand):
    help = "只读盘点 P4 Agent/Quick Action/MCP/cache/conflict/attachment/rollback 调用面。"

    def add_arguments(self, parser):
        parser.add_argument("--output", help="可选 JSON 输出路径。")

    def handle(self, *args, **options):
        root = Path(settings.BASE_DIR)
        entries = []
        for name, relative in P4_ENTRYPOINT_INVENTORY.items():
            path = root / relative
            exists = path.is_file()
            source = path.read_text(encoding="utf-8") if exists else ""
            matches = {
                key: [number for number, line in enumerate(source.splitlines(), start=1) if pattern.search(line)]
                for key, pattern in PATTERNS.items()
            }
            entries.append(
                {
                    "entrypoint": name,
                    "file": relative,
                    "exists": exists,
                    "matches": matches,
                }
            )

        report = {
            "generated_at": timezone.now().isoformat(),
            "phase": "P4-0",
            "summary": {
                "inventory_count": len(entries),
                "missing_file_count": sum(not item["exists"] for item in entries),
                "legacy_service_file_count": sum(bool(item["matches"]["legacy_services"]) for item in entries),
                "legacy_repository_file_count": sum(bool(item["matches"]["legacy_repository"]) for item in entries),
                "reversion_file_count": sum(bool(item["matches"]["reversion"]) for item in entries),
                "application_service_file_count": sum(bool(item["matches"]["application_service"]) for item in entries),
            },
            "entrypoints": entries,
        }
        serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        output = options.get("output")
        if output:
            path = Path(output)
            if path.exists() and path.is_dir():
                raise CommandError(f"输出路径不能是目录: {path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialized + "\n", encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"P4 调用面报告已写入: {path}"))
            return
        self.stdout.write(serialized)

