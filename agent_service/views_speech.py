"""
语音识别公开 API

提供以下端点（无需登录）：
- POST /api/agent/speech-to-text/    上传音频，返回识别文字

设计原则：
- 无需用户认证（公开接口）
- 限制最大时长 60 秒
- 限制最大文件大小 15 MB
- 降级链：百度云 VOP → faster-whisper tiny（本地）

Author: UniSchedulerSuper
"""
import os
import tempfile
import mimetypes

from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import AllowAny
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework import status

from agent_service.parsers.audio_parser import AudioParser, SUPPORTED_AUDIO_MIMES
from logger import logger

# 文件大小上限（15 MB，约对应 60s 高质量音频）
MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024


@api_view(['POST'])
@permission_classes([AllowAny])
@parser_classes([MultiPartParser, FormParser])
def speech_to_text(request):
    """
    语音转文字接口（公开）

    POST /api/agent/speech-to-text/
    Content-Type: multipart/form-data

    表单字段：
        audio (File): 音频文件，必填。
                      支持格式：wav / mp3 / ogg / flac / webm / aac / m4a / amr

    成功响应 200：
    {
        "success": true,
        "text": "识别出的文字内容",
        "duration_seconds": 12.5,
        "provider": "baidu | faster_whisper",
        "filename": "原始文件名"
    }

    错误响应 400/500：
    {
        "success": false,
        "error": "错误描述"
    }
    """
    audio_file = request.FILES.get('audio')
    if not audio_file:
        return Response(
            {"success": False, "error": "缺少 audio 文件字段"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # ——— 文件大小检查 ———
    if audio_file.size > MAX_FILE_SIZE_BYTES:
        return Response(
            {
                "success": False,
                "error": (
                    f"文件过大（{audio_file.size / 1024 / 1024:.1f} MB），"
                    f"最大允许 {MAX_FILE_SIZE_BYTES // 1024 // 1024} MB"
                ),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # ——— MIME 类型检测 ———
    mime_type = _detect_mime(audio_file)
    if mime_type not in SUPPORTED_AUDIO_MIMES:
        return Response(
            {
                "success": False,
                "error": (
                    f"不支持的音频格式：{mime_type or '未知'}。"
                    f"支持的格式：wav、mp3、ogg、flac、webm、aac、m4a、amr"
                ),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # ——— 写入临时文件 ———
    suffix = _get_suffix(audio_file.name, mime_type)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=suffix, delete=False, prefix="qa_speech_"
        ) as tmp:
            for chunk in audio_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        logger.debug(
            f"[SpeechAPI] 接收文件: {audio_file.name}，"
            f"{audio_file.size / 1024:.1f} KB，MIME={mime_type}"
        )

        # ——— 调用解析器 ———
        parser = AudioParser()
        result = parser.parse(tmp_path, mime_type=mime_type)

        if not result["success"]:
            logger.warning(
                f"[SpeechAPI] 识别失败: {audio_file.name} - {result['error']}"
            )
            return Response(
                {"success": False, "error": result["error"]},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        meta = result.get("metadata", {})
        logger.debug(
            f"[SpeechAPI] 识别成功: {audio_file.name}，"
            f"provider={meta.get('provider')}，{len(result['text'])} 字符"
        )
        return Response(
            {
                "success": True,
                "text": result["text"],
                "duration_seconds": meta.get("duration_seconds"),
                "provider": meta.get("provider"),
                "filename": audio_file.name,
            },
            status=status.HTTP_200_OK,
        )

    except Exception as e:
        logger.exception(f"[SpeechAPI] 处理异常: {e}")
        return Response(
            {"success": False, "error": f"服务器内部错误: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    finally:
        # 清理临时文件
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


# ------------------------------------------------------------------
# 工具函数
# ------------------------------------------------------------------

def _detect_mime(file_obj) -> str:
    """
    从上传文件中推断 MIME 类型。
    优先级：Content-Type 头 → 文件名扩展名。
    """
    # 1. HTTP Content-Type
    content_type = getattr(file_obj, 'content_type', '') or ''
    ct = content_type.split(';')[0].strip().lower()
    if ct and ct.startswith('audio/'):
        return ct

    # 2. 文件名扩展名
    name = getattr(file_obj, 'name', '') or ''
    mime, _ = mimetypes.guess_type(name)
    if mime:
        return mime.lower()

    return ''


def _get_suffix(filename: str, mime_type: str) -> str:
    """根据文件名或 MIME 推断扩展名（用于临时文件）"""
    if filename:
        _, ext = os.path.splitext(filename)
        if ext:
            return ext.lower()

    from agent_service.parsers.audio_parser import _MIME_TO_EXT
    ext = _MIME_TO_EXT.get(mime_type, '.audio')
    return f".{ext}" if not ext.startswith('.') else ext
