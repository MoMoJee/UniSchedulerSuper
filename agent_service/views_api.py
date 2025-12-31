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

from logger import logger


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
    sessions = AgentSession.objects.filter(
        user=user, 
        is_active=True
    ).order_by('-updated_at')
    
    # 从 LangGraph 检查点获取实际消息数量，过滤掉空会话
    from agent_service.agent_graph import app
    
    session_list = []
    for session in sessions:
        # 检查 LangGraph 中是否有消息
        try:
            config = {"configurable": {"thread_id": session.session_id}}
            state = app.get_state(config)
            actual_message_count = 0
            if state and state.values:
                messages = state.values.get("messages", [])
                # 只计算用户消息数量（更准确地反映对话轮数）
                actual_message_count = len([m for m in messages if hasattr(m, 'type') and m.type == 'human'])
                if actual_message_count == 0:
                    # 备选：计算所有消息
                    actual_message_count = len(messages)
        except Exception as e:
            logger.warning(f"获取会话 {session.session_id} 消息数量失败: {e}")
            actual_message_count = session.message_count
        
        # 跳过空会话
        if actual_message_count == 0:
            continue
            
        session_list.append({
            "session_id": session.session_id,
            "name": session.name,
            "message_count": actual_message_count,
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
        
        # 计算起始索引（用于正确返回消息的实际索引）
        total_messages = len(messages)
        start_idx = max(0, total_messages - limit)
        
        for idx, msg in enumerate(messages[-limit:], start=start_idx):
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
    from agent_service.tools.todo_tools import rollback_todos
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
        
        # 打印消息详情用于调试
        for i, msg in enumerate(current_messages):
            msg_id = getattr(msg, 'id', None)
            msg_type = type(msg).__name__
            logger.debug(f"  消息[{i}]: type={msg_type}, id={msg_id}")
        
        # 检查消息列表是否为空
        if len(current_messages) == 0:
            return Response({
                "success": False,
                "message": "会话消息为空，无法回滚"
            })
        
        # 检查索引有效性 - message_index 是要删除的起始位置
        if message_index < 0:
            return Response({
                "success": False,
                "message": f"无效的消息索引: {message_index} (不能为负数)"
            })
        
        if message_index >= len(current_messages):
            return Response({
                "success": False,
                "message": f"无效的消息索引: {message_index} (超出范围，当前消息数: {len(current_messages)})"
            })
        
        # 计算需要回滚的消息数量
        rolled_back_messages = len(current_messages) - message_index
        
        # 在删除前，尝试定位目标检查点用于 TODO 回滚
        target_checkpoint_id = None
        try:
            history = list(app.get_state_history(config))
            # 首选：找到消息数恰好等于目标索引的快照
            for snapshot in history:
                if snapshot.values:
                    msgs = snapshot.values.get("messages", [])
                    if len(msgs) == message_index:
                        target_checkpoint_id = snapshot.config.get("configurable", {}).get("checkpoint_id")
                        break
            # 备选：找到消息数少于目标索引的最近快照
            if not target_checkpoint_id:
                for snapshot in history:
                    if snapshot.values:
                        msgs = snapshot.values.get("messages", [])
                        if len(msgs) < message_index:
                            target_checkpoint_id = snapshot.config.get("configurable", {}).get("checkpoint_id")
                            break
        except Exception as e:
            logger.warning(f"获取用于 TODO 回滚的历史快照失败: {e}")

        # ====== 特殊处理：删除所有消息（message_index = 0）======
        if message_index == 0:
            logger.info("message_index=0，将清空所有消息（直接删除 checkpoint）")
            
            # 直接删除该会话的所有 checkpoint - 这是最可靠的方式
            from agent_service.agent_graph import clear_session_checkpoints
            success = clear_session_checkpoints(session_id)
            
            if success:
                logger.info(f"已通过删除 checkpoint 清空会话 {session_id}")
            else:
                logger.error(f"删除 checkpoint 失败")
                return Response({
                    "success": False,
                    "message": "清空会话失败"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            # ====== 部分删除消息 ======
            # 使用 RemoveMessage 删除 message_index 及之后的所有消息
            messages_to_remove = []
            for i, msg in enumerate(current_messages):
                if i >= message_index:
                    # 获取消息 ID
                    msg_id = getattr(msg, 'id', None)
                    logger.debug(f"检查消息 {i}: type={type(msg).__name__}, id={msg_id}")
                    if msg_id:
                        messages_to_remove.append(RemoveMessage(id=msg_id))
                        logger.info(f"准备删除消息 {i}: id={msg_id}, type={type(msg).__name__}")
                    else:
                        logger.warning(f"消息 {i} 没有 ID: type={type(msg).__name__}")
            
            logger.info(f"共找到 {len(messages_to_remove)} 条有 ID 的消息待删除（共需删除 {rolled_back_messages} 条）")
            
            if messages_to_remove:
                # 使用 update_state 删除消息
                try:
                    app.update_state(config, {"messages": messages_to_remove})
                    logger.info(f"已提交删除 {len(messages_to_remove)} 条消息")
                except Exception as e:
                    logger.exception(f"update_state 删除消息失败: {e}")
                    raise
            else:
                # 如果消息没有 ID，尝试使用 checkpointer 直接操作
                logger.warning("消息没有 ID，尝试直接操作 checkpointer")
                
                # 获取所有历史快照
                try:
                    history = list(app.get_state_history(config))
                    logger.info(f"找到 {len(history)} 个历史快照")
                except Exception as e:
                    logger.warning(f"获取历史快照失败: {e}")
                    history = []
                
                if not history:
                    logger.warning("没有找到历史快照，无法通过快照回滚")
                else:
                    # 找到消息数量 < message_index 的最新快照
                    target_snapshot = None
                    for snapshot in history:
                        if snapshot.values:
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
        new_messages = []
        if message_index == 0:
            # 清空 checkpoint 后，会话状态为空，这是预期行为
            logger.info("会话已清空，消息数: 0")
        else:
            try:
                new_state = app.get_state(config)
                new_messages = new_state.values.get("messages", []) if new_state and new_state.values else []
                logger.info(f"删除后消息数: {len(new_messages)}")
            except Exception as e:
                logger.warning(f"获取删除后状态失败: {e}")
        
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

        # ====== 清除搜索结果缓存 ======
        # 回滚后，搜索结果缓存可能已过期，需要清除以避免引用失效的项目
        try:
            from agent_service.tools.cache_manager import CacheManager
            CacheManager.clear_session_cache(session_id)
            logger.info(f"已清除会话 {session_id} 的搜索结果缓存")
        except Exception as e:
            logger.warning(f"清除搜索结果缓存失败: {e}")

        # ====== 同步回滚 TODO 列表 ======
        todo_rolled_back = False
        try:
            # 若未能定位 checkpoint，则传入一个不会命中的占位符，函数会清空列表
            cp_for_todo = target_checkpoint_id or f"rollback_{message_index}"
            todo_rolled_back = rollback_todos(session_id, cp_for_todo)
            logger.info(f"TODO 回滚结果: {todo_rolled_back}, checkpoint_id={cp_for_todo}")
        except Exception as e:
            logger.warning(f"TODO 回滚失败: {e}")
        
        return Response({
            "success": True,
            "rolled_back_messages": rolled_back_messages,
            "rolled_back_transactions": rolled_back_transactions,
            "rolled_back_details": rolled_back_details,
            "todo_rolled_back": todo_rolled_back,
            "remaining_messages": len(new_messages),
            "message": f"成功回滚，删除了 {rolled_back_messages} 条消息，撤销了 {rolled_back_transactions} 个操作"
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
def get_available_tools(request):
    """
    获取可用的工具列表（按分类）
    GET /api/agent/tools/
    
    返回:
    {
        "categories": [
            {
                "id": "planner",
                "display_name": "日程管理",
                "description": "管理日程、待办、提醒",
                "tools": [
                    {"name": "get_events", "display_name": "查询日程", "enabled": true},
                    ...
                ]
            },
            ...
        ],
        "default_tools": ["get_events", "create_event", ...]
    }
    """
    from agent_service.agent_graph import TOOL_CATEGORIES, get_default_tools
    
    # 工具的友好名称映射
    tool_display_names = {
        # Planner 统一工具（新版）
        "search_items": "统一搜索",
        "create_item": "创建项目",
        "update_item": "更新项目",
        "delete_item": "删除项目",
        "get_event_groups": "获取事件组",
        "complete_todo": "完成待办",
        # Planner 旧版
        "get_events": "查询日程",
        "create_event": "创建日程",
        "update_event": "更新日程",
        "delete_event": "删除日程",
        "get_todos": "查询待办",
        "create_todo": "创建待办",
        "update_todo": "更新待办",
        "delete_todo": "删除待办",
        "get_reminders": "查询提醒",
        "create_reminder": "创建提醒",
        "delete_reminder": "删除提醒",
        # Memory V2
        "save_personal_info": "保存个人信息",
        "get_personal_info": "获取个人信息",
        "update_personal_info": "更新个人信息",
        "delete_personal_info": "删除个人信息",
        "get_dialog_style": "获取对话风格",
        "update_dialog_style": "更新对话风格",
        "save_workflow_rule": "保存工作流规则",
        "get_workflow_rules": "获取工作流规则",
        "update_workflow_rule": "更新工作流规则",
        "delete_workflow_rule": "删除工作流规则",
        # Session TO DO (任务追踪)
        "add_task": "添加任务",
        "update_task_status": "更新任务状态",
        "get_task_list": "获取任务列表",
        "clear_completed_tasks": "清除已完成任务",
        # Map (MCP)
        "maps_search_poi": "搜索地点",
        "maps_search_nearby": "周边搜索",
        "maps_geo": "地理编码",
        "maps_regeo": "逆地理编码",
        "maps_bicycling": "骑行路线",
        "maps_walking": "步行路线",
        "maps_driving": "驾车路线",
        "maps_distance": "距离测量",
        "maps_weather": "天气查询",
        "maps_ip": "IP定位",
    }
    
    default_tools = get_default_tools()
    
    categories = []
    for cat_id, cat_info in TOOL_CATEGORIES.items():
        # 跳过隐藏的分类
        if cat_info.get("hidden"):
            continue
        
        tools = []
        for tool_name in cat_info["tools"]:
            tools.append({
                "name": tool_name,
                "display_name": tool_display_names.get(tool_name, tool_name),
                "enabled": tool_name in default_tools
            })
        
        categories.append({
            "id": cat_id,
            "display_name": cat_info["display_name"],
            "description": cat_info["description"],
            "tools": tools
        })
    
    return Response({
        "categories": categories,
        "default_tools": default_tools
    })


# 保留旧的 API 以兼容
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_available_experts(request):
    """
    获取可用的专家列表 (已弃用，请使用 get_available_tools)
    GET /api/agent/experts/
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
            "available": True
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


# ==========================================
# 记忆优化 API
# ==========================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def optimize_memory(request):
    """
    记忆优化端点 (支持分批处理和上下文精简)
    POST /api/agent/optimize-memory/
    """
    from agent_service.agent_graph import app, llm
    from agent_service.models import UserPersonalInfo, WorkflowRule, DialogStyle
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
    import json
    import re

    user = request.user
    data = request.data
    session_id = data.get("session_id", f"user_{user.id}_default")

    if not session_id.startswith(f"user_{user.id}_"):
        return Response({"error": "无权访问此会话"}, status=status.HTTP_403_FORBIDDEN)

    try:
        # 1. 获取配置
        try:
            style = DialogStyle.get_or_create_default(user)
            batch_size = getattr(style, 'memory_batch_size', 20)
        except Exception:
            batch_size = 20

        # 2. 获取会话消息
        config = {"configurable": {"thread_id": session_id, "user": user}}
        state = app.get_state(config)
        all_messages = state.values.get("messages", []) if state and state.values else []

        # 3. 预处理消息 (精简上下文)
        pruned_messages = []
        for m in all_messages:
            if isinstance(m, SystemMessage):
                continue
            if isinstance(m, ToolMessage):
                # 替换工具输出为占位符
                m_copy = ToolMessage(content="(Tool output omitted for optimization)", tool_call_id=m.tool_call_id)
                pruned_messages.append(m_copy)
            else:
                pruned_messages.append(m)

        if not pruned_messages:
            return Response({"success": True, "summary": "没有发现可优化的对话内容", "applied": {}})

        # 4. 分批处理
        chunks = [pruned_messages[i:i + batch_size] for i in range(0, len(pruned_messages), batch_size)]
        
        total_applied = {
            "personal_info": {"add": 0, "update": 0, "delete": 0}, 
            "workflow_rules": {"add": 0, "update": 0, "delete": 0}
        }
        summaries = []

        # 辅助函数
        def format_personal_info(u):
            infos = UserPersonalInfo.objects.filter(user=u)
            if not infos.exists(): return "(无)"
            return "\n".join([f"- {i.key}: {i.value}" for i in infos])

        def format_workflow_rules(u):
            rules = WorkflowRule.objects.filter(user=u, is_active=True)
            if not rules.exists(): return "(无)"
            return "\n".join([f"- {r.name} | 触发: {r.trigger}\n  步骤: {r.steps}" for r in rules])

        def format_messages(msgs):
            lines = []
            for m in msgs:
                role = 'user' if isinstance(m, HumanMessage) else 'assistant' if isinstance(m, AIMessage) else 'tool'
                content = getattr(m, 'content', '')
                lines.append(f"[{role}] {content}")
            return "\n".join(lines)

        # 循环处理每一批
        for i, chunk in enumerate(chunks):
            # 重新获取当前状态 (因为上一轮可能更新了数据库)
            current_info = format_personal_info(user)
            current_rules = format_workflow_rules(user)
            chunk_text = format_messages(chunk)

            optimize_prompt = f"""
你是一个记忆优化助手。正在处理第 {i+1}/{len(chunks)} 批对话记录。
请分析以下对话片段，并决定需要对用户记忆进行哪些操作。

## 当前用户个人信息 (实时状态)
{current_info}

## 当前工作流规则 (实时状态)
{current_rules}

## 本次对话片段 ({len(chunk)} 条消息)
{chunk_text}

## 你的任务
分析对话中的信息，判断是否需要：
1. 新增个人信息（用户提到的新事实）
2. 更新个人信息（用户纠正的旧信息）
3. 删除过时的个人信息
4. 新增/更新/删除工作流规则

请以 JSON 格式输出你的操作建议：
{{
  "personal_info": {{
    "add": [{{"key": "...", "value": "...", "description": "..."}}],
    "update": [{{"key": "...", "new_value": "...", "reason": "..."}}],
    "delete": [{{"key": "...", "reason": "..."}}]
  }},
  "workflow_rules": {{
    "add": [{{"name": "...", "trigger": "...", "steps": "..."}}],
    "update": [{{"name": "...", "new_steps": "...", "reason": "..."}}],
    "delete": [{{"name": "...", "reason": "..."}}]
  }},
  "summary": "本批次优化的简要说明"
}}
"""
            # 调用 LLM
            llm_msgs = [SystemMessage(content="你是一个记忆优化助手。"), HumanMessage(content=optimize_prompt)]
            result = llm.invoke(llm_msgs, config)
            text = getattr(result, 'content', '') if result else ''

            # 解析与执行
            try:
                ops = {"personal_info": {}, "workflow_rules": {}, "summary": ""}
                m = re.search(r"\{[\s\S]*\}", text)
                if m:
                    ops = json.loads(m.group(0))
                else:
                    # 尝试直接解析，如果失败则忽略
                    try: ops = json.loads(text)
                    except: pass
                
                if ops.get("summary"):
                    summaries.append(f"批次 {i+1}: {ops['summary']}")

                # 执行操作
                # Personal Info
                for item in ops.get("personal_info", {}).get("add", []) or []:
                    key, value, desc = item.get("key"), item.get("value"), item.get("description", "")
                    if key and value:
                        UserPersonalInfo.objects.update_or_create(user=user, key=key, defaults={"value": value, "description": desc})
                        total_applied["personal_info"]["add"] += 1
                
                for item in ops.get("personal_info", {}).get("update", []) or []:
                    key, new_value = item.get("key"), item.get("new_value")
                    if key and new_value is not None:
                        obj = UserPersonalInfo.objects.filter(user=user, key=key).first()
                        if obj:
                            obj.value = new_value
                            obj.save()
                            total_applied["personal_info"]["update"] += 1

                for item in ops.get("personal_info", {}).get("delete", []) or []:
                    key = item.get("key")
                    if key:
                        UserPersonalInfo.objects.filter(user=user, key=key).delete()
                        total_applied["personal_info"]["delete"] += 1

                # Workflow Rules
                for r in ops.get("workflow_rules", {}).get("add", []) or []:
                    name, trigger, steps = r.get("name"), r.get("trigger", ""), r.get("steps", "")
                    if name:
                        WorkflowRule.objects.update_or_create(user=user, name=name, defaults={"trigger": trigger, "steps": steps, "is_active": True})
                        total_applied["workflow_rules"]["add"] += 1

                for r in ops.get("workflow_rules", {}).get("update", []) or []:
                    name, new_steps = r.get("name"), r.get("new_steps")
                    if name and new_steps is not None:
                        obj = WorkflowRule.objects.filter(user=user, name=name).first()
                        if obj:
                            obj.steps = new_steps
                            obj.save()
                            total_applied["workflow_rules"]["update"] += 1

                for r in ops.get("workflow_rules", {}).get("delete", []) or []:
                    name = r.get("name")
                    if name:
                        WorkflowRule.objects.filter(user=user, name=name).delete()
                        total_applied["workflow_rules"]["delete"] += 1

            except Exception as e:
                logger.warning(f"批次 {i+1} 优化失败: {e}")
                summaries.append(f"批次 {i+1} 失败: {str(e)}")

        # 基于实际操作数计算总结
        total_ops = sum([
            total_applied["personal_info"]["add"],
            total_applied["personal_info"]["update"],
            total_applied["personal_info"]["delete"],
            total_applied["workflow_rules"]["add"],
            total_applied["workflow_rules"]["update"],
            total_applied["workflow_rules"]["delete"]
        ])
        
        if total_ops > 0:
            summary_parts = []
            pi = total_applied["personal_info"]
            wr = total_applied["workflow_rules"]
            if pi["add"]: summary_parts.append(f"新增{pi['add']}条个人信息")
            if pi["update"]: summary_parts.append(f"更新{pi['update']}条个人信息")
            if pi["delete"]: summary_parts.append(f"删除{pi['delete']}条个人信息")
            if wr["add"]: summary_parts.append(f"新增{wr['add']}条工作流规则")
            if wr["update"]: summary_parts.append(f"更新{wr['update']}条工作流规则")
            if wr["delete"]: summary_parts.append(f"删除{wr['delete']}条工作流规则")
            final_summary = "、".join(summary_parts)
        else:
            final_summary = "未发现可优化的内容"
        
        return Response({
            "success": True,
            "summary": final_summary,
            "applied": total_applied,
            "total_operations": total_ops
        })

    except Exception as e:
        logger.exception(f"记忆优化失败: {e}")
        return Response({"error": f"记忆优化失败: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==========================================
# 会话 TO DO 列表 API
# ==========================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_session_todos(request):
    """
    获取当前会话的 TO DO 列表
    GET /api/agent/session-todos/?session_id=xxx
    """
    from agent_service.models import SessionTodoItem, AgentSession
    
    user = request.user
    session_id = request.GET.get('session_id', f"user_{user.id}_default")
    
    if not session_id.startswith(f"user_{user.id}_"):
        return Response({"error": "无权访问此会话"}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        session = AgentSession.objects.filter(session_id=session_id).first()
        if not session:
            return Response({"todos": [], "count": 0})
        
        todos = SessionTodoItem.objects.filter(session=session).order_by('order', 'id')
        todo_list = [{
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "status": t.status,
            "order": t.order,
            "created_at": t.created_at.isoformat(),
            "updated_at": t.updated_at.isoformat()
        } for t in todos]
        
        return Response({
            "todos": todo_list,
            "count": len(todo_list)
        })
    except Exception as e:
        logger.exception(f"获取 TODO 列表失败: {e}")
        return Response({"error": f"获取 TODO 列表失败: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==========================================
# 附件系统 API
# ==========================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_attachable_items(request):
    """
    获取可用于附件的资源列表
    
    GET /api/agent/attachments/
    
    Query Parameters:
        type: 资源类型 (可选，不传则返回所有类型)
              - workflow: 工作流规则
              - (未来扩展: file, image 等)
    
    Response:
    {
        "items": [
            {
                "type": "workflow",
                "id": 1,
                "name": "创建日程流程",
                "preview": "当用户要求创建日程时...",
                "metadata": {...}
            }
        ],
        "types": ["workflow"]  // 当前支持的附件类型
    }
    """
    from agent_service.models import WorkflowRule
    
    user = request.user
    resource_type = request.query_params.get('type', None)
    
    items = []
    available_types = ['workflow']  # 当前支持的类型
    
    # 工作流规则
    if resource_type is None or resource_type == 'workflow':
        workflows = WorkflowRule.objects.filter(user=user, is_active=True).order_by('name')
        for wf in workflows:
            items.append({
                "type": "workflow",
                "id": wf.id,
                "name": wf.name,
                "preview": wf.trigger[:50] + "..." if len(wf.trigger) > 50 else wf.trigger,
                "metadata": {
                    "trigger": wf.trigger,
                    "steps": wf.steps,
                    "created_at": wf.created_at.isoformat(),
                    "updated_at": wf.updated_at.isoformat()
                }
            })
    
    # 未来可扩展其他类型
    # if resource_type is None or resource_type == 'file':
    #     files = UserFile.objects.filter(user=user)
    #     for f in files:
    #         items.append({...})
    
    return Response({
        "items": items,
        "types": available_types
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def format_attachment_content(request):
    """
    格式化附件内容用于发送到 Agent
    
    POST /api/agent/attachments/format/
    
    Body:
    {
        "attachments": [
            {"type": "workflow", "id": 1},
            {"type": "workflow", "id": 2}
        ]
    }
    
    Response:
    {
        "formatted_content": "【附件：工作流规则】\n1. 创建日程流程\n触发条件: ...\n执行步骤: ...\n\n",
        "count": 2
    }
    """
    from agent_service.models import WorkflowRule
    
    user = request.user
    attachments = request.data.get('attachments', [])
    
    if not attachments:
        return Response({"formatted_content": "", "count": 0})
    
    formatted_parts = []
    count = 0
    
    # 按类型分组处理
    workflows = []
    
    for att in attachments:
        att_type = att.get('type')
        att_id = att.get('id')
        
        if att_type == 'workflow':
            try:
                wf = WorkflowRule.objects.get(id=att_id, user=user)
                workflows.append(wf)
                count += 1
            except WorkflowRule.DoesNotExist:
                continue
    
    # 格式化工作流规则
    if workflows:
        wf_content = "【附件：工作流规则】\n请参考以下工作流规则执行任务：\n\n"
        for i, wf in enumerate(workflows, 1):
            wf_content += f"### {i}. {wf.name}\n"
            wf_content += f"**触发条件**: {wf.trigger}\n"
            wf_content += f"**执行步骤**: {wf.steps}\n\n"
        formatted_parts.append(wf_content)
    
    return Response({
        "formatted_content": "\n".join(formatted_parts),
        "count": count
    })
