"""
Agent WebSocket Consumer
处理与 Agent 的实时通信
"""
import json
import asyncio
import logging
from typing import Optional
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from asgiref.sync import sync_to_async
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk, ToolMessage
from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

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
        self.active_experts: list = ['planner', 'map', 'chat']  # 默认启用所有专家
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
        experts_param = params.get("active_experts", "planner,map,chat")
        self.active_experts = [e.strip() for e in experts_param.split(",") if e.strip()]
        
        logger.info(f"用户 {self.user.username} 连接 WebSocket, session={self.session_id}, experts={self.active_experts}")
        
        # 3. 初始化 Agent Graph
        await self._init_graph()
        
        # 4. 接受连接
        await self.accept()
        
        # 5. 发送欢迎消息
        await self.send_json({
            "type": "connected",
            "session_id": self.session_id,
            "active_experts": self.active_experts,
            "message": f"欢迎, {self.user.username}!"
        })
    
    async def disconnect(self, close_code):
        """处理 WebSocket 断开"""
        logger.info(f"用户 {self.user.username if self.user else 'unknown'} 断开 WebSocket, code={close_code}")
    
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
                    await self.send_json({"type": "stopped", "message": "已停止生成"})
                else:
                    await self.send_json({"type": "info", "message": "当前没有正在处理的消息"})
                
            elif msg_type == "message":
                # 用户消息
                content = data.get("content", "").strip()
                if not content:
                    await self.send_json({"type": "error", "message": "消息内容不能为空"})
                    return
                
                if self.is_processing:
                    await self.send_json({"type": "error", "message": "正在处理上一条消息，请稍候"})
                    return
                
                # 重置停止标志
                self.should_stop = False
                # 创建任务并运行
                self.current_task = asyncio.create_task(self._process_message(content))
                
            else:
                await self.send_json({"type": "error", "message": f"未知消息类型: {msg_type}"})
                
        except json.JSONDecodeError:
            await self.send_json({"type": "error", "message": "无效的 JSON 格式"})
        except Exception as e:
            logger.exception(f"处理消息时出错: {e}")
            await self.send_json({"type": "error", "message": f"服务器错误: {str(e)}"})
    
    async def _process_message(self, content: str):
        """
        处理用户消息并真正流式输出
        使用 stream_mode="messages" 获取 token 级别的流式输出
        """
        self.is_processing = True
        
        try:
            # 通知开始处理
            await self.send_json({"type": "processing", "message": "正在思考..."})
            
            # 准备配置
            config = {
                "configurable": {
                    "thread_id": self.session_id,
                    "user": self.user
                }
            }
            
            # 准备输入
            input_state = {
                "messages": [HumanMessage(content=content)],
                "next": "",
                "active_experts": self.active_experts,
                "current_agent": ""
            }
            
            # 导入 graph
            from agent_service.agent_graph import app
            
            # 使用 queue 在线程和异步代码之间传递事件
            import queue
            import threading
            
            event_queue = queue.Queue()
            
            def run_stream():
                """
                在后台线程中运行同步的 stream
                使用默认 stream 模式获取节点级别的输出
                """
                try:
                    print(f"[Stream] 开始流式处理, input_state keys={input_state.keys()}")
                    chunk_count = 0
                    
                    # 使用默认 stream 模式 (返回 state updates)
                    for output in app.stream(input_state, config):
                        chunk_count += 1
                        print(f"[Stream] chunk #{chunk_count}: output_type={type(output)}")
                        
                        # output 是一个字典，key 是节点名称，value 是该节点的输出
                        for node_name, node_output in output.items():
                            print(f"[Stream]   node={node_name}, output_type={type(node_output)}")
                            
                            # 检查是否有 messages
                            if isinstance(node_output, dict) and 'messages' in node_output:
                                for msg in node_output['messages']:
                                    print(f"[Stream]     msg_type={type(msg).__name__}")
                                    if hasattr(msg, 'content'):
                                        print(f"[Stream]     content={msg.content[:100] if msg.content else 'empty'}...")
                                    if hasattr(msg, 'tool_calls') and msg.tool_calls:
                                        print(f"[Stream]     tool_calls={msg.tool_calls}")
                                    
                                    # 把消息放入队列
                                    event_queue.put(("message", (node_name, msg)))
                            
                        if self.should_stop:
                            event_queue.put(("stop", None))
                            break
                            
                    print(f"[Stream] 流式处理完成, 共 {chunk_count} 个 outputs")
                    event_queue.put(("done", None))
                except Exception as e:
                    import traceback
                    print(f"[Stream] 流式处理异常: {e}")
                    traceback.print_exc()
                    event_queue.put(("error", f"{str(e)}\n{traceback.format_exc()}"))
            
            # 启动后台线程
            thread = threading.Thread(target=run_stream, daemon=True)
            thread.start()
            
            # 流式输出状态
            stream_started = False
            current_tool_calls = {}  # 追踪工具调用
            
            # 异步消费队列
            while True:
                if self.should_stop:
                    if stream_started:
                        await self.send_json({"type": "stream_end"})
                    break
                
                try:
                    # 非阻塞检查队列
                    item_type, item = event_queue.get_nowait()
                    
                    if item_type == "done" or item_type == "stop":
                        # 确保流结束
                        if stream_started:
                            await self.send_json({"type": "stream_end"})
                            stream_started = False
                        break
                    elif item_type == "error":
                        raise Exception(item)
                    elif item_type == "message":
                        # 新格式: (node_name, msg)
                        node_name, msg = item
                        
                        print(f"[Process] Processing message from node={node_name}, msg_type={type(msg).__name__}")
                        
                        # 处理 AIMessage 的内容
                        if hasattr(msg, 'content') and msg.content:
                            print(f"[Process] content present: {msg.content[:50]}...")
                            
                            # 检查是否有工具调用（如果有工具调用，content 可能是工具调用的中间状态）
                            has_tool_calls = hasattr(msg, 'tool_calls') and msg.tool_calls
                            
                            if not has_tool_calls:
                                # 没有工具调用，显示内容
                                if not stream_started:
                                    await self.send_json({"type": "stream_start"})
                                    stream_started = True
                                await self.send_json({
                                    "type": "stream_chunk",
                                    "content": msg.content
                                })
                        
                        # 处理工具调用
                        if hasattr(msg, 'tool_calls') and msg.tool_calls:
                            print(f"[Process] tool_calls present: {msg.tool_calls}")
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
                            await self.send_json({
                                "type": "tool_result",
                                "name": msg.name if hasattr(msg, 'name') else "tool",
                                "result": result_str[:200] + "..." if len(result_str) > 200 else result_str
                            })
                        
                except queue.Empty:
                    await asyncio.sleep(0.01)  # 更短的等待时间以提高响应速度
            
            # 等待线程结束
            thread.join(timeout=2.0)
            
            # 确保流正确结束
            if stream_started:
                await self.send_json({"type": "stream_end"})
            
            # 发送完成信号
            if not self.should_stop:
                await self.send_json({
                    "type": "finished",
                    "message": "处理完成"
                })
            
        except asyncio.CancelledError:
            logger.info(f"消息处理任务被取消")
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
    async def _init_graph(self):
        """初始化 Agent Graph"""
        from agent_service.agent_graph import app
        self.graph = app
    
    async def send_json(self, data: dict):
        """发送 JSON 数据"""
        await self.send(text_data=json.dumps(data, ensure_ascii=False))
    
    def _parse_query_string(self, query_string: str) -> dict:
        """解析 URL 查询参数"""
        params = {}
        if query_string:
            for pair in query_string.split("&"):
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    params[key] = value
        return params


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
