"""
基于现有提醒系统的 RRule 集成实现
解决您提到的自动补回删除提醒的问题，并提供完整的重复提醒生命周期管理
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import json
import uuid
import logging

# 导入我们的 RRule 引擎
from rrule_engine import RRuleEngine

# 尝试导入 dateutil，用于 RRule 处理
try:
    from dateutil.rrule import rrulestr
    HAS_DATEUTIL = True
except ImportError:
    HAS_DATEUTIL = False

logger = logging.getLogger("logger")


# class MemoryStorageBackend:
#     """内存存储后端 - 仅用于向后兼容"""
#
#     def __init__(self):
#         self._storage = {}
#
#     def save_segments(self, uid: str, segments_data: List[Dict[str, Any]]):
#         self._storage[uid] = segments_data
#
#     def load_segments(self, uid: str) -> Optional[List[Dict[str, Any]]]:
#         return self._storage.get(uid)
#
#     def delete_segments(self, uid: str):
#         if uid in self._storage:
#             del self._storage[uid]


class UserDataStorageBackend:
    """基于UserData的持久化存储后端"""
    
    def __init__(self, request):
        self.request = request
        self.storage_key = "rrule_series_storage"  # 统一的存储键
    
    def save_segments(self, uid: str, segments_data: List[Dict[str, Any]]):
        """保存规则段数据到UserData"""
        from core.models import UserData
        
        # 使用正确的UserData方法获取或初始化数据
        user_data, created, result_info = UserData.get_or_initialize(self.request, self.storage_key)
        if user_data is None:
            logger.error(f"Failed to initialize UserData for key {self.storage_key}: {result_info}")
            return
        
        # 获取当前存储的数据
        current_data = user_data.get_value()
        
        # 确保有segments字段
        if "segments" not in current_data:
            current_data["segments"] = []
        
        # 更新或添加段数据
        segments = current_data["segments"]
        
        # 移除同一uid的旧数据
        segments = [s for s in segments if s.get("uid") != uid]
        
        # 添加新的段数据
        for segment in segments_data:
            segments.append(segment)
        
        current_data["segments"] = segments
        
        # 保存回UserData
        user_data.set_value(current_data)
        logger.info(f"Saved {len(segments_data)} segments for uid {uid}")
    
    def load_segments(self, uid: str) -> Optional[List[Dict[str, Any]]]:
        """从UserData加载规则段数据"""
        from core.models import UserData
        
        # 使用正确的UserData方法获取数据
        user_data, created, result_info = UserData.get_or_initialize(self.request, self.storage_key)
        if user_data is None:
            logger.error(f"Failed to initialize UserData for key {self.storage_key}: {result_info}")
            return None
        
        # 获取存储的数据
        current_data = user_data.get_value()
        segments = current_data.get("segments", [])
        
        # 过滤出指定uid的段数据
        uid_segments = [s for s in segments if s.get("uid") == uid]
        
        if uid_segments:
            logger.info(f"Loaded {len(uid_segments)} segments for uid {uid}")
            return uid_segments
        else:
            logger.info(f"No segments found for uid {uid}")
            return None
    
    def delete_segments(self, uid: str):
        """删除指定uid的规则段数据"""
        from core.models import UserData
        
        # 使用正确的UserData方法获取数据
        user_data, created, result_info = UserData.get_or_initialize(self.request, self.storage_key)
        if user_data is None:
            logger.error(f"Failed to initialize UserData for key {self.storage_key}: {result_info}")
            return
        
        # 获取当前存储的数据
        current_data = user_data.get_value()
        segments = current_data.get("segments", [])
        
        # 过滤掉指定uid的段数据
        original_count = len(segments)
        current_data["segments"] = [s for s in segments if s.get("uid") != uid]
        deleted_count = original_count - len(current_data["segments"])
        
        # 保存回UserData
        user_data.set_value(current_data)
        logger.info(f"Deleted {deleted_count} segments for uid {uid}")
    
    def save_exception(self, series_id: str, exception_date: str, exception_type: str, new_data: Optional[Dict] = None):
        """保存异常数据到UserData"""
        from core.models import UserData
        
        # 使用正确的UserData方法获取或初始化数据
        user_data, created, result_info = UserData.get_or_initialize(self.request, self.storage_key)
        if user_data is None:
            logger.error(f"Failed to initialize UserData for key {self.storage_key}: {result_info}")
            return
        
        # 获取当前存储的数据
        current_data = user_data.get_value()
        
        # 确保有exceptions字段
        if "exceptions" not in current_data:
            current_data["exceptions"] = []
        
        # 创建异常记录
        exception_record = {
            "series_id": series_id,
            "exception_date": exception_date,
            "type": exception_type,
            "new_data": new_data or {}
        }
        
        # 检查是否已有相同的异常记录
        exceptions = current_data["exceptions"]
        existing_exception = None
        for i, exc in enumerate(exceptions):
            if exc["series_id"] == series_id and exc["exception_date"] == exception_date:
                existing_exception = i
                break
        
        if existing_exception is not None:
            # 更新现有异常
            exceptions[existing_exception] = exception_record
            logger.info(f"Updated exception for series {series_id} on {exception_date}")
        else:
            # 添加新异常
            exceptions.append(exception_record)
            logger.info(f"Added new exception for series {series_id} on {exception_date}")
        
        current_data["exceptions"] = exceptions
        
        # 保存回UserData
        user_data.set_value(current_data)
    
    def load_exceptions(self, series_id: str) -> List[Dict[str, Any]]:
        """加载指定系列的所有异常"""
        from core.models import UserData
        
        # 使用正确的UserData方法获取数据
        user_data, created, result_info = UserData.get_or_initialize(self.request, self.storage_key)
        if user_data is None:
            logger.error(f"Failed to initialize UserData for key {self.storage_key}: {result_info}")
            return []
        
        # 获取存储的数据
        current_data = user_data.get_value()
        exceptions = current_data.get("exceptions", [])
        
        # 过滤出指定系列的异常
        series_exceptions = [exc for exc in exceptions if exc["series_id"] == series_id]
        
        logger.info(f"Loaded {len(series_exceptions)} exceptions for series {series_id}")
        return series_exceptions


class IntegratedReminderManager:
    """集成的提醒管理器 - 解决RRule重复提醒的生命周期问题"""
    
    def __init__(self, request):
        # 初始化 RRule 引擎，使用持久化存储
        self.rrule_engine = RRuleEngine(UserDataStorageBackend(request))
        self.user = request.user
        # elif user:
        #     # 向后兼容，但需要创建一个模拟request对象
        #     class MockRequest:
        #         def __init__(self, user):
        #             self.user = user
        #     mock_request = MockRequest(user)
        #     self.rrule_engine = RRuleEngine(UserDataStorageBackend(mock_request))
        #     self.user = user
        # else:
        #     # 完全向后兼容，但会丢失例外信息
        #     self.rrule_engine = RRuleEngine(MemoryStorageBackend())
        #     self.user = None
        
        # 配置参数
        self.default_future_days = 365
        self.min_future_instances = 10
        self.max_instances_per_generation = 50
    
    def process_reminder_data(self, user_reminders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        处理用户的提醒数据，确保重复提醒有足够的实例
        这是核心函数，解决自动补回删除提醒的问题
        """
        print(f"DEBUG: process_reminder_data called with {len(user_reminders)} reminders")
        
        # 1. 分析现有的重复提醒系列
        series_info = self._analyze_recurring_series(user_reminders)
        print(f"DEBUG: Found {len(series_info)} recurring series")
        
        # 2. 检查每个系列是否需要补充实例
        updated_reminders = user_reminders.copy()
        
        for series_id, info in series_info.items():
            print(f"DEBUG: Checking series {series_id}")
            if self._needs_more_instances(info):
                print(f"DEBUG: Series {series_id} needs more instances, generating...")
                # 生成新的实例
                new_instances = self._generate_instances_for_series(info)
                print(f"DEBUG: Generated {len(new_instances)} new instances for series {series_id}")
                updated_reminders.extend(new_instances)
                
                logger.info(f"Generated {len(new_instances)} new instances for series {series_id}")
            else:
                print(f"DEBUG: Series {series_id} has enough instances")
        
        print(f"DEBUG: Returning {len(updated_reminders)} total reminders")
        return updated_reminders
    
    def create_recurring_reminder(self, reminder_data: Dict[str, Any], rrule_str: str) -> Dict[str, Any]:
        """创建新的重复提醒"""
        # 解析开始时间
        start_time_str = reminder_data.get('trigger_time', '')
        try:
            start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
        except:
            start_time = datetime.now()
        
        # 在 RRule 引擎中创建系列 - 只调用一次
        series_id = self.rrule_engine.create_series(rrule_str, start_time)
        
        # 更新提醒数据
        reminder_data.update({
            'id': str(uuid.uuid4()),
            'series_id': series_id,  # 使用引擎返回的系列ID
            'rrule': rrule_str,
            'is_recurring': True,
            'is_main_reminder': True,  # 标记为主提醒
            'created_at': datetime.now().isoformat(),
            'last_modified': datetime.now().isoformat()
        })
        
        logger.info(f"Created recurring reminder with series_id: {series_id}")
        return reminder_data
    
    def delete_reminder_instance(self, user_reminders: List[Dict[str, Any]], 
                               reminder_id: str, series_id: str) -> List[Dict[str, Any]]:
        """
        删除提醒实例，记录删除信息防止自动补回
        这是解决您提到问题的关键函数
        """
        updated_reminders = []
        deleted_reminder = None
        
        for reminder in user_reminders:
            if reminder.get('id') == reminder_id:
                deleted_reminder = reminder
                # 不添加到更新列表中，相当于删除
                continue
            updated_reminders.append(reminder)
        
        if deleted_reminder and series_id:
            # 在RRule引擎中记录例外，防止重新生成
            trigger_time_str = deleted_reminder.get('trigger_time', '')
            try:
                trigger_time = datetime.fromisoformat(trigger_time_str.replace('Z', '+00:00'))
                self.rrule_engine.delete_instance(series_id, trigger_time)
                logger.info(f"Added exception for deleted reminder at {trigger_time}")
            except Exception as e:
                logger.warning(f"Failed to add exception for deleted reminder: {e}")
        
        return updated_reminders
    
    def delete_reminder_this_and_after(self, user_reminders: List[Dict[str, Any]], 
                                     reminder_id: str, series_id: str) -> List[Dict[str, Any]]:
        """
        删除此提醒及之后的所有提醒（使用UNTIL截断）
        """
        logger.info(f"Delete reminder at {reminder_id}")
        updated_reminders = []
        target_reminder = None
        
        # 找到目标提醒
        for reminder in user_reminders:
            if reminder.get('id') == reminder_id:
                target_reminder = reminder
                break
        
        if not target_reminder or not series_id:
            return user_reminders
        
        try:
            # 获取目标提醒的时间
            trigger_time_str = target_reminder.get('trigger_time', '')
            trigger_time = datetime.fromisoformat(trigger_time_str.replace('Z', '+00:00'))
            
            # 在RRule引擎中截断系列
            self.rrule_engine.truncate_series_until(series_id, trigger_time)
            logger.info(f"Truncated series {series_id} until {trigger_time}")
            
            # 更新数据库中的提醒数据
            for reminder in user_reminders:
                if reminder.get('series_id') == series_id:
                    reminder_time_str = reminder.get('trigger_time', '')
                    try:
                        reminder_time = datetime.fromisoformat(reminder_time_str.replace('Z', '+00:00'))
                        
                        # 只保留在截断时间之前的提醒
                        if reminder_time < trigger_time:
                            # 更新此系列所有提醒的RRule字符串，添加UNTIL限制
                            current_rrule = reminder.get('rrule', '')
                            # TODO 当我对设定了截止时间的提醒执行”删除此及以后“操作时，这里的的代码并不会更改它们的截止时间
                            #   但是它们也并没有补全，因为
                            #   if has_until:
                            #       print(f"DEBUG: Series {series_id} (with UNTIL) has {future_instances} future instances, latest is {days_ahead} days ahead")
                            #       对于有截止时间的系列，如果还有未来实例就不需要生成更多
                            #       return False
                            #   这段代码。emmm……
                            if 'UNTIL=' in current_rrule.upper():
                                # 如果已有UNTIL，替换为新的（更早的）截止时间
                                # UNTIL应该设置为触发时间前一秒，确保触发时间点的提醒也被排除
                                import re
                                until_time = trigger_time - timedelta(seconds=1)
                                new_until_str = until_time.strftime('%Y%m%dT%H%M%S')
                                updated_rrule = re.sub(r'UNTIL=\d{8}T\d{6}', f'UNTIL={new_until_str}', current_rrule, flags=re.IGNORECASE)
                                reminder['rrule'] = updated_rrule
                                logger.info(f"Updated reminder {reminder.get('id', 'unknown')} RRule UNTIL to {new_until_str}")
                            else:
                                # 如果没有UNTIL，添加新的截止时间
                                until_time = trigger_time - timedelta(seconds=1)
                                until_str = until_time.strftime('%Y%m%dT%H%M%S')
                                if ';' in current_rrule:
                                    reminder['rrule'] = f"{current_rrule};UNTIL={until_str}"
                                else:
                                    reminder['rrule'] = f"{current_rrule};UNTIL={until_str}"
                                logger.info(f"Added UNTIL={until_str} to reminder {reminder.get('id', 'unknown')} RRule")
                            
                            updated_reminders.append(reminder)
                        # 在截断时间之后的提醒都被删除（不添加到updated_reminders）
                    except Exception as e:
                        logger.warning(f"Failed to parse reminder time: {e}")
                        # 如果无法解析时间，保留这个提醒
                        updated_reminders.append(reminder)
                else:
                    # 不属于这个系列的提醒直接保留
                    updated_reminders.append(reminder)
            
        except Exception as e:
            logger.error(f"Failed to truncate series {series_id}: {e}")
            return user_reminders
        
        return updated_reminders
    
    def modify_recurring_rule(self, user_reminders: List[Dict[str, Any]], 
                            series_id: str, from_date: datetime, 
                            new_rrule: str, scope: str = 'from_this',
                            additional_updates: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """修改重复规则"""
        updated_reminders = []
        main_reminder = None
        
        # 找到主提醒
        for reminder in user_reminders:
            if (reminder.get('series_id') == series_id and 
                reminder.get('is_main_reminder', False)):
                main_reminder = reminder
                break
        
        if not main_reminder:
            return user_reminders
        
        if scope == 'all':
            # 影响整个系列
            for reminder in user_reminders:
                if reminder.get('series_id') == series_id:
                    if reminder.get('is_main_reminder', False):
                        # 更新主提醒的规则
                        reminder['rrule'] = new_rrule
                        reminder['last_modified'] = datetime.now().isoformat()
                        updated_reminders.append(reminder)
                    # 删除所有生成的实例，稍后重新生成
                else:
                    updated_reminders.append(reminder)
            
            # 重新生成所有实例
            series_info = {
                'series_id': series_id,
                'main_reminder': main_reminder,
                'rrule': new_rrule,
                'instances': []
            }
            new_instances = self._generate_instances_for_series(series_info)
            updated_reminders.extend(new_instances)
            
        elif scope == 'from_this':
            # 从指定日期开始修改 - 需要创建新的series
            logger.info(f"Modifying series {series_id} from {from_date} with new rule: {new_rrule}")
            logger.info(f"Additional updates: {additional_updates}")
            
            # 1. 截断原来的series到指定时间
            self.rrule_engine.truncate_series_until(series_id, from_date)
            
            # 2. 创建新的series用于修改后的规则
            new_series_id = self.rrule_engine.create_series(new_rrule, from_date)
            logger.info(f"Created new series {new_series_id} for modified rule")
            
            # 3. 处理所有提醒
            for reminder in user_reminders:
                if reminder.get('series_id') == series_id:
                    try:
                        reminder_time = datetime.fromisoformat(
                            reminder.get('trigger_time', '').replace('Z', '+00:00')
                        )
                        
                        if reminder_time < from_date:
                            # 在修改时间之前的提醒：保留在原series中，添加UNTIL限制
                            # 更新此序列所有提醒的RRule字符串，添加或更新UNTIL限制
                            current_rrule = reminder.get('rrule', '')
                            until_time = from_date - timedelta(seconds=1)
                            until_str = until_time.strftime('%Y%m%dT%H%M%S')
                            
                            if 'UNTIL=' in current_rrule.upper():
                                # 如果已有UNTIL，替换为新的（更早的）截止时间
                                import re
                                updated_rrule = re.sub(r'UNTIL=\d{8}T\d{6}', f'UNTIL={until_str}', current_rrule, flags=re.IGNORECASE)
                                reminder['rrule'] = updated_rrule
                                logger.info(f"Updated reminder {reminder.get('id', 'unknown')} RRule UNTIL to {until_str}")
                            else:
                                # 如果没有UNTIL，添加新的截止时间
                                if ';' in current_rrule:
                                    reminder['rrule'] = f"{current_rrule};UNTIL={until_str}"
                                else:
                                    reminder['rrule'] = f"{current_rrule};UNTIL={until_str}"
                                logger.info(f"Added UNTIL={until_str} to reminder {reminder.get('id', 'unknown')} RRule")
                            
                            # 特殊处理主提醒
                            if reminder.get('is_main_reminder', False):
                                logger.info(f"Updated original main reminder with UNTIL={until_str}")
                            
                            reminder['last_modified'] = datetime.now().isoformat()
                            updated_reminders.append(reminder)
                            
                        else:
                            # 在修改时间之后的提醒：分配到新series，创建新的主提醒
                            is_first_modified = (reminder_time == from_date)
                            
                            if is_first_modified:
                                # 这是第一个被修改的提醒，但需要检查是否符合新的RRule
                                logger.info(f"Processing first modified reminder at {from_date}")
                                
                                # 检查指定的时间是否符合新的RRule
                                should_keep_original_time = True
                                actual_start_time = from_date
                                
                                # 检查是否有新的trigger_time需要应用
                                if additional_updates and 'trigger_time' in additional_updates:
                                    try:
                                        requested_time = datetime.fromisoformat(additional_updates['trigger_time'])
                                        actual_start_time = requested_time
                                        logger.info(f"Using requested trigger_time {requested_time} as start time")
                                    except:
                                        logger.warning(f"Invalid trigger_time format, using from_date")
                                
                                # 使用RRule检查actual_start_time是否符合新规则
                                try:
                                    if HAS_DATEUTIL:
                                        # 创建一个测试RRule来检查时间是否符合
                                        test_rrule = rrulestr(new_rrule, dtstart=actual_start_time)
                                        
                                        # 检查actual_start_time是否在规则的第一个实例中
                                        first_occurrence = next(iter(test_rrule), None)
                                        if first_occurrence:
                                            # 比较时间（忽略秒和微秒）
                                            actual_time_normalized = actual_start_time.replace(second=0, microsecond=0)
                                            first_time_normalized = first_occurrence.replace(second=0, microsecond=0)
                                            
                                            if actual_time_normalized != first_time_normalized:
                                                should_keep_original_time = False
                                                actual_start_time = first_occurrence
                                                logger.info(f"Original time {actual_start_time} doesn't match RRule, using first occurrence: {first_occurrence}")
                                            else:
                                                logger.info(f"Original time {actual_start_time} matches RRule first occurrence")
                                        else:
                                            logger.warning(f"No occurrences found for RRule: {new_rrule}")
                                            should_keep_original_time = False
                                            # 删除这个提醒，不符合新规则
                                            continue
                                    else:
                                        logger.warning("dateutil not available, cannot validate RRule")
                                        
                                except Exception as e:
                                    logger.warning(f"Failed to validate time against RRule: {e}")
                                    # 如果验证失败，保守地保留原时间
                                    pass
                                
                                # 这是第一个被修改的提醒，设为新series的主提醒
                                update_data = {
                                    'series_id': new_series_id,
                                    'rrule': new_rrule,
                                    'is_main_reminder': True,
                                    'is_instance': False,
                                    'last_modified': datetime.now().isoformat()
                                }
                                
                                # 应用额外的更新参数
                                if additional_updates:
                                    # 对于新系列的主提醒，允许更新trigger_time
                                    filtered_updates = additional_updates.copy()
                                    # 如果时间不符合规则，使用计算出的正确时间
                                    if not should_keep_original_time:
                                        filtered_updates['trigger_time'] = actual_start_time.strftime('%Y-%m-%dT%H:%M')
                                    update_data.update(filtered_updates)
                                    logger.info(f"Applied additional updates to new main reminder: {filtered_updates}")
                                
                                reminder.update(update_data)
                                # 移除instance相关字段
                                reminder.pop('original_reminder_id', None)
                                logger.info(f"Set reminder as new main reminder for series {new_series_id}")
                                logger.info(f"New main reminder data: title='{reminder.get('title')}', priority='{reminder.get('priority')}', trigger_time='{reminder.get('trigger_time')}'")
                            else:
                                # 其他受影响的提醒暂时删除，稍后重新生成
                                logger.info(f"Removing future reminder at {reminder_time} for regeneration")
                                continue
                            
                            updated_reminders.append(reminder)
                            
                    except Exception as e:
                        logger.warning(f"Failed to process reminder time: {e}")
                        updated_reminders.append(reminder)
                else:
                    # 不属于这个系列的提醒直接保留
                    updated_reminders.append(reminder)
            
            # 4. 为新series生成实例（从from_date之后开始）
            # 找到新的主提醒（已经更新过的）
            new_main_reminder = None
            for reminder in updated_reminders:
                if (reminder.get('series_id') == new_series_id and 
                    reminder.get('is_main_reminder', False)):
                    new_main_reminder = reminder
                    break
            
            if new_main_reminder:
                series_info = {
                    'series_id': new_series_id,
                    'main_reminder': new_main_reminder,  # 使用已更新的主提醒
                    'rrule': new_rrule,
                    'instances': []
                }
                # 从from_date的下一个实例开始生成
                next_start = from_date + timedelta(days=1)
                new_instances = self._generate_instances_for_series(series_info, start_from=next_start)
                
                # 额外的更新参数已经在主提醒中了，所以新实例会自动继承
                # 但我们还是要确保一下，防止主提醒更新后才生成实例的时序问题
                if additional_updates:
                    filtered_updates = {k: v for k, v in additional_updates.items() 
                                      if k not in ['trigger_time']}
                    for instance in new_instances:
                        # 检查是否已经有这些字段，如果没有则添加
                        for key, value in filtered_updates.items():
                            if key not in instance or instance[key] != value:
                                instance[key] = value
                                instance['last_modified'] = datetime.now().isoformat()
                
                updated_reminders.extend(new_instances)
                logger.info(f"Generated {len(new_instances)} new instances for series {new_series_id}")
            else:
                logger.warning(f"Could not find new main reminder for series {new_series_id}")
        
        return updated_reminders
    
    def _analyze_recurring_series(self, user_reminders: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """分析用户数据中的重复提醒系列"""
        series_info = {}
        
        for reminder in user_reminders:
            series_id = reminder.get('series_id')
            if not series_id or not reminder.get('rrule'):
                continue
            
            if series_id not in series_info:
                series_info[series_id] = {
                    'series_id': series_id,
                    'main_reminder': None,
                    'instances': [],
                    'rrule': reminder.get('rrule', '')
                }
            
            if reminder.get('is_main_reminder', False):
                series_info[series_id]['main_reminder'] = reminder
            else:
                series_info[series_id]['instances'].append(reminder)
        
        return series_info
    
    def _needs_more_instances(self, series_info: Dict[str, Any]) -> bool:
        """检查系列是否需要更多实例"""
        series_id = series_info['series_id']
        
        # 首先检查这个系列是否已经被删除或有删除标记
        try:
            series = self.rrule_engine.get_series(series_id)
            if series:
                # 检查是否有异常（删除操作），特别是最近的删除
                now = datetime.now()
                recent_exceptions = 0
                total_exceptions = 0
                
                for segment in series.segments:
                    for exdate in segment.exdates:
                        total_exceptions += 1
                        # 如果删除的是未来的日期，说明用户主动删除了后续实例
                        if exdate > now:
                            recent_exceptions += 1
                
                if total_exceptions > 0:
                    print(f"DEBUG: Series {series_id} has {total_exceptions} total exceptions, {recent_exceptions} future exceptions")
                    
                    # 如果有很多未来的删除，说明用户不想要这个系列继续
                    if recent_exceptions >= 3:  # 如果删除了3个或更多未来实例
                        print(f"DEBUG: Series {series_id} has too many future deletions, stopping generation")
                        return False
        except Exception as e:
            print(f"DEBUG: Error checking series status for {series_id}: {e}")
        
        now = datetime.now()
        future_instances = 0
        latest_instance_time = None
        
        # 计算现有的未来实例数量
        for instance in series_info['instances']:
            try:
                trigger_time = datetime.fromisoformat(
                    instance.get('trigger_time', '').replace('Z', '+00:00')
                )
                if trigger_time > now:
                    future_instances += 1
                    if latest_instance_time is None or trigger_time > latest_instance_time:
                        latest_instance_time = trigger_time
            except:
                continue
        
        # 检查主提醒是否也在未来
        main_reminder = series_info.get('main_reminder')
        if main_reminder:
            try:
                main_time = datetime.fromisoformat(
                    main_reminder.get('trigger_time', '').replace('Z', '+00:00')
                )
                if main_time > now:
                    future_instances += 1
                    if latest_instance_time is None or main_time > latest_instance_time:
                        latest_instance_time = main_time
            except:
                pass
        
        # 检查是否有UNTIL限制
        rrule_str = series_info.get('rrule', '')
        has_until = 'UNTIL=' in rrule_str.upper()
        
        days_ahead = 0
        if latest_instance_time:
            days_ahead = (latest_instance_time - now).days
        
        series_id = series_info['series_id']
        
        if has_until:
            print(f"DEBUG: Series {series_id} (with UNTIL) has {future_instances} future instances, latest is {days_ahead} days ahead")
            # 对于有截止时间的系列，检查是否还需要在截止时间之前生成更多实例
            # 解析UNTIL时间
            import re
            until_match = re.search(r'UNTIL=(\d{8}T\d{6})', rrule_str.upper())
            if until_match:
                until_str = until_match.group(1)
                try:
                    # 解析UNTIL时间 (格式: YYYYMMDDTHHMMSS)
                    until_time = datetime.strptime(until_str, '%Y%m%dT%H%M%S')
                    days_until_end = (until_time - now).days
                    
                    print(f"DEBUG: Series {series_id} ends in {days_until_end} days (until {until_time})")
                    
                    # 如果截止时间已过，不需要生成更多
                    if until_time <= now:
                        print(f"DEBUG: Series {series_id} has ended, no more instances needed")
                        return False
                    
                    # 如果还有时间但实例不足，需要生成更多
                    if future_instances < self.min_future_instances and days_until_end > 0:
                        print(f"DEBUG: Series {series_id} (with UNTIL) needs more instances before end date")
                        return True
                    else:
                        print(f"DEBUG: Series {series_id} (with UNTIL) has enough instances until end date")
                        return False
                        
                except ValueError as e:
                    print(f"DEBUG: Failed to parse UNTIL time {until_str}: {e}")
                    # 如果解析失败，按无截止时间处理
                    pass
            
            # 如果有UNTIL但解析失败，保守地不生成更多实例
            return False
        else:
            print(f"DEBUG: Series {series_id} (no UNTIL) has {future_instances} future instances, latest is {days_ahead} days ahead")
            # 检查是否需要更多实例（没有截止时间的系列）
            if future_instances < self.min_future_instances:
                print(f"DEBUG: Series {series_id} (no UNTIL) needs new instances, latest is {days_ahead} days ahead")
                return True
            else:
                print(f"DEBUG: Series {series_id} (no UNTIL) is good, latest is {days_ahead} days ahead")
                return False
    
    def _generate_instances_for_series(self, series_info: Dict[str, Any], 
                                     start_from: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """为系列生成新的实例"""
        main_reminder = series_info.get('main_reminder')
        if not main_reminder:
            return []
        
        series_id = series_info['series_id']
        rrule = series_info.get('rrule', '')
        
        if not rrule:
            return []
        
        if start_from is None:
            start_from = datetime.now()
        
        # 获取主提醒的开始时间
        try:
            main_start_time = datetime.fromisoformat(
                main_reminder.get('trigger_time', '').replace('Z', '+00:00')
            )
        except:
            main_start_time = start_from
        
        # 确保RRule引擎中有这个系列
        rrule_series = self.rrule_engine.get_series(series_id)
        if not rrule_series:
            # 如果系列不存在，记录警告但不创建新系列
            logger.warning(f"Series {series_id} not found in RRule engine, skipping instance generation")
            return []
        
        # 生成实例时间
        end_date = start_from + timedelta(days=self.default_future_days)
        instance_times = self.rrule_engine.generate_instances(
            series_id, start_from, end_date, self.max_instances_per_generation
        )
        
        print(f"DEBUG: Generated {len(instance_times)} instance times for series {series_id}")
        for i, dt in enumerate(instance_times[:5]):  # 只打印前5个
            print(f"  {i+1}. {dt.strftime('%Y-%m-%d %H:%M')}")
        
        # 创建实例数据
        new_instances = []
        existing_times = set()
        
        # 收集已存在的实例时间
        for instance in series_info['instances']:
            try:
                existing_time = datetime.fromisoformat(
                    instance.get('trigger_time', '').replace('Z', '+00:00')
                )
                existing_times.add(existing_time)
            except:
                continue
        
        # 也要排除主提醒的时间
        try:
            main_time = datetime.fromisoformat(
                main_reminder.get('trigger_time', '').replace('Z', '+00:00')
            )
            existing_times.add(main_time)
        except:
            pass
        
        # 生成新实例
        for instance_time in instance_times:
            if instance_time not in existing_times:
                new_instance = main_reminder.copy()
                new_instance.update({
                    'id': str(uuid.uuid4()),
                    'trigger_time': instance_time.isoformat(),
                    'is_main_reminder': False,
                    'is_instance': True,
                    'original_reminder_id': main_reminder['id'],
                    'created_at': datetime.now().isoformat(),
                    'last_modified': datetime.now().isoformat()
                })
                new_instances.append(new_instance)
        
        return new_instances
