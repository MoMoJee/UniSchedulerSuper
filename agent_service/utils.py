import functools
from logger import logger
import reversion
from agent_service.models import AgentTransaction
from core.models import UserData

def agent_transaction(action_type):
    """
    装饰器：自动为 Tool 创建 Revision 和 AgentTransaction 记录
    用于支持 Agent 操作的回滚功能
    
    关键：在执行操作**之前**保存快照，这样回滚时可以恢复到操作前的状态
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 1. 从 kwargs 中提取 config
            config = kwargs.get('config')
            
            # 处理 config 为 None 或不存在的情况
            if config is None:
                logger.debug(f"agent_transaction: config is None, running without tracking")
                return func(*args, **kwargs)
            
            # 从 config 中提取 configurable
            configurable = config.get('configurable', {}) if isinstance(config, dict) else getattr(config, 'configurable', {})
            if configurable is None:
                configurable = {}
                
            user = configurable.get('user')
            session_id = configurable.get('thread_id')
            tool_call_id = configurable.get('tool_call_id')  # 获取 tool_call_id

            if not user or not session_id:
                # 如果没有上下文，直接运行（兼容普通调用）
                logger.debug(f"agent_transaction: no user ({user}) or session_id ({session_id}), running without tracking")
                return func(*args, **kwargs)

            logger.info(f"agent_transaction: {action_type} for session {session_id}, user {user}, tool_call_id={tool_call_id}")

            # 2. 在执行操作之前，先保存当前状态的快照
            # 这样回滚时可以恢复到操作前的状态
            # 
            # 【优化】只追踪 Agent 工具实际操作的 UserData keys
            # 避免误伤用户配置（如 user_preference, agent_config 等）
            TRACKED_KEYS = [
                'todos',                    # 待办事项
                'outport_calendar_data',   # 日历导出数据
                'events',                   # 日程
                'events_rrule_series',     # 日程重复规则系列
                'reminders',                # 提醒
                'rrule_series_storage',    # 通用重复规则存储
            ]
            
            with reversion.create_revision():
                reversion.set_user(user)
                reversion.set_comment(f"Before: {action_type}")
                
                # 只保存 Agent 工具会修改的 UserData keys（操作前状态）
                user_data_objects = UserData.objects.filter(user=user, key__in=TRACKED_KEYS)
                for ud in user_data_objects:
                    reversion.add_to_revision(ud)
                
                tracked_count = user_data_objects.count()
                logger.debug(f"Tracking {tracked_count} UserData objects: {TRACKED_KEYS}")
            
            # 获取刚创建的快照 revision（操作前状态）
            before_revision = reversion.models.Revision.objects.filter(user=user).order_by('-date_created').first()
            revision_id = before_revision.id if before_revision else None
            
            logger.info(f"Saved pre-operation snapshot, revision_id={revision_id}")
                
            # 3. 现在执行实际业务逻辑（会修改数据）
            result = func(*args, **kwargs)
            
            # 4. 创建 AgentTransaction 关联记录
            # 构建描述
            description = f"Executed {action_type}"
            metadata = {}
            
            # 保存 tool_call_id 到 metadata，用于回滚时匹配
            if tool_call_id:
                metadata['tool_call_id'] = tool_call_id
            
            # 从 kwargs 中获取标题信息
            title_from_kwargs = kwargs.get('title') or (args[0] if args else None)
            if isinstance(title_from_kwargs, str) and title_from_kwargs:
                description = f"{action_type}: {title_from_kwargs}"
                metadata['title'] = title_from_kwargs
            
            if isinstance(result, dict):
                if 'title' in result:
                    description = f"{action_type}: {result['title']}"
                    metadata['title'] = result['title']
                if 'id' in result:
                    metadata['object_id'] = result['id']
                if 'uid' in result:
                    metadata['uid'] = result['uid']
            elif isinstance(result, str) and len(result) < 200:
                # 如果返回的是简短字符串，也记录下来
                if 'title' not in metadata:
                    description = f"{action_type}: {result[:100]}"
            
            # 创建事务记录，关联操作前的快照
            trans = AgentTransaction.objects.create(
                session_id=session_id,
                user=user,
                action_type=action_type,
                revision_id=revision_id,  # 这里保存的是操作前的快照ID
                metadata=metadata,
                description=description,
                is_rolled_back=False
            )
            logger.info(f"Created AgentTransaction {trans.id}: {description}, revision_id={revision_id} (pre-operation snapshot)")
                
            return result
        return wrapper
    return decorator
