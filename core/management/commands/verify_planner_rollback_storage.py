"""验证 P4 rollback 清理后的数据库与业务投影。"""

import json
from pathlib import Path

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone
from reversion.models import Revision, Version

from agent_service.models import AgentRollbackWindow, AgentTransaction as AgentServiceTransaction
from core.models import AgentTransaction as CoreAgentTransaction
from core.models import PlannerChangeSet, PlannerRollbackSnapshot, UserData
from core.planner.legacy import LegacyPlannerRepository
from core.planner.rollback_cleanup import (
    business_checksum, database_path, database_sha256, userdata_version_key,
)


class Command(BaseCommand):
    help = '验证 P4 rollback storage、SQLite 完整性及业务 checksum。'

    def add_arguments(self, parser):
        parser.add_argument('--strict', action='store_true')
        parser.add_argument('--output', help='JSON 报告路径。')

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA integrity_check')
            integrity = [row[0] for row in cursor.fetchall()]
            cursor.execute('PRAGMA foreign_key_check')
            foreign_keys = [list(row) for row in cursor.fetchall()]
        userdata_ct = ContentType.objects.get_for_model(UserData)
        userdata_versions = list(Version.objects.filter(content_type=userdata_ct).only('serialized_data'))
        planner_userdata_version_count = sum(
            userdata_version_key(version) in LegacyPlannerRepository.PLANNER_KEYS
            for version in userdata_versions
        )
        agent_before_revision_count = Revision.objects.filter(comment__startswith='Before:').count()
        legacy_agent_count = (
            AgentServiceTransaction.objects.filter(change_set_id__isnull=True)
            | AgentServiceTransaction.objects.filter(source='legacy_agent')
        ).distinct().count()
        available_without_snapshot = PlannerChangeSet.objects.filter(
            rollback_status='available', rollback_snapshot__isnull=True
        ).count()
        closed_snapshot_count = PlannerRollbackSnapshot.objects.filter(
            rollback_window__status=AgentRollbackWindow.STATUS_CLOSED
        ).count()
        orphan_revisions = Revision.objects.filter(version__isnull=True).count()
        checksum, counts = business_checksum()
        db_path = database_path()
        database_file = db_path if db_path.exists() else None
        checks = {
            'integrity_ok': integrity == ['ok'], 'foreign_keys_ok': not foreign_keys,
            'legacy_agent_transactions_zero': legacy_agent_count == 0,
            'core_transactions_zero': CoreAgentTransaction.objects.count() == 0,
            'planner_userdata_versions_zero': planner_userdata_version_count == 0,
            'agent_before_revisions_zero': agent_before_revision_count == 0,
            'available_changesets_have_snapshot': available_without_snapshot == 0,
            'closed_windows_have_no_snapshot': closed_snapshot_count == 0,
            'orphan_revisions_zero': orphan_revisions == 0,
        }
        report = {
            'generated_at': timezone.now().isoformat(),
            'database': {
                'path': str(db_path),
                'file_bytes': database_file.stat().st_size if database_file else None,
                'sha256': database_sha256(database_file) if database_file else None,
            },
            'checks': checks, 'integrity_result': integrity, 'foreign_key_violations': foreign_keys,
            'business_checksum': checksum, 'business_counts': counts,
            'counts': {
                'revision': Revision.objects.count(), 'version': Version.objects.count(),
                'userdata_version': len(userdata_versions),
                'planner_userdata_version': planner_userdata_version_count,
                'agent_before_revision': agent_before_revision_count,
                'legacy_agent_transaction': legacy_agent_count,
                'core_transaction': CoreAgentTransaction.objects.count(),
                'active_window': AgentRollbackWindow.objects.filter(status='active').count(),
                'snapshot': PlannerRollbackSnapshot.objects.count(),
                'available_without_snapshot': available_without_snapshot,
                'closed_window_snapshot': closed_snapshot_count,
                'orphan_revision': orphan_revisions,
            },
        }
        serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        if options.get('output'):
            path = Path(options['output'])
            if path.exists() and path.is_dir():
                raise CommandError(f'输出路径不能是目录: {path}')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialized + '\n', encoding='utf-8')
            self.stdout.write(self.style.SUCCESS(f'P4 rollback 验证报告已写入: {path}'))
        else:
            self.stdout.write(serialized)
        if options['strict'] and not all(checks.values()):
            raise CommandError('P4 rollback storage strict 验证失败。')
