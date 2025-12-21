"""
Agent Service WebSocket 路由配置
"""
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # WebSocket 端点: ws://host/ws/agent/
    re_path(r'ws/agent/$', consumers.AgentConsumer.as_asgi()),
    
    # 流式输出版本: ws://host/ws/agent/stream/
    re_path(r'ws/agent/stream/$', consumers.AgentStreamConsumer.as_asgi()),
]
