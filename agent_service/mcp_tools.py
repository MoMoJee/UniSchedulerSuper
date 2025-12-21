import asyncio
import logging
from typing import List, Any
from asgiref.sync import async_to_sync
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

def convert_async_tool_to_sync(tool: StructuredTool) -> StructuredTool:
    """
    将异步 LangChain Tool 转换为同步 Tool。
    使用 asgiref.sync.async_to_sync 确保在 Django 环境中正确运行。
    """
    if not tool.coroutine:
        return tool

    async_func = tool.coroutine

    def sync_wrapper(*args, **kwargs):
        return async_to_sync(async_func)(*args, **kwargs)

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
    """
    try:
        # 1. 异步获取工具 (需要在 async 上下文中运行，或者使用 async_to_sync)
        # 由于 get_tools 涉及网络 IO，我们需要小心处理
        async_get = async_to_sync(get_mcp_tools_async)
        tools = async_get()
        
        # 2. 将每个工具转换为同步版本
        sync_tools = [convert_async_tool_to_sync(t) for t in tools]
        return sync_tools
    except Exception as e:
        logger.error(f"获取 MCP 工具失败: {e}")
        return []
