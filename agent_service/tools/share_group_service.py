"""
分享组服务
管理分享组的缓存和名称→ID映射
参考 event_group_service.py 实现
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


class ShareGroupService:
    """
    分享组服务
    
    功能:
    - 从数据库获取用户所在的分享组列表
    - 提供名称→ID 解析
    - 支持模糊匹配
    - 获取分享组内的日程
    """
    
    # 缓存 TTL（秒）
    CACHE_TTL = 3600  # 1小时
    
    @classmethod
    def get_user_share_groups(cls, user: User, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        获取用户所在的所有分享组
        
        Args:
            user: 用户对象
            force_refresh: 是否强制刷新缓存
        
        Returns:
            分享组列表，每个包含 share_group_id, share_group_name, role, member_count 等
        """
        from agent_service.models import ShareGroupCache
        
        # 检查缓存
        if not force_refresh:
            try:
                cache = ShareGroupCache.objects.filter(user=user).first()
                if cache and cache.is_valid():
                    # 返回缓存的数据
                    return list(cache.id_to_info.values())
            except Exception as e:
                logger.warning(f"读取分享组缓存失败: {e}")
        
        # 从数据库获取
        try:
            from core.models import (
                CollaborativeCalendarGroup,
                GroupMembership,
                GroupCalendarData
            )
            
            # 获取用户的所有群组成员关系
            memberships = GroupMembership.objects.filter(user=user).select_related('share_group')
            
            # 预加载版本号
            group_ids = [m.share_group.share_group_id for m in memberships]
            group_versions = {
                gcd.share_group_id: gcd.version 
                for gcd in GroupCalendarData.objects.filter(share_group_id__in=group_ids)
            }
            
            name_to_id = {}
            id_to_info = {}
            
            for membership in memberships:
                group = membership.share_group
                member_count = GroupMembership.objects.filter(share_group=group).count()
                
                group_info = {
                    'share_group_id': group.share_group_id,
                    'share_group_name': group.share_group_name,
                    'share_group_color': group.share_group_color,
                    'share_group_description': group.share_group_description,
                    'role': membership.role,
                    'my_member_color': membership.member_color,
                    'member_count': member_count,
                    'owner_id': group.owner.id,
                    'owner_name': group.owner.username,
                    'version': group_versions.get(group.share_group_id, 0)
                }
                
                # 名称映射（不区分大小写）
                if group.share_group_name:
                    name_to_id[group.share_group_name.lower()] = group.share_group_id
                id_to_info[group.share_group_id] = group_info
            
            # 更新缓存
            cls._update_cache(user, name_to_id, id_to_info)
            
            return list(id_to_info.values())
            
        except Exception as e:
            logger.error(f"获取分享组失败: {e}")
            return []
    
    @classmethod
    def resolve_share_group_name(cls, user: User, name_or_id: str) -> Optional[str]:
        """
        将分享组名称或ID解析为ID
        
        Args:
            user: 用户对象
            name_or_id: 分享组名称或ID
        
        Returns:
            分享组ID字符串，未找到返回None
        """
        if not name_or_id:
            return None
        
        from agent_service.models import ShareGroupCache
        
        name_or_id = name_or_id.strip()
        
        # 先检查缓存
        try:
            cache = ShareGroupCache.objects.filter(user=user).first()
            if cache and cache.is_valid():
                # 尝试直接 ID 匹配
                if name_or_id in cache.id_to_info:
                    return name_or_id
                
                # 尝试名称匹配（不区分大小写）
                lower_name = name_or_id.lower()
                if lower_name in cache.name_to_id:
                    return cache.name_to_id[lower_name]
                
                # 尝试模糊匹配
                for cached_name, group_id in cache.name_to_id.items():
                    if lower_name in cached_name or cached_name in lower_name:
                        return group_id
        except Exception as e:
            logger.warning(f"读取分享组缓存失败: {e}")
        
        # 缓存未命中，刷新缓存并重试
        cls.get_user_share_groups(user, force_refresh=True)
        
        try:
            cache = ShareGroupCache.objects.filter(user=user).first()
            if cache:
                # 尝试直接 ID 匹配
                if name_or_id in cache.id_to_info:
                    return name_or_id
                
                # 尝试名称匹配
                lower_name = name_or_id.lower()
                if lower_name in cache.name_to_id:
                    return cache.name_to_id[lower_name]
                
                # 尝试模糊匹配
                for cached_name, group_id in cache.name_to_id.items():
                    if lower_name in cached_name or cached_name in lower_name:
                        return group_id
        except Exception as e:
            logger.error(f"解析分享组失败: {e}")
        
        return None
    
    @classmethod
    def resolve_share_group_names(cls, user: User, names_or_ids: List[str]) -> List[str]:
        """
        批量解析分享组名称或ID为ID列表
        
        Args:
            user: 用户对象
            names_or_ids: 分享组名称或ID列表
        
        Returns:
            分享组ID列表（过滤掉无法解析的项）
        """
        if not names_or_ids:
            return []
        
        resolved = []
        for item in names_or_ids:
            group_id = cls.resolve_share_group_name(user, item)
            if group_id:
                resolved.append(group_id)
        
        return resolved
    
    @classmethod
    def get_share_group_info(cls, user: User, share_group_id: str) -> Optional[Dict[str, Any]]:
        """
        获取分享组详情
        
        Args:
            user: 用户对象
            share_group_id: 分享组ID
        
        Returns:
            分享组信息字典，未找到返回None
        """
        from agent_service.models import ShareGroupCache
        
        try:
            cache = ShareGroupCache.objects.filter(user=user).first()
            if cache and cache.is_valid():
                return cache.id_to_info.get(share_group_id)
        except Exception as e:
            logger.warning(f"读取分享组缓存失败: {e}")
        
        # 刷新缓存
        cls.get_user_share_groups(user, force_refresh=True)
        
        try:
            cache = ShareGroupCache.objects.filter(user=user).first()
            if cache:
                return cache.id_to_info.get(share_group_id)
        except Exception as e:
            logger.error(f"获取分享组详情失败: {e}")
        
        return None
    
    @classmethod
    def get_share_group_events(cls, user: User, share_group_id: str) -> Tuple[List[Dict], List[Dict]]:
        """
        获取分享组内的所有日程
        
        Args:
            user: 用户对象
            share_group_id: 分享组ID
        
        Returns:
            Tuple[events, members]:
            - events: 日程列表，每个日程包含 owner_id 标识
            - members: 成员列表，包含 user_id, username, member_color
        """
        try:
            from core.models import GroupCalendarData, GroupMembership, UserData
            
            # 检查用户是否是该群组成员
            if not GroupMembership.objects.filter(
                share_group_id=share_group_id,
                user=user
            ).exists():
                logger.warning(f"用户 {user.username} 不是群组 {share_group_id} 的成员")
                return [], []
            
            # 获取群组数据
            try:
                group_data = GroupCalendarData.objects.get(share_group_id=share_group_id)
                events = group_data.events_data or []
            except GroupCalendarData.DoesNotExist:
                events = []
            
            # 获取成员信息
            memberships = GroupMembership.objects.filter(
                share_group_id=share_group_id
            ).select_related('user')
            
            members = []
            for membership in memberships:
                members.append({
                    'user_id': membership.user.id,
                    'username': membership.user.username,
                    'member_color': membership.member_color or '#6c757d'
                })
            
            # 获取当前用户的事件ID，标识哪些是自己的
            mock_request = MockRequest(user)
            user_events_data, _, _ = UserData.get_or_initialize(
                mock_request, new_key="events", data=[]
            )
            user_events = user_events_data.get_value() or [] if user_events_data else []
            user_event_ids = {event.get('id') for event in user_events if isinstance(event, dict)}
            
            # 为每个事件添加 owner_id 和 is_own 标识
            events_with_info = []
            for event in events:
                event_copy = event.copy()
                if event.get('id') in user_event_ids:
                    event_copy['owner_id'] = user.id
                    event_copy['is_own'] = True
                else:
                    event_copy['is_own'] = False
                events_with_info.append(event_copy)
            
            return events_with_info, members
            
        except Exception as e:
            logger.error(f"获取分享组日程失败: {e}")
            return [], []
    
    @classmethod
    def get_all_share_groups_events(
        cls, 
        user: User, 
        share_group_ids: Optional[List[str]] = None,
        exclude_own: bool = True
    ) -> List[Dict]:
        """
        获取用户所在的多个分享组的日程
        
        Args:
            user: 用户对象
            share_group_ids: 分享组ID列表，为None则获取所有分享组
            exclude_own: 是否排除用户自己的日程（避免重复）
        
        Returns:
            日程列表，每个日程带有 share_group_id, share_group_name, owner_id 等信息
        """
        try:
            # 获取用户所在的分享组
            groups = cls.get_user_share_groups(user)
            
            if not groups:
                return []
            
            # 如果指定了分享组ID，过滤
            if share_group_ids:
                groups = [g for g in groups if g['share_group_id'] in share_group_ids]
            
            all_events = []
            seen_event_ids = set()  # 用于去重
            
            for group in groups:
                events, members = cls.get_share_group_events(user, group['share_group_id'])
                
                # 创建成员ID到用户名的映射
                member_map = {m['user_id']: m['username'] for m in members}
                
                for event in events:
                    event_id = event.get('id')
                    
                    # 跳过已处理的事件（去重）
                    if event_id in seen_event_ids:
                        continue
                    seen_event_ids.add(event_id)
                    
                    # 如果需要排除自己的日程
                    if exclude_own and event.get('is_own', False):
                        continue
                    
                    # 添加分享组信息
                    event_copy = event.copy()
                    event_copy['_share_group_id'] = group['share_group_id']
                    event_copy['_share_group_name'] = group['share_group_name']
                    
                    # 添加所有者用户名
                    owner_id = event_copy.get('owner_id') or event_copy.get('user_id')
                    if owner_id:
                        event_copy['_owner_username'] = member_map.get(owner_id, '未知用户')
                    
                    all_events.append(event_copy)
            
            return all_events
            
        except Exception as e:
            logger.error(f"获取多个分享组日程失败: {e}")
            return []
    
    @classmethod
    def invalidate_cache(cls, user: User):
        """
        使缓存失效
        
        Args:
            user: 用户对象
        """
        from agent_service.models import ShareGroupCache
        
        try:
            ShareGroupCache.objects.filter(user=user).delete()
        except Exception as e:
            logger.warning(f"删除分享组缓存失败: {e}")
    
    @classmethod
    def _update_cache(cls, user: User, name_to_id: Dict[str, str], id_to_info: Dict[str, Dict]):
        """
        更新缓存
        
        Args:
            user: 用户对象
            name_to_id: 名称→ID映射
            id_to_info: ID→详情映射
        """
        from agent_service.models import ShareGroupCache
        
        try:
            cache, created = ShareGroupCache.objects.update_or_create(
                user=user,
                defaults={
                    'name_to_id': name_to_id,
                    'id_to_info': id_to_info,
                    'updated_at': datetime.now(timezone.utc),
                }
            )
        except Exception as e:
            logger.error(f"更新分享组缓存失败: {e}")
    
    @classmethod
    def format_share_groups_for_display(cls, groups: List[Dict[str, Any]]) -> str:
        """
        将分享组列表格式化为显示字符串
        
        Args:
            groups: 分享组列表
        
        Returns:
            格式化的字符串
        """
        if not groups:
            return "暂无分享组"
        
        lines = []
        for i, group in enumerate(groups, 1):
            name = group.get('share_group_name', '未命名')
            role = group.get('role', 'member')
            role_display = {'owner': '群主', 'admin': '管理员', 'member': '成员'}.get(role, role)
            member_count = group.get('member_count', 0)
            lines.append(f"#{i} {name} ({role_display}, {member_count}人)")
        
        return "\n".join(lines)
