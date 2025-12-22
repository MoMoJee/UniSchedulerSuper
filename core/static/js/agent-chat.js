/**
 * Agent Chat Module
 * 智能日程助手聊天功能
 * 
 * 功能包括：
 * - WebSocket 连接管理
 * - 消息发送/接收
 * - 会话历史管理
 * - 回滚功能
 * - 终止功能
 */

class AgentChat {
    constructor(userId, csrfToken) {
        // 用户信息
        this.userId = userId;
        this.csrfToken = csrfToken;
        
        // 会话状态
        this.sessionId = null;
        this.socket = null;
        this.isConnected = false;
        this.isProcessing = false;  // 是否正在处理消息
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 2000;
        
        // 会话切换时的回滚标记起点
        this.rollbackBaseIndex = 0;
        
        // DOM 元素
        this.messagesContainer = document.getElementById('agentMessages');
        this.inputField = document.getElementById('agentInput');
        this.sendBtn = document.getElementById('agentSendBtn');
        this.statusBadge = document.getElementById('agentStatusBadge');
        this.typingIndicator = document.getElementById('agentTyping');
        this.expandBtn = document.getElementById('agentExpandBtn');
        this.sessionHistoryBtn = document.getElementById('sessionHistoryBtn');
        this.sessionHistoryPanel = document.getElementById('sessionHistoryPanel');
        this.closeSessionHistoryBtn = document.getElementById('closeSessionHistoryBtn');
        this.sessionList = document.getElementById('sessionList');
        this.newSessionBtn = document.getElementById('newSessionBtn');
        this.agentChatContainer = document.getElementById('agentChatContainer');
        this.agentInputArea = document.getElementById('agentInputArea');
        
        // 消息计数（用于跟踪消息索引）
        this.messageCount = 0;
        
        // 工具名称映射
        this.toolNames = {
            'get_reminders': '查询提醒',
            'create_reminder': '创建提醒',
            'delete_reminder': '删除提醒',
            'update_reminder': '更新提醒',
            'get_events': '查询日程',
            'create_event': '创建日程',
            'update_event': '更新日程',
            'delete_event': '删除日程',
            'get_todos': '查询待办',
            'create_todo': '创建待办',
            'update_todo': '更新待办',
            'delete_todo': '删除待办',
            'save_memory': '保存记忆',
            'search_memory': '搜索记忆',
            'get_recent_memories': '获取最近记忆',
            'amap_search': '搜索地点',
            'amap_weather': '查询天气',
            'amap_route': '规划路线'
        };
        
        this.init();
    }

    /**
     * 初始化
     */
    init() {
        // 生成或恢复会话ID
        this.sessionId = this.getOrCreateSessionId();
        
        // 绑定事件
        this.bindEvents();
        
        // 连接 WebSocket
        this.connect();
        
        // 加载历史消息
        this.loadHistory().then(() => {
            // 加载完成后更新新建按钮状态
            this.updateNewSessionButton();
        });
        
        // 加载会话列表
        this.loadSessionList();
    }

    /**
     * 获取或创建会话ID
     */
    getOrCreateSessionId() {
        const storageKey = 'agent_session_id';
        let sessionId = localStorage.getItem(storageKey);
        if (!sessionId) {
            sessionId = `user_${this.userId}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
            localStorage.setItem(storageKey, sessionId);
        }
        return sessionId;
    }

    /**
     * 保存当前会话ID
     */
    saveSessionId(sessionId) {
        localStorage.setItem('agent_session_id', sessionId);
        this.sessionId = sessionId;
    }

    // ==========================================
    // 事件绑定
    // ==========================================

    /**
     * 绑定所有事件
     */
    bindEvents() {
        // 发送/终止按钮
        this.sendBtn.addEventListener('click', () => this.handleSendButtonClick());
        
        // 输入框事件
        this.inputField.addEventListener('input', () => {
            this.autoResize();
            this.updateSendButton();
        });
        
        this.inputField.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.handleSendButtonClick();
            }
        });
        
        // 快捷提示按钮（动态绑定，因为可能被重新创建）
        this.bindQuickPromptButtons();
        
        // 展开按钮 - 打开模态框
        if (this.expandBtn) {
            this.expandBtn.addEventListener('click', () => {
                const modal = document.getElementById('agentChatModal');
                if (modal) {
                    modal.style.display = 'block';
                    this.syncMessagesToModal();
                }
            });
        }
        
        // 会话历史按钮 - 切换历史面板
        if (this.sessionHistoryBtn) {
            this.sessionHistoryBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleSessionHistoryPanel();
            });
        }
        
        // 关闭历史面板按钮
        if (this.closeSessionHistoryBtn) {
            this.closeSessionHistoryBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.hideSessionHistoryPanel();
            });
        }
        
        // 新建会话按钮
        if (this.newSessionBtn) {
            this.newSessionBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.createNewSession();
            });
        }
    }

    /**
     * 绑定快捷提示按钮
     */
    bindQuickPromptButtons() {
        document.querySelectorAll('.quick-prompt-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const prompt = btn.dataset.prompt;
                this.inputField.value = prompt;
                this.updateSendButton();
                this.inputField.focus();
            });
        });
    }

    /**
     * 处理发送按钮点击
     */
    handleSendButtonClick() {
        if (this.isProcessing) {
            // 正在处理中，执行终止
            this.stopGeneration();
        } else {
            // 发送消息
            this.sendMessage();
        }
    }

    // ==========================================
    // WebSocket 连接管理
    // ==========================================

    /**
     * 连接 WebSocket
     */
    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/agent/?session_id=${this.sessionId}`;
        
        try {
            this.socket = new WebSocket(wsUrl);
            
            this.socket.onopen = () => {
                console.log('✅ Agent WebSocket 连接成功');
                this.isConnected = true;
                this.reconnectAttempts = 0;
                this.updateStatus('connected', '已连接');
                this.updateSendButton();
            };
            
            this.socket.onmessage = (event) => {
                this.handleMessage(JSON.parse(event.data));
            };
            
            this.socket.onclose = (event) => {
                console.log('❌ Agent WebSocket 连接关闭', event.code, event.reason);
                this.isConnected = false;
                this.isProcessing = false;
                this.updateStatus('disconnected', '已断开');
                this.updateSendButton();
                
                // 尝试重连
                if (this.reconnectAttempts < this.maxReconnectAttempts) {
                    this.reconnectAttempts++;
                    this.updateStatus('reconnecting', `重连中 (${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
                    setTimeout(() => this.connect(), this.reconnectDelay);
                }
            };
            
            this.socket.onerror = (error) => {
                console.error('Agent WebSocket 错误:', error);
                this.updateStatus('error', '连接错误');
            };
            
        } catch (error) {
            console.error('WebSocket 连接失败:', error);
            this.updateStatus('error', '连接失败');
        }
    }

    /**
     * 断开 WebSocket 连接
     */
    disconnect() {
        if (this.socket) {
            this.socket.close();
            this.socket = null;
        }
        this.isConnected = false;
        this.isProcessing = false;
    }

    /**
     * 重新连接（切换会话时使用）
     */
    reconnect() {
        this.disconnect();
        setTimeout(() => this.connect(), 100);
    }

    // ==========================================
    // 消息处理
    // ==========================================

    /**
     * 处理收到的 WebSocket 消息
     */
    handleMessage(data) {
        console.log('收到消息:', data);
        
        switch (data.type) {
            case 'connected':
                console.log('Agent 连接成功:', data.message);
                break;
            
            case 'processing':
                this.isProcessing = true;
                this.updateSendButton();
                this.showTyping();
                break;
            
            case 'message':
            case 'response':
                this.hideTyping();
                if (data.content) {
                    this.addMessage(data.content, 'agent', data.metadata || {});
                }
                break;
                
            case 'stream_start':
                this.hideTyping();
                this.startStreamMessage();
                break;
                
            case 'stream_chunk':
            case 'token':
                // 确保流式消息已开始
                if (!document.getElementById('streamingMessage')) {
                    this.hideTyping();
                    this.startStreamMessage();
                }
                this.appendToStreamMessage(data.content);
                break;
                
            case 'stream_end':
                this.endStreamMessage(data.metadata);
                break;
            
            case 'tool_call':
                this.showToolCall(data.name || data.tool, data.args);
                break;
                
            case 'tool_result':
                this.showToolResult(data.name || data.tool, data.result);
                break;
            
            case 'finished':
                this.hideTyping();
                this.isProcessing = false;
                this.updateSendButton();
                console.log('Agent 处理完成');
                break;
                
            case 'action_preview':
                this.showActionPreview(data.actions);
                break;
                
            case 'action_executed':
                this.showActionExecuted(data.results);
                if (data.refresh) {
                    this.refreshData(data.refresh);
                }
                break;
                
            case 'error':
                this.hideTyping();
                this.isProcessing = false;
                this.updateSendButton();
                this.addMessage(data.message || '抱歉，处理您的请求时出现错误。', 'error');
                break;
                
            case 'pong':
                // 心跳响应，忽略
                break;
                
            case 'stopped':
                // 生成已停止
                this.hideTyping();
                this.isProcessing = false;
                this.updateSendButton();
                this.showNotification('已停止生成', 'info');
                break;
                
            default:
                console.log('未知消息类型:', data.type);
        }
    }

    /**
     * 发送消息
     */
    sendMessage() {
        const message = this.inputField.value.trim();
        if (!message || !this.isConnected || this.isProcessing) return;
        
        // 清空输入
        this.inputField.value = '';
        this.autoResize();
        this.updateSendButton();
        
        // 隐藏欢迎消息
        const welcome = this.messagesContainer.querySelector('.agent-welcome');
        if (welcome) welcome.style.display = 'none';
        
        // 添加用户消息（带消息索引）
        const currentIndex = this.messageCount;
        this.addMessage(message, 'user', {}, currentIndex);
        this.messageCount += 1;
        
        // 标记为处理中
        this.isProcessing = true;
        this.updateSendButton();
        
        // 显示打字指示器
        this.showTyping();
        
        // 发送到 WebSocket
        this.socket.send(JSON.stringify({
            type: 'message',
            content: message
        }));
        
        // 更新会话最后消息预览
        this.updateSessionPreview(message);
        
        // 更新新建按钮状态
        this.updateNewSessionButton();
    }

    /**
     * 停止生成
     */
    stopGeneration() {
        if (!this.isProcessing) return;
        
        console.log('停止生成...');
        
        // 发送停止信号到后端
        if (this.socket && this.isConnected) {
            this.socket.send(JSON.stringify({
                type: 'stop'
            }));
        }
        
        // 立即更新UI状态
        this.hideTyping();
        this.isProcessing = false;
        this.updateSendButton();
        
        // 结束可能存在的流式消息
        const streamMsg = document.getElementById('streamingMessage');
        if (streamMsg) {
            streamMsg.classList.remove('streaming');
            streamMsg.id = '';
            // 添加已停止标记
            const contentDiv = streamMsg.querySelector('.message-content');
            if (contentDiv) {
                contentDiv.innerHTML += '<span class="text-muted"> [已停止]</span>';
            }
        }
    }

    // ==========================================
    // 消息渲染
    // ==========================================

    /**
     * 添加消息到界面
     */
    addMessage(content, type, metadata = {}, messageIndex = null) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `agent-message ${type}-message`;
        
        // 存储消息索引（用于回滚）
        if (messageIndex !== null) {
            messageDiv.dataset.messageIndex = messageIndex;
        }
        
        const avatar = type === 'user' ? 'user' : (type === 'error' ? 'exclamation-triangle' : 'robot');
        const avatarClass = type === 'error' ? 'error-avatar' : '';
        
        let metadataHtml = '';
        if (metadata.expert) {
            metadataHtml = `<span class="expert-badge">${metadata.expert}</span>`;
        }
        if (metadata.actions_count) {
            metadataHtml += `<span class="action-badge">${metadata.actions_count} 个操作</span>`;
        }
        
        // 用户消息添加回滚按钮（只有在回滚基准点之后的消息才显示）
        let rollbackBtn = '';
        if (type === 'user' && messageIndex !== null && messageIndex >= this.rollbackBaseIndex) {
            rollbackBtn = `
                <button class="rollback-btn" title="回到此消息前重新编辑" onclick="agentChat.showRollbackConfirm(${messageIndex}, this)">
                    <i class="fas fa-undo"></i>
                </button>
            `;
        }
        
        messageDiv.innerHTML = `
            <div class="message-avatar ${avatarClass}">
                <i class="fas fa-${avatar}"></i>
            </div>
            <div class="message-body">
                <div class="message-content">${this.formatContent(content)}</div>
                ${metadataHtml ? `<div class="message-meta">${metadataHtml}</div>` : ''}
            </div>
            ${rollbackBtn}
        `;
        
        this.messagesContainer.appendChild(messageDiv);
        this.scrollToBottom();
        
        // 更新消息计数
        if (messageIndex !== null && messageIndex >= this.messageCount) {
            this.messageCount = messageIndex + 1;
        }
    }

    /**
     * 格式化消息内容（简单 Markdown）
     */
    formatContent(content) {
        if (!content) return '';
        return content
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            .replace(/`(.*?)`/g, '<code>$1</code>')
            .replace(/\n/g, '<br>');
    }

    /**
     * 开始流式消息
     */
    startStreamMessage() {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'agent-message agent-message streaming';
        messageDiv.id = 'streamingMessage';
        
        messageDiv.innerHTML = `
            <div class="message-avatar">
                <i class="fas fa-robot"></i>
            </div>
            <div class="message-body">
                <div class="message-content"></div>
            </div>
        `;
        
        this.messagesContainer.appendChild(messageDiv);
        this.scrollToBottom();
    }

    /**
     * 追加流式消息内容
     */
    appendToStreamMessage(content) {
        const streamMsg = document.getElementById('streamingMessage');
        if (streamMsg) {
            const contentDiv = streamMsg.querySelector('.message-content');
            contentDiv.innerHTML += this.formatContent(content);
            this.scrollToBottom();
        }
    }

    /**
     * 结束流式消息
     */
    endStreamMessage(metadata = {}) {
        const streamMsg = document.getElementById('streamingMessage');
        if (streamMsg) {
            streamMsg.classList.remove('streaming');
            streamMsg.id = '';
            
            if (metadata.expert || metadata.actions_count) {
                const body = streamMsg.querySelector('.message-body');
                let metaHtml = '<div class="message-meta">';
                if (metadata.expert) metaHtml += `<span class="expert-badge">${metadata.expert}</span>`;
                if (metadata.actions_count) metaHtml += `<span class="action-badge">${metadata.actions_count} 个操作</span>`;
                metaHtml += '</div>';
                body.insertAdjacentHTML('beforeend', metaHtml);
            }
        }
        
        // 更新处理状态
        this.isProcessing = false;
        this.updateSendButton();
    }

    // ==========================================
    // 工具调用显示
    // ==========================================

    /**
     * 显示工具调用
     */
    showToolCall(tool, args) {
        const friendlyName = this.toolNames[tool] || tool;
        
        const toolDiv = document.createElement('div');
        toolDiv.className = 'tool-call-indicator';
        toolDiv.dataset.tool = tool;
        toolDiv.innerHTML = `
            <i class="fas fa-cog fa-spin me-2"></i>
            <span class="tool-action">正在${friendlyName}...</span>
        `;
        this.messagesContainer.appendChild(toolDiv);
        this.scrollToBottom();
    }

    /**
     * 显示工具执行结果
     */
    showToolResult(tool, result) {
        const indicators = this.messagesContainer.querySelectorAll('.tool-call-indicator:not(.tool-completed)');
        if (indicators.length > 0) {
            const lastIndicator = indicators[indicators.length - 1];
            const actionText = lastIndicator.querySelector('.tool-action').textContent
                .replace('正在', '').replace('...', '');
            
            lastIndicator.innerHTML = `
                <i class="fas fa-check-circle text-success me-2"></i>
                <span class="tool-action">${actionText}完成</span>
            `;
            lastIndicator.classList.add('tool-completed');
            
            // 2秒后淡出
            setTimeout(() => {
                lastIndicator.style.opacity = '0.6';
            }, 1500);
        }
    }

    /**
     * 显示操作预览
     */
    showActionPreview(actions) {
        const previewDiv = document.createElement('div');
        previewDiv.className = 'action-preview';
        
        let actionsHtml = actions.map(action => `
            <div class="preview-action">
                <i class="fas fa-${this.getActionIcon(action.type)} me-2"></i>
                ${action.description}
            </div>
        `).join('');
        
        previewDiv.innerHTML = `
            <div class="preview-header">
                <i class="fas fa-clipboard-list me-2"></i>即将执行以下操作:
            </div>
            <div class="preview-actions">${actionsHtml}</div>
            <div class="preview-buttons">
                <button class="btn btn-sm btn-success" onclick="agentChat.confirmActions()">
                    <i class="fas fa-check me-1"></i>确认执行
                </button>
                <button class="btn btn-sm btn-secondary" onclick="agentChat.cancelActions()">
                    <i class="fas fa-times me-1"></i>取消
                </button>
            </div>
        `;
        
        this.messagesContainer.appendChild(previewDiv);
        this.scrollToBottom();
    }

    /**
     * 确认执行操作
     */
    confirmActions() {
        this.socket.send(JSON.stringify({
            type: 'confirm_actions',
            confirm: true
        }));
        
        const preview = this.messagesContainer.querySelector('.action-preview');
        if (preview) preview.remove();
    }

    /**
     * 取消操作
     */
    cancelActions() {
        this.socket.send(JSON.stringify({
            type: 'confirm_actions',
            confirm: false
        }));
        
        const preview = this.messagesContainer.querySelector('.action-preview');
        if (preview) {
            preview.remove();
            this.addMessage('操作已取消。', 'agent');
        }
    }

    /**
     * 显示操作执行结果
     */
    showActionExecuted(results) {
        const resultDiv = document.createElement('div');
        resultDiv.className = 'action-result';
        
        const successCount = results.filter(r => r.success).length;
        const failCount = results.length - successCount;
        
        resultDiv.innerHTML = `
            <div class="result-summary">
                <i class="fas fa-check-circle text-success me-2"></i>
                ${successCount} 个操作成功执行
                ${failCount > 0 ? `<span class="text-warning ms-2">(${failCount} 个失败)</span>` : ''}
            </div>
        `;
        
        this.messagesContainer.appendChild(resultDiv);
        this.scrollToBottom();
    }

    /**
     * 获取操作图标
     */
    getActionIcon(type) {
        const icons = {
            'create_event': 'calendar-plus',
            'update_event': 'calendar-check',
            'delete_event': 'calendar-times',
            'create_todo': 'tasks',
            'update_todo': 'check-square',
            'delete_todo': 'trash',
            'create_reminder': 'bell',
            'default': 'bolt'
        };
        return icons[type] || icons['default'];
    }

    // ==========================================
    // 历史记录与会话管理
    // ==========================================

    /**
     * 加载历史消息
     */
    async loadHistory() {
        try {
            const response = await fetch(`/api/agent/history/?session_id=${encodeURIComponent(this.sessionId)}`, {
                headers: {
                    'X-CSRFToken': this.csrfToken
                }
            });
            
            if (response.ok) {
                const data = await response.json();
                const messages = data.messages || [];
                
                // 清空现有消息
                this.messagesContainer.innerHTML = '';
                
                // 重置消息计数
                this.messageCount = 0;
                
                if (messages.length > 0) {
                    // 设置回滚基准点为当前消息数（切换会话后的消息才能回滚）
                    this.rollbackBaseIndex = 0;
                    
                    // 渲染历史消息
                    messages.forEach(msg => {
                        if (msg.role === 'tool') return; // 跳过工具消息
                        
                        const type = msg.role === 'user' ? 'user' : 'agent';
                        const index = msg.index !== undefined ? msg.index : null;
                        
                        // 恢复工具调用信息
                        if (msg.tool_calls && msg.tool_calls.length > 0) {
                            msg.tool_calls.forEach(tc => {
                                this.addToolCallIndicatorFromHistory(tc.name);
                            });
                        }
                        
                        this.addMessage(msg.content, type, {}, index);
                    });
                    
                    // 更新消息计数
                    this.messageCount = data.total_messages || messages.length;
                    
                    // 更新回滚基准点
                    this.rollbackBaseIndex = this.messageCount;
                } else {
                    this.showWelcomeMessage();
                }
            } else {
                console.warn('加载历史消息失败:', response.status);
                this.showWelcomeMessage();
            }
        } catch (error) {
            console.error('加载历史消息失败:', error);
            this.showWelcomeMessage();
        }
    }

    /**
     * 从历史记录恢复工具调用指示器
     */
    addToolCallIndicatorFromHistory(toolName) {
        const friendlyName = this.toolNames[toolName] || toolName;
        
        const toolDiv = document.createElement('div');
        toolDiv.className = 'tool-call-indicator tool-completed';
        toolDiv.dataset.tool = toolName;
        toolDiv.innerHTML = `
            <i class="fas fa-check-circle text-success me-2"></i>
            <span class="tool-action">${friendlyName}完成</span>
        `;
        toolDiv.style.opacity = '0.6';
        this.messagesContainer.appendChild(toolDiv);
    }

    /**
     * 加载会话列表
     */
    async loadSessionList() {
        if (!this.sessionList) return;
        
        try {
            const response = await fetch(`/api/agent/sessions/?current_session_id=${encodeURIComponent(this.sessionId)}`, {
                headers: {
                    'X-CSRFToken': this.csrfToken
                }
            });
            
            if (response.ok) {
                const data = await response.json();
                this.renderSessionList(data.sessions || []);
            } else {
                this.sessionList.innerHTML = '<div class="text-muted text-center py-2">加载失败</div>';
            }
        } catch (error) {
            console.error('加载会话列表失败:', error);
            this.sessionList.innerHTML = '<div class="text-muted text-center py-2">加载失败</div>';
        }
    }

    /**
     * 渲染会话列表
     */
    renderSessionList(sessions) {
        if (sessions.length === 0) {
            this.sessionList.innerHTML = '<div class="text-muted text-center py-2">暂无历史会话</div>';
            return;
        }
        
        this.sessionList.innerHTML = sessions.map(session => {
            const isActive = session.session_id === this.sessionId;
            const preview = session.last_message_preview || '新对话';
            const date = new Date(session.updated_at).toLocaleDateString('zh-CN');
            const escapedName = this.escapeHtml(session.name);
            
            return `
                <div class="session-item ${isActive ? 'active' : ''}" 
                     data-session-id="${session.session_id}">
                    <div class="session-info" onclick="agentChat.switchSession('${session.session_id}')">
                        <div class="session-name" id="session-name-${session.session_id}">${escapedName}</div>
                        <div class="session-preview">${this.escapeHtml(preview)}</div>
                    </div>
                    <div class="session-meta">
                        <span class="session-date">${date}</span>
                        <span class="session-count">${session.message_count} 条</span>
                    </div>
                    <div class="session-actions">
                        <button class="session-action-btn" title="重命名" onclick="event.stopPropagation(); agentChat.renameSession('${session.session_id}', '${escapedName.replace(/'/g, "\\'")}')"><i class="fas fa-edit"></i></button>
                        <button class="session-action-btn delete" title="删除" onclick="event.stopPropagation(); agentChat.deleteSession('${session.session_id}')"><i class="fas fa-trash"></i></button>
                    </div>
                </div>
            `;
        }).join('');
    }
    
    /**
     * HTML 转义
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    /**
     * 重命名会话
     */
    async renameSession(sessionId, currentName) {
        const newName = prompt('请输入新的会话名称:', currentName);
        if (!newName || newName.trim() === '' || newName === currentName) return;
        
        try {
            const response = await fetch(`/api/agent/sessions/${encodeURIComponent(sessionId)}/rename/`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken
                },
                body: JSON.stringify({ name: newName.trim() })
            });
            
            if (response.ok) {
                // 更新UI
                const nameEl = document.getElementById(`session-name-${sessionId}`);
                if (nameEl) nameEl.textContent = newName.trim();
                this.showNotification('会话已重命名', 'success');
            } else {
                const data = await response.json();
                this.showNotification(data.error || '重命名失败', 'error');
            }
        } catch (error) {
            console.error('重命名失败:', error);
            this.showNotification('重命名失败', 'error');
        }
    }
    
    /**
     * 删除会话
     */
    async deleteSession(sessionId) {
        if (sessionId === this.sessionId) {
            this.showNotification('不能删除当前会话', 'warning');
            return;
        }
        
        if (!confirm('确定要删除这个会话吗？此操作不会回滚任何操作。')) return;
        
        try {
            const response = await fetch(`/api/agent/sessions/${encodeURIComponent(sessionId)}/`, {
                method: 'DELETE',
                headers: {
                    'X-CSRFToken': this.csrfToken
                }
            });
            
            if (response.ok) {
                // 从列表中移除
                const sessionItem = this.sessionList.querySelector(`[data-session-id="${sessionId}"]`);
                if (sessionItem) sessionItem.remove();
                this.showNotification('会话已删除', 'success');
            } else {
                const data = await response.json();
                this.showNotification(data.error || '删除失败', 'error');
            }
        } catch (error) {
            console.error('删除失败:', error);
            this.showNotification('删除失败', 'error');
        }
    }

    /**
     * 切换会话
     */
    async switchSession(sessionId) {
        if (sessionId === this.sessionId) {
            this.hideSessionHistoryPanel();
            return;
        }
        
        // 确认切换（回滚功能会失效）
        const hasMessages = this.messagesContainer.querySelectorAll('.agent-message.user-message').length > 0;
        if (hasMessages) {
            const confirmed = confirm('切换会话后，当前会话的回滚功能将不可用。是否继续？');
            if (!confirmed) return;
        }
        
        // 保存新的会话ID
        this.saveSessionId(sessionId);
        
        // 关闭历史面板
        this.hideSessionHistoryPanel();
        
        // 重置状态
        this.messageCount = 0;
        this.rollbackBaseIndex = 0;
        
        // 清空消息容器
        this.messagesContainer.innerHTML = '';
        
        // 重新连接 WebSocket
        this.reconnect();
        
        // 加载新会话历史
        await this.loadHistory();
        
        // 刷新会话列表
        this.loadSessionList();
        
        this.showNotification('已切换到历史会话', 'info');
    }

    /**
     * 创建新会话
     */
    async createNewSession() {
        // 检查当前会话是否为空
        if (this.isCurrentSessionEmpty()) {
            this.showNotification('当前会话还没有消息，无需新建', 'info');
            this.hideSessionHistoryPanel();
            return;
        }
        
        try {
            const response = await fetch('/api/agent/sessions/create/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken
                },
                body: JSON.stringify({})
            });
            
            if (response.ok) {
                const data = await response.json();
                
                // 保存新会话ID
                this.saveSessionId(data.session_id);
                
                // 关闭历史面板
                this.hideSessionHistoryPanel();
                
                // 重置状态
                this.messageCount = 0;
                this.rollbackBaseIndex = 0;
                
                // 清空并显示欢迎消息
                this.messagesContainer.innerHTML = '';
                this.showWelcomeMessage();
                
                // 重新连接 WebSocket
                this.reconnect();
                
                // 刷新会话列表
                this.loadSessionList();
                
                // 更新新建按钮状态
                this.updateNewSessionButton();
                
                this.showNotification('已创建新会话', 'success');
            } else {
                this.showNotification('创建会话失败', 'error');
            }
        } catch (error) {
            console.error('创建会话失败:', error);
            this.showNotification('创建会话失败', 'error');
        }
    }
    
    /**
     * 检查当前会话是否为空
     */
    isCurrentSessionEmpty() {
        const userMessages = this.messagesContainer.querySelectorAll('.agent-message.user-message');
        return userMessages.length === 0;
    }
    
    /**
     * 更新新建会话按钮状态
     */
    updateNewSessionButton() {
        if (!this.newSessionBtn) return;
        
        const isEmpty = this.isCurrentSessionEmpty();
        this.newSessionBtn.disabled = isEmpty;
        this.newSessionBtn.title = isEmpty ? '当前会话为空，无需新建' : '新建会话';
    }

    /**
     * 更新会话预览
     */
    updateSessionPreview(message) {
        // 更新本地存储或发送到后端
        // 这里简化处理，实际应该在后端更新
    }

    /**
     * 切换会话历史面板（上下分栏模式）
     */
    toggleSessionHistoryPanel() {
        if (this.sessionHistoryPanel.style.display === 'none') {
            this.showSessionHistoryPanel();
        } else {
            this.hideSessionHistoryPanel();
        }
    }
    
    /**
     * 显示会话历史面板
     */
    showSessionHistoryPanel() {
        this.sessionHistoryPanel.style.display = 'flex';
        // 让聊天区域变灰
        if (this.agentChatContainer) {
            this.agentChatContainer.classList.add('dimmed');
        }
        if (this.agentInputArea) {
            this.agentInputArea.classList.add('dimmed');
        }
        // 加载会话列表
        this.loadSessionList();
    }
    
    /**
     * 隐藏会话历史面板
     */
    hideSessionHistoryPanel() {
        this.sessionHistoryPanel.style.display = 'none';
        // 恢复聊天区域
        if (this.agentChatContainer) {
            this.agentChatContainer.classList.remove('dimmed');
        }
        if (this.agentInputArea) {
            this.agentInputArea.classList.remove('dimmed');
        }
    }

    // ==========================================
    // 回滚功能
    // ==========================================

    /**
     * 显示回滚确认（直接执行）
     */
    showRollbackConfirm(messageIndex, buttonElement) {
        const messageDiv = buttonElement.closest('.agent-message');
        const content = messageDiv.querySelector('.message-content').textContent;
        
        // 直接执行回滚
        this.rollbackToMessage(messageIndex, content);
    }

    /**
     * 回滚到指定消息
     */
    async rollbackToMessage(messageIndex, messageContent) {
        try {
            this.showNotification('正在回滚...', 'info');
            
            const response = await fetch('/api/agent/rollback/to-message/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken
                },
                body: JSON.stringify({
                    session_id: this.sessionId,
                    message_index: messageIndex
                })
            });
            
            const data = await response.json();
            console.log('回滚响应:', data);
            
            if (data.success) {
                // 删除界面上该消息及之后的所有消息
                const allMessages = this.messagesContainer.querySelectorAll('.agent-message');
                const messagesToRemove = [];
                
                allMessages.forEach((msgDiv) => {
                    const msgIndex = parseInt(msgDiv.dataset.messageIndex);
                    if (!isNaN(msgIndex) && msgIndex >= messageIndex) {
                        messagesToRemove.push(msgDiv);
                    }
                });
                
                // 也删除没有索引的 agent 消息（在目标消息之后的）
                let foundTarget = false;
                allMessages.forEach((msgDiv) => {
                    const msgIndex = parseInt(msgDiv.dataset.messageIndex);
                    if (!isNaN(msgIndex) && msgIndex === messageIndex) {
                        foundTarget = true;
                    }
                    if (foundTarget && !messagesToRemove.includes(msgDiv)) {
                        messagesToRemove.push(msgDiv);
                    }
                });
                
                console.log(`准备删除 ${messagesToRemove.length} 条消息元素`);
                messagesToRemove.forEach(msg => msg.remove());
                
                // 删除工具调用指示器
                this.messagesContainer.querySelectorAll('.tool-call-indicator').forEach(el => el.remove());
                
                // 更新消息计数
                this.messageCount = messageIndex;
                
                // 如果删除了所有消息，显示欢迎界面
                const remainingMessages = this.messagesContainer.querySelectorAll('.agent-message');
                if (remainingMessages.length === 0) {
                    this.showWelcomeMessage();
                }
                
                // 把原消息内容填入输入框
                if (messageContent) {
                    this.inputField.value = messageContent;
                    this.updateSendButton();
                    this.inputField.focus();
                }
                
                // 刷新数据
                this.refreshData(['events', 'todos', 'reminders']);
                
                // 显示成功提示
                let msg = `已回滚，删除了 ${data.rolled_back_messages} 条消息`;
                if (data.rolled_back_transactions > 0) {
                    msg += `，撤销了 ${data.rolled_back_transactions} 个操作`;
                }
                this.showNotification(msg, 'success');
            } else {
                this.showNotification(data.message || '回滚失败', 'error');
            }
        } catch (error) {
            console.error('回滚失败:', error);
            this.showNotification('回滚失败: ' + error.message, 'error');
        }
    }

    // ==========================================
    // UI 辅助方法
    // ==========================================

    /**
     * 显示欢迎消息
     */
    showWelcomeMessage() {
        // 确保不会重复显示
        const existing = this.messagesContainer.querySelector('.agent-welcome');
        if (existing) return;
        
        const welcomeDiv = document.createElement('div');
        welcomeDiv.className = 'agent-welcome';
        welcomeDiv.innerHTML = `
            <div class="welcome-icon">
                <i class="fas fa-robot"></i>
            </div>
            <h6>智能日程助手</h6>
            <p class="text-muted">我可以帮你管理日程、创建事件、安排待办，并提供智能建议。</p>
            <div class="quick-prompts">
                <button class="quick-prompt-btn" data-prompt="帮我查看今天的日程">
                    <i class="fas fa-calendar-day me-1"></i>今日日程
                </button>
                <button class="quick-prompt-btn" data-prompt="帮我创建一个明天下午3点的会议">
                    <i class="fas fa-plus me-1"></i>创建事件
                </button>
                <button class="quick-prompt-btn" data-prompt="分析我本周的时间安排">
                    <i class="fas fa-chart-pie me-1"></i>时间分析
                </button>
                <button class="quick-prompt-btn" data-prompt="帮我规划去北京的路线">
                    <i class="fas fa-map-marker-alt me-1"></i>路线规划
                </button>
            </div>
        `;
        this.messagesContainer.appendChild(welcomeDiv);
        
        // 绑定快捷提示按钮事件
        this.bindQuickPromptButtons();
    }

    /**
     * 显示打字指示器
     */
    showTyping() {
        if (this.typingIndicator) {
            this.typingIndicator.style.display = 'flex';
            this.scrollToBottom();
        }
    }

    /**
     * 隐藏打字指示器
     */
    hideTyping() {
        if (this.typingIndicator) {
            this.typingIndicator.style.display = 'none';
        }
    }

    /**
     * 更新状态显示
     */
    updateStatus(status, text) {
        if (!this.statusBadge) return;
        
        const dot = this.statusBadge.querySelector('.status-dot');
        const textSpan = this.statusBadge.querySelector('.status-text');
        
        if (dot) dot.className = 'status-dot ' + status;
        if (textSpan) textSpan.textContent = text;
    }

    /**
     * 更新发送按钮状态
     */
    updateSendButton() {
        if (!this.sendBtn) return;
        
        const hasContent = this.inputField.value.trim().length > 0;
        
        if (this.isProcessing) {
            // 处理中：显示终止按钮
            this.sendBtn.disabled = false;
            this.sendBtn.innerHTML = '<i class="fas fa-stop"></i>';
            this.sendBtn.classList.remove('btn-primary');
            this.sendBtn.classList.add('btn-danger');
            this.sendBtn.title = '停止生成';
        } else {
            // 空闲：显示发送按钮
            this.sendBtn.disabled = !hasContent || !this.isConnected;
            this.sendBtn.innerHTML = '<i class="fas fa-paper-plane"></i>';
            this.sendBtn.classList.remove('btn-danger');
            this.sendBtn.classList.add('btn-primary');
            this.sendBtn.title = '发送';
        }
    }

    /**
     * 自动调整输入框高度
     */
    autoResize() {
        if (!this.inputField) return;
        this.inputField.style.height = 'auto';
        this.inputField.style.height = Math.min(this.inputField.scrollHeight, 120) + 'px';
    }

    /**
     * 滚动到底部
     */
    scrollToBottom() {
        if (this.messagesContainer) {
            this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
        }
    }

    /**
     * 同步消息到模态框
     */
    syncMessagesToModal() {
        const modalMessages = document.getElementById('modalAgentMessages');
        if (modalMessages) {
            modalMessages.innerHTML = this.messagesContainer.innerHTML;
            modalMessages.scrollTop = modalMessages.scrollHeight;
        }
    }

    /**
     * 刷新数据
     */
    refreshData(refreshTypes) {
        if (!Array.isArray(refreshTypes)) {
            refreshTypes = [refreshTypes];
        }
        
        if (refreshTypes.includes('events') && window.eventManager) {
            window.eventManager.loadEvents();
        }
        if (refreshTypes.includes('todos') && window.todoManager) {
            window.todoManager.loadTodos();
        }
        if (refreshTypes.includes('reminders') && window.reminderManager) {
            window.reminderManager.loadReminders();
        }
    }

    /**
     * 显示通知
     */
    showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `agent-notification ${type}`;
        
        const iconMap = {
            'success': 'check-circle',
            'error': 'exclamation-circle',
            'warning': 'exclamation-triangle',
            'info': 'info-circle'
        };
        
        notification.innerHTML = `
            <i class="fas fa-${iconMap[type] || 'info-circle'} me-2"></i>
            ${message}
        `;
        
        this.messagesContainer.appendChild(notification);
        this.scrollToBottom();
        
        // 3秒后自动消失
        setTimeout(() => {
            notification.style.opacity = '0';
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    }
}

// 全局变量，在 HTML 中初始化
let agentChat = null;
