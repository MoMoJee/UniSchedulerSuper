import base64
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token

from agent_service.tools.planner_application_adapter import should_use_normalized
from core.models import PlannerCohortAssignment, UserData
from core.planner.p6 import RETIRED_DISPOSITION
from core.planner.rollout import PlannerRolloutPolicy


@override_settings(PLANNER_STORAGE_MODE='normalized')
class P6RuntimeNoFallbackTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('User1', password='password')
        self.token = Token.objects.create(user=self.user)
        self.legacy = UserData.objects.create(user=self.user, key='events', value='[{"legacy":true}]')
        PlannerCohortAssignment.objects.create(
            user=self.user,
            storage_mode='legacy',
            entrypoints={name: {'mode': 'quarantined'} for name in PlannerRolloutPolicy.ALL_ENTRYPOINTS},
            metadata={'p6_disposition': RETIRED_DISPOSITION, 'p6_cutover_manifest': {'schema': 1, 'sources': []}},
        )

    def test_v2_feed_and_caldav_return_stable_denial_without_legacy_read(self):
        before = self.legacy.value
        self.client.force_login(self.user)
        with patch('core.planner.legacy.LegacyPlannerRepository.read', side_effect=AssertionError('legacy read')):
            v2 = self.client.get('/api/v2/events/occurrences/?from=2026-01-01&to=2026-02-01')
            feed = self.client.get('/api/calendar/feed/', {'token': self.token.key, 'type': 'events'})
            auth = base64.b64encode(f'{self.user.username}:{self.token.key}'.encode()).decode()
            caldav = self.client.generic(
                'PROPFIND', f'/caldav/{self.user.username}/',
                HTTP_AUTHORIZATION=f'Basic {auth}', HTTP_DEPTH='1',
            )
        self.assertEqual(v2.status_code, 423)
        self.assertEqual(v2.json()['code'], 'planner_retired_quarantine')
        self.assertEqual(feed.status_code, 423)
        self.assertEqual(caldav.status_code, 423)
        self.legacy.refresh_from_db()
        self.assertEqual(self.legacy.value, before)

    def test_agent_and_course_import_never_select_legacy(self):
        config = {'configurable': {'user': self.user, 'planner_source': 'websocket_agent'}}
        self.assertTrue(should_use_normalized(config))
        self.client.force_login(self.user)
        response = self.client.post(
            '/api/import/confirm/',
            {'courses': [{'name': 'blocked', 'start': '2026-01-01T10:00:00', 'end': '2026-01-01T11:00:00'}]},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 423)
        self.assertEqual(response.json()['code'], 'planner_retired_quarantine')
