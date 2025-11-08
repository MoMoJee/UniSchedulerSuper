# Reminder 相关视图函数
import datetime
import uuid
import json
from datetime import timedelta
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from .models import UserData
from logger import logger

# 导入我们的新引擎
from integrated_reminder_manager import IntegratedReminderManager


def get_django_request(request):
    """
    获取原生的 Django HttpRequest 对象
    兼容 Django HttpRequest 和 DRF Request
    """
    from rest_framework.request import Request as DRFRequest
    if isinstance(request, DRFRequest):
        return request._request
    return request


# 提醒管理器工厂函数
def get_reminder_manager(request):
    """获取用户专属的提醒管理器实例"""
    if not request:
        raise ValueError("Request is required for IntegratedReminderManager")
    return IntegratedReminderManager(request=request)


def auto_generate_missing_instances(reminders):
    """自动生成缺失的重复提醒实例
    
    Args:
        reminders: 提醒列表，会被直接修改
    
    Returns:
        int: 生成的新实例数量
    """
    new_instances_count = 0
    now = datetime.datetime.now()
    
    # 获取所有重复系列
    recurring_series = {}
    for reminder in reminders:
        series_id = reminder.get('series_id')
        rrule = reminder.get('rrule')
        
        if series_id and rrule and 'FREQ=' in rrule and not reminder.get('is_detached', False):
            # 只处理没有截止时间的重复提醒（无UNTIL的）
            if 'UNTIL=' not in rrule:
                if series_id not in recurring_series:
                    recurring_series[series_id] = {
                        'reminders': [],
                        'rrule': rrule,
                        'base_reminder': reminder
                    }
                recurring_series[series_id]['reminders'].append(reminder)
    
    # 检查每个系列是否需要生成新实例
    for series_id, series_data in recurring_series.items():
        series_reminders = series_data['reminders']
        rrule = series_data['rrule']
        base_reminder = series_data['base_reminder']
        
        # 找到最晚的提醒时间
        latest_time = None
        for reminder in series_reminders:
            trigger_time = datetime.datetime.fromisoformat(reminder['trigger_time'])
            if latest_time is None or trigger_time > latest_time:
                latest_time = trigger_time
        
        if latest_time:
            # 如果最晚的提醒时间距离现在少于30天，生成新实例
            days_ahead = (latest_time - now).days
            if days_ahead < 30:
                print(f"DEBUG: Series {series_id} (no UNTIL) needs new instances, latest is {days_ahead} days ahead")
                
                # 生成新实例，从最晚时间之后开始
                new_instances = generate_reminder_instances(base_reminder, 90, 10)
                
                # 过滤掉已经存在的实例
                existing_times = {r['trigger_time'] for r in series_reminders}
                truly_new_instances = []
                
                for instance in new_instances:
                    if instance['trigger_time'] not in existing_times:
                        truly_new_instances.append(instance)
                
                if truly_new_instances:
                    reminders.extend(truly_new_instances)
                    new_instances_count += len(truly_new_instances)
                    print(f"DEBUG: Added {len(truly_new_instances)} new instances for unlimited series {series_id}")
            else:
                print(f"DEBUG: Series {series_id} (no UNTIL) is good, latest is {days_ahead} days ahead")
    
    return new_instances_count


def generate_reminder_instances(base_reminder, days_ahead=90, min_instances=10):
    """生成重复提醒的实例
    
    Args:
        base_reminder: 基础提醒数据
        days_ahead: 向前生成的天数（默认90天）
        min_instances: 最少生成的实例数量（默认10个）
    """
    instances = []
    if not base_reminder.get('rrule') or 'FREQ=' not in base_reminder.get('rrule', ''):
        return instances
    
    try:
        from datetime import datetime, timedelta
        import re
        
        rrule = base_reminder['rrule']
        start_time = datetime.fromisoformat(base_reminder['trigger_time'])
        
        # 解析UNTIL限制
        until_time = None
        if 'UNTIL=' in rrule:
            until_match = re.search(r'UNTIL=([^;]+)', rrule)
            if until_match:
                until_str = until_match.group(1)
                print(f"DEBUG: Parsing UNTIL string: '{until_str}' from rrule: '{rrule}'")
                try:
                    if until_str.endswith('Z'):
                        # UTC格式：20250830T000000Z
                        if 'T' in until_str and len(until_str) == 16:
                            # 格式：20250830T000000Z -> 2025-08-30T00:00:00
                            until_formatted = (until_str[:4] + '-' + until_str[4:6] + '-' + until_str[6:8] + 
                                             'T' + until_str[9:11] + ':' + until_str[11:13] + ':' + until_str[13:15])
                            until_time = datetime.fromisoformat(until_formatted)
                        else:
                            until_time = datetime.fromisoformat(until_str.replace('Z', ''))
                    elif 'T' in until_str and len(until_str) == 15:
                        # 本地时间格式（无Z后缀）：20250830T000000 -> 2025-08-30T00:00:00
                        until_formatted = (until_str[:4] + '-' + until_str[4:6] + '-' + until_str[6:8] + 
                                         'T' + until_str[9:11] + ':' + until_str[11:13] + ':' + until_str[13:15])
                        until_time = datetime.fromisoformat(until_formatted)
                        print(f"DEBUG: Formatted UNTIL string '{until_str}' -> '{until_formatted}' -> {until_time}")
                    else:
                        # 其他格式，直接解析
                        until_time = datetime.fromisoformat(until_str)
                    print(f"DEBUG: Parsed UNTIL time: {until_time}")
                except Exception as e:
                    print(f"DEBUG: Failed to parse UNTIL {until_str}: {e}")
        
        # 动态计算结束时间，确保生成足够的实例
        end_time = start_time + timedelta(days=days_ahead)
        
        # 如果有UNTIL限制，使用更早的时间
        if until_time:
            end_time = min(end_time, until_time)
            print(f"DEBUG: Using UNTIL limited end_time: {end_time}")
        
        # 对于较长周期的重复，扩展生成范围
        if 'FREQ=MONTHLY' in rrule:
            interval = 1
            if 'INTERVAL=' in rrule:
                interval_match = re.search(r'INTERVAL=(\d+)', rrule)
                if interval_match:
                    interval = int(interval_match.group(1))
            
            # 对于月重复，确保至少覆盖min_instances个周期
            min_months = max(12, interval * min_instances)
            end_time = max(end_time, start_time + timedelta(days=min_months * 32))
        
        elif 'FREQ=YEARLY' in rrule:
            # 对于年重复，至少生成5年
            end_time = max(end_time, start_time + timedelta(days=365 * 5))
        
        # 简单的重复规则解析（支持DAILY, WEEKLY, MONTHLY）
        if 'FREQ=DAILY' in rrule:
            interval = 1
            if 'INTERVAL=' in rrule:
                interval_match = re.search(r'INTERVAL=(\d+)', rrule)
                if interval_match:
                    interval = int(interval_match.group(1))
            
            current_time = start_time + timedelta(days=interval)
            while current_time <= end_time and len(instances) < max(min_instances * 3, 90):  # 确保生成足够实例
                instance = base_reminder.copy()
                instance['id'] = str(uuid.uuid4())
                instance['trigger_time'] = current_time.strftime("%Y-%m-%dT%H:%M:%S")
                instance['original_trigger_time'] = current_time.strftime("%Y-%m-%dT%H:%M:%S")
                instances.append(instance)
                current_time += timedelta(days=interval)
                
        elif 'FREQ=WEEKLY' in rrule:
            interval = 1
            if 'INTERVAL=' in rrule:
                interval_match = re.search(r'INTERVAL=(\d+)', rrule)
                if interval_match:
                    interval = int(interval_match.group(1))
            
            # 处理BYDAY规则
            weekdays = []
            if 'BYDAY=' in rrule:
                byday_match = re.search(r'BYDAY=([A-Z,]+)', rrule)
                if byday_match:
                    weekday_str = byday_match.group(1)
                    weekday_mapping = {
                        'MO': 0, 'TU': 1, 'WE': 2, 'TH': 3, 
                        'FR': 4, 'SA': 5, 'SU': 6
                    }
                    weekdays = [weekday_mapping[day] for day in weekday_str.split(',') if day in weekday_mapping]
            
            if weekdays:
                # 有指定星期几，按星期几重复
                current_date = start_time.date()
                count = 0
                while count < max(min_instances * 2, 50):  # 确保生成足够实例
                    current_date += timedelta(days=1)
                    if current_date.weekday() in weekdays:
                        # 检查是否符合间隔要求
                        week_diff = (current_date - start_time.date()).days // 7
                        if week_diff % interval == 0:
                            instance_time = datetime.combine(current_date, start_time.time())
                            if instance_time > end_time:
                                break
                            
                            instance = base_reminder.copy()
                            instance['id'] = str(uuid.uuid4())
                            instance['trigger_time'] = instance_time.strftime("%Y-%m-%dT%H:%M:%S")
                            instance['original_trigger_time'] = instance_time.strftime("%Y-%m-%dT%H:%M:%S")
                            instances.append(instance)
                            count += 1
            else:
                # 没有指定星期几，简单按周重复
                current_time = start_time + timedelta(weeks=interval)
                while current_time <= end_time and len(instances) < max(min_instances, 20):  # 确保生成足够实例
                    instance = base_reminder.copy()
                    instance['id'] = str(uuid.uuid4())
                    instance['trigger_time'] = current_time.strftime("%Y-%m-%dT%H:%M:%S")
                    instance['original_trigger_time'] = current_time.strftime("%Y-%m-%dT%H:%M:%S")
                    instances.append(instance)
                    current_time += timedelta(weeks=interval)
                
        elif 'FREQ=MONTHLY' in rrule:
            interval = 1
            if 'INTERVAL=' in rrule:
                interval_match = re.search(r'INTERVAL=(\d+)', rrule)
                if interval_match:
                    interval = int(interval_match.group(1))
            
            if 'BYMONTHDAY=' in rrule:
                # 按月的日期重复（如每月15日）
                monthday_match = re.search(r'BYMONTHDAY=(-?\d+)', rrule)
                if monthday_match:
                    monthday = int(monthday_match.group(1))
                    current_date = start_time.date()
                    max_months = max(min_instances, 24)  # 确保生成足够实例，最多24个月
                    for i in range(1, max_months + 1):
                        # 计算下一个月
                        if current_date.month + i * interval <= 12:
                            next_month = current_date.month + i * interval
                            next_year = current_date.year
                        else:
                            next_month = (current_date.month + i * interval - 1) % 12 + 1
                            next_year = current_date.year + (current_date.month + i * interval - 1) // 12
                        
                        try:
                            if monthday == -1:
                                # 月末
                                from calendar import monthrange
                                last_day = monthrange(next_year, next_month)[1]
                                next_date = datetime(next_year, next_month, last_day, start_time.hour, start_time.minute)
                            else:
                                next_date = datetime(next_year, next_month, monthday, start_time.hour, start_time.minute)
                            
                            if next_date > end_time:
                                break
                                
                            instance = base_reminder.copy()
                            instance['id'] = str(uuid.uuid4())
                            instance['trigger_time'] = next_date.strftime("%Y-%m-%dT%H:%M:%S")
                            instance['original_trigger_time'] = next_date.strftime("%Y-%m-%dT%H:%M:%S")
                            instances.append(instance)
                        except ValueError:
                            # 处理无效日期（如2月30日）
                            continue
                            
            elif 'BYDAY=' in rrule:
                # 按月的星期重复（如每月第2个星期一）
                byday_match = re.search(r'BYDAY=(-?\d+)([A-Z]{2})', rrule)
                if byday_match:
                    week_num = int(byday_match.group(1))
                    weekday_str = byday_match.group(2)
                    weekday_mapping = {
                        'MO': 0, 'TU': 1, 'WE': 2, 'TH': 3, 
                        'FR': 4, 'SA': 5, 'SU': 6
                    }
                    target_weekday = weekday_mapping.get(weekday_str)
                    
                    if target_weekday is not None:
                        current_date = start_time.date()
                        max_months = max(min_instances, 24)  # 确保生成足够实例，最多24个月
                        for i in range(1, max_months + 1):
                            # 计算下一个月
                            if current_date.month + i * interval <= 12:
                                next_month = current_date.month + i * interval
                                next_year = current_date.year
                            else:
                                next_month = (current_date.month + i * interval - 1) % 12 + 1
                                next_year = current_date.year + (current_date.month + i * interval - 1) // 12
                            
                            # 找到该月的第N个星期X
                            first_day = datetime(next_year, next_month, 1)
                            first_weekday = first_day.weekday()
                            
                            if week_num > 0:
                                # 正数：第N个星期X
                                days_to_add = (target_weekday - first_weekday) % 7 + (week_num - 1) * 7
                                target_date = first_day + timedelta(days=days_to_add)
                            else:
                                # 负数：倒数第N个星期X
                                from calendar import monthrange
                                last_day = monthrange(next_year, next_month)[1]
                                last_date = datetime(next_year, next_month, last_day)
                                last_weekday = last_date.weekday()
                                days_to_subtract = (last_weekday - target_weekday) % 7 + (abs(week_num) - 1) * 7
                                target_date = last_date - timedelta(days=days_to_subtract)
                            
                            # 检查日期是否在当月
                            if target_date.month == next_month:
                                instance_time = datetime.combine(target_date.date(), start_time.time())
                                if instance_time > end_time:
                                    break
                                    
                                instance = base_reminder.copy()
                                instance['id'] = str(uuid.uuid4())
                                instance['trigger_time'] = instance_time.strftime("%Y-%m-%dT%H:%M:%S")
                                instance['original_trigger_time'] = instance_time.strftime("%Y-%m-%dT%H:%M:%S")
                                instances.append(instance)
            else:
                # 简单的每隔x个月重复
                current_date = start_time.date()
                max_months = max(min_instances, 24)  # 确保生成足够实例，最多24个月
                for i in range(1, max_months + 1):
                    # 计算下一个月
                    if current_date.month + i * interval <= 12:
                        next_month = current_date.month + i * interval
                        next_year = current_date.year
                    else:
                        next_month = (current_date.month + i * interval - 1) % 12 + 1
                        next_year = current_date.year + (current_date.month + i * interval - 1) // 12
                    
                    try:
                        next_date = datetime(next_year, next_month, current_date.day, start_time.hour, start_time.minute)
                        if next_date > end_time:
                            break
                            
                        instance = base_reminder.copy()
                        instance['id'] = str(uuid.uuid4())
                        instance['trigger_time'] = next_date.strftime("%Y-%m-%dT%H:%M:%S")
                        instance['original_trigger_time'] = next_date.strftime("%Y-%m-%dT%H:%M:%S")
                        instances.append(instance)
                        
                        # 如果已经生成了足够的实例，可以退出
                        if len(instances) >= min_instances:
                            break
                    except ValueError:
                        # 处理无效日期（如月底日期）
                        continue
                
        # 可以添加更多重复规则支持
        
    except Exception as e:
        print(f"Error generating reminder instances: {e}")
    
    return instances


@csrf_exempt
def get_reminders(request):
    """获取所有提醒"""
    if request.method == 'GET':
        # 获取原生 Django request
        django_request = get_django_request(request)
        
        user_reminders_data, created, result = UserData.get_or_initialize(django_request, new_key="reminders")
        
        # 检查是否成功获取数据
        if user_reminders_data is None:
            logger.error(f"Failed to get reminders data: {result}")
            return JsonResponse({'status': 'error', 'message': result.get('message', '获取提醒数据失败')}, status=500)
        
        reminders = user_reminders_data.get_value()
        
        # 自动检查并生成缺失的重复提醒实例
        new_instances_generated = auto_generate_missing_instances(reminders)
        
        if new_instances_generated > 0:
            # 如果生成了新实例，保存更新后的数据
            user_reminders_data.set_value(reminders)
            print(f"DEBUG: Auto-generated {new_instances_generated} new reminder instances")
        
        # 返回提醒数据
        return JsonResponse({'reminders': reminders})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


def create_reminder(request):
    """创建新提醒 - 使用新的 RRule 引擎"""
    if request.method == 'POST':
        # 获取原生 Django request
        django_request = get_django_request(request)
        
        user_reminders_data, created, result = UserData.get_or_initialize(django_request, new_key="reminders")
        
        # 检查是否成功获取数据
        if user_reminders_data is None:
            logger.error(f"Failed to get reminders data: {result}")
            return JsonResponse({'status': 'error', 'message': result.get('message', '获取提醒数据失败')}, status=500)
        
        reminders = user_reminders_data.get_value()
        
        # 使用 request.data 兼容 DRF Request
        data = request.data if hasattr(request, 'data') else json.loads(request.body)
        title = data.get('title')
        content = data.get('content', '')
        trigger_time = data.get('trigger_time')
        priority = data.get('priority', 'medium')
        rrule = data.get('rrule', '')
        
        # 验证必填字段
        if not title or not trigger_time:
            return JsonResponse({'status': 'error', 'message': '标题和触发时间是必填项'}, status=400)
        
        # 准备提醒数据
        reminder_data = {
            "title": title,
            "content": content,
            "trigger_time": trigger_time,
            "priority": priority,
            "status": "active",
            "snooze_until": "",
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_modified": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        try:
            # 确保 reminders 是列表
            if not isinstance(reminders, list):
                reminders = []
            
            if rrule and 'FREQ=' in rrule:
                # 创建重复提醒
                print(f"DEBUG: Creating recurring reminder with rrule: {rrule}")
                reminder_mgr = get_reminder_manager(django_request)
                recurring_reminder = reminder_mgr.create_recurring_reminder(reminder_data, rrule)
                reminders.append(recurring_reminder)
                
                # 处理数据生成实例
                updated_reminders = reminder_mgr.process_reminder_data(reminders)
                user_reminders_data.set_value(updated_reminders)
                
                return JsonResponse({
                    'status': 'success', 
                    'message': f'重复提醒已创建，系列ID: {recurring_reminder["series_id"]}'
                })
            else:
                # 创建单个提醒
                reminder_data.update({
                    'id': str(uuid.uuid4()),
                    'series_id': None,
                    'rrule': '',
                    'is_recurring': False,
                    'is_main_reminder': False,
                    'is_detached': False
                })
                reminders.append(reminder_data)
                user_reminders_data.set_value(reminders)
                
                return JsonResponse({'status': 'success', 'message': '提醒已创建'})
                
        except Exception as e:
            print(f"ERROR in create_reminder: {e}")
            return JsonResponse({'status': 'error', 'message': f'创建提醒失败: {str(e)}'}, status=500)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


def update_reminder(request):
    """更新提醒 - 只处理前端实际使用的场景"""
    if request.method == 'POST':
        try:
            # 使用 request.data 兼容 DRF Request
            data = request.data if hasattr(request, 'data') else json.loads(request.body)
            reminder_id = data.get('id')
            
            if not reminder_id:
                return JsonResponse({'status': 'error', 'message': '提醒ID是必填项'}, status=400)
            
            # 获取原生 Django request
            django_request = get_django_request(request)
            
            # 获取用户数据
            user_reminders_data, created, result = UserData.get_or_initialize(django_request, new_key="reminders")
            reminders = user_reminders_data.get_value()
            
            # 查找目标提醒
            target_reminder = None
            for reminder in reminders:
                if reminder['id'] == reminder_id:
                    target_reminder = reminder
                    break
            
            if not target_reminder:
                return JsonResponse({'status': 'error', 'message': '未找到指定的提醒'}, status=404)
            
            # 检查是否有重复规则变化
            rrule_change_scope = data.get('rrule_change_scope')
            
            if rrule_change_scope == 'all' and not target_reminder.get('series_id') and data.get('rrule'):
                # 普通提醒转重复提醒（唯一使用重复规则变化的场景）
                logger.info(f"Converting single reminder {reminder_id} to recurring with rrule: {data.get('rrule')}")
                
                manager = IntegratedReminderManager(django_request)
                
                # 更新提醒的基本信息
                if 'title' in data:
                    target_reminder['title'] = data['title']
                if 'content' in data:
                    target_reminder['content'] = data['content']
                if 'trigger_time' in data:
                    target_reminder['trigger_time'] = data['trigger_time']
                if 'priority' in data:
                    target_reminder['priority'] = data['priority']
                
                # 从提醒列表中移除原提醒
                reminders = [r for r in reminders if r['id'] != reminder_id]
                
                # 使用提醒管理器创建新的重复提醒
                new_recurring_reminder = manager.create_recurring_reminder(target_reminder, data.get('rrule'))
                
                # 将新的重复提醒添加到列表
                reminders.append(new_recurring_reminder)
                
                # 处理重复提醒数据以生成实例
                final_reminders = manager.process_reminder_data(reminders)
                user_reminders_data.set_value(final_reminders)
                
                return JsonResponse({'status': 'success'})
            
            elif rrule_change_scope:
                # 其他重复规则变化场景应该使用批量编辑API
                return JsonResponse({'status': 'error', 'message': '此类重复提醒编辑请使用批量编辑功能'}, status=400)
            
            else:
                # 简单更新，直接修改提醒字段
                if 'title' in data:
                    target_reminder['title'] = data['title']
                if 'content' in data:
                    target_reminder['content'] = data['content']
                if 'trigger_time' in data:
                    target_reminder['trigger_time'] = data['trigger_time']
                if 'priority' in data:
                    target_reminder['priority'] = data['priority']
                if 'status' in data:
                    target_reminder['status'] = data['status']
                
                target_reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                user_reminders_data.set_value(reminders)
                return JsonResponse({'status': 'success'})
                
        except Exception as e:
            logger.error(f"Error updating reminder: {e}")
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


def update_reminder_status(request):
    """更新提醒状态（完成/忽略/延后/激活）"""
    if request.method == 'POST':
        # 获取原生 Django request
        django_request = get_django_request(request)
        
        user_reminders_data, created, result = UserData.get_or_initialize(django_request, new_key="reminders")
        reminders = user_reminders_data.get_value()
        
        # 使用 request.data 兼容 DRF Request
        data = request.data if hasattr(request, 'data') else json.loads(request.body)
        reminder_id = data.get('id')
        new_status = data.get('status')  # active/completed/dismissed/snoozed_15m/snoozed_1h/snoozed_1d
        snooze_until = data.get('snooze_until', '')
        
        if not reminder_id or not new_status:
            return JsonResponse({'status': 'error', 'message': '提醒ID和状态是必填项'}, status=400)
        
        # 查找要更新的提醒
        reminder_found = False
        for reminder in reminders:
            if reminder['id'] == reminder_id:
                reminder['status'] = new_status
                reminder['snooze_until'] = snooze_until
                reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # 如果是取消延后或激活，清空延后时间
                if new_status == 'active':
                    reminder['snooze_until'] = ''
                
                reminder_found = True
                break
        
        if not reminder_found:
            return JsonResponse({'status': 'error', 'message': '未找到指定的提醒'}, status=404)
        
        user_reminders_data.set_value(reminders)
        
        return JsonResponse({'status': 'success'})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


def delete_reminder(request):
    """删除提醒"""
    if request.method == 'POST':
        # 获取原生 Django request
        django_request = get_django_request(request)
        
        user_reminders_data, created, result = UserData.get_or_initialize(django_request, new_key="reminders")
        reminders = user_reminders_data.get_value()
        
        # 使用 request.data 兼容 DRF Request
        data = request.data if hasattr(request, 'data') else json.loads(request.body)
        reminder_id = data.get('id')
        
        if not reminder_id:
            return JsonResponse({'status': 'error', 'message': '提醒ID是必填项'}, status=400)
        
        # 查找并删除提醒
        original_length = len(reminders)
        reminders[:] = [reminder for reminder in reminders if reminder['id'] != reminder_id]
        
        if len(reminders) == original_length:
            return JsonResponse({'status': 'error', 'message': '未找到指定的提醒'}, status=404)
        
        user_reminders_data.set_value(reminders)
        
        return JsonResponse({'status': 'success'})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


@csrf_exempt
def maintain_reminders(request):
    """维护提醒实例 - 定期调用以确保重复提醒的实例足够"""
    if request.method == 'POST':
        # 获取原生 Django request
        django_request = get_django_request(request)
        
        user_reminders_data, created, result = UserData.get_or_initialize(django_request, new_key="reminders")
        reminders = user_reminders_data.get_value()
        
        # 确保 reminders 是列表
        if not isinstance(reminders, list):
            reminders = []
        
        try:
            # 使用新引擎处理提醒数据
            reminder_mgr = get_reminder_manager(request)
            updated_reminders = reminder_mgr.process_reminder_data(reminders)
            
            # 保存更新后的数据
            user_reminders_data.set_value(updated_reminders)
            
            added_count = len(updated_reminders) - len(reminders)
            
            return JsonResponse({
                'status': 'success',
                'original_count': len(reminders),
                'updated_count': len(updated_reminders),
                'added_instances': added_count
            })
            
        except Exception as e:
            logger.error(f"维护提醒失败: {str(e)}")
            return JsonResponse({'status': 'error', 'message': f'维护失败: {str(e)}'}, status=500)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


@csrf_exempt
def get_pending_reminders(request):
    """获取待触发的提醒（用于通知检查）"""
    if request.method == 'GET':
        # 获取原生 Django request
        django_request = get_django_request(request)
        
        user_reminders_data, created, result = UserData.get_or_initialize(django_request, new_key="reminders")
        reminders = user_reminders_data.get_value()
        
        current_time = datetime.datetime.now()
        pending_reminders = []
        
        for reminder in reminders:
            if reminder['status'] != 'active':
                continue
                
            trigger_time = datetime.datetime.fromisoformat(reminder['trigger_time'].replace('Z', '+00:00'))
            
            # 检查是否应该触发（允许1分钟的误差）
            if trigger_time <= current_time + timedelta(minutes=1):
                pending_reminders.append(reminder)
        
        return JsonResponse({'pending_reminders': pending_reminders})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


@csrf_exempt
def bulk_edit_reminders(request):
    """批量编辑重复提醒"""
    if request.method == 'POST':
        # 获取原生 Django request
        django_request = get_django_request(request)
        
        user_reminders_data, created, result = UserData.get_or_initialize(django_request, new_key="reminders")
        
        if user_reminders_data is None:
            return JsonResponse({'status': 'error', 'message': result.get('message', '获取用户数据失败')}, status=400)
        
        try:
            reminders = user_reminders_data.get_value()
            if not isinstance(reminders, list):
                reminders = []
        except:
            reminders = []
        
        # 使用 request.data 兼容 DRF Request
        data = request.data if hasattr(request, 'data') else json.loads(request.body)
        logger.debug(f"{data=}")

        reminder_id = data.get('reminder_id')
        operation = data.get('operation', 'edit')  # edit, delete
        edit_scope = data.get('edit_scope', 'single')  # single, all, future, from_time
        from_time = data.get('from_time')  # 当 edit_scope 为 from_time 时必需
        series_id = data.get('series_id')
        
        # 调整scope映射
        scope_mapping = {
            'this_only': 'single',
            'all': 'all', 
            'from_this': 'future',
            'from_time': 'from_time'
        }
        edit_scope = scope_mapping.get(edit_scope, edit_scope)
        
        # 获取更新数据
        updates = {
            'title': data.get('title'),
            'content': data.get('content'),  # 前端发送的是content，不是description
            'description': data.get('description'),  # 保留兼容性
            'priority': data.get('priority'),  # 添加missing的priority字段
            'importance': data.get('importance'),
            'urgency': data.get('urgency'),
            'trigger_time': data.get('trigger_time'),
            'rrule': data.get('rrule'),
            'reminder_mode': data.get('reminder_mode'),
        }
        # 过滤掉None值
        updates = {k: v for k, v in updates.items() if v is not None}
        
        logger.info(f"Received updates: {updates}")
        
        if not reminder_id:
            return JsonResponse({'status': 'error', 'message': '提醒ID是必填项'}, status=400)
        
        if edit_scope == 'from_time' and not from_time:
            return JsonResponse({'status': 'error', 'message': '当编辑范围为"从指定时间"时，必须提供起始时间'}, status=400)
        
        # 使用新的引擎处理
        try:
            if operation == 'delete':
                if edit_scope == 'single':
                    # 删除单个实例
                    reminder_mgr = get_reminder_manager(request)
                    updated_reminders = reminder_mgr.delete_reminder_instance(
                        reminders, reminder_id, series_id or ''
                    )
                    # 处理重复提醒数据以防止自动补回
                    final_reminders = reminder_mgr.process_reminder_data(updated_reminders)
                    user_reminders_data.set_value(final_reminders)
                    return JsonResponse({'status': 'success'})
                    
                elif edit_scope in ['all', 'future', 'from_time']:
                    # 删除整个系列或从某时间开始删除
                    reminder_mgr = get_reminder_manager(request)
                    
                    if edit_scope == 'all':
                        # 删除整个系列
                        updated_reminders = []
                        for reminder in reminders:
                            if reminder.get('series_id') != series_id:
                                updated_reminders.append(reminder)
                        
                        # 完全删除系列
                        if series_id:
                            reminder_mgr.rrule_engine.delete_series(series_id)
                            logger.info(f"Completely deleted series {series_id}")
                        
                        # 处理重复提醒数据以防止自动补回
                        final_reminders = reminder_mgr.process_reminder_data(updated_reminders)
                        user_reminders_data.set_value(final_reminders)
                        return JsonResponse({'status': 'success'})
                        
                    elif edit_scope in ['future', 'from_time']:
                        # 删除此及之后（使用截断方法）
                        if edit_scope == 'from_time' and from_time:
                            # 如果指定了from_time，找到对应的提醒
                            target_reminder_id = None
                            target_time = datetime.datetime.fromisoformat(from_time)
                            for reminder in reminders:
                                if (reminder.get('series_id') == series_id and 
                                    reminder.get('trigger_time')):
                                    try:
                                        reminder_time = datetime.datetime.fromisoformat(reminder['trigger_time'])
                                        if abs((reminder_time - target_time).total_seconds()) < 60:  # 允许1分钟误差
                                            target_reminder_id = reminder['id']
                                            break
                                    except:
                                        continue
                            
                            if not target_reminder_id:
                                return JsonResponse({'status': 'error', 'message': '找不到指定时间的提醒'}, status=400)
                                
                            reminder_id = target_reminder_id
                        
                        # 使用新的截断方法，它会同时更新RRule引擎和提醒数据
                        logger.info(f"使用新的截断方法，它会同时更新RRule引擎和提醒数据")
                        updated_reminders = reminder_mgr.delete_reminder_this_and_after(
                            reminders, reminder_id, series_id or ''
                        )
                        
                        # 处理重复提醒数据以防止自动补回
                        final_reminders = reminder_mgr.process_reminder_data(updated_reminders)
                        user_reminders_data.set_value(final_reminders)
                        return JsonResponse({'status': 'success'})
                    
            elif operation == 'edit':
                if edit_scope == 'single':
                    # 编辑单个提醒
                    for reminder in reminders:
                        if reminder['id'] == reminder_id:
                            reminder.update(updates)
                            reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            break
                    user_reminders_data.set_value(reminders)
                    return JsonResponse({'status': 'success'})
                    
                elif edit_scope in ['all', 'future', 'from_time']:
                    # 批量编辑 - 使用新的modify_recurring_rule方法
                    reminder_mgr = get_reminder_manager(request)
                    
                    # 确定修改的起始时间
                    cutoff_time = None
                    if from_time:
                        try:
                            cutoff_time = datetime.datetime.fromisoformat(from_time)
                        except:
                            cutoff_time = datetime.datetime.now()
                    elif edit_scope == 'future':
                        current_reminder = next((r for r in reminders if r.get('id') == reminder_id), None)
                        if current_reminder:
                            try:
                                cutoff_time = datetime.datetime.fromisoformat(current_reminder.get('trigger_time', ''))
                            except:
                                cutoff_time = datetime.datetime.now()
                        else:
                            cutoff_time = datetime.datetime.now()
                    
                    if edit_scope == 'all':
                        # 修改整个系列 - 简单更新所有相关提醒
                        updated_count = 0
                        for reminder in reminders:
                            if reminder.get('series_id') == series_id or reminder.get('id') == reminder_id:
                                # 只更新非时间字段，保持原有的trigger_time
                                update_data = {k: v for k, v in updates.items() if k not in ['trigger_time']}
                                reminder.update(update_data)
                                reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                updated_count += 1
                        
                        user_reminders_data.set_value(reminders)
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
                            for reminder in reminders:
                                if (reminder.get('series_id') == series_id and 
                                    reminder.get('rrule')):
                                    original_rrule = reminder.get('rrule')
                                    break
                            
                            # 如果RRule没有变化，按非RRule修改处理
                            if original_rrule and original_rrule == new_rrule:
                                logger.info(f"RRule unchanged for series {series_id}, treating as non-RRule modification")
                                logger.info(f"Original updates dict before filtering: {updates}")
                                
                                updated_count = 0
                                for reminder in reminders:
                                    if (reminder.get('series_id') == series_id and 
                                        reminder.get('trigger_time')):
                                        try:
                                            trigger_time = datetime.datetime.fromisoformat(reminder['trigger_time'])
                                            if trigger_time >= cutoff_time:
                                                # 对于非RRule修改，只更新非时间字段，保持原有的trigger_time
                                                update_data = {k: v for k, v in updates.items() if k not in ['rrule', 'trigger_time']}
                                                logger.info(f"After filtering out rrule and trigger_time: {update_data}")
                                                logger.info(f"Updating reminder {reminder.get('id', 'unknown')} with data: {update_data}")
                                                reminder.update(update_data)
                                                reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                                updated_count += 1
                                        except:
                                            pass
                                
                                user_reminders_data.set_value(reminders)
                                return JsonResponse({'status': 'success', 'updated_count': updated_count})
                            
                            # RRule确实发生了变化 - 需要创建新序列
                            logger.info(f"Modifying recurring rule from {cutoff_time} for series {series_id}")
                            
                            # 检查是否有新的trigger_time，如果有，使用它作为新系列的起始时间
                            new_start_time = cutoff_time
                            if 'trigger_time' in updates:
                                try:
                                    requested_time = datetime.datetime.fromisoformat(updates['trigger_time'])
                                    # 使用用户指定的新时间作为起始时间
                                    new_start_time = requested_time
                                    logger.info(f"Using requested trigger_time {requested_time} as new series start time")
                                except:
                                    logger.warning(f"Invalid trigger_time format: {updates.get('trigger_time')}, using cutoff_time")
                            
                            # 调用modify_recurring_rule方法，传递额外的更新参数和新的起始时间
                            # 如果用户提供了新的trigger_time，将其包含在additional_updates中
                            other_updates = {k: v for k, v in updates.items() if k not in ['rrule']}
                            updated_reminders = reminder_mgr.modify_recurring_rule(
                                reminders, series_id, new_start_time, new_rrule, 
                                scope='from_this', additional_updates=other_updates
                            )
                            
                            # 处理重复提醒数据以确保实例足够
                            final_reminders = reminder_mgr.process_reminder_data(updated_reminders)
                            user_reminders_data.set_value(final_reminders)
                            
                            logger.info(f"Successfully modified recurring rule for series {series_id}")
                            return JsonResponse({'status': 'success'})
                        
                        else:
                            # 只修改其他字段，不涉及RRule - 直接更新
                            logger.info(f"Modifying non-RRule fields from {cutoff_time} for series {series_id}")
                            
                            updated_count = 0
                            for reminder in reminders:
                                if (reminder.get('series_id') == series_id and 
                                    reminder.get('trigger_time')):
                                    try:
                                        trigger_time = datetime.datetime.fromisoformat(reminder['trigger_time'])
                                        if trigger_time >= cutoff_time:
                                            # 对于非RRule修改，排除trigger_time字段，保持原有时间
                                            update_data = {k: v for k, v in updates.items() if k != 'trigger_time'}
                                            reminder.update(update_data)
                                            reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                            updated_count += 1
                                    except:
                                        pass
                            
                            user_reminders_data.set_value(reminders)
                            return JsonResponse({'status': 'success', 'updated_count': updated_count})
                        
                    else:
                        # 其他情况的批量编辑（不涉及RRule修改）
                        updated_count = 0
                        for reminder in reminders:
                            should_update = False
                            if reminder.get('series_id') == series_id or reminder.get('id') == reminder_id:
                                if edit_scope == 'all':
                                    should_update = True
                                elif cutoff_time and reminder.get('trigger_time'):
                                    try:
                                        trigger_time = datetime.datetime.fromisoformat(reminder['trigger_time'])
                                        if trigger_time >= cutoff_time:
                                            should_update = True
                                    except:
                                        pass
                            
                            if should_update:
                                # 只更新非时间字段，保持原有的trigger_time
                                update_data = {k: v for k, v in updates.items() if k not in ['trigger_time']}
                                reminder.update(update_data)
                                reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                updated_count += 1
                        
                        user_reminders_data.set_value(reminders)
                        return JsonResponse({'status': 'success', 'updated_count': updated_count})
            
            return JsonResponse({'status': 'error', 'message': '无效的操作或范围'}, status=400)
                
        except Exception as e:
            logger.error(f"批量编辑提醒失败: {str(e)}")
            return JsonResponse({'status': 'error', 'message': f'操作失败: {str(e)}'}, status=500)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


def convert_recurring_to_single_impl(request):
    """
    将重复提醒转换为单次提醒的专用API端点
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': '不支持的请求方法'}, status=405)

    try:
        logger.info("=== Convert Recurring to Single Request ===")
        
        # 使用 request.data 兼容 DRF Request
        data = request.data if hasattr(request, 'data') else json.loads(request.body)
        series_id = data.get('series_id')
        reminder_id = data.get('reminder_id')
        update_data = data.get('update_data', {})
        
        logger.info(f"Series ID: {series_id}")
        logger.info(f"Target Reminder ID: {reminder_id}")
        logger.info(f"Update Data: {update_data}")
        
        if not series_id or not reminder_id:
            return JsonResponse({'status': 'error', 'message': '缺少必要参数'}, status=400)
        
        # 获取原生 Django request
        django_request = get_django_request(request)
        
        # 获取用户数据
        user_reminders_data, created, result = UserData.get_or_initialize(django_request, new_key="reminders")
        
        if user_reminders_data is None:
            return JsonResponse({'status': 'error', 'message': result.get('message', '获取用户数据失败')}, status=400)
        
        try:
            reminders = user_reminders_data.get_value()
            if not isinstance(reminders, list):
                reminders = []
        except:
            reminders = []
        
        # 找到目标提醒
        target_reminder = None
        for reminder in reminders:
            if reminder.get('id') == reminder_id:
                target_reminder = reminder
                break
                
        if not target_reminder:
            return JsonResponse({'status': 'error', 'message': '未找到目标提醒'}, status=400)
            
        target_time = datetime.datetime.fromisoformat(target_reminder['trigger_time'])
        logger.info(f"Target time: {target_time}")
        
        # 步骤1：将目标提醒转换为单次提醒
        target_reminder.update(update_data)
        target_reminder['rrule'] = None  # 清除RRule
        target_reminder['series_id'] = None  # 移除系列关联
        target_reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 步骤2：删除该系列中所有未来的提醒（时间晚于目标时间）
        reminders_to_keep = []
        deleted_count = 0
        
        for reminder in reminders:
            if reminder.get('series_id') == series_id:
                try:
                    reminder_time = datetime.datetime.fromisoformat(reminder['trigger_time'])
                    if reminder_time > target_time:
                        # 这是未来的提醒，删除它
                        deleted_count += 1
                        logger.info(f"Deleting future reminder: {reminder.get('id')} at {reminder_time}")
                        continue
                except:
                    pass
            
            reminders_to_keep.append(reminder)
        
        # 步骤3：为过去的提醒设置UNTIL截止时间
        past_reminders_updated = 0
        for reminder in reminders_to_keep:
            if (reminder.get('series_id') == series_id and 
                reminder.get('rrule') and 
                reminder.get('id') != reminder_id):
                try:
                    reminder_time = datetime.datetime.fromisoformat(reminder['trigger_time'])
                    if reminder_time <= target_time:
                        # 这是过去的提醒，需要添加UNTIL限制
                        current_rrule = reminder.get('rrule', '')
                        
                        # 检查是否已经有UNTIL或COUNT限制
                        if 'UNTIL=' not in current_rrule and 'COUNT=' not in current_rrule:
                            # 添加UNTIL限制到目标时间-1秒，避免重复生成
                            until_time = target_time - timedelta(seconds=1)
                            until_str = until_time.strftime('%Y%m%dT%H%M%S')
                            if ';' in current_rrule:
                                new_rrule = current_rrule + f';UNTIL={until_str}'
                            else:
                                new_rrule = current_rrule + f';UNTIL={until_str}'
                            
                            reminder['rrule'] = new_rrule
                            reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            past_reminders_updated += 1
                            logger.info(f"Updated past reminder {reminder.get('id')} with UNTIL={until_str}")
                except:
                    pass
        
        # 保存更新后的数据
        user_reminders_data.set_value(reminders_to_keep)
        
        logger.info(f"Conversion completed:")
        logger.info(f"- Target reminder converted to single")
        logger.info(f"- {deleted_count} future reminders deleted")
        logger.info(f"- {past_reminders_updated} past reminders updated with UNTIL")
        
        return JsonResponse({
            'status': 'success',
            'message': '重复提醒已成功转换为单次提醒',
            'deleted_count': deleted_count,
            'updated_count': past_reminders_updated
        })
        
    except Exception as e:
        logger.error(f"Error in convert_recurring_to_single: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
def snooze_reminder_impl(request):
    """延迟提醒"""
    if request.method == 'POST':
        # 获取原生 Django request
        django_request = get_django_request(request)
        
        user_reminders_data, created, result = UserData.get_or_initialize(django_request, new_key="reminders")
        reminders = user_reminders_data.get_value()
        
        # 使用 request.data 兼容 DRF Request
        data = request.data if hasattr(request, 'data') else json.loads(request.body)
        reminder_id = data.get('id')
        snooze_minutes = data.get('snooze_minutes', 10)  # 默认延迟10分钟
        
        if not reminder_id:
            return JsonResponse({'status': 'error', 'message': '提醒ID是必填项'}, status=400)
        
        # 查找要延迟的提醒
        reminder_found = False
        for reminder in reminders:
            if reminder['id'] == reminder_id:
                # 计算新的触发时间
                current_trigger = datetime.datetime.fromisoformat(reminder['trigger_time'].replace('Z', '+00:00'))
                new_trigger = current_trigger + timedelta(minutes=snooze_minutes)
                reminder['trigger_time'] = new_trigger.strftime("%Y-%m-%dT%H:%M:%S")
                reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                reminder_found = True
                break
        
        if not reminder_found:
            return JsonResponse({'status': 'error', 'message': '未找到指定的提醒'}, status=404)
        
        user_reminders_data.set_value(reminders)
        
        return JsonResponse({'status': 'success'})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)
@csrf_exempt
def dismiss_reminder_impl(request):
    """忽略/关闭提醒"""
    if request.method == 'POST':
        # 获取原生 Django request
        django_request = get_django_request(request)
        
        user_reminders_data, created, result = UserData.get_or_initialize(django_request, new_key="reminders")
        reminders = user_reminders_data.get_value()
        
        # 使用 request.data 兼容 DRF Request
        data = request.data if hasattr(request, 'data') else json.loads(request.body)
        reminder_id = data.get('id')
        
        if not reminder_id:
            return JsonResponse({'status': 'error', 'message': '提醒ID是必填项'}, status=400)
        
        # 查找要忽略的提醒
        reminder_found = False
        for reminder in reminders:
            if reminder['id'] == reminder_id:
                # 检查是否有重复规则（简单检查是否包含FREQ�?
                if reminder.get('rrule') and 'FREQ=' in reminder.get('rrule', ''):
                    # 有重复规则，简单地加一天作为下一次提�?
                    try:
                        current_trigger = datetime.datetime.fromisoformat(reminder['trigger_time'])
                        next_trigger = current_trigger + timedelta(days=1)
                        reminder['trigger_time'] = next_trigger.strftime("%Y-%m-%dT%H:%M:%S")
                        reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    except:
                        # 解析失败，直接标记为已忽�?
                        reminder['status'] = 'dismissed'
                        reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                else:
                    # 没有重复规则，直接标记为已忽�?
                    reminder['status'] = 'dismissed'
                    reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                reminder_found = True
                break
        
        if not reminder_found:
            return JsonResponse({'status': 'error', 'message': '未找到指定的提醒'}, status=404)
        
        user_reminders_data.set_value(reminders)
        
        return JsonResponse({'status': 'success'})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)

@csrf_exempt
def complete_reminder_impl(request):
    """完成提醒"""
    if request.method == 'POST':
        # 获取原生 Django request
        django_request = get_django_request(request)
        
        user_reminders_data, created, result = UserData.get_or_initialize(django_request, new_key="reminders")
        reminders = user_reminders_data.get_value()
        
        # 使用 request.data 兼容 DRF Request
        data = request.data if hasattr(request, 'data') else json.loads(request.body)
        reminder_id = data.get('id')
        
        if not reminder_id:
            return JsonResponse({'status': 'error', 'message': '提醒ID是必填项'}, status=400)
        
        # 查找要完成的提醒
        reminder_found = False
        for reminder in reminders:
            if reminder['id'] == reminder_id:
                # 检查是否有重复规则（简单检查是否包含FREQ�?
                if reminder.get('rrule') and 'FREQ=' in reminder.get('rrule', ''):
                    # 有重复规则，简单地加一天作为下一次提�?
                    try:
                        current_trigger = datetime.datetime.fromisoformat(reminder['trigger_time'])
                        next_trigger = current_trigger + timedelta(days=1)
                        reminder['trigger_time'] = next_trigger.strftime("%Y-%m-%dT%H:%M:%S")
                        reminder['status'] = 'active'  # 保持活跃状�?
                        reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    except:
                        # 解析失败，直接标记为已完�?
                        reminder['status'] = 'completed'
                        reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                else:
                    # 没有重复规则，直接标记为已完�?
                    reminder['status'] = 'completed'
                    reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                reminder_found = True
                break
        
        if not reminder_found:
            return JsonResponse({'status': 'error', 'message': '未找到指定的提醒'}, status=404)
        
        user_reminders_data.set_value(reminders)
        
        return JsonResponse({'status': 'success'})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)

