from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from agent_service.models import UserMemory, MemoryItem
from agent_service.utils import agent_transaction
from django.db.models import Q

@tool
@agent_transaction(action_type="save_memory")
def save_memory(content: str, category: str = "general", importance: int = 1, config: RunnableConfig = None) -> str:
    """
    保存一条关于用户的记忆。当用户提到个人喜好、重要事实或长期计划时使用。
    Args:
        content: 记忆内容
        category: 类别 (preference, fact, plan, general)
        importance: 重要性 (1-5, 5为最重要)
    """
    user = config.get("configurable", {}).get("user")
    if not user: return "Error: User not found."
    
    try:
        user_memory, _ = UserMemory.objects.get_or_create(user=user)
        MemoryItem.objects.create(
            memory=user_memory,
            content=content,
            category=category,
            importance=importance
        )
        return "记忆已保存。"
    except Exception as e:
        return f"保存失败: {str(e)}"

@tool
def search_memory(query: str, config: RunnableConfig) -> str:
    """
    搜索关于用户的记忆。当需要回忆用户之前的偏好或信息时使用。
    Args:
        query: 搜索关键词
    """
    user = config.get("configurable", {}).get("user")
    if not user: return "Error: User not found."
    
    try:
        user_memory = UserMemory.objects.filter(user=user).first()
        if not user_memory: return "没有找到相关记忆。"
        
        items = MemoryItem.objects.filter(
            memory=user_memory,
            content__icontains=query
        ).order_by('-importance', '-created_at')[:5]
        
        if not items: return "没有找到相关记忆。"
        
        result = "相关记忆:\n"
        for item in items:
            result += f"- [{item.category}] {item.content}\n"
        return result
    except Exception as e:
        return f"搜索失败: {str(e)}"

@tool
def get_recent_memories(limit: int = 5, config: RunnableConfig = None) -> str:
    """
    获取最近的记忆。
    Args:
        limit: 获取数量
    """
    user = config.get("configurable", {}).get("user")
    if not user: return "Error: User not found."
    
    try:
        user_memory = UserMemory.objects.filter(user=user).first()
        if not user_memory: return "没有记忆。"
        
        items = MemoryItem.objects.filter(memory=user_memory).order_by('-created_at')[:limit]
        
        result = "最近记忆:\n"
        for item in items:
            result += f"- [{item.category}] {item.content}\n"
        return result
    except Exception as e:
        return f"获取失败: {str(e)}"
