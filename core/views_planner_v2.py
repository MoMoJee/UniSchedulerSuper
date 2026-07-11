"""Planner v2 normalized event API。"""

from datetime import date, datetime, time, timedelta

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.planner.commands import PlannerCommandError, PlannerCommandService, PlannerCommandVersionConflict
from core.planner.presentation import serialize_event_definition, serialize_occurrence
from core.planner.recurrence.codec import PlannerTimeCodec, PlannerTimeError
from core.planner.repository import PlannerNotFoundError, PlannerRepository
from core.planner.rollout import PlannerRolloutPolicy


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


def _require_verified_normalized_access(user):
    """v2 显式接口只允许已验证投影，绝不回退或混写 legacy。"""
    if not PlannerRolloutPolicy.is_verified_clean(user):
        return Response(
            {
                'error': '该用户尚未完成 normalized Planner 校验，v2 接口不可用。',
                'code': 'planner_normalized_not_verified',
            },
            status=status.HTTP_409_CONFLICT,
        )
    return None


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_event_definitions_v2(request):
    """返回当前用户的 event definitions；正常 recurrence instance 不落行。"""
    not_ready = _require_verified_normalized_access(request.user)
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
    not_ready = _require_verified_normalized_access(request.user)
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


def _command_error_response(exc: Exception) -> Response:
    """保持 v2 command 的错误码稳定，避免客户端解析自然语言。"""
    if isinstance(exc, PlannerNotFoundError):
        return Response({'error': str(exc), 'code': 'event_not_found'}, status=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, PlannerCommandVersionConflict):
        return Response({'error': str(exc), 'code': exc.code}, status=status.HTTP_409_CONFLICT)
    if isinstance(exc, PlannerCommandError):
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
    not_ready = _require_verified_normalized_access(request.user)
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
    not_ready = _require_verified_normalized_access(request.user)
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
    not_ready = _require_verified_normalized_access(request.user)
    if not_ready:
        return not_ready
    try:
        range_start, range_end = _parse_range(request)
        query = request.query_params.get('q', '').strip().casefold()
        requested_types = {item.strip() for item in request.query_params.get('types', 'event').split(',') if item.strip()}
        if requested_types - {'event'}:
            raise PlannerCommandError('当前 P3-B search 仅支持 event 类型', code='unsupported_search_type')
        page = int(request.query_params.get('page', '1'))
        page_size = int(request.query_params.get('page_size', '50'))
        if page < 1 or not 1 <= page_size <= 100:
            raise PlannerCommandError('page 必须大于 0，page_size 必须在 1 到 100', code='invalid_pagination')
        occurrences = PlannerRepository.list_event_occurrences(
            request.user,
            range_start=range_start,
            range_end=range_end,
        )
        if query:
            def matches(occurrence):
                searchable = ' '.join(
                    str(occurrence.payload.get(field, '')) for field in ('title', 'description', 'location')
                ).casefold()
                return query in searchable
            occurrences = [item for item in occurrences if matches(item)]
        total = len(occurrences)
        offset = (page - 1) * page_size
        return Response(
            {
                'range': {'from': range_start.isoformat(), 'to': range_end.isoformat()},
                'query': query,
                'types': sorted(requested_types),
                'page': page,
                'page_size': page_size,
                'total': total,
                'results': [serialize_occurrence(item) for item in occurrences[offset : offset + page_size]],
            }
        )
    except Exception as exc:
        return _command_error_response(exc)
