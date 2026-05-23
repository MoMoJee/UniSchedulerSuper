# Agent 用量计费与 Provider Style 统一升级方案

> 创建时间：2026-05-23  
> 范围：系统内置 LLM 配置、Provider Style 解析、缓存命中计费、请求级用量明细、调试日志。  
> 本文档仅描述升级方案，本轮不改业务代码。

> 用户确认：本次只处理 system 模型；`cost_per_1k_input_cache_hit` 必须显式配置；请求级明细使用新增 ORM 表；手动 `reset_token_stats(current)` 保留 `monthly_used`。

---

## 0. TODO

1. **统一模型 Provider Style 配置**
   - 先升级 `config/api_keys.example.json`，再迁移 `config/api_keys.json`。
   - 用一个集中式 `provider_styles` 定义取代模型内多个并列 style 字段。
  - 先提供 `deepseek`、`kimi` 两家 style；其他 system provider 走 `openai-compatible` 扩展位。

2. **把缓存命中输入纳入计费**
   - 将计费 token 拆成三类：`input_cache_miss_tokens`、`output_tokens`、`input_cache_hit_tokens`。
   - 成本按三类单价分别计算，不再把所有 input tokens 都按未命中输入价格计费。
   - 与 Provider Style 的 usage 抽取规则和模型 pricing 配置联动。

3. **结构化保存每次请求用量明细**
   - 在用户维度新增或扩展结构，保存每次 LLM 请求的三类 token、模型信息、单价快照、费用、来源和必要调试元信息。
   - 写入时机与当前 `update_token_usage()` 一致。
   - 本阶段只做后端存储，不做前端可视化。

4. **补充日志与诊断**
   - Provider Style 解析、usage 抽取、计费拆分、明细落库均增加 DEBUG/INFO/WARNING/ERROR。
   - 日志不得输出完整 API Key、Token、Bearer、请求正文全文。

---

## 1. 现状与问题定位

### 1.1 当前关键链路

| 领域 | 当前文件 | 作用 |
|---|---|---|
| 模型配置读取 | `config/api_keys_manager.py` | 读取 `api_keys.json`、系统模型、成本配置、月抵用金 |
| Provider 适配 | `agent_service/provider_profiles.py` | 从模型字段推断 `provider_style/cache_usage_style/thinking_param_style/...` |
| LLM 构建 | `agent_service/agent_graph.py` | `_build_chat_llm()` 根据 thinking style 注入 provider 参数 |
| usage 抽取 | `agent_service/usage_extractor.py` | DeepSeek/Kimi 的 input/output/cache/reasoning 归一化 |
| 计费累计 | `agent_service/context_optimizer.py` | `update_token_usage()` 写 `UserData.agent_token_usage` |
| 上下文快照 | `agent_service/models.py` | `AgentSession.token_snapshots` 与 `last_llm_request_snapshot` |

### 1.2 已确认问题

1. `api_keys.example.json` 中模型配置存在多个并列字段：`provider_style`、`cache_usage_style`、`thinking_param_style`、`message_format_style`、`image_block_style`、`tool_name_style`。这些字段语义都属于 provider style，却分散在模型配置上。
2. `context_optimizer.get_system_models()` 会把系统模型转成前端/内部视图，但当前没有透传 `provider_style/cache_usage_style/message_format_style/image_block_style/tool_name_style`，导致 `agent_node()` 构造 `ProviderProfile` 时经常只能靠 `provider='system' + model_name` 推断。
3. `get_user_llm()` 对系统模型使用 `APIKeyManager.get_system_model_config()` 的完整配置，而 `agent_node()` 的 `provider_profile` 使用 `get_current_model_config()` 的裁剪配置，两条视图可能不一致。
4. 当前 `update_token_usage(user, input_tokens, output_tokens, model_id)` 不知道缓存命中输入，只能按全部 input 计费。
5. `usage_extractor.py` 已能抽取 `cache_hit_tokens/cache_miss_tokens`，但这些字段只进入 `AgentSession` 快照和调试快照，不进入费用计算。
6. `core/models.py` 的 `DATA_SCHEMA.agent_token_usage` 仍描述旧结构，运行时代码实际写入的是 `current_month/monthly_credit/monthly_used/models/history` 等新版结构。

---

## 2. 需求一：统一 Provider Style 与模型配置

### 2.1 目标结构

新增集中式 `provider_styles`，模型只引用一个 style 名称：

```json
{
  "provider_styles": {
    "deepseek": {
      "label": "DeepSeek OpenAI-compatible",
      "request": {
        "chat_api": "openai-compatible",
        "message_format": "openai-chat",
        "image_block": "none",
        "tool_name": "openai-compatible"
      },
      "thinking": {
        "mode_param": "deepseek",
        "enabled_extra_body": {"thinking": {"type": "enabled"}},
        "disabled_extra_body": {"thinking": {"type": "disabled"}},
        "enabled_extra_kwargs": {"reasoning_effort": "high"}
      },
      "usage": {
        "input_tokens": ["usage.input_tokens", "usage.prompt_tokens"],
        "output_tokens": ["usage.output_tokens", "usage.completion_tokens"],
        "cache_hit_input_tokens": [
          "usage.prompt_cache_hit_tokens",
          "usage.prompt_tokens_details.cached_tokens"
        ],
        "cache_miss_input_tokens": ["usage.prompt_cache_miss_tokens"],
        "reasoning_tokens": ["usage.completion_tokens_details.reasoning_tokens"]
      },
      "billing": {
        "input_cache_miss_price_key": "cost_per_1k_input_cache_miss",
        "input_cache_hit_price_key": "cost_per_1k_input_cache_hit",
        "output_price_key": "cost_per_1k_output"
      }
    }
  }
}
```

模型配置变为：

```json
{
  "system_deepseek_flash": {
    "name": "DeepSeek V4 Flash（系统提供）",
    "provider": "deepseek",
    "style": "deepseek",
    "api_key": "sk-xxx",
    "base_url": "https://api.deepseek.com",
    "model_name": "deepseek-v4-flash",
    "context_window": 1048576,
    "supports_tools": true,
    "supports_vision": false,
    "supports_multimodal": false,
    "supports_thinking": true,
    "thinking_mode": "optional",
    "cost_per_1k_input_cache_miss": 0.001,
    "cost_per_1k_input_cache_hit": 0.0001,
    "cost_per_1k_output": 0.002,
    "cost_currency": "CNY",
    "readonly": true,
    "enabled": true
  }
}
```

### 2.2 Kimi style 初版

```json
{
  "provider_styles": {
    "kimi": {
      "label": "Moonshot/Kimi OpenAI-compatible",
      "request": {
        "chat_api": "openai-compatible",
        "message_format": "openai-chat",
        "image_block": "openai-image-url",
        "tool_name": "openai-compatible"
      },
      "thinking": {
        "mode_param": "kimi-k2",
        "enabled_extra_body": {"thinking": {"type": "enabled", "keep": "all"}},
        "disabled_extra_body": {"thinking": {"type": "disabled", "keep": "all"}},
        "enabled_defaults": {"temperature": 1.0, "min_max_tokens": 16000}
      },
      "usage": {
        "input_tokens": ["usage.input_tokens", "usage.prompt_tokens"],
        "output_tokens": ["usage.output_tokens", "usage.completion_tokens"],
        "cache_hit_input_tokens": ["usage.cached_tokens"],
        "cache_miss_input_tokens": ["derived.input_minus_cache_hit"],
        "reasoning_tokens": []
      },
      "billing": {
        "input_cache_miss_price_key": "cost_per_1k_input_cache_miss",
        "input_cache_hit_price_key": "cost_per_1k_input_cache_hit",
        "output_price_key": "cost_per_1k_output"
      }
    }
  }
}
```

### 2.3 OpenAI-compatible 扩展位

保留 `openai-compatible` 作为默认扩展 style：

```json
{
  "openai-compatible": {
    "request": {
      "chat_api": "openai-compatible",
      "message_format": "openai-chat",
      "image_block": "openai-image-url",
      "tool_name": "openai-compatible"
    },
    "thinking": {"mode_param": "none"},
    "usage": {
      "input_tokens": ["usage.input_tokens", "usage.prompt_tokens"],
      "output_tokens": ["usage.output_tokens", "usage.completion_tokens"],
      "cache_hit_input_tokens": [],
      "cache_miss_input_tokens": ["derived.input_when_no_cache"],
      "reasoning_tokens": []
    }
  }
}
```

### 2.4 实施步骤

1. **先改 example**：在 `config/api_keys.example.json` 添加 `provider_styles`，并把系统模型的多个 style 字段替换为 `style`。
2. **保留兼容字段读取**：短期内 `build_provider_profile()` 同时支持新字段 `style` 和旧字段 `provider_style/cache_usage_style/...`，优先级为 `model.style` → 旧散字段 → provider/model_name 推断。注意！当解析降级的时候，必须添加 WARNING 日志
3. **新增 style resolver**：在 `config/api_keys_manager.py` 或 `agent_service/provider_profiles.py` 新增 `get_provider_style(style_name)` / `resolve_provider_style(model_config)`，统一返回完整 style dict。
4. **扩展 `ProviderProfile`**：新增 `style_name`、`style_config`、`usage_paths`、`billing_keys`；保留现有属性作为展开后的便捷字段。
5. **修复系统模型视图裁剪**：`context_optimizer.get_system_models()` 必须透传 `style`、`provider_style` 兼容字段、`supports_*`、pricing 三段价格，或直接返回非敏感完整配置副本。
6. **改 LLM 构建**：`_build_chat_llm()` 不再判断 `thinking_param_style == ...`，而是读取 `ProviderProfile.thinking` 生成 `extra_body/extra_kwargs`。
7. **改 materializer / tool mapper 输入**：继续使用展开后的 `image_block_style/tool_name_style`，但这些值来自集中 style。
8. **迁移实际配置**：在 example 校验通过后，再对 `config/api_keys.json` 做结构迁移，保留密钥值，不输出、不提交敏感内容。

### 2.5 验收检查

1. `python -m json.tool config/api_keys.example.json` 通过。
2. DeepSeek 模型解析出 `style_name=deepseek`、`cache_source=deepseek`、`thinking.mode_param=deepseek`。
3. Kimi 模型解析出 `style_name=kimi`、`cache_source=kimi`、`thinking.mode_param=kimi-k2`。
4. 未配置 style 的扩展模型回退到 `openai-compatible`，并打 WARNING 日志。
5. `last_llm_request_snapshot.provider_profile` 展示新的 `style_name` 和展开字段。

---

## 3. 需求二：缓存命中输入参与计费

### 3.1 统一 usage 内部结构

将 `extract_llm_usage()` 输出升级为三类计费 token：

```python
{
    "input_tokens": 10000,
    "output_tokens": 500,
    "input_cache_hit_tokens": 8500,
    "input_cache_miss_tokens": 1500,
    "billable_input_cache_hit_tokens": 8500,
    "billable_input_cache_miss_tokens": 1500,
    "billable_output_tokens": 500,
    "reasoning_tokens": 120,
    "total_tokens": 10500,
    "cache_hit_ratio": 0.85,
    "source": "actual",
    "provider_style": "deepseek",
    "raw_usage": {...}
}
```

兼容别名：短期保留 `cached_tokens/cache_hit_tokens/cache_miss_tokens`，但内部计费只读 `input_cache_hit_tokens/input_cache_miss_tokens/output_tokens`。！但是 在解析到兼容名的时候必须使用 WARNING 日志警告

### 3.2 三段价格配置

模型 pricing 使用三段字段：

| 字段 | 含义 | 兼容默认 |
|---|---|---|
| `cost_per_1k_input_cache_miss` | 未命中输入单价 | 回退旧 `cost_per_1k_input` |
| `cost_per_1k_input_cache_hit` | 缓存命中输入单价 | system 模型必须显式配置，缺失时报错 |
| `cost_per_1k_output` | 输出单价 | 沿用旧字段 |

旧字段 `cost_per_1k_input` 暂保留为兼容别名，读取时映射为 `input_cache_miss`。！但是 在解析到旧字段的时候必须使用 WARNING 日志警告

### 3.3 计费函数改造

新增结构化成本函数：

```python
def calculate_llm_cost(usage_info: dict, cost_config: dict) -> dict:
    miss_tokens = usage_info.get("input_cache_miss_tokens", 0)
    hit_tokens = usage_info.get("input_cache_hit_tokens", 0)
    output_tokens = usage_info.get("output_tokens", 0)
    miss_price = cost_config.get("cost_per_1k_input_cache_miss", cost_config.get("cost_per_1k_input", 0))
    hit_price = cost_config["cost_per_1k_input_cache_hit"]
    output_price = cost_config.get("cost_per_1k_output", 0)
    return {
        "input_cache_miss_cost": miss_tokens * miss_price / 1000,
        "input_cache_hit_cost": hit_tokens * hit_price / 1000,
        "output_cost": output_tokens * output_price / 1000,
        "total_cost": ...
    }
```

### 3.4 `update_token_usage()` 新签名

建议从：

```python
update_token_usage(user, input_tokens, output_tokens, model_id, cost=0)
```

升级为：

```python
update_token_usage(
    user,
    usage_info: dict,
    model_id: str,
    request_meta: dict | None = None,
    cost_override: dict | None = None,
)
```

短期保留旧签名包装，避免一次性改坏总结器等调用方。但是触发兼容的时候必须使用 WARNING 日志强调问题，方便之后排查

### 3.5 累计结构升级

`agent_token_usage.models[model_id]` 从：

```json
{"input_tokens": 12000, "output_tokens": 8000, "cost": 2.35}
```

升级为：

```json
{
  "input_tokens": 12000,
  "input_cache_miss_tokens": 9000,
  "input_cache_hit_tokens": 3000,
  "output_tokens": 8000,
  "cost": 2.12,
  "cost_breakdown": {
    "input_cache_miss_cost": 1.8,
    "input_cache_hit_cost": 0.02,
    "output_cost": 0.3
  },
  "currency": "CNY"
}
```

### 3.6 实施步骤

1. 扩展 `get_model_cost_config()`，返回三段价格和 `cost_currency`。
2. 新增 `calculate_llm_cost()`，旧 `calculate_cost()` 调用新函数并只返回 `total_cost`。
3. 改 `extract_llm_usage()`：按 resolved style 的 `usage` 路径抽取三类 token；没有 cache 字段时 `miss=input`、`hit=0`。（注意没有 cache 字段时需要WARNING警告日志）
4. 改 `agent_graph.agent_node()`：传完整 `usage_info` 给新版 `update_token_usage()`。
5. 改 `context_summarizer.py`：复用 `extract_llm_usage()`，不要保留独立 usage 抽取逻辑。
6. 修改累计结构时保留旧字段：`input_tokens` 仍代表总输入，新增字段代表拆分。
7. 更新 `/api/agent/token-usage/` 返回结构，保持前端现有字段可用；新增字段暂不展示。

### 3.7 日志要求

| 级别 | 内容 |
|---|---|
| DEBUG | usage 原始字段可用 key、style 名称、抽取后的三类 token、价格字段名 |
| INFO | 每次成功计费的总成本、模型、source、cache hit ratio |
| WARNING | 缺少 cache 字段、usage 降级估算 |
| ERROR | system 模型价格字段缺失、计费写入失败、成本配置无法解析 |

日志示例：

```python
logger.info(
    f"[Token计费] user={user.username}, model={model_id}, "
    f"miss={miss_tokens}, hit={hit_tokens}, out={output_tokens}, "
    f"cost=¥{total_cost:.6f}, source={source}, style={style_name}"
)
```

---

## 4. 需求三：请求级用量明细存储

### 4.1 存储位置

采用新增 ORM 表 `AgentUsageRecord`，`UserData.agent_token_usage` 只保留月度/模型累计统计。

原因：

1. 请求级明细天然适合按用户、时间、模型、会话分页查询，ORM 表比 UserData 大 JSON 更稳。
2. 明细可能持续增长，避免 `agent_token_usage` JSON 膨胀影响月度统计读写。
3. 后续前端可视化、审计、导出可以直接复用索引。
4. 写入时机仍保持在 `update_token_usage()` 内，与当前费用统计同步。

### 4.2 `DATA_SCHEMA` 升级

仍必须更新 `core/models.py` 中 `DATA_SCHEMA.agent_token_usage`，使其与运行时真实累计结构一致。注意 dict 默认值仍只能写 `{}`。

建议结构：

```python
"agent_token_usage": {
    "type": dict,
    "nullable": False,
    "default": {},
    "items": {
        "current_month": {"type": str, "nullable": False, "default": ""},
        "monthly_credit": {"type": float, "nullable": False, "default": 0.0},
        "monthly_used": {"type": float, "nullable": False, "default": 0.0},
        "models": {"type": dict, "nullable": False, "default": {}},
        "history": {"type": dict, "nullable": False, "default": {}},
        "last_updated": {"type": str, "nullable": True, "default": ""}
    }
}
```

### 4.3 `AgentUsageRecord` 模型结构

每次 `update_token_usage()` 成功计算费用后新增一条记录：

```python
class AgentUsageRecord(models.Model):
    record_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='agent_usage_records')
    session = models.ForeignKey(AgentSession, null=True, blank=True, on_delete=models.SET_NULL, related_name='usage_records')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    month = models.CharField(max_length=7, db_index=True)
    call_site = models.CharField(max_length=50, default='main_agent', db_index=True)
    model_id = models.CharField(max_length=100, db_index=True)
    model_name = models.CharField(max_length=200, blank=True, default='')
    provider = models.CharField(max_length=50, blank=True, default='')
    style = models.CharField(max_length=50, blank=True, default='')
    is_system_model = models.BooleanField(default=True)
    input_total_tokens = models.IntegerField(default=0)
    input_cache_miss_tokens = models.IntegerField(default=0)
    input_cache_hit_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    reasoning_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    cache_hit_ratio = models.FloatField(default=0.0)
    price_input_cache_miss_per_1k = models.FloatField(default=0.0)
    price_input_cache_hit_per_1k = models.FloatField(default=0.0)
    price_output_per_1k = models.FloatField(default=0.0)
    cost_input_cache_miss = models.FloatField(default=0.0)
    cost_input_cache_hit = models.FloatField(default=0.0)
    cost_output = models.FloatField(default=0.0)
    cost_total = models.FloatField(default=0.0)
    currency = models.CharField(max_length=10, default='CNY')
    source = models.CharField(max_length=20, default='actual')
    diagnostics = models.JSONField(default=dict, blank=True)
```

### 4.4 记录保留策略

第一阶段建议：

1. ORM 表默认完整保留，不在 `UserData` 中复制明细。
2. 为 `user/month/model_id/call_site/created_at` 添加索引，便于后续分页和聚合。
3. 如后续数据量过大，再增加后台归档任务或按月归档表；本次不裁剪。
4. `agent_token_usage.history` 继续只保存月度模型累计摘要。

### 4.5 写入时机与调用点

写入时机：`update_token_usage()` 内，在成本计算完成后创建 `AgentUsageRecord`，并更新 `agent_token_usage.models/monthly_used`。

调用点需要传入 `request_meta`：

| 调用方 | `call_site` | 可传 metadata |
|---|---|---|
| `agent_graph.agent_node()` | `main_agent` | `session_id`、`message_index`、`provider_profile`、`tool_schema_hash` |
| `context_summarizer.summarize()` | `summarizer` | `session_id`（若有）、summary range、trigger count |
| `skill_selector_node()` | `skill_selector` | 若未来计费则传 suffix/skill_count；当前未计入则先不写 |
| 会话命名器/Quick Action | 后续补齐 | 各自调用 LLM 时传入 call_site |

### 4.6 实施步骤

1. 在 `agent_service/models.py` 新增 `AgentUsageRecord`，注册 admin，并生成迁移。
2. 更新 `DATA_SCHEMA.agent_token_usage` 到新版累计结构。
3. 新增 helper：`create_usage_record(user, usage_info, model_id, cost_info, request_meta)`。
4. 在 `update_token_usage()` 中创建 ORM 明细记录，再更新 UserData 累计。
5. `/api/agent/token-usage/` 先不返回完整明细；可返回 `request_record_count` 和最近一条记录摘要用于调试。
6. 后续如要前端可视化，再新增分页接口 `/api/agent/token-usage/records/`。

### 4.7 日志要求

| 级别 | 内容 |
|---|---|
| DEBUG | record id、call_site、session_id、message_index、ORM 写入耗时 |
| INFO | 每次成功追加请求明细的模型、总费用、三类 token |
| WARNING | 缺少 request_meta、无法识别模型单价 |
| ERROR | JSON 写入失败、record 构造失败 |

---

## 5. 迁移顺序

### Phase 1：配置 example 与解析器兼容

1. 改 `config/api_keys.example.json`，新增 `provider_styles`，更新示例模型到 `style + 三段价格`。
2. 新增 style resolver，兼容旧散字段。
3. 单测或脚本验证 DeepSeek/Kimi/OpenAI-compatible 三类 profile 解析。

### Phase 2：实际配置迁移

1. 对 `config/api_keys.json` 做只改结构、不暴露密钥的迁移。
2. 对已有系统模型补 `style` 和三段价格。
3. `python -m json.tool` 校验 JSON。

### Phase 3：usage 抽取与三段计费

1. 升级 `extract_llm_usage()` 支持 style usage paths。
2. 升级成本配置读取和 `calculate_llm_cost()`。
3. 改主 Agent 和总结器调用。
4. 保留旧字段返回，确保前端当前统计页不坏。

### Phase 4：请求明细存储

1. 更新 `DATA_SCHEMA.agent_token_usage`。
2. 新增 `AgentUsageRecord` ORM 模型、admin 注册和迁移。
3. 新增 usage record builder。
4. 在 `update_token_usage()` 内创建明细记录。
5. 增加 `request_record_count/last_request_record` 调试返回。

### Phase 5：日志与验证收口

1. 增加 Provider Style、usage 抽取、计费、明细落库日志。
2. 用 mock response 覆盖 DeepSeek/Kimi cache 命中与无 cache 字段场景。
3. 跑 Django check 与相关单测。

---

## 6. 验证清单

### 6.1 配置验证

```powershell
.venv\Scripts\python.exe -m json.tool config\api_keys.example.json | Out-Null
.venv\Scripts\python.exe -m json.tool config\api_keys.json | Out-Null
```

### 6.2 Provider Style 单元验证

1. DeepSeek：开启 thinking 时生成 `extra_body.thinking.type=enabled`，关闭时为 `disabled`。
2. Kimi：开启 thinking 时包含 `thinking.keep=all`，并应用 `temperature=1.0/max_tokens>=16000`。
3. OpenAI-compatible：无 thinking 参数、无 cache 命中字段时 `input_cache_miss=input_total`。

### 6.3 Usage/计费验证

1. DeepSeek mock usage：`prompt_cache_hit_tokens=8000`、`prompt_cache_miss_tokens=2000`、`completion_tokens=500`，成本必须按三段价格计算。
2. Kimi mock usage：`prompt_tokens=10000`、`cached_tokens=7000`、`completion_tokens=500`，miss 必须派生为 3000。
3. 无 usage：触发 WARNING，`source=estimated`，cache hit=0，miss=input estimate。
4. `/api/agent/token-usage/` 旧字段仍可被当前前端读取。

### 6.4 明细验证

1. 每次主 Agent 成功 LLM 调用后，`AgentUsageRecord` 新增一条记录，存在三类 token、模型、单价、费用。
2. 总结器 LLM 调用也生成 `call_site=summarizer` 的记录。
3. `agent_token_usage.models` 保留月度累计，明细不复制到 UserData JSON。
4. 不记录 API Key、Bearer Token、完整请求消息正文。

---

## 7. 需要确认的问题

1. 已确认：`cost_per_1k_input_cache_hit` 必须显式配置；本次只处理 system 模型，不处理用户自定义模型。
2. 已确认：请求明细第一阶段直接新增 `AgentUsageRecord` ORM 表。
3. 已确认：`reset_token_stats(current)` 保留 `monthly_used`，不在本次升级中改变语义。
