"""
测试回滚机制 - 验证只追踪特定 keys

测试场景：
1. Agent 创建日程
2. 用户修改配置（如主题）
3. 回滚 Agent 操作
4. 验证日程被删除，配置未受影响
"""

import os
import sys
import django

# 设置 Django 环境
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'UniSchedulerSuper.settings')
django.setup()

from django.contrib.auth.models import User
from core.models import UserData
from agent_service.models import AgentTransaction
import reversion
import json

def test_rollback_isolation():
    """测试回滚隔离性 - 确保不误伤用户配置"""
    
    print("=" * 60)
    print("测试回滚机制 - 配置隔离性")
    print("=" * 60)
    
    # 1. 获取或创建测试用户
    user, created = User.objects.get_or_create(
        username='test_rollback_user',
        defaults={'email': 'test@example.com'}
    )
    if created:
        user.set_password('testpass123')
        user.save()
        print(f"✅ 创建测试用户: {user.username}")
    else:
        print(f"✅ 使用现有测试用户: {user.username}")
    
    # 2. 初始化数据
    print("\n--- 步骤 1: 初始化数据 ---")
    
    # 创建 events (会被追踪)
    events_data, _ = UserData.objects.get_or_create(
        user=user,
        key='events',
        defaults={'value': json.dumps([])}
    )
    events_data.value = json.dumps([])
    events_data.save()
    print(f"✅ 初始化 events: {events_data.value}")
    
    # 创建 user_preference (不会被追踪)
    pref_data, _ = UserData.objects.get_or_create(
        user=user,
        key='user_preference',
        defaults={'value': json.dumps({'theme': 'light'})}
    )
    pref_data.value = json.dumps({'theme': 'light'})
    pref_data.save()
    print(f"✅ 初始化 user_preference: {pref_data.value}")
    
    # 3. 模拟 Agent 创建日程（会创建快照）
    print("\n--- 步骤 2: 模拟 Agent 创建日程 ---")
    
    TRACKED_KEYS = ['todos', 'events', 'reminders', 'events_rrule_series', 'rrule_series_storage', 'outport_calendar_data']
    
    with reversion.create_revision():
        reversion.set_user(user)
        reversion.set_comment("Before: create_event")
        
        # 只追踪特定 keys（模拟优化后的逻辑）
        user_data_objects = UserData.objects.filter(user=user, key__in=TRACKED_KEYS)
        for ud in user_data_objects:
            reversion.add_to_revision(ud)
        
        print(f"✅ 创建快照，追踪了 {user_data_objects.count()} 个对象")
        for ud in user_data_objects:
            print(f"   - {ud.key}")
    
    # 获取刚创建的 Revision
    revision = reversion.models.Revision.objects.filter(user=user).latest('date_created')
    print(f"✅ Revision ID: {revision.id}")
    
    # 修改 events（添加一个日程）
    current_events = json.loads(events_data.value)
    current_events.append({
        'id': 'test_event_1',
        'title': '测试日程',
        'start': '2026-02-06T14:00:00',
        'end': '2026-02-06T15:00:00'
    })
    events_data.value = json.dumps(current_events)
    events_data.save()
    print(f"✅ 添加日程: {len(current_events)} 个日程")
    
    # 创建事务记录
    trans = AgentTransaction.objects.create(
        session_id='test_session_123',
        user=user,
        action_type='create_event',
        revision_id=revision.id,
        metadata={'tool_call_id': 'test_call_123'},
        description='测试：创建日程',
        is_rolled_back=False
    )
    print(f"✅ 创建事务记录 ID: {trans.id}")
    
    # 4. 用户修改配置（不会被追踪）
    print("\n--- 步骤 3: 用户修改配置 ---")
    pref_data.value = json.dumps({'theme': 'dark', 'language': 'zh-CN'})
    pref_data.save()
    print(f"✅ 修改 user_preference: {pref_data.value}")
    print(f"   注意：此修改没有创建 Revision（未被追踪）")
    
    # 5. 执行回滚
    print("\n--- 步骤 4: 执行回滚 ---")
    
    # 刷新数据
    events_data.refresh_from_db()
    pref_data.refresh_from_db()
    
    print(f"回滚前:")
    print(f"  - events: {events_data.value}")
    print(f"  - user_preference: {pref_data.value}")
    
    # 执行回滚
    try:
        revision.revert()
        trans.is_rolled_back = True
        trans.save()
        print(f"✅ 回滚成功")
    except Exception as e:
        print(f"❌ 回滚失败: {e}")
        return
    
    # 6. 验证结果
    print("\n--- 步骤 5: 验证结果 ---")
    
    # 刷新数据
    events_data.refresh_from_db()
    pref_data.refresh_from_db()
    
    print(f"回滚后:")
    print(f"  - events: {events_data.value}")
    print(f"  - user_preference: {pref_data.value}")
    
    # 验证
    events_after = json.loads(events_data.value)
    pref_after = json.loads(pref_data.value)
    
    events_empty = len(events_after) == 0
    theme_is_dark = pref_after.get('theme') == 'dark'
    
    print("\n" + "=" * 60)
    print("测试结果:")
    print("=" * 60)
    
    if events_empty:
        print("✅ events 已回滚到空列表（正确）")
    else:
        print(f"❌ events 未正确回滚: {events_after}")
    
    if theme_is_dark:
        print("✅ user_preference 保持 'dark'（正确，未被误伤）")
    else:
        print(f"❌ user_preference 被误回滚: {pref_after}")
    
    if events_empty and theme_is_dark:
        print("\n🎉 测试通过！回滚机制正确隔离了追踪和非追踪的 keys")
    else:
        print("\n⚠️ 测试失败，请检查实现")
    
    # 7. 清理
    print("\n--- 清理测试数据 ---")
    AgentTransaction.objects.filter(session_id='test_session_123').delete()
    print("✅ 清理完成")


def test_revision_content():
    """测试 Revision 内容 - 查看追踪了哪些对象"""
    
    print("\n" + "=" * 60)
    print("检查 Revision 追踪的对象")
    print("=" * 60)
    
    user = User.objects.filter(username='test_rollback_user').first()
    if not user:
        print("❌ 测试用户不存在，请先运行 test_rollback_isolation()")
        return
    
    # 获取最新的 Revision
    revision = reversion.models.Revision.objects.filter(user=user).latest('date_created')
    
    print(f"\nRevision ID: {revision.id}")
    print(f"创建时间: {revision.date_created}")
    print(f"注释: {revision.comment}")
    
    print(f"\n追踪的对象:")
    versions = revision.version_set.all()
    for version in versions:
        obj = version.object
        if hasattr(obj, 'key'):
            print(f"  - UserData(key='{obj.key}')")
        else:
            print(f"  - {version.object_repr}")
    
    print(f"\n共追踪了 {versions.count()} 个对象")


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'check':
        # 只检查 Revision 内容
        test_revision_content()
    else:
        # 完整测试
        test_rollback_isolation()
