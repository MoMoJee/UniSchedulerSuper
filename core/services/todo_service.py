import uuid
import datetime
from logger import logger
import reversion
from core.models import UserData

class MockRequest:
    def __init__(self, user):
        self.user = user
        self.is_authenticated = True

class TodoService:
    @staticmethod
    def get_todos(user):
        mock_request = MockRequest(user)
        user_todos_data, _, _ = UserData.get_or_initialize(mock_request, new_key="todos")
        if user_todos_data:
            return user_todos_data.get_value() or []
        return []

    @staticmethod
    def create_todo(user, title, description="", due_date="", estimated_duration="", importance="", urgency="", groupID="", session_id=None):
        mock_request = MockRequest(user)
        user_todos_data, _, _ = UserData.get_or_initialize(mock_request, new_key="todos")
        if not user_todos_data:
            raise Exception("Failed to get user todos data")
            
        todos = user_todos_data.get_value() or []
        if not isinstance(todos, list):
            todos = []
            
        with reversion.create_revision():
            reversion.set_user(user)
            reversion.set_comment(f"Create todo: {title}")
            
            new_todo = {
                "id": str(uuid.uuid4()),
                "title": title,
                "description": description,
                "due_date": due_date,
                "estimated_duration": estimated_duration,
                "importance": importance,
                "urgency": urgency,
                "groupID": groupID,
                "status": "pending",
                "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "last_modified": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            todos.append(new_todo)
            user_todos_data.set_value(todos)
            
            return new_todo

    @staticmethod
    def update_todo(user, todo_id, title=None, description=None, due_date=None, estimated_duration=None, importance=None, urgency=None, groupID=None, status=None, session_id=None):
        mock_request = MockRequest(user)
        user_todos_data, _, _ = UserData.get_or_initialize(mock_request, new_key="todos")
        if not user_todos_data:
            raise Exception("Failed to get user todos data")
            
        todos = user_todos_data.get_value() or []
        
        with reversion.create_revision():
            reversion.set_user(user)
            reversion.set_comment(f"Update todo: {todo_id}")
            
            target_todo = None
            for todo in todos:
                if todo['id'] == todo_id:
                    target_todo = todo
                    break
            
            if not target_todo:
                raise Exception("Todo not found")
                
            if title is not None: target_todo['title'] = title
            if description is not None: target_todo['description'] = description
            if due_date is not None: target_todo['due_date'] = due_date
            if estimated_duration is not None: target_todo['estimated_duration'] = estimated_duration
            if importance is not None: target_todo['importance'] = importance
            if urgency is not None: target_todo['urgency'] = urgency
            if groupID is not None: target_todo['groupID'] = groupID
            if status is not None: target_todo['status'] = status
            
            target_todo['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            user_todos_data.set_value(todos)
            return target_todo

    @staticmethod
    def delete_todo(user, todo_id, session_id=None):
        mock_request = MockRequest(user)
        user_todos_data, _, _ = UserData.get_or_initialize(mock_request, new_key="todos")
        if not user_todos_data:
            raise Exception("Failed to get user todos data")
            
        todos = user_todos_data.get_value() or []
        original_count = len(todos)
        
        with reversion.create_revision():
            reversion.set_user(user)
            reversion.set_comment(f"Delete todo: {todo_id}")
            
            todos = [t for t in todos if t['id'] != todo_id]
            
            if len(todos) < original_count:
                user_todos_data.set_value(todos)
                return True
            return False
