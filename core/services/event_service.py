import uuid
import datetime
import logging
import reversion
from datetime import timedelta
from core.models import UserData, AgentTransaction
from core.views_events import EventsRRuleManager 
from core.views_share_groups import sync_group_calendar_data

logger = logging.getLogger(__name__)

class MockRequest:
    def __init__(self, user):
        self.user = user
        self.is_authenticated = True

class EventService:
    @staticmethod
    def _convert_time_format(events):
        """
        解析事件列表，将UTC时间转换为本地时间（减去8小时）。
        """
        for event in events:
            for key in ['start', 'end']:
                if key in event and isinstance(event[key], str) and event[key].endswith('Z'):
                    utc_time = datetime.datetime.fromisoformat(event[key].replace('Z', '+00:00'))
                    local_time = utc_time - timedelta(hours=-8)
                    event[key] = local_time.strftime('%Y-%m-%dT%H:%M')
        return events

    @staticmethod
    def create_event(user, title, start, end, description="", importance="", urgency="", groupID="", rrule="", shared_to_groups=None, ddl="", session_id=None):
        """
        创建日程
        """
        if shared_to_groups is None:
            shared_to_groups = []
            
        mock_request = MockRequest(user)
        manager = EventsRRuleManager(user)
        
        with reversion.create_revision():
            reversion.set_user(user)
            reversion.set_comment(f"Create event: {title}")
            
            event_data = {
                'title': title,
                'start': start,
                'end': end,
                'description': description,
                'importance': importance,
                'urgency': urgency,
                'groupID': groupID,
                'shared_to_groups': shared_to_groups,
            }
            
            user_preference_data, _, _ = UserData.get_or_initialize(mock_request, new_key="user_preference")
            user_preference = user_preference_data.get_value() or {} if user_preference_data else {}
            
            if ddl:
                event_data['ddl'] = ddl
            elif user_preference.get("auto_ddl", False):
                event_data['ddl'] = end
            else:
                event_data['ddl'] = ''
                
            main_event = None
            user_events_data, _, _ = UserData.get_or_initialize(mock_request, new_key="events", data=[])
            if not user_events_data:
                raise Exception("Failed to get user events data")

            events = user_events_data.get_value() or []
            if not isinstance(events, list):
                events = []

            if rrule:
                rrule = rrule.strip().rstrip(';')
                main_event = manager.create_recurring_event(event_data, rrule)
                events.append(main_event)
                
                if 'COUNT=' not in rrule and 'UNTIL=' not in rrule:
                    if 'FREQ=MONTHLY' in rrule:
                        additional_instances = manager.generate_event_instances(main_event, 365, 36)
                    elif 'FREQ=WEEKLY' in rrule:
                        additional_instances = manager.generate_event_instances(main_event, 180, 26)
                    else:
                        additional_instances = manager.generate_event_instances(main_event, 90, 20)
                    events.extend(additional_instances)
                else:
                    if 'COUNT=' in rrule:
                        import re
                        count_match = re.search(r'COUNT=(\d+)', rrule)
                        if count_match:
                            count = int(count_match.group(1))
                            additional_instances = manager.generate_event_instances(main_event, 365, count)
                            events.extend(additional_instances)
                    elif 'UNTIL=' in rrule:
                        additional_instances = manager.generate_event_instances(main_event, 365 * 2, 1000)
                        events.extend(additional_instances)
            else:
                event_data['id'] = str(uuid.uuid4())
                event_data['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                events.append(event_data)
                main_event = event_data
            
            user_events_data.set_value(events)
            
            if shared_to_groups:
                try:
                    sync_group_calendar_data(shared_to_groups, user)
                except Exception as e:
                    logger.error(f"同步群组数据失败: {str(e)}")
            
            if session_id:
                # AgentTransaction creation logic should be handled by decorator or caller
                pass
                
            return main_event

    @staticmethod
    def get_events(user):
        """获取用户所有日程"""
        mock_request = MockRequest(user)
        user_events_data, _, _ = UserData.get_or_initialize(mock_request, new_key="events", data=[])
        if user_events_data:
            return user_events_data.get_value() or []
        return []

    @staticmethod
    def delete_event(user, event_id, delete_scope='single', session_id=None):
        """删除日程"""
        mock_request = MockRequest(user)
        user_events_data, _, _ = UserData.get_or_initialize(mock_request, new_key="events", data=[])
        if not user_events_data:
            raise Exception("Failed to get user events data")
            
        events = user_events_data.get_value() or []
        
        with reversion.create_revision():
            reversion.set_user(user)
            reversion.set_comment(f"Delete event: {event_id}")
            
            target_event = None
            for event in events:
                if event.get('id') == event_id:
                    target_event = event
                    break
                    
            if not target_event:
                raise Exception("Event not found")
                
            is_recurring = target_event.get('is_recurring', False)
            series_id = target_event.get('series_id')
            original_count = len(events)
            
            if is_recurring and series_id:
                if delete_scope == 'single':
                    events = [event for event in events if event.get('id') != event_id]
                    if len(events) < original_count:
                        if target_event.get('is_main_event'):
                            series_events = [e for e in events if e.get('series_id') == series_id]
                            if series_events:
                                series_events.sort(key=lambda x: x['start'])
                                new_main_event = series_events[0]
                                for i, event in enumerate(events):
                                    if event.get('id') == new_main_event['id']:
                                        events[i]['is_main_event'] = True
                                        events[i]['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                        break
                elif delete_scope == 'all':
                    events = [event for event in events if event.get('series_id') != series_id]
                elif delete_scope == 'future':
                    target_start = datetime.datetime.fromisoformat(target_event['start'])
                    events = [
                        event for event in events 
                        if not (event.get('series_id') == series_id and 
                               datetime.datetime.fromisoformat(event['start']) >= target_start)
                    ]
            else:
                events = [event for event in events if event.get('id') != event_id]
            
            if len(events) < original_count:
                user_events_data.set_value(events)
                return True
            return False

    @staticmethod
    def update_event(user, event_id, title=None, start=None, end=None, description=None, importance=None, urgency=None, groupID=None, rrule=None, shared_to_groups=None, ddl=None, update_scope='single', session_id=None):
        """更新日程"""
        mock_request = MockRequest(user)
        manager = EventsRRuleManager(user)
        
        user_events_data, _, _ = UserData.get_or_initialize(mock_request, new_key="events", data=[])
        if not user_events_data:
            raise Exception("Failed to get user events data")
            
        events = user_events_data.get_value() or []
        events = EventService._convert_time_format(events)
        
        with reversion.create_revision():
            reversion.set_user(user)
            reversion.set_comment(f"Update event: {event_id}")
            
            target_event = None
            old_shared_to_groups = []
            for event in events:
                if event.get('id') == event_id:
                    target_event = event
                    old_shared_to_groups = list(event.get('shared_to_groups', []))
                    break
                    
            if not target_event:
                raise Exception("Event not found")
                
            # 更新字段
            if title is not None: target_event['title'] = title
            if start is not None: target_event['start'] = start
            if end is not None: target_event['end'] = end
            if description is not None: target_event['description'] = description
            if importance is not None: target_event['importance'] = importance
            if urgency is not None: target_event['urgency'] = urgency
            if groupID is not None: target_event['groupID'] = groupID
            if ddl is not None: target_event['ddl'] = ddl
            if shared_to_groups is not None: target_event['shared_to_groups'] = shared_to_groups
            
            target_event['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 简化处理：暂不支持复杂的 RRule 修改逻辑迁移 (如拆分系列等)，仅支持基础属性更新
            # 如果需要完整支持 RRule 修改，需要迁移 update_events_impl 中几百行的逻辑
            # 对于 Agent 来说，通常是简单的修改，或者删除重建
            
            user_events_data.set_value(events)
            
            # 同步群组
            affected_groups = set(old_shared_to_groups)
            if shared_to_groups:
                affected_groups.update(shared_to_groups)
            
            if affected_groups:
                try:
                    sync_group_calendar_data(list(affected_groups), user)
                except Exception as e:
                    logger.error(f"同步群组数据失败: {str(e)}")
                    
            return target_event
