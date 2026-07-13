import json
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from core.models import CalendarCollectionVersion, EventGroup


class Command(BaseCommand):
    help = '初始化并校验 P5 CalDAV collection 单调版本。'

    def add_arguments(self, parser):
        parser.add_argument('--initialize', action='store_true')
        parser.add_argument('--strict', action='store_true')
        parser.add_argument('--username')
        parser.add_argument('--output')

    def handle(self, *args, **options):
        users = User.objects.filter(
            is_active=True,
            planner_cohort_assignment__storage_mode='normalized',
            planner_cohort_assignment__deleted_at__isnull=True,
        ).order_by('id')
        if options['username']:
            users = users.filter(username=options['username'])
        initialized = 0
        issues = []
        collections = 0
        for user in users:
            expected = {'default', 'reminders', *EventGroup.objects.filter(
                user=user, deleted_at__isnull=True
            ).values_list('group_id', flat=True)}
            if options['initialize']:
                for collection_id in expected:
                    _, created = CalendarCollectionVersion.objects.get_or_create(
                        user=user, collection_type='caldav', collection_id=collection_id
                    )
                    initialized += int(created)
            for collection in CalendarCollectionVersion.objects.filter(
                user=user, collection_type='caldav'
            ).prefetch_related('changes'):
                collections += 1
                tokens = list(collection.changes.order_by('token').values_list('token', flat=True))
                if tokens and tokens != list(range(tokens[0], tokens[-1] + 1)):
                    issues.append({'user': user.username, 'collection': collection.collection_id, 'code': 'token_gap'})
                if tokens and tokens[-1] != collection.version:
                    issues.append({'user': user.username, 'collection': collection.collection_id, 'code': 'version_tail_mismatch'})
            missing = expected - set(CalendarCollectionVersion.objects.filter(
                user=user, collection_type='caldav'
            ).values_list('collection_id', flat=True))
            for collection_id in sorted(missing):
                issues.append({'user': user.username, 'collection': collection_id, 'code': 'missing_version'})
        report = {
            'users': users.count(), 'collections': collections, 'initialized': initialized,
            'issues': issues, 'ok': not issues,
        }
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        if options['output']:
            Path(options['output']).write_text(payload, encoding='utf-8')
        self.stdout.write(payload)
        if options['strict'] and issues:
            raise CommandError(f'collection version 校验失败: {len(issues)} issue(s)')
