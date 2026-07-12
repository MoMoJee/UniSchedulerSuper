"""清理 P4 cutover 前的 legacy Planner rollback 历史。"""

import json
from pathlib import Path

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.functions import Length
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from reversion.models import Revision, Version

from agent_service.models import AgentRollbackWindow, AgentTransaction as AgentServiceTransaction
from core.models import AgentTransaction as CoreAgentTransaction
from core.models import PlannerChangeSet, PlannerRollbackSnapshot, UserData
from core.planner.rollback_cleanup import (
    NORMALIZED_REVERSION_LABELS, affected_refs_from_payloads, business_checksum, delete_ids,
)


class Command(BaseCommand):
    help = '按精确 ID 集合 dry-run 或清理 P4 cutover 前 legacy Planner rollback 历史。'

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--dry-run', action='store_true')
        mode.add_argument('--apply', action='store_true')
        parser.add_argument('--cutover', help='ISO8601 cutover；dry-run 缺省为当前时间。')
        parser.add_argument('--output', help='JSON 报告路径。')

    def handle(self, *args, **options):
        cutover = parse_datetime(options.get('cutover') or '') if options.get('cutover') else timezone.now()
        if cutover is None:
            raise CommandError('--cutover 必须是合法 ISO8601 时间。')
        if timezone.is_naive(cutover):
            cutover = timezone.make_aware(cutover, timezone.get_current_timezone())

        userdata_ct = ContentType.objects.get_for_model(UserData)
        normalized_ct_ids = [
            ContentType.objects.get_for_model(apps.get_model(*label.split('.', 1))).pk
            for label in NORMALIZED_REVERSION_LABELS
        ]
        legacy_agent_transactions = AgentServiceTransaction.objects.filter(
            change_set_id__isnull=True
        ) | AgentServiceTransaction.objects.filter(source='legacy_agent')
        legacy_agent_transaction_ids = list(legacy_agent_transactions.values_list('pk', flat=True).distinct())
        core_transaction_ids = list(CoreAgentTransaction.objects.values_list('pk', flat=True))
        referenced_revision_ids = set(
            AgentServiceTransaction.objects.filter(pk__in=legacy_agent_transaction_ids, revision_id__isnull=False)
            .values_list('revision_id', flat=True)
        ) | set(
            CoreAgentTransaction.objects.filter(pk__in=core_transaction_ids, revision_id__isnull=False)
            .values_list('revision_id', flat=True)
        )
        version_ids = set(
            Version.objects.filter(revision_id__in=referenced_revision_ids).values_list('pk', flat=True)
        )
        version_ids.update(
            Version.objects.filter(
                content_type=userdata_ct, revision__date_created__lt=cutover
            ).values_list('pk', flat=True)
        )
        version_ids.update(
            Version.objects.filter(
                content_type_id__in=normalized_ct_ids, revision__date_created__lt=cutover
            ).values_list('pk', flat=True)
        )
        old_change_set_ids = list(
            PlannerChangeSet.objects.filter(
                Q(revision__isnull=False) | Q(is_reverted=True) | Q(rollback_status__in=['available', 'expired', 'reverted'])
                | ~Q(before_payload={}) | ~Q(after_payload={}),
                created_at__lt=cutover, rollback_snapshot__isnull=True,
            )
            .values_list('pk', flat=True)
        )
        closed_window_ids = list(
            AgentRollbackWindow.objects.filter(status=AgentRollbackWindow.STATUS_CLOSED)
            .values_list('pk', flat=True)
        )
        sorted_version_ids = sorted(version_ids)
        serialized_bytes = sum(
            Version.objects.filter(pk__in=sorted_version_ids[offset:offset + 500])
            .aggregate(total=Sum(Length('serialized_data')))['total'] or 0
            for offset in range(0, len(sorted_version_ids), 500)
        )
        before_checksum, before_counts = business_checksum()
        report = {
            'generated_at': timezone.now().isoformat(), 'mode': 'apply' if options['apply'] else 'dry-run',
            'cutover': cutover.isoformat(),
            'selection': {
                'agent_service_legacy_transactions': len(legacy_agent_transaction_ids),
                'core_transactions': len(core_transaction_ids),
                'versions': len(version_ids), 'version_serialized_bytes': serialized_bytes,
                'referenced_revisions': len(referenced_revision_ids),
                'old_change_sets_without_snapshot': len(old_change_set_ids),
                'closed_windows': len(closed_window_ids),
            },
            'business_checksum_before': before_checksum,
            'business_counts_before': before_counts,
            'deleted': {},
        }
        if options['apply']:
            with transaction.atomic():
                report['deleted']['versions'] = delete_ids(Version, sorted_version_ids)
                report['deleted']['agent_service_transactions'] = delete_ids(
                    AgentServiceTransaction, legacy_agent_transaction_ids
                )
                report['deleted']['core_transactions'] = delete_ids(CoreAgentTransaction, core_transaction_ids)
                compacted = 0
                for change_set in PlannerChangeSet.objects.filter(pk__in=old_change_set_ids):
                    change_set.affected_refs = affected_refs_from_payloads(
                        change_set.before_payload, change_set.after_payload
                    )
                    change_set.before_payload = {}
                    change_set.after_payload = {}
                    change_set.revision = None
                    change_set.source = change_set.source or 'web_v2'
                    change_set.rollback_status = 'not_reversible'
                    change_set.save(update_fields={
                        'affected_refs', 'before_payload', 'after_payload', 'revision',
                        'source', 'rollback_status',
                    })
                    compacted += 1
                report['deleted']['compacted_change_sets'] = compacted
                report['deleted']['closed_windows'] = delete_ids(AgentRollbackWindow, closed_window_ids)
                orphan_revision_ids = list(
                    Revision.objects.filter(version__isnull=True).values_list('pk', flat=True)
                )
                report['deleted']['orphan_revisions'] = delete_ids(Revision, orphan_revision_ids)
                after_checksum, after_counts = business_checksum()
                if after_checksum != before_checksum:
                    raise CommandError('业务投影 checksum 在清理事务中发生变化，已回滚。')
                report['business_checksum_after'] = after_checksum
                report['business_counts_after'] = after_counts

        serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        if options.get('output'):
            path = Path(options['output'])
            if path.exists() and path.is_dir():
                raise CommandError(f'输出路径不能是目录: {path}')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialized + '\n', encoding='utf-8')
            self.stdout.write(self.style.SUCCESS(f'P4 rollback 清理报告已写入: {path}'))
        else:
            self.stdout.write(serialized)
