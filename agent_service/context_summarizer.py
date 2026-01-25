"""
智能对话历史总结模块

功能:
1. 判断是否需要触发总结（基于目标使用率和触发比例）
2. 调用 LLM 生成对话总结
3. 管理总结元数据
4. 总结后保证剩余 token 低于目标阈值

Author: Agent Service
Created: 2026-01-02
Updated: 2026-01-20 - 使用用户配置的触发逻辑
"""

import logging
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage, ToolMessage

from logger import logger


class ConversationSummarizer:
    """
    对话历史总结器

    触发策略 (基于用户配置):
    - target_usage_ratio: 目标窗口使用率 (如 0.3 表示上下文窗口的 30%)
    - summary_trigger_ratio: 当新消息 token / 总结 token > 此值时触发增量总结
    - min_messages_before_summary: 最少消息数才开始总结

    工作流程:
    1. 首次总结：消息数 >= min_messages_before_summary 且无历史总结
    2. 增量总结：新消息 tokens / 历史总结 tokens > summary_trigger_ratio
    3. 提取需要总结的消息
    4. 调用 LLM 生成总结
    """

    def __init__(
        self,
        llm,
        token_calculator,
        context_window: int = 128000,
        target_usage_ratio: float = 0.6,
        summary_trigger_ratio: float = 0.5,
        min_messages_before_summary: int = 20,
        summary_token_ratio: float = 0.26,
        target_summary_tokens: int = 2000
    ):
        """
        初始化总结器

        Args:
            llm: LangChain LLM 实例
            token_calculator: Token 计算器
            context_window: 模型上下文窗口大小
            target_usage_ratio: 目标窗口使用率
            summary_trigger_ratio: 总结触发阈值 (新消息token/总结token)
            min_messages_before_summary: 最少消息数才开始总结
            summary_token_ratio: 总结占用的 token 比例
            target_summary_tokens: 目标总结 token 数
        """
        self.llm = llm
        self.token_calculator = token_calculator
        self.context_window = context_window
        self.target_usage_ratio = target_usage_ratio
        self.summary_trigger_ratio = summary_trigger_ratio
        self.min_messages_before_summary = min_messages_before_summary
        self.summary_token_ratio = summary_token_ratio
        self.target_summary_tokens = target_summary_tokens
        
        # 计算 token 阈值
        self.max_tokens = int(context_window * target_usage_ratio)
        self.summary_budget = int(self.max_tokens * summary_token_ratio)
        
        logger.info(
            f"[总结器初始化] context_window={context_window}, "
            f"target_usage_ratio={target_usage_ratio}, summary_token_ratio={summary_token_ratio}, "
            f"max_tokens={self.max_tokens}, summary_budget={self.summary_budget}"
        )

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
        if len(messages) < self.min_messages_before_summary:
            logger.debug(f"[总结] 消息数不足: {len(messages)} < {self.min_messages_before_summary}")
            return False

        # 计算总 token 数，如果还没超过目标上限，不触发
        total_tokens = sum(self.token_calculator.calculate_message(m) for m in messages)
        if total_tokens <= self.max_tokens:
            logger.debug(
                f"[总结] Token 数未超过目标: {total_tokens} <= {self.max_tokens}, 不触发总结"
            )
            return False

        # 首次总结：无历史总结时触发
        if summary_metadata is None:
            logger.info(f"[总结] 首次总结触发: {len(messages)} 条消息, {total_tokens} tokens > {self.max_tokens}")
            return True

        # 增量总结：计算新消息 token 与历史总结 token 的比例
        summarized_until = summary_metadata.get('summarized_until', 0)
        new_messages = messages[summarized_until:]

        if len(new_messages) < 5:  # 新消息太少，不触发
            return False

        new_tokens = sum(self.token_calculator.calculate_message(m) for m in new_messages)
        summary_tokens = summary_metadata.get('summary_tokens', 1)  # 避免除零

        ratio = new_tokens / summary_tokens

        should = ratio > self.summary_trigger_ratio

        logger.info(
            f"[总结] 检查触发: 新消息={len(new_messages)}条({new_tokens}t), "
            f"历史总结={summary_tokens}t, 比例={ratio:.1%}, 阈值={self.summary_trigger_ratio:.1%}, "
            f"触发={'是' if should else '否'}"
        )

        return should

    def calculate_summarize_range(
        self,
        messages: List[BaseMessage],
        summary_metadata: Optional[Dict]
    ) -> Tuple[int, int]:
        """
        计算需要总结的消息范围

        总结后:
        - 剩余消息 token + 新总结 token < summary_budget
        - 至少保留 min_messages_before_summary 条最近消息

        Args:
            messages: 当前所有消息
            summary_metadata: 现有的总结元数据

        Returns:
            (start_index, end_index): 需要总结的消息范围 [start, end)
        """
        # 计算总 token 数
        total_tokens = sum(self.token_calculator.calculate_message(m) for m in messages)
        
        # 如果总 token 数还没超过目标，不需要总结
        if total_tokens <= self.max_tokens:
            logger.info(
                f"[总结] 范围计算: 总消息={len(messages)}, 总tokens={total_tokens}, "
                f"目标上限={self.max_tokens}, 无需总结"
            )
            return 0, 0
        
        # 从后往前计算需要保留的消息
        messages_to_keep = []
        keep_tokens = 0
        # 保留的消息 token 不超过 (max_tokens - summary_budget)
        target_keep = self.max_tokens - self.summary_budget

        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            msg_tokens = self.token_calculator.calculate_message(msg)

            # 检查是否还需要继续保留
            if keep_tokens + msg_tokens > target_keep and len(messages_to_keep) >= self.min_messages_before_summary:
                break

            messages_to_keep.insert(0, i)
            keep_tokens += msg_tokens

        # 计算需要总结的范围
        if messages_to_keep:
            end_index = messages_to_keep[0]  # 保留消息的第一条之前都需要总结
        else:
            end_index = len(messages)

        # 【关键】确保截断点不会破坏工具调用的完整性
        # 如果 end_index 位置的消息是 ToolMessage，说明它前面有 AIMessage 带 tool_calls
        # 需要向后调整 end_index，将整个工具调用序列包含在保留部分中
        # 这样可以避免 "Messages with role 'tool' must be a response to a preceding message with 'tool_calls'" 错误
        while end_index < len(messages) and isinstance(messages[end_index], ToolMessage):
            end_index += 1
            logger.debug(f"[总结] 调整截断点以保持工具调用完整性: end_index -> {end_index}")
        
        # 如果调整后 end_index 指向的是 AIMessage 且有 tool_calls，也需要包含后续的 ToolMessage
        # 反向检查：如果 end_index-1 是带 tool_calls 的 AIMessage，需要把 ToolMessage 也包含进保留部分
        if end_index > 0 and end_index < len(messages):
            prev_msg = messages[end_index - 1]
            if isinstance(prev_msg, AIMessage) and hasattr(prev_msg, 'tool_calls') and prev_msg.tool_calls:
                # 前一条是带 tool_calls 的 AI 消息，需要把这条和后续的 ToolMessage 都包含在保留部分
                end_index -= 1
                logger.debug(f"[总结] 调整截断点以包含完整工具调用: end_index -> {end_index}")

        # 开始位置：从头开始（如果有之前的总结，将其内容融入新总结）
        start_index = 0

        logger.info(
            f"[总结] 范围计算: 总消息={len(messages)}, 总tokens={total_tokens}, "
            f"需要总结=[0, {end_index}), 保留=[{end_index}, {len(messages)}), "
            f"保留消息={len(messages) - end_index}条, 目标保留={target_keep}t"
        )

        return start_index, end_index

    async def summarize(
        self,
        messages: List[BaseMessage],
        previous_summary: Optional[str] = None,
        user=None,
        model_id: str = "system_deepseek"
    ) -> Optional[Dict]:
        """
        生成对话历史总结

        Args:
            messages: 要总结的消息列表
            previous_summary: 之前的总结（用于增量更新）
            user: Django User 对象（用于 token 统计）
            model_id: 使用的模型 ID

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

            # ===== Token 统计 =====
            if user and user.is_authenticated:
                try:
                    from agent_service.context_optimizer import update_token_usage
                    
                    # 尝试从 response 获取实际 token 使用
                    input_tokens = 0
                    output_tokens = 0
                    
                    # 优先检查 usage_metadata
                    if hasattr(response, 'usage_metadata') and response.usage_metadata:
                        usage_metadata = response.usage_metadata
                        if isinstance(usage_metadata, dict):
                            input_tokens = usage_metadata.get('input_tokens', 0) or usage_metadata.get('prompt_tokens', 0)
                            output_tokens = usage_metadata.get('output_tokens', 0) or usage_metadata.get('completion_tokens', 0)
                        else:
                            input_tokens = getattr(usage_metadata, 'input_tokens', 0) or getattr(usage_metadata, 'prompt_tokens', 0)
                            output_tokens = getattr(usage_metadata, 'output_tokens', 0) or getattr(usage_metadata, 'completion_tokens', 0)
                    
                    # 回退：检查 response_metadata
                    if not input_tokens and hasattr(response, 'response_metadata'):
                        metadata = response.response_metadata
                        usage = metadata.get('token_usage') or metadata.get('usage') or {}
                        input_tokens = usage.get('prompt_tokens', 0) or usage.get('input_tokens', 0)
                        output_tokens = usage.get('completion_tokens', 0) or usage.get('output_tokens', 0)
                    
                    # 如果无法获取实际值，使用估算值
                    if input_tokens == 0 or output_tokens == 0:
                        logger.warning(f"[总结] 无法从 API 获取 Token 用量，降级为估算值")
                        if input_tokens == 0:
                            input_tokens = self.token_calculator.calculate_text(prompt)
                        if output_tokens == 0:
                            output_tokens = summary_tokens
                    
                    update_token_usage(user, input_tokens, output_tokens, model_id)
                    logger.info(f"[总结] Token 统计已更新: in={input_tokens}, out={output_tokens}")
                except Exception as e:
                    logger.warning(f"[总结] Token 统计失败: {e}")

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
    summary_token_budget: Optional[int] = None,  # 已弃用，保留参数兼容性
    recent_token_budget: Optional[int] = None    # 已弃用，保留参数兼容性
) -> List[BaseMessage]:
    """
    构建优化的上下文

    新逻辑:
    - 如果有总结，使用 [System] + [Summary] + [总结截止点之后的所有消息]
    - 如果没有总结，使用 [System] + [所有消息]（压缩工具输出）
    - 不再做消息截断，依赖总结功能来控制 token 数

    Args:
        user: Django User 对象
        system_prompt: 系统提示词
        messages: 完整消息列表
        summary_metadata: 总结元数据
        token_calculator: Token 计算器
        tool_compressor: 工具压缩器
        summary_token_budget: (已弃用)
        recent_token_budget: (已弃用)

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

        logger.info(f"[上下文] 添加历史总结: {summary_tokens}t, 截止第 {recent_start_index} 条")

    # 3. 最近对话（从总结截止点之后开始，包含所有消息）
    recent_messages = list(messages[recent_start_index:])

    # 压缩工具消息（减少 token 但保留所有消息）
    if tool_compressor:
        compressed_messages = []
        for msg in recent_messages:
            if isinstance(msg, ToolMessage):
                compressed_messages.append(tool_compressor.compress(msg, token_calculator))
            else:
                compressed_messages.append(msg)
        recent_messages = compressed_messages

    optimized.extend(recent_messages)

    # 重新计算实际 token
    recent_tokens = sum(token_calculator.calculate_message(m) for m in recent_messages)

    # 日志
    total_tokens = system_tokens + summary_tokens + recent_tokens
    logger.info(
        f"[上下文] 构建完成: "
        f"System={system_tokens}t, "
        f"Summary={summary_tokens}t, "
        f"Recent={recent_tokens}t ({len(recent_messages)}条), "
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
