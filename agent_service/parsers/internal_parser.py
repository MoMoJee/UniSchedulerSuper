"""
内部元素解析器

将系统内的 Event / Todo / Reminder / WorkflowRule 格式化为 AI 可读的文本。

关键适配：
  - Events, Todos, Reminders 存储在 UserData 表的 JSON 字段中，按 ID 遍历查找
  - WorkflowRule 是标准 Django ORM 模型，可直接 objects.get()
"""
from typing import Dict, Any, Optional

from .base import BaseParser
from logger import logger


class InternalElementParser(BaseParser):
    """解析系统内部元素（日程 / 待办 / 提醒 / 工作流）"""

    # 虚拟 MIME，仅用于 ParserFactory 分发
    INTERNAL_MIME = 'application/x-internal-element'

    def can_parse(self, mime_type: str) -> bool:
        return mime_type == self.INTERNAL_MIME

    # ---- 公共入口 ----

    def parse(self, file_path: str = None, **kwargs) -> Dict[str, Any]:
        """
        解析内部元素。

        必须通过 kwargs 传入：
            element_type: 'event' | 'todo' | 'reminder' | 'workflow'
            element_id:   元素 ID (str)
            user:         django.contrib.auth.models.User 实例
        """
        element_type = kwargs.get('element_type')
        element_id = kwargs.get('element_id')
        user = kwargs.get('user')

        if not all([element_type, element_id, user]):
            return {
                "success": False,
                "text": "",
                "metadata": {},
                "error": "缺少必要参数: element_type, element_id, user"
            }

        dispatch = {
            'event': self._parse_event,
            'todo': self._parse_todo,
            'reminder': self._parse_reminder,
            'workflow': self._parse_workflow,
        }

        handler = dispatch.get(element_type)
        if not handler:
            return {
                "success": False,
                "text": "",
                "metadata": {},
                "error": f"不支持的元素类型: {element_type}"
            }

        try:
            return handler(user, element_id)
        except Exception as e:
            logger.error(f"内部元素解析失败 [{element_type}:{element_id}]: {e}")
            return {
                "success": False,
                "text": "",
                "metadata": {},
                "error": str(e)
            }

    # ---- UserData 查找辅助 ----

    @staticmethod
    def _find_in_userdata(user, key: str, element_id: str) -> Optional[dict]:
        """从 UserData JSON 列表中按 id 查找元素"""
        from core.models import UserData

        class MockRequest:
            def __init__(self, u):
                self.user = u
                self.is_authenticated = True

        mock = MockRequest(user)
        user_data, _, _ = UserData.get_or_initialize(mock, new_key=key, data=[])
        items = user_data.get_value() or []

        for item in items:
            if item.get('id') == element_id:
                return item
        return None

    # ---- 各类型解析 ----

    def _parse_event(self, user, event_id: str) -> Dict[str, Any]:
        event = self._find_in_userdata(user, 'events', event_id)
        if not event:
            return self._not_found('event', event_id)

        lines = [
            f"📅 日程: {event.get('title', '无标题')}",
            f"时间: {event.get('start', '?')} → {event.get('end', '?')}",
        ]
        if event.get('description'):
            lines.append(f"描述: {event['description']}")
        if event.get('location'):
            lines.append(f"地点: {event['location']}")
        if event.get('importance'):
            lines.append(f"重要性: {event['importance']}")
        if event.get('urgency'):
            lines.append(f"紧急性: {event['urgency']}")
        if event.get('status'):
            lines.append(f"状态: {event['status']}")
        if event.get('ddl'):
            lines.append(f"截止: {event['ddl']}")
        if event.get('tags'):
            lines.append(f"标签: {', '.join(event['tags'])}")
        if event.get('is_recurring'):
            lines.append(f"重复规则: {event.get('rrule', '?')}")
        if event.get('linked_reminders'):
            lines.append(f"关联提醒: {len(event['linked_reminders'])} 个")

        return {
            "success": True,
            "text": '\n'.join(lines),
            "metadata": {
                "type": "event",
                "id": event_id,
                "title": event.get('title', ''),
                "start": event.get('start', ''),
                "end": event.get('end', ''),
            },
            "error": ""
        }

    def _parse_todo(self, user, todo_id: str) -> Dict[str, Any]:
        todo = self._find_in_userdata(user, 'todos', todo_id)
        if not todo:
            return self._not_found('todo', todo_id)

        status_map = {
            'pending': '待办',
            'in-progress': '进行中',
            'completed': '已完成',
            'cancelled': '已取消',
        }

        lines = [
            f"✅ 待办: {todo.get('title', '无标题')}",
            f"状态: {status_map.get(todo.get('status', ''), todo.get('status', '?'))}",
        ]
        if todo.get('description'):
            lines.append(f"描述: {todo['description']}")
        if todo.get('due_date'):
            lines.append(f"截止: {todo['due_date']}")
        if todo.get('importance'):
            lines.append(f"重要性: {todo['importance']}")
        if todo.get('urgency'):
            lines.append(f"紧急性: {todo['urgency']}")
        if todo.get('estimated_duration'):
            lines.append(f"预估耗时: {todo['estimated_duration']}")
        if todo.get('priority_score') is not None:
            lines.append(f"优先级分数: {todo['priority_score']}")
        if todo.get('dependencies'):
            lines.append(f"依赖项: {len(todo['dependencies'])} 个")
        if todo.get('linked_reminders'):
            lines.append(f"关联提醒: {len(todo['linked_reminders'])} 个")

        return {
            "success": True,
            "text": '\n'.join(lines),
            "metadata": {
                "type": "todo",
                "id": todo_id,
                "title": todo.get('title', ''),
                "status": todo.get('status', ''),
                "due_date": todo.get('due_date', ''),
            },
            "error": ""
        }

    def _parse_reminder(self, user, reminder_id: str) -> Dict[str, Any]:
        reminder = self._find_in_userdata(user, 'reminders', reminder_id)
        if not reminder:
            return self._not_found('reminder', reminder_id)

        lines = [
            f"🔔 提醒: {reminder.get('title', '无标题')}",
            f"触发时间: {reminder.get('trigger_time', '?')}",
            f"状态: {reminder.get('status', '?')}",
        ]
        if reminder.get('content'):
            lines.append(f"内容: {reminder['content']}")
        if reminder.get('priority'):
            lines.append(f"优先级: {reminder['priority']}")
        if reminder.get('is_recurring'):
            lines.append(f"重复规则: {reminder.get('rrule', '?')}")
        if reminder.get('linked_event_id'):
            lines.append(f"关联日程: {reminder['linked_event_id']}")
        if reminder.get('linked_todo_id'):
            lines.append(f"关联待办: {reminder['linked_todo_id']}")

        return {
            "success": True,
            "text": '\n'.join(lines),
            "metadata": {
                "type": "reminder",
                "id": reminder_id,
                "title": reminder.get('title', ''),
                "trigger_time": reminder.get('trigger_time', ''),
                "status": reminder.get('status', ''),
            },
            "error": ""
        }

    def _parse_workflow(self, user, workflow_id: str) -> Dict[str, Any]:
        """WorkflowRule 是标准 Django ORM 模型"""
        from agent_service.models import WorkflowRule

        try:
            rule = WorkflowRule.objects.get(id=int(workflow_id), user=user)
        except WorkflowRule.DoesNotExist:
            return self._not_found('workflow', workflow_id)
        except (ValueError, TypeError):
            return self._not_found('workflow', workflow_id)

        lines = [
            f"⚙️ 工作流: {rule.name}",
            f"触发条件: {rule.trigger}",
            f"步骤:\n{rule.steps}",
            f"状态: {'启用' if rule.is_active else '停用'}",
        ]

        return {
            "success": True,
            "text": '\n'.join(lines),
            "metadata": {
                "type": "workflow",
                "id": str(rule.id),
                "name": rule.name,
                "trigger": rule.trigger,
                "is_active": rule.is_active,
            },
            "error": ""
        }

    # ---- 通用辅助 ----

    @staticmethod
    def _not_found(element_type: str, element_id: str) -> Dict[str, Any]:
        type_names = {
            'event': '日程',
            'todo': '待办',
            'reminder': '提醒',
            'workflow': '工作流',
        }
        name = type_names.get(element_type, element_type)
        return {
            "success": False,
            "text": "",
            "metadata": {},
            "error": f"未找到{name} (ID: {element_id})"
        }

    # ---- 批量查找接口（供 API 使用）----

    @staticmethod
    def list_attachable_items(user, element_type: str, search: str = '') -> list:
        """
        列出可附件的内部元素，供前端选择器使用。

        Returns:
            list[dict]: 每项包含 id, title, subtitle, type
        """
        results = []

        if element_type == 'event':
            items = InternalElementParser._get_all_items(user, 'events')
            for item in items:
                title = item.get('title', '')
                if search and search.lower() not in title.lower():
                    continue
                results.append({
                    'id': item.get('id'),
                    'title': title,
                    'subtitle': f"{item.get('start', '')} ~ {item.get('end', '')}",
                    'type': 'event',
                })

        elif element_type == 'todo':
            items = InternalElementParser._get_all_items(user, 'todos')
            for item in items:
                title = item.get('title', '')
                if search and search.lower() not in title.lower():
                    continue
                status_map = {
                    'pending': '待办', 'in-progress': '进行中',
                    'completed': '已完成', 'cancelled': '已取消',
                }
                results.append({
                    'id': item.get('id'),
                    'title': title,
                    'subtitle': status_map.get(item.get('status', ''), item.get('status', '')),
                    'type': 'todo',
                })

        elif element_type == 'reminder':
            items = InternalElementParser._get_all_items(user, 'reminders')
            for item in items:
                title = item.get('title', '')
                if search and search.lower() not in title.lower():
                    continue
                results.append({
                    'id': item.get('id'),
                    'title': title,
                    'subtitle': item.get('trigger_time', ''),
                    'type': 'reminder',
                })

        elif element_type == 'workflow':
            from agent_service.models import WorkflowRule
            rules = WorkflowRule.objects.filter(user=user, is_active=True)
            if search:
                rules = rules.filter(name__icontains=search)
            for rule in rules:
                results.append({
                    'id': str(rule.id),
                    'title': rule.name,
                    'subtitle': rule.trigger,
                    'type': 'workflow',
                })

        return results

    @staticmethod
    def _get_all_items(user, key: str) -> list:
        """从 UserData 获取完整列表"""
        from core.models import UserData

        class MockRequest:
            def __init__(self, u):
                self.user = u
                self.is_authenticated = True

        mock = MockRequest(user)
        user_data, _, _ = UserData.get_or_initialize(mock, new_key=key, data=[])
        return user_data.get_value() or []
