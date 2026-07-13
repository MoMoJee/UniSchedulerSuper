import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from caldav_service.views.base import CalDAVView
from caldav_service.views.calendar import CalendarCollectionView
from caldav_service.views.calendar_home import CalendarHomeView
from caldav_service.views.event import EventObjectView


class Command(BaseCommand):
    help = '审计 P5 暴露的 CalDAV capability，禁止宣称未实现协议。'

    def add_arguments(self, parser):
        parser.add_argument('--strict', action='store_true')
        parser.add_argument('--output')

    def handle(self, *args, **options):
        declared = {
            'dav': '1, calendar-access',
            'home_allow': CalendarHomeView.allow_header,
            'collection_allow': CalendarCollectionView.allow_header,
            'event_allow': EventObjectView.allow_header,
            'reminder_event_allow': 'OPTIONS, GET, HEAD',
            'reports': ['calendar-multiget', 'calendar-query'],
        }
        forbidden_tokens = ['LOCK', 'UNLOCK', 'COPY', 'MOVE', 'sync-collection', 'free-busy-query']
        serialized = json.dumps(declared)
        issues = [token for token in forbidden_tokens if token in serialized]
        report = {'declared': declared, 'forbidden_declared': issues, 'ok': not issues}
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        if options['output']:
            Path(options['output']).write_text(payload, encoding='utf-8')
        self.stdout.write(payload)
        if options['strict'] and issues:
            raise CommandError(f'发现虚假 capability: {issues}')
