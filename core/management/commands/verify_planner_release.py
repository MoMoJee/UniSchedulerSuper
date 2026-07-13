"""Repeatable P6 production read-smoke and release gate."""

import base64
import json
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from core.management.commands.audit_legacy_planner_archive import build_archive_manifest
from core.models import PlannerCohortAssignment, PlannerLegacyWriteGuard, UserData
from core.planner.p6 import RETIRED_QUARANTINE_USERS
from core.planner.rollout import PlannerRolloutPolicy


class Command(BaseCommand):
    help = '验证 P6 cohort/guard/archive/DB，并执行 MoMoJee 与 quarantine 只读 HTTP smoke。'

    def add_arguments(self, parser):
        parser.add_argument('--output', required=True)
        parser.add_argument('--strict', action='store_true')

    def handle(self, *args, **options):
        before = self._counts()
        guard = PlannerLegacyWriteGuard.objects.filter(singleton=True).first()
        archive = build_archive_manifest()
        momo = User.objects.get(username='MoMoJee')
        client = APIClient()
        client.force_authenticate(momo)
        momo_statuses = {
            'bootstrap': client.get('/api/v2/planner/bootstrap/').status_code,
            'events': client.get('/api/v2/events/occurrences/?from=2026-07-01&to=2026-08-01').status_code,
            'todos': client.get('/api/v2/todos/').status_code,
            'reminders': client.get('/api/v2/reminders/?from=2026-07-01&to=2026-08-01').status_code,
        }
        token = Token.objects.filter(user=momo).first()
        if token:
            client.force_authenticate(None)
            momo_statuses['feed'] = client.get('/api/calendar/feed/', {'token': token.key, 'type': 'events'}).status_code
            auth = base64.b64encode(f'{momo.username}:{token.key}'.encode()).decode()
            momo_statuses['caldav'] = client.generic(
                'PROPFIND', f'/caldav/{momo.username}/',
                HTTP_AUTHORIZATION=f'Basic {auth}', HTTP_DEPTH='0',
            ).status_code
        quarantine = {}
        for user in User.objects.filter(username__in=RETIRED_QUARANTINE_USERS).order_by('username'):
            client.force_authenticate(user)
            quarantine[user.username] = client.get(
                '/api/v2/events/occurrences/?from=2026-07-01&to=2026-08-01'
            ).status_code
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA integrity_check')
            integrity = [row[0] for row in cursor.fetchall()]
            cursor.execute('PRAGMA foreign_key_check')
            foreign_keys = cursor.fetchall()
        cohorts = list(PlannerCohortAssignment.objects.filter(deleted_at__isnull=True))
        checks = {
            'momo_http': all(code in {200, 207} for code in momo_statuses.values()),
            'quarantine_http_423': len(quarantine) == 5 and all(code == 423 for code in quarantine.values()),
            'all_cohorts_complete': len(cohorts) == User.objects.count() and all(
                set(item.entrypoints) == set(PlannerRolloutPolicy.ALL_ENTRYPOINTS) for item in cohorts
            ),
            'guard_enabled': bool(guard and guard.enabled),
            'archive_checksum_matches_guard': bool(guard and guard.archive_manifest_sha256 == archive['archive_sha256']),
            'integrity_ok': integrity == ['ok'],
            'foreign_keys_ok': not foreign_keys,
            'read_smoke_zero_write': before == self._counts(),
        }
        report = {
            'generated_at': timezone.now().isoformat(),
            'checks': checks,
            'momo_statuses': momo_statuses,
            'quarantine_statuses': quarantine,
            'archive_sha256': archive['archive_sha256'],
            'counts': before,
            'passed': all(checks.values()),
        }
        path = Path(options['output'])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(f'P6 release verify 已写入: {path}'))
        if options['strict'] and not report['passed']:
            raise CommandError('P6 release verify 未通过')

    @staticmethod
    def _counts():
        from core.models import CalendarEvent, Reminder, Todo
        return {
            'users': User.objects.count(),
            'userdata': UserData.objects.count(),
            'events': CalendarEvent.objects.count(),
            'todos': Todo.objects.count(),
            'reminders': Reminder.objects.count(),
        }
