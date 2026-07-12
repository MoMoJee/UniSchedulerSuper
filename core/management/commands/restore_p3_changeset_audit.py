"""从 P4 前只读备份恢复被误删的 P3 ChangeSet 为轻量审计摘要。"""

import json
import sqlite3
from datetime import datetime, timezone as datetime_timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import PlannerChangeSet
from core.planner.rollback_cleanup import affected_refs_from_payloads


class Command(BaseCommand):
    help = '仅恢复 P3 ChangeSet 的 ID/命令/时间/affected refs；不恢复 rollback payload。'

    def add_arguments(self, parser):
        parser.add_argument('--source-db', required=True)

    def handle(self, *args, **options):
        def aware(value):
            if not value:
                return None
            parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
            return parsed.replace(tzinfo=datetime_timezone.utc) if parsed.tzinfo is None else parsed

        source = Path(options['source_db']).resolve()
        if not source.is_file():
            raise CommandError(f'备份数据库不存在: {source}')
        connection = sqlite3.connect(f'file:{source.as_posix()}?mode=ro', uri=True)
        try:
            rows = connection.execute(
                'SELECT id,user_id,session_id,tool_call_id,command_type,before_payload,'
                'after_payload,is_reverted,reverted_at,created_at,updated_at,deleted_at,version '
                'FROM core_plannerchangeset ORDER BY id'
            ).fetchall()
        finally:
            connection.close()
        created = 0
        with transaction.atomic():
            for row in rows:
                (pk, user_id, session_id, tool_call_id, command_type, before_raw, after_raw,
                 is_reverted, reverted_at, created_at, updated_at, deleted_at, version) = row
                before_payload = json.loads(before_raw or '{}')
                after_payload = json.loads(after_raw or '{}')
                _, was_created = PlannerChangeSet.objects.update_or_create(
                    pk=pk,
                    defaults={
                        'user_id': user_id, 'session_id': session_id or '',
                        'tool_call_id': tool_call_id or '', 'command_type': command_type,
                        'before_payload': {}, 'after_payload': {},
                        'is_reverted': bool(is_reverted), 'reverted_at': aware(reverted_at),
                        'source': 'web_v2',
                        'affected_refs': affected_refs_from_payloads(before_payload, after_payload),
                        'rollback_status': 'reverted' if is_reverted else 'not_reversible',
                        'created_at': aware(created_at), 'updated_at': aware(updated_at),
                        'deleted_at': aware(deleted_at), 'version': version,
                    },
                )
                PlannerChangeSet.objects.filter(pk=pk).update(
                    created_at=aware(created_at), updated_at=aware(updated_at)
                )
                created += int(was_created)
        self.stdout.write(self.style.SUCCESS(
            f'已从只读备份恢复 {len(rows)} 条轻量 ChangeSet（新建 {created}），未恢复 before/after payload。'
        ))
