import hashlib
from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from asgiref.sync import async_to_sync

from agent_service.attachment_handler import AttachmentHandler
from agent_service.consumers import AgentConsumer
from agent_service.models import AgentSession, SessionAttachment
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
        self.client.force_login(self.user)
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
        self.series_id = result['event']['recurrence']['series_id']

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

    def test_recurring_occurrence_attachment_uses_master_id_and_effective_slot(self):
        occurrences = PlannerApplicationService.list_event_occurrences(
            PlannerExecutionContext(
                user=self.user, source='internal_attachment',
                entrypoint=PlannerRolloutPolicy.ENTRYPOINT_INTERNAL_ATTACHMENT,
            ),
            range_start=timezone.make_aware(datetime(2026, 3, 1, 0)),
            range_end=timezone.make_aware(datetime(2026, 3, 4, 0)),
        )['occurrences']
        ref = occurrences[1]['occurrence_ref']
        result = AttachmentHandler.handle_internal(
            self.user, self.session.session_id, 'event', self.event_id,
            occurrence_ref=ref,
        )
        self.assertTrue(result['success'])
        attachment = result['attachment']
        self.assertEqual(attachment.internal_id, self.event_id)
        self.assertEqual(attachment.internal_snapshot['occurrence_ref']['recurrence_id'], ref['recurrence_id'])
        self.assertIn('2026-03-02', attachment.parsed_text)

    def test_rollback_requeues_target_and_deletes_only_later_attachments(self):
        target = SessionAttachment.objects.create(
            user=self.user, session_id=self.session.session_id, type='word',
            filename='target.docx', parsed_text='target', parse_status='completed', message_index=2,
        )
        later = SessionAttachment.objects.create(
            user=self.user, session_id=self.session.session_id, type='word',
            filename='later.docx', parsed_text='later', parse_status='completed', message_index=5,
        )
        result = AttachmentHandler.requeue_target_and_delete_later(self.session.session_id, 2)
        self.assertEqual(result['requeued_count'], 1)
        self.assertEqual(result['deleted_later_count'], 1)
        target.refresh_from_db(); later.refresh_from_db()
        self.assertIsNone(target.message_index)
        self.assertFalse(target.is_deleted)
        self.assertTrue(later.is_deleted)

        AttachmentHandler.mark_sent(
            [target.id], 7, user=self.user, session_id=self.session.session_id
        )
        target.refresh_from_db()
        self.assertEqual(target.message_index, 7)

    def test_todo_and_reminder_internal_attachments_share_normalized_contract(self):
        todo = PlannerApplicationService.create_todo(self.context_for_api(), {
            'title': '附件待办', 'description': '待办正文', 'status': 'pending',
        })['todo']
        reminder = PlannerApplicationService.create_reminder(self.context_for_api(), {
            'title': '附件提醒', 'content': '提醒正文', 'priority': 'normal',
            'trigger': timezone.make_aware(datetime(2026, 3, 1, 12)).isoformat(),
            'recurrence': {'rrule': 'FREQ=DAILY;COUNT=2'},
        })['reminder']
        reminder_ref = PlannerApplicationService.list_reminder_occurrences(
            self.context_for_api(),
            range_start=timezone.make_aware(datetime(2026, 3, 1, 0)),
            range_end=timezone.make_aware(datetime(2026, 3, 4, 0)),
        )['occurrences'][1]['occurrence_ref']

        todo_result = AttachmentHandler.handle_internal(
            self.user, self.session.session_id, 'todo', todo['todo_id']
        )
        reminder_result = AttachmentHandler.handle_internal(
            self.user, self.session.session_id, 'reminder', reminder['reminder_id'],
            occurrence_ref=reminder_ref,
        )
        self.assertTrue(todo_result['success'])
        self.assertIn('待办正文', todo_result['attachment'].parsed_text)
        self.assertTrue(reminder_result['success'])
        self.assertEqual(
            reminder_result['attachment'].internal_snapshot['occurrence_ref']['recurrence_id'],
            reminder_ref['recurrence_id'],
        )

    def test_consumer_freezes_pending_attachment_at_human_message_index(self):
        attachment = SessionAttachment.objects.create(
            user=self.user, session_id=self.session.session_id, type='word',
            filename='message.docx', parsed_text='模型必须看见的正文', parse_status='completed',
        )
        consumer = AgentConsumer()
        consumer.user = self.user
        consumer.session_id = self.session.session_id
        messages = async_to_sync(consumer._build_input_messages)(
            '请阅读附件', [attachment.id], message_index=4,
        )
        self.assertEqual(len(messages), 1)
        self.assertIn('模型必须看见的正文', messages[0].additional_kwargs['attachments_context'])
        attachment.refresh_from_db()
        self.assertEqual(attachment.message_index, 4)

        with self.assertRaisesMessage(ValueError, '附件不存在、已发送或不属于当前会话'):
            async_to_sync(consumer._build_input_messages)(
                '不能重复使用已发送附件', [attachment.id], message_index=6,
            )

    def test_format_endpoint_rejects_stale_or_cross_session_attachment(self):
        pending = SessionAttachment.objects.create(
            user=self.user, session_id=self.session.session_id, type='word',
            filename='pending.docx', parsed_text='pending', parse_status='completed',
        )
        valid = self.client.post('/api/agent/attachments/format/', {
            'session_id': self.session.session_id, 'attachment_ids': [pending.id],
        }, content_type='application/json')
        self.assertEqual(valid.status_code, 200)
        pending.message_index = 2
        pending.save(update_fields=['message_index'])
        stale = self.client.post('/api/agent/attachments/format/', {
            'session_id': self.session.session_id, 'attachment_ids': [pending.id],
        }, content_type='application/json')
        self.assertEqual(stale.status_code, 409)
        pending.message_index = None
        pending.save(update_fields=['message_index'])
        other_session = self.client.post('/api/agent/attachments/format/', {
            'session_id': 'user_1_other', 'attachment_ids': [pending.id],
        }, content_type='application/json')
        self.assertEqual(other_session.status_code, 409)

    def context_for_api(self):
        return PlannerExecutionContext(
            user=self.user, source='web_v2',
            entrypoint=PlannerRolloutPolicy.ENTRYPOINT_API_V2,
        )
