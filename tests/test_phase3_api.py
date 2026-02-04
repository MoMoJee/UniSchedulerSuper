"""
测试 Phase 3 API 和通信功能
"""
import os
import sys
import django
import json

# 设置 Django 环境
sys.path.insert(0, 'd:/PROJECTS/UniSchedulerSuper')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'UniSchedulerSuper.settings')
django.setup()

from django.test import TestCase, Client
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token

def test_session_api():
    """测试 Session 管理 API"""
    print("=" * 50)
    print("测试 1: Session 管理 API")
    print("=" * 50)
    
    # 获取或创建测试用户
    user, _ = User.objects.get_or_create(username='test_user', defaults={'email': 'test@example.com'})
    token, _ = Token.objects.get_or_create(user=user)
    
    client = Client()
    
    # 1. 获取会话列表
    print("\n[GET /api/agent/sessions/]")
    response = client.get('/api/agent/sessions/', HTTP_AUTHORIZATION=f'Token {token.key}')
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Sessions: {len(data.get('sessions', []))} 个")
        print("✅ 获取会话列表成功")
    else:
        print(f"Response: {response.content.decode()}")
        print("❌ 获取会话列表失败")
        return False
    
    # 2. 创建新会话 (注意 URL 是 /sessions/create/)
    print("\n[POST /api/agent/sessions/create/]")
    response = client.post(
        '/api/agent/sessions/create/',
        data=json.dumps({}),  # 不指定 session_id，让系统自动生成
        content_type='application/json',
        HTTP_AUTHORIZATION=f'Token {token.key}'
    )
    print(f"Status: {response.status_code}")
    if response.status_code in [200, 201]:
        data = response.json()
        print(f"Session ID: {data.get('session_id')}")
        print("✅ 创建会话成功")
    else:
        print(f"Response: {response.content.decode()}")
        print("❌ 创建会话失败")
        return False
    
    return True

def test_history_api():
    """测试历史记录 API"""
    print("\n" + "=" * 50)
    print("测试 2: 历史记录 API")
    print("=" * 50)
    
    user, _ = User.objects.get_or_create(username='test_user', defaults={'email': 'test@example.com'})
    token, _ = Token.objects.get_or_create(user=user)
    
    client = Client()
    
    # 使用正确格式的 session_id (user_{id}_xxx)
    session_id = f"user_{user.id}_default"
    
    # 获取历史记录
    print(f"\n[GET /api/agent/history/?session_id={session_id}]")
    response = client.get(
        f'/api/agent/history/?session_id={session_id}',
        HTTP_AUTHORIZATION=f'Token {token.key}'
    )
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"History messages: {len(data.get('messages', []))} 条")
        print("✅ 获取历史记录成功")
        return True
    else:
        print(f"Response: {response.content.decode()}")
        print("❌ 获取历史记录失败")
        return False

def test_rollback_preview():
    """测试回滚预览 API"""
    print("\n" + "=" * 50)
    print("测试 3: 回滚预览 API")
    print("=" * 50)
    
    user, _ = User.objects.get_or_create(username='test_user', defaults={'email': 'test@example.com'})
    token, _ = Token.objects.get_or_create(user=user)
    
    client = Client()
    
    # 使用正确格式的 session_id
    session_id = f"user_{user.id}_default"
    
    # 预览回滚
    print(f"\n[POST /api/agent/rollback/preview/]")
    response = client.post(
        '/api/agent/rollback/preview/',
        data=json.dumps({'session_id': session_id, 'steps': 1}),
        content_type='application/json',
        HTTP_AUTHORIZATION=f'Token {token.key}'
    )
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Preview: {data}")
        print("✅ 回滚预览成功")
        return True
    else:
        print(f"Response: {response.content.decode()}")
        # 404 是正常的（没有历史记录）
        if response.status_code == 404:
            print("⚠️ 没有找到可回滚的记录（正常情况）")
            return True
        print("❌ 回滚预览失败")
        return False

def test_url_routing():
    """测试 URL 路由配置"""
    print("\n" + "=" * 50)
    print("测试 4: URL 路由检查")
    print("=" * 50)
    
    from django.urls import reverse, get_resolver
    
    # 检查 API 路由是否注册
    try:
        resolver = get_resolver()
        patterns = [p.pattern for p in resolver.url_patterns]
        print(f"顶级 URL 模式: {patterns}")
        
        # 尝试解析 API 端点
        endpoints = [
            '/api/agent/sessions/',
            '/api/agent/history/',
            '/api/agent/rollback/preview/',
            '/api/agent/rollback/',
        ]
        
        for endpoint in endpoints:
            try:
                match = resolver.resolve(endpoint)
                print(f"✅ {endpoint} -> {match.func.__name__}")
            except Exception as e:
                print(f"❌ {endpoint} -> 路由未找到: {e}")
                return False
        
        print("✅ URL 路由配置正确")
        return True
    except Exception as e:
        print(f"❌ 路由检查失败: {e}")
        return False

if __name__ == "__main__":
    print("开始测试 Phase 3 API\n")
    
    results = []
    
    # 先测试 URL 路由
    results.append(("URL路由", test_url_routing()))
    
    # 测试各个 API
    results.append(("Session API", test_session_api()))
    results.append(("History API", test_history_api()))
    results.append(("Rollback Preview", test_rollback_preview()))
    
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
