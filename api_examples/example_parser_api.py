"""
解析器 API 使用示例
展示如何调用对外开放的文件解析接口

当前已开放的解析接口：
- POST /api/agent/speech-to-text/   语音转文字（无需认证）

计划中的接口（尚未开放）：
- POST /api/agent/parse/image/      图片 OCR 提取文字
- POST /api/agent/parse/document/   文档解析为 Markdown（PDF/Word/Excel）

语音转文字的降级链：
  百度云 VOP（pro_api）→ faster-whisper tiny（本地）

音频格式支持：
  wav、mp3、ogg、flac、webm、aac、m4a、amr

限制：
  - 单文件最大 15 MB
  - 音频时长最长 60 秒

前置条件：
    1. Django 服务已启动
    2. （可选）在 config/api_keys.json 中启用百度云语音服务获得更好精度

使用方法：
    python api_examples/example_parser_api.py
    python api_examples/example_parser_api.py --audio path/to/file.wav
"""

import sys
import os
import requests
import json
import wave
import struct
import math
import argparse
import tempfile

# ==================== 配置区 ====================
BASE_URL = "http://127.0.0.1:8000"
SPEECH_API = f"{BASE_URL}/api/agent/speech-to-text/"


# ==================== 终端颜色 ====================

class Colors:
    HEADER  = '\033[95m'
    OKBLUE  = '\033[94m'
    OKCYAN  = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL    = '\033[91m'
    ENDC    = '\033[0m'
    BOLD    = '\033[1m'


def print_success(msg): print(f"{Colors.OKGREEN}✅ {msg}{Colors.ENDC}")
def print_error(msg):   print(f"{Colors.FAIL}❌ {msg}{Colors.ENDC}")
def print_warning(msg): print(f"{Colors.WARNING}⚠️  {msg}{Colors.ENDC}")
def print_info(msg):    print(f"{Colors.OKCYAN}ℹ️  {msg}{Colors.ENDC}")


def print_header(msg):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{msg:^60}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}\n")


def print_response(data: dict):
    """格式化打印响应"""
    print(json.dumps(data, ensure_ascii=False, indent=2))


# ==================== 本地音频生成工具 ====================

def _write_wav(path: str, duration_sec: float, freq: float = 440.0,
               sample_rate: int = 16000, amplitude: int = 8000):
    """
    生成一个纯正弦波 WAV 文件（用于离线测试，不含真实语音）。

    Args:
        path:        输出路径
        duration_sec: 时长（秒）
        freq:        正弦波频率（Hz），默认 440 Hz（A4音）
        sample_rate: 采样率，百度 VOP 要求 16000
        amplitude:   振幅（0~32767）
    """
    n_samples = int(sample_rate * duration_sec)
    with wave.open(path, 'w') as wf:
        wf.setnchannels(1)           # 单声道
        wf.setsampwidth(2)           # 16-bit
        wf.setframerate(sample_rate)
        samples = [
            int(amplitude * math.sin(2 * math.pi * freq * i / sample_rate))
            for i in range(n_samples)
        ]
        wf.writeframes(struct.pack(f'<{n_samples}h', *samples))


def make_test_wav(duration_sec: float = 3.0, label: str = 'test') -> str:
    """生成测试用 WAV 文件，返回临时文件路径"""
    tmp = tempfile.NamedTemporaryFile(
        suffix='.wav', delete=False, prefix=f'parser_test_{label}_'
    )
    tmp.close()
    _write_wav(tmp.name, duration_sec)
    print_info(f"生成测试 WAV: {os.path.basename(tmp.name)}，时长={duration_sec}s")
    return tmp.name


def cleanup(*paths):
    """删除临时文件"""
    for p in paths:
        if p and os.path.exists(p):
            try:
                os.unlink(p)
            except Exception:
                pass


# ==================== 语音转文字 API 示例 ====================

def example_speech_to_text_basic(audio_path: str):
    """
    示例 1: 基础用法 —— 上传音频文件，获取识别文字

    API: POST /api/agent/speech-to-text/
    认证: 无需（公开接口）

    注意：测试使用纯正弦波，识别结果将为空或乱码，属正常现象。
          实际使用请传入包含真实语音的音频文件。
    """
    print_header("示例 1: 基础语音转文字")

    if not os.path.exists(audio_path):
        print_error(f"文件不存在: {audio_path}")
        return

    file_size = os.path.getsize(audio_path) / 1024
    print_info(f"上传文件: {os.path.basename(audio_path)}（{file_size:.1f} KB）")

    with open(audio_path, 'rb') as f:
        response = requests.post(
            SPEECH_API,
            files={'audio': (os.path.basename(audio_path), f, 'audio/wav')},
            timeout=60,
        )

    print_info(f"HTTP 状态码: {response.status_code}")
    data = response.json()
    print_response(data)

    if data.get('success'):
        text = data.get('text', '')
        provider = data.get('provider', '')
        duration = data.get('duration_seconds')
        print_success(
            f"识别成功 | 引擎={provider} | "
            f"时长={f'{duration:.1f}s' if duration else '未知'} | "
            f"文字长度={len(text)} 字符"
        )
        if text:
            print(f"\n  识别结果: {Colors.BOLD}{text}{Colors.ENDC}\n")
        else:
            print_warning("识别结果为空（正弦波测试文件属正常现象）")
    else:
        print_error(f"识别失败: {data.get('error')}")

    return data


def example_speech_to_text_real(audio_path: str):
    """
    示例 2: 使用真实音频文件识别

    API: POST /api/agent/speech-to-text/
    用法: 传入包含人声的音频文件（wav/mp3 均可）
    """
    print_header("示例 2: 真实音频文件识别")

    if not os.path.exists(audio_path):
        print_error(f"文件不存在: {audio_path}")
        print_info("跳过本示例，请通过 --audio 参数指定真实音频文件路径")
        return None

    file_size_kb = os.path.getsize(audio_path) / 1024
    ext = os.path.splitext(audio_path)[1].lower()
    mime_map = {
        '.wav': 'audio/wav', '.mp3': 'audio/mpeg',
        '.ogg': 'audio/ogg', '.flac': 'audio/flac',
        '.webm': 'audio/webm', '.aac': 'audio/aac',
        '.m4a': 'audio/m4a', '.amr': 'audio/amr',
    }
    mime = mime_map.get(ext, 'audio/wav')

    print_info(f"文件: {os.path.basename(audio_path)}")
    print_info(f"大小: {file_size_kb:.1f} KB")
    print_info(f"MIME: {mime}")

    with open(audio_path, 'rb') as f:
        response = requests.post(
            SPEECH_API,
            files={'audio': (os.path.basename(audio_path), f, mime)},
            timeout=60,
        )

    print_info(f"HTTP 状态码: {response.status_code}")
    data = response.json()

    if data.get('success'):
        text = data.get('text', '')
        provider = data.get('provider', '')
        duration = data.get('duration_seconds')
        print_success(
            f"识别成功 | 引擎={provider} | "
            f"时长={f'{duration:.1f}s' if duration else '未知'}"
        )
        print(f"\n  {Colors.BOLD}识别结果：{Colors.ENDC}")
        print(f"  {text}\n")
    else:
        print_error(f"识别失败: {data.get('error')}")

    return data


def example_speech_no_auth_check():
    """
    示例 3: 验证接口无需认证

    该接口是公开接口，无需 Token，直接调用即可。
    """
    print_header("示例 3: 公开接口（无需认证）验证")

    # 创建一个极短的 WAV 文件
    wav_path = make_test_wav(duration_sec=1.0, label='noauth')
    try:
        with open(wav_path, 'rb') as f:
            # 不携带任何 Authorization 头
            response = requests.post(
                SPEECH_API,
                files={'audio': ('test.wav', f, 'audio/wav')},
                timeout=30,
            )

        if response.status_code in (200, 422):
            print_success(f"接口无需认证，返回 {response.status_code}（200=成功/422=识别结果为空均正常）")
        elif response.status_code == 401:
            print_error("接口意外需要认证（请检查 views_speech.py 中的 permission_classes）")
        else:
            print_info(f"HTTP {response.status_code}: {response.text[:200]}")
    finally:
        cleanup(wav_path)


def example_speech_duration_limit():
    """
    示例 4: 时长限制测试 —— 超过 60 秒应返回 422 错误

    API 限制: 音频时长 ≤ 60s
    """
    print_header("示例 4: 时长限制（> 60s 应被拒绝）")

    wav_path = make_test_wav(duration_sec=65.0, label='toolong')
    print_info("已生成 65s 测试 WAV，预期返回 422 Unprocessable Entity...")

    try:
        with open(wav_path, 'rb') as f:
            response = requests.post(
                SPEECH_API,
                files={'audio': ('too_long.wav', f, 'audio/wav')},
                timeout=30,
            )

        print_info(f"HTTP 状态码: {response.status_code}")
        data = response.json()

        if response.status_code == 422 and not data.get('success'):
            print_success(f"正确拒绝了超长音频: {data.get('error')}")
        elif response.status_code == 200:
            print_warning("服务器未拦截超长音频（可能时长检测不精确，属于可接受行为）")
        else:
            print_info(f"响应: {json.dumps(data, ensure_ascii=False)}")
    finally:
        cleanup(wav_path)


def example_speech_unsupported_format():
    """
    示例 5: 不支持的文件格式应返回 400 错误

    API 只接受: wav/mp3/ogg/flac/webm/aac/m4a/amr
    """
    print_header("示例 5: 不支持的格式（应返回 400）")

    # 伪造一个 .txt 文件以错误的 MIME 提交
    tmp = tempfile.NamedTemporaryFile(suffix='.txt', delete=False, prefix='parser_test_bad_')
    tmp.write(b'this is not audio')
    tmp.close()

    print_info("上传 text/plain 文件（预期返回 400）...")

    try:
        with open(tmp.name, 'rb') as f:
            response = requests.post(
                SPEECH_API,
                files={'audio': ('test.txt', f, 'text/plain')},
                timeout=15,
            )

        print_info(f"HTTP 状态码: {response.status_code}")
        data = response.json()

        if response.status_code == 400 and not data.get('success'):
            print_success(f"正确拒绝了无效格式: {data.get('error')}")
        else:
            print_warning(f"响应: {json.dumps(data, ensure_ascii=False)}")
    finally:
        cleanup(tmp.name)


def example_speech_missing_field():
    """
    示例 6: 缺少 audio 字段应返回 400 错误
    """
    print_header("示例 6: 缺少 audio 字段（应返回 400）")

    print_info("发送空表单（无 audio 字段）...")
    response = requests.post(SPEECH_API, data={}, timeout=10)

    print_info(f"HTTP 状态码: {response.status_code}")
    data = response.json()

    if response.status_code == 400 and not data.get('success'):
        print_success(f"正确返回错误: {data.get('error')}")
    else:
        print_warning(f"响应: {json.dumps(data, ensure_ascii=False)}")


# ==================== 主函数 ====================

def main():
    parser = argparse.ArgumentParser(
        description='解析器 API 示例脚本（语音转文字）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 运行所有测试（使用合成音频）
  python api_examples/example_parser_api.py

  # 使用真实音频运行
  python api_examples/example_parser_api.py --audio path/to/recording.wav

  # 只测试真实音频，跳过合成音频测试
  python api_examples/example_parser_api.py --audio path/to/recording.wav --only-real
        """
    )
    parser.add_argument('--audio', metavar='PATH',
                        help='真实音频文件路径（wav/mp3/ogg/flac 等）')
    parser.add_argument('--only-real', action='store_true',
                        help='仅测试真实音频，跳过合成音频示例')
    args = parser.parse_args()

    # 标题
    print(f"{Colors.HEADER}{Colors.BOLD}")
    print("=" * 60)
    print("解析器 API 测试脚本".center(60))
    print("（当前功能：语音转文字）".center(60))
    print("=" * 60)
    print(f"{Colors.ENDC}")

    print_info(f"目标服务: {BASE_URL}")
    print_info("语音转文字接口无需认证，可直接调用")

    if args.only_real:
        if not args.audio:
            print_error("--only-real 需要同时指定 --audio 参数")
            sys.exit(1)
        example_speech_to_text_real(args.audio)
        return

    # —— 合成音频基础示例 ——
    wav_path = make_test_wav(duration_sec=3.0, label='basic')
    try:
        example_speech_to_text_basic(wav_path)
    finally:
        cleanup(wav_path)

    # —— 真实音频示例 ——
    if args.audio:
        example_speech_to_text_real(args.audio)
    else:
        print_header("示例 2: 真实音频文件识别（已跳过）")
        print_info("请通过 --audio <path> 参数指定真实音频文件来运行此示例")
        print_info("支持格式：wav / mp3 / ogg / flac / webm / aac / m4a / amr")

    # —— 验证测试 ——
    example_speech_no_auth_check()
    example_speech_duration_limit()
    example_speech_unsupported_format()
    example_speech_missing_field()

    print_header("测试完成")
    print_success("所有示例已运行完毕！")
    print()
    print_info("提示：")
    print("  • 合成正弦波音频识别结果为空属正常（无真实语音内容）")
    print("  • 使用 --audio 参数传入真实录音文件以获得实际识别结果")
    print("  • 在 config/api_keys.json 中启用百度云语音可获得更高精度")


if __name__ == "__main__":
    main()
