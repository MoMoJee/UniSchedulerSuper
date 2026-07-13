"""Verify that P6 application and SQLite guards are active."""

import json
from pathlib import Path
from uuid import uuid4

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from core.models import PlannerLegacyWriteGuard, UserData
from core.planner.legacy import LegacyPlannerWriteForbidden, PlannerUserDataCompat


EXPECTED_TRIGGERS = {
    'p6_userdata_planner_insert_guard', 'p6_userdata_planner_update_guard',
    'p6_userdata_planner_delete_guard', 'p6_group_calendar_projection_insert_guard',
    'p6_group_calendar_projection_update_guard',
}


class Command(BaseCommand):
    help = '零持久写入地验证 P6 Planner legacy application/raw SQL/trigger 防写。'

    def add_arguments(self, parser):
        parser.add_argument('--output', required=True)
        parser.add_argument('--strict', action='store_true')

    def handle(self, *args, **options):
        guard = PlannerLegacyWriteGuard.objects.filter(singleton=True).first()
        with connection.cursor() as cursor:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'p6_%_guard'")
            triggers = {row[0] for row in cursor.fetchall()}
        checks = {
            'guard_enabled': bool(guard and guard.enabled),
            'triggers_complete': EXPECTED_TRIGGERS <= triggers,
            'orm_insert_blocked': self._blocked(lambda user: UserData.objects.create(user=user, key='events', value='[]')),
            'raw_insert_blocked': self._blocked(self._raw_insert),
            'compat_insert_blocked': self._blocked(self._compat_insert),
            'config_userdata_writable': self._config_write_works(),
        }
        report = {
            'generated_at': timezone.now().isoformat(),
            'checks': checks,
            'trigger_names': sorted(triggers),
            'archive_manifest_sha256': guard.archive_manifest_sha256 if guard else '',
            'passed': all(checks.values()),
        }
        path = Path(options['output'])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(f'legacy write guard 报告已写入: {path}'))
        if options['strict'] and not report['passed']:
            raise CommandError('P6 legacy write guard 验证失败')

    @staticmethod
    def _blocked(operation):
        marker = f'__p6_guard_{uuid4().hex}'
        try:
            with transaction.atomic():
                user = User.objects.create_user(marker)
                try:
                    operation(user)
                except (IntegrityError, LegacyPlannerWriteForbidden):
                    return True
                finally:
                    transaction.set_rollback(True)
        except (IntegrityError, LegacyPlannerWriteForbidden):
            return True
        return False

    @staticmethod
    def _raw_insert(user):
        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO core_userdata (user_id, key, value) VALUES (%s, %s, %s)', [user.id, 'todos', '[]'])

    @staticmethod
    def _compat_insert(user):
        request = type('Request', (), {'user': user})()
        PlannerUserDataCompat.get_or_initialize(request, 'reminders', [])

    @staticmethod
    def _config_write_works():
        marker = f'__p6_config_{uuid4().hex}'
        with transaction.atomic():
            user = User.objects.create_user(marker)
            row = UserData.objects.create(user=user, key='ui_settings', value='{}')
            row.value = '{"ok":true}'
            row.save(update_fields=['value'])
            row.delete()
            transaction.set_rollback(True)
        return True
