"""
CalDAV Principal 视图

处理：
- /caldav/ — 服务根，返回 current-user-principal
- /caldav/principals/<username>/ — 主体资源，返回 calendar-home-set
"""

import xml.etree.ElementTree as ET

from caldav_service.views.base import CalDAVView
from caldav_service.xml_utils import (
    dav, caldav, make_multistatus, add_response, add_propstat,
    get_prop, set_text_prop, set_href_prop,
)
from logger import logger


class ServiceRootView(CalDAVView):
    """
    /caldav/ — CalDAV 服务根

    PROPFIND:
    - 已认证 → 207 返回 current-user-principal
    - 未认证 → 401 + WWW-Authenticate + DAV 头，让客户端重试带凭据
    """

    def propfind(self, request):
        user, err = self.require_auth(request)
        if err:
            return err

        multistatus = make_multistatus()
        resp = add_response(multistatus, '/caldav/')
        propstat = add_propstat(resp)
        prop = get_prop(propstat)

        # resourcetype = collection
        rt = ET.SubElement(prop, dav("resourcetype"))
        ET.SubElement(rt, dav("collection"))

        # current-user-principal
        set_href_prop(prop, dav("current-user-principal"), f'/caldav/principals/{user.username}/')

        # principal-URL (一些客户端请求这个)
        set_href_prop(prop, dav("principal-URL"), f'/caldav/principals/{user.username}/')

        logger.debug(f"[CalDAV] ServiceRoot: authenticated response for {user.username}")
        return self.xml_response(multistatus)

    def get(self, request):
        """GET /caldav/ — 简单的信息响应。"""
        return self.propfind(request)


class PrincipalView(CalDAVView):
    """
    /caldav/principals/<username>/ — 用户主体资源

    PROPFIND → 返回 calendar-home-set，告知客户端日历所在位置。
    """

    def propfind(self, request, username):
        user, err = self.require_auth(request)
        if err:
            return err

        # 只允许访问自己的 principal
        if user.username != username:
            return self._forbidden()

        multistatus = make_multistatus()
        resp = add_response(multistatus, f'/caldav/principals/{username}/')
        propstat = add_propstat(resp)
        prop = get_prop(propstat)

        # displayname
        set_text_prop(prop, dav("displayname"), username)

        # resourcetype = principal
        rt = ET.SubElement(prop, dav("resourcetype"))
        ET.SubElement(rt, dav("collection"))
        ET.SubElement(rt, dav("principal"))

        # calendar-home-set
        set_href_prop(prop, caldav("calendar-home-set"), f'/caldav/{username}/')

        # principal-URL
        set_href_prop(prop, dav("principal-URL"), f'/caldav/principals/{username}/')

        # current-user-principal
        set_href_prop(prop, dav("current-user-principal"), f'/caldav/principals/{username}/')

        # supported-report-set
        srs = ET.SubElement(prop, dav("supported-report-set"))
        for report_name in ["calendar-multiget", "calendar-query"]:
            sr = ET.SubElement(srs, dav("supported-report"))
            r = ET.SubElement(sr, dav("report"))
            ET.SubElement(r, caldav(report_name))

        return self.xml_response(multistatus)

    def get(self, request, username):
        return self.propfind(request, username)

    def _forbidden(self):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Access denied: cannot access another user's principal.")
