"""
标识符解析器
支持多种引用方式解析为 UUID: 编号(#1, #g1, #s1)、UUID、标题

编号命名空间：
- #数字 (如 #1, #2): 日程/待办/提醒（search_items 返回）
- #g数字 (如 #g1, #g2): 事件组（get_event_groups 返回）
- #s数字 (如 #s1, #s2): 分享组（get_share_groups 返回）
"""
import re
import uuid
from typing import Optional, Dict, Any, Tuple

from logger import logger


# 编号格式正则
INDEX_PATTERN = re.compile(r'^#(\d+)$')           # #1, #2 - 日程/待办/提醒
GROUP_INDEX_PATTERN = re.compile(r'^#g(\d+)$', re.IGNORECASE)    # #g1, #g2 - 事件组
SHARE_INDEX_PATTERN = re.compile(r'^#s(\d+)$', re.IGNORECASE)    # #s1, #s2 - 分享组


class IdentifierResolver:
    """
    智能标识符解析器
    支持多种引用方式解析为 UUID
    
    支持的格式：
    - "#1", "#2": 日程/待办/提醒编号
    - "#g1", "#g2": 事件组编号
    - "#s1", "#s2": 分享组编号
    - UUID 格式
    - 标题模糊匹配
    """
    
    @classmethod
    def resolve(cls, identifier: str, item_type: str, session_id: Optional[str], user) -> Optional[str]:
        """
        解析标识符为 UUID
        
        Args:
            identifier: 标识符，支持以下格式：
                - "#1", "#2": 编号引用（从最近查询结果）
                - "550e8400-e29b-41d4...": 完整 UUID
                - "会议": 标题匹配
            item_type: "event" | "todo" | "reminder" | None (自动检测)
            session_id: 当前会话 ID
            user: 当前用户
        
        Returns:
            解析后的 UUID，找不到返回 None
        """
        if not identifier:
            return None
        
        identifier = str(identifier).strip()
        
        # 1. 检查是否是编号格式 (#N)
        if identifier.startswith('#'):
            result = cls._resolve_by_index(identifier, item_type, session_id)
            if result:
                return result
        
        # 2. 检查是否是 UUID 格式
        if cls._is_uuid(identifier):
            return identifier
        
        # 3. 按标题模糊匹配
        return cls._resolve_by_title(identifier, item_type, session_id, user)
    
    @classmethod
    def resolve_with_type(
        cls, 
        identifier: str, 
        session_id: Optional[str], 
        user,
        preferred_type: Optional[str] = None
    ) -> Optional[Tuple[str, str]]:
        """
        解析标识符并返回 (UUID, 类型) 元组
        
        Args:
            identifier: 标识符
            session_id: 当前会话 ID
            user: 当前用户
            preferred_type: 优先考虑的类型（可选）
        
        Returns:
            (uuid, type) 元组，或 None
        """
        if not identifier:
            return None
        
        identifier = str(identifier).strip()
        
        # 1. 检查编号格式
        if identifier.startswith('#'):
            result = cls._resolve_by_index_with_type(identifier, session_id, preferred_type)
            if result:
                return result
        
        # 2. UUID 格式（需要搜索确定类型）
        if cls._is_uuid(identifier):
            if preferred_type:
                # 验证该 UUID 是否属于指定类型
                if cls._verify_uuid_type(identifier, preferred_type, user):
                    return (identifier, preferred_type)
            # 搜索所有类型确定实际类型
            item_type = cls._find_type_for_uuid(identifier, user)
            if item_type:
                return (identifier, item_type)
            return None
        
        # 3. 标题匹配
        return cls._resolve_by_title_with_type(identifier, session_id, user, preferred_type)
    
    @classmethod
    def resolve_event_group(cls, identifier: str, user) -> Optional[str]:
        """
        解析事件组标识符为 UUID
        
        支持格式：
        - "#g1", "#g2": 事件组编号
        - UUID
        - 事件组名称
        
        Args:
            identifier: 事件组标识符
            user: 当前用户
        
        Returns:
            事件组 UUID，未找到返回 None
        """
        if not identifier:
            return None
        
        identifier = str(identifier).strip()
        
        from agent_service.tools.event_group_service import EventGroupService
        
        # 1. 检查 #g 格式
        match = GROUP_INDEX_PATTERN.match(identifier)
        if match:
            index = int(match.group(1))
            groups = EventGroupService.get_user_groups(user)
            if groups and 1 <= index <= len(groups):
                return groups[index - 1].get('id')
            return None
        
        # 2. 检查是否是 UUID
        if cls._is_uuid(identifier):
            return identifier
        
        # 3. 按名称解析
        return EventGroupService.resolve_group_name(user, identifier)
    
    @classmethod
    def resolve_share_group(cls, identifier: str, user) -> Optional[str]:
        """
        解析分享组标识符为 ID
        
        支持格式：
        - "#s1", "#s2": 分享组编号
        - ID
        - 分享组名称
        
        Args:
            identifier: 分享组标识符
            user: 当前用户
        
        Returns:
            分享组 ID，未找到返回 None
        """
        if not identifier:
            return None
        
        identifier = str(identifier).strip()
        
        from agent_service.tools.share_group_service import ShareGroupService
        
        # 1. 检查 #s 格式
        match = SHARE_INDEX_PATTERN.match(identifier)
        if match:
            index = int(match.group(1))
            groups = ShareGroupService.get_user_share_groups(user)
            if groups and 1 <= index <= len(groups):
                return groups[index - 1].get('share_group_id')
            return None
        
        # 2. 直接作为 ID 或名称解析
        return ShareGroupService.resolve_share_group_name(user, identifier)
    
    @staticmethod
    def _is_uuid(s: str) -> bool:
        """检查字符串是否是 UUID 格式"""
        try:
            uuid.UUID(s)
            return True
        except (ValueError, AttributeError):
            return False
    
    @classmethod
    def _get_session_from_id(cls, session_id: Optional[str]):
        """从 session_id 获取 session 对象"""
        if not session_id:
            return None
        try:
            from agent_service.models import AgentSession
            return AgentSession.objects.filter(session_id=session_id).first()
        except Exception as e:
            logger.warning(f"获取会话失败: {e}")
            return None
    
    @classmethod
    def _resolve_by_index(cls, index_str: str, item_type: Optional[str], session_id: Optional[str]) -> Optional[str]:
        """从会话缓存中按编号解析（仅处理 #数字 格式）"""
        if not session_id:
            return None
        
        # 检查是否是 #数字 格式（不是 #g 或 #s）
        match = INDEX_PATTERN.match(index_str)
        if not match:
            return None
        
        try:
            from agent_service.models import SearchResultCache, AgentSession
            
            session = AgentSession.objects.filter(session_id=session_id).first()
            if not session:
                return None
            
            # 获取最新的缓存
            cache = SearchResultCache.objects.filter(session=session).order_by('-updated_at').first()
            
            if cache and cache.index_mapping:
                info = cache.index_mapping.get(index_str)
                if info:
                    # 如果指定了类型，验证类型匹配
                    if item_type and info.get('type') != item_type:
                        logger.warning(f"编号 {index_str} 的类型 {info.get('type')} 与指定类型 {item_type} 不匹配")
                        return None
                    return info.get('uuid')
        except Exception as e:
            logger.error(f"按编号解析失败: {e}")
        
        return None
    
    @classmethod
    def _resolve_by_index_with_type(
        cls, 
        index_str: str, 
        session_id: Optional[str],
        preferred_type: Optional[str] = None
    ) -> Optional[Tuple[str, str]]:
        """从会话缓存中按编号解析，返回 (UUID, 类型) 元组"""
        if not session_id:
            return None
        
        # 检查是否是 #数字 格式
        match = INDEX_PATTERN.match(index_str)
        if not match:
            return None
        
        try:
            from agent_service.models import SearchResultCache, AgentSession
            
            session = AgentSession.objects.filter(session_id=session_id).first()
            if not session:
                return None
            
            cache = SearchResultCache.objects.filter(session=session).order_by('-updated_at').first()
            
            if cache and cache.index_mapping:
                info = cache.index_mapping.get(index_str)
                if info and 'uuid' in info and 'type' in info:
                    # 如果指定了类型，验证类型匹配
                    if preferred_type and info.get('type') != preferred_type:
                        logger.warning(f"编号 {index_str} 类型 {info.get('type')} 与期望类型 {preferred_type} 不匹配")
                        # 仍然返回结果，让调用方决定如何处理
                    return (info['uuid'], info['type'])
        except Exception as e:
            logger.error(f"按编号解析失败: {e}")
        
        return None
        
        return None
    
    @classmethod
    def _verify_uuid_type(cls, uuid_str: str, expected_type: str, user) -> bool:
        """验证 UUID 是否属于指定类型"""
        try:
            if expected_type == 'event':
                from core.services.event_service import EventService
                events = EventService.get_events(user)
                return any(event.get('id') == uuid_str for event in events)
            
            elif expected_type == 'todo':
                from core.services.todo_service import TodoService
                todos = TodoService.get_todos(user)
                return any(todo.get('id') == uuid_str for todo in todos)
            
            elif expected_type == 'reminder':
                from core.services.reminder_service import ReminderService
                reminders = ReminderService.get_reminders(user)
                return any(reminder.get('id') == uuid_str for reminder in reminders)
        except Exception as e:
            logger.error(f"验证 UUID 类型失败: {e}")
        
        return False
    
    @classmethod
    def _resolve_by_title(cls, title: str, item_type: Optional[str], session_id: Optional[str], user) -> Optional[str]:
        """按标题模糊匹配"""
        # 先尝试从缓存中匹配
        if session_id:
            try:
                from agent_service.models import SearchResultCache, AgentSession
                
                session = AgentSession.objects.filter(session_id=session_id).first()
                if session:
                    cache = SearchResultCache.objects.filter(session=session).order_by('-updated_at').first()
                    
                    if cache and cache.title_mapping:
                        # 精确匹配
                        if title in cache.title_mapping:
                            info = cache.title_mapping[title]
                            if not item_type or info.get('type') == item_type:
                                return info.get('uuid')
                        
                        # 模糊匹配
                        for cached_title, info in cache.title_mapping.items():
                            if title in cached_title or cached_title in title:
                                if not item_type or info.get('type') == item_type:
                                    return info.get('uuid')
            except Exception as e:
                logger.warning(f"从缓存按标题匹配失败: {e}")
        
        # 缓存未命中，直接搜索数据
        if item_type:
            return cls._search_by_title(title, item_type, user)
        else:
            # 搜索所有类型
            for search_type in ['event', 'todo', 'reminder']:
                result = cls._search_by_title(title, search_type, user)
                if result:
                    return result
            return None
    
    @classmethod
    def _resolve_by_title_with_type(
        cls, 
        title: str, 
        session_id: Optional[str], 
        user,
        preferred_type: Optional[str] = None
    ) -> Optional[Tuple[str, str]]:
        """按标题模糊匹配，返回 (UUID, 类型) 元组"""
        if session_id:
            try:
                from agent_service.models import SearchResultCache, AgentSession
                
                session = AgentSession.objects.filter(session_id=session_id).first()
                if session:
                    cache = SearchResultCache.objects.filter(session=session).order_by('-updated_at').first()
                    
                    if cache and cache.title_mapping:
                        # 精确匹配
                        if title in cache.title_mapping:
                            info = cache.title_mapping[title]
                            if 'uuid' in info and 'type' in info:
                                if not preferred_type or info['type'] == preferred_type:
                                    return (info['uuid'], info['type'])
                        
                        # 模糊匹配
                        for cached_title, info in cache.title_mapping.items():
                            if title in cached_title or cached_title in title:
                                if 'uuid' in info and 'type' in info:
                                    if not preferred_type or info['type'] == preferred_type:
                                        return (info['uuid'], info['type'])
            except Exception as e:
                logger.warning(f"从缓存按标题匹配失败: {e}")
        
        # 缓存未命中，搜索数据库
        # 如果指定了优先类型，先搜索该类型
        search_order = ['event', 'todo', 'reminder']
        if preferred_type and preferred_type in search_order:
            search_order.remove(preferred_type)
            search_order.insert(0, preferred_type)
        
        for search_type in search_order:
            uuid_result = cls._search_by_title(title, search_type, user)
            if uuid_result:
                return (uuid_result, search_type)
        
        return None
    
    @classmethod
    def _search_by_title(cls, title: str, item_type: str, user) -> Optional[str]:
        """从数据库中按标题搜索"""
        try:
            if item_type == 'event':
                from core.services.event_service import EventService
                events = EventService.get_events(user)
                for event in events:
                    if title in event.get('title', '') or event.get('title', '') in title:
                        return event.get('id')
            
            elif item_type == 'todo':
                from core.services.todo_service import TodoService
                todos = TodoService.get_todos(user)
                for todo in todos:
                    if title in todo.get('title', '') or todo.get('title', '') in title:
                        return todo.get('id')
            
            elif item_type == 'reminder':
                from core.services.reminder_service import ReminderService
                reminders = ReminderService.get_reminders(user)
                for reminder in reminders:
                    if title in reminder.get('title', '') or reminder.get('title', '') in title:
                        return reminder.get('id')
        except Exception as e:
            logger.error(f"按标题搜索失败: {e}")
        
        return None
    
    @classmethod
    def _find_type_for_uuid(cls, uuid_str: str, user) -> Optional[str]:
        """根据 UUID 查找其类型"""
        try:
            # 搜索 events
            from core.services.event_service import EventService
            events = EventService.get_events(user)
            for event in events:
                if event.get('id') == uuid_str:
                    return 'event'
            
            # 搜索 todos
            from core.services.todo_service import TodoService
            todos = TodoService.get_todos(user)
            for todo in todos:
                if todo.get('id') == uuid_str:
                    return 'todo'
            
            # 搜索 reminders
            from core.services.reminder_service import ReminderService
            reminders = ReminderService.get_reminders(user)
            for reminder in reminders:
                if reminder.get('id') == uuid_str:
                    return 'reminder'
        except Exception as e:
            logger.error(f"查找 UUID 类型失败: {e}")
        
        return None
