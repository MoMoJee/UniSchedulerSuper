# Token 统计与图片处理日志优化

**时间**: 2025-02-18  
**目标**: 增强 Token 计费透明度与图片处理可调试性

---

## 一、优化背景

### 问题描述
Token 统计系统存在以下可见性问题：
1. **图片处理模式不透明**: 无法从日志判断使用了 Vision 模式（Base64）还是 OCR 模式
2. **Token 估算降级无感知**: 当 API 未返回实际 Token 数时，系统自动降级为估算，但日志信息不足
3. **图片 Token 成本不明确**: 多模态消息包含图片时，缺少 Token 预估信息

### 影响范围
- **成本可见性**: 用户无法准确了解实际 Token 消耗情况
- **调试困难**: 图片相关问题难以排查（Base64 vs OCR 的选择）
- **估算风险**: 使用估算值但用户不知情，可能导致成本核算偏差

---

##二、Token 统计机制分析

### 2.1 当前 Token 计算流程

```
Agent请求 → LangChain/LangGraph → LLM API
                                     ↓
                            response.usage_metadata
                                     ↓
                    ┌────────────────┴────────────────┐
                    │                                 │
              有 Token 数据                      无 Token 数据
                    │                                 │
               actual token                    ⚠️ 降级为估算
                    │                                 │
                    └────────────┬────────────────────┘
                                 ↓
                      update_token_usage()
                                 ↓
                      agent_token_usage (UserData)
```

### 2.2 Token 计算的三种方式

| 方式 | 数据来源 | 准确性 | 使用场景 |
|------|----------|--------|----------|
| **Actual** | `response.usage_metadata` | ⭐⭐⭐⭐⭐ 精确 | API 正常返回 Token 数据 |
| **Tiktoken** | tokenizer 库计算 | ⭐⭐⭐⭐ 接近 | API 未返回，但模型支持 tiktoken |
| **Estimate** | 字符数 / 2.5 | ⭐⭐ 粗略 | 其他情况的降级方案 |

### 2.3 图片处理的两种模式

#### Vision 模式（支持视觉的模型）
```
图片 → ImageParser.parse(skip_ocr=True) 
        ↓
    Base64编码 (压缩至 1024px)
        ↓
    multimodal content: [text, image_url{base64}]
        ↓
    LLM API (Vision) → 约 85-100 tokens/图
```

**特点**:
- ✅ 模型直接"看"图片，理解能力强
- ❌ Token 消耗高（每张图约 85-765 tokens，取决于 detail 参数）
- ⚠️ Base64 字符串很长（几十 KB），但不计入文本 token

#### OCR 模式（不支持视觉的模型）
```
图片 → ImageParser.parse(skip_ocr=False)
        ↓
    OCR 提取文字 (EasyOCR/Tesseract)
        ↓
    纯文本消息: [text + OCR结果]
        ↓
    LLM API (Text-only) → 按文本长度计费
```

**特点**:
- ✅ Token 消耗低（仅提取的文字长度）
- ❌ 无法理解图片内容（只能识别文字）
- ⚠️ OCR 可能失败或不准确

---

## 三、具体优化措施

### 3.1 图片解析日志优化

**文件**: `agent_service/parsers/image_parser.py`

**改进内容**:
```python
# Vision 模式日志（skip_ocr=True）
logger.debug(
    f"[图片解析-Vision模式] 文件={filename}, "
    f"原始尺寸={width}x{height}, "
    f"Base64长度={base64_len:,} 字符, 跳过OCR"
)

# OCR 模式日志（skip_ocr=False）
logger.debug(
    f"[图片解析-OCR模式] 文件={filename}, "
    f"原始尺寸={width}x{height}, "
    f"提取文字={len(ocr_text)} 字符, Base64长度={base64_len:,} 字符"
)
```

**效果**:
- ✅ 明确标识处理模式（Vision vs OCR）
- ✅ 显示 Base64 长度（判断压缩效果）
- ✅ 显示 OCR 提取的文字长度

---

### 3.2 多模态消息构建日志优化

**文件**: `agent_service/consumers.py`

**改进内容**:
```python
# 估算图片 token 数（OpenAI 视觉模型的粗略估算）
estimated_tokens_per_image = 85  # 低细节图片约 85 tokens
estimated_image_tokens = len(image_blocks) * estimated_tokens_per_image

logger.info(
    f"[多模态] 构建多模态消息: {len(image_blocks)} 张图片, "
    f"附件上下文 {len(attachments_context)} 字符, "
    f"预估图片Token≈{estimated_image_tokens} (按{estimated_tokens_per_image}token/图)"
)
```

**效果**:
- ✅ 显示图片数量
- ✅ 预估 Token 消耗（帮助用户评估成本）
- ✅ 说明估算依据（85 token/图）

**注意**: 
- 实际 Token 数取决于 `detail` 参数：
  - `low`: ~85 tokens
  - `high`: ~170-765 tokens（取决于图片尺寸分块数）
  - `auto`: 由 API 自动选择

---

### 3.3 Token 统计降级日志优化

**文件**: `agent_service/agent_graph.py`

**改进内容**:
```python
if input_tokens == 0 or output_tokens == 0:
    # 准备降级日志信息
    usage_metadata_str = str(response.usage_metadata)[:200]
    response_metadata_keys = list(response.response_metadata.keys())
    
    logger.warning(
        f"⚠️ [Token统计降级] 无法从API获取Token用量，使用估算值。"
        f"模型={current_model_id}, "
        f"usage_metadata={usage_metadata_str}, "
        f"response_metadata 可用字段={response_metadata_keys}"
    )
    
    if input_tokens == 0:
        # ... 估算逻辑 ...
        logger.debug(f"[Token统计] 输入Token估算: {total_input_chars} 字符 → {input_tokens} tokens")
    
    if output_tokens == 0:
        # ... 估算逻辑 ...
        logger.debug(f"[Token统计] 输出Token估算: {len(response_content)} 字符 → {output_tokens} tokens")
```

**效果**:
- ✅ 明确 WARNING 级别（引起用户重视）
- ✅ 显示 API 返回的元数据内容（便于调试）
- ✅ 显示估算方法的详细计算过程
- ✅ 标识当前使用的模型（不同模型可能有不同行为）

---

## 四、日志级别说明

| 级别 | 场景 | 示例 |
|------|------|------|
| **DEBUG** | 详细的处理过程，用于开发调试 | 图片尺寸、Base64长度、OCR文字长度、Token估算公式 |
| **INFO** | 正常业务流程的关键信息 | 多模态消息构建、图片数量、预估Token |
| **WARNING** | 降级或异常但不影响功能 | Token统计降级为估算、API未返回usage数据 |
| **ERROR** | 严重错误，功能受影响 | 图片解析失败、Token统计失败 |

---

## 五、使用场景示例

### 场景 1: Vision 模式发送图片
```
[图片解析-Vision模式] 文件=screenshot.png, 原始尺寸=1920x1080, Base64长度=87,654 字符, 跳过OCR
[多模态] 构建多模态消息: 2 张图片, 附件上下文 0 字符, 预估图片Token≈170 (按85token/图)
[Agent] Token 统计已更新: in=1250, out=320, model=gpt-4-vision-preview
```

**解读**:
- 使用 Vision 模式（支持图片理解）
- 发送了 2 张图片，预估消耗约 170 tokens
- API 成功返回实际 Token 数（in=1250 包含图片+文本）

---

### 场景 2: OCR 模式发送图片
```
[图片解析-OCR模式] 文件=document.jpg, 原始尺寸=2480x3508, 提取文字=523 字符, Base64长度=156,789 字符
[Agent] Token 统计已更新: in=420, out=150, model=gpt-3.5-turbo
```

**解读**:
- 使用 OCR 模式（模型不支持 Vision）
- 提取了 523 字符文字（Base64 未发送，仅用于缩略图）
- Token 消耗仅包含文字部分（约 420 tokens）

---

### 场景 3: Token 统计降级
```
⚠️ [Token统计降级] 无法从API获取Token用量，使用估算值。模型=qwen-plus, usage_metadata=None, response_metadata 可用字段=['model_name', 'system_fingerprint', 'created']
[Token统计] 输入Token估算: 2150 字符 → 860 tokens
[Token统计] 输出Token估算: 450 字符 → 180 tokens
[Agent] Token 统计已更新: in=860, out=180, model=qwen-plus
```

**解读**:
- API 未返回 `usage_metadata`（可能是模型不支持或 API 异常）
- 降级使用字符数估算（字符数 / 2.5）
- ⚠️ 提示用户核实实际计费（估算可能有偏差）

---

## 六、注意事项

### 6.1 Token 估算的局限性
- **字符数法不准确**: 中文字符占用更多 token，英文单词长度也影响 token 数
- **图片 token 变化大**: 实际消耗取决于 `detail` 参数和图片尺寸
- **建议**: 尽量确保 API 返回 `usage_metadata`，避免依赖估算

### 6.2 日志性能影响
- DEBUG 日志默认不输出到生产环境（需在 `logger.py` 中配置）
- Base64 字符串很长，日志中截断显示（仅显示长度）
- 建议在开发环境启用 DEBUG，生产环境使用 INFO/WARNING

### 6.3 成本优化建议
1. **优先使用 Text-only 模型**: 如果只需要识别图片中的文字，OCR 模式更省钱
2. **控制图片尺寸**: 超大图片会被压缩到 1024px，但编码仍消耗 CPU
3. **使用 `detail="low"`**: 对于不需要精细识别的场景，可节省 50% 以上 Token
4. **监控估算比例**: 如果 WARNING 日志频繁出现，检查 API 配置

---

## 七、相关文件清单

| 文件 | 修改内容 | 行号 |
|------|---------|------|
| `agent_service/parsers/image_parser.py` | 添加 Vision/OCR 模式 DEBUG 日志 | ~40-60 |
| `agent_service/consumers.py` | 添加图片 Token 预估日志 | ~367 |
| `agent_service/agent_graph.py` | 增强 Token 降级 WARNING 日志 | ~726-745 |

---

## 八、后续计划

### 优化方向
- [ ] 在前端 UI 显示 Token 统计详情（实际 vs 估算标识）
- [ ] 记录每次请求的 Token 计算方式（actual/tiktoken/estimate）
- [ ] 提供 Token 统计报表（按模型、按日期、按计算方式分组）
- [ ] 支持自定义图片 Token 估算参数（不同模型不同费率）

### 监控指标
- 估算降级频率（WARNING 日志数量/总请求数）
- Vision vs OCR 使用比例
- 平均每图 Token 消耗（实际值）

---

**文档版本**: v1.0  
**更新日期**: 2025-02-18  
**维护者**: AI Assistant
