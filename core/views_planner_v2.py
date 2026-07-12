"""Planner v2 normalized event API。"""

from datetime import date, datetime, time, timedelta

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.models import CollaborativeCalendarGroup, EventRecurrenceSeries, EventShareGroup, GroupMembership
from core.planner.commands import PlannerCommandError, PlannerCommandService, PlannerCommandVersionConflict
from core.planner.entities import (
    PlannerEntityCommandService,
    PlannerEntityQueryService,
    serialize_group,
    serialize_reminder,
    serialize_todo,
)
from core.planner.presentation import serialize_event_definition, serialize_occurrence
from core.planner.recurrence.codec import PlannerTimeCodec, PlannerTimeError
from core.planner.repository import PlannerNotFoundError, PlannerRepository
from core.planner.rollout import PlannerRolloutPolicy
from logger import logger


def _parse_range(request):
    """解析 v2 查询窗口；只接受明确边界，避免全表/无限规则扫描。"""
    from_value = request.query_params.get('from')
    to_value = request.query_params.get('to')
    if not from_value or not to_value:
        raise PlannerTimeError('查询参数 from 与 to 均为必填')
    range_start = _to_utc_datetime(from_value)
    range_end = _to_utc_datetime(to_value)
    if range_start >= range_end:
        raise PlannerTimeError('from 必须早于 to')
    return range_start, range_end


def _to_utc_datetime(value: str) -> datetime:
    parsed = PlannerTimeCodec.parse_value(value)
    if isinstance(parsed, date) and not isinstance(parsed, datetime):
        parsed = datetime.combine(parsed, time.min, tzinfo=PlannerTimeCodec.get_timezone())
    return PlannerTimeCodec.to_utc(parsed)


def _require_normalized_access(user, *, write: bool = False):
    """v2 必须同时满足全局模式、用户 cohort、入口和迁移校验。"""
    decision = (
        PlannerRolloutPolicy.can_write_normalized(user, PlannerRolloutPolicy.ENTRYPOINT_API_V2)
        if write
        else PlannerRolloutPolicy.can_read_normalized(user, PlannerRolloutPolicy.ENTRYPOINT_API_V2)
    )
    allowed_modes = {'normalized'} if write else {'shadow', 'normalized'}
    if decision.effective_mode not in allowed_modes:
        code = 'planner_normalized_write_not_enabled' if write else 'planner_normalized_read_not_enabled'
        return Response(
            {
                'error': '当前用户或入口尚未获准访问 normalized Planner。',
                'code': code,
                'reason': decision.reason,
                'effective_mode': decision.effective_mode,
            },
            status=status.HTTP_409_CONFLICT,
        )
    return None


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def planner_bootstrap_v2(request):
    """前端一次读取本会话固定的 Planner cohort 模式；不访问业务数据。"""
    entrypoints = [
        PlannerRolloutPolicy.ENTRYPOINT_API_V2,
        PlannerRolloutPolicy.ENTRYPOINT_WEB_CALENDAR,
        PlannerRolloutPolicy.ENTRYPOINT_WEB_TODO,
        PlannerRolloutPolicy.ENTRYPOINT_WEB_REMINDER,
        PlannerRolloutPolicy.ENTRYPOINT_WEB_SEARCH,
        PlannerRolloutPolicy.ENTRYPOINT_WEB_SHARE,
        PlannerRolloutPolicy.ENTRYPOINT_COURSE_IMPORT,
    ]
    decisions = {name: PlannerRolloutPolicy.decide(request.user, name) for name in entrypoints}
    return Response(
        {
            'entrypoints': {
                name: {
                    'mode': decision.effective_mode,
                    'reason': decision.reason,
                    'can_read_normalized': decision.effective_mode in {'shadow', 'normalized'},
                    'can_write_normalized': decision.effective_mode == 'normalized',
                }
                for name, decision in decisions.items()
            }
        }
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_event_definitions_v2(request):
    """返回当前用户的 event definitions；正常 recurrence instance 不落行。"""
    not_ready = _require_normalized_access(request.user)
    if not_ready:
        return not_ready
    try:
        range_start, range_end = _parse_range(request)
        definitions = PlannerRepository.list_event_definitions(
            request.user,
            range_start=range_start,
            range_end=range_end,
        )
    except (PlannerTimeError, ValueError) as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(
        {
            'range': {'from': range_start.isoformat(), 'to': range_end.isoformat()},
            'definitions': [serialize_event_definition(item) for item in definitions],
            'count': len(definitions),
        }
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_event_occurrences_v2(request):
    """按半开窗口纯展开 occurrence；该查询不写入任何模型。"""
    not_ready = _require_normalized_access(request.user)
    if not_ready:
        return not_ready
    try:
        range_start, range_end = _parse_range(request)
        occurrences = PlannerRepository.list_event_occurrences(
            request.user,
            range_start=range_start,
            range_end=range_end,
        )
    except (PlannerTimeError, ValueError) as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(
        {
            'range': {'from': range_start.isoformat(), 'to': range_end.isoformat()},
            'occurrences': [serialize_occurrence(item) for item in occurrences],
            'count': len(occurrences),
        }
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_event_conflicts_v2(request):
    """复用 occurrence query 检测半开区间重叠；不物化虚拟实例。"""
    not_ready = _require_normalized_access(request.user)
    if not_ready:
        return not_ready
    try:
        range_start, range_end = _parse_range(request)
        occurrences = PlannerRepository.list_event_occurrences(
            request.user, range_start=range_start, range_end=range_end
        )
        normalized = []
        for occurrence in occurrences:
            start_value = occurrence.start
            end_value = occurrence.end
            if isinstance(start_value, date) and not isinstance(start_value, datetime):
                start_value = datetime.combine(start_value, time.min, tzinfo=PlannerTimeCodec.get_timezone())
                end_value = datetime.combine(end_value, time.min, tzinfo=PlannerTimeCodec.get_timezone())
            normalized.append(
                (PlannerTimeCodec.to_utc(start_value), PlannerTimeCodec.to_utc(end_value), occurrence)
            )
        normalized.sort(key=lambda item: (item[0], item[1], item[2].ref.entity_id))
        active = []
        conflicts = []
        for start_value, end_value, occurrence in normalized:
            active = [item for item in active if item[1] > start_value]
            for other_start, other_end, other in active:
                conflicts.append(
                    {
                        'overlap': {
                            'start': max(start_value, other_start).isoformat(),
                            'end': min(end_value, other_end).isoformat(),
                        },
                        'items': [serialize_occurrence(other), serialize_occurrence(occurrence)],
                    }
                )
            active.append((start_value, end_value, occurrence))
        return Response({'conflicts': conflicts, 'count': len(conflicts)})
    except (PlannerTimeError, ValueError) as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


def _command_error_response(exc: Exception) -> Response:
    """保持 v2 command 的错误码稳定，避免客户端解析自然语言。"""
    if isinstance(exc, PlannerNotFoundError):
        return Response({'error': str(exc), 'code': 'event_not_found'}, status=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, PlannerCommandVersionConflict):
        return Response({'error': str(exc), 'code': exc.code}, status=status.HTTP_409_CONFLICT)
    if isinstance(exc, PlannerCommandError):
        logger.warning(f'Planner v2 command rejected: code={exc.code}, error={exc}')
        conflict_codes = {'recurrence_split_requires_override_policy'}
        response_status = status.HTTP_409_CONFLICT if exc.code in conflict_codes else status.HTTP_422_UNPROCESSABLE_ENTITY
        return Response({'error': str(exc), 'code': exc.code}, status=response_status)
    if isinstance(exc, (PlannerTimeError, ValueError)):
        return Response({'error': str(exc), 'code': 'invalid_command'}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    raise exc


def _expected_version(request) -> int:
    """body 优先、If-Match 兼容；写命令禁止无版本覆盖。"""
    raw = request.data.get('expected_version')
    if raw is None:
        raw = request.headers.get('If-Match')
    if raw is None:
        raise PlannerCommandError('expected_version 为必填', code='expected_version_required')
    if isinstance(raw, str):
        raw = raw.strip().removeprefix('W/').strip('"')
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise PlannerCommandError('expected_version 必须是整数', code='expected_version_required') from exc
    if value < 1:
        raise PlannerCommandError('expected_version 必须大于 0', code='expected_version_required')
    return value


def _command_payload(request):
    """去掉 command 元数据，剩余字段直接作为领域 payload。"""
    if not isinstance(request.data, dict):
        raise PlannerCommandError('请求体必须是 JSON object')
    return {key: value for key, value in request.data.items() if key not in {'scope', 'occurrence_ref', 'expected_version'}}


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_event_v2(request):
    """创建单次或 recurrence master；正常 occurrence 不写 CalendarEvent。"""
    not_ready = _require_normalized_access(request.user, write=True)
    if not_ready:
        return not_ready
    try:
        event = PlannerCommandService.create_event(request.user, _command_payload(request))
        projection = PlannerRepository.list_event_definitions(
            request.user,
            # DATE 类型以 Asia/Shanghai 午夜转 UTC，repository 的全天过滤按 date
            # 比较；加一日 buffer 可保证刚创建的全天单次 event 也被回显。
            range_start=_to_utc_datetime(request.data['start']) - timedelta(days=1),
            range_end=_to_utc_datetime(request.data['end']) + timedelta(days=1),
        )
        item = next(item for item in projection if item.event.pk == event.pk)
        return Response({'event': serialize_event_definition(item)}, status=status.HTTP_201_CREATED)
    except Exception as exc:  # 领域错误统一在此映射；其余异常仍由 Django 记录。
        return _command_error_response(exc)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def event_command_v2(request, event_id: str):
    """按 scope 修改或删除 event；重复单次操作只写 sparse override。"""
    not_ready = _require_normalized_access(request.user, write=True)
    if not_ready:
        return not_ready
    try:
        expected_version = _expected_version(request)
        scope = request.data.get('scope', 'all') if isinstance(request.data, dict) else 'all'
        occurrence_ref = request.data.get('occurrence_ref') if isinstance(request.data, dict) else None
        if request.method == 'PATCH':
            event = PlannerCommandService.patch_event(
                request.user,
                event_id,
                _command_payload(request),
                scope=scope,
                occurrence_ref=occurrence_ref,
                expected_version=expected_version,
            )
            result = {
                'event_id': event.event_id,
                'version': event.version,
                'source_version': PlannerCommandService.source_version(event, occurrence_ref),
                'scope': scope,
            }
            return Response(result)
        event = PlannerCommandService.delete_event(
            request.user,
            event_id,
            scope=scope,
            occurrence_ref=occurrence_ref,
            expected_version=expected_version,
        )
        return Response(
            {
                'event_id': event.event_id,
                'version': event.version,
                'source_version': PlannerCommandService.source_version(event, occurrence_ref),
                'scope': scope,
                'deleted': True,
            }
        )
    except Exception as exc:
        return _command_error_response(exc)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_events_v2(request):
    """窗口受限的服务器端 event/occurrence 搜索，不下载 legacy 全量 JSON。"""
    not_ready = _require_normalized_access(request.user)
    if not_ready:
        return not_ready
    try:
        range_start, range_end = _parse_range(request)
        query = request.query_params.get('q', '').strip().casefold()
        requested_types = {item.strip() for item in request.query_params.get('types', 'event,todo,reminder').split(',') if item.strip()}
        if requested_types - {'event', 'todo', 'reminder'}:
            raise PlannerCommandError('types 仅支持 event、todo、reminder', code='unsupported_search_type')
        page = int(request.query_params.get('page', '1'))
        page_size = int(request.query_params.get('page_size', '50'))
        if page < 1 or not 1 <= page_size <= 100:
            raise PlannerCommandError('page 必须大于 0，page_size 必须在 1 到 100', code='invalid_pagination')
        event_ids = PlannerRepository.search_event_candidate_ids(request.user, query) if 'event' in requested_types else set()
        occurrences = PlannerRepository.list_event_occurrences(
            request.user,
            range_start=range_start,
            range_end=range_end,
            event_ids=event_ids,
        ) if 'event' in requested_types else []
        if query:
            def matches(occurrence):
                searchable = ' '.join(
                    str(occurrence.payload.get(field, '')) for field in ('title', 'description', 'location')
                ).casefold()
                return query in searchable
            occurrences = [item for item in occurrences if matches(item)]
        results = [serialize_occurrence(item) for item in occurrences]
        if 'todo' in requested_types:
            todos = PlannerEntityQueryService.list_todos(request.user)
            for todo in todos:
                searchable = f'{todo.title} {todo.description}'.casefold()
                due = todo.due_at or todo.due_date
                due_in_range = due is None or range_start <= _to_utc_datetime(due.isoformat()) < range_end
                if due_in_range and (not query or query in searchable):
                    results.append(serialize_todo(todo))
        if 'reminder' in requested_types:
            reminder_occurrences = PlannerEntityQueryService.list_reminder_occurrences(
                request.user, range_start=range_start, range_end=range_end
            )
            for item in reminder_occurrences:
                searchable = f"{item.payload.get('title', '')} {item.payload.get('content', '')}".casefold()
                if not query or query in searchable:
                    results.append(serialize_occurrence(item))
        results.sort(key=lambda item: str(item.get('start') or item.get('due') or ''))
        total = len(results)
        offset = (page - 1) * page_size
        return Response(
            {
                'range': {'from': range_start.isoformat(), 'to': range_end.isoformat()},
                'query': query,
                'types': sorted(requested_types),
                'page': page,
                'page_size': page_size,
                'total': total,
                'results': results[offset : offset + page_size],
            }
        )
    except Exception as exc:
        return _command_error_response(exc)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def groups_v2(request):
    not_ready = _require_normalized_access(request.user, write=request.method == 'POST')
    if not_ready:
        return not_ready
    try:
        if request.method == 'GET':
            groups = PlannerEntityQueryService.list_groups(request.user)
            return Response({'groups': [serialize_group(item) for item in groups], 'count': len(groups)})
        group = PlannerEntityCommandService.create_group(request.user, request.data)
        return Response({'group': serialize_group(group)}, status=status.HTTP_201_CREATED)
    except Exception as exc:
        return _command_error_response(exc)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def group_command_v2(request, group_id: str):
    not_ready = _require_normalized_access(request.user, write=True)
    if not_ready:
        return not_ready
    try:
        expected = _expected_version(request)
        if request.method == 'PATCH':
            group = PlannerEntityCommandService.patch_group(request.user, group_id, _command_payload(request), expected)
        else:
            group = PlannerEntityCommandService.delete_group(
                request.user,
                group_id,
                expected,
                delete_items=bool(request.data.get('delete_items', False)),
            )
        return Response({'group': serialize_group(group), 'deleted': request.method == 'DELETE'})
    except Exception as exc:
        return _command_error_response(exc)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def todos_v2(request):
    not_ready = _require_normalized_access(request.user, write=request.method == 'POST')
    if not_ready:
        return not_ready
    try:
        if request.method == 'GET':
            todos = PlannerEntityQueryService.list_todos(
                request.user,
                status_value=request.query_params.get('status', ''),
                group_id=request.query_params.get('group_id', ''),
            )
            return Response({'todos': [serialize_todo(item) for item in todos], 'count': len(todos)})
        todo = PlannerEntityCommandService.create_todo(request.user, request.data)
        todo = next(item for item in PlannerEntityQueryService.list_todos(request.user) if item.pk == todo.pk)
        return Response({'todo': serialize_todo(todo)}, status=status.HTTP_201_CREATED)
    except Exception as exc:
        return _command_error_response(exc)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def todo_command_v2(request, todo_id: str):
    not_ready = _require_normalized_access(request.user, write=True)
    if not_ready:
        return not_ready
    try:
        expected = _expected_version(request)
        if request.method == 'PATCH':
            todo = PlannerEntityCommandService.patch_todo(request.user, todo_id, _command_payload(request), expected)
        else:
            todo = PlannerEntityCommandService.delete_todo(request.user, todo_id, expected)
        return Response({'todo': serialize_todo(todo), 'deleted': request.method == 'DELETE'})
    except Exception as exc:
        return _command_error_response(exc)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def convert_todo_v2(request, todo_id: str):
    not_ready = _require_normalized_access(request.user, write=True)
    if not_ready:
        return not_ready
    try:
        expected = _expected_version(request)
        todo, event = PlannerEntityCommandService.convert_todo(request.user, todo_id, _command_payload(request), expected)
        return Response({'todo': serialize_todo(todo), 'event_id': event.event_id, 'event_version': event.version})
    except Exception as exc:
        return _command_error_response(exc)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def reminders_v2(request):
    not_ready = _require_normalized_access(request.user, write=request.method == 'POST')
    if not_ready:
        return not_ready
    try:
        if request.method == 'GET':
            if request.query_params.get('from') or request.query_params.get('to'):
                range_start, range_end = _parse_range(request)
                items = PlannerEntityQueryService.list_reminder_occurrences(request.user, range_start=range_start, range_end=range_end)
                return Response({'occurrences': [serialize_occurrence(item) for item in items], 'count': len(items)})
            reminders = PlannerEntityQueryService.list_reminders(request.user)
            return Response({'reminders': [serialize_reminder(item) for item in reminders], 'count': len(reminders)})
        reminder = PlannerEntityCommandService.create_reminder(request.user, request.data)
        return Response({'reminder': serialize_reminder(reminder)}, status=status.HTTP_201_CREATED)
    except Exception as exc:
        return _command_error_response(exc)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def reminder_command_v2(request, reminder_id: str):
    not_ready = _require_normalized_access(request.user, write=True)
    if not_ready:
        return not_ready
    try:
        expected = _expected_version(request)
        if request.method == 'PATCH':
            reminder = PlannerEntityCommandService.patch_reminder(request.user, reminder_id, _command_payload(request), expected)
        else:
            reminder = PlannerEntityCommandService.delete_reminder(request.user, reminder_id, expected)
        return Response({'reminder': serialize_reminder(reminder), 'deleted': request.method == 'DELETE'})
    except Exception as exc:
        return _command_error_response(exc)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reminder_occurrence_action_v2(request):
    not_ready = _require_normalized_access(request.user, write=True)
    if not_ready:
        return not_ready
    try:
        return Response(PlannerEntityCommandService.act_on_reminder_occurrence(request.user, request.data))
    except Exception as exc:
        return _command_error_response(exc)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def shared_group_occurrences_v2(request, share_group_id: str):
    """通过 membership + EventShareGroup join 返回只读共享 occurrence。"""
    not_ready = _require_normalized_access(request.user)
    if not_ready:
        return not_ready
    try:
        range_start, range_end = _parse_range(request)
        group = CollaborativeCalendarGroup.objects.filter(share_group_id=share_group_id).first()
        if group is None:
            raise PlannerCommandError('共享组不存在', code='share_group_not_found')
        membership = GroupMembership.objects.filter(share_group=group, user=request.user).first()
        if group.owner_id != request.user.id and membership is None:
            return Response({'error': '无权访问共享组', 'code': 'share_group_forbidden'}, status=status.HTTP_403_FORBIDDEN)
        links = EventShareGroup.objects.filter(
            share_group=group, event__deleted_at__isnull=True
        ).select_related('event__user')
        ids_by_owner: dict[int, set[str]] = {}
        owners = {}
        event_meta = {}
        for link in links:
            ids_by_owner.setdefault(link.event.user_id, set()).add(link.event.event_id)
            owners[link.event.user_id] = link.event.user
            series = EventRecurrenceSeries.objects.filter(
                master_event=link.event, deleted_at__isnull=True
            ).first()
            event_meta[link.event.event_id] = {
                'rrule': series.rrule_canonical or series.rrule if series else '',
                'series_id': series.series_id if series else None,
                'master_start': (link.event.start_date or link.event.start_at).isoformat(),
                'master_end': (link.event.end_date or link.event.end_at).isoformat(),
                'share_group_ids': list(
                    link.event.share_links.values_list('share_group__share_group_id', flat=True)
                ),
            }
        results = []
        for owner_id, event_ids in ids_by_owner.items():
            occurrences = PlannerRepository.list_event_occurrences(
                owners[owner_id], range_start=range_start, range_end=range_end, event_ids=event_ids
            )
            owner_membership = GroupMembership.objects.filter(share_group=group, user_id=owner_id).first()
            for occurrence in occurrences:
                if occurrence.ref.entity_id not in event_ids:
                    continue
                item = serialize_occurrence(occurrence)
                item.update(
                    {
                        'read_only': owner_id != request.user.id,
                        'owner_id': owner_id,
                        'owner_username': owners[owner_id].username,
                        'member_color': owner_membership.member_color if owner_membership else group.share_group_color,
                        'share_group_id': group.share_group_id,
                        **event_meta[occurrence.ref.entity_id],
                    }
                )
                results.append(item)
        results.sort(key=lambda item: item['start'])
        members = [
            {
                'user_id': item.user_id,
                'username': item.user.username,
                'color': item.member_color,
            }
            for item in GroupMembership.objects.filter(share_group=group).select_related('user')
        ]
        return Response({
            'occurrences': results,
            'count': len(results),
            'read_only': group.owner_id != request.user.id,
            'current_user_id': request.user.id,
            'members': members,
        })
    except Exception as exc:
        return _command_error_response(exc)
