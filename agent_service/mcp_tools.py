import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.tools import StructuredTool, tool
from langchain_core.runnables import RunnableConfig
from agent_service.memory_store import store

# 配置 MCP 客户端
client = MultiServerMCPClient(
    {
        "amap-amap-sse": {
            "url": "https://mcp.amap.com/sse?key=0473448f0b67ef98d9a6da61c4b220f0",
            "transport": "sse"
        },
        "unischedulersuper": {
            "command": "python",
            "args": ["d:/PROJECTS/UniSchedulerSuper/agent_service/mcp_server.py"],
            "transport": "stdio"
        }
    },
)

async def get_mcp_tools_async():
    """异步获取 MCP 工具"""
    try:
        return await client.get_tools()
    except Exception as e:
        print(f"警告: 无法连接到 MCP 服务器: {e}")
        return []

def async_to_sync_tool(async_tool):
    """将异步工具转换为同步工具"""
    
    # 获取原始的异步函数
    original_coroutine = async_tool.coroutine
    
    # 创建同步包装函数
    def sync_wrapper(*args, **kwargs):
        """同步包装器,在新的事件循环中运行异步函数"""
        try:
            # 尝试获取当前事件循环
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果循环正在运行,创建新的循环
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, original_coroutine(*args, **kwargs))
                    return future.result()
            else:
                # 如果循环未运行,直接运行
                return loop.run_until_complete(original_coroutine(*args, **kwargs))
        except RuntimeError:
            # 如果没有事件循环,创建新的
            return asyncio.run(original_coroutine(*args, **kwargs))
    
    # 创建新的同步工具
    sync_tool = StructuredTool(
        name=async_tool.name,
        description=async_tool.description,
        func=sync_wrapper,
        args_schema=async_tool.args_schema,
    )
    
    return sync_tool

# ==========================================
# 本地记忆检索工具
# ==========================================
@tool
def search_memory(query: str, config: RunnableConfig) -> str:
    """
    搜索用户的过往记忆细节。
    当你需要回忆用户的具体偏好、经历或细节，而这些信息不在系统提示词的【核心画像】中时，使用此工具。
    
    Args:
        query: 搜索关键词
    """
    user_id = config.get("configurable", {}).get("user_id")
    if not user_id:
        return "无法获取用户ID，搜索失败。"
        
    # 在 InMemoryStore 中搜索
    # 注意：由于未配置 Embedding，这里使用简单的文本包含匹配
    # 生产环境应配置 Vector Store 以支持语义搜索
    results = store.search(("users", str(user_id), "memories"))
    
    matched_memories = []
    for item in results:
        content = item.value.get("content", "")
        # 简单的关键词匹配
        if query.lower() in content.lower():
            matched_memories.append(content)
            
    if not matched_memories:
        return f"未找到关于 '{query}' 的相关记忆。"
        
    return f"找到以下相关记忆:\n" + "\n".join([f"- {m}" for m in matched_memories])

def load_mcp_tools():
    """加载并返回同步的 MCP 工具列表"""
    print("正在加载 MCP 工具...")
    try:
        async_tools = asyncio.run(get_mcp_tools_async())
        sync_tools = [async_to_sync_tool(tool) for tool in async_tools]
        
        # 添加本地记忆搜索工具
        sync_tools.append(search_memory)
        
        print(f"成功加载 {len(sync_tools)} 个工具 (含本地工具)")
        return sync_tools
    except Exception as e:
        print(f"加载 MCP 工具失败: {e}")
        return [search_memory] # 即使 MCP 失败，也返回本地工具
