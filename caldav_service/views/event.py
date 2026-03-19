"""
CalDAV Event Object 视图

处理 /caldav/<username>/<calendar_id>/<event_uid>.ics

支持：
- GET    — 获取单个事件的 iCalendar 表示
- PUT    — 创建或更新事件
- DELETE — 删除事件
"""

import uuid
import json
import datetime

from django.http import HttpResponse, HttpResponseForbidden, HttpResponseNotFound

from caldav_service.views.base import CalDAVView, MockRequest
from caldav_service.etag import compute_event_etag
from caldav_service.ical_builder import (
    build_single_event_ical, get_event_uid,
    build_single_reminder_ical, get_reminder_uid,
)
from caldav_service.ical_parser import ical_to_event_dict

from core.models import UserData
from core.services.event_service import EventService

from logger import logger

# PUT 请求体大小上限（512KB）
MAX_PUT_BODY_SIZE = 512 * 1024


class EventObjectView(CalDAVView):
    """
    /caldav/<username>/<calendar_id>/<event_uid>.ics

    单个日历对象资源。
    """

    # --------------------------------------------------
    # GET
    # --------------------------------------------------

    def get(self, request, username, calendar_id, event_uid):
        user, err = self.require_auth(request)
        if err:
            return err
        if user.username != username:
            return HttpResponseForbidden("Access denied.")

        item = self._find_item(user, calendar_id, event_uid)
        if item is None:
            return HttpResponseNotFound("Event not found.")

        if self.is_reminder_calendar(calendar_id):
            ical_bytes = build_single_reminder_ical(item)
        else:
            ical_bytes = build_single_event_ical(item)
        etag = compute_event_etag(item)

        resp = HttpResponse(ical_bytes, content_type='text/calendar; charset=utf-8')
        resp['ETag'] = etag
        return resp

    # --------------------------------------------------
    # PUT — 创建或更新
    # --------------------------------------------------

    def put(self, request, username, calendar_id, event_uid):
        user, err = self.require_auth(request)
        if err:
            return err
        if user.username != username:
            return HttpResponseForbidden("Access denied.")

        # 提醒日历为只读
        if self.is_reminder_calendar(calendar_id):
            return HttpResponse("Reminders calendar is read-only via CalDAV.", status=403)

        # 请求体大小检查
        if len(request.body) > MAX_PUT_BODY_SIZE:
            return HttpResponse("Request body too large.", status=413)

        ical_text = request.body

        # 判断是创建还是更新
        existing = self._find_item(user, calendar_id, event_uid)

        # If-Match 冲突检测
        if_match = request.META.get('HTTP_IF_MATCH', '').strip()
        if existing and if_match:
            current_etag = compute_event_etag(existing)
            if if_match != '*' and if_match != current_etag:
                return HttpResponse(status=412)  # Precondition Failed

        # If-None-Match: * → 客户端期望创建新资源（已存在则冲突）
        if_none_match = request.META.get('HTTP_IF_NONE_MATCH', '').strip()
        if if_none_match == '*' and existing:
            return HttpResponse(status=412)

        try:
            new_data = ical_to_event_dict(ical_text, existing_event=existing)
        except ValueError as e:
            logger.warning(f"CalDAV PUT parse error: {e}")
            return HttpResponse(f"Invalid iCalendar data: {e}", status=400)

        # 确定 groupID
        if calendar_id != 'default':
            new_data['groupID'] = calendar_id
        elif existing:
            new_data['groupID'] = existing.get('groupID', '')

        if existing:
            # === 更新 ===
            return self._handle_update(user, existing, new_data, username, calendar_id, event_uid)
        else:
            # === 创建 ===
            return self._handle_create(user, new_data, username, calendar_id, event_uid)

    def _handle_create(self, user, new_data, username, calendar_id, event_uid):
        """
        处理 PUT 创建新事件。

        直接写入 UserData 而非通过 EventService.create_event，
        因为需要控制事件 ID 以与 CalDAV URL UID 保持一致。
        """
        import reversion

        # 从 event_uid 提取内部 id：evt-{id} → {id}
        internal_id = event_uid
        if internal_id.startswith('evt-'):
            internal_id = internal_id[4:]

        new_data['id'] = internal_id
        new_data.setdefault('status', 'confirmed')
        new_data.setdefault('last_modified', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        new_data.setdefault('groupID', '')
        new_data.setdefault('description', '')
        new_data.setdefault('importance', '')
        new_data.setdefault('urgency', '')
        new_data.setdefault('ddl', '')
        new_data.setdefault('tags', [])
        new_data.setdefault('linked_reminders', [])
        new_data.setdefault('shared_to_groups', [])

        rrule = new_data.get('rrule', '')

        mock_request = MockRequest(user)

        try:
            with reversion.create_revision():
                reversion.set_user(user)
                reversion.set_comment(f"CalDAV PUT create: {new_data.get('title', '')}")

                user_events_data, _, _ = UserData.get_or_initialize(mock_request, new_key="events", data=[])
                if not user_events_data:
                    return HttpResponse("Failed to access events data", status=500)

                events = user_events_data.get_value() or []
                if not isinstance(events, list):
                    events = []

                # 防重复：如果已存在相同 id 的事件，先移除
                events = [e for e in events if e.get('id') != internal_id]

                if rrule:
                    # 使用 EventService 的 RRule 管理器处理重复事件
                    from core.views_events import EventsRRuleManager
                    manager = EventsRRuleManager(user)
                    event_data_for_rrule = {k: v for k, v in new_data.items() if k != 'rrule'}
                    main_event = manager.create_recurring_event(event_data_for_rrule, rrule)
                    # 重写 id 以保持 CalDAV UID 一致性
                    main_event['id'] = internal_id
                    events.append(main_event)
                    instances = manager.generate_event_instances(main_event, 180, 26)
                    events.extend(instances)
                else:
                    events.append(new_data)

                user_events_data.set_value(events)

        except Exception as e:
            logger.error(f"CalDAV PUT create failed: {e}")
            return HttpResponse(f"Failed to create event: {e}", status=500)

        etag = compute_event_etag(new_data)
        resp = HttpResponse(status=201)
        resp['Location'] = f'/caldav/{username}/{calendar_id}/{event_uid}.ics'
        resp['ETag'] = etag
        return resp

    def _handle_update(self, user, existing, new_data, username, calendar_id, event_uid):
        """处理 PUT 更新已有事件。"""
        event_id = existing['id']

        # 保存 caldav_uid（确保 CalDAV 客户端的 UID 往返一致）
        caldav_uid = new_data.get('caldav_uid')
        if caldav_uid and caldav_uid != existing.get('caldav_uid'):
            self._update_event_field(user, event_id, 'caldav_uid', caldav_uid)

        # 构造更新参数：只传有变化的字段
        update_kwargs = {}
        for field in ('title', 'start', 'end', 'description', 'importance', 'urgency', 'groupID'):
            if field in new_data and new_data[field] != existing.get(field):
                update_kwargs[field] = new_data[field]
        if 'location' in new_data and new_data['location'] != existing.get('location', ''):
            update_kwargs['description'] = new_data.get('description', existing.get('description', ''))
            # location 不是 EventService.update_event 的直接参数，需要直接写入
            self._update_event_field(user, event_id, 'location', new_data['location'])
        if 'status' in new_data and new_data['status'] != existing.get('status', 'confirmed'):
            self._update_event_field(user, event_id, 'status', new_data['status'])

        # 处理 rrule 变更
        rrule_val = new_data.get('rrule')
        if rrule_val and rrule_val != existing.get('rrule', ''):
            update_kwargs['rrule'] = rrule_val
        
        if update_kwargs:
            try:
                EventService.update_event(user=user, event_id=event_id, **update_kwargs)
            except Exception as e:
                logger.error(f"CalDAV PUT update failed: {e}")
                return HttpResponse(f"Failed to update event: {e}", status=500)

        # 重新计算 ETag
        updated_event = self._find_item(user, calendar_id, event_uid)
        etag = compute_event_etag(updated_event) if updated_event else ''

        resp = HttpResponse(status=204)
        if etag:
            resp['ETag'] = etag
        return resp

    # --------------------------------------------------
    # DELETE
    # --------------------------------------------------

    def delete(self, request, username, calendar_id, event_uid):
        user, err = self.require_auth(request)
        if err:
            return err
        if user.username != username:
            return HttpResponseForbidden("Access denied.")

        # 提醒日历为只读
        if self.is_reminder_calendar(calendar_id):
            return HttpResponse("Reminders calendar is read-only via CalDAV.", status=403)

        existing = self._find_item(user, calendar_id, event_uid)
        if existing is None:
            return HttpResponseNotFound("Event not found.")

        # If-Match 冲突检测
        if_match = request.META.get('HTTP_IF_MATCH', '').strip()
        if if_match and if_match != '*':
            current_etag = compute_event_etag(existing)
            if if_match != current_etag:
                return HttpResponse(status=412)

        try:
            EventService.delete_event(user=user, event_id=existing['id'])
        except Exception as e:
            logger.error(f"CalDAV DELETE failed: {e}")
            return HttpResponse(f"Failed to delete event: {e}", status=500)

        return HttpResponse(status=204)

    # --------------------------------------------------
    # 查找辅助
    # --------------------------------------------------

    def _find_item(self, user, calendar_id, event_uid):
        """
        根据 event_uid 在用户事件或提醒中查找匹配的项目。
        """
        if self.is_reminder_calendar(calendar_id):
            items = self.get_events_for_calendar(user, calendar_id)
            for item in items:
                uid = get_reminder_uid(item)
                if uid == event_uid:
                    return item
            return None

        events = self.get_events_for_calendar(user, calendar_id)
        for event in events:
            if not self.should_include_event(event):
                continue
            uid = get_event_uid(event)
            if uid == event_uid:
                return event
        return None

    def _update_event_field(self, user, event_id: str, field: str, value):
        """直接更新事件的某个字段（对于 EventService 不直接支持的字段）。"""
        mock_request = MockRequest(user)
        user_events_data, _, _ = UserData.get_or_initialize(mock_request, new_key="events", data=[])
        if not user_events_data:
            return

        events = user_events_data.get_value() or []
        for event in events:
            if event.get('id') == event_id:
                event[field] = value
                event['last_modified'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                break

        user_events_data.set_value(events)
