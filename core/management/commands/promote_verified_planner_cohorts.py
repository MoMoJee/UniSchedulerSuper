"""Seal P6 manifests and atomically promote every eligible user entrypoint."""

import hashlib
import json
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import PlannerCohortAssignment, PlannerMigrationState
from core.planner.p6 import RETIRED_DISPOSITION, classify_p6_user
from core.planner.rollout import PlannerRolloutPolicy


class Command(BaseCommand):
    help = 'P6 cohort 提升；默认 dry-run，--apply 才封存 manifest 并登记全部入口。'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--all-entrypoints', action='store_true', required=True)
        parser.add_argument('--output', required=True)

    def handle(self, *args, **options):
        if options['apply'] and options['dry_run']:
            raise CommandError('--apply 与 --dry-run 不能同时使用')
        apply = bool(options['apply'])
        now = timezone.now()
        rows = []
        blocking = []
        for user in User.objects.order_by('id'):
            classification = classify_p6_user(user)
            if classification.name == 'blocking':
                blocking.append(user.username)
                rows.append({'user_id': user.id, 'username': user.username, 'action': 'blocked', 'reason': classification.reason})
                continue
            manifest = self._manifest(user, classification.reason)
            disposition = 'retired_quarantine' if classification.name == 'retired_quarantine' else 'active_normalized'
            rows.append({
                'user_id': user.id,
                'username': user.username,
                'action': 'quarantine' if disposition == 'retired_quarantine' else 'promote',
                'manifest_sha256': manifest['manifest_sha256'],
                'entrypoint_count': len(PlannerRolloutPolicy.ALL_ENTRYPOINTS),
            })
            if not apply:
                continue
            with transaction.atomic():
                assignment, _ = PlannerCohortAssignment.objects.select_for_update().get_or_create(user=user)
                enabled_at = assignment.enabled_at or now
                entrypoints = {
                    name: {
                        'mode': 'quarantined' if disposition == 'retired_quarantine' else 'normalized',
                        'enabled_at': enabled_at.isoformat(),
                    }
                    for name in PlannerRolloutPolicy.ALL_ENTRYPOINTS
                }
                metadata = {
                    **(assignment.metadata or {}),
                    'p6_disposition': RETIRED_DISPOSITION if disposition == 'retired_quarantine' else disposition,
                    'p6_cutover_manifest': manifest,
                    'p6_sealed_at': enabled_at.isoformat(),
                }
                desired_mode = PlannerCohortAssignment.MODE_LEGACY if disposition == 'retired_quarantine' else PlannerCohortAssignment.MODE_NORMALIZED
                changes = {
                    'storage_mode': desired_mode,
                    'entrypoints': entrypoints,
                    'enabled_at': enabled_at,
                    'disabled_at': now if disposition == 'retired_quarantine' else None,
                    'note': RETIRED_DISPOSITION if disposition == 'retired_quarantine' else 'P6 all-entrypoint normalized cutover',
                    'metadata': metadata,
                }
                dirty = {name for name, value in changes.items() if getattr(assignment, name) != value}
                if dirty:
                    for name, value in changes.items():
                        setattr(assignment, name, value)
                    assignment.bump_version(update_fields=dirty)

        report = {
            'generated_at': now.isoformat(),
            'mode': 'apply' if apply else 'dry-run',
            'all_entrypoints': list(PlannerRolloutPolicy.ALL_ENTRYPOINTS),
            'summary': {
                'user_count': len(rows),
                'promote_count': sum(row['action'] == 'promote' for row in rows),
                'quarantine_count': sum(row['action'] == 'quarantine' for row in rows),
                'blocking_count': len(blocking),
            },
            'users': rows,
        }
        path = Path(options['output'])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(f'P6 cohort {report["mode"]} 已写入: {path}'))
        if blocking:
            raise CommandError(f'存在未决用户，拒绝提升: {", ".join(blocking)}')

    @staticmethod
    def _manifest(user, reason):
        sources = [
            {
                'source_key': state.source_key,
                'source_row_id': state.source_row_id,
                'source_checksum': state.source_checksum,
                'status': state.status,
            }
            for state in PlannerMigrationState.objects.filter(user=user).order_by('source_key')
        ]
        canonical = json.dumps(sources, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
        return {
            'schema': 1,
            'reason': reason,
            'sources': sources,
            'manifest_sha256': hashlib.sha256(canonical.encode('utf-8')).hexdigest(),
        }
