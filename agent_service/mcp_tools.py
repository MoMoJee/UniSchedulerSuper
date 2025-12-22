import asyncio
import logging
import threading
import concurrent.futures
from typing import List, Any
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.tools import StructuredTool, Tool
from langchain_core.runnables import RunnableConfig

# 配置日志
logger = logging.getLogger(__name__)

# 配置 MCP 客户端
# 注意: 这里的配置应该根据实际环境进行调整，或者从 settings 中读取
MCP_SERVERS_CONFIG = {
    "amap-amap-sse": {
            "url": "https://mcp.amap.com/sse?key=0473448f0b67ef98d9a6da61c4b220f0",
            "transport": "sse"
        },
    # "unischedulersuper": {
    #     "command": "python",
    #     "args": ["d:/PROJECTS/UniSchedulerSuper/agent_service/mcp_server.py"],
    #     "transport": "stdio"
    # }
}

client = MultiServerMCPClient(MCP_SERVERS_CONFIG)

async def get_mcp_tools_async() -> List[StructuredTool]:
    """异步获取 MCP 工具"""
    try:
        # client.get_tools() 返回的是 LangChain Tools 列表
        tools = await client.get_tools()
        return tools
    except Exception as e:
        logger.error(f"无法连接到 MCP 服务器: {e}")
        return []

def _run_async_in_thread(coro):
    """
    在新线程中运行异步协程，避免与现有事件循环冲突。
    """
    result = None
    exception = None
    
    def run():
        nonlocal result, exception
        try:
            # 创建新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(coro)
            finally:
                loop.close()
        except Exception as e:
            exception = e
    
    thread = threading.Thread(target=run)
    thread.start()
    thread.join(timeout=30)  # 30秒超时
    
    if exception:
        raise exception
    return result

def convert_async_tool_to_sync(tool: StructuredTool) -> StructuredTool:
    """
    将异步 LangChain Tool 转换为同步 Tool。
    使用线程池确保在任何环境中都能正确运行。
    """
    if not tool.coroutine:
        return tool

    async_func = tool.coroutine

    def sync_wrapper(*args, **kwargs):
        """在新线程中执行异步函数"""
        return _run_async_in_thread(async_func(*args, **kwargs))

    return StructuredTool.from_function(
        func=sync_wrapper,
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        return_direct=tool.return_direct
    )

def get_mcp_tools_sync() -> List[StructuredTool]:
    """
    同步获取并转换所有 MCP 工具。
    这是给 Agent 使用的主要入口点。
    使用线程来避免与现有事件循环冲突。
    """
    try:
        # 在新线程中获取工具
        tools = _run_async_in_thread(get_mcp_tools_async())
        
        if not tools:
            logger.warning("MCP 工具列表为空")
            return []
        
        # 将每个工具转换为同步版本
        sync_tools = [convert_async_tool_to_sync(t) for t in tools]
        logger.info(f"成功加载 {len(sync_tools)} 个 MCP 工具: {[t.name for t in sync_tools]}")
        return sync_tools
    except Exception as e:
        logger.error(f"获取 MCP 工具失败: {e}")
        import traceback
        traceback.print_exc()
        return []
