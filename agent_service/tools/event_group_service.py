"""
事件组服务
管理事件组的缓存和名称→UUID映射
"""
import json
from typing import Dict, Optional, Tuple, List, Any
from datetime import datetime, timezone
from django.contrib.auth.models import User

from logger import logger


class MockRequest:
    """模拟 Django Request 对象"""
    def __init__(self, user):
        self.user = user
        self.is_authenticated = True


class EventGroupService:
    """
    事件组服务
    
    功能:
    - 从数据库获取用户的事件组列表
    - 将结果缓存到 EventGroupCache
    - 提供名称→UUID 解析
    - 支持模糊匹配
    """
    
    # 缓存 TTL（秒）
    CACHE_TTL = 3600  # 1小时
    
    @classmethod
    def get_user_groups(cls, user: User, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        获取用户的所有事件组
        
        Args:
            user: 用户对象
            force_refresh: 是否强制刷新缓存
        
        Returns:
            事件组列表，每个包含 id, name, description, color 等
        """
        from agent_service.models import EventGroupCache
        
        # 检查缓存
        if not force_refresh:
            try:
                cache = EventGroupCache.objects.filter(user=user).first()
                if cache and cache.is_valid():
                    # 返回缓存的数据
                    return list(cache.uuid_to_info.values())
            except Exception as e:
                logger.warning(f"读取事件组缓存失败: {e}")
        
        # 从数据库获取（通过 UserData）
        try:
            from core.models import UserData
            
            mock_request = MockRequest(user)
            user_data, created = UserData.objects.get_or_create(
                user=user, 
                key="events_groups", 
                defaults={"value": json.dumps([])}
            )
            
            groups = json.loads(user_data.value) if user_data.value else []
            
            name_to_uuid = {}
            uuid_to_info = {}
            
            for group in groups:
                group_id = group.get('id', '')
                group_info = {
                    'id': group_id,  # 使用 id 而非 uuid，保持一致
                    'uuid': group_id,  # 兼容性
                    'name': group.get('name', ''),
                    'description': group.get('description', ''),
                    'color': group.get('color', '#3788d8'),
                }
                
                if group.get('name'):
                    name_to_uuid[group['name'].lower()] = group_id
                uuid_to_info[group_id] = group_info
            
            # 更新缓存
            cls._update_cache(user, name_to_uuid, uuid_to_info)
            
            return list(uuid_to_info.values())
            
        except Exception as e:
            logger.error(f"获取事件组失败: {e}")
            return []
    
    @classmethod
    def resolve_group_name(cls, user: User, name_or_uuid: str) -> Optional[str]:
        """
        将组名或UUID解析为UUID
        
        Args:
            user: 用户对象
            name_or_uuid: 组名或UUID
        
        Returns:
            UUID字符串，未找到返回None
        """
        if not name_or_uuid:
            return None
        
        from agent_service.models import EventGroupCache
        
        name_or_uuid = name_or_uuid.strip()
        
        # 先检查缓存
        try:
            cache = EventGroupCache.objects.filter(user=user).first()
            if cache and cache.is_valid():
                # 尝试直接 UUID 匹配
                if name_or_uuid in cache.uuid_to_info:
                    return name_or_uuid
                
                # 尝试名称匹配（不区分大小写）
                lower_name = name_or_uuid.lower()
                if lower_name in cache.name_to_uuid:
                    return cache.name_to_uuid[lower_name]
                
                # 尝试模糊匹配
                for cached_name, uuid in cache.name_to_uuid.items():
                    if lower_name in cached_name or cached_name in lower_name:
                        return uuid
        except Exception as e:
            logger.warning(f"读取事件组缓存失败: {e}")
        
        # 缓存未命中，刷新缓存并重试
        cls.get_user_groups(user, force_refresh=True)
        
        try:
            cache = EventGroupCache.objects.filter(user=user).first()
            if cache:
                # 尝试直接 UUID 匹配
                if name_or_uuid in cache.uuid_to_info:
                    return name_or_uuid
                
                # 尝试名称匹配
                lower_name = name_or_uuid.lower()
                if lower_name in cache.name_to_uuid:
                    return cache.name_to_uuid[lower_name]
                
                # 尝试模糊匹配
                for cached_name, uuid in cache.name_to_uuid.items():
                    if lower_name in cached_name or cached_name in lower_name:
                        return uuid
        except Exception as e:
            logger.error(f"解析事件组失败: {e}")
        
        return None
    
    @classmethod
    def get_group_info(cls, user: User, uuid: str) -> Optional[Dict[str, Any]]:
        """
        获取事件组详情
        
        Args:
            user: 用户对象
            uuid: 事件组UUID
        
        Returns:
            事件组信息字典，未找到返回None
        """
        from agent_service.models import EventGroupCache
        
        try:
            cache = EventGroupCache.objects.filter(user=user).first()
            if cache and cache.is_valid():
                return cache.uuid_to_info.get(uuid)
        except Exception as e:
            logger.warning(f"读取事件组缓存失败: {e}")
        
        # 刷新缓存
        cls.get_user_groups(user, force_refresh=True)
        
        try:
            cache = EventGroupCache.objects.filter(user=user).first()
            if cache:
                return cache.uuid_to_info.get(uuid)
        except Exception as e:
            logger.error(f"获取事件组详情失败: {e}")
        
        return None
    
    @classmethod
    def get_default_group(cls, user: User) -> Optional[str]:
        """
        获取用户的默认事件组
        
        Args:
            user: 用户对象
        
        Returns:
            默认事件组的ID，未找到返回None
        """
        try:
            groups = cls.get_user_groups(user)
            if groups:
                # 返回第一个组的 ID
                return groups[0].get('id')
        except Exception as e:
            logger.error(f"获取默认事件组失败: {e}")
        
        return None
    
    @classmethod
    def invalidate_cache(cls, user: User):
        """
        使缓存失效
        
        Args:
            user: 用户对象
        """
        from agent_service.models import EventGroupCache
        
        try:
            EventGroupCache.objects.filter(user=user).delete()
        except Exception as e:
            logger.warning(f"删除事件组缓存失败: {e}")
    
    @classmethod
    def _update_cache(cls, user: User, name_to_uuid: Dict[str, str], uuid_to_info: Dict[str, Dict]):
        """
        更新缓存
        
        Args:
            user: 用户对象
            name_to_uuid: 名称→UUID映射
            uuid_to_info: UUID→详情映射
        """
        from agent_service.models import EventGroupCache
        
        try:
            cache, created = EventGroupCache.objects.update_or_create(
                user=user,
                defaults={
                    'name_to_uuid': name_to_uuid,
                    'uuid_to_info': uuid_to_info,
                    'updated_at': datetime.now(timezone.utc),
                }
            )
        except Exception as e:
            logger.error(f"更新事件组缓存失败: {e}")
    
    @classmethod
    def create_group(cls, user: User, name: str, description: str = "", color: str = "#3788d8") -> Optional[Dict[str, Any]]:
        """
        创建新事件组
        
        Args:
            user: 用户对象
            name: 组名
            description: 描述
            color: 颜色
        
        Returns:
            创建的事件组信息，失败返回None
        """
        import uuid as uuid_module
        
        try:
            from core.models import UserData
            
            # 获取现有组
            user_data, created = UserData.objects.get_or_create(
                user=user, 
                key="events_groups", 
                defaults={"value": json.dumps([])}
            )
            
            groups = json.loads(user_data.value) if user_data.value else []
            
            # 创建新组
            new_group = {
                'id': str(uuid_module.uuid4()),
                'name': name,
                'description': description,
                'color': color,
            }
            
            groups.append(new_group)
            user_data.value = json.dumps(groups)
            user_data.save()
            
            # 使缓存失效
            cls.invalidate_cache(user)
            
            return {
                'id': new_group['id'],
                'uuid': new_group['id'],  # 兼容性
                'name': name,
                'description': description,
                'color': color,
            }
        except Exception as e:
            logger.error(f"创建事件组失败: {e}")
            return None
    
    @classmethod
    def format_groups_for_display(cls, groups: List[Dict[str, Any]], include_hint: bool = True) -> str:
        """
        将事件组列表格式化为显示字符串
        
        使用 #g 前缀区分事件组和日程/待办/提醒的编号
        
        Args:
            groups: 事件组列表
            include_hint: 是否包含使用提示
        
        Returns:
            格式化的字符串
        """
        if not groups:
            return "暂无事件组"
        
        lines = []
        for i, group in enumerate(groups, 1):
            name = group.get('name', '未命名')
            desc = group.get('description', '')
            desc_str = f" - {desc}" if desc else ""
            lines.append(f"#g{i} {name}{desc_str}")
        
        result = "\n".join(lines)
        
        if include_hint:
            result += "\n\n💡 使用 #g序号 或组名引用事件组（如 event_group='#g1' 或 event_group='工作'）"
        
        return result
