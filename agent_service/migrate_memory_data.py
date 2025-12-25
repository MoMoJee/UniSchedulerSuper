"""
数据迁移脚本：将 MemoryItem 数据迁移到 UserPersonalInfo

使用方法：
    python manage.py shell < agent_service/migrations/migrate_memory_data.py

或者在 Django shell 中执行：
    exec(open('agent_service/migrations/migrate_memory_data.py').read())
"""
import os
import sys
import django

# 设置 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'UniSchedulerSuper.settings')
django.setup()

from django.contrib.auth.models import User
from agent_service.models import MemoryItem, UserPersonalInfo, DialogStyle


def migrate_memory_items():
    """将 MemoryItem 迁移到 UserPersonalInfo"""
    print("开始迁移 MemoryItem 数据...")
    
    migrated_count = 0
    skipped_count = 0
    error_count = 0
    
    memory_items = MemoryItem.objects.all()
    print(f"找到 {memory_items.count()} 条 MemoryItem 记录")
    
    for item in memory_items:
        try:
            # 根据 category 生成 key
            category_map = {
                'preference': '偏好',
                'fact': '事实',
                'plan': '计划',
                'general': '信息'
            }
            category_name = category_map.get(item.category, '信息')
            
            # 使用 content 的前20个字符作为 key（如果 content 太长）
            content_preview = item.content[:50] if len(item.content) > 50 else item.content
            key = f"[{category_name}] {content_preview}"
            
            # 检查是否已存在相同的 key
            existing = UserPersonalInfo.objects.filter(user=item.user, key=key).first()
            if existing:
                # 如果已存在，跳过
                skipped_count += 1
                continue
            
            # 创建新的 UserPersonalInfo 记录
            UserPersonalInfo.objects.create(
                user=item.user,
                key=key,
                value=item.content,
                description=f"从旧记忆系统迁移 (类别: {item.category}, 重要性: {item.importance})"
            )
            migrated_count += 1
            
        except Exception as e:
            print(f"迁移失败: {item.id} - {str(e)}")
            error_count += 1
    
    print(f"\n迁移完成:")
    print(f"  - 成功迁移: {migrated_count} 条")
    print(f"  - 跳过(已存在): {skipped_count} 条")
    print(f"  - 失败: {error_count} 条")


def create_default_dialog_styles():
    """为所有用户创建默认的 DialogStyle"""
    print("\n创建默认 DialogStyle...")
    
    created_count = 0
    skipped_count = 0
    
    users = User.objects.all()
    print(f"找到 {users.count()} 个用户")
    
    for user in users:
        style, created = DialogStyle.objects.get_or_create(
            user=user,
            defaults={'content': DialogStyle.DEFAULT_TEMPLATE}
        )
        if created:
            created_count += 1
        else:
            skipped_count += 1
    
    print(f"\n创建完成:")
    print(f"  - 新建: {created_count} 个")
    print(f"  - 跳过(已存在): {skipped_count} 个")


if __name__ == '__main__':
    print("=" * 50)
    print("记忆系统数据迁移脚本")
    print("=" * 50)
    
    # 执行迁移
    migrate_memory_items()
    create_default_dialog_styles()
    
    print("\n" + "=" * 50)
    print("迁移脚本执行完毕")
    print("=" * 50)
