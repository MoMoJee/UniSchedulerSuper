import uuid
import datetime
import logging
import reversion
from core.models import UserData
from integrated_reminder_manager import IntegratedReminderManager

logger = logging.getLogger(__name__)

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
    def update_reminder(user, reminder_id, title=None, content=None, trigger_time=None, priority=None, status=None, rrule=None, session_id=None):
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
