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

# Memory 工具
MEMORY_TOOLS = {
    "save_memory": save_memory,
    "search_memory": search_memory,
    "get_recent_memories": get_recent_memories,
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
        "description": "保存和搜索用户偏好与重要信息",
        "tools": list(MEMORY_TOOLS.keys())
    },
    "map": {
        "display_name": "地图服务",
        "description": "查询地点、规划路线、周边搜索",
        "tools": list(MCP_TOOLS.keys())
    }
}

# 所有工具合集
ALL_TOOLS = {**PLANNER_TOOLS, **MEMORY_TOOLS, **MCP_TOOLS}

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
    # 默认启用所有 planner 和 memory 工具
    return list(PLANNER_TOOLS.keys()) + list(MEMORY_TOOLS.keys())

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
    
    # 根据启用的工具构建能力描述
    capabilities = []
    if any(t in active_tool_names for t in PLANNER_TOOLS.keys()):
        capabilities.append("- 管理日程 (Events): 查询、创建、更新、删除")
        capabilities.append("- 管理待办 (Todos): 查询、创建、更新、删除")
        capabilities.append("- 管理提醒 (Reminders): 查询、创建、删除")
    if any(t in active_tool_names for t in MEMORY_TOOLS.keys()):
        capabilities.append("- 记忆管理: 保存用户偏好和重要信息，搜索历史记忆")
    if any(t in active_tool_names for t in MCP_TOOLS.keys()):
        capabilities.append("- 地图服务: 查询地点、规划路线、周边搜索")
    
    capabilities_str = "\n".join(capabilities) if capabilities else "- 基础对话功能"
    
    system_prompt = f"""你是一个智能日程助手。
当前时间: {current_time}

你的能力:
{capabilities_str}

你当前可用的工具列表: {', '.join(active_tool_names) if active_tool_names else '无可用工具'}

注意事项:
1. 创建日程或提醒时，时间格式为: YYYY-MM-DDTHH:MM (例如: 2025-12-25T14:30)
2. 如果用户请求的功能不在你当前的能力范围内，请友好地告知用户
3. 如果用户没有提供完整信息，请礼貌询问
4. 工具调用后，请根据返回结果给用户一个清晰的回复
5. 如果用户提到重要的个人信息或偏好，请主动保存到记忆中
"""
    
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
def create_workflow():
    """创建工作流图"""
    workflow = StateGraph(AgentState)
    
    # 添加节点
    workflow.add_node("agent", agent_node)
    
    # 工具节点 (使用所有工具，实际可用性由 active_tools 控制)
    all_tools_list = list(ALL_TOOLS.values())
    workflow.add_node("tools", ToolNode(all_tools_list))
    
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
