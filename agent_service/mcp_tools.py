import asyncio
import logging
import threading
import concurrent.futures
from typing import List, Any, Dict, Tuple
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
        logger.info(f"已配置 MCP 服务: 高德地图 @ {amap_url[:50]}... (SSE)")
    
    # ========== 12306 MCP 服务 (Streamable HTTP 传输) ==========
    mcp_12306_url = APIKeyManager.get_12306_mcp_url()
    if mcp_12306_url:
        config["12306-mcp"] = {
            "url": mcp_12306_url,
            "transport": "streamable_http"  # 12306 使用 Streamable HTTP 协议
        }
        logger.info(f"已配置 MCP 服务: 12306 火车票 @ {mcp_12306_url} (streamable_http)")
    
    return config

MCP_SERVERS_CONFIG = _build_mcp_servers_config()

# 每个 MCP 服务独立的客户端实例（懒加载）
_clients: Dict[str, MultiServerMCPClient] = {}


async def get_single_mcp_service_tools(service_name: str, service_config: Dict[str, Any]) -> Tuple[str, List[StructuredTool]]:
    """
    获取单个 MCP 服务的工具
    
    Args:
        service_name: 服务名称（如 'amap-mcp', '12306-mcp'）
        service_config: 服务配置（包含 url 和 transport）
    
    Returns:
        (service_name, tools) 元组，如果失败则返回空列表
    """
    try:
        # 为每个服务创建独立的客户端
        client = MultiServerMCPClient({service_name: service_config})
        logger.debug(f"正在连接 MCP 服务: {service_name}")
        
        # 获取工具
        tools = await client.get_tools()
        
        if tools:
            logger.info(f"✅ {service_name} 成功加载 {len(tools)} 个工具")
            return (service_name, tools)
        else:
            logger.warning(f"⚠️ {service_name} 连接成功但未返回工具")
            return (service_name, [])
            
    except Exception as e:
        logger.error(f"❌ {service_name} 连接失败: {e}")
        logger.debug(f"详细错误信息:", exc_info=True)
        return (service_name, [])


async def get_mcp_tools_async() -> List[StructuredTool]:
    """
    异步获取所有 MCP 工具（各服务独立连接）
    
    策略：
    - 每个 MCP 服务独立连接
    - 单个服务失败不影响其他服务
    - 只要有任何一个服务成功，就返回成功的工具
    """
    if not MCP_SERVERS_CONFIG:
        logger.warning("没有配置任何 MCP 服务")
        return []
    
    logger.info(f"开始连接 {len(MCP_SERVERS_CONFIG)} 个 MCP 服务: {list(MCP_SERVERS_CONFIG.keys())}")
    
    # 并发连接所有服务（使用 gather 而不是 TaskGroup 以避免一个失败导致全部失败）
    tasks = [
        get_single_mcp_service_tools(name, config)
        for name, config in MCP_SERVERS_CONFIG.items()
    ]
    
    # return_exceptions=True 确保单个服务失败不影响其他服务
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 收集所有成功的工具
    all_tools = []
    success_count = 0
    failed_count = 0
    
    for result in results:
        if isinstance(result, Exception):
            # gather 捕获的异常
            logger.error(f"服务连接异常: {result}")
            failed_count += 1
            continue
        
        service_name, tools = result
        if tools:
            all_tools.extend(tools)
            success_count += 1
        else:
            failed_count += 1
    
    # 汇总日志
    if success_count > 0:
        logger.info(f"✅ MCP 工具加载完成: 成功 {success_count} 个服务, 失败 {failed_count} 个服务, 共 {len(all_tools)} 个工具")
    elif failed_count > 0:
        logger.warning(f"⚠️ 所有 MCP 服务均连接失败 ({failed_count} 个)")
    else:
        logger.warning("⚠️ 没有可用的 MCP 服务")
    
    return all_tools

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
