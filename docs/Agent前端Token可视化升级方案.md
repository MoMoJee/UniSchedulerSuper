# Agent 前端 Token 可视化升级方案

> 创建时间：2026-05-23  
> 范围：上下文构建详情弹窗、AI 设置 - Token 统计、请求级用量聚合接口、静态文件版本号。  
> 本文档仅描述升级方案，本轮不改业务代码。

---

## 0. TODO

1. **调整上下文构建详情中的 token 统计位置**
   - 目标组件是上下文构建详情界面里的 `viz-section-token-stats`。
   - 不是右侧 Agent 标题旁的 `contextUsageBarContainer` 独立窄条。
   - 将 token 统计从独立折叠 section 移到详情页顶部元信息行。
   - 在原先“模型 + 时间 + 消息数量 + 工具数量”这一行内加入百分比堆积图。

2. **取消系统提示词默认展开**
   - 当前 `_renderVizUiMode()` 渲染消息 section 时使用 `i === 0`，导致第一条系统提示词默认展开。
   - 改为默认全部消息 section 收起，或只展开用户最近消息/错误诊断类内容。
   - 本需求明确要求取消“打开任意请求详情就默认展开第一条系统提示词”的机制。

3. **重构 AI 设置 - Token 统计界面**
   - 当前 `agent-config.js` 存在旧版 `updateTokenStatsUI(stats)` 与新版 `updateTokenStatsUI(data)` 同名函数覆盖问题。
   - 新界面要基于三类 token：`input_cache_miss_tokens`、`input_cache_hit_tokens`、`output_tokens`。
   - 使用饼图或百分比堆积图展示各模型 token 用量、费用和请求明细元数据。
   - 配套后端需要补充 `AgentUsageRecord` 聚合数据，不能只依赖当前 `request_record_count/last_request_record` 摘要。

---

## 1. 已阅读的规范与代码锚点

### 1.1 前端规范

| 文档 | 本次约束 |
|---|---|
| `docs/前端开发规范/index.md` | 修改静态文件后必须更新 `home.html` 中版本号；无构建工具，原生 JS 直接加载 |
| `docs/前端开发规范/JS模块规范.md` | 维持现有全局实例模式；`agent-chat.js` 和 `agent-config.js` 内新增方法使用 camelCase，内部方法用 `_` 前缀 |
| `docs/前端开发规范/模板与CDN规范.md` | 不引入 `document.write`；若新增静态资源必须带版本号；优先不新增外部依赖 |
| `docs/前端开发规范/API调用规范.md` | GET 直接 fetch；POST 携带 CSRF；失败响应要兜底处理 |

### 1.2 当前实现锚点

| 文件 | 当前逻辑 |
|---|---|
| `core/static/js/agent-chat.js` | `_renderVizUiMode()` 渲染上下文构建详情；`snapshot.token_stats` 现在被渲染成 `viz-section-token-stats` 独立 section |
| `core/static/js/agent-chat.js` | 消息 section 使用 `this._buildVizSection(title, body, `msg-${i}`, i === 0)`，导致第 0 条系统提示词默认展开 |
| `core/static/css/agent-chat.css` | 已有 `.context-viz-*` 样式；需要新增顶部元信息行和百分比堆积条样式 |
| `core/templates/home.html` | 上下文构建弹窗结构在页面底部；`agent-chat.js?v=20260522-001`、`agent-config.js?v=20260102-001` 需要更新版本号 |
| `core/static/js/agent-config.js` | `loadTokenStats()` 请求 `/api/agent/token-usage/`；存在旧版和新版 `updateTokenStatsUI()` 同名覆盖问题 |
| `core/templates/home.html` | `ai-token-stats` tab 当前是配额卡片 + 表格 + 文本提示，无法展示三类 token 和请求元数据 |
| `agent_service/context_optimizer.py` | `/api/agent/token-usage/` 当前返回 `models`、`request_record_count`、`last_request_record` 摘要 |
| `agent_service/models.py` | `AgentUsageRecord` 已记录请求级 token、单价、费用、source、call_site、diagnostics |

---

## 2. 需求一：上下文构建详情顶部 token 可视化

### 2.1 现状问题

当前 `_renderVizUiMode(container, snapshot)` 的顶部元信息是一个纯文本 `div`：

```javascript
let html = `<div style="margin-bottom:16px;font-size:12px;color:var(--text-muted);">
    <strong>模型:</strong> ...
    | <strong>时间:</strong> ...
    | <strong>消息数:</strong> ...
    | <strong>工具数:</strong> ...
</div>`;
```

随后如果存在 `snapshot.token_stats`，会生成独立折叠块：

```javascript
html += this._buildVizSection(
    '📊 Token 统计',
    `...`,
    'token-stats', false
);
```

这会让 token 统计离顶部概览太远，也让 `viz-section-token-stats` 看起来像一条普通详情 section，而不是该请求的核心摘要。

### 2.2 目标交互

打开上下文构建详情后，详情面板顶部第一行变成“请求摘要条”：

```text
模型 DeepSeek | 时间 21:30:12 | 消息 18 | 工具 23 | Token 10.5K
[ cache miss 18% ][ cache hit 76% ][ output 6% ]  命中率 80.0%  source actual
```

要求：

1. token 统计直接放在页面顶端的原“模型 + 时间 + 消息数量 + 工具数量”行。
2. 使用百分比堆积图，展示 `input_cache_miss_tokens`、`input_cache_hit_tokens`、`output_tokens`。
3. 保留工具定义、消息列表等后续 section，但不再生成独立 `viz-section-token-stats`。
4. 若老 snapshot 只有 `cache_hit_tokens/cache_miss_tokens`，前端兼容映射到新字段。
5. 若没有 token stats，顶部仍正常显示模型/时间/消息/工具，堆积图区域显示“暂无 token 统计”。

### 2.3 数据字段映射

从 `snapshot.token_stats` 读取：

| 目标字段 | 优先来源 | 兼容来源 |
|---|---|---|
| 未命中输入 | `input_cache_miss_tokens` | `cache_miss_tokens` |
| 命中输入 | `input_cache_hit_tokens` | `cache_hit_tokens` / `cached_tokens` |
| 输出 | `output_tokens` | 无 |
| 总输入 | `input_tokens` | `未命中输入 + 命中输入` |
| 命中率 | `cache_hit_ratio` | `input_cache_hit_tokens / input_tokens` |
| source | `source` | `tokens_source` |

建议新增内部 helper：

```javascript
_normalizeVizTokenStats(tokenStats) {
    const inputMiss = Number(tokenStats.input_cache_miss_tokens ?? tokenStats.cache_miss_tokens ?? 0);
    const inputHit = Number(tokenStats.input_cache_hit_tokens ?? tokenStats.cache_hit_tokens ?? tokenStats.cached_tokens ?? 0);
    const output = Number(tokenStats.output_tokens || 0);
    const input = Number(tokenStats.input_tokens || inputMiss + inputHit);
    const total = inputMiss + inputHit + output;
    const hitRatio = input > 0 ? inputHit / input : 0;
    return { inputMiss, inputHit, output, input, total, hitRatio };
}
```

### 2.4 前端实施步骤

1. 在 `agent-chat.js` 新增 `_normalizeVizTokenStats()`、`_renderVizSummaryHeader(snapshot, messages)`、`_renderPercentStack(parts)`。
2. 将 `_renderVizUiMode()` 顶部 HTML 替换为 `_renderVizSummaryHeader()`。
3. 删除或跳过原 `snapshot.token_stats` 对应的 `_buildVizSection('📊 Token 统计', ..., 'token-stats', false)`。
4. 新增 CSS 类：`.context-viz-summary-header`、`.context-viz-meta-row`、`.context-viz-token-stack`、`.context-viz-token-segment`、`.token-miss`、`.token-hit`、`.token-output`。
5. 移动端保持两行布局：第一行元信息，第二行堆积图和说明。
6. 修改 `core/templates/home.html` 中 `agent-chat.js` 和 `agent-chat.css` 版本号。

### 2.5 验收标准

1. 打开上下文构建详情，顶部直接显示 token 百分比堆积图。
2. DOM 中不再出现独立的 `viz-section-token-stats` section。
3. 老 snapshot 仍能显示 cache hit/miss/output，缺失字段不报错。
4. 右侧 Agent 标题旁的 `contextUsageBarContainer` 不受影响。

---

## 3. 需求二：取消系统提示词默认展开

### 3.1 现状问题

当前消息 section 渲染逻辑：

```javascript
html += this._buildVizSection(title, body, `msg-${i}`, i === 0);
```

第 0 条通常是系统提示词，因此每次打开任意请求详情都会默认展开系统提示词。系统提示词一般很长，导致用户进入详情后首先看到大块 prompt，而不是请求概览。

### 3.2 目标行为

1. 打开上下文构建详情时，所有消息 section 默认收起。
2. 工具定义 section 仍可按现有规则默认收起。
3. 用户可以手动点击展开任意 system/human/ai/tool 消息。
4. JSON 模式不受影响。

### 3.3 实施方案

最小改动：

```javascript
html += this._buildVizSection(title, body, `msg-${i}`, false);
```

可选增强：新增 `_shouldExpandVizMessage(msg, index, messages)`，以后按规则展开错误消息或最近用户消息。本次需求建议先保持简单：全部消息默认收起。

### 3.4 验收标准

1. 任意历史请求详情打开后，第一条系统提示词默认收起。
2. 点击 section header 后仍能展开/收起。
3. 切换 UI/JSON tab 后不会恢复旧的默认展开系统提示词行为。

---

## 4. 需求三：AI 设置 - Token 统计重构

### 4.1 现状问题

`agent-config.js` 中存在两个同名方法：

1. 旧版 `updateTokenStatsUI(stats)` 读取 `total_input_tokens/total_output_tokens/total_cost/quota/model_stats`。
2. 新版 `updateTokenStatsUI(data)` 读取 `monthly_credit/monthly_used/remaining/models`。

后者覆盖前者。虽然运行上目前使用新版，但代码会误导后续维护，并且 UI 仍是表格为主，无法表达三类 token、cache hit 成本、请求级元数据。

### 4.2 目标信息架构

AI 设置 - Token 统计 tab 拆成四个区域：

| 区域 | 内容 | 数据来源 |
|---|---|---|
| 月度配额摘要 | monthly credit、used、remaining、使用率 | `/api/agent/token-usage/` |
| 全模型 token 分布 | 按模型展示 input miss / input hit / output 百分比堆积图 | `models[model_id]` |
| 成本拆分 | 每个模型的 miss/hit/output cost breakdown 和单价 | `models[model_id].cost_breakdown` + 后端新增 prices 聚合 |
| 请求元数据统计 | call_site、source、provider/style、cache hit ratio、最近请求、请求数量 | `AgentUsageRecord` 聚合接口 |

### 4.3 后端配套接口

当前 `/api/agent/token-usage/` 已返回：

```json
{
  "models": {...},
  "request_record_count": 12,
  "last_request_record": {...}
}
```

这不足以支撑“全部元数据统计”。建议新增只读接口：

```text
GET /api/agent/token-usage/records/summary/?month=YYYY-MM
```

返回：

```json
{
  "success": true,
  "month": "2026-05",
  "record_count": 120,
  "by_call_site": {
    "main_agent": {"count": 80, "cost_total": 1.2, "input_cache_hit_tokens": 100000},
    "summarizer": {"count": 40, "cost_total": 0.2}
  },
  "by_model": {
    "system_deepseek_flash": {
      "record_count": 70,
      "input_cache_miss_tokens": 20000,
      "input_cache_hit_tokens": 80000,
      "output_tokens": 12000,
      "cost_input_cache_miss": 0.02,
      "cost_input_cache_hit": 0.0016,
      "cost_output": 0.024,
      "cost_total": 0.0456,
      "avg_cache_hit_ratio": 0.8,
      "source_counts": {"actual": 68, "estimated": 2},
      "style_counts": {"deepseek": 70}
    }
  },
  "recent_records": [
    {
      "record_id": "...",
      "created_at": "...",
      "model_id": "system_deepseek_flash",
      "call_site": "main_agent",
      "source": "actual",
      "input_cache_miss_tokens": 2000,
      "input_cache_hit_tokens": 8000,
      "output_tokens": 500,
      "cost_total": 0.00316,
      "cache_hit_ratio": 0.8
    }
  ]
}
```

实现位置建议：

| 文件 | 变更 |
|---|---|
| `agent_service/views_config_api.py` | 新增 `get_token_usage_records_summary()` |
| `agent_service/urls.py` | 新增 `token-usage/records/summary/` 路由 |
| `agent_service/context_optimizer.py` | 可新增 `get_token_usage_record_summary(user, month=None)` helper |
| `agent_service/models.py` | 如查询性能不足，再补索引；当前已有 user/month/model_id/call_site/created_at 索引 |

### 4.4 前端实现方案

1. 清理 `agent-config.js` 中旧版 `updateTokenStatsUI(stats)` 和 `updateModelStatsTable(modelStats)`，避免同名覆盖。
2. 保留 `loadTokenStats()`，但拆为两个请求：
   - `/api/agent/token-usage/` 获取月度累计。
   - `/api/agent/token-usage/records/summary/` 获取请求级聚合。
3. 新增 `renderTokenStatsDashboard(monthlyData, recordSummary)`。
4. 新增 helper：
   - `_normalizeModelTokenStats(models, recordSummary)`
   - `_renderTokenStackBar(parts, options)`
   - `_renderModelTokenCards(models)`
   - `_renderCostBreakdown(model)`
   - `_renderUsageMetadataSummary(recordSummary)`
   - `_renderRecentUsageRecords(records)`
5. `home.html` 中重构 `ai-token-stats` tab 的 DOM，保留现有 ID 或提供兼容 fallback，避免 `loadTokenStats()` 早期空指针。
6. `agent-config.js`、`home.html`、可能新增 CSS 所在静态文件版本号必须同步更新。

### 4.5 可视化设计

建议优先使用原生 HTML/CSS 百分比堆积图，不新增图表库：

```html
<div class="token-stack" title="miss 20%, hit 75%, output 5%">
  <div class="token-stack-segment token-miss" style="width:20%"></div>
  <div class="token-stack-segment token-hit" style="width:75%"></div>
  <div class="token-stack-segment token-output" style="width:5%"></div>
</div>
```

理由：

1. 项目无构建工具，新增 Chart.js 等库会增加 CDN/本地资源管理成本。
2. 百分比堆积图更适合比较三类 token 在同一模型内的占比。
3. 饼图可作为总成本占比的后续增强，但第一阶段不必引入。

视觉编码建议：

| 类型 | 颜色语义 |
|---|---|
| input cache miss | 暖色，表示较贵输入 |
| input cache hit | 绿色，表示缓存收益 |
| output | 蓝色，表示生成成本 |
| estimated source | 警告色 badge |
| actual source | 成功色 badge |

### 4.6 前端验收标准

1. AI 设置 - Token 统计不再是单一表格，而是摘要 + 模型卡片/行 + token 堆积图 + 成本拆分 + 元数据统计。
2. 每个模型能看到三类 token 数量、占比、成本和 cache hit ratio。
3. 能看到 `request_record_count`、按 `call_site` 聚合、按 `source` 聚合、最近请求摘要。
4. 无使用记录时展示空状态，不报 JS 错误。
5. `agent-config.js 有同名函数覆盖问题` 已清理。

---

## 5. 静态文件与版本号

涉及文件：

| 文件 | 预计变更 |
|---|---|
| `core/static/js/agent-chat.js` | 上下文详情顶部 token 堆积图、取消系统提示词默认展开 |
| `core/static/js/agent-config.js` | Token 统计 dashboard 重构、清理同名函数覆盖 |
| `core/static/css/agent-chat.css` | 上下文详情顶部摘要条和 token 堆积图样式 |
| `core/static/css/home-styles.css` 或现有设置页 CSS | AI 设置 Token 统计 dashboard 样式，如当前项目没有独立设置页 CSS，则先复用 `home.html` 现有 Bootstrap + 少量内联类 |
| `core/templates/home.html` | `ai-token-stats` DOM 重构，更新 `agent-chat.js`、`agent-config.js`、相关 CSS 的 `?v=YYYYMMDD-NNN` |

要求：

1. 修改任意静态 JS/CSS 后，必须同步更新 `home.html 版本号`。
2. 不使用 `document.write`。
3. 第一阶段不新增外部图表依赖；如未来引入 Chart.js，必须按 CDN 规范处理并记录版本。

---

## 6. 实施顺序

### Phase 1：上下文详情轻量改造

1. 修改 `_renderVizUiMode()` 顶部摘要行。
2. 新增 token stats normalize 和百分比堆积图渲染 helper。
3. 移除独立 `viz-section-token-stats` 输出。
4. 将消息 section 默认展开参数从 `i === 0` 改为 `false`。
5. 补 CSS 和版本号。

### Phase 2：后端请求级聚合接口

1. 新增 `get_token_usage_record_summary()` helper。
2. 新增 `/api/agent/token-usage/records/summary/`。
3. 聚合 `AgentUsageRecord` 的 model、call_site、source、style、cost、token 和 recent records。
4. 用空数据、单模型、多模型、estimated source 场景验证。

### Phase 3：AI 设置 Token 统计重构

1. 清理 `agent-config.js` 旧版 `updateTokenStatsUI()` 和 `updateModelStatsTable()`。
2. 重构 `ai-token-stats` tab DOM。
3. 接入月度累计与请求聚合接口。
4. 实现模型 token 堆积图、成本拆分、元数据聚合、最近请求列表。
5. 补空状态、错误状态、加载状态。

### Phase 4：验证与文档收口

1. 校验前端无 console error。
2. 使用 Playwright 或浏览器手动检查上下文详情和 AI 设置页。
3. 验证移动端宽度下文本不溢出。
4. 运行 Django check，确认新增接口无问题。
5. 更新 changelog 和前端规范，如新增通用 token-stack 样式则补到样式规范。

---

## 7. 验证清单

### 7.1 文档与静态检查

```powershell
$doc = '.\docs\Agent前端Token可视化升级方案.md'
$content = Get-Content $doc -Raw -Encoding UTF8
$fence = ([char]96).ToString() * 3
$fences = ([regex]::Matches($content, [regex]::Escape($fence))).Count
if (($fences % 2) -ne 0) { throw "unclosed code fence count=$fences" }
```

### 7.2 上下文构建详情

1. 有 `token_stats` 的 snapshot 顶部显示百分比堆积图。
2. 没有 `token_stats` 的 snapshot 显示空状态。
3. 系统提示词默认收起。
4. JSON tab 可正常显示原始 snapshot。
5. 右侧标题窄条 `contextUsageBarContainer` 仍能打开详情。

### 7.3 AI 设置 - Token 统计

1. 空数据时显示空状态。
2. 单模型数据时显示三类 token 堆积图和 cost breakdown。
3. 多模型数据时每个模型独立显示堆积图，并显示总请求数。
4. `actual/estimated/legacy` source 有聚合展示。
5. 最近请求列表不显示敏感内容，仅显示模型、调用点、source、token、成本、时间。

---

## 8. 注意事项

1. 不要把本需求误改成右侧 Agent 标题旁的上下文窄条。
2. `viz-section-token-stats` 的职责要被顶部摘要条取代，而不是简单换样式。
3. `AgentUsageRecord.diagnostics` 可能包含 provider profile 摘要，前端第一阶段不要直接完整展示 diagnostics。
4. `request_record_count/last_request_record` 只是摘要，不足以支撑完整统计，必须新增聚合接口或扩展后端返回。
5. 静态文件修改后必须更新 `home.html 版本号`，否则浏览器缓存会导致验证结果不可信。

---

## 9. 2026-05-24 补充：上下文请求历史父子调用树

### 9.1 问题

一次用户请求可能触发多轮 `Agent -> Tool -> Agent` 循环。旧版 `last_llm_request_snapshot` 只保留最后一次 LLM 调用，导致左侧“请求历史”看起来只有一条记录，顶部 token 也只反映最后一次调用。

### 9.2 目标

1. 左侧历史仍以“一次用户消息到 Agent 结束”为父级调用。
2. 父级右侧内容继续展示当前最终完整上下文，但顶部 token 统计必须聚合所有子调用。
3. 父级包含多轮工具调用时，左侧以文件树形式展示每一轮 LLM 子调用。
4. 点击子调用时，右侧 UI 展示该轮真实上下文和该轮真实 token。
5. JSON 模式与 UI 模式同步：父级 JSON 展示完整父快照和 `child_snapshots`，子级 JSON 展示该子调用快照。

### 9.3 实施要点

1. 后端用最近一条 `HumanMessage` 的 state 索引作为 `parent_message_index`。
2. 同一 `parent_message_index` 下每次 LLM 调用追加到 `child_snapshots`。
3. 父级 `token_stats` 由 `child_snapshots[*].token_stats` 求和，字段仍使用 `input_cache_miss_tokens`、`input_cache_hit_tokens`、`output_tokens`。
4. 前端 `_loadContextSnapshots()` 渲染父子树，`_selectSnapshot(index, childIndex)` 同时支持父级和子级选择。
5. `_renderContextVizDetail()` 通过 `_getSelectedContextSnapshot()` 同步 UI/JSON 两种模式。
