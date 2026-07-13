import hashlib
from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import (
    PlannerCohortAssignment, PlannerMigrationState, ReminderRecurrenceSeries, UserData,
)
from core.planner.application import PlannerApplicationService
from core.planner.context import PlannerExecutionContext
from core.planner.rollout import PlannerRolloutPolicy


@override_settings(PLANNER_STORAGE_MODE='normalized')
class ReminderScopeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='reminder-scope')
        source = UserData.objects.create(user=self.user, key='reminders', value='[]')
        PlannerMigrationState.objects.create(
            user=self.user, source_key='reminders', source_row_id=source.id,
            source_checksum=hashlib.sha256(b'[]').hexdigest(),
            status=PlannerMigrationState.STATUS_VERIFIED,
        )
        PlannerCohortAssignment.objects.create(
            user=self.user, storage_mode=PlannerCohortAssignment.MODE_NORMALIZED,
            entrypoints={
                PlannerRolloutPolicy.ENTRYPOINT_API_V2: {'mode': 'normalized'},
            },
        )
        self.context = PlannerExecutionContext(
            user=self.user, source='test', entrypoint=PlannerRolloutPolicy.ENTRYPOINT_API_V2
        )
        self.start = timezone.make_aware(datetime(2026, 7, 13, 10))
        self.client.force_login(self.user)

    def create(self, *, recurring=True):
        payload = {
            'title': '提醒', 'content': '原内容', 'priority': 'normal',
            'trigger': self.start.isoformat(),
        }
        if recurring:
            payload['recurrence'] = {'rrule': 'FREQ=DAILY;COUNT=5'}
        return PlannerApplicationService.create_reminder(self.context, payload)['reminder']

    def occurrences(self):
        return PlannerApplicationService.list_reminder_occurrences(
            self.context, range_start=self.start - timedelta(days=1),
            range_end=self.start + timedelta(days=10),
        )['occurrences']

    def test_single_reminder_can_attach_recurrence(self):
        reminder = self.create(recurring=False)
        result = PlannerApplicationService.patch_reminder(
            self.context, reminder['reminder_id'],
            {'recurrence': {'rrule': 'FREQ=DAILY;COUNT=3'}}, reminder['version'], scope='all'
        )['reminder']
        self.assertEqual(result['recurrence']['rrule'], 'COUNT=3;FREQ=DAILY')
        self.assertEqual(len(self.occurrences()), 3)

    def test_patch_single_only_changes_selected_occurrence(self):
        reminder = self.create()
        occurrences = self.occurrences()
        selected = occurrences[1]['occurrence_ref']
        PlannerApplicationService.patch_reminder(
            self.context, reminder['reminder_id'],
            {'title': '仅第二次', 'content': '新内容'}, selected['source_version'],
            scope='single', occurrence_ref=selected,
        )
        updated = self.occurrences()
        self.assertEqual([item['title'] for item in updated], ['提醒', '仅第二次', '提醒', '提醒', '提醒'])
        self.assertEqual(updated[1]['content'], '新内容')

    def test_patch_all_changes_time_but_rejects_date_change(self):
        reminder = self.create()
        source_version = self.occurrences()[0]['occurrence_ref']['source_version']
        PlannerApplicationService.patch_reminder(
            self.context, reminder['reminder_id'],
            {'trigger': self.start.replace(hour=11).isoformat()}, source_version, scope='all'
        )
        self.assertTrue(all(
            datetime.fromisoformat(item['start'].replace('Z', '+00:00'))
            .astimezone(timezone.get_current_timezone()).hour == 11
            for item in self.occurrences()
        ))
        current = PlannerApplicationService.list_reminders(self.context)['reminders'][0]
        with self.assertRaisesMessage(Exception, '不允许修改系列起始日期'):
            PlannerApplicationService.patch_reminder(
                self.context, reminder['reminder_id'],
                {'trigger': (self.start + timedelta(days=1)).isoformat()},
                current['recurrence']['source_version'], scope='all'
            )

    def test_this_and_future_creates_child_lineage(self):
        reminder = self.create()
        selected = self.occurrences()[2]['occurrence_ref']
        result = PlannerApplicationService.patch_reminder(
            self.context, reminder['reminder_id'], {'title': '未来提醒'},
            selected['source_version'], scope='this_and_future', occurrence_ref=selected,
        )['reminder']
        self.assertNotEqual(result['reminder_id'], reminder['reminder_id'])
        child = ReminderRecurrenceSeries.objects.get(master_reminder__reminder_id=result['reminder_id'])
        self.assertIsNotNone(child.parent_series_id)
        self.assertEqual(child.split_recurrence_id, selected['recurrence_id'])
        self.assertEqual([item['title'] for item in self.occurrences()], [
            '提醒', '提醒', '未来提醒', '未来提醒', '未来提醒'
        ])

    def test_all_can_replace_and_remove_recurrence(self):
        reminder = self.create()
        version = self.occurrences()[0]['occurrence_ref']['source_version']
        replaced = PlannerApplicationService.patch_reminder(
            self.context, reminder['reminder_id'],
            {'recurrence': {'rrule': 'FREQ=WEEKLY;COUNT=2'}}, version, scope='all',
        )['reminder']
        self.assertEqual(replaced['recurrence']['rrule'], 'COUNT=2;FREQ=WEEKLY')
        self.assertEqual(len(self.occurrences()), 2)
        detached = PlannerApplicationService.patch_reminder(
            self.context, reminder['reminder_id'], {'recurrence': None},
            replaced['recurrence']['source_version'], scope='all',
        )['reminder']
        self.assertIsNone(detached['recurrence'])
        self.assertEqual(len(self.occurrences()), 1)

    def test_this_and_future_can_replace_child_rule_and_trigger(self):
        reminder = self.create()
        selected = self.occurrences()[2]['occurrence_ref']
        child = PlannerApplicationService.patch_reminder(
            self.context, reminder['reminder_id'], {
                'title': '每周未来提醒',
                'trigger': self.start.replace(day=15, hour=14).isoformat(),
                'recurrence': {'rrule': 'FREQ=WEEKLY;COUNT=2'},
            }, selected['source_version'], scope='this_and_future', occurrence_ref=selected,
        )['reminder']
        self.assertEqual(child['recurrence']['rrule'], 'COUNT=2;FREQ=WEEKLY')
        starts = [datetime.fromisoformat(item['start']).astimezone(timezone.get_current_timezone())
                  for item in self.occurrences()]
        self.assertEqual(
            [(item.day, item.hour) for item in starts],
            [(13, 10), (14, 10), (15, 14), (22, 14)],
        )

    def test_stale_source_version_is_rejected(self):
        reminder = self.create()
        ref = self.occurrences()[0]['occurrence_ref']
        PlannerApplicationService.patch_reminder(
            self.context, reminder['reminder_id'], {'title': '新标题'},
            ref['source_version'], scope='all',
        )
        with self.assertRaisesMessage(Exception, '版本冲突'):
            PlannerApplicationService.patch_reminder(
                self.context, reminder['reminder_id'], {'title': '旧写入'},
                ref['source_version'], scope='all',
            )

    def test_delete_single_and_future(self):
        reminder = self.create()
        items = self.occurrences()
        PlannerApplicationService.delete_reminder(
            self.context, reminder['reminder_id'], items[1]['occurrence_ref']['source_version'],
            scope='single', occurrence_ref=items[1]['occurrence_ref'],
        )
        remaining = self.occurrences()
        self.assertEqual(len(remaining), 4)
        anchor = remaining[2]['occurrence_ref']
        PlannerApplicationService.delete_reminder(
            self.context, reminder['reminder_id'], anchor['source_version'],
            scope='this_and_future', occurrence_ref=anchor,
        )
        self.assertEqual(len(self.occurrences()), 2)

    def test_v2_api_accepts_recurrence_and_scope_contract(self):
        created = self.client.post('/api/v2/reminders/', {
            'title': 'API提醒', 'content': '', 'priority': 'normal',
            'trigger': self.start.isoformat(),
        }, content_type='application/json')
        self.assertEqual(created.status_code, 201)
        reminder = created.json()['reminder']
        attached = self.client.patch(
            f"/api/v2/reminders/{reminder['reminder_id']}/",
            {
                'scope': 'all', 'expected_version': reminder['version'],
                'recurrence': {'rrule': 'FREQ=DAILY;COUNT=3'},
            }, content_type='application/json',
        )
        self.assertEqual(attached.status_code, 200)
        occurrences = self.client.get(
            '/api/v2/reminders/',
            {'from': self.start.isoformat(), 'to': (self.start + timedelta(days=5)).isoformat()},
        ).json()['occurrences']
        target = occurrences[1]['occurrence_ref']
        patched = self.client.patch(
            f"/api/v2/reminders/{reminder['reminder_id']}/",
            {
                'scope': 'single', 'occurrence_ref': target,
                'expected_version': target['source_version'], 'title': 'API单次修改',
            }, content_type='application/json',
        )
        self.assertEqual(patched.status_code, 200)
        after = self.client.get(
            '/api/v2/reminders/',
            {'from': self.start.isoformat(), 'to': (self.start + timedelta(days=5)).isoformat()},
        ).json()['occurrences']
        self.assertEqual([item['title'] for item in after], ['API提醒', 'API单次修改', 'API提醒'])
