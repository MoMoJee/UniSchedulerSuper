"""为明确不修复的隔离账号记录可机读处置，不改变 issue resolved 状态。"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import PlannerMigrationIssue, PlannerMigrationState


class Command(BaseCommand):
    help = '记录 Planner quarantine 处置；默认 dry-run，--apply 才写入 metadata。'

    def add_arguments(self, parser):
        parser.add_argument('--username', action='append', required=True, help='目标用户名，可重复。')
        parser.add_argument('--disposition', default='retired-test-data')
        parser.add_argument('--note', default='')
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        usernames = list(dict.fromkeys(options['username']))
        users = {user.username: user for user in User.objects.filter(username__in=usernames)}
        missing = sorted(set(usernames) - set(users))
        if missing:
            raise CommandError(f'用户不存在: {", ".join(missing)}')
        now = timezone.now().isoformat()
        report = []
        for username in usernames:
            user = users[username]
            unresolved = PlannerMigrationIssue.objects.filter(user=user, is_resolved=False)
            states = PlannerMigrationState.objects.filter(user=user)
            if not unresolved.exists() or not states.filter(status=PlannerMigrationState.STATUS_QUARANTINED).exists():
                raise CommandError(f'用户不是具有未解决 issue 的 quarantine 用户: {username}')
            report.append({'username': username, 'issue_count': unresolved.count(), 'state_count': states.count()})
            if not options['apply']:
                continue
            with transaction.atomic():
                for issue in unresolved.select_for_update():
                    issue.metadata = {
                        **issue.metadata,
                        'disposition': options['disposition'],
                        'disposition_note': options['note'],
                        'disposition_at': now,
                    }
                    issue.save(update_fields=['metadata', 'updated_at'])
                for state in states.select_for_update():
                    state.metadata = {
                        **state.metadata,
                        'disposition': options['disposition'],
                        'disposition_note': options['note'],
                        'disposition_at': now,
                    }
                    state.status = PlannerMigrationState.STATUS_QUARANTINED
                    state.save(update_fields=['metadata', 'status', 'updated_at'])
        action = '已写入' if options['apply'] else 'dry-run'
        self.stdout.write(self.style.SUCCESS(f'{action}: {report}'))

