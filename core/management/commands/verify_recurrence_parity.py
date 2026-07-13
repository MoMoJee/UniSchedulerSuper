"""只读验证 legacy 已物化 recurrence 与 normalized 按窗展开结果。"""

import json
from datetime import datetime, time
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from core.models import PlannerMigrationState
from core.planner.recurrence.codec import PlannerTimeCodec
from core.planner.verification import PlannerMigrationVerifier
from core.planner.p6 import RETIRED_QUARANTINE_USERS


class Command(BaseCommand):
    help = '只读比较 recurrence occurrence 集；--sample all 代表校验全部用户。'

    def add_arguments(self, parser):
        parser.add_argument('--user-id', type=int, help='只校验指定用户。')
        parser.add_argument('--sample', default='all', choices=['all'], help='当前只支持 all。')
        parser.add_argument('--from', dest='from_value', default='2020-01-01', help='窗口起点。')
        parser.add_argument('--to', dest='to_value', default='2035-01-01', help='窗口终点。')
        parser.add_argument('--strict', action='store_true', help='存在差异时以非零状态退出。')
        parser.add_argument('--only-imported', action='store_true', help='只校验已导入 state 的用户，适合 staging 演练。')
        parser.add_argument('--output', help='可选 JSON 输出路径。')
        parser.add_argument('--exclude-retired-quarantine', action='store_true', help='P6：排除五个已批准的退役测试账号。')

    def handle(self, *args, **options):
        range_start = self._window_value(options['from_value'])
        range_end = self._window_value(options['to_value'])
        users = User.objects.order_by('id')
        if options['exclude_retired_quarantine']:
            users = users.exclude(username__in=RETIRED_QUARANTINE_USERS)
        if options.get('user_id') is not None:
            users = users.filter(id=options['user_id'])
            if not users.exists():
                raise CommandError(f'用户不存在: {options["user_id"]}')
        elif options['only_imported']:
            users = users.filter(planner_migration_states__status__in=[
                PlannerMigrationState.STATUS_IMPORTED,
                PlannerMigrationState.STATUS_VERIFIED,
            ]).distinct()
        reports = [
            PlannerMigrationVerifier(user, range_start=range_start, range_end=range_end).verify(recurrence_only=True)
            for user in users.iterator(chunk_size=50)
        ]
        result = {
            'sample': options['sample'],
            'user_count': len(reports),
            'difference_count': sum(item['difference_count'] for item in reports),
            'cohort_eligible_user_count': sum(item['cohort_eligible'] for item in reports),
            'users': reports,
        }
        serialized = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        if options.get('output'):
            path = Path(options['output'])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialized + '\n', encoding='utf-8')
            self.stdout.write(self.style.SUCCESS(f'recurrence parity 报告已写入: {path}'))
        else:
            self.stdout.write(serialized)
        if options['strict'] and result['difference_count']:
            raise CommandError(f"发现 {result['difference_count']} 个 recurrence parity 差异")

    @staticmethod
    def _window_value(value: str) -> datetime:
        parsed = PlannerTimeCodec.parse_value(value)
        if isinstance(parsed, datetime):
            return PlannerTimeCodec.to_utc(parsed)
        return PlannerTimeCodec.to_utc(datetime.combine(parsed, time.min))
