"""P4 cutover 后保留的旧 rollback URL 兼容响应。"""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods


@csrf_exempt
@require_http_methods(["POST"])
def rollback_transaction_impl(request):
    """旧事务历史已清理；任何旧协议请求都稳定返回 410。"""
    return JsonResponse({
        'status': 'error',
        'code': 'rollback_legacy_unsupported',
        'message': '旧版事务回滚已停用；仅支持当前 Agent 会话窗口内的新消息回滚。',
    }, status=410)
