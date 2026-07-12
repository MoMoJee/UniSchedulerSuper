import hashlib
from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from agent_service.attachment_handler import AttachmentHandler
from agent_service.models import AgentSession
from agent_service.parsers.internal_parser import InternalElementParser
from core.models import CalendarEvent, PlannerCohortAssignment, PlannerMigrationState, UserData
from core.planner.application import PlannerApplicationService
from core.planner.context import PlannerExecutionContext
from core.planner.rollout import PlannerRolloutPolicy


@override_settings(PLANNER_STORAGE_MODE='normalized')
class InternalAttachmentParserTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='attachment-user', password='test-password')
        self.legacy = UserData.objects.create(user=self.user, key='events', value='[]')
        PlannerMigrationState.objects.create(
            user=self.user, source_key='events', source_row_id=self.legacy.id,
            source_checksum=hashlib.sha256(b'[]').hexdigest(),
            status=PlannerMigrationState.STATUS_VERIFIED,
        )
        PlannerCohortAssignment.objects.create(
            user=self.user, storage_mode=PlannerCohortAssignment.MODE_NORMALIZED,
            entrypoints={
                PlannerRolloutPolicy.ENTRYPOINT_API_V2: {'mode': 'normalized'},
                PlannerRolloutPolicy.ENTRYPOINT_INTERNAL_ATTACHMENT: {'mode': 'normalized'},
            },
        )
        self.session = AgentSession.objects.create(
            user=self.user, session_id=f'user_{self.user.id}_attachment', name='attachment'
        )
        start = timezone.make_aware(datetime(2026, 3, 1, 9))
        result = PlannerApplicationService.create_event(
            PlannerExecutionContext(
                user=self.user, source='web_v2', entrypoint=PlannerRolloutPolicy.ENTRYPOINT_API_V2
            ),
            {
                'title': '附件日程', 'description': '不可变内容',
                'start': start.isoformat(), 'end': (start + timedelta(hours=1)).isoformat(),
                'recurrence': {'rrule': 'FREQ=DAILY'},
            }, range_start=start, range_end=start + timedelta(hours=1),
        )
        self.event_id = result['event']['event_id']

    def test_normalized_list_and_parse_do_not_read_legacy_json(self):
        items = InternalElementParser.list_attachable_items(self.user, 'event', '附件')
        self.assertEqual([item['id'] for item in items], [self.event_id])
        result = InternalElementParser().parse(
            element_type='event', element_id=self.event_id, user=self.user
        )
        self.assertTrue(result['success'])
        self.assertIn('FREQ=DAILY', result['text'])
        self.assertEqual(result['metadata']['snapshot']['description'], '不可变内容')
        self.legacy.refresh_from_db()
        self.assertEqual(self.legacy.value, '[]')

    def test_attachment_snapshot_survives_source_deletion(self):
        result = AttachmentHandler.handle_internal(
            self.user, self.session.session_id, 'event', self.event_id
        )
        self.assertTrue(result['success'])
        attachment = result['attachment']
        self.assertEqual(attachment.internal_snapshot['description'], '不可变内容')
        CalendarEvent.objects.filter(user=self.user, event_id=self.event_id).update(deleted_at=timezone.now())
        attachment.refresh_from_db()
        self.assertIn('不可变内容', attachment.parsed_text)
        self.assertEqual(attachment.internal_snapshot['title'], '附件日程')

