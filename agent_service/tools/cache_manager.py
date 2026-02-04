"""
缓存管理器
处理搜索结果缓存和回滚同步

支持功能:
- 智能去重：同一个UUID在不同搜索中复用相同编号
- LRU淘汰：限制缓存大小，自动清理最久未访问的项目
- 会话级持久化：编号在会话期间保持稳定
"""
import time
from typing import Dict, Any, List, Optional, Union, Tuple

from logger import logger


class CacheManager:
    """
    缓存管理器 - 处理搜索结果缓存和回滚同步
    
    支持智能去重和会话级持久化
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
    def save_search_cache_smart(
        session_or_id: Union[str, Any],
        items: List[Dict[str, Any]],
        result_types: List[str],
        user: Any = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        智能保存搜索结果缓存（支持去重和LRU淘汰）
        
        特性:
        - UUID去重：已存在的UUID复用原编号，只更新信息和访问时间
        - LRU淘汰：超过MAX_CACHE_SIZE时淘汰最久未访问的项目
        - 返回编号映射：便于格式化输出时使用正确的编号
        
        Args:
            session_or_id: AgentSession 实例或 session_id 字符串
            items: 搜索结果列表，每个 item 需要有 id, title 字段
            result_types: 每个 item 对应的类型列表
            user: User 实例（当 session_or_id 为字符串时需要）
        
        Returns:
            (成功标志, 统计信息)
            统计信息: {
                'reused': 复用的编号数,
                'new': 新分配的编号数,
                'total_cached': 缓存总数,
                'item_to_index': {uuid: index_key} 映射
            }
        """
        try:
            from agent_service.models import SearchResultCache, AgentSession
            
            current_time = int(time.time())
            
            # 获取 session 和 user
            if isinstance(session_or_id, str):
                session = AgentSession.objects.filter(session_id=session_or_id).first()
                if not session:
                    logger.warning(f"[Cache] 未找到会话 {session_or_id}")
                    return False, {}
                if not user:
                    user = session.user
            else:
                session = session_or_id
                if not user:
                    user = session.user
            
            # 获取或创建缓存
            cache, created = SearchResultCache.objects.get_or_create(
                session=session,
                result_type='mixed',
                defaults={
                    'user': user,
                    'index_mapping': {},
                    'uuid_to_index': {},
                    'title_mapping': {},
                    'next_index': 1,
                    'query_params': {}
                }
            )
            
            # 确保字段已初始化（兼容旧数据）
            if not cache.uuid_to_index:
                cache.uuid_to_index = {}
            if not hasattr(cache, 'next_index') or cache.next_index is None:
                cache.next_index = len(cache.index_mapping) + 1
            
            reused_count = 0
            new_count = 0
            item_to_index: Dict[str, str] = {}  # uuid -> index_key
            
            # 遍历新搜索结果
            for item, item_type in zip(items, result_types):
                item_uuid = item.get('id', '')
                item_title = item.get('title', '')
                
                if not item_uuid:
                    continue
                
                # 检查 UUID 是否已存在
                if item_uuid in cache.uuid_to_index:
                    # 已存在：复用编号，更新信息
                    existing_index = cache.uuid_to_index[item_uuid]
                    cache.index_mapping[existing_index] = {
                        'uuid': item_uuid,
                        'type': item_type,
                        'title': item_title,
                        'last_seen': current_time
                    }
                    item_to_index[item_uuid] = existing_index
                    reused_count += 1
                else:
                    # 新UUID：分配新编号
                    new_index = f"#{cache.next_index}"
                    cache.index_mapping[new_index] = {
                        'uuid': item_uuid,
                        'type': item_type,
                        'title': item_title,
                        'last_seen': current_time
                    }
                    cache.uuid_to_index[item_uuid] = new_index
                    item_to_index[item_uuid] = new_index
                    cache.next_index += 1
                    new_count += 1
                
                # 更新标题映射
                if item_title:
                    cache.title_mapping[item_title] = {
                        'uuid': item_uuid,
                        'type': item_type
                    }
            
            # LRU 淘汰
            cache.cleanup_lru()
            
            # 保存
            cache.save()
            
            stats = {
                'reused': reused_count,
                'new': new_count,
                'total_cached': len(cache.index_mapping),
                'item_to_index': item_to_index
            }
            
            logger.info(f"[Cache] 智能缓存: 复用 {reused_count} 个编号, 新增 {new_count} 个, 总计 {len(cache.index_mapping)} 个")
            return True, stats
            
        except Exception as e:
            logger.error(f"[Cache] 智能保存缓存失败: {e}", exc_info=True)
            return False, {}
    
    @staticmethod
    def save_search_cache(
        session,
        user,
        result_type: str,
        items: List[Dict[str, Any]],
        query_params: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        保存搜索结果缓存（旧接口，保持兼容）
        
        注意：建议使用 save_search_cache_smart 以获得智能去重功能
        
        Args:
            session: AgentSession 实例
            user: User 实例
            result_type: 结果类型 (event/todo/reminder/mixed)
            items: 搜索结果列表，每个 item 需要有 id, title, type 字段
            query_params: 查询参数（用于调试）
        
        Returns:
            是否保存成功
        """
        # 转换为新接口格式
        result_types = [item.get('type', result_type) for item in items]
        success, _ = CacheManager.save_search_cache_smart(session, items, result_types, user)
        return success
    
    @staticmethod
    def save_mixed_search_cache(
        session_or_id: Union[str, Any],
        items_or_events: Optional[List[Dict]] = None,
        result_types: Optional[List[str]] = None,
        todos: Optional[List[Dict]] = None,
        reminders: Optional[List[Dict]] = None,
        query_params: Optional[Dict[str, Any]] = None,
        user: Any = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        保存混合搜索结果缓存（跨类型搜索）- 使用智能去重
        
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
            (成功标志, 统计信息) - 统计信息包含 item_to_index 映射
        """
        try:
            # 判断调用方式并构建统一的 items 和 result_types
            if isinstance(session_or_id, str) and result_types is not None:
                # 简化调用: save_mixed_search_cache(session_id, items, result_types)
                items = items_or_events or []
                types = result_types
            else:
                # 完整调用: 合并所有结果
                events = items_or_events or []
                todos_list = todos or []
                reminders_list = reminders or []
                
                items = []
                types = []
                
                for event in events:
                    items.append(event)
                    types.append('event')
                for todo in todos_list:
                    items.append(todo)
                    types.append('todo')
                for reminder in reminders_list:
                    items.append(reminder)
                    types.append('reminder')
            
            # 使用智能去重保存
            return CacheManager.save_search_cache_smart(session_or_id, items, types, user)
            
        except Exception as e:
            logger.error(f"[Cache] 保存混合搜索缓存失败: {e}")
            return False, {}
    
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
                
                # 从 uuid_to_index 中获取编号（如果存在）
                index_key = cache.uuid_to_index.get(item_uuid) if cache.uuid_to_index else None
                
                # 从 index_mapping 中移除
                if index_key and index_key in cache.index_mapping:
                    del cache.index_mapping[index_key]
                    modified = True
                
                # 从 uuid_to_index 中移除
                if cache.uuid_to_index and item_uuid in cache.uuid_to_index:
                    del cache.uuid_to_index[item_uuid]
                    modified = True
                
                # 从 title_mapping 中移除
                new_title_mapping: Dict[str, Dict[str, Any]] = {}
                for title, info in cache.title_mapping.items():
                    if info.get('uuid') != item_uuid:
                        new_title_mapping[title] = info
                    else:
                        modified = True
                
                if modified:
                    cache.title_mapping = new_title_mapping
                    cache.save()
            
            return True
            
        except Exception as e:
            logger.error(f"[Cache] 使缓存失效失败: {e}")
            return False
