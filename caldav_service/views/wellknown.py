"""
/.well-known/caldav 入口

RFC 6764 要求 CalDAV 服务器在此路径提供服务发现入口。

返回 301 重定向到 /caldav/，但用 PROPFIND 时返回未认证的 DAV 发现响应，
以便 iOS 等客户端确认这是合法 CalDAV 服务器。
"""

import xml.etree.ElementTree as ET

from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from caldav_service.auth import get_user_from_request
from caldav_service.xml_utils import (
    dav, caldav, make_multistatus, add_response, add_propstat,
    get_prop, set_href_prop, serialize_xml,
)
from logger import logger


@method_decorator(csrf_exempt, name='dispatch')
class WellKnownCalDAVView(View):
    """
    /.well-known/caldav

    客户端的 CalDAV 服务发现入口。
    - 已认证 → 返回 current-user-principal 指向 /caldav/principals/{user}/
    - 未认证 → 返回最小 DAV 响应 + WWW-Authenticate，让客户端知道这是 CalDAV 服务器
    """

    http_method_names = ['get', 'head', 'options', 'propfind']

    def dispatch(self, request, *args, **kwargs):
        method = request.method.lower()
        if method == 'propfind':
            return self.propfind(request)
        if method in ('get', 'head'):
            return self.propfind(request)
        if method == 'options':
            resp = HttpResponse(status=200)
            resp['Allow'] = 'OPTIONS, GET, HEAD, PROPFIND'
            resp['DAV'] = '1, 2, 3, calendar-access'
            return resp
        return HttpResponse(status=405)

    def propfind(self, request):
        user = get_user_from_request(request)

        multistatus = make_multistatus()
        resp_el = add_response(multistatus, '/.well-known/caldav')
        propstat = add_propstat(resp_el)
        prop = get_prop(propstat)

        # resourcetype = collection
        rt = ET.SubElement(prop, dav("resourcetype"))
        ET.SubElement(rt, dav("collection"))

        if user:
            # 已认证：完整的 principal 发现
            set_href_prop(prop, dav("current-user-principal"), f'/caldav/principals/{user.username}/')
            logger.debug(f"[CalDAV] WellKnown: authenticated for {user.username}")
        else:
            # 未认证：返回最小有效 DAV 响应，并告知客户端需要认证
            cup = ET.SubElement(prop, dav("current-user-principal"))
            ET.SubElement(cup, dav("unauthenticated"))
            logger.debug("[CalDAV] WellKnown: unauthenticated discovery")

        body = serialize_xml(multistatus)
        http_resp = HttpResponse(body, content_type="application/xml; charset=utf-8", status=207)
        http_resp['DAV'] = '1, 2, 3, calendar-access'
        if not user:
            http_resp['WWW-Authenticate'] = 'Basic realm="UniScheduler CalDAV"'
        return http_resp


wellknown_caldav_view = WellKnownCalDAVView.as_view()
