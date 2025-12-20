import os
import json
import uuid
from langgraph.store.memory import InMemoryStore

# ==========================================
# 长期记忆存储 (Store 持久化层)
# ==========================================
MEMORY_FILE = "agent_service/long_term_memory.json"

# 初始化 LangGraph Store
# 在生产环境中，这里可以使用 PostgresStore
store = InMemoryStore()

def load_store_from_file():
    """从文件加载数据到 InMemoryStore"""
    if not os.path.exists(MEMORY_FILE):
        return
    try:
        with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # data 结构: { "user_id": { "core": {...}, "memories": [...] } }
            for user_id, user_data in data.items():
                # 1. 加载核心画像
                if "core" in user_data:
                    store.put(("users", str(user_id)), "core", user_data["core"])
                
                # 2. 加载细节记忆 (作为独立的 Item)
                if "memories" in user_data and isinstance(user_data["memories"], list):
                    for mem in user_data["memories"]:
                        # mem 结构: {"id": "...", "content": "..."}
                        mem_id = mem.get("id", str(uuid.uuid4()))
                        store.put(("users", str(user_id), "memories"), mem_id, mem)
        print(f"已从 {MEMORY_FILE} 加载长期记忆")
    except Exception as e:
        print(f"加载记忆文件失败: {e}")

def save_store_to_file(user_id: str):
    """将 Store 中的数据持久化到文件"""
    # 读取现有文件以保留其他用户数据
    all_data = {}
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                all_data = json.load(f)
        except Exception:
            pass
    
    # 获取当前用户数据
    user_str = str(user_id)
    if user_str not in all_data:
        all_data[user_str] = {}
    
    # 1. 保存核心画像
    core_item = store.get(("users", user_str), "core")
    if core_item:
        all_data[user_str]["core"] = core_item.value
    
    # 2. 保存细节记忆
    # 搜索该用户命名空间下的所有 memories
    memories_result = store.search(("users", user_str, "memories"))
    memories_list = []
    for item in memories_result:
        memories_list.append(item.value)
    all_data[user_str]["memories"] = memories_list
    
    # 写入文件
    os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)
    with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)

# 模块加载时自动初始化数据
load_store_from_file()
