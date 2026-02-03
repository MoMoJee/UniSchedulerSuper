"""
Quick Action Agent
快速操作执行器 - 通过 HTTP API 触发的单次对话 Agent

核心设计原则：
1. 禁止向用户提问 - 必须立即给出确定性结果
2. 可多次调用工具 - 但只有一次对话机会
3. 三种结果类型：成功/需要补充信息/失败

Author: Quick Action System
"""

from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated, List, Any, Dict, Optional
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from datetime import datetime
import operator

from agent_service.agent_graph import get_user_llm, PLANNER_TOOLS
from agent_service.context_optimizer import update_token_usage, get_current_model_config
from logger import logger


class QuickActionState(TypedDict):
    """Quick Action 状态"""
    messages: Annotated[List, operator.add]
    user: Any  # Django User
    task_id: str
    input_text: str
    
    # 执行追踪
    iteration: int  # 迭代次数
    tool_calls_log: List[dict]  # 工具调用日志
    
    # 最终结果
    final_result: dict
    tokens_used: dict  # {input: x, output: y}


# ============================================
# System Prompt（核心）
# ============================================
QUICK_ACTION_SYSTEM_PROMPT = """你是一个快速操作执行器，负责根据用户的一句话指令立即执行日程管理操作。

## 核心规则
1. **禁止询问用户**：无论任何情况，你都不能向用户提问或等待用户回复
2. **必须给出确定性结果**：只能返回以下三种结果之一
3. **单次对话执行**：你只有这一次机会完成任务，不会有后续对话
4. **可多次调用工具**：你可以多次使用工具来完成任务，但必须主动决策

## 三种允许的结果

### 结果1：操作成功 ✅
当你成功执行了操作（创建、修改、删除、完成待办等），返回：
- 明确说明执行了什么操作
- 提供操作的详细信息
- 使用友好的自然语言描述

示例：
"✅ 已将「团队会议」的时间从 2月8日 14:00-15:00 修改为 20:00-21:00"
"✅ 已创建新日程：2月10日 09:00-10:00「项目评审」"
"✅ 已完成待办：提交月度报告"

### 结果2：需要明确信息 ⚠️（严格限制使用）
**仅当满足以下所有条件时才能使用**：
1. 用户提供的信息确实不足以执行操作
2. 你已经尝试通过工具搜索但找到了多个完全无法区分的匹配项
3. 缺失的信息是用户必须明确指定的（如"哪一个会议"）

返回格式：
- 清楚说明为什么无法执行
- 列出找到的所有选项（最多5个）
- 提示用户如何补充信息

示例：
"⚠️ 找到 3 个2月8日的会议，无法确定要修改哪一个：
1. 09:00-10:00「晨会」
2. 14:00-15:00「团队会议」  
3. 16:00-17:00「项目评审」
请在下次请求中明确指定会议名称，如'将团队会议改到晚上8点'"

**禁止滥用**：
- ❌ 不能因为"可能有风险"就返回建议
- ❌ 不能因为"想确认一下"就返回建议
- ❌ 如果只找到1个匹配，必须直接执行，不能询问
- ❌ 如果可以通过上下文推断，必须推断而不是询问

### 结果3：操作失败 ❌
当操作无法执行且无法恢复时：
- 说明失败原因
- 不提供建议（因为无法恢复）

示例：
"❌ 未找到2月8日的任何会议"
"❌ 操作失败：日程已被删除"
"❌ 缺少必要信息：未指定日程时间"

## 可用工具
- search_items: 搜索日程/待办/提醒
- create_item: 创建新项目
- update_item: 更新已有项目
- delete_item: 删除项目
- get_event_groups: 获取日程组列表
- get_share_groups: 获取分享组列表
- complete_todo: 快捷完成待办
- check_schedule_conflicts: 检查日程冲突

## 典型执行流程

### 场景A：修改日程
用户输入："2月8日的会议改到晚上8点"

1. 调用 search_items(item_type="event", time_range="2026-02-08")
2. 检查结果：
   - 如果找到1个会议 → 直接调用 update_item 修改
   - 如果找到多个会议 → 返回结果2（需要明确）
   - 如果没找到 → 返回结果3（失败）

### 场景B：创建日程
用户输入："明天下午3点开会，讨论项目进度"

1. 解析信息：时间=明天15:00，标题=讨论项目进度
2. 调用 create_item(item_type="event", title="讨论项目进度", start="明天 15:00", ...)
3. 返回结果1（成功）

### 场景C：完成待办
用户输入："完成报告提交"

1. 调用 search_items(item_type="todo", keyword="报告提交")
2. 如果找到1个 → 调用 complete_todo
3. 返回结果1（成功）

## 智能推断规则
1. **时间推断**：
   - "明天" = 当前日期+1天
   - "下周一" = 计算下周一的日期
   - "晚上8点" = 20:00
   
2. **持续时间推断**：
   - 会议默认1小时
   - 如果说"2小时会议"，则设置相应时长
   
3. **重复规则推断**：
   - "每周" → 按周重复
   - "每天" → 按天重复

## 当前时间
{current_time}

## 执行要求
- 立即分析用户输入并开始执行
- 需要信息时先用工具搜索，不要假设
- 执行后立即返回明确结果
- 保持简洁但完整的反馈
"""


def build_system_message(current_time: str) -> SystemMessage:
    """构建系统消息"""
    return SystemMessage(content=QUICK_ACTION_SYSTEM_PROMPT.format(
        current_time=current_time
    ))


# ============================================
# Agent 节点
# ============================================
def agent_node(state: QuickActionState) -> Dict:
    """Agent 决策节点"""
    user = state['user']
    messages = state['messages']
    
    # 获取用户配置的 LLM
    llm = get_user_llm(user)
    
    # 绑定工具
    tools = list(PLANNER_TOOLS.values())
    llm_with_tools = llm.bind_tools(tools)
    
    # 调用 LLM
    response = llm_with_tools.invoke(messages)
    
    # 记录 Token 使用
    input_tokens = 0
    output_tokens = 0
    if hasattr(response, 'usage_metadata'):
        usage = response.usage_metadata
        if isinstance(usage, dict):
            input_tokens = usage.get('input_tokens', 0) or usage.get('prompt_tokens', 0)
            output_tokens = usage.get('output_tokens', 0) or usage.get('completion_tokens', 0)
        else:
            input_tokens = getattr(usage, 'input_tokens', 0) or getattr(usage, 'prompt_tokens', 0)
            output_tokens = getattr(usage, 'output_tokens', 0) or getattr(usage, 'completion_tokens', 0)
    
    # 累加 tokens
    prev_tokens = state.get('tokens_used', {})
    new_tokens = {
        "input": prev_tokens.get('input', 0) + input_tokens,
        "output": prev_tokens.get('output', 0) + output_tokens
    }
    
    logger.debug(f"[QuickAction] Agent iteration {state.get('iteration', 0) + 1}, "
                 f"tokens: +{input_tokens}/{output_tokens}, total: {new_tokens}")
    
    # 更新状态
    return {
        "messages": [response],
        "iteration": state.get('iteration', 0) + 1,
        "tokens_used": new_tokens
    }


def tool_node_wrapper(state: QuickActionState) -> Dict:
    """工具执行节点"""
    from langchain_core.runnables import RunnableConfig
    
    user = state['user']
    messages = state['messages']
    last_message = messages[-1]
    
    # 获取当前的工具调用日志
    tool_calls_log = list(state.get('tool_calls_log', []))
    
    # 构建 config（传递用户和会话信息给工具）
    config = RunnableConfig(
        configurable={
            "user": user,
            "thread_id": state['task_id'],
            "session_id": state['task_id']
        }
    )
    
    # 执行工具调用
    tool_results = []
    for tool_call in last_message.tool_calls:
        tool_name = tool_call['name']
        tool_args = tool_call['args']
        tool_call_id = tool_call['id']
        
        # 记录工具调用
        log_entry = {
            "tool": tool_name,
            "args": tool_args,
            "timestamp": datetime.now().isoformat()
        }
        
        try:
            # 检查工具是否存在
            if tool_name not in PLANNER_TOOLS:
                raise ValueError(f"未知工具: {tool_name}")
            
            # 执行工具
            tool = PLANNER_TOOLS[tool_name]
            result = tool.invoke(tool_args, config=config)
            
            # 处理结果
            if isinstance(result, str):
                result_str = result
            else:
                import json
                result_str = json.dumps(result, ensure_ascii=False, default=str)
            
            log_entry["result"] = result_str[:1000] if len(result_str) > 1000 else result_str
            log_entry["status"] = "success"
            
            logger.debug(f"[QuickAction] Tool {tool_name} success: {log_entry['result'][:200]}...")
            
        except Exception as e:
            logger.error(f"[QuickAction] Tool {tool_name} failed: {e}")
            result_str = f"工具执行失败: {str(e)}"
            log_entry["result"] = result_str
            log_entry["status"] = "error"
        
        # 构造 ToolMessage
        tool_results.append(ToolMessage(
            content=result_str,
            tool_call_id=tool_call_id
        ))
        
        tool_calls_log.append(log_entry)
    
    return {
        "messages": tool_results,
        "tool_calls_log": tool_calls_log
    }


# ============================================
# 路由逻辑
# ============================================
def should_continue(state: QuickActionState) -> str:
    """判断是否继续执行"""
    messages = state['messages']
    last_message = messages[-1]
    iteration = state.get('iteration', 0)
    
    # 最多执行 10 轮（防止无限循环）
    MAX_ITERATIONS = 10
    if iteration >= MAX_ITERATIONS:
        logger.warning(f"[QuickAction] Task {state['task_id']} reached max iterations ({MAX_ITERATIONS})")
        return "format_result"
    
    # 如果有工具调用，继续执行
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        return "tools"
    
    # 否则结束
    return "format_result"


def format_result_node(state: QuickActionState) -> Dict:
    """格式化最终结果"""
    messages = state['messages']
    last_message = messages[-1]
    
    # 提取 AI 的最终回复
    if hasattr(last_message, 'content'):
        content = last_message.content
    else:
        content = str(last_message)
    
    # 分析结果类型
    result_type = "action_completed"
    if "⚠️" in content or "需要明确" in content or "无法确定" in content:
        result_type = "need_clarification"
    elif "❌" in content or "失败" in content or "错误" in content or "未找到" in content:
        result_type = "error"
    
    logger.info(f"[QuickAction] Task {state['task_id']} result: {result_type}")
    
    return {
        "final_result": {
            "type": result_type,
            "message": content,
            "tool_calls": state.get('tool_calls_log', [])
        }
    }


# ============================================
# 构建 Graph
# ============================================
def create_quick_action_graph():
    """创建 Quick Action Graph"""
    workflow = StateGraph(QuickActionState)
    
    # 添加节点
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node_wrapper)
    workflow.add_node("format_result", format_result_node)
    
    # 设置入口
    workflow.set_entry_point("agent")
    
    # 添加条件边
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "format_result": "format_result"
        }
    )
    
    # 工具执行后回到 agent
    workflow.add_edge("tools", "agent")
    
    # 结束
    workflow.add_edge("format_result", END)
    
    return workflow.compile()


# 全局实例（延迟初始化，避免 import 时报错）
_quick_action_graph = None


def get_quick_action_graph():
    """获取 Quick Action Graph 实例"""
    global _quick_action_graph
    if _quick_action_graph is None:
        _quick_action_graph = create_quick_action_graph()
    return _quick_action_graph


# ============================================
# 执行入口
# ============================================
def execute_quick_action_sync(user, input_text: str, task_id: Optional[str] = None) -> Dict:
    """
    同步执行快速操作
    
    Args:
        user: Django User 对象
        input_text: 用户输入的指令
        task_id: 任务ID（可选）
    
    Returns:
        Dict: 执行结果
        {
            "type": "action_completed" | "need_clarification" | "error",
            "message": "执行结果描述",
            "tool_calls": [...],
            "tokens": {"input": x, "output": y}
        }
    """
    import uuid
    
    if not task_id:
        task_id = str(uuid.uuid4())
    
    # 构建初始消息
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M （%A）')
    system_msg = build_system_message(current_time)
    user_msg = HumanMessage(content=input_text)
    
    # 构建初始状态
    initial_state = {
        "messages": [system_msg, user_msg],
        "user": user,
        "task_id": task_id,
        "input_text": input_text,
        "iteration": 0,
        "tool_calls_log": [],
        "tokens_used": {"input": 0, "output": 0},
        "final_result": {}
    }
    
    try:
        # 获取 graph
        graph = get_quick_action_graph()
        
        # 执行 Graph
        final_state = graph.invoke(
            initial_state,
            config={"recursion_limit": 15}
        )
        
        # 获取结果
        result = final_state.get('final_result', {})
        tokens = final_state.get('tokens_used', {})
        
        return {
            "type": result.get('type', 'error'),
            "message": result.get('message', '执行完成但未返回消息'),
            "tool_calls": result.get('tool_calls', []),
            "tokens": tokens
        }
        
    except Exception as e:
        logger.exception(f"[QuickAction] Execution failed: {e}")
        return {
            "type": "error",
            "message": f"❌ 执行出错: {str(e)}",
            "tool_calls": [],
            "tokens": {"input": 0, "output": 0}
        }
