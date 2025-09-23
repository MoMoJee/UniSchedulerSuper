"""
Events管理模块 - 支持RRule重复事件
"""

import json
import uuid
import datetime
import re
from datetime import timedelta
from typing import List, Dict, Any, Optional

from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt

from core.models import UserData
from integrated_reminder_manager import IntegratedReminderManager, UserDataStorageBackend
from rrule_engine import RRuleEngine
from logger import logger


class EventsRRuleManager(IntegratedReminderManager):
    """Events专用的RRule管理器 - 继承并适配提醒管理器"""
    
    def __init__(self, user_or_request):
        # 自动包裹MockRequest，确保有is_authenticated属性
        from django.http import HttpRequest
        class MockRequest:
            def __init__(self, user):
                self.user = user
                self.is_authenticated = True
        if hasattr(user_or_request, 'is_authenticated') and not isinstance(user_or_request, HttpRequest):
            # 传入的是user对象
            mock_request = MockRequest(user_or_request)
        elif hasattr(user_or_request, 'user'):
            # 传入的是request对象
            mock_request = MockRequest(user_or_request.user)
        else:
            # 兜底
            mock_request = MockRequest(user_or_request)
        super().__init__(mock_request)
        # 重新配置RRule引擎使用Events专用的存储键
        self.storage_backend = UserDataStorageBackend(mock_request)
        self.storage_backend.storage_key = "events_rrule_series"
        # 重新初始化RRule引擎使用新的存储后端
        self.rrule_engine = RRuleEngine(self.storage_backend)
    
    def create_recurring_event(self, event_data: Dict[str, Any], rrule: str) -> Dict[str, Any]:
        """创建重复事件 - 基于提醒的实现但适配事件数据结构"""
        try:
            # 安全解析开始时间
            def parse_datetime_safe(time_str):
                """安全解析datetime字符串，确保返回naive datetime"""
                if not time_str:
                    return datetime.datetime.now()
                
                # 规范化时间字符串
                if 'T' in time_str:
                    # 移除可能的时区信息
                    if time_str.endswith('Z'):
                        time_str = time_str[:-1]
                    elif '+' in time_str or time_str.count('-') > 2:
                        # 移除时区偏移
                        if '+' in time_str:
                            time_str = time_str.split('+')[0]
                        else:
                            # 处理负时区偏移
                            parts = time_str.split('-')
                            if len(parts) > 3:  # YYYY-MM-DDTHH:MM:SS-offset
                                time_str = '-'.join(parts[:3])
                    
                    # 如果没有秒，添加:00
                    if time_str.count(':') == 1:
                        time_str += ':00'
                
                return datetime.datetime.fromisoformat(time_str)
            
            # 解析开始时间
            start_time = parse_datetime_safe(event_data['start'])
            
            # 判断是否为复杂重复模式，需要查找下一个符合条件的时间点
            needs_next_occurrence = self._is_complex_rrule(rrule)
            # 检查是否包含多个BYDAY值
            has_multiple_byday = self._has_multiple_byday_values(rrule)
            logger.info(f"Event RRule: {rrule}, is_complex: {needs_next_occurrence}, has_multiple_byday: {has_multiple_byday}, start_time: {start_time}")
            
            if needs_next_occurrence and not has_multiple_byday:
                # 对于复杂重复模式但只有单个BYDAY值的情况，查找下一个符合条件的时间点
                actual_start_time = self._find_next_occurrence(rrule, start_time)
                logger.info(f"Found next occurrence: {actual_start_time}")
                if actual_start_time:
                    # 使用找到的时间点，但保留原始时间的时分秒
                    original_hour = start_time.hour
                    original_minute = start_time.minute
                    original_second = start_time.second
                    actual_start_time = actual_start_time.replace(
                        hour=original_hour,
                        minute=original_minute,
                        second=original_second,
                        microsecond=start_time.microsecond
                    )
                    logger.info(f"Adjusted start time from {start_time} to {actual_start_time} (preserved time {original_hour}:{original_minute}:{original_second})")
                else:
                    # 如果找不到符合条件的时间点，使用原始时间
                    actual_start_time = start_time
                    logger.warning(f"No valid occurrence found, using original time: {actual_start_time}")
            else:
                # 对于简单重复模式或多BYDAY值模式，直接使用用户输入的时间
                # 多BYDAY值（如BYDAY=WE,FR）应该让RRule引擎自动处理多个日期
                actual_start_time = start_time
                reason = "multiple BYDAY values" if has_multiple_byday else "simple repeat mode"
                logger.info(f"{reason}, using original time: {actual_start_time}")
            
            # 创建RRule系列，使用返回的UID作为series_id
            series_id = self.rrule_engine.create_series(rrule, actual_start_time)
            
            # 计算结束时间
            end_time = parse_datetime_safe(event_data['end'])
            duration = end_time - start_time
            actual_end_time = actual_start_time + duration
            
            # 创建主事件
            main_event = event_data.copy()
            main_event.update({
                'id': str(uuid.uuid4()),
                'series_id': series_id,
                'rrule': rrule,
                'start': actual_start_time.strftime("%Y-%m-%dT%H:%M:%S"),
                'end': actual_end_time.strftime("%Y-%m-%dT%H:%M:%S"),
                'is_recurring': True,
                'is_main_event': True,
                'recurrence_id': '',
                'parent_event_id': '',
                'last_modified': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
            logger.info(f"[DEBUG] Created main_event with series_id: {series_id}")
            logger.info(f"[DEBUG] Main event data: {main_event}")
            logger.info(f"Created recurring event series {series_id} with rrule: {rrule}")
            return main_event
            
        except Exception as e:
            logger.error(f"Failed to create recurring event: {str(e)}")
            raise
    
    def _has_multiple_byday_values(self, rrule_str: str) -> bool:
        """检查RRule是否包含多个BYDAY值（如BYDAY=MO,FR）"""
        byday_match = re.search(r'BYDAY=([A-Z0-9,+-]+)', rrule_str)
        if byday_match:
            byday_value = byday_match.group(1)
            return ',' in byday_value
        return False
    
    def _is_complex_rrule(self, rrule_str: str) -> bool:
        """判断是否为复杂的RRule模式，需要查找下一个符合条件的时间点"""
        # 复杂模式包括：BYWEEKDAY（按星期）、BYMONTHDAY（按月的日期）、BYSETPOS（按位置）等
        complex_patterns = ['BYWEEKDAY', 'BYMONTHDAY', 'BYSETPOS', 'BYYEARDAY', 'BYWEEKNO', 'BYDAY']
        return any(pattern in rrule_str for pattern in complex_patterns)
    
    def _find_next_occurrence(self, rrule_str: str, start_time: datetime.datetime) -> Optional[datetime.datetime]:
        """从指定时间开始查找下一个符合RRule条件的时间点"""
        try:
            from dateutil.rrule import rrulestr
            
            # 构建完整的RRule字符串用于测试
            full_rrule = f"DTSTART:{start_time.strftime('%Y%m%dT%H%M%S')}\nRRULE:{rrule_str}"
            
            # 解析RRule
            rule = rrulestr(full_rrule, dtstart=start_time)
            
            # 获取前几个实例
            instances = list(rule[:5])  # 获取前5个实例
            
            if instances:
                # 检查第一个实例是否就是我们想要的时间
                first_instance = instances[0]
                
                # 如果第一个实例的日期时间与开始时间完全相同，说明开始时间本身就符合条件
                if (first_instance.date() == start_time.date() and 
                    first_instance.hour == start_time.hour and 
                    first_instance.minute == start_time.minute):
                    return start_time
                else:
                    # 否则返回第一个符合条件的时间点
                    return first_instance
            
            return None
            
        except Exception as e:
            logger.warning(f"Failed to find next occurrence for rrule {rrule_str}: {e}")
            return None
    
    def _find_nth_weekday_in_month(self, year: int, month: int, week_num: int, target_weekday: int, 
                                   start_time: datetime.datetime) -> Optional[datetime.datetime]:
        """在指定年月中查找第N个指定星期几的日期
        
        Args:
            year: 年份
            month: 月份
            week_num: 第几周（1-5，-1表示最后一周）
            target_weekday: 目标星期几（0=周一, 6=周日）
            start_time: 原始开始时间（用于保持时分秒）
            
        Returns:
            找到的日期时间，如果不存在则返回None
        """
        try:
            import calendar
            
            # 获取该月第一天和最后一天
            first_day = datetime.datetime(year, month, 1)
            last_day_of_month = calendar.monthrange(year, month)[1]
            last_day = datetime.datetime(year, month, last_day_of_month)
            
            if week_num > 0:
                # 正数：从月初开始找第N个指定星期几
                current_date = first_day
                count = 0
                
                while current_date <= last_day:
                    if current_date.weekday() == target_weekday:
                        count += 1
                        if count == week_num:
                            # 找到了，保持原始时间的时分秒
                            return current_date.replace(
                                hour=start_time.hour,
                                minute=start_time.minute,
                                second=start_time.second,
                                microsecond=start_time.microsecond
                            )
                    current_date += datetime.timedelta(days=1)
            else:
                # 负数：从月末开始找倒数第N个指定星期几
                current_date = last_day
                count = 0
                
                while current_date >= first_day:
                    if current_date.weekday() == target_weekday:
                        count += 1
                        if count == abs(week_num):
                            # 找到了，保持原始时间的时分秒
                            return current_date.replace(
                                hour=start_time.hour,
                                minute=start_time.minute,
                                second=start_time.second,
                                microsecond=start_time.microsecond
                            )
                    current_date -= datetime.timedelta(days=1)
            
            return None
            
        except Exception as e:
            logger.warning(f"Failed to find {week_num} weekday {target_weekday} in {year}-{month}: {e}")
            return None
    
    def modify_recurring_event(self, events: List[Dict[str, Any]], series_id: str, 
                             from_time: Optional[str] = None, new_rrule: Optional[str] = None) -> List[Dict[str, Any]]:
        """修改重复事件规则"""
        try:
            if from_time:
                from_datetime = datetime.datetime.fromisoformat(from_time)
            else:
                from_datetime = datetime.datetime.now()
                
            modified_events = []
            
            for event in events:
                if event.get('series_id') == series_id:
                    event_start = datetime.datetime.fromisoformat(event['start'])
                    
                    if event_start >= from_datetime:
                        # 更新事件
                        modified_event = event.copy()
                        if new_rrule and event.get('is_main_event'):
                            modified_event['rrule'] = new_rrule
                        modified_event['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        modified_events.append(modified_event)
                    else:
                        # 保持原有事件不变
                        modified_events.append(event)
                else:
                    modified_events.append(event)
                    
            return modified_events
            
        except Exception as e:
            logger.error(f"Failed to modify recurring event: {str(e)}")
            raise
    
    def process_event_data(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """处理事件数据，生成RRule实例 - 适配事件时间结构"""
        if not isinstance(events, list):
            return []
        
        # 自动生成缺失的重复事件实例
        new_instances_count = self.auto_generate_missing_instances(events)
        
        if new_instances_count > 0:
            logger.info(f"Generated {new_instances_count} new event instances")
        
        return events
    
    def auto_generate_missing_instances(self, events: List[Dict[str, Any]]) -> int:
        """自动生成缺失的重复事件实例"""
        new_instances_count = 0
        # 使用本地时区的现在时间
        now = datetime.datetime.now()
        
        logger.info(f"[DEBUG] auto_generate_missing_instances called with {len(events)} events")
        
        # 获取所有重复系列
        recurring_series = {}
        for event in events:
            series_id = event.get('series_id')
            rrule = event.get('rrule')
            
            logger.info(f"[DEBUG] Processing event: series_id={series_id}, rrule={rrule}, is_detached={event.get('is_detached', False)}")
            
            if series_id and rrule and 'FREQ=' in rrule and not event.get('is_detached', False):
                if series_id not in recurring_series:
                    recurring_series[series_id] = {
                        'events': [],
                        'rrule': rrule,
                        'main_event': None
                    }
                recurring_series[series_id]['events'].append(event)
                
                if event.get('is_main_event'):
                    recurring_series[series_id]['main_event'] = event
        
        logger.info(f"[DEBUG] Found {len(recurring_series)} recurring series")
        
        # 检查每个系列是否需要生成新实例
        for series_id, series_data in recurring_series.items():
            logger.info(f"[DEBUG] Processing series {series_id}")
            series_events = series_data['events']
            rrule = series_data['rrule']
            main_event = series_data['main_event']
            
            if not main_event:
                logger.warning(f"[DEBUG] No main event found for series {series_id}")
                continue
            
            # 检查是否有COUNT限制
            has_count = 'COUNT=' in rrule
            has_until = 'UNTIL=' in rrule
            
            if has_count:
                # 检查COUNT限制
                import re
                count_match = re.search(r'COUNT=(\d+)', rrule)
                if count_match:
                    count_limit = int(count_match.group(1))
                    current_count = len(series_events)
                    
                    if current_count >= count_limit:
                        logger.info(f"Series {series_id} has reached COUNT limit {count_limit} (current: {current_count})")
                        continue
                    else:
                        logger.info(f"Series {series_id} COUNT: {current_count}/{count_limit}")
                        # 只生成到达限制为止的实例
                        remaining_count = count_limit - current_count
                        new_instances = self.generate_event_instances(main_event, 365, remaining_count)
                        
                        # 过滤掉已经存在的实例
                        existing_starts = {e['start'] for e in series_events}
                        truly_new_instances = []
                        
                        for instance in new_instances[:remaining_count]:  # 确保不超过限制
                            if instance['start'] not in existing_starts:
                                truly_new_instances.append(instance)
                        
                        if truly_new_instances:
                            events.extend(truly_new_instances)
                            new_instances_count += len(truly_new_instances)
                            logger.info(f"Added {len(truly_new_instances)} new instances for COUNT-limited series {series_id}")
                continue
            
            if has_until:
                # 有UNTIL限制的，不自动生成（可能需要专门处理）
                continue
                    
            # 只处理没有COUNT和UNTIL限制的重复事件
            # 找到最晚的事件时间
            latest_time = None
            for event in series_events:
                try:
                    # 解析时间字符串，确保是naive datetime
                    start_str = event['start']
                    if 'T' in start_str:
                        # 移除可能的时区信息
                        if start_str.endswith('Z'):
                            start_str = start_str[:-1]
                        elif '+' in start_str or start_str.count('-') > 2:
                            # 移除时区偏移
                            if '+' in start_str:
                                start_str = start_str.split('+')[0]
                            else:
                                # 处理负时区偏移
                                parts = start_str.split('-')
                                if len(parts) > 3:  # YYYY-MM-DDTHH:MM:SS-offset
                                    start_str = '-'.join(parts[:3])
                        
                        start_time = datetime.datetime.fromisoformat(start_str)
                    else:
                        start_time = datetime.datetime.fromisoformat(start_str)
                    
                    if latest_time is None or start_time > latest_time:
                        latest_time = start_time
                        
                except (ValueError, TypeError) as e:
                    logger.warning(f"Failed to parse event start time '{event.get('start')}': {e}")
                    continue
            
            if latest_time:
                # 如果最晚的事件时间距离现在少于30天，生成新实例
                days_ahead = (latest_time - now).days
                logger.info(f"Series {series_id} latest event is {days_ahead} days from now")
                
                # 修复逻辑：如果没有足够的未来实例（少于30天或只有主事件），则生成
                if days_ahead < 30 or len(series_events) == 1:
                    logger.info(f"Series {series_id} (no UNTIL) needs new instances, latest is {days_ahead} days ahead, count: {len(series_events)}")
                    
                    # 根据重复频率调整生成参数
                    rrule = main_event.get('rrule', '')
                    if 'FREQ=MONTHLY' in rrule:
                        # 月度重复需要更长的时间范围和更多实例
                        new_instances = self.generate_event_instances(main_event, 365, 36)  # 3年的月度实例
                    elif 'FREQ=WEEKLY' in rrule:
                        # 周度重复
                        new_instances = self.generate_event_instances(main_event, 180, 26)  # 半年的周度实例
                    else:
                        # 日度或其他重复
                        new_instances = self.generate_event_instances(main_event, 90, 20)
                    
                    # 过滤掉已经存在的实例
                    existing_starts = {e['start'] for e in series_events}
                    truly_new_instances = []
                    
                    for instance in new_instances:
                        if instance['start'] not in existing_starts:
                            truly_new_instances.append(instance)
                    
                    if truly_new_instances:
                        events.extend(truly_new_instances)
                        new_instances_count += len(truly_new_instances)
                        logger.info(f"Added {len(truly_new_instances)} new instances for unlimited series {series_id}")
                else:
                    logger.info(f"Series {series_id} (no UNTIL) is good, latest is {days_ahead} days ahead")
        
        return new_instances_count
    
    def generate_event_instances(self, main_event: Dict[str, Any], days_ahead: int = 90, max_instances: int = 20) -> List[Dict[str, Any]]:
        """生成事件实例 - 使用RRule引擎以正确处理EXDATE等例外"""
        instances = []
        
        try:
            rrule = main_event.get('rrule', '')
            series_id = main_event.get('series_id', '')
            
            if not rrule or not series_id or 'FREQ=' not in rrule:
                return instances
                
            # 使用RRule引擎生成实例，这会正确处理EXDATE
            start_time = datetime.datetime.fromisoformat(main_event['start'])
            end_time = start_time + datetime.timedelta(days=days_ahead)
            
            # 从RRule引擎获取实例时间
            instance_times = self.rrule_engine.generate_instances(
                series_id, 
                start_time, 
                end_time, 
                max_instances
            )
            
            # 计算持续时间
            event_start = datetime.datetime.fromisoformat(main_event['start'])
            event_end = datetime.datetime.fromisoformat(main_event['end'])
            duration = event_end - event_start
            
            # 生成事件实例
            for instance_time in instance_times:
                # 跳过主事件的时间
                if instance_time == event_start:
                    continue
                    
                instance = main_event.copy()
                instance.update({
                    'id': str(uuid.uuid4()),
                    'start': instance_time.strftime("%Y-%m-%dT%H:%M:%S"),
                    'end': (instance_time + duration).strftime("%Y-%m-%dT%H:%M:%S"),
                    'is_main_event': False,
                    'recurrence_id': instance_time.strftime("%Y%m%dT%H%M%S"),
                    'last_modified': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                logger.info(f"[DEBUG] Generated instance with series_id: {instance.get('series_id')}")
                instances.append(instance)
                
        except Exception as e:
            logger.error(f"Error generating event instances: {e}")
            # 如果RRule引擎出错，回退到原始逻辑
            return self._generate_event_instances_fallback(main_event, days_ahead, max_instances)
            
        return instances
    
    def _generate_event_instances_fallback(self, main_event: Dict[str, Any], days_ahead: int = 90, max_instances: int = 20) -> List[Dict[str, Any]]:
        """生成事件实例的回退方法 - 原始的简单解析逻辑"""
        instances = []
        
        if not main_event.get('rrule') or 'FREQ=' not in main_event.get('rrule', ''):
            return instances
        
        try:
            import re
            rrule = main_event['rrule']
            # 解析EXDATE
            exdates = set()
            exdate_match = re.findall(r'EXDATE=([^;]+)', rrule)
            for exdate_str in exdate_match:
                for dt_str in exdate_str.split(','):
                    exdates.add(dt_str.strip())
            # ...existing code for parse_datetime_safe, start_time, end_time, duration, until_time, generation_end_time, etc...
            def parse_datetime_safe(time_str):
                if not time_str:
                    return datetime.datetime.now()
                if 'T' in time_str:
                    if time_str.endswith('Z'):
                        time_str = time_str[:-1]
                    elif '+' in time_str or time_str.count('-') > 2:
                        if '+' in time_str:
                            time_str = time_str.split('+')[0]
                        else:
                            parts = time_str.split('-')
                            if len(parts) > 3:
                                time_str = '-'.join(parts[:3])
                    if time_str.count(':') == 1:
                        time_str += ':00'
                return datetime.datetime.fromisoformat(time_str)
            start_time = parse_datetime_safe(main_event['start'])
            end_time = parse_datetime_safe(main_event['end'])
            duration = end_time - start_time
            until_time = None
            if 'UNTIL=' in rrule:
                until_match = re.search(r'UNTIL=([^;]+)', rrule)
                if until_match:
                    until_str = until_match.group(1)
                    try:
                        if until_str.endswith('Z'):
                            if 'T' in until_str and len(until_str) == 16:
                                until_formatted = (until_str[:4] + '-' + until_str[4:6] + '-' + until_str[6:8] +
                                                 'T' + until_str[9:11] + ':' + until_str[11:13] + ':' + until_str[13:15])
                                until_time = datetime.datetime.fromisoformat(until_formatted)
                            else:
                                until_time = datetime.datetime.fromisoformat(until_str.replace('Z', ''))
                        elif 'T' in until_str and len(until_str) == 15:
                            until_formatted = (until_str[:4] + '-' + until_str[4:6] + '-' + until_str[6:8] +
                                             'T' + until_str[9:11] + ':' + until_str[11:13] + ':' + until_str[13:15])
                            until_time = datetime.datetime.fromisoformat(until_formatted)
                        else:
                            until_time = datetime.datetime.fromisoformat(until_str)
                    except Exception as e:
                        logger.error(f"Failed to parse UNTIL {until_str}: {e}")
            generation_end_time = start_time + timedelta(days=days_ahead)
            if until_time:
                generation_end_time = min(generation_end_time, until_time)
            # FREQ=DAILY
            if 'FREQ=DAILY' in rrule:
                interval = 1
                if 'INTERVAL=' in rrule:
                    interval_match = re.search(r'INTERVAL=(\d+)', rrule)
                    if interval_match:
                        interval = int(interval_match.group(1))
                current_time = start_time + timedelta(days=interval)
                while current_time <= generation_end_time and len(instances) < max_instances:
                    dt_str = current_time.strftime("%Y-%m-%dT%H:%M:%S")
                    if dt_str in exdates:
                        current_time += timedelta(days=interval)
                        continue
                    instance = main_event.copy()
                    instance.update({
                        'id': str(uuid.uuid4()),
                        'start': dt_str,
                        'end': (current_time + duration).strftime("%Y-%m-%dT%H:%M:%S"),
                        'is_main_event': False,
                        'recurrence_id': current_time.strftime("%Y%m%dT%H%M%S"),
                        'last_modified': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    logger.info(f"[DEBUG] Generated instance with series_id: {instance.get('series_id')}")
                    instances.append(instance)
                    current_time += timedelta(days=interval)
            # FREQ=WEEKLY
            elif 'FREQ=WEEKLY' in rrule:
                interval = 1
                if 'INTERVAL=' in rrule:
                    interval_match = re.search(r'INTERVAL=(\d+)', rrule)
                    if interval_match:
                        interval = int(interval_match.group(1))
                current_time = start_time + timedelta(weeks=interval)
                while current_time <= generation_end_time and len(instances) < max_instances:
                    dt_str = current_time.strftime("%Y-%m-%dT%H:%M:%S")
                    if dt_str in exdates:
                        current_time += timedelta(weeks=interval)
                        continue
                    instance = main_event.copy()
                    instance.update({
                        'id': str(uuid.uuid4()),
                        'start': dt_str,
                        'end': (current_time + duration).strftime("%Y-%m-%dT%H:%M:%S"),
                        'is_main_event': False,
                        'recurrence_id': current_time.strftime("%Y%m%dT%H%M%S"),
                        'last_modified': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    instances.append(instance)
                    current_time += timedelta(weeks=interval)
            # FREQ=MONTHLY
            elif 'FREQ=MONTHLY' in rrule:
                interval = 1
                if 'INTERVAL=' in rrule:
                    interval_match = re.search(r'INTERVAL=(\d+)', rrule)
                    if interval_match:
                        interval = int(interval_match.group(1))
                count_limit = None
                if 'COUNT=' in rrule:
                    count_match = re.search(r'COUNT=(\d+)', rrule)
                    if count_match:
                        count_limit = int(count_match.group(1))
                if count_limit:
                    iterations = count_limit - 1
                else:
                    if until_time:
                        months_needed = ((until_time.year - start_time.year) * 12 +
                                       (until_time.month - start_time.month)) // interval
                        iterations = min(max_instances, max(months_needed, 1))
                    else:
                        months_needed = ((generation_end_time.year - start_time.year) * 12 +
                                       (generation_end_time.month - start_time.month)) // interval
                        iterations = min(max_instances, max(months_needed, 24))
                byday_match = re.search(r'BYDAY=([+-]?\d+)([A-Z]{2})', rrule)
                current_time = start_time
                for i in range(iterations):
                    try:
                        total_months = interval * (i + 1)
                        if start_time.month + total_months > 12:
                            new_year = start_time.year + ((start_time.month + total_months - 1) // 12)
                            new_month = ((start_time.month + total_months - 1) % 12) + 1
                        else:
                            new_year = start_time.year
                            new_month = start_time.month + total_months
                        if byday_match:
                            week_num = int(byday_match.group(1))
                            weekday_str = byday_match.group(2)
                            weekday_map = {'MO': 0, 'TU': 1, 'WE': 2, 'TH': 3, 'FR': 4, 'SA': 5, 'SU': 6}
                            target_weekday = weekday_map.get(weekday_str, 0)
                            current_time = self._find_nth_weekday_in_month(new_year, new_month, week_num, target_weekday, start_time)
                            if not current_time:
                                continue
                        else:
                            current_time = start_time.replace(year=new_year, month=new_month)
                        dt_str = current_time.strftime("%Y-%m-%dT%H:%M:%S")
                        if dt_str in exdates:
                            continue
                        if current_time <= generation_end_time:
                            if count_limit and len(instances) >= count_limit - 1:
                                break
                            instance = main_event.copy()
                            instance.update({
                                'id': str(uuid.uuid4()),
                                'start': dt_str,
                                'end': (current_time + duration).strftime("%Y-%m-%dT%H:%M:%S"),
                                'is_main_event': False,
                                'recurrence_id': current_time.strftime("%Y%m%dT%H%M%S"),
                                'last_modified': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            })
                            instances.append(instance)
                        else:
                            break
                    except ValueError:
                        break
        except Exception as e:
            logger.error(f"Failed to generate event instances: {str(e)}")
        return instances
    
    def _generate_event_instances(self, main_event: Dict[str, Any], rrule: str, 
                                existing_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """生成事件实例 - 适配事件的start/end时间结构"""
        try:
            # 获取现有时间点
            existing_times = set()
            for event in existing_events:
                existing_times.add(event['start'])
            
            # 生成新实例
            start_time = datetime.datetime.fromisoformat(main_event['start'])
            end_time = datetime.datetime.fromisoformat(main_event['end'])
            duration = end_time - start_time
            
            # 使用RRule引擎生成时间点
            instances = self.rrule_engine.generate_instances(
                main_event['series_id'],
                start_date=datetime.datetime.now(),
                end_date=datetime.datetime.now() + timedelta(days=90),
                max_count=50
            )
            
            new_events = []
            for instance_time in instances:
                instance_start = instance_time.strftime("%Y-%m-%dT%H:%M:%S")
                instance_end = (instance_time + duration).strftime("%Y-%m-%dT%H:%M:%S")
                
                if instance_start not in existing_times:
                    new_event = main_event.copy()
                    new_event.update({
                        'id': str(uuid.uuid4()),
                        'start': instance_start,
                        'end': instance_end,
                        'is_main_event': False,
                        'recurrence_id': instance_start,
                        'parent_event_id': main_event['id'],
                        'last_modified': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    new_events.append(new_event)
            
            logger.info(f"Generated {len(new_events)} new event instances")
            return new_events
            
        except Exception as e:
            logger.error(f"Failed to generate event instances: {str(e)}")
            return []

    def delete_event_instance(self, events: List[Dict[str, Any]], event_id: str, series_id: str) -> List[Dict[str, Any]]:
        """删除单个事件实例，使用EXDATE机制防止重新生成"""
        updated_events = []
        deleted_event = None
        
        for event in events:
            if event.get('id') == event_id:
                deleted_event = event
                # 不添加到更新列表中，相当于删除
                continue
            updated_events.append(event)
        
        if deleted_event and series_id:
            # 在RRule引擎中记录例外，防止重新生成
            start_time_str = deleted_event.get('start', '')
            try:
                start_time = datetime.datetime.fromisoformat(start_time_str)
                self.rrule_engine.delete_instance(series_id, start_time)
                logger.info(f"Added exception for deleted event at {start_time}")
            except Exception as e:
                logger.warning(f"Failed to add exception for deleted event: {e}")
        
        return updated_events

    def delete_event_this_and_after(self, events: List[Dict[str, Any]], event_id: str, series_id: str) -> List[Dict[str, Any]]:
        """删除此事件及之后的所有事件实例，使用UNTIL截断机制"""
        # 找到目标事件的时间
        target_event = None
        for event in events:
            if event.get('id') == event_id:
                target_event = event
                break
        
        if not target_event or not series_id:
            return events
        
        try:
            # 获取目标事件的时间
            start_time_str = target_event.get('start', '')
            start_time = datetime.datetime.fromisoformat(start_time_str)
            
            # 在RRule引擎中截断系列
            self.rrule_engine.truncate_series_until(series_id, start_time)
            logger.info(f"Truncated event series {series_id} until {start_time}")
            
            # 更新数据库中的事件数据
            updated_events = []
            for event in events:
                if event.get('series_id') == series_id:
                    event_start_str = event.get('start', '')
                    try:
                        event_start_time = datetime.datetime.fromisoformat(event_start_str)
                        
                        # 只保留在截断时间之前的事件
                        if event_start_time < start_time:
                            # 更新此系列所有事件的RRule字符串，添加UNTIL限制
                            current_rrule = event.get('rrule', '')
                            if 'UNTIL=' in current_rrule.upper():
                                # 如果已有UNTIL，替换为新的（更早的）截止时间
                                import re
                                until_time = start_time - datetime.timedelta(seconds=1)
                                new_until_str = until_time.strftime('%Y%m%dT%H%M%S')
                                updated_rrule = re.sub(r'UNTIL=\d{8}T\d{6}', f'UNTIL={new_until_str}', current_rrule, flags=re.IGNORECASE)
                                event['rrule'] = updated_rrule
                                logger.info(f"Updated event {event.get('id', 'unknown')} RRule UNTIL to {new_until_str}")
                            else:
                                # 如果没有UNTIL，添加新的截止时间
                                until_time = start_time - datetime.timedelta(seconds=1)
                                until_str = until_time.strftime('%Y%m%dT%H%M%S')
                                if ';' in current_rrule:
                                    event['rrule'] = f"{current_rrule};UNTIL={until_str}"
                                else:
                                    event['rrule'] = f"{current_rrule};UNTIL={until_str}"
                                logger.info(f"Added UNTIL={until_str} to event {event.get('id', 'unknown')} RRule")
                            
                            updated_events.append(event)
                        # 在截断时间之后的事件都被删除（不添加到updated_events）
                    except Exception as e:
                        logger.warning(f"Failed to parse event time: {e}")
                        # 如果无法解析时间，保留这个事件
                        updated_events.append(event)
                else:
                    # 不属于这个系列的事件直接保留
                    updated_events.append(event)
            
            return updated_events
            
        except Exception as e:
            logger.error(f"Failed to truncate event series {series_id}: {e}")
            return events

    # def process_event_data(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    #     """处理事件数据，确保重复事件的实例足够"""
    #     # 调用父类的处理逻辑，适配事件数据结构
    #     return self.process_reminder_data(events)

    def modify_recurring_rule(self, events: List[Dict[str, Any]], series_id: str, 
                            cutoff_time: datetime.datetime, new_rrule: str, 
                            scope: str = 'from_this', additional_updates: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """修改重复规则"""
        if additional_updates is None:
            additional_updates = {}
        
        # 调用父类的方法，适配事件数据结构
        return super().modify_recurring_rule(events, series_id, cutoff_time, new_rrule, scope, additional_updates)


def get_events_manager(request) -> EventsRRuleManager:
    """获取Events RRule管理器实例"""
    return EventsRRuleManager(request)


@login_required
def get_events_impl(request):
    """获取所有日程和日程组 - 支持RRule处理"""
    if request.method == 'GET':
        # 自动新建一个日程
        now = datetime.datetime.now()
        # 找到最近的整点
        next_hour = now.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)
        # 计算一天之后的时间
        one_day_later = next_hour + datetime.timedelta(hours=1)
        # 格式化为指定的格式
        next_hour_formatted = next_hour.strftime("%Y-%m-%dT%H:%M:%S")
        one_day_later_formatted = one_day_later.strftime("%Y-%m-%dT%H:%M:%S")

        user_data: 'UserData'
        # 当没有读取到events的值（即新用户）的时候，自动新建一个任务
        user_data, created, result = UserData.get_or_initialize(request=request, new_key="events", data=[
            {
                "id": '1',
                "title": "让我们开始吧！",
                "start": next_hour_formatted,
                "end": one_day_later_formatted,
                "backgroundColor": "red",
                "description": "花一小时时间，学习如何使用我们的计划工具！",
                "importance": "important",
                "urgency": "urgent",
                "groupID": "1",
                "ddl": "",
                "last_modified": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                # RRule相关字段
                "rrule": "",
                "series_id": "",
                "is_recurring": False,
                "is_main_event": False,
                "is_detached": False,
                "recurrence_id": "",
                "parent_event_id": ""
            }
        ])
        
        # 检查用户数据是否成功获取
        if user_data is None:
            logger.error("Failed to get user data")
            return JsonResponse({'status': 'error', 'message': 'Failed to initialize user data'}, status=500)

        # 获取用户的所有日程组
        user_data_groups, created = UserData.objects.get_or_create(user=request.user, key="events_groups", defaults={"value": json.dumps([
            {
                "id": '1',
                "name": "学习如何使用日程组！",
                "description": "进阶工具：日程组，继续学习如何使用我们的计划工具！",
                "color": "red"
            }
        ])})

        events_groups = json.loads(user_data_groups.value)

        events = user_data.get_value(check=True)  # 设为 True ，每次服务器修改都能让用户端实时更新
        
        # 确保events是列表类型
        if not isinstance(events, list):
            events = []
        
        # 使用RRule管理器处理重复事件
        events_manager = get_events_manager(request)
        processed_events = events_manager.process_event_data(events)
        
        # 保存处理后的数据
        user_data.set_value(processed_events)
        
        if not processed_events:
            processed_events = []
        # 返回事件和日程组数据
        if not events_groups:
            events_groups = []

        # 返回事件和日程组数据
        return JsonResponse({"events": processed_events, "events_groups": events_groups})
    
    # 处理非GET请求
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)


@login_required
@csrf_exempt 
def create_event_impl(request):
    """创建新的event"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)
        
    manager = EventsRRuleManager(request.user)
    
    try:
        data = json.loads(request.body)
        
        # 提取事件数据
        event_data = {
            'title': data.get('title'),
            'start': data.get('start'),
            'end': data.get('end'),
            'description': data.get('description', ''),
            'importance': data.get('importance'),
            'urgency': data.get('urgency'),
            'group_id': data.get('groupId'),
        }
        
        # 获取用户偏好设置
        user_preference_data, created, result = UserData.get_or_initialize(
            request, new_key="user_preference"
        )
        if user_preference_data is None:
            return JsonResponse({'status': 'error', 'message': 'Failed to get user preferences'}, status=500)
        
        user_preference = user_preference_data.get_value() or {}
        
        # 根据用户设置处理DDL
        if user_preference.get("auto_ddl", False):
            event_data['ddl'] = data.get('ddl', '')
        else:
            event_data['ddl'] = ''
            
        # 处理RRule相关数据
        rrule = data.get('rrule')
        if rrule:
            # 创建重复事件系列
            main_event = manager.create_recurring_event(event_data, rrule)
            
            logger.info(f"[DEBUG] main_event returned from create_recurring_event: {main_event}")
            
            # 将主事件保存到events数据中
            user_events_data, created, result = UserData.get_or_initialize(
                request, new_key="events", data=[]
            )
            if user_events_data is None:
                return JsonResponse({'status': 'error', 'message': 'Failed to get user events data'}, status=500)

            events = user_events_data.get_value() or []
            if not isinstance(events, list):
                events = []

            events.append(main_event)
            logger.info(f"[DEBUG] Added main_event to events array, main_event series_id: {main_event.get('series_id')}")
            
            # 只有当不包含COUNT和UNTIL限制时，才自动生成后续实例
            if 'COUNT=' not in rrule and 'UNTIL=' not in rrule:
                # 无限制重复 - 生成适当数量的实例，与update_events_impl保持一致
                if 'FREQ=MONTHLY' in rrule:
                    additional_instances = manager.generate_event_instances(main_event, 365, 36)
                elif 'FREQ=WEEKLY' in rrule:
                    additional_instances = manager.generate_event_instances(main_event, 180, 26)
                else:  # DAILY, YEARLY等
                    additional_instances = manager.generate_event_instances(main_event, 90, 20)
                events.extend(additional_instances)
                logger.info(f"Generated {len(additional_instances)} instances for unlimited recurring event")
                user_events_data.set_value(events)
            else:
                # 有限制的重复事件，手动生成指定数量的实例
                if 'COUNT=' in rrule:
                    import re
                    count_match = re.search(r'COUNT=(\d+)', rrule)
                    if count_match:
                        count = int(count_match.group(1))
                        # 生成指定数量的实例（包括主事件）
                        additional_instances = manager.generate_event_instances(main_event, 365, count - 1)
                        events.extend(additional_instances)
                elif 'UNTIL=' in rrule:
                    # 处理UNTIL限制的重复事件
                    print(f"[DEBUG] Processing UNTIL event with rrule: {rrule}")
                    # 生成从开始时间到UNTIL时间之间的所有实例
                    # 使用较大的天数范围来确保覆盖整个UNTIL期间
                    additional_instances = manager.generate_event_instances(main_event, 365 * 2)  # 2年范围
                    print(f"[DEBUG] Generated {len(additional_instances)} additional instances for UNTIL event")
                    events.extend(additional_instances)
                
                user_events_data.set_value(events)
        else:
            # 创建单次事件
            event_data['id'] = str(uuid.uuid4())
            event_data['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 保存到events数据中
            user_events_data, created, result = UserData.get_or_initialize(
                request, new_key="events", data=[]
            )
            if user_events_data is None:
                return JsonResponse({'status': 'error', 'message': 'Failed to get user events data'}, status=500)
            
            events = user_events_data.get_value() or []
            if not isinstance(events, list):
                events = []
            
            events.append(event_data)
            user_events_data.set_value(events)
            
            main_event = event_data
        
        return JsonResponse({
            'status': 'success',
            'event': main_event
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error', 
            'message': f'创建事件失败: {str(e)}'
        }, status=500)


def delete_event_impl(request):
    """删除事件 - 支持RRule删除策略"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)
        
    try:
        data = json.loads(request.body)
        event_id = data.get('eventId')
        delete_scope = data.get('delete_scope', 'single')  # single, all, future
        
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON data'}, status=400)
        
    if event_id is None:
        return JsonResponse({'status': 'error', 'message': 'eventId is missing'}, status=400)
        
    try:
        # 获取events数据
        user_events_data, created, result = UserData.get_or_initialize(
            request, new_key="events", data=[]
        )
        events = user_events_data.get_value() or []
        
        # 查找要删除的事件
        target_event = None
        for event in events:
            if event.get('id') == event_id:
                target_event = event
                break
                
        if not target_event:
            return JsonResponse({'status': 'error', 'message': 'Event not found'}, status=404)
            
        # 检查是否是重复事件
        is_recurring = target_event.get('is_recurring', False)
        series_id = target_event.get('series_id')
        
        if is_recurring and series_id:
            # 重复事件的处理
            if delete_scope == 'single':
                # 仅删除单个实例
                original_count = len(events)
                events = [event for event in events if event.get('id') != event_id]
                
                if len(events) < original_count:
                    # 如果删除的是主事件，需要特殊处理
                    if target_event.get('is_main_event'):
                        # 找到系列中的下一个实例作为新的主事件
                        series_events = [e for e in events if e.get('series_id') == series_id]
                        if series_events:
                            # 选择最早的实例作为新主事件
                            series_events.sort(key=lambda x: x['start'])
                            new_main_event = series_events[0]
                            for i, event in enumerate(events):
                                if event.get('id') == new_main_event['id']:
                                    events[i]['is_main_event'] = True
                                    break
                        else:
                            # 如果没有其他实例，系列被完全删除
                            pass
                            
            elif delete_scope == 'all':
                # 删除整个系列
                original_count = len(events)
                events = [event for event in events if event.get('series_id') != series_id]
                
            elif delete_scope == 'future':
                # 删除此及之后的实例
                target_start = datetime.datetime.fromisoformat(target_event['start'])
                original_count = len(events)
                
                events = [
                    event for event in events 
                    if not (event.get('series_id') == series_id and 
                           datetime.datetime.fromisoformat(event['start']) >= target_start)
                ]
                
        else:
            # 单次事件，直接删除
            original_count = len(events)
            events = [event for event in events if event.get('id') != event_id]
        
        # 保存更新后的数据
        if len(events) < original_count:
            user_events_data.set_value(events)
            
            # 同时从临时数据中删除（兼容现有逻辑）
            user_temp_events_data, created, result = UserData.get_or_initialize(
                request, new_key="planner", data={
                    "dialogue": [],
                    "temp_events": [],
                    "ai_planning_time": {}
                }
            )
            planner_data = user_temp_events_data.get_value() or {}
            temp_events = planner_data.get("temp_events", [])
            
            if is_recurring and series_id and delete_scope in ['all', 'future']:
                # 批量删除临时事件
                if delete_scope == 'all':
                    temp_events = [event for event in temp_events if event.get('series_id') != series_id]
                elif delete_scope == 'future':
                    target_start = datetime.datetime.fromisoformat(target_event['start'])
                    temp_events = [
                        event for event in temp_events 
                        if not (event.get('series_id') == series_id and 
                               datetime.datetime.fromisoformat(event['start']) >= target_start)
                    ]
            else:
                # 单个删除
                temp_events = [event for event in temp_events if event.get('id') != event_id]
                
            planner_data["temp_events"] = temp_events
            user_temp_events_data.set_value(planner_data)
            
            return JsonResponse({
                'status': 'success',
                'deleted_count': original_count - len(events),
                'scope': delete_scope
            })
        else:
            return JsonResponse({'status': 'error', 'message': 'Event not found'}, status=404)
            
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'删除事件失败: {str(e)}'
        }, status=500)


@login_required
@csrf_exempt
def bulk_edit_events_impl(request):
    """批量编辑事件 - 支持四种编辑模式"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)
    
    try:
        data = json.loads(request.body)
        
        # 提取参数
        event_id = data.get('event_id')
        operation = data.get('operation')  # 'edit' or 'delete'
        edit_scope = data.get('edit_scope')  # 'single', 'all', 'future', 'from_time'
        from_time = data.get('from_time')
        series_id = data.get('series_id')
        
        # 编辑数据
        updates = {
            'title': data.get('title'),
            'description': data.get('description'),
            'importance': data.get('importance'),
            'urgency': data.get('urgency'),
            'start': data.get('start'),
            'end': data.get('end'),
            'rrule': data.get('rrule'),
            'groupID': data.get('groupID'),
            'ddl': data.get('ddl'),
        }
        # 过滤掉None值
        updates = {k: v for k, v in updates.items() if v is not None}
        
        logger.info(f"Bulk edit events - Operation: {operation}, Scope: {edit_scope}, Event ID: {event_id}, Series ID: {series_id}")
        
        # 添加调试信息：检查事件数据结构
        logger.info(f"[DEBUG] Request data keys: {list(data.keys())}")
        
        if not event_id:
            return JsonResponse({'status': 'error', 'message': '事件ID是必填项'}, status=400)
            
        if edit_scope == 'from_time' and not from_time:
            return JsonResponse({'status': 'error', 'message': '当编辑范围为"从指定时间"时，必须提供起始时间'}, status=400)
        
        # 获取事件数据
        user_events_data, created, result = UserData.get_or_initialize(
            request, new_key="events", data=[]
        )
        if user_events_data is None:
            return JsonResponse({'status': 'error', 'message': 'Failed to get user events data'}, status=500)
            
        events = user_events_data.get_value() or []
        if not isinstance(events, list):
            events = []
        events = convert_time_format(events)
        
        # 使用Events的RRule引擎
        manager = EventsRRuleManager(request.user)
        
        # 如果没有提供series_id，尝试从事件数据中获取
        if not series_id and event_id:
            for event in events:
                if event.get('id') == event_id:
                    series_id = event.get('series_id')
                    logger.info(f"Found series_id from event data: {series_id}")
                    # 添加调试信息：显示事件的详细信息
                    logger.info(f"[DEBUG] Event data: id={event.get('id')}, series_id={event.get('series_id')}, rrule={event.get('rrule')}, is_recurring={event.get('is_recurring')}")
                    break
        
        # 添加调试信息：最终使用的series_id
        logger.info(f"[DEBUG] Final series_id to use: {series_id}")
        
        if operation == 'delete':
            if edit_scope == 'single':
                # 删除单个实例，使用EXDATE机制
                # 找到目标事件的时间
                target_event_time = None
                for event in events:
                    if event.get('id') == event_id:
                        try:
                            start_time = event.get('start')
                            if start_time:
                                target_event_time = datetime.datetime.fromisoformat(start_time)
                                break
                        except Exception as e:
                            logger.error(f"Error parsing event start time: {e}")
                            pass
                
                if target_event_time and series_id:
                    # 添加EXDATE例外
                    manager.rrule_engine.delete_instance(series_id, target_event_time)
                    logger.info(f"Added exception for deleted event at {target_event_time}")
                    
                    # 获取更新后的系列信息，包含EXDATE
                    updated_series = manager.rrule_engine.get_series(series_id)
                    if updated_series:
                        # 获取包含EXDATE的完整rrule字符串
                        segments_data = updated_series.get_segments_data()
                        if segments_data:
                            # 重新构建rrule字符串，包含EXDATE
                            main_segment = segments_data[0]  # 取第一个段
                            updated_rrule = main_segment['rrule_str']
                            
                            # 添加EXDATE信息
                            if main_segment.get('exdates'):
                                exdate_strs = []
                                for exdate in main_segment['exdates']:
                                    if isinstance(exdate, str):
                                        exdate_strs.append(exdate)
                                    else:
                                        exdate_strs.append(exdate.strftime('%Y%m%dT%H%M%S'))
                                if exdate_strs:
                                    updated_rrule += ';EXDATE=' + ','.join(exdate_strs)
                            
                            logger.info(f"Updated rrule with EXDATE: {updated_rrule}")
                            
                            # 更新events数组中所有同系列事件的rrule字段
                            for event in events:
                                if event.get('series_id') == series_id:
                                    event['rrule'] = updated_rrule
                                    event['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # 从events数组中移除该实例
                updated_events = manager.delete_event_instance(events, event_id, series_id or '')
                # 直接保存，不调用process_event_data避免自动生成
                user_events_data.set_value(updated_events)
                return JsonResponse({'status': 'success'})
                
            elif edit_scope in ['all', 'future', 'from_time']:
                # 删除整个系列或从某时间开始删除
                if edit_scope == 'all':
                    # 删除整个系列
                    updated_events = []
                    for event in events:
                        if event.get('series_id') != series_id:
                            updated_events.append(event)
                    
                    # 完全删除系列
                    if series_id:
                        manager.rrule_engine.delete_series(series_id)
                        logger.info(f"Completely deleted event series {series_id}")
                    
                    # 直接保存，不调用process_event_data避免自动生成
                    user_events_data.set_value(updated_events)
                    return JsonResponse({'status': 'success'})
                    
                elif edit_scope in ['future', 'from_time']:
                    # 删除此及之后（使用截断方法）
                    if edit_scope == 'from_time' and from_time:
                        # 如果指定了from_time，找到对应的事件
                        target_event_id = None
                        target_time = datetime.datetime.fromisoformat(from_time)
                        for event in events:
                            if (event.get('series_id') == series_id and 
                                event.get('start')):
                                try:
                                    event_start = event.get('start')
                                    event_id_val = event.get('id')
                                    if event_start and event_id_val:
                                        event_time = datetime.datetime.fromisoformat(event_start)
                                        if abs((event_time - target_time).total_seconds()) < 60:  # 允许1分钟误差
                                            target_event_id = event_id_val
                                            break
                                except:
                                    continue
                        
                        if not target_event_id:
                            return JsonResponse({'status': 'error', 'message': '找不到指定时间的事件'}, status=400)
                            
                        event_id = target_event_id
                    
                    # 使用截断方法删除
                    updated_events = manager.delete_event_this_and_after(events, event_id, series_id or '')
                    
                    # 直接保存，不调用process_event_data避免自动生成
                    user_events_data.set_value(updated_events)
                    return JsonResponse({'status': 'success'})
        
        elif operation == 'edit':
            if edit_scope == 'single':
                # 编辑单个事件 - 需要从重复系列中分离
                for event in events:
                    if event.get('id') == event_id:
                        # 检查是否是重复事件的实例
                        was_recurring = event.get('series_id') or event.get('rrule') or event.get('is_recurring')
                        
                        if was_recurring:
                            # 生成新的独立事件ID，避免与原系列冲突
                            new_event_id = str(uuid.uuid4())
                            logger.info(f"Detaching event {event_id} from series, assigning new ID: {new_event_id}")
                            
                            # 保留原系列信息作为参考
                            original_series_id = event.get('series_id', '')
                            original_rrule = event.get('rrule', '')
                            
                            # 更新事件数据
                            event.update(updates)
                            event['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            
                            # 标记为已脱离系列的独立事件
                            event['id'] = new_event_id  # 分配新ID
                            event['is_detached'] = True  # 标记为已脱离
                            event['rrule'] = ''  # 清除重复规则
                            event['is_recurring'] = False  # 不再是重复事件
                            event['is_main_event'] = False  # 不是主事件
                            event['series_id'] = ''  # 清除系列ID
                            
                            # 保留原始信息供参考
                            event['original_series_id'] = original_series_id
                            event['original_rrule'] = original_rrule
                            event['detached_at'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            
                            logger.info(f"Event {event_id} successfully detached from series {original_series_id} with new ID {new_event_id}")
                        else:
                            # 非重复事件，直接更新
                            event.update(updates)
                            event['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            logger.info(f"Updated single event {event_id}")
                        break
                
                # 处理重复事件数据，确保分离后的原系列能正常生成后续实例
                final_events = manager.process_event_data(events)
                user_events_data.set_value(final_events)
                return JsonResponse({'status': 'success'})
                
            elif edit_scope in ['all', 'future', 'from_time']:
                # 批量编辑 - 使用manager的方法
                
                # 确定修改的起始时间
                cutoff_time = None
                if from_time:
                    try:
                        cutoff_time = datetime.datetime.fromisoformat(from_time)
                    except:
                        cutoff_time = datetime.datetime.now()
                elif edit_scope == 'future':
                    current_event = next((e for e in events if e.get('id') == event_id), None)
                    if current_event:
                        try:
                            cutoff_time = datetime.datetime.fromisoformat(current_event.get('start', ''))
                        except:
                            cutoff_time = datetime.datetime.now()
                    else:
                        cutoff_time = datetime.datetime.now()
                
                if edit_scope == 'all':
                    # 修改整个系列
                    updated_count = 0
                    for event in events:
                        if event.get('series_id') == series_id or event.get('id') == event_id:
                            # 只更新非时间字段，保持原有的start/end时间
                            update_data = {k: v for k, v in updates.items() if k not in ['start', 'end']}
                            event.update(update_data)
                            event['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            updated_count += 1
                    
                    user_events_data.set_value(events)
                    return JsonResponse({'status': 'success', 'updated_count': updated_count})
                    
                elif edit_scope in ['future', 'from_time']:
                    # 从指定时间开始修改
                    if cutoff_time is None:
                        return JsonResponse({'status': 'error', 'message': '无法确定修改的起始时间'}, status=400)
                    
                    if 'rrule' in updates:
                        # 检查RRule是否真的发生了变化
                        new_rrule = updates.get('rrule')
                        if not new_rrule:
                            return JsonResponse({'status': 'error', 'message': 'RRule是必填项'}, status=400)
                        
                        # 找到当前序列的原始RRule进行比较
                        original_rrule = None
                        for event in events:
                            if (event.get('series_id') == series_id and 
                                event.get('rrule')):
                                original_rrule = event.get('rrule')
                                break
                        
                        # 如果RRule没有变化，按非RRule修改处理
                        if original_rrule and original_rrule == new_rrule:
                            logger.info(f"RRule unchanged for event series {series_id}, treating as non-RRule modification")
                            
                            updated_count = 0
                            for event in events:
                                if (event.get('series_id') == series_id and 
                                    event.get('start')):
                                    try:
                                        event_time = datetime.datetime.fromisoformat(event['start'])
                                        if event_time >= cutoff_time:
                                            # 对于非RRule修改，只更新非时间字段，保持原有的start/end时间
                                            update_data = {k: v for k, v in updates.items() if k not in ['rrule', 'start', 'end']}
                                            event.update(update_data)
                                            event['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                            updated_count += 1
                                    except:
                                        pass
                            
                            user_events_data.set_value(events)
                            return JsonResponse({'status': 'success', 'updated_count': updated_count})
                        
                        # RRule确实发生了变化 - 需要创建新序列
                        logger.info(f"Modifying recurring rule from {cutoff_time} for event series {series_id}")
                        
                        # 检查是否有新的start时间，如果有，使用它作为新系列的起始时间
                        new_start_time = cutoff_time
                        if 'start' in updates:
                            try:
                                requested_time = datetime.datetime.fromisoformat(updates['start'])
                                # 使用用户指定的新时间作为起始时间
                                new_start_time = requested_time
                                logger.info(f"Using requested start time {requested_time} as new series start time")
                            except:
                                logger.warning(f"Invalid start time format: {updates.get('start')}, using cutoff_time")
                        
                        # 调用modify_recurring_rule方法，传递额外的更新参数和新的起始时间
                        other_updates = {k: v for k, v in updates.items() if k not in ['rrule']}
                        updated_events = manager.modify_recurring_rule(
                            events, series_id, new_start_time, new_rrule, 
                            scope='from_this', additional_updates=other_updates
                        )
                        
                        # 处理重复事件数据以确保实例足够
                        final_events = manager.process_event_data(updated_events)
                        user_events_data.set_value(final_events)
                        
                        logger.info(f"Successfully modified recurring rule for event series {series_id}")
                        return JsonResponse({'status': 'success'})
                    
                    else:
                        # 只修改其他字段，不涉及RRule - 直接更新
                        logger.info(f"Modifying non-RRule fields from {cutoff_time} for event series {series_id}")
                        
                        updated_count = 0
                        for event in events:
                            if (event.get('series_id') == series_id and 
                                event.get('start')):
                                try:
                                    event_time = datetime.datetime.fromisoformat(event['start'])
                                    if event_time >= cutoff_time:
                                        # 对于非RRule修改，排除start/end字段，保持原有时间
                                        update_data = {k: v for k, v in updates.items() if k not in ['start', 'end']}
                                        event.update(update_data)
                                        event['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                        updated_count += 1
                                except:
                                    pass
                        
                        user_events_data.set_value(events)
                        return JsonResponse({'status': 'success', 'updated_count': updated_count})
        
        return JsonResponse({'status': 'error', 'message': '不支持的操作'}, status=400)
        
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': '无效的JSON数据'}, status=400)
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logger.error(f"批量编辑事件失败: {str(e)}")
        logger.error(f"Error traceback: {error_trace}")
        return JsonResponse({'status': 'error', 'message': f'批量编辑失败: {str(e)}'}, status=500)


# RRule专用API函数

def convert_recurring_to_single_impl(request):
    """将重复事件转换为单次事件"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)
        
    try:
        data = json.loads(request.body)
        series_id = data.get('series_id')
        
        if not series_id:
            return JsonResponse({'status': 'error', 'message': 'series_id is required'}, status=400)
            
        # 获取events数据
        user_events_data, created, result = UserData.get_or_initialize(
            request, new_key="events", data=[]
        )
        if user_events_data is None:
            return JsonResponse({'status': 'error', 'message': 'Failed to get user events data'}, status=500)
            
        events = user_events_data.get_value() or []
        if not isinstance(events, list):
            events = []
        
        converted_count = 0
        
        # 转换整个系列为单次事件
        for i, event in enumerate(events):
            if event.get('series_id') == series_id:
                # 移除RRule相关字段
                events[i].pop('rrule', None)
                events[i].pop('series_id', None)
                events[i]['is_recurring'] = False
                events[i]['is_main_event'] = False
                events[i]['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                converted_count += 1
        
        if converted_count > 0:
            user_events_data.set_value(events)
            
        return JsonResponse({
            'status': 'success',
            'converted_count': converted_count
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'转换事件失败: {str(e)}'
        }, status=500)

def split_event_series_impl(request):
    """分离事件系列 - 从指定时间点分割为两个独立系列"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)
        
    try:
        data = json.loads(request.body)
        series_id = data.get('series_id')
        split_time = data.get('split_time')
        
        if not series_id or not split_time:
            return JsonResponse({'status': 'error', 'message': 'series_id and split_time are required'}, status=400)
            
        # 获取events数据
        user_events_data, created, result = UserData.get_or_initialize(
            request, new_key="events", data=[]
        )
        if user_events_data is None:
            return JsonResponse({'status': 'error', 'message': 'Failed to get user events data'}, status=500)
            
        events = user_events_data.get_value() or []
        if not isinstance(events, list):
            events = []
        
        split_datetime = datetime.datetime.fromisoformat(split_time)
        new_series_id = str(uuid.uuid4())
        
        moved_count = 0
        
        # 将指定时间之后的事件移动到新系列
        for i, event in enumerate(events):
            if event.get('series_id') == series_id:
                event_start = datetime.datetime.fromisoformat(event['start'])
                if event_start >= split_datetime:
                    events[i]['series_id'] = new_series_id
                    # 第一个移动的事件成为新系列的主事件
                    if moved_count == 0:
                        events[i]['is_main_event'] = True
                    else:
                        events[i]['is_main_event'] = False
                    events[i]['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    moved_count += 1
        
        if moved_count > 0:
            user_events_data.set_value(events)
            
        return JsonResponse({
            'status': 'success',
            'new_series_id': new_series_id,
            'moved_count': moved_count
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'分离事件系列失败: {str(e)}'
        }, status=500)

def convert_time_format(events):
    """
    解析事件列表，将UTC时间转换为本地时间（减去8小时）。
    :param events: 事件列表，每个事件是一个字典，包含时间信息。
    :return: 转换后的时间列表。
    """
    for event in events:
        # 检查 'start' 和 'end' 时间是否为 UTC 时间（以 'Z' 结尾）
        for key in ['start', 'end']:
            if event[key].endswith('Z'):
                # 转换为 datetime 对象并减去8小时
                utc_time = datetime.datetime.fromisoformat(event[key].replace('Z', '+00:00'))
                local_time = utc_time - timedelta(hours=-8)
                # 格式化为本地时间格式
                event[key] = local_time.strftime('%Y-%m-%dT%H:%M')
    return events


@login_required
@csrf_exempt 
def update_events_impl(request):
    """更新事件 - 支持RRule修改"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)
        
    try:
        data = json.loads(request.body)
        event_id = data.get('eventId')
        
        if not event_id:
            return JsonResponse({'status': 'error', 'message': 'eventId is required'}, status=400)
            
        # 基础字段
        new_start = data.get('newStart')
        new_end = data.get('newEnd')
        title = data.get('title')
        description = data.get('description')
        importance = data.get('importance')
        urgency = data.get('urgency')
        group_id = data.get('groupID', '')
        ddl = data.get('ddl')
        last_modified = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # RRule相关字段
        rrule_change_scope = data.get('rrule_change_scope', 'single')  # single, all, future, from_time
        new_rrule = data.get('rrule')  # 新的RRule规则
        from_time = data.get('from_time')  # 从何时开始修改
        
        manager = EventsRRuleManager(request.user)
        
        # 获取events数据
        user_events_data, created, result = UserData.get_or_initialize(
            request, new_key="events", data=[]
        )
        if user_events_data is None:
            return JsonResponse({'status': 'error', 'message': 'Failed to get user events data'}, status=500)
            
        events = user_events_data.get_value() or []
        if not isinstance(events, list):
            events = []
        events = convert_time_format(events)
        
        # 查找要更新的事件
        target_event = None
        for event in events:
            if event.get('id') == event_id:
                target_event = event
                break
                
        if not target_event:
            return JsonResponse({'status': 'error', 'message': 'Event not found'}, status=404)
            
        # 检查是否是重复事件
        is_recurring = target_event.get('is_recurring', False)
        series_id = target_event.get('series_id')
        
        if is_recurring and series_id:
            # 重复事件的处理
            if rrule_change_scope == 'single':
                # 仅修改单个实例 - 创建例外
                updated_event = target_event.copy()
                updated_event.update({
                    'start': new_start,
                    'end': new_end,
                    'title': title,
                    'description': description,
                    'importance': importance,
                    'urgency': urgency,
                    'groupID': group_id,
                    'ddl': ddl,
                    'last_modified': last_modified,
                    'is_exception': True,  # 标记为例外
                    'original_start': target_event['start']  # 保存原始时间
                })
                
                # 更新events中的数据
                for i, event in enumerate(events):
                    if event.get('id') == event_id:
                        events[i] = updated_event
                        break
                        
            elif rrule_change_scope == 'all':
                # 修改整个系列
                # 更新主事件
                main_event_updated = False
                for i, event in enumerate(events):
                    if event.get('series_id') == series_id and event.get('is_main_event'):
                        events[i].update({
                            'title': title,
                            'description': description,
                            'importance': importance,
                            'urgency': urgency,
                            'groupID': group_id,
                            'ddl': ddl,
                            'last_modified': last_modified
                        })
                        if new_rrule:
                            events[i]['rrule'] = new_rrule
                        main_event_updated = True
                        break
                
                # 更新所有实例
                if main_event_updated:
                    for i, event in enumerate(events):
                        if event.get('series_id') == series_id and not event.get('is_main_event'):
                            events[i].update({
                                'title': title,
                                'description': description,
                                'importance': importance,
                                'urgency': urgency,
                                'groupID': group_id,
                                'ddl': ddl,
                                'last_modified': last_modified
                            })
                            
            elif rrule_change_scope == 'future':
                # 从当前实例开始修改后续实例
                current_start = datetime.datetime.fromisoformat(target_event['start'])
                
                for i, event in enumerate(events):
                    if event.get('series_id') == series_id:
                        event_start = datetime.datetime.fromisoformat(event['start'])
                        if event_start >= current_start:
                            events[i].update({
                                'title': title,
                                'description': description,
                                'importance': importance,
                                'urgency': urgency,
                                'groupID': group_id,
                                'ddl': ddl,
                                'last_modified': last_modified
                            })
                            
            else:  # rrule_change_scope == 'from_time'
                # 从指定时间开始修改
                if from_time:
                    from_datetime = datetime.datetime.fromisoformat(from_time)
                    
                    for i, event in enumerate(events):
                        if event.get('series_id') == series_id:
                            event_start = datetime.datetime.fromisoformat(event['start'])
                            if event_start >= from_datetime:
                                events[i].update({
                                    'title': title,
                                    'description': description,
                                    'importance': importance,
                                    'urgency': urgency,
                                    'groupID': group_id,
                                    'ddl': ddl,
                                    'last_modified': last_modified
                                })
        else:
            # 单次事件的处理
            updated_event = None
            for i, event in enumerate(events):
                if event.get('id') == event_id:
                    events[i].update({
                        'start': new_start,
                        'end': new_end,
                        'title': title,
                        'description': description,
                        'importance': importance,
                        'urgency': urgency,
                        'groupID': group_id,
                        'ddl': ddl,
                        'last_modified': last_modified
                    })
                    
                    # 如果添加了RRule，转换为重复事件
                    if new_rrule:
                        # 生成系列ID
                        series_id = str(uuid.uuid4())
                        events[i].update({
                            'rrule': new_rrule,
                            'is_recurring': True,
                            'series_id': series_id,
                            'is_main_event': True
                        })
                        
                        # 生成重复实例
                        main_event = events[i]
                        logger.info(f"Converting single event {event_id} to recurring with rrule: {new_rrule}")
                        
                        # 生成重复实例
                        if 'COUNT=' not in new_rrule and 'UNTIL=' not in new_rrule:
                            # 无限制重复 - 生成适当数量的实例
                            if 'FREQ=MONTHLY' in new_rrule:
                                new_instances = manager.generate_event_instances(main_event, 365, 36)
                            elif 'FREQ=WEEKLY' in new_rrule:
                                new_instances = manager.generate_event_instances(main_event, 180, 26)
                            else:
                                new_instances = manager.generate_event_instances(main_event, 90, 20)
                            events.extend(new_instances)
                            logger.info(f"Generated {len(new_instances)} instances for unlimited recurring event")
                        else:
                            # 有限制的重复事件
                            if 'COUNT=' in new_rrule:
                                import re
                                count_match = re.search(r'COUNT=(\d+)', new_rrule)
                                if count_match:
                                    count = int(count_match.group(1))
                                    new_instances = manager.generate_event_instances(main_event, 365, count - 1)
                                    events.extend(new_instances)
                                    logger.info(f"Generated {len(new_instances)} instances for COUNT-limited recurring event")
                            elif 'UNTIL=' in new_rrule:
                                new_instances = manager.generate_event_instances(main_event, 365 * 2)
                                events.extend(new_instances)
                                logger.info(f"Generated {len(new_instances)} instances for UNTIL-limited recurring event")
                    
                    updated_event = events[i]
                    break
        
        # 保存更新后的数据
        user_events_data.set_value(events)
        
        # 同时更新临时数据（兼容现有逻辑）
        user_temp_events_data, created, result = UserData.get_or_initialize(
            request, new_key="planner", data={
                "dialogue": [],
                "temp_events": [],
                "ai_planning_time": {}
            }
        )
        if user_temp_events_data is not None:
            planner_data = user_temp_events_data.get_value() or {}
            temp_events = planner_data.get("temp_events", [])
            
            for i, event in enumerate(temp_events):
                if event.get('id') == event_id:
                    temp_events[i].update({
                        'start': new_start,
                        'end': new_end,
                        'title': title,
                        'description': description,
                        'importance': importance,
                        'urgency': urgency,
                        'groupID': group_id,
                        'ddl': ddl,
                        'last_modified': last_modified
                    })
                    break
                    
            planner_data["temp_events"] = temp_events
            user_temp_events_data.set_value(planner_data)
        
        return JsonResponse({'status': 'success'})
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'更新事件失败: {str(e)}'
        }, status=500)
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)
