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
        
        logger.debug(
            f"[总结器初始化] context_window={context_window}, "
            f"target_usage_ratio={target_usage_ratio}, summary_token_ratio={summary_token_ratio}, "
            f"max_tokens={self.max_tokens}, summary_budget={self.summary_budget}"
        )

    def should_summarize(
        self,
        messages: List[BaseMessage],
        summary_metadata: Optional[Dict],
        actual_total_tokens: int = 0
    ) -> bool:
        """
        判断是否应该触发总结

        Args:
            messages: 当前所有消息
            summary_metadata: 现有的总结元数据
            actual_total_tokens: 实际 token 数（优先使用，避免估算误差）。
                传入时将跳过逐条估算，直接与 max_tokens 比较。

        Returns:
            是否应该触发总结
        """
        # 消息数量不足
        if len(messages) < self.min_messages_before_summary:
            return False

        # 计算总 token 数，如果还没超过触发阈值，不触发
        # 触发阈值 = max_tokens × summary_trigger_ratio
        # 例：context_window=131072, target_usage_ratio=0.3, summary_trigger_ratio=0.3
        # → max_tokens = 39321t，触发阈值 = 39321 × 0.3 = 11796t
        # 这样可以在接近上限之前提前压缩，而不是等到超过上限才触发
        # （build_optimized_context 已保证发送的 token 不超过 max_tokens，
        #   所以 total_tokens > max_tokens 永远不会成立，必须用更低的触发阈值）
        if actual_total_tokens > 0:
            total_tokens = actual_total_tokens
        else:
            total_tokens = sum(self.token_calculator.calculate_message(m) for m in messages)
        summary_trigger_tokens = int(self.max_tokens * self.summary_trigger_ratio)
        if total_tokens <= summary_trigger_tokens:
            logger.debug(
                f"[总结] 未触发: total_tokens={total_tokens} <= trigger_tokens={summary_trigger_tokens} "
                f"(max_tokens={self.max_tokens}, trigger_ratio={self.summary_trigger_ratio}, "
                f"source={'actual' if actual_total_tokens > 0 else 'estimated'})"
            )
            return False
            
        # 触发总结（无论是首次还是增量，均基于总 token 超过触发阈值）
        logger.debug(
            f"[总结] 将触发: total_tokens={total_tokens} > trigger_tokens={summary_trigger_tokens}"
        )
        return True

    def calculate_summarize_range(
        self,
        messages: List[BaseMessage],
        summary_metadata: Optional[Dict],
        actual_total_tokens: int = 0,
        token_snapshots: Optional[Dict] = None
    ) -> Tuple[int, int]:
        """
        计算需要总结的消息范围

        Args:
            messages: 当前所有消息
            summary_metadata: 现有的总结元数据
            actual_total_tokens: 实际 token 数（优先使用）
            token_snapshots: 每轮 LLM 调用快照 {消息数str: {input_tokens, source}}
                差值公式: actual_total - snap[K] = messages[K:] 的实际 token（系统提示抵消）
        """
        if actual_total_tokens > 0:
            total_tokens = actual_total_tokens
        else:
            total_tokens = sum(self.token_calculator.calculate_message(m) for m in messages)

        summary_trigger_tokens = int(self.max_tokens * self.summary_trigger_ratio)
        if total_tokens <= summary_trigger_tokens:
            return 0, 0

        # 近期消息保留预算 = trigger_tokens × (1 - summary_token_ratio)
        target_keep = max(int(summary_trigger_tokens * (1 - self.summary_token_ratio)), 0)

        end_index = 0
        found_via_snapshots = False

        # ===== 方案 A：token_snapshots 精确法 =====
        # snap[K] = 当 state 有 K 条消息时 LLM 调用的 input_tokens = SP + tokens(msgs[0:K])
        # actual_total - snap[K] = tokens(msgs[K:])，SP 在差值中抵消，精确无误
        # 从大 split 往小扫，找最大 end_index（最大化压缩量），使尾部实际 token <= target_keep
        if token_snapshots and actual_total_tokens > 0:
            snap_map = {}
            for k, v in token_snapshots.items():
                try:
                    ki = int(k)
                    tok = v.get('input_tokens', 0) if isinstance(v, dict) else 0
                    if tok > 0 and ki > 0:
                        snap_map[ki] = tok
                except (ValueError, TypeError):
                    pass

            if snap_map:
                sorted_snap_keys = sorted(snap_map.keys())
                max_split = len(messages) - self.min_messages_before_summary
                for split in range(max_split, 0, -1):
                    candidates = [k for k in sorted_snap_keys if k <= split]
                    if not candidates:
                        continue
                    snap_key = max(candidates)
                    # tail_tokens 使用最近快照边界，略高估（含 snap_key..split 段），保守安全
                    tail_tokens = actual_total_tokens - snap_map[snap_key]
                    if tail_tokens <= target_keep:
                        end_index = split
                        found_via_snapshots = True
                        logger.debug(
                            f"[总结] 范围(快照法): split={split}, snap_key={snap_key}, "
                            f"tail={tail_tokens}t <= target={target_keep}t"
                        )
                        break

        # ===== 方案 B：scale-factor 回退 =====
        if not found_via_snapshots:
            estimated_total = sum(self.token_calculator.calculate_message(m) for m in messages)
            token_scale = (
                (actual_total_tokens / estimated_total)
                if (actual_total_tokens > 0 and estimated_total > 0)
                else 1.0
            )
            messages_to_keep = []
            keep_tokens = 0
            for i in range(len(messages) - 1, -1, -1):
                msg_tokens = int(self.token_calculator.calculate_message(messages[i]) * token_scale)
                if keep_tokens + msg_tokens > target_keep and len(messages_to_keep) >= self.min_messages_before_summary:
                    break
                messages_to_keep.insert(0, i)
                keep_tokens += msg_tokens
            end_index = messages_to_keep[0] if messages_to_keep else len(messages)
            logger.debug(
                f"[总结] 范围(缩放法): scale={token_scale:.2f}x, end_index={end_index}, target={target_keep}t"
            )

        # 确保截断点不破坏工具调用完整性
        while end_index < len(messages) and isinstance(messages[end_index], ToolMessage):
            end_index += 1
        if end_index > 0 and end_index < len(messages):
            prev_msg = messages[end_index - 1]
            if isinstance(prev_msg, AIMessage) and hasattr(prev_msg, 'tool_calls') and prev_msg.tool_calls:
                end_index -= 1

        start_index = 0
        logger.debug(
            f"[总结] 范围计算完成: 总消息={len(messages)}, 总tokens={total_tokens}, "
            f"需要总结=[0, {end_index}), 保留=[{end_index}, {len(messages)}), "
            f"保留消息={len(messages) - end_index}条, target_keep={target_keep}t, "
            f"方法={'快照' if found_via_snapshots else '缩放'}"
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
                    tokens_source = 'estimated'  # 默认为估算
                    
                    # 优先检查 usage_metadata
                    if hasattr(response, 'usage_metadata') and response.usage_metadata:
                        usage_metadata = response.usage_metadata
                        if isinstance(usage_metadata, dict):
                            input_tokens = usage_metadata.get('input_tokens', 0) or usage_metadata.get('prompt_tokens', 0)
                            output_tokens = usage_metadata.get('output_tokens', 0) or usage_metadata.get('completion_tokens', 0)
                        else:
                            input_tokens = getattr(usage_metadata, 'input_tokens', 0) or getattr(usage_metadata, 'prompt_tokens', 0)
                            output_tokens = getattr(usage_metadata, 'output_tokens', 0) or getattr(usage_metadata, 'completion_tokens', 0)
                        
                        if input_tokens > 0 and output_tokens > 0:
                            tokens_source = 'actual'
                    
                    # 回退：检查 response_metadata
                    if not input_tokens and hasattr(response, 'response_metadata'):
                        metadata = response.response_metadata
                        usage = metadata.get('token_usage') or metadata.get('usage') or {}
                        input_tokens = usage.get('prompt_tokens', 0) or usage.get('input_tokens', 0)
                        output_tokens = usage.get('completion_tokens', 0) or usage.get('output_tokens', 0)
                        
                        if input_tokens > 0 and output_tokens > 0:
                            tokens_source = 'actual'
                    
                    # 如果无法获取实际值，使用估算值
                    if input_tokens == 0 or output_tokens == 0:
                        logger.warning(f"⚠️ [总结-Token降级] 无法从API获取Token用量，使用估算值（将用于上下文显示）")
                        tokens_source = 'estimated'
                        if input_tokens == 0:
                            input_tokens = self.token_calculator.calculate_text(prompt)
                        if output_tokens == 0:
                            output_tokens = summary_tokens
                    
                    from asgiref.sync import sync_to_async
                    await sync_to_async(update_token_usage)(user, input_tokens, output_tokens, model_id)
                    logger.debug(f"[总结-计费] Token 统计已更新: in={input_tokens}, out={output_tokens}, source={tokens_source}")
                except Exception as e:
                    logger.warning(f"[总结] Token 统计失败: {e}")
                    tokens_source = 'estimated'
                    input_tokens = self.token_calculator.calculate_text(prompt)
                    output_tokens = summary_tokens

            # 记录压缩率
            compression_rate = 1 - (summary_tokens / original_tokens) if original_tokens > 0 else 0
            logger.info(
                f"[总结] 完成: {len(messages)}条消息, "
                f"{original_tokens}t → {summary_tokens}t, "
                f"压缩率={compression_rate:.1%}, "
                f"input_tokens={input_tokens}, source={tokens_source}"
            )

            return {
                "summary": summary_text,
                "summarized_until": len(messages),
                "summary_tokens": summary_tokens,
                "summary_input_tokens": input_tokens,  # 新增：总结时的真实 input_tokens
                "tokens_source": tokens_source,  # 新增：Token 数据来源
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
            
            # 处理多模态消息内容：提取文本部分，图片显示占位符
            raw_content = msg.content
            if isinstance(raw_content, list):
                text_parts = []
                image_count = 0
                for block in raw_content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") in ("image_url", "image"):
                            image_count += 1
                    elif isinstance(block, str):
                        text_parts.append(block)
                content = " ".join(text_parts)
                if image_count > 0:
                    content = f"[包含 {image_count} 张图片] " + content
            else:
                content = raw_content if isinstance(raw_content, str) else str(raw_content)

            # 截断过长的内容
            if len(content) > 500:
                content = content[:500] + "..."

            # 附件内容（文档/图片解析结果）存储在 additional_kwargs 中，需单独提取
            if isinstance(msg, HumanMessage):
                kwargs = getattr(msg, 'additional_kwargs', {}) or {}
                attach_ctx = kwargs.get('attachments_context', '')
                if attach_ctx:
                    preview = attach_ctx[:800] + ("...[附件内容截断]" if len(attach_ctx) > 800 else "")
                    content = content + f"\n[附件内容] {preview}"

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


# ========== 工具压缩配置 ==========
# 保留最近 X 条用户消息对应的工具调用结果不压缩
# 只有 X 条用户消息之前的工具调用结果会被压缩
# 【已废弃】此常量已移至用户配置（tool_compress_preserve_recent_messages），保留仅作为后备默认值
TOOL_COMPRESS_PRESERVE_RECENT_USER_MESSAGES = 5  # 后备默认值


def _find_compression_boundary(messages: List[BaseMessage], preserve_count: int) -> int:
    """
    找到工具压缩的边界索引
    
    从后往前数 preserve_count 条用户消息，返回第一条被保留的用户消息的索引。
    该索引之前的 ToolMessage 可以被压缩，该索引及之后的 ToolMessage 不压缩。
    
    Args:
        messages: 消息列表
        preserve_count: 保留最近多少条用户消息对应的工具不压缩
        
    Returns:
        边界索引。该索引之前的 ToolMessage 可以压缩。
        如果用户消息数 <= preserve_count，返回 0（不压缩任何工具消息）
    """
    # 从后往前找所有 HumanMessage 的位置
    human_indices = []
    for i, msg in enumerate(messages):
        if isinstance(msg, HumanMessage):
            human_indices.append(i)
    
    # 如果用户消息数量 <= preserve_count，不压缩任何工具消息
    if len(human_indices) <= preserve_count:
        return 0
    
    # 找到倒数第 preserve_count 条用户消息的索引
    # 例如：preserve_count=2，有5条用户消息在索引 [3, 10, 15, 22, 30]
    # 倒数第2条是索引 22，所以边界是 22
    boundary_index = human_indices[-preserve_count]
    
    return boundary_index


def build_optimized_context(
    user,
    system_prompt: str,
    messages: List[BaseMessage],
    summary_metadata: Optional[Dict],
    token_calculator,
    tool_compressor,
    summary_token_budget: Optional[int] = None,  # 已弃用，保留参数兼容性
    recent_token_budget: Optional[int] = None,   # 已弃用，保留参数兼容性
    preserve_recent_count: int = TOOL_COMPRESS_PRESERVE_RECENT_USER_MESSAGES  # 保留最近几条用户消息对应的工具不压缩
) -> List[BaseMessage]:
    """
    构建优化的上下文

    新逻辑:
    - 如果有总结，使用 [System] + [Summary] + [总结截止点之后的所有消息]
    - 如果没有总结，使用 [System] + [所有消息]（智能压缩工具输出）
    
    Args:
        preserve_recent_count: 保留最近几条用户消息对应的工具调用结果不压缩
    - 工具压缩策略：只压缩最近 N 条用户消息之前的工具调用结果
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
        summarized_until = summary_metadata.get('summarized_until', 0)
        summary_tokens_count = summary_metadata.get('summary_tokens', 0)
        created_at = summary_metadata.get('created_at', '')
        # 截取到秒，格式如 "2026-03-15 12:30"
        created_at_str = (created_at[:16].replace('T', ' ')) if created_at else '未知'

        # 构建结构化总结头部，让 LLM 明确感知覆盖范围和压缩信息
        summary_header = (
            f"【对话历史总结】\n"
            f"覆盖范围: 消息 #0–#{summarized_until - 1}（共 {summarized_until} 条）\n"
            f"生成时间: {created_at_str}\n"
            f"压缩规模: 约 {summary_tokens_count} tokens\n"
            f"---\n"
        )
        summary_msg = SystemMessage(content=f"{summary_header}{summary_text}\n---")
        optimized.append(summary_msg)
        summary_tokens = summary_tokens_count
        recent_start_index = summarized_until

        logger.debug(f"[上下文] 添加历史总结: {summary_tokens}t, 截止第 {recent_start_index} 条")
        logger.info(
            f"[上下文] 注入结构化总结头: summarized_until={summarized_until}, "
            f"summary_tokens={summary_tokens_count}, created_at={created_at_str}"
        )

    # 3. 最近对话（从总结截止点之后开始，包含所有消息）
    recent_messages = list(messages[recent_start_index:])

    # 智能压缩工具消息：只压缩最近 N 条用户消息之前的工具调用结果
    if tool_compressor:
        # 找到压缩边界（基于 recent_messages 的相对索引）
        compress_boundary = _find_compression_boundary(
            recent_messages,
            preserve_recent_count
        )
        
        compressed_count = 0
        preserved_count = 0
        
        compressed_messages = []
        for i, msg in enumerate(recent_messages):
            if isinstance(msg, ToolMessage):
                if i < compress_boundary:
                    # 边界之前的工具消息可以压缩
                    compressed_msg = tool_compressor.compress(msg, token_calculator)
                    compressed_messages.append(compressed_msg)
                    if compressed_msg is not msg:  # 实际被压缩了
                        compressed_count += 1
                else:
                    # 边界及之后的工具消息保持原样
                    compressed_messages.append(msg)
                    preserved_count += 1
            else:
                compressed_messages.append(msg)
        
        recent_messages = compressed_messages
        
        if compressed_count > 0 or preserved_count > 0:
            logger.debug(f"[上下文] 工具压缩: 压缩 {compressed_count} 条, 保留 {preserved_count} 条 (边界索引={compress_boundary}, preserve_recent_count={preserve_recent_count})")

    optimized.extend(recent_messages)

    # 重新计算实际 token
    recent_tokens = sum(token_calculator.calculate_message(m) for m in recent_messages)

    # 日志
    total_tokens = system_tokens + summary_tokens + recent_tokens
    logger.debug(
        f"[上下文] 构建完成: "
        f"System={system_tokens}t, "
        f"Summary={summary_tokens}t, "
        f"Recent={recent_tokens}t ({len(recent_messages)}条), "
        f"Total={total_tokens}t (优化前预估，不用于计费)"
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
