# WebSocket 通信规范

> 描述 UniSchedulerSuper Agent Chat WebSocket 的连接、消息协议和错误处理规范。

---

## 1. 连接规范

### 1.1 连接 URL

```
ws://host/ws/agent/?session_id=<sessionId>&active_tools=<tool1,tool2,...>
```

参数说明：

| 参数 | 必填 | 说明 |
|------|------|------|
| `session_id` | 否 | 会话 ID，不传则后端创建新会话 |
| `active_tools` | 否 | 启用的工具组（逗号分隔），如 `planner,memory` |

### 1.2 认证

WebSocket 连接使用 Django Session Cookie 认证（与页面 HTTP 会话共享）。  
外部客户端（无 Cookie）需使用 Token 认证，参见后端 `agent_service/consumers.py`。

### 1.3 连接建立（JS 代码）

```javascript
connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    let wsUrl = `${protocol}//${window.location.host}/ws/agent/?session_id=${this.sessionId}`;
    wsUrl += `&active_tools=${encodeURIComponent(this.activeTools.join(','))}`;

    this.socket = new WebSocket(wsUrl);
    this.socket.onopen    = () => this.onOpen();
    this.socket.onmessage = (event) => this.onMessage(event);
    this.socket.onclose   = (event) => this.onClose(event);
    this.socket.onerror   = (error)  => this.onError(error);
}
```

---

## 2. 消息协议

### 2.1 客户端 → 服务端

```json
// 发送消息
{"type": "message", "content": "帮我创建一个明天上午9点的会议"}

// 心跳
{"type": "ping"}

// 停止生成
{"type": "stop"}

// 检查状态
{"type": "check_status"}
```

发送方式：
```javascript
sendMessage(content) {
    if (this.socket?.readyState === WebSocket.OPEN) {
        this.socket.send(JSON.stringify({ type: 'message', content }));
    }
}
```

### 2.2 服务端 → 客户端

| type | 说明 | 关键字段 |
|------|------|---------|
| `connected` | 连接成功 | `session_id` |
| `stream_start` | 开始流式输出 | — |
| `stream_chunk` | 流式文本片段 | `content: string` |
| `stream_end` | 流式输出结束 | `content`（完整文本）, `finished: true` |
| `tool_call` | 工具调用开始 | `name`, `args` |
| `tool_result` | 工具返回结果 | `name`, `result` |
| `error` | 错误 | `message` |
| `pong` | 心跳回应 | — |
| `stopped` | Agent 已停止生成 | — |

---

## 3. 重连机制

`AgentChat` 实现自动重连，参数：

```javascript
this.maxReconnectAttempts = 5;   // 最大重连次数
this.reconnectDelay = 2000;       // 重连间隔（毫秒）
```

重连逻辑：
```javascript
socket.onclose = (event) => {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
        this.reconnectAttempts++;
        this.updateStatus('reconnecting', `重连中... (${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
        setTimeout(() => this.connect(), this.reconnectDelay);
    } else {
        this.updateStatus('disconnected', '连接已断开');
    }
};
```

**规则**：
- 非主动关闭（如网络中断）时自动重连。
- 主动断开（切换会话、页面卸载）时不重连。
- 每次重连成功后，`reconnectAttempts` 重置为 0。

---

## 4. 消息处理规范

### 4.1 统一 switch 分发

`onMessage` 中使用 `switch (data.type)` 统一分发消息：

```javascript
onMessage(event) {
    const data = JSON.parse(event.data);
    switch (data.type) {
        case 'connected':
            this.sessionId = data.session_id;
            this.isConnected = true;
            break;
        case 'stream_start':
            this.isStreamingActive = true;
            this.streamingContent = '';
            this.appendStreamContainer();
            break;
        case 'stream_chunk':
            this.streamingContent += data.content;
            this.updateStreamContainer(data.content);
            break;
        case 'stream_end':
            this.isStreamingActive = false;
            this.finalizeStreamContainer(data.content);
            break;
        case 'tool_call':
            this.renderToolCall(data.name, data.args);
            break;
        case 'tool_result':
            this.renderToolResult(data.name, data.result);
            break;
        case 'error':
            this.renderError(data.message);
            break;
        case 'pong':
            break;
        case 'stopped':
            this.isProcessing = false;
            break;
    }
}
```

### 4.2 流式渲染

流式文本（`stream_chunk`）采用增量追加方式渲染，避免整体重渲染：

```javascript
// stream_start → 创建空消息容器
// stream_chunk → 追加文本内容到容器
// stream_end   → 用服务端返回的完整文本替换（保证最终一致性）
```

---

## 5. 会话管理

### 5.1 会话 ID 持久化

会话 ID 存储在 `localStorage['agent_session_id']`，页面刷新后自动恢复：

```javascript
// 保存
localStorage.setItem('agent_session_id', sessionId);

// 读取
const savedId = localStorage.getItem('agent_session_id');
```

### 5.2 切换会话

切换会话流程：
1. `socket.close()` — 关闭当前 WS 连接（不触发自动重连）
2. 更新 `this.sessionId`
3. 更新 `localStorage['agent_session_id']`
4. `this.connect()` — 建立新连接

---

## 6. 状态管理

`AgentChat` 维护的关键状态字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `isConnected` | boolean | WebSocket 是否已连接 |
| `isProcessing` | boolean | Agent 是否正在处理消息 |
| `isStreamingActive` | boolean | 是否正在接收流式输出 |
| `streamingContent` | string | 已接收的流式文本 |
| `reconnectAttempts` | number | 当前重连次数 |
| `sessionId` | string | 当前会话 ID |
| `activeTools` | string[] | 已启用的工具组 key 列表 |
