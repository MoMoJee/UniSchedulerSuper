"""
Events API 使用示例（已修正）
展示如何使用 Token 认证调用 Events 相关的所有 API

基于实际的 URL 配置：
- GET  /get_calendar/events/ - 获取日程列表
- POST /events/create_event/ - 创建日程（单个和重复）
- POST /get_calendar/update_events/ - 更新日程
- POST /api/events/bulk-edit/ - 批量编辑重复日程
- POST /get_calendar/delete_event/ - 删除日程

前置条件：
1. 确保 Django 服务已启动（python manage.py runserver）
2. 已有用户账号：test_user / test_password

使用方法：
    python api_examples/example_events_api_fixed.py
"""

import requests
import json
from datetime import datetime, timedelta

# ==================== 配置区 ====================
BASE_URL = "http://127.0.0.1:8000"
USERNAME = "test_user"
PASSWORD = "test_password"

# ==================== 辅助函数 ====================

def get_auth_token(username=USERNAME, password=PASSWORD):
    """获取认证 Token"""
    print("\n" + "="*60)
    print("🔐 获取认证 Token")
    print("="*60)
    
    response = requests.post(
        f"{BASE_URL}/api/auth/login/",
        json={"username": username, "password": password}
    )
    
    if response.status_code == 200:
        token = response.json().get('token')
        print(f"✓ Token 获取成功")
        return token
    else:
        print(f"✗ 登录失败 (状态码: {response.status_code})")
        return None


def get_headers(token):
    """生成请求头"""
    return {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json"
    }


# ==================== Events API 示例 ====================

def example_get_events(token):
    """
    示例 1: 获取日程列表
    
    API: GET /get_calendar/events/
    """
    print("\n" + "="*60)
    print("📅 示例 1: 获取日程列表")
    print("="*60)
    
    response = requests.get(
        f"{BASE_URL}/get_calendar/events/",
        headers=get_headers(token)
    )
    
    if response.status_code == 200:
        data = response.json()
        events = data.get('events', [])
        print(f"✓ 成功获取 {len(events)} 个日程")
        
        if events:
            print("\n前 3 个日程:")
            for i, event in enumerate(events[:3], 1):
                is_recurring = "重复" if event.get('is_recurring') else "单个"
                print(f"  {i}. [{is_recurring}] {event.get('title')}")
                print(f"     {event.get('start')} ~ {event.get('end')}")
        
        return events
    else:
        print(f"✗ 获取失败: {response.status_code}")
        return []


def example_create_single_event(token):
    """
    示例 2: 创建单个日程
    
    API: POST /events/create_event/
    """
    print("\n" + "="*60)
    print("➕ 示例 2: 创建单个日程")
    print("="*60)
    
    # 准备日程数据
    tomorrow = datetime.now() + timedelta(days=1)
    event_data = {
        "title": "API 示例：团队会议",
        "start": tomorrow.strftime("%Y-%m-%dT10:00:00"),
        "end": tomorrow.strftime("%Y-%m-%dT11:00:00"),
        "description": "讨论项目进度和下一步计划",
        "importance": "important",
        "urgency": "urgent",
        "groupID": "1",  # 配合 eventgroup_api 中的获取 groupID 的功能使用
        "ddl": ""
    }
    
    print(f"创建日程: {event_data['title']}")
    print(f"时间: {event_data['start']} ~ {event_data['end']}")
    
    response = requests.post(
        f"{BASE_URL}/events/create_event/",
        headers=get_headers(token),
        json=event_data
    )
    
    if response.status_code == 200:
        result = response.json()
        event_id = result.get('event', {}).get('id')
        print(f"✓ 日程创建成功")
        print(f"  ID: {event_id}")
        return event_id
    else:
        print(f"✗ 创建失败: {response.status_code}")
        print(f"  响应: {response.text[:200]}")
        return None


def example_create_recurring_event(token):
    """
    示例 3: 创建重复日程
    
    API: POST /events/create_event/
    注意：重复日程也使用同一个端点，通过 rrule 字段区分
    """
    print("\n" + "="*60)
    print("🔄 示例 3: 创建重复日程")
    print("="*60)
    
    # 创建每周重复的日程
    tomorrow = datetime.now() + timedelta(days=1)
    event_data = {
        "title": "API 示例：每周例会",
        "start": tomorrow.strftime("%Y-%m-%dT14:00:00"),
        "end": tomorrow.strftime("%Y-%m-%dT15:00:00"),
        "description": "每周固定例会",
        "importance": "important",
        "urgency": "not-urgent",
        "groupID": "1",
        "rrule": "FREQ=WEEKLY;INTERVAL=1;COUNT=5",  # 每周重复5次
        "ddl": ""
    }
    
    print(f"创建重复日程: {event_data['title']}")
    print(f"重复规则: {event_data['rrule']}")
    
    response = requests.post(
        f"{BASE_URL}/events/create_event/",
        headers=get_headers(token),
        json=event_data
    )
    
    if response.status_code == 200:
        result = response.json()
        event = result.get('event', {})
        series_id = event.get('series_id')
        event_id = event.get('id')
        print(f"✓ 重复日程创建成功")
        print(f"  系列 ID: {series_id}")
        print(f"  第一个实例 ID: {event_id}")
        return series_id, event_id
    else:
        print(f"✗ 创建失败: {response.status_code}")
        print(f"  响应: {response.text[:200]}")
        return None, None


def example_update_single_event(token, event_id):
    """
    示例 4: 更新单个日程
    
    API: POST /get_calendar/update_events/
    """
    print("\n" + "="*60)
    print("✏️  示例 4: 更新单个日程")
    print("="*60)
    
    if not event_id:
        print("⚠ 跳过: 没有可用的日程 ID")
        return False
    
    # 准备更新数据
    tomorrow = datetime.now() + timedelta(days=1)
    new_start = tomorrow.replace(hour=15, minute=0, second=0)
    new_end = new_start + timedelta(hours=1)
    
    update_data = {
        "eventId": event_id,
        "title": "API 示例：团队会议（已更新）",
        "start": new_start.strftime("%Y-%m-%dT%H:%M:%S"),
        "end": new_end.strftime("%Y-%m-%dT%H:%M:%S"),
        "description": "更新后的描述：新增性能优化议题",
        "importance": "not-important",
        "urgency": "not-urgent"
    }

    # 如果要把单个日程转换为重复日程，只需要加上 rrule 参数即可
    rrule_update_data = {
        "eventId": event_id,
        "rrule": "FREQ=DAILY;INTERVAL=1;COUNT=10",  # 注意千万不要在末尾加分号，主包测试了两个小时才发现写错了
        "title": "API 示例：团队会议（每日）",
        "start": new_start.strftime("%Y-%m-%dT%H:%M:%S"),
        "end": new_end.strftime("%Y-%m-%dT%H:%M:%S"),
        "description": "更新后的描述：新增性能优化议题",
        "importance": "not-important",
        "urgency": "not-urgent"
    }
    
    print(f"更新日程 ID: {event_id}")
    print(f"新标题: {update_data['title']}")
    print(f"新时间: {new_start.strftime('%H:%M')}")
    
    response = requests.post(
        f"{BASE_URL}/get_calendar/update_events/",
        headers=get_headers(token),
        json=update_data
    )
    
    if response.status_code == 200:
        print(f"✓ 日程更新成功")
        return True
    else:
        print(f"✗ 更新失败: {response.status_code}")
        print(f"  响应: {response.text[:200]}")
        return False


def example_bulk_edit_recurring(token, series_id, event_id):
    """
    示例 5: 批量编辑重复日程（所有实例）
    
    API: POST /api/events/bulk-edit/
    """
    print("\n" + "="*60)
    print("🔄 示例 5: 批量编辑重复日程（所有实例）")
    print("="*60)
    
    if not series_id or not event_id:
        print("⚠ 跳过: 没有可用的系列 ID")
        return False
    
    update_data_all = {
        "event_id": event_id,
        "series_id": series_id,
        "operation": "edit",
        "edit_scope": "all",
        "title": "API 示例：每周例会（全部已更新）",
        "description": "批量更新后的描述",
        "importance": "important",
        "urgency": "urgent"
    }
    # all 模式下，event_id 理论上只要指定随便一个 日程序列之中的日程 的ID 即可

    update_data_single = {
        "event_id": event_id,
        "series_id": series_id,
        "operation": "edit",
        "edit_scope": "single",
        "title": "API 示例：每周重要例会（单独更新）",
        "description": "单独更新重要会议",
        "importance": "important",
        "urgency": "urgent"
    }
    # single 模式，会将选中的 event_id 的日程从原系列中分离，series_id，被清除不再参与后续的重复日程变化。同时，为了避免其所在的原日程序列检测到少了这么一个日程后自动生成补全，因此还会自动给其余的日程 rrule 加上一个 EXDATE 参数

    update_data_future = {
        "event_id": event_id,
        "series_id": series_id,
        "operation": "edit",
        "edit_scope": "all",
        "title": "API 示例：每周例会（已更新选中的 event_id 及以后的日程的相关参数）",
        "description": "批量更新后的描述",
        "importance": "important",
        "urgency": "urgent",
        "rrule": "FREQ=WEEKLY;INTERVAL=1;COUNT=5"
    }
    # future 模式，修改给定的 event_id 及以后所有日程。
    # 如果没有给出 rrule 参数，那么被修改的日程仍旧在原序列中。
    # 如果给出了 rrule 参数，那么会删除系列中原先之后所有的日程，然后用新规则创建后续的日程，创建新序列。原日程序列会在此被加上截断规则，并删除后续

    update_data_from_time = {
        "event_id": event_id,
        "series_id": series_id,
        "operation": "edit",
        "edit_scope": "from_time",
        "from_time": datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        "title": "API 示例：每周例会（已更新选中的 time 及以后的日程的相关参数）",
        "description": "from time 更新",
        "importance": "important",
        "urgency": "urgent",
        "rrule": "FREQ=WEEKLY;INTERVAL=1;COUNT=5"
    }
    
    print(f"更新系列 ID: {series_id}")
    print(f"编辑范围: 所有实例")
    
    response = requests.post(
        f"{BASE_URL}/api/events/bulk-edit/",
        headers=get_headers(token),
        json=update_data_all
    )
    
    if response.status_code == 200:
        print(f"✓ 批量编辑成功")
        return True
    else:
        print(f"✗ 编辑失败: {response.status_code}")
        print(f"  响应: {response.text[:200]}")
        return False


def example_delete_single_event(token, event_id):
    """
    示例 6: 删除单个日程
    
    API: POST /get_calendar/delete_event/
    """
    print("\n" + "="*60)
    print("🗑️  示例 6: 删除单个日程")
    print("="*60)
    
    if not event_id:
        print("⚠ 跳过: 没有可用的日程 ID")
        return False
    
    delete_data = {
        "eventId": event_id,
        "delete_scope": "single"
    }
    
    print(f"删除日程 ID: {event_id}")
    
    response = requests.post(
        f"{BASE_URL}/get_calendar/delete_event/",
        headers=get_headers(token),
        json=delete_data
    )
    
    if response.status_code == 200:
        print(f"✓ 日程删除成功")
        return True
    else:
        print(f"✗ 删除失败: {response.status_code}")
        print(f"  响应: {response.text[:200]}")
        return False


def example_delete_recurring_series(token, series_id, event_id):
    """
    示例 7: 删除整个重复日程系列
    
    API: POST /get_calendar/delete_event/
    """
    print("\n" + "="*60)
    print("🗑️  示例 7: 删除重复日程系列")
    print("="*60)
    
    if not series_id or not event_id:
        print("⚠ 跳过: 没有可用的系列 ID")
        return False
    
    delete_data = {
        "eventId": event_id,
        "series_id": series_id,
        "delete_scope": "all"
    }
    
    print(f"删除系列 ID: {series_id}")
    print(f"删除范围: 所有实例")
    
    response = requests.post(
        f"{BASE_URL}/get_calendar/delete_event/",
        headers=get_headers(token),
        json=delete_data
    )
    
    if response.status_code == 200:
        print(f"✓ 重复日程系列删除成功")
        return True
    else:
        print(f"✗ 删除失败: {response.status_code}")
        print(f"  响应: {response.text[:200]}")
        return False


def example_create_event_with_ddl(token):
    """
    示例 8: 创建带截止时间的日程
    
    API: POST /events/create_event/
    """
    print("\n" + "="*60)
    print("⏰ 示例 8: 创建带截止时间的日程")
    print("="*60)
    
    # 准备日程数据
    future_date = datetime.now() + timedelta(days=3)
    event_data = {
        "title": "API 示例：项目截止日",
        "start": future_date.strftime("%Y-%m-%dT09:00:00"),
        "end": future_date.strftime("%Y-%m-%dT12:00:00"),
        "description": "项目必须在此时间前完成",
        "importance": "important",
        "urgency": "urgent",
        "groupID": "1",
        "ddl": future_date.strftime("%Y-%m-%dT12:00:00")
    }
    
    print(f"创建日程: {event_data['title']}")
    print(f"截止时间: {event_data['ddl']}")
    
    response = requests.post(
        f"{BASE_URL}/events/create_event/",
        headers=get_headers(token),
        json=event_data
    )
    
    if response.status_code == 200:
        result = response.json()
        event_id = result.get('event', {}).get('id')
        print(f"✓ 带DDL的日程创建成功")
        print(f"  ID: {event_id}")
        return event_id
    else:
        print(f"✗ 创建失败: {response.status_code}")
        print(f"  响应: {response.text[:200]}")
        return None


# ==================== 主程序 ====================

def main():
    """主程序：运行所有示例"""
    print("\n" + "🎯"*30)
    print(" "*25 + "Events API 完整示例")
    print("🎯"*30)
    
    # 获取 Token
    token = get_auth_token()
    if not token:
        print("\n❌ 无法获取 Token，示例终止")
        print("💡 提示：请确保用户已创建，或修改配置区的用户名密码")
        return
    
    # 1. 获取现有日程列表
    print("\n【第一部分：查询操作】")
    existing_events = example_get_events(token)
    
    # 2. 创建单个日程
    print("\n【第二部分：创建操作】")
    single_event_id = example_create_single_event(token)
    
    # 3. 创建重复日程
    recurring_series_id, recurring_event_id = example_create_recurring_event(token)
    
    # 4. 创建带DDL的日程
    ddl_event_id = example_create_event_with_ddl(token)
    
    # 5. 更新单个日程
    print("\n【第三部分：更新操作】")
    if single_event_id:
        example_update_single_event(token, single_event_id)
    
    # 6. 批量编辑重复日程（所有实例）
    if recurring_series_id and recurring_event_id:
        example_bulk_edit_recurring(token, recurring_series_id, recurring_event_id)
    
    # 7. 删除单个日程
    print("\n【第四部分：删除操作】")
    if ddl_event_id:
        example_delete_single_event(token, ddl_event_id)
    
    # 8. 删除重复日程系列
    if recurring_series_id and recurring_event_id:
        example_delete_recurring_series(token, recurring_series_id, recurring_event_id)
    
    # 9. 最后再次获取日程列表，查看变化
    print("\n【第五部分：最终状态】")
    final_events = example_get_events(token)
    
    # 总结
    print("\n" + "="*60)
    print("✅ 示例执行完成")
    print("="*60)
    print(f"初始日程数: {len(existing_events) if existing_events else 0}")
    print(f"最终日程数: {len(final_events) if final_events else 0}")
    print("\n💡 提示：可以打开浏览器访问 http://127.0.0.1:8000 查看日程")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  程序被用户中断")
    except Exception as e:
        print(f"\n\n❌ 发生错误: {str(e)}")
        import traceback
        traceback.print_exc()
