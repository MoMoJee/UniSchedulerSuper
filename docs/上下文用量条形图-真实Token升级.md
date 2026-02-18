# 上下文用量条形图升级 - 使用 LLM 真实 Token 数据

**时间**: 2026-02-18  
**目标**: 从 LLM API 获取真实的 Token 数据，替代字符数估算

---

## 一、升级概述

### 核心改进

**之前**：前端显示使用字符数估算（不准确）
- ❌ 不包含工具定义（~4000 tokens）
- ❌ 图片固定 85 tokens
- ❌ 估算公式粗糙（±20-30% 误差）

**现在**：使用 LLM API 返回的真实 Token 数据
- ✅ 来自 `response.usage_metadata.input_tokens`（API 官方数据）
- ✅ 包含所有上下文（工具定义、图片、特殊 token）
- ✅ 精确度 ⭐⭐⭐⭐⭐

---

## 二、数据流架构

### 新的数据流

```
用户发送消息
    ↓
Agent 请求 LLM
    ↓
LLM 返回: response.usage_metadata {
    input_tokens: 4648,    // ← 包含所有上下文
    output_tokens: 118
}
    ↓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
两条路径（同时进行）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ↓                               ↓
【路径 1：计费】                   【路径 2：前端显示】
    ↓                               ↓
update_token_usage()            session.update_context_tokens()
    ↓                               ↓
保存到 UserData               保存到 AgentSession
agent_token_usage             last_input_tokens
（用于成本统计）              （用于前端显示）
                                    ↓
                            前端调用 /api/agent/context-usage/
                                    ↓
                            读取 last_input_tokens 和 summary_input_tokens
                                    ↓
                            计算 recent_tokens = last - summary
                                    ↓
                            返回前端渲染条形图
```

---

## 三、数据库模型扩展

### AgentSession 新增字段

| 字段 | 类型 | 说明 | 示例值 |
|------|------|------|--------|
| `summary_input_tokens` | IntegerField | 总结时的 input_tokens（LLM 真实值） | 3200 |
| `summary_tokens_source` | CharField(20) | Token 数据来源 | 'actual' / 'estimated' |
| `last_input_tokens` | IntegerField | 最近一次请求的 input_tokens（LLM 真实值） | 4648 |
| `last_input_tokens_source` | CharField(20) | Token 数据来源 | 'actual' / 'estimated' |
| `last_input_tokens_updated_at` | DateTimeField | 最近一次更新时间 | 2026-02-18 01:36:35 |

### 新增方法

```python
# AgentSession.update_context_tokens()
def update_context_tokens(self, input_tokens: int, tokens_source: str = 'actual'):
    """更新最近一次请求的上下文 Token 数（LLM 真实返回值）"""
    self.last_input_tokens = input_tokens
    self.last_input_tokens_source = tokens_source
    self.last_input_tokens_updated_at = timezone.now()
    self.save(update_fields=[...])

# AgentSession.save_summary() - 扩展参数
def save_summary(self, summary_text, summarized_until, summary_tokens,
                 summary_input_tokens=0, tokens_source='estimated'):
    """保存总结（新增 summary_input_tokens 和 tokens_source）"""
    # ...
```

---

## 四、关键修改清单

### 1. agent_graph.py（每次 LLM 请求后保存）

**位置**: Line 755-770

```python
# 成本由 update_token_usage 自动计算（基于 CNY）
update_token_usage(user, input_tokens, output_tokens, current_model_id)
logger.debug(f"[Agent] Token 统计已更新: in={input_tokens}, out={output_tokens}, source={source}")

# ========== 保存上下文 Token 数到会话（用于前端显示）==========
try:
    from agent_service.models import AgentSession
    session_id = configurable.get("thread_id")
    if session_id:
        session = AgentSession.objects.filter(session_id=session_id).first()
        if session:
            session.update_context_tokens(input_tokens, source)
            logger.debug(f"[上下文显示] 已更新会话 Token: session={session_id}, input_tokens={input_tokens}, source={source}")
except Exception as e:
    logger.error(f"[上下文显示] 保存 Token 失败: {e}", exc_info=True)
```

**日志输出**:
```log
[Agent] Token 统计已更新: in=4648, out=118, model=system_deepseek, source=actual
[上下文显示] 已更新会话 Token: session=user_123_default, input_tokens=4648, source=actual
```

---

### 2. context_summarizer.py（总结时保存 input_tokens）

**位置**: Line 264-300

**修改 1: 提取 tokens_source**

```python
# 尝试从 response 获取实际 token 使用
input_tokens = 0
output_tokens = 0
tokens_source = 'estimated'  # ← 新增默认值

# 优先检查 usage_metadata
if hasattr(response, 'usage_metadata') and response.usage_metadata:
    # ... 提取 input_tokens 和 output_tokens ...
    if input_tokens > 0 and output_tokens > 0:
        tokens_source = 'actual'  # ← 标记为真实值

# 如果无法获取实际值，使用估算值
if input_tokens == 0 or output_tokens == 0:
    logger.warning(f"⚠️ [总结-Token降级] 无法从API获取Token用量，使用估算值（将用于上下文显示）")
    tokens_source = 'estimated'
    # ... 估算逻辑 ...
```

**修改 2: 返回 summary_input_tokens 和 tokens_source**

```python
return {
    "summary": summary_text,
    "summarized_until": len(messages),
    "summary_tokens": summary_tokens,
    "summary_input_tokens": input_tokens,  # ← 新增
    "tokens_source": tokens_source,  # ← 新增
    "created_at": datetime.now().isoformat(),
    # ...
}
```

**日志输出**:
```log
[总结] 完成: 5条消息, 1200t → 300t, 压缩率=75.0%, input_tokens=3200, source=actual
[总结-计费] Token 统计已更新: in=3200, out=300, source=actual
```

---

### 3. consumers.py（保存总结时传递新参数）

**位置**: Line 1237-1247

```python
# 保存总结（包含真实的 input_tokens 和 tokens_source）
await database_sync_to_async(session.save_summary)(
    summary_text=new_summary_metadata['summary'],
    summarized_until=end_idx,
    summary_tokens=new_summary_metadata['summary_tokens'],
    summary_input_tokens=new_summary_metadata.get('summary_input_tokens', 0),  # ← 新增
    tokens_source=new_summary_metadata.get('tokens_source', 'estimated')  # ← 新增
)

tokens_source = new_summary_metadata.get('tokens_source', 'estimated')
summary_input_tokens = new_summary_metadata.get('summary_input_tokens', 0)

logger.info(
    f"[总结] 完成: 总结了 {end_idx} 条消息, "
    f"output={new_summary_metadata['summary_tokens']}t, "
    f"input={summary_input_tokens}t, source={tokens_source}"
)
```

**日志输出**:
```log
[总结] 完成: 总结了 50 条消息, output=300t, input=3200t, source=actual
```

---

### 4. views_api.py - get_context_usage（关键升级）

**位置**: Line 1835-1950

#### 核心逻辑

```python
# ========== 使用 LLM 真实返回的 Token 数据 ==========
session = AgentSession.objects.filter(session_id=session_id).first()

if session:
    # 读取总结的真实 Token 数据
    if session.summary_text:
        summary_input_tokens = session.summary_input_tokens or 0  # 总结时的 input_tokens
        summary_tokens_source = session.summary_tokens_source or 'estimated'
    
    # 读取最近一次请求的真实 input_tokens
    total_tokens = session.last_input_tokens or 0
    total_tokens_source = session.last_input_tokens_source or 'estimated'
    
    logger.debug(
        f"[上下文显示] 读取会话Token数据: session={session_id}, "
        f"total={total_tokens} (source={total_tokens_source}), "
        f"summary_input={summary_input_tokens} (source={summary_tokens_source})"
    )

# ========== 计算 recent_tokens ==========
# recent_tokens = 最近一次请求的 input_tokens - 总结时的 input_tokens
if has_summary and summary_input_tokens > 0:
    recent_tokens = max(0, total_tokens - summary_input_tokens)
else:
    recent_tokens = total_tokens
```

#### 降级处理

```python
# ========== 降级处理：如果没有真实数据，使用估算 ==========
if total_tokens == 0:
    logger.warning(
        f"⚠️ [上下文显示-降级] 会话 {session_id} 无真实Token数据，使用估算值。"
        f"可能原因：1) 新会话尚未请求LLM  2) 数据库未迁移"
    )
    
    # 降级：使用旧的估算方式
    # ... estimate_tokens() 逻辑 ...
    
    total_tokens_source = 'estimated'

# 如果使用了估算值，发出 WARNING
if total_tokens_source == 'estimated' or summary_tokens_source == 'estimated':
    logger.warning(
        f"⚠️ [上下文显示-使用估算] session={session_id}, "
        f"total_source={total_tokens_source}, summary_source={summary_tokens_source}, "
        f"显示值可能不准确（不包含工具定义约4k tokens）"
    )
```

#### 返回数据（新增字段）

```python
return Response({
    "session_id": session_id,
    # ... existing fields ...
    "tokens_source": total_tokens_source,  # ← 新增：标识数据来源
    "summary_tokens_source": summary_tokens_source  # ← 新增：总结数据来源
})
```

---

## 五、日志系统

### DEBUG 日志（正常情况）

```log
# 每次 LLM 请求后
[Agent] Token 统计已更新: in=4648, out=118, model=system_deepseek, source=actual
[上下文显示] 已更新会话 Token: session=user_123_default, input_tokens=4648, source=actual

# 读取上下文数据时
[上下文显示] 读取会话Token数据: session=user_123_default, total=4648 (source=actual), summary_input=3200 (source=actual)
[上下文显示] 计算recent_tokens: total=4648 - summary_input=3200 = 1448

# 总结完成时
[总结] 完成: 5条消息, 1200t → 300t, 压缩率=75.0%, input_tokens=3200, source=actual
[总结-计费] Token 统计已更新: in=3200, out=300, source=actual
[总结] 完成: 总结了 50 条消息, output=300t, input=3200t, source=actual
```

---

### WARNING 日志（降级情况）

#### 场景 1: 新会话无数据

```log
⚠️ [上下文显示-降级] 会话 user_456_new 无真实Token数据，使用估算值。
可能原因：1) 新会话尚未请求LLM  2) 数据库未迁移
[上下文显示-降级] 估算total_tokens=399
⚠️ [上下文显示-使用估算] session=user_456_new, total_source=estimated, summary_source=estimated, 
显示值可能不准确（不包含工具定义约4k tokens）
```

#### 场景 2: API 未返回 Token 数据

```log
⚠️ [Token统计降级] 无法从API获取Token用量，使用估算值（将用于计费，可能存在偏差）。
模型=custom_model, usage_metadata=None, response_metadata 可用字段=['model_name']
[Token统计] 输入Token估算: 1200 字符 → 480 tokens
[Token统计] 输出Token估算: 300 字符 → 120 tokens
[Agent] Token 统计已更新: in=480, out=120, model=custom_model, source=estimated
[上下文显示] 已更新会话 Token: session=user_123_default, input_tokens=480, source=estimated
```

#### 场景 3: 总结时 API 未返回

```log
⚠️ [总结-Token降级] 无法从API获取Token用量，使用估算值（将用于上下文显示）
[总结] 完成: 5条消息, 1200t → 300t, 压缩率=75.0%, input_tokens=1200, source=estimated
[总结] 完成: 总结了 50 条消息, output=300t, input=1200t, source=estimated
```

---

## 六、图片 Token 问题解决

### 为什么图片问题自动解决？

**之前（估算方式）**:
```python
# views_api.py 中的 estimate_tokens()
elif block.get('type') == 'image_url':
    total += 85  # ⚠️ 固定 85 tokens，实际 85-765 tokens
```

**现在（LLM 真实返回）**:
```python
# LLM API 返回的 input_tokens 已经包含图片的真实消耗
response.usage_metadata.input_tokens = 4648
# 其中可能包含：
#   - 文本: 399 tokens
#   - 工具定义: 4000 tokens
#   - 图片（2张）: 249 tokens（每张实际可能是 85/170/765）
```

**结论**: ✅ 使用 LLM 真实返回值后，图片 Token 数自动准确！

---

## 七、数据库迁移

### 执行迁移

```bash
# 生成迁移文件
python manage.py makemigrations agent_service

# 预览 SQL
python manage.py sqlmigrate agent_service <migration_number>

# 执行迁移
python manage.py migrate agent_service
```

### 迁移内容

```sql
ALTER TABLE agent_service_agentsession ADD COLUMN summary_input_tokens INTEGER DEFAULT 0;
ALTER TABLE agent_service_agentsession ADD COLUMN summary_tokens_source VARCHAR(20) DEFAULT 'estimated';
ALTER TABLE agent_service_agentsession ADD COLUMN last_input_tokens INTEGER DEFAULT 0;
ALTER TABLE agent_service_agentsession ADD COLUMN last_input_tokens_source VARCHAR(20) DEFAULT 'estimated';
ALTER TABLE agent_service_agentsession ADD COLUMN last_input_tokens_updated_at TIMESTAMP NULL;
```

### 兼容性说明

**向后兼容**: ✅ 完全兼容
- 新字段都有默认值（0, 'estimated', NULL）
- 旧会话首次请求时会自动填充数据
- 降级机制确保无数据时使用估算

---

## 八、前端集成（无需修改）

### API 请求（不变）

```javascript
const response = await fetch(`/api/agent/context-usage/?session_id=${sessionId}`);
```

### API 响应（新增字段）

```json
{
    "session_id": "user_123_default",
    "context_window": 128000,
    "target_max_tokens": 76800,
    "trigger_tokens": 38400,
    "summary_tokens": 300,
    "recent_tokens": 1448,
    "remaining_tokens": 75052,
    "total_tokens": 4648,
    "has_summary": true,
    "tokens_source": "actual",             // ← 新增
    "summary_tokens_source": "actual"      // ← 新增
}
```

### 前端渲染（不变）

```javascript
renderContextUsageBar(data) {
    // ... 现有逻辑不变 ...
    const summaryPercent = (summary_tokens / total) * 100;
    const recentPercent = (recent_tokens / total) * 100;
    const remainingPercent = (remaining_tokens / total) * 100;
    
    // 可选：根据 tokens_source 显示标识
    if (data.tokens_source === 'estimated') {
        container.title += ' (预估值)';
    }
}
```

---

## 九、测试场景

### 场景 1: 新会话第一次请求

**预期**:
1. Agent 请求 LLM
2. 获取 `response.usage_metadata.input_tokens = 4648`
3. 保存到 `session.last_input_tokens = 4648`, `source = 'actual'`
4. 前端显示: `total=4648, recent=4648, remaining=72152`
5. 日志: ✅ DEBUG 无 WARNING

---

### 场景 2: 有总结的会话

**预期**:
1. 总结时保存 `summary_input_tokens = 3200`, `source = 'actual'`
2. 新请求后 `last_input_tokens = 4648`, `source = 'actual'`
3. 计算 `recent_tokens = 4648 - 3200 = 1448`
4. 前端显示: `summary=300, recent=1448, total=4648`
5. 日志: ✅ DEBUG 无 WARNING

---

### 场景 3: API 未返回 Token 数据（降级）

**预期**:
1. LLM 返回但无 `usage_metadata`
2. 使用估算: `input_tokens = 480` (from char count)
3. 保存 `last_input_tokens = 480`, `source = 'estimated'`
4. 前端显示: `total=480` (不准确，缺少工具定义)
5. 日志: ⚠️ WARNING 提示降级

---

### 场景 4: 旧会话（未迁移数据）

**预期**:
1. `session.last_input_tokens = 0` (默认值)
2. 触发降级逻辑，使用估算
3. 前端显示: 估算值（不准确）
4. 日志: ⚠️ WARNING 提示"数据库未迁移"
5. 用户发送新消息后，自动填充真实值

---

## 十、优势总结

### 精确度提升

| 项目 | 之前（估算） | 现在（真实） | 提升 |
|------|-------------|------------|------|
| 文本 Token | ±20% 误差 | 精确 | ⭐⭐⭐⭐⭐ |
| 工具定义 | ❌ 不包含（~4k） | ✅ 包含 | ⭐⭐⭐⭐⭐ |
| 图片 Token | 固定 85 | 实际 85-765 | ⭐⭐⭐⭐⭐ |
| 特殊 Token | ❌ 不计算 | ✅ 包含 | ⭐⭐⭐⭐⭐ |

### 可见性提升

| 日志级别 | 场景 | 信息 |
|---------|------|------|
| DEBUG | 每次请求 | `in=4648, source=actual` |
| DEBUG | 读取数据 | `total=4648, summary_input=3200` |
| DEBUG | 计算结果 | `recent_tokens=1448` |
| WARNING | 降级 | `无真实Token数据，使用估算值` |
| WARNING | 使用估算 | `可能原因：新会话/未迁移` |

---

## 十一、后续优化建议

### 短期（可选）

1. **前端标识数据来源**: 显示 "估算" 或 "精确" 标签
2. **监控降级频率**: 统计使用估算的比例
3. **历史数据补齐**: 为旧会话触发一次 dummy 请求填充数据

### 长期（研究）

1. **缓存 Token 数据**: 减少数据库读写
2. **实时更新**: WebSocket 推送 Token 变化
3. **多模型对比**: 显示不同模型的 Token 消耗差异

---

## 十二、文件修改清单

| 文件 | 修改内容 | 行数 |
|------|---------|------|
| `agent_service/models.py` | 添加 5 个新字段 + 1 个新方法 | ~50 |
| `agent_service/agent_graph.py` | 保存 last_input_tokens | ~20 |
| `agent_service/context_summarizer.py` | 保存 summary_input_tokens + tokens_source | ~50 |
| `agent_service/consumers.py` | 传递新参数给 save_summary | ~10 |
| `agent_service/views_api.py` | 重写 get_context_usage 逻辑 | ~120 |

**总计**: ~250 行代码变更

---

## 十三、验证清单

- [ ] 数据库迁移成功
- [ ] 新会话首次请求显示真实 Token
- [ ] 有总结的会话计算 recent_tokens 正确
- [ ] API 未返回时降级处理正常
- [ ] 日志输出符合预期（DEBUG/WARNING）
- [ ] 前端条形图显示正常
- [ ] 切换模型后 Token 数据更新
- [ ] 图片 Token 精确计算

---

**文档版本**: v1.0  
**更新日期**: 2026-02-18  
**维护者**: AI Assistant
