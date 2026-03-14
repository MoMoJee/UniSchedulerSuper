"""
显式上下文构建器 (Context Builder)

参考 OpenCode 设计理念：
- 显式优于隐式：上下文构建应显式声明，而非隐式继承
- 当前态优于历史态：优先传递当前状态，而非依赖历史
- 摘要优于全量：使用摘要而非保留全量历史

核心功能：
1. L1: 系统提示构建 - 显式声明激活技能、可用工具、文件上下文、状态快照
2. L2: 对话历史构建 - 策略性选择（全量/摘要/最近）
3. L3: 当前输入构建 - 用户文本、附件、即时指令

Author: Agent Service
Created: 2026-03-13
"""

import datetime
import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from django.contrib.auth.models import User
from langchain_core.messages import (
    BaseMessage, SystemMessage, HumanMessage, AIMessage, ToolMessage
)

from agent_service.models import AgentSession, AgentSkill, DialogStyle
from agent_service.context_optimizer import TokenCalculator
from agent_service.context_summarizer import build_optimized_context as build_summarized_context

logger = logging.getLogger(__name__)


# ==========================================
# 数据类定义
# ==========================================

@dataclass
class BuildOptions:
    """上下文构建选项"""
    # 当前激活的技能
    active_skills: List[int] = field(default_factory=list)

    # 可用工具列表
    available_tools: List[str] = field(default_factory=list)

    # 文件上下文
    file_context: List[Dict[str, Any]] = field(default_factory=list)

    # 状态快照
    state_snapshot: Optional[Dict[str, Any]] = None

    # 历史构建策略
    history_strategy: str = 'summary'  # 'full' | 'summary' | 'recent'

    # 保留最近消息数（history_strategy = 'recent' 时使用）
    recent_count: int = 5

    # 保留最近工具调用数（用于工具输出压缩边界）
    preserve_recent_tools: int = 5


@dataclass
class FileRef:
    """文件引用"""
    name: str
    path: str
    file_type: str = ""
    summary: str = ""
    content: Optional[str] = None


# ==========================================
# 上下文构建器
# ==========================================

class ContextBuilder:
    """
    显式上下文构建器

    每次 LLM 调用都重新构建完整消息序列：
    [系统提示层] + [对话历史层] + [当前输入层]
         ↓              ↓              ↓
      动态注入      策略性选择      用户当前输入
    """

    def __init__(self, session: AgentSession, user: User):
        """
        初始化上下文构建器

        Args:
            session: AgentSession 实例
            user: Django User 实例
        """
        self.session = session
        self.user = user
        self.token_calculator = TokenCalculator(method='estimate')
        logger.info(f"[ContextBuilder] 初始化: session={session.session_id}, user={user.username}")

    def build(self, user_input: str, options: BuildOptions) -> List[BaseMessage]:
        """
        构建完整上下文消息序列

        Args:
            user_input: 用户输入文本
            options: 构建选项

        Returns:
            完整的消息列表
        """
        logger.info(
            f"[ContextBuilder] 开始构建上下文: "
            f"session={self.session.session_id}, "
            f"strategy={options.history_strategy}, "
            f"active_skills={len(options.active_skills)}, "
            f"available_tools={len(options.available_tools)}"
        )
            完整的消息列表
        """
        return [
            self.build_system_prompt(options),
            *self.build_history(options),
            self.build_user_message(user_input, options)
        ]

    def build_system_prompt(self, options: BuildOptions) -> SystemMessage:
        """
        L1: 显式构建系统提示

        包含：
        - 角色定义（DialogStyle）
        - 当前激活技能（显式声明）
        - 可用工具集（当前轮次）
        - 文件上下文（显式维护）
        - 状态快照（跨轮传递）
        """
        logger.debug(f"[ContextBuilder] 构建系统提示: strategy={options.history_strategy}")

        # 1. 加载用户的对话风格模板
        try:
            dialog_style = DialogStyle.get_or_create_default(self.user)
            base_prompt = dialog_style.content
            logger.debug(f"[ContextBuilder] 加载对话风格成功: {len(base_prompt)} 字符")
        except Exception as e:
            logger.warning(f"[ContextBuilder] 加载对话风格失败: {e}")
            base_prompt = DialogStyle.DEFAULT_TEMPLATE

        # 2. 构建能力描述
        capabilities = self._build_capabilities(options.available_tools)

        # 3. 构建技能提示（显式声明）
        skill_hint = self._build_skill_hint(options.active_skills)
        if skill_hint:
            logger.debug(f"[ContextBuilder] 技能提示: {len(skill_hint)} 字符, {len(options.active_skills)} 个技能")

        # 4. 构建文件上下文提示（显式维护）
        file_hint = self._build_file_hint(options.file_context)
        if file_hint:
            logger.debug(f"[ContextBuilder] 文件上下文: {len(options.file_context)} 个文件")

        # 5. 构建状态快照提示（跨轮传递）
        state_hint = self._build_state_hint(options.state_snapshot)

        # 6. 组装完整提示
        system_prompt = f"""{base_prompt}

当前时间: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

你的能力:
{capabilities}

你当前可用的工具列表: {', '.join(options.available_tools) if options.available_tools else '无可用工具'}

注意事项:
1. 创建日程或提醒时，时间格式为: YYYY-MM-DDTHH:MM (例如: 2025-12-25T14:30)
2. 如果用户请求的功能不在你当前的能力范围内，请友好地告知用户
3. 如果用户没有提供完整信息，请礼貌询问
4. 工具调用后，请根据返回结果给用户一个清晰的回复
5. 如果用户提到重要的个人信息或偏好，请使用 save_personal_info 保存
6. 如果用户要求将某段流程或知识沉淀为可复用的指令，使用 save_skill 保存为技能{skill_hint}{file_hint}{state_hint}"""

        return SystemMessage(content=system_prompt)

    def _build_capabilities(self, available_tools: List[str]) -> str:
        """构建能力描述"""
        # TODO: 根据可用工具动态生成能力描述
        # 当前复用 agent_graph.py 中的逻辑
        return "- 日程/待办/提醒管理\n- 记忆管理\n- 任务追踪\n- 技能管理"

    def _build_skill_hint(self, active_skill_ids: List[int]) -> str:
        """构建技能提示（显式声明）"""
        if not active_skill_ids:
            return ""

        try:
            skills = AgentSkill.objects.filter(
                id__in=active_skill_ids,
                user=self.user,
                is_active=True
            )
            if not skills.exists():
                return ""

            skill_sections = []
            for s in skills:
                skill_sections.append(f"### {s.name}\n{s.content}")

            return "\n\n## 用户自定义技能\n以下是与当前任务相关的技能指令，请参考执行：\n\n" + "\n\n".join(skill_sections)
        except Exception as e:
            logger.warning(f"[ContextBuilder] 加载技能失败: {e}")
            return ""

    def _build_file_hint(self, file_context: List[Dict[str, Any]]) -> str:
        """构建文件上下文提示（显式维护）"""
        if not file_context:
            return ""

        sections = []
        for f in file_context:
            section = f"## {f.get('name', 'unknown')}\n"
            if f.get('summary'):
                section += f"- 内容摘要: {f.get('summary')}\n"
            if f.get('status'):
                section += f"- 处理状态: {f.get('status')}\n"
            if f.get('current_position'):
                section += f"- 当前处理位置: {f.get('current_position')}\n"
            sections.append(section)

        return "\n\n## 当前关注文件\n" + "\n".join(sections)

    def _build_state_hint(self, state_snapshot: Optional[Dict[str, Any]]) -> str:
        """构建状态快照提示（跨轮传递）"""
        if not state_snapshot:
            return ""

        sections = []

        if state_snapshot.get('phase'):
            sections.append(f"- 任务阶段: {state_snapshot.get('phase')}")

        if state_snapshot.get('active_skills'):
            sections.append(f"- 已激活技能: {state_snapshot.get('active_skills')}")

        if state_snapshot.get('focus_files'):
            sections.append(f"- 关注文件: {state_snapshot.get('focus_files')}")

        if state_snapshot.get('pending_tasks'):
            sections.append(f"- 待处理: {state_snapshot.get('pending_tasks')}")

        if state_snapshot.get('accumulated_findings'):
            sections.append(f"- 累积发现: {state_snapshot.get('accumulated_findings')}")

        if not sections:
            return ""

        return "\n\n## 当前状态\n" + "\n".join(sections)

    def build_history(self, options: BuildOptions) -> List[BaseMessage]:
        """
        L2: 策略性选择对话历史

        Args:
            options: 构建选项

        Returns:
            历史消息列表
        """
        # 获取会话的总结信息
        summary_metadata = None
        if self.session.summary_text:
            summary_metadata = {
                'summary': self.session.summary_text,
                'summarized_until': self.session.summary_until_index,
                'summary_tokens': self.session.summary_tokens
            }

        # 根据策略选择历史
        if options.history_strategy == 'full':
            return self._build_full_history()
        elif options.history_strategy == 'recent':
            return self._build_recent_history(options.recent_count)
        elif options.history_strategy == 'summary':
            return self._build_summary_history(summary_metadata, options)
        else:
            logger.warning(f"[ContextBuilder] 未知历史策略: {options.history_strategy}, 使用 summary")
            return self._build_summary_history(summary_metadata, options)

    def _build_full_history(self) -> List[BaseMessage]:
        """全量历史（仅适用于短会话）"""
        # TODO: 从 MessagePart 模型加载历史
        # 当前返回空列表，由 agent_node 补充
        return []

    def _build_recent_history(self, count: int) -> List[BaseMessage]:
        """最近 N 条历史"""
        # TODO: 从 MessagePart 模型加载最近 N 条
        return []

    def _build_summary_history(
        self,
        summary_metadata: Optional[Dict],
        options: BuildOptions
    ) -> List[BaseMessage]:
        """
        摘要历史策略

        结构: [Summary] + [最近 N 条消息]
        """
        # TODO: 从 MessagePart 模型加载历史
        # 当前复用 context_summarizer 的逻辑
        # 这需要传入实际的 messages 列表
        return []

    def build_user_message(self, user_input: str, options: BuildOptions) -> HumanMessage:
        """
        L3: 构建当前输入

        Args:
            user_input: 用户输入文本
            options: 构建选项

        Returns:
            HumanMessage
        """
        # TODO: 处理附件和即时指令
        return HumanMessage(content=user_input)


# ==========================================
# 工具函数
# ==========================================

def load_state_snapshot(session: AgentSession) -> Optional[Dict[str, Any]]:
    """
    加载会话的最新状态快照

    Args:
        session: AgentSession 实例

    Returns:
        状态快照字典，如果没有则返回 None
    """
    try:
        from agent_service.models import AgentStateSnapshot

        latest_snapshot = AgentStateSnapshot.objects.filter(
            session=session
        ).order_by('-created_at').first()

        if latest_snapshot:
            return {
                'phase': latest_snapshot.phase,
                'active_skills': latest_snapshot.active_skills,
                'focus_files': latest_snapshot.focus_files,
                'accumulated_findings': latest_snapshot.accumulated_findings,
                'pending_tasks': latest_snapshot.pending_tasks,
                'tool_results_summary': latest_snapshot.tool_results_summary,
                'checkpoint_id': latest_snapshot.checkpoint_id
            }
    except Exception as e:
        logger.warning(f"[ContextBuilder] 加载状态快照失败: {e}")

    return None


def save_state_snapshot(
    session: AgentSession,
    checkpoint_id: str,
    state_data: Dict[str, Any]
) -> bool:
    """
    保存会话的状态快照

    Args:
        session: AgentSession 实例
        checkpoint_id: 检查点 ID
        state_data: 状态数据

    Returns:
        是否保存成功
    """
    try:
        from agent_service.models import AgentStateSnapshot

        snapshot, created = AgentStateSnapshot.objects.update_or_create(
            session=session,
            checkpoint_id=checkpoint_id,
            defaults={
                'phase': state_data.get('phase', 'idle'),
                'active_skills': state_data.get('active_skills', []),
                'focus_files': state_data.get('focus_files', []),
                'accumulated_findings': state_data.get('accumulated_findings', []),
                'pending_tasks': state_data.get('pending_tasks', []),
                'tool_results_summary': state_data.get('tool_results_summary', []),
                'last_user_message': state_data.get('last_user_message', ''),
                'metadata': state_data.get('metadata', {}),
            }
        )
        return True
    except Exception as e:
        logger.error(f"[ContextBuilder] 保存状态快照失败: {e}")
        return False


def save_message_parts(
    session: AgentSession,
    user: User,
    message_index: int,
    messages: List[BaseMessage],
    checkpoint_id: str = ""
) -> bool:
    """
    将消息保存为结构化的 MessagePart

    Args:
        session: AgentSession 实例
        user: Django User 实例
        message_index: 消息索引
        messages: 消息列表
        checkpoint_id: 检查点 ID

    Returns:
        是否保存成功
    """
    try:
        from agent_service.models import MessagePart, MessagePartType

        for i, msg in enumerate(messages):
            # 确定角色
            if isinstance(msg, HumanMessage):
                role = 'user'
            elif isinstance(msg, AIMessage):
                role = 'assistant'
            elif isinstance(msg, ToolMessage):
                role = 'tool'
            elif isinstance(msg, SystemMessage):
                role = 'system'
            else:
                role = 'unknown'

            # 根据消息类型创建对应的 MessagePart
            if isinstance(msg, ToolMessage):
                # 工具调用记录
                MessagePart.objects.create(
                    session=session,
                    user=user,
                    message_index=message_index + i,
                    part_type=MessagePartType.TOOL,
                    tool_name=msg.name if hasattr(msg, 'name') else '',
                    tool_input={},
                    tool_output=msg.content if hasattr(msg, 'content') else str(msg),
                    tool_status='success' if not str(msg).startswith('Error') else 'error',
                    role=role,
                    checkpoint_id=checkpoint_id
                )
            elif isinstance(msg, HumanMessage):
                # 用户消息
                content = msg.content if isinstance(msg.content, str) else json.dumps(msg.content, ensure_ascii=False)
                MessagePart.objects.create(
                    session=session,
                    user=user,
                    message_index=message_index + i,
                    part_type=MessagePartType.TEXT,
                    content=content,
                    role=role,
                    checkpoint_id=checkpoint_id
                )
            elif isinstance(msg, AIMessage):
                # AI 消息
                content = msg.content if isinstance(msg.content, str) else json.dumps(msg.content, ensure_ascii=False)

                # 检查是否有工具调用
                tool_calls = getattr(msg, 'tool_calls', None)
                if tool_calls:
                    for tc in tool_calls:
                        MessagePart.objects.create(
                            session=session,
                            user=user,
                            message_index=message_index + i,
                            part_type=MessagePartType.TOOL,
                            tool_name=tc.get('name', ''),
                            tool_input=tc.get('args', {}),
                            tool_output='',
                            tool_status='pending',
                            role=role,
                            checkpoint_id=checkpoint_id
                        )

                # 添加文本内容
                if content:
                    MessagePart.objects.create(
                        session=session,
                        user=user,
                        message_index=message_index + i,
                        part_type=MessagePartType.TEXT,
                        content=content,
                        role=role,
                        checkpoint_id=checkpoint_id
                    )
            elif isinstance(msg, SystemMessage):
                # 系统消息（通常不保存，除非需要）
                pass

        return True
    except Exception as e:
        logger.error(f"[ContextBuilder] 保存消息分片失败: {e}")
        return False


def load_message_parts(
    session: AgentSession,
    from_index: Optional[int] = None,
    to_index: Optional[int] = None,
    checkpoint_id: Optional[str] = None
) -> List[BaseMessage]:
    """
    从 MessagePart 加载消息历史

    Args:
        session: AgentSession 实例
        from_index: 起始索引（包含）
        to_index: 结束索引（不包含）
        checkpoint_id: 检查点 ID（可选）

    Returns:
        消息列表
    """
    try:
        from agent_service.models import MessagePart

        query = MessagePart.objects.filter(session=session)

        if checkpoint_id:
            query = query.filter(checkpoint_id=checkpoint_id)
        elif from_index is not None or to_index is not None:
            if from_index is not None:
                query = query.filter(message_index__gte=from_index)
            if to_index is not None:
                query = query.filter(message_index__lt=to_index)

        parts = query.order_by('message_index', 'part_type')

        # 按消息索引分组
        messages_dict: Dict[int, List[MessagePart]] = {}
        for part in parts:
            if part.message_index not in messages_dict:
                messages_dict[part.message_index] = []
            messages_dict[part.message_index].append(part)

        # 构建消息列表
        result = []
        for idx in sorted(messages_dict.keys()):
            parts_at_idx = messages_dict[idx]

            # 收集文本内容
            text_parts = []
            tool_calls = []
            has_error = False

            for part in parts_at_idx:
                if part.part_type == MessagePartType.TEXT:
                    text_parts.append(part.content)
                elif part.part_type == MessagePartType.TOOL:
                    if part.tool_status == 'pending':
                        tool_calls.append({
                            'name': part.tool_name,
                            'args': part.tool_input
                        })
                    elif part.tool_output:
                        # ToolMessage 单独添加
                        result.append(ToolMessage(
                            content=part.tool_output,
                            tool_call_id=part.tool_input.get('id', ''),
                            name=part.tool_name
                        ))
                        if part.tool_status == 'error':
                            has_error = True

            # 添加用户/AI 消息
            if text_parts:
                content = '\n'.join(text_parts)
                role = parts_at_idx[0].role if parts_at_idx else 'unknown'

                if role == 'user':
                    result.append(HumanMessage(content=content))
                elif role == 'assistant':
                    if tool_calls:
                        # 使用 tool_calls 参数创建 AIMessage
                        from langchain_core.utils.function_calling import convert_to_openai_tool
                        msg = AIMessage(content=content, tool_calls=tool_calls)
                    else:
                        msg = AIMessage(content=content)
                    result.append(msg)

        return result
    except Exception as e:
        logger.error(f"[ContextBuilder] 加载消息分片失败: {e}")
        return []
