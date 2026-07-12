"""Unified Planner tools 的 normalized application adapter。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from agent_service.tools.cache_manager import CacheManager
from agent_service.tools.repeat_parser import RepeatParser
from agent_service.tools.time_parser import TimeRangeParser
from core.planner.application import PlannerApplicationService
from core.planner.context import PlannerExecutionContext
from core.planner.recurrence.codec import PlannerTimeCodec
from core.planner.rollout import PlannerRolloutPolicy


SOURCE_ENTRYPOINT = {
    'websocket_agent': PlannerRolloutPolicy.ENTRYPOINT_AGENT,
    'quick_action': PlannerRolloutPolicy.ENTRYPOINT_QUICK_ACTION,
    'mcp_stdio': PlannerRolloutPolicy.ENTRYPOINT_MCP,
    'mcp_http': PlannerRolloutPolicy.ENTRYPOINT_MCP,
}


def _configurable(config) -> dict[str, Any]:
    if isinstance(config, dict):
        return config.get('configurable') or {}
    return getattr(config, 'configurable', {}) or {}


def build_context(config) -> PlannerExecutionContext:
    values = _configurable(config)
    user = values.get('user')
    source = values.get('planner_source') or 'websocket_agent'
    session_id = values.get('session_id') or values.get('thread_id') or ''
    tool_call_id = values.get('tool_call_id') or ''
    rollback_window_id = values.get('rollback_window_id') or ''
    message_index = values.get('message_index')
    reversible = bool(
        source == 'websocket_agent' and session_id and tool_call_id
        and rollback_window_id and message_index is not None
    )
    return PlannerExecutionContext(
        user=user, source=source, entrypoint=SOURCE_ENTRYPOINT[source],
        session_id=session_id, tool_call_id=tool_call_id,
        request_id=values.get('request_id') or '', message_index=message_index,
        rollback_window_id=rollback_window_id, reversible=reversible,
    )


def should_use_normalized(config) -> bool:
    context = build_context(config)
    return PlannerRolloutPolicy.decide(context.user, context.entrypoint).effective_mode in {'shadow', 'normalized'}


def _range(value: str | None):
    parsed = TimeRangeParser.parse(value) if value else None
    if parsed:
        start, end = parsed
        zone = PlannerTimeCodec.get_timezone()
        if timezone.is_naive(start): start = timezone.make_aware(start, zone)
        if timezone.is_naive(end): end = timezone.make_aware(end, zone)
        return PlannerTimeCodec.to_utc(start), PlannerTimeCodec.to_utc(end)
    now = timezone.now()
    return now - timedelta(days=30), now + timedelta(days=90)


def _resolve_group(context, identifier: str | None) -> str | None:
    if not identifier:
        return None
    groups = PlannerApplicationService.list_groups(context)['groups']
    if identifier.lower().startswith('#g') and identifier[2:].isdigit():
        index = int(identifier[2:]) - 1
        return groups[index]['group_id'] if 0 <= index < len(groups) else None
    for group in groups:
        if identifier in {group['group_id'], group['name']}:
            return group['group_id']
    return None


def _resolve_share_groups(context, identifiers: list[str] | None) -> list[str] | None:
    if identifiers is None:
        return None
    groups = PlannerApplicationService.list_share_groups(context)['share_groups']
    resolved = []
    for identifier in identifiers:
        if identifier.lower().startswith('#s') and identifier[2:].isdigit():
            index = int(identifier[2:]) - 1
            if 0 <= index < len(groups): resolved.append(groups[index]['share_group_id'])
            continue
        match = next((item for item in groups if identifier in {item['share_group_id'], item['name']}), None)
        if match: resolved.append(match['share_group_id'])
    return resolved


def _cache_item(item: dict[str, Any]) -> dict[str, Any]:
    item_type = item.get('entity_type')
    if item_type == 'event' or (item_type == 'reminder' and item.get('occurrence_ref')):
        ref = item['occurrence_ref']
        return {
            **item, 'entity_id': ref['entity_id'], 'series_id': ref.get('series_id'),
            'recurrence_id': ref.get('recurrence_id'), 'source_version': ref['source_version'],
            'trigger_time': item.get('start'), 'due_date': item.get('due'),
        }
    entity_id = item.get(f'{item_type}_id')
    return {
        **item, 'id': f'{item_type}:{entity_id}', 'entity_id': entity_id,
        'source_version': item.get('version'), 'due_date': item.get('due'),
        'trigger_time': item.get('trigger'),
    }


def _display(item: dict[str, Any], index: str) -> str:
    item_type = item.get('entity_type')
    if item_type == 'event':
        return f"{index} [日程] {item.get('start')} ~ {item.get('end')} {item.get('title')}"
    if item_type == 'todo':
        return f"{index} [待办] {item.get('title')}（状态: {item.get('status')}，截止: {item.get('due') or '无'}）"
    return f"{index} [提醒] {item.get('title')}（触发: {item.get('start') or item.get('trigger')}）"


def search_normalized(config, *, item_type='all', keyword=None, time_range=None, status=None, event_group=None, share_groups=None, share_groups_only=False, limit=20) -> str:
    context = build_context(config)
    start, end = _range(time_range)
    types = {'event', 'todo', 'reminder'} if item_type == 'all' else {item_type}
    payload = PlannerApplicationService.search_items(
        context, query=keyword or '', requested_types=types,
        range_start=start, range_end=end, page=1, page_size=min(max(int(limit), 1), 100),
    )
    own = [] if share_groups_only else payload['results']
    group_id = _resolve_group(context, event_group)
    if event_group:
        own = [item for item in own if item.get('entity_type') != 'event' or item.get('group_id') == group_id]
    if status and status != 'all':
        own = [item for item in own if item.get('status') == status]

    selected_share_ids = _resolve_share_groups(context, share_groups)
    shared = []
    if share_groups != [] and ('event' in types):
        available = PlannerApplicationService.list_share_groups(context)['share_groups']
        for group in available:
            if selected_share_ids is not None and group['share_group_id'] not in selected_share_ids:
                continue
            group_payload = PlannerApplicationService.list_shared_occurrences(
                context, share_group_id=group['share_group_id'], range_start=start, range_end=end
            )
            for item in group_payload['occurrences']:
                if keyword and keyword.casefold() not in f"{item.get('title','')} {item.get('description','')}".casefold():
                    continue
                if item.get('read_only'):
                    item['_share_group_name'] = group['name']
                    shared.append(item)

    cached = [_cache_item(item) for item in own[:limit]]
    types_for_cache = [item['entity_type'] for item in cached]
    mapping = {}
    if context.session_id and cached:
        success, stats = CacheManager.save_mixed_search_cache(context.session_id, cached, types_for_cache, user=context.user)
        if success: mapping = stats.get('item_to_index', {})
    lines = [_display(item, mapping.get(item['id'], f'#{index + 1}')) for index, item in enumerate(cached)]
    for item in shared[:max(0, limit - len(lines))]:
        lines.append(f"- [共享只读/{item.get('_share_group_name')}] {item.get('start')} {item.get('title')}")
    if not lines:
        return '未找到符合条件的项目'
    default_note = '' if time_range else '\n查询窗口：过去30天至未来90天。'
    return '\n'.join(lines) + f"\n\n共显示 {len(lines)} 项。可编辑项目请使用 #序号引用。" + default_note


def _resolve_ref(context, identifier: str, preferred_type: str | None = None):
    cached = CacheManager.get_normalized_ref(context.session_id, context.user, identifier, preferred_type) if context.session_id else None
    if cached:
        return cached
    return PlannerApplicationService.resolve_item(context, identifier, preferred_type)


def create_normalized(config, *, item_type, title, description=None, start=None, end=None, event_group=None, importance=None, urgency=None, shared_to_groups=None, ddl=None, due_date=None, priority=None, trigger_time=None, content=None, repeat=None) -> str:
    context = build_context(config)
    rrule = RepeatParser.parse(repeat) if repeat else None
    if item_type == 'event':
        group_id = _resolve_group(context, event_group)
        if event_group and not group_id: return f"❌ 未找到日程组: {event_group}"
        shares = _resolve_share_groups(context, shared_to_groups)
        if shared_to_groups and not shares: return f"❌ 未找到分享组: {shared_to_groups}"
        payload = {
            'title': title, 'description': description or '', 'start': start, 'end': end,
            'importance': importance or '', 'urgency': urgency or '', 'group_id': group_id,
            'ddl_at': ddl or None, 'share_group_ids': shares or [],
        }
        if rrule: payload['recurrence'] = {'rrule': rrule}
        result = PlannerApplicationService.create_event(
            context, payload, range_start=PlannerTimeCodec.to_utc(PlannerTimeCodec.parse_value(start)),
            range_end=PlannerTimeCodec.to_utc(PlannerTimeCodec.parse_value(end)),
        )['event']
        return f"✅ 日程创建成功！\n标题: {result['title']}\n时间: {result['start']} ~ {result['end']}\nID: {result['event_id']}"
    if item_type == 'todo':
        result = PlannerApplicationService.create_todo(context, {
            'title': title, 'description': description or '', 'due': due_date or None,
            'importance': priority or '',
        })['todo']
        return f"✅ 待办创建成功！\n标题: {result['title']}\nID: {result['todo_id']}"
    if item_type == 'reminder':
        payload = {
            'title': title, 'content': content or description or '',
            'trigger': trigger_time, 'priority': priority or 'normal',
        }
        if rrule: payload['recurrence'] = {'rrule': rrule}
        result = PlannerApplicationService.create_reminder(context, payload)['reminder']
        return f"✅ 提醒创建成功！\n标题: {result['title']}\nID: {result['reminder_id']}"
    return f"❌ 不支持的类型: {item_type}"


def update_normalized(config, *, identifier, item_type=None, edit_scope='single', from_time=None, title=None, description=None, start=None, end=None, event_group=None, importance=None, urgency=None, shared_to_groups=None, ddl=None, due_date=None, priority=None, status=None, trigger_time=None, content=None, repeat=None, clear_repeat=False) -> str:
    context = build_context(config)
    info = _resolve_ref(context, identifier, item_type)
    if not info: return f"❌ 无法找到项目 '{identifier}'。请先搜索并使用 #序号。"
    resolved_type, entity_id = info['type'], info['entity_id']
    expected = int(info.get('source_version') or 0)
    if resolved_type == 'event':
        scope = 'this_and_future' if edit_scope in {'future', 'from_time'} else edit_scope
        ref = info.get('occurrence_ref')
        if info.get('series_id') and scope in {'single', 'this_and_future'} and not (ref and ref.get('recurrence_id')):
            return '❌ 重复日程的 single/future 操作必须先搜索到具体 occurrence，并使用对应 #序号。'
        payload = {key: value for key, value in {
            'title': title, 'description': description, 'start': start, 'end': end,
            'importance': importance, 'urgency': urgency, 'ddl_at': ddl,
        }.items() if value is not None}
        if event_group is not None:
            payload['group_id'] = _resolve_group(context, event_group)
        if shared_to_groups is not None:
            payload['share_group_ids'] = _resolve_share_groups(context, shared_to_groups) or []
        if repeat is not None: payload['recurrence'] = {'rrule': RepeatParser.parse(repeat)}
        elif clear_repeat: payload['recurrence'] = None
        if scope == 'this_and_future': payload['override_policy'] = 'map_by_ordinal'
        result = PlannerApplicationService.patch_event(
            context, entity_id, payload, scope=scope, occurrence_ref=ref, expected_version=expected
        )
        CacheManager.invalidate_item(context.session_id, entity_id)
        return f"✅ 日程更新成功！\n范围: {edit_scope}\nID: {result['event_id']}\n版本: {result['source_version']}"
    if resolved_type == 'todo':
        payload = {key: value for key, value in {
            'title': title, 'description': description, 'due': due_date,
            'importance': priority, 'status': status,
        }.items() if value is not None}
        result = PlannerApplicationService.patch_todo(context, entity_id, payload, expected)['todo']
        CacheManager.invalidate_item(context.session_id, entity_id)
        return f"✅ 待办更新成功！\n标题: {result['title']}\n状态: {result['status']}\nID: {entity_id}"
    if info.get('series_id') and edit_scope != 'all':
        return '❌ 当前 normalized 提醒仅支持修改整个重复系列；单次状态请使用提醒操作。'
    payload = {key: value for key, value in {
        'title': title, 'content': content if content is not None else description,
        'trigger': trigger_time, 'priority': priority, 'status': status,
    }.items() if value is not None}
    result = PlannerApplicationService.patch_reminder(context, entity_id, payload, expected)['reminder']
    CacheManager.invalidate_item(context.session_id, entity_id)
    return f"✅ 提醒更新成功！\n标题: {result['title']}\nID: {entity_id}"


def delete_normalized(config, *, identifier, item_type=None, delete_scope='single') -> str:
    context = build_context(config)
    info = _resolve_ref(context, identifier, item_type)
    if not info: return f"❌ 无法找到项目 '{identifier}'。请先搜索并使用 #序号。"
    entity_id, expected = info['entity_id'], int(info.get('source_version') or 0)
    if info['type'] == 'event':
        scope = 'this_and_future' if delete_scope == 'future' else delete_scope
        ref = info.get('occurrence_ref')
        if info.get('series_id') and scope in {'single', 'this_and_future'} and not (ref and ref.get('recurrence_id')):
            return '❌ 重复日程的 single/future 删除必须使用具体 occurrence 的 #序号。'
        PlannerApplicationService.delete_event(
            context, entity_id, scope=scope, occurrence_ref=ref, expected_version=expected
        )
    elif info['type'] == 'todo':
        PlannerApplicationService.delete_todo(context, entity_id, expected)
    else:
        if info.get('series_id') and delete_scope != 'all':
            if delete_scope == 'single' and info.get('occurrence_ref'):
                PlannerApplicationService.act_on_reminder_occurrence(context, {
                    'occurrence_ref': info['occurrence_ref'], 'expected_version': expected, 'action': 'dismiss',
                })
            else:
                return '❌ 当前 normalized 重复提醒不支持 future 删除。'
        else:
            PlannerApplicationService.delete_reminder(context, entity_id, expected)
    CacheManager.invalidate_item(context.session_id, entity_id)
    return f"✅ {info['type']} 删除成功！\n范围: {delete_scope}\nID: {entity_id}"


def groups_normalized(config) -> str:
    groups = PlannerApplicationService.list_groups(build_context(config))['groups']
    return '\n'.join(f"#g{index + 1} {item['name']} - {item['description']}" for index, item in enumerate(groups)) or '暂无事件组。'


def share_groups_normalized(config) -> str:
    groups = PlannerApplicationService.list_share_groups(build_context(config))['share_groups']
    return '\n'.join(f"#s{index + 1} {item['name']} - {item['description']}" for index, item in enumerate(groups)) or '暂无分享组。'


def complete_todo_normalized(config, identifier: str) -> str:
    return update_normalized(config, identifier=identifier, item_type='todo', status='completed')


def conflicts_normalized(config, time_range='this_week', **_kwargs) -> str:
    context = build_context(config)
    start, end = _range(time_range)
    result = PlannerApplicationService.list_conflicts(context, range_start=start, range_end=end)
    if not result['conflicts']: return '✅ 指定时间范围内没有日程冲突。'
    lines = [f"发现 {result['count']} 组冲突："]
    for item in result['conflicts']:
        titles = ' / '.join(entry['title'] for entry in item['items'])
        lines.append(f"- {item['overlap']['start']} ~ {item['overlap']['end']}: {titles}")
    return '\n'.join(lines)

