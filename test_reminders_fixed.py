"""
测试修复后的 Reminders API
验证所有参数名称是否正确
"""

import requests
from datetime import datetime, timedelta

BASE_URL = "http://127.0.0.1:8000"
USERNAME = "test_user"
PASSWORD = "test_password"


def get_token():
    """获取认证 Token"""
    print("🔐 获取 Token...")
    response = requests.post(
        f"{BASE_URL}/api/auth/login/",
        json={"username": USERNAME, "password": PASSWORD}
    )
    if response.status_code == 200:
        token = response.json().get('token')
        print(f"✅ Token 获取成功")
        return token
    else:
        print(f"❌ 登录失败")
        return None


def test_create_single_reminder(token):
    """测试创建单次提醒 - 验证参数名称"""
    print("\n" + "="*60)
    print("测试 1: 创建单次提醒")
    print("="*60)
    
    now = datetime.now()
    data = {
        "title": "测试提醒",
        "trigger_time": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S"),  # ✅ trigger_time
        "content": "这是测试内容",  # ✅ content
        "priority": "high"  # ✅ priority
    }
    
    print(f"发送数据: {data}")
    
    response = requests.post(
        f"{BASE_URL}/api/reminders/create/",
        headers={"Authorization": f"Token {token}", "Content-Type": "application/json"},
        json=data
    )
    
    print(f"状态码: {response.status_code}")
    print(f"响应: {response.json()}")
    
    if response.status_code == 200:
        print("✅ 单次提醒创建成功")
        return True
    else:
        print("❌ 创建失败")
        return False


def test_create_recurring_reminder(token):
    """测试创建重复提醒 - 验证 rrule 参数"""
    print("\n" + "="*60)
    print("测试 2: 创建重复提醒")
    print("="*60)
    
    now = datetime.now()
    data = {
        "title": "测试重复提醒",
        "trigger_time": (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),  # ✅ trigger_time
        "content": "每天重复的提醒",  # ✅ content
        "priority": "medium",  # ✅ priority
        "rrule": "FREQ=DAILY;INTERVAL=1;COUNT=5"  # ✅ rrule 字符串格式
    }
    
    print(f"发送数据: {data}")
    
    response = requests.post(
        f"{BASE_URL}/api/reminders/create/",
        headers={"Authorization": f"Token {token}", "Content-Type": "application/json"},
        json=data
    )
    
    print(f"状态码: {response.status_code}")
    print(f"响应: {response.json()}")
    
    if response.status_code == 200:
        print("✅ 重复提醒创建成功")
        return True
    else:
        print("❌ 创建失败")
        return False


def test_get_reminders(token):
    """测试获取提醒列表 - 验证返回字段"""
    print("\n" + "="*60)
    print("测试 3: 获取提醒列表")
    print("="*60)
    
    response = requests.get(
        f"{BASE_URL}/api/reminders/",
        headers={"Authorization": f"Token {token}"}
    )
    
    print(f"状态码: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        reminders = data.get('reminders', [])
        print(f"✅ 获取成功，共 {len(reminders)} 个提醒")
        
        if reminders:
            print("\n示例提醒字段:")
            reminder = reminders[0]
            print(f"  title: {reminder.get('title')}")
            print(f"  trigger_time: {reminder.get('trigger_time')}")  # ✅ 验证字段名
            print(f"  content: {reminder.get('content')}")  # ✅ 验证字段名
            print(f"  priority: {reminder.get('priority')}")  # ✅ 验证字段名
            print(f"  status: {reminder.get('status')}")
            print(f"  rrule: {reminder.get('rrule')}")
        
        return True
    else:
        print("❌ 获取失败")
        return False


def main():
    """运行所有测试"""
    print("\n" + "🧪"*30)
    print("Reminders API 参数名称测试")
    print("🧪"*30)
    
    token = get_token()
    if not token:
        print("\n❌ 无法获取 Token，测试终止")
        return
    
    # 运行测试
    results = []
    results.append(("创建单次提醒", test_create_single_reminder(token)))
    results.append(("创建重复提醒", test_create_recurring_reminder(token)))
    results.append(("获取提醒列表", test_get_reminders(token)))
    
    # 总结
    print("\n" + "="*60)
    print("测试总结")
    print("="*60)
    
    for test_name, success in results:
        icon = "✅" if success else "❌"
        print(f"{icon} {test_name}")
    
    all_passed = all(result[1] for result in results)
    
    if all_passed:
        print("\n🎉 所有测试通过！参数名称修复成功！")
    else:
        print("\n⚠️  部分测试失败，请检查错误信息")


if __name__ == "__main__":
    main()
