"""将 legacy Planner JSON 导入 normalized 旁路表。"""

import json
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from core.planner.migration import PlannerLegacyMigration


class Command(BaseCommand):
    help = '导入 legacy Planner JSON 到 normalized 旁路表；默认 dry-run，必须显式 --apply。'

    def add_arguments(self, parser):
        parser.add_argument('--user-id', type=int, help='只迁移指定用户。')
        parser.add_argument('--batch-size', type=int, default=50, help='每批处理用户数，默认 50。')
        parser.add_argument('--apply', action='store_true', help='显式写入 normalized 旁路表。')
        parser.add_argument('--dry-run', action='store_true', help='显式只生成迁移计划；这是默认行为。')
        parser.add_argument('--skip-quarantined', action='store_true', help='apply 时跳过计划中存在 issue 的用户。')
        parser.add_argument('--record-quarantined', action='store_true', help='仅记录隔离 state/issue，不导入隔离用户业务投影。')
        parser.add_argument('--output', help='可选 JSON 报告文件。')

    def handle(self, *args, **options):
        if options['batch_size'] <= 0:
            raise CommandError('--batch-size 必须大于 0')
        if options['apply'] and options['dry_run']:
            raise CommandError('--apply 与 --dry-run 不可同时使用')
        if options['record_quarantined'] and not (options['apply'] and options['skip_quarantined']):
            raise CommandError('--record-quarantined 必须与 --apply --skip-quarantined 一起使用')
        users = User.objects.order_by('id')
        if options.get('user_id') is not None:
            users = users.filter(id=options['user_id'])
            if not users.exists():
                raise CommandError(f'用户不存在: {options["user_id"]}')

        reports = []
        for user in users.iterator(chunk_size=options['batch_size']):
            migration = PlannerLegacyMigration(user)
            plan = migration.build_plan()
            if options['apply'] and options['skip_quarantined'] and not plan['cohort_eligible']:
                if options['record_quarantined']:
                    reports.append(migration.record_quarantine())
                else:
                    plan['skipped'] = 'quarantined_by_plan'
                    reports.append(plan)
                continue
            reports.append(migration.apply() if options['apply'] else plan)

        result = {
            'apply': options['apply'],
            'user_count': len(reports),
            'cohort_eligible_user_count': sum(report['cohort_eligible'] for report in reports),
            'quarantined_user_count': sum(not report['cohort_eligible'] for report in reports),
            'users': reports,
        }
        serialized = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        output = options.get('output')
        if output:
            path = Path(output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialized + '\n', encoding='utf-8')
            self.stdout.write(self.style.SUCCESS(f'迁移报告已写入: {path}'))
            return
        self.stdout.write(serialized)
