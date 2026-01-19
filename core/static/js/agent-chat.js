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
        
        // 工具选择状态
        this.availableTools = [];  // 可用工具列表（从服务器获取）
        this.activeTools = [];     // 当前启用的工具
        this.pendingTools = [];    // 待确认的工具选择
        this.toolPanelVisible = false;
        
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
        this.toolSelectBtn = document.getElementById('toolSelectBtn');
        this.toolSelectPanel = document.getElementById('toolSelectPanel');
        
        // 附件系统元素
        this.attachmentBtn = document.getElementById('attachmentBtn');
        this.attachmentPanel = document.getElementById('attachmentPanel');
        this.attachmentPanelBody = document.getElementById('attachmentPanelBody');
        this.attachmentTypeList = document.getElementById('attachmentTypeList');
        this.attachmentContentList = document.getElementById('attachmentContentList');
        this.attachmentContentItems = document.getElementById('attachmentContentItems');
        this.attachmentBackBtn = document.getElementById('attachmentBackBtn');
        this.attachmentPanelTitle = document.getElementById('attachmentPanelTitle');
        this.selectedAttachmentsContainer = document.getElementById('selectedAttachments');
        this.closeAttachmentPanelBtn = document.getElementById('closeAttachmentPanel');
        this.selectedAttachments = [];  // 已选择的附件列表（单选，最多一个）
        this.attachmentPanelVisible = false;
        this.currentAttachmentType = null;  // 当前选择的附件类型
        
        // TO DO 面板元素
        this.todoPanelElement = document.getElementById('sessionTodoPanel');
        this.todoListElement = document.getElementById('sessionTodoList');
        this.closeTodoPanelBtn = document.getElementById('closeTodoPanelBtn');
        this.sessionTodos = [];  // 当前会话的 TO DO 列表
        this.todoPanelCollapsed = false;  // TO DO 面板是否收起
        
        // 消息计数（用于跟踪消息索引）
        this.messageCount = 0;
        
        // 流式回复状态跟踪
        this.isStreamingActive = false;  // 是否正在流式回复
        this.streamingContent = '';      // 已接收的流式内容
        
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
            // Memory V2
            'save_personal_info': '保存个人信息',
            'get_personal_info': '获取个人信息',
            'update_personal_info': '更新个人信息',
            'delete_personal_info': '删除个人信息',
            'get_dialog_style': '获取对话风格',
            'update_dialog_style': '更新对话风格',
            'save_workflow_rule': '保存工作流规则',
            'get_workflow_rules': '获取工作流规则',
            'update_workflow_rule': '更新工作流规则',
            'delete_workflow_rule': '删除工作流规则',
            // Session TO DO (任务追踪)
            'add_task': '添加任务',
            'update_task_status': '更新任务状态',
            'get_task_list': '获取任务列表',
            'clear_completed_tasks': '清除已完成任务',
            // MCP
            'amap_search': '搜索地点',
            'amap_weather': '查询天气',
            'amap_route': '规划路线'
        };
        
        this.init();
    }

    /**
     * 初始化
     */
    async init() {
        // 生成或恢复会话ID
        this.sessionId = this.getOrCreateSessionId();
        
        // 绑定事件
        this.bindEvents();
        
        // 加载可用工具列表（必须等待完成，因为后续 WebSocket 连接需要工具列表）
        await this.loadAvailableTools();
        
        // 连接 WebSocket（现在 activeTools 已经准备好了）
        this.connect();
        
        // 加载历史消息
        this.loadHistory().then(() => {
            // 加载完成后更新新建按钮状态
            this.updateNewSessionButton();
            
            // 【关键】检查并恢复流式回复状态（必须在 loadHistory 之后）
            this.restoreStreamingState();
        });
        
        // 加载会话列表
        this.loadSessionList();
        
        // 加载当前会话的 TOD O 列表
        this.loadSessionTodos();
    }

    /**
     * 获取或创建会话ID
     * 关键：必须验证存储的 sessionId 是否属于当前用户，防止用户切换时使用错误的会话
     */
    getOrCreateSessionId() {
        const storageKey = 'agent_session_id';
        const userKey = 'agent_session_user_id';
        
        let sessionId = localStorage.getItem(storageKey);
        const storedUserId = localStorage.getItem(userKey);
        
        // 验证：如果存储的用户ID与当前用户不匹配，需要清除并创建新会话
        if (!sessionId || storedUserId !== String(this.userId)) {
            sessionId = `user_${this.userId}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
            localStorage.setItem(storageKey, sessionId);
            localStorage.setItem(userKey, String(this.userId));
            console.log(`[AgentChat] 为用户 ${this.userId} 创建新会话: ${sessionId}`);
        }
        return sessionId;
    }

    /**
     * 获取当前会话的回滚基准点
     */
    getRollbackBaseIndex() {
        const key = `rollback_base_${this.sessionId}`;
        const stored = localStorage.getItem(key);
        return stored !== null ? parseInt(stored, 10) : 0;
    }

    /**
     * 保存当前会话的回滚基准点
     */
    saveRollbackBaseIndex(index) {
        const key = `rollback_base_${this.sessionId}`;
        localStorage.setItem(key, index.toString());
        this.rollbackBaseIndex = index;
    }

    // ==========================================
    // 配置存储系统
    // ==========================================

    /**
     * 获取用户配置存储的 key
     */
    getConfigStorageKey() {
        return `agent_config_${this.userId}`;
    }

    /**
     * 加载用户配置
     * @returns {Object} 配置对象
     */
    loadUserConfig() {
        try {
            const stored = localStorage.getItem(this.getConfigStorageKey());
            if (stored) {
                return JSON.parse(stored);
            }
        } catch (e) {
            console.error('加载用户配置失败:', e);
        }
        // 默认配置
        return {
            activeTools: null,  // null 表示使用服务器默认值
            llmModel: 'deepseek-chat',  // 预留字段
            llmTemperature: 0,  // 预留字段
            theme: 'auto',  // 预留字段
        };
    }

    /**
     * 保存用户配置
     * @param {Object} config 配置对象
     */
    saveUserConfig(config) {
        try {
            const currentConfig = this.loadUserConfig();
            const newConfig = { ...currentConfig, ...config };
            localStorage.setItem(this.getConfigStorageKey(), JSON.stringify(newConfig));
            console.log('💾 保存用户配置:', newConfig);
        } catch (e) {
            console.error('保存用户配置失败:', e);
        }
    }

    /**
     * 获取已保存的工具选择
     * @returns {Array|null} 工具列表，或 null 表示使用默认
     */
    getSavedActiveTools() {
        const config = this.loadUserConfig();
        return config.activeTools;
    }

    /**
     * 保存工具选择
     * @param {Array} tools 工具列表
     */
    saveActiveTools(tools) {
        this.saveUserConfig({ activeTools: tools });
    }

    /**
     * 保存当前会话ID
     * 同时保存用户ID以确保用户隔离
     */
    saveSessionId(sessionId) {
        localStorage.setItem('agent_session_id', sessionId);
        localStorage.setItem('agent_session_user_id', String(this.userId));
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
        
        // 记忆优化按钮
        const memoryOptimizeBtn = document.getElementById('memoryOptimizeBtn');
        if (memoryOptimizeBtn) {
            memoryOptimizeBtn.addEventListener('click', () => this.optimizeMemory());
        }
        
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
        
        // 工具选择按钮
        if (this.toolSelectBtn) {
            this.toolSelectBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleToolPanel();
            });
        }
        
        // 附件按钮
        if (this.attachmentBtn) {
            this.attachmentBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleAttachmentPanel();
            });
        }
        
        // 关闭附件面板
        if (this.closeAttachmentPanelBtn) {
            this.closeAttachmentPanelBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.hideAttachmentPanel();
            });
        }
        
        // 附件返回按钮
        if (this.attachmentBackBtn) {
            this.attachmentBackBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.showAttachmentTypeList();
            });
        }
        
        // 附件类型选择
        this.bindAttachmentTypeEvents();
        
        // TO DO 面板收起按钮
        if (this.closeTodoPanelBtn) {
            this.closeTodoPanelBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleTodoPanelCollapse();
            });
        }
        
        // 点击外部关闭工具面板和附件面板
        document.addEventListener('click', (e) => {
            if (this.toolPanelVisible && this.toolSelectPanel && 
                !this.toolSelectPanel.contains(e.target) && 
                !this.toolSelectBtn.contains(e.target)) {
                this.hideToolPanel();
            }
            if (this.attachmentPanelVisible && this.attachmentPanel &&
                !this.attachmentPanel.contains(e.target) &&
                !this.attachmentBtn.contains(e.target)) {
                this.hideAttachmentPanel();
            }
        });
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
        // 构建 WebSocket URL，包含 session_id 和 active_tools
        let wsUrl = `${protocol}//${window.location.host}/ws/agent/?session_id=${this.sessionId}`;
        if (this.activeTools.length > 0) {
            wsUrl += `&active_tools=${encodeURIComponent(this.activeTools.join(','))}`;
        }
        
        console.log('🔌 WebSocket 连接:');
        console.log('   - URL:', wsUrl);
        console.log('   - activeTools:', this.activeTools);
        console.log('   - 工具数量:', this.activeTools.length);
        
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
                // 同步服务器端的消息数量
                if (data.message_count !== undefined) {
                    this.messageCount = data.message_count;
                    console.log('📊 同步消息计数:', this.messageCount);
                }
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
                // 检查是否是 TO DO 相关工具，实时更新 TO DO 面板
                this.updateTodoFromToolResult(data.name || data.tool, data.result);
                break;
            
            case 'finished':
                this.hideTyping();
                this.isProcessing = false;
                this.updateSendButton();
                // 同步服务器端的消息数量（确保与后端一致）
                if (data.message_count !== undefined) {
                    this.messageCount = data.message_count;
                    console.log('📊 处理完成，同步消息计数:', this.messageCount);
                }
                
                // 【关键】如果有流式消息正在显示，结束它
                const activeStreamMsg = document.getElementById('streamingMessage');
                if (activeStreamMsg) {
                    console.log('🔄 收到 finished 事件，结束流式消息');
                    this.endStreamMessage(data.metadata || {});
                }
                
                // 清除恢复超时定时器
                if (this.streamingRestoreTimeout) {
                    clearTimeout(this.streamingRestoreTimeout);
                    this.streamingRestoreTimeout = null;
                }
                
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
                // 【关键】错误时清除流式状态
                this.isStreamingActive = false;
                this.streamingContent = '';
                this.clearStreamingState();
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
                // 【关键】停止时清除流式状态
                this.isStreamingActive = false;
                this.streamingContent = '';
                this.clearStreamingState();
                break;
                
            case 'recursion_limit':
                // 达到递归限制，询问用户是否继续
                this.hideTyping();
                this.isProcessing = false;
                this.updateSendButton();
                this.showRecursionLimitMessage(data.message || '工具调用次数达到上限，是否继续执行？');
                break;
            
            case 'status_response':
                // 后端状态查询响应
                console.log('📥 收到状态响应:', data);
                
                // 如果后端建议立即同步（说明流式输出已在后端完成，前端错过了）
                if (data.should_sync_immediately) {
                    console.log('🔄 后端流式输出已完成，立即同步历史消息');
                    this.forceEndStreamingWithSync();
                    return;
                }
                
                // 综合判断是否真的完成
                // 1. is_processing = false 表示当前没有活跃的处理任务
                // 2. has_pending_messages = true 表示还有待处理的消息（如 tool 或 human）
                // 3. last_message_role = 'assistant' 且没有 tool_calls 表示真的完成了
                
                if (this.isStreamingActive) {
                    if (data.has_pending_messages) {
                        // 还有待处理的消息（例如工具调用结果），继续等待
                        console.log('⏳ 检测到待处理消息，继续等待...', {
                            last_message_role: data.last_message_role,
                            has_pending_messages: data.has_pending_messages
                        });
                    } else if (!data.is_processing && !data.has_pending_messages) {
                        // 没有活跃任务，也没有待处理消息，应该是完成了
                        console.log('✅ 确认后端已完成，准备同步');
                        // 给一点延迟，让可能的 finished 消息先到达
                        setTimeout(() => {
                            if (this.isStreamingActive && document.getElementById('streamingMessage')) {
                                console.log('🔄 执行强制同步');
                                this.forceEndStreamingWithSync();
                            }
                        }, 1000);
                    }
                }
                break;
                
            default:
                console.log('未知消息类型:', data.type);
        }
    }

    /**
     * 发送消息
     */
    async sendMessage() {
        const message = this.inputField.value.trim();
        if (!message || !this.isConnected || this.isProcessing) return;
        
        // 清空输入
        this.inputField.value = '';
        this.autoResize();
        this.updateSendButton();
        
        // 隐藏欢迎消息
        const welcome = this.messagesContainer.querySelector('.agent-welcome');
        if (welcome) welcome.style.display = 'none';
        
        // 获取附件内容（如果有）
        let fullMessage = message;
        if (this.selectedAttachments.length > 0) {
            const attachmentContent = await this.getFormattedAttachmentContent();
            if (attachmentContent) {
                fullMessage = `${attachmentContent}\n\n${message}`;
            }
            // 清空已选附件
            this.clearSelectedAttachments();
        }
        
        // 添加用户消息（带消息索引 - 这是后端 LangGraph 中的索引）
        // messageCount 在发送前表示后端消息列表的当前长度，也就是新消息的索引
        const currentIndex = this.messageCount;
        // 显示给用户的是原始消息，但发送的包含附件
        this.addMessage(message, 'user', {}, currentIndex);
        // 注意: 不在这里增加 messageCount，等 'finished' 事件从服务器同步
        // 但为了回滚功能，需要临时增加1表示用户消息已发送
        this.messageCount += 1;
        
        // 标记为处理中
        this.isProcessing = true;
        this.updateSendButton();
        
        // 【关键】立即保存流式状态（即使还没开始接收内容）
        this.isStreamingActive = true;
        this.streamingContent = '';
        this.saveStreamingState();
        console.log('📤 消息已发送，初始化流式状态');
        
        // 显示打字指示器
        this.showTyping();
        
        // 发送到 WebSocket
        this.socket.send(JSON.stringify({
            type: 'message',
            content: fullMessage
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
        
        // 【关键】清除流式状态
        this.isStreamingActive = false;
        this.streamingContent = '';
        this.clearStreamingState();
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
        
        // 用户消息添加回滚按钮（只有在回滚基准点之后的消息才显示，且仅当前会话）
        let rollbackInfo = '';
        if (type === 'user' && messageIndex !== null && messageIndex >= this.rollbackBaseIndex) {
            rollbackInfo = `
                <div class="rollback-info-wrapper">
                    <span class="rollback-info-text">可回滚此消息</span>
                    <button class="rollback-btn" title="回到此消息前重新编辑" onclick="agentChat.showRollbackConfirm(${messageIndex}, this)">
                        <i class="fas fa-undo"></i>
                    </button>
                </div>
            `;
        }
        
        messageDiv.innerHTML = `
            <div class="message-avatar ${avatarClass}">
                <i class="fas fa-${avatar}"></i>
            </div>
            <div class="message-body">
                <div class="message-content">${this.formatContent(content)}</div>
                ${metadataHtml ? `<div class="message-meta">${metadataHtml}</div>` : ''}
                ${rollbackInfo}
            </div>
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
        
        // 【关键】保存流式状态
        this.isStreamingActive = true;
        this.streamingContent = '';
        this.saveStreamingState();
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
            
            // 【关键】累积内容并保存状态
            this.streamingContent += content;
            this.saveStreamingState();
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
        
        // 注意: 消息计数会在 'finished' 事件中从服务器同步，这里不增加
        
        // 更新处理状态
        this.isProcessing = false;
        this.updateSendButton();
        
        // 【关键】清除流式状态和超时定时器
        this.isStreamingActive = false;
        this.streamingContent = '';
        this.clearStreamingState();
        if (this.streamingRestoreTimeout) {
            clearTimeout(this.streamingRestoreTimeout);
            this.streamingRestoreTimeout = null;
        }
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
                    const totalMessages = data.total_messages || messages.length;
                    this.messageCount = totalMessages;
                    
                    // 【关键】从 localStorage 恢复回滚基准点
                    // 如果没有存储值，说明是首次加载或切换后首次加载，使用消息总数
                    const storedBaseIndex = this.getRollbackBaseIndex();
                    // 如果存储的基准点有效（<=消息总数），使用它；否则使用消息总数
                    if (storedBaseIndex <= totalMessages) {
                        this.rollbackBaseIndex = storedBaseIndex;
                    } else {
                        // 存储的值无效（可能是回滚后消息减少了），重置为消息总数
                        this.saveRollbackBaseIndex(totalMessages);
                    }
                    
                    // 渲染历史消息
                    messages.forEach(msg => {
                        const index = msg.index !== undefined ? msg.index : null;
                        
                        if (msg.role === 'user') {
                            // 用户消息
                            if (msg.content && msg.content.trim()) {
                                this.addMessage(msg.content, 'user', {}, index);
                            }
                        } else if (msg.role === 'assistant') {
                            // AI消息
                            // 第一步：显示AI的思考内容（如果有）
                            if (msg.content && msg.content.trim()) {
                                this.addMessage(msg.content, 'agent', {}, index);
                            }
                            
                            // 第二步：显示工具调用指示器（如果有）
                            if (msg.tool_calls && msg.tool_calls.length > 0) {
                                msg.tool_calls.forEach(tc => {
                                    this.addToolCallIndicatorFromHistory(tc.name);
                                });
                            }
                        } else if (msg.role === 'tool') {
                            // 工具执行结果
                            if (msg.content && msg.content.trim()) {
                                this.showToolResultFromHistory(msg.content);
                            }
                        }
                    });
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
     * 从历史记录恢复工具执行结果
     */
    showToolResultFromHistory(result) {
        // 截断过长的结果
        const displayResult = result.length > 200 ? result.substring(0, 200) + '...' : result;
        
        const resultDiv = document.createElement('div');
        resultDiv.className = 'tool-result-indicator';
        resultDiv.innerHTML = `
            <i class="fas fa-reply text-info me-2"></i>
            <span class="tool-result-text">${this.formatContent(displayResult)}</span>
        `;
        resultDiv.style.opacity = '0.7';
        this.messagesContainer.appendChild(resultDiv);
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
        
        // 先恢复 UI（取消变灰），这样优化提示框可以点击
        this.hideSessionHistoryPanel();
        
        // 如果当前会话有足够消息，提示是否优化记忆
        if (this.messageCount >= 4) {
            await this.showMemoryOptimizePrompt();
        }
        
        // 【关键】切换前，将当前会话的回滚基准点设为消息总数（使所有消息不可回滚）
        this.saveRollbackBaseIndex(this.messageCount);
        
        // 保存新的会话ID
        this.saveSessionId(sessionId);
        
        // 重置状态
        this.messageCount = 0;
        
        // 清空消息容器
        this.messagesContainer.innerHTML = '';
        
        // 重新连接 WebSocket
        this.reconnect();
        
        // 【关键】切换后，将新会话的回滚基准点设为很大的数（稍后在 loadHistory 中会设置为实际消息数）
        this.saveRollbackBaseIndex(999999);
        
        // 加载新会话历史
        await this.loadHistory();
        
        // 加载新会话的 TO DO 列表
        this.loadSessionTodos();
        
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
        
        // 先关闭历史面板，恢复 UI
        this.hideSessionHistoryPanel();
        
        // 如果当前会话有足够消息，提示是否优化记忆
        if (this.messageCount >= 4) {
            await this.showMemoryOptimizePrompt();
        }
        
        // 弹出确认对话框：提示回滚功能将失效
        const confirmed = confirm('创建新会话后，当前会话的所有消息将无法回滚。是否继续？');
        if (!confirmed) return;
        
        // 【关键】新建前，将当前会话的回滚基准点设为消息总数（使所有消息不可回滚）
        this.saveRollbackBaseIndex(this.messageCount);
        
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
                
                // 重置状态：新会话从0开始，所有新消息都可回滚
                this.messageCount = 0;
                // 【关键】新会话的回滚基准点为0，所有新消息都可回滚
                this.saveRollbackBaseIndex(0);
                
                // 清空并显示欢迎消息
                this.messagesContainer.innerHTML = '';
                this.showWelcomeMessage();
                
                // 重新连接 WebSocket
                this.reconnect();
                
                // 清空 TO DO 列表（新会话没有 TO DO）
                this.sessionTodos = [];
                this.renderTodoPanel();
                
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
    // 工具选择功能
    // ==========================================

    /**
     * 加载可用工具列表
     */
    async loadAvailableTools() {
        try {
            const response = await fetch('/api/agent/tools/', {
                headers: {
                    'X-CSRFToken': this.csrfToken
                }
            });
            
            if (response.ok) {
                const data = await response.json();
                this.availableTools = data.categories || [];
                
                // 从存储中恢复工具选择
                const savedTools = this.getSavedActiveTools();
                if (savedTools !== null) {
                    // 过滤掉不在可用工具中的（可能工具已被移除）
                    const allToolNames = this.availableTools.flatMap(cat => cat.tools.map(t => t.name));
                    this.activeTools = savedTools.filter(t => allToolNames.includes(t));
                    console.log('🔄 从存储恢复工具选择:', this.activeTools);
                } else {
                    // 使用服务器默认值
                    this.activeTools = data.default_tools || [];
                    console.log('ℹ️ 使用默认工具:', this.activeTools);
                }
                this.pendingTools = [...this.activeTools];
                
                // 更新工具按钮状态
                this.updateToolButtonBadge();
                
                console.log('✅ 加载工具列表成功:', this.availableTools);
            } else {
                console.error('加载工具列表失败:', response.status);
            }
        } catch (error) {
            console.error('加载工具列表失败:', error);
        }
    }

    /**
     * 切换工具选择面板
     */
    toggleToolPanel() {
        if (this.toolPanelVisible) {
            this.hideToolPanel();
        } else {
            this.showToolPanel();
        }
    }

    /**
     * 显示工具选择面板
     */
    showToolPanel() {
        if (!this.toolSelectPanel) return;
        
        // 隐藏其他面板
        this.hideSessionHistoryPanel();
        
        // 重置待确认的工具为当前激活的工具
        this.pendingTools = [...this.activeTools];
        
        // 渲染工具列表
        this.renderToolPanel();
        
        // 添加分栏样式
        const panelContent = document.querySelector('.agent-panel-content');
        if (panelContent) {
            panelContent.classList.add('tool-selecting');
        }
        
        // 禁用其他按钮
        this.setOtherButtonsDisabled(true);
        
        // 更新工具按钮状态
        this.toolSelectBtn.classList.add('active');
        
        this.toolSelectPanel.style.display = 'flex';
        this.toolPanelVisible = true;
    }

    /**
     * 隐藏工具选择面板
     */
    hideToolPanel() {
        if (!this.toolSelectPanel) return;
        
        // 移除分栏样式
        const panelContent = document.querySelector('.agent-panel-content');
        if (panelContent) {
            panelContent.classList.remove('tool-selecting');
        }
        
        // 恢复其他按钮
        this.setOtherButtonsDisabled(false);
        
        // 更新工具按钮状态
        this.toolSelectBtn.classList.remove('active');
        
        this.toolSelectPanel.style.display = 'none';
        this.toolPanelVisible = false;
    }

    /**
     * 设置其他按钮的禁用状态
     */
    setOtherButtonsDisabled(disabled) {
        // 发送按钮
        if (this.sendBtn) {
            if (disabled) {
                this.sendBtn.classList.add('disabled-by-tool-panel');
            } else {
                this.sendBtn.classList.remove('disabled-by-tool-panel');
            }
        }
        
        // 输入框
        if (this.inputField) {
            this.inputField.disabled = disabled;
        }
        
        // 会话历史按钮
        if (this.sessionHistoryBtn) {
            if (disabled) {
                this.sessionHistoryBtn.classList.add('disabled-by-tool-panel');
                this.sessionHistoryBtn.style.pointerEvents = 'none';
                this.sessionHistoryBtn.style.opacity = '0.5';
            } else {
                this.sessionHistoryBtn.classList.remove('disabled-by-tool-panel');
                this.sessionHistoryBtn.style.pointerEvents = '';
                this.sessionHistoryBtn.style.opacity = '';
            }
        }
        
        // 展开按钮
        if (this.expandBtn) {
            if (disabled) {
                this.expandBtn.classList.add('disabled-by-tool-panel');
                this.expandBtn.style.pointerEvents = 'none';
                this.expandBtn.style.opacity = '0.5';
            } else {
                this.expandBtn.classList.remove('disabled-by-tool-panel');
                this.expandBtn.style.pointerEvents = '';
                this.expandBtn.style.opacity = '';
            }
        }
        
        // 新建会话按钮
        if (this.newSessionBtn) {
            if (disabled) {
                this.newSessionBtn.classList.add('disabled-by-tool-panel');
                this.newSessionBtn.style.pointerEvents = 'none';
                this.newSessionBtn.style.opacity = '0.5';
            } else {
                this.newSessionBtn.classList.remove('disabled-by-tool-panel');
                this.newSessionBtn.style.pointerEvents = '';
                this.newSessionBtn.style.opacity = '';
            }
        }
    }

    /**
     * 渲染工具选择面板
     */
    renderToolPanel() {
        if (!this.toolSelectPanel) return;
        
        let html = `
            <div class="tool-panel-header">
                <span class="fw-bold"><i class="fas fa-tools me-2"></i>选择工具</span>
                <button class="btn btn-sm btn-link text-muted" onclick="agentChat.hideToolPanel()">
                    <i class="fas fa-times"></i>
                </button>
            </div>
            <div class="tool-panel-body">
        `;
        
        this.availableTools.forEach(category => {
            const allSelected = category.tools.every(t => this.pendingTools.includes(t.name));
            const someSelected = category.tools.some(t => this.pendingTools.includes(t.name));
            
            html += `
                <div class="tool-category">
                    <div class="tool-category-header">
                        <label class="form-check">
                            <input type="checkbox" class="form-check-input category-checkbox" 
                                   data-category="${category.id}"
                                   ${allSelected ? 'checked' : ''} 
                                   ${someSelected && !allSelected ? 'indeterminate' : ''}
                                   onchange="agentChat.toggleCategory('${category.id}', this.checked)">
                            <span class="form-check-label fw-bold">${category.display_name}</span>
                        </label>
                        <small class="text-muted">${category.description}</small>
                    </div>
                    <div class="tool-list">
            `;
            
            category.tools.forEach(tool => {
                const isChecked = this.pendingTools.includes(tool.name);
                html += `
                    <label class="form-check tool-item">
                        <input type="checkbox" class="form-check-input tool-checkbox" 
                               data-tool="${tool.name}" data-category="${category.id}"
                               ${isChecked ? 'checked' : ''}
                               onchange="agentChat.toggleTool('${tool.name}', this.checked)">
                        <span class="form-check-label">${tool.display_name}</span>
                    </label>
                `;
            });
            
            html += `
                    </div>
                </div>
            `;
        });
        
        html += `
            </div>
            <div class="tool-panel-footer">
                <button class="btn btn-sm btn-secondary" onclick="agentChat.hideToolPanel()">取消</button>
                <button class="btn btn-sm btn-primary" onclick="agentChat.applyToolSelection()">
                    <i class="fas fa-check me-1"></i>应用
                </button>
            </div>
        `;
        
        this.toolSelectPanel.innerHTML = html;
        
        // 设置 indeterminate 状态
        this.availableTools.forEach(category => {
            const allSelected = category.tools.every(t => this.pendingTools.includes(t.name));
            const someSelected = category.tools.some(t => this.pendingTools.includes(t.name));
            const checkbox = this.toolSelectPanel.querySelector(`input[data-category="${category.id}"].category-checkbox`);
            if (checkbox && someSelected && !allSelected) {
                checkbox.indeterminate = true;
            }
        });
    }

    /**
     * 切换整个分类
     */
    toggleCategory(categoryId, checked) {
        const category = this.availableTools.find(c => c.id === categoryId);
        if (!category) return;
        
        category.tools.forEach(tool => {
            if (checked) {
                if (!this.pendingTools.includes(tool.name)) {
                    this.pendingTools.push(tool.name);
                }
            } else {
                this.pendingTools = this.pendingTools.filter(t => t !== tool.name);
            }
        });
        
        // 更新UI
        this.renderToolPanel();
    }

    /**
     * 切换单个工具
     */
    toggleTool(toolName, checked) {
        if (checked) {
            if (!this.pendingTools.includes(toolName)) {
                this.pendingTools.push(toolName);
            }
        } else {
            this.pendingTools = this.pendingTools.filter(t => t !== toolName);
        }
        
        // 更新分类复选框状态
        this.updateCategoryCheckboxes();
    }

    /**
     * 更新分类复选框状态
     */
    updateCategoryCheckboxes() {
        this.availableTools.forEach(category => {
            const allSelected = category.tools.every(t => this.pendingTools.includes(t.name));
            const someSelected = category.tools.some(t => this.pendingTools.includes(t.name));
            const checkbox = this.toolSelectPanel.querySelector(`input[data-category="${category.id}"].category-checkbox`);
            if (checkbox) {
                checkbox.checked = allSelected;
                checkbox.indeterminate = someSelected && !allSelected;
            }
        });
    }

    /**
     * 应用工具选择
     */
    applyToolSelection() {
        this.activeTools = [...this.pendingTools];
        
        console.log('📦 应用工具选择:');
        console.log('   - activeTools:', this.activeTools);
        console.log('   - 工具数量:', this.activeTools.length);
        
        // 保存到存储
        this.saveActiveTools(this.activeTools);
        
        // 更新工具按钮徽章
        this.updateToolButtonBadge();
        
        // 重新连接 WebSocket 以使用新的工具配置
        console.log('🔄 重新连接 WebSocket...');
        this.reconnect();
        
        this.hideToolPanel();
        this.showNotification(`已启用 ${this.activeTools.length} 个工具`, 'success');
    }

    /**
     * 更新工具按钮徽章
     */
    updateToolButtonBadge() {
        if (!this.toolSelectBtn) return;
        
        const totalTools = this.availableTools.reduce((sum, cat) => sum + cat.tools.length, 0);
        const activeCount = this.activeTools.length;
        
        // 更新按钮标题
        this.toolSelectBtn.title = `工具选择 (${activeCount}/${totalTools})`;
        
        // 如果不是全部启用，显示徽章
        let badge = this.toolSelectBtn.querySelector('.tool-badge');
        if (activeCount < totalTools) {
            if (!badge) {
                badge = document.createElement('span');
                badge.className = 'tool-badge';
                this.toolSelectBtn.appendChild(badge);
            }
            badge.textContent = activeCount;
        } else if (badge) {
            badge.remove();
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
     * 显示递归限制提示并询问是否继续
     */
    showRecursionLimitMessage(message) {
        const container = document.createElement('div');
        container.className = 'message-wrapper agent-message recursion-limit-wrapper';
        
        container.innerHTML = `
            <div class="message-avatar">
                <i class="fas fa-exclamation-triangle"></i>
            </div>
            <div class="message-content">
                <div class="recursion-limit-content">
                    <div class="recursion-limit-text">
                        <i class="fas fa-pause-circle me-2"></i>
                        ${message}
                    </div>
                    <div class="recursion-limit-actions mt-3">
                        <button class="btn btn-primary btn-sm continue-btn me-2">
                            <i class="fas fa-play-circle me-1"></i>继续执行
                        </button>
                        <button class="btn btn-secondary btn-sm cancel-btn">
                            <i class="fas fa-stop-circle me-1"></i>停止
                        </button>
                    </div>
                </div>
            </div>
        `;
        
        // 绑定按钮事件
        const continueBtn = container.querySelector('.continue-btn');
        const cancelBtn = container.querySelector('.cancel-btn');
        
        continueBtn.addEventListener('click', () => {
            // 禁用按钮并显示处理中
            continueBtn.disabled = true;
            cancelBtn.disabled = true;
            continueBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>继续中...';
            
            // 发送继续消息
            if (this.socket && this.isConnected) {
                this.socket.send(JSON.stringify({ type: 'continue' }));
                this.isProcessing = true;
                this.updateSendButton();
                // 先移除这个提示框，再显示 typing indicator
                container.remove();
                this.showTyping();
            } else {
                // 连接断开，恢复按钮
                continueBtn.disabled = false;
                cancelBtn.disabled = false;
                continueBtn.innerHTML = '<i class="fas fa-play-circle me-1"></i>继续执行';
                this.showNotification('连接已断开，请刷新页面', 'error');
            }
        });
        
        cancelBtn.addEventListener('click', () => {
            // 直接移除这个提示
            container.remove();
            this.showNotification('已停止继续执行', 'info');
        });
        
        this.messagesContainer.appendChild(container);
        this.scrollToBottom();
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

    /**
     * 记忆优化 - 分析当前对话并提取有用信息到记忆系统
     */
    async optimizeMemory() {
        const btn = document.getElementById('memoryOptimizeBtn');
        if (!btn) return;
        
        // 检查消息数量
        if (this.messageCount < 2) {
            this.showNotification('对话太短，无需优化记忆', 'info');
            return;
        }
        
        // 确认对话框
        const confirmed = confirm('是否分析当前对话并优化 AI 记忆？\n\nAI 将从对话中提取有用信息（如个人偏好、工作习惯等）并保存到记忆系统。');
        if (!confirmed) return;
        
        // 显示加载状态
        btn.disabled = true;
        btn.classList.add('optimizing');
        const originalIcon = btn.innerHTML;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        
        // 禁用 UI - 变灰整个 Agent 面板内容区域
        const agentPanelContent = document.querySelector('.agent-panel-content');
        if (agentPanelContent) agentPanelContent.classList.add('dimmed');
        if (this.agentChatContainer) this.agentChatContainer.classList.add('dimmed');
        if (this.inputField) this.inputField.disabled = true;
        if (this.sendBtn) this.sendBtn.disabled = true;
        
        try {
            const response = await fetch('/api/agent/optimize-memory/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken
                },
                body: JSON.stringify({
                    session_id: this.sessionId
                })
            });
            
            if (response.ok) {
                const data = await response.json();
                console.log('记忆优化响应:', data);
                
                // 使用后端返回的 total_operations 字段
                const totalOps = data.total_operations || 0;
                
                if (totalOps > 0) {
                    this.showNotification(`记忆优化完成：${data.summary || `执行了 ${totalOps} 个操作`}`, 'success');
                } else {
                    this.showNotification('未发现需要更新的记忆', 'info');
                }
            } else {
                const error = await response.json();
                this.showNotification(error.message || '记忆优化失败', 'error');
            }
        } catch (error) {
            console.error('记忆优化失败:', error);
            this.showNotification('记忆优化失败: ' + error.message, 'error');
        } finally {
            // 恢复按钮状态
            btn.disabled = false;
            btn.classList.remove('optimizing');
            btn.innerHTML = originalIcon;
            
            // 恢复 UI
            const agentPanelContent = document.querySelector('.agent-panel-content');
            if (agentPanelContent) agentPanelContent.classList.remove('dimmed');
            if (this.agentChatContainer) this.agentChatContainer.classList.remove('dimmed');
            if (this.inputField) this.inputField.disabled = false;
            if (this.sendBtn) this.sendBtn.disabled = false;
        }
    }

    /**
     * 会话切换时的记忆优化提示
     */
    showMemoryOptimizePrompt() {
        // 创建提示条
        const existingPrompt = this.messagesContainer.querySelector('.memory-optimize-prompt');
        if (existingPrompt) existingPrompt.remove();
        
        const prompt = document.createElement('div');
        prompt.className = 'memory-optimize-prompt';
        prompt.innerHTML = `
            <i class="fas fa-lightbulb text-warning"></i>
            <div class="memory-optimize-prompt-text">
                切换会话前，是否要分析当前对话并保存有用信息到记忆？
            </div>
            <div class="memory-optimize-prompt-actions">
                <button class="btn btn-sm btn-outline-primary optimize-yes">
                    <i class="fas fa-brain me-1"></i>优化
                </button>
                <button class="btn btn-sm btn-outline-secondary optimize-no">
                    跳过
                </button>
            </div>
        `;
        
        this.messagesContainer.appendChild(prompt);
        this.scrollToBottom();
        
        return new Promise((resolve) => {
            prompt.querySelector('.optimize-yes').addEventListener('click', async () => {
                prompt.remove();
                await this.optimizeMemory();
                resolve(true);
            });
            
            prompt.querySelector('.optimize-no').addEventListener('click', () => {
                prompt.remove();
                resolve(false);
            });
        });
    }

    // ==========================================
    // TO DO 面板功能
    // ==========================================

    /**
     * 加载当前会话的 TO DO 列表
     */
    async loadSessionTodos() {
        try {
            const response = await fetch(`/api/agent/session-todos/?session_id=${encodeURIComponent(this.sessionId)}`, {
                headers: {
                    'X-CSRFToken': this.csrfToken
                }
            });
            
            if (response.ok) {
                const data = await response.json();
                this.sessionTodos = data.todos || [];
                this.renderTodoPanel();
                console.log('✅ 加载 TODO 列表:', this.sessionTodos.length, '项');
            } else {
                console.error('加载 TODO 列表失败:', response.status);
            }
        } catch (error) {
            console.error('加载 TODO 列表失败:', error);
        }
    }

    /**
     * 渲染 TO DO 面板
     */
    renderTodoPanel() {
        if (!this.todoPanelElement || !this.todoListElement) return;
        
        // 如果没有 TO DO，隐藏面板
        if (!this.sessionTodos || this.sessionTodos.length === 0) {
            this.todoPanelElement.style.display = 'none';
            return;
        }
        
        // 显示面板
        this.todoPanelElement.style.display = 'block';
        
        // 如果面板收起状态，只显示摘要
        if (this.todoPanelCollapsed) {
            const pendingCount = this.sessionTodos.filter(t => t.status !== 'done').length;
            const doneCount = this.sessionTodos.filter(t => t.status === 'done').length;
            this.todoListElement.innerHTML = `
                <div class="todo-summary text-muted">
                    <small>${pendingCount} 项待完成，${doneCount} 项已完成</small>
                </div>
            `;
            this.closeTodoPanelBtn.innerHTML = '<i class="fas fa-chevron-down"></i>';
            return;
        }
        
        // 展开状态，显示完整列表
        this.closeTodoPanelBtn.innerHTML = '<i class="fas fa-chevron-up"></i>';
        
        const statusIcons = {
            'pending': '☐',
            'in_progress': '⏳',
            'done': '✅'
        };
        
        const statusClasses = {
            'pending': 'todo-pending',
            'in_progress': 'todo-in-progress',
            'done': 'todo-done'
        };
        
        let html = '<div class="todo-items">';
        this.sessionTodos.forEach((todo, index) => {
            const icon = statusIcons[todo.status] || '?';
            const statusClass = statusClasses[todo.status] || '';
            html += `
                <div class="todo-item ${statusClass}" data-todo-id="${todo.id}">
                    <span class="todo-icon">${icon}</span>
                    <span class="todo-title">${this.escapeHtml(todo.title)}</span>
                </div>
            `;
        });
        html += '</div>';
        
        this.todoListElement.innerHTML = html;
    }

    /**
     * 切换 TO DO 面板收起/展开
     */
    toggleTodoPanelCollapse() {
        this.todoPanelCollapsed = !this.todoPanelCollapsed;
        this.renderTodoPanel();
    }

    /**
     * 更新任务追踪列表（当收到 WebSocket 消息时调用）
     */
    updateTodoFromToolResult(toolName, result) {
        // 当检测到任务追踪相关工具被调用时，重新加载任务列表
        const taskToolNames = ['add_task', 'update_task_status', 'clear_completed_tasks'];
        if (taskToolNames.includes(toolName)) {
            // 延迟一下确保后端已处理完成
            setTimeout(() => {
                this.loadSessionTodos();
            }, 500);
        }
    }

    // ==========================================
    // 附件系统
    // ==========================================

    /**
     * 绑定附件类型选择事件
     */
    bindAttachmentTypeEvents() {
        if (this.attachmentTypeList) {
            this.attachmentTypeList.querySelectorAll('.attachment-type-item:not(.disabled)').forEach(item => {
                item.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const type = item.dataset.type;
                    this.selectAttachmentType(type);
                });
            });
        }
    }

    /**
     * 切换附件面板显示
     */
    toggleAttachmentPanel() {
        if (this.attachmentPanelVisible) {
            this.hideAttachmentPanel();
        } else {
            this.showAttachmentPanel();
        }
    }

    /**
     * 显示附件面板（显示类型选择列表）
     */
    showAttachmentPanel() {
        if (this.attachmentPanel) {
            // 重置到类型选择视图
            this.showAttachmentTypeList();
            
            this.attachmentPanel.style.display = 'block';
            this.attachmentPanelVisible = true;
            if (this.attachmentBtn) {
                this.attachmentBtn.classList.add('active');
            }
            
            // 添加禁用效果类到父容器
            const panelContent = document.querySelector('.agent-panel-content');
            if (panelContent) {
                panelContent.classList.add('attachment-mode');
            }
        }
    }

    /**
     * 隐藏附件面板
     */
    hideAttachmentPanel() {
        if (this.attachmentPanel) {
            this.attachmentPanel.style.display = 'none';
            this.attachmentPanelVisible = false;
            if (this.attachmentBtn) {
                this.attachmentBtn.classList.remove('active');
            }
            
            // 移除禁用效果类
            const panelContent = document.querySelector('.agent-panel-content');
            if (panelContent) {
                panelContent.classList.remove('attachment-mode');
            }
        }
    }

    /**
     * 显示附件类型列表（第一级）
     */
    showAttachmentTypeList() {
        if (this.attachmentTypeList) {
            this.attachmentTypeList.style.display = 'block';
        }
        if (this.attachmentContentList) {
            this.attachmentContentList.style.display = 'none';
        }
        if (this.attachmentPanelTitle) {
            this.attachmentPanelTitle.innerHTML = '<i class="fas fa-paperclip me-1"></i>选择附件类型';
        }
        this.currentAttachmentType = null;
    }

    /**
     * 选择附件类型，显示内容列表（第二级）
     */
    async selectAttachmentType(type) {
        this.currentAttachmentType = type;
        
        // 更新标题
        const typeLabels = {
            'workflow': '工作流规则'
        };
        if (this.attachmentPanelTitle) {
            this.attachmentPanelTitle.innerHTML = `<i class="fas fa-project-diagram me-1"></i>${typeLabels[type] || type}`;
        }
        
        // 切换视图
        if (this.attachmentTypeList) {
            this.attachmentTypeList.style.display = 'none';
        }
        if (this.attachmentContentList) {
            this.attachmentContentList.style.display = 'block';
        }
        
        // 加载该类型的内容
        await this.loadAttachmentContent(type);
    }

    /**
     * 加载指定类型的附件内容
     */
    async loadAttachmentContent(type) {
        if (!this.attachmentContentItems) return;
        
        // 显示加载中
        this.attachmentContentItems.innerHTML = `
            <div class="text-center py-3">
                <i class="fas fa-spinner fa-spin"></i> 加载中...
            </div>
        `;
        
        try {
            const response = await fetch(`/api/agent/attachments/?type=${type}`, {
                headers: { 'X-CSRFToken': this.csrfToken }
            });
            
            if (!response.ok) {
                throw new Error('加载失败');
            }
            
            const data = await response.json();
            this.renderAttachmentContentList(data.items);
        } catch (error) {
            console.error('加载附件内容失败:', error);
            this.attachmentContentItems.innerHTML = `
                <div class="attachment-empty">
                    <i class="fas fa-exclamation-circle"></i>
                    <p>加载失败</p>
                </div>
            `;
        }
    }

    /**
     * 渲染附件内容列表（单选模式）
     */
    renderAttachmentContentList(items) {
        if (!this.attachmentContentItems) return;
        
        if (!items || items.length === 0) {
            this.attachmentContentItems.innerHTML = `
                <div class="attachment-empty">
                    <i class="fas fa-folder-open"></i>
                    <p>暂无可用内容</p>
                    <small class="text-muted">在"记忆设置"中添加工作流规则</small>
                </div>
            `;
            return;
        }

        // 检查当前是否有选中项
        const selectedItem = this.selectedAttachments.length > 0 ? this.selectedAttachments[0] : null;
        
        let html = '';
        items.forEach(item => {
            const isSelected = selectedItem && 
                               selectedItem.type === item.type && 
                               selectedItem.id === item.id;
            const isDisabled = selectedItem && !isSelected;
            
            html += `
                <div class="attachment-item ${isSelected ? 'selected' : ''} ${isDisabled ? 'disabled' : ''}" 
                     data-type="${item.type}" 
                     data-id="${item.id}"
                     data-name="${this.escapeHtml(item.name)}">
                    <input type="checkbox" class="attachment-item-checkbox" 
                           ${isSelected ? 'checked' : ''} 
                           ${isDisabled ? 'disabled' : ''}>
                    <div class="attachment-item-content">
                        <div class="attachment-item-name">${this.escapeHtml(item.name)}</div>
                        <div class="attachment-item-preview">${this.escapeHtml(item.preview)}</div>
                    </div>
                </div>
            `;
        });

        this.attachmentContentItems.innerHTML = html;

        // 绑定点击事件
        this.attachmentContentItems.querySelectorAll('.attachment-item:not(.disabled)').forEach(el => {
            el.addEventListener('click', () => {
                const type = el.dataset.type;
                const id = parseInt(el.dataset.id);
                const name = el.dataset.name;
                this.toggleAttachmentSingle(type, id, name);
            });
        });
    }

    /**
     * 切换附件选择状态（单选模式）
     */
    toggleAttachmentSingle(type, id, name) {
        const isCurrentlySelected = this.selectedAttachments.length > 0 &&
                                     this.selectedAttachments[0].type === type &&
                                     this.selectedAttachments[0].id === id;

        if (isCurrentlySelected) {
            // 取消选择
            this.selectedAttachments = [];
        } else {
            // 选择新项（替换旧项）
            this.selectedAttachments = [{ type, id, name }];
        }

        this.updateAttachmentBadge();
        this.renderSelectedAttachments();
        
        // 重新渲染列表以更新禁用状态
        this.loadAttachmentContent(this.currentAttachmentType);
    }

    /**
     * 更新附件按钮徽章
     */
    updateAttachmentBadge() {
        const badge = this.attachmentBtn?.querySelector('.attachment-badge');
        if (badge) {
            const count = this.selectedAttachments.length;
            badge.textContent = count;
            badge.style.display = count > 0 ? 'block' : 'none';
        }
    }

    /**
     * 渲染已选附件预览
     */
    renderSelectedAttachments() {
        if (!this.selectedAttachmentsContainer) return;

        if (this.selectedAttachments.length === 0) {
            this.selectedAttachmentsContainer.style.display = 'none';
            return;
        }

        this.selectedAttachmentsContainer.style.display = 'flex';
        
        const typeIcons = {
            'workflow': 'fa-project-diagram'
        };

        this.selectedAttachmentsContainer.innerHTML = this.selectedAttachments.map(att => `
            <span class="selected-attachment-tag" data-type="${att.type}" data-id="${att.id}">
                <i class="fas ${typeIcons[att.type] || 'fa-file'}"></i>
                ${this.escapeHtml(att.name)}
                <i class="fas fa-times remove-attachment"></i>
            </span>
        `).join('');

        // 绑定移除事件
        this.selectedAttachmentsContainer.querySelectorAll('.remove-attachment').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const tag = btn.closest('.selected-attachment-tag');
                const type = tag.dataset.type;
                const id = parseInt(tag.dataset.id);
                this.removeAttachment(type, id);
            });
        });
    }

    /**
     * 移除附件
     */
    removeAttachment(type, id) {
        this.selectedAttachments = [];
        this.updateAttachmentBadge();
        this.renderSelectedAttachments();
        
        // 如果面板打开，重新渲染内容列表
        if (this.attachmentPanelVisible && this.currentAttachmentType) {
            this.loadAttachmentContent(this.currentAttachmentType);
        }
    }

    /**
     * 清空已选附件
     */
    clearSelectedAttachments() {
        this.selectedAttachments = [];
        this.updateAttachmentBadge();
        this.renderSelectedAttachments();
    }

    /**
     * 获取附件格式化内容（发送消息时调用）
     */
    async getFormattedAttachmentContent() {
        if (this.selectedAttachments.length === 0) {
            return '';
        }

        try {
            const response = await fetch('/api/agent/attachments/format/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken
                },
                body: JSON.stringify({
                    attachments: this.selectedAttachments
                })
            });

            if (!response.ok) {
                throw new Error('格式化附件失败');
            }

            const data = await response.json();
            return data.formatted_content;
        } catch (error) {
            console.error('获取附件内容失败:', error);
            return '';
        }
    }

    // ==========================================
    // 流式状态管理（刷新恢复）
    // ==========================================

    /**
     * 获取流式状态存储键
     */
    getStreamingStateKey() {
        return `agent_streaming_${this.userId}_${this.sessionId}`;
    }

    /**
     * 保存流式状态到 localStorage
     */
    saveStreamingState() {
        try {
            const state = {
                isActive: this.isStreamingActive,
                content: this.streamingContent,
                timestamp: Date.now(),
                sessionId: this.sessionId
            };
            const key = this.getStreamingStateKey();
            localStorage.setItem(key, JSON.stringify(state));
            console.log('💾 保存流式状态:', {
                key: key,
                isActive: state.isActive,
                contentLength: state.content.length,
                sessionId: state.sessionId
            });
        } catch (error) {
            console.error('保存流式状态失败:', error);
        }
    }

    /**
     * 清除流式状态
     */
    clearStreamingState() {
        try {
            localStorage.removeItem(this.getStreamingStateKey());
            console.log('🧹 清除流式状态');
        } catch (error) {
            console.error('清除流式状态失败:', error);
        }
    }

    /**
     * 恢复流式状态（页面刷新后调用）
     */
    restoreStreamingState() {
        try {
            const key = this.getStreamingStateKey();
            const stateJson = localStorage.getItem(key);
            
            // 调试：列出所有相关的 localStorage 键
            console.log('🔍 检查流式状态:', {
                key: key,
                hasState: !!stateJson,
                userId: this.userId,
                sessionId: this.sessionId
            });
            
            // 调试：显示所有 agent_streaming_ 开头的键
            const allKeys = [];
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                if (k.startsWith('agent_streaming_')) {
                    allKeys.push({
                        key: k,
                        length: localStorage.getItem(k)?.length || 0
                    });
                }
            }
            if (allKeys.length > 0) {
                console.log('📋 localStorage 中的流式状态键:', allKeys);
            }
            
            if (!stateJson) {
                console.log('ℹ️ 无需恢复流式状态');
                return;
            }

            const state = JSON.parse(stateJson);
            console.log('📦 读取到状态:', {
                isActive: state.isActive,
                contentLength: state.content?.length || 0,
                timestamp: new Date(state.timestamp).toLocaleString(),
                sessionId: state.sessionId
            });
            
            // 检查状态是否过期（超过 5 分钟则认为无效）
            const now = Date.now();
            const age = now - state.timestamp;
            if (age > 5 * 60 * 1000) {
                console.log('⏰ 流式状态已过期，清除', { ageMinutes: (age / 60000).toFixed(1) });
                this.clearStreamingState();
                return;
            }

            // 检查会话 ID 是否匹配
            if (state.sessionId !== this.sessionId) {
                console.log('🔄 会话 ID 不匹配，清除旧状态', {
                    expected: this.sessionId,
                    got: state.sessionId
                });
                this.clearStreamingState();
                return;
            }

            // 恢复流式状态（移除对 content 非空的要求）
            if (state.isActive) {
                console.log('🔄 开始恢复流式状态:', {
                    contentLength: state.content?.length || 0,
                    hasContent: !!state.content
                });
                
                // 检查是否已存在流式消息元素
                let streamMsg = document.getElementById('streamingMessage');
                if (!streamMsg) {
                    // 创建流式消息元素
                    streamMsg = document.createElement('div');
                    streamMsg.className = 'agent-message agent-message streaming';
                    streamMsg.id = 'streamingMessage';
                    
                    // 如果有内容则显示，否则显示等待提示
                    const contentHtml = state.content ? 
                        this.formatContent(state.content) : 
                        '<span class="text-muted">正在思考...</span>';
                    
                    streamMsg.innerHTML = `
                        <div class="message-avatar">
                            <i class="fas fa-robot"></i>
                        </div>
                        <div class="message-body">
                            <div class="message-content">${contentHtml}</div>
                            <div class="message-meta">
                                <span class="text-muted" style="font-size: 0.85em;">
                                    <i class="fas fa-sync fa-spin"></i> 已恢复流式回复${state.content ? '（' + state.content.length + ' 字符）' : ''}，继续接收中...
                                </span>
                            </div>
                        </div>
                    `;
                    this.messagesContainer.appendChild(streamMsg);
                    this.scrollToBottom();
                    console.log('✅ 流式消息 DOM 元素已创建');
                }

                // 恢复状态变量
                this.isStreamingActive = true;
                this.streamingContent = state.content || '';
                this.isProcessing = true;
                this.updateSendButton();
                
                // 显示恢复提示
                const contentInfo = state.content ? 
                    `，已恢复 ${state.content.length} 字符` : '';
                this.showNotification(`已恢复流式回复${contentInfo}`, 'info');
                
                console.log('✅ 流式状态恢复完成', {
                    isStreamingActive: this.isStreamingActive,
                    contentLength: this.streamingContent.length,
                    isProcessing: this.isProcessing
                });
                
                // 【关键】恢复后立即检查后端状态
                this.checkStreamingStatusAfterRestore();
                
                // 【关键】设置超时保护，避免无限等待
                // 注意：工具调用可能需要较长时间，所以设置 30 秒
                // 超时时先检查状态，而不是直接强制结束
                this.streamingRestoreTimeout = setTimeout(async () => {
                    if (this.isStreamingActive && document.getElementById('streamingMessage')) {
                        console.log('⏰ 流式恢复超时（30秒），检查状态...');
                        
                        // 超时时先检查一次状态
                        try {
                            const response = await fetch(`/api/agent/history/?session_id=${encodeURIComponent(this.sessionId)}`, {
                                headers: {'X-CSRFToken': this.csrfToken}
                            });
                            
                            if (response.ok) {
                                const data = await response.json();
                                const messages = data.messages || [];
                                
                                if (messages.length > 0) {
                                    const lastMsg = messages[messages.length - 1];
                                    
                                    // 如果最后一条是完整的 assistant 消息，才强制结束
                                    if (lastMsg.role === 'assistant' && lastMsg.content && !lastMsg.tool_calls) {
                                        console.log('✅ 确认后端已完成，执行强制同步');
                                        this.forceEndStreamingWithSync();
                                    } else {
                                        console.log('⏳ 后端仍在处理中，继续等待', {
                                            lastRole: lastMsg.role,
                                            hasToolCalls: !!lastMsg.tool_calls
                                        });
                                        
                                        // 延长超时时间，再等待 30 秒
                                        this.streamingRestoreTimeout = setTimeout(() => {
                                            if (this.isStreamingActive) {
                                                console.log('⏰ 二次超时，强制同步');
                                                this.forceEndStreamingWithSync();
                                            }
                                        }, 30000);
                                    }
                                }
                            } else {
                                // API 失败，保守起见不结束
                                console.warn('⚠️ 状态检查失败，继续等待');
                            }
                        } catch (error) {
                            console.error('超时检查失败:', error);
                            // 出错时不结束，让用户手动刷新
                        }
                    }
                }, 30000); // 30 秒超时
            } else {
                // 状态无效（isActive 为 false），清除
                console.log('❌ 状态无效，isActive =', state.isActive);
                this.clearStreamingState();
            }
        } catch (error) {
            console.error('恢复流式状态失败:', error);
            this.clearStreamingState();
        }
    }

    /**
     * 恢复后检查后端流式状态
     * 如果后端已经完成回复，立即同步并结束流式显示
     */
    async checkStreamingStatusAfterRestore() {
        try {
            console.log('🔍 检查后端流式状态...');
            
            // 等待 WebSocket 连接稳定（最多等待 2 秒）
            let waitCount = 0;
            while (!this.isConnected && waitCount < 20) {
                await new Promise(resolve => setTimeout(resolve, 100));
                waitCount++;
            }
            
            if (!this.isConnected) {
                console.log('⚠️ WebSocket 未连接，无法检查状态');
                return;
            }
            
            // 方案1: 先通过 API 查询历史消息，判断是否真的完成
            try {
                const response = await fetch(`/api/agent/history/?session_id=${encodeURIComponent(this.sessionId)}`, {
                    headers: {'X-CSRFToken': this.csrfToken}
                });
                
                if (response.ok) {
                    const data = await response.json();
                    const messages = data.messages || [];
                    
                    // 检查最后一条消息
                    if (messages.length > 0) {
                        const lastMsg = messages[messages.length - 1];
                        
                        // 如果最后一条是完整的 assistant 消息（不是 tool），说明真的完成了
                        if (lastMsg.role === 'assistant' && lastMsg.content && !lastMsg.tool_calls) {
                            console.log('✅ 确认后端已完成（最后消息是完整的 assistant 回复）');
                            this.forceEndStreamingWithSync();
                            return;
                        } else {
                            console.log('⏳ 后端可能还在处理（最后消息不是完整回复）', {
                                role: lastMsg.role,
                                hasContent: !!lastMsg.content,
                                hasToolCalls: !!lastMsg.tool_calls
                            });
                        }
                    }
                }
            } catch (error) {
                console.warn('查询历史消息失败:', error);
            }
            
            // 方案2: 仍然通过 WebSocket 查询（作为辅助）
            this.socket.send(JSON.stringify({
                type: 'check_status',
                session_id: this.sessionId
            }));
            
            console.log('✅ 已发送状态查询请求');
        } catch (error) {
            console.error('检查后端状态失败:', error);
        }
    }

    /**
     * 强制结束流式状态并同步最新消息
     */
    async forceEndStreamingWithSync() {
        try {
            console.log('🔄 强制结束流式状态，同步最新消息...');
            
            const streamMsg = document.getElementById('streamingMessage');
            if (streamMsg) {
                // 移除"继续接收中"的提示
                const metaDiv = streamMsg.querySelector('.message-meta');
                if (metaDiv) {
                    metaDiv.remove();
                }
                
                // 移除 streaming 类和 ID
                streamMsg.classList.remove('streaming');
                streamMsg.id = '';
                
                // 添加"已同步"标记
                const body = streamMsg.querySelector('.message-body');
                if (body) {
                    body.insertAdjacentHTML('beforeend', 
                        '<div class="message-meta"><span class="text-muted" style="font-size: 0.85em;">✓ 已同步</span></div>'
                    );
                }
            }
            
            // 清除状态
            this.isStreamingActive = false;
            this.streamingContent = '';
            this.isProcessing = false;
            this.clearStreamingState();
            this.updateSendButton();
            
            // 重新加载历史消息以获取完整内容
            console.log('🔄 重新加载历史消息...');
            await this.loadHistory();
            
            console.log('✅ 流式状态已强制结束并同步');
        } catch (error) {
            console.error('强制结束流式状态失败:', error);
        }
    }
}

// 全局变量，在 HTML 中初始化
let agentChat = null;
