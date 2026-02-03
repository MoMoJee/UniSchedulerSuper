# Quick Action API 测试示例

本目录包含 Quick Action API 的测试脚本和使用示例。

## 文件说明

### 1. `example_quick_action_api.py`
完整的 API 测试示例，包含所有功能的详细演示：
- ✅ 异步模式创建任务
- ✅ 同步模式创建任务  
- ✅ 查询任务状态
- ✅ 长轮询查询
- ✅ 历史任务列表
- ✅ 取消任务
- ✅ 多场景测试

**使用方法：**
```bash
python api_examples/example_quick_action_api.py
```

### 2. `simple_quick_action_test.py`
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

## API 端点

所有端点都需要 Token 认证：`Authorization: Token <your_token>`

### POST `/api/agent/quick-action/`
创建快速操作任务

**请求体：**
```json
{
  "text": "明天下午3点开会",
  "sync": false,    // 可选，是否同步执行（默认 false）
  "timeout": 30     // 可选，同步模式超时时间（秒）
}
```

**响应（异步模式）：**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "status_url": "/api/agent/quick-action/550e8400.../",
  "created_at": "2026-02-04T10:00:00"
}
```

**响应（同步模式）：**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "success",
  "result_type": "action_completed",
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

### 场景1：创建日程
```python
payload = {"text": "明天下午3点开会，讨论项目进度", "sync": True}
```

### 场景2：修改日程
```python
payload = {"text": "2月8日的会议改到晚上8点", "sync": True}
```

### 场景3：完成待办
```python
payload = {"text": "完成代码评审", "sync": True}
```

### 场景4：创建重复日程
```python
payload = {"text": "从下周一开始，每周一上午10点例会", "sync": True}
```

### 场景5：查询日程
```python
payload = {"text": "查看本周的所有会议", "sync": True}
```

## 注意事项

1. **同步 vs 异步模式**
   - 同步模式：等待执行完成后返回结果，适合需要立即反馈的场景
   - 异步模式：立即返回任务ID，适合长耗时操作或批量操作

2. **长轮询**
   - 异步模式下，使用 `?wait=true` 可以避免轮询，最多等待30秒
   - 超过30秒仍未完成，会返回当前状态，需要继续轮询

3. **Token 消耗**
   - 每次快速操作都会消耗 Token，按用户配置的模型计费
   - 在响应中可以查看 Token 消耗详情

4. **请求限制**
   - 输入文本最多1000字符
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
