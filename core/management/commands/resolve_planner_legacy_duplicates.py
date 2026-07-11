"""安全处置完全重复的 legacy Planner UserData 源行。"""

import hashlib
import json

import reversion
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count

from core.management.commands.audit_planner_legacy import PLANNER_KEYS
from core.models import UserData
from logger import logger


class Command(BaseCommand):
    help = '只删除字节级完全相同的 Planner legacy 重复 key；默认 dry-run。'

    def add_arguments(self, parser):
        parser.add_argument('--user-id', type=int, required=True, help='要处理的用户。')
        parser.add_argument('--key', choices=PLANNER_KEYS, help='可选：只处理一个 Planner key。')
        parser.add_argument('--apply', action='store_true', help='显式执行删除；默认仅报告。')

    def handle(self, *args, **options):
        user_id = options['user_id']
        keys = [options['key']] if options.get('key') else list(PLANNER_KEYS)
        duplicate_groups = (
            UserData.objects.filter(user_id=user_id, key__in=keys)
            .values('key')
            .annotate(row_count=Count('id'))
            .filter(row_count__gt=1)
            .order_by('key')
        )

        report = {'user_id': user_id, 'apply': options['apply'], 'resolved': [], 'requires_manual_review': []}
        for group in duplicate_groups:
            key = group['key']
            rows = list(UserData.objects.filter(user_id=user_id, key=key).order_by('id'))
            checksums = {hashlib.sha256((row.value or '').encode('utf-8')).hexdigest() for row in rows}
            row_ids = [row.id for row in rows]
            if len(checksums) != 1:
                report['requires_manual_review'].append({'key': key, 'row_ids': row_ids, 'reason': 'payload_differs'})
                continue

            try:
                parsed = json.loads(rows[0].value or '')
            except (TypeError, json.JSONDecodeError):
                report['requires_manual_review'].append({'key': key, 'row_ids': row_ids, 'reason': 'invalid_json'})
                continue

            if not isinstance(parsed, (list, dict)):
                report['requires_manual_review'].append({'key': key, 'row_ids': row_ids, 'reason': 'unsupported_payload_type'})
                continue

            keep_id, *delete_ids = row_ids
            item = {'key': key, 'keep_id': keep_id, 'delete_ids': delete_ids, 'checksum': checksums.pop()}
            report['resolved'].append(item)
            if not options['apply']:
                continue

            with transaction.atomic(), reversion.create_revision():
                row = rows[0]
                reversion.set_user(row.user)
                reversion.set_comment(f'Resolve duplicate Planner legacy key: {key}')
                UserData.objects.filter(id__in=delete_ids).delete()
            logger.info(f'已清理用户 {rows[0].user.username} 的重复 Planner legacy key: {key}')

        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        if report['requires_manual_review']:
            raise CommandError('存在内容不一致或格式异常的重复 Planner key，未执行自动合并。')
