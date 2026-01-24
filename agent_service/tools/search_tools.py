"""
联网搜索工具
基于 Tavily API 提供实时网络搜索能力

使用前需要在 config/api_keys.json 中配置 tavily api_key:
{
    "search_services": {
        "tavily": {
            "api_key": "your-tavily-api-key"
        }
    }
}
"""
import logging
from typing import Optional, Literal, List
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from config.api_keys_manager import APIKeyManager

from logger import logger

# Tavily 客户端实例（延迟初始化）
_tavily_client = None


def _get_tavily_client():
    """获取 Tavily 客户端实例（延迟初始化）"""
    global _tavily_client
    
    if _tavily_client is not None:
        return _tavily_client
    
    api_key = APIKeyManager.get_search_service_key('tavily')
    if not api_key:
        logger.warning("Tavily API key 未配置，请在 config/api_keys.json 中设置")
        return None
    
    try:
        from tavily import TavilyClient
        _tavily_client = TavilyClient(api_key)
        logger.info("Tavily 客户端初始化成功")
        return _tavily_client
    except ImportError:
        logger.error("tavily-python 未安装，请运行: pip install tavily-python")
        return None
    except Exception as e:
        logger.error(f"Tavily 客户端初始化失败: {e}")
        return None


def _format_search_results(results: dict, max_results: int = 5) -> str:
    """格式化搜索结果"""
    if not results:
        return "搜索未返回结果"
    
    search_results = results.get('results', [])
    if not search_results:
        return "未找到相关结果"
    
    # 限制结果数量
    search_results = search_results[:max_results]
    
    output_lines = [f"找到 {len(search_results)} 条相关结果：\n"]
    
    for i, result in enumerate(search_results, 1):
        title = result.get('title', '无标题')
        url = result.get('url', '')
        content = result.get('content', '')
        score = result.get('score', 0)
        
        # 截断过长的内容
        if len(content) > 300:
            content = content[:300] + "..."
        
        output_lines.append(f"【{i}】{title}")
        output_lines.append(f"   链接: {url}")
        output_lines.append(f"   摘要: {content}")
        if score:
            output_lines.append(f"   相关度: {score:.2f}")
        output_lines.append("")
    
    # 如果有 answer 字段（Tavily 的 AI 总结）
    answer = results.get('answer')
    if answer:
        output_lines.insert(1, f"📝 AI 总结: {answer}\n")
    
    return "\n".join(output_lines)


@tool
def web_search(
    config: RunnableConfig,
    query: str
) -> str:
    """
    简单搜索 - 快速获取网络信息。
    
    只需提供搜索关键词，使用默认参数快速搜索。适合简单的信息查询。
    
    Args:
        query: 搜索关键词，支持自然语言查询
    
    Returns:
        格式化的搜索结果，包含标题、链接、摘要
    
    Examples:
        - web_search("今天天气")
        - web_search("Python 教程")
        - web_search("2024年人工智能发展趋势")
    """
    client = _get_tavily_client()
    if not client:
        return "❌ 搜索服务未配置或初始化失败。请在 config/api_keys.json 中配置 Tavily API key。"
    
    try:
        # 使用默认参数执行搜索
        logger.info(f"[Tavily] 简单搜索: {query}")
        results = client.search(
            query=query,
            search_depth="basic",
            max_results=5,
            include_answer=True
        )
        
        return _format_search_results(results, 5)
        
    except Exception as e:
        logger.error(f"[Tavily] 搜索失败: {e}")
        return f"❌ 搜索失败: {str(e)}"


@tool
def web_search_advanced(
    config: RunnableConfig,
    query: str,
    topic: Optional[Literal["general", "news", "finance"]] = None,
    search_depth: Optional[Literal["basic", "advanced"]] = None,
    max_results: int = 5,
    time_range: Optional[Literal["day", "week", "month", "year"]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    country: Optional[str] = None,
    include_domains: Optional[List[str]] = None,
    exclude_domains: Optional[List[str]] = None,
    include_answer: bool = True
) -> str:
    """
    高级搜索 - 支持丰富的搜索参数，精确控制搜索结果。
    
    适合需要精细控制搜索范围、时间、来源等场景。
    
    Args:
        query: 搜索关键词，支持自然语言查询（必填）
        topic: 搜索主题类型
            - None 或 "general": 通用搜索（默认）
            - "news": 新闻搜索
            - "finance": 财经搜索
        search_depth: 搜索深度
            - None 或 "basic": 基础搜索，速度快（默认）
            - "advanced": 深度搜索，结果更精准但较慢
        max_results: 返回结果数量（1-10，默认5）
        time_range: 时间范围过滤（与 start_date/end_date 二选一）
            - None: 不限时间（默认）
            - "day": 最近一天
            - "week": 最近一周
            - "month": 最近一月
            - "year": 最近一年
        start_date: 开始日期，格式 YYYY-MM-DD（如 "2024-01-01"）
        end_date: 结束日期，格式 YYYY-MM-DD（如 "2024-12-31"）
        country: 国家/地区过滤（如 "china", "us"），仅在 topic 为 general 时有效
        include_domains: 只搜索这些域名（如 ["zhihu.com", "weibo.com"]）
        exclude_domains: 排除这些域名（如 ["example.com"]）
        include_answer: 是否包含 AI 生成的答案总结（默认 True）
    
    Returns:
        格式化的搜索结果，包含标题、链接、摘要
    
    Examples:
        - web_search_advanced("特斯拉股价", topic="finance")
        - web_search_advanced("科技新闻", topic="news", time_range="day")
        - web_search_advanced("Python教程", include_domains=["csdn.net", "zhihu.com"])
        - web_search_advanced("AI发展", start_date="2024-01-01", end_date="2024-06-30")
    """
    client = _get_tavily_client()
    if not client:
        return "❌ 搜索服务未配置或初始化失败。请在 config/api_keys.json 中配置 Tavily API key。"
    
    try:
        # 限制 max_results 范围
        max_results = max(1, min(10, max_results))
        
        # 构建搜索参数
        search_params = {
            "query": query,
            "max_results": max_results,
            "include_answer": include_answer,
        }
        
        # 可选参数 - topic
        if topic and topic != "general":
            search_params["topic"] = topic
        
        # 可选参数 - search_depth
        if search_depth:
            search_params["search_depth"] = search_depth
        
        # 可选参数 - 时间范围（time_range 和 start_date/end_date 二选一）
        if time_range:
            search_params["days"] = {
                "day": 1,
                "week": 7,
                "month": 30,
                "year": 365
            }.get(time_range)
        elif start_date or end_date:
            if start_date:
                search_params["start_date"] = start_date
            if end_date:
                search_params["end_date"] = end_date
        
        # 可选参数 - country（仅 general topic 有效）
        if country and (not topic or topic == "general"):
            search_params["country"] = country
        
        # 可选参数 - 域名过滤
        if include_domains:
            search_params["include_domains"] = include_domains
        if exclude_domains:
            search_params["exclude_domains"] = exclude_domains
        
        # 执行搜索
        logger.info(f"[Tavily] 高级搜索: {query}, 参数: {search_params}")
        results = client.search(**search_params)
        
        return _format_search_results(results, max_results)
        
    except Exception as e:
        logger.error(f"[Tavily] 高级搜索失败: {e}")
        return f"❌ 搜索失败: {str(e)}"


# 工具列表导出
SEARCH_TOOLS = [web_search, web_search_advanced]

SEARCH_TOOLS_MAP = {
    "web_search": web_search,
    "web_search_advanced": web_search_advanced,
}


def is_search_available() -> bool:
    """检查搜索服务是否可用"""
    api_key = APIKeyManager.get_search_service_key('tavily')
    return bool(api_key)
