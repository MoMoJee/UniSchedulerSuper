import uuid
import datetime
from logger import logger
import reversion
from core.models import UserData
from integrated_reminder_manager import IntegratedReminderManager

class MockRequest:
    def __init__(self, user):
        self.user = user
        self.is_authenticated = True

class ReminderService:
    @staticmethod
    def get_reminders(user):
        mock_request = MockRequest(user)
        user_reminders_data, _, _ = UserData.get_or_initialize(mock_request, new_key="reminders")
        if user_reminders_data:
            return user_reminders_data.get_value() or []
        return []

    @staticmethod
    def create_reminder(user, title, content="", trigger_time="", priority="normal", rrule="", session_id=None):
        mock_request = MockRequest(user)
        
        with reversion.create_revision():
            reversion.set_user(user)
            reversion.set_comment(f"Create reminder: {title}")
            
            user_reminders_data, _, _ = UserData.get_or_initialize(mock_request, new_key="reminders")
            if not user_reminders_data:
                raise Exception("Failed to get user reminders data")
                
            reminders = user_reminders_data.get_value() or []
            if not isinstance(reminders, list):
                reminders = []
                
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
            
            if rrule and 'FREQ=' in rrule:
                reminder_mgr = IntegratedReminderManager(mock_request)
                recurring_reminder = reminder_mgr.create_recurring_reminder(reminder_data, rrule)
                reminders.append(recurring_reminder)
                updated_reminders = reminder_mgr.process_reminder_data(reminders)
                user_reminders_data.set_value(updated_reminders)
                return recurring_reminder
            else:
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
                return reminder_data

    @staticmethod
    def update_reminder(user, reminder_id, title=None, content=None, trigger_time=None, priority=None, status=None, rrule=None, session_id=None, _clear_rrule=False):
        """
        更新提醒
        
        Args:
            _clear_rrule: 如果为True，会清除提醒的重复规则（将rrule设为空字符串）
                         这解决了 rrule=None（不修改）和 rrule=""（清除）的歧义
        """
        mock_request = MockRequest(user)
        
        with reversion.create_revision():
            reversion.set_user(user)
            reversion.set_comment(f"Update reminder: {reminder_id}")
            
            user_reminders_data, _, _ = UserData.get_or_initialize(mock_request, new_key="reminders")
            if not user_reminders_data:
                raise Exception("Failed to get user reminders data")
                
            reminders = user_reminders_data.get_value() or []
            
            target_reminder = None
            for reminder in reminders:
                if reminder['id'] == reminder_id:
                    target_reminder = reminder
                    break
            
            if not target_reminder:
                raise Exception("Reminder not found")
                
            if title is not None: target_reminder['title'] = title
            if content is not None: target_reminder['content'] = content
            if trigger_time is not None: target_reminder['trigger_time'] = trigger_time
            if priority is not None: target_reminder['priority'] = priority
            if status is not None: target_reminder['status'] = status
            
            # 处理 _clear_rrule: 显式清除重复规则
            if _clear_rrule:
                target_reminder['rrule'] = ''
                target_reminder['is_recurring'] = False
            
            target_reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            user_reminders_data.set_value(reminders)
            return target_reminder

    @staticmethod
    def delete_reminder(user, reminder_id, session_id=None):
        mock_request = MockRequest(user)
        user_reminders_data, _, _ = UserData.get_or_initialize(mock_request, new_key="reminders")
        if not user_reminders_data:
            raise Exception("Failed to get user reminders data")
            
        reminders = user_reminders_data.get_value() or []
        original_count = len(reminders)
        
        with reversion.create_revision():
            reversion.set_user(user)
            reversion.set_comment(f"Delete reminder: {reminder_id}")
            
            reminders = [r for r in reminders if r['id'] != reminder_id]
            
            if len(reminders) < original_count:
                user_reminders_data.set_value(reminders)
                return True
            return False

    @staticmethod
    def bulk_edit(user, reminder_id, operation='edit', edit_scope='single',
                  title=None, content=None, trigger_time=None, priority=None,
                  status=None, rrule=None, from_time=None, session_id=None):
        """
        批量编辑提醒 - 支持四种编辑范围
        
        Args:
            user: 用户对象
            reminder_id: 目标提醒ID
            operation: 操作类型 'edit' 或 'delete'
            edit_scope: 编辑范围
                - 'single': 仅当前实例（从系列独立出来）
                - 'all': 整个系列
                - 'from_this': 此实例及之后
                - 'from_time': 从指定时间开始（需配合 from_time 参数）
            from_time: edit_scope='from_time' 时的起始时间
            session_id: 会话ID（用于 AgentTransaction）
            其他参数: 要更新的字段
        
        Returns:
            dict: 操作结果
        """
        from rest_framework.test import APIRequestFactory
        from core.views_reminder import bulk_edit_reminders
        
        # 首先获取提醒信息以获取 series_id
        mock_request = MockRequest(user)
        user_reminders_data, _, _ = UserData.get_or_initialize(mock_request, new_key="reminders")
        reminders = user_reminders_data.get_value() or []
        
        target_reminder = None
        series_id = None
        for reminder in reminders:
            if reminder.get('id') == reminder_id:
                target_reminder = reminder
                series_id = reminder.get('series_id')
                break
        
        if not target_reminder:
            raise Exception(f"Reminder not found: {reminder_id}")
        
        # 构建请求数据
        request_data = {
            'reminder_id': reminder_id,
            'operation': operation,
            'edit_scope': edit_scope,
        }
        
        if series_id:
            request_data['series_id'] = series_id
        if from_time:
            request_data['from_time'] = from_time
        if title is not None:
            request_data['title'] = title
        if content is not None:
            request_data['content'] = content
        if trigger_time is not None:
            request_data['trigger_time'] = trigger_time
        if priority is not None:
            request_data['priority'] = priority
        if status is not None:
            request_data['status'] = status
        if rrule is not None:
            request_data['rrule'] = rrule
        
        # 使用 APIRequestFactory 创建模拟请求
        factory = APIRequestFactory()
        request = factory.post('/api/reminders/bulk-edit/', request_data, format='json')
        request.user = user
        request.validated_data = request_data  # 模拟 @validate_body 装饰器的效果
        
        # 调用现有的 bulk_edit_reminders
        with reversion.create_revision():
            reversion.set_user(user)
            reversion.set_comment(f"Bulk edit reminder: {reminder_id}, scope: {edit_scope}")
            
            response = bulk_edit_reminders(request)
        
        # 解析响应
        import json
        response_data = json.loads(response.content)
        
        if response.status_code != 200:
            raise Exception(response_data.get('message', 'Bulk edit failed'))
        
        return response_data
    
    @staticmethod
    def get_reminder_by_id(user, reminder_id):
        """根据ID获取单个提醒"""
        mock_request = MockRequest(user)
        user_reminders_data, _, _ = UserData.get_or_initialize(mock_request, new_key="reminders")
        reminders = user_reminders_data.get_value() or []
        
        for reminder in reminders:
            if reminder.get('id') == reminder_id:
                return reminder
        return None