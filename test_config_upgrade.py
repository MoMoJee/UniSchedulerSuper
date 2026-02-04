"""
测试配置升级：验证 recursion_limit 和 tool_compress_preserve_recent_messages
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'UniSchedulerSuper.settings')
django.setup()

from django.contrib.auth.models import User
from agent_service.context_optimizer import get_optimization_config
from core.models import UserData

def test_config_upgrade():
    print("=" * 60)
    print("测试配置升级")
    print("=" * 60)
    
    # 获取测试用户（假设 ID=1 存在）
    try:
        user = User.objects.first()
        if not user:
            print("❌ 没有找到用户，请先创建用户")
            return
        
        print(f"\n✅ 测试用户: {user.username} (ID: {user.id})")
        
        # 读取配置
        print("\n📖 读取优化配置...")
        config = get_optimization_config(user)
        
        print("\n📊 当前配置：")
        print("-" * 60)
        
        # 旧配置
        print("\n【已有配置】")
        print(f"  enable_optimization:           {config.get('enable_optimization')}")
        print(f"  target_usage_ratio:            {config.get('target_usage_ratio')}")
        print(f"  token_calculation_method:      {config.get('token_calculation_method')}")
        print(f"  enable_summarization:          {config.get('enable_summarization')}")
        print(f"  summary_trigger_ratio:         {config.get('summary_trigger_ratio')}")
        print(f"  min_messages_before_summary:   {config.get('min_messages_before_summary')}")
        print(f"  compress_tool_output:          {config.get('compress_tool_output')}")
        print(f"  tool_output_max_tokens:        {config.get('tool_output_max_tokens')}")
        
        # 新配置
        print("\n【新增配置】")
        recursion_limit = config.get('recursion_limit')
        preserve_recent = config.get('tool_compress_preserve_recent_messages')
        
        print(f"  recursion_limit:                      {recursion_limit} {'✅' if recursion_limit is not None else '❌ 缺失'}")
        print(f"  tool_compress_preserve_recent_messages: {preserve_recent} {'✅' if preserve_recent is not None else '❌ 缺失'}")
        
        # 验证默认值
        print("\n🔍 验证默认值：")
        if recursion_limit == 25:
            print(f"  ✅ recursion_limit = {recursion_limit} (默认值正确)")
        else:
            print(f"  ⚠️  recursion_limit = {recursion_limit} (预期默认值: 25)")
        
        if preserve_recent == 5:
            print(f"  ✅ tool_compress_preserve_recent_messages = {preserve_recent} (默认值正确)")
        else:
            print(f"  ⚠️  tool_compress_preserve_recent_messages = {preserve_recent} (预期默认值: 5)")
        
        # 测试数据库 schema
        print("\n🗄️  检查数据库 schema...")
        from core.models import DATA_SCHEMA
        opt_schema = DATA_SCHEMA.get('agent_optimization_config', {}).get('items', {})
        
        has_recursion = 'recursion_limit' in opt_schema
        has_preserve = 'tool_compress_preserve_recent_messages' in opt_schema
        
        print(f"  recursion_limit in schema:                      {has_recursion} {'✅' if has_recursion else '❌'}")
        print(f"  tool_compress_preserve_recent_messages in schema: {has_preserve} {'✅' if has_preserve else '❌'}")
        
        if has_recursion:
            print(f"    - type: {opt_schema['recursion_limit'].get('type')}")
            print(f"    - default: {opt_schema['recursion_limit'].get('default')}")
        
        if has_preserve:
            print(f"    - type: {opt_schema['tool_compress_preserve_recent_messages'].get('type')}")
            print(f"    - default: {opt_schema['tool_compress_preserve_recent_messages'].get('default')}")
        
        print("\n" + "=" * 60)
        print("✅ 配置升级测试完成！")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    test_config_upgrade()
