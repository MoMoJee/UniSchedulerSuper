"""
CalDAV Calendar Collection 视图

处理 /caldav/<username>/<calendar_id>/ — 日历集合

PROPFIND Depth:0 → 返回日历集合属性（displayname, ctag 等）
PROPFIND Depth:1 → 返回集合属性 + 枚举所有 .ics 事件资源（含 ETag）
REPORT → calendar-multiget / calendar-query
"""

import datetime
import xml.etree.ElementTree as ET
from typing import Optional

from django.http import HttpResponse, HttpResponseForbidden

from caldav_service.views.base import CalDAVView
from caldav_service.etag import compute_event_etag, compute_calendar_ctag
from caldav_service.ical_builder import (
    build_single_event_ical, build_series_ical, get_event_uid,
    build_single_reminder_ical, get_reminder_uid,
)
from caldav_service.xml_utils import (
    dav, caldav, cs, ical, NS_CALDAV,
    make_multistatus, add_response, add_propstat,
    get_prop, set_text_prop, parse_xml_body, get_local_name,
)
from core.views_calendar_subscription import _parse_dt
from logger import logger


class CalendarCollectionView(CalDAVView):
    """
    /caldav/<username>/<calendar_id>/

    处理该日历集合的 PROPFIND 和 REPORT。
    """

    # --------------------------------------------------
    # PROPFIND
    # --------------------------------------------------

    def propfind(self, request, username, calendar_id):
        user, err = self.require_auth(request)
        if err:
            return err
        if user.username != username:
            return HttpResponseForbidden("Access denied.")

        depth = request.META.get('HTTP_DEPTH', '1')
        events = self.get_events_for_calendar(user, calendar_id)

        multistatus = make_multistatus()

        # 集合自身
        self._add_collection_response(multistatus, user, username, calendar_id, events)

        # Depth:1 → 列举事件
        if depth != '0':
            is_rem = self.is_reminder_calendar(calendar_id)
            seen_uids = set()
            for item in events:
                if is_rem:
                    self._add_item_stub_response(multistatus, username, calendar_id, item, is_reminder=True)
                else:
                    if not self.should_include_event(item):
                        continue
                    uid = get_event_uid(item)
                    # 同一 UID 只输出一次（主事件 + 脱离实例共享 UID）
                    if uid in seen_uids:
                        continue
                    seen_uids.add(uid)
                    self._add_item_stub_response(multistatus, username, calendar_id, item, is_reminder=False)

        return self.xml_response(multistatus)

    def get(self, request, username, calendar_id):
        """GET on collection — 一些客户端可能尝试 GET。"""
        return self.propfind(request, username, calendar_id)

    # --------------------------------------------------
    # MKCALENDAR — 拒绝客户端创建日历（服务端管理）
    # --------------------------------------------------

    def mkcalendar(self, request, username, calendar_id):
        user, err = self.require_auth(request)
        if err:
            return err
        return HttpResponse(
            "Calendar creation is managed by the server.",
            status=403,
            content_type="text/plain",
        )

    # --------------------------------------------------
    # PROPPATCH — 接受属性修改请求（静默成功）
    # --------------------------------------------------

    def proppatch(self, request, username, calendar_id):
        user, err = self.require_auth(request)
        if err:
            return err
        if user.username != username:
            return HttpResponseForbidden("Access denied.")

        multistatus = make_multistatus()
        resp = add_response(multistatus, f'/caldav/{username}/{calendar_id}/')
        propstat = add_propstat(resp)
        prop = get_prop(propstat)

        # 解析请求体，为每个请求的属性返回成功
        body = request.body
        if body:
            try:
                root = parse_xml_body(body)
                for set_el in root.iter(dav("set")):
                    for prop_el in set_el.iter(dav("prop")):
                        for child in prop_el:
                            ET.SubElement(prop, child.tag)
            except Exception:
                pass  # 解析失败时返回空的 200 propstat

        return self.xml_response(multistatus)

    # --------------------------------------------------
    # REPORT
    # --------------------------------------------------

    def report(self, request, username, calendar_id):
        user, err = self.require_auth(request)
        if err:
            return err
        if user.username != username:
            return HttpResponseForbidden("Access denied.")

        body = request.body
        if not body:
            return HttpResponse(status=400)

        root = parse_xml_body(body)
        local_name = get_local_name(root.tag)

        if local_name == 'calendar-multiget':
            return self._handle_multiget(request, root, user, username, calendar_id)
        elif local_name == 'calendar-query':
            return self._handle_calendar_query(request, root, user, username, calendar_id)
        else:
            logger.warning(f"CalDAV REPORT: unsupported report type '{local_name}'")
            return HttpResponse(status=501)

    # --------------------------------------------------
    # calendar-multiget
    # --------------------------------------------------

    def _handle_multiget(self, request, root, user, username, calendar_id):
        """
        calendar-multiget: 客户端指定一批 href，批量返回 VEVENT 数据。
        对于重复事件系列，返回主 VEVENT + 所有脱离实例。
        """
        events = self.get_events_for_calendar(user, calendar_id)
        is_rem = self.is_reminder_calendar(calendar_id)

        # 构建 uid → item 索引（主事件优先）
        item_by_uid = {}
        for item in events:
            if is_rem:
                uid = get_reminder_uid(item)
                item_by_uid[uid] = item
            else:
                if self.should_include_event(item):
                    uid = get_event_uid(item)
                    # 优先存主事件
                    if uid not in item_by_uid or item.get('is_main_event'):
                        item_by_uid[uid] = item

        # 提取请求的 href 列表
        requested_hrefs = set()
        for href_el in root.iter(dav("href")):
            if href_el.text:
                requested_hrefs.add(href_el.text.strip())

        multistatus = make_multistatus()

        for href in requested_hrefs:
            # 从 href 中提取 uid: /caldav/user/cal/evt-xxx.ics → evt-xxx
            uid = href.rstrip('/').rsplit('/', 1)[-1]
            if uid.endswith('.ics'):
                uid = uid[:-4]

            item = item_by_uid.get(uid)
            if item:
                self._add_item_full_response(
                    multistatus, href, item, user, calendar_id, is_reminder=is_rem)
            else:
                # 404 for this href
                resp = add_response(multistatus, href)
                propstat = add_propstat(resp, status="HTTP/1.1 404 Not Found")

        return self.xml_response(multistatus)

    # --------------------------------------------------
    # calendar-query
    # --------------------------------------------------

    def _handle_calendar_query(self, request, root, user, username, calendar_id):
        """
        calendar-query: 服务端据条件过滤（主要是 time-range）。
        对于重复事件系列，返回主 VEVENT + 所有脱离实例。
        """
        events = self.get_events_for_calendar(user, calendar_id)
        is_rem = self.is_reminder_calendar(calendar_id)

        # 提取 time-range 参数（如果有）
        time_start, time_end = self._extract_time_range(root)

        multistatus = make_multistatus()
        seen_uids = set()

        for item in events:
            if is_rem:
                if time_start or time_end:
                    if not self._reminder_in_time_range(item, time_start, time_end):
                        continue
                uid = get_reminder_uid(item)
                href = f'/caldav/{username}/{calendar_id}/{uid}.ics'
                self._add_item_full_response(
                    multistatus, href, item, user, calendar_id, is_reminder=True)
            else:
                if not self.should_include_event(item):
                    continue
                if time_start or time_end:
                    if not self._event_in_time_range(item, time_start, time_end):
                        continue
                uid = get_event_uid(item)
                if uid in seen_uids:
                    continue
                seen_uids.add(uid)
                href = f'/caldav/{username}/{calendar_id}/{uid}.ics'
                self._add_item_full_response(
                    multistatus, href, item, user, calendar_id, is_reminder=False)

        return self.xml_response(multistatus)

    def _extract_time_range(self, root):
        """从 calendar-query XML 中提取 time-range 的 start/end。"""
        time_start = None
        time_end = None
        for tr in root.iter(caldav("time-range")):
            start_str = tr.get("start", "")
            end_str = tr.get("end", "")
            if start_str:
                time_start = self._parse_caldav_datetime(start_str)
            if end_str:
                time_end = self._parse_caldav_datetime(end_str)
        return time_start, time_end

    def _parse_caldav_datetime(self, val: str) -> Optional[datetime.datetime]:
        """解析 CalDAV time-range 格式（如 20260301T000000Z）。"""
        val = val.strip()
        try:
            if val.endswith('Z'):
                return datetime.datetime.strptime(val, "%Y%m%dT%H%M%SZ").replace(
                    tzinfo=datetime.timezone.utc)
            elif 'T' in val:
                return datetime.datetime.strptime(val, "%Y%m%dT%H%M%S")
            else:
                return datetime.datetime.strptime(val, "%Y%m%d")
        except (ValueError, TypeError):
            return None

    def _event_in_time_range(self, event: dict, time_start, time_end) -> bool:
        """判断事件是否在给定时间范围内（有重叠即算在内）。"""
        evt_start = _parse_dt(event.get("start", ""))
        evt_end = _parse_dt(event.get("end", ""))
        if not evt_start:
            return False
        if evt_end is None:
            evt_end = evt_start

        # 将 naive datetime 视为北京时间
        beijing = datetime.timezone(datetime.timedelta(hours=8))
        if evt_start.tzinfo is None:
            evt_start = evt_start.replace(tzinfo=beijing)
        if evt_end.tzinfo is None:
            evt_end = evt_end.replace(tzinfo=beijing)

        if time_start and evt_end < time_start:
            return False
        if time_end and evt_start > time_end:
            return False
        return True

    # --------------------------------------------------
    # 响应构建辅助
    # --------------------------------------------------

    def _add_collection_response(self, multistatus, user, username, calendar_id, events):
        """构造日历集合自身的 response。"""
        resp = add_response(multistatus, f'/caldav/{username}/{calendar_id}/')
        propstat = add_propstat(resp)
        prop = get_prop(propstat)

        # resourcetype
        rt = ET.SubElement(prop, dav("resourcetype"))
        ET.SubElement(rt, dav("collection"))
        ET.SubElement(rt, caldav("calendar"))

        # displayname
        display_name = self._get_calendar_display_name(user, calendar_id)
        set_text_prop(prop, dav("displayname"), display_name)

        # calendar-color
        color = self._get_calendar_color(user, calendar_id)
        set_text_prop(prop, ical("calendar-color"), color)

        # getctag
        ctag = compute_calendar_ctag(events)
        set_text_prop(prop, cs("getctag"), ctag)

        # supported-calendar-component-set
        sccs = ET.SubElement(prop, caldav("supported-calendar-component-set"))
        comp = ET.SubElement(sccs, caldav("comp"))
        comp.set("name", "VEVENT")

    def _add_item_stub_response(self, multistatus, username, calendar_id, item, is_reminder=False):
        """构造事件/提醒的 stub response（只有 href + getetag，无 calendar-data）。"""
        uid = get_reminder_uid(item) if is_reminder else get_event_uid(item)
        href = f'/caldav/{username}/{calendar_id}/{uid}.ics'

        resp = add_response(multistatus, href)
        propstat = add_propstat(resp)
        prop = get_prop(propstat)

        set_text_prop(prop, dav("getetag"), compute_event_etag(item))
        set_text_prop(prop, dav("getcontenttype"), "text/calendar; charset=utf-8")

        # resourcetype 为空（文件，非集合）
        ET.SubElement(prop, dav("resourcetype"))

    def _add_item_full_response(self, multistatus, href, item,
                                user=None, calendar_id=None, is_reminder=False):
        """构造事件/提醒的完整 response（含 calendar-data）。"""
        resp = add_response(multistatus, href)
        propstat = add_propstat(resp)
        prop = get_prop(propstat)

        set_text_prop(prop, dav("getetag"), compute_event_etag(item))
        set_text_prop(prop, dav("getcontenttype"), "text/calendar; charset=utf-8")

        # calendar-data
        if is_reminder:
            ical_bytes = build_single_reminder_ical(item)
        else:
            # 重复事件系列：包含主 VEVENT + 脱离实例
            detached = []
            if user and calendar_id and item.get('series_id') and item.get('is_main_event'):
                detached = self.find_series_detached(user, calendar_id, item)
            if detached:
                ical_bytes = build_series_ical(item, detached)
            else:
                ical_bytes = build_single_event_ical(item)
        set_text_prop(prop, caldav("calendar-data"), ical_bytes.decode('utf-8'))

        ET.SubElement(prop, dav("resourcetype"))

    def _get_calendar_display_name(self, user, calendar_id: str) -> str:
        """获取日历显示名称。"""
        if calendar_id == 'default':
            return 'UniScheduler'
        if calendar_id == 'reminders':
            return '提醒'
        groups = self.load_events_groups(user)
        for g in groups:
            if g.get('id') == calendar_id:
                return g.get('name', calendar_id)
        return calendar_id

    def _get_calendar_color(self, user, calendar_id: str) -> str:
        """获取日历颜色（Apple 8位 RGBA hex）。"""
        color = '#4A90E2'
        if calendar_id == 'reminders':
            color = '#FF6B6B'
        elif calendar_id != 'default':
            groups = self.load_events_groups(user)
            for g in groups:
                if g.get('id') == calendar_id:
                    color = g.get('color', '#888888')
                    break
        if len(color) == 7:
            color += 'FF'
        return color

    def _reminder_in_time_range(self, reminder: dict, time_start, time_end) -> bool:
        """判断提醒是否在给定时间范围内。"""
        trigger = _parse_dt(reminder.get("trigger_time", ""))
        if not trigger:
            return False
        beijing = datetime.timezone(datetime.timedelta(hours=8))
        if trigger.tzinfo is None:
            trigger = trigger.replace(tzinfo=beijing)
        if time_start and trigger < time_start:
            return False
        if time_end and trigger > time_end:
            return False
        return True
