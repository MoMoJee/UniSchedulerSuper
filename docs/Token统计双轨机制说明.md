# Token 统计双轨机制说明

**时间**: 2026-02-18  
**问题**: 为什么日志中出现两次 Token 统计？

---

## 一、问题现象

用户在日志中发现了两次 Token 统计：

```log
2026-02-18 01:36:31 | DEBUG | agent_service\context_summarizer.py | build_optimized_context:548 | 
[上下文] 构建完成: System=395t, Summary=0t, Recent=4t (1条), Total=399t

2026-02-18 01:36:35 | DEBUG | agent_service\context_optimizer.py | update_token_usage:607 | 
[Token统计] 开始更新: user=MoMoJee, model=system_deepseek, in=4648, out=118
```

**疑问**：
1. 这两个统计分别用在什么位置？
2. 最终计费用的是哪个？
3. 为什么数值差异这么大（399 vs 4648）？

---

## 二、双轨机制解析

### 2.1 第一轨：上下文优化预估（不用于计费）

**文件**: `agent_service/context_summarizer.py`  
**函数**: `build_optimized_context()`  
**行号**: ~548

```python
logger.debug(
    f"[上下文] 构建完成: "
    f"System={system_tokens}t, "
    f"Summary={summary_tokens}t, "
    f"Recent={recent_tokens}t ({len(recent_messages)}条), "
    f"Total={total_tokens}t (优化前预估，不用于计费)"
)
```

**用途**：
- 判断是否需要压缩上下文
- 决定是否生成总结（Summary）
- 优化工具输出长度

**计算方式**：
- 使用本地 `TokenCalculator` (tiktoken 库)
- 仅计算**即将发送给 LLM 的消息内容**
- **不包含**系统指令、工具定义、模型特定的额外开销

**特点**：
- ✅ 快速本地计算（无需 API 调用）
- ✅ 用于决策逻辑（压缩/总结）
- ❌ 不准确（缺少模型特定开销）
- ❌ 不用于计费

---

### 2.2 第二轨：实际 Token 计费（用于计费）

**文件**: `agent_service/context_optimizer.py`  
**函数**: `update_token_usage()`  
**行号**: ~607

```python
logger.debug(
    f"[Token统计-计费] 开始更新: user={user.username}, "
    f"model={model_id}, in={input_tokens}, out={output_tokens}"
)
```

**用途**：
- 计费和配额管理
- 月度统计和成本核算
- 保存到 `agent_token_usage` (UserData)

**计算方式（三级优先级）**：

| 优先级 | 数据来源 | 准确性 | 说明 |
|--------|----------|--------|------|
| 1️⃣ **Actual** | `response.usage_metadata` | ⭐⭐⭐⭐⭐ 精确 | LLM API 返回的实际用量 |
| 2️⃣ **Response Metadata** | `response.response_metadata['usage']` | ⭐⭐⭐⭐⭐ 精确 | 旧版 API 的返回格式 |
| 3️⃣ **Estimated** | 字符数 / 2.5 | ⭐⭐ 粗略 | ⚠️ 降级方案，仅在 API 未返回时使用 |

**特点**：
- ✅ 来自 LLM API 官方数据（最准确）
- ✅ 包含所有开销（系统指令、工具定义、特殊 token 等）
- ✅ 用于实际计费
- ⚠️ 需要 API 调用后才能获取

---

## 三、为什么数值差异巨大？

### 示例分析

**第一轨（上下文预估）**: Total=399t
- System prompt: 395t
- 用户消息 "你好": 4t
- **不包含**: 工具定义、模型特定开销

**第二轨（实际计费）**: in=4648t
- System prompt: 395t
- 用户消息: 4t
- **工具定义**: ~4000t (所有工具的 JSON Schema)
- **额外开销**: ~250t (special tokens, format control)

### 工具定义的影响

当前系统有 **50+ 工具**（包括 Planner、MCP、12306 等），每个工具的定义包括：
- 函数名称和描述
- 参数 Schema (JSON)
- 示例和约束

**估算**：
- 简单工具: ~50-100 tokens
- 复杂工具: ~200-500 tokens
- 50 个工具合计: **~4000-5000 tokens**

这就是为什么 `in=4648` 远大于 `Total=399t` 的原因！

---

## 四、数据流向图

```
用户发送消息
    ↓
┌─────────────────────────────────────────────┐
│ 第一轨：上下文优化预估（不计费）            │
│ context_summarizer.py                       │
│                                             │
│ 1. 计算当前消息 Token 数（本地 tiktoken）   │
│ 2. 判断是否需要压缩                        │
│ 3. 记录日志: Total=399t (优化前预估)       │
└─────────────────────────────────────────────┘
    ↓
构建完整消息（+ 工具定义）
    ↓
发送给 LLM API
    ↓
LLM API 处理并返回
    ↓
┌─────────────────────────────────────────────┐
│ 第二轨：实际 Token 计费（用于计费）         │
│ agent_graph.py → context_optimizer.py       │
│                                             │
│ 1. 提取 response.usage_metadata             │
│    - input_tokens (含工具定义)             │
│    - output_tokens                          │
│ 2. 如果 API 未返回，降级为估算（WARNING）  │
│ 3. 调用 update_token_usage() 保存          │
│ 4. 记录日志: in=4648, out=118, source=actual│
└─────────────────────────────────────────────┘
    ↓
保存到 UserData.agent_token_usage
    ↓
用于配额管理和成本核算
```

---

## 五、估算值降级机制

### 何时触发估算？

当 LLM API **未返回** `usage_metadata` 时（极少见，但可能发生）：
- 某些第三方 API 不支持 usage 字段
- API 服务异常或超时
- 使用不兼容的模型

### 估算方式

```python
# 输入 Token 估算：所有消息内容的字符数 / 2.5
total_input_chars = sum(len(msg.content) for msg in full_messages)
input_tokens = int(total_input_chars / 2.5)

# 输出 Token 估算：响应内容的字符数 / 2.5
output_tokens = int(len(response_content) / 2.5) or 10
```

**注意**：
- ⚠️ 此估算值**会用于计费**
- ⚠️ 可能存在较大偏差（±30%）
- ⚠️ 建议定期核对实际账单

### 日志示例（降级场景）

```log
⚠️ [Token统计降级] 无法从API获取Token用量，使用估算值（将用于计费，可能存在偏差）。
模型=custom_model, usage_metadata=None, response_metadata 可用字段=['model_name']

[Token统计] 输入Token估算: 12000 字符 → 4800 tokens
[Token统计] 输出Token估算: 350 字符 → 140 tokens

[Agent] Token 统计已更新: in=4800, out=140, model=custom_model, source=estimated
```

---

## 六、完整日志示例

### 正常情况（使用 API 返回值）

```log
# 第一轨：上下文优化预估
[上下文] 构建完成: System=395t, Summary=0t, Recent=4t (1条), Total=399t (优化前预估，不用于计费)

# 第二轨：实际 Token 计费
[Token统计-计费] 开始更新: user=MoMoJee, model=system_deepseek, in=4648, out=118
[Token统计-计费] 已保存: user=MoMoJee, model=system_deepseek, input=4648, output=118, cost=¥0.0129
[Agent] Token 统计已更新: in=4648, out=118, model=system_deepseek, source=actual
```

**解读**：
- 优化前预估: 399 tokens（本地计算，不含工具定义）
- 实际计费: 4648 tokens（API 返回，含工具定义）
- 数据来源: `actual`（来自 API）
- 成本: ¥0.0129 (4.648k × 0.002 + 0.118k × 0.003)

---

### 异常情况（降级为估算）

```log
# 第一轨：上下文优化预估
[上下文] 构建完成: System=520t, Summary=0t, Recent=150t (3条), Total=670t (优化前预估，不用于计费)

# 第二轨：降级为估算
⚠️ [Token统计降级] 无法从API获取Token用量，使用估算值（将用于计费，可能存在偏差）。
模型=qwen-plus, usage_metadata=None, response_metadata 可用字段=['model_name', 'system_fingerprint']

[Token统计] 输入Token估算: 1680 字符 → 672 tokens
[Token统计] 输出Token估算: 285 字符 → 114 tokens
[Agent] Token 统计已更新: in=672, out=114, model=qwen-plus, source=estimated

[Token统计-计费] 开始更新: user=TestUser, model=qwen-plus, in=672, out=114
[Token统计-计费] 已保存: user=TestUser, model=qwen-plus, input=672, output=114, cost=¥0.0018
```

**解读**：
- ⚠️ API 未返回 `usage_metadata`
- 降级使用字符数估算（字符数 / 2.5）
- 数据来源: `estimated`（不精确）
- **建议**: 核对官方账单，评估偏差

---

## 七、常见问题 FAQ

### Q1: 为什么需要两个统计？

**A**: 
- **第一轨**：优化决策（需要快速本地计算）
- **第二轨**：精确计费（需要 API 官方数据）

两者目的不同，无法合并。

---

### Q2: 第一轨的预估有什么用？

**A**: 用于上下文管理：
- 判断消息历史是否过长（需要总结）
- 决定是否压缩工具输出
- 估算是否接近模型上下文窗口限制

---

### Q3: 如何判断当前使用的是估算值？

**A**: 查看日志中的 `source` 字段：
- `source=actual`: 来自 API（精确）
- `source=estimated`: 降级估算（不精确）

或者查找 `⚠️ [Token统计降级]` WARNING 日志。

---

### Q4: 估算值的误差有多大？

**A**: 
- **英文文本**: ±10%（接近实际值）
- **中文文本**: ±20%（中文 token 化更复杂）
- **工具定义**: **不包含**（缺失 ~4000 tokens）

**建议**: 如果频繁出现估算，检查 API 配置或更换模型。

---

### Q5: 如何避免使用估算值？

**A**: 
1. 使用官方 API（OpenAI、DeepSeek、Qwen 等）
2. 确保 API 返回 `usage` 字段
3. 检查网络连接和 API 响应完整性
4. 避免使用不兼容的自定义模型

---

### Q6: 成本计算公式是什么？

**A**: 
```python
cost = (input_tokens / 1000) × cost_per_1k_input + 
       (output_tokens / 1000) × cost_per_1k_output
```

示例（DeepSeek V3）：
- Input: 4648 tokens × (0.002 CNY / 1000) = ¥0.009296
- Output: 118 tokens × (0.003 CNY / 1000) = ¥0.000354
- **Total**: ¥0.00965 ≈ **¥0.0097**

---

## 八、监控建议

### 关键日志监控

1. **估算频率**:
   ```bash
   grep "Token统计降级" logs/*.log | wc -l
   ```
   
   如果频率 > 5%，需要检查 API 配置。

2. **数据来源分布**:
   ```bash
   grep "source=actual" logs/*.log | wc -l
   grep "source=estimated" logs/*.log | wc -l
   ```
   
   理想情况: `actual` > 95%

3. **成本异常**:
   ```bash
   grep "cost=¥" logs/*.log | awk -F'¥' '{print $2}' | sort -nr | head -10
   ```
   
   检查是否有异常高额消费。

---

## 九、修改日志

| 日期 | 文件 | 修改内容 |
|------|------|----------|
| 2026-02-18 | `context_summarizer.py:549` | 添加备注 "(优化前预估，不用于计费)" |
| 2026-02-18 | `agent_graph.py:730` | WARNING 中添加 "将用于计费，可能存在偏差" |
| 2026-02-18 | `agent_graph.py:756` | DEBUG 日志添加 `source=actual/estimated` |
| 2026-02-18 | `context_optimizer.py:607` | 标注 "[Token统计-计费]" |

---

## 十、相关文档

- [Token统计与图片处理日志优化.md](./Token统计与图片处理日志优化.md) - 图片 Token 处理说明
- [上下文优化机制说明.md](./上下文优化机制说明.md) - 上下文压缩和总结机制（待补充）

---

**文档版本**: v1.0  
**更新日期**: 2026-02-18  
**维护者**: AI Assistant
