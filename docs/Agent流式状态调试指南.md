# Agent 流式状态调试指南

## 🐛 问题排查步骤

### 步骤 1: 打开浏览器控制台
1. 打开主页面（有 Agent 聊天框的页面）
2. 按 `F12` 打开开发者工具
3. 切换到 `Console` 标签页

### 步骤 2: 发送消息触发流式回复
1. 在 Agent 输入框中输入一个问题（例如："请详细介绍一下你的功能"）
2. 点击发送
3. **立即查看控制台日志**，应该看到：
   ```
   💾 保存流式状态: {key: "agent_streaming_1_...", isActive: true, contentLength: 0, sessionId: "..."}
   ```

### 步骤 3: 在流式回复过程中刷新
1. 当看到 Agent 开始输出内容时（不要等完成）
2. **立即按 F5 刷新页面**
3. 页面重新加载后，查看控制台日志

### 预期的日志输出

#### ✅ 正常情况（成功保存和恢复）：

**保存阶段（刷新前）：**
```
💾 保存流式状态: {
  key: "agent_streaming_1_user_1_xxx",
  isActive: true,
  contentLength: 0,
  sessionId: "user_1_xxx"
}
💾 保存流式状态: {
  key: "agent_streaming_1_user_1_xxx",
  isActive: true,
  contentLength: 15,
  sessionId: "user_1_xxx"
}
💾 保存流式状态: {
  key: "agent_streaming_1_user_1_xxx",
  isActive: true,
  contentLength: 32,
  sessionId: "user_1_xxx"
}
...（每收到一个 chunk 就保存一次）
```

**恢复阶段（刷新后）：**
```
🔍 检查流式状态: {
  key: "agent_streaming_1_user_1_xxx",
  hasState: true,
  userId: 1,
  sessionId: "user_1_xxx"
}
📋 localStorage 中的流式状态键: [
  {key: "agent_streaming_1_user_1_xxx", length: 250}
]
📦 读取到状态: {
  isActive: true,
  contentLength: 32,
  timestamp: "2026-01-19 ...",
  sessionId: "user_1_xxx"
}
🔄 开始恢复流式状态: {contentLength: 32, hasContent: true}
✅ 流式消息 DOM 元素已创建
✅ 流式状态恢复完成: {
  isStreamingActive: true,
  contentLength: 32,
  isProcessing: true
}
```

#### ❌ 异常情况（未保存）：

```
🔍 检查流式状态: {
  key: "agent_streaming_1_user_1_xxx",
  hasState: false,        // ← 这里是 false
  userId: 1,
  sessionId: "user_1_xxx"
}
ℹ️ 无需恢复流式状态
```

---

## 🔧 使用调试工具

### 方式 1: 直接在浏览器中访问调试页面
在浏览器中打开：
```
http://localhost:8000/static/test-streaming-state.html
```

### 方式 2: 在控制台中手动检查

#### 2.1 查看所有流式状态键
```javascript
// 复制粘贴到控制台执行
for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key.startsWith('agent_streaming_')) {
        const value = JSON.parse(localStorage.getItem(key));
        console.log('键:', key);
        console.log('值:', value);
    }
}
```

#### 2.2 手动保存测试状态
```javascript
// 复制粘贴到控制台执行
const testState = {
    isActive: true,
    content: '测试内容',
    timestamp: Date.now(),
    sessionId: 'user_1_test'
};
const testKey = 'agent_streaming_1_user_1_test';
localStorage.setItem(testKey, JSON.stringify(testState));
console.log('✅ 测试状态已保存:', testKey);

// 然后刷新页面看是否能恢复
```

#### 2.3 监控 localStorage 变化
```javascript
// 复制粘贴到控制台执行
const originalSetItem = localStorage.setItem;
localStorage.setItem = function(key, value) {
    if (key.startsWith('agent_streaming_')) {
        console.log('🔵 localStorage.setItem:', key, value.substring(0, 100));
    }
    originalSetItem.apply(this, arguments);
};
console.log('✅ localStorage 监控已启动');
```

---

## 🎯 常见问题排查

### 问题 1: "ℹ️ 无需恢复流式状态"
**原因**: localStorage 中没有保存状态

**检查点**:
1. 确认 `startStreamMessage()` 被调用了吗？
   - 搜索控制台日志中的 `💾 保存流式状态`
   - 如果没有，说明 `stream_start` 或 `stream_chunk` 事件没有触发

2. 确认 `sessionId` 和 `userId` 是否正确？
   - 在控制台执行：
     ```javascript
     console.log('当前用户:', agentChat.userId);
     console.log('当前会话:', agentChat.sessionId);
     ```

3. 确认 localStorage 是否可用？
   - 在控制台执行：
     ```javascript
     try {
         localStorage.setItem('test', 'test');
         localStorage.removeItem('test');
         console.log('✅ localStorage 可用');
     } catch (e) {
         console.error('❌ localStorage 不可用:', e);
     }
     ```

### 问题 2: 保存了但没有恢复
**原因**: 状态被认为无效

**检查点**:
1. 状态是否过期？（超过 5 分钟）
2. 会话 ID 是否匹配？
3. `isActive` 是否为 `true`？

**解决方法**:
```javascript
// 在控制台执行，查看详细信息
const key = `agent_streaming_${agentChat.userId}_${agentChat.sessionId}`;
const state = JSON.parse(localStorage.getItem(key));
console.log('状态详情:', {
    存在: !!state,
    激活: state?.isActive,
    内容长度: state?.content?.length,
    时间: new Date(state?.timestamp).toLocaleString(),
    年龄: ((Date.now() - state?.timestamp) / 1000).toFixed(1) + '秒',
    会话ID匹配: state?.sessionId === agentChat.sessionId
});
```

### 问题 3: WebSocket 连接问题
**原因**: 后端没有发送流式事件

**检查点**:
1. 查看 Network 标签页中的 WebSocket 连接
2. 检查是否收到 `stream_start` 和 `stream_chunk` 消息

**解决方法**:
```javascript
// 在控制台执行，监控 WebSocket 消息
const originalOnMessage = agentChat.socket.onmessage;
agentChat.socket.onmessage = function(event) {
    const data = JSON.parse(event.data);
    if (data.type === 'stream_start' || data.type === 'stream_chunk' || data.type === 'stream_end') {
        console.log('🔵 WebSocket 流式消息:', data.type, data.content?.substring(0, 50));
    }
    originalOnMessage.call(this, event);
};
console.log('✅ WebSocket 监控已启动');
```

---

## 📊 完整的调试流程

1. **准备阶段**
   ```javascript
   // 打开主页面，在控制台执行以下代码启动监控
   console.log('调试信息:', {
       userId: agentChat.userId,
       sessionId: agentChat.sessionId,
       isConnected: agentChat.isConnected
   });
   ```

2. **触发流式回复**
   - 发送消息
   - **立即查看控制台**，寻找 `💾 保存流式状态`

3. **刷新页面**
   - 在流式回复进行时按 F5
   - **立即查看控制台**，寻找 `🔍 检查流式状态`

4. **分析结果**
   - 如果看到 `✅ 流式状态恢复完成` → 成功！
   - 如果看到 `ℹ️ 无需恢复流式状态` → 参考上面的问题排查

---

## 🆘 如果还是不行

### 最后的排查手段

在 `agent-chat.js` 中临时添加更多日志（在 `handleMessage` 方法中）：

```javascript
case 'stream_start':
    console.log('🟢 收到 stream_start 事件');
    this.hideTyping();
    this.startStreamMessage();
    console.log('🟢 startStreamMessage 已调用，isStreamingActive:', this.isStreamingActive);
    break;

case 'stream_chunk':
case 'token':
    console.log('🟢 收到 stream_chunk 事件, content:', data.content?.substring(0, 20));
    if (!document.getElementById('streamingMessage')) {
        console.log('🟡 streamingMessage 不存在，重新创建');
        this.hideTyping();
        this.startStreamMessage();
    }
    this.appendToStreamMessage(data.content);
    console.log('🟢 appendToStreamMessage 已调用，累计长度:', this.streamingContent.length);
    break;
```

然后重新测试，查看每个步骤的日志输出。

---

**更新时间**: 2026-01-19  
**版本**: v1.1
