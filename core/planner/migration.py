"""legacy Planner JSON 到正规化表的可重跑导入逻辑。

本模块只构建旁路投影，不改变 legacy JSON，也不负责切换读取流量。
任何不能逐项解释的数据都会进入 issue，调用方据此阻止用户进入 cohort。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable

import reversion
from django.contrib.auth.models import User
from django.db import transaction

from core.models import (
    CalendarEvent,
    CollaborativeCalendarGroup,
    EventGroup,
    EventRecurrenceExDate,
    EventRecurrenceSeries,
    EventReminderLink,
    EventShareGroup,
    EventTag,
    PlannerLegacyIdMap,
    PlannerMigrationIssue,
    PlannerMigrationState,
    Reminder,
    ReminderAdvanceTrigger,
    ReminderOccurrenceState,
    ReminderRecurrenceExDate,
    ReminderRecurrenceSeries,
    Todo,
    TodoDependency,
    TodoReminderLink,
    TodoTag,
)
from core.planner.legacy import LegacyPlannerDataError, LegacyPlannerPayload, LegacyPlannerRepository
from core.planner.recurrence.codec import InvalidRRuleError, PlannerTimeCodec, PlannerTimeError, canonicalize_rrule
from core.planner.recurrence.expander import RecurrenceDefinition, RecurrenceExpander
from logger import logger


SOURCE_KEYS = (
    'events_groups',
    'todos',
    'reminders',
    'events',
    'events_rrule_series',
    'rrule_series_storage',
)
LIST_SOURCE_KEYS = frozenset({'events_groups', 'todos', 'reminders', 'events'})
RULE_SOURCE_KEYS = frozenset({'events_rrule_series', 'rrule_series_storage'})
_DURATION_RE = re.compile(r'^(?:(\d+)h)?(?:(\d+)m)?$')


@dataclass(frozen=True)
class MigrationIssueSpec:
    """尚未持久化的迁移问题。"""

    source_key: str
    code: str
    legacy_id: str = ''
    series_id: str = ''
    detail: dict[str, Any] = field(default_factory=dict)


class PlannerLegacyMigration:
    """单用户的导入计划与 apply 逻辑。"""

    def __init__(self, user: User):
        self.user = user
        self.payloads: dict[str, LegacyPlannerPayload] = {}
        self.issues: list[MigrationIssueSpec] = []
        self.counts: Counter[str] = Counter()
        self._groups: dict[str, EventGroup] = {}
        self._events: dict[str, CalendarEvent] = {}
        self._todos: dict[str, Todo] = {}
        self._reminders: dict[str, Reminder] = {}
        self._event_rows: list[dict[str, Any]] = []
        self._todo_rows: list[dict[str, Any]] = []
        self._reminder_rows: list[dict[str, Any]] = []
        self._rule_cache: dict[tuple[str, str], tuple[str | None, tuple[str, ...]]] = {}

    def build_plan(self) -> dict[str, Any]:
        """读取 source 并分类；该方法没有数据库写副作用。"""
        self._load_payloads()
        self._event_rows = self._items('events')
        self._todo_rows = self._items('todos')
        self._reminder_rows = self._items('reminders')

        self._validate_required_ids(self._items('events_groups'), 'events_groups')
        self._validate_required_ids(self._todo_rows, 'todos')
        self._validate_required_ids(self._reminder_rows, 'reminders')
        self._validate_required_ids(self._event_rows, 'events')
        self._validate_importable_entities()

        recurring_events = self._recurring_groups(self._event_rows)
        recurring_reminders = self._recurring_groups(self._reminder_rows)
        self.counts['event_groups'] = len(self._items('events_groups'))
        self.counts['todos'] = len(self._todo_rows)
        self.counts['reminders'] = len(self._reminder_rows)
        self.counts['events'] = len(self._event_rows)
        self.counts['event_series_candidates'] = len(recurring_events)
        self.counts['reminder_series_candidates'] = len(recurring_reminders)

        for series_id, rows in recurring_events.items():
            self._validate_event_series(series_id, rows)
        for series_id, rows in recurring_reminders.items():
            self._validate_reminder_series(series_id, rows)
        self._validate_references()

        return self.report(applied=False)

    def apply(self) -> dict[str, Any]:
        """在单一事务中写入该用户的旁路投影、state 与 issue。"""
        if not self.payloads:
            self.build_plan()
        if self._is_already_imported():
            report = self.report(applied=False)
            report['skipped'] = 'source_checksum_unchanged'
            return report

        with transaction.atomic(), reversion.create_revision():
            reversion.set_user(self.user)
            reversion.set_comment('Import legacy Planner JSON into normalized shadow tables')
            self._import_groups()
            self._import_todos()
            self._import_reminders()
            self._import_events()
            self._import_relationships()
            self._persist_states_and_issues()

        logger.info(
            f'Planner legacy 导入完成: user={self.user.id}, '
            f'counts={dict(self.counts)}, issues={len(self.issues)}'
        )
        return self.report(applied=True)

    def record_quarantine(self) -> dict[str, Any]:
        """仅持久化隔离 state/issue，不导入任何 normalized 业务实体。"""
        if not self.payloads:
            self.build_plan()
        if not self.issues:
            raise ValueError('没有 migration issue，不能记录 quarantine')
        with transaction.atomic(), reversion.create_revision():
            reversion.set_user(self.user)
            reversion.set_comment('Record Planner migration quarantine')
            self._persist_states_and_issues(quarantine_all=True)
        report = self.report(applied=True)
        report['quarantine_recorded'] = True
        return report

    def report(self, *, applied: bool) -> dict[str, Any]:
        """返回可机读报告；不带原始业务正文或敏感配置。"""
        return {
            'user_id': self.user.id,
            'username': self.user.username,
            'applied': applied,
            'source_rows': {
                key: {
                    'source_row_id': payload.source_row_id,
                    'checksum': payload.checksum,
                    'item_count': len(payload.value) if isinstance(payload.value, (list, dict)) else None,
                }
                for key, payload in self.payloads.items()
            },
            'counts': dict(sorted(self.counts.items())),
            'issue_count': len(self.issues),
            'issues': [
                {
                    'source_key': issue.source_key,
                    'legacy_id': issue.legacy_id,
                    'series_id': issue.series_id,
                    'code': issue.code,
                    'detail': issue.detail,
                }
                for issue in self.issues
            ],
            'cohort_eligible': not self.issues,
        }

    def _load_payloads(self) -> None:
        for key in SOURCE_KEYS:
            try:
                payload = LegacyPlannerRepository.read(self.user, key)
            except LegacyPlannerDataError as exc:
                self._issue(key, 'source_unreadable', detail={'error': str(exc)})
                continue
            if payload is None:
                continue
            expected_type = list if key in LIST_SOURCE_KEYS else dict
            if not isinstance(payload.value, expected_type):
                self._issue(
                    key,
                    'source_type_invalid',
                    detail={'expected': expected_type.__name__, 'actual': type(payload.value).__name__},
                )
                continue
            self.payloads[key] = payload

    def _items(self, key: str) -> list[dict[str, Any]]:
        payload = self.payloads.get(key)
        if payload is None:
            return []
        result: list[dict[str, Any]] = []
        for index, item in enumerate(payload.value):
            if not isinstance(item, dict):
                self._issue(key, 'item_not_object', detail={'index': index})
                continue
            if key in {'events', 'todos', 'reminders'} and not self._legacy_id(item):
                item = dict(item)
                item['id'] = self.synthetic_legacy_id(payload.source_row_id, key, index)
                item['_planner_synthetic_id'] = True
                self.counts['synthetic_ids_generated'] += 1
            result.append(item)
        return result

    @staticmethod
    def synthetic_legacy_id(source_row_id: int, source_key: str, index: int) -> str:
        """为缺 ID 的旧列表项生成可重跑、可追溯的兼容 ID。"""
        return f'legacy-{source_key}-{source_row_id}-{index}'

    def _validate_required_ids(self, rows: Iterable[dict[str, Any]], source_key: str) -> None:
        seen: set[str] = set()
        for index, row in enumerate(rows):
            legacy_id = self._legacy_id(row)
            if not legacy_id:
                self._issue(source_key, 'missing_legacy_id', detail={'index': index})
                continue
            if legacy_id in seen:
                self._issue(source_key, 'duplicate_legacy_item_id', legacy_id=legacy_id)
            seen.add(legacy_id)

    @staticmethod
    def _recurring_groups(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            series_id = str(row.get('series_id') or '').strip()
            has_rule = bool(str(row.get('rrule') or '').strip())
            if series_id:
                groups[series_id].append(row)
            elif has_rule:
                # 历史数据缺少 series_id 时，仅以自身 immutable legacy id 作为候选。
                legacy_id = str(row.get('id') or '').strip()
                if legacy_id:
                    groups[legacy_id].append(row)
        return groups

    def _validate_event_series(self, series_id: str, rows: list[dict[str, Any]]) -> None:
        masters = [row for row in rows if row.get('is_main_event')]
        if len(masters) != 1:
            self._issue('events', 'event_series_master_ambiguous', series_id=series_id, detail={'master_count': len(masters)})
            return
        if len(self._segments('events_rrule_series', series_id)) > 1:
            self._issue('events_rrule_series', 'multi_segment_series_requires_review', series_id=series_id)
            return
        self._canonical_rule(masters[0], 'events', series_id, rows=rows)

    def _validate_reminder_series(self, series_id: str, rows: list[dict[str, Any]]) -> None:
        masters = [row for row in rows if row.get('is_main_reminder')]
        if len(masters) != 1:
            self._issue('reminders', 'reminder_series_master_ambiguous', series_id=series_id, detail={'master_count': len(masters)})
            return
        if len(self._segments('rrule_series_storage', series_id)) > 1:
            self._issue('rrule_series_storage', 'multi_segment_series_requires_review', series_id=series_id)
            return
        self._canonical_rule(masters[0], 'reminders', series_id, rows=rows)

    def _canonical_rule(
        self,
        row: dict[str, Any],
        source_key: str,
        series_id: str,
        *,
        rows: list[dict[str, Any]] | None = None,
    ) -> str | None:
        """把旧式内嵌 EXDATE 与 COUNT+UNTIL 规范为单一 RFC 规则。"""
        cache_key = (source_key, series_id)
        if cache_key in self._rule_cache:
            return self._rule_cache[cache_key][0]
        rule = str(row.get('rrule') or '').strip()
        segments = self._segments(
            'events_rrule_series' if source_key == 'events' else 'rrule_series_storage',
            series_id,
        )
        if not rule and segments:
            rule = str(segments[0].get('rrule_str') or segments[0].get('rrule') or '').strip()
        try:
            dtstart = self._parse_temporal(row.get('start') if source_key == 'events' else row.get('trigger_time'))
            if dtstart is None:
                raise PlannerTimeError('DTSTART 缺失')
            stripped_rule, inline_exdates = self._split_inline_exdates(rule, dtstart=dtstart)
            parts = self._rrule_parts(stripped_rule)
            if 'COUNT' in parts and 'UNTIL' in parts:
                canonical = self._resolve_count_until(
                    parts,
                    dtstart=dtstart,
                    rows=rows or [],
                    source_key=source_key,
                    series_id=series_id,
                    inline_exdates=inline_exdates,
                )
            else:
                canonical = canonicalize_rrule(stripped_rule, dtstart=dtstart)
            self._rule_cache[cache_key] = (canonical, inline_exdates)
            return canonical
        except (InvalidRRuleError, PlannerTimeError, TypeError, ValueError) as exc:
            self._issue(source_key, 'rrule_invalid', legacy_id=self._legacy_id(row), series_id=series_id, detail={'error': str(exc)})
            self._rule_cache[cache_key] = (None, ())
            return None

    @staticmethod
    def _rrule_parts(rule: str) -> dict[str, str]:
        raw = rule.strip()
        if raw.upper().startswith('RRULE:'):
            raw = raw[6:]
        return {
            key.strip().upper(): value.strip()
            for component in raw.strip(';').split(';')
            if '=' in component
            for key, value in [component.split('=', 1)]
        }

    def _split_inline_exdates(self, rule: str, *, dtstart: date | datetime) -> tuple[str, tuple[str, ...]]:
        """兼容旧引擎把 EXDATE 误拼在 RRULE 中的历史格式。"""
        components = []
        recurrence_ids: list[str] = []
        for component in rule.strip().rstrip(';').split(';'):
            key, separator, value = component.partition('=')
            if separator and key.strip().upper() == 'EXDATE':
                for raw_value in value.split(','):
                    recurrence_id = self._recurrence_id(raw_value.strip())
                    if not recurrence_id:
                        raise PlannerTimeError('EXDATE 时间无法解析')
                    recurrence_ids.append(recurrence_id)
                continue
            components.append(component)
        return ';'.join(components), tuple(sorted(set(recurrence_ids)))

    def _resolve_count_until(
        self,
        parts: dict[str, str],
        *,
        dtstart: date | datetime,
        rows: list[dict[str, Any]],
        source_key: str,
        series_id: str,
        inline_exdates: tuple[str, ...],
    ) -> str:
        """只在一个候选规则与已物化 occurrence 集唯一等价时消除 COUNT/UNTIL 冲突。"""
        candidates: list[str] = []
        for discarded_key in ('COUNT', 'UNTIL'):
            candidate_parts = {key: value for key, value in parts.items() if key != discarded_key}
            candidate_raw = ';'.join(f'{key}={value}' for key, value in candidate_parts.items())
            candidates.append(canonicalize_rrule(candidate_raw, dtstart=dtstart))
        observed_ids = self._observed_recurrence_ids(rows, source_key)
        matched = [
            candidate
            for candidate in candidates
            if self._candidate_matches_observed(candidate, dtstart, observed_ids, inline_exdates)
        ]
        if len(matched) != 1:
            raise InvalidRRuleError('COUNT 与 UNTIL 无法从已物化 occurrence 集唯一判定')
        return matched[0]

    def _observed_recurrence_ids(self, rows: Iterable[dict[str, Any]], source_key: str) -> set[str]:
        field = 'start' if source_key == 'events' else 'trigger_time'
        values: set[str] = set()
        for item in rows:
            recurrence_id = self._recurrence_id(item.get(field))
            if recurrence_id:
                values.add(recurrence_id)
        return values

    def _candidate_matches_observed(
        self,
        rule: str,
        dtstart: date | datetime,
        observed_ids: set[str],
        exdates: tuple[str, ...],
    ) -> bool:
        if not observed_ids:
            return False
        observed_values = [PlannerTimeCodec.parse_recurrence_id(item) for item in observed_ids]
        range_start = min(PlannerTimeCodec.recurrence_datetime(item) for item in observed_values)
        range_end = max(PlannerTimeCodec.recurrence_datetime(item) for item in observed_values) + timedelta(days=1)
        definition = RecurrenceDefinition(
            entity_type='event',
            entity_id='legacy-comparison',
            series_id='legacy-comparison',
            dtstart=dtstart,
            duration=timedelta(seconds=1),
            rrule=rule,
            exdates=frozenset(exdates),
        )
        actual_ids = {
            occurrence.ref.recurrence_id
            for occurrence in RecurrenceExpander.expand(definition, range_start=range_start, range_end=range_end)
        }
        return actual_ids == observed_ids

    def _validate_references(self) -> None:
        group_ids = {self._legacy_id(row) for row in self._items('events_groups')}
        for source_key, rows in (('events', self._event_rows), ('todos', self._todo_rows)):
            for row in rows:
                group_id = str(row.get('groupID') or '').strip()
                if group_id and group_id not in group_ids:
                    self._issue(source_key, 'group_reference_missing', legacy_id=self._legacy_id(row), detail={'group_id': group_id})
        share_group_ids = {
            str(share_group_id)
            for row in self._event_rows
            for share_group_id in (row.get('shared_to_groups') or [])
            if isinstance(share_group_id, str) and share_group_id
        }
        existing_share_group_ids = set(
            CollaborativeCalendarGroup.objects.filter(share_group_id__in=share_group_ids).values_list('share_group_id', flat=True)
        )
        missing_share_group_refs: dict[str, list[str]] = defaultdict(list)
        invalid_share_group_refs: list[str] = []
        for row in self._event_rows:
            for share_group_id in row.get('shared_to_groups') or []:
                if not isinstance(share_group_id, str) or not share_group_id:
                    invalid_share_group_refs.append(self._legacy_id(row))
                elif share_group_id not in existing_share_group_ids:
                    missing_share_group_refs[share_group_id].append(self._legacy_id(row))
        for share_group_id, legacy_ids in missing_share_group_refs.items():
            self._issue(
                'events',
                'share_group_reference_missing',
                detail={
                    'share_group_id': share_group_id,
                    'referencing_event_count': len(legacy_ids),
                    'example_legacy_id': legacy_ids[0],
                },
            )
        if invalid_share_group_refs:
            self._issue(
                'events',
                'share_group_reference_invalid',
                detail={'referencing_event_count': len(invalid_share_group_refs), 'example_legacy_id': invalid_share_group_refs[0]},
            )

    def _validate_importable_entities(self) -> None:
        """让 dry-run 与 apply 使用相同的字段可解释性门槛。"""
        for row in self._items('events_groups'):
            legacy_id = self._legacy_id(row)
            if not str(row.get('name') or '').strip():
                self._issue('events_groups', 'group_name_missing', legacy_id=legacy_id)
            self._validate_duration('events_groups', legacy_id, row.get('default_duration'))
        for row in self._event_rows:
            legacy_id = self._legacy_id(row)
            try:
                start = self._parse_temporal(row.get('start'))
                end = self._parse_temporal(row.get('end'))
            except (PlannerTimeError, TypeError, ValueError):
                self._issue('events', 'event_time_invalid', legacy_id=legacy_id, series_id=str(row.get('series_id') or ''))
                continue
            if start is None or end is None:
                self._issue('events', 'event_time_invalid', legacy_id=legacy_id, series_id=str(row.get('series_id') or ''))
            elif type(start) is not type(end):
                self._issue('events', 'event_time_type_mismatch', legacy_id=legacy_id, series_id=str(row.get('series_id') or ''))
            elif end <= start:
                self._issue('events', 'event_range_invalid', legacy_id=legacy_id, series_id=str(row.get('series_id') or ''))
            if not str(row.get('title') or '').strip():
                self._issue('events', 'event_title_missing', legacy_id=legacy_id, series_id=str(row.get('series_id') or ''))
        for row in self._todo_rows:
            legacy_id = self._legacy_id(row)
            if not str(row.get('title') or '').strip():
                self._issue('todos', 'todo_required_field_missing', legacy_id=legacy_id)
            try:
                self._parse_temporal(row.get('due_date'), allow_empty=True)
            except (PlannerTimeError, TypeError, ValueError):
                self._issue('todos', 'todo_due_date_invalid', legacy_id=legacy_id)
            try:
                int(row.get('priority_score', 0))
            except (TypeError, ValueError):
                self._issue('todos', 'priority_score_invalid', legacy_id=legacy_id)
            self._validate_duration('todos', legacy_id, row.get('estimated_duration'))
        for row in self._reminder_rows:
            legacy_id = self._legacy_id(row)
            if not str(row.get('title') or '').strip():
                self._issue('reminders', 'reminder_title_missing', legacy_id=legacy_id, series_id=str(row.get('series_id') or ''))
            try:
                trigger = self._parse_temporal(row.get('trigger_time'))
            except (PlannerTimeError, TypeError, ValueError):
                trigger = None
            if trigger is None:
                self._issue('reminders', 'reminder_trigger_invalid', legacy_id=legacy_id, series_id=str(row.get('series_id') or ''))

    def _validate_duration(self, source_key: str, legacy_id: str, value: Any) -> None:
        if value not in (None, '') and self._duration_seconds(value) is None:
            self._issue(source_key, 'duration_invalid', legacy_id=legacy_id, detail={'field_value_type': type(value).__name__})

    def _import_groups(self) -> None:
        for row in self._items('events_groups'):
            group_id = self._legacy_id(row)
            if not group_id or self._has_issue('events_groups', group_id):
                continue
            defaults = {
                'name': str(row.get('name') or ''),
                'description': str(row.get('description') or ''),
                'color': str(row.get('color') or '#3498db'),
                'group_type': str(row.get('type') or 'other'),
                'default_importance': str(row.get('default_importance') or ''),
                'default_urgency': str(row.get('default_urgency') or ''),
                'default_duration_seconds': self._duration_seconds(row.get('default_duration')),
                'working_hours': row.get('working_hours') if isinstance(row.get('working_hours'), dict) else {},
                'metadata': self._metadata(row, self._group_keys()),
            }
            if not defaults['name']:
                self._issue('events_groups', 'group_name_missing', legacy_id=group_id)
                continue
            group, created = EventGroup.objects.get_or_create(user=self.user, group_id=group_id, defaults=defaults)
            if not created and group.name != defaults['name']:
                self._issue('events_groups', 'normalized_target_conflict', legacy_id=group_id)
                continue
            self._groups[group_id] = group
            self._map('event_group', group_id, entity_id=group_id)
            self.counts['event_groups_imported'] += 1

    def _import_todos(self) -> None:
        recurring_ids = set(self._recurring_groups(self._todo_rows))
        for row in self._todo_rows:
            legacy_id = self._legacy_id(row)
            if not legacy_id or legacy_id in recurring_ids or self._has_issue('todos', legacy_id):
                continue
            todo = self._create_todo(row)
            if todo:
                self._todos[legacy_id] = todo
                self._map('todo', legacy_id, entity_id=todo.todo_id)
                self.counts['todos_imported'] += 1

    def _import_reminders(self) -> None:
        series_groups = self._recurring_groups(self._reminder_rows)
        recurring_ids = {id(row) for rows in series_groups.values() for row in rows}
        for row in self._reminder_rows:
            if id(row) in recurring_ids:
                continue
            legacy_id = self._legacy_id(row)
            if not legacy_id or self._has_issue('reminders', legacy_id):
                continue
            reminder = self._create_reminder(row)
            if reminder:
                self._reminders[legacy_id] = reminder
                self._map('reminder', legacy_id, entity_id=reminder.reminder_id)
                self._import_advance_triggers(reminder, row)
                self.counts['reminders_imported'] += 1

        for series_id, rows in series_groups.items():
            if self._has_issue_for_series(series_id):
                continue
            self._import_reminder_series(series_id, rows)

    def _import_events(self) -> None:
        series_groups = self._recurring_groups(self._event_rows)
        recurring_ids = {id(row) for rows in series_groups.values() for row in rows}
        for row in self._event_rows:
            if id(row) in recurring_ids:
                if row.get('is_detached') and row.get('original_series_id'):
                    self._issue('events', 'detached_event_requires_recurrence_slot', legacy_id=self._legacy_id(row), series_id=str(row.get('original_series_id')))
                continue
            legacy_id = self._legacy_id(row)
            if not legacy_id or self._has_issue('events', legacy_id):
                continue
            event = self._create_event(row)
            if event:
                self._events[legacy_id] = event
                self._map('event', legacy_id, entity_id=event.event_id)
                self.counts['events_imported'] += 1

        for series_id, rows in series_groups.items():
            if self._has_issue_for_series(series_id):
                continue
            self._import_event_series(series_id, rows)

    def _import_event_series(self, series_id: str, rows: list[dict[str, Any]]) -> None:
        master = next(row for row in rows if row.get('is_main_event'))
        event = self._create_event(master)
        if event is None:
            return
        canonical = self._canonical_rule(master, 'events', series_id, rows=rows)
        if not canonical:
            return
        dtstart = self._parse_temporal(master.get('start'))
        if dtstart is None:
            return
        ical_uid = str(master.get('caldav_uid') or f'legacy-event-{series_id}')[:255]
        series, created = EventRecurrenceSeries.objects.get_or_create(
            user=self.user,
            series_id=series_id,
            defaults={
                'master_event': event,
                'ical_uid': ical_uid,
                'rrule': canonical,
                'rrule_canonical': canonical,
                'dtstart_at': dtstart if isinstance(dtstart, datetime) else None,
                'dtstart_date': dtstart if isinstance(dtstart, date) and not isinstance(dtstart, datetime) else None,
                'tzid': event.tzid,
                'ical_metadata': self._metadata(master, self._event_keys()),
            },
        )
        if not created and series.master_event_id != event.id:
            self._issue('events', 'normalized_series_target_conflict', series_id=series_id)
            return
        self._events[self._legacy_id(master)] = event
        self._map('event', self._legacy_id(master), entity_id=event.event_id, series_id=series_id)
        self._import_series_exdates(
            EventRecurrenceExDate,
            series,
            'events_rrule_series',
            series_id,
            inline_exdates=self._rule_cache[('events', series_id)][1],
        )
        for row in rows:
            if row is master:
                continue
            recurrence_id = self._recurrence_id(row.get('recurrence_id') or row.get('start'))
            if not recurrence_id:
                self._issue('events', 'recurrence_instance_slot_missing', legacy_id=self._legacy_id(row), series_id=series_id)
                continue
            self._map('event', self._legacy_id(row), entity_id=event.event_id, series_id=series_id, recurrence_id=recurrence_id)
        self.counts['event_series_imported'] += 1

    def _import_reminder_series(self, series_id: str, rows: list[dict[str, Any]]) -> None:
        master = next(row for row in rows if row.get('is_main_reminder'))
        reminder = self._create_reminder(master)
        if reminder is None:
            return
        canonical = self._canonical_rule(master, 'reminders', series_id, rows=rows)
        if not canonical:
            return
        dtstart = self._parse_temporal(master.get('trigger_time'))
        if dtstart is None:
            return
        series, created = ReminderRecurrenceSeries.objects.get_or_create(
            user=self.user,
            series_id=series_id,
            defaults={
                'master_reminder': reminder,
                'ical_uid': str(master.get('caldav_uid') or '')[:255],
                'rrule': canonical,
                'rrule_canonical': canonical,
                'dtstart_at': dtstart if isinstance(dtstart, datetime) else None,
                'dtstart_date': dtstart if isinstance(dtstart, date) and not isinstance(dtstart, datetime) else None,
                'tzid': reminder.tzid,
                'ical_metadata': self._metadata(master, self._reminder_keys()),
            },
        )
        if not created and series.master_reminder_id != reminder.id:
            self._issue('reminders', 'normalized_series_target_conflict', series_id=series_id)
            return
        self._reminders[self._legacy_id(master)] = reminder
        self._map('reminder', self._legacy_id(master), entity_id=reminder.reminder_id, series_id=series_id)
        self._import_series_exdates(
            ReminderRecurrenceExDate,
            series,
            'rrule_series_storage',
            series_id,
            inline_exdates=self._rule_cache[('reminders', series_id)][1],
        )
        for row in rows:
            if row is master:
                continue
            recurrence_id = self._recurrence_id(row.get('recurrence_id') or row.get('trigger_time'))
            if not recurrence_id:
                self._issue('reminders', 'recurrence_instance_slot_missing', legacy_id=self._legacy_id(row), series_id=series_id)
                continue
            self._map('reminder', self._legacy_id(row), entity_id=reminder.reminder_id, series_id=series_id, recurrence_id=recurrence_id)
            if row.get('status', 'active') != 'active' or row.get('snooze_until') or row.get('notification_sent'):
                ReminderOccurrenceState.objects.get_or_create(
                    series=series,
                    recurrence_id=recurrence_id,
                    defaults={
                        'status': str(row.get('status') or 'active'),
                        'effective_trigger_at': self._datetime_or_none(row.get('trigger_time')),
                        'snooze_until': self._datetime_or_none(row.get('snooze_until')),
                        'notification_sent_at': self._datetime_or_none(row.get('notification_sent_at')),
                        'patch': self._metadata(row, self._reminder_keys()),
                    },
                )
        self._import_advance_triggers(reminder, master)
        self.counts['reminder_series_imported'] += 1

    def _create_event(self, row: dict[str, Any]) -> CalendarEvent | None:
        legacy_id = self._legacy_id(row)
        start = self._parse_temporal(row.get('start'))
        end = self._parse_temporal(row.get('end'))
        if not legacy_id or start is None or end is None:
            self._issue('events', 'event_time_invalid', legacy_id=legacy_id)
            return None
        is_all_day = isinstance(start, date) and not isinstance(start, datetime)
        if is_all_day != (isinstance(end, date) and not isinstance(end, datetime)):
            self._issue('events', 'event_time_type_mismatch', legacy_id=legacy_id)
            return None
        if end <= start:
            self._issue('events', 'event_range_invalid', legacy_id=legacy_id)
            return None
        group = self._groups.get(str(row.get('groupID') or '').strip())
        defaults = {
            'group': group,
            'title': str(row.get('title') or ''),
            'description': str(row.get('description') or ''),
            'location': str(row.get('location') or ''),
            'status': str(row.get('status') or 'confirmed'),
            'importance': str(row.get('importance') or ''),
            'urgency': str(row.get('urgency') or ''),
            'ddl_at': self._datetime_or_none(row.get('ddl')),
            'tzid': PlannerTimeCodec.DEFAULT_TZID,
            'is_all_day': is_all_day,
            'start_at': start if isinstance(start, datetime) else None,
            'end_at': end if isinstance(end, datetime) else None,
            'start_date': start if is_all_day else None,
            'end_date': end if is_all_day else None,
            'metadata': self._metadata(row, self._event_keys()),
        }
        if not defaults['title']:
            self._issue('events', 'event_title_missing', legacy_id=legacy_id)
            return None
        event, created = CalendarEvent.objects.get_or_create(user=self.user, event_id=legacy_id, defaults=defaults)
        if not created and event.title != defaults['title']:
            self._issue('events', 'normalized_target_conflict', legacy_id=legacy_id)
            return None
        return event

    def _create_todo(self, row: dict[str, Any]) -> Todo | None:
        legacy_id = self._legacy_id(row)
        due = self._parse_temporal(row.get('due_date'), allow_empty=True)
        priority = row.get('priority_score', 0)
        try:
            priority_score = int(priority)
        except (TypeError, ValueError):
            self._issue('todos', 'priority_score_invalid', legacy_id=legacy_id)
            return None
        if isinstance(priority, float) and not priority.is_integer():
            self._issue('todos', 'priority_score_precision_loss', legacy_id=legacy_id, detail={'legacy_value': priority})
        defaults = {
            'group': self._groups.get(str(row.get('groupID') or '').strip()),
            'title': str(row.get('title') or ''),
            'description': str(row.get('description') or ''),
            'status': str(row.get('status') or 'pending'),
            'importance': str(row.get('importance') or ''),
            'urgency': str(row.get('urgency') or ''),
            'priority_score': priority_score,
            'estimated_duration_seconds': self._duration_seconds(row.get('estimated_duration')),
            'tzid': PlannerTimeCodec.DEFAULT_TZID,
            'due_at': due if isinstance(due, datetime) else None,
            'due_date': due if isinstance(due, date) and not isinstance(due, datetime) else None,
            'metadata': self._metadata(row, self._todo_keys()),
        }
        if not legacy_id or not defaults['title']:
            self._issue('todos', 'todo_required_field_missing', legacy_id=legacy_id)
            return None
        todo, created = Todo.objects.get_or_create(user=self.user, todo_id=legacy_id, defaults=defaults)
        if not created and todo.title != defaults['title']:
            self._issue('todos', 'normalized_target_conflict', legacy_id=legacy_id)
            return None
        return todo

    def _create_reminder(self, row: dict[str, Any]) -> Reminder | None:
        legacy_id = self._legacy_id(row)
        trigger = self._parse_temporal(row.get('trigger_time'))
        if not legacy_id or trigger is None:
            self._issue('reminders', 'reminder_trigger_invalid', legacy_id=legacy_id)
            return None
        defaults = {
            'title': str(row.get('title') or ''),
            'content': str(row.get('content') or ''),
            'priority': str(row.get('priority') or 'normal'),
            'status': str(row.get('status') or 'active'),
            'tzid': PlannerTimeCodec.DEFAULT_TZID,
            'trigger_at': trigger if isinstance(trigger, datetime) else None,
            'trigger_date': trigger if isinstance(trigger, date) and not isinstance(trigger, datetime) else None,
            'snooze_until': self._datetime_or_none(row.get('snooze_until')),
            'notification_sent_at': self._datetime_or_none(row.get('notification_sent_at')),
            'notification_payload': {'legacy_notification_sent': bool(row.get('notification_sent'))},
            'metadata': self._metadata(row, self._reminder_keys()),
        }
        if not defaults['title']:
            self._issue('reminders', 'reminder_title_missing', legacy_id=legacy_id)
            return None
        reminder, created = Reminder.objects.get_or_create(user=self.user, reminder_id=legacy_id, defaults=defaults)
        if not created and reminder.title != defaults['title']:
            self._issue('reminders', 'normalized_target_conflict', legacy_id=legacy_id)
            return None
        return reminder

    def _import_relationships(self) -> None:
        for row in self._event_rows:
            event = self._events.get(self._legacy_id(row))
            if not event:
                continue
            self._import_tags(EventTag, event, row.get('tags'))
            self._import_event_links(event, row)
        for row in self._todo_rows:
            todo = self._todos.get(self._legacy_id(row))
            if not todo:
                continue
            self._import_tags(TodoTag, todo, row.get('tags'))
            self._import_todo_links(todo, row)
        for row in self._reminder_rows:
            reminder = self._reminders.get(self._legacy_id(row))
            if not reminder:
                continue
            linked_event = self._events.get(str(row.get('linked_event_id') or ''))
            linked_todo = self._todos.get(str(row.get('linked_todo_id') or ''))
            if linked_event:
                EventReminderLink.objects.get_or_create(event=linked_event, reminder=reminder)
            if linked_todo:
                TodoReminderLink.objects.get_or_create(todo=linked_todo, reminder=reminder)

    @staticmethod
    def _import_tags(model, parent, tags: Any) -> None:
        if not isinstance(tags, list):
            return
        for tag in tags:
            if not isinstance(tag, str) or not tag.strip():
                continue
            normalized = tag.strip().casefold()
            model.objects.get_or_create(**{model._meta.get_field('event' if model is EventTag else 'todo').name: parent, 'normalized_tag': normalized}, defaults={'tag': tag.strip()})

    def _import_event_links(self, event: CalendarEvent, row: dict[str, Any]) -> None:
        for reminder_id in row.get('linked_reminders') or []:
            reminder = self._reminders.get(str(reminder_id))
            if reminder:
                EventReminderLink.objects.get_or_create(event=event, reminder=reminder)
        for share_group_id in row.get('shared_to_groups') or []:
            share_group = CollaborativeCalendarGroup.objects.filter(share_group_id=str(share_group_id)).first()
            if share_group is None:
                if not any(
                    issue.code == 'share_group_reference_missing'
                    and issue.detail.get('share_group_id') == str(share_group_id)
                    for issue in self.issues
                ):
                    self._issue(
                        'events',
                        'share_group_reference_missing',
                        detail={'share_group_id': str(share_group_id), 'referencing_event_count': 1, 'example_legacy_id': self._legacy_id(row)},
                    )
                continue
            EventShareGroup.objects.get_or_create(event=event, share_group=share_group)

    def _import_todo_links(self, todo: Todo, row: dict[str, Any]) -> None:
        for reminder_id in row.get('linked_reminders') or []:
            reminder = self._reminders.get(str(reminder_id))
            if reminder:
                TodoReminderLink.objects.get_or_create(todo=todo, reminder=reminder)
        for dependency_id in row.get('dependencies') or []:
            dependency = self._todos.get(str(dependency_id))
            if dependency and dependency != todo:
                TodoDependency.objects.get_or_create(todo=todo, depends_on=dependency)

    @staticmethod
    def _import_advance_triggers(reminder: Reminder, row: dict[str, Any]) -> None:
        for trigger in row.get('advance_triggers') or []:
            if not isinstance(trigger, dict):
                continue
            seconds = PlannerLegacyMigration._duration_seconds(trigger.get('time_before'))
            if seconds is None:
                continue
            ReminderAdvanceTrigger.objects.get_or_create(
                reminder=reminder,
                time_before_seconds=seconds,
                defaults={
                    'priority': str(trigger.get('priority') or ''),
                    'message': str(trigger.get('message') or ''),
                },
            )

    def _import_series_exdates(
        self,
        model,
        series,
        source_key: str,
        series_id: str,
        *,
        inline_exdates: tuple[str, ...] = (),
    ) -> None:
        for recurrence_id in inline_exdates:
            model.objects.get_or_create(series=series, recurrence_id=recurrence_id, defaults={'source': 'legacy_inline_rrule'})
        for segment in self._segments(source_key, series_id):
            for raw_exdate in segment.get('exdates') or []:
                recurrence_id = self._recurrence_id(raw_exdate)
                if not recurrence_id:
                    self._issue(source_key, 'exdate_invalid', series_id=series_id)
                    continue
                model.objects.get_or_create(series=series, recurrence_id=recurrence_id, defaults={'source': 'legacy'})

    def _segments(self, source_key: str, series_id: str) -> list[dict[str, Any]]:
        payload = self.payloads.get(source_key)
        if payload is None:
            return []
        segments = payload.value.get('segments', [])
        if not isinstance(segments, list):
            self._issue(source_key, 'segments_not_list', series_id=series_id)
            return []
        return [item for item in segments if isinstance(item, dict) and str(item.get('uid') or '') == series_id]

    def _persist_states_and_issues(self, *, quarantine_all: bool = False) -> None:
        issues_by_key: dict[str, list[MigrationIssueSpec]] = defaultdict(list)
        for issue in self.issues:
            issues_by_key[issue.source_key].append(issue)
        for key, payload in self.payloads.items():
            state, _ = PlannerMigrationState.objects.get_or_create(user=self.user, source_key=key)
            key_issues = issues_by_key.get(key, [])
            state.source_row_id = payload.source_row_id
            state.source_checksum = payload.checksum
            state.imported_count = 0 if quarantine_all else self._state_imported_count(key)
            state.issue_count = len(key_issues)
            state.last_error = key_issues[0].code if key_issues else ''
            state.status = (
                PlannerMigrationState.STATUS_QUARANTINED
                if quarantine_all or key_issues
                else PlannerMigrationState.STATUS_IMPORTED
            )
            state.save(update_fields=['source_row_id', 'source_checksum', 'imported_count', 'issue_count', 'last_error', 'status', 'updated_at'])
            for issue in key_issues:
                PlannerMigrationIssue.objects.get_or_create(
                    user=self.user,
                    source_row_id=payload.source_row_id,
                    source_key=issue.source_key,
                    legacy_id=issue.legacy_id,
                    series_id=issue.series_id,
                    code=issue.code,
                    is_resolved=False,
                    defaults={'state': state, 'detail': issue.detail},
                )

    def _state_imported_count(self, key: str) -> int:
        mapping = {
            'events_groups': 'event_groups_imported',
            'todos': 'todos_imported',
            'reminders': 'reminders_imported',
            'events': 'events_imported',
            'events_rrule_series': 'event_series_imported',
            'rrule_series_storage': 'reminder_series_imported',
        }
        return self.counts[mapping[key]]

    def _is_already_imported(self) -> bool:
        if not self.payloads:
            return False
        for key, payload in self.payloads.items():
            state = PlannerMigrationState.objects.filter(user=self.user, source_key=key).first()
            if state is None or state.source_checksum != payload.checksum:
                return False
            if state.status not in {
                PlannerMigrationState.STATUS_IMPORTED,
                PlannerMigrationState.STATUS_VERIFIED,
                PlannerMigrationState.STATUS_QUARANTINED,
            }:
                return False
        return True

    def _map(self, entity_type: str, legacy_id: str, *, entity_id: str, series_id: str = '', recurrence_id: str = '') -> None:
        if not legacy_id:
            return
        PlannerLegacyIdMap.objects.get_or_create(
            user=self.user,
            entity_type=entity_type,
            legacy_id=legacy_id,
            defaults={
                'entity_id': entity_id,
                'series_id': series_id,
                'recurrence_id': recurrence_id,
                'source_row_id': self.payloads.get('events').source_row_id if entity_type == 'event' and self.payloads.get('events') else None,
            },
        )

    def _has_issue(self, source_key: str, legacy_id: str) -> bool:
        return any(issue.source_key == source_key and issue.legacy_id == legacy_id for issue in self.issues)

    def _has_issue_for_series(self, series_id: str) -> bool:
        return any(issue.series_id == series_id for issue in self.issues)

    def _issue(self, source_key: str, code: str, *, legacy_id: str = '', series_id: str = '', detail: dict[str, Any] | None = None) -> None:
        spec = MigrationIssueSpec(source_key, code, legacy_id, series_id, detail or {})
        if spec not in self.issues:
            self.issues.append(spec)

    @staticmethod
    def _legacy_id(row: dict[str, Any]) -> str:
        return str(row.get('id') or '').strip()

    @staticmethod
    def _parse_temporal(value: Any, *, allow_empty: bool = False) -> date | datetime | None:
        if value in (None, ''):
            return None if allow_empty else None
        parsed = PlannerTimeCodec.parse_value(value)
        if isinstance(parsed, datetime):
            return PlannerTimeCodec.to_utc(parsed)
        return parsed

    @classmethod
    def _datetime_or_none(cls, value: Any) -> datetime | None:
        parsed = cls._parse_temporal(value, allow_empty=True)
        if parsed is None:
            return None
        if isinstance(parsed, datetime):
            return parsed
        return PlannerTimeCodec.to_utc(datetime.combine(parsed, time.min))

    @classmethod
    def _recurrence_id(cls, value: Any) -> str:
        try:
            parsed = cls._parse_temporal(value)
        except (PlannerTimeError, TypeError, ValueError):
            return ''
        return PlannerTimeCodec.format_recurrence_id(parsed) if parsed is not None else ''

    @staticmethod
    def _duration_seconds(value: Any) -> int | None:
        if value in (None, ''):
            return None
        if isinstance(value, int) and value >= 0:
            return value
        if not isinstance(value, str):
            return None
        match = _DURATION_RE.fullmatch(value.strip().lower())
        if not match:
            return None
        hours, minutes = match.groups()
        if not hours and not minutes:
            return None
        return int(hours or 0) * 3600 + int(minutes or 0) * 60

    @staticmethod
    def _metadata(row: dict[str, Any], known_fields: set[str]) -> dict[str, Any]:
        unknown = {key: value for key, value in row.items() if key not in known_fields}
        return {'legacy_unknown_fields': unknown} if unknown else {}

    @staticmethod
    def _group_keys() -> set[str]:
        return {'id', 'name', 'description', 'color', 'type', 'default_duration', 'default_importance', 'default_urgency', 'working_hours'}

    @staticmethod
    def _event_keys() -> set[str]:
        return {
            'id', 'title', 'start', 'end', 'description', 'importance', 'urgency', 'groupID', 'ddl', 'rrule',
            'rrule_generated', 'rrule_parent_id', 'series_id', 'is_recurring', 'is_main_event', 'is_detached',
            'recurrence_id', 'parent_event_id', 'original_series_id', 'linked_reminders', 'tags', 'location',
            'status', 'shared_to_groups', 'caldav_uid', 'last_modified',
        }

    @staticmethod
    def _todo_keys() -> set[str]:
        return {
            'id', 'title', 'description', 'importance', 'urgency', 'created_at', 'due_date', 'estimated_duration',
            'groupID', 'last_modified', 'tags', 'status', 'dependencies', 'linked_reminders', 'priority_score',
        }

    @staticmethod
    def _reminder_keys() -> set[str]:
        return {
            'id', 'title', 'content', 'trigger_time', 'priority', 'rrule', 'status', 'snooze_until', 'created_at',
            'last_modified', 'advance_triggers', 'linked_event_id', 'linked_todo_id', 'notification_sent',
            'notification_sent_at', 'series_id', 'is_recurring', 'is_main_reminder', 'is_detached', 'recurrence_id',
            'caldav_uid',
        }
