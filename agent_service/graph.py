import os
import datetime
from typing import Annotated, TypedDict, List
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, AIMessageChunk, RemoveMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from agent_service.mcp_tools import load_mcp_tools

# ==========================================
# 配置区域
# ==========================================
# 请在此处填入您的 DeepSeek API Key
# 警告：将 API Key 硬编码在代码中是不安全的，仅用于临时测试。
# 生产环境中请使用环境变量。
os.environ["OPENAI_API_KEY"] = "sk-xx"
os.environ["OPENAI_API_BASE"] = "https://api.deepseek.com" 

# 上下文管理配置
MAX_MESSAGES = 6 # 触发总结的消息数量阈值 (保留最近的 N 条消息，其余总结)

import json
import uuid
from agent_service.memory_store import store, save_store_to_file

# ==========================================
# 状态定义
# ==========================================

# ==========================================
# 状态定义
# ==========================================
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    user_id: int
    summary: str # 对话摘要
    selected_tool_names: List[str] # 动态筛选出的工具名称列表

# ==========================================
# 工具定义
# ==========================================
# 加载 MCP 工具 (高德地图 + 本地日程服务 + 本地记忆搜索)
tools = load_mcp_tools()

# ==========================================
# 模型初始化
# ==========================================
# 使用 deepseek-chat
llm = ChatOpenAI(
    model="deepseek-chat", 
    temperature=0,
    base_url="https://api.deepseek.com"
)
llm_with_tools = llm.bind_tools(tools)

# ==========================================
# 节点逻辑
# ==========================================
def select_tools_node(state: AgentState):
    """
    工具筛选节点 (Router)
    根据用户意图，从所有可用工具中筛选出最相关的子集。
    这可以减少 Agent 的上下文负担，提高准确率。
    """
    messages = state['messages']
    last_user_message = messages[-1]
    
    # 如果最后一条不是用户消息（例如是工具输出），则保持原有的工具选择
    if not isinstance(last_user_message, HumanMessage):
        return {}
        
    user_query = last_user_message.content
    
    # 构建工具描述列表 (仅包含名称和描述，节省 Token)
    tool_descriptions = "\n".join([f"- {t.name}: {t.description}" for t in tools])
    
    # 调用 LLM 进行筛选
    # 注意：这里使用 json 模式强制输出列表
    prompt = f"""
    你是一个精准的工具分发员。
    
    【可用工具列表】
    {tool_descriptions}
    
    【用户指令】
    {user_query}
    
    请分析用户指令，判断需要使用哪些工具。
    如果用户只是闲聊，返回空列表 []。
    如果用户需要执行特定任务，返回最相关的工具名称列表。
    
    请务必只返回 JSON 格式的字符串，例如：["tool_a", "tool_b"]
    """
    
    try:
        response = llm.invoke(prompt)
        content = response.content
        
        # 简单的 JSON 解析
        import re
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if json_match:
            selected_names = json.loads(json_match.group())
            # 过滤掉不存在的工具名
            valid_names = [t.name for t in tools]
            final_selection = [name for name in selected_names if name in valid_names]
            
            # 如果筛选结果为空，但用户似乎在提问，为了保险起见，可以保留一些基础工具
            # 或者直接返回空，让 Agent 依靠自身能力回答
            return {"selected_tool_names": final_selection}
            
    except Exception as e:
        print(f"工具筛选失败: {e}")
        
    # 默认情况（或出错时）：不选中任何工具，或者选中所有工具（视策略而定）
    # 这里选择返回空，让 Agent 纯聊天，或者根据需要调整
    return {"selected_tool_names": []}

def agent_node(state: AgentState, config: RunnableConfig):
    messages = state['messages']
    user_id = state['user_id']
    summary = state.get('summary', "")
    selected_tool_names = state.get('selected_tool_names', [])
    
    # 根据筛选结果绑定工具
    # 策略：始终包含 search_memory 以便随时查阅记忆，其他工具按需加载
    current_tools = [t for t in tools if t.name in selected_tool_names]
    
    # 确保 search_memory 始终可用 (如果它不在筛选列表中)
    if "search_memory" not in [t.name for t in current_tools]:
        search_memory_tool = next((t for t in tools if t.name == "search_memory"), None)
        if search_memory_tool:
            current_tools.append(search_memory_tool)
    
    # 绑定工具
    if current_tools:
        llm_with_selected_tools = llm.bind_tools(current_tools)
    else:
        llm_with_selected_tools = llm # 无工具模式
    
    # 获取 thread_id
    thread_id = config.get("configurable", {}).get("thread_id", "default_thread")
    
    # 注入 user_id 到 config 中，供工具使用
    config["configurable"]["user_id"] = user_id
    
    # 加载核心画像 (Core Profile)
    core_profile = {}
    try:
        # Namespace: ("users", user_id)
        # Key: "core"
        item = store.get(("users", str(user_id)), "core")
        if item:
            core_profile = item.value
    except Exception as e:
        print(f"读取 Store 失败: {e}")
    
    # 构建系统提示词，包含当前时间和用户信息
    now = datetime.datetime.now()
    current_time = now.strftime("%Y-%m-%d %H:%M:%S")
    weekday = now.strftime("%A") # 获取星期几，例如 Monday
    
    # 简单的星期映射，方便中文理解（可选）
    weekday_map = {
        "Monday": "星期一", "Tuesday": "星期二", "Wednesday": "星期三",
        "Thursday": "星期四", "Friday": "星期五", "Saturday": "星期六", "Sunday": "星期日"
    }
    weekday_cn = weekday_map.get(weekday, weekday)

    system_prompt_content = f"""
    你是一个智能日程助手。
    当前时间是: {current_time} ({weekday_cn})
    你的会话ID (session_id) 是: {thread_id}
    
    你可以帮助用户管理日程和提醒。
    
    【核心用户画像 (常用信息)】
    {json.dumps(core_profile, ensure_ascii=False, indent=2) if core_profile else "暂无核心画像"}
    
    注意：
    1. 上述【核心用户画像】仅包含最常用的信息。
    2. 如果你需要查找更具体的细节（例如具体的过往经历、特定的偏好细节等），请使用 `search_memory` 工具进行搜索。
    3. 如果用户让你记住某些偏好，请在回复中明确确认。
    
    如果用户让你创建日程或提醒，但没有提供具体时间，请礼貌地询问。
    
    当调用创建日程 (create_calendar_event) 或创建提醒 (create_reminder) 工具时，
    请务必将 session_id 参数设置为 "{thread_id}"，以便支持后续的撤回操作。
    
    如果用户要求撤回上一步操作，请调用 rollback_transaction 工具，并传入 session_id。
    """
    
    # 如果有摘要，添加到系统提示词中
    if summary:
        system_prompt_content += f"""
        
        【之前的对话摘要】
        {summary}
        """
    
    system_prompt = SystemMessage(content=system_prompt_content)
    
    # 将系统提示词放在消息列表的最前面
    full_messages = [system_prompt] + messages
    
    response = llm_with_selected_tools.invoke(full_messages)
    return {"messages": [response]}

def summarize_conversation(state: AgentState):
    """
    总结旧的对话历史，以减少上下文长度。
    同时提取长期记忆并保存到 Store。
    """
    summary = state.get("summary", "")
    messages = state["messages"]
    user_id = state["user_id"]
    
    # 如果消息数量未超过阈值，不进行总结
    if len(messages) <= MAX_MESSAGES:
        return {}
        
    # 保留最近的 2 条消息
    messages_to_summarize = messages[:-2]
    
    if not messages_to_summarize:
        return {}
        
    # 从 Store 加载现有核心画像
    current_core = {}
    try:
        item = store.get(("users", str(user_id)), "core")
        if item:
            current_core = item.value
    except Exception:
        pass
        
    # 调用 LLM 生成摘要和提取记忆
    prompt = f"""
    请分析以下对话历史，完成三个任务：
    1. 将对话总结为一个简洁的段落（Context Summary）。
    2. 提取或更新用户的【核心画像】（Core Profile）。这应该只包含最关键、最常用的信息（如姓名、职业、核心习惯）。
    3. 提取具体的【细节记忆】（Memories）。这包含具体的事件、临时的偏好或不常用的细节。
    
    现有摘要: {summary}
    现有核心画像: {json.dumps(current_core, ensure_ascii=False)}
    
    新对话内容:
    """
    
    for msg in messages_to_summarize:
        role = "User" if isinstance(msg, HumanMessage) else ("AI" if isinstance(msg, AIMessage) else "System/Tool")
        content = msg.content
        if isinstance(content, list):
             content = str(content)
        prompt += f"{role}: {content}\n"
        
    prompt += """
    
    请按以下 JSON 格式输出：
    {
        "summary": "新的对话摘要...",
        "core_profile_updates": {
            "name": "...",
            "job": "..."
        },
        "new_memories": [
            "用户提到他上次去日本是在2023年",
            "用户不喜欢吃香菜"
        ]
    }
    """
    
    # 使用 json 模式调用 LLM
    response = llm.invoke(prompt)
    content = response.content
    
    # 简单的 JSON 解析
    new_summary = summary
    try:
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            new_summary = result.get("summary", summary)
            
            # 1. 更新核心画像
            updates = result.get("core_profile_updates", {})
            if updates:
                current_core.update(updates)
                store.put(("users", str(user_id)), "core", current_core)
            
            # 2. 添加新记忆
            new_memories = result.get("new_memories", [])
            for mem_text in new_memories:
                mem_id = str(uuid.uuid4())
                store.put(("users", str(user_id), "memories"), mem_id, {"content": mem_text, "created_at": datetime.datetime.now().isoformat()})
            
            # 持久化到文件
            if updates or new_memories:
                save_store_to_file(user_id)
                
        else:
            new_summary = content
            
    except Exception as e:
        print(f"解析摘要失败: {e}")
        new_summary = content
    
    # 删除已总结的消息
    delete_messages = [RemoveMessage(id=m.id) for m in messages_to_summarize if m.id]
    
    return {"summary": new_summary, "messages": delete_messages}

def router(state: AgentState):
    """
    决定下一步走向：工具调用、总结或结束
    """
    last_message = state['messages'][-1]
    
    # 1. 如果有工具调用，优先处理工具
    if last_message.tool_calls:
        return "tools"
        
    # 2. 如果消息列表过长，进行总结
    # 注意：只有在 AI 回复之后才检查总结，这样可以确保一轮对话完整
    if len(state['messages']) > MAX_MESSAGES:
        return "summarize"
        
    # 3. 否则结束
    return END

# ==========================================
# 图构建
# ==========================================
workflow = StateGraph(AgentState)

# 自定义工具节点，用于注入 user_id 到 config
tool_node = ToolNode(tools)

def custom_tool_node(state: AgentState, config: RunnableConfig):
    user_id = state.get("user_id")
    # 确保 configurable 存在
    if "configurable" not in config:
        config["configurable"] = {}
    # 注入 user_id
    config["configurable"]["user_id"] = user_id
    
    # 调用原始工具节点
    return tool_node.invoke(state, config)

# 添加节点
workflow.add_node("select_tools", select_tools_node)
workflow.add_node("agent", agent_node)
workflow.add_node("tools", custom_tool_node)
workflow.add_node("summarize", summarize_conversation)

# 设置入口点
workflow.set_entry_point("select_tools")

# 添加边
workflow.add_edge("select_tools", "agent")
workflow.add_conditional_edges(
    "agent",
    router,
    {
        "tools": "tools",
        "summarize": "summarize",
        END: END
    }
)

workflow.add_edge("tools", "agent")
workflow.add_edge("summarize", END)

import requests

# ... (imports)

# ... (AgentState, tools, llm setup)

# ... (agent_node, should_continue, workflow setup)

# 初始化内存检查点
# 注意：MemorySaver 仅用于开发/测试，重启后数据丢失。
# 生产环境请使用 PostgresSaver 或 SqliteSaver
memory = MemorySaver()

# 编译图，启用记忆功能
app = workflow.compile(checkpointer=memory)

def get_history(thread_id: str, config: dict = None):
    """获取会话历史快照"""
    # 始终获取该线程的完整历史
    full_history = list(app.get_state_history({"configurable": {"thread_id": thread_id}}))
    
    # 如果指定了特定的 checkpoint_id，则截取该点之前的历史
    if config and "checkpoint_id" in config.get("configurable", {}):
        target_id = config["configurable"]["checkpoint_id"]
        # 历史列表是按时间倒序排列的 (最新 -> 最旧)
        # 我们需要找到目标 checkpoint，并保留它及其之后的所有元素（即更旧的快照）
        for i, snapshot in enumerate(full_history):
            if snapshot.config['configurable']['checkpoint_id'] == target_id:
                return full_history[i:]
        
        # 如果没找到目标 checkpoint，可能是因为它是旧的或者无效的，这里返回完整历史作为降级
        # 或者也可以返回空列表，视情况而定
        return full_history
        
    return full_history

def get_turn_history(thread_id: str, config: dict = None):
    """
    Get a list of snapshots representing the end of each conversation turn.
    Returns a list of (turn_number, snapshot, user_message_preview)
    """
    history = get_history(thread_id, config)
    if not history:
        return []
        
    turn_snapshots = []
    seen_counts = set()
    
    for snapshot in history:
        msgs = snapshot.values['messages']
        human_msgs = [m for m in msgs if isinstance(m, HumanMessage)]
        count = len(human_msgs)
        
        if count not in seen_counts:
            seen_counts.add(count)
            # Get the last human message content for preview
            preview = human_msgs[-1].content if human_msgs else "<Start>"
            if len(preview) > 50:
                preview = preview[:50] + "..."
            
            turn_snapshots.append({
                "turn": count,
                "snapshot": snapshot,
                "preview": preview,
                "timestamp": snapshot.created_at
            })
            
    # Sort by turn number (0 to N)
    turn_snapshots.sort(key=lambda x: x['turn'])
    return turn_snapshots

def find_snapshot_by_turns(history, turns_back):
    """
    Find the snapshot index that corresponds to rolling back `turns_back` conversation turns.
    A "turn" is defined by a HumanMessage.
    """
    if not history:
        return None
        
    current_messages = history[0].values['messages']
    # Count total HumanMessages
    human_msgs = [m for m in current_messages if isinstance(m, HumanMessage)]
    total_turns = len(human_msgs)
    
    if turns_back >= total_turns:
        # Rollback to beginning (empty state)
        # Find the last snapshot with 0 messages or just the oldest one
        return history[-1] 
    
    target_turn_count = total_turns - turns_back
    
    # We want to find a snapshot where the number of HumanMessages is target_turn_count
    # AND it is the *last* snapshot of that turn (i.e., fully processed).
    # Since we iterate from 0 (latest), the first one we find with the correct count 
    # is the *end* of that turn.
    
    for snapshot in history:
        msgs = snapshot.values['messages']
        current_human_count = sum(1 for m in msgs if isinstance(m, HumanMessage))
        
        if current_human_count == target_turn_count:
            return snapshot
            
    return None

def time_travel_rollback(thread_id: str, turns: int, config: dict = None):
    """
    执行时间旅行回滚
    1. 获取目标快照 (基于对话轮次)
    2. 调用后端 API 回滚该时间点之后的所有数据库事务
    3. 返回目标快照的配置，以便下次运行时使用
    """
    history = get_history(thread_id, config)
    if not history:
        print("没有历史记录")
        return None
        
    target_snapshot = find_snapshot_by_turns(history, turns)
    
    if not target_snapshot:
        print(f"无法回滚 {turns} 轮对话")
        return None
        
    target_config = target_snapshot.config
    target_timestamp = target_snapshot.created_at
    
    print(f"正在回滚到: {target_timestamp} (Turns back: {turns})")
    
    # 调用后端 API 回滚数据库事务
    # 注意：这里假设后端 API 运行在本地 8000 端口
    try:
        # 构造 ISO 格式的时间戳字符串
        # 注意：LangGraph 的 created_at 可能是 UTC，需要确保与 Django 后端时区一致
        # 这里简单起见直接传递 ISO 字符串
        if isinstance(target_timestamp, str):
            timestamp_str = target_timestamp
        else:
            timestamp_str = target_timestamp.isoformat()
        
        response = requests.post(
            "http://127.0.0.1:8000/api/agent/rollback/",
            json={
                "session_id": thread_id,
                "target_timestamp": timestamp_str
            },
            headers={
                "Authorization": f"Token xx", # 使用硬编码的 Token 用于演示
                "Content-Type": "application/json"
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"后端回滚结果: {result.get('message')}")
            if result.get('data', {}).get('reverted_transactions'):
                for tx in result['data']['reverted_transactions']:
                    print(f"  - 已撤销: {tx.get('description')} ({tx.get('timestamp')})")
        elif response.status_code == 404:
             print("后端提示：该时间点之后没有需要回滚的事务。")
        else:
            print(f"后端回滚失败: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"调用后端回滚 API 出错: {e}")
        
    return target_config

def run_agent_demo(user_id: int, user_input: str, thread_id: str = "1", config: dict = None):
    """
    运行 Agent 的简单演示函数
    """
    print(f"User (ID: {user_id}): {user_input}")
    
    # 构造输入状态，只包含新消息
    input_state = {
        "messages": [HumanMessage(content=user_input)],
        "user_id": user_id
    }
    
    # 配置线程 ID 以保持上下文
    if config is None:
        config = {"configurable": {"thread_id": thread_id}}
    
    print("Agent: ", end="", flush=True)
    
    # 流式输出
    # 使用 stream_mode=["messages", "updates"] 同时获取 token 流和状态更新
    for mode, chunk in app.stream(input_state, config=config, stream_mode=["messages", "updates"]):
        if mode == "messages":
            # chunk 是 (message, metadata)
            message, metadata = chunk
            # 只打印 AI 消息的内容块
            if isinstance(message, AIMessageChunk):
                print(message.content, end="", flush=True)
        elif mode == "updates":
            # chunk 是状态更新字典
            for key, value in chunk.items():
                if key == "agent":
                    # 代理节点完成，换行
                    print("") 
                    msg = value["messages"][0]
                    if msg.tool_calls:
                        print(f"  (Tool Calls: {msg.tool_calls})")
                elif key == "tools":
                    # 工具节点完成
                    for msg in value["messages"]:
                        print(f"Tool Output: {msg.content}")
                    print("Agent: ", end="", flush=True) # 准备下一轮 AI 输出
                elif key == "summarize":
                    # 总结节点完成
                    print(f"\n[System] 已触发对话总结，压缩了历史消息。")
                    if "summary" in value:
                        print(f"[Summary] {value['summary'][:50]}...")
    print("") # 最后换行

if __name__ == "__main__":
    # 测试代码
    # 假设有一个用户 ID 为 1
    # 注意：运行此脚本需要 Django 环境已加载
    import sys
    import django
    
    # 添加项目根目录到 sys.path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    sys.path.append(project_root)
    
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'UniSchedulerSuper.settings')
    django.setup()
    
    # 交互式循环
    print("=== 智能日程助手 (CLI Demo) ===")
    print("输入 'q' 退出")
    print("输入 '/history' 查看历史快照")
    print("输入 '/rewind N' 回滚 N 轮对话 (例如 /rewind 1)")
    
    # 使用固定的 thread_id 来保持会话记忆
    thread_id = "cli_demo_user_1"
    current_config = None # 用于存储当前使用的配置（可能指向旧的 checkpoint）
    
    while True:
        user_input = input("\n请输入指令: ")
        if user_input.lower() == 'q':
            break
        
        if user_input.lower() == '/history':
            target_config = current_config if current_config else {"configurable": {"thread_id": thread_id}}
            turns = get_turn_history(thread_id, config=target_config)
            print(f"对话历史 (当前共 {len(turns)-1} 轮):")
            for item in turns:
                ts = item['timestamp']
                if not isinstance(ts, str):
                    ts = ts.strftime("%Y-%m-%d %H:%M:%S")
                
                if item['turn'] == 0:
                    print(f"  [Start] {ts} (初始状态)")
                else:
                    print(f"  [Turn {item['turn']}] {ts} | User: {item['preview']}")
            continue
            
        if user_input.lower().startswith('/rewind '):
            try:
                steps = int(user_input.split(' ')[1])
                target_config = current_config if current_config else {"configurable": {"thread_id": thread_id}}
                new_config = time_travel_rollback(thread_id, steps, config=target_config)
                if new_config:
                    current_config = new_config
                    print(f"已回滚到快照，下次对话将从该点继续。")
            except ValueError:
                print("请输入有效的步数")
            continue
        
        try:
            # 如果有 current_config (回滚后)，使用它；否则使用默认的 thread_id 配置
            run_config = current_config if current_config else {"configurable": {"thread_id": thread_id}}
            
            run_agent_demo(1, user_input, thread_id=thread_id, config=run_config)
            
            # 运行一次后，重置 current_config，后续对话将基于新的最新状态继续
            current_config = None
            
        except Exception as e:
            print(f"发生错误: {e}")
