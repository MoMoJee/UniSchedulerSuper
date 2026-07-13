"""Read-only final P6 user/data/runtime inventory."""

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from core.models import (
    CalendarChange,
    CalendarEvent,
    EventOccurrenceOverride,
    EventRecurrenceSeries,
    GroupCalendarData,
    PlannerCohortAssignment,
    PlannerLegacyIdMap,
    PlannerMigrationIssue,
    PlannerMigrationState,
    Reminder,
    ReminderOccurrenceState,
    ReminderRecurrenceSeries,
    Todo,
    UserData,
)
from core.planner.legacy import LegacyPlannerRepository
from core.planner.p6 import classify_p6_user


RUNTIME_ROOTS = ('core', 'agent_service', 'caldav_service')
OFFLINE_PATH_MARKERS = ('/management/commands/', '/migrations/', '/tests/')
LEGACY_PATTERNS = {
    'legacy_repository': re.compile(r'\bLegacyPlannerRepository\b'),
    'legacy_compat': re.compile(r'\bPlannerUserDataCompat\b'),
    'group_events_projection': re.compile(r'\bevents_data\b'),
}


class Command(BaseCommand):
    help = '只读输出 P6 用户分类、legacy manifest 摘要、normalized 计数和 runtime 入口基线。'

    def add_arguments(self, parser):
        parser.add_argument('--output', required=True)
        parser.add_argument('--strict', action='store_true')

    def handle(self, *args, **options):
        before = self._db_fingerprint()
        classifications = Counter()
        users = []
        for user in User.objects.order_by('id').iterator(chunk_size=100):
            item = classify_p6_user(user)
            classifications[item.name] += 1
            users.append({
                'user_id': user.id,
                'username': user.username,
                'classification': item.name,
                'reason': item.reason,
                'source_key_count': item.source_key_count,
                'state_count': item.state_count,
                'unresolved_issue_count': item.unresolved_issue_count,
            })

        legacy_rows = []
        for row in UserData.objects.filter(key__in=LegacyPlannerRepository.PLANNER_KEYS).order_by('user_id', 'key', 'id'):
            raw = row.value or ''
            legacy_rows.append({
                'user_id': row.user_id,
                'key': row.key,
                'source_row_id': row.id,
                'bytes': len(raw.encode('utf-8')),
                'sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
            })

        runtime_findings = self._runtime_findings()
        after = self._db_fingerprint()
        report = {
            'generated_at': timezone.now().isoformat(),
            'classification_summary': dict(sorted(classifications.items())),
            'users': users,
            'legacy': {
                'row_count': len(legacy_rows),
                'byte_count': sum(item['bytes'] for item in legacy_rows),
                'rows': legacy_rows,
                'group_calendar_projection_rows': GroupCalendarData.objects.count(),
            },
            'normalized_counts': {
                'events': CalendarEvent.objects.count(),
                'event_series': EventRecurrenceSeries.objects.count(),
                'event_overrides': EventOccurrenceOverride.objects.count(),
                'todos': Todo.objects.count(),
                'reminders': Reminder.objects.count(),
                'reminder_series': ReminderRecurrenceSeries.objects.count(),
                'reminder_states': ReminderOccurrenceState.objects.count(),
                'legacy_id_maps': PlannerLegacyIdMap.objects.count(),
                'migration_states': PlannerMigrationState.objects.count(),
                'migration_issues': PlannerMigrationIssue.objects.count(),
                'cohorts': PlannerCohortAssignment.objects.filter(deleted_at__isnull=True).count(),
                'calendar_changes': CalendarChange.objects.count(),
            },
            'runtime_legacy_findings': runtime_findings,
            'read_only_fingerprint_before': before,
            'read_only_fingerprint_after': after,
            'read_only_verified': before == after,
        }
        path = Path(options['output'])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(f'P6 readiness 已写入: {path}'))
        if options['strict'] and (classifications.get('blocking', 0) or before != after):
            raise CommandError('P6 readiness 阻断：存在未决用户或审计产生了数据库写入')

    @staticmethod
    def _db_fingerprint():
        return {
            'userdata': UserData.objects.count(),
            'states': PlannerMigrationState.objects.count(),
            'issues': PlannerMigrationIssue.objects.count(),
            'cohorts': PlannerCohortAssignment.objects.count(),
            'events': CalendarEvent.objects.count(),
            'todos': Todo.objects.count(),
            'reminders': Reminder.objects.count(),
        }

    @staticmethod
    def _runtime_findings():
        root = Path(settings.BASE_DIR)
        findings = []
        for directory in RUNTIME_ROOTS:
            for path in sorted((root / directory).rglob('*.py')):
                relative = '/' + path.relative_to(root).as_posix()
                if any(marker in relative for marker in OFFLINE_PATH_MARKERS):
                    continue
                source = path.read_text(encoding='utf-8')
                matched = sorted(name for name, pattern in LEGACY_PATTERNS.items() if pattern.search(source))
                if matched:
                    findings.append({'file': relative.lstrip('/'), 'patterns': matched})
        return findings
