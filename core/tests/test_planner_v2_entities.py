"""P3-C Todo/Reminder/Group normalized v2 集成测试。"""

import hashlib
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.models import (
    CalendarEvent,
    PlannerCohortAssignment,
    PlannerMigrationState,
    Reminder,
    ReminderOccurrenceState,
    Todo,
    TodoDependency,
    UserData,
)


@override_settings(PLANNER_STORAGE_MODE='normalized')
class PlannerV2EntityApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='planner-entity-user', password='test-password')
        source = UserData.objects.create(user=self.user, key='events', value='[]')
        PlannerMigrationState.objects.create(
            user=self.user,
            source_key='events',
            source_row_id=source.id,
            source_checksum=hashlib.sha256(b'[]').hexdigest(),
            status=PlannerMigrationState.STATUS_VERIFIED,
        )
        PlannerCohortAssignment.objects.create(
            user=self.user,
            storage_mode=PlannerCohortAssignment.MODE_NORMALIZED,
            entrypoints={'api_v2': {'mode': 'normalized'}},
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_group_and_todo_crud_dependencies_and_conversion_are_normalized(self):
        group_response = self.client.post('/api/v2/groups/', {'name': '学习', 'color': '#123456'}, format='json')
        self.assertEqual(group_response.status_code, 201, group_response.content)
        group_id = group_response.json()['group']['group_id']
        first = self.client.post(
            '/api/v2/todos/',
            {'title': '准备材料', 'group_id': group_id, 'due': '2026-03-01T08:00:00+08:00', 'tags': ['课程']},
            format='json',
        )
        second = self.client.post('/api/v2/todos/', {'title': '提交材料'}, format='json')
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(second.status_code, 201, second.content)
        first_id = first.json()['todo']['todo_id']
        second_id = second.json()['todo']['todo_id']

        dependency = self.client.patch(
            f'/api/v2/todos/{second_id}/',
            {'expected_version': 1, 'dependencies': [first_id]},
            format='json',
        )
        cycle = self.client.patch(
            f'/api/v2/todos/{first_id}/',
            {'expected_version': 1, 'dependencies': [second_id]},
            format='json',
        )
        converted = self.client.post(
            f'/api/v2/todos/{first_id}/convert/',
            {
                'expected_version': 1,
                'start': '2026-03-01T09:00:00+08:00',
                'end': '2026-03-01T10:00:00+08:00',
            },
            format='json',
        )

        self.assertEqual(dependency.status_code, 200, dependency.content)
        self.assertEqual(TodoDependency.objects.count(), 1)
        self.assertEqual(cycle.status_code, 422, cycle.content)
        self.assertEqual(cycle.json()['code'], 'todo_dependency_cycle')
        self.assertEqual(converted.status_code, 200, converted.content)
        self.assertEqual(CalendarEvent.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Todo.objects.get(todo_id=first_id).status, 'completed')

    def test_recurring_reminder_reads_do_not_materialize_states_and_action_is_sparse(self):
        create = self.client.post(
            '/api/v2/reminders/',
            {
                'title': '每日服药',
                'trigger': '2026-03-01T09:00:00+08:00',
                'recurrence': {'rrule': 'FREQ=DAILY;COUNT=2'},
            },
            format='json',
        )
        self.assertEqual(create.status_code, 201, create.content)
        first_read = self.client.get('/api/v2/reminders/?from=2026-03-01&to=2026-03-04')
        second_read = self.client.get('/api/v2/reminders/?from=2026-03-01&to=2026-03-04')
        self.assertEqual(first_read.status_code, 200, first_read.content)
        self.assertEqual(first_read.json()['count'], 2)
        self.assertEqual(second_read.json()['count'], 2)
        self.assertEqual(ReminderOccurrenceState.objects.count(), 0)
        ref = first_read.json()['occurrences'][0]['occurrence_ref']

        action = self.client.post(
            '/api/v2/reminders/occurrences/action/',
            {'action': 'complete', 'expected_version': ref['source_version'], 'occurrence_ref': ref},
            format='json',
        )

        self.assertEqual(action.status_code, 200, action.content)
        self.assertEqual(Reminder.objects.count(), 1)
        self.assertEqual(ReminderOccurrenceState.objects.filter(status='completed').count(), 1)

        reset = self.client.post(
            '/api/v2/reminders/occurrences/action/',
            {
                'action': 'reset',
                'expected_version': action.json()['source_version'],
                'occurrence_ref': ref,
            },
            format='json',
        )
        after_reset = self.client.get('/api/v2/reminders/?from=2026-03-01&to=2026-03-04')
        self.assertEqual(reset.status_code, 200, reset.content)
        self.assertEqual(after_reset.json()['occurrences'][0]['status'], 'active')
        self.assertEqual(ReminderOccurrenceState.objects.count(), 1)

    def test_search_merges_event_todo_and_reminder(self):
        self.client.post(
            '/api/v2/events/',
            {'title': '统一关键词事件', 'start': '2026-03-01T09:00:00+08:00', 'end': '2026-03-01T10:00:00+08:00'},
            format='json',
        )
        self.client.post('/api/v2/todos/', {'title': '统一关键词待办'}, format='json')
        self.client.post(
            '/api/v2/reminders/',
            {'title': '统一关键词提醒', 'trigger': '2026-03-01T11:00:00+08:00'},
            format='json',
        )

        response = self.client.get('/api/v2/search/?q=统一关键词&from=2026-03-01&to=2026-03-02')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['total'], 3)
        self.assertEqual({item['entity_type'] for item in response.json()['results']}, {'event', 'todo', 'reminder'})
