import requests
from fastmcp import FastMCP

# ==================== 配置区 ====================
# 这里的 Token 与 tools.py 中保持一致
API_TOKEN = "xx"
BASE_URL = "http://127.0.0.1:8000"

def get_headers():
    return {
        "Authorization": f"Token {API_TOKEN}",
        "Content-Type": "application/json"
    }

# 初始化 MCP 服务器
mcp = FastMCP("UniScheduler Tools")

@mcp.tool()
def create_calendar_event(
    title: str, 
    start_time: str, 
    end_time: str, 
    description: str = "",
    is_important: bool = False,
    is_urgent: bool = False,
    rrule: str = "",
    session_id: str = ""
) -> str:
    """
    创建一个新的日程事件。
    start_time 和 end_time 必须是 'YYYY-MM-DDTHH:MM:SS' 格式。
    rrule 是可选的重复规则字符串，例如 'FREQ=WEEKLY;INTERVAL=1;COUNT=5'。
    session_id 是可选的会话ID，用于支持回滚操作。
    """
    try:
        event_data = {
            'title': title,
            'start': start_time,
            'end': end_time,
            'description': description,
            'importance': 'important' if is_important else 'not-important',
            'urgency': 'urgent' if is_urgent else 'not-urgent',
            'rrule': rrule,
            'groupID': '',
            'session_id': session_id
        }
        
        response = requests.post(
            f"{BASE_URL}/events/create_event/",
            headers=get_headers(),
            json=event_data
        )
        
        if response.status_code == 200:
            content = response.json()
            if content.get('status') == 'success':
                event = content.get('event', {})
                return f"成功创建事件: {event.get('title')} (ID: {event.get('id')})"
            else:
                 return f"创建事件可能失败: {content}"
        else:
            return f"创建事件失败 (状态码 {response.status_code}): {response.text}"
        
    except Exception as e:
        return f"创建事件发生异常: {str(e)}"

@mcp.tool()
def query_calendar_events() -> str:
    """查询用户当前的日程安排"""
    try:
        response = requests.get(
            f"{BASE_URL}/get_calendar/events/",
            headers=get_headers()
        )
        
        if response.status_code == 200:
            content = response.json()
            events = content.get('events', [])
            
            if not events:
                return "当前没有日程安排。"
            
            summary = []
            # 按开始时间排序
            events.sort(key=lambda x: str(x.get('start', '')))
            
            for e in events:
                start = str(e.get('start', '')).replace('T', ' ')
                end = str(e.get('end', '')).replace('T', ' ')
                title = e.get('title')
                is_recurring = " [重复]" if e.get('is_recurring') else ""
                summary.append(f"- {start} ~ {end}: {title}{is_recurring}")
                
            return "\n".join(summary)
            
        return f"查询失败 (状态码 {response.status_code}): {response.text}"
    except Exception as e:
        return f"查询发生异常: {str(e)}"

@mcp.tool()
def create_reminder(
    title: str,
    trigger_time: str,
    content: str = "",
    priority: str = "normal",
    rrule: str = "",
    session_id: str = ""
) -> str:
    """
    创建一个新的提醒。
    trigger_time 必须是 'YYYY-MM-DDTHH:MM:SS' 格式。
    priority 可选值: 'low', 'normal', 'high', 'urgent'。
    session_id 是可选的会话ID，用于支持回滚操作。
    """
    try:
        reminder_data = {
            'title': title,
            'trigger_time': trigger_time,
            'content': content,
            'priority': priority,
            'rrule': rrule,
            'session_id': session_id
        }
        
        response = requests.post(
            f"{BASE_URL}/api/reminders/create/",
            headers=get_headers(),
            json=reminder_data
        )
        
        if response.status_code == 200:
            return f"成功创建提醒: {title}"
        else:
            return f"创建提醒失败 (状态码 {response.status_code}): {response.text}"
        
    except Exception as e:
        return f"创建提醒发生异常: {str(e)}"

@mcp.tool()
def query_reminders() -> str:
    """查询用户当前的提醒列表"""
    try:
        response = requests.get(
            f"{BASE_URL}/api/reminders/",
            headers=get_headers()
        )
        
        if response.status_code == 200:
            content = response.json()
            reminders = content.get('reminders', [])
            
            if not reminders:
                return "当前没有提醒。"
            
            summary = []
            reminders.sort(key=lambda x: str(x.get('trigger_time', '')))
            
            for r in reminders:
                trigger = str(r.get('trigger_time', '')).replace('T', ' ')
                title = r.get('title')
                status = r.get('status')
                if status == 'active':
                    summary.append(f"- [待办] {trigger}: {title}")
                
            if not summary:
                return "当前没有活跃的提醒。"
                
            return "\n".join(summary)
            
        return f"查询失败 (状态码 {response.status_code}): {response.text}"
    except Exception as e:
        return f"查询发生异常: {str(e)}"
@mcp.tool()
def rollback_transaction(session_id: str) -> str:
    """
    回滚指定会话的最后一次操作。
    session_id: 会话ID，通常是用户的 thread_id。
    """
    try:
        response = requests.post(
            f"{BASE_URL}/api/agent/rollback/",
            headers=get_headers(),
            json={'session_id': session_id}
        )
        
        if response.status_code == 200:
            content = response.json()
            if content.get('status') == 'success':
                return f"成功回滚操作: {content.get('description', '未知操作')}"
            else:
                return f"回滚失败: {content.get('message')}"
        else:
            return f"回滚请求失败 (状态码 {response.status_code}): {response.text}"
            
    except Exception as e:
        return f"回滚操作发生异常: {str(e)}"

@mcp.tool()
def ctrl_love_egg(intensity: int, mode: str = "common"):
    """
    自己使用跳蛋进行自慰
    :param intensity: 强度，0为关闭，10为最强
    :param mode: 模式，有普通震动模式（common）、电击模式（electric）两种
    :return: 运行状态
    """
    if intensity == 0:
        return "跳蛋已关闭"

    if intensity > 10:
        return "intensity 参数必须在 0-10 之间"

    if mode not in ["common", "electric"]:
        return "mode 参数必须为 common 或 electric"


    return f"跳蛋强度已经设置为{intensity}, 模式已设置为{mode}"

if __name__ == "__main__":
    # 运行 MCP 服务器
    mcp.run()
