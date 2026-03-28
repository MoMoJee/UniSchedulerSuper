"""
云盘文件搜索工具 — 供 AI Agent 调用

提供文件搜索和文件内容读取能力，让 Agent 能够：
1. 搜索用户云盘中的文件
2. 读取文件的 Markdown 内容
"""
from typing import Optional
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from logger import logger


@tool
def search_cloud_files(
    config: RunnableConfig,
    query: str,
    category: Optional[str] = None,
    limit: int = 5,
) -> str:
    """
    在用户云盘中搜索文件内容。

    Args:
        query: 搜索关键词
        category: 文件分类过滤，可选 "document"（文档）或 "image"（图片），默认搜索全部
        limit: 返回结果数量上限，默认 5

    Returns:
        匹配的文件列表，包含文件名、相关片段等信息
    """
    from file_service.search import FileSearchEngine

    user = config.get("configurable", {}).get("user")
    if not user:
        return "错误：无法获取用户信息"

    try:
        results = FileSearchEngine.search(
            user=user, query=query, limit=limit, category=category
        )
    except Exception as e:
        logger.warning(f"云盘文件搜索失败: {e}")
        return f"搜索出错: {e}"

    if not results:
        return f"未找到与「{query}」相关的文件"

    lines = [f"找到 {len(results)} 个相关文件：\n"]
    for i, r in enumerate(results, 1):
        uf = r['file']
        lines.append(
            f"{i}. **{uf.filename}** (ID: {uf.id}, 类型: {uf.category})\n"
            f"   相关片段: {r['snippet']}\n"
        )
    return "\n".join(lines)


@tool
def read_cloud_file(
    config: RunnableConfig,
    file_id: int,
    max_chars: int = 8000,
) -> str:
    """
    读取云盘文件的 Markdown 内容。

    Args:
        file_id: 文件 ID（可通过 search_cloud_files 获取）
        max_chars: 最大返回字符数，默认 8000

    Returns:
        文件的 Markdown 文本内容
    """
    from file_service.models import UserFile

    user = config.get("configurable", {}).get("user")
    if not user:
        return "错误：无法获取用户信息"

    try:
        uf = UserFile.objects.get(id=file_id, user=user, is_deleted=False)
    except UserFile.DoesNotExist:
        return f"未找到 ID 为 {file_id} 的文件，或无权访问"

    if uf.is_image:
        return f"文件「{uf.filename}」是图片，无文本内容可读取"

    if not uf.parsed_markdown:
        if uf.parse_status == 'pending':
            return f"文件「{uf.filename}」尚未解析完成，请稍后再试"
        elif uf.parse_status == 'failed':
            return f"文件「{uf.filename}」解析失败: {uf.parse_error}"
        return f"文件「{uf.filename}」暂无可读取的文本内容"

    content = uf.parsed_markdown
    if len(content) > max_chars:
        content = content[:max_chars] + f"\n\n...(内容已截断，共 {len(uf.parsed_markdown)} 字符)"

    return f"## {uf.filename}\n\n{content}"


# 工具映射
CLOUD_FILE_TOOLS_MAP = {
    'search_cloud_files': search_cloud_files,
    'read_cloud_file': read_cloud_file,
}
