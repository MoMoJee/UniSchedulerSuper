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
            {"session_id": "user_1_xxx", "name": "对话 1", "message_count": 10, ...},
            ...
        ],
        "current_session_id": "user_1_xxx"
    }
    """
    from agent_service.models import AgentSession
    
    user = request.user
    
    # 获取用户的所有会话
    sessions = AgentSession.objects.filter(user=user, is_active=True).order_by('-updated_at')
    
    session_list = []
    for session in sessions:
        session_list.append({
            "session_id": session.session_id,
            "name": session.name,
            "message_count": session.message_count,
            "last_message_preview": session.last_message_preview,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat()
        })
    
    # 获取当前会话 ID
    current_session_id = request.query_params.get("current_session_id")
    
    return Response({
        "sessions": session_list,
        "current_session_id": current_session_id,
        "user": user.username
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_session(request):
    """
    创建新会话
    POST /api/agent/sessions/
    
    Body:
    {
        "name": "可选的会话名称"
    }
    
    返回:
    {
        "session_id": "user_1_xxx",
        "name": "对话 X",
        "status": "created"
    }
    """
    import uuid
    from agent_service.models import AgentSession, AgentTransaction
    
    user = request.user
    data = request.data
    name = data.get("name", "")
    
    # 生成新的 session_id
    session_id = f"user_{user.id}_{uuid.uuid4().hex[:8]}"
    
    # 自动生成会话名称
    if not name:
        count = AgentSession.objects.filter(user=user).count()
        name = f"对话 {count + 1}"
    
    # 创建会话记录
    session = AgentSession.objects.create(
        user=user,
        session_id=session_id,
        name=name
    )
    
    # 注意：切换会话时，旧会话的回滚标记需要重置
    # 这里不做任何操作，让前端在切换时处理
    
    return Response({
        "session_id": session_id,
        "name": name,
        "status": "created"
    })


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_session(request, session_id):
    """
    删除会话
    DELETE /api/agent/sessions/<session_id>/
    """
    from agent_service.models import AgentSession
    
    user = request.user
    
    # 验证权限
    if not session_id.startswith(f"user_{user.id}_"):
        return Response(
            {"error": "无权访问此会话"},
            status=status.HTTP_403_FORBIDDEN
        )
    
    try:
        session = AgentSession.objects.get(session_id=session_id, user=user)
        session.is_active = False  # 软删除
        session.save()
        
        return Response({"status": "deleted"})
    except AgentSession.DoesNotExist:
        return Response(
            {"error": "会话不存在"},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def rename_session(request, session_id):
    """
    重命名会话
    PUT /api/agent/sessions/<session_id>/
    
    Body: {"name": "新名称"}
    """
    from agent_service.models import AgentSession
    
    user = request.user
    
    if not session_id.startswith(f"user_{user.id}_"):
        return Response(
            {"error": "无权访问此会话"},
            status=status.HTTP_403_FORBIDDEN
        )
    
    try:
        session = AgentSession.objects.get(session_id=session_id, user=user)
        session.name = request.data.get("name", session.name)
        session.save()
        
        return Response({
            "session_id": session_id,
            "name": session.name,
            "status": "updated"
        })
    except AgentSession.DoesNotExist:
        return Response(
            {"error": "会话不存在"},
            status=status.HTTP_404_NOT_FOUND
        )


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
            {"role": "user", "content": "...", "index": 0, "can_rollback": true},
            {"role": "assistant", "content": "...", "index": 1},
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
        
        # 格式化消息，添加索引
        formatted_messages = []
        user_message_indices = []  # 记录用户消息的索引
        
        for idx, msg in enumerate(messages[-limit:]):
            if isinstance(msg, HumanMessage):
                user_message_indices.append(idx)
                formatted_messages.append({
                    "role": "user",
                    "content": msg.content,
                    "id": msg.id,
                    "index": idx,
                    "can_rollback": True  # 用户消息可以回滚
                })
            elif isinstance(msg, AIMessage):
                formatted_messages.append({
                    "role": "assistant",
                    "content": msg.content,
                    "id": msg.id,
                    "index": idx,
                    "tool_calls": [
                        {"name": tc.get("name"), "args": tc.get("args")}
                        for tc in (msg.tool_calls or [])
                    ] if msg.tool_calls else None
                })
            elif isinstance(msg, ToolMessage):
                formatted_messages.append({
                    "role": "tool",
                    "content": msg.content,
                    "tool_call_id": msg.tool_call_id,
                    "index": idx
                })
        
        return Response({
            "session_id": session_id,
            "messages": formatted_messages,
            "total_messages": len(messages)
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


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def rollback_to_message(request):
    """
    回滚到特定消息（检查点）
    POST /api/agent/rollback/to-message/
    
    Body:
    {
        "session_id": "xxx",
        "message_index": 5  // 要回滚到的消息索引（删除此索引及之后的消息）
    }
    
    返回:
    {
        "success": true,
        "rolled_back_messages": 3,
        "rolled_back_transactions": 2,
        "message": "成功回滚"
    }
    """
    import reversion
    from agent_service.agent_graph import app, checkpointer
    from agent_service.models import AgentTransaction
    from langchain_core.messages import HumanMessage, AIMessage, RemoveMessage
    
    user = request.user
    data = request.data
    session_id = data.get("session_id", f"user_{user.id}_default")
    message_index = data.get("message_index")
    
    if message_index is None:
        return Response(
            {"error": "缺少 message_index 参数"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # 验证 session_id 归属
    if not session_id.startswith(f"user_{user.id}_"):
        return Response(
            {"error": "无权访问此会话"},
            status=status.HTTP_403_FORBIDDEN
        )
    
    try:
        config = {"configurable": {"thread_id": session_id}}
        
        # 获取当前状态
        current_state = app.get_state(config)
        
        if not current_state or not current_state.values:
            return Response({
                "success": False,
                "message": "会话不存在或为空"
            })
        
        current_messages = current_state.values.get("messages", [])
        logger.info(f"当前消息数: {len(current_messages)}, 要回滚到索引: {message_index}")
        
        if message_index < 0 or message_index >= len(current_messages):
            return Response({
                "success": False,
                "message": f"无效的消息索引: {message_index}"
            })
        
        # 计算需要回滚的消息数量
        rolled_back_messages = len(current_messages) - message_index
        
        # ====== 直接删除消息 ======
        # 使用 RemoveMessage 删除 message_index 及之后的所有消息
        messages_to_remove = []
        for i, msg in enumerate(current_messages):
            if i >= message_index:
                # 获取消息 ID
                msg_id = getattr(msg, 'id', None)
                if msg_id:
                    messages_to_remove.append(RemoveMessage(id=msg_id))
                    logger.info(f"准备删除消息 {i}: id={msg_id}, type={type(msg).__name__}")
        
        if messages_to_remove:
            # 使用 update_state 删除消息
            app.update_state(config, {"messages": messages_to_remove})
            logger.info(f"已提交删除 {len(messages_to_remove)} 条消息")
        else:
            # 如果消息没有 ID，尝试使用 checkpointer 直接操作
            logger.warning("消息没有 ID，尝试直接操作 checkpointer")
            
            # 获取所有历史快照
            history = list(app.get_state_history(config))
            logger.info(f"找到 {len(history)} 个历史快照")
            
            # 找到消息数量 < message_index 的最新快照
            target_snapshot = None
            for snapshot in history:
                snapshot_msgs = snapshot.values.get("messages", [])
                if len(snapshot_msgs) < message_index:
                    target_snapshot = snapshot
                    break
            
            if target_snapshot:
                # 使用目标快照的 checkpoint_id
                target_checkpoint_id = target_snapshot.config.get("configurable", {}).get("checkpoint_id")
                logger.info(f"使用快照 checkpoint_id={target_checkpoint_id}")
                
                # 直接删除 checkpointer 中较新的 checkpoint
                if hasattr(checkpointer, 'storage'):
                    thread_storage = checkpointer.storage.get(session_id, {})
                    if target_checkpoint_id and target_checkpoint_id in thread_storage:
                        # 保留目标及之前的 checkpoint，删除之后的
                        keys_to_delete = []
                        found_target = False
                        for cp_id in list(thread_storage.keys()):
                            if found_target:
                                keys_to_delete.append(cp_id)
                            if cp_id == target_checkpoint_id:
                                found_target = True
                        
                        for cp_id in keys_to_delete:
                            del thread_storage[cp_id]
                        logger.info(f"删除了 {len(keys_to_delete)} 个 checkpoint")
        
        # 验证删除结果
        new_state = app.get_state(config)
        new_messages = new_state.values.get("messages", []) if new_state and new_state.values else []
        logger.info(f"删除后消息数: {len(new_messages)}")
        
        # ====== 回滚数据库事务 ======
        # 回滚该 session 中所有未回滚的事务（从最新到最旧）
        # 因为我们无法精确知道哪些事务对应哪些消息，
        # 所以简单起见，回滚所有在回滚点之后的事务
        transactions = AgentTransaction.objects.filter(
            session_id=session_id,
            is_rolled_back=False
        ).order_by('-created_at')
        
        rolled_back_transactions = 0
        rolled_back_details = []
        
        # 回滚所有未回滚的事务
        for trans in transactions:
            if trans.revision_id:
                try:
                    revision = reversion.models.Revision.objects.get(id=trans.revision_id)
                    revision.revert()
                    trans.is_rolled_back = True
                    trans.save()
                    rolled_back_transactions += 1
                    rolled_back_details.append({
                        "action": trans.action_type,
                        "description": trans.description
                    })
                    logger.info(f"回滚事务 #{trans.id}: {trans.action_type} - {trans.description}")
                except reversion.models.Revision.DoesNotExist:
                    logger.warning(f"Revision {trans.revision_id} 不存在，标记为已回滚")
                    trans.is_rolled_back = True
                    trans.save()
                except Exception as e:
                    logger.error(f"回滚事务 #{trans.id} 失败: {e}")
            else:
                # 没有 revision_id 的事务直接标记为已回滚
                trans.is_rolled_back = True
                trans.save()
                logger.info(f"事务 #{trans.id} 没有 revision_id，已标记为回滚")
        
        logger.info(f"共回滚了 {rolled_back_transactions} 个数据库事务")
        
        return Response({
            "success": True,
            "rolled_back_messages": rolled_back_messages,
            "rolled_back_transactions": rolled_back_transactions,
            "rolled_back_details": rolled_back_details,
            "remaining_messages": len(new_messages),
            "message": f"成功回滚，删除了 {rolled_back_messages} 条消息，撤销了 {rolled_back_transactions} 个操作"
        })
        
    except Exception as e:
        logger.exception(f"执行回滚失败: {e}")
        return Response(
            {"error": f"执行回滚失败: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
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
