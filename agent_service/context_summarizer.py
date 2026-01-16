"""
智能对话历史总结模块

功能:
1. 判断是否需要触发总结
2. 调用 LLM 生成对话总结
3. 管理总结元数据

Author: Agent Service
Created: 2026-01-02
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage, ToolMessage

logger = logging.getLogger(__name__)


class ConversationSummarizer:
    """
    对话历史总结器

    工作流程:
    1. 检查是否达到总结触发条件
    2. 提取需要总结的消息
    3. 调用 LLM 生成总结
    4. 返回总结元数据
    """

    def __init__(
        self,
        llm,
        token_calculator,
        target_summary_tokens: int = 20000,
        min_messages: int = 20,
        trigger_ratio: float = 0.5
    ):
        """
        初始化总结器

        Args:
            llm: LangChain LLM 实例
            token_calculator: Token 计算器
            target_summary_tokens: 目标总结 token 数
            min_messages: 最少消息数才开始总结
            trigger_ratio: 触发阈值 (新消息 tokens / 历史总结 tokens)
        """
        self.llm = llm
        self.token_calculator = token_calculator
        self.target_summary_tokens = target_summary_tokens
        self.min_messages = min_messages
        self.trigger_ratio = trigger_ratio

    def should_summarize(
        self,
        messages: List[BaseMessage],
        summary_metadata: Optional[Dict]
    ) -> bool:
        """
        判断是否应该触发总结

        Args:
            messages: 当前所有消息
            summary_metadata: 现有的总结元数据

        Returns:
            是否应该触发总结
        """
        # 消息数量不足
        if len(messages) < self.min_messages:
            logger.debug(f"[总结] 消息数不足: {len(messages)} < {self.min_messages}")
            return False

        # 首次总结
        if summary_metadata is None:
            logger.info(f"[总结] 首次总结触发: {len(messages)} 条消息")
            return True

        # 计算新增消息的 token 数
        summarized_until = summary_metadata.get('summarized_until', 0)
        new_messages = messages[summarized_until:]

        if len(new_messages) < 10:  # 新消息太少
            return False

        new_tokens = 0
        for msg in new_messages:
            new_tokens += self.token_calculator.calculate_message(msg)

        summary_tokens = summary_metadata.get('summary_tokens', 1)  # 避免除零

        ratio = new_tokens / summary_tokens

        should = ratio > self.trigger_ratio

        logger.info(
            f"[总结] 检查触发: 新消息={len(new_messages)}条({new_tokens}t), "
            f"历史总结={summary_tokens}t, 比例={ratio:.1%}, 阈值={self.trigger_ratio:.1%}, "
            f"触发={'是' if should else '否'}"
        )

        return should

    async def summarize(
        self,
        messages: List[BaseMessage],
        previous_summary: Optional[str] = None
    ) -> Optional[Dict]:
        """
        生成对话历史总结

        Args:
            messages: 要总结的消息列表
            previous_summary: 之前的总结（用于增量更新）

        Returns:
            总结元数据 {
                "summary": "总结文本",
                "summarized_until": 消息数,
                "summary_tokens": token 数,
                "created_at": 创建时间,
                "message_count": 消息数,
                "original_tokens": 原始 token 数
            }
            如果消息为空则返回 None
        """
        if not messages:
            return None

        # 计算原始 token 数
        original_tokens = sum(self.token_calculator.calculate_message(m) for m in messages)

        # 构建总结提示
        conversation_text = self._format_messages_for_summary(messages)

        # 构建提示词
        if previous_summary:
            prompt = self._build_incremental_summary_prompt(
                previous_summary,
                conversation_text,
                len(messages),
                original_tokens
            )
        else:
            prompt = self._build_initial_summary_prompt(
                conversation_text,
                len(messages),
                original_tokens
            )

        # 调用 LLM
        try:
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            summary_text = response.content

            # 计算总结的 token 数
            summary_tokens = self.token_calculator.calculate_text(summary_text)

            # 记录压缩率
            compression_rate = 1 - (summary_tokens / original_tokens) if original_tokens > 0 else 0
            logger.info(
                f"[总结] 完成: {len(messages)}条消息, "
                f"{original_tokens}t → {summary_tokens}t, "
                f"压缩率={compression_rate:.1%}"
            )

            return {
                "summary": summary_text,
                "summarized_until": len(messages),
                "summary_tokens": summary_tokens,
                "created_at": datetime.now().isoformat(),
                "message_count": len(messages),
                "original_tokens": original_tokens,
                "compression_rate": compression_rate,
            }

        except Exception as e:
            logger.error(f"[总结] 失败: {e}")
            raise

    def _format_messages_for_summary(self, messages: List[BaseMessage]) -> str:
        """将消息格式化为总结所需的文本"""
        lines = []

        for i, msg in enumerate(messages):
            if isinstance(msg, SystemMessage):
                continue  # 跳过系统消息

            role = self._get_role_name(msg)
            content = msg.content if isinstance(msg.content, str) else str(msg.content)

            # 截断过长的内容
            if len(content) > 500:
                content = content[:500] + "..."

            lines.append(f"[{role}] {content}")

            # 如果是 AI 消息且有工具调用
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    lines.append(f"  → 调用工具: {tc.get('name', 'unknown')}")

        return "\n".join(lines)

    def _get_role_name(self, msg: BaseMessage) -> str:
        """获取消息角色名称"""
        if isinstance(msg, HumanMessage):
            return "用户"
        elif isinstance(msg, AIMessage):
            return "AI"
        elif isinstance(msg, ToolMessage):
            return f"工具({msg.name if hasattr(msg, 'name') else 'unknown'})"
        else:
            return "系统"

    def _build_initial_summary_prompt(
        self,
        conversation_text: str,
        message_count: int,
        original_tokens: int
    ) -> str:
        """构建初始总结提示词"""
        return f"""请总结以下对话历史，保留关键信息：

## 对话历史
共 {message_count} 条消息，约 {original_tokens} tokens

{conversation_text}

## 总结要求
1. 提取用户的主要意图和需求
2. 记录重要的决策和操作结果（创建了什么日程、待办等）
3. 保留关键的时间、地点、人物信息
4. 压缩冗余的工具调用细节，只保留结果
5. 目标长度: 约 {self.target_summary_tokens} tokens

## 输出格式
简洁的段落式总结，保持时间顺序，重点突出。不要使用 Markdown 标题格式，直接输出文本。"""

    def _build_incremental_summary_prompt(
        self,
        previous_summary: str,
        new_conversation: str,
        message_count: int,
        original_tokens: int
    ) -> str:
        """构建增量总结提示词"""
        return f"""请基于已有总结，更新为包含新对话内容的总结：

## 已有总结
{previous_summary}

## 新增对话
共 {message_count} 条新消息，约 {original_tokens} tokens

{new_conversation}

## 总结要求
1. 将新内容融入已有总结
2. 保留重要的历史信息
3. 更新可能已变化的信息
4. 记录新的操作和结果
5. 目标长度: 约 {self.target_summary_tokens} tokens

## 输出格式
输出完整的更新后总结，简洁的段落式，保持时间顺序，重点突出。"""


def build_optimized_context(
    user,
    system_prompt: str,
    messages: List[BaseMessage],
    summary_metadata: Optional[Dict],
    token_calculator,
    tool_compressor,
    summary_token_budget: int,
    recent_token_budget: int
) -> List[BaseMessage]:
    """
    构建优化的上下文

    结构: [System] + [Summary] + [Recent Messages]

    Args:
        user: Django User 对象
        system_prompt: 系统提示词
        messages: 完整消息列表
        summary_metadata: 总结元数据
        token_calculator: Token 计算器
        tool_compressor: 工具压缩器
        summary_token_budget: 历史总结 token 预算
        recent_token_budget: 最近对话 token 预算

    Returns:
        优化后的消息列表
    """
    optimized = []

    # 1. System Prompt
    system_msg = SystemMessage(content=system_prompt)
    optimized.append(system_msg)
    system_tokens = token_calculator.calculate_message(system_msg)

    # 2. 历史总结（如果有）
    summary_tokens = 0
    recent_start_index = 0

    if summary_metadata and summary_metadata.get('summary'):
        summary_text = summary_metadata['summary']
        summary_msg = SystemMessage(content=f"【对话历史总结】\n{summary_text}\n---")
        optimized.append(summary_msg)
        summary_tokens = summary_metadata.get('summary_tokens', 0)
        recent_start_index = summary_metadata.get('summarized_until', 0)

        logger.debug(f"[上下文] 添加历史总结: {summary_tokens}t, 截止第 {recent_start_index} 条")

    # 3. 最近对话
    recent_messages = messages[recent_start_index:]

    # 压缩工具消息
    if tool_compressor:
        compressed_messages = []
        for msg in recent_messages:
            if isinstance(msg, ToolMessage):
                compressed_messages.append(tool_compressor.compress(msg, token_calculator))
            else:
                compressed_messages.append(msg)
        recent_messages = compressed_messages

    # 4. 从后往前选择最近对话（直到达到 Token 预算）
    # 关键：保持工具调用链的完整性
    # - ToolMessage 必须有对应的 AIMessage (with tool_calls)
    # - AIMessage (with tool_calls) 必须有对应的 ToolMessage
    
    # 建立工具调用关系映射
    tool_call_to_ai_index = {}  # tool_call_id -> AIMessage index
    tool_call_to_tool_index = {}  # tool_call_id -> ToolMessage index
    ai_to_tool_calls = {}  # AIMessage index -> [tool_call_ids]
    
    for i, msg in enumerate(recent_messages):
        if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
            tool_call_ids = []
            for tc in msg.tool_calls:
                tc_id = tc.get('id') if isinstance(tc, dict) else getattr(tc, 'id', None)
                if tc_id:
                    tool_call_to_ai_index[tc_id] = i
                    tool_call_ids.append(tc_id)
            ai_to_tool_calls[i] = tool_call_ids
        elif isinstance(msg, ToolMessage):
            tc_id = getattr(msg, 'tool_call_id', None)
            if tc_id:
                tool_call_to_tool_index[tc_id] = i

    # 从后往前选择消息，但保持工具调用链完整
    selected_indices = set()
    cumulative_tokens = 0
    available_tokens = recent_token_budget

    for i in range(len(recent_messages) - 1, -1, -1):
        if i in selected_indices:
            continue

        msg = recent_messages[i]
        msg_tokens = token_calculator.calculate_message(msg)

        # 如果是 ToolMessage
        if isinstance(msg, ToolMessage):
            tool_call_id = getattr(msg, 'tool_call_id', None)
            ai_index = tool_call_to_ai_index.get(tool_call_id)

            if ai_index is None:
                # 没有对应的 AIMessage，跳过
                logger.debug(f"[上下文] 跳过孤立 ToolMessage (无 AIMessage): {tool_call_id}")
                continue

            # 需要同时包含 AIMessage 和该 AIMessage 的所有 ToolMessage
            ai_msg = recent_messages[ai_index]
            all_tool_call_ids = ai_to_tool_calls.get(ai_index, [])
            
            # 计算需要的总 token
            total_needed = token_calculator.calculate_message(ai_msg)
            tool_indices = []
            for tc_id in all_tool_call_ids:
                t_idx = tool_call_to_tool_index.get(tc_id)
                if t_idx is not None and t_idx not in selected_indices:
                    tool_indices.append(t_idx)
                    total_needed += token_calculator.calculate_message(recent_messages[t_idx])

            if ai_index in selected_indices:
                # AIMessage 已选，只需要添加 ToolMessage
                total_needed = msg_tokens

            if cumulative_tokens + total_needed > available_tokens:
                # 预算不够，跳过整个工具调用链
                continue

            # 添加 AIMessage 和所有关联的 ToolMessage
            if ai_index not in selected_indices:
                selected_indices.add(ai_index)
                cumulative_tokens += token_calculator.calculate_message(ai_msg)
            
            for t_idx in tool_indices:
                selected_indices.add(t_idx)
                cumulative_tokens += token_calculator.calculate_message(recent_messages[t_idx])

        # 如果是带 tool_calls 的 AIMessage
        elif isinstance(msg, AIMessage) and i in ai_to_tool_calls:
            all_tool_call_ids = ai_to_tool_calls[i]
            
            # 计算需要的总 token（AIMessage + 所有 ToolMessage）
            total_needed = msg_tokens
            tool_indices = []
            for tc_id in all_tool_call_ids:
                t_idx = tool_call_to_tool_index.get(tc_id)
                if t_idx is not None:
                    tool_indices.append(t_idx)
                    total_needed += token_calculator.calculate_message(recent_messages[t_idx])
                else:
                    # 缺少 ToolMessage，跳过整个链
                    logger.debug(f"[上下文] 跳过不完整的工具调用 (缺 ToolMessage): {tc_id}")
                    total_needed = float('inf')
                    break

            if cumulative_tokens + total_needed > available_tokens:
                # 预算不够或链不完整，跳过
                continue

            # 添加 AIMessage 和所有 ToolMessage
            selected_indices.add(i)
            cumulative_tokens += msg_tokens
            for t_idx in tool_indices:
                if t_idx not in selected_indices:
                    selected_indices.add(t_idx)
                    cumulative_tokens += token_calculator.calculate_message(recent_messages[t_idx])

        else:
            # 普通消息
            if cumulative_tokens + msg_tokens > available_tokens:
                # 超出预算，停止添加
                break

            selected_indices.add(i)
            cumulative_tokens += msg_tokens

    # 按原始顺序排列选中的消息
    selected_messages = [recent_messages[i] for i in sorted(selected_indices)]

    # 最终验证：确保工具调用链完整
    final_messages = []
    pending_tool_calls = {}  # tool_call_id -> AIMessage index in final_messages

    for msg in selected_messages:
        if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
            # 检查是否所有 tool_calls 都有对应的 ToolMessage
            all_have_responses = True
            tool_call_ids = []
            for tc in msg.tool_calls:
                tc_id = tc.get('id') if isinstance(tc, dict) else getattr(tc, 'id', None)
                if tc_id:
                    tool_call_ids.append(tc_id)
                    if tc_id not in tool_call_to_tool_index:
                        all_have_responses = False
                    else:
                        t_idx = tool_call_to_tool_index[tc_id]
                        if t_idx not in selected_indices:
                            all_have_responses = False

            if all_have_responses:
                final_messages.append(msg)
                for tc_id in tool_call_ids:
                    pending_tool_calls[tc_id] = len(final_messages) - 1
            else:
                # 跳过不完整的工具调用
                logger.debug(f"[上下文] 验证时跳过不完整工具调用 AIMessage")
        elif isinstance(msg, ToolMessage):
            tool_call_id = getattr(msg, 'tool_call_id', None)
            if tool_call_id in pending_tool_calls:
                final_messages.append(msg)
                del pending_tool_calls[tool_call_id]
            else:
                logger.debug(f"[上下文] 验证时跳过孤立 ToolMessage: {tool_call_id}")
        else:
            final_messages.append(msg)

    optimized.extend(final_messages)

    # 重新计算实际 token
    actual_tokens = sum(token_calculator.calculate_message(m) for m in final_messages)

    # 日志
    total_tokens = system_tokens + summary_tokens + actual_tokens
    logger.info(
        f"[上下文] 构建完成: "
        f"System={system_tokens}t, "
        f"Summary={summary_tokens}t, "
        f"Recent={actual_tokens}t ({len(final_messages)}条/{len(recent_messages)}条), "
        f"Total={total_tokens}t"
    )

    return optimized


def build_full_context(system_prompt: str, messages: List[BaseMessage]) -> List[BaseMessage]:
    """
    构建完整上下文（不优化）

    Args:
        system_prompt: 系统提示词
        messages: 完整消息列表

    Returns:
        完整消息列表
    """
    system_msg = SystemMessage(content=system_prompt)
    return [system_msg] + messages
