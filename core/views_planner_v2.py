"""Planner v2 的只读 definitions/occurrences API。"""

from datetime import date, datetime, time

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.planner.presentation import serialize_event_definition, serialize_occurrence
from core.planner.recurrence.codec import PlannerTimeCodec, PlannerTimeError
from core.planner.repository import PlannerRepository
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


def _require_verified_normalized_read(user):
    """v2 显式接口只允许已验证的 shadow 投影，绝不回退混读。"""
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
    not_ready = _require_verified_normalized_read(request.user)
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
    not_ready = _require_verified_normalized_read(request.user)
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
