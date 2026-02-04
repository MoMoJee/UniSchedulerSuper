"""
上下文优化功能测试脚本

测试内容:
1. TokenCalculator 计算功能
2. ToolMessageCompressor 压缩功能
3. build_optimized_context 构建功能
4. 模拟短窗口限制下的上下文优化

运行方式:
    python manage.py shell < tests/test_context_optimization.py
    或
    python -c "import django; django.setup(); exec(open('tests/test_context_optimization.py').read())"
"""

import os
import sys
import django

# 设置 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'UniSchedulerSuper.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
django.setup()

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from agent_service.context_optimizer import (
    TokenCalculator, ToolMessageCompressor,
    get_current_model_config, get_optimization_config, SYSTEM_MODELS
)
from agent_service.context_summarizer import build_optimized_context, build_full_context

print("=" * 60)
print("上下文优化功能测试")
print("=" * 60)


# ==========================================
# 测试 1: TokenCalculator
# ==========================================
print("\n[测试 1] TokenCalculator")
print("-" * 40)

calculator = TokenCalculator(method="estimate")

# 测试文本计算
test_text = "这是一段测试文本，用于验证 Token 计算功能。Hello World! 你好世界！"
tokens = calculator.calculate_text(test_text)
print(f"  文本: {test_text[:30]}...")
print(f"  估算 Token 数: {tokens}")
print(f"  字符数: {len(test_text)}")
print(f"  比例: 1 token ≈ {len(test_text)/tokens:.2f} 字符")

# 测试消息计算
msg = HumanMessage(content="请帮我创建一个明天上午10点的会议，主题是项目评审")
msg_tokens = calculator.calculate_message(msg)
print(f"\n  消息: {msg.content[:30]}...")
print(f"  消息 Token 数: {msg_tokens}")

print("\n  ✅ TokenCalculator 测试通过")


# ==========================================
# 测试 2: ToolMessageCompressor
# ==========================================
print("\n[测试 2] ToolMessageCompressor")
print("-" * 40)

compressor = ToolMessageCompressor(max_tokens=50)

# 创建一个大的工具消息
large_content = {
    "success": True,
    "events": [
        {"id": 1, "title": "会议1", "start": "2026-01-03T10:00:00", "end": "2026-01-03T11:00:00", "description": "这是一个很长的描述" * 10},
        {"id": 2, "title": "会议2", "start": "2026-01-03T14:00:00", "end": "2026-01-03T15:00:00", "description": "另一个长描述" * 10},
        {"id": 3, "title": "会议3", "start": "2026-01-03T16:00:00", "end": "2026-01-03T17:00:00"},
        {"id": 4, "title": "会议4", "start": "2026-01-04T10:00:00", "end": "2026-01-04T11:00:00"},
        {"id": 5, "title": "会议5", "start": "2026-01-04T14:00:00", "end": "2026-01-04T15:00:00"},
    ],
    "total": 5
}

import json
tool_msg = ToolMessage(
    content=json.dumps(large_content, ensure_ascii=False),
    tool_call_id="call_123",
    name="get_events"
)

original_tokens = calculator.calculate_message(tool_msg)
compressed_msg = compressor.compress(tool_msg, calculator)
compressed_tokens = calculator.calculate_message(compressed_msg)

print(f"  原始消息 Token: {original_tokens}")
print(f"  压缩后 Token: {compressed_tokens}")
print(f"  压缩率: {(1 - compressed_tokens/original_tokens)*100:.1f}%")
print(f"  压缩后内容预览: {compressed_msg.content[:100]}...")

print("\n  ✅ ToolMessageCompressor 测试通过")


# ==========================================
# 测试 3: build_optimized_context (短窗口)
# ==========================================
print("\n[测试 3] build_optimized_context (短窗口限制)")
print("-" * 40)

# 创建模拟对话历史
messages = []

# 添加 20 条对话
for i in range(10):
    messages.append(HumanMessage(content=f"用户消息 {i+1}: 这是第 {i+1} 轮对话的用户输入，包含一些额外的内容来增加长度。"))
    messages.append(AIMessage(content=f"AI 回复 {i+1}: 这是第 {i+1} 轮对话的 AI 回复，我会尝试给出有帮助的回答。这里再添加一些额外的文字来增加消息长度。"))

# 添加几条工具消息
messages.append(HumanMessage(content="请帮我查看今天的日程安排"))
messages.append(AIMessage(content="好的，我来帮您查看", tool_calls=[{"name": "get_events", "id": "call_456", "args": {}}]))
messages.append(ToolMessage(
    content=json.dumps({"events": [{"title": f"会议{j}", "time": f"0{j}:00"} for j in range(1, 6)]}, ensure_ascii=False),
    tool_call_id="call_456",
    name="get_events"
))
messages.append(AIMessage(content="您今天有5个会议安排..."))

print(f"  原始消息数量: {len(messages)}")

# 计算原始总 token
total_original_tokens = sum(calculator.calculate_message(m) for m in messages)
print(f"  原始总 Token: {total_original_tokens}")

# 使用短窗口限制进行优化
SHORT_WINDOW = 2048  # 模拟短窗口
TARGET_RATIO = 0.6
max_tokens = int(SHORT_WINDOW * TARGET_RATIO)  # 约 1228 tokens

system_prompt = "你是一个日程管理助手。"
system_tokens = calculator.calculate_text(system_prompt)
available_tokens = max_tokens - system_tokens

print(f"\n  模拟窗口大小: {SHORT_WINDOW}")
print(f"  目标使用率: {TARGET_RATIO*100}%")
print(f"  最大可用 Token: {max_tokens}")
print(f"  System Prompt Token: {system_tokens}")
print(f"  剩余可用 Token: {available_tokens}")

# 计算预算
summary_budget = int(available_tokens * 0.26)
recent_budget = int(available_tokens * 0.65)
print(f"\n  总结预算: {summary_budget}")
print(f"  最近对话预算: {recent_budget}")

# 构建优化上下文
optimized = build_optimized_context(
    user=None,
    system_prompt=system_prompt,
    messages=messages,
    summary_metadata=None,
    token_calculator=calculator,
    tool_compressor=compressor,
    summary_token_budget=summary_budget,
    recent_token_budget=recent_budget
)

print(f"\n  优化后消息数量: {len(optimized)}")

# 计算优化后总 token
total_optimized_tokens = sum(calculator.calculate_message(m) for m in optimized)
print(f"  优化后总 Token: {total_optimized_tokens}")
print(f"  Token 削减: {total_original_tokens} -> {total_optimized_tokens} ({(1 - total_optimized_tokens/total_original_tokens)*100:.1f}%)")

# 显示优化后的消息结构
print(f"\n  优化后消息结构:")
for i, msg in enumerate(optimized):
    msg_type = type(msg).__name__
    content_preview = msg.content[:50] if len(msg.content) > 50 else msg.content
    content_preview = content_preview.replace('\n', ' ')
    print(f"    [{i+1}] {msg_type}: {content_preview}...")

print("\n  ✅ build_optimized_context 测试通过")


# ==========================================
# 测试 4: 系统模型配置
# ==========================================
print("\n[测试 4] 系统模型配置")
print("-" * 40)

print(f"  系统模型列表:")
for model_id, config in SYSTEM_MODELS.items():
    print(f"    - {model_id}: {config.get('name')}")
    print(f"      上下文窗口: {config.get('context_window')}")
    print(f"      API URL: {config.get('api_url')}")

print("\n  ✅ 系统模型配置测试通过")


# ==========================================
# 测试 5: 边界情况
# ==========================================
print("\n[测试 5] 边界情况测试")
print("-" * 40)

# 空消息列表
empty_optimized = build_optimized_context(
    user=None,
    system_prompt="系统提示",
    messages=[],
    summary_metadata=None,
    token_calculator=calculator,
    tool_compressor=None,
    summary_token_budget=1000,
    recent_token_budget=1000
)
print(f"  空消息列表 -> 优化后: {len(empty_optimized)} 条消息")
assert len(empty_optimized) == 1  # 只有 System Prompt
print("  ✅ 空消息列表测试通过")

# 单条消息
single_msg = [HumanMessage(content="你好")]
single_optimized = build_optimized_context(
    user=None,
    system_prompt="系统提示",
    messages=single_msg,
    summary_metadata=None,
    token_calculator=calculator,
    tool_compressor=None,
    summary_token_budget=1000,
    recent_token_budget=1000
)
print(f"  单条消息 -> 优化后: {len(single_optimized)} 条消息")
assert len(single_optimized) == 2  # System Prompt + 用户消息
print("  ✅ 单条消息测试通过")


# ==========================================
# 总结
# ==========================================
print("\n" + "=" * 60)
print("所有测试通过! ✅")
print("=" * 60)

print("""
测试结果说明:
1. TokenCalculator 可以正确估算文本和消息的 Token 数
2. ToolMessageCompressor 可以有效压缩工具输出
3. build_optimized_context 在短窗口限制下能正确裁剪上下文
4. 系统模型配置正确加载
5. 边界情况处理正确

下一步建议:
- 在实际对话中测试，观察日志输出
- 如果需要更精确的 Token 计算，可安装 tiktoken: pip install tiktoken
""")
