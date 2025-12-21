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
from langchain_core.messages import HumanMessage, AIMessage
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
        self.active_experts: list = ['planner', 'chat']
        self.graph = None
        self.is_processing = False
    
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
        experts_param = params.get("active_experts", "planner,chat")
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
                
            elif msg_type == "message":
                # 用户消息
                content = data.get("content", "").strip()
                if not content:
                    await self.send_json({"type": "error", "message": "消息内容不能为空"})
                    return
                
                if self.is_processing:
                    await self.send_json({"type": "error", "message": "正在处理上一条消息，请稍候"})
                    return
                
                await self._process_message(content)
                
            else:
                await self.send_json({"type": "error", "message": f"未知消息类型: {msg_type}"})
                
        except json.JSONDecodeError:
            await self.send_json({"type": "error", "message": "无效的 JSON 格式"})
        except Exception as e:
            logger.exception(f"处理消息时出错: {e}")
            await self.send_json({"type": "error", "message": f"服务器错误: {str(e)}"})
    
    async def _process_message(self, content: str):
        """处理用户消息并调用 Agent"""
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
                "active_experts": self.active_experts
            }
            
            # 调用 Agent (使用流式输出)
            full_response = ""
            
            # 在同步环境中运行 graph
            result = await self._invoke_graph(input_state, config)
            
            if result and "messages" in result:
                # 获取最后一条 AI 消息
                for msg in reversed(result["messages"]):
                    if isinstance(msg, AIMessage):
                        full_response = msg.content
                        break
            
            # 发送完整响应
            await self.send_json({
                "type": "message",
                "content": full_response,
                "finished": True
            })
            
        except Exception as e:
            logger.exception(f"Agent 调用失败: {e}")
            await self.send_json({
                "type": "error",
                "message": f"Agent 调用失败: {str(e)}"
            })
        finally:
            self.is_processing = False
    
    @database_sync_to_async
    def _init_graph(self):
        """初始化 Agent Graph (同步方法的异步包装)"""
        from agent_service.agent_graph import app
        self.graph = app
    
    @sync_to_async
    def _invoke_graph(self, input_state, config):
        """调用 Agent Graph (同步方法的异步包装)"""
        if not self.graph:
            raise RuntimeError("Graph 未初始化")
        return self.graph.invoke(input_state, config)
    
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
