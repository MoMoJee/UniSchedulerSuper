"""
UniScheduler Agent Graph - 新架构实现
基于 Service Layer 和多专家系统 (Planner/Map/Chat)
"""
import os
import datetime
import json
from typing import Annotated, TypedDict, List, Literal
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

# 导入新的工具
from agent_service.tools.planner_tools import (
    get_events, create_event, update_event, delete_event,
    get_todos, create_todo, update_todo, delete_todo,
    get_reminders, create_reminder, delete_reminder
)
from agent_service.tools.memory_tools import save_memory, search_memory, get_recent_memories
from agent_service.mcp_tools import get_mcp_tools_sync

# ==========================================
# 配置区域
# ==========================================
# 从环境变量获取 API Key，如果不存在则使用默认值
os.environ.setdefault("OPENAI_API_KEY", "sk-d90196210d2a40ffb87cab0bfd08a192")
os.environ.setdefault("OPENAI_API_BASE", "https://api.deepseek.com")

# ==========================================
# 状态定义
# ==========================================
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    next: str  # 下一个节点
    active_experts: List[str]  # 活跃的专家列表 (可选: planner, map, chat)

# ==========================================
# 工具定义
# ==========================================
# Planner 工具集
planner_tools = [
    get_events, create_event, update_event, delete_event,
    get_todos, create_todo, update_todo, delete_todo,
    get_reminders, create_reminder, delete_reminder
]

# Memory 工具集
memory_tools = [save_memory, search_memory, get_recent_memories]

# MCP 工具集 (地图等外部工具)
try:
    mcp_tools = get_mcp_tools_sync()
except Exception as e:
    print(f"警告: MCP 工具加载失败: {e}")
    mcp_tools = []

# ==========================================
# 模型初始化
# ==========================================
llm = ChatOpenAI(
    model="deepseek-chat",
    temperature=0,
    base_url=os.environ.get("OPENAI_API_BASE")
)

# ==========================================
# Supervisor 节点 (路由器)
# ==========================================
def supervisor_node(state: AgentState, config: RunnableConfig) -> dict:
    """
    Supervisor 负责决定将任务分配给哪个专家。
    根据 active_experts 筛选可用的专家。
    """
    messages = state['messages']
    active_experts = state.get('active_experts', ['planner', 'map', 'chat'])
    
    # 如果最后一条消息不是人类消息，直接结束
    if not messages or not isinstance(messages[-1], HumanMessage):
        return {"next": "FINISH"}
    
    user_query = messages[-1].content
    
    # 构建专家选项
    expert_options = []
    if 'planner' in active_experts:
        expert_options.append("planner: 管理日程、待办、提醒")
    if 'map' in active_experts:
        expert_options.append("map: 地图查询、路线规划")
    if 'chat' in active_experts:
        expert_options.append("chat: 闲聊、记忆管理、通用问答")
    
    options_str = "\n".join(expert_options)
    
    # 构建路由提示词
    system_prompt = f"""你是一个任务分配助手。根据用户的请求，选择最合适的专家来处理。

可用专家:
{options_str}

用户请求: {user_query}

请只返回一个专家名称: planner, map, chat, 或 FINISH (如果任务已完成)。
只返回名称，不要有其他内容。
"""
    
    response = llm.invoke([SystemMessage(content=system_prompt)])
    next_expert = response.content.strip().lower()
    
    # 验证选择
    valid_choices = active_experts + ['finish']
    if next_expert not in valid_choices:
        next_expert = 'chat'  # 默认使用 chat
    
    return {"next": next_expert}

# ==========================================
# Worker 节点
# ==========================================
def planner_agent(state: AgentState, config: RunnableConfig) -> dict:
    """Planner Agent: 处理日程、待办、提醒"""
    messages = state['messages']
    
    # 获取当前时间
    now = datetime.datetime.now()
    current_time = now.strftime("%Y-%m-%d %H:%M:%S")
    
    system_prompt = f"""你是一个专业的日程管理助手。
当前时间: {current_time}

你可以:
- 查询、创建、更新、删除日程 (Events)
- 查询、创建、更新、删除待办事项 (Todos)
- 查询、创建、删除提醒 (Reminders)

注意事项:
1. 创建日程或提醒时，时间格式为: YYYY-MM-DDTHH:MM (例如: 2025-12-25T14:30)
2. 如果用户没有提供完整时间信息，请礼貌询问
3. 使用工具时，确保传递正确的参数
"""
    
    llm_with_tools = llm.bind_tools(planner_tools)
    full_messages = [SystemMessage(content=system_prompt)] + messages
    
    response = llm_with_tools.invoke(full_messages, config)
    return {"messages": [response]}

def map_agent(state: AgentState, config: RunnableConfig) -> dict:
    """Map Agent: 处理地图相关查询"""
    messages = state['messages']
    
    system_prompt = """你是一个地图查询助手。
你可以使用高德地图工具查询:
- 地点搜索
- 路线规划
- 周边信息

请根据用户需求调用合适的工具。
"""
    
    if not mcp_tools:
        return {"messages": [AIMessage(content="抱歉，地图工具当前不可用。")]}
    
    llm_with_tools = llm.bind_tools(mcp_tools)
    full_messages = [SystemMessage(content=system_prompt)] + messages
    
    response = llm_with_tools.invoke(full_messages, config)
    return {"messages": [response]}

def chat_agent(state: AgentState, config: RunnableConfig) -> dict:
    """Chat Agent: 闲聊和记忆管理"""
    messages = state['messages']
    
    system_prompt = """你是一个友好的聊天助手。
你可以:
- 与用户闲聊
- 记住用户的偏好和重要信息 (使用 save_memory)
- 回忆之前的对话内容 (使用 search_memory)

如果用户提到重要的个人信息或偏好，请主动保存到记忆中。
"""
    
    llm_with_tools = llm.bind_tools(memory_tools)
    full_messages = [SystemMessage(content=system_prompt)] + messages
    
    response = llm_with_tools.invoke(full_messages, config)
    return {"messages": [response]}

# ==========================================
# 路由逻辑
# ==========================================
def route_after_supervisor(state: AgentState) -> Literal["planner", "map", "chat", "FINISH"]:
    """根据 supervisor 的决定路由到相应的节点"""
    next_node = state.get("next", "FINISH")
    if next_node == "finish":
        return "FINISH"
    return next_node

def route_after_agent(state: AgentState) -> Literal["tools", "supervisor", "FINISH"]:
    """Agent 执行后，判断是否需要调用工具"""
    last_message = state['messages'][-1]
    
    # 如果有工具调用，前往 tools 节点
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        return "tools"
    
    # 否则返回 supervisor 继续路由
    return "supervisor"

# ==========================================
# 图构建
# ==========================================
workflow = StateGraph(AgentState)

# 添加节点
workflow.add_node("supervisor", supervisor_node)
workflow.add_node("planner", planner_agent)
workflow.add_node("map", map_agent)
workflow.add_node("chat", chat_agent)

# 工具节点 (合并所有工具)
all_tools = planner_tools + memory_tools + mcp_tools
workflow.add_node("tools", ToolNode(all_tools))

# 设置入口点
workflow.set_entry_point("supervisor")

# Supervisor 后的路由
workflow.add_conditional_edges(
    "supervisor",
    route_after_supervisor,
    {
        "planner": "planner",
        "map": "map",
        "chat": "chat",
        "FINISH": END
    }
)

# 各个 Agent 后的路由
for agent_name in ["planner", "map", "chat"]:
    workflow.add_conditional_edges(
        agent_name,
        route_after_agent,
        {
            "tools": "tools",
            "supervisor": "supervisor",
            "FINISH": END
        }
    )

# 工具调用后返回对应的 Agent
# 注意: 这里简化处理，统一返回 supervisor 重新路由
workflow.add_edge("tools", "supervisor")

# ==========================================
# 编译图
# ==========================================
# 使用 MemorySaver 作为 checkpointer (开发测试用，重启后数据会丢失)
# 生产环境建议使用持久化存储
checkpointer = MemorySaver()

app = workflow.compile(checkpointer=checkpointer)

# ==========================================
# 辅助函数
# ==========================================
def create_initial_state(user, active_experts=None):
    """创建初始状态"""
    if active_experts is None:
        active_experts = ['planner', 'chat']  # 默认启用 planner 和 chat
    
    return {
        "messages": [],
        "next": "",
        "active_experts": active_experts
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
