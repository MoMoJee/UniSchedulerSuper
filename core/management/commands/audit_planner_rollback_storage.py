"""只读统计 Planner/Agent rollback 与 django-reversion 存储。"""

import json
from pathlib import Path

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Avg, Count, Max, Sum
from django.db.models.functions import Length
from django.utils import timezone
from reversion.models import Revision, Version

from agent_service.models import AgentRollbackWindow, AgentTransaction as AgentServiceTransaction
from core.models import AgentTransaction as CoreAgentTransaction
from core.models import PlannerChangeSet, PlannerRollbackSnapshot, UserData
from core.planner.legacy import LegacyPlannerRepository
from core.planner.rollback_cleanup import userdata_version_key


class Command(BaseCommand):
    help = "只读审计 Planner rollback/reversion 存储；不创建 Revision，不修改业务数据。"

    def add_arguments(self, parser):
        parser.add_argument("--output", help="可选 JSON 输出路径。")

    def handle(self, *args, **options):
        database_name = Path(settings.DATABASES["default"]["NAME"])
        file_bytes = database_name.stat().st_size if database_name.exists() else None

        totals = Version.objects.aggregate(
            version_count=Count("id"),
            serialized_bytes=Sum(Length("serialized_data")),
            max_version_bytes=Max(Length("serialized_data")),
            avg_version_bytes=Avg(Length("serialized_data")),
        )
        userdata_type = ContentType.objects.get_for_model(UserData)
        userdata = Version.objects.filter(content_type=userdata_type).aggregate(
            version_count=Count("id"),
            serialized_bytes=Sum(Length("serialized_data")),
            max_version_bytes=Max(Length("serialized_data")),
        )
        planner_userdata_versions = [
            version for version in Version.objects.filter(content_type=userdata_type).only('serialized_data')
            if userdata_version_key(version) in LegacyPlannerRepository.PLANNER_KEYS
        ]
        planner_userdata_serialized_bytes = sum(
            len(version.serialized_data or '') for version in planner_userdata_versions
        )
        agent_revisions = Revision.objects.filter(comment__startswith="Before:")
        agent_versions = Version.objects.filter(revision__in=agent_revisions)
        agent = agent_versions.aggregate(
            version_count=Count("id"),
            serialized_bytes=Sum(Length("serialized_data")),
            max_version_bytes=Max(Length("serialized_data")),
        )

        content_types = list(
            Version.objects.values("content_type__app_label", "content_type__model")
            .annotate(version_count=Count("id"), serialized_bytes=Sum(Length("serialized_data")))
            .order_by("-serialized_bytes", "content_type__app_label", "content_type__model")
        )
        change_sets = PlannerChangeSet.objects.aggregate(
            row_count=Count("id"),
            before_chars=Sum(Length("before_payload")),
            after_chars=Sum(Length("after_payload")),
        )
        snapshots = PlannerRollbackSnapshot.objects.aggregate(
            row_count=Count('id'), compressed_bytes=Sum(Length('payload')),
            uncompressed_bytes=Sum('uncompressed_size'),
        )

        report = {
            "generated_at": timezone.now().isoformat(),
            "database": {"path": str(database_name), "file_bytes": file_bytes},
            "summary": {
                "revision_count": Revision.objects.count(),
                **{key: value or 0 for key, value in totals.items()},
                "userdata_version_count": userdata["version_count"] or 0,
                "userdata_serialized_bytes": userdata["serialized_bytes"] or 0,
                "planner_userdata_version_count": len(planner_userdata_versions),
                "planner_userdata_serialized_bytes": planner_userdata_serialized_bytes,
                "agent_before_revision_count": agent_revisions.count(),
                "agent_before_version_count": agent["version_count"] or 0,
                "agent_before_serialized_bytes": agent["serialized_bytes"] or 0,
                "agent_service_transaction_count": AgentServiceTransaction.objects.count(),
                "core_transaction_count": CoreAgentTransaction.objects.count(),
                "planner_changeset_count": change_sets["row_count"] or 0,
                "rollback_window_count": AgentRollbackWindow.objects.count(),
                "rollback_snapshot_count": snapshots["row_count"] or 0,
                "rollback_snapshot_compressed_bytes": snapshots["compressed_bytes"] or 0,
                "rollback_snapshot_uncompressed_bytes": snapshots["uncompressed_bytes"] or 0,
            },
            "planner_changeset_payload_chars": {
                "before": change_sets["before_chars"] or 0,
                "after": change_sets["after_chars"] or 0,
            },
            "userdata_versions": {key: value or 0 for key, value in userdata.items()},
            "agent_before_versions": {key: value or 0 for key, value in agent.items()},
            "version_content_types": content_types,
            "warnings": [
                "项目同时存在 core.AgentTransaction 与 agent_service.AgentTransaction。",
                "SQLite 删除行后不会自动缩小文件；清理阶段必须另行压缩并复验。",
            ],
        }
        serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        output = options.get("output")
        if output:
            path = Path(output)
            if path.exists() and path.is_dir():
                raise CommandError(f"输出路径不能是目录: {path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialized + "\n", encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"P4 rollback 存储审计已写入: {path}"))
            return
        self.stdout.write(serialized)
