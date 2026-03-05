"""
UniScheduler MCP Server
独立的 MCP 服务端，将日程管理工具暴露给外部客户端（Claude Desktop、Copilot 等）

完整复用 agent_service/tools/unified_planner_tools.py 中现有的工具函数，
不修改任何原有代码。每个 MCP 工具只是一个薄包装层：
  1. 构造 RunnableConfig（注入认证用户）
  2. 调用原有 LangChain @tool 函数

使用方式：
  stdio 模式（Claude Desktop 本地）:
    set MCP_USER_TOKEN=your_token
    python mcp_server.py

  HTTP 模式（远程客户端）:
    python mcp_server.py --http --port 8100
"""

import os
import sys
import argparse
import contextvars

# ============================================================
# Django 初始化 — 必须在导入任何 Django model 之前
# ============================================================
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'UniSchedulerSuper.settings')

import django
django.setup()

# ============================================================
# 导入依赖
# ============================================================
from typing import Optional, List, Literal

from mcp.server.fastmcp import FastMCP

# 导入现有工具（LangChain @tool 装饰的函数）
from agent_service.tools.unified_planner_tools import (
    search_items as _search_items,
    create_item as _create_item,
    update_item as _update_item,
    delete_item as _delete_item,
    complete_todo as _complete_todo,
    get_event_groups as _get_event_groups,
    get_share_groups as _get_share_groups,
    check_schedule_conflicts as _check_schedule_conflicts,
)

from rest_framework.authtoken.models import Token
from django.contrib.auth.models import User

from logger import logger

# ============================================================
# 用户认证
# ============================================================

# stdio 模式下的全局用户（启动时从 MCP_USER_TOKEN 解析）
_stdio_user: Optional[User] = None

# contextvars 用于 HTTP 模式下在 verify_token 和 tool 之间传递用户
_current_user_var: contextvars.ContextVar[Optional[User]] = contextvars.ContextVar(
    'mcp_current_user', default=None
)

# Token -> User 缓存（避免每次 tool 调用都查数据库）
_token_user_cache: dict[str, User] = {}


def _resolve_user_from_token(token_str: str) -> Optional[User]:
    """从 Token 字符串解析 Django User 对象"""
    if token_str in _token_user_cache:
        return _token_user_cache[token_str]
    try:
        token_obj = Token.objects.select_related('user').get(key=token_str)
        _token_user_cache[token_str] = token_obj.user
        return token_obj.user
    except Token.DoesNotExist:
        return None


def _get_current_user() -> User:
    """获取当前请求的认证用户"""
    # 优先从 contextvars 获取（HTTP 模式）
    user = _current_user_var.get(None)
    if user is not None:
        return user

    # 兜底使用 stdio 模式的全局用户
    if _stdio_user is not None:
        return _stdio_user

    raise ValueError("未找到认证用户。stdio 模式请通过 --token <TOKEN> 参数或 MCP_USER_TOKEN 环境变量指定；HTTP 模式请在请求头中提供 Authorization: Bearer <token>")


def _build_config(user: User) -> dict:
    """构造 LangChain RunnableConfig，注入用户信息"""
    # 每个用户使用独立的 session_id，避免多用户共用同一缓存导致 #序号 串台
    user_session_id = f"mcp_{user.id}"
    return {
        "configurable": {
            "user": user,
            "session_id": user_session_id,
            "thread_id": user_session_id,
        }
    }


# ============================================================
# 创建 FastMCP 服务端
# ============================================================
mcp = FastMCP(
    "UniScheduler",
    instructions="UniScheduler 日程管理系统的 MCP 服务端。提供日程、待办、提醒的搜索、创建、更新、删除功能。",
    stateless_http=True,
    json_response=True,
)


# ============================================================
# MCP 工具定义 — 薄包装层，调用现有 unified_planner_tools
# ============================================================

@mcp.tool()
async def search_items(
    item_type: str = "all",
    keyword: Optional[str] = None,
    time_range: Optional[str] = None,
    status: Optional[str] = None,
    event_group: Optional[str] = None,
    share_groups: Optional[List[str]] = None,
    share_groups_only: bool = False,
    limit: int = 20,
) -> str:
    """
    统一搜索日程、待办、提醒

    Args:
        item_type: 类型过滤 - "event"(日程), "todo"(待办), "reminder"(提醒), "all"(全部)
        keyword: 关键词搜索（标题/描述匹配）
        time_range: 时间范围 - 预设("today","tomorrow","this_week","next_week","this_month")
                    或中文("今天","明天","本周","下周","本月") 或自定义("2024-01-01 ~ 2024-01-31")
        status: 状态过滤 - 待办("pending","completed","all"), 提醒("active","snoozed","dismissed","all")
        event_group: 日程组过滤（支持名称或UUID）
        share_groups: 分享组列表（支持名称或ID），None=所有，[]=仅自己
        share_groups_only: 是否仅搜索分享组内容
        limit: 返回数量上限，默认20
    """
    from asgiref.sync import sync_to_async
    user = await sync_to_async(_get_current_user)()
    config = _build_config(user)
    input_args = {
        "item_type": item_type,
        "keyword": keyword,
        "time_range": time_range,
        "status": status,
        "event_group": event_group,
        "share_groups": share_groups,
        "share_groups_only": share_groups_only,
        "limit": limit,
    }
    return await sync_to_async(_search_items.invoke)(input=input_args, config=config)


@mcp.tool()
async def create_item(
    item_type: str,
    title: str,
    description: Optional[str] = None,
    # 日程参数
    start: Optional[str] = None,
    end: Optional[str] = None,
    event_group: Optional[str] = None,
    importance: Optional[str] = None,
    urgency: Optional[str] = None,
    shared_to_groups: Optional[List[str]] = None,
    ddl: Optional[str] = None,
    # 待办参数
    due_date: Optional[str] = None,
    priority: Optional[str] = None,
    # 提醒参数
    trigger_time: Optional[str] = None,
    content: Optional[str] = None,
    # 重复规则
    repeat: Optional[str] = None,
) -> str:
    """
    创建日程/待办/提醒

    Args:
        item_type: 类型 - "event"(日程), "todo"(待办), "reminder"(提醒)
        title: 标题（必填）
        description: 描述/备注
        start: 日程开始时间 (格式: "2024-01-15T09:00")
        end: 日程结束时间
        event_group: 事件组（支持名称，如"工作"会自动查找对应UUID）
        importance: 重要程度 ("important", "not-important")
        urgency: 紧急程度 ("urgent", "not-urgent")
        shared_to_groups: 分享到的群组列表（支持群组名称）
        ddl: 截止日期
        due_date: 待办截止日期 (格式: "2024-01-15")
        priority: 优先级 - 待办("high","medium","low"), 提醒("high","normal","low")
        trigger_time: 提醒触发时间 (格式: "2024-01-15T09:00")
        content: 提醒内容
        repeat: 重复规则 - 简化格式("每天","每周","每月","每周一三五","工作日","周末") 或标准 RRULE
    """
    from asgiref.sync import sync_to_async
    user = await sync_to_async(_get_current_user)()
    config = _build_config(user)
    input_args = {
        "item_type": item_type,
        "title": title,
        "description": description,
        "start": start,
        "end": end,
        "event_group": event_group,
        "importance": importance,
        "urgency": urgency,
        "shared_to_groups": shared_to_groups,
        "ddl": ddl,
        "due_date": due_date,
        "priority": priority,
        "trigger_time": trigger_time,
        "content": content,
        "repeat": repeat,
    }
    return await sync_to_async(_create_item.invoke)(input=input_args, config=config)


@mcp.tool()
async def update_item(
    identifier: str,
    item_type: Optional[str] = None,
    edit_scope: str = "single",
    from_time: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    event_group: Optional[str] = None,
    importance: Optional[str] = None,
    urgency: Optional[str] = None,
    shared_to_groups: Optional[List[str]] = None,
    ddl: Optional[str] = None,
    due_date: Optional[str] = None,
    priority: Optional[str] = None,
    status: Optional[str] = None,
    trigger_time: Optional[str] = None,
    content: Optional[str] = None,
    repeat: Optional[str] = None,
    clear_repeat: bool = False,
) -> str:
    """
    更新日程/待办/提醒（增量更新，只需传入要修改的字段）

    Args:
        identifier: 项目标识 - "#1"(搜索结果序号), UUID, 或标题（模糊匹配）
        item_type: 可选类型指定 - "event", "todo", "reminder"
        edit_scope: 编辑范围（重复项目）- "single"(仅当前), "all"(整个系列), "future"(此及之后), "from_time"(从指定时间)
        from_time: 当 edit_scope="from_time" 时必填
        title: 新标题
        description: 新描述
        start: 新开始时间
        end: 新结束时间
        event_group: 新事件组（名称或UUID）
        importance: 重要程度
        urgency: 紧急程度
        shared_to_groups: 分享群组列表（传空列表可清除分享）
        ddl: 截止日期
        due_date: 待办截止日期
        priority: 优先级
        status: 状态 - "pending", "completed"
        trigger_time: 提醒触发时间
        content: 提醒内容
        repeat: 新的重复规则
        clear_repeat: 为True时清除重复规则
    """
    from asgiref.sync import sync_to_async
    user = await sync_to_async(_get_current_user)()
    config = _build_config(user)
    input_args = {
        "identifier": identifier,
        "item_type": item_type,
        "edit_scope": edit_scope,
        "from_time": from_time,
        "title": title,
        "description": description,
        "start": start,
        "end": end,
        "event_group": event_group,
        "importance": importance,
        "urgency": urgency,
        "shared_to_groups": shared_to_groups,
        "ddl": ddl,
        "due_date": due_date,
        "priority": priority,
        "status": status,
        "trigger_time": trigger_time,
        "content": content,
        "repeat": repeat,
        "clear_repeat": clear_repeat,
    }
    return await sync_to_async(_update_item.invoke)(input=input_args, config=config)


@mcp.tool()
async def delete_item(
    identifier: str,
    item_type: Optional[str] = None,
    delete_scope: str = "single",
) -> str:
    """
    删除日程/待办/提醒

    Args:
        identifier: 项目标识 - "#1"(搜索结果序号), UUID, 或标题
        item_type: 可选类型指定 - "event", "todo", "reminder"
        delete_scope: 删除范围（重复项目）- "single"(仅当前), "all"(整个系列), "future"(此及之后)
    """
    from asgiref.sync import sync_to_async
    user = await sync_to_async(_get_current_user)()
    config = _build_config(user)
    input_args = {
        "identifier": identifier,
        "item_type": item_type,
        "delete_scope": delete_scope,
    }
    return await sync_to_async(_delete_item.invoke)(input=input_args, config=config)


@mcp.tool()
async def complete_todo(identifier: str) -> str:
    """
    快捷完成待办事项（标记为已完成）

    Args:
        identifier: 待办标识 - "#1"(搜索结果序号), UUID, 或标题
    """
    from asgiref.sync import sync_to_async
    user = await sync_to_async(_get_current_user)()
    config = _build_config(user)
    return await sync_to_async(_complete_todo.invoke)(input={"identifier": identifier}, config=config)


@mcp.tool()
async def get_event_groups() -> str:
    """获取用户的所有事件组列表，用于在创建/更新日程时选择事件组"""
    from asgiref.sync import sync_to_async
    user = await sync_to_async(_get_current_user)()
    config = _build_config(user)
    return await sync_to_async(_get_event_groups.invoke)(input={}, config=config)


@mcp.tool()
async def get_share_groups() -> str:
    """获取用户所在的所有分享组列表，用于查看可用的分享组以便在搜索或创建日程时使用"""
    from asgiref.sync import sync_to_async
    user = await sync_to_async(_get_current_user)()
    config = _build_config(user)
    return await sync_to_async(_get_share_groups.invoke)(input={}, config=config)


@mcp.tool()
async def check_schedule_conflicts(
    time_range: str = "this_week",
    include_share_groups: bool = True,
    analysis_focus: Optional[List[str]] = None,
) -> str:
    """
    智能日程冲突检查：结合算法检测和LLM分析，给出日程优化建议

    Args:
        time_range: 时间范围 - "today","this_week","next_week","this_month" 等
        include_share_groups: 是否包含分享组日程
        analysis_focus: 分析侧重 - ["conflicts"(冲突), "density"(密度), "reasonability"(合理性)]
    """
    from asgiref.sync import sync_to_async
    user = await sync_to_async(_get_current_user)()
    config = _build_config(user)
    input_args = {
        "time_range": time_range,
        "include_share_groups": include_share_groups,
        "analysis_focus": analysis_focus,
    }
    return await sync_to_async(_check_schedule_conflicts.invoke)(input=input_args, config=config)


# ============================================================
# 入口
# ============================================================

def _init_stdio_user(token_str: str = ""):
    """
    stdio 模式下解析并绑定全局用户。

    Token 优先级（高 → 低）：
    1. 命令行 --token 参数（显式传入）
    2. MCP_USER_TOKEN 环境变量
    """
    global _stdio_user
    # 优先使用显式传入的 token，否则读环境变量
    token_str = token_str or os.environ.get('MCP_USER_TOKEN', '')
    if not token_str:
        print("❌ 未指定用户 Token，stdio 模式至少需要以下之一：", file=sys.stderr)
        print("   1. 命令行参数:    python mcp_server.py --token <YOUR_TOKEN>", file=sys.stderr)
        print("   2. 环境变量:      set MCP_USER_TOKEN=<YOUR_TOKEN> && python mcp_server.py", file=sys.stderr)
        sys.exit(1)

    user = _resolve_user_from_token(token_str)
    if user is None:
        print(f"❌ Token 无效或用户不存在: {token_str[:8]}...", file=sys.stderr)
        sys.exit(1)

    _stdio_user = user
    print(f"✅ 已认证用户: {user.username} (ID: {user.id})", file=sys.stderr)


def _setup_http_auth():
    """HTTP 模式下配置 Token 认证"""
    try:
        from mcp.server.auth.provider import AccessToken, TokenVerifier
        from mcp.server.auth.settings import AuthSettings
        from pydantic import AnyHttpUrl

        class DjangoTokenVerifier(TokenVerifier):
            """使用 Django REST Framework Token 验证 MCP 请求"""

            async def verify_token(self, token: str) -> Optional[AccessToken]:
                from asgiref.sync import sync_to_async
                try:
                    user = await sync_to_async(_resolve_user_from_token)(token)
                    if user is None:
                        return None

                    # 将用户存入 contextvars，供工具函数读取
                    _current_user_var.set(user)

                    return AccessToken(
                        token=token,
                        client_id=str(user.id),
                        scopes=["user"],
                    )
                except Exception as e:
                    logger.error(f"Token 验证失败: {e}")
                    return None

        return DjangoTokenVerifier()

    except ImportError as e:
        print(f"⚠️  HTTP 认证模块导入失败: {e}", file=sys.stderr)
        print("   请确保已安装 mcp[cli] 包", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser(description="UniScheduler MCP Server")
    parser.add_argument(
        '--http', action='store_true',
        help='使用 streamable-http 传输（远程模式），默认为 stdio（本地模式）'
    )
    parser.add_argument(
        '--token', type=str, default='',
        metavar='TOKEN',
        help='用户认证 Token（stdio 模式首选方式，优先级高于 MCP_USER_TOKEN 环境变量）'
    )
    parser.add_argument(
        '--port', type=int, default=8100,
        help='HTTP 模式的端口号（默认 8100）'
    )
    parser.add_argument(
        '--host', type=str, default='0.0.0.0',
        help='HTTP 模式的绑定地址（默认 0.0.0.0）'
    )
    parser.add_argument(
        '--no-auth', action='store_true',
        help='HTTP 模式下禁用 Token 认证（仅用于开发测试）'
    )
    args = parser.parse_args()

    if args.http:
        # HTTP 模式
        transport = "streamable-http"
        mcp.settings.host = args.host
        mcp.settings.port = args.port

        # 检查是否有固定用户 Token（可选，用于单用户简化场景）
        token_str = os.environ.get('MCP_USER_TOKEN', '')
        if token_str:
            global _stdio_user
            user = _resolve_user_from_token(token_str)
            if user:
                _stdio_user = user
                print(f"✅ HTTP 模式 - 固定用户: {user.username}", file=sys.stderr)

        # 配置认证
        if not args.no_auth:
            verifier = _setup_http_auth()
            if verifier:
                mcp._tool_manager  # ensure initialized
                print("ℹ️  HTTP 认证已配置（支持 Header 或 Query 参数 token=/api_key=）", file=sys.stderr)
        else:
            if not _stdio_user:
                print("⚠️  --no-auth 模式需要设置 MCP_USER_TOKEN 环境变量", file=sys.stderr)
                sys.exit(1)
            print("⚠️  HTTP 认证已禁用（仅用于开发测试）", file=sys.stderr)

        print(f"🚀 UniScheduler MCP Server (HTTP) 启动中...", file=sys.stderr)
        print(f"   地址: http://{args.host}:{args.port}/mcp", file=sys.stderr)
        
        # 拦截 FastMCP 的 ASGI 应用，注入 Query Parameter 到 Authorization Header 的中间件
        import uvicorn
        from urllib.parse import parse_qs, unquote
        
        # 获取原始的 Starlette app
        original_app = mcp.streamable_http_app()
        
        async def query_to_header_middleware(scope, receive, send):
            if scope["type"] == "http":
                # 修复某些 MCP 客户端（如 Cline/VSCode）将 URL 查询参数错误进行 URL 编码并当作 path 处理的问题
                # 例如传来了 /sse%3Fapi_key%3Dxxx -> 被 unquote 后变成 /sse?api_key=xxx
                raw_path = scope.get("path", "")
                decoded_path = unquote(raw_path)
                
                # 如果 path 中包含了 ?，说明客户端错误地把 query 当作 path 发送了
                if "?" in decoded_path:
                    actual_path, fake_query = decoded_path.split("?", 1)
                    scope["path"] = actual_path
                    # 补充或覆盖原来的 query_string
                    if fake_query:
                        scope["query_string"] = fake_query.encode("utf-8")
                
                # 重新解析实际的 Query String
                query_string = scope.get("query_string", b"").decode("utf-8")
                query_params = parse_qs(query_string)
                
                # 提取 token（从 Query 或 Header）
                token = query_params.get("token", [None])[0] or query_params.get("api_key", [None])[0]
                headers = list(scope.get("headers", []))
                
                # 如果 URL 里没有，尝试从 headers 里拿（兼顾纯 Header 调用）
                if not token:
                    for k, v in headers:
                        if k.decode('utf-8').lower() == 'authorization':
                            auth_str = v.decode('utf-8')
                            if auth_str.lower().startswith('bearer '):
                                token = auth_str[7:].strip()
                            break

                if token:
                    # 获取 headers，如果 query 参数里有，则补充进去让 FastMCP 能看到
                    if query_params.get("token") or query_params.get("api_key"):
                        auth_exists = any(k.decode('utf-8').lower() == 'authorization' for k, v in headers)
                        if not auth_exists:
                            headers.append((b'authorization', f'Bearer {token}'.encode('utf-8')))
                            scope["headers"] = headers
                            
                    # 关键修复：MCP 客户端（如 Copilot）在执行工具时，是通过独立的 HTTP POST /messages 请求发送的
                    # 它与最初的 GET /sse 不是同一个 ASGI 上下文。因此我们需要在**每一次完整的 HTTP 路由分发**前，
                    # 拦截并提前设置好 _current_user_var，确保它能被 anyio 传递到同步的 tool 线程中！
                    try:
                        from asgiref.sync import sync_to_async
                        user = await sync_to_async(_resolve_user_from_token)(token)
                        if user:
                            _current_user_var.set(user)
                    except Exception as e:
                        logger.error(f"Middleware 解析用户失败: {e}")
                        
            return await original_app(scope, receive, send)
            
        # 由于 uvicorn 版本差异（部分版本没有 host_header 参数或严格校验不同）
        # 我们这里采用兼容性更好的改写：不传 host_header，而是设置 server_header
        uvicorn.run(
            query_to_header_middleware, 
            host=args.host, 
            port=args.port,
            proxy_headers=True,
            forwarded_allow_ips="*"
        )
        return

    else:
        # stdio 模式
        transport = "stdio"
        _init_stdio_user(args.token)
        print("🚀 UniScheduler MCP Server (stdio) 已启动", file=sys.stderr)

    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
