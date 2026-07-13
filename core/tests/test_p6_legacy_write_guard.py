from django.contrib.auth.models import User
from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase

from core.models import CalendarEvent, PlannerLegacyWriteGuard, UserData
from core.planner.commands import PlannerCommandService
from core.planner.legacy import LegacyPlannerWriteForbidden, PlannerUserDataCompat


class P6LegacyWriteGuardTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = User.objects.create_user('p6-guard-user')
        self.planner_row = UserData.objects.create(user=self.user, key='events', value='[]')
        PlannerLegacyWriteGuard.objects.update_or_create(singleton=True, defaults={'enabled': True})

    def tearDown(self):
        # Django flush must be able to clean the isolated test database.
        PlannerLegacyWriteGuard.objects.filter(singleton=True).update(enabled=False)
        super().tearDown()

    def _assert_integrity_blocked(self, operation):
        with self.assertRaises(IntegrityError), transaction.atomic():
            operation()

    def test_orm_raw_sql_and_compat_planner_writes_are_blocked(self):
        self._assert_integrity_blocked(lambda: UserData.objects.create(user=self.user, key='todos', value='[]'))
        self._assert_integrity_blocked(lambda: UserData.objects.filter(pk=self.planner_row.pk).update(value='[1]'))
        self._assert_integrity_blocked(lambda: UserData.objects.filter(pk=self.planner_row.pk).delete())
        self._assert_integrity_blocked(self._raw_insert)
        request = type('Request', (), {'user': self.user})()
        with self.assertRaises(LegacyPlannerWriteForbidden):
            PlannerUserDataCompat.get_or_initialize(request, 'reminders', [])

    def test_configuration_userdata_and_normalized_commands_still_write(self):
        config = UserData.objects.create(user=self.user, key='ui_settings', value='{}')
        config.value = '{"theme":"dark"}'
        config.save(update_fields=['value'])
        event = PlannerCommandService.create_event(self.user, {
            'title': 'normalized survives guard',
            'start': '2026-07-13T10:00:00+08:00',
            'end': '2026-07-13T11:00:00+08:00',
        })
        self.assertTrue(CalendarEvent.objects.filter(pk=event.pk).exists())
        config.delete()

    def _raw_insert(self):
        with connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO core_userdata (user_id, key, value) VALUES (%s, %s, %s)',
                [self.user.id, 'reminders', '[]'],
            )
