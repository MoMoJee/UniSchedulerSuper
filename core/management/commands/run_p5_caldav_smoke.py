import base64
import json
from uuid import uuid4

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from rest_framework.authtoken.models import Token

from core.models import (
    CalendarChange, CalendarCollectionVersion, CalendarEvent, EventRecurrenceSeries,
    PlannerChangeSet, PlannerCohortAssignment, UserData,
)
from core.management.commands.audit_legacy_planner_archive import build_archive_manifest


class Command(BaseCommand):
    help = '在活动数据库创建并完整清理隔离账号，执行 P5 CalDAV HTTP 写入 smoke。'

    def handle(self, *args, **options):
        tracked = [
            User, Token, UserData, CalendarEvent, EventRecurrenceSeries,
            CalendarCollectionVersion, CalendarChange, PlannerChangeSet,
        ]
        before = {model._meta.label: model.objects.count() for model in tracked}
        legacy_before = build_archive_manifest()['archive_sha256']
        username = f'__p5_smoke_{uuid4().hex[:10]}'
        user = None
        statuses = {}
        try:
            user = User.objects.create_user(username=username, password=uuid4().hex)
            token = Token.objects.create(user=user)
            PlannerCohortAssignment.objects.create(
                user=user, storage_mode='normalized',
                entrypoints={
                    'calendar_feed': {'mode': 'normalized'},
                    'caldav_read': {'mode': 'normalized'},
                    'caldav_write': {'mode': 'normalized'},
                },
                metadata={'p6_cutover_manifest': {'schema': 1, 'sources': []}},
            )
            auth = 'Basic ' + base64.b64encode(f'{username}:{token.key}'.encode()).decode()
            client = Client()
            request = lambda method, path, body=b'', **headers: client.generic(
                method, path, data=body, content_type='text/calendar; charset=utf-8',
                HTTP_AUTHORIZATION=auth, **headers,
            )
            statuses['home'] = request('PROPFIND', f'/caldav/{username}/', HTTP_DEPTH='1').status_code
            path = f'/caldav/{username}/default/live-smoke.ics'
            body1 = b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:p5-live-smoke@example.test\r\nDTSTART;TZID=Asia/Shanghai:20260713T100000\r\nDTEND;TZID=Asia/Shanghai:20260713T110000\r\nSUMMARY:P5 live smoke\r\nRRULE:FREQ=DAILY;COUNT=3\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'
            created = request('PUT', path, body1, HTTP_IF_NONE_MATCH='*')
            statuses['create'] = created.status_code
            statuses['get'] = request('GET', path).status_code
            body2 = body1.replace(b'P5 live smoke', b'P5 live smoke updated')
            updated = request('PUT', path, body2, HTTP_IF_MATCH=created.get('ETag', ''))
            statuses['update'] = updated.status_code
            statuses['stale'] = request('PUT', path, body1, HTTP_IF_MATCH=created.get('ETag', '')).status_code
            statuses['delete'] = request('DELETE', path, HTTP_IF_MATCH=updated.get('ETag', '')).status_code
            legacy_unchanged = build_archive_manifest()['archive_sha256'] == legacy_before
            if statuses != {'home': 207, 'create': 201, 'get': 200, 'update': 204, 'stale': 412, 'delete': 204}:
                raise CommandError(f'HTTP smoke 状态不符合预期: {statuses}')
            if not legacy_unchanged:
                raise CommandError('smoke 修改了 legacy UserData')
        finally:
            if user is not None:
                user.delete()
        after = {model._meta.label: model.objects.count() for model in tracked}
        report = {
            'statuses': statuses, 'legacy_unchanged': legacy_unchanged,
            'counts_before': before, 'counts_after_cleanup': after,
            'cleanup_exact': before == after,
        }
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        if before != after:
            raise CommandError('隔离 smoke 清理后业务计数未恢复')
