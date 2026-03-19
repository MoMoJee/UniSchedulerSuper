"""
CalDAV WebDAV 方法路由中间件

拦截发往非 CalDAV 路径的 WebDAV 方法（PROPFIND/REPORT/PROPPATCH/MKCALENDAR），
将其重定向到 CalDAV 服务入口，解决以下问题：

1. iOS accountsd 发送 PROPFIND / 时被 CSRF 中间件拦截返回 403
2. iOS 探测 /principals/ 等路径返回 404
3. 其他客户端探测非标准路径

此中间件必须放在 CSRF 中间件之前。
"""

from django.http import HttpResponse
from logger import logger


# CalDAV 服务自己的路径前缀，不需要拦截
CALDAV_PREFIXES = ('/caldav/', '/caldav', '/.well-known/caldav')

# WebDAV 方法列表
WEBDAV_METHODS = {'PROPFIND', 'PROPPATCH', 'REPORT', 'MKCALENDAR', 'MKCOL'}


class CalDAVRoutingMiddleware:
    """
    拦截发往非 CalDAV 路径的 WebDAV 请求，返回 CalDAV 发现响应。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        method = request.method.upper()
        path = request.path

        # 只拦截 WebDAV 方法 且 不是已注册的 CalDAV 路径
        if method in WEBDAV_METHODS and not any(path.startswith(p) for p in CALDAV_PREFIXES):
            logger.debug(
                f"[CalDAV Routing] Intercepted {method} {path} → redirect to /caldav/"
            )
            resp = HttpResponse(status=301)
            resp['Location'] = '/caldav/'
            resp['DAV'] = '1, 2, 3, calendar-access'
            resp['WWW-Authenticate'] = 'Basic realm="UniScheduler CalDAV"'
            return resp

        return self.get_response(request)
