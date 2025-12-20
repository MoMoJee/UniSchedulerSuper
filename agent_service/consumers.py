import json
from channels.generic.websocket import AsyncWebsocketConsumer
from langchain_core.messages import HumanMessage
from .graph import app

class AgentConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # 简单鉴权：检查用户是否登录
        if self.scope["user"].is_anonymous:
            await self.close()
        else:
            await self.accept()

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            user_input = data.get("message")
            user = self.scope["user"]
            
            if not user_input:
                return

            # 初始化状态
            initial_state = {
                "messages": [HumanMessage(content=user_input)],
                "user_id": user.id
            }

            # 运行 LangGraph
            # 使用 astream_events 获取详细的流式事件
            async for event in app.astream_events(initial_state, version="v1"):
                kind = event["event"]
                
                # 1. LLM 开始流式输出 (思考过程/Token)
                if kind == "on_chat_model_stream":
                    content = event["data"]["chunk"].content
                    if content:
                        await self.send(json.dumps({
                            "type": "token",
                            "content": content
                        }))
                
                # 2. 工具开始调用
                elif kind == "on_tool_start":
                    await self.send(json.dumps({
                        "type": "thought",
                        "content": f"正在调用工具: {event['name']}..."
                    }))
                    
                # 3. 工具调用结束
                elif kind == "on_tool_end":
                    output = event['data'].get('output')
                    # 截断过长的输出
                    if len(str(output)) > 100:
                        output = str(output)[:100] + "..."
                    
                    await self.send(json.dumps({
                        "type": "thought",
                        "content": f"工具调用完成: {output}"
                    }))

                # 4. 整个链结束 (最终回复通常在 on_chat_model_stream 中已经流式传输完了，
                # 但这里可以作为一个结束信号，或者处理非流式的最终状态)
                elif kind == "on_chain_end" and event["name"] == "LangGraph":
                    pass
                    
            # 发送结束信号
            await self.send(json.dumps({
                "type": "done"
            }))
            
        except Exception as e:
            await self.send(json.dumps({
                "type": "error",
                "content": str(e)
            }))
