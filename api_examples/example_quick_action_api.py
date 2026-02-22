"""
Quick Action API 使用示例
展示如何使用 Token 认证调用 Quick Action 快速操作 API

Quick Action 是一个快速操作执行器，可以通过一句话完成日程管理任务，
无需多轮对话，适合移动端、快捷方式等场景。

输入方式（二选一）：
  方式一：JSON Body 文本输入
    Content-Type: application/json
    { "text": "明天下午3点开会", "sync": false }

  方式二：multipart/form-data 语音输入
    字段：audio=<音频文件>，支持 wav/mp3/ogg/flac/webm/aac/m4a/amr，≤ 60s
    服务端自动将音频识别为文字后执行操作
    两种方式不可同时提供，否则返回 400。

API 端点：
- POST   /api/agent/quick-action/           - 创建快速操作任务（文本/语音，同步/异步）
- GET    /api/agent/quick-action/<uuid>/    - 查询任务状态（支持长轮询）
- GET    /api/agent/quick-action/list/      - 获取历史任务列表
- DELETE /api/agent/quick-action/<uuid>/cancel/ - 取消待执行任务

独立语音转文字接口（无需认证）：
- POST   /api/agent/speech-to-text/         - 仅做语音识别，不触发操作
  详见 api_examples/example_parser_api.py

前置条件：
1. Django 服务已启动：python manage.py runserver
2. 已有用户账号（需配置 LLM）
3. 已执行数据库迁移：python manage.py migrate

使用方法：
    python api_examples/example_quick_action_api.py
    python api_examples/example_quick_action_api.py --audio path/to/file.wav
"""

import requests
import json
import time
import os
import wave
import struct
import math
import tempfile
import argparse
from datetime import datetime

# ==================== 配置区 ====================
BASE_URL = "http://127.0.0.1:8000"
USERNAME = "MoMoJee"  # 修改为你的用户名
PASSWORD = "xxxxxx"  # 修改为你的密码

# ==================== 辅助函数 ====================

class Colors:
    """终端颜色"""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def print_success(message):
    print(f"{Colors.OKGREEN}✅ {message}{Colors.ENDC}")


def print_error(message):
    print(f"{Colors.FAIL}❌ {message}{Colors.ENDC}")


def print_warning(message):
    print(f"{Colors.WARNING}⚠️  {message}{Colors.ENDC}")


def print_info(message):
    print(f"{Colors.OKCYAN}ℹ️  {message}{Colors.ENDC}")


def print_header(message):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{message:^60}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}\n")


def get_auth_token(username=USERNAME, password=PASSWORD):
    """获取认证 Token"""
    print_header("获取认证 Token")
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/auth/login/",
            json={"username": username, "password": password}
        )
        
        if response.status_code == 200:
            token = response.json().get('token')
            print_success(f"Token 获取成功")
            return token
        else:
            print_error(f"登录失败 (状态码: {response.status_code})")
            print(f"响应: {response.text}")
            return None
    except Exception as e:
        print_error(f"请求失败: {e}")
        return None


def get_headers(token):
    """生成请求头"""
    return {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json"
    }


def format_result(result_data):
    """格式化输出结果"""
    if not result_data:
        return
    
    result_type = result_data.get('type', '')
    message = result_data.get('message', '')
    
    if result_type == 'action_completed':
        print_success(f"操作成功: {message}")
    elif result_type == 'need_clarification':
        print_warning(f"需要补充信息:\n{message}")
    elif result_type == 'error':
        print_error(f"操作失败: {message}")
    else:
        print_info(f"结果: {message}")
    
    # 显示工具调用记录
    tool_calls = result_data.get('tool_calls', [])
    if tool_calls:
        print(f"\n  工具调用记录 ({len(tool_calls)} 次):")
        for i, call in enumerate(tool_calls, 1):
            status = "✓" if call.get('status') == 'success' else "✗"
            print(f"    {i}. {status} {call.get('tool')} - {call.get('result', '')[:50]}...")


# ==================== 音频辅助工具 ====================

def _write_test_wav(path: str, duration_sec: float = 3.0,
                   freq: float = 440.0, sample_rate: int = 16000):
    """生成纯正弦波 WAV 文件（用于接口测试，不含真实语音）"""
    n = int(sample_rate * duration_sec)
    with wave.open(path, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        samples = [int(8000 * math.sin(2 * math.pi * freq * i / sample_rate))
                   for i in range(n)]
        wf.writeframes(struct.pack(f'<{n}h', *samples))


def make_test_wav(duration_sec: float = 3.0) -> str:
    """生成临时测试 WAV，返回路径"""
    tmp = tempfile.NamedTemporaryFile(
        suffix='.wav', delete=False, prefix='qa_test_wave_'
    )
    tmp.close()
    _write_test_wav(tmp.name, duration_sec)
    return tmp.name


# ==================== Quick Action API 示例 ====================

def example_create_quick_action_async(token):
    """
    示例 1: 创建快速操作（异步模式）
    
    POST /api/agent/quick-action/
    """
    print_header("示例 1: 创建快速操作（异步模式）")
    
    # 测试用例：创建明天的会议
    payload = {
        "text": "明天下午3点开会，讨论项目进度",
        "sync": False  # 异步模式
    }
    
    print_info(f"请求内容: {payload['text']}")
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/agent/quick-action/",
            headers=get_headers(token),
            json=payload
        )
        
        if response.status_code == 201:
            data = response.json()
            task_id = data.get('task_id')
            print_success(f"任务创建成功")
            print(f"  任务 ID: {task_id}")
            print(f"  状态: {data.get('status')}")
            print(f"  创建时间: {data.get('created_at')}")
            return task_id
        else:
            print_error(f"请求失败 (状态码: {response.status_code})")
            print(f"响应: {response.text}")
            return None
    except Exception as e:
        print_error(f"请求失败: {e}")
        return None


def example_create_quick_action_sync(token):
    """
    示例 2: 创建快速操作（同步模式）
    
    POST /api/agent/quick-action/
    """
    print_header("示例 2: 创建快速操作（同步模式）")
    
    # 测试用例：完成待办
    payload = {
        "text": "完成今天的代码评审任务",
        "sync": True,  # 同步模式
        "timeout": 30
    }
    
    print_info(f"请求内容: {payload['text']}")
    print_info("同步模式：将等待任务执行完成...")
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/agent/quick-action/",
            headers=get_headers(token),
            json=payload
        )
        
        if response.status_code == 200:
            data = response.json()
            print_success(f"任务执行完成")
            print(f"  任务 ID: {data.get('task_id')}")
            print(f"  状态: {data.get('status')}")
            print(f"  执行时间: {data.get('execution_time_ms')} ms")
            
            # 显示结果
            if data.get('result'):
                print("\n  执行结果:")
                format_result(data.get('result'))
            
            # 显示 Token 消耗
            tokens = data.get('tokens', {})
            if tokens:
                print(f"\n  Token 消耗:")
                print(f"    输入: {tokens.get('input')}")
                print(f"    输出: {tokens.get('output')}")
                print(f"    成本: {tokens.get('cost')} CNY")
                print(f"    模型: {tokens.get('model')}")
            
            return data.get('task_id')
        else:
            print_error(f"请求失败 (状态码: {response.status_code})")
            print(f"响应: {response.text}")
            return None
    except Exception as e:
        print_error(f"请求失败: {e}")
        return None


def example_get_task_status(token, task_id):
    """
    示例 3: 查询任务状态
    
    GET /api/agent/quick-action/<task_id>/
    """
    print_header("示例 3: 查询任务状态")
    
    if not task_id:
        print_error("任务 ID 为空，跳过测试")
        return
    
    print_info(f"查询任务: {task_id}")
    
    try:
        response = requests.get(
            f"{BASE_URL}/api/agent/quick-action/{task_id}/",
            headers=get_headers(token)
        )
        
        if response.status_code == 200:
            data = response.json()
            status = data.get('status')
            
            print_success(f"任务状态: {status}")
            print(f"  输入文本: {data.get('input_text')}")
            print(f"  创建时间: {data.get('created_at')}")
            
            if data.get('started_at'):
                print(f"  开始时间: {data.get('started_at')}")
            
            if data.get('completed_at'):
                print(f"  完成时间: {data.get('completed_at')}")
                print(f"  执行时长: {data.get('duration', 0):.2f} 秒")
            
            # 如果任务完成，显示结果
            if status in ['success', 'failed'] and data.get('result'):
                print("\n  执行结果:")
                format_result(data.get('result'))
            
            return data
        else:
            print_error(f"请求失败 (状态码: {response.status_code})")
            print(f"响应: {response.text}")
            return None
    except Exception as e:
        print_error(f"请求失败: {e}")
        return None


def example_long_polling(token, task_id):
    """
    示例 4: 长轮询查询任务状态
    
    GET /api/agent/quick-action/<task_id>/?wait=true
    """
    print_header("示例 4: 长轮询查询任务状态")
    
    if not task_id:
        print_error("任务 ID 为空，跳过测试")
        return
    
    print_info(f"长轮询任务: {task_id}")
    print_info("等待任务完成（最多30秒）...")
    
    try:
        start_time = time.time()
        response = requests.get(
            f"{BASE_URL}/api/agent/quick-action/{task_id}/?wait=true",
            headers=get_headers(token),
            timeout=35  # 稍微大于服务器的30秒超时
        )
        wait_time = time.time() - start_time
        
        if response.status_code == 200:
            data = response.json()
            status = data.get('status')
            
            print_success(f"任务状态: {status} (等待了 {wait_time:.2f} 秒)")
            
            if status in ['success', 'failed']:
                if data.get('result'):
                    print("\n  执行结果:")
                    format_result(data.get('result'))
            elif status in ['pending', 'processing']:
                print_warning("任务仍在执行中，需要继续等待")
            
            return data
        else:
            print_error(f"请求失败 (状态码: {response.status_code})")
            return None
    except requests.Timeout:
        print_warning("请求超时（任务可能需要更长时间执行）")
        return None
    except Exception as e:
        print_error(f"请求失败: {e}")
        return None


def example_list_quick_actions(token):
    """
    示例 5: 获取历史任务列表
    
    GET /api/agent/quick-action/list/
    """
    print_header("示例 5: 获取历史任务列表")
    
    try:
        response = requests.get(
            f"{BASE_URL}/api/agent/quick-action/list/?limit=5",
            headers=get_headers(token)
        )
        
        if response.status_code == 200:
            data = response.json()
            tasks = data.get('tasks', [])
            count = data.get('count', 0)
            
            print_success(f"获取成功 (共 {count} 个任务，显示最近 {len(tasks)} 个)")
            
            if tasks:
                print("\n  最近的任务:")
                for i, task in enumerate(tasks, 1):
                    status_icon = {
                        'pending': '⏳',
                        'processing': '🔄',
                        'success': '✅',
                        'failed': '❌',
                        'timeout': '⏱️'
                    }.get(task.get('status'), '❓')
                    
                    print(f"\n  {i}. {status_icon} {task.get('status').upper()}")
                    print(f"     任务ID: {task.get('task_id')}")
                    print(f"     输入: {task.get('input_text')}")
                    print(f"     创建时间: {task.get('created_at')}")
                    
                    if task.get('result_preview'):
                        print(f"     结果预览: {task.get('result_preview')[:100]}...")
                    
                    if task.get('execution_time_ms'):
                        print(f"     执行时间: {task.get('execution_time_ms')} ms")
            else:
                print_info("暂无历史任务")
            
            return tasks
        else:
            print_error(f"请求失败 (状态码: {response.status_code})")
            print(f"响应: {response.text}")
            return None
    except Exception as e:
        print_error(f"请求失败: {e}")
        return None


def example_cancel_task(token, task_id):
    """
    示例 6: 取消待执行任务
    
    DELETE /api/agent/quick-action/<task_id>/cancel/
    """
    print_header("示例 6: 取消待执行任务")
    
    if not task_id:
        print_error("任务 ID 为空，跳过测试")
        return
    
    print_info(f"取消任务: {task_id}")
    
    try:
        response = requests.delete(
            f"{BASE_URL}/api/agent/quick-action/{task_id}/cancel/",
            headers=get_headers(token)
        )
        
        if response.status_code == 200:
            data = response.json()
            print_success(f"任务已取消: {data.get('message')}")
            return True
        elif response.status_code == 400:
            data = response.json()
            print_warning(f"无法取消: {data.get('error')}")
            return False
        elif response.status_code == 404:
            print_error("任务不存在")
            return False
        else:
            print_error(f"请求失败 (状态码: {response.status_code})")
            print(f"响应: {response.text}")
            return False
    except Exception as e:
        print_error(f"请求失败: {e}")
        return False


def example_create_quick_action_audio_async(token, audio_path: str = None):
    """
    示例 7: 语音输入 —— 异步模式

    POST /api/agent/quick-action/
    Content-Type: multipart/form-data
    字段: audio=<音频文件>

    服务端流程：
      1. 接收音频，调用语音识别（百度云 VOP / faster-whisper 本地兜底）
      2. 将识别文字作为指令传给 Quick Action Agent
      3. Agent 执行操作，返回结果

    注意：测试使用合成正弦波，识别结果将为空/乱码，Agent 会报错，属于预期行为。
          实际使用请传入包含真实日程指令的音频。
    """
    print_header("示例 7: 语音输入 Quick Action（异步模式）")

    # 如果没有真实音频，生成一个合成 WAV 用于接口联调
    generated = False
    if not audio_path or not os.path.exists(audio_path):
        audio_path = make_test_wav(duration_sec=3.0)
        generated = True
        print_warning("未提供真实音频，使用合成正弦波（识别结果将为空）")
    else:
        print_info(f"使用真实音频: {os.path.basename(audio_path)}")

    try:
        file_size_kb = os.path.getsize(audio_path) / 1024
        print_info(f"文件大小: {file_size_kb:.1f} KB")

        ext = os.path.splitext(audio_path)[1].lower()
        mime_map = {
            '.wav': 'audio/wav', '.mp3': 'audio/mpeg',
            '.ogg': 'audio/ogg', '.flac': 'audio/flac',
            '.webm': 'audio/webm', '.aac': 'audio/aac',
            '.m4a': 'audio/m4a', '.amr': 'audio/amr',
        }
        mime = mime_map.get(ext, 'audio/wav')

        token_headers = {"Authorization": f"Token {token}"}

        with open(audio_path, 'rb') as f:
            response = requests.post(
                f"{BASE_URL}/api/agent/quick-action/",
                headers=token_headers,
                files={'audio': (os.path.basename(audio_path), f, mime)},
                data={'sync': 'false'},
                timeout=60,
            )

        print_info(f"HTTP 状态码: {response.status_code}")

        if response.status_code == 201:
            data = response.json()
            task_id = data.get('task_id')
            input_type = data.get('input_type', 'unknown')
            print_success(f"任务创建成功（input_type={input_type}）")
            print(f"  任务 ID: {task_id}")
            print(f"  状态: {data.get('status')}")
            print(f"  输入类型: {input_type}")
            return task_id
        elif response.status_code == 422:
            data = response.json()
            print_warning(f"语音识别失败（预期行为，合成音频无语音内容）: {data.get('error')}")
            return None
        else:
            print_error(f"请求失败 (状态码: {response.status_code})")
            print(f"响应: {response.text}")
            return None
    except Exception as e:
        print_error(f"请求失败: {e}")
        return None
    finally:
        if generated and audio_path and os.path.exists(audio_path):
            os.unlink(audio_path)


def example_create_quick_action_audio_sync(token, audio_path: str = None):
    """
    示例 8: 语音输入 —— 同步模式

    POST /api/agent/quick-action/
    Content-Type: multipart/form-data
    字段: audio=<音频文件>, sync=true

    同步模式下请求会阻塞直到任务完成（或超时），适合对延迟不敏感的场景。
    """
    print_header("示例 8: 语音输入 Quick Action（同步模式）")

    if not audio_path or not os.path.exists(audio_path):
        print_warning("未提供真实音频，跳过同步语音示例")
        print_info("请通过 --audio 参数指定包含日程指令的真实音频文件")
        print_info("示例指令：'明天下午三点开会，讨论项目进度'")
        return None

    print_info(f"使用真实音频: {os.path.basename(audio_path)}")
    print_info("同步模式：等待语音识别 + Agent 执行完成...")

    ext = os.path.splitext(audio_path)[1].lower()
    mime_map = {
        '.wav': 'audio/wav', '.mp3': 'audio/mpeg',
        '.ogg': 'audio/ogg', '.flac': 'audio/flac',
        '.webm': 'audio/webm', '.aac': 'audio/aac',
        '.m4a': 'audio/m4a', '.amr': 'audio/amr',
    }
    mime = mime_map.get(ext, 'audio/wav')
    token_headers = {"Authorization": f"Token {token}"}

    try:
        with open(audio_path, 'rb') as f:
            response = requests.post(
                f"{BASE_URL}/api/agent/quick-action/",
                headers=token_headers,
                files={'audio': (os.path.basename(audio_path), f, mime)},
                data={'sync': 'true', 'timeout': '30'},
                timeout=40,
            )

        print_info(f"HTTP 状态码: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print_success(f"任务执行完成（input_type={data.get('input_type', 'audio')}）")
            print(f"  任务 ID: {data.get('task_id')}")
            print(f"  状态: {data.get('status')}")
            print(f"  执行时间: {data.get('execution_time_ms')} ms")

            if data.get('result'):
                print("\n  执行结果:")
                format_result(data.get('result'))

            tokens = data.get('tokens', {})
            if tokens:
                print(f"\n  Token 消耗:")
                print(f"    输入: {tokens.get('input')}")
                print(f"    输出: {tokens.get('output')}")
                print(f"    成本: {tokens.get('cost')} CNY")
                print(f"    模型: {tokens.get('model')}")

            return data.get('task_id')
        elif response.status_code == 422:
            data = response.json()
            print_warning(f"语音识别失败: {data.get('error')}")
            return None
        else:
            print_error(f"请求失败 (状态码: {response.status_code})")
            print(f"响应: {response.text}")
            return None
    except Exception as e:
        print_error(f"请求失败: {e}")
        return None


def example_ambiguous_input_error(token):
    """
    示例 9: 同时提供 text 和 audio —— 应返回 400 AMBIGUOUS_INPUT

    POST /api/agent/quick-action/
    text 与 audio 不可兼得，此示例验证错误处理逻辑。
    """
    print_header("示例 9: 同时提供 text 和 audio（应返回 400）")

    wav_path = make_test_wav(duration_sec=1.0)
    print_info("同时提交 text 字段和 audio 文件...")

    try:
        token_headers = {"Authorization": f"Token {token}"}
        with open(wav_path, 'rb') as f:
            response = requests.post(
                f"{BASE_URL}/api/agent/quick-action/",
                headers=token_headers,
                files={'audio': ('test.wav', f, 'audio/wav')},
                data={'text': '明天下午3点开会', 'sync': 'false'},
                timeout=15,
            )

        print_info(f"HTTP 状态码: {response.status_code}")
        data = response.json()

        if response.status_code == 400 and data.get('code') == 'AMBIGUOUS_INPUT':
            print_success(f"正确返回 AMBIGUOUS_INPUT: {data.get('error')}")
        else:
            print_warning(f"响应: {json.dumps(data, ensure_ascii=False)}")
    except Exception as e:
        print_error(f"请求失败: {e}")
    finally:
        if os.path.exists(wav_path):
            os.unlink(wav_path)


def example_multiple_scenarios(token):
    """
    示例 10: 多场景测试
    """
    print_header("示例 10: 多场景测试")
    
    test_cases = [
        "明天上午10点开会",
        "后天下午3点到5点有个培训",
        "下周一提醒我交报告",
        "完成买菜这个待办",
        "2月10日的会议改到晚上8点",
        "查看本周的所有会议",
    ]
    
    results = []
    
    for i, text in enumerate(test_cases, 1):
        print(f"\n{Colors.OKCYAN}测试用例 {i}/{len(test_cases)}: {text}{Colors.ENDC}")
        
        # 创建任务（同步模式，快速得到结果）
        payload = {"text": text, "sync": True, "timeout": 30}
        
        try:
            response = requests.post(
                f"{BASE_URL}/api/agent/quick-action/",
                headers=get_headers(token),
                json=payload,
                timeout=35
            )
            
            if response.status_code == 200:
                data = response.json()
                result_type = data.get('result', {}).get('type')
                
                if result_type == 'action_completed':
                    print_success("执行成功")
                elif result_type == 'need_clarification':
                    print_warning("需要补充信息")
                else:
                    print_error("执行失败")
                
                results.append({
                    'text': text,
                    'success': result_type == 'action_completed',
                    'result_type': result_type
                })
            else:
                print_error(f"请求失败 (状态码: {response.status_code})")
                results.append({'text': text, 'success': False, 'result_type': 'error'})
        except Exception as e:
            print_error(f"请求失败: {e}")
            results.append({'text': text, 'success': False, 'result_type': 'error'})
        
        # 短暂延迟，避免请求过快
        time.sleep(0.5)
    
    # 统计结果
    print(f"\n{Colors.HEADER}{Colors.BOLD}测试结果统计{Colors.ENDC}")
    success_count = sum(1 for r in results if r['success'])
    print(f"  成功: {success_count}/{len(results)}")
    print(f"  失败: {len(results) - success_count}/{len(results)}")
    
    return results


# ==================== 主函数 ====================

def main():
    """主测试流程"""
    parser = argparse.ArgumentParser(
        description='Quick Action API 测试脚本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 只运行文本模式测试
  python api_examples/example_quick_action_api.py

  # 同时运行语音模式测试（需要真实音频）
  python api_examples/example_quick_action_api.py --audio path/to/command.wav

语音音频建议：
  录制一段包含日程指令的音频，如"明天下午三点开会，讨论项目进度"
  支持格式：wav / mp3 / ogg / flac / webm / aac / m4a / amr（≤ 60 秒）
        """
    )
    parser.add_argument('--audio', metavar='PATH',
                        help='用于语音输入示例的音频文件路径')
    args = parser.parse_args()

    print(f"{Colors.HEADER}{Colors.BOLD}")
    print("="*60)
    print("Quick Action API 测试脚本".center(60))
    print("="*60)
    print(f"{Colors.ENDC}")

    if args.audio:
        print_info(f"语音文件: {args.audio}")
        if not os.path.exists(args.audio):
            print_error(f"文件不存在: {args.audio}")
            return
    else:
        print_info("未指定 --audio，语音同步示例将跳过")

    # 1. 获取 Token
    token = get_auth_token()
    if not token:
        print_error("无法获取 Token，测试终止")
        return

    # ——————————————————————————————————————
    # 文本输入系列（示例 1-6）
    # ——————————————————————————————————————

    # 2. 测试异步模式
    task_id_async = example_create_quick_action_async(token)

    if task_id_async:
        time.sleep(1)
        example_get_task_status(token, task_id_async)
        time.sleep(1)
        example_long_polling(token, task_id_async)

    # 3. 测试同步模式
    example_create_quick_action_sync(token)

    # 4. 查看历史列表
    example_list_quick_actions(token)

    # 5. 测试取消任务
    print_info("\n准备测试取消功能...")
    cancel_task_id = example_create_quick_action_async(token)
    if cancel_task_id:
        time.sleep(0.2)
        example_cancel_task(token, cancel_task_id)

    # ——————————————————————————————————————
    # 语音输入系列（示例 7-9）
    # ——————————————————————————————————————

    # 7. 语音异步（使用合成音频验证接口联通性）
    example_create_quick_action_audio_async(token, args.audio)

    # 8. 语音同步（仅在提供真实音频时运行，否则提示跳过）
    example_create_quick_action_audio_sync(token, args.audio)

    # 9. 互斥参数错误验证
    example_ambiguous_input_error(token)

    # ——————————————————————————————————————
    # 多场景压测（示例 10，可选）
    # ——————————————————————————————————————
    print_info("\n是否执行多场景测试？这可能需要几分钟时间...")
    user_input = input("输入 'y' 继续，或按回车跳过: ").strip().lower()
    if user_input == 'y':
        example_multiple_scenarios(token)

    print_header("测试完成")
    print_success("所有测试已完成！")
    print()
    print_info("语音功能说明：")
    print("  • 合成正弦波的识别结果为空属正常（无真实语音内容）")
    print("  • 使用 --audio 参数传入真实录音以测试完整语音→操作流程")
    print("  • 独立语音识别接口见 example_parser_api.py")


if __name__ == "__main__":
    main()
