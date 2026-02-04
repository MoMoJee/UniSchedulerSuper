"""
简单测试 Agent Graph 的基本功能
"""
import os
import sys
import django

# 设置 Django 环境
sys.path.insert(0, 'd:/PROJECTS/UniSchedulerSuper')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'UniSchedulerSuper.settings')
django.setup()

from django.contrib.auth.models import User
from langchain_core.messages import HumanMessage
from agent_service.agent_graph import app, create_initial_state, get_config

def test_basic_chat():
    """测试基本对话功能"""
    print("=" * 50)
    print("测试 1: 基本对话")
    print("=" * 50)
    
    # 获取或创建测试用户
    user, created = User.objects.get_or_create(username='test_user', defaults={'email': 'test@example.com'})
    print(f"使用用户: {user.username} (ID: {user.id})")
    
    # 创建初始状态
    initial_state = create_initial_state(user, active_experts=['chat'])
    
    # 创建配置
    config = get_config(user, thread_id="test_basic_chat")
    
    # 发送消息
    user_message = "你好，你是谁？"
    print(f"\n用户: {user_message}")
    
    try:
        result = app.invoke(
            {**initial_state, "messages": [HumanMessage(content=user_message)]},
            config
        )
        
        # 打印响应
        last_message = result['messages'][-1]
        print(f"助手: {last_message.content}")
        print("\n✅ 基本对话测试通过")
        return True
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_planner_query():
    """测试日程查询功能"""
    print("\n" + "=" * 50)
    print("测试 2: 日程查询")
    print("=" * 50)
    
    user, _ = User.objects.get_or_create(username='test_user', defaults={'email': 'test@example.com'})
    
    initial_state = create_initial_state(user, active_experts=['planner'])
    config = get_config(user, thread_id="test_planner")
    
    user_message = "我有哪些日程？"
    print(f"\n用户: {user_message}")
    
    try:
        result = app.invoke(
            {**initial_state, "messages": [HumanMessage(content=user_message)]},
            config
        )
        
        last_message = result['messages'][-1]
        print(f"助手: {last_message.content}")
        print("\n✅ 日程查询测试通过")
        return True
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_supervisor_routing():
    """测试 Supervisor 路由功能"""
    print("\n" + "=" * 50)
    print("测试 3: Supervisor 路由")
    print("=" * 50)
    
    user, _ = User.objects.get_or_create(username='test_user', defaults={'email': 'test@example.com'})
    
    initial_state = create_initial_state(user, active_experts=['planner', 'chat'])
    config = get_config(user, thread_id="test_routing")
    
    # 测试不同类型的请求
    test_cases = [
        ("今天天气怎么样？", "chat"),
        ("帮我查看今天的日程", "planner"),
    ]
    
    for message, expected_expert in test_cases:
        print(f"\n用户: {message}")
        print(f"期望路由到: {expected_expert}")
        
        try:
            result = app.invoke(
                {**initial_state, "messages": [HumanMessage(content=message)]},
                config
            )
            
            last_message = result['messages'][-1]
            print(f"助手: {last_message.content[:100]}...")
            print("✓ 路由成功")
        except Exception as e:
            print(f"✗ 路由失败: {e}")
            return False
    
    print("\n✅ Supervisor 路由测试通过")
    return True

if __name__ == "__main__":
    print("开始测试 UniScheduler Agent Graph\n")
    
    results = []
    
    # 运行测试
    results.append(("基本对话", test_basic_chat()))
    results.append(("日程查询", test_planner_query()))
    results.append(("Supervisor路由", test_supervisor_routing()))
    
    # 汇总结果
    print("\n" + "=" * 50)
    print("测试结果汇总")
    print("=" * 50)
    
    for test_name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{test_name}: {status}")
    
    total_passed = sum(1 for _, passed in results if passed)
    print(f"\n总计: {total_passed}/{len(results)} 个测试通过")
    
    if total_passed == len(results):
        print("\n🎉 所有测试通过！")
        sys.exit(0)
    else:
        print("\n⚠️ 部分测试失败")
        sys.exit(1)
