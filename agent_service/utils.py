import functools
import reversion
from core.models import AgentTransaction

def agent_transaction(action_type):
    """
    装饰器：自动为 Tool 创建 Revision 和 AgentTransaction 记录
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 1. 从 kwargs 或 RunnableConfig 中提取 session_id 和 user
            config = kwargs.get('config', {}).get('configurable', {})
            user = config.get('user')
            session_id = config.get('thread_id')

            if not user or not session_id:
                # 如果没有上下文，直接运行（兼容普通调用）
                return func(*args, **kwargs)

            # 2. 开启 Reversion 事务
            # 注意：Service 层内部可能也开启了 create_revision，嵌套使用是支持的
            # 但为了确保 AgentTransaction 关联到正确的 Revision，我们在最外层再包一层
            with reversion.create_revision():
                reversion.set_user(user)
                reversion.set_comment(f"Agent Action: {action_type}")
                
                # 执行实际业务逻辑
                result = func(*args, **kwargs)
                
            # 3. 创建 AgentTransaction 关联记录
            # 在 block 结束后，获取刚刚创建的 revision
            latest_revision = reversion.models.Revision.objects.filter(user=user).order_by('-date_created').first()
            
            if latest_revision:
                description = f"Executed {action_type}"
                # 尝试从结果中提取更多信息
                if isinstance(result, dict):
                    if 'title' in result:
                        description += f": {result['title']}"
                    elif 'id' in result:
                        description += f" (ID: {result['id']})"
                elif hasattr(result, 'title'):
                    description += f": {result.title}"
                elif isinstance(result, str):
                    description += f": {result[:50]}"
                    
                AgentTransaction.objects.create(
                    session_id=session_id,
                    revision=latest_revision,
                    action_type=action_type,
                    description=description
                )
                
            return result
        return wrapper
    return decorator
