# Quick Action API 测试示例

本目录包含 Quick Action API 的测试脚本和使用示例。

## 文件说明

### 1. `example_quick_action_api.py`
完整的 API 测试示例，包含所有功能的详细演示：
- ✅ 异步模式创建任务（文字输入）
- ✅ 同步模式创建任务（文字输入）
- ✅ 查询任务状态
- ✅ 长轮询查询
- ✅ 历史任务列表
- ✅ 取消任务
- ✅ **音频异步模式**（`--audio` 参数指定音频文件）
- ✅ **音频同步模式**
- ✅ **同时传入文字+音频的报错测试**
- ✅ 多场景测试

**使用方法：**
```bash
# 纯文字模式
python api_examples/example_quick_action_api.py

# 指定真实音频文件
python api_examples/example_quick_action_api.py --audio /path/to/audio.wav
```

### 2. `example_parser_api.py`
语音转文字（Speech-to-Text）独立接口的测试示例：
- ✅ 基础合成音频转文字测试（无依赖，自动生成 WAV）
- ✅ 真实音频文件转文字（`--audio` 参数）
- ✅ 无 Token 免认证访问验证
- ✅ 超时音频（>60s）拒绝测试
- ✅ 不支持格式拒绝测试
- ✅ 缺少字段报错测试

**使用方法：**
```bash
# 仅合成音频测试（无需真实麦克风）
python api_examples/example_parser_api.py

# 使用真实音频
python api_examples/example_parser_api.py --audio /path/to/audio.wav

# 仅测试真实音频（跳过合成音频测试）
python api_examples/example_parser_api.py --audio /path/to/audio.wav --only-real
```

### 3. `simple_quick_action_test.py`
简化版快速测试脚本，适合快速验证功能：
- 4个基本测试用例
- 自动统计成功率
- 代码简洁易读

**使用方法：**
```bash
python api_examples/simple_quick_action_test.py
```

## 前置条件

### 1. 启动 Django 服务
```bash
python manage.py runserver
```

### 2. 执行数据库迁移
```bash
python manage.py makemigrations agent_service --name add_quick_action_task
python manage.py migrate
```

### 3. 配置用户账号
在测试脚本中修改以下配置：
```python
USERNAME = "your_username"  # 你的用户名
PASSWORD = "your_password"  # 你的密码
```

### 4. 确保用户已配置 LLM
用户需要在系统中配置可用的 LLM 模型（系统模型或自定义模型）。

### 5. 配置语音服务（使用音频输入时）
编辑 `config/api_keys.json`，在 `speech_services` 下填写百度 VOP 配置：
```json
"speech_services": {
    "baidu": {
        "enabled": true,
        "auth_type": "bearer",
        "bearer_token": "bce-v3/ALTAK-...",
        "api_url": "https://vop.baidu.com/pro_api",
        "dev_pid": 80001
    },
    "faster_whisper": { "enabled": true, "local": true, "model_size": "tiny" }
}
```
> ⚠️ 修改 `api_keys.json` 后必须重启 Django，配置仅在进程启动时读取一次。

## API 端点

所有端点都需要 Token 认证：`Authorization: Token <your_token>`  
（语音转文字独立接口 `POST /api/agent/speech-to-text/` 除外，无需认证）

### POST `/api/agent/quick-action/`
创建快速操作任务

**输入方式（二选一，不可同时提供）：**

| 方式 | Content-Type | 字段 |
|------|-------------|------|
| 文字 | `application/json` | `text`（字符串，最多1000字符） |
| 音频 | `multipart/form-data` | `audio`（音频文件，≤60s，≤15MB） |

**文字请求体（JSON）：**
```json
{
  "text": "明天下午3点开会",
  "sync": false,    
  "timeout": 30     
}
```

**音频请求体（multipart/form-data）：**
```
audio=<二进制音频文件>
sync=true
timeout=30
```
支持格式：`wav`、`mp3`、`ogg`、`flac`、`webm`、`aac`、`m4a`、`amr`

**响应（异步模式）：**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "status_url": "/api/agent/quick-action/550e8400.../",
  "input_type": "text",
  "created_at": "2026-02-04T10:00:00"
}
```

**响应（同步模式）：**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "success",
  "result_type": "action_completed",
  "input_type": "audio",
  "result": {
    "message": "✅ 已创建新日程：2月5日 15:00-16:00「会议」",
    "tool_calls": [...]
  },
  "execution_time_ms": 1234,
  "tokens": {
    "input": 100,
    "output": 50,
    "cost": 0.001,
    "model": "gpt-4"
  }
}
```

**错误响应：**

| 状态码 | `error_code` | 说明 |
|-------|-------------|------|
| 400 | `AMBIGUOUS_INPUT` | 同时提供了 `text` 和 `audio`，无法确定输入方式 |
| 400 | `EMPTY_INPUT` | `text` 和 `audio` 均未提供 |
| 400 | `TEXT_TOO_LONG` | 文字超过1000字符 |
| 400 | `UNSUPPORTED_AUDIO_FORMAT` | 音频格式不支持 |
| 400 | `AUDIO_TOO_LARGE` | 音频文件超过15MB |
| 422 | `SPEECH_RECOGNITION_FAILED` | 语音识别失败（Baidu 和本地模型均未返回结果） |
| 422 | `EMPTY_SPEECH_RESULT` | 语音识别成功但结果为空（无法识别到有效文字） |

### POST `/api/agent/speech-to-text/`
独立语音转文字接口，**无需认证（对外公开）**

**请求：** `multipart/form-data`，字段名 `audio`

```bash
curl -X POST http://127.0.0.1:8000/api/agent/speech-to-text/ \
  -F "audio=@/path/to/voice.wav"
```

**成功响应：**
```json
{
  "success": true,
  "text": "明天下午三点开会",
  "duration_seconds": 3.2,
  "provider": "baidu",
  "filename": "voice.wav"
}
```

**错误响应：**

| 状态码 | `error_code` | 说明 |
|-------|-------------|------|
| 400 | `MISSING_AUDIO` | 请求中没有 `audio` 字段 |
| 400 | `UNSUPPORTED_FORMAT` | 音频格式不支持 |
| 400 | `FILE_TOO_LARGE` | 文件超过15MB |
| 400 | `DURATION_TOO_LONG` | 音频超过60秒 |
| 422 | `RECOGNITION_FAILED` | 识别失败 |
| 422 | `EMPTY_RESULT` | 识别成功但无文字内容 |

### GET `/api/agent/quick-action/<task_id>/`
查询任务状态

**查询参数：**
- `wait=true`: 启用长轮询（最多等待30秒）

**响应：**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "success",
  "result_type": "action_completed",
  "result": {
    "message": "✅ 已创建新日程...",
    "tool_calls": [...]
  },
  "input_text": "明天下午3点开会",
  "execution_time_ms": 1234,
  "created_at": "2026-02-04T10:00:00",
  "completed_at": "2026-02-04T10:00:01"
}
```

### GET `/api/agent/quick-action/list/`
获取历史任务列表

**查询参数：**
- `limit`: 返回数量（默认20，最大100）
- `offset`: 偏移量
- `status`: 筛选状态（pending/processing/success/failed/timeout）
- `days`: 获取最近N天（默认7天）

**响应：**
```json
{
  "count": 100,
  "limit": 20,
  "offset": 0,
  "tasks": [
    {
      "task_id": "550e8400...",
      "status": "success",
      "result_type": "action_completed",
      "input_text": "明天下午3点开会",
      "created_at": "2026-02-04T10:00:00",
      "execution_time_ms": 1234,
      "result_preview": "✅ 已创建新日程..."
    }
  ]
}
```

### DELETE `/api/agent/quick-action/<task_id>/cancel/`
取消待执行任务

只能取消状态为 `pending` 的任务。

**响应：**
```json
{
  "message": "任务已取消"
}
```

## 结果类型

Quick Action 执行后会返回以下三种结果类型之一：

### 1. `action_completed` ✅ 操作成功
操作已成功执行，无需用户进一步操作。

**示例：**
```
✅ 已将「团队会议」的时间从 2月8日 14:00-15:00 修改为 20:00-21:00
✅ 已创建新日程：2月10日 09:00-10:00「项目评审」
✅ 已完成待办：提交月度报告
```

### 2. `need_clarification` ⚠️ 需要补充信息
找到多个匹配项，需要用户明确指定。

**示例：**
```
⚠️ 找到 3 个2月8日的会议，无法确定要修改哪一个：
1. 09:00-10:00「晨会」
2. 14:00-15:00「团队会议」  
3. 16:00-17:00「项目评审」
请在下次请求中明确指定会议名称，如'将团队会议改到晚上8点'
```

### 3. `error` ❌ 操作失败
操作无法执行。

**示例：**
```
❌ 未找到2月8日的任何会议
❌ 操作失败：日程已被删除
❌ 缺少必要信息：未指定日程时间
```

## 常见使用场景

### 场景1：创建日程（文字）
```python
payload = {"text": "明天下午3点开会，讨论项目进度", "sync": True}
```

### 场景2：修改日程（文字）
```python
payload = {"text": "2月8日的会议改到晚上8点", "sync": True}
```

### 场景3：完成待办（文字）
```python
payload = {"text": "完成代码评审", "sync": True}
```

### 场景4：创建重复日程（文字）
```python
payload = {"text": "从下周一开始，每周一上午10点例会", "sync": True}
```

### 场景5：查询日程（文字）
```python
payload = {"text": "查看本周的所有会议", "sync": True}
```

### 场景6：音频输入（multipart/form-data）
```python
import requests

with open("voice.wav", "rb") as f:
    response = requests.post(
        "http://127.0.0.1:8000/api/agent/quick-action/",
        headers={"Authorization": f"Token {token}"},
        data={"sync": "true"},
        files={"audio": ("voice.wav", f, "audio/wav")}
    )
print(response.json())
```

### 场景7：仅语音转文字（无需登录）
```python
import requests

with open("voice.wav", "rb") as f:
    response = requests.post(
        "http://127.0.0.1:8000/api/agent/speech-to-text/",
        files={"audio": ("voice.wav", f, "audio/wav")}
    )
print(response.json()["text"])
```

## 注意事项

1. **文字 vs 音频输入（二选一）**
   - 一次请求只能携带 `text` **或** `audio`，两者同时提供会返回 `400 AMBIGUOUS_INPUT`
   - 两者都不提供会返回 `400 EMPTY_INPUT`

2. **音频格式与限制**
   - 支持格式：`wav / mp3 / ogg / flac / webm / aac / m4a / amr`
   - 最大时长：60 秒
   - 最大文件大小：15 MB
   - 百度 VOP 内部仅接受 PCM/WAV 16000Hz 单声道；其他格式由服务端自动转换（需安装 `pydub` + `ffmpeg`）

3. **语音识别降级链**
   - 优先调用百度 VOP `pro_api`（Bearer Token 认证）
   - 若百度不可用，自动降级到本地 `faster-whisper tiny` 模型
   - 本地模型需预先安装：`pip install faster-whisper`

4. **同步 vs 异步模式**
   - 同步模式：等待执行完成后返回结果，适合需要立即反馈的场景
   - 异步模式：立即返回任务ID，适合长耗时操作或批量操作

5. **长轮询**
   - 异步模式下，使用 `?wait=true` 可以避免频繁轮询，最多等待30秒
   - 超过30秒仍未完成，会返回当前状态，需要继续轮询

6. **Token 消耗**
   - 每次快速操作都会消耗 LLM Token，按用户配置的模型计费
   - 在响应中可以查看 Token 消耗详情（`tokens` 字段）

7. **请求限制**
   - 文字输入最多1000字符
   - Agent 最多执行10轮迭代（防止无限循环）

## 故障排查

### 问题1：401 Unauthorized
**原因：** Token 无效或过期  
**解决：** 重新登录获取新的 Token

### 问题2：404 Not Found
**原因：** URL 路径错误或任务不存在  
**解决：** 检查 URL 路径和任务 ID

### 问题3：500 Internal Server Error
**原因：** 服务器内部错误  
**解决：** 检查服务器日志，确认数据库迁移已执行

### 问题4：任务一直处于 pending 状态
**原因：** 后台线程执行失败  
**解决：** 检查服务器日志，确认用户已配置 LLM

### 问题5：400 AMBIGUOUS_INPUT
**原因：** 请求中同时携带了 `text` 字段和 `audio` 文件  
**解决：** 二选一，不要同时提供

### 问题6：422 SPEECH_RECOGNITION_FAILED
**原因：** 百度 VOP 和本地 faster-whisper 均无法识别  
**可能原因：**
- `config/api_keys.json` 中 `speech_services.baidu.enabled` 为 `false`
- Bearer Token 无效或无 `pro_api` 权限
- 本地未安装 `faster-whisper`（`pip install faster-whisper`）
- 修改 `api_keys.json` 后未重启 Django 服务（配置仅在启动时读取一次）

### 问题7：百度语音返回 3302 无权限
**原因：** 使用了 `oauth2` 认证类型，对应的 App 没有 `pro_api` 权限  
**解决：** 将 `config/api_keys.json` 中 `auth_type` 改为 `bearer`，并填写有效的 BCE Bearer Token

## 开发者指南

### 添加新的测试用例
在 `example_quick_action_api.py` 中的 `example_multiple_scenarios()` 函数添加新的测试文本：

```python
test_cases = [
    "你的新测试用例",
    # ...
]
```

### 调试模式
在脚本中添加更详细的输出：

```python
response = requests.post(...)
print("Request:", json.dumps(payload, indent=2, ensure_ascii=False))
print("Response:", json.dumps(response.json(), indent=2, ensure_ascii=False))
```

## 参考文档

- [快速创建功能构建计划](../docs/快速创建功能构建计划.md)
- [Agent Integration Plan](../docs/Agent_Integration_Plan.md)
- [API Token 使用指南](../docs/API_TOKEN_使用指南.md)
