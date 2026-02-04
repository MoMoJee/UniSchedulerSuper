"""
UniScheduler API Token 测试脚本
用于测试 Token 认证功能是否正常工作
"""

import requests
import json

# 配置
BASE_URL = "http://localhost:8000"  # 修改为你的服务器地址
USERNAME = "MoMoJee"  # 修改为你的用户名
PASSWORD = "yzh11621@411314"  # 修改为你的密码

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


def print_info(message):
    print(f"{Colors.OKCYAN}ℹ️  {message}{Colors.ENDC}")


def print_header(message):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{message:^60}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}\n")


def test_api_login():
    """测试 API 登录获取 Token"""
    print_header("测试 1: API 登录获取 Token")
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/auth/login/",
            json={
                "username": USERNAME,
                "password": PASSWORD
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            token = data.get('token')
            print_success(f"登录成功！")
            print_info(f"Token: {token}")
            print_info(f"用户ID: {data.get('user_id')}")
            print_info(f"用户名: {data.get('username')}")
            return token
        else:
            print_error(f"登录失败！状态码: {response.status_code}")
            print_error(f"响应: {response.text}")
            return None
            
    except Exception as e:
        print_error(f"请求失败: {str(e)}")
        return None


def test_token_verify(token):
    """测试 Token 验证"""
    print_header("测试 2: 验证 Token")
    
    try:
        response = requests.get(
            f"{BASE_URL}/api/auth/token/verify/",
            headers={
                "Authorization": f"Token {token}"
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            print_success("Token 验证成功！")
            print_info(f"用户: {data.get('username')}")
            print_info(f"邮箱: {data.get('email')}")
            return True
        else:
            print_error(f"验证失败！状态码: {response.status_code}")
            print_error(f"响应: {response.text}")
            return False
            
    except Exception as e:
        print_error(f"请求失败: {str(e)}")
        return False


def test_get_events(token):
    """测试获取日程列表"""
    print_header("测试 3: 使用 Token 获取日程列表")
    
    try:
        response = requests.get(
            f"{BASE_URL}/get_calendar/events",
            headers={
                "Authorization": f"Token {token}"
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            events = data.get('events', [])
            print_success(f"获取日程成功！共 {len(events)} 个日程")
            
            if events:
                print_info("前3个日程:")
                for i, event in enumerate(events[:3], 1):
                    print(f"  {i}. {event.get('title')} - {event.get('start')}")
            return True
        else:
            print_error(f"获取失败！状态码: {response.status_code}")
            print_error(f"响应: {response.text}")
            return False
            
    except Exception as e:
        print_error(f"请求失败: {str(e)}")
        return False


def test_get_reminders(token):
    """测试获取提醒列表"""
    print_header("测试 4: 使用 Token 获取提醒列表")
    
    try:
        response = requests.get(
            f"{BASE_URL}/api/reminders/",
            headers={
                "Authorization": f"Token {token}"
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            reminders = data.get('reminders', [])
            print_success(f"获取提醒成功！共 {len(reminders)} 个提醒")
            
            if reminders:
                print_info("前3个提醒:")
                for i, reminder in enumerate(reminders[:3], 1):
                    print(f"  {i}. {reminder.get('title')} - {reminder.get('trigger_time')}")
            return True
        else:
            print_error(f"获取失败！状态码: {response.status_code}")
            print_error(f"响应: {response.text}")
            return False
            
    except Exception as e:
        print_error(f"请求失败: {str(e)}")
        return False


def test_get_user_settings(token):
    """测试获取用户设置"""
    print_header("测试 5: 使用 Token 获取用户设置")
    
    try:
        response = requests.get(
            f"{BASE_URL}/get_calendar/user_settings/",
            headers={
                "Authorization": f"Token {token}"
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            print_success("获取用户设置成功！")
            print_info(f"主题: {data.get('theme', 'N/A')}")
            print_info(f"周数显示: {data.get('show_week_number', 'N/A')}")
            print_info(f"自动DDL: {data.get('auto_ddl', 'N/A')}")
            return True
        else:
            print_error(f"获取失败！状态码: {response.status_code}")
            print_error(f"响应: {response.text}")
            return False
            
    except Exception as e:
        print_error(f"请求失败: {str(e)}")
        return False


def test_without_token():
    """测试无 Token 访问（应该失败）"""
    print_header("测试 6: 无 Token 访问（预期失败）")
    
    try:
        response = requests.get(f"{BASE_URL}/api/reminders/")
        
        if response.status_code == 403 or response.status_code == 401:
            print_success("正确拒绝了无认证的请求！")
            return True
        else:
            print_error(f"安全问题！无认证也能访问。状态码: {response.status_code}")
            return False
            
    except Exception as e:
        print_error(f"请求失败: {str(e)}")
        return False


def main():
    print(f"{Colors.BOLD}")
    print("╔═══════════════════════════════════════════════════════════╗")
    print("║                                                           ║")
    print("║       UniScheduler API Token 认证功能测试                 ║")
    print("║                                                           ║")
    print("╚═══════════════════════════════════════════════════════════╝")
    print(f"{Colors.ENDC}")
    
    print_info(f"服务器地址: {BASE_URL}")
    print_info(f"测试用户: {USERNAME}")
    print()
    
    results = {
        "通过": 0,
        "失败": 0
    }
    
    # 测试 1: 登录获取 Token
    token = test_api_login()
    if token:
        results["通过"] += 1
    else:
        results["失败"] += 1
        print_error("无法继续后续测试，因为未能获取 Token")
        return
    
    # 测试 2: 验证 Token
    if test_token_verify(token):
        results["通过"] += 1
    else:
        results["失败"] += 1
    
    # 测试 3: 获取日程
    if test_get_events(token):
        results["通过"] += 1
    else:
        results["失败"] += 1
    
    # 测试 4: 获取提醒
    if test_get_reminders(token):
        results["通过"] += 1
    else:
        results["失败"] += 1
    #
    # 测试 5: 获取用户设置
    if test_get_user_settings(token):
        results["通过"] += 1
    else:
        results["失败"] += 1

    # 测试 6: 无 Token 访问
    if test_without_token():
        results["通过"] += 1
    else:
        results["失败"] += 1

    # 总结
    print_header("测试总结")
    total = results["通过"] + results["失败"]
    print(f"总测试数: {total}")
    print_success(f"通过: {results['通过']}")
    if results["失败"] > 0:
        print_error(f"失败: {results['失败']}")

    if results["失败"] == 0:
        print(f"\n{Colors.OKGREEN}{Colors.BOLD}🎉 所有测试通过！Token 认证功能正常工作！{Colors.ENDC}\n")
    else:
        print(f"\n{Colors.WARNING}{Colors.BOLD}⚠️  有 {results['失败']} 个测试失败，请检查配置{Colors.ENDC}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}测试被用户中断{Colors.ENDC}")
    except Exception as e:
        print_error(f"测试过程中发生错误: {str(e)}")
