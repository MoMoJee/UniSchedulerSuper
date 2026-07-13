"""Create/verify/seal the P6 read-only Planner legacy archive manifest."""

import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import GroupCalendarData, PlannerLegacyWriteGuard, UserData
from core.planner.legacy import LegacyPlannerRepository


def build_archive_manifest():
    rows = []
    for row in UserData.objects.filter(key__in=LegacyPlannerRepository.PLANNER_KEYS).order_by('user_id', 'key', 'id'):
        raw = row.value or ''
        rows.append({
            'user_id': row.user_id,
            'key': row.key,
            'source_row_id': row.id,
            'bytes': len(raw.encode('utf-8')),
            'sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
        })
    group_rows = []
    for row in GroupCalendarData.objects.order_by('share_group_id'):
        raw = json.dumps(row.events_data, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
        group_rows.append({
            'share_group_id': row.share_group_id,
            'bytes': len(raw.encode('utf-8')),
            'sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
        })
    canonical = json.dumps({'userdata_rows': rows, 'group_projection_rows': group_rows}, separators=(',', ':'), sort_keys=True)
    return {
        'schema': 1,
        'userdata_row_count': len(rows),
        'userdata_bytes': sum(row['bytes'] for row in rows),
        'group_projection_row_count': len(group_rows),
        'userdata_rows': rows,
        'group_projection_rows': group_rows,
        'archive_sha256': hashlib.sha256(canonical.encode('utf-8')).hexdigest(),
    }


class Command(BaseCommand):
    help = '输出/复验 P6 legacy archive manifest；--seal --apply 开启数据库防写。'

    def add_arguments(self, parser):
        parser.add_argument('--output', required=True)
        parser.add_argument('--verify')
        parser.add_argument('--seal', action='store_true')
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        if options['apply'] and not options['seal']:
            raise CommandError('--apply 必须与 --seal 一起使用')
        manifest = build_archive_manifest()
        verified = None
        if options.get('verify'):
            expected = json.loads(Path(options['verify']).read_text(encoding='utf-8'))
            verified = expected.get('archive_sha256') == manifest['archive_sha256']
            if not verified:
                raise CommandError('archive manifest checksum 不一致')
        if options['seal'] and options['apply']:
            with transaction.atomic():
                guard, _ = PlannerLegacyWriteGuard.objects.select_for_update().get_or_create(singleton=True)
                guard.enabled = True
                guard.enabled_at = guard.enabled_at or timezone.now()
                guard.archive_manifest_sha256 = manifest['archive_sha256']
                guard.metadata = {'schema': 1, 'userdata_row_count': manifest['userdata_row_count']}
                guard.save()
        report = {**manifest, 'generated_at': timezone.now().isoformat(), 'verified_against_input': verified, 'sealed': bool(options['seal'] and options['apply'])}
        path = Path(options['output'])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(f'legacy archive manifest 已写入: {path}'))
