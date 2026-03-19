"""
CalDAV Calendar Home 视图

处理 /caldav/<username>/ — 日历主目录

PROPFIND Depth:1 → 枚举该用户的所有日历集合
"""

import xml.etree.ElementTree as ET

from django.http import HttpResponseForbidden

from caldav_service.views.base import CalDAVView
from caldav_service.etag import compute_calendar_ctag
from caldav_service.xml_utils import (
    dav, caldav, cs, ical,
    make_multistatus, add_response, add_propstat,
    get_prop, set_text_prop,
)
from logger import logger


class CalendarHomeView(CalDAVView):
    """
    /caldav/<username>/ — 用户日历主目录

    PROPFIND Depth:0 → 返回目录自身属性
    PROPFIND Depth:1 → 返回目录自身 + 所有日历集合
    """

    def propfind(self, request, username):
        user, err = self.require_auth(request)
        if err:
            return err
        if user.username != username:
            return HttpResponseForbidden("Access denied.")

        depth = request.META.get('HTTP_DEPTH', '1')

        multistatus = make_multistatus()

        # 日历主目录本身
        self._add_home_response(multistatus, username)

        # Depth:1 → 列举所有日历集合
        if depth != '0':
            self._add_calendar_responses(multistatus, user, username)

        return self.xml_response(multistatus)

    def get(self, request, username):
        return self.propfind(request, username)

    def _add_home_response(self, multistatus, username):
        """添加日历主目录自身的 response。"""
        resp = add_response(multistatus, f'/caldav/{username}/')
        propstat = add_propstat(resp)
        prop = get_prop(propstat)

        # resourcetype = collection
        rt = ET.SubElement(prop, dav("resourcetype"))
        ET.SubElement(rt, dav("collection"))

        set_text_prop(prop, dav("displayname"), "UniScheduler")

        # current-user-principal
        cup = ET.SubElement(prop, dav("current-user-principal"))
        href = ET.SubElement(cup, dav("href"))
        href.text = f'/caldav/principals/{username}/'

    def _add_calendar_responses(self, multistatus, user, username):
        """为每个 events_group、默认日历和提醒日历各添加一个 response。"""
        all_events = self.load_events(user)
        groups = self.load_events_groups(user)
        reminders = self.load_reminders(user)

        # 收集所有有 group 的事件 ID
        group_ids = {g.get('id') for g in groups if g.get('id')}

        # 默认日历：只包含没有 groupID 或 groupID 不在任何已知组中的事件（避免重复）
        ungrouped_events = [
            e for e in all_events
            if not e.get('groupID') or e.get('groupID') not in group_ids
        ]
        self._add_single_calendar_response(
            multistatus, username,
            calendar_id='default',
            display_name='UniScheduler',
            color='#4A90E2',
            events=ungrouped_events,
        )

        # 各 events_group
        for group in groups:
            gid = group.get('id', '')
            if not gid:
                continue
            group_events = [e for e in all_events if e.get('groupID') == gid]
            self._add_single_calendar_response(
                multistatus, username,
                calendar_id=gid,
                display_name=group.get('name', gid),
                color=group.get('color', '#888888'),
                events=group_events,
            )

        # 提醒日历（提醒转为 VEVENT 暴露给 CalDAV 客户端）
        from caldav_service.ical_builder import should_include_reminder
        visible_reminders = [r for r in reminders if should_include_reminder(r)]
        if visible_reminders or True:  # 即使为空也展示此日历
            self._add_single_calendar_response(
                multistatus, username,
                calendar_id='reminders',
                display_name='提醒',
                color='#FF6B6B',
                events=visible_reminders,
            )

    def _add_single_calendar_response(self, multistatus, username, calendar_id,
                                       display_name, color, events):
        """为单个日历集合构造 <D:response>。"""
        resp = add_response(multistatus, f'/caldav/{username}/{calendar_id}/')
        propstat = add_propstat(resp)
        prop = get_prop(propstat)

        # resourcetype = collection + calendar
        rt = ET.SubElement(prop, dav("resourcetype"))
        ET.SubElement(rt, dav("collection"))
        ET.SubElement(rt, caldav("calendar"))

        # displayname
        set_text_prop(prop, dav("displayname"), display_name)

        # calendar-color (Apple extension)
        color_hex = color if color.startswith('#') else f'#{color}'
        # Apple Calendar 期望 8 位 RGBA
        if len(color_hex) == 7:
            color_hex += 'FF'
        set_text_prop(prop, ical("calendar-color"), color_hex)

        # getctag (Apple Calendar Server extension)
        ctag = compute_calendar_ctag(events)
        set_text_prop(prop, cs("getctag"), ctag)

        # supported-calendar-component-set
        sccs = ET.SubElement(prop, caldav("supported-calendar-component-set"))
        comp = ET.SubElement(sccs, caldav("comp"))
        comp.set("name", "VEVENT")

        # supported-report-set
        srs = ET.SubElement(prop, dav("supported-report-set"))
        for rname in ["calendar-multiget", "calendar-query"]:
            sr = ET.SubElement(srs, dav("supported-report"))
            r = ET.SubElement(sr, dav("report"))
            ET.SubElement(r, caldav(rname))
