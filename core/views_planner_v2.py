"""Planner v2 normalized event API。"""

from datetime import date, datetime, time

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.planner.application import PlannerApplicationAccessError, PlannerApplicationService
from core.planner.commands import PlannerCommandError, PlannerCommandVersionConflict
from core.planner.context import PlannerExecutionContext
from core.planner.recurrence.codec import PlannerTimeCodec, PlannerTimeError
from core.planner.repository import PlannerNotFoundError
from core.planner.rollout import PlannerRolloutPolicy
from logger import logger


def _web_context(request) -> PlannerExecutionContext:
    return PlannerExecutionContext(
        user=request.user,
        source='web_v2',
        entrypoint=PlannerRolloutPolicy.ENTRYPOINT_API_V2,
        request_id=request.headers.get('X-Request-ID', ''),
    )


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
    try:
        range_start, range_end = _parse_range(request)
        return Response(PlannerApplicationService.list_event_definitions(
            _web_context(request), range_start=range_start, range_end=range_end
        ))
    except (PlannerTimeError, ValueError) as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as exc:
        return _command_error_response(exc)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_event_occurrences_v2(request):
    """按半开窗口纯展开 occurrence；该查询不写入任何模型。"""
    try:
        range_start, range_end = _parse_range(request)
        return Response(PlannerApplicationService.list_event_occurrences(
            _web_context(request), range_start=range_start, range_end=range_end
        ))
    except (PlannerTimeError, ValueError) as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as exc:
        return _command_error_response(exc)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_event_conflicts_v2(request):
    """复用 occurrence query 检测半开区间重叠；不物化虚拟实例。"""
    try:
        range_start, range_end = _parse_range(request)
        return Response(PlannerApplicationService.list_conflicts(
            _web_context(request), range_start=range_start, range_end=range_end
        ))
    except (PlannerTimeError, ValueError) as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as exc:
        return _command_error_response(exc)


def _command_error_response(exc: Exception) -> Response:
    """保持 v2 command 的错误码稳定，避免客户端解析自然语言。"""
    if isinstance(exc, PlannerApplicationAccessError):
        if exc.decision.reason == 'share_group_forbidden':
            return Response({'error': str(exc), 'code': 'share_group_forbidden'}, status=status.HTTP_403_FORBIDDEN)
        return Response(
            {
                'error': str(exc),
                'code': exc.code,
                'reason': exc.decision.reason,
                'effective_mode': exc.decision.effective_mode,
            },
            status=status.HTTP_409_CONFLICT,
        )
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
    try:
        result = PlannerApplicationService.create_event(
            _web_context(request),
            _command_payload(request),
            range_start=_to_utc_datetime(request.data['start']),
            range_end=_to_utc_datetime(request.data['end']),
        )
        return Response(result, status=status.HTTP_201_CREATED)
    except Exception as exc:  # 领域错误统一在此映射；其余异常仍由 Django 记录。
        return _command_error_response(exc)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def event_command_v2(request, event_id: str):
    """按 scope 修改或删除 event；重复单次操作只写 sparse override。"""
    try:
        expected_version = _expected_version(request)
        scope = request.data.get('scope', 'all') if isinstance(request.data, dict) else 'all'
        occurrence_ref = request.data.get('occurrence_ref') if isinstance(request.data, dict) else None
        if request.method == 'PATCH':
            result = PlannerApplicationService.patch_event(
                _web_context(request),
                event_id,
                _command_payload(request),
                scope=scope,
                occurrence_ref=occurrence_ref,
                expected_version=expected_version,
            )
            return Response(result)
        result = PlannerApplicationService.delete_event(
            _web_context(request),
            event_id,
            scope=scope,
            occurrence_ref=occurrence_ref,
            expected_version=expected_version,
        )
        return Response(result)
    except Exception as exc:
        return _command_error_response(exc)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_events_v2(request):
    """窗口受限的服务器端 event/occurrence 搜索，不下载 legacy 全量 JSON。"""
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
        return Response(PlannerApplicationService.search_items(
            _web_context(request), query=query, requested_types=requested_types,
            range_start=range_start, range_end=range_end, page=page, page_size=page_size,
        ))
    except Exception as exc:
        return _command_error_response(exc)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def groups_v2(request):
    try:
        if request.method == 'GET':
            return Response(PlannerApplicationService.list_groups(_web_context(request)))
        return Response(PlannerApplicationService.create_group(_web_context(request), request.data), status=status.HTTP_201_CREATED)
    except Exception as exc:
        return _command_error_response(exc)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def group_command_v2(request, group_id: str):
    try:
        expected = _expected_version(request)
        if request.method == 'PATCH':
            return Response(PlannerApplicationService.patch_group(_web_context(request), group_id, _command_payload(request), expected))
        return Response(PlannerApplicationService.delete_group(
            _web_context(request), group_id, expected, delete_items=bool(request.data.get('delete_items', False))
        ))
    except Exception as exc:
        return _command_error_response(exc)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def todos_v2(request):
    try:
        if request.method == 'GET':
            return Response(PlannerApplicationService.list_todos(
                _web_context(request),
                status_value=request.query_params.get('status', ''),
                group_id=request.query_params.get('group_id', ''),
            ))
        return Response(PlannerApplicationService.create_todo(_web_context(request), request.data), status=status.HTTP_201_CREATED)
    except Exception as exc:
        return _command_error_response(exc)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def todo_command_v2(request, todo_id: str):
    try:
        expected = _expected_version(request)
        if request.method == 'PATCH':
            return Response(PlannerApplicationService.patch_todo(_web_context(request), todo_id, _command_payload(request), expected))
        return Response(PlannerApplicationService.delete_todo(_web_context(request), todo_id, expected))
    except Exception as exc:
        return _command_error_response(exc)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def convert_todo_v2(request, todo_id: str):
    try:
        expected = _expected_version(request)
        return Response(PlannerApplicationService.convert_todo(_web_context(request), todo_id, _command_payload(request), expected))
    except Exception as exc:
        return _command_error_response(exc)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def reminders_v2(request):
    try:
        if request.method == 'GET':
            if request.query_params.get('from') or request.query_params.get('to'):
                range_start, range_end = _parse_range(request)
                return Response(PlannerApplicationService.list_reminder_occurrences(
                    _web_context(request), range_start=range_start, range_end=range_end
                ))
            return Response(PlannerApplicationService.list_reminders(_web_context(request)))
        return Response(PlannerApplicationService.create_reminder(_web_context(request), request.data), status=status.HTTP_201_CREATED)
    except Exception as exc:
        return _command_error_response(exc)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def reminder_command_v2(request, reminder_id: str):
    try:
        expected = _expected_version(request)
        scope = request.data.get('scope', 'all') if isinstance(request.data, dict) else 'all'
        occurrence_ref = request.data.get('occurrence_ref') if isinstance(request.data, dict) else None
        if request.method == 'PATCH':
            return Response(PlannerApplicationService.patch_reminder(
                _web_context(request), reminder_id, _command_payload(request), expected,
                scope=scope, occurrence_ref=occurrence_ref,
            ))
        return Response(PlannerApplicationService.delete_reminder(
            _web_context(request), reminder_id, expected,
            scope=scope, occurrence_ref=occurrence_ref,
        ))
    except Exception as exc:
        return _command_error_response(exc)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reminder_occurrence_action_v2(request):
    try:
        return Response(PlannerApplicationService.act_on_reminder_occurrence(_web_context(request), request.data))
    except Exception as exc:
        return _command_error_response(exc)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def shared_group_occurrences_v2(request, share_group_id: str):
    """通过 membership + EventShareGroup join 返回只读共享 occurrence。"""
    try:
        range_start, range_end = _parse_range(request)
        return Response(PlannerApplicationService.list_shared_occurrences(
            _web_context(request), share_group_id=share_group_id,
            range_start=range_start, range_end=range_end,
        ))
    except Exception as exc:
        return _command_error_response(exc)
