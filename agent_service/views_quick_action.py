"""
Quick Action API Views
快速操作 HTTP API 接口

提供以下端点：
- POST /api/quick-action/          创建快速操作任务
- GET  /api/quick-action/<id>/     查询任务状态（支持长轮询）
- GET  /api/quick-action/list/     获取历史任务列表

Author: Quick Action System
"""

from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from django.db.models import Q
import threading
import time
import os
import tempfile
import mimetypes
from datetime import datetime, timedelta

from agent_service.models import QuickActionTask
from agent_service.quick_action_agent import execute_quick_action_sync, build_system_message
from agent_service.context_optimizer import update_token_usage, get_current_model_config
from logger import logger


# ============================================
# 创建快速操作
# ============================================
@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def create_quick_action(request):
    """
    创建快速操作任务

    支持两种输入方式（二选一，不可同时提供）：

    方式一：JSON Body（纯文本）
        Content-Type: application/json
        {
            "text": "2月8日的会议改到晚上8点",
            "sync": false,    // 可选，是否同步执行（默认异步）
            "timeout": 30     // 可选，同步执行超时时间（秒）
        }

    方式二：multipart/form-data（语音输入）
        Content-Type: multipart/form-data
        字段：
            audio (File): 音频文件，≤ 60s，支持 wav/mp3/ogg/flac/webm/aac/m4a/amr
            sync  (str):  可选，"true" 表示同步执行
            timeout (int): 可选，同步超时秒数

    两种方式不可同时提供 text 与 audio，否则返回 400。

    Response (async):
    {
        "task_id": "uuid",
        "status": "pending",
        "status_url": "/api/quick-action/<uuid>/",
        "created_at": "2024-02-08T10:00:00",
        "input_type": "text | audio"   // 标注本次输入类型
    }

    Response (sync): 同步返回完整任务结果
    """
    has_text = bool(request.data.get('text', '').strip())
    has_audio = 'audio' in request.FILES

    # ——— 互斥检查 ———
    if has_text and has_audio:
        return Response(
            {
                "error": "text 与 audio 不能同时提供，请二选一",
                "code": "AMBIGUOUS_INPUT",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not has_text and not has_audio:
        return Response(
            {"error": "必须提供 text 或 audio 之一", "code": "EMPTY_INPUT"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    sync_mode = request.data.get('sync', False)
    # multipart 中 sync 是字符串
    if isinstance(sync_mode, str):
        sync_mode = sync_mode.lower() in ('true', '1', 'yes')
    timeout = int(request.data.get('timeout', 30))

    input_type = 'text'

    # ——— 语音输入路径 ———
    if has_audio:
        audio_result = _transcribe_audio(request.FILES['audio'])
        if not audio_result['success']:
            return Response(
                {
                    "error": f"语音识别失败：{audio_result['error']}",
                    "code": "SPEECH_RECOGNITION_FAILED",
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        text = audio_result['text'].strip()
        input_type = 'audio'
        if not text:
            return Response(
                {"error": "语音识别结果为空", "code": "EMPTY_SPEECH_RESULT"},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
    else:
        text = request.data.get('text', '').strip()

    # ——— 文本校验 ———
    if len(text) > 1000:
        return Response(
            {"error": "输入文本过长，最多1000字符", "code": "TEXT_TOO_LONG"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    user = request.user
    
    # 创建任务
    task = QuickActionTask.objects.create(
        user=user,
        input_text=text
    )
    
    logger.debug(f"[QuickAction] Created task {task.task_id} for user {user.username} (input_type={input_type}): {text[:50]}...")
    
    if sync_mode:
        # 同步执行
        return _execute_sync(task, user, text, timeout)
    else:
        # 确保任务已保存到数据库（刷新事务）
        from django.db import transaction
        transaction.on_commit(lambda: _start_async_execution(task.task_id, user.id, text))
        
        return Response({
            "task_id": str(task.task_id),
            "status": "pending",
            "status_url": f"/api/agent/quick-action/{task.task_id}/",
            "created_at": task.created_at.isoformat(),
            "input_type": input_type,
        }, status=status.HTTP_201_CREATED)


def _start_async_execution(task_id, user_id: int, text: str):
    """启动异步执行线程"""
    thread = threading.Thread(
        target=_execute_async,
        args=(task_id, user_id, text)
    )
    thread.daemon = True
    thread.start()


def _execute_sync(task: QuickActionTask, user, text: str, timeout: int) -> Response:
    """同步执行快速操作"""
    try:
        task.mark_processing()
        
        # 执行
        result = execute_quick_action_sync(user, text, str(task.task_id))
        
        # 获取模型信息并记录 token 使用
        model_id, _ = get_current_model_config(user)
        tokens = result.get('tokens', {})
        input_tokens = tokens.get('input', 0)
        output_tokens = tokens.get('output', 0)
        
        if input_tokens > 0 or output_tokens > 0:
            update_token_usage(user, input_tokens, output_tokens, model_id)
        
        # 更新任务
        task.mark_completed(
            result_type=result.get('type', 'error'),
            result={"message": result.get('message', ''), "tool_calls": result.get('tool_calls', [])},
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model_used=model_id
        )
        
        return Response(task.to_response_dict(), status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.exception(f"[QuickAction] Sync execution failed: {e}")
        task.mark_completed(
            result_type='error',
            result={"message": f"❌ 执行出错: {str(e)}"}
        )
        return Response(task.to_response_dict(), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _execute_async(task_id, user_id: int, text: str):
    """异步执行快速操作（后台线程）"""
    # Django 在线程中需要重新设置数据库连接
    from django.db import connection
    from django.contrib.auth.models import User
    import time
    
    try:
        # 重新获取 user 和 task（避免跨线程问题）
        connection.ensure_connection()
        user = User.objects.get(id=user_id)
        
        # 重试获取任务（防止事务未提交）
        task = None
        for attempt in range(5):
            try:
                task = QuickActionTask.objects.get(task_id=task_id)
                break
            except QuickActionTask.DoesNotExist:
                if attempt < 4:
                    time.sleep(0.1 * (attempt + 1))  # 递增延迟
                else:
                    raise
        
        if not task:
            raise QuickActionTask.DoesNotExist(f"Task {task_id} not found after retries")
        
        task.mark_processing()
        
        # 执行
        result = execute_quick_action_sync(user, text, str(task_id))
        
        # 获取模型信息
        model_id, _ = get_current_model_config(user)
        tokens = result.get('tokens', {})
        input_tokens = tokens.get('input', 0)
        output_tokens = tokens.get('output', 0)
        
        if input_tokens > 0 or output_tokens > 0:
            update_token_usage(user, input_tokens, output_tokens, model_id)
        
        # 更新任务
        task.mark_completed(
            result_type=result.get('type', 'error'),
            result={"message": result.get('message', ''), "tool_calls": result.get('tool_calls', [])},
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model_used=model_id
        )
        
        logger.debug(f"[QuickAction] Task {task_id} completed: {result.get('type')}")
        
    except Exception as e:
        logger.exception(f"[QuickAction] Async execution failed: {e}")
        try:
            task = QuickActionTask.objects.get(task_id=task_id)
            task.mark_completed(
                result_type='error',
                result={"message": f"❌ 执行出错: {str(e)}"}
            )
        except Exception:
            pass
    finally:
        connection.close()


# ============================================
# 查询任务状态
# ============================================
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_quick_action_status(request, task_id):
    """
    查询任务状态
    
    GET /api/quick-action/<task_id>/
    GET /api/quick-action/<task_id>/?wait=true   # 长轮询模式
    
    Query Parameters:
    - wait: true/false - 是否使用长轮询（最多等待30秒）
    
    Response:
    {
        "task_id": "uuid",
        "status": "success",
        "result_type": "action_completed",
        "result": {"message": "...", "tool_calls": [...]},
        "input_text": "原始输入",
        "tool_calls_count": 3,
        "execution_time_ms": 1234,
        "tokens": {"input": 100, "output": 50, "cost": 0.001, "model": "gpt-4"},
        "created_at": "...",
        "completed_at": "..."
    }
    """
    try:
        task = QuickActionTask.objects.get(task_id=task_id, user=request.user)
    except QuickActionTask.DoesNotExist:
        return Response(
            {"error": "任务不存在", "code": "NOT_FOUND"},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # 长轮询支持
    wait = request.query_params.get('wait', 'false').lower() == 'true'
    if wait and task.status in ['pending', 'processing']:
        # 最多等待 30 秒，每 0.5 秒检查一次
        max_wait = 30
        interval = 0.5
        waited = 0
        
        while waited < max_wait and task.status in ['pending', 'processing']:
            time.sleep(interval)
            waited += interval
            task.refresh_from_db()
    
    return Response(task.to_response_dict(), status=status.HTTP_200_OK)


# ============================================
# 历史任务列表
# ============================================
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_quick_actions(request):
    """
    获取历史快速操作任务列表
    
    GET /api/quick-action/list/
    GET /api/quick-action/list/?limit=10&offset=0
    GET /api/quick-action/list/?status=success
    GET /api/quick-action/list/?days=7
    
    Query Parameters:
    - limit: 返回数量限制（默认20，最大100）
    - offset: 偏移量（用于分页）
    - status: 筛选状态（pending/processing/success/failed/timeout）
    - days: 获取最近N天的任务（默认7天）
    
    Response:
    {
        "count": 100,
        "limit": 20,
        "offset": 0,
        "tasks": [...]
    }
    """
    user = request.user
    
    # 解析参数
    limit = min(int(request.query_params.get('limit', 20)), 100)
    offset = int(request.query_params.get('offset', 0))
    status_filter = request.query_params.get('status', None)
    days = int(request.query_params.get('days', 7))
    
    # 构建查询
    queryset = QuickActionTask.objects.filter(
        user=user,
        created_at__gte=timezone.now() - timedelta(days=days)
    )
    
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    
    # 统计总数
    total_count = queryset.count()
    
    # 分页
    tasks = queryset.order_by('-created_at')[offset:offset + limit]
    
    # 格式化结果
    task_list = []
    for task in tasks:
        task_data = {
            "task_id": str(task.task_id),
            "status": task.status,
            "result_type": task.result_type,
            "input_text": task.input_text[:100] + ("..." if len(task.input_text) > 100 else ""),
            "created_at": task.created_at.isoformat(),
            "execution_time_ms": task.get_execution_time_ms(),
        }
        
        # 完成的任务附加结果预览
        if task.status in ['success', 'failed'] and task.result:
            message = task.result.get('message', '')
            task_data['result_preview'] = message[:200] + ("..." if len(message) > 200 else "")
        
        task_list.append(task_data)
    
    return Response({
        "count": total_count,
        "limit": limit,
        "offset": offset,
        "tasks": task_list
    }, status=status.HTTP_200_OK)


# ============================================
# 取消任务（可选功能）
# ============================================
@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def cancel_quick_action(request, task_id):
    """
    取消待执行的任务
    
    DELETE /api/quick-action/<task_id>/
    
    可以取消 pending 或 processing 状态的任务。
    """
    from .quick_action_agent import set_task_cancelled
    
    try:
        task = QuickActionTask.objects.get(task_id=task_id, user=request.user)
    except QuickActionTask.DoesNotExist:
        return Response(
            {"error": "任务不存在", "code": "NOT_FOUND"},
            status=status.HTTP_404_NOT_FOUND
        )
    
    if task.status not in ['pending', 'processing']:
        return Response(
            {"error": f"无法取消状态为 {task.status} 的任务", "code": "INVALID_STATUS"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # 设置取消标志（通知后台线程停止）
    set_task_cancelled(str(task_id))
    
    # 更新任务状态
    task.status = 'failed'
    task.result_type = 'error'
    task.result = {"message": "任务已被用户取消", "cancelled": True}
    task.completed_at = timezone.now()
    task.save()
    
    logger.debug(f"[QuickAction] Task {task_id} cancelled by user")
    
    return Response({"message": "任务已取消"}, status=status.HTTP_200_OK)


# ============================================
# 音频转写辅助函数
# ============================================

def _transcribe_audio(audio_file) -> dict:
    """
    将上传的音频文件转写为文字。

    Args:
        audio_file: Django InMemoryUploadedFile 或 TemporaryUploadedFile

    Returns:
        {
            "success": bool,
            "text": str,
            "duration_seconds": float | None,
            "error": str
        }
    """
    from agent_service.parsers.audio_parser import AudioParser, SUPPORTED_AUDIO_MIMES, _MIME_TO_EXT

    # 大小限制：15 MB
    MAX_AUDIO_SIZE = 15 * 1024 * 1024
    if audio_file.size > MAX_AUDIO_SIZE:
        return {
            "success": False,
            "text": "",
            "error": (
                f"音频文件过大（{audio_file.size / 1024 / 1024:.1f} MB），"
                f"最大允许 {MAX_AUDIO_SIZE // 1024 // 1024} MB"
            ),
        }

    # MIME 检测：优先 Content-Type，其次按文件名猜
    content_type = getattr(audio_file, 'content_type', '') or ''
    mime_type = content_type.split(';')[0].strip().lower()
    if not mime_type.startswith('audio/'):
        guessed, _ = mimetypes.guess_type(audio_file.name or '')
        if guessed:
            mime_type = guessed.lower()

    if mime_type not in SUPPORTED_AUDIO_MIMES:
        return {
            "success": False,
            "text": "",
            "error": (
                f"不支持的音频格式：{mime_type or '未知'}。"
                "支持：wav、mp3、ogg、flac、webm、aac、m4a、amr"
            ),
        }

    # 写入临时文件
    ext = _MIME_TO_EXT.get(mime_type, 'audio')
    if not ext.startswith('.'):
        ext = f'.{ext}'

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False, prefix='qa_audio_') as tmp:
            for chunk in audio_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        parser = AudioParser()
        result = parser.parse(tmp_path, mime_type=mime_type)
        return {
            "success": result["success"],
            "text": result.get("text", ""),
            "duration_seconds": result.get("metadata", {}).get("duration_seconds"),
            "error": result.get("error", ""),
        }
    except Exception as e:
        logger.exception(f"[QuickAction] 音频转写异常: {e}")
        return {"success": False, "text": "", "error": str(e)}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
