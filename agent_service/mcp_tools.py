import asyncio
import logging
import threading
import concurrent.futures
from typing import List, Any, Dict
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.tools import StructuredTool, Tool
from langchain_core.runnables import RunnableConfig

# 配置日志
from logger import logger

# 从统一配置读取 API 密钥
from config.api_keys_manager import APIKeyManager

# 动态构建 MCP 服务器配置
def _build_mcp_servers_config() -> Dict[str, Dict[str, Any]]:
    """
    动态构建所有 MCP 服务器配置
    
    支持的 MCP 服务:
    - 高德地图 (amap): 地点搜索、路线规划、周边搜索 (SSE 传输)
    - 12306: 火车票查询、车站搜索、余票查询、换乘方案 (Streamable HTTP 传输)
    """
    config = {}
    
    # ========== 高德地图 MCP 服务 (SSE 传输) ==========
    amap_url = APIKeyManager.get_amap_mcp_url()
    if amap_url:
        config["amap-mcp"] = {
            "url": amap_url,
            "transport": "sse"
        }
        logger.info(f"已加载 MCP 服务: 高德地图 @ {amap_url[:50]}... (SSE)")
    
    # ========== 12306 MCP 服务 (Streamable HTTP 传输) ==========
    mcp_12306_url = APIKeyManager.get_12306_mcp_url()
    if mcp_12306_url:
        config["12306-mcp"] = {
            "url": mcp_12306_url,
            "transport": "streamable_http"  # 12306 使用 Streamable HTTP 协议
        }
        logger.info(f"已加载 MCP 服务: 12306 火车票 @ {mcp_12306_url} (streamable_http)")
    
    return config

MCP_SERVERS_CONFIG = _build_mcp_servers_config()

# 延迟初始化 client，避免启动时阻塞
_client = None

def _get_client():
    """获取或创建 MCP 客户端"""
    global _client
    if _client is None:
        _client = MultiServerMCPClient(MCP_SERVERS_CONFIG)
    return _client

async def get_mcp_tools_async() -> List[StructuredTool]:
    """异步获取 MCP 工具"""
    if not MCP_SERVERS_CONFIG:
        logger.warning("没有配置任何 MCP 服务")
        return []
    
    try:
        client = _get_client()
        logger.info(f"正在连接 MCP 服务器: {list(MCP_SERVERS_CONFIG.keys())}")
        
        # client.get_tools() 返回的是 LangChain Tools 列表
        tools = await client.get_tools()
        
        if tools:
            logger.info(f"成功获取 {len(tools)} 个 MCP 工具")
            for t in tools:
                logger.debug(f"  - {t.name}: {t.description[:50] if t.description else 'N/A'}...")
        else:
            logger.warning("MCP 服务连接成功但未返回任何工具")
            
        return tools
    except Exception as e:
        logger.error(f"无法连接到 MCP 服务器: {e}", exc_info=True)
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
