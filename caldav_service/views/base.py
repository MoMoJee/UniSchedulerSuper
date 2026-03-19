"""
CalDAV 视图基类

扩展 Django View 支持 WebDAV 方法 (PROPFIND, REPORT, MKCALENDAR 等)，
提供通用认证和响应辅助。
"""

import json

from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from caldav_service.auth import get_user_from_request
from caldav_service.xml_utils import serialize_xml
from core.models import UserData

from logger import logger


class MockRequest:
    """用于 Service 层调用的 mock request。"""
    def __init__(self, user):
        self.user = user
        self.is_authenticated = True


@method_decorator(csrf_exempt, name='dispatch')
class CalDAVView(View):
    """
    CalDAV 视图基类。
    - CSRF 豁免（CalDAV 客户端不会携带 CSRF Token）
    - 扩展 http_method_names 以支持 WebDAV 方法
    - 提供认证和公共辅助方法
    """

    http_method_names = [
        'get', 'put', 'delete', 'head', 'options',
        'propfind', 'proppatch', 'report', 'mkcalendar',
    ]

    def dispatch(self, request, *args, **kwargs):
        # 诊断日志：记录请求方法、路径和关键头
        auth_type = 'none'
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header:
            auth_type = auth_header.split(' ')[0] if ' ' in auth_header else 'unknown'
        logger.debug(
            f"[CalDAV] {request.method} {request.path} "
            f"Auth={auth_type} Depth={request.META.get('HTTP_DEPTH', '-')} "
            f"User-Agent={request.META.get('HTTP_USER_AGENT', '-')[:80]}"
        )

        method = request.method.lower()
        if method in self.http_method_names:
            handler = getattr(self, method, None)
            if handler:
                resp = handler(request, *args, **kwargs)
                # 所有 CalDAV 响应都要带 DAV 头，让客户端识别为 CalDAV 服务器
                resp['DAV'] = '1, 2, 3, calendar-access'
                return resp
        return self.http_method_not_allowed(request, *args, **kwargs)

    # =====================================================
    # 认证
    # =====================================================

    def authenticate(self, request):
        """
        认证请求，返回 User 或 None。
        """
        return get_user_from_request(request)

    def require_auth(self, request):
        """
        认证请求并返回 User。认证失败时返回 (None, HttpResponse 401)。
        """
        user = self.authenticate(request)
        if user is None:
            resp = HttpResponse("Unauthorized", status=401)
            resp['WWW-Authenticate'] = 'Basic realm="UniScheduler CalDAV"'
            return None, resp
        return user, None

    # =====================================================
    # 辅助
    # =====================================================

    def xml_response(self, root, status=207):
        """返回 XML 响应。"""
        body = serialize_xml(root)
        resp = HttpResponse(body, content_type="application/xml; charset=utf-8", status=status)
        return resp

    def options(self, request, *args, **kwargs):
        """所有 CalDAV 端点通用的 OPTIONS 响应。"""
        resp = HttpResponse(status=200)
        resp['Allow'] = 'OPTIONS, GET, HEAD, PUT, DELETE, PROPFIND, REPORT'
        resp['DAV'] = '1, 2, 3, calendar-access'
        return resp

    # =====================================================
    # 数据加载
    # =====================================================

    def load_events(self, user) -> list:
        """加载用户事件列表。"""
        try:
            data = UserData.objects.get(user=user, key="events")
            events = json.loads(data.value)
            return events if isinstance(events, list) else []
        except UserData.DoesNotExist:
            return []

    def load_events_groups(self, user) -> list:
        """加载用户日历分组列表。"""
        try:
            data = UserData.objects.get(user=user, key="events_groups")
            groups = json.loads(data.value)
            return groups if isinstance(groups, list) else []
        except UserData.DoesNotExist:
            return []

    def load_todos(self, user) -> list:
        """加载用户待办列表。"""
        try:
            data = UserData.objects.get(user=user, key="todos")
            todos = json.loads(data.value)
            return todos if isinstance(todos, list) else []
        except UserData.DoesNotExist:
            return []

    def load_reminders(self, user) -> list:
        """加载用户提醒列表。"""
        try:
            data = UserData.objects.get(user=user, key="reminders")
            reminders = json.loads(data.value)
            return reminders if isinstance(reminders, list) else []
        except UserData.DoesNotExist:
            return []

    def get_events_for_calendar(self, user, calendar_id: str) -> list:
        """
        获取指定日历（events_group）中的事件。
        calendar_id='default' 返回没有 groupID 或 groupID 不在已知组中的事件。
        calendar_id='reminders' 返回提醒列表（作为 VEVENT 暴露）。
        """
        if calendar_id == 'reminders':
            return self._get_reminders_as_events(user)
        events = self.load_events(user)
        if calendar_id == 'default':
            groups = self.load_events_groups(user)
            group_ids = {g.get('id') for g in groups if g.get('id')}
            return [
                e for e in events
                if not e.get('groupID') or e.get('groupID') not in group_ids
            ]
        return [e for e in events if e.get('groupID') == calendar_id]

    def _get_reminders_as_events(self, user) -> list:
        """获取应在 CalDAV 中展示的提醒列表。"""
        from caldav_service.ical_builder import should_include_reminder
        reminders = self.load_reminders(user)
        return [r for r in reminders if should_include_reminder(r)]

    def is_reminder_calendar(self, calendar_id: str) -> bool:
        """判断 calendar_id 是否为提醒日历。"""
        return calendar_id == 'reminders'

    def should_include_event(self, event: dict) -> bool:
        """
        判断事件是否应在 CalDAV 中暴露。
        只暴露主事件 + 脱离实例 + 普通非重复事件。
        """
        is_recurring = event.get("is_recurring", False)
        is_main_event = event.get("is_main_event", False)
        is_detached = event.get("is_detached", False)

        if is_detached:
            return True
        if is_recurring and not is_main_event:
            return False
        return True
