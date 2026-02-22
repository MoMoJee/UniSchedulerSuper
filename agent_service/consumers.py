"""
Agent WebSocket Consumer
处理与 Agent 的实时通信
"""

# ========== Agent 配置常量 ==========
# Agent 单次对话中允许的最大图执行步数 (recursion_limit)
# 注意：这不是工具调用次数，而是图的执行步数（包括 LLM 调用、工具执行、结果处理等）
# 一轮完整的"工具调用"通常需要 2-3 个步数：LLM生成工具调用 → 执行工具 → LLM处理结果
# 建议值：50 (约可支持 15-20 轮工具调用)，25 (约可支持 8-10 轮工具调用)
# 达到此限制后会提示用户是否继续
# 【已废弃】此常量已移至用户配置中，保留仅作为后备默认值
RECURSION_LIMIT = 25  # 后备默认值

import json
import asyncio
import logging
from typing import Optional
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from asgiref.sync import sync_to_async
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk, ToolMessage
from django.contrib.auth.models import User

from logger import logger

# ========== 异步 App 获取 ==========
# 缓存编译后的 app 实例
_cached_async_app = None

async def get_async_app():
    """
    获取带有异步 checkpointer 的 app（单例模式）
    必须在异步上下文中调用
    """
    global _cached_async_app
    if _cached_async_app is None:
        from agent_service.agent_graph import get_app_with_checkpointer
        _cached_async_app = await get_app_with_checkpointer()
        logger.info("[Consumers] 异步 App 已初始化")
    return _cached_async_app

class AgentConsumer(AsyncWebsocketConsumer):
    """
    Agent WebSocket Consumer
    
    URL: ws://host/ws/agent/?active_experts=planner,chat&session_id=xxx
    
    消息协议:
    - 客户端 -> 服务器:
        {"type": "message", "content": "用户消息"}
        {"type": "ping"}
    
    - 服务器 -> 客户端:
        {"type": "token", "content": "流式token"}
        {"type": "message", "content": "完整消息", "finished": true}
        {"type": "tool_call", "name": "tool_name", "args": {...}}
        {"type": "tool_result", "name": "tool_name", "result": "..."}
        {"type": "error", "message": "错误信息"}
        {"type": "pong"}
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user: Optional[User] = None
        self.session_id: Optional[str] = None
        self.active_tools: list = []  # 启用的工具列表
        self.graph = None
        self.is_processing = False
        self.should_stop = False  # 停止标志
        self.current_task: Optional[asyncio.Task] = None  # 当前处理任务
    
    async def connect(self):
        """处理 WebSocket 连接"""
        # 1. 验证用户身份
        self.user = self.scope.get("user")
        if not self.user or not self.user.is_authenticated:
            logger.warning("未认证用户尝试连接 WebSocket")
            await self.close(code=4001)
            return
        
        # 2. 解析 URL 参数
        query_string = self.scope.get("query_string", b"").decode()
        params = self._parse_query_string(query_string)
        
        self.session_id = params.get("session_id", f"user_{self.user.id}_default")
        
        # 获取启用的工具
        # 注意：区分"未传递参数"和"传递空参数"：
        # - 未传递参数（None）：使用默认工具
        # - 传递空参数（""）：不启用任何工具（用户明确选择为空）
        from agent_service.agent_graph import get_default_tools
        tools_param = params.get("active_tools")  # None 或 字符串
        if tools_param is None:
            # 未传递参数，使用默认工具
            self.active_tools = get_default_tools()
            logger.debug(f"未指定工具参数，使用默认工具: {len(self.active_tools)} 个")
        elif tools_param == "":
            # 传递了空参数，用户明确选择不启用任何工具
            self.active_tools = []
            logger.debug(f"用户明确选择不启用任何工具")
        else:
            # 传递了具体的工具列表
            self.active_tools = [t.strip() for t in tools_param.split(",") if t.strip()]
            logger.debug(f"用户选择工具: {self.active_tools}")
        
        logger.info(f"用户 {self.user.username} 连接 WebSocket, session={self.session_id}, tools={len(self.active_tools)} 个")
        
        # 3. 初始化 Agent Graph
        await self._init_graph()
        
        # 4. 接受连接
        await self.accept()
        
        # 5. 加入 session group（用于广播消息）
        self.group_name = f"agent_session_{self.session_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        logger.info(f"✅ 已加入 channel group: {self.group_name}")
        
        # 6. 获取当前消息数量
        current_message_count = 0
        try:
            app = await get_async_app()
            config = {"configurable": {"thread_id": self.session_id}}
            state = await app.aget_state(config)
            if state and state.values:
                messages = state.values.get("messages", [])
                current_message_count = len(messages)
        except Exception as e:
            logger.warning(f"[WebSocket] 获取消息数量失败: {e}")
        
        # 6. 检查会话命名状态
        is_naming = False
        session_name = ""
        try:
            from agent_service.models import AgentSession
            session = await database_sync_to_async(
                AgentSession.objects.filter(session_id=self.session_id).first
            )()
            if session:
                is_naming = session.is_naming
                session_name = session.name
        except Exception as e:
            logger.warning(f"[WebSocket] 检查命名状态失败: {e}")
        
        # 7. 发送欢迎消息（包含消息数量和命名状态）
        await self.send_json({
            "type": "connected",
            "session_id": self.session_id,
            "active_tools": self.active_tools,
            "message_count": current_message_count,
            "is_naming": is_naming,
            "session_name": session_name,
            "message": f"欢迎, {self.user.username}!"
        })
    
    async def send_json(self, content, close=False):
        """重写 send_json，使用 channel_layer 广播消息到所有连接"""
        # 如果是流式相关消息，通过 channel_layer 广播
        msg_type = content.get("type")
        if msg_type in ["stream_start", "stream_chunk", "tool_call", "tool_result", "stream_end", "finished"]:
            # 通过 channel_layer 广播到 group 中所有连接
            if hasattr(self, 'group_name') and self.channel_layer:
                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        "type": "broadcast_message",
                        "content": content
                    }
                )
            else:
                # 没有 channel_layer，回退到直接发送
                await self.send(text_data=json.dumps(content, ensure_ascii=False))
        else:
            # 非流式消息，直接发送
            await self.send(text_data=json.dumps(content, ensure_ascii=False))
    
    async def broadcast_message(self, event):
        """接收 channel_layer 广播的消息并发送给客户端"""
        content = event["content"]
        await self.send(text_data=json.dumps(content, ensure_ascii=False))
    
    async def disconnect(self, close_code):
        """处理 WebSocket 断开"""
        logger.info(f"用户 {self.user.username if self.user else 'unknown'} 断开 WebSocket, code={close_code}")
        
        # 离开 channel group
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            logger.info(f"🚪 已离开 channel group: {self.group_name}")
    
    async def receive(self, text_data):
        """处理收到的消息"""
        try:
            data = json.loads(text_data)
            msg_type = data.get("type", "message")
            
            if msg_type == "ping":
                # 心跳响应
                await self.send_json({"type": "pong"})
                
            elif msg_type == "stop":
                # 停止当前处理
                if self.is_processing:
                    self.should_stop = True
                    # 取消当前任务
                    if self.current_task and not self.current_task.done():
                        self.current_task.cancel()
                        logger.info(f"用户 {self.user.username} 取消了当前任务")
                    logger.info(f"用户 {self.user.username} 请求停止处理")
                    # 【修复】不要在这里发送 stopped，让任务取消后在 finally 中统一处理
                    # await self.send_json({"type": "stopped", "message": "已停止生成"})
                else:
                    await self.send_json({"type": "info", "message": "当前没有正在处理的消息"})
                
            elif msg_type == "message":
                # 用户消息
                content = data.get("content", "").strip()
                attachment_ids = data.get("attachment_ids", [])
                if not content:
                    await self.send_json({"type": "error", "message": "消息内容不能为空"})
                    return
                
                if self.is_processing:
                    await self.send_json({"type": "error", "message": "正在处理上一条消息，请稍候"})
                    return
                
                # 重置停止标志
                self.should_stop = False
                # 创建任务并运行
                self.current_task = asyncio.create_task(self._process_message(content, attachment_ids=attachment_ids))
            
            elif msg_type == "continue":
                # 用户选择继续执行（达到递归限制后）
                logger.info(f"用户 {self.user.username} 选择继续执行")
                if self.is_processing:
                    await self.send_json({"type": "error", "message": "正在处理中，请稍候"})
                    return
                
                # 重置停止标志并继续
                self.should_stop = False
                self.current_task = asyncio.create_task(self._continue_processing())
            
            elif msg_type == "check_status":
                # 查询当前会话的处理状态（用于刷新后恢复流式状态）
                logger.info(f"用户 {self.user.username} 查询会话状态")
                
                # 获取 LangGraph 的实际状态
                has_pending_messages = False
                last_message_role = None
                should_sync_immediately = False
                try:
                    app = await get_async_app()
                    config = {"configurable": {"thread_id": self.session_id}}
                    state = await app.aget_state(config)
                    if state and state.values:
                        messages = state.values.get("messages", [])
                        if messages:
                            last_msg = messages[-1]
                            last_message_role = getattr(last_msg, 'type', None)
                            # 如果最后一条消息是工具消息或人类消息，说明还需要继续处理
                            if last_message_role in ['tool', 'human']:
                                has_pending_messages = True
                            # 如果最后一条是 AI 消息且不在处理中，说明流式输出已完成，前端应该立即同步
                            elif last_message_role == 'ai' and not self.is_processing:
                                should_sync_immediately = True
                                logger.info(f"检测到流式输出已完成，建议前端立即同步")
                except Exception as e:
                    logger.warning(f"获取 LangGraph 状态失败: {e}")
                
                await self.send_json({
                    "type": "status_response",
                    "session_id": self.session_id,
                    "is_processing": self.is_processing,
                    "should_stop": self.should_stop,
                    "has_pending_messages": has_pending_messages,
                    "last_message_role": last_message_role,
                    "should_sync_immediately": should_sync_immediately
                })
                
            else:
                await self.send_json({"type": "error", "message": f"未知消息类型: {msg_type}"})
                
        except json.JSONDecodeError:
            await self.send_json({"type": "error", "message": "无效的 JSON 格式"})
        except Exception as e:
            logger.exception(f"处理消息时出错: {e}")
            await self.send_json({"type": "error", "message": f"服务器错误: {str(e)}"})
    
    async def _build_human_message(self, content: str, attachment_ids: list = None) -> HumanMessage:
        """
        构建 HumanMessage，支持多模态附件。
        
        核心改造：
        1. content 只包含用户输入文本（图片除外，图片以 image_url 块形式包含）
        2. 附件的描述信息（给 LLM 看）存到 additional_kwargs['attachments_context']
        3. 附件元数据（给前端历史渲染）存到 additional_kwargs['attachments_metadata']
        """
        if not attachment_ids:
            return HumanMessage(content=content)
        
        try:
            from agent_service.attachment_handler import AttachmentHandler
            from agent_service.models import SessionAttachment
            
            # 异步查询附件
            attachments = await database_sync_to_async(
                lambda: list(SessionAttachment.objects.filter(
                    id__in=attachment_ids, user=self.user, is_deleted=False
                ))
            )()
            
            if not attachments:
                return HumanMessage(content=content)
            
            # 构建附件元数据（供前端历史渲染）
            attachments_metadata = []
            for att in attachments:
                meta = {
                    'sa_id': att.id,
                    'type': att.type,
                    'filename': att.filename,
                    'mime_type': att.mime_type,
                }
                if att.is_internal:
                    meta['internal_type'] = att.internal_type
                    meta['internal_id'] = att.internal_id
                    meta['name'] = att.filename  # 元素标题/名称
                if att.file:
                    meta['file_url'] = att.file.url
                if att.thumbnail:
                    meta['thumbnail_url'] = att.thumbnail.url
                attachments_metadata.append(meta)
            
            # 构建多模态 content_blocks（用于判断是否有图片，以及给 LLM 的上下文）
            content_blocks = await database_sync_to_async(
                AttachmentHandler.format_for_message
            )(attachments, user=self.user)
            
            if not content_blocks:
                return HumanMessage(
                    content=content,
                    additional_kwargs={
                        'attachment_ids': attachment_ids,
                        'attachments_metadata': attachments_metadata,
                    }
                )
            
            # 分离图片块和文本块
            image_blocks = [b for b in content_blocks if b.get('type') == 'image_url']
            text_blocks = [b for b in content_blocks if b.get('type') == 'text']
            
            # 标记附件为已发送
            att_ids = [a.id for a in attachments]
            await database_sync_to_async(
                AttachmentHandler.mark_sent
            )(att_ids, message_index=0)
            
            if image_blocks:
                # 有图片：构建多模态 content（text + images），文本块作为附件上下文
                multimodal_content = [{"type": "text", "text": content}]
                multimodal_content.extend(image_blocks)
                
                # 提取纯文本附件的描述（给 LLM 的上下文）
                attachments_context = '\n\n'.join(b.get('text', '') for b in text_blocks)
                
                # 估算图片 token 数（OpenAI 视觉模型的粗略估算）
                # 参考: 低细节图片约 85 tokens, 高细节图片约 170-765 tokens (取决于分块数)
                # 这里假设使用 detail="auto" 配置，平均约 85-100 tokens/图
                estimated_tokens_per_image = 85
                estimated_image_tokens = len(image_blocks) * estimated_tokens_per_image
                
                logger.debug(
                    f"[多模态] 构建多模态消息: {len(image_blocks)} 张图片, "
                    f"附件上下文 {len(attachments_context)} 字符, "
                    f"预估图片Token≈{estimated_image_tokens} (按{estimated_tokens_per_image}token/图)"
                )
                
                return HumanMessage(
                    content=multimodal_content,
                    additional_kwargs={
                        'attachment_ids': attachment_ids,
                        'attachments_metadata': attachments_metadata,
                        'attachments_context': attachments_context,
                    }
                )
            else:
                # 纯文本附件：content 只包含用户输入，附件描述存到 attachments_context
                attachments_context = '\n\n'.join(b.get('text', '') for b in text_blocks)
                
                logger.debug(f"[附件] 纯文本附件: {len(attachments)} 个, 上下文 {len(attachments_context)} 字符")
                
                return HumanMessage(
                    content=content,
                    additional_kwargs={
                        'attachment_ids': attachment_ids,
                        'attachments_metadata': attachments_metadata,
                        'attachments_context': attachments_context,
                    }
                )
            
        except Exception as e:
            logger.error(f"[多模态] 构建多模态消息失败: {e}", exc_info=True)
            # 降级为纯文本
            return HumanMessage(content=content)

    async def _process_message(self, content: str, attachment_ids: list = None):
        """
        处理用户消息并真正流式输出
        使用 stream_mode="messages" 获取 token 级别的流式输出
        
        Args:
            content: 用户消息文本
            attachment_ids: SessionAttachment IDs（用于构建多模态消息）
        """
        self.is_processing = True
        
        try:
            # 通知开始处理
            await self.send_json({"type": "processing", "message": "正在思考..."})
            
            # 准备配置
            # 从用户配置读取 recursion_limit
            from agent_service.context_optimizer import get_optimization_config
            opt_config = await database_sync_to_async(get_optimization_config)(self.user)
            recursion_limit = opt_config.get('recursion_limit', RECURSION_LIMIT)
            
            config = {
                "configurable": {
                    "thread_id": self.session_id,
                    "user": self.user,
                    "active_tools": self.active_tools  # 传递 active_tools 到 config
                },
                "recursion_limit": recursion_limit  # 从用户配置读取，单次对话最大工具调用步数
            }
            
            # 获取异步 app
            app = await get_async_app()
            
            # ========== 【关键】配额检查 ==========
            from agent_service.context_optimizer import check_quota_available, get_current_model_config
            
            current_model_id, _ = await database_sync_to_async(get_current_model_config)(self.user)
            quota_info = await database_sync_to_async(check_quota_available)(self.user, current_model_id)
            
            if not quota_info.get('available', True):
                # 配额不足，拒绝处理
                await self.send_json({
                    "type": "quota_exceeded",
                    "message": quota_info.get('message', "您本月的抵用金已用尽，请使用自己的模型或等待下个月"),
                    "monthly_credit": quota_info.get('monthly_credit', 0),
                    "monthly_used": quota_info.get('monthly_used', 0),
                    "remaining": quota_info.get('remaining', 0)
                })
                self.is_processing = False
                return
            
            # ========== 【关键】检查是否是第一条消息，决定是否自动命名 ==========
            is_first_message = False
            try:
                current_state = await app.aget_state(config)
                if not current_state or not current_state.values or not current_state.values.get("messages"):
                    is_first_message = True
                    logger.info(f"[自动命名] 检测到第一条消息: {content[:50]}...")
            except Exception as e:
                logger.warning(f"[自动命名] 检查第一条消息失败: {e}")
            
            # 如果是第一条消息，执行自动命名（在回复之前）
            if is_first_message:
                await self._auto_name_session(content)
            
            # ========== 【关键】发送前检查并执行历史总结 ==========
            # 获取当前历史消息，检查是否需要总结
            try:
                current_state = await app.aget_state(config)
                if current_state and current_state.values:
                    current_messages = current_state.values.get("messages", [])
                    if current_messages:
                        await self._check_and_summarize(current_messages, config)
            except Exception as e:
                logger.warning(f"[总结] 发送前检查失败: {e}")
            
            # ========== 更新 last_message_preview ==========
            await self._update_last_message_preview(content)
            
            # 准备输入 — 支持多模态（attachment_ids → content_blocks）
            human_message = await self._build_human_message(content, attachment_ids)
            
            input_state = {
                "messages": [human_message],
                "active_tools": self.active_tools
            }
            
            # 流式输出状态
            stream_started = False
            
            # 【重构】使用异步 astream 替代同步 stream + 后台线程
            # 这样 asyncio.CancelledError 可以传播到底层 HTTP 客户端并中断请求
            try:
                logger.debug(f"[Stream] 开始异步流式处理")
                chunk_count = 0
                
                async for output in app.astream(input_state, config):
                    # 检查停止标志
                    if self.should_stop:
                        logger.debug(f"[Stream] 检测到停止信号，中断处理")
                        break
                    
                    chunk_count += 1
                    
                    # output 是一个字典，key 是节点名称，value 是该节点的输出
                    for node_name, node_output in output.items():
                        if self.should_stop:
                            logger.debug(f"[Stream] 检测到停止信号，中断节点处理")
                            break
                        
                        # 检查是否有 messages
                        if isinstance(node_output, dict) and 'messages' in node_output:
                            for msg in node_output['messages']:
                                if self.should_stop:
                                    logger.debug(f"[Stream] 检测到停止信号，中断消息处理")
                                    break
                                
                                # 处理 AIMessage 的内容
                                if hasattr(msg, 'content') and msg.content:
                                    if not stream_started:
                                        await self.send_json({"type": "stream_start"})
                                        stream_started = True
                                    await self.send_json({
                                        "type": "stream_chunk",
                                        "content": msg.content
                                    })
                                
                                # 处理工具调用
                                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                                    if stream_started:
                                        await self.send_json({"type": "stream_end"})
                                        stream_started = False
                                    for tc in msg.tool_calls:
                                        await self.send_json({
                                            "type": "tool_call",
                                            "name": tc.get("name", "unknown"),
                                            "args": tc.get("args", {})
                                        })
                                
                                # 处理 ToolMessage
                                if hasattr(msg, 'type') and getattr(msg, 'type', None) == 'tool':
                                    result_str = str(msg.content) if hasattr(msg, 'content') else str(msg)
                                    tool_name = msg.name if hasattr(msg, 'name') else "tool"
                                    # 根据工具名称确定需要刷新的数据类型
                                    refresh_types = self._get_refresh_types_for_tool(tool_name)
                                    await self.send_json({
                                        "type": "tool_result",
                                        "name": tool_name,
                                        "result": result_str,
                                        "refresh": refresh_types
                                    })
                    
                    # 每次迭代后让出控制权，允许处理取消信号
                    await asyncio.sleep(0)
                
                logger.debug(f"[Stream] 异步流式处理完成, 共 {chunk_count} 个 outputs")
                
            except asyncio.CancelledError:
                logger.debug(f"[Stream] 异步流式处理被取消")
                raise  # 重新抛出让外层处理
            except Exception as e:
                error_str = str(e)
                logger.exception(f"[Stream] 异步流式处理异常: {e}")
                
                # 检查是否是递归限制错误
                if "Recursion limit" in error_str or "GraphRecursionError" in type(e).__name__:
                    logger.warning(f"达到递归限制: {error_str}")
                    if stream_started:
                        await self.send_json({"type": "stream_end"})
                        stream_started = False
                    
                    await self.send_json({
                        "type": "recursion_limit",
                        "message": "工具调用次数达到上限，是否继续执行？"
                    })
                    return  # 递归限制不算错误，直接返回
                else:
                    raise  # 其他异常重新抛出
            
            # 确保流正确结束
            if stream_started:
                await self.send_json({"type": "stream_end"})
            
            # 获取最终消息数量
            final_message_count = 0
            final_messages = []
            try:
                final_state = await app.aget_state(config)
                if final_state and final_state.values:
                    final_messages = final_state.values.get("messages", [])
                    final_message_count = len(final_messages)
            except Exception as e:
                logger.warning(f"获取最终消息数量失败: {e}")
            
            # 发送完成信号（包含消息数量）
            if not self.should_stop:
                await self.send_json({
                    "type": "finished",
                    "message": "处理完成",
                    "message_count": final_message_count
                })
                
                # 注意：总结检查已移至发送前执行，回复后不再检查
            
        except asyncio.CancelledError:
            logger.info(f"消息处理任务被取消")
            # 【重要】任务取消时，确保流式状态正确结束
            try:
                await self.send_json({"type": "stream_end"})
            except:
                pass
            
            # 【重要】清理可能不完整的状态，确保下次对话能正常进行
            try:
                await self._cleanup_after_stop(config)
            except Exception as cleanup_error:
                logger.warning(f"停止后清理状态失败: {cleanup_error}")
            
            # 发送 stopped 消息
            await self.send_json({"type": "stopped", "message": "已停止生成"})
        except Exception as e:
            logger.exception(f"Agent 调用失败: {e}")
            await self.send_json({
                "type": "error",
                "message": f"Agent 调用失败: {str(e)}"
            })
        finally:
            self.is_processing = False
            self.current_task = None
            self.should_stop = False

    async def _continue_processing(self):
        """
        继续处理（达到递归限制后用户选择继续）
        添加一条继续执行的消息，让 Agent 从中断处继续
        【重构】使用异步 astream 替代同步 stream + 后台线程
        """
        self.is_processing = True
        
        try:
            await self.send_json({"type": "processing", "message": "继续执行..."})
            
            app = await get_async_app()
            from langchain_core.messages import HumanMessage
            
            config = {
                "configurable": {
                    "thread_id": self.session_id,
                    "user": self.user,
                    "active_tools": self.active_tools
                },
                "recursion_limit": RECURSION_LIMIT  # 单次对话最大工具调用步数
            }
            
            # 先检查并清理不完整的工具调用
            await self._cleanup_incomplete_tool_calls(config)
            
            # 构建继续执行的输入消息
            continue_message = HumanMessage(content="继续执行上述任务，完成未完成的工作。")
            input_state = {"messages": [continue_message]}
            
            stream_started = False
            
            # 【重构】使用异步 astream
            try:
                logger.info(f"[Continue] 开始异步继续执行")
                chunk_count = 0
                
                async for output in app.astream(input_state, config):
                    if self.should_stop:
                        logger.info(f"[Continue] 检测到停止信号，中断处理")
                        break
                    
                    chunk_count += 1
                    
                    for node_name, node_output in output.items():
                        if self.should_stop:
                            break
                        
                        if isinstance(node_output, dict) and 'messages' in node_output:
                            for msg in node_output['messages']:
                                if self.should_stop:
                                    break
                                
                                # 处理 AIMessage 内容
                                if hasattr(msg, 'content') and msg.content:
                                    has_tool_calls = hasattr(msg, 'tool_calls') and msg.tool_calls
                                    if not has_tool_calls:
                                        if not stream_started:
                                            await self.send_json({"type": "stream_start"})
                                            stream_started = True
                                        await self.send_json({
                                            "type": "stream_chunk",
                                            "content": msg.content
                                        })
                                
                                # 处理工具调用
                                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                                    if stream_started:
                                        await self.send_json({"type": "stream_end"})
                                        stream_started = False
                                    for tc in msg.tool_calls:
                                        await self.send_json({
                                            "type": "tool_call",
                                            "name": tc.get("name", "unknown"),
                                            "args": tc.get("args", {})
                                        })
                                
                                # 处理 ToolMessage
                                if hasattr(msg, 'type') and getattr(msg, 'type', None) == 'tool':
                                    result_str = str(msg.content) if hasattr(msg, 'content') else str(msg)
                                    tool_name = msg.name if hasattr(msg, 'name') else "tool"
                                    # 根据工具名称确定需要刷新的数据类型
                                    refresh_types = self._get_refresh_types_for_tool(tool_name)
                                    await self.send_json({
                                        "type": "tool_result",
                                        "name": tool_name,
                                        "result": result_str,
                                        "refresh": refresh_types
                                    })
                    
                    # 让出控制权
                    await asyncio.sleep(0)
                
                logger.info(f"[Continue] 异步继续执行完成, 共 {chunk_count} 个 outputs")
                
            except asyncio.CancelledError:
                logger.info(f"[Continue] 异步继续执行被取消")
                raise
            except Exception as e:
                error_str = str(e)
                logger.exception(f"[Continue] 异步继续执行异常: {e}")
                
                if "Recursion limit" in error_str or "GraphRecursionError" in type(e).__name__:
                    logger.warning(f"继续执行时再次达到递归限制: {error_str}")
                    if stream_started:
                        await self.send_json({"type": "stream_end"})
                        stream_started = False
                    
                    await self.send_json({
                        "type": "recursion_limit",
                        "message": "工具调用次数再次达到上限，是否继续执行？"
                    })
                    return
                else:
                    raise
            
            # 确保流正确结束
            if stream_started:
                await self.send_json({"type": "stream_end"})
            
            # 获取最终消息数量
            final_message_count = 0
            try:
                final_state = await app.aget_state(config)
                if final_state and final_state.values:
                    final_messages = final_state.values.get("messages", [])
                    final_message_count = len(final_messages)
            except Exception as e:
                logger.warning(f"获取最终消息数量失败: {e}")
            
            if not self.should_stop:
                await self.send_json({
                    "type": "finished",
                    "message": "处理完成",
                    "message_count": final_message_count
                })
            
        except asyncio.CancelledError:
            logger.info(f"继续处理任务被取消")
            try:
                await self.send_json({"type": "stream_end"})
            except:
                pass
            
            # 【重要】清理可能不完整的状态
            try:
                await self._cleanup_after_stop(config)
            except Exception as cleanup_error:
                logger.warning(f"停止后清理状态失败: {cleanup_error}")
            
            await self.send_json({"type": "stopped", "message": "已停止生成"})
        except Exception as e:
            logger.exception(f"继续处理失败: {e}")
            await self.send_json({
                "type": "error",
                "message": f"继续处理失败: {str(e)}"
            })
        finally:
            self.is_processing = False
            self.current_task = None
            self.should_stop = False

    async def _cleanup_after_stop(self, config):
        """
        停止后清理状态
        确保 LangGraph 的状态是完整的，以便下次对话能正常进行
        主要处理：
        1. 如果最后一条是 AIMessage 带有 tool_calls 但没有对应的 ToolMessage，添加占位响应
        2. 如果最后一条是 HumanMessage，添加一条 AI 中断提示
        """
        app = await get_async_app()
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
        
        try:
            state = await app.aget_state(config)
            if not state or not state.values:
                logger.info("[Cleanup] 无状态需要清理")
                return
            
            messages = state.values.get("messages", [])
            if not messages:
                logger.info("[Cleanup] 无消息需要清理")
                return
            
            last_msg = messages[-1]
            logger.info(f"[Cleanup] 最后一条消息类型: {type(last_msg).__name__}")
            
            # 情况1: 最后是带有 tool_calls 的 AIMessage，需要添加占位工具响应
            if isinstance(last_msg, AIMessage) and hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
                logger.info(f"[Cleanup] 检测到不完整的工具调用，添加占位响应")
                fake_tool_messages = []
                for tc in last_msg.tool_calls:
                    tool_call_id = tc.get("id", "")
                    tool_name = tc.get("name", "unknown")
                    fake_tool_messages.append(
                        ToolMessage(
                            content=f"[操作被用户中断]",
                            tool_call_id=tool_call_id,
                            name=tool_name
                        )
                    )
                
                if fake_tool_messages:
                    await app.aupdate_state(
                        config, 
                        {"messages": fake_tool_messages}
                    )
                    logger.info(f"[Cleanup] 已添加 {len(fake_tool_messages)} 个占位工具响应")
                    
                    # 添加一条 AI 消息说明中断
                    interrupt_msg = AIMessage(content="[对话被用户中断]")
                    await app.aupdate_state(
                        config,
                        {"messages": [interrupt_msg]}
                    )
                    logger.info("[Cleanup] 已添加中断说明消息")
            
            # 情况2: 最后是 HumanMessage，说明 AI 还没来得及回复，添加中断说明
            elif isinstance(last_msg, HumanMessage):
                logger.info(f"[Cleanup] 检测到未完成的用户消息，添加中断说明")
                interrupt_msg = AIMessage(content="[对话被用户中断，AI 尚未回复]")
                await app.aupdate_state(
                    config,
                    {"messages": [interrupt_msg]}
                )
                logger.info("[Cleanup] 已添加中断说明消息")
            
            else:
                logger.info("[Cleanup] 状态完整，无需清理")
                    
        except Exception as e:
            logger.warning(f"[Cleanup] 停止后清理状态时出错: {e}")

    async def _cleanup_incomplete_tool_calls(self, config):
        """
        清理不完整的工具调用消息
        当递归限制中断时，可能存在 AIMessage 有 tool_calls 但没有对应的 ToolMessage
        """
        app = await get_async_app()
        from langchain_core.messages import AIMessage, ToolMessage
        
        try:
            state = await app.aget_state(config)
            if not state or not state.values:
                return
            
            messages = state.values.get("messages", [])
            if not messages:
                return
            
            last_msg = messages[-1]
            
            # 检查最后一条消息是否是带有 tool_calls 的 AIMessage
            if isinstance(last_msg, AIMessage) and hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
                logger.info(f"检测到不完整的工具调用，需要清理")
                
                # 为每个未完成的 tool_call 添加一个假的 ToolMessage
                fake_tool_messages = []
                for tc in last_msg.tool_calls:
                    tool_call_id = tc.get("id", "")
                    tool_name = tc.get("name", "unknown")
                    fake_tool_messages.append(
                        ToolMessage(
                            content=f"[工具调用被中断，未完成执行]",
                            tool_call_id=tool_call_id,
                            name=tool_name
                        )
                    )
                
                if fake_tool_messages:
                    # 更新状态添加假的工具响应
                    await app.aupdate_state(
                        config, 
                        {"messages": fake_tool_messages}
                    )
                    logger.info(f"已添加 {len(fake_tool_messages)} 个占位工具响应")
                    
        except Exception as e:
            logger.warning(f"清理不完整工具调用时出错: {e}")

    async def _init_graph(self):
        """初始化 Agent Graph"""
        self.graph = await get_async_app()
    
    def _get_refresh_types_for_tool(self, tool_name: str) -> list:
        """
        根据工具名称确定需要刷新的前端数据类型
        
        Args:
            tool_name: 工具名称
            
        Returns:
            需要刷新的数据类型列表 ['events', 'todos', 'reminders']
        """
        # 写入类工具（创建、更新、删除、完成）需要刷新对应的数据
        REFRESH_MAP = {
            # 创建/更新/删除项目 - 根据项目类型刷新
            'create_item': ['events', 'todos', 'reminders'],  # 无法预知类型，全部刷新
            'update_item': ['events', 'todos', 'reminders'],  # 无法预知类型，全部刷新
            'delete_item': ['events', 'todos', 'reminders'],  # 无法预知类型，全部刷新
            # 待办专用
            'complete_todo': ['todos'],
            # 事件组/分享组（可能影响日历显示）
            'get_event_groups': [],  # 只读
            'get_share_groups': [],  # 只读
            # 查询类工具 - 不刷新
            'search_items': [],
            'check_schedule_conflicts': [],
        }
        
        return REFRESH_MAP.get(tool_name, [])
    
    def _parse_query_string(self, query_string: str) -> dict:
        """解析 URL 查询参数"""
        from urllib.parse import unquote
        params = {}
        if query_string:
            for pair in query_string.split("&"):
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    # URL 解码参数值
                    params[key] = unquote(value)
        return params

    async def _auto_name_session(self, first_message: str):
        """
        自动为会话生成名称
        
        Args:
            first_message: 用户发的第一条消息
        """
        try:
            from agent_service.models import AgentSession
            from agent_service.agent_graph import get_user_llm
            from agent_service.context_optimizer import get_current_model_config, update_token_usage
            
            # 获取会话
            session = await database_sync_to_async(
                AgentSession.objects.filter(session_id=self.session_id).first
            )()
            
            if not session:
                logger.warning(f"[自动命名] 找不到会话: {self.session_id}")
                return
            
            # 检查是否已经自动命名过
            if session.is_auto_named:
                return
            
            logger.debug(f"[自动命名] 开始为会话命名: {self.session_id}")
            
            # 设置正在命名状态
            session.is_naming = True
            await database_sync_to_async(session.save)()
            
            # 获取当前模型 ID（用于 token 统计）
            current_model_id, _ = await database_sync_to_async(get_current_model_config)(self.user)
            
            # 通知前端开始命名
            await self.send_json({
                "type": "naming_start",
                "session_id": self.session_id,
                "message": "正在生成会话名称..."
            })
            
            try:
                # 获取用户的 LLM
                user_llm = await database_sync_to_async(get_user_llm)(self.user)
                
                # 构建命名提示词
                naming_prompt = f"""请根据以下用户消息，为这次对话起一个简短的名称（5-15个字符），直接返回名称，不要有任何额外的解释或标点符号。

用户消息: {first_message[:200]}

名称:"""
                
                # 调用 LLM 生成名称
                response = await asyncio.to_thread(
                    lambda: user_llm.invoke(naming_prompt)
                )
                
                # ===== Token 统计 =====
                if self.user and self.user.is_authenticated:
                    try:
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
                            logger.warning(f"[自动命名] 无法从 API 获取 Token 用量，降级为估算值")
                            if input_tokens == 0:
                                input_tokens = int(len(naming_prompt) / 2.5)  # 粗略估算
                            if output_tokens == 0:
                                output_tokens = 20  # 会话名称通常很短
                        
                        await database_sync_to_async(update_token_usage)(
                            self.user, input_tokens, output_tokens, current_model_id
                        )
                        logger.debug(f"[自动命名] Token 统计已更新: in={input_tokens}, out={output_tokens}")
                    except Exception as e:
                        logger.warning(f"[自动命名] Token 统计失败: {e}")
                
                # 提取生成的名称
                generated_name = response.content.strip() if hasattr(response, 'content') else str(response).strip()
                
                # 限制长度并清理
                generated_name = generated_name.replace('"', '').replace("'", '').strip()
                if len(generated_name) > 30:
                    generated_name = generated_name[:30] + "..."
                
                # 如果生成失败，使用默认名称
                if not generated_name or len(generated_name) < 2:
                    generated_name = first_message[:20] + ("..." if len(first_message) > 20 else "")
                
                logger.debug(f"[自动命名] 生成名称: {generated_name}")
                
                # 更新会话名称
                session.name = generated_name
                session.is_naming = False
                session.is_auto_named = True
                await database_sync_to_async(session.save)()
                
                # 通知前端命名完成
                await self.send_json({
                    "type": "naming_end",
                    "session_id": self.session_id,
                    "success": True,
                    "name": generated_name
                })
                
            except Exception as e:
                logger.error(f"[自动命名] 生成名称失败: {e}", exc_info=True)
                
                # 使用消息前缀作为备用名称
                fallback_name = first_message[:20] + ("..." if len(first_message) > 20 else "")
                session.name = fallback_name
                session.is_naming = False
                session.is_auto_named = True
                await database_sync_to_async(session.save)()
                
                await self.send_json({
                    "type": "naming_end",
                    "session_id": self.session_id,
                    "success": True,
                    "name": fallback_name,
                    "fallback": True
                })
                
        except Exception as e:
            logger.error(f"[自动命名] 失败: {e}", exc_info=True)
            # 出错时也要清除命名状态
            try:
                session = await database_sync_to_async(
                    AgentSession.objects.filter(session_id=self.session_id).first
                )()
                if session:
                    session.is_naming = False
                    await database_sync_to_async(session.save)()
            except:
                pass

    async def _update_last_message_preview(self, user_message: str):
        """
        更新会话的最后一条用户消息预览
        
        Args:
            user_message: 用户发送的消息内容
        """
        try:
            from agent_service.models import AgentSession
            
            session = await database_sync_to_async(
                AgentSession.objects.filter(session_id=self.session_id).first
            )()
            
            if session:
                # 截取预览（50个字符）
                preview = user_message[:50] + ("..." if len(user_message) > 50 else "")
                session.last_message_preview = preview
                await database_sync_to_async(session.save)()
                
        except Exception as e:
            logger.warning(f"[预览] 更新失败: {e}")

    async def _check_and_summarize(self, messages, config):
        """
        检查是否需要执行历史总结，如果需要则执行
        
        Args:
            messages: 当前所有消息
            config: Graph 配置
        """
        try:
            from agent_service.models import AgentSession
            from agent_service.context_summarizer import ConversationSummarizer
            from agent_service.context_optimizer import TokenCalculator, get_optimization_config
            from agent_service.agent_graph import get_user_llm, get_current_model_config
            
            session_id = config.get("configurable", {}).get("thread_id", "")
            if not session_id:
                return
            
            # 获取优化配置（添加详细日志）
            logger.debug(f"[总结] 开始获取优化配置, user={self.user}, user_id={self.user.id if self.user else 'None'}")
            opt_config = await database_sync_to_async(get_optimization_config)(self.user)
            logger.debug(f"[总结] 获取到的配置: {opt_config}")
            
            # 获取用户配置的 LLM（用于总结）
            user_llm = await database_sync_to_async(get_user_llm)(self.user)
            
            # 检查是否启用总结
            if not opt_config.get('enable_summarization', True):
                logger.debug("[总结] 总结功能已禁用")
                return
            
            min_messages = opt_config.get('min_messages_before_summary', 20)
            if not messages or len(messages) < min_messages:
                return
            
            # 获取会话
            session = await database_sync_to_async(
                AgentSession.objects.filter(session_id=session_id).first
            )()
            if not session:
                return
            
            # 获取现有总结
            summary_metadata = await database_sync_to_async(session.get_summary_metadata)()
            
            # Token 计算器
            calculator = TokenCalculator(
                method=opt_config.get('token_calculation_method', 'estimate')
            )
            
            # 获取模型上下文窗口和模型 ID
            current_model_id, model_config = await database_sync_to_async(get_current_model_config)(self.user)
            context_window = model_config.get('context_window', 128000) if model_config else 128000
            
            # 创建总结器（使用用户配置的 LLM）
            summarizer = ConversationSummarizer(
                llm=user_llm,
                token_calculator=calculator,
                context_window=context_window,
                target_usage_ratio=opt_config.get('target_usage_ratio', 0.6),
                summary_trigger_ratio=opt_config.get('summary_trigger_ratio', 0.5),
                min_messages_before_summary=min_messages,
                summary_token_ratio=opt_config.get('summary_token_ratio', 0.26),
                target_summary_tokens=opt_config.get('target_summary_tokens', 2000)
            )
            
            # 检查是否需要总结
            if not summarizer.should_summarize(messages, summary_metadata):
                return
            
            logger.info(f"[总结] 触发历史总结: session={session_id}, messages={len(messages)}")
            
            # 设置正在总结状态
            await database_sync_to_async(session.set_summarizing)(True)
            
            # 通知前端开始总结
            await self.send_json({
                "type": "summarizing_start",
                "message": "正在总结对话历史..."
            })
            
            try:
                # 计算需要总结的范围
                start_idx, end_idx = summarizer.calculate_summarize_range(messages, summary_metadata)
                messages_to_summarize = messages[start_idx:end_idx]
                
                # 获取之前的总结（用于增量更新）
                previous_summary = summary_metadata.get('summary', '') if summary_metadata else None
                
                # 执行总结（传递 user 用于 token 统计）
                new_summary_metadata = await summarizer.summarize(
                    messages_to_summarize,
                    previous_summary=previous_summary,
                    user=self.user,
                    model_id=current_model_id
                )
                
                if new_summary_metadata:
                    # 保存总结（包含真实的 input_tokens 和 tokens_source）
                    await database_sync_to_async(session.save_summary)(
                        summary_text=new_summary_metadata['summary'],
                        summarized_until=end_idx,
                        summary_tokens=new_summary_metadata['summary_tokens'],
                        summary_input_tokens=new_summary_metadata.get('summary_input_tokens', 0),
                        tokens_source=new_summary_metadata.get('tokens_source', 'estimated')
                    )
                    
                    tokens_source = new_summary_metadata.get('tokens_source', 'estimated')
                    summary_input_tokens = new_summary_metadata.get('summary_input_tokens', 0)
                    
                    logger.debug(
                        f"[总结] 完成: 总结了 {end_idx} 条消息, "
                        f"output={new_summary_metadata['summary_tokens']}t, "
                        f"input={summary_input_tokens}t, source={tokens_source}"
                    )
                    
                    # 通知前端总结完成
                    await self.send_json({
                        "type": "summarizing_end",
                        "success": True,
                        "summary": new_summary_metadata['summary'],
                        "summarized_until": end_idx,
                        "summary_tokens": new_summary_metadata['summary_tokens']
                    })
                else:
                    await database_sync_to_async(session.set_summarizing)(False)
                    await self.send_json({
                        "type": "summarizing_end",
                        "success": False,
                        "message": "总结生成失败"
                    })
                    
            except Exception as e:
                logger.error(f"[总结] 执行失败: {e}", exc_info=True)
                await database_sync_to_async(session.set_summarizing)(False)
                await self.send_json({
                    "type": "summarizing_end",
                    "success": False,
                    "message": f"总结失败: {str(e)}"
                })
                
        except Exception as e:
            logger.error(f"[总结] 检查失败: {e}", exc_info=True)


class AgentStreamConsumer(AgentConsumer):
    """
    支持流式输出的 Agent Consumer
    使用 LangGraph 的 stream 方法实现打字机效果
    """
    
    async def _process_message(self, content: str):
        """处理用户消息并流式输出"""
        self.is_processing = True
        
        try:
            await self.send_json({"type": "processing", "message": "正在思考..."})
            
            config = {
                "configurable": {
                    "thread_id": self.session_id,
                    "user": self.user
                }
            }
            
            input_state = {
                "messages": [HumanMessage(content=content)],
                "next": "",
                "active_experts": self.active_experts
            }
            
            # 使用流式输出
            full_response = ""
            async for event in self._stream_graph(input_state, config):
                event_type = event.get("type")
                
                if event_type == "token":
                    # 流式 token
                    token = event.get("content", "")
                    full_response += token
                    await self.send_json({
                        "type": "token",
                        "content": token
                    })
                    
                elif event_type == "tool_call":
                    # 工具调用通知
                    await self.send_json({
                        "type": "tool_call",
                        "name": event.get("name"),
                        "args": event.get("args", {})
                    })
                    
                elif event_type == "tool_result":
                    # 工具执行结果
                    await self.send_json({
                        "type": "tool_result",
                        "name": event.get("name"),
                        "result": event.get("result", "")
                    })
            
            # 发送完成信号
            await self.send_json({
                "type": "message",
                "content": full_response,
                "finished": True
            })
            
        except Exception as e:
            logger.exception(f"Agent 流式调用失败: {e}")
            await self.send_json({
                "type": "error",
                "message": f"Agent 调用失败: {str(e)}"
            })
        finally:
            self.is_processing = False
    
    async def _stream_graph(self, input_state, config):
        """
        流式调用 Graph
        注意: 这需要 graph 支持流式输出
        目前使用简化实现，后续可以扩展为真正的流式
        """
        # 简化实现：直接调用 invoke 然后返回完整响应
        result = await self._invoke_graph(input_state, config)
        
        if result and "messages" in result:
            for msg in reversed(result["messages"]):
                if isinstance(msg, AIMessage):
                    # 模拟流式输出（分块发送）
                    content = msg.content
                    chunk_size = 10  # 每次发送的字符数
                    
                    for i in range(0, len(content), chunk_size):
                        chunk = content[i:i+chunk_size]
                        yield {"type": "token", "content": chunk}
                        await asyncio.sleep(0.02)  # 模拟打字效果
                    break
