"""
Events管理模块 - 支持RRule重复事件
写在前面：
我觉得大费周章写这些处理函数完全是浪费时间，就应该找点现成实现的
但是反正，我已经写了一大堆情况的处理了，但是真要测试起来的话，总会有一些漏洞，我也只能慢慢打补丁。但说真的，现在的这些 RRule 功能已经足以满足大部分情况了，除非你非得把一个 RRule 系列删来改去的
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
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
import reversion
from core.models import UserData, AgentTransaction

from core.utils.validators import validate_body
from integrated_reminder_manager import IntegratedReminderManager, UserDataStorageBackend
from rrule_engine import RRuleEngine
from logger import logger


def get_django_request(request):
    """
    通过 request 对象，获取原生的 Django HttpRequest 对象
    兼容 Django HttpRequest 和 DRF Request
    因为 UserData.get_or_initialize 函数需要 Django HttpRequest 对象，而 DRF 相关操作产生的是 request 对象
    """
    from rest_framework.request import Request as DRFRequest
    if isinstance(request, DRFRequest):
        return request._request
    return request


def _sync_groups_after_edit(events: List[Dict], series_id: str, user, deleted_event_groups: set = None):
    """
    编辑事件后同步群组数据的辅助函数
    
    参数:
        events: 所有事件列表
        series_id: 受影响的系列ID（可能为空）
        user: 触发编辑的用户
        deleted_event_groups: 被删除事件的群组集合（可选）
    """
    try:
        # 收集所有受影响的群组ID
        affected_groups = set()
        
        # 如果传入了被删除事件的群组，先添加这些
        if deleted_event_groups:
            affected_groups.update(deleted_event_groups)
            logger.info(f"[SYNC] 收集到被删除事件的群组: {deleted_event_groups}")
        
        # 如果有 series_id，检查该系列的所有事件
        if series_id:
            for event in events:
                if event.get('series_id') == series_id:
                    # 收集当前分享的群组
                    shared_to_groups = event.get('shared_to_groups', [])
                    if shared_to_groups:
                        affected_groups.update(shared_to_groups)
                    
                    # 收集之前分享的群组（如果有记录）
                    old_shared_groups = event.get('_old_shared_to_groups', [])
                    if old_shared_groups:
                        affected_groups.update(old_shared_groups)
        
        # 如果有受影响的群组，触发同步
        if affected_groups:
            from .views_share_groups import sync_group_calendar_data
            sync_group_calendar_data(list(affected_groups), user)
            logger.info(f"编辑事件后同步到群组: {affected_groups}")
            
    except Exception as e:
        logger.error(f"同步群组数据失败: {str(e)}")


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
            logger.info(f"Event RRule: {rrule}, is_complex: {needs_next_occurrence}, start_time: {start_time}")
            
            if needs_next_occurrence:
                # 对于复杂重复模式，查找下一个符合条件的时间点
                # 无论是单个还是多个BYDAY值，都需要验证所选日期是否符合规则
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
                # 对于简单重复模式，直接使用用户输入的时间
                actual_start_time = start_time
                logger.info(f"Simple repeat mode, using original time: {actual_start_time}")
            
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
            
            # logger.info(f"[DEBUG] Created main_event with series_id: {series_id}")
            # logger.info(f"[DEBUG] Main event data: {main_event}")
            # logger.info(f"Created recurring event series {series_id} with rrule: {rrule}")
            return main_event
            
        except Exception as e:
            logger.error(f"Failed to create recurring event: {str(e)}")
            raise
    

    
    def _is_complex_rrule(self, rrule_str: str) -> bool:
        """判断是否为复杂的RRule模式，需要查找下一个符合条件的时间点"""
        # 复杂模式包括：BYWEEKDAY（按星期）、BYMONTHDAY（按月的日期）、BYSETPOS（按位置）等
        complex_patterns = ['BYWEEKDAY', 'BYMONTHDAY', 'BYSETPOS', 'BYYEARDAY', 'BYWEEKNO', 'BYDAY']
        return any(pattern in rrule_str for pattern in complex_patterns)
    
    def _find_next_occurrence(self, rrule_str: str, start_time: datetime.datetime) -> Optional[datetime.datetime]:
        """从指定时间开始查找下一个符合RRule条件的时间点"""
        try:
            from dateutil.rrule import rrulestr
            
            # 确保时间是naive datetime，避免时区问题
            if start_time.tzinfo is not None:
                start_time = start_time.replace(tzinfo=None)
            
            # 处理rrule中的UNTIL值，如果包含Z后缀，需要转换为本地时间
            processed_rrule = rrule_str
            if 'UNTIL=' in rrule_str:
                import re
                until_match = re.search(r'UNTIL=([^;]+)', rrule_str)
                if until_match:
                    until_str = until_match.group(1)
                    # 如果UNTIL是UTC格式（以Z结尾），转换为naive格式
                    if until_str.endswith('Z'):
                        # 移除Z后缀，使用naive datetime
                        until_naive = until_str[:-1]
                        processed_rrule = rrule_str.replace(f'UNTIL={until_str}', f'UNTIL={until_naive}')
            
            # 构建完整的RRule字符串用于测试
            full_rrule = f"DTSTART:{start_time.strftime('%Y%m%dT%H%M%S')}\nRRULE:{processed_rrule}"
            
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
        
        # logger.info(f"[DEBUG] auto_generate_missing_instances called with {len(events)} events")
        
        # 获取所有重复系列
        recurring_series = {}
        for event in events:
            series_id = event.get('series_id')
            rrule = event.get('rrule')
            
            # logger.debug(f"Processing event: series_id={series_id}, rrule={rrule}, is_detached={event.get('is_detached', False)}")
            
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
        
        # logger.info(f"[DEBUG] Found {len(recurring_series)} recurring series")
        
        # 检查每个系列是否需要生成新实例
        for series_id, series_data in recurring_series.items():
            # logger.info(f"[DEBUG] Processing series {series_id}")
            series_events = series_data['events']
            rrule = series_data['rrule']
            main_event = series_data['main_event']
            
            if not main_event:
                # logger.warning(f"[DEBUG] No main event found for series {series_id}")
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
                        # 生成足够的实例来达到目标数量
                        remaining_count = count_limit - current_count
                        # 传递较大的max_instances来确保生成足够的实例
                        # 因为generate_event_instances会过滤掉与主事件相同的时间
                        new_instances = self.generate_event_instances(main_event, 365, remaining_count + 5)
                        
                        # 过滤掉已经存在的实例
                        existing_starts = {e['start'] for e in series_events}
                        truly_new_instances = []
                        
                        for instance in new_instances:
                            if instance['start'] not in existing_starts and len(truly_new_instances) < remaining_count:
                                truly_new_instances.append(instance)
                        
                        if truly_new_instances:
                            events.extend(truly_new_instances)
                            new_instances_count += len(truly_new_instances)
                            logger.info(f"Added {len(truly_new_instances)} new instances for COUNT-limited series {series_id} (target: {remaining_count})")
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
                # logger.info(f"Series {series_id} latest event is {days_ahead} days from now")
                
                # 修复逻辑：如果没有足够的未来实例（少于30天或只有主事件），则生成
                if days_ahead < 30 or len(series_events) == 1:
                    # logger.info(f"Series {series_id} (no UNTIL) needs new instances, latest is {days_ahead} days ahead, count: {len(series_events)}")
                    
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
                        # logger.info(f"Added {len(truly_new_instances)} new instances for unlimited series {series_id}")
                else:
                    pass
                    # logger.info(f"Series {series_id} (no UNTIL) is good, latest is {days_ahead} days ahead")
        
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
                instance_end = (instance_time + duration).strftime("%Y-%m-%dT%H:%M:%S")
                
                # 处理ddl：如果主事件有ddl，提取时间部分，并与当前实例的end日期组合
                instance_ddl = ''
                if main_event.get('ddl'):
                    try:
                        main_ddl = main_event['ddl']
                        if 'T' in main_ddl:
                            ddl_time_part = main_ddl.split('T')[1]
                            instance_end_date = instance_end.split('T')[0]
                            instance_ddl = f"{instance_end_date}T{ddl_time_part}"
                        else:
                            instance_ddl = main_event['ddl']
                    except Exception as e:
                        logger.warning(f"Failed to generate ddl for instance: {e}")
                        instance_ddl = ''
                
                instance.update({
                    'id': str(uuid.uuid4()),
                    'start': instance_time.strftime("%Y-%m-%dT%H:%M:%S"),
                    'end': instance_end,
                    'ddl': instance_ddl,
                    'is_main_event': False,
                    'recurrence_id': instance_time.strftime("%Y%m%dT%H%M%S"),
                    'last_modified': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                # logger.debug(f"Generated instance with series_id: {instance.get('series_id')}")
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
                    instance_end = (current_time + duration).strftime("%Y-%m-%dT%H:%M:%S")
                    
                    # 处理ddl：如果主事件有ddl，提取时间部分，并与当前实例的end日期组合
                    instance_ddl = ''
                    if main_event.get('ddl'):
                        try:
                            main_ddl = main_event['ddl']
                            if 'T' in main_ddl:
                                ddl_time_part = main_ddl.split('T')[1]
                                instance_end_date = instance_end.split('T')[0]
                                instance_ddl = f"{instance_end_date}T{ddl_time_part}"
                            else:
                                instance_ddl = main_event['ddl']
                        except Exception as e:
                            logger.warning(f"Failed to generate ddl for DAILY instance: {e}")
                            instance_ddl = ''
                    
                    instance.update({
                        'id': str(uuid.uuid4()),
                        'start': dt_str,
                        'end': instance_end,
                        'ddl': instance_ddl,
                        'is_main_event': False,
                        'recurrence_id': current_time.strftime("%Y%m%dT%H%M%S"),
                        'last_modified': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    # logger.info(f"[DEBUG] Generated instance with series_id: {instance.get('series_id')}")
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
                    instance_end = (current_time + duration).strftime("%Y-%m-%dT%H:%M:%S")
                    
                    # 处理ddl：如果主事件有ddl，提取时间部分，并与当前实例的end日期组合
                    instance_ddl = ''
                    if main_event.get('ddl'):
                        try:
                            main_ddl = main_event['ddl']
                            if 'T' in main_ddl:
                                ddl_time_part = main_ddl.split('T')[1]
                                instance_end_date = instance_end.split('T')[0]
                                instance_ddl = f"{instance_end_date}T{ddl_time_part}"
                            else:
                                instance_ddl = main_event['ddl']
                        except Exception as e:
                            logger.warning(f"Failed to generate ddl for WEEKLY instance: {e}")
                            instance_ddl = ''
                    
                    instance.update({
                        'id': str(uuid.uuid4()),
                        'start': dt_str,
                        'end': instance_end,
                        'ddl': instance_ddl,
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
                            instance_end = (current_time + duration).strftime("%Y-%m-%dT%H:%M:%S")
                            
                            # 处理ddl：如果主事件有ddl，提取时间部分，并与当前实例的end日期组合
                            instance_ddl = ''
                            if main_event.get('ddl'):
                                try:
                                    main_ddl = main_event['ddl']
                                    if 'T' in main_ddl:
                                        ddl_time_part = main_ddl.split('T')[1]
                                        instance_end_date = instance_end.split('T')[0]
                                        instance_ddl = f"{instance_end_date}T{ddl_time_part}"
                                    else:
                                        instance_ddl = main_event['ddl']
                                except Exception as e:
                                    logger.warning(f"Failed to generate ddl for MONTHLY instance: {e}")
                                    instance_ddl = ''
                            
                            instance.update({
                                'id': str(uuid.uuid4()),
                                'start': dt_str,
                                'end': instance_end,
                                'ddl': instance_ddl,
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
                    
                    # 处理ddl：如果主事件有ddl，提取时间部分，并与当前实例的end日期组合
                    instance_ddl = ''
                    if main_event.get('ddl'):
                        try:
                            # 从主事件的ddl中提取时间部分（HH:MM:SS）
                            main_ddl = main_event['ddl']
                            if 'T' in main_ddl:
                                ddl_time_part = main_ddl.split('T')[1]  # 获取时间部分
                                # 从instance_end中提取日期部分
                                instance_end_date = instance_end.split('T')[0]
                                # 组合：当前实例的日期 + 主事件ddl的时间
                                instance_ddl = f"{instance_end_date}T{ddl_time_part}"
                            else:
                                instance_ddl = main_event['ddl']
                        except Exception as e:
                            logger.warning(f"Failed to generate ddl for instance: {e}")
                            instance_ddl = ''
                    
                    new_event.update({
                        'id': str(uuid.uuid4()),
                        'start': instance_start,
                        'end': instance_end,
                        'ddl': instance_ddl,  # 使用计算后的ddl
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
        """修改重复规则 - Events专用实现"""
        if additional_updates is None:
            additional_updates = {}
        
        updated_events = []
        main_event = None
        
        # 找到主事件
        for event in events:
            if (event.get('series_id') == series_id and 
                event.get('is_main_event', False)):
                main_event = event
                break
        
        if not main_event:
            logger.error(f"No main event found for series {series_id}")
            return events
        
        if scope == 'all':
            # 影响整个系列
            for event in events:
                if event.get('series_id') == series_id:
                    if event.get('is_main_event', False):
                        # 更新主事件的规则
                        event['rrule'] = new_rrule
                        if additional_updates:
                            event.update({k: v for k, v in additional_updates.items() if k not in ['start', 'end']})
                        event['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        updated_events.append(event)
                    # 删除所有生成的实例，稍后重新生成
                else:
                    updated_events.append(event)
            
        elif scope == 'from_this':
            # 从指定日期开始修改 - 需要创建新的series
            logger.info(f"Modifying events series {series_id} from {cutoff_time} with new rule: {new_rrule}")
            
            # 标准化时间为naive datetime
            if cutoff_time.tzinfo is not None:
                cutoff_time = cutoff_time.replace(tzinfo=None)
            
            # 1. 截断原来的series到指定时间
            self.rrule_engine.truncate_series_until(series_id, cutoff_time)
            
            # 2. 确定新系列的起始时间
            new_start_time = cutoff_time
            if additional_updates and 'start' in additional_updates:
                try:
                    requested_time = datetime.datetime.fromisoformat(additional_updates['start'])
                    new_start_time = requested_time
                    logger.info(f"Using requested start time {requested_time} as new series start time")
                except:
                    logger.warning(f"Invalid start time format: {additional_updates.get('start')}, using cutoff_time")
            
            # 3. 对于复杂重复模式，查找下一个符合条件的时间点
            needs_adjustment = self._is_complex_rrule(new_rrule)
            if needs_adjustment:
                adjusted_start_time = self._find_next_occurrence(new_rrule, new_start_time)
                if adjusted_start_time:
                    # 使用找到的时间点，但保留原始时间的时分秒
                    original_hour = new_start_time.hour
                    original_minute = new_start_time.minute
                    original_second = new_start_time.second
                    adjusted_start_time = adjusted_start_time.replace(
                        hour=original_hour,
                        minute=original_minute,
                        second=original_second,
                        microsecond=new_start_time.microsecond
                    )
                    new_start_time = adjusted_start_time
                    logger.info(f"Adjusted new series start time to first valid occurrence: {new_start_time}")
            
            # 4. 创建新的series
            new_series_id = self.rrule_engine.create_series(new_rrule, new_start_time)
            logger.info(f"Created new series {new_series_id} for modified rule")
            
            # 5. 先找到cutoff_time时刻或之后的第一个事件（作为模板）
            template_event = None
            first_future_event_time = None
            
            for event in events:
                if event.get('series_id') == series_id:
                    try:
                        event_start = event.get('start', '')
                        if event_start:
                            event_time = datetime.datetime.fromisoformat(event_start)
                            if event_time.tzinfo is not None:
                                event_time = event_time.replace(tzinfo=None)
                            
                            # 找到第一个在cutoff_time或之后的事件
                            if event_time >= cutoff_time:
                                if template_event is None or event_time < first_future_event_time:
                                    template_event = event
                                    first_future_event_time = event_time
                    except:
                        continue
            
            # 如果找不到未来事件，使用main_event作为模板
            if template_event is None:
                template_event = main_event
            
            # 6. 创建新的主事件
            new_main_event = template_event.copy()
            new_end_time = new_start_time + (datetime.datetime.fromisoformat(template_event['end']) - datetime.datetime.fromisoformat(template_event['start']))
            
            # 【关键修复】保存原有的 shared_to_groups（从template_event继承）
            original_shared_groups = template_event.get('shared_to_groups', [])
            
            new_main_event.update({
                'id': str(uuid.uuid4()),
                'series_id': new_series_id,
                'rrule': new_rrule,
                'start': new_start_time.strftime("%Y-%m-%dT%H:%M:%S"),
                'end': new_end_time.strftime("%Y-%m-%dT%H:%M:%S"),
                'is_main_event': True,
                'is_recurring': True,
                'last_modified': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                # 【关键修复】确保继承 shared_to_groups
                'shared_to_groups': original_shared_groups
            })
            
            if additional_updates:
                # 处理additional_updates，排除start/end/rrule/ddl
                filtered_updates = {k: v for k, v in additional_updates.items() 
                                  if k not in ['start', 'end', 'rrule', 'ddl']}
                new_main_event.update(filtered_updates)
                
                # 【关键修复】如果 additional_updates 中没有 shared_to_groups，使用原有的
                if 'shared_to_groups' not in filtered_updates:
                    new_main_event['shared_to_groups'] = original_shared_groups
                
                # 特殊处理ddl：如果有ddl更新，需要使用新的end日期
                if 'ddl' in additional_updates:
                    ddl_value = additional_updates['ddl']
                    if ddl_value and 'T' in ddl_value:
                        # 提取时间部分
                        ddl_time_part = ddl_value.split('T')[1]
                        # 使用新的end日期
                        new_end_str = new_end_time.strftime("%Y-%m-%dT%H:%M:%S")
                        new_end_date = new_end_str.split('T')[0]
                        # 组合：新end的日期 + ddl的时间
                        new_main_event['ddl'] = f"{new_end_date}T{ddl_time_part}"
                    else:
                        new_main_event['ddl'] = ddl_value
            
            updated_events.append(new_main_event)
            logger.info(f"Created new main event {new_main_event['id']} for new series {new_series_id}")
            
            # 7. 处理所有旧系列的事件
            for event in events:
                if event.get('series_id') == series_id:
                    try:
                        event_start = event.get('start', '')
                        if event_start:
                            # 标准化事件时间
                            event_time = datetime.datetime.fromisoformat(event_start)
                            if event_time.tzinfo is not None:
                                event_time = event_time.replace(tzinfo=None)
                        else:
                            continue
                    except:
                        continue
                        
                    if event_time < cutoff_time:
                        # 在修改时间之前的事件：保留在原series中，添加UNTIL限制
                        current_rrule = event.get('rrule', '')
                        until_time = cutoff_time - datetime.timedelta(seconds=1)
                        until_str = until_time.strftime('%Y%m%dT%H%M%S')
                        
                        if 'UNTIL=' in current_rrule.upper():
                            import re
                            updated_rrule = re.sub(r'UNTIL=\d{8}T\d{6}', f'UNTIL={until_str}', current_rrule, flags=re.IGNORECASE)
                            event['rrule'] = updated_rrule
                        else:
                            if current_rrule and not current_rrule.endswith(';'):
                                event['rrule'] = f"{current_rrule};UNTIL={until_str}"
                            else:
                                event['rrule'] = f"{current_rrule}UNTIL={until_str}"
                        
                        event['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        updated_events.append(event)
                        logger.info(f"Updated event {event.get('id')} with UNTIL={until_str}")
                    
                    # 删除所有在cutoff_time及之后的旧实例（会由新系列重新生成）
                    # 不需要else分支，cutoff_time及之后的事件都不加入updated_events
                else:
                    # 不是这个系列的事件，保留
                    updated_events.append(event)
        
        return updated_events


def get_events_manager(request) -> EventsRRuleManager:
    """获取Events RRule管理器实例"""
    return EventsRRuleManager(request)


def get_events_impl(request):
    """获取所有日程和日程组 - 支持RRule处理"""
    if request.method == 'GET':
        # 获取原生 Django request
        django_request = get_django_request(request)
        
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
        user_data, created, result = UserData.get_or_initialize(request=django_request, new_key="events", data=[
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
        user_data_groups, created = UserData.objects.get_or_create(user=django_request.user, key="events_groups", defaults={"value": json.dumps([
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

        # 添加分享信息：标记哪些事件被分享到了哪些群组
        # 导入必要的模型
        from .models import GroupCalendarData, GroupMembership
        
        # 获取用户所属的所有群组
        user_memberships = GroupMembership.objects.filter(user=django_request.user).select_related('share_group')
        
        # 为每个事件添加 shared_groups 字段
        for event in processed_events:
            event_id = event.get('id')
            shared_groups = []
            
            # 检查每个群组是否包含此事件
            for membership in user_memberships:
                try:
                    group_data = GroupCalendarData.objects.get(share_group=membership.share_group)
                    # 检查事件ID是否在群组的事件列表中
                    for group_event in group_data.events_data:
                        if group_event.get('id') == event_id:
                            shared_groups.append({
                                'share_group_id': membership.share_group.share_group_id,
                                'share_group_name': membership.share_group.share_group_name,
                                'share_group_color': membership.share_group.share_group_color
                            })
                            break
                except GroupCalendarData.DoesNotExist:
                    continue
            
            event['shared_groups'] = shared_groups
        
        # 返回事件和日程组数据
        return JsonResponse({"events": processed_events, "events_groups": events_groups})
    
    # 处理非GET请求
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)


@validate_body({
    'title': {'type': str, 'required': True, 'comment': '事件标题'},
    'start': {'type': str, 'required': True, 'comment': '开始时间，格式：YYYY-MM-DDTHH:MM:SS'},
    'end': {'type': str, 'required': True, 'comment': '结束时间，格式：YYYY-MM-DDTHH:MM:SS'},
    'description': {'type': str, 'required': False, 'comment': '事件描述', 'alias': 'context'},
    'importance': {'type': str, 'required': False, 'choices': ['important', 'not-important', ''], 'comment': '重要性标记'},
    'urgency': {'type': str, 'required': False, 'choices': ['urgent', 'not-urgent', ''], 'comment': '紧急性标记'},
    'groupID': {'type': str, 'required': False, 'comment': '所属群组ID', 'alias': 'groupId'},
    'rrule': {'type': str, 'required': False, 'comment': '重复规则字符串', 'alias': 'RRule'},
    'shared_to_groups': {'type': list, 'required': False, 'comment': '分享到的群组ID列表'},
    'ddl': {'type': str, 'required': False, 'comment': '截止时间，格式：YYYY-MM-DDTHH:MM:SS'},
    'session_id': {'type': str, 'required': False, 'comment': 'Agent会话ID，用于回滚'},
})
def create_event_impl(request):
    """创建新的event"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)
        
    django_request = get_django_request(request)  # 获取原生 Django request
    manager = EventsRRuleManager(request.user)
    
    try:
        # 使用 validate_body 处理后的数据
        data = request.validated_data
        session_id = data.get('session_id')
        
        # 开启版本控制
        with reversion.create_revision():
            reversion.set_user(request.user)
            reversion.set_comment(f"Create event: {data.get('title')}")
            
            # 提取事件数据
            event_data = {
                'title': data.get('title'),
                'start': data.get('start'),
                'end': data.get('end'),
                'description': data.get('description', ''),
                'importance': data.get('importance'),
                'urgency': data.get('urgency'),
                'groupID': data.get('groupID'),
                'shared_to_groups': data.get('shared_to_groups', []),  # 新增：分享到的群组列表
            }
            
            # logger.info(f"[DEBUG] create_event_impl - received shared_to_groups: {data.get('shared_to_groups', [])}")
            # logger.info(f"[DEBUG] create_event_impl - event_data: {event_data}")
            
            # 获取用户偏好设置
            user_preference_data, created, result = UserData.get_or_initialize(
                django_request, new_key="user_preference"
            )
            if user_preference_data is None:
                return JsonResponse({'status': 'error', 'message': 'Failed to get user preferences'}, status=500)
            
            user_preference = user_preference_data.get_value() or {}
            
            # 处理DDL - 如果用户传了ddl就使用，否则根据用户设置决定
            ddl_from_request = data.get('ddl', '')
            if ddl_from_request:
                # 用户明确设置了ddl，直接使用
                event_data['ddl'] = ddl_from_request
            elif user_preference.get("auto_ddl", False):
                # 用户未设置ddl，但启用了auto_ddl，使用end时间
                event_data['ddl'] = data.get('end', '')
            else:
                # 用户未设置ddl，且未启用auto_ddl
                event_data['ddl'] = ''
                
            # 处理RRule相关数据
            rrule = data.get('rrule')
            if rrule:
                # 清理 rrule 字符串：移除末尾的分号和空格
                rrule = rrule.strip().rstrip(';')
                # 创建重复事件系列
                main_event = manager.create_recurring_event(event_data, rrule)
                
                # logger.info(f"[DEBUG] main_event returned from create_recurring_event: {main_event}")
                # logger.info(f"[DEBUG] main_event 的 shared_to_groups: {main_event.get('shared_to_groups', 'NOT FOUND')}")
                
                # 将主事件保存到events数据中
                user_events_data, created, result = UserData.get_or_initialize(
                    django_request, new_key="events", data=[]
                )
                if user_events_data is None:
                    return JsonResponse({'status': 'error', 'message': 'Failed to get user events data'}, status=500)

                events = user_events_data.get_value() or []
                if not isinstance(events, list):
                    events = []

                events.append(main_event)
                # logger.info(f"[DEBUG] Added main_event to events array, main_event series_id: {main_event.get('series_id')}")
                
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
                            # RRule引擎会生成所有实例，generate_event_instances会过滤掉主事件
                            # 所以需要传递完整的count值确保总数正确
                            additional_instances = manager.generate_event_instances(main_event, 365, count)
                            events.extend(additional_instances)
                    elif 'UNTIL=' in rrule:
                        # 处理UNTIL限制的重复事件
                        # print(f"[DEBUG] Processing UNTIL event with rrule: {rrule}")
                        # 生成从开始时间到UNTIL时间之间的所有实例
                        # 使用较大的天数范围和实例数量来确保覆盖整个UNTIL期间
                        additional_instances = manager.generate_event_instances(main_event, 365 * 2, 1000)  # 2年范围，最多1000个实例
                        # print(f"[DEBUG] Generated {len(additional_instances)} additional instances for UNTIL event")
                        events.extend(additional_instances)
                    
                    user_events_data.set_value(events)
            else:
                # 创建单次事件
                event_data['id'] = str(uuid.uuid4())
                event_data['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # logger.info(f"[DEBUG] 单次事件 event_data 准备保存: {event_data}")
                # logger.info(f"[DEBUG] 其中 shared_to_groups = {event_data.get('shared_to_groups', 'NOT FOUND')}")
                
                # 保存到events数据中
                user_events_data, created, result = UserData.get_or_initialize(
                    django_request, new_key="events", data=[]
                )
                if user_events_data is None:
                    return JsonResponse({'status': 'error', 'message': 'Failed to get user events data'}, status=500)
                
                events = user_events_data.get_value() or []
                if not isinstance(events, list):
                    events = []
                
                events.append(event_data)
                user_events_data.set_value(events)
                
                # logger.info(f"[DEBUG] 保存后，events 数组中的最后一个事件: {events[-1]}")
                # logger.info(f"[DEBUG] 最后一个事件的 shared_to_groups: {events[-1].get('shared_to_groups', 'NOT FOUND')}")
                
                main_event = event_data
            
            # 新增：如果事件分享到了群组，触发同步
            shared_to_groups = data.get('shared_to_groups', [])
            if shared_to_groups:
                try:
                    from .views_share_groups import sync_group_calendar_data
                    sync_group_calendar_data(shared_to_groups, request.user)
                    logger.info(f"创建事件后同步到群组: {shared_to_groups}")
                except Exception as e:
                    logger.error(f"同步群组数据失败: {str(e)}")
                    # 不影响事件创建，继续返回成功
            
            # 如果提供了 session_id，记录 AgentTransaction
            if session_id:
                try:
                    reversion.add_meta(
                        AgentTransaction,
                        session_id=session_id,
                        action_type="create_event",
                        description=f"Created event: {main_event.get('title')}"
                    )
                    logger.info(f"Recorded AgentTransaction for session {session_id}")
                except Exception as e:
                    logger.error(f"Failed to record AgentTransaction: {e}")

        return JsonResponse({
            'status': 'success',
            'event': main_event
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error', 
            'message': f'创建事件失败: {str(e)}'
        }, status=500)


@validate_body({
    'eventId': {'type': str, 'required': True, 'alias': 'id', 'synonyms': ['uuid', 'event_id', 'eventID'], 'comment': '事件ID。警告：已弃用，建议使用delete_event_impl替代'},
    'delete_scope': {'type': str, 'required': False, 'default': 'single', 'choices': ['single', 'all', 'future'], 'comment': '删除范围：单个、所有、将来。警告：已弃用，建议使用delete_event_impl替代'},
    'series_id': {'type': str, 'required': False, 'comment': '重复事件的系列ID，当delete_scope为all或future时建议提供。警告：已弃用，建议使用delete_event_impl替代'},
})
def delete_event_impl(request):
    """
    已弃用
    删除事件 - 支持RRule删除策略
    """

    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)
        
    try:
        # 使用 validate_body 处理后的数据
        data = request.validated_data
        event_id = data.get('eventId')
        delete_scope = data.get('delete_scope', 'single')  # single, all, future
        
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Invalid data: {str(e)}'}, status=400)
        
    if not event_id:
        return JsonResponse({'status': 'error', 'message': 'eventId is missing'}, status=400)
        
    try:
        # 获取原生 Django request
        django_request = get_django_request(request)
        
        # 获取events数据
        user_events_data, created, result = UserData.get_or_initialize(
            django_request, new_key="events", data=[]
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
                        logger.info(f"[MAIN_EVENT_TRANSFER] Deleting main event {event_id} from series {series_id}, finding replacement...")
                        
                        # 找到系列中的下一个实例作为新的主事件
                        series_events = [e for e in events if e.get('series_id') == series_id]
                        if series_events:
                            # 选择最早的实例作为新主事件
                            series_events.sort(key=lambda x: x['start'])
                            new_main_event = series_events[0]
                            for i, event in enumerate(events):
                                if event.get('id') == new_main_event['id']:
                                    events[i]['is_main_event'] = True
                                    events[i]['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    logger.info(f"[MAIN_EVENT_TRANSFER] Promoted event {new_main_event['id']} (start: {new_main_event['start']}) to main event for series {series_id}")
                                    break
                        else:
                            # 如果没有其他实例，系列被完全删除
                            logger.info(f"[MAIN_EVENT_TRANSFER] No other events in series {series_id}, series will be empty")
                    else:
                        logger.info(f"Deleted single event instance {event_id} (not main event)")
                            
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


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@validate_body({
    'event_id': {'type': str, 'required': True, 'alias': 'id', 'synonyms': ['uuid', 'eventId'], 'comment': '事件的唯一标识符'},
    'operation': {'type': str, 'required': True, 'choices': ['edit', 'delete'], 'comment': '操作类型：编辑或删除'},
    'edit_scope': {'type': str, 'required': True, 'choices': ['single', 'all', 'future', 'from_time'], 'comment': '编辑范围：单个、所有、将来、从指定时间开始'},
    'from_time': {'type': str, 'required': False, 'comment': '当 edit_scope 为 from_time 时必填，格式：YYYY-MM-DDTHH:MM:SS'},
    'series_id': {'type': str, 'required': False, 'comment': '重复事件的系列ID'},
    'title': {'type': str, 'required': False, 'comment': '事件标题'},
    'description': {'type': str, 'required': False, 'comment': '事件描述'},
    'importance': {'type': str, 'required': False, 'choices': ['important', 'not-important', ''], 'comment': '重要性标记，空字符串表示清除'},
    'urgency': {'type': str, 'required': False, 'choices': ['urgent', 'not-urgent', ''], 'comment': '紧急性标记，空字符串表示清除'},
    'start': {'type': str, 'required': False, 'comment': '开始时间，格式：YYYY-MM-DDTHH:MM:SS'},
    'end': {'type': str, 'required': False, 'comment': '结束时间，格式：YYYY-MM-DDTHH:MM:SS'},
    'rrule': {'type': str, 'required': False, 'comment': '重复规则字符串，空字符串表示取消重复'},
    'groupID': {'type': str, 'required': False, 'comment': '所属群组ID'},
    'ddl': {'type': str, 'required': False, 'comment': '截止时间，格式：YYYY-MM-DDTHH:MM:SS，空字符串表示清除'},
    'shared_to_groups': {'type': list, 'required': False, 'comment': '分享到的群组ID列表'},
})
def bulk_edit_events_impl(request):
    """批量编辑事件 - 支持四种编辑模式"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)
    
    import time
    start_time = time.time()
    
    try:
        # 使用 validate_body 处理后的数据
        data = request.validated_data
        
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
            'shared_to_groups': data.get('shared_to_groups'),  # 群组分享
        }
        # 过滤掉None值和空字符串（title/description/ddl/rrule/importance/urgency除外，它们允许为空）
        # ddl允许为空表示清除截止时间
        # rrule允许为空表示取消重复
        # importance/urgency允许为空表示清除重要性/紧急性标记
        updates = {k: v for k, v in updates.items() 
                   if v is not None and (v != '' or k in ['title', 'description', 'ddl', 'rrule', 'importance', 'urgency'])}
        
        # logger.info(f"Bulk edit events - Operation: {operation}, Scope: {edit_scope}, Event ID: {event_id}, Series ID: {series_id}")
        # logger.info(f"[DEBUG] shared_to_groups from request: {data.get('shared_to_groups')}")
        # logger.info(f"[DEBUG] groupID from request: {data.get('groupID')}, type: {type(data.get('groupID'))}")
        # logger.info(f"[DEBUG] ddl from request: {data.get('ddl')}, type: {type(data.get('ddl'))}")
        # logger.info(f"[DEBUG] Filtered updates: {updates}")
        
        # 添加调试信息：检查事件数据结构
        # logger.info(f"[DEBUG] Request data keys: {list(data.keys())}")
        
        if not event_id:
            return JsonResponse({'status': 'error', 'message': '事件ID是必填项'}, status=400)
            
        if edit_scope == 'from_time' and not from_time:
            return JsonResponse({'status': 'error', 'message': '当编辑范围为"从指定时间"时，必须提供起始时间'}, status=400)
        
        # 获取原生 Django request
        django_request = get_django_request(request)
        
        # 获取事件数据
        user_events_data, created, result = UserData.get_or_initialize(
            django_request, new_key="events", data=[]
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
                    # logger.info(f"[DEBUG] Event data: id={event.get('id')}, series_id={event.get('series_id')}, rrule={event.get('rrule')}, is_recurring={event.get('is_recurring')}")
                    break
        
        # # 添加调试信息：最终使用的series_id
        # logger.info(f"[DEBUG] Final series_id to use: {series_id}")
        
        if operation == 'delete':
            # 【关键修复】在删除前先收集受影响的群组
            affected_groups_before_delete = set()
            target_event_for_deletion = None
            
            for event in events:
                if event.get('id') == event_id:
                    target_event_for_deletion = event
                    # 收集被删除事件分享的群组
                    event_shared_groups = event.get('shared_to_groups', [])
                    if event_shared_groups:
                        affected_groups_before_delete.update(event_shared_groups)
                        # logger.info(f"[DELETE_SYNC] 收集到被删除事件 {event_id} 的群组: {event_shared_groups}")
                    break
            
            # 如果是删除系列，收集该系列所有事件的群组
            if edit_scope in ['all', 'future', 'from_time'] and series_id:
                for event in events:
                    if event.get('series_id') == series_id:
                        event_shared_groups = event.get('shared_to_groups', [])
                        if event_shared_groups:
                            affected_groups_before_delete.update(event_shared_groups)
                logger.info(f"[DELETE_SYNC] 收集到系列 {series_id} 的群组: {affected_groups_before_delete}")
            
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
                # 先检查是否删除的是主事件，如果是需要转移主事件标记
                deleted_event_info = None
                for event in events:
                    if event.get('id') == event_id:
                        deleted_event_info = {
                            'was_main_event': event.get('is_main_event', False),
                            'series_id': event.get('series_id', '')
                        }
                        break
                
                updated_events = manager.delete_event_instance(events, event_id, series_id or '')
                
                # 如果删除的是主事件，需要转移主事件标记
                if deleted_event_info and deleted_event_info['was_main_event'] and deleted_event_info['series_id']:
                    logger.info(f"[MAIN_EVENT_TRANSFER] Deleted event {event_id} was main event, finding replacement...")
                    
                    # 找到同系列的其他事件
                    series_events = [e for e in updated_events 
                                    if e.get('series_id') == deleted_event_info['series_id']]
                    
                    if series_events:
                        # 按开始时间排序，选择最早的作为新主日程
                        series_events.sort(key=lambda x: x.get('start', ''))
                        new_main_event_id = series_events[0]['id']
                        
                        # 更新新主日程的标记
                        for evt in updated_events:
                            if evt.get('id') == new_main_event_id:
                                evt['is_main_event'] = True
                                evt['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                logger.info(f"[MAIN_EVENT_TRANSFER] Promoted event {new_main_event_id} (start: {evt.get('start')}) to main event for series {deleted_event_info['series_id']}")
                                break
                    else:
                        logger.warning(f"[MAIN_EVENT_TRANSFER] No other events in series {deleted_event_info['series_id']} after deletion, will generate new main event")
                        
                        # 如果没有其他实例，立即生成下一个实例作为新主事件
                        # 先获取被删除事件的信息
                        deleted_event = None
                        for event in events:
                            if event.get('id') == event_id:
                                deleted_event = event
                                break
                        
                        if deleted_event and deleted_event.get('rrule'):
                            try:
                                # 解析删除事件的时间
                                deleted_start_str = deleted_event.get('start', '')
                                if deleted_start_str:
                                    deleted_start = datetime.datetime.fromisoformat(deleted_start_str)
                                    if deleted_start.tzinfo is not None:
                                        deleted_start = deleted_start.replace(tzinfo=None)
                                    
                                    # 生成下一个实例作为新主事件
                                    logger.info(f"[MAIN_EVENT_TRANSFER] Generating next instance as new main event...")
                                    
                                    # 创建一个临时主事件用于生成
                                    temp_main_event = deleted_event.copy()
                                    temp_main_event['id'] = str(uuid.uuid4())
                                    temp_main_event['is_main_event'] = True
                                    temp_main_event['is_recurring'] = True
                                    temp_main_event['is_detached'] = False
                                    
                                    # 生成1个新实例（下一个）
                                    new_instances = manager.generate_event_instances(
                                        temp_main_event,
                                        start_date=deleted_start + timedelta(days=1),  # 从明天开始
                                        end_date=deleted_start + timedelta(days=90),   # 未来90天
                                        max_instances=1  # 只生成1个
                                    )
                                    
                                    if new_instances:
                                        # 将第一个新实例标记为主事件
                                        new_instances[0]['is_main_event'] = True
                                        updated_events.extend(new_instances)
                                        logger.info(f"[MAIN_EVENT_TRANSFER] Generated new main event {new_instances[0]['id']} (start: {new_instances[0].get('start')})")
                                    else:
                                        logger.error(f"[MAIN_EVENT_TRANSFER] Failed to generate new main event for series {deleted_event_info['series_id']}")
                            except Exception as gen_error:
                                logger.error(f"[MAIN_EVENT_TRANSFER] Error generating new main event: {gen_error}")
                                import traceback
                                traceback.print_exc()
                
                # 直接保存，不调用process_event_data避免自动生成
                user_events_data.set_value(updated_events)
                
                # 【关键修复】删除后同步群组
                if affected_groups_before_delete:
                    try:
                        from .views_share_groups import sync_group_calendar_data
                        sync_group_calendar_data(list(affected_groups_before_delete), request.user)
                        logger.info(f"[DELETE_SYNC] 删除单个事件后同步群组: {affected_groups_before_delete}")
                    except Exception as sync_error:
                        logger.error(f"[DELETE_SYNC] 同步群组失败: {sync_error}")
                
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
                    
                    # 【关键修复】删除后同步群组
                    if affected_groups_before_delete:
                        try:
                            from .views_share_groups import sync_group_calendar_data
                            sync_group_calendar_data(list(affected_groups_before_delete), request.user)
                            logger.info(f"[DELETE_SYNC] 删除整个系列后同步群组: {affected_groups_before_delete}")
                        except Exception as sync_error:
                            logger.error(f"[DELETE_SYNC] 同步群组失败: {sync_error}")
                    
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
                    
                    # 【关键修复】删除后同步群组
                    if affected_groups_before_delete:
                        try:
                            from .views_share_groups import sync_group_calendar_data
                            sync_group_calendar_data(list(affected_groups_before_delete), request.user)
                            logger.info(f"[DELETE_SYNC] 删除此及之后的事件后同步群组: {affected_groups_before_delete}")
                        except Exception as sync_error:
                            logger.error(f"[DELETE_SYNC] 同步群组失败: {sync_error}")
                    
                    return JsonResponse({'status': 'success'})
        
        elif operation == 'edit':
            # 【关键修复】在编辑前先收集受影响的群组
            affected_groups_before_edit = set()
            target_event_for_edit = None
            
            # 找到目标事件并保存旧的群组信息
            for event in events:
                if event.get('id') == event_id:
                    target_event_for_edit = event
                    # 保存旧的群组列表（深拷贝）
                    old_shared_groups = list(event.get('shared_to_groups', []))
                    if old_shared_groups:
                        affected_groups_before_edit.update(old_shared_groups)
                        logger.info(f"[EDIT_SYNC] 收集到编辑前的群组: {old_shared_groups}")
                    
                    # 如果是系列修改，收集该系列所有事件的群组
                    if edit_scope in ['all', 'future', 'from_time'] and event.get('series_id'):
                        series_id_to_collect = event.get('series_id')
                        for evt in events:
                            if evt.get('series_id') == series_id_to_collect:
                                evt_shared_groups = list(evt.get('shared_to_groups', []))
                                if evt_shared_groups:
                                    affected_groups_before_edit.update(evt_shared_groups)
                        logger.info(f"[EDIT_SYNC] 收集到系列的群组: {affected_groups_before_edit}")
                    break
            
            if edit_scope == 'single':
                # 编辑单个事件 - 需要从重复系列中分离
                for event in events:
                    if event.get('id') == event_id:
                        # 检查是否是重复事件的实例
                        was_recurring = event.get('series_id') or event.get('rrule') or event.get('is_recurring')
                        original_series_id = event.get('series_id', '')
                        
                        if was_recurring and original_series_id:
                            # 关键步骤：给原系列添加EXDATE，防止自动生成逻辑补全这个日期
                            
                            # 1. 获取原始事件的时间，用于添加EXDATE
                            target_event_time = None
                            try:
                                start_time_str = event.get('start')
                                if start_time_str:
                                    target_event_time = datetime.datetime.fromisoformat(start_time_str)
                            except Exception as e:
                                logger.error(f"Error parsing event start time: {e}")
                            
                            # 2. 添加EXDATE例外到原系列
                            if target_event_time:
                                manager.rrule_engine.delete_instance(original_series_id, target_event_time)
                                logger.info(f"Added EXDATE for series {original_series_id} at {target_event_time}")
                                
                                # 3. 获取更新后的系列信息，包含EXDATE
                                updated_series = manager.rrule_engine.get_series(original_series_id)
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
                                        
                                        # 4. 更新events数组中所有同系列事件的rrule字段
                                        for evt in events:
                                            if evt.get('series_id') == original_series_id:
                                                evt['rrule'] = updated_rrule
                                                evt['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            
                            # 5. 将UTC时间转换为本地时间格式（如果需要）
                            if 'start' in updates and updates['start']:
                                start_val = updates['start']
                                # 确保 start_val 是字符串类型
                                if isinstance(start_val, str) and start_val.endswith('Z'):
                                    utc_time = datetime.datetime.fromisoformat(start_val.replace('Z', '+00:00'))
                                    local_time = utc_time - timedelta(hours=-8)
                                    updates['start'] = local_time.strftime('%Y-%m-%dT%H:%M:%S')
                            if 'end' in updates and updates['end']:
                                end_val = updates['end']
                                # 确保 end_val 是字符串类型
                                if isinstance(end_val, str) and end_val.endswith('Z'):
                                    utc_time = datetime.datetime.fromisoformat(end_val.replace('Z', '+00:00'))
                                    local_time = utc_time - timedelta(hours=-8)
                                    updates['end'] = local_time.strftime('%Y-%m-%dT%H:%M:%S')
                            
                            # 6. 检查是否是主日程，如果是需要转移主日程标记
                            was_main_event = event.get('is_main_event', False)
                            
                            # 更新事件数据并脱离系列
                            original_rrule = event.get('rrule', '')
                            
                            # 过滤掉空值，避免覆盖原有数据（title/description/importance/urgency/shared_to_groups除外）
                            # importance/urgency允许为空，以便清除重要性和紧急性
                            # shared_to_groups允许为空数组，表示取消分享
                            filtered_updates = {k: v for k, v in updates.items() 
                                                if v != '' or k in ['title', 'description', 'importance', 'urgency', 'shared_to_groups']}
                            
                            # logger.info(f"[DEBUG] Applying filtered_updates to event {event_id}: {filtered_updates}")
                            
                            # 更新事件数据
                            event.update(filtered_updates)
                            event['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            
                            # logger.info(f"[DEBUG] After update, event['shared_to_groups']: {event.get('shared_to_groups')}")
                            
                            # 标记为例外事件,从系列中独立出去
                            event['is_exception'] = True  # 标记为例外
                            event['original_start'] = event.get('start')  # 保存原始时间
                            event['is_detached'] = True  # 标记为已脱离
                            event['rrule'] = ''  # 清除重复规则
                            event['is_recurring'] = False  # 不再是重复事件
                            event['is_main_event'] = False  # 不是主事件
                            event['series_id'] = ''  # 清除系列ID
                            
                            # 保留原始信息供参考
                            event['original_series_id'] = original_series_id
                            event['original_rrule'] = original_rrule
                            event['detached_at'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            
                            logger.info(f"Event {event_id} successfully isolated from series {original_series_id}")
                            
                            # 7. 如果独立的是主日程，需要将系列中的下一个事件提升为新主日程
                            if was_main_event:
                                logger.info(f"[MAIN_EVENT_TRANSFER] Event {event_id} was main event, finding replacement...")
                                
                                # 找到同系列的其他事件
                                series_events = [e for e in events 
                                                if e.get('series_id') == original_series_id 
                                                and e.get('id') != event_id]
                                
                                if series_events:
                                    # 按开始时间排序，选择最早的作为新主日程
                                    series_events.sort(key=lambda x: x.get('start', ''))
                                    new_main_event_id = series_events[0]['id']
                                    
                                    # 更新新主日程的标记
                                    for evt in events:
                                        if evt.get('id') == new_main_event_id:
                                            evt['is_main_event'] = True
                                            evt['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                            logger.info(f"[MAIN_EVENT_TRANSFER] Promoted event {new_main_event_id} (start: {evt.get('start')}) to main event for series {original_series_id}")
                                            break
                                else:
                                    logger.warning(f"[MAIN_EVENT_TRANSFER] No other events in series {original_series_id}, will generate new main event")
                                    
                                    # 如果没有其他实例，立即生成下一个实例作为新主事件
                                    # 获取原始rrule（未分离前的）
                                    if original_rrule:
                                        try:
                                            # 解析当前事件的时间
                                            current_start_str = event.get('start', '')
                                            if current_start_str:
                                                current_start = datetime.datetime.fromisoformat(current_start_str)
                                                if current_start.tzinfo is not None:
                                                    current_start = current_start.replace(tzinfo=None)
                                                
                                                # 生成下一个实例作为新主事件
                                                logger.info(f"[MAIN_EVENT_TRANSFER] Generating next instance as new main event...")
                                                
                                                # 创建一个临时主事件用于生成
                                                temp_main_event = event.copy()
                                                temp_main_event['id'] = str(uuid.uuid4())
                                                temp_main_event['is_main_event'] = True
                                                temp_main_event['is_recurring'] = True
                                                temp_main_event['is_detached'] = False
                                                temp_main_event['series_id'] = original_series_id
                                                temp_main_event['rrule'] = original_rrule
                                                
                                                # 生成1个新实例（下一个）
                                                new_instances = manager.generate_event_instances(
                                                    temp_main_event,
                                                    start_date=current_start + timedelta(days=1),  # 从明天开始
                                                    end_date=current_start + timedelta(days=90),   # 未来90天
                                                    max_instances=1  # 只生成1个
                                                )
                                                
                                                if new_instances:
                                                    # 将第一个新实例标记为主事件
                                                    new_instances[0]['is_main_event'] = True
                                                    events.extend(new_instances)
                                                    logger.info(f"[MAIN_EVENT_TRANSFER] Generated new main event {new_instances[0]['id']} (start: {new_instances[0].get('start')})")
                                                else:
                                                    logger.error(f"[MAIN_EVENT_TRANSFER] Failed to generate new main event for series {original_series_id}")
                                        except Exception as gen_error:
                                            logger.error(f"[MAIN_EVENT_TRANSFER] Error generating new main event: {gen_error}")
                                            import traceback
                                            traceback.print_exc()
                        else:
                            # 非重复事件，直接更新
                            # 过滤掉空值，避免覆盖原有数据（title/description/importance/urgency/shared_to_groups除外）
                            # importance/urgency允许为空，以便清除重要性和紧急性
                            # shared_to_groups允许为空数组，表示取消分享
                            filtered_updates = {k: v for k, v in updates.items() 
                                                if v != '' or k in ['title', 'description', 'importance', 'urgency', 'shared_to_groups']}
                            
                            event.update(filtered_updates)
                            event['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            
                            # 检查是否正在将单个事件转换为重复事件
                            if 'rrule' in updates and updates['rrule'] and 'FREQ=' in updates['rrule']:
                                logger.info(f"Converting single event {event_id} to recurring event with rrule: {updates['rrule']}")
                                
                                # 确保事件有正确的重复事件标志
                                event['is_recurring'] = True
                                event['is_main_event'] = True
                                event['is_detached'] = False
                                event['recurrence_id'] = ''
                                event['parent_event_id'] = ''
                                
                                # 获取或创建series_id
                                series_id = event.get('series_id') or updates.get('series_id')
                                
                                try:
                                    # 解析开始时间
                                    start_time_str = event.get('start', '')
                                    if start_time_str:
                                        event_start_time = datetime.datetime.fromisoformat(start_time_str)
                                        if event_start_time.tzinfo is not None:
                                            event_start_time = event_start_time.replace(tzinfo=None)
                                    else:
                                        event_start_time = datetime.datetime.now()
                                    
                                    # 检查是否需要调整开始时间（对于复杂RRule）
                                    new_rrule = updates['rrule']
                                    needs_adjustment = manager._is_complex_rrule(new_rrule)
                                    if needs_adjustment:
                                        adjusted_start = manager._find_next_occurrence(new_rrule, event_start_time)
                                        if adjusted_start:
                                            # 保留原始时间的时分秒
                                            adjusted_start = adjusted_start.replace(
                                                hour=event_start_time.hour,
                                                minute=event_start_time.minute,
                                                second=event_start_time.second,
                                                microsecond=event_start_time.microsecond
                                            )
                                            event_start_time = adjusted_start
                                            # 更新事件的开始和结束时间
                                            end_time_str = event.get('end', '')
                                            if end_time_str:
                                                end_time = datetime.datetime.fromisoformat(end_time_str)
                                                if end_time.tzinfo is not None:
                                                    end_time = end_time.replace(tzinfo=None)
                                                duration = end_time - datetime.datetime.fromisoformat(event['start'])
                                                event['start'] = adjusted_start.strftime("%Y-%m-%dT%H:%M:%S")
                                                event['end'] = (adjusted_start + duration).strftime("%Y-%m-%dT%H:%M:%S")
                                            logger.info(f"Adjusted start time to first valid occurrence: {event_start_time}")
                                    
                                    # 创建RRule系列（无论是否已有series_id，都要确保RRule引擎中有数据）
                                    if series_id:
                                        # 如果已有series_id，检查RRule引擎中是否存在
                                        existing_series = manager.rrule_engine.get_series(series_id)
                                        if not existing_series:
                                            # RRule引擎中不存在，重新创建
                                            logger.info(f"Series {series_id} not found in RRule engine, creating it")
                                            # 使用已有的series_id创建系列
                                            manager.rrule_engine.create_series(new_rrule, event_start_time)
                                            # 但create_series会生成新的UID，我们需要手动设置
                                            # 这是个问题，暂时使用create_series生成新的series_id
                                            new_series_id = manager.rrule_engine.create_series(new_rrule, event_start_time)
                                            event['series_id'] = new_series_id
                                            logger.info(f"Created new series {new_series_id} (replaced old series_id)")
                                        else:
                                            logger.info(f"Series {series_id} already exists in RRule engine")
                                    else:
                                        # 没有series_id，创建新的
                                        new_series_id = manager.rrule_engine.create_series(new_rrule, event_start_time)
                                        event['series_id'] = new_series_id
                                        logger.info(f"Created new series {new_series_id} for single-to-recurring conversion")
                                    
                                except Exception as create_error:
                                    logger.error(f"Failed to create RRule series: {create_error}")
                                    import traceback
                                    traceback.print_exc()
                                    # 继续处理，即使创建系列失败
                            
                            logger.info(f"Updated single event {event_id}")
                        break
                
                # 检查处理时间
                if time.time() - start_time > 25:
                    user_events_data.set_value(events)
                    return JsonResponse({'status': 'success', 'message': '单个事件修改完成'})
                
                # 处理重复事件数据，确保分离后的原系列能正常生成后续实例
                try:
                    final_events = manager.process_event_data(events)
                    user_events_data.set_value(final_events)
                    
                    # 【关键修复】同步群组数据，传入编辑前收集的群组
                    # 收集编辑后的新群组
                    new_shared_groups = updates.get('shared_to_groups', [])
                    if new_shared_groups:
                        affected_groups_before_edit.update(new_shared_groups)
                    
                    _sync_groups_after_edit(final_events, series_id, request.user, affected_groups_before_edit)
                    
                    return JsonResponse({'status': 'success'})
                except Exception as process_error:
                    logger.error(f"process_event_data failed in single edit: {str(process_error)}")
                    user_events_data.set_value(events)
                    
                    # 即使处理失败，也要同步群组
                    try:
                        new_shared_groups = updates.get('shared_to_groups', [])
                        if new_shared_groups:
                            affected_groups_before_edit.update(new_shared_groups)
                        _sync_groups_after_edit(events, series_id, request.user, affected_groups_before_edit)
                    except:
                        pass
                    
                    return JsonResponse({'status': 'success', 'message': '事件已修改，数据处理可能不完整'})
                
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
                            logger.info(f"Found current event, cutoff_time set to: {cutoff_time}")
                        except:
                            cutoff_time = datetime.datetime.now()
                            logger.warning(f"Failed to parse event start time, using current time: {cutoff_time}")
                    else:
                        cutoff_time = datetime.datetime.now()
                        logger.warning(f"Current event not found, using current time: {cutoff_time}")
                
                if edit_scope == 'all':
                    # 修改整个系列
                    updated_count = 0
                    for event in events:
                        if event.get('series_id') == series_id or event.get('id') == event_id:
                            # 只更新非时间字段，保持原有的start/end时间
                            # 同时过滤空字符串，避免覆盖原有数据（title/description/ddl/rrule/shared_to_groups除外）
                            update_data = {k: v for k, v in updates.items() 
                                           if k not in ['start', 'end', 'ddl'] and 
                                           (v != '' or k in ['title', 'description', 'rrule', 'shared_to_groups'])}
                            
                            # 特殊处理rrule：如果rrule为空，表示取消重复，需要清除相关字段
                            if 'rrule' in updates and updates['rrule'] == '':
                                update_data['rrule'] = ''
                                update_data['is_recurring'] = False
                                update_data['is_main_event'] = False
                                update_data['series_id'] = ''
                                update_data['recurrence_id'] = ''
                                update_data['parent_event_id'] = ''
                                logger.info(f"Clearing recurring fields for event {event.get('id')}")
                            
                            # 特殊处理ddl：如果更新中有ddl，需要重新计算每个实例的ddl
                            if 'ddl' in updates:
                                ddl_value = updates['ddl']
                                if ddl_value and 'T' in ddl_value:
                                    # 提取时间部分
                                    ddl_time_part = ddl_value.split('T')[1]
                                    # 从当前事件的end中提取日期部分
                                    event_end = event.get('end', '')
                                    if event_end and 'T' in event_end:
                                        event_end_date = event_end.split('T')[0]
                                        # 组合：当前事件的日期 + 更新的时间
                                        update_data['ddl'] = f"{event_end_date}T{ddl_time_part}"
                                    else:
                                        update_data['ddl'] = ddl_value
                                else:
                                    # ddl为空或格式不正确，直接使用
                                    update_data['ddl'] = ddl_value
                            
                            event.update(update_data)
                            event['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            updated_count += 1
                    
                    user_events_data.set_value(events)
                    
                    # 【关键修复】同步群组数据，传入编辑前收集的群组
                    new_shared_groups = updates.get('shared_to_groups', [])
                    if new_shared_groups:
                        affected_groups_before_edit.update(new_shared_groups)
                    _sync_groups_after_edit(events, series_id, request.user, affected_groups_before_edit)
                    
                    return JsonResponse({'status': 'success', 'updated_count': updated_count})
                    
                elif edit_scope in ['future', 'from_time']:
                    # 从指定时间开始修改
                    if cutoff_time is None:
                        return JsonResponse({'status': 'error', 'message': '无法确定修改的起始时间'}, status=400)
                    
                    if 'rrule' in updates:
                        logger.info(f"RRule detected in updates: {updates.get('rrule')}")
                        # 检查RRule是否真的发生了变化
                        new_rrule = updates.get('rrule')
                        
                        # 允许空rrule（表示取消重复）
                        # if not new_rrule:
                        #     return JsonResponse({'status': 'error', 'message': 'RRule是必填项'}, status=400)
                        
                        # 找到当前序列的原始RRule进行比较
                        original_rrule = None
                        for event in events:
                            if (event.get('series_id') == series_id and 
                                event.get('rrule')):
                                original_rrule = event.get('rrule')
                                break
                        
                        logger.info(f"Original RRule: {original_rrule}, New RRule: {new_rrule}")
                        
                        # 如果RRule没有变化，按非RRule修改处理
                        if original_rrule and original_rrule == new_rrule:
                            logger.info(f"RRule unchanged for event series {series_id}, treating as non-RRule modification")
                            logger.info(f"Cutoff time: {cutoff_time}, Updates to apply: {updates}")
                            
                            updated_count = 0
                            for event in events:
                                if (event.get('series_id') == series_id and 
                                    event.get('start')):
                                    try:
                                        event_time = datetime.datetime.fromisoformat(event['start'])
                                        # 确保时区一致性 - 统一转换为naive datetime进行比较
                                        if cutoff_time.tzinfo is not None:
                                            # cutoff_time有时区信息，转换为naive
                                            cutoff_time_naive = cutoff_time.replace(tzinfo=None)
                                        else:
                                            cutoff_time_naive = cutoff_time
                                            
                                        if event_time.tzinfo is not None:
                                            # event_time有时区信息，转换为naive  
                                            event_time_naive = event_time.replace(tzinfo=None)
                                        else:
                                            event_time_naive = event_time
                                            
                                        logger.info(f"Checking event {event.get('id')} at {event_time_naive} >= {cutoff_time_naive}: {event_time_naive >= cutoff_time_naive}")
                                        if event_time_naive >= cutoff_time_naive:
                                            # 对于非RRule修改，只更新非时间字段，保持原有的start/end时间
                                            # 同时过滤空字符串，避免覆盖原有数据（title/description/ddl/shared_to_groups除外）
                                            update_data = {k: v for k, v in updates.items() 
                                                           if k not in ['rrule', 'start', 'end', 'ddl'] and 
                                                           (v != '' or k in ['title', 'description', 'shared_to_groups'])}
                                            
                                            # 特殊处理ddl：如果更新中有ddl，需要重新计算每个实例的ddl
                                            if 'ddl' in updates:
                                                ddl_value = updates['ddl']
                                                if ddl_value and 'T' in ddl_value:
                                                    # 提取时间部分
                                                    ddl_time_part = ddl_value.split('T')[1]
                                                    # 从当前事件的end中提取日期部分
                                                    event_end = event.get('end', '')
                                                    if event_end and 'T' in event_end:
                                                        event_end_date = event_end.split('T')[0]
                                                        # 组合：当前事件的日期 + 更新的时间
                                                        update_data['ddl'] = f"{event_end_date}T{ddl_time_part}"
                                                    else:
                                                        update_data['ddl'] = ddl_value
                                                else:
                                                    # ddl为空或格式不正确，直接使用
                                                    update_data['ddl'] = ddl_value
                                            
                                            logger.info(f"Updating event {event.get('id')} with: {update_data}")
                                            event.update(update_data)
                                            event['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                            updated_count += 1
                                    except Exception as e:
                                        logger.error(f"Error processing event {event.get('id', 'unknown')}: {e}")
                            
                            logger.info(f"Updated {updated_count} events in RRule unchanged branch, saving to database")
                            
                            user_events_data.set_value(events)
                            return JsonResponse({'status': 'success', 'updated_count': updated_count})
                        
                        # RRule确实发生了变化
                        logger.info(f"Modifying recurring rule from {cutoff_time} for event series {series_id}")
                        
                        # 特殊处理：如果new_rrule为空，表示取消重复（结束重复系列）
                        # 逻辑：保留当前被选中的这一个日程（转换为单个），删除之后的所有日程
                        if new_rrule == '':
                            logger.info(f"Canceling recurrence from {cutoff_time} for event series {series_id}")
                            logger.info(f"Will keep current event and delete future events")
                            
                            # 确保时区一致性
                            if cutoff_time.tzinfo is not None:
                                cutoff_time_naive = cutoff_time.replace(tzinfo=None)
                            else:
                                cutoff_time_naive = cutoff_time
                            
                            # 找到当前被选中的事件及之后的事件
                            current_event = None
                            events_to_delete = []
                            
                            for event in events:
                                if (event.get('series_id') == series_id and event.get('start')):
                                    try:
                                        event_time = datetime.datetime.fromisoformat(event['start'])
                                        if event_time.tzinfo is not None:
                                            event_time_naive = event_time.replace(tzinfo=None)
                                        else:
                                            event_time_naive = event_time
                                        
                                        # 当前及之后的事件
                                        if event_time_naive >= cutoff_time_naive:
                                            # 第一个遇到的（时间最早的）就是当前事件
                                            if current_event is None:
                                                current_event = event
                                                logger.info(f"Found current event to keep: {event.get('id')} at {event_time_naive}")
                                            else:
                                                # 之后的事件标记为删除
                                                events_to_delete.append(event.get('id'))
                                                logger.info(f"Marking future event for deletion: {event.get('id')} at {event_time_naive}")
                                    except Exception as e:
                                        logger.error(f"Error parsing event time: {e}")
                            
                            # 将当前事件转换为单个日程
                            if current_event:
                                current_event['rrule'] = ''
                                current_event['is_recurring'] = False
                                current_event['is_main_event'] = False
                                current_event['series_id'] = ''
                                current_event['recurrence_id'] = ''
                                current_event['parent_event_id'] = ''
                                current_event['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                logger.info(f"Converted current event to single event")
                            
                            # 删除未来的事件
                            original_count = len(events)
                            events = [e for e in events if e.get('id') not in events_to_delete]
                            deleted_count = original_count - len(events)
                            logger.info(f"Deleted {deleted_count} future events")
                            
                            # 截断RRule系列
                            if series_id:
                                try:
                                    manager.rrule_engine.truncate_series_until(series_id, cutoff_time_naive)
                                    logger.info(f"Truncated series {series_id} until {cutoff_time_naive}")
                                except Exception as truncate_error:
                                    logger.warning(f"Failed to truncate series: {truncate_error}")
                            
                            user_events_data.set_value(events)
                            return JsonResponse({
                                'status': 'success', 
                                'message': f'已结束重复系列，保留当前日程，删除了{deleted_count}个未来日程'
                            })
                        
                        # 否则，RRule改变为新的非空值 - 需要创建新序列
                        
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
                        
                        # 检查处理时间，避免超时
                        if time.time() - start_time > 25:  # 25秒后返回，避免超时
                            logger.warning("批量编辑接近超时，返回成功响应")
                            return JsonResponse({'status': 'success', 'message': '操作正在后台处理中'})
                        
                        # 调用modify_recurring_rule方法，传递额外的更新参数和新的起始时间
                        other_updates = {k: v for k, v in updates.items() if k not in ['rrule']}
                        try:
                            updated_events = manager.modify_recurring_rule(
                                events, series_id, new_start_time, new_rrule, 
                                scope='from_this', additional_updates=other_updates
                            )
                        except Exception as modify_error:
                            logger.error(f"modify_recurring_rule failed: {str(modify_error)}")
                            # 即使modify失败，也要确保有响应
                            return JsonResponse({'status': 'error', 'message': f'修改重复规则失败: {str(modify_error)}'}, status=500)
                        
                        # 处理重复事件数据以确保实例足够
                        # 再次检查处理时间
                        current_time = time.time()
                        if current_time - start_time > 27:  # 27秒后快速返回
                            logger.warning("批量编辑接近超时，保存数据并返回")
                            user_events_data.set_value(updated_events)
                            return JsonResponse({'status': 'success', 'message': '操作已完成，数据正在同步'})
                        
                        try:
                            # 如果时间充足，进行完整的数据处理
                            if current_time - start_time < 20:  # 20秒内进行完整处理
                                final_events = manager.process_event_data(updated_events)
                                user_events_data.set_value(final_events)
                                
                                # 【关键修复】修改rrule后同步群组数据
                                new_shared_groups = updates.get('shared_to_groups', [])
                                if new_shared_groups:
                                    affected_groups_before_edit.update(new_shared_groups)
                                _sync_groups_after_edit(final_events, series_id, request.user, affected_groups_before_edit)
                            else:
                                # 时间不足，只保存基本更新
                                user_events_data.set_value(updated_events)
                                logger.info("时间不足，跳过完整数据处理")
                                
                                # 【关键修复】即使时间不足，也要同步群组数据
                                new_shared_groups = updates.get('shared_to_groups', [])
                                if new_shared_groups:
                                    affected_groups_before_edit.update(new_shared_groups)
                                _sync_groups_after_edit(updated_events, series_id, request.user, affected_groups_before_edit)
                            
                            logger.info(f"Successfully modified recurring rule for event series {series_id}")
                            return JsonResponse({'status': 'success'})
                        except Exception as process_error:
                            logger.error(f"process_event_data failed: {str(process_error)}")
                            # 如果process失败，至少保存updated_events
                            try:
                                user_events_data.set_value(updated_events)
                                
                                # 【关键修复】即使处理失败，也要同步群组数据
                                try:
                                    new_shared_groups = updates.get('shared_to_groups', [])
                                    if new_shared_groups:
                                        affected_groups_before_edit.update(new_shared_groups)
                                    _sync_groups_after_edit(updated_events, series_id, request.user, affected_groups_before_edit)
                                except Exception as sync_error:
                                    logger.error(f"群组同步失败: {sync_error}")
                                
                                return JsonResponse({'status': 'success', 'message': '操作完成，但数据处理可能不完整'})
                            except Exception as save_error:
                                logger.error(f"Even save failed: {str(save_error)}")
                                return JsonResponse({'status': 'error', 'message': '保存数据时出错'}, status=500)
                    
                    else:
                        # 只修改其他字段，不涉及RRule - 直接更新
                        logger.info(f"Modifying non-RRule fields from {cutoff_time} for event series {series_id}")
                        logger.info(f"Updates to apply: {updates}")
                        
                        updated_count = 0
                        for event in events:
                            if (event.get('series_id') == series_id and 
                                event.get('start')):
                                try:
                                    event_time = datetime.datetime.fromisoformat(event['start'])
                                    # 确保时区一致性 - 统一转换为naive datetime进行比较
                                    if cutoff_time.tzinfo is not None:
                                        cutoff_time_naive = cutoff_time.replace(tzinfo=None)
                                    else:
                                        cutoff_time_naive = cutoff_time
                                        
                                    if event_time.tzinfo is not None:
                                        event_time_naive = event_time.replace(tzinfo=None)
                                    else:
                                        event_time_naive = event_time
                                        
                                    logger.info(f"Checking event {event.get('id')} at {event_time_naive} >= {cutoff_time_naive}: {event_time_naive >= cutoff_time_naive}")
                                    if event_time_naive >= cutoff_time_naive:
                                        # 对于非RRule修改，排除start/end字段，保持原有时间
                                        # 同时过滤空字符串，避免覆盖原有数据（title/description/ddl/shared_to_groups除外）
                                        # 注意：rrule已在上面的分支中处理，这里不应该包含rrule
                                        update_data = {k: v for k, v in updates.items() 
                                                       if k not in ['rrule', 'start', 'end', 'ddl'] and 
                                                       (v != '' or k in ['title', 'description', 'shared_to_groups'])}
                                        
                                        # 特殊处理ddl：如果更新中有ddl，需要重新计算每个实例的ddl
                                        if 'ddl' in updates:
                                            ddl_value = updates['ddl']
                                            if ddl_value and 'T' in ddl_value:
                                                # 提取时间部分
                                                ddl_time_part = ddl_value.split('T')[1]
                                                # 从当前事件的end中提取日期部分
                                                event_end = event.get('end', '')
                                                if event_end and 'T' in event_end:
                                                    event_end_date = event_end.split('T')[0]
                                                    # 组合：当前事件的日期 + 更新的时间
                                                    update_data['ddl'] = f"{event_end_date}T{ddl_time_part}"
                                                else:
                                                    update_data['ddl'] = ddl_value
                                            else:
                                                # ddl为空或格式不正确，直接使用
                                                update_data['ddl'] = ddl_value
                                        
                                        logger.info(f"Updating event {event.get('id')} with: {update_data}")
                                        event.update(update_data)
                                        event['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                        updated_count += 1
                                except Exception as e:
                                    logger.error(f"Error processing event {event.get('id', 'unknown')}: {e}")
                        
                        logger.info(f"Updated {updated_count} events, saving to database")
                        user_events_data.set_value(events)
                        
                        # [DEBUG] 保存后验证
                        saved_events = user_events_data.get_value() or []
                        for evt in saved_events:
                            if evt.get('series_id') == series_id:
                                # logger.info(f"[DEBUG] After save - Event {evt.get('id')} shared_to_groups: {evt.get('shared_to_groups')}")
                                break
                        
                        # 【关键修复】同步群组数据，传入编辑前收集的群组
                        new_shared_groups = updates.get('shared_to_groups', [])
                        if new_shared_groups:
                            affected_groups_before_edit.update(new_shared_groups)
                        _sync_groups_after_edit(events, series_id, request.user, affected_groups_before_edit)
                        
                        return JsonResponse({'status': 'success', 'updated_count': updated_count})
        
        # 如果到达这里，说明没有匹配的操作
        logger.warning(f"未匹配的操作: operation={operation}, edit_scope={edit_scope}")
        return JsonResponse({'status': 'error', 'message': f'不支持的操作: {operation} with scope {edit_scope}'}, status=400)
        
    except TimeoutError:
        logger.error("批量编辑事件超时")
        return JsonResponse({'status': 'error', 'message': '操作超时，请稍后重试'}, status=408)
    except json.JSONDecodeError as e:
        logger.error(f"JSON解析错误: {str(e)}")
        return JsonResponse({'status': 'error', 'message': '无效的JSON数据'}, status=400)
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logger.error(f"批量编辑事件失败: {str(e)}")
        logger.error(f"Error traceback: {error_trace}")
        
        # 根据错误类型返回更具体的错误信息
        error_message = str(e).lower()
        if "broken pipe" in error_message or "connectionreset" in error_message or "connectionaborted" in error_message:
            logger.error("检测到连接中断错误 - 可能是响应过大或客户端断开连接")
            return JsonResponse({'status': 'success', 'message': '操作可能已完成，请刷新页面查看结果'}, status=200)
        elif "timeout" in error_message or "timed out" in error_message:
            return JsonResponse({'status': 'error', 'message': '操作超时，请稍后重试'}, status=408)
        elif "memory" in error_message or "out of memory" in error_message:
            logger.error("内存不足错误")
            return JsonResponse({'status': 'error', 'message': '数据量过大，请分批处理'}, status=507)
        else:
            # 确保错误信息不会过长导致响应问题
            truncated_error = str(e)[:500] if len(str(e)) > 500 else str(e)
            return JsonResponse({'status': 'error', 'message': f'批量编辑失败: {truncated_error}'}, status=500)
    finally:
        # 清理资源
        try:
            # 重置信号处理
            pass
        except:
            pass


# RRule专用API函数
def convert_time_format(events):
    """
    解析事件列表，将UTC时间转换为本地时间（减去8小时）。
    :param events: 事件列表，每个事件是一个字典，包含时间信息。
    :return: 转换后的时间列表。
    """
    for event in events:
        # 检查 'start' 和 'end' 时间是否为 UTC 时间（以 'Z' 结尾）
        for key in ['start', 'end']:
            # 确保值存在且是字符串类型
            if key in event and isinstance(event[key], str) and event[key].endswith('Z'):
                # 转换为 datetime 对象并减去8小时
                utc_time = datetime.datetime.fromisoformat(event[key].replace('Z', '+00:00'))
                local_time = utc_time - timedelta(hours=-8)
                # 格式化为本地时间格式
                event[key] = local_time.strftime('%Y-%m-%dT%H:%M')
    return events


@validate_body({
    'eventId': {'type': str, 'required': True, 'alias': 'id', 'synonyms': ['uuid', 'event_id'], 'comment': '事件ID'},
    'newStart': {'type': str, 'required': False, 'alias': 'start', 'comment': '新的开始时间，格式：YYYY-MM-DDTHH:MM'},
    'newEnd': {'type': str, 'required': False, 'alias': 'end', 'comment': '新的结束时间，格式：YYYY-MM-DDTHH:MM'},
    'title': {'type': str, 'required': False, 'comment': '事件标题'},
    'description': {'type': str, 'required': False, 'comment': '事件描述'},
    'importance': {'type': str, 'required': False, 'choices': ['important', 'not-important', ''], 'comment': '重要性标记'},
    'urgency': {'type': str, 'required': False, 'choices': ['urgent', 'not-urgent', ''], 'comment': '紧急性标记'},
    'groupID': {'type': str, 'required': False, 'comment': '所属群组ID', 'alias': 'groupId'},
    'ddl': {'type': str, 'required': False, 'comment': '截止时间，格式：YYYY-MM-DDTHH:MM'},
    'shared_to_groups': {'type': list, 'required': False, 'comment': '分享到的群组ID列表'},
    'rrule': {'type': str, 'required': False, 'comment': '新的重复规则', 'alias': 'RRule'},
    'rrule_change_scope': {'type': str, 'required': False, 'default': 'single', 'choices': ['single', 'all', 'future', 'from_time'], 'comment': '重复规则修改范围'},
    'from_time': {'type': str, 'required': False, 'comment': '当rrule_change_scope为from_time时必填，格式：YYYY-MM-DDTHH:MM'},
})
def update_events_impl(request):
    """更新事件 - 支持RRule修改"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)
        
    try:
        # 使用 validate_body 处理后的数据
        data = request.validated_data
        event_id = data.get('eventId')  # 就这狗屎大小写的，前后端、每个数据类型，都tm不一样
        
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
        shared_to_groups = data.get('shared_to_groups', [])  # 新增：分享到的群组
        last_modified = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # logger.info(f"[DEBUG] update_events_impl - received shared_to_groups: {data.get('shared_to_groups', [])}")
        # logger.info(f"[DEBUG] update_events_impl - title: {title}, description: {description}")
        
        # RRule相关字段
        rrule_change_scope = data.get('rrule_change_scope', 'single')  # single, all, future, from_time
        new_rrule = data.get('rrule')  # 新的RRule规则
        # 清理 rrule 字符串：移除末尾的分号和空格
        if new_rrule:
            new_rrule = new_rrule.strip().rstrip(';')
        from_time = data.get('from_time')  # 从何时开始修改，配合 from_time 模式
        
        manager = EventsRRuleManager(request.user)
        
        # 获取原生 Django request
        django_request = get_django_request(request)
        
        # 获取events数据
        user_events_data, created, result = UserData.get_or_initialize(
            django_request, new_key="events", data=[]
        )
        if user_events_data is None:
            return JsonResponse({'status': 'error', 'message': 'Failed to get user events data'}, status=500)
            
        events = user_events_data.get_value() or []
        if not isinstance(events, list):
            events = []
        events = convert_time_format(events)
        
        # 查找要更新的事件
        target_event = None
        old_shared_to_groups = []  # 【关键修复】在更新前保存旧的群组信息
        for event in events:
            if event.get('id') == event_id:
                target_event = event
                # 立即保存旧的群组列表（深拷贝，避免被后续修改影响）
                old_shared_to_groups = list(event.get('shared_to_groups', []))
                logger.info(f"[SYNC] 保存更新前的群组: {old_shared_to_groups}")
                break
                
        if not target_event:
            return JsonResponse({'status': 'error', 'message': 'Event not found'}, status=404)
            
        # 检查是否是重复事件
        is_recurring = target_event.get('is_recurring', False)
        series_id = target_event.get('series_id')
        
        if is_recurring and series_id:
            # 重复事件的处理
            if rrule_change_scope == 'single':
                # 仅修改单个实例 - 创建例外并独立出去
                # 关键步骤：给原系列添加EXDATE，防止自动生成逻辑补全这个日期
                
                # 1. 获取原始事件的时间，用于添加EXDATE
                target_event_time = None
                try:
                    start_time = target_event.get('start')
                    if start_time:
                        target_event_time = datetime.datetime.fromisoformat(start_time)
                except Exception as e:
                    logger.error(f"Error parsing event start time: {e}")
                
                # 2. 添加EXDATE例外到原系列
                if target_event_time and series_id:
                    manager.rrule_engine.delete_instance(series_id, target_event_time)
                    logger.info(f"Added EXDATE for series {series_id} at {target_event_time}")
                    
                    # 3. 获取更新后的系列信息，包含EXDATE
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
                            
                            # 4. 更新events数组中所有同系列事件的rrule字段
                            for event in events:
                                if event.get('series_id') == series_id:
                                    event['rrule'] = updated_rrule
                                    event['last_modified'] = last_modified
                
                # 5. 创建独立的例外事件（在新时间）
                # 将UTC时间转换为本地时间格式（如果需要）
                formatted_start = new_start
                formatted_end = new_end
                if new_start and isinstance(new_start, str) and new_start.endswith('Z'):
                    utc_time = datetime.datetime.fromisoformat(new_start.replace('Z', '+00:00'))
                    local_time = utc_time - timedelta(hours=-8)
                    formatted_start = local_time.strftime('%Y-%m-%dT%H:%M:%S')
                if new_end and isinstance(new_end, str) and new_end.endswith('Z'):
                    utc_time = datetime.datetime.fromisoformat(new_end.replace('Z', '+00:00'))
                    local_time = utc_time - timedelta(hours=-8)
                    formatted_end = local_time.strftime('%Y-%m-%dT%H:%M:%S')
                
                updated_event = target_event.copy()
                updated_event.update({
                    'start': formatted_start,
                    'end': formatted_end,
                    'title': title,
                    'description': description,
                    'importance': importance,
                    'urgency': urgency,
                    'groupID': group_id,
                    'ddl': ddl,
                    'shared_to_groups': shared_to_groups,  # 新增
                    'last_modified': last_modified,
                    'is_exception': True,  # 标记为例外
                    'original_start': target_event['start'],  # 保存原始时间
                    'original_series_id': series_id,  # 保存原始系列ID（用于追溯）
                    # 将事件从序列中独立出去
                    'series_id': None,  # 移除系列ID
                    'is_recurring': False,  # 标记为非重复事件
                    'is_main_event': False,  # 不是主事件
                    'rrule': None  # 移除RRule规则
                })
                
                # 6. 更新events中的数据
                for i, event in enumerate(events):
                    if event.get('id') == event_id:
                        events[i] = updated_event
                        break
                
                # 注意：由于我们已经给原系列添加了EXDATE，
                # 原位置不会再自动生成实例，所以不需要创建"替换事件"
                logger.info(f"Successfully isolated event {event_id} from series {series_id}")
                        
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
                            'shared_to_groups': shared_to_groups,  # 新增
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
                                'shared_to_groups': shared_to_groups,  # 新增
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
                                'shared_to_groups': shared_to_groups,  # 新增
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
                                    'shared_to_groups': shared_to_groups,  # 新增
                                    'last_modified': last_modified
                                })
        else:
            # 单次事件的处理
            # 将UTC时间转换为本地时间格式（如果需要）
            formatted_start = new_start
            formatted_end = new_end
            if new_start and isinstance(new_start, str) and new_start.endswith('Z'):
                utc_time = datetime.datetime.fromisoformat(new_start.replace('Z', '+00:00'))
                local_time = utc_time - timedelta(hours=-8)
                formatted_start = local_time.strftime('%Y-%m-%dT%H:%M:%S')
            if new_end and isinstance(new_end, str) and new_end.endswith('Z'):
                utc_time = datetime.datetime.fromisoformat(new_end.replace('Z', '+00:00'))
                local_time = utc_time - timedelta(hours=-8)
                formatted_end = local_time.strftime('%Y-%m-%dT%H:%M:%S')
            
            updated_event = None
            for i, event in enumerate(events):
                if event.get('id') == event_id:
                    events[i].update({
                        'start': formatted_start,
                        'end': formatted_end,
                        'title': title,
                        'description': description,
                        'importance': importance,
                        'urgency': urgency,
                        'groupID': group_id,
                        'ddl': ddl,
                        'shared_to_groups': shared_to_groups,  # 新增
                        'last_modified': last_modified
                    })
                    updated_event = events[i]  # 保存更新后的事件引用
                    
                    # 如果添加了RRule，转换为重复事件
                    if new_rrule:
                        # 清理 rrule 字符串：移除末尾的分号
                        new_rrule = new_rrule.strip().rstrip(';')
                        logger.info(f"Converting single event {event_id} to recurring with rrule: {new_rrule}")
                        
                        # 解析开始时间
                        try:
                            start_time = datetime.datetime.fromisoformat(new_start)
                            if start_time.tzinfo is not None:
                                start_time = start_time.replace(tzinfo=None)
                        except:
                            start_time = datetime.datetime.now()
                        
                        # 检查是否需要调整开始时间（对于复杂RRule）
                        needs_adjustment = manager._is_complex_rrule(new_rrule)
                        if needs_adjustment:
                            adjusted_start = manager._find_next_occurrence(new_rrule, start_time)
                            if adjusted_start:
                                # 保留原始时间的时分秒
                                adjusted_start = adjusted_start.replace(
                                    hour=start_time.hour,
                                    minute=start_time.minute,
                                    second=start_time.second,
                                    microsecond=start_time.microsecond
                                )
                                start_time = adjusted_start
                                # 更新事件的开始和结束时间
                                try:
                                    end_time = datetime.datetime.fromisoformat(new_end)
                                    if end_time.tzinfo is not None:
                                        end_time = end_time.replace(tzinfo=None)
                                    duration = end_time - datetime.datetime.fromisoformat(new_start)
                                    new_start = adjusted_start.strftime("%Y-%m-%dT%H:%M:%S")
                                    new_end = (adjusted_start + duration).strftime("%Y-%m-%dT%H:%M:%S")
                                    events[i]['start'] = new_start
                                    events[i]['end'] = new_end
                                except:
                                    pass
                                logger.info(f"Adjusted start time to first valid occurrence: {start_time}")
                        
                        # 创建RRule系列
                        series_id = manager.rrule_engine.create_series(new_rrule, start_time)
                        logger.info(f"Created RRule series {series_id} in engine")
                        
                        # 验证系列是否成功创建
                        verify_series = manager.rrule_engine.get_series(series_id)
                        if verify_series:
                            logger.info(f"Verified: Series {series_id} exists in RRule engine")
                        else:
                            logger.error(f"Failed to verify series {series_id} - series not found in engine!")
                        
                        events[i].update({
                            'rrule': new_rrule,
                            'is_recurring': True,
                            'series_id': series_id,
                            'is_main_event': True
                        })
                        
                        # 生成重复实例
                        main_event = events[i]
                        
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
                                    # 传递完整的count值确保总数正确
                                    new_instances = manager.generate_event_instances(main_event, 365, count)
                                    events.extend(new_instances)
                                    logger.info(f"Generated {len(new_instances)} instances for COUNT-limited recurring event")
                            elif 'UNTIL=' in new_rrule:
                                # 使用较大的max_instances参数确保覆盖整个UNTIL期间
                                new_instances = manager.generate_event_instances(main_event, 365 * 2, 1000)
                                events.extend(new_instances)
                                logger.info(f"Generated {len(new_instances)} instances for UNTIL-limited recurring event")
                    
                    updated_event = events[i]
                    break
        
        # 保存更新后的数据
        user_events_data.set_value(events)
        
        # 同时更新临时数据（兼容现有逻辑）
        user_temp_events_data, created, result = UserData.get_or_initialize(
            django_request, new_key="planner", data={
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
        
        # 新增：同步群组数据
        try:
            # 收集受影响的群组
            affected_groups = set()
            
            # ✅ 关键修复：使用保存的旧群组列表（而不是从 target_event 获取）
            # 1. 收集更新前的群组（从我们在函数开头保存的变量）
            if old_shared_to_groups:
                affected_groups.update(old_shared_to_groups)
                logger.info(f"[SYNC] 收集到更新前的群组: {old_shared_to_groups}")
            
            # 2. 收集更新后的群组（从请求数据）
            new_shared_groups = data.get('shared_to_groups', [])
            if new_shared_groups:
                affected_groups.update(new_shared_groups)
                logger.info(f"[SYNC] 收集到更新后的群组: {new_shared_groups}")
            
            # 3. 如果是重复事件的批量修改，还需要检查整个系列的其他实例
            if is_recurring and series_id and rrule_change_scope in ['all', 'future', 'from_time']:
                for event in events:
                    if event.get('series_id') == series_id:
                        event_shared_groups = event.get('shared_to_groups', [])
                        if event_shared_groups:
                            affected_groups.update(event_shared_groups)
            
            # 触发同步
            if affected_groups:
                from .views_share_groups import sync_group_calendar_data
                sync_group_calendar_data(list(affected_groups), request.user)
                logger.info(f"[SYNC] update_events 后同步到群组: {affected_groups}")
            else:
                logger.info(f"[SYNC] update_events - 没有受影响的群组，跳过同步")
                
        except Exception as sync_error:
            logger.error(f"同步群组数据失败: {str(sync_error)}")
            # 不影响事件更新，继续返回成功
        
        return JsonResponse({'status': 'success'})
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'更新事件失败: {str(e)}'
        }, status=500)

