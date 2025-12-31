"""
缓存管理器
处理搜索结果缓存和回滚同步
"""
from typing import Dict, Any, List, Optional, Union

from logger import logger


class CacheManager:
    """
    缓存管理器 - 处理搜索结果缓存和回滚同步
    """
    
    @staticmethod
    def clear_session_cache(session_id: str) -> int:
        """
        清除会话的所有搜索缓存（在回滚时调用）
        
        Args:
            session_id: 会话 ID
        
        Returns:
            删除的缓存数量
        """
        try:
            from agent_service.models import AgentSession, SearchResultCache
            
            session = AgentSession.objects.filter(session_id=session_id).first()
            if session:
                deleted_count, _ = SearchResultCache.objects.filter(session=session).delete()
                logger.info(f"[Cache] 已清除会话 {session_id} 的 {deleted_count} 条搜索缓存")
                return deleted_count
            else:
                logger.warning(f"[Cache] 未找到会话 {session_id}")
                return 0
        except Exception as e:
            logger.error(f"[Cache] 清除缓存失败: {e}")
            return 0
    
    @staticmethod
    def save_search_cache(
        session,
        user,
        result_type: str,
        items: List[Dict[str, Any]],
        query_params: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        保存搜索结果缓存
        
        Args:
            session: AgentSession 实例
            user: User 实例
            result_type: 结果类型 (event/to do/reminder/mixed)
            items: 搜索结果列表，每个 item 需要有 id, title, type 字段
            query_params: 查询参数（用于调试）
        
        Returns:
            是否保存成功
        """
        try:
            from agent_service.models import SearchResultCache
            
            # 构建编号映射
            index_mapping: Dict[str, Dict[str, Any]] = {}
            title_mapping: Dict[str, Dict[str, Any]] = {}
            
            for i, item in enumerate(items, 1):
                index_key = f"#{i}"
                item_uuid = item.get('id', '')
                item_title = item.get('title', '')
                item_type = item.get('type', result_type)
                
                if item_uuid:
                    index_mapping[index_key] = {
                        'uuid': item_uuid,
                        'type': item_type,
                        'title': item_title
                    }
                    
                    if item_title:
                        title_mapping[item_title] = {
                            'uuid': item_uuid,
                            'type': item_type
                        }
            
            # 更新或创建缓存
            cache, created = SearchResultCache.objects.update_or_create(
                session=session,
                result_type=result_type,
                defaults={
                    'user': user,
                    'index_mapping': index_mapping,
                    'title_mapping': title_mapping,
                    'query_params': query_params or {}
                }
            )
            
            logger.info(f"[Cache] {'创建' if created else '更新'}搜索缓存: {len(items)} 条结果")
            return True
            
        except Exception as e:
            logger.error(f"[Cache] 保存搜索缓存失败: {e}")
            return False
    
    @staticmethod
    def save_mixed_search_cache(
        session_or_id: Union[str, Any],
        items_or_events: Optional[List[Dict]] = None,
        result_types: Optional[List[str]] = None,
        todos: Optional[List[Dict]] = None,
        reminders: Optional[List[Dict]] = None,
        query_params: Optional[Dict[str, Any]] = None,
        user: Any = None
    ) -> bool:
        """
        保存混合搜索结果缓存（跨类型搜索）
        
        支持两种调用方式:
        1. save_mixed_search_cache(session_id, items, result_types) - 简化调用
        2. save_mixed_search_cache(session, user=user, items_or_events=events, todos=todos, reminders=reminders) - 完整调用
        
        Args:
            session_or_id: AgentSession 实例或 session_id 字符串
            items_or_events: 简化调用时为混合项目列表，完整调用时为 events 列表
            result_types: 简化调用时每个 item 对应的类型列表
            todos: 完整调用时的待办列表
            reminders: 完整调用时的提醒列表
            query_params: 查询参数
            user: 完整调用时的 User 实例
        
        Returns:
            是否保存成功
        """
        try:
            from agent_service.models import SearchResultCache, AgentSession
            
            # 判断调用方式
            if isinstance(session_or_id, str) and result_types is not None:
                # 简化调用: save_mixed_search_cache(session_id, items, result_types)
                session_id = session_or_id
                items = items_or_events or []
                
                session = AgentSession.objects.filter(session_id=session_id).first()
                if not session:
                    logger.warning(f"[Cache] 未找到会话 {session_id}")
                    return False
                
                # 构建映射
                index_mapping: Dict[str, Dict[str, Any]] = {}
                title_mapping: Dict[str, Dict[str, Any]] = {}
                
                for i, (item, item_type) in enumerate(zip(items, result_types), 1):
                    index_key = f"#{i}"
                    item_uuid = item.get('id', '')
                    item_title = item.get('title', '')
                    
                    if item_uuid:
                        index_mapping[index_key] = {
                            'uuid': item_uuid,
                            'type': item_type,
                            'title': item_title
                        }
                        
                        if item_title:
                            title_mapping[item_title] = {
                                'uuid': item_uuid,
                                'type': item_type
                            }
                
                # 更新或创建缓存
                cache, created = SearchResultCache.objects.update_or_create(
                    session=session,
                    result_type='mixed',
                    defaults={
                        'user': session.user,
                        'index_mapping': index_mapping,
                        'title_mapping': title_mapping,
                        'query_params': {}
                    }
                )
                
                logger.info(f"[Cache] {'创建' if created else '更新'}混合搜索缓存: {len(items)} 条结果")
                return True
            
            else:
                # 完整调用: save_mixed_search_cache(session, user=..., events=..., todos=..., reminders=...)
                session = session_or_id
                events = items_or_events or []
                todos_list = todos or []
                reminders_list = reminders or []
                
                # 合并所有结果并编号
                all_items: List[Dict[str, Any]] = []
                
                for event in events:
                    all_items.append({**event, 'type': 'event'})
                for todo in todos_list:
                    all_items.append({**todo, 'type': 'todo'})
                for reminder in reminders_list:
                    all_items.append({**reminder, 'type': 'reminder'})
                
                # 构建映射
                index_mapping: Dict[str, Dict[str, Any]] = {}
                title_mapping: Dict[str, Dict[str, Any]] = {}
                
                for i, item in enumerate(all_items, 1):
                    index_key = f"#{i}"
                    item_uuid = item.get('id', '')
                    item_title = item.get('title', '')
                    item_type = item.get('type', '')
                    
                    if item_uuid:
                        index_mapping[index_key] = {
                            'uuid': item_uuid,
                            'type': item_type,
                            'title': item_title
                        }
                        
                        if item_title:
                            title_mapping[item_title] = {
                                'uuid': item_uuid,
                                'type': item_type
                            }
                
                # 更新或创建缓存
                cache, created = SearchResultCache.objects.update_or_create(
                    session=session,
                    result_type='mixed',
                    defaults={
                        'user': user,
                        'index_mapping': index_mapping,
                        'title_mapping': title_mapping,
                        'query_params': query_params or {}
                    }
                )
                
                total = len(events) + len(todos_list) + len(reminders_list)
                logger.info(f"[Cache] {'创建' if created else '更新'}混合搜索缓存: {total} 条结果")
                return True
            
        except Exception as e:
            logger.error(f"[Cache] 保存混合搜索缓存失败: {e}")
            return False
    
    @staticmethod
    def get_cached_item(session, identifier: str) -> Optional[Dict[str, Any]]:
        """
        从缓存中获取项目信息
        
        Args:
            session: AgentSession 实例
            identifier: 标识符（编号或标题）
        
        Returns:
            {"uuid": "xxx", "type": "event", "title": "..."} 或 None
        """
        try:
            from agent_service.models import SearchResultCache
            
            # 获取最新的缓存
            cache = SearchResultCache.objects.filter(session=session).order_by('-updated_at').first()
            
            if not cache:
                return None
            
            # 按编号查找
            if identifier.startswith('#'):
                return cache.index_mapping.get(identifier)
            
            # 按标题查找
            info = cache.title_mapping.get(identifier)
            if info:
                return info
            
            # 模糊匹配标题
            for title, info_dict in cache.title_mapping.items():
                if identifier in title or title in identifier:
                    return info_dict
            
            return None
            
        except Exception as e:
            logger.error(f"[Cache] 获取缓存项失败: {e}")
            return None
    
    @staticmethod
    def invalidate_item(session_or_id: Union[str, Any], item_uuid: str) -> bool:
        """
        使特定项目的缓存失效
        当项目被修改或删除时调用
        
        Args:
            session_or_id: AgentSession 实例或 session_id 字符串
            item_uuid: 项目 UUID
        
        Returns:
            是否成功
        """
        try:
            from agent_service.models import SearchResultCache, AgentSession
            
            # 获取 session
            if isinstance(session_or_id, str):
                session = AgentSession.objects.filter(session_id=session_or_id).first()
                if not session:
                    return False
            else:
                session = session_or_id
            
            caches = SearchResultCache.objects.filter(session=session)
            
            for cache in caches:
                modified = False
                
                # 从 index_mapping 中移除
                new_index_mapping: Dict[str, Dict[str, Any]] = {}
                for key, info in cache.index_mapping.items():
                    if info.get('uuid') != item_uuid:
                        new_index_mapping[key] = info
                    else:
                        modified = True
                
                # 从 title_mapping 中移除
                new_title_mapping: Dict[str, Dict[str, Any]] = {}
                for title, info in cache.title_mapping.items():
                    if info.get('uuid') != item_uuid:
                        new_title_mapping[title] = info
                    else:
                        modified = True
                
                if modified:
                    cache.index_mapping = new_index_mapping
                    cache.title_mapping = new_title_mapping
                    cache.save()
            
            return True
            
        except Exception as e:
            logger.error(f"[Cache] 使缓存失效失败: {e}")
            return False
