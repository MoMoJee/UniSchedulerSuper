"""
音频解析器（语音转文字）

功能：
- 检查音频时长（最长 60 秒）
- 百度云语音识别（pro_api，OAuth2 认证，云端优先）
- faster-whisper tiny 模型（本地轻量级兜底，无需 GPU）

百度云 VOP API 格式约束：
- 仅接受 PCM / WAV（16000Hz 单声道）
- 其他格式（mp3、ogg、flac 等）会尝试使用 pydub 转换

降级链：baidu（云端） → faster-whisper-tiny（本地） → 返回错误

Author: UniSchedulerSuper
"""
import os
import wave
import base64
import struct
from typing import Dict, Any, Optional, Tuple

from .base import BaseParser
from logger import logger


# 百度云 VOP 支持直接传入的格式
_BAIDU_NATIVE_FORMATS = {'pcm', 'wav'}

# 本解析器受理的 MIME 类型
SUPPORTED_AUDIO_MIMES = {
    'audio/wav',
    'audio/x-wav',
    'audio/wave',
    'audio/mpeg',         # mp3
    'audio/mp3',
    'audio/ogg',
    'audio/webm',
    'audio/flac',
    'audio/x-flac',
    'audio/aac',
    'audio/mp4',
    'audio/m4a',
    'audio/x-m4a',
    'audio/amr',
}

# MIME → 扩展名，用于 pydub 格式推断
_MIME_TO_EXT = {
    'audio/wav': 'wav',
    'audio/x-wav': 'wav',
    'audio/wave': 'wav',
    'audio/mpeg': 'mp3',
    'audio/mp3': 'mp3',
    'audio/ogg': 'ogg',
    'audio/webm': 'webm',
    'audio/flac': 'flac',
    'audio/x-flac': 'flac',
    'audio/aac': 'aac',
    'audio/mp4': 'mp4',
    'audio/m4a': 'm4a',
    'audio/x-m4a': 'm4a',
    'audio/amr': 'amr',
}

MAX_DURATION_SECONDS = 60


class AudioParser(BaseParser):
    """
    音频解析器（语音转文字）
    
    降级链：百度云 VOP → faster-whisper tiny（本地）
    """

    # 百度 access_token 类级缓存
    _baidu_access_token: str = ""
    _baidu_token_expires_at: float = 0.0

    # faster-whisper 模型缓存（延迟加载）
    _whisper_model = None

    def can_parse(self, mime_type: str) -> bool:
        return mime_type.lower() in SUPPORTED_AUDIO_MIMES

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def parse(self, file_path: str, **kwargs) -> Dict[str, Any]:
        """
        将音频文件转为文字。

        Kwargs:
            mime_type (str): MIME 类型（辅助格式推断）

        Returns:
            {
                "success": bool,
                "text": str,
                "metadata": {"duration_seconds": float, "provider": str},
                "error": str
            }
        """
        filename = os.path.basename(file_path)
        mime_type = kwargs.get('mime_type', '').lower()

        # ——— 1. 时长检查 ———
        try:
            duration = self._get_duration(file_path, mime_type)
        except Exception as e:
            logger.warning(f"[AudioParser] 时长检测失败，将继续尝试解析: {e}")
            duration = None

        if duration is not None and duration > MAX_DURATION_SECONDS:
            return {
                "success": False,
                "text": "",
                "metadata": {"duration_seconds": duration},
                "error": f"音频时长 {duration:.1f}s 超过最大限制 {MAX_DURATION_SECONDS}s",
            }

        logger.debug(f"[AudioParser] 开始解析: {filename}，时长={duration}s，MIME={mime_type}")

        # ——— 2. 降级链 ———
        fallback_chain = self._get_fallback_chain()
        logger.debug(f"[AudioParser] 降级链: {' → '.join(fallback_chain)}")

        dispatch = {
            'baidu': self._try_baidu_speech,
            'faster_whisper': self._try_faster_whisper,
        }

        for provider in fallback_chain:
            handler = dispatch.get(provider)
            if not handler:
                continue

            text = handler(file_path, mime_type)
            if text is not None:  # None 表示该引擎不可用/失败，空串是有效结果
                logger.info(
                    f"[AudioParser] {provider} 识别成功: {filename}，"
                    f"{len(text)} 字符"
                )
                return {
                    "success": True,
                    "text": text,
                    "metadata": {
                        "duration_seconds": duration,
                        "provider": provider,
                    },
                    "error": "",
                }

        return {
            "success": False,
            "text": "",
            "metadata": {"duration_seconds": duration},
            "error": "所有语音识别引擎均不可用或识别失败",
        }

    # ------------------------------------------------------------------
    # 降级链构建
    # ------------------------------------------------------------------
    def _get_fallback_chain(self) -> list:
        """从 APIKeyManager 读取已启用的服务"""
        from config.api_keys_manager import APIKeyManager
        return APIKeyManager.get_speech_fallback_chain()

    # ------------------------------------------------------------------
    # 时长检测
    # ------------------------------------------------------------------
    def _get_duration(self, file_path: str, mime_type: str) -> Optional[float]:
        """
        获取音频时长（秒）。
        优先用 wave 模块（WAV）；其他格式依次尝试 mutagen / pydub。
        """
        ext = _MIME_TO_EXT.get(mime_type, '').lower() or os.path.splitext(file_path)[1].lower().lstrip('.')

        # WAV 原生解析（无依赖）
        if ext == 'wav':
            try:
                with wave.open(file_path, 'rb') as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    if rate > 0:
                        return frames / rate
            except Exception:
                pass

        # mutagen（轻量，支持 mp3/flac/ogg 等）
        try:
            import mutagen
            audio = mutagen.File(file_path)
            if audio is not None and audio.info is not None:
                return audio.info.length
        except ImportError:
            pass
        except Exception:
            pass

        # pydub（需要 ffmpeg）
        try:
            from pydub import AudioSegment
            seg = AudioSegment.from_file(file_path)
            return len(seg) / 1000.0
        except ImportError:
            pass
        except Exception:
            pass

        return None

    # ------------------------------------------------------------------
    # 百度云 VOP API
    # ------------------------------------------------------------------
    def _try_baidu_speech(self, file_path: str, mime_type: str) -> Optional[str]:
        """
        调用百度云语音识别 pro_api。

        Returns:
            识别文字（字符串）；None 表示不可用或失败。
        """
        from config.api_keys_manager import APIKeyManager

        config = APIKeyManager.get_speech_service_config('baidu')
        if not config:
            logger.debug("[Speech-百度] 未启用或未配置，跳过")
            return None

        api_key = config.get('api_key', '')
        secret_key = config.get('secret_key', '')
        auth_type = config.get('auth_type', 'oauth2')

        if auth_type == 'oauth2' and (not api_key or not secret_key):
            logger.warning("[Speech-百度] api_key 或 secret_key 为空，跳过")
            return None

        if auth_type == 'bearer' and not config.get('bearer_token', ''):
            logger.warning("[Speech-百度] bearer_token 为空，跳过")
            return None

        try:
            import requests as req_lib

            # 1. 准备 PCM/WAV 数据（可能需要格式转换）
            audio_bytes, fmt, rate, channels = self._prepare_audio_for_baidu(
                file_path, mime_type
            )
            if audio_bytes is None:
                logger.warning("[Speech-百度] 音频格式转换失败，跳过百度识别")
                return None

            # 2. 编码为 Base64
            speech_b64 = base64.b64encode(audio_bytes).decode('utf-8')

            # 3. 构建认证头及 token 字段
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            }
            token_field = ""

            if auth_type == 'bearer':
                headers['Authorization'] = f"Bearer {config['bearer_token']}"
            else:
                # OAuth2：获取 access_token
                access_token = self._get_baidu_access_token(config)
                if not access_token:
                    return None
                token_field = access_token

            # 4. 组装请求体
            import socket
            cuid = config.get('cuid', socket.gethostname()[:32] or 'UniScheduler')
            api_url = config.get('api_url', 'https://vop.baidu.com/pro_api')
            dev_pid = config.get('dev_pid', 80001)  # 80001 = 普通话+英语（云端增强版）

            payload = {
                "format": fmt,
                "rate": rate,
                "channel": channels,
                "cuid": cuid,
                "token": token_field,
                "dev_pid": dev_pid,
                "speech": speech_b64,
                "len": len(audio_bytes),
            }

            resp = req_lib.post(
                api_url,
                headers=headers,
                json=payload,
                timeout=30,
            )
            resp.encoding = 'utf-8'
            data = resp.json()

            # 5. 解析结果
            err_no = data.get('err_no', -1)
            if err_no != 0:
                err_msg = data.get('err_msg', '')
                logger.warning(f"[Speech-百度] API 错误 err_no={err_no}: {err_msg}")
                # token 过期时清除缓存
                if err_no in (3303, 3307):
                    AudioParser._baidu_access_token = ""
                    AudioParser._baidu_token_expires_at = 0.0
                return None

            results = data.get('result', [])
            text = ''.join(results)
            logger.debug(f"[Speech-百度] 成功: sn={data.get('sn', 'N/A')}, {len(text)} 字符")
            return text.strip()

        except req_lib.exceptions.Timeout:
            logger.warning("[Speech-百度] 请求超时 (30s)，将尝试本地引擎")
            return None
        except req_lib.exceptions.ConnectionError:
            logger.warning("[Speech-百度] 网络连接失败，将尝试本地引擎")
            return None
        except Exception as e:
            logger.warning(f"[Speech-百度] 异常: {e}，将尝试本地引擎")
            return None

    def _get_baidu_access_token(self, config: dict) -> str:
        """获取百度 OAuth2 access_token（带类级缓存）"""
        import time

        if (AudioParser._baidu_access_token
                and time.time() < AudioParser._baidu_token_expires_at - 300):
            return AudioParser._baidu_access_token

        try:
            import requests as req_lib

            token_url = config.get(
                'token_url',
                'https://aip.baidubce.com/oauth/2.0/token'
            )
            params = {
                "grant_type": "client_credentials",
                "client_id": config['api_key'],
                "client_secret": config['secret_key'],
            }
            resp = req_lib.post(token_url, params=params, timeout=10)
            data = resp.json()
            token = data.get('access_token', '')
            expires_in = data.get('expires_in', 0)

            if not token:
                error = data.get('error_description', data.get('error', '未知错误'))
                logger.warning(f"[Speech-百度] 获取 access_token 失败: {error}")
                return ""

            AudioParser._baidu_access_token = token
            AudioParser._baidu_token_expires_at = time.time() + expires_in
            logger.info(f"[Speech-百度] access_token 获取成功，有效期 {expires_in // 86400} 天")
            return token

        except Exception as e:
            logger.warning(f"[Speech-百度] 获取 access_token 异常: {e}")
            return ""

    def _prepare_audio_for_baidu(
        self, file_path: str, mime_type: str
    ) -> Tuple[Optional[bytes], str, int, int]:
        """
        将音频准备为百度 VOP 可接受的 PCM/WAV（16000Hz，单声道）形式。

        Returns:
            (audio_bytes, format_str, sample_rate, channels)
            若转换失败则返回 (None, '', 0, 0)
        """
        ext = _MIME_TO_EXT.get(mime_type.lower(), '').lower() \
              or os.path.splitext(file_path)[1].lower().lstrip('.')

        # ——— WAV 原生路径 ———
        if ext == 'wav':
            try:
                with wave.open(file_path, 'rb') as wf:
                    rate = wf.getframerate()
                    channels = wf.getnchannels()
                    sampwidth = wf.getsampwidth()
                    frames = wf.readframes(wf.getnframes())

                    # 正好符合要求：直接读取 PCM 数据
                    if rate == 16000 and channels == 1 and sampwidth == 2:
                        return frames, 'pcm', 16000, 1

                    # 需要转换 → 尝试 pydub
                    logger.debug(
                        f"[Speech-百度] WAV 参数不符 (rate={rate}, ch={channels})，尝试转换"
                    )
            except Exception as e:
                logger.debug(f"[Speech-百度] wave 读取失败: {e}，尝试 pydub")

        # ——— pydub 转换路径 ———
        try:
            from pydub import AudioSegment
            import io

            if ext in ('wav', 'pcm'):
                seg = AudioSegment.from_wav(file_path)
            elif ext == 'mp3':
                seg = AudioSegment.from_mp3(file_path)
            elif ext == 'ogg':
                seg = AudioSegment.from_ogg(file_path)
            elif ext == 'flac':
                seg = AudioSegment.from_file(file_path, format='flac')
            else:
                seg = AudioSegment.from_file(file_path)

            # 转为 16000Hz 单声道 16-bit PCM
            seg = seg.set_frame_rate(16000).set_channels(1).set_sample_width(2)
            pcm_data = seg.raw_data
            logger.debug(f"[Speech-百度] pydub 转换成功，PCM {len(pcm_data)} bytes")
            return pcm_data, 'pcm', 16000, 1

        except ImportError:
            logger.debug("[Speech-百度] pydub 未安装，仅支持标准 WAV 文件")
        except Exception as e:
            logger.warning(f"[Speech-百度] pydub 转换失败: {e}")

        # ——— 最终检查：对于无法转换的格式直接拒绝 ———
        if ext not in _BAIDU_NATIVE_FORMATS:
            logger.warning(
                f"[Speech-百度] 格式 '{ext}' 不受百度 VOP 原生支持，且无法转换（请安装 pydub+ffmpeg）"
            )
            return None, '', 0, 0

        # WAV 但读取失败 → 原样发送（让 API 自己判断）
        try:
            with open(file_path, 'rb') as f:
                raw = f.read()
            return raw, 'wav', 16000, 1
        except Exception as e:
            logger.warning(f"[Speech-百度] 读取文件失败: {e}")
            return None, '', 0, 0

    # ------------------------------------------------------------------
    # 本地兜底：faster-whisper（tiny 模型，轻量级）
    # ------------------------------------------------------------------
    def _try_faster_whisper(self, file_path: str, mime_type: str = '') -> Optional[str]:
        """
        使用 faster-whisper tiny 模型本地识别。

        模型首次加载约 200MB 下载量，之后缓存在本地。
        Returns:
            识别文字；None 表示引擎不可用。
        """
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            logger.debug("[Speech-Whisper] faster-whisper 未安装，跳过本地识别")
            return None

        try:
            if AudioParser._whisper_model is None:
                logger.info("[Speech-Whisper] 首次加载 tiny 模型（约 72MB）...")
                AudioParser._whisper_model = WhisperModel(
                    "tiny",
                    device="cpu",
                    compute_type="int8",    # 最小内存占用
                )
                logger.info("[Speech-Whisper] 模型加载完成")

            segments, info = AudioParser._whisper_model.transcribe(
                file_path,
                beam_size=5,
                language="zh",            # 指定中文，提高精度
                vad_filter=True,          # 过滤静音段
            )
            text = ''.join(seg.text for seg in segments)
            logger.debug(
                f"[Speech-Whisper] 识别完成: lang={info.language}, "
                f"prob={info.language_probability:.2f}, {len(text)} 字符"
            )
            return text.strip()

        except Exception as e:
            logger.warning(f"[Speech-Whisper] 识别失败: {e}")
            return None
