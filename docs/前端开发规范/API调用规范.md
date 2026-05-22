# API 调用规范

> 描述前端 JavaScript 调用后端 API 的统一规范。

---

## 1. 基本请求格式

### 1.1 GET 请求

```javascript
async loadTodos() {
    try {
        const params = new URLSearchParams({ status: 'active' });
        const response = await fetch(`/api/todos/?${params}`);
        if (response.ok) {
            const data = await response.json();
            this.todos = data.todos || [];
        } else {
            console.error('加载待办失败:', response.status);
        }
    } catch (error) {
        console.error('网络错误:', error);
    }
}
```

### 1.2 POST / PUT / PATCH / DELETE 请求

```javascript
async createTodo(todoData) {
    try {
        const response = await fetch('/api/todos/create/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCSRFToken()    // POST 等写操作必须携带
            },
            body: JSON.stringify(todoData)
        });

        if (response.ok) {
            const result = await response.json();
            if (result.todo) {
                this.todos.push(result.todo);
                this.renderTodos();
            }
        } else {
            const err = await response.json().catch(() => ({}));
            console.error('创建失败:', err.message || response.status);
        }
    } catch (error) {
        console.error('网络错误:', error);
    }
}
```

---

## 2. CSRF Token 获取

所有 POST / PUT / PATCH / DELETE 请求必须在 `headers` 中携带 `X-CSRFToken`。

### 2.1 全局变量方式（推荐）

在模板中注入（优先读取）：
```html
<script>window.CSRF_TOKEN = '{{ csrf_token }}';</script>
```

在 JS 中通过辅助方法读取：
```javascript
getCSRFToken() {
    if (window.CSRF_TOKEN) {
        return window.CSRF_TOKEN;
    }
    // 降级：从 cookie 读取
    const name = 'csrftoken';
    const value = document.cookie.split(';')
        .find(c => c.trim().startsWith(name + '='));
    return value ? value.split('=')[1] : '';
}
```

### 2.2 使用规则

- `window.CSRF_TOKEN` 是首选来源（由模板注入）。
- 若 `window.CSRF_TOKEN` 不存在，降级从 `document.cookie` 读取 `csrftoken`。
- **Token 认证（外部客户端）**不需要 CSRF Token，改用：
  ```javascript
  headers: { 'Authorization': `Token ${userToken}` }
  ```

---

## 3. 响应处理规范

### 3.1 标准处理流程

```javascript
const response = await fetch(url, options);

if (response.ok) {
    // HTTP 2xx → 业务逻辑
    const data = await response.json();
    ...
} else {
    // HTTP 4xx/5xx → 错误处理
    const err = await response.json().catch(() => ({}));
    const msg = err.message || err.error || `请求失败 (${response.status})`;
    console.error(msg);
    // 可视情况弹出用户提示
}
```

### 3.2 后端 JSON 响应结构（参见 API 接口规范）

成功时：
```json
{"status": "success", "data": {...}}
```
失败时：
```json
{"status": "error", "message": "错误描述"}
```

### 3.3 超时处理

对实时性要求高的请求，使用 `AbortController` 设置超时：

```javascript
const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), 10000); // 10s 超时

try {
    const response = await fetch(url, {
        signal: controller.signal,
        headers: { ... }
    });
    ...
} catch (error) {
    if (error.name === 'AbortError') {
        console.warn('请求超时');
    } else {
        console.error('网络错误:', error);
    }
} finally {
    clearTimeout(timer);
}
```

---

## 4. URL 规范

### 4.1 前端使用的 URL 前缀

| 前缀 | 说明 |
|------|------|
| `/api/` | 标准 REST API |
| `/get_calendar/` | 日历数据接口（历史遗留） |
| `/events/` | 事件操作接口（历史遗留） |
| `/api/agent/` | Agent 服务 API |
| `/api/auth/` | 认证相关 |

### 4.2 URL 硬编码

URL 目前直接在各模块 JS 中硬编码（无路由配置文件）。新增接口时，在对应模块的方法中直接写相对路径。

---

## 5. 防重复请求

写操作（创建/更新/删除）使用提交标志防止用户重复点击：

```javascript
class EventManager {
    constructor() {
        this._isSubmitting = false;
    }

    async submitCreateEvent(eventData) {
        if (this._isSubmitting) return;
        this._isSubmitting = true;
        try {
            ...
        } finally {
            this._isSubmitting = false;
        }
    }
}
```

读操作（列表加载）使用 `_inFlightFetchKey` 防并发重复请求（参见 [JS 模块规范](./JS模块规范.md) 第 3.2 节）。

---

## 6. 乐观更新

列表类操作推荐使用乐观更新（先更新本地数组，再发请求），提升响应速度：

```javascript
async createTodo(todoData) {
    const response = await fetch('/api/todos/create/', { ... });
    if (response.ok) {
        const result = await response.json();
        if (result.todo) {
            // 乐观：直接 push 服务端返回的完整对象（含 id），无需重新请求列表
            this.todos.push(result.todo);
            this.renderTodos();
        }
    }
}
```

---

## 7. 文件上传

文件上传使用 `FormData`，不设置 `Content-Type`（让浏览器自动设置 boundary）：

```javascript
const formData = new FormData();
formData.append('file', fileInput.files[0]);

const response = await fetch('/api/files/upload/', {
    method: 'POST',
    headers: { 'X-CSRFToken': this.getCSRFToken() },
    // 注意：不设置 Content-Type，FormData 自动处理
    body: formData
});
```
