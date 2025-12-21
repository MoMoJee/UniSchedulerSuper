"""
Agent Service REST API Views
处理会话管理、历史查询和回滚功能
"""
import json
import logging
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

logger = logging.getLogger(__name__)


# ==========================================
# Session 管理 API
# ==========================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_sessions(request):
    """
    获取用户的所有会话列表
    GET /api/agent/sessions/
    
    返回:
    {
        "sessions": [
            {"session_id": "user_1_default", "created_at": "...", "message_count": 10},
            ...
        ]
    }
    """
    from agent_service.agent_graph import app
    from langgraph.checkpoint.memory import MemorySaver
    
    user = request.user
    sessions = []
    
    # 注意：MemorySaver 不持久化，这里只能获取当前内存中的会话
    # 生产环境需要使用持久化存储（如 SQLite/PostgreSQL）
    
    # 暂时返回默认会话信息
    default_session_id = f"user_{user.id}_default"
    
    try:
        # 尝试获取会话状态
        config = {"configurable": {"thread_id": default_session_id}}
        state = app.get_state(config)
        
        if state and state.values:
            message_count = len(state.values.get("messages", []))
            sessions.append({
                "session_id": default_session_id,
                "message_count": message_count,
                "is_default": True
            })
    except Exception as e:
        logger.warning(f"获取会话状态失败: {e}")
    
    return Response({
        "sessions": sessions,
        "user": user.username
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_session(request):
    """
    创建新会话或清除现有会话
    POST /api/agent/sessions/
    
    Body:
    {
        "session_id": "optional_custom_id",  // 可选，不提供则自动生成
        "clear_existing": false  // 是否清除现有会话
    }
    
    返回:
    {
        "session_id": "user_1_xxx",
        "status": "created"
    }
    """
    import uuid
    from agent_service.agent_graph import app
    
    user = request.user
    data = request.data
    
    session_id = data.get("session_id")
    clear_existing = data.get("clear_existing", False)
    
    # 生成或验证 session_id
    if not session_id:
        session_id = f"user_{user.id}_{uuid.uuid4().hex[:8]}"
    else:
        # 确保 session_id 属于当前用户
        if not session_id.startswith(f"user_{user.id}_"):
            return Response(
                {"error": "无效的 session_id 格式"},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    # 如果需要清除现有会话
    if clear_existing:
        # 注意：MemorySaver 的清除需要重新编译 graph
        # 这里我们只是创建一个新的 session_id
        logger.info(f"用户 {user.username} 请求清除会话 {session_id}")
    
    return Response({
        "session_id": session_id,
        "status": "created" if not clear_existing else "cleared"
    })


# ==========================================
# 历史与回滚 API
# ==========================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_history(request):
    """
    获取会话历史
    GET /api/agent/history/?session_id=xxx&limit=20
    
    返回:
    {
        "session_id": "xxx",
        "messages": [
            {"role": "user", "content": "...", "timestamp": "..."},
            {"role": "assistant", "content": "...", "timestamp": "..."},
            ...
        ]
    }
    """
    from agent_service.agent_graph import app
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
    
    user = request.user
    session_id = request.query_params.get("session_id", f"user_{user.id}_default")
    limit = int(request.query_params.get("limit", 50))
    
    # 验证 session_id 归属
    if not session_id.startswith(f"user_{user.id}_"):
        return Response(
            {"error": "无权访问此会话"},
            status=status.HTTP_403_FORBIDDEN
        )
    
    try:
        config = {"configurable": {"thread_id": session_id}}
        state = app.get_state(config)
        
        if not state or not state.values:
            return Response({
                "session_id": session_id,
                "messages": []
            })
        
        messages = state.values.get("messages", [])
        
        # 格式化消息
        formatted_messages = []
        for msg in messages[-limit:]:
            if isinstance(msg, HumanMessage):
                formatted_messages.append({
                    "role": "user",
                    "content": msg.content,
                    "id": msg.id
                })
            elif isinstance(msg, AIMessage):
                formatted_messages.append({
                    "role": "assistant",
                    "content": msg.content,
                    "id": msg.id,
                    "tool_calls": [
                        {"name": tc.get("name"), "args": tc.get("args")}
                        for tc in (msg.tool_calls or [])
                    ] if msg.tool_calls else None
                })
            elif isinstance(msg, ToolMessage):
                formatted_messages.append({
                    "role": "tool",
                    "content": msg.content,
                    "tool_call_id": msg.tool_call_id
                })
        
        return Response({
            "session_id": session_id,
            "messages": formatted_messages
        })
        
    except Exception as e:
        logger.exception(f"获取历史失败: {e}")
        return Response(
            {"error": f"获取历史失败: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def rollback_preview(request):
    """
    预览回滚操作
    POST /api/agent/rollback/preview/
    
    Body:
    {
        "session_id": "xxx",
        "steps": 1  // 回滚几步
    }
    
    返回:
    {
        "can_rollback": true,
        "affected_items": [
            {"type": "event", "action": "delete", "title": "会议"},
            {"type": "todo", "action": "delete", "title": "待办"},
        ],
        "message": "将撤销最近 1 步操作"
    }
    """
    from agent_service.agent_graph import app
    from agent_service.models import AgentTransaction
    
    user = request.user
    data = request.data
    session_id = data.get("session_id", f"user_{user.id}_default")
    steps = data.get("steps", 1)
    
    # 验证 session_id 归属
    if not session_id.startswith(f"user_{user.id}_"):
        return Response(
            {"error": "无权访问此会话"},
            status=status.HTTP_403_FORBIDDEN
        )
    
    try:
        # 查询最近的 Agent 事务
        transactions = AgentTransaction.objects.filter(
            session_id=session_id
        ).order_by('-created_at')[:steps]
        
        if not transactions:
            return Response({
                "can_rollback": False,
                "affected_items": [],
                "message": "没有可回滚的操作"
            })
        
        # 收集受影响的项目
        affected_items = []
        for trans in transactions:
            affected_items.append({
                "type": trans.action_type,
                "action": "rollback",
                "revision_id": trans.revision_id,
                "created_at": trans.created_at.isoformat()
            })
        
        return Response({
            "can_rollback": True,
            "affected_items": affected_items,
            "message": f"将撤销最近 {len(affected_items)} 步操作",
            "steps": len(affected_items)
        })
        
    except Exception as e:
        logger.exception(f"预览回滚失败: {e}")
        return Response(
            {"error": f"预览回滚失败: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def execute_rollback(request):
    """
    执行回滚操作
    POST /api/agent/rollback/
    
    Body:
    {
        "session_id": "xxx",
        "steps": 1
    }
    
    返回:
    {
        "success": true,
        "rolled_back": 1,
        "message": "成功回滚 1 步操作"
    }
    """
    import reversion
    from agent_service.models import AgentTransaction
    
    user = request.user
    data = request.data
    session_id = data.get("session_id", f"user_{user.id}_default")
    steps = data.get("steps", 1)
    
    # 验证 session_id 归属
    if not session_id.startswith(f"user_{user.id}_"):
        return Response(
            {"error": "无权访问此会话"},
            status=status.HTTP_403_FORBIDDEN
        )
    
    try:
        # 获取要回滚的事务
        transactions = list(AgentTransaction.objects.filter(
            session_id=session_id
        ).order_by('-created_at')[:steps])
        
        if not transactions:
            return Response({
                "success": False,
                "rolled_back": 0,
                "message": "没有可回滚的操作"
            })
        
        rolled_back = 0
        
        for trans in transactions:
            if trans.revision_id:
                try:
                    # 使用 django-reversion 回滚
                    revision = reversion.models.Revision.objects.get(id=trans.revision_id)
                    revision.revert()
                    
                    # 标记事务为已回滚
                    trans.is_rolled_back = True
                    trans.save()
                    
                    rolled_back += 1
                    logger.info(f"成功回滚事务 {trans.id}, revision={trans.revision_id}")
                    
                except reversion.models.Revision.DoesNotExist:
                    logger.warning(f"Revision {trans.revision_id} 不存在")
                except Exception as e:
                    logger.error(f"回滚事务 {trans.id} 失败: {e}")
        
        return Response({
            "success": rolled_back > 0,
            "rolled_back": rolled_back,
            "message": f"成功回滚 {rolled_back} 步操作"
        })
        
    except Exception as e:
        logger.exception(f"执行回滚失败: {e}")
        return Response(
            {"error": f"执行回滚失败: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ==========================================
# Agent 配置 API (简化版)
# ==========================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_available_experts(request):
    """
    获取可用的专家列表
    GET /api/agent/experts/
    
    返回:
    {
        "experts": [
            {"name": "planner", "display_name": "日程管理", "description": "..."},
            {"name": "map", "display_name": "地图查询", "description": "..."},
            {"name": "chat", "display_name": "闲聊助手", "description": "..."},
        ]
    }
    """
    experts = [
        {
            "name": "planner",
            "display_name": "日程管理",
            "description": "管理日程、待办、提醒",
            "available": True
        },
        {
            "name": "map",
            "display_name": "地图查询",
            "description": "查询地点、规划路线",
            "available": False  # MCP 服务可能不可用
        },
        {
            "name": "chat",
            "display_name": "闲聊助手",
            "description": "闲聊和记忆管理",
            "available": True
        }
    ]
    
    return Response({"experts": experts})


# ==========================================
# 健康检查
# ==========================================

@api_view(['GET'])
def health_check(request):
    """
    健康检查端点
    GET /api/agent/health/
    """
    return Response({
        "status": "healthy",
        "service": "agent_service"
    })
