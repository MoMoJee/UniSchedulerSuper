"""
上下文优化功能测试脚本 - 模拟对话接口

测试目标:
1. 使用较短的上下文窗口（如 400 tokens）
2. 模拟多轮对话
3. 观察上下文优化是否正确触发和工作

运行方式:
    python tests/test_context_optimization_live.py
"""

import os
import sys
import json
import django

# 设置 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'UniSchedulerSuper.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
django.setup()

from django.contrib.auth import get_user_model
from langchain_core.messages import HumanMessage, AIMessage
from agent_service.agent_graph import create_workflow, get_default_tools
from agent_service.context_optimizer import TokenCalculator
from core.models import UserData

User = get_user_model()


def setup_test_user_with_short_context(username='testuser', context_window=400):
    """
    设置测试用户，配置短上下文窗口
    """
    # 获取或创建测试用户
    user, created = User.objects.get_or_create(
        username=username,
        defaults={'email': f'{username}@test.com'}
    )
    if created:
        user.set_password('testpass123')
        user.save()
        print(f"[Setup] 创建测试用户: {username}")
    else:
        print(f"[Setup] 使用已有用户: {username}")
    
    # 配置短上下文窗口的自定义模型
    agent_config = {
        'current_model_id': 'test_short_context',
        'custom_models': {
            'test_short_context': {
                'name': f'测试短窗口模型 ({context_window} tokens)',
                'provider': 'custom',
                'api_url': 'https://api.deepseek.com/v1/chat/completions',
                'api_key': os.environ.get('OPENAI_API_KEY', ''),
                'model_name': 'deepseek-chat',
                'context_window': context_window,  # 短窗口！
                'cost_per_1k_input': 0.00014,
                'cost_per_1k_output': 0.00028,
            }
        }
    }
    
    # 保存配置
    UserData.objects.update_or_create(
        user=user,
        key='agent_config',
        defaults={'value': json.dumps(agent_config)}
    )
    print(f"[Setup] 配置上下文窗口: {context_window} tokens")
    
    # 配置优化参数
    opt_config = {
        'enable_optimization': True,
        'target_usage_ratio': 0.6,  # 使用 60% 的窗口
        'token_calculation_method': 'estimate',
        'summary_token_ratio': 0.26,
        'recent_token_ratio': 0.65,
        'enable_summarization': True,
        'summary_trigger_ratio': 0.5,
        'min_messages_before_summary': 5,  # 降低触发阈值便于测试
        'compress_tool_output': True,
        'tool_output_max_tokens': 50,
    }
    
    UserData.objects.update_or_create(
        user=user,
        key='agent_optimization_config',
        defaults={'value': json.dumps(opt_config)}
    )
    print(f"[Setup] 优化配置已设置")
    
    return user


def simulate_conversation(user, num_turns=8, dry_run=True):
    """
    模拟多轮对话
    
    Args:
        user: 测试用户
        num_turns: 对话轮数
        dry_run: 如果为 True，不实际调用 LLM
    """
    print("\n" + "=" * 60)
    print(f"模拟 {num_turns} 轮对话")
    print("=" * 60)
    
    # 创建 agent graph
    app = create_workflow()
    
    # 使用固定的 thread_id
    thread_id = f"test_context_opt_{user.id}"
    
    # 准备消息列表
    messages = []
    
    # 模拟用户消息
    user_messages = [
        "你好，请帮我创建一个明天上午10点的会议",
        "主题是项目评审会议，地点在3号会议室",
        "对了，我还需要创建一个待办事项，提醒我准备会议资料",
        "帮我查看一下这周的日程安排",
        "把明天的会议改到下午2点",
        "再帮我创建一个后天的培训安排",
        "帮我删除刚才创建的待办事项",
        "总结一下我现在的日程安排",
    ]
    
    # 模拟 AI 回复
    ai_responses = [
        "好的，我来帮您创建明天上午10点的会议。请问会议主题是什么？",
        "好的，我已经创建了会议：明天上午10点，项目评审会议，地点3号会议室。",
        "我已经创建了待办事项：准备会议资料。请问有截止时间吗？",
        "这周您的日程安排如下：\n1. 明天 10:00 项目评审会议\n2. 周三 14:00 部门例会\n...",
        "好的，我已经将明天的会议时间改到了下午2点。",
        "我已经创建了后天的培训安排。请问培训主题和时间？",
        "好的，待办事项已删除。",
        "您目前的日程安排总结如下：...",
    ]
    
    calculator = TokenCalculator(method='estimate')
    
    for turn in range(min(num_turns, len(user_messages))):
        print(f"\n--- 第 {turn + 1} 轮对话 ---")
        
        # 添加用户消息
        user_msg = HumanMessage(content=user_messages[turn])
        messages.append(user_msg)
        
        # 计算当前消息总 token
        total_tokens = sum(calculator.calculate_message(m) for m in messages)
        print(f"[对话] 用户: {user_messages[turn][:50]}...")
        print(f"[对话] 当前消息数: {len(messages)}, 总 token: {total_tokens}")
        
        if dry_run:
            # 模拟 AI 回复
            ai_msg = AIMessage(content=ai_responses[turn])
            messages.append(ai_msg)
            print(f"[对话] AI (模拟): {ai_responses[turn][:50]}...")
        else:
            # 实际调用 LLM
            config = {
                "configurable": {
                    "thread_id": thread_id,
                    "user": user,
                    "active_tools": get_default_tools(),
                }
            }
            
            input_state = {
                "messages": messages,
                "active_tools": get_default_tools(),
            }
            
            print(f"[对话] 调用 LLM...")
            try:
                result = None
                for output in app.stream(input_state, config):
                    for node_name, node_output in output.items():
                        if node_name == "agent" and "messages" in node_output:
                            result = node_output["messages"][-1]
                            messages.append(result)
                            print(f"[对话] AI: {result.content[:100]}...")
            except Exception as e:
                print(f"[对话] 调用失败: {e}")
                # 添加模拟回复继续测试
                ai_msg = AIMessage(content=f"[模拟回复] {ai_responses[turn]}")
                messages.append(ai_msg)
    
    print("\n" + "=" * 60)
    print("对话模拟完成")
    print("=" * 60)
    
    final_tokens = sum(calculator.calculate_message(m) for m in messages)
    print(f"最终消息数: {len(messages)}")
    print(f"最终总 token: {final_tokens}")
    
    return messages


def test_optimization_directly(user, messages):
    """
    直接测试上下文优化逻辑
    """
    print("\n" + "=" * 60)
    print("直接测试上下文优化")
    print("=" * 60)
    
    from agent_service.context_optimizer import (
        TokenCalculator, ToolMessageCompressor,
        get_current_model_config, get_optimization_config
    )
    from agent_service.context_summarizer import build_optimized_context
    
    # 获取配置
    current_model_id, model_config = get_current_model_config(user)
    opt_config = get_optimization_config(user)
    
    print(f"当前模型: {current_model_id}")
    print(f"上下文窗口: {model_config.get('context_window')}")
    print(f"优化配置: {opt_config}")
    
    # 计算参数
    context_window = model_config.get('context_window', 128000)
    target_ratio = opt_config.get('target_usage_ratio', 0.6)
    max_tokens = int(context_window * target_ratio)
    
    calculator = TokenCalculator(method='estimate')
    system_prompt = "你是一个日程管理助手。"
    system_tokens = calculator.calculate_text(system_prompt)
    available_tokens = max_tokens - system_tokens
    
    print(f"\n计算结果:")
    print(f"  最大可用 token: {max_tokens}")
    print(f"  System prompt token: {system_tokens}")
    print(f"  剩余可用 token: {available_tokens}")
    
    # 计算预算
    summary_budget = int(available_tokens * opt_config.get('summary_token_ratio', 0.26))
    recent_budget = int(available_tokens * opt_config.get('recent_token_ratio', 0.65))
    
    print(f"  总结预算: {summary_budget}")
    print(f"  最近对话预算: {recent_budget}")
    
    # 原始消息 token
    original_tokens = sum(calculator.calculate_message(m) for m in messages)
    print(f"\n原始消息: {len(messages)} 条, {original_tokens} tokens")
    
    # 执行优化
    tool_compressor = ToolMessageCompressor(max_tokens=50)
    
    optimized = build_optimized_context(
        user=user,
        system_prompt=system_prompt,
        messages=messages,
        summary_metadata=None,
        token_calculator=calculator,
        tool_compressor=tool_compressor,
        summary_token_budget=summary_budget,
        recent_token_budget=recent_budget
    )
    
    optimized_tokens = sum(calculator.calculate_message(m) for m in optimized)
    print(f"优化后: {len(optimized)} 条, {optimized_tokens} tokens")
    print(f"削减率: {(1 - optimized_tokens/original_tokens)*100:.1f}%")
    
    print("\n优化后消息:")
    for i, msg in enumerate(optimized):
        msg_type = type(msg).__name__
        content = msg.content[:60].replace('\n', ' ') if msg.content else ''
        print(f"  [{i+1}] {msg_type}: {content}...")


def main():
    print("=" * 60)
    print("上下文优化功能实时测试")
    print("=" * 60)
    
    # 设置测试用户，使用 400 token 的短窗口
    user = setup_test_user_with_short_context(
        username='context_test_user',
        context_window=400
    )
    
    # 模拟对话（干运行模式，不实际调用 LLM）
    messages = simulate_conversation(user, num_turns=8, dry_run=True)
    
    # 直接测试优化逻辑
    test_optimization_directly(user, messages)
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)
    print("""
下一步：
1. 查看上面的优化结果
2. 如果想实际调用 LLM，修改 dry_run=False
3. 观察 Django 日志中的 [Agent] 开头的日志
""")


if __name__ == '__main__':
    main()
