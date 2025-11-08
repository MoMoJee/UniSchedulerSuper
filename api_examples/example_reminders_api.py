"""
Reminders API 使用示例
展示如何使用 Token 认证调用 Reminders 相关的所有 API

前置条件：
1. 确保 Django 服务已启动（python manage.py runserver）
2. 已有用户账号，或运行示例时自动创建

使用方法：
    python api_examples/example_reminders_api.py
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


# ==================== Reminders API 示例 ====================

def example_get_reminders(token):
    """
    示例 1: 获取提醒列表
    
    API: GET /api/reminders/
    """
    print("\n" + "="*60)
    print("🔔 示例 1: 获取提醒列表")
    print("="*60)
    
    response = requests.get(
        f"{BASE_URL}/api/reminders/",
        headers=get_headers(token)
    )
    
    if response.status_code == 200:
        data = response.json()
        reminders = data.get('reminders', [])
        print(f"✓ 成功获取 {len(reminders)} 个提醒")
        
        if reminders:
            print("\n提醒列表:")
            for i, reminder in enumerate(reminders[:5], 1):  # 只显示前5个
                status_icon = "✅" if reminder.get('status') == 'completed' else "⏰"
                print(f"  {status_icon} {i}. {reminder.get('title')}")
                print(f"     时间: {reminder.get('trigger_time')}, 状态: {reminder.get('status')}")  # ✅ 修正: trigger_time
        
        return reminders
    else:
        print(f"✗ 获取失败: {response.status_code}")
        print(f"  响应: {response.text}")
        return []


def example_create_reminder(token, title, trigger_time, priority="normal", rrule="", content=""):
    """
    示例 2: 创建提醒

    API: POST /api/reminders/create/

    Args:
        token: 认证 Token
        title: 提醒标题
        trigger_time: 触发时间（ISO格式 %Y-%m-%dT%H:%M:%S）
        priority: 优先级（low/medium/high/critical，默认 medium）
        rrule: 重复规则（可选，空表示单次提醒）
        content: 提醒内容（可选）
    """
    print("\n" + "=" * 60)
    print(f"➕ 示例 2: 创建提醒 - {title}")
    print("=" * 60)

    reminder_data = {
        "title": title,
        "trigger_time": trigger_time,  # ✅ 修正: trigger_time
        "content": content,  # ✅ 修正: content
        "priority": priority,  # ✅ 修正: priority
        "rrule": rrule,  # ✅ 修正: rrule 字符串格式
    }

    print(f"标题: {title}")
    print(f"时间: {trigger_time}")
    print(f"优先级: {priority}")
    if rrule:
        print(f"重复规则: {rrule}")

    response = requests.post(
        f"{BASE_URL}/api/reminders/create/",
        headers=get_headers(token),
        json=reminder_data
    )

    if response.status_code == 200:
        result = response.json()
        print(f"✓ 提醒创建成功")
        print(f"  消息: {result.get('message')}")
        return True
    else:
        print(f"✗ 创建失败: {response.status_code}")
        print(f"  响应: {response.text}")
        return None


def example_create_recurring_reminder(token, title, trigger_time, rrule="FREQ=DAILY;INTERVAL=1;UNTIL=20251116T000000"):
    """
    示例 3: 创建重复提醒
    
    API: POST /api/reminders/create/
    
    Args:
        token: 认证 Token
        title: 提醒标题
        trigger_time: 首次触发时间（ISO格式）
        rrule: 重复规则（默认: 每天重复30次）
    """
    print("\n" + "="*60)
    print(f"🔄 示例 3: 创建重复提醒 - {title}")
    print("="*60)
    
    reminder_data = {
        "title": title,
        "trigger_time": trigger_time,  # ✅ 修正: trigger_time
        "content": f"这是一个重复提醒",  # ✅ 修正: content
        "priority": "normal",  # ✅ 修正: priority
        "rrule": rrule  # ✅ 修正: rrule 字符串格式
    }
    
    print(f"标题: {title}")
    print(f"首次时间: {trigger_time}")
    print(f"重复规则: {rrule}")
    
    response = requests.post(
        f"{BASE_URL}/api/reminders/create/",
        headers=get_headers(token),
        json=reminder_data
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"✓ 重复提醒创建成功")
        print(f"  消息: {result.get('message')}")
        return True
    else:
        print(f"✗ 创建失败: {response.status_code}")
        print(f"  响应: {response.text}")
        return None


def example_update_reminder(token, reminder_id, **updates):
    """
    示例 4: 更新提醒

    API: POST /api/reminders/update/

    Args:
        token: 认证 Token
        reminder_id: 提醒 ID
        **updates: 要更新的字段（支持: title, content, trigger_time, priority, status, rrule, rrule_change_scope(仅在 rrule 不为空时生效，且必须为 all 作用是把一个单次日程转换为重复日程）

    注意: 此API仅用于简单更新单次提醒或将单次提醒转为重复提醒
          复杂的重复提醒编辑请使用 /api/reminders/bulk-edit/
          ！如果用此API编辑重复日程的单例，会导致未知的后果

    示例：
    example_update_reminder(token="xxx", reminder_id="xxx", title="测试", priority="high", status="completed", rrule="FREQ=DAILY;INTERVAL=1;UNTIL=20251116T000000", rrule_change_scope="all")
    """
    print("\n" + "=" * 60)
    print(f"✏️  示例 4: 更新提醒")
    print("=" * 60)

    if not reminder_id:
        print("⚠ 跳过: 没有可用的提醒 ID")
        return False

    update_data = {"id": reminder_id}
    update_data.update(updates)

    print(f"更新提醒 ID: {reminder_id}")
    print(f"更新内容: {updates}")

    response = requests.post(
        f"{BASE_URL}/api/reminders/update/",
        headers=get_headers(token),
        json=update_data
    )

    if response.status_code == 200:
        print(f"✓ 提醒更新成功")
        return True
    else:
        print(f"✗ 更新失败: {response.status_code}")
        print(f"  响应: {response.text}")
        return False


def example_update_reminder_status(token, reminder_id, status, snooze_until=None):
    """
    示例 5: 更新提醒状态
    
    API: POST /api/reminders/update-status/
    
    Args:
        token: 认证 Token
        reminder_id: 提醒 ID
        status: 新状态（active/completed/dismissed/snoozed_15m/snoozed_1h/snoozed_1d/snoozed_custom）
        snooze_until: 延后到的时间（ISO格式，status为snoozed时使用）
    """
    print("\n" + "="*60)
    print(f"🔄 示例 5: 更新提醒状态为 {status}")
    print("="*60)
    
    if not reminder_id:
        print("⚠ 跳过: 没有可用的提醒 ID")
        return False
    
    status_data = {
        "id": reminder_id,
        "status": status
    }
    
    if snooze_until:
        status_data["snooze_until"] = snooze_until
    
    print(f"更新提醒 ID: {reminder_id}")
    print(f"新状态: {status}")
    if snooze_until:
        print(f"延后至: {snooze_until}")
    
    response = requests.post(
        f"{BASE_URL}/api/reminders/update-status/",
        headers=get_headers(token),
        json=status_data
    )
    
    if response.status_code == 200:
        print(f"✓ 状态更新成功")
        return True
    else:
        print(f"✗ 更新失败: {response.status_code}")
        print(f"  响应: {response.text}")
        return False


def example_snooze_reminder(token, reminder_id, snooze_minutes=10):
    """
    示例 6: 延后提醒
    
    使用 update-status API 延后提醒
    
    Args:
        token: 认证 Token
        reminder_id: 提醒 ID
        snooze_minutes: 延后分钟数（默认10分钟）
    """
    print("\n" + "="*60)
    print(f"⏰ 示例 6: 延后提醒 {snooze_minutes} 分钟")
    print("="*60)
    
    snooze_until = (datetime.now() + timedelta(minutes=snooze_minutes)).strftime("%Y-%m-%dT%H:%M:%S")
    
    return example_update_reminder_status(
        token,
        reminder_id,
        status="snoozed_15m" if snooze_minutes <= 15 else "snoozed_1h" if snooze_minutes <= 60 else "snoozed_1d",
        snooze_until=snooze_until
    )


def example_complete_reminder(token, reminder_id):
    """
    示例 7: 完成提醒
    
    使用 update-status API 标记提醒为已完成
    
    Args:
        token: 认证 Token
        reminder_id: 提醒 ID
    """
    print("\n" + "="*60)
    print(f"✅ 示例 7: 完成提醒")
    print("="*60)
    
    return example_update_reminder_status(
        token,
        reminder_id,
        status="completed"
    )


def example_dismiss_reminder(token, reminder_id):
    """
    示例 8: 忽略提醒
    
    使用 update-status API 忽略提醒
    
    Args:
        token: 认证 Token
        reminder_id: 提醒 ID
    """
    print("\n" + "="*60)
    print(f"❌ 示例 8: 忽略提醒")
    print("="*60)
    
    return example_update_reminder_status(
        token,
        reminder_id,
        status="dismissed"
    )


def example_delete_reminder(token, reminder_id):
    """
    示例 9: 删除提醒

    仅删除指定ID的提醒
    对于重复提醒的批量删除，建议使用 /api/reminders/bulk-edit/
    使用此 URL 删除重复提醒会导致未知的结果
    
    API: POST /api/reminders/delete/
    
    Args:
        token: 认证 Token
        reminder_id: 提醒 ID
    """
    print("\n" + "="*60)
    print(f"🗑️  示例 9: 删除提醒")
    print("="*60)
    
    if not reminder_id:
        print("⚠ 跳过: 没有可用的提醒 ID")
        return False
    
    delete_data = {
        "id": reminder_id
    }
    
    print(f"删除提醒 ID: {reminder_id}")
    
    response = requests.post(
        f"{BASE_URL}/api/reminders/delete/",
        headers=get_headers(token),
        json=delete_data
    )
    
    if response.status_code == 200:
        print(f"✓ 提醒删除成功")
        return True
    else:
        print(f"✗ 删除失败: {response.status_code}")
        print(f"  响应: {response.text}")
        return False


def example_batch_create_reminders(token):
    """
    示例 10: 批量创建提醒
    
    这是一个组合示例，展示如何批量创建多个提醒
    """
    print("\n" + "="*60)
    print("📋 示例 10: 批量创建提醒")
    print("="*60)
    
    now = datetime.now()
    
    # 定义多个提醒
    reminders_to_create = [
        {
            "title": "喝水提醒",
            "time": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S"),
            "content": "记得多喝水，保持健康",
            "priority": "low"
        },
        {
            "title": "会议提醒",
            "time": (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S"),
            "content": "下午的团队会议即将开始",
            "priority": "high"
        },
        {
            "title": "休息提醒",
            "time": (now + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S"),
            "content": "工作一段时间了，休息一下吧",
            "priority": "medium"
        }
    ]
    
    created_count = 0
    
    print(f"准备创建 {len(reminders_to_create)} 个提醒...")
    
    for reminder_data in reminders_to_create:
        success = example_create_reminder(
            token,
            reminder_data['title'],
            reminder_data['time'],
            reminder_data['priority'],
            "",  # rrule
            reminder_data['content']
        )
        if success:
            created_count += 1
    
    print(f"\n✓ 批量创建完成，成功创建 {created_count} 个提醒")
    return created_count


def example_reminder_workflow(token):
    """
    示例 11: 提醒工作流程
    
    这是一个综合示例，展示提醒的典型使用场景：
    1. 创建提醒
    2. 接收提醒后的不同操作：延后、完成、忽略
    
    注意: 由于API不返回创建的提醒ID，此示例仅演示流程，实际操作需要从获取列表中找到ID
    """
    print("\n" + "="*60)
    print("🔄 示例 11: 提醒工作流程")
    print("="*60)
    
    now = datetime.now()
    
    # 场景 1: 创建一个提醒并演示延后
    print("\n场景 1: 创建提醒（演示延后操作）")
    success1 = example_create_reminder(
        token,
        "API 示例：检查邮件",
        (now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S"),
        "medium",
        "",
        "检查重要邮件"
    )
    
    if success1:
        print("\n  💡 如需延后，可获取提醒列表找到ID后调用 example_snooze_reminder()")
    
    # 场景 2: 创建一个提醒并演示完成
    print("\n场景 2: 创建提醒（演示完成操作）")
    success2 = example_create_reminder(
        token,
        "API 示例：提交报告",
        (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S"),
        "high",
        "",
        "提交本周工作报告"
    )
    
    if success2:
        print("\n  💡 如需完成，可获取提醒列表找到ID后调用 example_complete_reminder()")
    
    # 场景 3: 创建一个提醒并演示忽略
    print("\n场景 3: 创建提醒（演示忽略操作）")
    success3 = example_create_reminder(
        token,
        "API 示例：更新软件",
        (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S"),
        "low",
        "",
        "检查并更新系统软件"
    )
    
    if success3:
        print("\n  💡 如需忽略，可获取提醒列表找到ID后调用 example_dismiss_reminder()")
    
    print("\n✓ 工作流程演示完成")
    print("💡 提示: 调用 example_get_reminders() 获取刚创建的提醒ID")
    
    created_count = sum([1 for s in [success1, success2, success3] if s])
    return created_count


def example_daily_reminders(token):
    """
    示例 12: 每日提醒设置
    
    展示如何设置每日重复的提醒
    """
    print("\n" + "="*60)
    print("📅 示例 12: 每日提醒设置")
    print("="*60)
    
    tomorrow = datetime.now() + timedelta(days=1)
    
    # 创建每日提醒
    daily_reminders = [
        {
            "title": "早晨提醒：查看今日日程",
            "time": tomorrow.replace(hour=8, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%S"),
            "rrule": "FREQ=DAILY;INTERVAL=1;COUNT=30"
        },
        {
            "title": "午餐提醒：休息时间",
            "time": tomorrow.replace(hour=12, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%S"),
            "rrule": "FREQ=DAILY;INTERVAL=1;COUNT=30"
        },
        {
            "title": "晚间提醒：总结今日工作",
            "time": tomorrow.replace(hour=18, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%S"),
            "rrule": "FREQ=DAILY;INTERVAL=1;COUNT=30"
        }
    ]
    
    created_count = 0
    
    for reminder_data in daily_reminders:
        success = example_create_recurring_reminder(
            token,
            f"API 示例：{reminder_data['title']}",
            reminder_data['time'],
            reminder_data['rrule']
        )
        if success:
            created_count += 1
    
    print(f"\n✓ 创建了 {created_count} 个每日提醒")
    return created_count


# ==================== 主程序 ====================

def main():
    """主程序：运行所有示例"""
    print("\n" + "🎯"*30)
    print("Reminders API 完整示例")
    print("🎯"*30)
    
    # 获取 Token
    token = get_auth_token()
    if not token:
        print("\n❌ 无法获取 Token，示例终止")
        print("💡 提示：请确保用户已创建，或修改配置区的用户名密码")
        return
    
    # 1. 获取现有提醒
    existing_reminders = example_get_reminders(token)
    
    # 2. 创建单个提醒
    now = datetime.now()
    single_reminder_created = example_create_reminder(
        token,
        "API 示例：重要会议提醒",
        (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S"),
        "high",
        "",
        "参加下午的项目评审会议"
    )
    
    # 3. 创建重复提醒
    recurring_reminder_created = example_create_recurring_reminder(
        token,
        "API 示例：每日站会",
        (now + timedelta(days=1)).replace(hour=9, minute=30, second=0).strftime("%Y-%m-%dT%H:%M:%S"),
        "FREQ=DAILY;INTERVAL=1;COUNT=30"
    )
    
    # 4. 更新提醒（需要先获取ID）
    print("\n" + "="*60)
    print("💡 提示：更新提醒需要先获取提醒ID")
    print("   请先调用 example_get_reminders() 获取列表")
    print("="*60)
    
    # 5. 批量创建提醒
    batch_count = example_batch_create_reminders(token)
    
    # 6. 提醒工作流程
    workflow_count = example_reminder_workflow(token)
    
    # 7. 每日提醒设置
    daily_count = example_daily_reminders(token)
    
    # 8. 清理说明
    print("\n" + "="*60)
    print("🧹 清理示例数据")
    print("="*60)
    
    total_created = sum([
        1 if single_reminder_created else 0,
        1 if recurring_reminder_created else 0,
        batch_count,
        workflow_count,
        daily_count
    ])
    
    print(f"本次示例共创建了约 {total_created} 个提醒系列")
    print("💡 提示: 要删除这些提醒，请:")
    print("   1. 调用 example_get_reminders(token) 获取提醒列表")
    print("   2. 找到示例提醒的ID（标题包含'API 示例'）")
    print("   3. 调用 example_delete_reminder(token, reminder_id) 删除")
    
    # 最终结果
    print("\n" + "="*60)
    print("✅ 所有示例执行完成！")
    print("="*60)
    print("\n💡 API 使用要点：")
    print("  📌 字段名称对照:")
    print("     ✅ trigger_time (触发时间)")
    print("     ✅ content (内容/描述)")
    print("     ✅ priority (优先级: low/medium/high/critical)")
    print("     ✅ rrule (重复规则: FREQ=DAILY;INTERVAL=1)")
    print("\n  📌 状态管理:")
    print("     - active: 激活")
    print("     - completed: 已完成")
    print("     - dismissed: 已忽略")
    print("     - snoozed_15m/1h/1d: 延后")
    print("\n  📌 API 端点:")
    print("     GET  /api/reminders/ - 获取提醒列表")
    print("     POST /api/reminders/create/ - 创建提醒")
    print("     POST /api/reminders/update/ - 更新单次提醒")
    print("     POST /api/reminders/update-status/ - 更新状态")
    print("     POST /api/reminders/delete/ - 删除提醒")
    print("     POST /api/reminders/bulk-edit/ - 批量编辑重复提醒")


if __name__ == "__main__":
    main()
