"""
UniScheduler Agent Graph - 单Agent多工具模式
用户可选择启用的工具，Agent 根据可用工具执行任务
"""
import os
import sqlite3
import datetime
import json
from typing import Annotated, TypedDict, List, Literal, Optional
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

# 导入工具
from agent_service.tools.planner_tools import (
    get_events, create_event, update_event, delete_event,
    get_todos, create_todo, update_todo, delete_todo,
    get_reminders, create_reminder, delete_reminder
)
from agent_service.tools.memory_tools import save_memory, search_memory, get_recent_memories
# 导入新的记忆工具 V2
from agent_service.tools.memory_tools_v2 import (
    save_personal_info, get_personal_info, update_personal_info, delete_personal_info,
    get_dialog_style, update_dialog_style,
    save_workflow_rule, get_workflow_rules, update_workflow_rule, delete_workflow_rule,
    ALL_MEMORY_TOOLS_V2
)
# 导入 TODO 工具
from agent_service.tools.todo_tools import (
    create_todo as create_session_todo,
    update_todo_status, get_session_todos, clear_completed_todos,
    TODO_TOOLS
)
from agent_service.mcp_tools import get_mcp_tools_sync

from logger import logger
# ==========================================
# 配置区域
# ==========================================
os.environ.setdefault("OPENAI_API_KEY", "sk-d90196210d2a40ffb87cab0bfd08a192")
os.environ.setdefault("OPENAI_API_BASE", "https://api.deepseek.com")

# ==========================================
# 工具注册表
# ==========================================
# Planner 工具
PLANNER_TOOLS = {
    "get_events": get_events,
    "create_event": create_event,
    "update_event": update_event,
    "delete_event": delete_event,
    "get_todos": get_todos,
    "create_todo": create_todo,
    "update_todo": update_todo,
    "delete_todo": delete_todo,
    "get_reminders": get_reminders,
    "create_reminder": create_reminder,
    "delete_reminder": delete_reminder,
}

# Memory 工具 (旧版，保留兼容)
MEMORY_TOOLS_LEGACY = {
    "save_memory": save_memory,
    "search_memory": search_memory,
    "get_recent_memories": get_recent_memories,
}

# Memory 工具 V2 (新版)
MEMORY_TOOLS = {
    # 个人信息工具
    "save_personal_info": save_personal_info,
    "get_personal_info": get_personal_info,
    "update_personal_info": update_personal_info,
    "delete_personal_info": delete_personal_info,
    # 对话风格工具
    "get_dialog_style": get_dialog_style,
    "update_dialog_style": update_dialog_style,
    # 工作流规则工具
    "save_workflow_rule": save_workflow_rule,
    "get_workflow_rules": get_workflow_rules,
    "update_workflow_rule": update_workflow_rule,
    "delete_workflow_rule": delete_workflow_rule,
}

# TODO 工具
TODO_TOOLS_MAP = {
    "create_session_todo": create_session_todo,
    "update_todo_status": update_todo_status,
    "get_session_todos": get_session_todos,
    "clear_completed_todos": clear_completed_todos,
}

# MCP 工具 (动态加载)
MCP_TOOLS = {}
try:
    mcp_tools_list = get_mcp_tools_sync()
    if mcp_tools_list:
        MCP_TOOLS = {t.name: t for t in mcp_tools_list}
        print(f"信息: 成功加载 {len(MCP_TOOLS)} 个 MCP 工具: {list(MCP_TOOLS.keys())}")
    else:
        print("信息: MCP 工具列表为空")
except Exception as e:
    print(f"警告: MCP 工具加载失败: {e}")

# 所有工具的分类信息 (供 API 使用)
TOOL_CATEGORIES = {
    "planner": {
        "display_name": "日程管理",
        "description": "管理日程、待办、提醒",
        "tools": list(PLANNER_TOOLS.keys())
    },
    "memory": {
        "display_name": "记忆管理",
        "description": "保存和管理用户个人信息、偏好、工作流规则",
        "tools": list(MEMORY_TOOLS.keys())
    },
    "todo": {
        "display_name": "任务追踪",
        "description": "创建和管理会话级 TODO 列表，追踪多步骤任务进度",
        "tools": list(TODO_TOOLS_MAP.keys())
    },
    "map": {
        "display_name": "地图服务",
        "description": "查询地点、规划路线、周边搜索",
        "tools": list(MCP_TOOLS.keys())
    }
}

# 所有工具合集
ALL_TOOLS = {**PLANNER_TOOLS, **MEMORY_TOOLS, **TODO_TOOLS_MAP, **MCP_TOOLS}

def get_tools_by_names(tool_names: List[str]) -> list:
    """根据工具名称列表获取工具对象"""
    tools = []
    for name in tool_names:
        if name in ALL_TOOLS:
            tools.append(ALL_TOOLS[name])
    return tools

def get_all_tool_names() -> List[str]:
    """获取所有可用工具名称"""
    return list(ALL_TOOLS.keys())

def get_default_tools() -> List[str]:
    """获取默认启用的工具"""
    # 默认启用所有 planner、memory 和 todo 工具
    return list(PLANNER_TOOLS.keys()) + list(MEMORY_TOOLS.keys()) + list(TODO_TOOLS_MAP.keys())

# ==========================================
# 状态定义
# ==========================================
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    active_tools: List[str]  # 当前启用的工具名称列表

# ==========================================
# 模型初始化
# ==========================================
llm = ChatOpenAI(
    model="deepseek-chat",
    temperature=0,
    streaming=True,
    base_url=os.environ.get("OPENAI_API_BASE")
)

# ==========================================
# System Prompt 构建
# ==========================================
def build_system_prompt(user, active_tool_names: List[str], current_time: str) -> str:
    """
    构建 System Prompt
    - 加载用户的对话风格模板（如果有），否则使用默认模板
    - 添加工作流规则查询提示
    - 可选加载少量个人信息
    """
    from agent_service.models import DialogStyle, UserPersonalInfo
    
    # 1. 加载用户的对话风格模板
    try:
        if user and user.is_authenticated:
            dialog_style = DialogStyle.get_or_create_default(user)
            base_prompt = dialog_style.content
        else:
            base_prompt = DialogStyle.DEFAULT_TEMPLATE
    except Exception as e:
        logger.warning(f"[Agent] 加载对话风格失败: {e}")
        base_prompt = DialogStyle.DEFAULT_TEMPLATE
    
    # 2. 构建能力描述
    capabilities = []
    if any(t in active_tool_names for t in PLANNER_TOOLS.keys()):
        capabilities.append("- 管理日程 (Events): 查询、创建、更新、删除")
        capabilities.append("- 管理待办 (Todos): 查询、创建、更新、删除")
        capabilities.append("- 管理提醒 (Reminders): 查询、创建、删除")
    if any(t in active_tool_names for t in MEMORY_TOOLS.keys()):
        capabilities.append("- 记忆管理: 保存用户个人信息、偏好、工作流规则")
    if any(t in active_tool_names for t in TODO_TOOLS_MAP.keys()):
        capabilities.append("- 任务追踪: 创建和管理会话级 TODO 列表")
    if any(t in active_tool_names for t in MCP_TOOLS.keys()):
        capabilities.append("- 地图服务: 查询地点、规划路线、周边搜索")
    
    capabilities_str = "\n".join(capabilities) if capabilities else "- 基础对话功能"
    
    # 3. 工作流规则提示（不预加载，提示可查询）
    workflow_hint = ""
    if any(t in active_tool_names for t in ['get_workflow_rules', 'save_workflow_rule']):
        workflow_hint = """

## 工作流规则
如果用户给你布置了复杂的多步骤任务，你可以：
1. 使用 `get_workflow_rules` 工具查询是否有相关的工作流规则
2. 按照规则指导的步骤执行任务
3. 如果用户纠正了某个流程，使用 `save_workflow_rule` 或 `update_workflow_rule` 更新规则"""
    
    # 4. TODO 提示
    todo_hint = ""
    if any(t in active_tool_names for t in TODO_TOOLS_MAP.keys()):
        todo_hint = """

## 任务追踪
对于复杂的多步骤任务，你可以：
1. 使用 `create_session_todo` 创建任务列表，追踪需要完成的步骤
2. 使用 `update_todo_status` 更新任务状态 (pending/in_progress/done)
3. 完成所有任务后，使用 `clear_completed_todos` 清理已完成项"""
    
    # 5. 加载少量关键个人信息
    info_hint = ""
    try:
        if user and user.is_authenticated:
            key_infos = UserPersonalInfo.objects.filter(user=user)[:5]
            if key_infos.exists():
                info_hint = "\n\n## 用户基本信息\n" + "\n".join([f"- {i.key}: {i.value}" for i in key_infos])
    except Exception as e:
        logger.warning(f"[Agent] 加载个人信息失败: {e}")
    
    # 6. 组装完整 prompt
    system_prompt = f"""{base_prompt}

当前时间: {current_time}

你的能力:
{capabilities_str}

你当前可用的工具列表: {', '.join(active_tool_names) if active_tool_names else '无可用工具'}

注意事项:
1. 创建日程或提醒时，时间格式为: YYYY-MM-DDTHH:MM (例如: 2025-12-25T14:30)
2. 如果用户请求的功能不在你当前的能力范围内，请友好地告知用户
3. 如果用户没有提供完整信息，请礼貌询问
4. 工具调用后，请根据返回结果给用户一个清晰的回复
5. 如果用户提到重要的个人信息或偏好，请使用 save_personal_info 保存{workflow_hint}{todo_hint}{info_hint}"""
    
    return system_prompt


# ==========================================
# Agent 节点
# ==========================================
def agent_node(state: AgentState, config: RunnableConfig) -> dict:
    """
    统一的 Agent 节点，根据 active_tools 动态绑定工具
    
    注意: active_tools 优先从 config 中获取，以确保每次调用都使用最新的工具配置
    这是因为 LangGraph 的 checkpoint 机制会保存/恢复 state，可能导致 active_tools 被旧值覆盖
    """
    messages = state['messages']
    
    # 优先从 config 获取 active_tools，否则从 state 获取，最后使用默认值
    configurable = config.get("configurable", {})
    active_tool_names = configurable.get("active_tools") or state.get('active_tools') or get_default_tools()
    user = configurable.get("user")
    
    # 详细记录工具状态
    logger.debug(f"[Agent] agent_node 调用:")
    logger.debug(f"[Agent]   - state keys: {list(state.keys())}")
    logger.debug(f"[Agent]   - config.configurable: {configurable}")
    logger.debug(f"[Agent]   - active_tools from config: {configurable.get('active_tools', 'NOT SET')}")
    logger.debug(f"[Agent]   - active_tools from state: {state.get('active_tools', 'NOT SET')}")
    logger.debug(f"[Agent]   - active_tool_names (最终使用): {active_tool_names}")
    logger.debug(f"[Agent]   - 消息数量: {len(messages)}")
    
    # 获取当前时间
    now = datetime.datetime.now()
    current_time = now.strftime("%Y-%m-%d %H:%M:%S")
    
    # 构建 system prompt（使用新的构建函数）
    system_prompt = build_system_prompt(user, active_tool_names, current_time)
    
    # 动态获取工具
    tools = get_tools_by_names(active_tool_names)
    
    logger.debug(f"[Agent] 工具绑定:")
    logger.debug(f"[Agent]   - 请求的工具名称: {active_tool_names}")
    logger.debug(f"[Agent]   - 实际获取的工具数量: {len(tools)}")
    logger.debug(f"[Agent]   - 实际工具名称: {[t.name for t in tools]}")
    
    if tools:
        llm_with_tools = llm.bind_tools(tools)
    else:
        llm_with_tools = llm
    
    full_messages = [SystemMessage(content=system_prompt)] + messages
    response = llm_with_tools.invoke(full_messages, config)
    
    return {"messages": [response]}

# ==========================================
# 路由逻辑
# ==========================================
def route_after_agent(state: AgentState) -> Literal["tools", "END"]:
    """Agent 执行后，判断是否需要调用工具"""
    last_message = state['messages'][-1]
    
    # 如果有工具调用，前往 tools 节点
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        return "tools"
    
    # 否则结束
    return "END"

# ==========================================
# 图构建
# ==========================================
def create_tool_node_with_permission_check():
    """
    创建带权限检查的工具节点
    只有在 active_tools 中的工具才能被调用，否则返回错误消息
    """
    from langchain_core.messages import ToolMessage
    
    all_tools_dict = ALL_TOOLS
    
    def tool_node_with_check(state: AgentState, config: RunnableConfig) -> dict:
        """执行工具调用，并检查工具权限"""
        messages = state['messages']
        last_message = messages[-1]
        
        # 获取当前启用的工具列表
        configurable = config.get("configurable", {})
        active_tool_names = configurable.get("active_tools") or state.get('active_tools') or get_default_tools()
        
        logger.debug(f"[ToolNode] 权限检查:")
        logger.debug(f"[ToolNode]   - active_tools: {active_tool_names}")
        
        if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
            return {"messages": []}
        
        tool_messages = []
        for tool_call in last_message.tool_calls:
            tool_name = tool_call.get("name")
            tool_call_id = tool_call.get("id")
            tool_args = tool_call.get("args", {})
            
            logger.debug(f"[ToolNode]   - 请求调用工具: {tool_name}")
            
            # 检查工具是否被启用
            if tool_name not in active_tool_names:
                # 工具未启用，返回错误消息
                error_msg = f"工具 '{tool_name}' 未启用。请在工具选择面板中启用该工具后再试。"
                logger.warning(f"[ToolNode] 工具权限拒绝: {tool_name} 不在 active_tools 中")
                tool_messages.append(
                    ToolMessage(
                        content=error_msg,
                        tool_call_id=tool_call_id,
                        name=tool_name
                    )
                )
                continue
            
            # 检查工具是否存在
            if tool_name not in all_tools_dict:
                error_msg = f"工具 '{tool_name}' 不存在。"
                logger.error(f"[ToolNode] 工具不存在: {tool_name}")
                tool_messages.append(
                    ToolMessage(
                        content=error_msg,
                        tool_call_id=tool_call_id,
                        name=tool_name
                    )
                )
                continue
            
            # 执行工具
            try:
                tool = all_tools_dict[tool_name]
                result = tool.invoke(tool_args, config)
                logger.debug(f"[ToolNode]   - 工具执行成功: {tool_name}")
                tool_messages.append(
                    ToolMessage(
                        content=str(result),
                        tool_call_id=tool_call_id,
                        name=tool_name
                    )
                )
            except Exception as e:
                error_msg = f"工具 '{tool_name}' 执行失败: {str(e)}"
                logger.exception(f"[ToolNode] 工具执行异常: {tool_name}")
                tool_messages.append(
                    ToolMessage(
                        content=error_msg,
                        tool_call_id=tool_call_id,
                        name=tool_name
                    )
                )
        
        return {"messages": tool_messages}
    
    return tool_node_with_check


def create_workflow():
    """创建工作流图"""
    workflow = StateGraph(AgentState)
    
    # 添加节点
    workflow.add_node("agent", agent_node)
    
    # 使用带权限检查的工具节点
    workflow.add_node("tools", create_tool_node_with_permission_check())
    
    # 设置入口点
    workflow.set_entry_point("agent")
    
    # Agent 后的路由
    workflow.add_conditional_edges(
        "agent",
        route_after_agent,
        {
            "tools": "tools",
            "END": END
        }
    )
    
    # 工具调用后返回 Agent
    workflow.add_edge("tools", "agent")
    
    return workflow

# 创建工作流
workflow = create_workflow()

# ==========================================
# 编译图
# ==========================================
CHECKPOINTS_DIR = os.path.join(os.path.dirname(__file__), 'checkpoints')
os.makedirs(CHECKPOINTS_DIR, exist_ok=True)
CHECKPOINT_DB_PATH = os.path.join(CHECKPOINTS_DIR, 'agent_checkpoints.sqlite')

def get_checkpointer():
    """获取一个新的 SqliteSaver 实例"""
    conn = sqlite3.connect(CHECKPOINT_DB_PATH, check_same_thread=False)
    return SqliteSaver(conn)

# 创建全局 checkpointer
checkpointer = get_checkpointer()

# 编译带 checkpointer 的 app
app = workflow.compile(checkpointer=checkpointer)

# 也提供无 checkpointer 的版本
app_no_checkpointer = workflow.compile()

# ==========================================
# Checkpoint 操作函数
# ==========================================
def clear_session_checkpoints(thread_id: str) -> bool:
    """
    清除指定会话的所有 checkpoint（用于完全重置会话）
    
    Args:
        thread_id: 会话 ID
        
    Returns:
        是否成功清除
    """
    try:
        conn = sqlite3.connect(CHECKPOINT_DB_PATH, check_same_thread=False)
        cursor = conn.cursor()
        
        # 删除 checkpoints 表中的记录
        cursor.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        deleted_checkpoints = cursor.rowcount
        
        # 删除 checkpoint_writes 表中的记录（如果存在）
        try:
            cursor.execute("DELETE FROM checkpoint_writes WHERE thread_id = ?", (thread_id,))
        except sqlite3.OperationalError:
            pass  # 表可能不存在
        
        # 删除 checkpoint_blobs 表中的记录（如果存在）
        try:
            cursor.execute("DELETE FROM checkpoint_blobs WHERE thread_id = ?", (thread_id,))
        except sqlite3.OperationalError:
            pass  # 表可能不存在
        
        conn.commit()
        conn.close()
        
        logger.info(f"已清除会话 {thread_id} 的 {deleted_checkpoints} 个 checkpoint")
        return True
    except Exception as e:
        logger.exception(f"清除会话 checkpoint 失败: {e}")
        return False

# ==========================================
# 辅助函数
# ==========================================
def create_initial_state(user, active_tools=None):
    """创建初始状态"""
    if active_tools is None:
        active_tools = get_default_tools()
    
    return {
        "messages": [],
        "active_tools": active_tools
    }

def get_config(user, thread_id=None):
    """生成 config 字典"""
    if thread_id is None:
        thread_id = f"user_{user.id}_default"
    
    return {
        "configurable": {
            "thread_id": thread_id,
            "user": user
        }
    }
