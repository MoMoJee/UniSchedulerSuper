"""日历事件扩展 Payload 的存储、查询、隔离与限制测试。"""

import hashlib
from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    CalendarEvent,
    PlannerChangeSet,
    PlannerCohortAssignment,
    PlannerMigrationState,
    UserData,
)
from core.planner.payloads import (
    PayloadValidationError,
    list_payload_registrations,
    normalize_event_payload,
    validate_json_schema,
)


@override_settings(PLANNER_STORAGE_MODE='normalized')
class PlannerEventPayloadApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='payload-user', password='test-password')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.start = timezone.make_aware(datetime(2026, 5, 1, 9, 0))
        self.end = self.start + timedelta(hours=1)
        self._mark_verified()

    def _mark_verified(self):
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

    def _create(self, *, payload='__omitted__', recurrence=None):
        body = {
            'title': '携带扩展数据的日程',
            'start': self.start.isoformat(),
            'end': self.end.isoformat(),
        }
        if payload != '__omitted__':
            body['payload'] = payload
        if recurrence is not None:
            body['recurrence'] = recurrence
        return self.client.post('/api/v2/events/', body, format='json')

    def _definitions(self, query=''):
        return self.client.get(f'/api/v2/events/definitions/?from=2026-05-01&to=2026-05-02{query}')

    def _occurrences(self, query=''):
        return self.client.get(f'/api/v2/events/occurrences/?from=2026-05-01&to=2026-05-02{query}')

    def test_create_and_query_returns_two_isolated_payloads(self):
        payload = {
            'org.uss.scheduler': {
                'format': 'json',
                'data': {'source': 'api-test', 'counter': 1},
            },
            'com.acme.notes': {
                'format': 'json',
                'data': {'freeform': [1, 2, 3]},
            },
        }

        created = self._create(payload=payload)

        self.assertEqual(created.status_code, 201, created.content)
        expected = {
            'org.uss.scheduler': {'format': 'json', 'data': {'source': 'api-test', 'counter': 1}},
            'com.acme.notes': {'format': 'json', 'data': {'freeform': [1, 2, 3]}},
        }
        self.assertEqual(created.json()['event']['payload'], expected)
        event = CalendarEvent.objects.get(user=self.user)
        self.assertEqual(event.payload, expected)

        definitions = self._definitions()
        occurrences = self._occurrences()

        self.assertEqual(definitions.status_code, 200, definitions.content)
        self.assertEqual(definitions.json()['definitions'][0]['payload'], expected)
        self.assertEqual(occurrences.status_code, 200, occurrences.content)
        self.assertEqual(occurrences.json()['occurrences'][0]['payload'], expected)
        self.assertEqual(
            definitions.json()['definitions'][0]['payload']['org.uss.scheduler'],
            expected['org.uss.scheduler'],
        )
        self.assertEqual(
            definitions.json()['definitions'][0]['payload']['com.acme.notes'],
            expected['com.acme.notes'],
        )

    def test_query_can_opt_out_of_payload(self):
        created = self._create(payload={'com.acme.notes': {'format': 'json', 'data': {'x': 1}}})
        self.assertEqual(created.status_code, 201, created.content)

        definitions = self._definitions('&include_payload=0')
        occurrences = self._occurrences('&include_payload=false')
        included = self._occurrences('&include_payload=1')
        invalid = self._occurrences('&include_payload=maybe')

        self.assertEqual(definitions.status_code, 200, definitions.content)
        self.assertEqual(occurrences.status_code, 200, occurrences.content)
        self.assertNotIn('payload', definitions.json()['definitions'][0])
        self.assertNotIn('payload', occurrences.json()['occurrences'][0])
        self.assertEqual(
            included.json()['occurrences'][0]['payload']['com.acme.notes']['data'],
            {'x': 1},
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.json()['code'], 'invalid_include_payload')

    def test_event_without_payload_can_be_created_queried_and_updated(self):
        created = self._create()
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.json()['event']['payload'], {})

        event = CalendarEvent.objects.get(user=self.user)
        self.assertEqual(event.payload, {})
        self.assertEqual(self._occurrences().json()['occurrences'][0]['payload'], {})

        patched = self.client.patch(
            f'/api/v2/events/{event.event_id}/',
            {'title': '无扩展数据也可更新', 'expected_version': event.version},
            format='json',
        )

        self.assertEqual(patched.status_code, 200, patched.content)
        refreshed = self._occurrences().json()['occurrences'][0]
        self.assertEqual(refreshed['title'], '无扩展数据也可更新')
        self.assertEqual(refreshed['payload'], {})

    def test_payload_update_replaces_keys_and_can_be_cleared(self):
        created = self._create(payload={
            'org.uss.scheduler': {'format': 'json', 'data': {'source': 'v1'}},
            'com.acme.notes': {'format': 'json', 'data': {'note': 'old'}},
        })
        event = CalendarEvent.objects.get(user=self.user)
        self.assertEqual(created.status_code, 201, created.content)

        replaced = self.client.patch(
            f'/api/v2/events/{event.event_id}/',
            {
                'expected_version': event.version,
                'payload': {'org.uss.scheduler': {'format': 'json', 'data': {'source': 'v2'}}},
            },
            format='json',
        )

        self.assertEqual(replaced.status_code, 200, replaced.content)
        event.refresh_from_db()
        self.assertEqual(
            event.payload,
            {'org.uss.scheduler': {'format': 'json', 'data': {'source': 'v2'}}},
        )

        cleared = self.client.patch(
            f'/api/v2/events/{event.event_id}/',
            {'expected_version': event.version, 'payload': {}},
            format='json',
        )
        self.assertEqual(cleared.status_code, 200, cleared.content)
        event.refresh_from_db()
        self.assertEqual(event.payload, {})

        # null 等价于清空，不把 payload 变成字符串或列表。
        null_cleared = self.client.patch(
            f'/api/v2/events/{event.event_id}/',
            {'expected_version': event.version, 'payload': None},
            format='json',
        )
        self.assertEqual(null_cleared.status_code, 200, null_cleared.content)
        event.refresh_from_db()
        self.assertEqual(event.payload, {})

    def test_unknown_registration_and_unknown_format_are_preserved(self):
        created = self._create(payload={
            'com.acme.unknown': {'format': 'XML', 'data': '<note>保留</note>'},
            'single-key': {'format': 'yaml', 'data': 'a: 1', 'version': 7},
        })

        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(
            created.json()['event']['payload'],
            {
                'com.acme.unknown': {'format': 'xml', 'data': '<note>保留</note>'},
                'single-key': {'format': 'yaml', 'data': 'a: 1', 'version': 7},
            },
        )
        # 未知注册名不参与 schema 校验，也不会影响基础查询。
        self.assertEqual(CalendarEvent.objects.get(user=self.user).title, '携带扩展数据的日程')

    def test_split_and_detach_copy_master_payload(self):
        expected = {'org.uss.scheduler': {'format': 'json', 'data': {'source': 'master'}}}
        created = self._create(
            payload=expected,
            recurrence={'rrule': 'FREQ=DAILY;COUNT=3'},
        )
        self.assertEqual(created.status_code, 201, created.content)
        window = '/api/v2/events/occurrences/?from=2026-05-01&to=2026-05-05'
        target = self.client.get(window).json()['occurrences'][1]['occurrence_ref']

        split = self.client.patch(
            f"/api/v2/events/{created.json()['event']['event_id']}/",
            {
                'scope': 'this_and_future',
                'occurrence_ref': target,
                'expected_version': target['source_version'],
                'title': '分裂后的子系列',
            },
            format='json',
        )

        self.assertEqual(split.status_code, 200, split.content)
        child_id = split.json()['event_id']
        child_rows = [
            item for item in self.client.get(window).json()['occurrences']
            if item['occurrence_ref']['entity_id'] == child_id
        ]
        self.assertTrue(child_rows)
        self.assertTrue(all(item['payload'] == expected for item in child_rows))

        created_again = self._create(
            payload=expected,
            recurrence={'rrule': 'FREQ=DAILY;COUNT=3'},
        )
        self.assertEqual(created_again.status_code, 201, created_again.content)
        created_again_id = created_again.json()['event']['event_id']
        detach_target = [
            item for item in self.client.get(window).json()['occurrences']
            if item['occurrence_ref']['entity_id'] == created_again_id
        ][-1]['occurrence_ref']
        detached = self.client.patch(
            f"/api/v2/events/{created_again.json()['event']['event_id']}/",
            {
                'scope': 'single',
                'occurrence_ref': detach_target,
                'expected_version': detach_target['source_version'],
                'detach': True,
            },
            format='json',
        )

        self.assertEqual(detached.status_code, 200, detached.content)
        detached_id = detached.json()['event_id']
        detached_rows = [
            item for item in self.client.get(window).json()['occurrences']
            if item['occurrence_ref']['entity_id'] == detached_id
        ]
        self.assertTrue(detached_rows)
        self.assertTrue(all(item['payload'] == expected for item in detached_rows))

    def test_conflict_and_search_queries_return_or_omit_payload(self):
        first = self._create(payload={'com.acme.notes': {'format': 'json', 'data': {'n': 1}}})
        self.assertEqual(first.status_code, 201, first.content)
        second = self._create(payload={'com.acme.notes': {'format': 'json', 'data': {'n': 2}}})
        self.assertEqual(second.status_code, 201, second.content)

        conflicts = self.client.get(
            '/api/v2/events/conflicts/?from=2026-05-01&to=2026-05-02'
        )
        search = self.client.get(
            '/api/v2/search/?from=2026-05-01&to=2026-05-02&types=event'
        )
        conflicts_without = self.client.get(
            '/api/v2/events/conflicts/?from=2026-05-01&to=2026-05-02&include_payload=0'
        )
        search_without = self.client.get(
            '/api/v2/search/?from=2026-05-01&to=2026-05-02&types=event&include_payload=0'
        )

        self.assertEqual(conflicts.status_code, 200, conflicts.content)
        self.assertTrue(all('payload' in item for pair in conflicts.json()['conflicts'] for item in pair['items']))
        self.assertTrue(all('payload' in item for item in search.json()['results']))
        self.assertTrue(
            all('payload' not in item for pair in conflicts_without.json()['conflicts'] for item in pair['items'])
        )
        self.assertTrue(all('payload' not in item for item in search_without.json()['results']))

    def test_registered_schema_violation_rejects_write_without_side_effects(self):
        count_before = CalendarEvent.objects.count()
        changes_before = PlannerChangeSet.objects.count()

        response = self._create(payload={
            'org.uss.scheduler': {'format': 'json', 'data': ['not-an-object']},
        })

        self.assertEqual(response.status_code, 422, response.content)
        self.assertEqual(response.json()['code'], 'payload_schema_violation')
        self.assertEqual(CalendarEvent.objects.count(), count_before)
        self.assertEqual(PlannerChangeSet.objects.count(), changes_before)

    def test_payload_limits_are_enforced(self):
        with self.settings(PLANNER_EVENT_PAYLOAD_MAX_KEYS=1):
            too_many = self._create(payload={
                'a.one': {'format': 'json', 'data': {}},
                'b.two': {'format': 'json', 'data': {}},
            })
        self.assertEqual(too_many.status_code, 422)
        self.assertEqual(too_many.json()['code'], 'payload_too_large')

        with self.settings(PLANNER_EVENT_PAYLOAD_MAX_ENTRY_BYTES=16):
            too_large_entry = self._create(payload={
                'com.acme.notes': {'format': 'json', 'data': {'text': 'x' * 64}},
            })
        self.assertEqual(too_large_entry.status_code, 422)
        self.assertEqual(too_large_entry.json()['code'], 'payload_too_large')

        with self.settings(PLANNER_EVENT_PAYLOAD_MAX_TOTAL_BYTES=70):
            too_large_total = self._create(payload={
                'com.acme.one': {'format': 'json', 'data': {'text': 'x' * 32}},
                'com.acme.two': {'format': 'json', 'data': {'text': 'y' * 32}},
            })
        self.assertEqual(too_large_total.status_code, 422)
        self.assertEqual(too_large_total.json()['code'], 'payload_too_large')

        with self.settings(PLANNER_EVENT_PAYLOAD_MAX_KEY_LENGTH=4):
            bad_key = self._create(payload={
                'com.acme.long': {'format': 'json', 'data': {}},
            })
        self.assertEqual(bad_key.status_code, 422)
        self.assertEqual(bad_key.json()['code'], 'payload_key_invalid')

    def test_invalid_payload_shape_is_rejected(self):
        cases = [
            (['not-a-map'], 'invalid_payload'),
            ({'com.acme.notes': {'data': {}}}, 'payload_entry_invalid'),
            ({'com.acme.notes': {'format': 'json'}}, 'payload_entry_invalid'),
            ({'com.acme.notes': {'format': 'json', 'data': {}, 'extra': True}}, 'payload_entry_invalid'),
            ({'com.acme.notes': {'format': 'json!', 'data': {}}}, 'payload_entry_invalid'),
            ({'com.acme.notes': {'format': 'json', 'data': {}, 'version': 0}}, 'payload_entry_invalid'),
            ({'com.acme.notes': {'format': 'json', 'data': {}, 'version': True}}, 'payload_entry_invalid'),
            ({'bad key': {'format': 'json', 'data': {}}}, 'payload_key_invalid'),
        ]
        for payload, expected_code in cases:
            with self.subTest(payload=payload):
                response = self._create(payload=payload)
                self.assertEqual(response.status_code, 422, response.content)
                self.assertEqual(response.json()['code'], expected_code)

        self.assertEqual(CalendarEvent.objects.count(), 0)

    def test_recurring_occurrences_inherit_master_payload_and_scope_is_limited(self):
        created = self._create(
            payload={'org.uss.scheduler': {'format': 'json', 'data': {'source': 'series'}}},
            recurrence={'rrule': 'FREQ=DAILY;COUNT=2'},
        )
        self.assertEqual(created.status_code, 201, created.content)
        event = CalendarEvent.objects.get(user=self.user)

        occurrences = self.client.get(
            '/api/v2/events/occurrences/?from=2026-05-01&to=2026-05-03'
        ).json()['occurrences']
        self.assertEqual(len(occurrences), 2)
        self.assertTrue(all(item['payload'] == created.json()['event']['payload'] for item in occurrences))

        patched_all = self.client.patch(
            f'/api/v2/events/{event.event_id}/',
            {
                'expected_version': event.version,
                'scope': 'all',
                'payload': {'org.uss.scheduler': {'format': 'json', 'data': {'source': 'all'}}},
            },
            format='json',
        )
        self.assertEqual(patched_all.status_code, 200, patched_all.content)
        event.refresh_from_db()
        self.assertEqual(event.payload['org.uss.scheduler']['data'], {'source': 'all'})

        single = self.client.patch(
            f'/api/v2/events/{event.event_id}/',
            {
                'expected_version': event.version,
                'scope': 'single',
                'payload': {'org.uss.scheduler': {'format': 'json', 'data': {'source': 'single'}}},
            },
            format='json',
        )
        self.assertEqual(single.status_code, 422)
        self.assertEqual(single.json()['code'], 'payload_scope_not_supported')

        future = self.client.patch(
            f'/api/v2/events/{event.event_id}/',
            {
                'expected_version': event.version,
                'scope': 'this_and_future',
                'payload': {'org.uss.scheduler': {'format': 'json', 'data': {'source': 'future'}}},
            },
            format='json',
        )
        self.assertEqual(future.status_code, 422)
        self.assertEqual(future.json()['code'], 'payload_scope_not_supported')


class EventPayloadValidationUnitTests(TestCase):
    def test_registry_contains_versioned_schema(self):
        registrations = {item.key: item for item in list_payload_registrations()}
        self.assertIn('org.uss.scheduler', registrations)
        self.assertEqual(registrations['org.uss.scheduler'].schema_version, 1)
        self.assertEqual(registrations['org.uss.scheduler'].schema['type'], 'object')

    def test_normalize_deep_copies_data(self):
        raw = {'com.acme.notes': {'format': 'json', 'data': {'items': [1, 2]}}}
        normalized = normalize_event_payload(raw)
        normalized['com.acme.notes']['data']['items'].append(3)
        self.assertEqual(raw['com.acme.notes']['data']['items'], [1, 2])

    def test_normalize_rejects_non_json_data(self):
        with self.assertRaises(PayloadValidationError) as context:
            normalize_event_payload({'com.acme.notes': {'format': 'json', 'data': {1, 2}}})
        self.assertEqual(context.exception.code, 'invalid_payload_data')

    def test_schema_validator_supports_required_properties_and_local_refs(self):
        schema = {
            'type': 'object',
            'required': ['name'],
            'properties': {'name': {'type': 'string', 'minLength': 2}},
            'additionalProperties': False,
        }
        self.assertEqual(validate_json_schema({'name': 'ok'}, schema), [])
        self.assertTrue(validate_json_schema({'name': 'x', 'extra': 1}, schema))
        self.assertTrue(validate_json_schema({}, schema))

        referenced = {
            '$defs': {'name': {'type': 'string'}},
            'type': 'object',
            'properties': {'name': {'$ref': '#/$defs/name'}},
        }
        self.assertEqual(validate_json_schema({'name': 'ok'}, referenced), [])
        self.assertTrue(validate_json_schema({'name': 1}, referenced))

    def test_schema_validator_handles_combinators_and_item_constraints(self):
        schema = {
            'type': 'array',
            'items': {'oneOf': [{'type': 'string'}, {'type': 'integer', 'minimum': 1}]},
            'minItems': 1,
            'uniqueItems': True,
        }
        self.assertEqual(validate_json_schema(['a', 2], schema), [])
        self.assertTrue(validate_json_schema([], schema))
        self.assertTrue(validate_json_schema(['a', 'a'], schema))
        self.assertTrue(validate_json_schema([0], schema))
