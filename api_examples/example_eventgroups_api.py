"""
Event Groups API 使用示例
展示如何使用 Token 认证调用 Event Groups 相关的所有 API

前置条件：
1. 确保 Django 服务已启动（python manage.py runserver）
2. 已有用户账号，或运行示例时自动创建

使用方法：
    python api_examples/example_eventgroups_api.py
"""

import requests
import json

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


# ==================== Event Groups API 示例 ====================

def example_get_event_groups(token):
    """
    示例 1: 获取日程组列表
    
    API: GET /get_calendar/events/
    注意：日程组信息包含在 events_groups 字段中
    """
    print("\n" + "="*60)
    print("📁 示例 1: 获取日程组列表")
    print("="*60)
    
    response = requests.get(
        f"{BASE_URL}/get_calendar/events/",
        headers=get_headers(token)
    )
    
    if response.status_code == 200:
        data = response.json()
        groups = data.get('events_groups', [])
        print(f"✓ 成功获取 {len(groups)} 个日程组")
        
        if groups:
            print("\n现有日程组:")
            for i, group in enumerate(groups, 1):
                print(f"  {i}. {group.get('name')} - {group.get('description')}")
                print(f"     颜色: {group.get('color')}, ID: {group.get('id')}")
        else:
            print("  当前没有日程组")
        
        return groups
    else:
        print(f"✗ 获取失败: {response.status_code}")
        print(f"  响应: {response.text}")
        return []


def example_create_event_group(token, name, description, color):
    """
    示例 2: 创建日程组
    注意！服务器端不会对某些创建失败 进行报错，因此执行此创建操作后，务必用 example_get_event_groups 或相同功能的函数进行验证！
    API: POST /get_calendar/create_events_group/
    
    Args:
        token: 认证 Token
        name: 组名
        description: 描述
        color: 颜色代码（如 #FF5733）
    """
    print("\n" + "="*60)
    print(f"➕ 示例 2: 创建日程组 - {name}")
    print("="*60)
    
    group_data = {
        "name": name,
        "description": description,
        "color": color
    }
    
    print(f"组名: {name}")
    print(f"描述: {description}")
    print(f"颜色: {color}")
    
    response = requests.post(
        f"{BASE_URL}/get_calendar/create_events_group/",
        headers=get_headers(token),
        json=group_data
    )
    
    if response.status_code == 200:
        print(f"✓ 日程组创建成功")
        
        # 获取最新的组列表，找到刚创建的组
        groups = example_get_event_groups(token)
        for group in groups:
            if group.get('name') == name:
                return group.get('id')
        return None
    else:
        print(f"✗ 创建失败: {response.status_code}")
        print(f"  响应: {response.text}")
        return None


def example_update_event_group(token, group_id, new_title, new_description, new_color):
    """
    示例 3: 更新日程组
    注意！服务器端不会对传入不存在于数据库中的 id 进行报错，因此执行此更新操作后，务必用 example_get_event_groups 或相同功能的函数进行验证！
    API: POST /get_calendar/update_events_group/
    
    Args:
        token: 认证 Token
        group_id: 日程组 ID
        new_title: 新标题
        new_description: 新描述
        new_color: 新颜色
    """
    print("\n" + "="*60)
    print(f"✏️  示例 3: 更新日程组")
    print("="*60)
    
    if not group_id:
        print("⚠ 跳过: 没有可用的日程组 ID")
        return False
    
    update_data = {
        "groupID": group_id,
        "title": new_title,
        "description": new_description,
        "color": new_color
    }
    
    print(f"更新组 ID: {group_id}")
    print(f"新标题: {new_title}")
    print(f"新描述: {new_description}")
    print(f"新颜色: {new_color}")
    
    response = requests.post(
        f"{BASE_URL}/get_calendar/update_events_group/",
        headers=get_headers(token),
        json=update_data
    )
    
    if response.status_code == 200:
        print(f"✓ 日程组更新成功")
        return True
    else:
        print(f"✗ 更新失败: {response.status_code}")
        print(f"  响应: {response.text}")
        return False


def example_delete_event_groups(token, group_ids, delete_events=False):
    """
    示例 4: 删除日程组
    注意！服务器端不会对传入不存在于数据库中的 id 进行报错，因此执行此删除操作后，务必用 example_get_event_groups 或相同功能的函数进行验证！
    API: POST /get_calendar/delete_event_groups/
    
    Args:
        token: 认证 Token
        group_ids: 日程组 ID 列表
        delete_events: 是否同时删除组内的日程
    """
    print("\n" + "="*60)
    print(f"🗑️  示例 4: 删除日程组")
    print("="*60)
    
    if not group_ids:
        print("⚠ 跳过: 没有可用的日程组 ID")
        return False
    
    delete_data = {
        "groupIds": group_ids,
        "deleteEvents": delete_events
    }
    
    print(f"删除组 ID: {group_ids}")
    print(f"同时删除组内日程: {'是' if delete_events else '否'}")
    
    response = requests.post(
        f"{BASE_URL}/get_calendar/delete_event_groups/",
        headers=get_headers(token),
        json=delete_data
    )
    
    if response.status_code == 200:
        print(f"✓ 日程组删除成功")
        print(f"  删除了 {len(group_ids)} 个日程组")
        return True
    else:
        print(f"✗ 删除失败: {response.status_code}")
        print(f"  响应: {response.text}")
        return False


def example_batch_create_groups(token):
    """
    示例 5: 批量创建多个日程组
    
    这是一个组合示例，展示如何批量创建多个相关的日程组
    """
    print("\n" + "="*60)
    print("🎨 示例 5: 批量创建日程组")
    print("="*60)
    
    # 定义多个日程组
    groups_to_create = [
        {
            "name": "工作",
            "description": "工作相关的所有日程",
            "color": "#FF6B6B"  # 红色
        },
        {
            "name": "学习",
            "description": "学习、培训、阅读等",
            "color": "#4ECDC4"  # 青色
        },
        {
            "name": "个人",
            "description": "个人事务和休闲活动",
            "color": "#45B7D1"  # 蓝色
        },
        {
            "name": "健康",
            "description": "运动、健身、体检等",
            "color": "#96CEB4"  # 绿色
        },
        {
            "name": "家庭",
            "description": "家庭活动和聚会",
            "color": "#FFEAA7"  # 黄色
        }
    ]
    
    created_ids = []
    
    print(f"准备创建 {len(groups_to_create)} 个日程组...")
    
    for group_data in groups_to_create:
        group_id = example_create_event_group(
            token,
            group_data['name'],
            group_data['description'],
            group_data['color']
        )
        if group_id:
            created_ids.append(group_id)
    
    print(f"\n✓ 批量创建完成，成功创建 {len(created_ids)} 个日程组")
    return created_ids


def example_organize_groups(token):
    """
    示例 6: 日程组管理示例
    
    这是一个综合示例，展示日程组的典型使用场景：
    1. 查看现有分组
    2. 创建新分组
    3. 更新分组信息
    4. 删除不需要的分组
    """
    print("\n" + "="*60)
    print("📊 示例 6: 日程组管理场景")
    print("="*60)
    
    # 1. 查看现有分组
    print("\n步骤 1: 查看现有分组")
    existing_groups = example_get_event_groups(token)
    
    # 2. 创建一个临时测试分组
    print("\n步骤 2: 创建临时测试分组")
    test_group_id = example_create_event_group(
        token,
        "测试分组",
        "这是一个临时的测试分组",
        "#E74C3C"
    )
    
    # 3. 更新分组信息
    if test_group_id:
        print("\n步骤 3: 更新分组信息")
        example_update_event_group(
            token,
            test_group_id,
            "测试分组（已更新）",
            "更新后的描述：用于演示更新功能",
            "#9B59B6"
        )
    
    # 4. 查看更新后的分组列表
    print("\n步骤 4: 查看更新后的分组")
    updated_groups = example_get_event_groups(token)
    
    # 5. 删除测试分组（清理）
    if test_group_id:
        print("\n步骤 5: 清理测试分组")
        example_delete_event_groups(
            token,
            [test_group_id],
            delete_events=False
        )
    
    print("\n✓ 日程组管理场景演示完成")


# ==================== 主程序 ====================

def main():
    """主程序：运行所有示例"""
    print("\n" + "🎯"*30)
    print("Event Groups API 完整示例")
    print("🎯"*30)
    
    # 获取 Token
    token = get_auth_token()
    if not token:
        print("\n❌ 无法获取 Token，示例终止")
        print("💡 提示：请确保用户已创建，或修改配置区的用户名密码")
        return
    
    # 1. 获取现有日程组
    existing_groups = example_get_event_groups(token)
    
    # 2. 创建单个日程组
    work_group_id = example_create_event_group(
        token,
        "API 示例：工作",
        "工作相关日程",
        "#FF6B6B"
    )
    
    # 3. 更新日程组
    if work_group_id:
        example_update_event_group(
            token,
            work_group_id,
            "API 示例：工作（重要）",
            "工作相关的重要日程",
            "#E74C3C"
        )
    
    # 4. 批量创建多个日程组
    batch_ids = example_batch_create_groups(token)
    
    # 5. 日程组管理场景演示
    example_organize_groups(token)
    
    # 6. 清理示例数据（可选）
    print("\n" + "="*60)
    print("🧹 清理示例数据")
    print("="*60)
    
    all_cleanup_ids = []
    if work_group_id:
        all_cleanup_ids.append(work_group_id)
    all_cleanup_ids.extend(batch_ids)
    
    if all_cleanup_ids:
        print(f"准备清理 {len(all_cleanup_ids)} 个示例日程组...")
        example_delete_event_groups(token, all_cleanup_ids, delete_events=False)
    
    # 最终结果
    print("\n" + "="*60)
    print("✅ 所有示例执行完成！")
    print("="*60)
    print("\n💡 提示：")
    print("  - 可以修改配置区的 BASE_URL、USERNAME、PASSWORD")
    print("  - 可以单独运行任意示例函数")
    print("  - 日程组可以用于组织和分类日程")
    print("  - 删除日程组时可以选择是否同时删除组内日程")


if __name__ == "__main__":
    main()
