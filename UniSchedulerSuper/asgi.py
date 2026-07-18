"""
ASGI config for UniSchedulerSuper project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/asgi/
"""

import os

from django.conf import settings
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'UniSchedulerSuper.settings')

# 初始化 Django ASGI application 先于导入路由
django_asgi_app = get_asgi_application()

# Daphne does not serve static assets by itself.  Keep the development ASGI
# entrypoint self-contained so the same server can exercise both the React
# bundle and Channels WebSockets.  Production remains unchanged: DEBUG is off
# and nginx serves /static/ directly.
http_application = (
    ASGIStaticFilesHandler(django_asgi_app) if settings.DEBUG else django_asgi_app
)

# 在 Django 初始化后导入路由
from agent_service.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    # HTTP 请求由 Django 处理
    "http": http_application,
    
    # WebSocket 请求由 Channels 处理
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        )
    ),
})
