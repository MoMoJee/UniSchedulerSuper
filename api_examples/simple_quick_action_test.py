"""
Quick Action API 简单测试
快速测试 Quick Action 基本功能

使用方法：
    python api_examples/simple_quick_action_test.py
"""

import requests
import json
import time

# 配置
BASE_URL = "http://127.0.0.1:8000"
USERNAME = "test_user"  # 修改为你的用户名
PASSWORD = "test_password"  # 修改为你的密码


def get_token():
    """获取认证 Token"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login/",
        json={"username": USERNAME, "password": PASSWORD}
    )
    if response.status_code == 200:
        return response.json().get('token')
    return None


def test_quick_action_sync(token, text):
    """测试同步快速操作"""
    print(f"\n{'='*60}")
    print(f"测试: {text}")
    print('='*60)
    
    response = requests.post(
        f"{BASE_URL}/api/agent/quick-action/",
        headers={"Authorization": f"Token {token}"},
        json={"text": text, "sync": True}
    )
    
    if response.status_code == 200:
        data = response.json()
        result = data.get('result', {})
        result_type = result.get('type', '')
        message = result.get('message', '')
        
        print(f"状态: {data.get('status')}")
        print(f"结果类型: {result_type}")
        print(f"结果消息:\n{message}")
        
        tokens = data.get('tokens', {})
        if tokens:
            print(f"\nToken 消耗: {tokens.get('input')} / {tokens.get('output')}")
            print(f"成本: {tokens.get('cost')} CNY")
        
        return result_type == 'action_completed'
    else:
        print(f"请求失败: {response.status_code}")
        print(response.text)
        return False


def test_quick_action_async(token, text):
    """测试异步快速操作"""
    print(f"\n{'='*60}")
    print(f"测试 (异步): {text}")
    print('='*60)
    
    # 创建任务
    response = requests.post(
        f"{BASE_URL}/api/agent/quick-action/",
        headers={"Authorization": f"Token {token}"},
        json={"text": text, "sync": False}
    )
    
    if response.status_code != 201:
        print(f"创建任务失败: {response.status_code}")
        return False
    
    task_id = response.json().get('task_id')
    print(f"任务创建成功: {task_id}")
    
    # 长轮询等待结果
    print("等待执行结果...")
    response = requests.get(
        f"{BASE_URL}/api/agent/quick-action/{task_id}/?wait=true",
        headers={"Authorization": f"Token {token}"},
        timeout=35
    )
    
    if response.status_code == 200:
        data = response.json()
        result = data.get('result', {})
        result_type = result.get('type', '')
        message = result.get('message', '')
        
        print(f"状态: {data.get('status')}")
        print(f"结果类型: {result_type}")
        print(f"结果消息:\n{message}")
        
        return result_type == 'action_completed'
    else:
        print(f"查询失败: {response.status_code}")
        return False


def main():
    """主测试流程"""
    print("\n" + "="*60)
    print("Quick Action API 简单测试".center(60))
    print("="*60)
    
    # 获取 Token
    print("\n获取认证 Token...")
    token = get_token()
    if not token:
        print("❌ 登录失败，请检查用户名和密码")
        return
    print("✅ Token 获取成功")
    
    # 测试用例
    test_cases = [
        ("明天下午3点开会", "同步"),
        ("后天上午10点提醒我交报告", "同步"),
        ("完成代码评审", "同步"),
        ("下周一开始每周例会", "异步"),
    ]
    
    results = []
    
    for text, mode in test_cases:
        if mode == "同步":
            success = test_quick_action_sync(token, text)
        else:
            success = test_quick_action_async(token, text)
        
        results.append((text, success))
        time.sleep(1)  # 短暂延迟
    
    # 统计结果
    print("\n" + "="*60)
    print("测试结果统计".center(60))
    print("="*60)
    
    success_count = sum(1 for _, success in results if success)
    total_count = len(results)
    
    for text, success in results:
        icon = "✅" if success else "❌"
        print(f"{icon} {text}")
    
    print(f"\n成功: {success_count}/{total_count}")
    print(f"失败: {total_count - success_count}/{total_count}")
    
    if success_count == total_count:
        print("\n🎉 所有测试通过！")
    else:
        print("\n⚠️ 部分测试失败")


if __name__ == "__main__":
    main()
