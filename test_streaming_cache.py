"""
测试流式缓存功能
运行方法：在服务器运行时执行此脚本，检查后端是否正确缓存消息
"""
import asyncio

# 模拟检查缓存状态
def check_cache_status():
    """检查缓存字典"""
    from agent_service.consumers import AgentConsumer
    
    print("=" * 60)
    print("流式缓存状态检查")
    print("=" * 60)
    
    if not hasattr(AgentConsumer, '_streaming_cache'):
        print("❌ 错误：AgentConsumer 没有 _streaming_cache 属性！")
        return
    
    cache = AgentConsumer._streaming_cache
    print(f"✅ 缓存字典存在")
    print(f"📊 当前缓存的 session 数量: {len(cache)}")
    
    if cache:
        print("\n缓存详情:")
        for session_id, data in cache.items():
            is_streaming = data.get("is_streaming", False)
            msg_count = len(data.get("messages", []))
            timestamp = data.get("timestamp", 0)
            print(f"  - Session: {session_id}")
            print(f"    是否流式中: {'🟢 是' if is_streaming else '🔴 否'}")
            print(f"    消息数量: {msg_count}")
            print(f"    时间戳: {timestamp}")
            
            if msg_count > 0 and msg_count <= 5:
                print(f"    消息类型: {[m.get('type') for m in data['messages']]}")
    else:
        print("\n💡 当前没有缓存的 session（正常，说明没有正在进行的流式对话）")
    
    print("\n" + "=" * 60)
    
    # 检查方法是否存在
    print("\n方法检查:")
    methods = ['_restore_streaming_state', 'send_json', '_cleanup_cache_later']
    for method in methods:
        if hasattr(AgentConsumer, method):
            print(f"  ✅ {method} 存在")
        else:
            print(f"  ❌ {method} 不存在！")
    
    print("=" * 60)

if __name__ == "__main__":
    import django
    import os
    import sys
    
    # 设置 Django 环境
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'UniSchedulerSuper.settings')
    django.setup()
    
    check_cache_status()
