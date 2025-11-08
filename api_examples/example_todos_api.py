"""
TODOs API 使用示例
展示如何使用 Token 认证调用 TODOs 相关的所有 API

前置条件：
1. 确保 Django 服务已启动（python manage.py runserver）
2. 已有用户账号，或运行示例时自动创建

使用方法：
    python api_examples/example_todos_api.py
"""

import requests

# ==================== 配置区 ====================
BASE_URL = "http://127.0.0.1:8000"
USERNAME = "test_user"
PASSWORD = "test_password"

# ==================== 辅助函数 ====================

def get_auth_token(username=USERNAME, password=PASSWORD):
    """
    获取认证 Token
    
    Returns:
        str: 认证 Token，失败返回 None
    """
    print("\n" + "="*60)
    print("🔐 获取认证 Token")
    print("="*60)
    
    response = requests.post(
        f"{BASE_URL}/api/auth/login/",
        json={"username": username, "password": password}
    )
    
    if response.status_code == 200:
        token = response.json().get('token')
        print(f"✓ Token 获取成功: {token[:30]}...")
        return token
    else:
        print(f"✗ 登录失败 (状态码: {response.status_code})")
        print(f"  提示: 请先创建用户或修改配置中的用户名密码")
        return None


def get_headers(token):
    """
    生成请求头
    
    Args:
        token: 认证 Token
        
    Returns:
        dict: 包含认证信息的请求头
    """
    return {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json"
    }


# ==================== TODOs API 示例 ====================

def example_get_todos(token):
    """
    示例 1: 获取待办事项列表
    
    API: GET /api/todos/
    """
    print("\n" + "="*60)
    print("📝 示例 1: 获取待办事项列表")
    print("="*60)
    
    response = requests.get(
        f"{BASE_URL}/api/todos/",
        headers=get_headers(token)
    )
    
    if response.status_code == 200:
        data = response.json()
        todos = data.get('todos', [])
        print(f"✓ 成功获取 {len(todos)} 个待办事项")
        
        if todos:
            print("\n待办事项列表:")
            for i, todo in enumerate(todos[:5], 1):  # 只显示前5个
                status_icon = "✅" if todo.get('status') == 'completed' else "⏳"
                print(f"  {status_icon} {i}. {todo.get('title')}")
                print(f"     截止: {todo.get('due_date', '无')}, 重要性: {todo.get('importance', 'medium')}")
        
        return todos
    else:
        print(f"✗ 获取失败: {response.status_code}")
        print(f"  响应: {response.text}")
        return []


def example_create_todo(token, title, description, due_date, importance="medium", urgency="normal"):
    """
    示例 2: 创建待办事项
    
    API: POST /api/todos/create/
    
    Args:
        token: 认证 Token
        title: 标题
        description: 描述
        due_date: 截止日期（YYYY-MM-DD）
        importance: 重要性（important|not-important）
        urgency: 紧急程度（urgent|not-urgent）
    """
    print("\n" + "="*60)
    print(f"➕ 示例 2: 创建待办事项 - {title}")
    print("="*60)
    
    todo_data = {
        "title": title,
        "description": description,
        "due_date": due_date,
        "estimated_duration": 30,  # 预计耗时（分钟）
        "importance": importance,
        "urgency": urgency,
        "groupID": "",  # 可以关联到某个日程组
    }
    
    print(f"标题: {title}")
    print(f"描述: {description}")
    print(f"截止: {due_date}")
    print(f"重要性: {importance}, 紧急度: {urgency}")
    
    response = requests.post(
        f"{BASE_URL}/api/todos/create/",
        headers=get_headers(token),
        json=todo_data
    )
    
    if response.status_code == 200:
        result = response.json()
        todo_id = result.get('todo', {}).get('id')
        print(f"✓ 待办事项创建成功")
        print(f"  ID: {todo_id}")
        return todo_id
    else:
        print(f"✗ 创建失败: {response.status_code}")
        print(f"  响应: {response.text}")
        return None


def example_update_todo(token, todo_id, **updates):
    """
    示例 3: 更新待办事项
    
    API: POST /api/todos/update/
    
    Args:
        token: 认证 Token
        todo_id: 待办事项 ID
        **updates: 要更新的字段，包含：
        {
            "title": title,
            "description": description,
            "due_date": due_date,
            "estimated_duration": 30,  # 预计耗时（分钟）
            "importance": importance,
            "urgency": urgency,
            "groupID": "",  # 可以关联到某个日程组
        }
    """
    print("\n" + "="*60)
    print(f"✏️  示例 3: 更新待办事项")
    print("="*60)
    
    if not todo_id:
        print("⚠ 跳过: 没有可用的待办事项 ID")
        return False
    
    update_data = {"id": todo_id}
    update_data.update(updates)
    
    print(f"更新 TODO ID: {todo_id}")
    print(f"更新内容: {updates}")
    
    response = requests.post(
        f"{BASE_URL}/api/todos/update/",
        headers=get_headers(token),
        json=update_data
    )
    
    if response.status_code == 200:
        print(f"✓ 待办事项更新成功")
        return True
    else:
        print(f"✗ 更新失败: {response.status_code}")
        print(f"  响应: {response.text}")
        return False


def example_convert_todo_to_event(token, todo_id, start_time, end_time):
    """
    示例 4: 将待办事项转换为日程
    注意，转换完之后，在浏览器端本来会弹出提示，问是否要删除原 TO DO。这里则需要手动用 delete 删除之
    
    API: POST /api/todos/convert/
    
    Args:
        token: 认证 Token
        todo_id: 待办事项 ID
        start_time: 日程开始时间（'%Y-%m-%dT%H:%M:%S'）
        end_time: 日程结束时间（'%Y-%m-%dT%H:%M:%S'）
    """
    print("\n" + "="*60)
    print(f"🔄 示例 4: 将待办事项转换为日程")
    print("="*60)
    
    if not todo_id:
        print("⚠ 跳过: 没有可用的待办事项 ID")
        return False
    
    convert_data = {
        "id": todo_id,
        "start_time": start_time,
        "end_time": end_time
    }
    
    print(f"转换 TODO ID: {todo_id}")
    print(f"日程时间: {start_time} ~ {end_time}")
    
    response = requests.post(
        f"{BASE_URL}/api/todos/convert/",
        headers=get_headers(token),
        json=convert_data
    )
    
    if response.status_code == 200:
        result = response.json()
        event = result.get('event', {})
        print(f"✓ 转换成功")
        print(f"  新日程 ID: {event.get('id')}")
        print(f"  原 TODO 状态已更新为: converted")
        return True
    else:
        print(f"✗ 转换失败: {response.status_code}")
        print(f"  响应: {response.text}")
        return False


def example_delete_todo(token, todo_id):
    """
    示例 5: 删除待办事项
    
    API: POST /api/todos/delete/
    
    Args:
        token: 认证 Token
        todo_id: 待办事项 ID
    """
    print("\n" + "="*60)
    print(f"🗑️  示例 5: 删除待办事项")
    print("="*60)
    
    if not todo_id:
        print("⚠ 跳过: 没有可用的待办事项 ID")
        return False
    
    delete_data = {
        "id": todo_id
    }
    
    print(f"删除 TODO ID: {todo_id}")
    
    response = requests.post(
        f"{BASE_URL}/api/todos/delete/",
        headers=get_headers(token),
        json=delete_data
    )
    
    if response.status_code == 200:
        print(f"✓ 待办事项删除成功")
        return True
    else:
        print(f"✗ 删除失败: {response.status_code}")
        print(f"  响应: {response.text}")
        return False

