# Token 统计计费升级文档

## 📋 需求概述

1. 每次 LLM 调用（对话、工具调用、历史总结、会话命名）都统计输入/输出 token 和成本
2. 按用户+模型分别统计，系统模型和自定义模型分开
3. 系统模型月度限额：5 CNY/月，UTC 每月1日重置
4. 自定义模型仅统计不限额
5. 所有单位使用 CNY

## 🔧 技术方案

### 数据结构

```python
# UserData key='agent_token_usage'
{
    "current_month": "2026-01",
    "monthly_credit": 5.0,        # 本月抵用金 (CNY)
    "monthly_used": 2.35,         # 本月已使用 (CNY，仅系统模型)
    "last_reset": "2026-01-01T00:00:00Z",
    
    # 按模型统计（当月）
    "models": {
        "system_deepseek": {
            "input_tokens": 12000,
            "output_tokens": 8000,
            "cost": 2.35
        },
        "custom_xxx": {
            "input_tokens": 5000,
            "output_tokens": 3000,
            "cost": 0.5  # 仅统计，不计入限额
        }
    },
    
    # 历史统计（按月归档）
    "history": {
        "2025-12": {
            "system_deepseek": {"input": 50000, "output": 30000, "cost": 10.5}
        }
    }
}
```

### 系统模型成本配置

在 `api_keys_manager.py` 中添加：

```python
SYSTEM_MODEL_COSTS = {
    "system_deepseek": {
        "name": "DeepSeek Chat（系统提供）",
        "cost_per_1k_input": 0.001,    # CNY
        "cost_per_1k_output": 0.002,   # CNY
    }
}
```

### 配额检查逻辑

1. **发送消息前检查**：
   - 如果使用系统模型且 `monthly_used >= monthly_credit`
   - 返回错误，前端显示提示
   
2. **允许完成当前回复**：
   - 检查点在用户发送新消息时
   - Agent 回复过程中不中断

### 月度重置

- 每次调用时检查 `current_month`
- 如果不是当前月，自动重置：
  - 归档上月数据到 `history`
  - 重置 `monthly_used = 0`
  - 重置 `monthly_credit = 5.0`
  - 清空当月 `models` 统计

## 📝 实施步骤

### Phase 1: 后端核心逻辑

1. **api_keys_manager.py**
   - 添加 `SYSTEM_MODEL_COSTS` 配置
   - 添加 `get_model_cost_config(model_id)` 方法

2. **context_optimizer.py**
   - 重写 `update_token_usage()` 函数
   - 添加 `check_quota_available(user, model_id)` 函数
   - 添加 `get_token_stats(user)` 函数
   - 添加月度自动重置逻辑

3. **统计调用点补充**
   - context_summarizer.py: `summarize()` 方法
   - agent_service/models.py: `generate_name_if_needed()` 方法

### Phase 2: 配额拦截

1. **consumers.py**
   - 在 `process_message()` 开始处调用 `check_quota_available()`
   - 超额时发送 `quota_exceeded` 事件

2. **前端拦截** (agent-chat.js)
   - 处理 `quota_exceeded` 事件
   - 显示友好提示

### Phase 3: API 接口

1. **views_config_api.py**
   - 重写 `get_token_stats()` API
   - 返回新数据结构

### Phase 4: 前端界面

1. **home.html**
   - 重构 Token 统计面板 UI

2. **agent-config.js**
   - 实现 `loadTokenStats()` 方法
   - 显示配额使用进度条

## ✅ 确认事项

- [x] 汇率：不需要转换，直接存储 CNY
- [x] 重置通知：不需要邮件，界面提示即可
- [x] 超额处理：允许完成当前回复，禁止发新消息
- [x] 统计不区分用途：普通对话、总结、命名统一按输入/输出统计
