"""显式设置通过校验用户的 Planner cohort；不会修改任何业务数据流量。"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
import reversion

from core.models import PlannerCohortAssignment
from core.planner.rollout import PlannerRolloutPolicy


class Command(BaseCommand):
    help = '为一个已通过严格校验的用户登记 Planner cohort/入口；不切换全局流量。'

    def add_arguments(self, parser):
        parser.add_argument('--user-id', type=int, required=True)
        parser.add_argument('--mode', choices=['legacy', 'shadow', 'normalized'], required=True)
        parser.add_argument('--entrypoint', action='append', required=True, help='可重复传入，如 --entrypoint web。')
        parser.add_argument('--note', default='', help='人工审批或演练记录。')

    def handle(self, *args, **options):
        user = User.objects.filter(id=options['user_id']).first()
        if user is None:
            raise CommandError(f'用户不存在: {options["user_id"]}')
        mode = options['mode']
        if mode != 'legacy' and not PlannerRolloutPolicy.is_verified_clean(user):
            raise CommandError('用户尚未完成严格 migration 校验或仍有未解决 issue，拒绝进入 shadow/normalized cohort。')

        with transaction.atomic(), reversion.create_revision():
            reversion.set_user(user)
            reversion.set_comment(f'Set Planner cohort: {mode}')
            assignment, _ = PlannerCohortAssignment.objects.get_or_create(user=user)
            previous_mode = assignment.storage_mode
            entrypoints = dict(assignment.entrypoints or {})
            timestamp = timezone.now().isoformat()
            for entrypoint in options['entrypoint']:
                entrypoints[entrypoint] = {'enabled_at': timestamp, 'mode': mode}
            assignment.storage_mode = mode
            assignment.entrypoints = entrypoints
            if mode != 'legacy' and (assignment.enabled_at is None or previous_mode == 'legacy'):
                assignment.enabled_at = timezone.now()
            assignment.disabled_at = timezone.now() if mode == 'legacy' else None
            assignment.note = options['note']
            assignment.bump_version(update_fields={'storage_mode', 'entrypoints', 'enabled_at', 'disabled_at', 'note'})
        self.stdout.write(self.style.SUCCESS(f'已登记用户 {user.id} 的 Planner cohort: {mode} / {", ".join(options["entrypoint"])}'))
