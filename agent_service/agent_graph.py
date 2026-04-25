"""
UniScheduler Agent Graph - 单Agent多工具模式
用户可选择启用的工具，Agent 根据可用工具执行任务
"""
import os
import sqlite3
import datetime
import json
from typing import Annotated, TypedDict, List, Literal, Optional, Dict
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

# 导入工具
from agent_service.tools.planner_tools import (
    get_events, create_event, update_event, delete_event,
    get_todos, create_todo, update_todo, delete_todo,
    get_reminders, create_reminder, delete_reminder
)
# 导入统一 Planner 工具（优化版）
from agent_service.tools.unified_planner_tools import (
    search_items, create_item, update_item, delete_item,
    get_event_groups, get_share_groups, complete_todo, 
    check_schedule_conflicts, UNIFIED_PLANNER_TOOLS
)
from agent_service.tools.memory_tools import save_memory, search_memory, get_recent_memories
# 导入新的记忆工具 V2
from agent_service.tools.memory_tools_v2 import (
    save_personal_info, get_personal_info, update_personal_info, delete_personal_info,
    get_dialog_style, update_dialog_style,
    save_workflow_rule, get_workflow_rules, update_workflow_rule, delete_workflow_rule,
    ALL_MEMORY_TOOLS_V2
)
# 导入 to do 工具（任务追踪）
from agent_service.tools.todo_tools import (
    add_task, update_task_status, get_task_list, clear_completed_tasks,
    TODO_TOOLS
)
# 导入联网搜索工具
from agent_service.tools.search_tools import (
    web_search, web_search_advanced,
    SEARCH_TOOLS_MAP, is_search_available
)
# 导入 VariFlight 航班查询工具
from agent_service.tools.variflight_tools import (
    query_flight_by_number, query_flights_by_route,
    query_flight_itineraries, query_flight_transfer,
    VARIFLIGHT_TOOLS_MAP, VARIFLIGHT_TOOL_DESCRIPTIONS,
    is_variflight_available
)
# 导入 Skill 工具
from agent_service.tools.skill_tools import (
    save_skill, list_skills as list_skills_tool,
    SKILL_TOOLS
)
# 导入云盘文件搜索工具
from agent_service.tools.cloud_file_tools import (
    search_cloud_files, read_cloud_file,
    CLOUD_FILE_TOOLS_MAP
)
from agent_service.mcp_tools import get_mcp_tools_sync

# 导入上下文优化模块
from agent_service.context_optimizer import (
    TokenCalculator, ToolMessageCompressor,
    get_current_model_config, get_optimization_config, update_token_usage
)
from agent_service.context_summarizer import (
    ConversationSummarizer, build_optimized_context, build_full_context
)

from logger import logger
# ==========================================
# 配置区域 - 从统一配置读取 API 密钥
# ==========================================
from config.api_keys_manager import APIKeyManager

# ==========================================
# 工具注册表
# ==========================================
# Planner 工具（旧版，保留兼容）
PLANNER_TOOLS_LEGACY = {
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

# Planner 工具（新版 - 统一简化接口）
# 优化点：
# - 统一搜索：search_items 替代 get_events/get_todos/get_reminders
# - 标识符解析：支持 #1/#2（搜索结果序号）、UUID、标题匹配
# - 事件组映射：自动将组名转为 UUID
# - 增量编辑：只需传入要修改的参数
# - 简化重复规则：支持 "每周一三五" 等自然语言格式
PLANNER_TOOLS = {
    "search_items": search_items,
    "create_item": create_item,
    "update_item": update_item,
    "delete_item": delete_item,
    "get_event_groups": get_event_groups,
    "get_share_groups": get_share_groups,
    "complete_todo": complete_todo,
    "check_schedule_conflicts": check_schedule_conflicts,
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

# TO DO 工具（任务追踪 - 用于 Agent 执行复杂多步骤任务时的进度追踪）
TODO_TOOLS_MAP = {
    "add_task": add_task,
    "update_task_status": update_task_status,
    "get_task_list": get_task_list,
    "clear_completed_tasks": clear_completed_tasks,
}

# Skill 工具（技能管理 - Agent 可创建/列举用户技能）
SKILL_TOOLS_MAP = SKILL_TOOLS

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
        "description": "统一管理日程、待办、提醒（优化版）",
        "tools": list(PLANNER_TOOLS.keys()),
        "tool_descriptions": {
            "search_items": "统一搜索日程/待办/提醒，返回带序号的结果",
            "create_item": "创建日程/待办/提醒，支持事件组名称和简化重复规则",
            "update_item": "更新项目，支持 #序号 引用，增量更新",
            "delete_item": "删除项目，支持系列删除控制",
            "check_schedule_conflicts": "冲突检测",
            "get_event_groups": "获取事件组列表",
            "get_share_groups": "获取用户所在的分享组列表",
            "complete_todo": "快捷完成待办",
        }
    },
    "planner_legacy": {
        "display_name": "日程管理（旧版）",
        "description": "管理日程、待办、提醒（兼容旧版）",
        "tools": list(PLANNER_TOOLS_LEGACY.keys()),
        "hidden": True  # 隐藏不在 UI 显示，但仍可通过 API 启用
    },
    "memory": {
        "display_name": "记忆管理",
        "description": "保存和管理用户个人信息、偏好、工作流规则",
        "tools": list(MEMORY_TOOLS.keys())
    },
    "todo": {
        "display_name": "任务追踪",
        "description": "Agent 执行复杂任务时追踪进度（不是用户的待办事项）",
        "tools": list(TODO_TOOLS_MAP.keys())
    },
    "map": {
        "display_name": "地图服务",
        "description": "查询地点、规划路线、周边搜索（高德地图）",
        # 排除包含 'train' 的工具（避免与火车票查询工具冲突，如 get-train-route-stations）
        "tools": [t for t in MCP_TOOLS.keys() if 
                  ('amap' in t.lower() or 'maps' in t.lower() or 'poi' in t.lower() or 
                   'route' in t.lower() or 'geocode' in t.lower() or 'regeo' in t.lower() or 
                   'weather' in t.lower() or 'district' in t.lower() or 'traffic' in t.lower()) and
                  'train' not in t.lower()]  # 排除火车相关工具
    },
    "train": {
        "display_name": "火车票查询",
        "description": "12306 火车票查询、车站搜索、余票查询、换乘方案",
        "tools": [t for t in MCP_TOOLS.keys() if 'ticket' in t.lower() or 'train' in t.lower() or 'station' in t.lower() or 'transfer' in t.lower() or '12306' in t.lower() or 'query-ticket' in t.lower()],
        "tool_descriptions": {
            "query-tickets": "余票/车次/座席/时刻一站式查询",
            "query-ticket-price": "实时查询各车次票价信息",
            "search-stations": "车站智能搜索（支持中文/拼音/简拼）",
            "query-transfer": "一次中转换乘方案",
            "get-train-route-stations": "查询列车经停站及时刻表",
            "get-current-time": "获取当前时间与相对日期",
            "get-train-no-by-train-code": "车次号转官方编号"
        }
    },
    "search": {
        "display_name": "联网搜索",
        "description": "实时网络搜索，获取最新新闻、资讯和信息",
        "tools": list(SEARCH_TOOLS_MAP.keys()) if is_search_available() else [],
        "tool_descriptions": {
            "web_search": "简单搜索，快速获取网络信息",
            "web_search_advanced": "高级搜索，支持时间、来源、主题等精细控制",
        }
    },
    "flight": {
        "display_name": "航班查询",
        "description": "飞常准航班查询：航班动态、票价、中转方案",
        "tools": list(VARIFLIGHT_TOOLS_MAP.keys()) if is_variflight_available() else [],
        "tool_descriptions": VARIFLIGHT_TOOL_DESCRIPTIONS
    },
    "skill": {
        "display_name": "技能管理",
        "description": "创建和管理 Agent 技能（可复用的行为指令）",
        "tools": list(SKILL_TOOLS_MAP.keys()),
        "tool_descriptions": {
            "save_skill": "保存/更新一个技能",
            "list_skills": "列出所有已保存的技能",
        }
    },
    "cloud_file": {
        "display_name": "云盘文件",
        "description": "搜索和读取云盘中的文件内容",
        "tools": list(CLOUD_FILE_TOOLS_MAP.keys()),
        "tool_descriptions": {
            "search_cloud_files": "在云盘中搜索文件内容",
            "read_cloud_file": "读取云盘文件的 Markdown 内容",
        }
    }
}

# 所有工具合集（包含新旧版本）
ALL_TOOLS = {**PLANNER_TOOLS, **PLANNER_TOOLS_LEGACY, **MEMORY_TOOLS, **TODO_TOOLS_MAP, **SKILL_TOOLS_MAP, **MCP_TOOLS, **SEARCH_TOOLS_MAP, **VARIFLIGHT_TOOLS_MAP, **CLOUD_FILE_TOOLS_MAP}

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
    # 默认启用所有 planner、memory、todo 和 skill 工具
    return list(PLANNER_TOOLS.keys()) + list(MEMORY_TOOLS.keys()) + list(TODO_TOOLS_MAP.keys()) + list(SKILL_TOOLS_MAP.keys()) + list(CLOUD_FILE_TOOLS_MAP.keys())

# ==========================================
# 状态定义
# ==========================================
def _replace_list(existing: List[int], new: List[int]) -> List[int]:
    """用于 AgentState 中 selected_skill_ids 的 reducer：直接替换（不累加）"""
    return new

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    active_tools: List[str]  # 当前启用的工具名称列表
    selected_skill_ids: Annotated[List[int], _replace_list]  # 筛选器选出的 skill ID

# ==========================================
# 模型初始化
# ==========================================
class DisabledLLM:
    """无可用 LLM 配置时的降级占位符。"""

    def __init__(self, reason: str):
        self.reason = reason

    def bind_tools(self, tools):
        return self

    def invoke(self, *args, **kwargs):
        raise RuntimeError(self.reason)

    async def ainvoke(self, *args, **kwargs):
        raise RuntimeError(self.reason)


def _normalize_base_url(base_url: str) -> str:
    """统一处理 base_url 格式，去掉 /chat/completions 并移除末尾斜杠。"""
    if not base_url:
        return ""
    if base_url.endswith('/chat/completions'):
        base_url = base_url.rsplit('/chat/completions', 1)[0]
    return base_url.rstrip('/')


def _build_chat_llm(model_name: str, base_url: str, api_key: str) -> Optional[ChatOpenAI]:
    """构建 ChatOpenAI 实例，不满足条件时返回 None。"""
    if not model_name or not base_url or not api_key:
        return None
    return ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=api_key,  # type: ignore
        # temperature=0,
        streaming=False,  # 关闭流式传输（项目只需节点级别流式，不需要 LLM 级别流式）
    )


_default_llm: Optional[object] = None


def get_default_llm():
    """
    获取默认 LLM 实例（系统模型 > 环境变量 > 降级占位符）。
    """
    global _default_llm
    if _default_llm is not None:
        return _default_llm

    system_models = APIKeyManager.get_system_models()

    for model_id, model_config in system_models.items():
        if not model_config:
            continue
        api_key = model_config.get('api_key', '')
        base_url = _normalize_base_url(model_config.get('base_url', ''))
        model_name = model_config.get('model_name', '')
        llm = _build_chat_llm(model_name, base_url, api_key)
        if llm:
            logger.info(f"[LLM] 使用默认系统模型: {model_name} ({model_id})")
            _default_llm = llm
            return _default_llm

    env_api_key = os.environ.get("OPENAI_API_KEY", "")
    env_base_url = _normalize_base_url(
        os.environ.get("OPENAI_API_BASE", "") or os.environ.get("OPENAI_BASE_URL", "")
    )
    env_model = os.environ.get("OPENAI_MODEL", "")
    env_llm = _build_chat_llm(env_model, env_base_url, env_api_key)
    if env_llm:
        logger.info("[LLM] 使用环境变量配置的默认模型")
        _default_llm = env_llm
        return _default_llm

    _default_llm = DisabledLLM(
        "LLM 未配置。请在 config/api_keys.json 的 system_models 中配置，或设置 OPENAI_API_KEY/OPENAI_API_BASE/OPENAI_MODEL 环境变量。"
    )
    logger.warning("[LLM] 未检测到可用模型配置，已进入降级模式")
    return _default_llm


def get_user_llm(user):
    """
    获取用户配置的 LLM 实例
    
    根据用户选择的模型（系统模型或自定义模型）创建对应的 LLM 实例。
    系统模型的配置从 api_keys.json 统一读取。
    
    Args:
        user: Django User 对象
    
    Returns:
        ChatOpenAI 实例
    """
    if not user or not user.is_authenticated:
        return get_default_llm()
    
    try:
        current_model_id, model_config = get_current_model_config(user)
        
        # 判断是否为系统模型
        is_system = model_config.get('provider') == 'system' or current_model_id.startswith('system_')
        
        if is_system:
            # 系统模型：从统一配置读取
            system_model_config = APIKeyManager.get_system_model_config(current_model_id)
            if system_model_config:
                api_key = system_model_config.get('api_key', '')
                base_url = system_model_config.get('base_url', '')
                model_name = system_model_config.get('model_name', 'deepseek-chat')
                
                # 调试日志
                logger.debug(f"[LLM] 系统模型配置: id={current_model_id}, model={model_name}")
                logger.debug(f"[LLM] base_url(原始): {base_url}")
                logger.debug(f"[LLM] api_key(前8位): {api_key[:8] if api_key else 'None'}...")
                
                # 统一处理 base_url（与自定义模型保持一致）
                base_url = _normalize_base_url(base_url)
                
                logger.debug(f"[LLM] base_url(处理后): {base_url}")
                
                user_llm = _build_chat_llm(model_name, base_url, api_key)
                if user_llm:
                    logger.debug(f"[LLM] 使用系统模型: {model_name} ({current_model_id}) @ {base_url}")
                    return user_llm
            
            # 系统模型配置不存在，使用默认
            logger.warning(f"[LLM] 系统模型 {current_model_id} 配置不存在，使用默认")
            return get_default_llm()
        
        # 自定义模型：使用用户配置
        api_url = model_config.get('api_url', '') or model_config.get('base_url', '')
        api_url = _normalize_base_url(api_url)
        
        api_key = model_config.get('api_key', '')
        model_name = model_config.get('model_name', model_config.get('model', ''))
        
        user_llm = _build_chat_llm(model_name, api_url, api_key)
        if user_llm:
            logger.debug(f"[LLM] 使用自定义模型: {model_name} @ {api_url}")
            return user_llm
        
    except Exception as e:
        logger.warning(f"[LLM] 创建用户 LLM 失败，使用默认: {e}")

    return get_default_llm()


# ==========================================
# System Prompt 构建
# ==========================================
def build_system_prompt(user, active_tool_names: List[str], current_time: str, selected_skill_ids: List[int] = None, summary_metadata: Optional[Dict] = None) -> str:
    """
    构建 System Prompt
    - 加载用户的对话风格模板（如果有），否则使用默认模板
    - 添加工作流规则查询提示
    - 可选加载少量个人信息
    - 注入被 Skill Selector 选中的技能完整内容
    - summary_metadata: 實际传入时会在系统提示中增加上下文状态声明
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
    # 检查新版统一 Planner 工具
    if any(t in active_tool_names for t in PLANNER_TOOLS.keys()):
        capabilities.append("- 日程/待办/提醒管理（统一接口）:")
        capabilities.append("  - search_items: 统一搜索，返回带 #序号 的结果")
        capabilities.append("  - create_item: 创建日程/待办/提醒，event_group 支持名称，repeat 支持简化格式")
        capabilities.append("  - update_item: 更新项目，identifier 支持 #1/#2、UUID、标题匹配")
        capabilities.append("  - delete_item: 删除项目，支持系列删除")
        capabilities.append("  - complete_todo: 快捷完成待办")
        capabilities.append("  - check_schedule_conflicts: 智能冲突检查，结合算法检测+LLM分析+个人偏好")
    # 检查旧版 Planner 工具
    elif any(t in active_tool_names for t in PLANNER_TOOLS_LEGACY.keys()):
        capabilities.append("- 管理日程 (Events): 查询、创建、更新、删除")
        capabilities.append("- 管理待办 (Todos): 查询、创建、更新、删除")
        capabilities.append("- 管理提醒 (Reminders): 查询、创建、删除")
    if any(t in active_tool_names for t in MEMORY_TOOLS.keys()):
        capabilities.append("- 记忆管理: 保存用户个人信息、偏好、工作流规则")
    if any(t in active_tool_names for t in TODO_TOOLS_MAP.keys()):
        capabilities.append("- 任务追踪: 创建和管理会话级任务列表")
    if any(t in active_tool_names for t in SKILL_TOOLS_MAP.keys()):
        capabilities.append("- 技能管理: 保存和列举可复用的行为指令（skill）")
    
    # 检查 MCP 工具 - 分类处理
    # 注意：排除包含 'train' 的工具，避免与火车票查询工具冲突
    map_tools = [t for t in active_tool_names if t in MCP_TOOLS and 
                 ('amap' in t.lower() or 'maps' in t.lower() or 'poi' in t.lower() or 
                  'route' in t.lower() or 'geocode' in t.lower()) and
                 'train' not in t.lower()]
    train_tools = [t for t in active_tool_names if t in MCP_TOOLS and 
                   ('ticket' in t.lower() or 'train' in t.lower() or 'station' in t.lower() or 'transfer' in t.lower())]
    
    if map_tools:
        capabilities.append("- 地图服务: 查询地点、规划路线、周边搜索（高德地图）")
    if train_tools:
        capabilities.append("- 火车票查询（12306）:")
        capabilities.append("  - query-tickets: 余票/车次/座席/时刻一站式查询")
        capabilities.append("  - query-ticket-price: 实时查询各车次票价信息")
        capabilities.append("  - search-stations: 车站智能搜索（支持中文/拼音/简拼）")
        capabilities.append("  - query-transfer: 一次中转换乘方案")
        capabilities.append("  - get-train-route-stations: 查询列车经停站及时刻表")
        capabilities.append("  - get-current-time: 获取当前时间与相对日期")
    
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
    
    # 4. 任务追踪提示
    todo_hint = ""
    if any(t in active_tool_names for t in TODO_TOOLS_MAP.keys()):
        todo_hint = """

## 任务追踪（注意：这不是用户的"待办事项"！）
当你执行复杂的多步骤任务时，可以使用任务追踪功能来管理执行进度：
1. 使用 `add_task` 添加任务到追踪列表
2. 使用 `update_task_status` 更新任务状态 (pending/in_progress/done)
3. 完成所有任务后，使用 `clear_completed_tasks` 清理已完成项

重要区分：
- `add_task` 等是 Agent 的任务追踪工具，用于追踪当前对话中要执行的步骤
- `create_todo` 等是用户的待办事项工具，用于创建用户自己的待办清单

## 状态快照（可选，供会话恢复使用）
完成一个复杂任务周期后，可在回复末尾附加状态块（用户屏蔽，系统解析）：
```
[AGENT_STATE]
phase: "planning|executing|done"
pending: ["待处理事项1", "待处理事项2"]
findings: ["关键发现1"]
[/AGENT_STATE]
```"""
    
    # 5. 加载少量关键个人信息
    info_hint = ""
    try:
        if user and user.is_authenticated:
            key_infos = UserPersonalInfo.objects.filter(user=user)[:5]
            if key_infos.exists():
                info_hint = "\n\n## 用户基本信息\n" + "\n".join([f"- {i.key}: {i.value}" for i in key_infos])
    except Exception as e:
        logger.warning(f"[Agent] 加载个人信息失败: {e}")

    # 6a. 上下文状态提示（有历史总结时注入，让 LLM 明确感知压缩信息）
    context_status_hint = ""
    if summary_metadata and summary_metadata.get('summary'):
        summarized_until = summary_metadata.get('summarized_until', 0)
        context_status_hint = f"""

## 上下文状态
当前会话已有 {summarized_until} 条历史消息被自动压缩为摘要（详情见下方《对话历史总结》）。
- 消息 #{summarized_until} 起为完整历史
- 如需引用早期内容，请告知用户“早期历史已压缩”并请其重新提供相关信息"""
        logger.info(f"[Prompt] 注入上下文状态提示: summarized_until={summarized_until}")

    # 6b. 注入最新 AGENT_STATE 快照（如果存在）
    agent_state_hint = ""
    if summary_metadata and summary_metadata.get('state_snapshot'):
        snapshot = summary_metadata['state_snapshot']
        phase = snapshot.get('phase', 'idle')
        pending = snapshot.get('pending_tasks', [])
        findings = snapshot.get('accumulated_findings', [])

        if phase != 'idle' or pending or findings:
            parts = ["\n\n## 上次任务状态快照（由你在上轮结束时生成）"]
            parts.append(f"- 阶段: {phase}")
            if pending:
                pending_str = ', '.join(pending) if isinstance(pending, list) else str(pending)
                parts.append(f"- 待处理: {pending_str}")
            if findings:
                findings_str = ', '.join(findings) if isinstance(findings, list) else str(findings)
                parts.append(f"- 关键发现: {findings_str}")
            parts.append("请根据此状态继续任务，如已完成则忽略。")
            agent_state_hint = '\n'.join(parts)
            logger.info(f"[Prompt] 注入 AGENT_STATE 快照: phase={phase}")

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
5. 如果用户提到重要的个人信息或偏好，请使用 save_personal_info 保存
6. 如果用户要求将某段流程或知识沉淀为可复用的指令，使用 save_skill 保存为技能{workflow_hint}{todo_hint}{info_hint}{context_status_hint}{agent_state_hint}"""

    # 7. 注入被 Skill Selector 选中的技能完整内容
    skill_hint = ""
    if selected_skill_ids:
        try:
            from agent_service.models import AgentSkill
            selected_skills = AgentSkill.objects.filter(
                id__in=selected_skill_ids,
                user=user,
                is_active=True
            )
            if selected_skills.exists():
                skill_sections = []
                skill_list_lines = []
                for s in selected_skills:
                    skill_sections.append(f"### {s.name}\n{s.content}")
                    desc = s.description.strip() if s.description else "无描述"
                    skill_list_lines.append(f"- [{s.id}] {s.name}：{desc}")
                skill_activation_list = "\n".join(skill_list_lines)
                skill_hint = (
                    f"\n\n## 本轮激活技能清单\n"
                    f"{skill_activation_list}\n\n"
                    f"## 用户自定义技能（完整指令）\n"
                    f"以下是与当前任务相关的技能指令，请参考执行：\n\n"
                    + "\n\n".join(skill_sections)
                )
                logger.debug(f"[Agent] 注入 {selected_skills.count()} 个技能到 System Prompt")
        except Exception as e:
            logger.warning(f"[Agent] 加载技能失败: {e}")

    system_prompt += skill_hint
    
    return system_prompt


# ==========================================
# Skill Selector Node（技能预筛选节点）
# ==========================================
def skill_selector_node(state: AgentState, config: RunnableConfig) -> dict:
    """
    技能预筛选节点。
    在每轮用户消息进入主 Agent 之前执行，从用户激活的 Skill 池中
    选出与本轮任务相关的 Skill ID，后续注入 System Prompt。
    
    - 若无激活 skill → 直接返回空列表，跳过 LLM 调用
    - LLM 解析失败 → 兜底返回空列表，不阻断主流程
    """
    user = config.get("configurable", {}).get("user")
    if not user or not user.is_authenticated:
        return {"selected_skill_ids": []}

    try:
        from agent_service.models import AgentSkill
        active_skills = list(AgentSkill.objects.filter(user=user, is_active=True).values('id', 'name', 'description'))
    except Exception as e:
        logger.warning(f"[SkillSelector] 查询技能失败: {e}")
        return {"selected_skill_ids": []}

    if not active_skills:
        return {"selected_skill_ids": []}

    # 取最后一条 HumanMessage 作为上下文
    messages = state.get('messages', [])
    last_human_msg = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            if isinstance(msg.content, str):
                last_human_msg = msg.content[:500]
            elif isinstance(msg.content, list):
                text_parts = [b.get("text", "") for b in msg.content if isinstance(b, dict) and b.get("type") == "text"]
                last_human_msg = " ".join(text_parts)[:500]
            break

    if not last_human_msg:
        return {"selected_skill_ids": []}

    # 构建技能摘要列表
    skill_list_str = json.dumps(
        [{"id": s["id"], "name": s["name"], "description": s["description"]} for s in active_skills],
        ensure_ascii=False
    )

    selector_prompt = f"""你是一个技能选择器。根据用户的消息，从下列技能中选出相关的技能编号。
只返回 JSON 数组（如 [1, 3]），不要解释。如果没有相关技能则返回空数组 []。

技能列表：
{skill_list_str}

用户消息：{last_human_msg}"""

    try:
        llm = get_user_llm(user)
        response = llm.invoke(
            [SystemMessage(content=selector_prompt)],
            config={**config, "max_tokens": 200}
        )

        # 解析返回的 JSON 数组
        response_text = response.content.strip()
        # 尝试提取 JSON 数组（兼容 LLM 可能包裹在 ```json ... ``` 中）
        import re
        json_match = re.search(r'\[[\d\s,]*\]', response_text)
        if json_match:
            selected_ids = json.loads(json_match.group())
            # 验证：只允许存在于 active_skills 中的 ID
            valid_ids = {s["id"] for s in active_skills}
            selected_ids = [sid for sid in selected_ids if isinstance(sid, int) and sid in valid_ids]
            logger.info(f"[SkillSelector] 从 {len(active_skills)} 个技能中选出 {len(selected_ids)} 个: {selected_ids}")
            return {"selected_skill_ids": selected_ids}
        else:
            logger.warning(f"[SkillSelector] 无法从 LLM 响应中解析 JSON 数组: {response_text[:200]}")
            return {"selected_skill_ids": []}

    except Exception as e:
        logger.warning(f"[SkillSelector] LLM 调用失败，跳过技能选择: {e}")
        return {"selected_skill_ids": []}


# ==========================================
# Agent 节点
# ==========================================
def agent_node(state: AgentState, config: RunnableConfig) -> dict:
    """
    统一的 Agent 节点，根据 active_tools 动态绑定工具
    
    支持:
    - 动态工具绑定
    - 上下文优化 (Token 管理)
    - Token 使用统计
    
    注意: active_tools 优先从 config 中获取，以确保每次调用都使用最新的工具配置
    这是因为 LangGraph 的 checkpoint 机制会保存/恢复 state，可能导致 active_tools 被旧值覆盖
    """
    messages = state['messages']
    
    # 优先从 config 获取 active_tools，否则从 state 获取
    # 如果都没有，默认为空列表（不启用任何工具，纯对话模式）
    configurable = config.get("configurable", {})
    active_tool_names = (
        configurable.get("active_tools") or 
        state.get('active_tools') or 
        []  # 默认为空列表，而不是调用 get_default_tools()
    )
    
    user = configurable.get("user")
    
    # 获取当前时间
    now = datetime.datetime.now()
    current_time = now.strftime("%Y-%m-%d %H:%M:%S")

    # ========== 提前加载 summary_metadata（用于系统提示上下文状态感知）==========
    # 必须在 build_system_prompt 之前读取，以便注入"历史已压缩"声明
    early_summary_metadata = None
    if user and user.is_authenticated:
        try:
            from agent_service.models import AgentSession as _AgentSession
            _session_id = configurable.get("thread_id", "")
            if _session_id:
                _session = _AgentSession.objects.filter(session_id=_session_id).first()
                if _session:
                    early_summary_metadata = _session.get_summary_metadata()
                    # 注入 state_snapshot 到 summary_metadata
                    if _session.state_snapshot:
                        if early_summary_metadata is None:
                            early_summary_metadata = {}
                        early_summary_metadata['state_snapshot'] = _session.state_snapshot
        except Exception as _e:
            logger.debug(f"[Agent] 提前加载 summary_metadata 失败（无影响）: {_e}")

    # 构建 system prompt（含筛选器选出的技能，以及历史摘要状态）
    selected_skill_ids = state.get('selected_skill_ids') or []
    system_prompt = build_system_prompt(
        user, active_tool_names, current_time,
        selected_skill_ids=selected_skill_ids,
        summary_metadata=early_summary_metadata,
    )
    system_message = SystemMessage(content=system_prompt)
    
    # 动态获取工具
    tools = get_tools_by_names(active_tool_names)
    
    # ========== 获取当前模型配置 ==========
    current_model_id = 'system_deepseek'
    model_config = None
    
    if user and user.is_authenticated:
        try:
            current_model_id, model_config = get_current_model_config(user)
            logger.debug(f"[Agent] 获取到模型配置: model_id={current_model_id}")
            logger.debug(f"[Agent] 模型详情: {model_config}")
        except Exception as e:
            logger.warning(f"[Agent] 获取模型配置失败: {e}")
    
    # ========== 动态创建 LLM 实例 ==========
    # 使用统一的 get_user_llm() 函数，正确处理系统模型和自定义模型
    active_llm = get_user_llm(user)

    if isinstance(active_llm, DisabledLLM):
        return {
            "messages": [
                AIMessage(
                    content=(
                        "当前未配置可用的 LLM。请在 config/api_keys.json 的 system_models 中配置，"
                        "或设置 OPENAI_API_KEY/OPENAI_API_BASE/OPENAI_MODEL 环境变量。"
                    )
                )
            ]
        }
    
    if tools:
        llm_with_tools = active_llm.bind_tools(tools)
    else:
        llm_with_tools = active_llm
    
    # ========== 上下文优化逻辑 ==========
    optimized_messages = messages
    summary_metadata = None
    
    if user and user.is_authenticated:
        try:
            from agent_service.models import DialogStyle, AgentSession
            dialog_style = DialogStyle.get_or_create_default(user)
            enable_optimization = getattr(dialog_style, 'enable_context_optimization', True)
            
            logger.debug(f"[Agent] 上下文优化检查: enable={enable_optimization}, msg_count={len(messages)}")
            
            # 获取优化配置
            opt_config = get_optimization_config(user)
            
            # Token 计算器
            calculator = TokenCalculator(
                method=opt_config.get('token_calculation_method', 'estimate')
            )
            
            # 获取会话和已有的总结
            session_id = config.get("configurable", {}).get("thread_id", "")
            session = None
            if session_id:
                session = AgentSession.objects.filter(session_id=session_id).first()
                if session:
                    summary_metadata = session.get_summary_metadata()
                    if summary_metadata:
                        logger.debug(f"[Agent] 加载历史总结: {summary_metadata.get('summary_tokens', 0)}t, 截止第 {summary_metadata.get('summarized_until', 0)} 条")
            
            if enable_optimization:
                # 创建工具压缩器
                # 【重要】以下工具的结果不应被压缩，因为它们的输出是 LLM 后续操作的关键信息：
                # - search_items: 搜索结果用于后续引用
                # - web_search*: 网络搜索结果需要完整呈现
                # - 12306 相关工具（mcp_12306-mcp_*）: 火车票查询结果需要完整解析
                tool_compressor = ToolMessageCompressor(
                    max_tokens=opt_config.get('tool_output_max_tokens', 200),
                    exclude_tools=['search_items', 'web_search', 'web_search_advanced'],
                    exclude_prefixes=['mcp_12306']  # 排除所有 12306 MCP 工具（前缀匹配）
                ) if opt_config.get('compress_tool_output', True) else None
                
                # ====== 计算原始消息的 token 总数 ======
                # 优先策略：
                # - 如果会话有历史真实 token 数（上一轮 LLM 返回的 input_tokens），
                #   用它来代替"历史消息"的估算，只对最后一条新消息（用户当前输入）做预估。
                # - 否则退回逐条估算。
                #
                # 为什么这么做：
                # - 多模态消息（包含图片 base64）的逐条估算非常不准确，即使修复了 calculate_message
                #   也只是粗略 512 tokens/图片；而历史数据是 LLM 服务商返回的真实值。
                # - 最后一条用户消息是本次新增内容，必须预估，因为还没发送过。
                
                original_tokens = None  # None 表示尚未计算
                
                if session and session.last_input_tokens > 0 and len(messages) > 1:
                    # 方案 A：历史真实 token 数 + 新增最后一条消息的预估
                    last_msg = messages[-1]
                    last_msg_tokens = calculator.calculate_message(last_msg)
                    
                    # 如果最后一条是多模态消息，记录更详细的调试信息
                    if hasattr(last_msg, 'content') and isinstance(last_msg.content, list):
                        img_count = sum(1 for b in last_msg.content if isinstance(b, dict) and b.get("type") in ("image_url", "image"))
                        text_parts = [b.get("text", "") for b in last_msg.content if isinstance(b, dict) and b.get("type") == "text"]
                        text_len = sum(len(t) for t in text_parts)
                        logger.debug(
                            f"[Token预估] 最后一条消息: 多模态, {img_count} 张图片 + {text_len} 字符文本 → 预估 {last_msg_tokens}t"
                        )
                    
                    # 历史 token 数（上一轮真实值）已经包含了除最新用户消息之外的所有上下文
                    # 所以：本次预估 ≈ 上轮真实 input_tokens + 最后一条新消息
                    original_tokens = session.last_input_tokens + last_msg_tokens
                    logger.debug(
                        f"[Agent] 上下文优化（基于历史真实 token）:"
                        f"\n[Agent]   - 历史真实 input_tokens: {session.last_input_tokens}t (source={session.last_input_tokens_source})"
                        f"\n[Agent]   - 新消息预估: {last_msg_tokens}t"
                        f"\n[Agent]   - 原始消息: {len(messages)} 条, 预估共 {original_tokens} tokens"
                    )
                else:
                    # 方案 B：无历史数据，退回逐条估算（首次对话或无快照）
                    original_tokens = sum(calculator.calculate_message(m) for m in messages)
                    
                    # 检查是否有多模态消息，若有则发出警告
                    multimodal_msgs = []
                    for i, m in enumerate(messages):
                        if hasattr(m, 'content') and isinstance(m.content, list):
                            img_count = sum(1 for b in m.content if isinstance(b, dict) and b.get("type") in ("image_url", "image"))
                            if img_count > 0:
                                multimodal_msgs.append((i, img_count))
                    
                    if multimodal_msgs:
                        logger.debug(
                            f"[Token预估-降级] 无历史真实 token 数据，对含图片消息使用估算（精度较低）。"
                            f" 含图片消息索引: {multimodal_msgs}，每张图片估算 512t。"
                            f" 原始消息: {len(messages)} 条, {original_tokens} tokens"
                        )
                    else:
                        logger.debug(f"[Agent] 上下文优化(无历史数据，退回逐条估算):")
                        logger.debug(f"[Agent]   - 原始消息: {len(messages)} 条, {original_tokens} tokens")
                
                # 使用优化上下文（使用已有总结，不再截断）
                optimized_messages = build_optimized_context(
                    user=user,
                    system_prompt=system_prompt,
                    messages=messages,
                    summary_metadata=summary_metadata,
                    token_calculator=calculator,
                    tool_compressor=tool_compressor,
                    preserve_recent_count=opt_config.get('tool_compress_preserve_recent_messages', 5)
                )
                
                # 移除第一个 SystemMessage（因为 build_optimized_context 已经添加了）
                if optimized_messages and isinstance(optimized_messages[0], SystemMessage):
                    optimized_messages = optimized_messages[1:]
                
                # 计算优化后的 token 总数
                optimized_tokens = sum(calculator.calculate_message(m) for m in optimized_messages)
                
                logger.debug(f"[Agent] 上下文优化完成:")
                logger.debug(f"[Agent]   - 优化后消息: {len(optimized_messages)} 条, {optimized_tokens} tokens")
                if original_tokens and original_tokens > 0:
                    logger.debug(f"[Agent]   - 削减率: {(1 - optimized_tokens/original_tokens)*100:.1f}%")
                
        except Exception as e:
            logger.error(f"[Agent] 上下文优化失败: {e}", exc_info=True)
            optimized_messages = messages
    
    full_messages = [system_message] + list(optimized_messages)
    
    # ========== 注入附件上下文（跟随每条 HumanMessage 位置）==========
    # 遍历所有 HumanMessage，将附件上下文以独立 SystemMessage 注入到紧随其后的位置
    # 对非最新消息中的文件附件，截断长文本
    from agent_service.attachment_handler import AttachmentHandler

    # 找到最后一条 HumanMessage 的原始索引
    last_human_idx = None
    for i in range(len(full_messages) - 1, -1, -1):
        if isinstance(full_messages[i], HumanMessage):
            last_human_idx = i
            break

    # 从后向前遍历，避免插入导致索引偏移
    for i in range(len(full_messages) - 1, -1, -1):
        msg = full_messages[i]
        if not isinstance(msg, HumanMessage):
            continue

        kwargs = getattr(msg, 'additional_kwargs', None) or {}
        attachments_context = kwargs.get('attachments_context', '')
        if not attachments_context:
            continue

        is_latest = (i == last_human_idx)

        # 非最新消息：对包含文件附件的上下文执行截断
        if not is_latest:
            meta_list = kwargs.get('attachments_metadata', [])
            has_file_attachment = any(
                m.get('type') in ('image', 'pdf', 'word', 'excel')
                for m in meta_list
            )
            if has_file_attachment:
                attachments_context = AttachmentHandler.truncate_attachment_text(
                    attachments_context
                )

        label = "最新消息附件" if is_latest else "历史消息附件"
        attachment_msg = SystemMessage(
            content=f"【{label}内容】以下是用户该条消息中包含的附件信息：\n\n{attachments_context}"
        )
        full_messages.insert(i + 1, attachment_msg)
        logger.debug(f"[Agent] 注入附件上下文@msg#{i}: {len(attachments_context)} 字符, latest={is_latest}")
    
    # ========== 多模态动态重建：根据当前模型能力重建历史消息中的图片内容 ==========
    current_supports_vision = model_config.get('supports_vision', False) if model_config else False
    rebuilt_count = 0
    
    for i, msg in enumerate(full_messages):
        if not isinstance(msg, HumanMessage):
            continue
        
        # 检查消息是否包含附件
        attachment_ids = []
        if hasattr(msg, 'additional_kwargs') and msg.additional_kwargs:
            attachment_ids = msg.additional_kwargs.get('attachment_ids', [])
            # 也检查 attachments_metadata 中的 sa_id
            if not attachment_ids:
                metadata = msg.additional_kwargs.get('attachments_metadata', [])
                attachment_ids = [m.get('sa_id') for m in metadata if m.get('sa_id')]
        
        if not attachment_ids:
            # 没有附件，但可能有旧格式的 image_url 块需要降级
            if not current_supports_vision and isinstance(msg.content, list):
                text_parts = []
                image_count = 0
                for block in msg.content:
                    if isinstance(block, dict):
                        if block.get('type') == 'text':
                            text_parts.append(block.get('text', ''))
                        elif block.get('type') == 'image_url':
                            image_count += 1
                    elif isinstance(block, str):
                        text_parts.append(block)
                if image_count > 0:
                    text_parts.append(f"[此消息包含 {image_count} 张图片，当前模型不支持图片识别]")
                    new_content = '\n'.join(text_parts) if text_parts else str(msg.content)
                    full_messages[i] = HumanMessage(
                        content=new_content,
                        additional_kwargs=msg.additional_kwargs,
                    )
                    rebuilt_count += 1
            continue
        
        # 有附件，根据模型能力重建消息内容
        try:
            from agent_service.attachment_handler import AttachmentHandler
            
            new_content = AttachmentHandler.rebuild_message_content_for_model(
                original_content=msg.content,
                attachment_ids=attachment_ids,
                user=user,
                supports_vision=current_supports_vision
            )
            
            if new_content != msg.content:
                full_messages[i] = HumanMessage(
                    content=new_content,
                    additional_kwargs=msg.additional_kwargs,
                )
                rebuilt_count += 1
        except Exception as e:
            logger.warning(f"[Agent] 重建消息内容失败: {e}")
    
    if rebuilt_count > 0:
        mode = "多模态" if current_supports_vision else "纯文本"
        logger.debug(f"[Agent] 动态重建: {rebuilt_count} 条消息已根据当前模型能力({mode})重建内容")
    
    # 打印最终发送给 LLM 的消息
    logger.debug(f"[Agent] 发送给 LLM 的消息: {len(full_messages)} 条")

    # ========== 保存 LLM 请求快照（供前端上下文可视化）==========
    try:
        _snapshot_messages = []
        for _msg in full_messages:
            _role = getattr(_msg, 'type', 'unknown')
            _serialized = {"role": _role}

            # 序列化 content（多模态中 base64 截断）
            if isinstance(_msg.content, str):
                _serialized["content"] = _msg.content
            elif isinstance(_msg.content, list):
                _blocks = []
                for _block in _msg.content:
                    if isinstance(_block, dict) and _block.get('type') == 'image_url':
                        _url = _block.get('image_url', {}).get('url', '')
                        _blocks.append({
                            "type": "image_url",
                            "image_url": {"url": _url[:100] + '...[base64_truncated]' if len(_url) > 100 else _url}
                        })
                    else:
                        _blocks.append(_block)
                _serialized["content"] = _blocks
            else:
                _serialized["content"] = str(_msg.content) if _msg.content else ""

            # tool_calls / tool info
            if hasattr(_msg, 'tool_calls') and _msg.tool_calls:
                _serialized["tool_calls"] = _msg.tool_calls
            if hasattr(_msg, 'name') and _msg.name:
                _serialized["name"] = _msg.name
            if hasattr(_msg, 'tool_call_id') and _msg.tool_call_id:
                _serialized["tool_call_id"] = _msg.tool_call_id

            # 元数据标记
            _meta = {"type": _role}
            _content_str = _serialized.get("content", "")
            if isinstance(_content_str, str):
                if _content_str.startswith("【附件") or _content_str.startswith("【最新消息附件") or _content_str.startswith("【历史消息附件"):
                    _meta["type"] = "attachment_context"
                elif "【对话历史总结】" in _content_str:
                    _meta["type"] = "summary"
                elif _role == "system":
                    _meta["type"] = "system_prompt"
            _kwargs = getattr(_msg, 'additional_kwargs', None) or {}
            if _kwargs.get('attachments_metadata'):
                _meta["has_attachments"] = True
                _meta["attachment_ids"] = _kwargs.get('attachment_ids', [])
            _serialized["_meta"] = _meta

            _snapshot_messages.append(_serialized)

        _invoke_session_id = configurable.get("thread_id", "")
        if _invoke_session_id and user and user.is_authenticated:
            from agent_service.models import AgentSession as _SnapshotSession
            from datetime import datetime as _dt
            _invoke_session = _SnapshotSession.objects.filter(session_id=_invoke_session_id).first()
            if _invoke_session:
                # 序列化工具定义（名称 + 描述 + 参数 schema）
                _tool_defs = []
                for _t in tools:
                    try:
                        _tdef = {"name": _t.name, "description": _t.description}
                        if hasattr(_t, 'args_schema') and _t.args_schema is not None:
                            try:
                                # Pydantic v2 优先，回退到 v1
                                if hasattr(_t.args_schema, 'model_json_schema'):
                                    _tdef["parameters"] = _t.args_schema.model_json_schema()
                                elif hasattr(_t.args_schema, 'schema'):
                                    _tdef["parameters"] = _t.args_schema.schema()
                            except Exception as _schema_e:
                                logger.debug(f"[Snapshot] 工具 {_t.name} schema 获取失败: {_schema_e}")
                        _tool_defs.append(_tdef)
                    except Exception:
                        pass
                _invoke_session.last_llm_request_snapshot = {
                    "timestamp": _dt.now().isoformat(),
                    "message_index": len(state.get("messages", [])),
                    "model_id": current_model_id,
                    "model_name": model_config.get('model_name', '') if model_config else '',
                    "supports_vision": current_supports_vision,
                    "tool_names": active_tool_names,
                    "tool_definitions": _tool_defs,
                    "messages": _snapshot_messages,
                    "token_stats": {
                        "total_messages": len(full_messages),
                        "system_prompt_chars": len(str(full_messages[0].content)) if full_messages else 0,
                        "total_chars": sum(len(str(m.content)) for m in full_messages),
                    }
                }
                _invoke_session.save(update_fields=['last_llm_request_snapshot'])
                logger.debug(f"[Agent] 保存 LLM 请求快照: {len(_snapshot_messages)} 条消息, {len(_tool_defs)} 个工具定义")
    except Exception as _snap_e:
        logger.warning(f"[Agent] 保存 LLM 请求快照失败: {_snap_e}")

    response = llm_with_tools.invoke(full_messages, config)
    
    # ========== Token 统计 ==========
    if user and user.is_authenticated:
        try:
            # 尝试从 response 获取实际 token 使用
            input_tokens = 0
            output_tokens = 0
            
            # 优先检查 usage_metadata（LangChain 新版本标准）
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                usage_metadata = response.usage_metadata
                if isinstance(usage_metadata, dict):
                    input_tokens = usage_metadata.get('input_tokens', 0) or usage_metadata.get('prompt_tokens', 0)
                    output_tokens = usage_metadata.get('output_tokens', 0) or usage_metadata.get('completion_tokens', 0)
                else:
                    input_tokens = getattr(usage_metadata, 'input_tokens', 0) or getattr(usage_metadata, 'prompt_tokens', 0)
                    output_tokens = getattr(usage_metadata, 'output_tokens', 0) or getattr(usage_metadata, 'completion_tokens', 0)
            
            # 回退：检查 response_metadata
            if not input_tokens and hasattr(response, 'response_metadata'):
                metadata = response.response_metadata
                usage = metadata.get('token_usage') or metadata.get('usage') or {}
                input_tokens = usage.get('prompt_tokens', 0) or usage.get('input_tokens', 0)
                output_tokens = usage.get('completion_tokens', 0) or usage.get('output_tokens', 0)
            
            # 如果无法从 API 获取，使用估算值
            if input_tokens == 0 or output_tokens == 0:
                # 准备降级日志信息
                usage_metadata_str = str(response.usage_metadata) if hasattr(response, 'usage_metadata') else 'None'
                response_metadata_keys = list(response.response_metadata.keys()) if hasattr(response, 'response_metadata') else []
                
                logger.warning(
                    f"⚠️ [Token统计降级] 无法从API获取Token用量，使用估算值（将用于计费，可能存在偏差）。"
                    f"模型={current_model_id}, "
                    f"usage_metadata={usage_metadata_str[:200]}, "
                    f"response_metadata 可用字段={response_metadata_keys}"
                )

                
                if input_tokens == 0:
                    # 估算输入 token：所有消息内容的长度 / 2.5
                    total_input_chars = sum(
                        len(msg.content) if hasattr(msg, 'content') and isinstance(msg.content, str) else 0
                        for msg in full_messages
                    )
                    input_tokens = int(total_input_chars / 2.5)
                    logger.debug(f"[Token统计] 输入Token估算: {total_input_chars} 字符 → {input_tokens} tokens")
                
                if output_tokens == 0:
                    # 估算输出 token：响应内容长度 / 2.5
                    response_content = response.content if hasattr(response, 'content') and isinstance(response.content, str) else ""
                    output_tokens = int(len(response_content) / 2.5) or 10  # 至少 10 tokens
                    logger.debug(f"[Token统计] 输出Token估算: {len(response_content)} 字符 → {output_tokens} tokens")
            
            if input_tokens > 0 or output_tokens > 0:
                # 判断数据来源
                has_usage_metadata = hasattr(response, 'usage_metadata') and response.usage_metadata
                has_response_metadata_usage = False
                if not has_usage_metadata and hasattr(response, 'response_metadata'):
                    metadata = response.response_metadata
                    usage = metadata.get('token_usage') or metadata.get('usage') or {}
                    has_response_metadata_usage = bool(usage.get('prompt_tokens') or usage.get('input_tokens'))
                
                source = "actual" if (has_usage_metadata or has_response_metadata_usage) else "estimated"
                
                # 成本由 update_token_usage 自动计算（基于 CNY）
                update_token_usage(user, input_tokens, output_tokens, current_model_id)
                logger.debug(f"[Agent] Token 统计已更新: in={input_tokens}, out={output_tokens}, model={current_model_id}, source={source}")
                
                # ========== 保存上下文 Token 数到会话（用于前端显示）==========
                try:
                    from agent_service.models import AgentSession
                    session_id = configurable.get("thread_id")
                    if session_id:
                        session = AgentSession.objects.filter(session_id=session_id).first()
                        if session:
                            # 更新最新的 input_tokens（用于实时显示）
                            session.update_context_tokens(input_tokens, source)
                            
                            # 保存当前消息的 Token 快照（用于回滚时恢复显示）
                            # AI 响应的索引 = 当前消息列表长度（因为返回后会追加到列表）
                            current_message_index = len(state["messages"])
                            session.save_token_snapshot(current_message_index, input_tokens, source)
                            
                            logger.debug(f"[Token快照] 已保存: session={session_id}, message_index={current_message_index}, input_tokens={input_tokens}, source={source}")
                        else:
                            logger.warning(f"[上下文显示] 未找到会话: session_id={session_id}")
                except Exception as e:
                    logger.error(f"[上下文显示] 保存 Token 失败: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"[Agent] Token 统计失败: {e}", exc_info=True)
    
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
        active_tool_names = (
            configurable.get("active_tools") or 
            state.get('active_tools') or 
            []  # 默认为空列表，不启用任何工具
        )
        
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
                # 将 tool_call_id 添加到 config 中，用于事务记录
                tool_config = {**config}
                if "configurable" in tool_config:
                    tool_config["configurable"] = {
                        **tool_config["configurable"],
                        "tool_call_id": tool_call_id
                    }
                else:
                    tool_config["configurable"] = {"tool_call_id": tool_call_id}
                
                result = tool.invoke(tool_args, tool_config)
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
    workflow  = StateGraph(AgentState)
    
    # 添加节点
    workflow.add_node("skill_selector", skill_selector_node)
    workflow.add_node("agent", agent_node)
    
    # 使用带权限检查的工具节点
    workflow.add_node("tools", create_tool_node_with_permission_check())
    
    # 设置入口点 → 先经过技能筛选器
    workflow.set_entry_point("skill_selector")
    
    # skill_selector → agent
    workflow.add_edge("skill_selector", "agent")
    
    # Agent 后的路由
    workflow.add_conditional_edges(
        "agent",
        route_after_agent,
        {
            "tools": "tools",
            "END": END
        }
    )
    
    # 工具调用后直接返回 Agent（不再经过 skill_selector）
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

# ========== 同步 Checkpointer（用于同步 API 视图）==========

def get_sync_checkpointer():
    """获取同步 checkpointer（用于同步 API）"""
    conn = sqlite3.connect(CHECKPOINT_DB_PATH, check_same_thread=False)
    return SqliteSaver(conn)

# 创建同步 checkpointer 和 app
sync_checkpointer = get_sync_checkpointer()
app = workflow.compile(checkpointer=sync_checkpointer)

# 为了向后兼容，创建别名（views_api.py 中使用 checkpointer）
checkpointer = sync_checkpointer

# ========== 异步 Checkpointer（用于 WebSocket 流式处理）==========
import aiosqlite

# 全局异步 checkpointer 实例（懒加载）
_async_checkpointer = None
_async_checkpointer_conn = None

async def get_async_checkpointer():
    """
    获取异步 checkpointer（懒加载单例）
    必须在异步上下文中调用
    """
    global _async_checkpointer, _async_checkpointer_conn
    if _async_checkpointer is None:
        _async_checkpointer_conn = await aiosqlite.connect(CHECKPOINT_DB_PATH)
        _async_checkpointer = AsyncSqliteSaver(_async_checkpointer_conn)
        # 初始化数据库表
        await _async_checkpointer.setup()
        logger.info(f"[Checkpointer] 异步 checkpointer 已初始化: {CHECKPOINT_DB_PATH}")
    return _async_checkpointer

async def get_app_with_checkpointer():
    """
    获取带有异步 checkpointer 的 app（懒加载）
    必须在异步上下文中调用
    """
    checkpointer = await get_async_checkpointer()
    return workflow.compile(checkpointer=checkpointer)

# 预编译无 checkpointer 的版本（用于测试）
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
        
        logger.debug(f"已清除会话 {thread_id} 的 {deleted_checkpoints} 个 checkpoint")
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
        "active_tools": active_tools,
        "selected_skill_ids": []
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
