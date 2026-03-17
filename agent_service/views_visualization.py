"""
上下文可视化 API

为前端提供最新的上下文组成可视化数据：
- System Prompt 组成
- 历史消息摘要
- 附件上下文
- 技能注入
- 工具绑定
- Token 使用情况

Author: Agent Service
Created: 2026-03-14
"""

from typing import Dict, Any, List

from django.contrib.auth.models import User
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from agent_service.models import AgentSession
from agent_service.agent_graph import get_default_tools
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage

from logger import logger


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_context_visualization(request):
    """
    获取当前会话的上下文可视化数据

    GET /api/agent/context-visualization/?session_id=xxx

    返回:
    {
        "session_id": "xxx",
        "system_prompt": {
            "role_definition": "...",        // 角色定义
            "capabilities": "...",           // 能力描述
            "active_tools": [...],          // 激活的工具列表
            "skill_injection": "...",       // 技能注入内容
            "state_snapshot": {...},        // 状态快照
            "file_context": [...],         // 文件上下文
        },
        "history": {
            "summary": "...",              // 历史摘要
            "message_count": 15,           // 历史消息数
            "summarized_until": 10,        // 摘要截止位置
        },
        "current_message": {
            "content": "...",              // 当前消息内容
            "attachments": [...],           // 附件列表
            "has_attachment_context": true, // 是否有附件上下文
        },
        "token_usage": {
            "system_prompt_tokens": 500,
            "history_tokens": 2000,
            "recent_tokens": 500,
            "total": 3000
        },
        "tools": {
            "bound": [...],                // 当前绑定的工具
            "recent_calls": [...]           // 最近工具调用
        }
    }
    """
    user = request.user
    session_id = request.query_params.get("session_id", f"user_{user.id}_default")
    logger.info(f"[可视化] 请求上下文可视化: user={user.id}, session={session_id}")

    # 验证 session_id 归属
    if not session_id.startswith(f"user_{user.id}_"):
        return Response(
            {"error": "无权访问此会话"},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        # 获取会话
        session = AgentSession.objects.filter(session_id=session_id).first()
        if not session:
            return Response(
                {"error": "会话不存在"},
                status=status.HTTP_404_NOT_FOUND
            )

        # ========== 1. System Prompt 组成 ==========
        system_prompt_info = _get_system_prompt_info(session, user)

        # ========== 2. 历史消息信息 ==========
        history_info = _get_history_info(session, session_id)

        # ========== 3. 当前消息信息 ==========
        current_message_info = _get_current_message_info(session_id)

        # ========== 4. Token 使用情况 ==========
        token_info = _get_token_info(session, session_id)

        # ========== 5. 工具信息 ==========
        tools_info = _get_tools_info(session, session_id)

        # ========== 6. 最近一次 LLM 请求（真实数据）==========
        llm_request_info = _get_llm_request_info(session)

        # ========== 7. 消息列表 ==========
        messages_info = _get_messages_list(session_id)

        logger.info(
            f"[可视化] 返回上下文可视化: session={session_id}, "
            f"message_count={history_info.get('message_count', 0)}, "
            f"has_summary={history_info.get('has_summary', False)}, "
            f"has_snapshot={system_prompt_info.get('has_snapshot', False)}"
        )

        return Response({
            "session_id": session_id,
            "system_prompt": system_prompt_info,
            "history": history_info,
            "current_message": current_message_info,
            "token_usage": token_info,
            "tools": tools_info,
            "messages": messages_info,
            "llm_request": llm_request_info  # 真实的 LLM 请求数据
        })

    except Exception as e:
        logger.exception(f"获取上下文可视化数据失败: {e}")
        return Response(
            {"error": f"获取上下文可视化数据失败: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def _get_system_prompt_info(session: AgentSession, user: User) -> Dict[str, Any]:
    """获取 System Prompt 的各个组成部分"""
    try:
        # 加载状态快照
        from agent_service.session_store import load_state_snapshot
        state_snapshot = load_state_snapshot(session)

        # 获取对话风格
        from agent_service.models import DialogStyle
        dialog_style = DialogStyle.get_or_create_default(user)

        # 获取默认工具
        default_tools = get_default_tools()

        return {
            "role_definition": dialog_style.content[:500] if dialog_style.content else "",
            "capabilities": "日程管理、记忆管理、任务追踪、技能管理",
            "active_tools": default_tools,
            "skill_injection": {
                "has_skills": state_snapshot.get('active_skills', []) if state_snapshot else [],
                "snapshot": state_snapshot
            },
            "state_snapshot": state_snapshot,
            "file_context": [],  # TODO: 从附件加载
            "has_snapshot": state_snapshot is not None
        }
    except Exception as e:
        logger.warning(f"[可视化] 获取 System Prompt 信息失败: {e}")
        return {"error": str(e)}


def _get_history_info(session: AgentSession, session_id: str) -> Dict[str, Any]:
    """获取历史消息信息"""
    try:
        # 尝试从 checkpointer 获取消息
        from agent_service.agent_graph import app
        config = {"configurable": {"thread_id": session_id}}
        state = app.get_state(config)

        message_count = 0
        if state and state.values:
            messages = state.values.get("messages", [])
            message_count = len(messages)

        return {
            "summary": session.summary_text[:500] if session.summary_text else "",
            "message_count": message_count,
            "summarized_until": session.summary_until_index or 0,
            "has_summary": bool(session.summary_text)
        }
    except Exception as e:
        logger.warning(f"[可视化] 获取历史信息失败: {e}")
        return {"error": str(e)}


def _get_current_message_info(session_id: str) -> Dict[str, Any]:
    """获取当前消息信息"""
    try:
        from agent_service.agent_graph import app
        config = {"configurable": {"thread_id": session_id}}
        state = app.get_state(config)

        if not state or not state.values:
            return {"content": "", "attachments": [], "has_attachment_context": False}

        messages = state.values.get("messages", [])
        if not messages:
            return {"content": "", "attachments": [], "has_attachment_context": False}

        # 获取最后一条人类消息
        last_human_msg = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_human_msg = msg
                break

        if not last_human_msg:
            return {"content": "", "attachments": [], "has_attachment_context": False}

        # 提取内容
        content = ""
        if isinstance(last_human_msg.content, str):
            content = last_human_msg.content
        elif isinstance(last_human_msg.content, list):
            text_parts = [b.get('text', '') for b in last_human_msg.content if isinstance(b, dict) and b.get('type') == 'text']
            content = ' '.join(text_parts)

        # 提取附件
        attachments = []
        has_attachment_context = False
        if hasattr(last_human_msg, 'additional_kwargs') and last_human_msg.additional_kwargs:
            attachments_metadata = last_human_msg.additional_kwargs.get('attachments_metadata', [])
            attachments = attachments_metadata
            has_attachment_context = bool(last_human_msg.additional_kwargs.get('attachments_context', ''))

        return {
            "content": content[:500],  # 限制长度
            "attachments": attachments,
            "has_attachment_context": has_attachment_context
        }
    except Exception as e:
        logger.warning(f"[可视化] 获取当前消息信息失败: {e}")
        return {"error": str(e)}


def _get_token_info(session: AgentSession, session_id: str) -> Dict[str, Any]:
    """获取 Token 使用信息"""
    try:
        # 读取会话的 Token 数据
        return {
            "system_prompt_tokens": 0,  # TODO: 需要从 SystemPrompt 计算
            "history_tokens": session.summary_tokens or 0,
            "recent_tokens": session.last_input_tokens or 0,
            "total": session.last_input_tokens or 0,
            "source": session.last_input_tokens_source or "estimated"
        }
    except Exception as e:
        logger.warning(f"[可视化] 获取 Token 信息失败: {e}")
        return {"error": str(e)}


def _get_tools_info(session: AgentSession, session_id: str) -> Dict[str, Any]:
    """获取工具调用信息"""
    try:
        from agent_service.models import AgentTransaction

        # 获取最近的工具调用
        recent_calls = list(AgentTransaction.objects.filter(
            session_id=session_id
        ).order_by('-created_at')[:10].values(
            'id', 'action_type', 'tool_type', 'status',
            'created_at', 'is_rolled_back'
        ))

        # 统计
        total_calls = AgentTransaction.objects.filter(session_id=session_id).count()
        reversible_calls = AgentTransaction.objects.filter(
            session_id=session_id,
            reversible=True,
            is_rolled_back=False
        ).count()

        return {
            "bound": get_default_tools(),  # 当前绑定的工具
            "recent_calls": recent_calls,
            "total_calls": total_calls,
            "reversible_calls": reversible_calls
        }
    except Exception as e:
        logger.warning(f"[可视化] 获取工具信息失败: {e}")
        return {"error": str(e)}


def _get_messages_list(session_id: str) -> List[Dict[str, Any]]:
    """获取消息列表"""
    try:
        from agent_service.agent_graph import app

        config = {"configurable": {"thread_id": session_id}}
        state = app.get_state(config)

        if not state or not state.values:
            return []

        messages = state.values.get("messages", [])
        result = []

        for i, msg in enumerate(messages):
            msg_dict = {
                "index": i,
                "role": "",
                "content": "",
                "tool_calls": [],
                "tool_name": "",
                "tool_output": "",
                "tool_status": ""
            }

            # 根据消息类型提取信息
            if hasattr(msg, 'type'):
                msg_dict["role"] = msg.type

            # 提取 content
            if hasattr(msg, 'content'):
                if isinstance(msg.content, str):
                    msg_dict["content"] = msg.content
                elif isinstance(msg.content, list):
                    # 处理多模态内容
                    text_parts = []
                    for block in msg.content:
                        if isinstance(block, dict):
                            if block.get('type') == 'text':
                                text_parts.append(block.get('text', ''))
                    msg_dict["content"] = '\n'.join(text_parts)

            # 提取 tool_calls
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "name": tc.get('name', ''),
                        "args": tc.get('args', {})
                    }
                    for tc in msg.tool_calls
                ]

            # 提取 tool 信息 (ToolMessage)
            if hasattr(msg, 'name') and msg.name:
                msg_dict["tool_name"] = msg.name
            if hasattr(msg, 'tool_call_id'):
                msg_dict["tool_call_id"] = msg.tool_call_id

            # tool_status
            if hasattr(msg, 'status'):
                msg_dict["tool_status"] = msg.status

            # additional_kwargs (attachments)
            if hasattr(msg, 'additional_kwargs') and msg.additional_kwargs:
                attachments_metadata = msg.additional_kwargs.get('attachments_metadata', [])
                if attachments_metadata:
                    msg_dict["attachments"] = attachments_metadata

            result.append(msg_dict)

        return result
    except Exception as e:
        logger.warning(f"[可视化] 获取消息列表失败: {e}")
        return []


def _get_llm_request_info(session: AgentSession) -> Dict[str, Any]:
    """
    获取最近一次 LLM 请求的真实数据（从 last_llm_request_snapshot 字段读取）
    """
    try:
        snapshot = getattr(session, 'last_llm_request_snapshot', None)
        if not snapshot:
            return {
                "has_data": False,
                "message": "暂无 LLM 请求数据"
            }

        messages = snapshot.get("messages", [])

        # 提取 System Prompt（第一条 system 消息）
        system_prompt = ""
        for msg in messages:
            if msg.get("role") == "system" and msg.get("_meta", {}).get("type") == "system_prompt":
                system_prompt = msg.get("content", "")
                break
        if not system_prompt:
            for msg in messages:
                if msg.get("role") == "system":
                    system_prompt = msg.get("content", "")
                    break

        # 提取工具调用
        tool_calls = []
        for msg in messages:
            if msg.get("tool_calls"):
                tool_calls.extend(msg.get("tool_calls", []))

        return {
            "has_data": True,
            **snapshot,
            "message_count": len(messages),
            "system_prompt": system_prompt,
            "system_prompt_length": len(system_prompt),
            "tool_calls": tool_calls,
            "tool_calls_count": len(tool_calls),
            "messages": messages,
        }
    except Exception as e:
        logger.warning(f"[可视化] 获取 LLM 请求数据失败: {e}")
        return {"has_data": False, "error": str(e)}
