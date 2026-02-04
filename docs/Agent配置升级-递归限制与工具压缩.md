# Agent 配置系统升级 - 递归限制与工具压缩配置

> **升级日期**: 2026-02-04  
> **升级内容**: 将硬编码的 `RECURSION_LIMIT` 和 `TOOL_COMPRESS_PRESERVE_RECENT_USER_MESSAGES` 迁移到用户可配置的 `agent_optimization_config` 中

---

## 📋 升级概述

### 升级前
- `RECURSION_LIMIT = 25` - 硬编码在 `consumers.py` 中
- `TOOL_COMPRESS_PRESERVE_RECENT_USER_MESSAGES = 5` - 硬编码在 `context_summarizer.py` 中
- 所有用户使用相同的固定值，无法个性化调整

### 升级后
- 两个参数都加入了 `agent_optimization_config` 数据库配置
- 用户可以通过前端 UI 自定义配置
- 支持实时生效，无需重启服务

---

## 🎯 新增配置项

### 1. recursion_limit（最大执行步数）

| 属性 | 值 |
|------|-----|
| **配置键** | `recursion_limit` |
| **默认值** | `25` |
| **类型** | `int` |
| **范围** | `10-100`（前端限制） |
| **说明** | Agent 单次对话允许的最大图执行步数 |

**解释**：
- 这**不是**工具调用次数，而是图的执行步数
- 一轮完整的工具调用通常需要 2-3 个步数：
  1. LLM 生成工具调用
  2. 执行工具
  3. LLM 处理结果
- 建议值：
  - `25` ≈ 支持 8-10 轮工具调用
  - `50` ≈ 支持 15-20 轮工具调用

---

### 2. tool_compress_preserve_recent_messages（保留最近消息数）

| 属性 | 值 |
|------|-----|
| **配置键** | `tool_compress_preserve_recent_messages` |
| **默认值** | `5` |
| **类型** | `int` |
| **范围** | `1-20`（前端限制） |
| **说明** | 最近 N 条用户消息对应的工具调用结果不压缩 |

**解释**：
- 从后往前数 N 条用户消息
- 这 N 条消息之后的工具调用结果**不会被压缩**
- N 条消息之前的工具调用结果**会被智能压缩**
- 目的：保留最近的完整上下文，同时压缩历史信息

**示例**：
```
设置为 5，对话历史：

用户消息 1  →  工具调用 A  ← 会被压缩
用户消息 2  →  工具调用 B  ← 会被压缩
用户消息 3  →  工具调用 C  ← 会被压缩
...
用户消息 6  →  工具调用 F  ← 不压缩（倒数第 5 条）
用户消息 7  →  工具调用 G  ← 不压缩（倒数第 4 条）
用户消息 8  →  工具调用 H  ← 不压缩（倒数第 3 条）
用户消息 9  →  工具调用 I  ← 不压缩（倒数第 2 条）
用户消息 10 →  工具调用 J  ← 不压缩（倒数第 1 条）
```

---

## 📁 修改文件清单

### 后端文件

1. **core/models.py**
   - ✅ 在 `agent_optimization_config` schema 中添加两个新字段

2. **agent_service/context_optimizer.py**
   - ✅ 在默认配置中添加两个新字段

3. **agent_service/consumers.py**
   - ✅ 从用户配置读取 `recursion_limit`
   - ✅ 更新注释说明迁移状态

4. **agent_service/context_summarizer.py**
   - ✅ 添加 `preserve_recent_count` 参数
   - ✅ 更新注释说明迁移状态

5. **agent_service/agent_graph.py**
   - ✅ 传递 `preserve_recent_count` 参数到上下文构建函数

6. **agent_service/views_config_api.py**
   - ✅ 添加两个新字段到 `allowed_fields` 列表

### 前端文件

7. **core/templates/home.html**
   - ✅ 添加"工具输出压缩"部分的 UI：
     - 工具输出最大 Token（已有）
     - **保留最近消息数**（新增）
   - ✅ 添加"执行控制"部分的 UI：
     - **最大执行步数**（新增）
     - 说明文字和提示

8. **core/static/js/agent-config.js**
   - ✅ `updateOptimizationUI()` - 加载配置时填充新字段
   - ✅ `saveOptimizationConfig()` - 保存配置时包含新字段
   - ✅ `resetOptimizationConfig()` - 重置时恢复默认值

---

## 🧪 测试验证

运行测试脚本：
```bash
python test_config_upgrade.py
```

测试结果：
```
✅ 测试用户: MoMoJee (ID: 1)

【新增配置】
  recursion_limit:                      25 ✅
  tool_compress_preserve_recent_messages: 5 ✅

🗄️  检查数据库 schema...
  recursion_limit in schema:                      True ✅
  tool_compress_preserve_recent_messages in schema: True ✅
```

---

## 🎨 前端界面预览

### AI 设置 → 上下文优化 → 工具输出压缩

```
┌─────────────────────────────────────────────────┐
│ 📦 工具输出压缩                                  │
├─────────────────────────────────────────────────┤
│                                                 │
│ ☑️ 压缩工具输出                                  │
│    自动压缩过长的工具返回结果                    │
│                                                 │
│ 工具输出最大 Token    保留最近消息数             │
│ [   200   ]          [    5    ]               │
│ 每次工具调用结果      最近 N 条用户消息          │
│ 的最大 Token 数       的工具结果不压缩           │
│                                                 │
└─────────────────────────────────────────────────┘
```

### AI 设置 → 上下文优化 → 执行控制

```
┌─────────────────────────────────────────────────┐
│ ⚙️ 执行控制                                      │
├─────────────────────────────────────────────────┤
│                                                 │
│ 最大执行步数                                     │
│ [   25   ]                                      │
│ 单次对话允许的最大图执行步数                      │
│ （约支持 8-10 轮工具调用）                        │
│                                                 │
│ ℹ️ 执行步数说明：                                │
│   一轮完整的工具调用通常需要 2-3 个步数。        │
│   建议值：25（约 8-10 轮）或 50（约 15-20 轮）   │
│                                                 │
└─────────────────────────────────────────────────┘
```

---

## 📊 配置建议

### 保守策略（适合新用户）
```json
{
  "recursion_limit": 25,
  "tool_compress_preserve_recent_messages": 5
}
```

### 激进策略（复杂任务）
```json
{
  "recursion_limit": 50,
  "tool_compress_preserve_recent_messages": 3
}
```

### 调试模式（开发测试）
```json
{
  "recursion_limit": 100,
  "tool_compress_preserve_recent_messages": 10
}
```

---

## 🔄 兼容性

### 向后兼容
- ✅ 旧代码中的常量保留作为后备默认值
- ✅ 数据库中没有配置时自动使用默认值
- ✅ 现有用户无感知升级

### 迁移说明
- 无需数据迁移脚本
- 用户首次访问设置页面时会看到默认值
- 可以立即调整配置并保存

---

## 🎉 升级完成

所有修改已完成并通过测试！用户现在可以：

1. ✅ 在前端 UI 中调整 Agent 最大执行步数
2. ✅ 自定义工具压缩策略（保留多少最近消息）
3. ✅ 配置实时生效，无需重启
4. ✅ 每个用户独立配置，满足个性化需求

---

## 📝 后续优化建议

1. **添加配置模板**：为不同场景提供预设配置（简单对话/复杂任务/调试模式）
2. **配置验证**：添加前端实时验证和智能推荐
3. **使用统计**：记录实际使用的平均步数，帮助用户调整配置
4. **性能监控**：监控配置对系统性能的影响

---

**文档版本**: 1.0  
**最后更新**: 2026-02-04
