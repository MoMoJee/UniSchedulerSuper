"""
CalDAV Event Object 视图

处理 /caldav/<username>/<calendar_id>/<event_uid>.ics

支持：
- GET    — 获取单个事件的 iCalendar 表示（重复系列返回多 VEVENT）
- PUT    — 创建或更新事件（支持 iOS "仅此"/"此及以后" 编辑）
- DELETE — 删除事件
"""

import re
import uuid
import json
import datetime

from django.http import HttpResponse, HttpResponseForbidden, HttpResponseNotFound

from caldav_service.views.base import CalDAVView, MockRequest
from caldav_service.etag import compute_event_etag
from caldav_service.ical_builder import (
    build_single_event_ical, build_series_ical, get_event_uid,
    build_single_reminder_ical, get_reminder_uid,
)
from caldav_service.ical_parser import ical_to_all_event_dicts

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
            # 重复事件系列：返回主 VEVENT + 所有脱离实例
            detached = self.find_series_detached(user, calendar_id, item)
            if detached:
                ical_bytes = build_series_ical(item, detached)
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

        # 解析所有 VEVENT（主事件 + 例外实例）
        try:
            main_data, exceptions = ical_to_all_event_dicts(ical_text, existing_event=existing)
        except ValueError as e:
            logger.warning(f"CalDAV PUT parse error: {e}")
            return HttpResponse(f"Invalid iCalendar data: {e}", status=400)

        # 确定 groupID
        if calendar_id != 'default':
            main_data['groupID'] = calendar_id
        elif existing:
            main_data['groupID'] = existing.get('groupID', '')

        if existing:
            if exceptions:
                # iOS "仅此" 模式：PUT body 含主 VEVENT + RECURRENCE-ID 例外
                return self._handle_recurring_put(
                    user, existing, main_data, exceptions,
                    username, calendar_id, event_uid)
            else:
                # 普通更新（含 "此及以后" 的第一步：RRULE 截断）
                return self._handle_update(
                    user, existing, main_data,
                    username, calendar_id, event_uid)
        else:
            # 创建新事件（含 "此及以后" 的第二步：新系列）
            return self._handle_create(
                user, main_data, username, calendar_id, event_uid)

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
        """
        处理 PUT 更新已有事件。
        对于重复事件主事件的 RRULE 变更（如 UNTIL 截断），同步清理超出范围的实例。
        """
        event_id = existing['id']

        # 保存 caldav_uid（确保 CalDAV 客户端的 UID 往返一致）
        caldav_uid = new_data.get('caldav_uid')
        if caldav_uid and caldav_uid != existing.get('caldav_uid'):
            self._update_event_field(user, event_id, 'caldav_uid', caldav_uid)

        # 检测 RRULE 变更
        new_rrule = new_data.get('rrule', '')
        old_rrule = existing.get('rrule', '')
        is_main = existing.get('is_main_event', False)
        series_id = existing.get('series_id', '')
        rrule_changed = new_rrule and new_rrule != old_rrule

        # 如果是主事件的 RRULE 变更（"此及以后" 第一步：截断），
        # 需要直接操作数据库以同步清理实例
        if rrule_changed and is_main and series_id:
            self._handle_rrule_truncation(user, existing, new_data, new_rrule)
            # 构造更新参数（排除 rrule，已在上面处理）
            update_kwargs = {}
            for field in ('title', 'start', 'end', 'description', 'importance', 'urgency', 'groupID'):
                if field in new_data and new_data[field] != existing.get(field):
                    update_kwargs[field] = new_data[field]
            if update_kwargs:
                try:
                    EventService.update_event(user=user, event_id=event_id, **update_kwargs)
                except Exception as e:
                    logger.error(f"CalDAV PUT update (after rrule) failed: {e}")
        else:
            # 普通字段更新
            update_kwargs = {}
            for field in ('title', 'start', 'end', 'description', 'importance', 'urgency', 'groupID'):
                if field in new_data and new_data[field] != existing.get(field):
                    update_kwargs[field] = new_data[field]
            if 'location' in new_data and new_data['location'] != existing.get('location', ''):
                self._update_event_field(user, event_id, 'location', new_data['location'])
            if 'status' in new_data and new_data['status'] != existing.get('status', 'confirmed'):
                self._update_event_field(user, event_id, 'status', new_data['status'])

            if rrule_changed:
                update_kwargs['rrule'] = new_rrule

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
    # 重复事件 "仅此" 编辑
    # --------------------------------------------------

    def _handle_recurring_put(self, user, existing, main_data, exceptions,
                               username, calendar_id, event_uid):
        """
        处理 iOS "仅此"（single）编辑模式。

        iOS 发送的 PUT body 包含多个 VEVENT：
        - 主 VEVENT（含 RRULE，通常不变或微调）
        - 例外 VEVENT（含 RECURRENCE-ID，表示被修改的单个实例）

        处理逻辑：
        1. 更新主事件（RRULE 等可能有细微变化）
        2. 对每个例外 VEVENT：找到对应预生成实例 → 标记为 is_detached → 应用修改
        """
        import reversion

        series_id = existing.get('series_id', '')
        if not series_id:
            # 不是重复系列，不应有例外
            return self._handle_update(user, existing, main_data,
                                       username, calendar_id, event_uid)

        mock_request = MockRequest(user)

        try:
            with reversion.create_revision():
                reversion.set_user(user)
                reversion.set_comment(
                    f"CalDAV PUT single-instance edit: {main_data.get('title', '')}")

                user_events_data, _, _ = UserData.get_or_initialize(
                    mock_request, new_key="events", data=[])
                if not user_events_data:
                    return HttpResponse("Failed to access events data", status=500)

                events = user_events_data.get_value() or []
                if not isinstance(events, list):
                    events = []

                # 1. 更新主事件（RRULE 等属性）
                for event in events:
                    if event.get('id') == existing['id']:
                        for field in ('title', 'start', 'end', 'description',
                                      'location', 'status'):
                            if field in main_data:
                                event[field] = main_data[field]
                        if 'caldav_uid' in main_data:
                            event['caldav_uid'] = main_data['caldav_uid']
                        if main_data.get('rrule'):
                            event['rrule'] = main_data['rrule']
                        event['last_modified'] = datetime.datetime.now().strftime(
                            '%Y-%m-%d %H:%M:%S')
                        break

                # 2. 收集已有的脱离实例 recurrence_id（避免重复脱离）
                existing_detached_rids = set()
                for event in events:
                    if (event.get('is_detached')
                            and (event.get('series_id') == series_id
                                 or event.get('original_series_id') == series_id)):
                        rid = event.get('recurrence_id', '')
                        if rid:
                            existing_detached_rids.add(rid)

                # 3. 处理每个例外 VEVENT
                for exc in exceptions:
                    rec_id = exc.get('recurrence_id', '')
                    if not rec_id:
                        continue

                    # 已经有同 recurrence_id 的脱离实例 → 更新它
                    if rec_id in existing_detached_rids:
                        for event in events:
                            if (event.get('is_detached')
                                    and event.get('recurrence_id') == rec_id
                                    and (event.get('series_id') == series_id
                                         or event.get('original_series_id') == series_id)):
                                for field in ('title', 'start', 'end', 'description',
                                              'location', 'status'):
                                    if field in exc:
                                        event[field] = exc[field]
                                event['last_modified'] = datetime.datetime.now().strftime(
                                    '%Y-%m-%d %H:%M:%S')
                                break
                        continue

                    # 查找匹配的预生成实例
                    target_instance = None
                    for event in events:
                        if (event.get('series_id') == series_id
                                and event.get('recurrence_id') == rec_id
                                and not event.get('is_main_event', False)
                                and not event.get('is_detached', False)):
                            target_instance = event
                            break

                    # 获取主事件的 caldav_uid，传播给脱离实例
                    main_caldav_uid = existing.get('caldav_uid', '')

                    if target_instance:
                        # 脱离此实例
                        target_instance['is_detached'] = True
                        target_instance['is_exception'] = True
                        # 保留 series_id 以便 CalDAV UID 一致
                        if main_caldav_uid:
                            target_instance['caldav_uid'] = main_caldav_uid
                        for field in ('title', 'start', 'end', 'description',
                                      'location', 'status'):
                            if field in exc:
                                target_instance[field] = exc[field]
                        target_instance['last_modified'] = datetime.datetime.now().strftime(
                            '%Y-%m-%d %H:%M:%S')

                        logger.info(
                            f"[CalDAV] Detached instance rec_id={rec_id} "
                            f"from series {series_id}")
                    else:
                        # 实例不存在（超出预生成范围），创建新的脱离实例
                        new_instance = {
                            'id': str(uuid.uuid4()),
                            'series_id': series_id,
                            'is_recurring': True,
                            'is_main_event': False,
                            'is_detached': True,
                            'is_exception': True,
                            'recurrence_id': rec_id,
                            'groupID': existing.get('groupID', ''),
                            'status': 'confirmed',
                            'description': '',
                            'importance': '',
                            'urgency': '',
                            'ddl': '',
                            'tags': [],
                            'linked_reminders': [],
                            'shared_to_groups': [],
                            'last_modified': datetime.datetime.now().strftime(
                                '%Y-%m-%d %H:%M:%S'),
                        }
                        if main_caldav_uid:
                            new_instance['caldav_uid'] = main_caldav_uid
                        for field in ('title', 'start', 'end', 'description',
                                      'location', 'status'):
                            if field in exc:
                                new_instance[field] = exc[field]
                        events.append(new_instance)

                        logger.info(
                            f"[CalDAV] Created new detached instance rec_id={rec_id} "
                            f"for series {series_id}")

                user_events_data.set_value(events)

        except Exception as e:
            logger.error(f"CalDAV PUT recurring edit failed: {e}")
            return HttpResponse(f"Failed to update recurring event: {e}", status=500)

        # 返回
        updated_event = self._find_item(user, calendar_id, event_uid)
        etag = compute_event_etag(updated_event) if updated_event else ''

        resp = HttpResponse(status=204)
        if etag:
            resp['ETag'] = etag
        return resp

    # --------------------------------------------------
    # RRULE 截断辅助（"此及以后" 第一步）
    # --------------------------------------------------

    def _handle_rrule_truncation(self, user, main_event, new_data, new_rrule):
        """
        处理主事件 RRULE 变更（通常是 iOS "此及以后" 添加 UNTIL 截断）。
        更新主事件并清理超出新 RRULE 范围的预生成实例。
        """
        series_id = main_event['series_id']
        mock_request = MockRequest(user)

        user_events_data, _, _ = UserData.get_or_initialize(
            mock_request, new_key="events", data=[])
        if not user_events_data:
            return

        events = user_events_data.get_value() or []

        # 更新主事件的 rrule 和其他属性
        for event in events:
            if event.get('id') == main_event['id']:
                event['rrule'] = new_rrule
                for field in ('title', 'start', 'end', 'description',
                              'location', 'status'):
                    if field in new_data:
                        event[field] = new_data[field]
                if 'caldav_uid' in new_data:
                    event['caldav_uid'] = new_data['caldav_uid']
                event['last_modified'] = datetime.datetime.now().strftime(
                    '%Y-%m-%d %H:%M:%S')
                break

        # 更新所有同系列事件的 rrule（保持一致）
        for event in events:
            if (event.get('series_id') == series_id
                    and event.get('id') != main_event['id']
                    and not event.get('is_detached', False)):
                event['rrule'] = new_rrule
                event['last_modified'] = datetime.datetime.now().strftime(
                    '%Y-%m-%d %H:%M:%S')

        # 如果新 RRULE 含 UNTIL，移除超出范围的预生成实例
        until_match = re.search(r'UNTIL=(\d{8}T\d{6})', new_rrule)
        if until_match:
            until_str = until_match.group(1)
            until_dt = datetime.datetime.strptime(until_str, '%Y%m%dT%H%M%S')

            before_count = len(events)
            events = [
                e for e in events
                if not (
                    e.get('series_id') == series_id
                    and not e.get('is_main_event', False)
                    and not e.get('is_detached', False)
                    and e.get('start', '')
                    and datetime.datetime.fromisoformat(e['start']) > until_dt
                )
            ]
            removed = before_count - len(events)
            if removed:
                logger.info(
                    f"[CalDAV] RRULE truncation: removed {removed} instances "
                    f"beyond UNTIL={until_str} for series {series_id}")

        # 如果新 RRULE 含 COUNT，按 COUNT 限制实例数量
        count_match = re.search(r'COUNT=(\d+)', new_rrule)
        if count_match:
            max_count = int(count_match.group(1))
            # 按 start 排序同系列实例，只保留前 N 个
            series_instances = [
                e for e in events
                if (e.get('series_id') == series_id
                    and not e.get('is_main_event', False)
                    and not e.get('is_detached', False))
            ]
            series_instances.sort(key=lambda x: x.get('start', ''))
            # COUNT 包含主事件本身，所以实例最多 count-1 个
            if len(series_instances) >= max_count:
                to_remove = {
                    e['id'] for e in series_instances[max_count - 1:]
                }
                events = [e for e in events if e.get('id') not in to_remove]

        user_events_data.set_value(events)
        logger.info(f"[CalDAV] RRULE updated for series {series_id}: {new_rrule}")

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
            # CalDAV 删除一个 .ics 资源 = 删除整个系列（主事件 + 所有实例）
            if existing.get('is_main_event') and existing.get('series_id'):
                EventService.delete_event(
                    user=user, event_id=existing['id'], delete_scope='all')
            else:
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
        优先匹配 get_event_uid，其次匹配 caldav_uid 或 id（fallback）。
        """
        if self.is_reminder_calendar(calendar_id):
            items = self.get_events_for_calendar(user, calendar_id)
            for item in items:
                uid = get_reminder_uid(item)
                if uid == event_uid:
                    return item
            return None

        events = self.get_events_for_calendar(user, calendar_id)

        # 第一轮：精确匹配 get_event_uid
        for event in events:
            if not self.should_include_event(event):
                continue
            uid = get_event_uid(event)
            if uid == event_uid:
                return event

        # 第二轮：尝试匹配 caldav_uid 或 id（兼容 CalDAV 创建的重复事件）
        for event in events:
            if not self.should_include_event(event):
                continue
            if event.get('caldav_uid') == event_uid or event.get('id') == event_uid:
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
