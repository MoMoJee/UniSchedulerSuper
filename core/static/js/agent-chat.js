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
        this.clearBtn = document.getElementById('agentClearBtn');
        // 文件上传元素
        this.attachmentUploadZone = document.getElementById('attachmentUploadZone');
        this.attachmentUploadBackBtn = document.getElementById('attachmentUploadBackBtn');
        this.uploadDropzone = document.getElementById('uploadDropzone');
        this.fileUploadInput = document.getElementById('fileUploadInput');
        this.uploadProgress = document.getElementById('uploadProgress');
        this.uploadProgressText = document.getElementById('uploadProgressText');
        // 附件状态（多选）
        this.selectedAttachments = [];  // [{type, id, name, sa_id?}] 支持多个
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
        this.isToolCallInProgress = false; // 是否有工具调用正在进行
        
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
            // MCP - 地图服务
            'amap_search': '搜索地点',
            'amap_weather': '查询天气',
            'amap_route': '规划路线',
            // 联网搜索
            'web_search': '简单搜索',
            'web_search_advanced': '高级搜索'
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
        
        // 加载草稿
        this.loadDraft();
        
        // 加载可用工具列表（必须等待完成，因为后续 WebSocket 连接需要工具列表）
        await this.loadAvailableTools();
        
        // 连接 WebSocket（现在 activeTools 已经准备好了）
        this.connect();
        
        // 加载历史消息
        this.loadHistory().then(() => {
            // 加载完成后更新新建按钮状态
            this.updateNewSessionButton();
            
            // 检查是否正在命名中
            const isNaming = localStorage.getItem(`naming_${this.sessionId}`) === 'true';
            
            if (isNaming) {
                // 如果正在命名，先恢复命名状态
                // 流式状态也要保留（但不显示UI），等命名结束后继续
                this.restoreNamingState();
                // 恢复流式状态的内部变量（不显示UI）
                this.restoreStreamingStateVariables();
            } else {
                // 【关键】检查并恢复流式回复状态（必须在 loadHistory 之后）
                this.restoreStreamingState();
            }
            
            // 【关键】检查并恢复递归限制状态（在流式状态之后）
            this.restoreRecursionLimitState();
            
            // 加载上下文使用情况
            this.updateContextUsageBar();
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
    // 本地持久化 (Draft)
    // ==========================================

    /**
     * 保存草稿到 localStorage
     */
    saveDraft() {
        if (!this.userId) return;
        const draft = {
            text: this.inputField ? this.inputField.value : '',
            attachments: this.selectedAttachments || [],
            timestamp: Date.now()
        };
        try {
            localStorage.setItem(`agent_draft_${this.userId}`, JSON.stringify(draft));
        } catch (e) {
            console.warn('保存草稿失败:', e);
        }
    }

    /**
     * 加载草稿
     */
    loadDraft() {
        if (!this.userId) return;
        try {
            const draftJson = localStorage.getItem(`agent_draft_${this.userId}`);
            if (!draftJson) return;

            const draft = JSON.parse(draftJson);
            
            // 恢复文本
            if (draft.text && this.inputField) {
                this.inputField.value = draft.text;
                this.autoResize();
                this.updateSendButton();
            }

            // 恢复附件
            if (draft.attachments && Array.isArray(draft.attachments) && draft.attachments.length > 0) {
                this.selectedAttachments = draft.attachments;
                this.updateAttachmentBadge();
                this.renderSelectedAttachments();
                this.updateSendButton();
            }
        } catch (e) {
            console.warn('加载草稿失败:', e);
        }
    }

    /**
     * 清除草稿
     */
    clearDraft() {
        if (!this.userId) return;
        
        // 清除 localStorage
        localStorage.removeItem(`agent_draft_${this.userId}`);
        
        // 清除 UI
        if (this.inputField) {
            this.inputField.value = '';
            this.autoResize();
        }
        this.clearSelectedAttachments();
        this.updateSendButton();
        this.showNotification('内容已清除', 'info');
    }

    // ==========================================
    // 事件绑定
    // ==========================================

    /**
     * 绑定所有事件
     */
    bindEvents() {
        // 清除按钮
        if (this.clearBtn) {
            this.clearBtn.addEventListener('click', () => this.clearDraft());
        }

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
            this.saveDraft();
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
        
        // 文件上传区返回按钮
        if (this.attachmentUploadBackBtn) {
            this.attachmentUploadBackBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.showAttachmentTypeList();
            });
        }
        
        // 文件上传 - 点击选择
        if (this.uploadDropzone) {
            this.uploadDropzone.addEventListener('click', () => {
                if (this.fileUploadInput) this.fileUploadInput.click();
            });
            // 拖拽支持
            this.uploadDropzone.addEventListener('dragover', (e) => {
                e.preventDefault();
                this.uploadDropzone.classList.add('dragover');
            });
            this.uploadDropzone.addEventListener('dragleave', () => {
                this.uploadDropzone.classList.remove('dragover');
            });
            this.uploadDropzone.addEventListener('drop', (e) => {
                e.preventDefault();
                this.uploadDropzone.classList.remove('dragover');
                const files = e.dataTransfer.files;
                if (files.length > 0) this.handleFileUpload(files[0]);
            });
        }
        if (this.fileUploadInput) {
            this.fileUploadInput.addEventListener('change', (e) => {
                if (e.target.files.length > 0) {
                    this.handleFileUpload(e.target.files[0]);
                    e.target.value = ''; // 允许重复选择同一文件
                }
            });
        }
        
        // 全局文件拖拽支持 - 整个 Agent 面板区域
        const agentPanelEl = document.querySelector('.agent-panel-content');
        if (agentPanelEl) {
            let dragCounter = 0;
            agentPanelEl.addEventListener('dragenter', (e) => {
                const hasFiles = e.dataTransfer && e.dataTransfer.types.includes('Files');
                const hasInternal = e.dataTransfer && e.dataTransfer.types.includes('application/x-unischeduler-element');
                if (!hasFiles && !hasInternal) return;
                e.preventDefault();
                dragCounter++;
                if (dragCounter === 1) {
                    agentPanelEl.classList.add(hasInternal ? 'element-drag-over' : 'file-drag-over');
                }
            });
            agentPanelEl.addEventListener('dragover', (e) => {
                const hasFiles = e.dataTransfer && e.dataTransfer.types.includes('Files');
                const hasInternal = e.dataTransfer && e.dataTransfer.types.includes('application/x-unischeduler-element');
                if (!hasFiles && !hasInternal) return;
                e.preventDefault();
                e.dataTransfer.dropEffect = 'copy';
            });
            agentPanelEl.addEventListener('dragleave', (e) => {
                const hasFiles = e.dataTransfer && e.dataTransfer.types.includes('Files');
                const hasInternal = e.dataTransfer && e.dataTransfer.types.includes('application/x-unischeduler-element');
                if (!hasFiles && !hasInternal) return;
                dragCounter--;
                if (dragCounter <= 0) {
                    dragCounter = 0;
                    agentPanelEl.classList.remove('file-drag-over', 'element-drag-over');
                }
            });
            agentPanelEl.addEventListener('drop', (e) => {
                const hasFiles = e.dataTransfer && e.dataTransfer.types.includes('Files');
                const hasInternal = e.dataTransfer && e.dataTransfer.types.includes('application/x-unischeduler-element');
                if (!hasFiles && !hasInternal) return;
                e.preventDefault();
                e.stopPropagation();
                dragCounter = 0;
                agentPanelEl.classList.remove('file-drag-over', 'element-drag-over');
                if (hasFiles) {
                    // 文件拖拽：先打开附件面板进入上传区（显示进度），再上传
                    this.showAttachmentPanel();
                    this.showUploadZone();
                    const files = e.dataTransfer.files;
                    if (files.length > 0) this.handleFileUpload(files[0]);
                } else if (hasInternal) {
                    // 内部元素（Todo/Reminder）拖入附加到对话
                    try {
                        const rawData = e.dataTransfer.getData('text/plain');
                        const data = JSON.parse(rawData);
                        if (data.type && data.id !== undefined && data.title !== undefined) {
                            this.toggleAttachmentMulti(data.type, String(data.id), data.title);
                            this.showNotification(`已附加${data.type === 'todo' ? '待办' : '提醒'}: ${data.title}`, 'success');
                        }
                    } catch (err) {
                        console.error('[AgentPanel] 解析内部元素拖拽数据失败:', err);
                    }
                }
            });

            // 监听 FullCalendar 事件拖入（通过 eventDragStop 分发的自定义事件）
            agentPanelEl.addEventListener('fcEventDropped', (e) => {
                const data = e.detail;
                if (data && data.type && data.id !== undefined && data.title !== undefined) {
                    this.toggleAttachmentMulti(data.type, String(data.id), data.title);
                    this.showNotification(`已附加${data.type === 'reminder' ? '提醒' : '日程'}: ${data.title}`, 'success');
                }
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
        // 始终传递 active_tools 参数，即使为空（空字符串表示不启用任何工具）
        wsUrl += `&active_tools=${encodeURIComponent(this.activeTools.join(','))}`;
        
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
     * 生成消息指纹用于去重
     * @param {Object} data - 消息数据
     * @returns {string} 消息指纹
     */
    generateMessageFingerprint(data) {
        // 根据消息类型生成不同的指纹
        const type = data.type;
        let content = '';
        
        switch (type) {
            case 'tool_call':
                content = `${data.name}|${JSON.stringify(data.args)}`;
                break;
            case 'tool_result':
                content = `${data.name}|${data.result?.substring(0, 100) || ''}`;
                break;
            case 'stream_chunk':
                content = data.content?.substring(0, 50) || '';
                break;
            case 'message':
            case 'response':
                content = data.content?.substring(0, 100) || data.message?.substring(0, 100) || '';
                break;
            case 'finished':
                content = `${data.message_count || ''}`;
                break;
            default:
                content = JSON.stringify(data).substring(0, 100);
        }
        
        return `${type}:${content}`;
    }

    /**
     * 检查消息是否重复（用于处理channel_layer广播导致的重复消息）
     * @param {Object} data - 消息数据
     * @returns {boolean} 是否重复
     */
    isMessageDuplicate(data) {
        // 初始化去重缓存
        if (!this.recentMessages) {
            this.recentMessages = new Map();
        }
        
        const fingerprint = this.generateMessageFingerprint(data);
        const now = Date.now();
        
        // 清理过期的指纹（超过500ms的）
        for (const [key, timestamp] of this.recentMessages.entries()) {
            if (now - timestamp > 500) {
                this.recentMessages.delete(key);
            }
        }
        
        // 检查是否存在相同指纹
        if (this.recentMessages.has(fingerprint)) {
            console.log(`🔄 跳过重复消息: ${data.type}`);
            return true;
        }
        
        // 记录新指纹
        this.recentMessages.set(fingerprint, now);
        return false;
    }

    /**
     * 处理收到的 WebSocket 消息
     */
    handleMessage(data) {
        console.log('收到消息:', data);
        
        // 【关键】消息去重：channel_layer广播可能导致消息被接收两次
        // 对于某些消息类型进行去重处理
        const deduplicateTypes = ['tool_call', 'tool_result', 'stream_start', 'stream_chunk', 'stream_end', 'finished'];
        if (deduplicateTypes.includes(data.type) && this.isMessageDuplicate(data)) {
            return; // 跳过重复消息
        }
        
        switch (data.type) {
            case 'connected':
                console.log('Agent 连接成功:', data.message);
                // 同步服务器端的消息数量
                if (data.message_count !== undefined) {
                    this.messageCount = data.message_count;
                    console.log('📊 同步消息计数:', this.messageCount);
                }
                // 【关键】同步命名状态（根据后端实际状态决定是否显示/清除命名提示）
                this.syncNamingState(data.is_naming, data.session_name);
                break;
            
            case 'processing':
                this.isProcessing = true;
                this.updateSendButton();
                this.showTyping();
                break;
            
            case 'message':
            case 'response':
                this.hideTyping();
                // 【修复】只有在没有进行流式传输时才添加消息
                // 如果isStreamingActive或刚结束流式(finished后短时间内)，说明内容已通过stream_chunk显示
                const existingStreamMsg = document.getElementById('streamingMessage');
                
                // 如果正在流式传输，跳过
                if (this.isStreamingActive || existingStreamMsg) {
                    console.log('⏭️ 跳过重复的 message/response 事件（正在流式传输）');
                    break;
                }
                
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
                // 根据后端返回的 refresh 字段刷新对应数据
                if (data.refresh && Array.isArray(data.refresh) && data.refresh.length > 0) {
                    console.log('🔄 工具执行完成，刷新数据:', data.refresh);
                    this.refreshData(data.refresh);
                }
                break;
            
            case 'finished':
                this.hideTyping();
                this.isProcessing = false;
                this.isToolCallInProgress = false; // 重置工具调用状态
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
                
                // 【关键】清除递归限制状态
                this.clearRecursionLimitState();
                
                // 更新上下文使用量条形图
                this.updateContextUsageBar();
                
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
                // 【关键】错误时清除递归限制状态
                this.clearRecursionLimitState();
                break;
                
            case 'quota_exceeded':
                // 配额超额，不允许发送新消息
                this.hideTyping();
                this.isProcessing = false;
                this.updateSendButton();
                this.showQuotaExceededMessage(data);
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
                // 【关键】停止时清除递归限制状态
                this.clearRecursionLimitState();
                break;
                
            case 'recursion_limit':
                // 达到递归限制，询问用户是否继续
                console.log('🚨 收到递归限制消息:', data);
                this.hideTyping();
                this.isProcessing = false;
                this.updateSendButton();
                this.showRecursionLimitMessage(data.message || '工具调用次数达到上限，是否继续执行？');
                // 【关键】保存递归限制状态，以便刷新后恢复
                this.saveRecursionLimitState(data.message || '工具调用次数达到上限，是否继续执行？');
                console.log('✅ 递归限制按钮已显示');
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
            
            // ========== 历史总结相关消息 ==========
            case 'summarizing_start':
                // 开始执行历史总结
                console.log('📝 开始历史总结:', data.message);
                this.showSummarizingIndicator(data.message || '正在总结对话历史...');
                break;
            
            case 'summarizing_end':
                // 历史总结完成
                console.log('📝 历史总结完成:', data);
                this.hideSummarizingIndicator();
                if (data.success) {
                    this.showSummaryDivider(data.summary, data.summarized_until, data.summary_tokens);
                    // 总结完成后更新上下文使用量条形图
                    this.updateContextUsageBar();
                } else {
                    console.warn('历史总结失败:', data.message);
                }
                break;
            
            // ========== 会话命名相关消息 ==========
            case 'naming_start':
                // 开始自动命名
                console.log('✏️ 开始自动命名:', data.session_id);
                // 隐藏打字指示器，显示命名提示
                this.hideTyping();
                this.showNamingIndicator(data.session_id);
                break;
            
            case 'naming_end':
                // 命名完成
                console.log('✏️ 命名完成:', data);
                this.hideNamingIndicator(data.session_id, data.name);
                // 命名完成后，恢复打字指示器（等待流式回复）
                this.showTyping();
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
        this.saveDraft();
        this.autoResize();
        this.updateSendButton();
        
        // 隐藏欢迎消息
        const welcome = this.messagesContainer.querySelector('.agent-welcome');
        if (welcome) welcome.style.display = 'none';
        
        // 获取附件内容（如果有）
        let attachmentIds = [];
        let attachmentsList = [];  // 用于前端显示磁贴
        if (this.selectedAttachments.length > 0) {
            const attachmentResult = await this.getFormattedAttachmentContent();
            attachmentIds = attachmentResult.sa_ids || [];
            // 保存附件列表供前端渲染磁贴
            attachmentsList = this.selectedAttachments.map(att => ({
                sa_id: att.sa_id,
                type: att.type,
                id: att.id || att.internal_id,
                name: att.name,
                filename: att.filename || att.name,
                thumbnail_url: att.thumbnail_url,
                file_url: att.file_url || (att._full_data && att._full_data.file_url),
                mime_type: att.mime_type,
                internal_type: att.internal_type
            }));
            // 清空已选附件
            this.clearSelectedAttachments();
        }
        
        // 添加用户消息（带消息索引 - 这是后端 LangGraph 中的索引）
        // messageCount 在发送前表示后端消息列表的当前长度，也就是新消息的索引
        const currentIndex = this.messageCount;
        // 显示纯用户文本 + 附件磁贴，前端立即渲染
        this.addMessage(message, 'user', {attachments: attachmentsList}, currentIndex);
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
        
        // 发送到 WebSocket（包含 attachment_ids 用于多模态消息）
        const wsPayload = {
            type: 'message',
            content: message  // 只发送纯用户文本，附件上下文由后端从 SessionAttachment 重新构建
        };
        if (attachmentIds.length > 0) {
            wsPayload.attachment_ids = attachmentIds;
        }
        this.socket.send(JSON.stringify(wsPayload));
        
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
        // 【关键】清除递归限制状态
        this.clearRecursionLimitState();
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
        
        // 存储附件数据（用于回滚恢复）
        if (metadata.attachments && metadata.attachments.length > 0) {
            messageDiv.dataset.attachments = JSON.stringify(metadata.attachments);
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
        
        // 渲染附件磁贴（如果有）
        const attachmentsHtml = metadata.attachments ? this.renderAttachmentTiles(metadata.attachments) : '';
        
        messageDiv.innerHTML = `
            <div class="message-avatar ${avatarClass}">
                <i class="fas fa-${avatar}"></i>
            </div>
            <div class="message-body">
                <div class="message-content">${this.formatContent(content, metadata.attachments && metadata.attachments.length > 0)}</div>
                ${attachmentsHtml}
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
     * 构建包含附件的显示内容（多模态格式）
     * 用于发送时立即显示，格式与后端返回的一致
     */
    buildDisplayContentWithAttachments(message, attachments) {
        const imageAtts = attachments.filter(a => a.type === 'image' && a.thumbnail_url);
        
        if (imageAtts.length === 0) {
            // 无图片附件，返回纯文本
            return message;
        }
        
        // 构建多模态数组（与后端格式一致）
        const content = [];
        
        // 添加文本块
        if (message && message.trim()) {
            content.push({
                type: 'text',
                text: message
            });
        }
        
        // 添加图片块（使用缩略图 URL）
        imageAtts.forEach(att => {
            content.push({
                type: 'image_url',
                image_url: {
                    url: att.thumbnail_url,
                    detail: 'auto'
                }
            });
        });
        
        return content;
    }

    /**
     * 从多模态 content（array）中提取纯文本部分
     */
    extractTextFromContent(content) {
        if (!content) return '';
        if (typeof content === 'string') return content;
        if (Array.isArray(content)) {
            return content
                .filter(b => b && b.type === 'text')
                .map(b => b.text || '')
                .join('\n');
        }
        return String(content);
    }

    /**
     * 从多模态 content（array）中提取图片 URL 列表
     */
    extractImagesFromContent(content) {
        if (!Array.isArray(content)) return [];
        return content
            .filter(b => b && b.type === 'image_url' && b.image_url)
            .map(b => b.image_url.url || '');
    }

    /**
     * 格式化消息内容（完整 Markdown 解析）
     * 支持：标题、列表、表格、代码块、行内代码、粗体、斜体、链接、引用、分隔线、脚注、数学公式等
     * 支持：多模态消息中的图片内联预览
     * @param {string|Array} content - 消息内容（string 或多模态 array）
     * @param {boolean} skipImages - 如果为 true，则不从多模态 content 中提取图片（避免与 attachments tiles 重复）
     */
    formatContent(content, skipImages = false) {
        if (!content) return '';

        // 多模态消息处理（content 为 array）
        let imageHtml = '';
        if (Array.isArray(content)) {
            if (!skipImages) {
                const images = this.extractImagesFromContent(content);
                if (images.length > 0) {
                    imageHtml = '<div class="message-images">' +
                        images.map(url =>
                            `<div class="message-image-wrapper">` +
                            `<img src="${this.escapeHtml(url)}" class="message-image" ` +
                            `alt="附件图片" loading="lazy" ` +
                            `onclick="agentChat.showImagePreview(this.src)" />` +
                            `</div>`
                        ).join('') + '</div>';
                }
            }
            // 无论是否跳过图片，都需要将数组转换为纯文本
            content = this.extractTextFromContent(content);
        }

        if (typeof content !== 'string') {
            content = String(content);
        }

        let html = content;
        const footnotes = {}; // 存储脚注
        
        // 1. 转义 HTML 特殊字符（避免 XSS）
        html = html
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
        
        // 2. 提取并保存脚注定义 [^1]: 注释内容
        html = html.replace(/^\[\^(\w+)\]:\s*(.+)$/gm, (match, id, text) => {
            footnotes[id] = text;
            return ''; // 移除脚注定义
        });
        
        // 3. 处理数学公式块（$$...$$）- 必须在代码块之前
        html = html.replace(/\$\$([\s\S]*?)\$\$/g, (match, formula) => {
            return `<div class="math-block" data-formula="${this.escapeHtml(formula.trim())}">\\[${formula.trim()}\\]</div>`;
        });
        
        // 4. 处理行内数学公式（$...$）
        html = html.replace(/\$([^\$\n]+?)\$/g, (match, formula) => {
            return `<span class="math-inline" data-formula="${this.escapeHtml(formula.trim())}">\\(${formula.trim()}\\)</span>`;
        });
        
        // 5. 处理代码块（```）- 必须在其他处理之前
        html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, code) => {
            const language = lang || 'plaintext';
            return `<pre><code class="language-${language}">${code.trim()}</code></pre>`;
        });
        
        // 6. 处理表格（| col1 | col2 |）
        html = html.replace(/^\|(.+)\|\n\|[\s\-:|]+\|\n((?:\|.+\|\n?)+)/gm, (match, header, rows) => {
            // 解析表头
            const headers = header.split('|').map(h => h.trim()).filter(h => h);
            const headerHtml = '<thead><tr>' + headers.map(h => `<th>${h}</th>`).join('') + '</tr></thead>';
            
            // 解析行
            const rowsArray = rows.trim().split('\n');
            const rowsHtml = '<tbody>' + rowsArray.map(row => {
                const cells = row.split('|').map(c => c.trim()).filter(c => c);
                return '<tr>' + cells.map(c => `<td>${c}</td>`).join('') + '</tr>';
            }).join('') + '</tbody>';
            
            return `<table class="markdown-table">${headerHtml}${rowsHtml}</table>`;
        });
        
        // 7. 处理标题（# ## ### 等）
        html = html.replace(/^#{6}\s+(.+)$/gm, '<h6>$1</h6>');
        html = html.replace(/^#{5}\s+(.+)$/gm, '<h5>$1</h5>');
        html = html.replace(/^#{4}\s+(.+)$/gm, '<h4>$1</h4>');
        html = html.replace(/^#{3}\s+(.+)$/gm, '<h3>$1</h3>');
        html = html.replace(/^#{2}\s+(.+)$/gm, '<h2>$1</h2>');
        html = html.replace(/^#{1}\s+(.+)$/gm, '<h1>$1</h1>');
        
        // 8. 处理引用块（> 开头）
        html = html.replace(/^&gt;\s+(.+)$/gm, '<blockquote>$1</blockquote>');
        // 合并连续的 blockquote
        html = html.replace(/<\/blockquote>\n<blockquote>/g, '<br>');
        
        // 9. 处理无序列表（- 或 * 开头）
        html = html.replace(/^[\-\*]\s+(.+)$/gm, '<li>$1</li>');
        // 包裹在 ul 标签中
        html = html.replace(/(<li>.*<\/li>)/s, (match) => {
            return '<ul>' + match + '</ul>';
        });
        // 合并连续的 ul
        html = html.replace(/<\/ul>\n<ul>/g, '');
        
        // 10. 处理有序列表（1. 2. 3. 开头）
        html = html.replace(/^\d+\.\s+(.+)$/gm, '<li>$1</li>');
        // 如果有序列表项没有被无序列表包裹，则包裹在 ol 中
        html = html.replace(/(?<!<ul>)(<li>.*<\/li>)(?!<\/ul>)/gs, (match) => {
            if (!match.includes('<ul>')) {
                return '<ol>' + match + '</ol>';
            }
            return match;
        });
        // 合并连续的 ol
        html = html.replace(/<\/ol>\n<ol>/g, '');
        
        // 11. 处理分隔线（--- 或 ***）
        html = html.replace(/^[\-\*]{3,}$/gm, '<hr>');
        
        // 12. 处理粗斜体（*** 或 ___）
        html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
        html = html.replace(/___(.+?)___/g, '<strong><em>$1</em></strong>');
        
        // 13. 处理粗体（** 或 __）
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/__(.+?)__/g, '<strong>$1</strong>');
        
        // 14. 处理斜体（* 或 _）
        html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
        html = html.replace(/_(.+?)_/g, '<em>$1</em>');
        
        // 15. 处理删除线（~~）
        html = html.replace(/~~(.+?)~~/g, '<del>$1</del>');
        
        // 16. 处理行内代码（`）
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
        
        // 17. 处理脚注引用 [^1]
        html = html.replace(/\[\^(\w+)\]/g, (match, id) => {
            if (footnotes[id]) {
                return `<sup class="footnote-ref"><a href="#fn-${id}" id="fnref-${id}">[${id}]</a></sup>`;
            }
            return match;
        });
        
        // 18. 处理链接 [text](url)
        html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
        
        // 19. 处理图片 ![alt](url)
        html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<img src="$2" alt="$1" style="max-width: 100%; height: auto;">');
        
        // 20. 处理换行（两个空格+换行 或 单独的换行）
        html = html.replace(/  \n/g, '<br>');
        html = html.replace(/\n/g, '<br>');
        
        // 21. 处理段落（连续的非标签行）
        // 简单处理：多个 <br> 替换为段落分隔
        html = html.replace(/(<br>){2,}/g, '</p><p>');
        html = '<p>' + html + '</p>';
        // 清理不需要 p 标签的地方
        html = html.replace(/<p><(h[1-6]|ul|ol|pre|blockquote|hr|table|div)/g, '<$1');
        html = html.replace(/<\/(h[1-6]|ul|ol|pre|blockquote|hr|table|div)><\/p>/g, '</$1>');
        html = html.replace(/<p><\/p>/g, '');
        
        // 22. 添加脚注列表（如果有）
        if (Object.keys(footnotes).length > 0) {
            let footnotesHtml = '<div class="footnotes"><hr><ol>';
            for (const [id, text] of Object.entries(footnotes)) {
                footnotesHtml += `<li id="fn-${id}">${text} <a href="#fnref-${id}" class="footnote-backref">↩</a></li>`;
            }
            footnotesHtml += '</ol></div>';
            html += footnotesHtml;
        }
        
        // 23. 触发 MathJax 渲染（如果已加载）
        setTimeout(() => {
            if (window.MathJax && window.MathJax.typesetPromise) {
                window.MathJax.typesetPromise().catch((err) => {
                    console.warn('MathJax 渲染失败:', err);
                });
            }
        }, 100);
        
        // 24. 附加多模态图片预览
        if (imageHtml) {
            html = imageHtml + html;
        }
        
        return html;
    }
    
    /**
     * 渲染附件磁贴
     * @param {Array} attachments - 附件列表
     * @returns {string} HTML 字符串
     */
    renderAttachmentTiles(attachments) {
        if (!attachments || attachments.length === 0) {
            return '';
        }
        
        // 内部元素类型集合
        const internalTypes = ['event', 'todo', 'reminder', 'workflow'];
        
        const tiles = attachments.map(att => {
            // 统一获取内部类型：
            // - 后端 history 返回: type='internal', internal_type='event'/'todo'/..., internal_id=123
            // - 前端发送时: type='event'/'todo'/... (直接就是元素类型), id=123
            const isInternal = att.type === 'internal' || internalTypes.includes(att.type);
            const elementType = att.internal_type || (internalTypes.includes(att.type) ? att.type : null);
            const elementId = att.internal_id || att.id;
            
            // 图片类型：显示缩略图
            if (att.type === 'image') {
                const thumbUrl = att.thumbnail_url;
                if (!thumbUrl) {
                    // 没有缩略图 URL（不使用 filename 作为 img src，避免 404）
                    return `
                        <div class="attachment-tile attachment-tile-file" data-sa-id="${att.sa_id || ''}">
                            <div class="attachment-tile-icon" style="color: #17a2b8;">
                                <i class="fas fa-image"></i>
                            </div>
                            <div class="attachment-tile-name">${att.filename || '图片'}</div>
                        </div>
                    `;
                }
                const previewUrl = att.file_url || thumbUrl;
                return `
                    <div class="attachment-tile attachment-tile-image" data-sa-id="${att.sa_id || ''}">
                        <img src="${this.escapeHtml(thumbUrl)}" alt="${att.filename || '图片'}" 
                             class="attachment-thumbnail" 
                             data-preview-url="${this.escapeHtml(previewUrl)}"
                             onclick="agentChat.showImagePreview(this.dataset.previewUrl)" />
                        <div class="attachment-tile-name">${att.filename || '图片'}</div>
                    </div>
                `;
            }
            
            // 内部元素类型：显示图标+名称
            if (isInternal && elementType) {
                let icon = 'file';
                let color = '#6c757d';
                
                switch (elementType) {
                    case 'event':
                        icon = 'calendar-alt';
                        color = '#007bff';
                        break;
                    case 'todo':
                        icon = 'tasks';
                        color = '#28a745';
                        break;
                    case 'reminder':
                        icon = 'bell';
                        color = '#ffc107';
                        break;
                    case 'workflow':
                        icon = 'project-diagram';
                        color = '#6f42c1';
                        break;
                }
                
                return `
                    <div class="attachment-tile attachment-tile-internal" 
                         data-sa-id="${att.sa_id || ''}" 
                         data-internal-type="${elementType}" 
                         data-internal-id="${this.escapeHtml(String(elementId))}">
                        <div class="attachment-tile-icon" style="color: ${color};">
                            <i class="fas fa-${icon}"></i>
                        </div>
                        <div class="attachment-tile-name">${att.name || att.filename || '未命名'}</div>
                    </div>
                `;
            }
            
            // 其他文件类型：根据类型显示不同图标
            const fileIcons = {
                'pdf': { icon: 'file-pdf', color: '#dc3545' },
                'word': { icon: 'file-word', color: '#2b579a' },
                'excel': { icon: 'file-excel', color: '#217346' },
            };
            const fileInfo = fileIcons[att.type] || { icon: 'file', color: '#6c757d' };
            const safeFileUrl = this.escapeHtml(att.file_url || '');
            const safeMime = this.escapeHtml(att.mime_type || '');
            const safeName = this.escapeHtml(att.filename || att.name || '文件');

            return `
                <div class="attachment-tile attachment-tile-file"
                     data-sa-id="${att.sa_id || ''}"
                     data-file-url="${safeFileUrl}"
                     data-mime-type="${safeMime}"
                     data-filename="${safeName}"
                     data-att-type="${att.type || 'file'}">
                    <div class="attachment-tile-icon" style="color: ${fileInfo.color};">
                        <i class="fas fa-${fileInfo.icon}"></i>
                    </div>
                    <div class="attachment-tile-name">${safeName}</div>
                </div>
            `;
        }).join('');
        
        const html = `<div class="message-attachment-tiles">${tiles}</div>`;
        
        // 使用 setTimeout 确保 DOM 已渲染后绑定事件委托
        setTimeout(() => {
            document.querySelectorAll('.attachment-tile-internal').forEach(tile => {
                if (tile.dataset._bound) return;
                tile.dataset._bound = '1';
                tile.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const type = tile.dataset.internalType;
                    const id = tile.dataset.internalId;
                    this.previewAttachment(type, id);
                });
            });
            // 文件类型瓦片（pdf/word/excel）点击预览
            document.querySelectorAll('.attachment-tile-file[data-file-url]').forEach(tile => {
                if (tile.dataset._bound) return;
                tile.dataset._bound = '1';
                tile.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const fileUrl = tile.dataset.fileUrl;
                    const mimeType = tile.dataset.mimeType;
                    const filename = tile.dataset.filename;
                    const attType = tile.dataset.attType;
                    if (fileUrl) {
                        this.showDocumentPreview(fileUrl, mimeType, filename, attType);
                    }
                });
            });
        }, 0);
        
        return html;
    }
    
    /**
     * 文档预览（PDF 内嵌 / Word·Excel 信息面板）
     *
     * @param {string} fileUrl  - 文件 URL（如 /media/attachments/…/foo.pdf）
     * @param {string} mimeType - MIME 类型
     * @param {string} filename - 文件名（仅用于显示）
     * @param {string} attType  - 附件类型字符串：'pdf'|'word'|'excel'
     */
    showDocumentPreview(fileUrl, mimeType, filename, attType) {
        const overlay = document.createElement('div');
        overlay.className = 'doc-preview-overlay';

        const isPdf = attType === 'pdf' || mimeType === 'application/pdf';

        const fileIcons = {
            'pdf':   { icon: 'file-pdf',   color: '#dc3545', label: 'PDF 文档' },
            'word':  { icon: 'file-word',  color: '#2b579a', label: 'Word 文档' },
            'excel': { icon: 'file-excel', color: '#217346', label: 'Excel 表格' },
        };
        const fi = fileIcons[attType] || { icon: 'file', color: '#6c757d', label: '文件' };

        if (isPdf) {
            // PDF：先构建带 loading 状态的外壳，再 fetch 成 blob URL 嵌入 iframe
            // 用 blob: URL 规避 Django 默认的 X-Frame-Options: DENY 限制
            overlay.innerHTML = `
                <div class="doc-preview-container doc-preview-pdf">
                    <div class="doc-preview-toolbar">
                        <span class="doc-preview-title">
                            <i class="fas fa-${fi.icon}" style="color:${fi.color}"></i>
                            ${this.escapeHtml(filename)}
                        </span>
                        <div class="doc-preview-actions">
                            <a href="${this.escapeHtml(fileUrl)}" download="${this.escapeHtml(filename)}"
                               class="doc-preview-btn" title="下载">
                                <i class="fas fa-download"></i> 下载
                            </a>
                            <button class="doc-preview-close" title="关闭">
                                <i class="fas fa-times"></i>
                            </button>
                        </div>
                    </div>
                    <div class="doc-preview-loading" id="docPreviewLoading">
                        <i class="fas fa-spinner fa-spin"></i> 正在加载…
                    </div>
                    <iframe class="doc-preview-iframe" id="docPreviewIframe"
                            style="display:none" type="application/pdf"></iframe>
                </div>
            `;

            // 关闭逻辑（需先挂载再设 blob 以便 cleanup）
            let blobUrl = null;
            const cleanup = () => {
                if (blobUrl) { URL.revokeObjectURL(blobUrl); blobUrl = null; }
                overlay.remove();
            };
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay || e.target.closest('.doc-preview-close')) cleanup();
            });
            const onKeyDown = (e) => {
                if (e.key === 'Escape') { cleanup(); document.removeEventListener('keydown', onKeyDown); }
            };
            document.addEventListener('keydown', onKeyDown);
            document.body.appendChild(overlay);

            // 异步 fetch → blob URL → 注入 iframe
            fetch(fileUrl, { credentials: 'same-origin' })
                .then(r => {
                    if (!r.ok) throw new Error(`HTTP ${r.status}`);
                    return r.blob();
                })
                .then(blob => {
                    blobUrl = URL.createObjectURL(blob);
                    const iframe = overlay.querySelector('#docPreviewIframe');
                    const loading = overlay.querySelector('#docPreviewLoading');
                    iframe.src = blobUrl;
                    iframe.style.display = '';
                    if (loading) loading.style.display = 'none';
                })
                .catch(err => {
                    const loading = overlay.querySelector('#docPreviewLoading');
                    if (loading) loading.innerHTML =
                        `<i class="fas fa-exclamation-circle" style="color:#dc3545"></i> 加载失败，请直接下载查看`;
                    console.error('[PDF预览] 加载失败:', err);
                });

            return; // 已自行挂载，跳过下方统一 appendChild
        } else {
            // Word / Excel：浏览器无法直接渲染，显示信息面板+下载
            overlay.innerHTML = `
                <div class="doc-preview-container doc-preview-info">
                    <div class="doc-preview-toolbar">
                        <span class="doc-preview-title">
                            <i class="fas fa-${fi.icon}" style="color:${fi.color}"></i>
                            ${this.escapeHtml(filename)}
                        </span>
                        <button class="doc-preview-close" title="关闭">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                    <div class="doc-preview-body">
                        <div class="doc-preview-icon-large">
                            <i class="fas fa-${fi.icon}" style="color:${fi.color}"></i>
                        </div>
                        <p class="doc-preview-label">${fi.label}</p>
                        <p class="doc-preview-name">${this.escapeHtml(filename)}</p>
                        <p class="doc-preview-hint">此格式无法在浏览器中直接预览</p>
                        <a href="${this.escapeHtml(fileUrl)}" download="${this.escapeHtml(filename)}"
                           class="doc-preview-btn doc-preview-download">
                            <i class="fas fa-download"></i> 下载文件
                        </a>
                    </div>
                </div>
            `;
        }

        // 关闭逻辑
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay || e.target.closest('.doc-preview-close')) {
                overlay.remove();
            }
        });
        // Esc 也可关闭
        const onKeyDown = (e) => {
            if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', onKeyDown); }
        };
        document.addEventListener('keydown', onKeyDown);
        overlay.addEventListener('remove', () => document.removeEventListener('keydown', onKeyDown));

        document.body.appendChild(overlay);
    }

    /**
     * 全屏预览图片
     */
    showImagePreview(src) {
        const overlay = document.createElement('div');
        overlay.className = 'image-preview-overlay';
        overlay.innerHTML = `
            <div class="image-preview-container">
                <img src="${src}" class="image-preview-full" alt="图片预览" />
                <button class="image-preview-close" title="关闭">
                    <i class="fas fa-times"></i>
                </button>
            </div>
        `;
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay || e.target.closest('.image-preview-close')) {
                overlay.remove();
            }
        });
        document.body.appendChild(overlay);
    }

    /**
     * HTML 转义辅助函数
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
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
        // 如果工具调用正在进行中，不把内容添加到 message-content
        // 这些内容是 AI 对工具结果的描述，应该只显示在 tool-result-indicator 中
        if (this.isToolCallInProgress) {
            console.log('🚫 工具调用进行中，跳过 stream_chunk:', content.substring(0, 50));
            return;
        }
        
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
     * 【重要】stream_end 只表示一段流式输出结束，不代表整个处理完成
     * Agent 可能在工具调用后继续回复，所以不能在这里重置 isProcessing
     * isProcessing 只在 finished、stopped、error 时才重置
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
        
        // 【修复】stream_end 不再重置 isProcessing
        // isProcessing 只在 finished、stopped、error 时才重置
        // 但发送按钮状态不需要更新，因为仍在处理中
        // this.isProcessing = false;  // 删除：不要在这里重置
        // this.updateSendButton();    // 删除：不要在这里更新按钮
        
        // 【关键】清除流式状态（但保留 isProcessing）
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
        // 【修复】检查是否已经存在相同工具的未完成调用指示器
        const existingIndicators = this.messagesContainer.querySelectorAll(`.tool-call-indicator:not(.tool-completed)[data-tool="${tool}"]`);
        if (existingIndicators.length > 0) {
            console.log(`⚠️ 工具 ${tool} 的调用指示器已存在，跳过重复创建`);
            return;
        }
        
        // 标记工具调用开始，后续的 stream_chunk 不应该显示在 message-content 中
        this.isToolCallInProgress = true;
        
        // 如果当前有流式消息正在显示，结束它
        const streamMsg = document.getElementById('streamingMessage');
        if (streamMsg) {
            const contentDiv = streamMsg.querySelector('.message-content');
            // 如果流式消息有内容，保留它；如果没有内容，删除该消息
            if (contentDiv && contentDiv.textContent.trim()) {
                // 有内容，结束流式状态但保留消息
                streamMsg.classList.remove('streaming');
                streamMsg.id = '';
            } else {
                // 没有内容，删除这个空消息
                streamMsg.remove();
            }
        }
        
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
     * 显示工具执行结果（流式传输时调用）
     */
    showToolResult(tool, result) {
        const indicators = this.messagesContainer.querySelectorAll('.tool-call-indicator:not(.tool-completed)');
        if (indicators.length > 0) {
            const lastIndicator = indicators[indicators.length - 1];
            
            // 【修复】检查该指示器是否已经被标记为完成，避免重复标记
            if (lastIndicator.classList.contains('tool-completed')) {
                console.log(`⚠️ 工具调用指示器已完成，跳过重复标记`);
            } else {
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
        
        // 显示小字形式的工具结果内容
        this.showToolResultContent(tool, result);
        
        // 标记工具调用已完成，后续的 stream_chunk 可以正常显示
        this.isToolCallInProgress = false;
    }
    
    /**
     * 显示工具结果内容（统一的可展开样式）
     */
    showToolResultContent(tool, result) {
        const friendlyName = this.toolNames[tool] || tool;
        const resultStr = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
        const isLong = resultStr.length > 100;
        const displayResult = isLong ? resultStr.substring(0, 100) + '...' : resultStr;
        
        const resultDiv = document.createElement('div');
        resultDiv.className = 'tool-result-indicator';
        resultDiv.innerHTML = `
            <i class="fas fa-reply text-info me-2"></i>
            <div class="tool-result-content">
                <span class="tool-result-text">${this.formatContent(displayResult)}</span>
                ${isLong ? `
                    <span class="tool-result-full" style="display: none;">${this.formatContent(resultStr)}</span>
                    <button class="tool-result-toggle btn btn-link btn-sm p-0 ms-1" onclick="agentChat.toggleToolResult(this)">
                        <i class="fas fa-chevron-down"></i> 展开
                    </button>
                ` : ''}
            </div>
        `;
        resultDiv.style.opacity = '0.7';
        this.messagesContainer.appendChild(resultDiv);
        this.scrollToBottom();
    }
    
    /**
     * 切换工具结果展开/收起
     */
    toggleToolResult(button) {
        const container = button.closest('.tool-result-content');
        const shortText = container.querySelector('.tool-result-text');
        const fullText = container.querySelector('.tool-result-full');
        const isExpanded = fullText.style.display !== 'none';
        
        if (isExpanded) {
            // 收起
            shortText.style.display = '';
            fullText.style.display = 'none';
            button.innerHTML = '<i class="fas fa-chevron-down"></i> 展开';
        } else {
            // 展开
            shortText.style.display = 'none';
            fullText.style.display = '';
            button.innerHTML = '<i class="fas fa-chevron-up"></i> 收起';
        }
    }
    
    // ==========================================
    // 历史总结 UI
    // ==========================================
    
    /**
     * 显示正在总结的指示器
     */
    showSummarizingIndicator(message) {
        // 移除已有的指示器
        this.hideSummarizingIndicator();
        
        const indicator = document.createElement('div');
        indicator.className = 'summarizing-indicator';
        indicator.id = 'summarizingIndicator';
        indicator.innerHTML = `
            <div class="summarizing-content">
                <div class="summarizing-spinner">
                    <i class="fas fa-spinner fa-spin"></i>
                </div>
                <span class="summarizing-text">${this.escapeHtml(message)}</span>
            </div>
        `;
        
        this.messagesContainer.appendChild(indicator);
        this.scrollToBottom();
        
        // 保存状态到 localStorage 以便刷新后恢复
        localStorage.setItem(`summarizing_${this.sessionId}`, 'true');
    }
    
    /**
     * 隐藏正在总结的指示器
     */
    hideSummarizingIndicator() {
        const indicator = document.getElementById('summarizingIndicator');
        if (indicator) {
            indicator.remove();
        }
        localStorage.removeItem(`summarizing_${this.sessionId}`);
    }
    
    /**
     * 显示会话命名中指示器
     * 同时在会话列表和聊天区域显示
     */
    showNamingIndicator(sessionId) {
        // 1. 更新会话列表中的名称显示
        const nameEl = document.getElementById(`session-name-${sessionId}`);
        if (nameEl) {
            nameEl.innerHTML = '<span class="naming-indicator"><i class="fas fa-spinner fa-spin"></i> 正在命名...</span>';
        }
        
        // 2. 在聊天区域显示命名中的提示（类似流式恢复的样式）
        // 只有当前会话才显示
        if (sessionId === this.sessionId) {
            this.showNamingMessage();
        }
        
        // 3. 保存状态到 localStorage 以便刷新后恢复
        localStorage.setItem(`naming_${sessionId}`, 'true');
    }
    
    /**
     * 在聊天区域显示命名中的消息提示
     */
    showNamingMessage() {
        // 检查是否已存在命名消息
        let namingMsg = document.getElementById('namingMessage');
        if (namingMsg) return;
        
        namingMsg = document.createElement('div');
        namingMsg.className = 'agent-message agent-message naming-message';
        namingMsg.id = 'namingMessage';
        namingMsg.innerHTML = `
            <div class="message-avatar">
                <i class="fas fa-robot"></i>
            </div>
            <div class="message-body">
                <div class="message-content">
                    <span class="text-muted"><i class="fas fa-spinner fa-spin me-2"></i>正在为会话命名...</span>
                </div>
            </div>
        `;
        this.messagesContainer.appendChild(namingMsg);
        this.scrollToBottom();
        console.log('✏️ 显示命名中消息');
    }
    
    /**
     * 隐藏聊天区域的命名消息
     */
    hideNamingMessage() {
        const namingMsg = document.getElementById('namingMessage');
        if (namingMsg) {
            namingMsg.remove();
            console.log('✏️ 移除命名中消息');
        }
    }
    
    /**
     * 隐藏会话命名指示器，显示新名称
     */
    hideNamingIndicator(sessionId, newName) {
        // 1. 更新会话列表中的名称
        const nameEl = document.getElementById(`session-name-${sessionId}`);
        if (nameEl && newName) {
            nameEl.textContent = newName;
        }
        
        // 2. 移除聊天区域的命名消息
        if (sessionId === this.sessionId) {
            this.hideNamingMessage();
        }
        
        // 3. 清除 localStorage 状态
        localStorage.removeItem(`naming_${sessionId}`);
    }
    
    /**
     * 更新会话预览文本
     */
    updateSessionPreview(sessionId, preview) {
        const previewEl = document.getElementById(`session-preview-${sessionId}`);
        if (previewEl) {
            previewEl.textContent = preview;
        }
    }
    
    /**
     * 显示总结分割线（在已被总结的消息和未总结的消息之间）
     * @param {string} summary 总结内容
     * @param {number} summarizedUntil 总结覆盖到的消息索引
     * @param {number} summaryTokens 总结 token 数
     */
    showSummaryDivider(summary, summarizedUntil, summaryTokens) {
        // 移除已有的分割线
        const existingDivider = this.messagesContainer.querySelector('.summary-divider');
        if (existingDivider) {
            existingDivider.remove();
        }
        
        // 创建总结分割线
        const divider = document.createElement('div');
        divider.className = 'summary-divider';
        divider.dataset.summarizedUntil = summarizedUntil;
        
        // 截断总结预览
        const previewLength = 100;
        const summaryPreview = summary.length > previewLength 
            ? summary.substring(0, previewLength) + '...' 
            : summary;
        
        divider.innerHTML = `
            <div class="summary-divider-line"></div>
            <div class="summary-divider-content">
                <div class="summary-badge" onclick="agentChat.toggleSummaryDetail(this)">
                    <i class="fas fa-compress-alt me-1"></i>
                    <span>已总结 ${summarizedUntil} 条消息 (${summaryTokens} tokens)</span>
                    <i class="fas fa-chevron-down ms-1 summary-toggle-icon"></i>
                </div>
                <div class="summary-detail" style="display: none;">
                    <div class="summary-text">${this.escapeHtml(summary)}</div>
                </div>
            </div>
            <div class="summary-divider-line"></div>
        `;
        
        // 将分割线追加到消息容器末尾（因为是在消息渲染过程中按正确顺序调用的）
        this.messagesContainer.appendChild(divider);
        
        // 保存总结信息到 localStorage
        localStorage.setItem(`summary_${this.sessionId}`, JSON.stringify({
            summary: summary,
            summarizedUntil: summarizedUntil,
            summaryTokens: summaryTokens
        }));
    }
    
    /**
     * 切换总结详情的展开/收起
     */
    toggleSummaryDetail(badge) {
        const container = badge.closest('.summary-divider-content');
        const detail = container.querySelector('.summary-detail');
        const icon = badge.querySelector('.summary-toggle-icon');
        const isExpanded = detail.style.display !== 'none';
        
        if (isExpanded) {
            detail.style.display = 'none';
            icon.className = 'fas fa-chevron-down ms-1 summary-toggle-icon';
        } else {
            detail.style.display = 'block';
            icon.className = 'fas fa-chevron-up ms-1 summary-toggle-icon';
        }
    }
    
    /**
     * 从 localStorage 恢复总结状态
     */
    restoreSummaryState() {
        // 检查是否正在总结
        const isSummarizing = localStorage.getItem(`summarizing_${this.sessionId}`);
        if (isSummarizing === 'true') {
            this.showSummarizingIndicator('正在总结对话历史...');
        }
        
        // 检查是否有已保存的总结（不再从这里恢复，由 loadHistory 的 API 返回）
    }
    
    /**
     * 从 localStorage 恢复命名状态
     * 刷新页面后如果会话正在命名，需要恢复显示
     * 注意：实际状态以 WebSocket connected 消息中的 is_naming 为准
     */
    restoreNamingState() {
        const isNaming = localStorage.getItem(`naming_${this.sessionId}`);
        if (isNaming === 'true') {
            console.log('🔄 临时恢复命名状态（等待后端确认）');
            this.showNamingIndicator(this.sessionId);
        }
    }
    
    /**
     * 根据后端实际状态同步命名显示
     * 在 WebSocket connected 消息中调用
     */
    syncNamingState(isNaming, sessionName) {
        const localNamingState = localStorage.getItem(`naming_${this.sessionId}`) === 'true';
        
        console.log('🔄 同步命名状态:', { isNaming, sessionName, localNamingState });
        
        if (isNaming) {
            // 后端确认正在命名中
            if (!localNamingState) {
                // localStorage 没有记录，需要显示
                this.showNamingIndicator(this.sessionId);
            }
            // 如果 localStorage 已有记录，restoreNamingState 已经显示了
        } else {
            // 后端确认没有在命名
            if (localNamingState) {
                // localStorage 有旧记录，需要清除并隐藏
                console.log('🔄 后端确认命名已完成，清除旧状态');
                this.hideNamingIndicator(this.sessionId, sessionName);
            }
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
                    
                    // 【新增】检查是否正在总结
                    if (data.is_summarizing) {
                        this.showSummarizingIndicator('正在总结对话历史...');
                    }
                    
                    // 保存总结信息，用于在渲染消息时插入分割线
                    const summaryInfo = data.summary;
                    let summaryDividerInserted = false;
                    
                    // 渲染历史消息
                    messages.forEach(msg => {
                        const index = msg.index !== undefined ? msg.index : null;
                        
                        // 【关键】在正确的位置插入总结分割线
                        // 分割线应该出现在 summarized_until 位置的消息之前
                        // 代表：分割线之前的消息已被总结，分割线之后的消息是原始内容
                        if (summaryInfo && !summaryDividerInserted && index !== null && index >= summaryInfo.summarized_until) {
                            this.showSummaryDivider(
                                summaryInfo.text,
                                summaryInfo.summarized_until,
                                summaryInfo.tokens
                            );
                            summaryDividerInserted = true;
                        }
                        
                        // 检查消息是否有有效内容（兼容多模态 array 和普通 string）
                        const hasContent = (c) => {
                            if (!c) return false;
                            if (typeof c === 'string') return c.trim().length > 0;
                            if (Array.isArray(c)) return c.length > 0;
                            return true;
                        };
                        
                        if (msg.role === 'user') {
                            // 用户消息
                            if (hasContent(msg.content)) {
                                const metadata = {};
                                // 如果消息包含附件列表，传递给 addMessage 渲染磁贴
                                if (msg.attachments && msg.attachments.length > 0) {
                                    metadata.attachments = msg.attachments;
                                }
                                this.addMessage(msg.content, 'user', metadata, index);
                            }
                        } else if (msg.role === 'assistant') {
                            // AI消息
                            // 第一步：显示AI的思考内容（如果有）
                            if (hasContent(msg.content)) {
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
                            if (hasContent(msg.content)) {
                                this.showToolResultFromHistory(msg.content, msg.name);
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
    showToolResultFromHistory(result, toolName = null) {
        // 使用统一的工具结果显示方法
        this.showToolResultContent(toolName || 'tool', result);
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
            
            // 检查是否正在命名中
            const isNaming = session.is_naming || false;
            const displayName = isNaming ? 
                '<span class="naming-indicator"><i class="fas fa-spinner fa-spin"></i> 正在命名...</span>' : 
                escapedName;
            
            return `
                <div class="session-item ${isActive ? 'active' : ''}" 
                     data-session-id="${session.session_id}">
                    <div class="session-info" onclick="agentChat.switchSession('${session.session_id}')">
                        <div class="session-name" id="session-name-${session.session_id}">${displayName}</div>
                        <div class="session-preview" id="session-preview-${session.session_id}">${this.escapeHtml(preview)}</div>
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
        
        // 更新上下文使用量条形图
        this.updateContextUsageBar();
        
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
                
                // 更新上下文使用量条形图（新会话为空）
                this.updateContextUsageBar();
                
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
     * 更新会话预览（发送消息后立即更新UI）
     */
    updateSessionPreview(message) {
        // 截取预览文本
        const preview = message.length > 50 ? message.substring(0, 50) + '...' : message;
        
        // 更新当前会话在列表中的预览
        const previewEl = document.getElementById(`session-preview-${this.sessionId}`);
        if (previewEl) {
            previewEl.textContent = preview;
        }
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
        
        // 保存当前滚动位置（如果面板已存在）
        const existingBody = this.toolSelectPanel.querySelector('.tool-panel-body');
        const scrollTop = existingBody ? existingBody.scrollTop : 0;
        
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
        
        // 恢复滚动位置
        if (scrollTop > 0) {
            const newBody = this.toolSelectPanel.querySelector('.tool-panel-body');
            if (newBody) {
                // 使用 setTimeout 确保 DOM 渲染完成后再恢复滚动
                setTimeout(() => {
                    newBody.scrollTop = scrollTop;
                }, 0);
            }
        }
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
        
        // 更新UI（滚动位置会在 renderToolPanel 内部自动保持）
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
    // 附件详情 Modal
    // ==========================================

    /**
     * 显示日程详情 Modal
     * @param {string|number} eventId - 日程 ID
     */
    showEventDetailModal(eventId) {
        try {
            if (!window.eventManager) {
                this.showNotification('日程管理器未初始化', 'error');
                return;
            }
            
            // 从 eventManager 缓存中查找
            const event = window.eventManager.events?.find(
                e => String(e.id) === String(eventId)
            );
            
            if (!event) {
                this.showNotification('日程不存在或已被删除', 'warning');
                return;
            }
            
            // 转换为 openEventDetailModal 期望的格式
            const eventInfo = {
                id: event.id,
                title: event.title,
                start: event.start,
                end: event.end,
                allDay: event.allDay,
                extendedProps: {
                    location: event.location,
                    description: event.description,
                    color: event.color,
                    series_id: event.series_id,
                    rec_type: event.rec_type
                }
            };
            
            window.eventManager.openEventDetailModal(eventInfo);
        } catch (error) {
            console.error('打开日程详情失败:', error);
            this.showNotification('打开日程详情失败', 'error');
        }
    }

    /**
     * 显示待办详情 Modal
     * @param {string|number} todoId - 待办 ID
     */
    showTodoDetailModal(todoId) {
        try {
            if (!window.todoManager) {
                this.showNotification('待办管理器未初始化', 'error');
                return;
            }
            
            const todo = window.todoManager.todos?.find(
                t => String(t.id) === String(todoId)
            );
            
            if (!todo) {
                this.showNotification('待办不存在或已被删除', 'warning');
                return;
            }
            
            window.todoManager.openTodoDetailModal(todo);
        } catch (error) {
            console.error('打开待办详情失败:', error);
            this.showNotification('打开待办详情失败', 'error');
        }
    }

    /**
     * 显示提醒详情 Modal
     * @param {string|number} reminderId - 提醒 ID
     */
    showReminderDetailModal(reminderId) {
        try {
            if (!window.reminderManager) {
                this.showNotification('提醒管理器未初始化', 'error');
                return;
            }
            
            const reminder = window.reminderManager.reminders?.find(
                r => String(r.id) === String(reminderId)
            );
            
            if (!reminder) {
                this.showNotification('提醒不存在或已被删除', 'warning');
                return;
            }
            
            window.reminderManager.openReminderDetailModal(reminder);
        } catch (error) {
            console.error('打开提醒详情失败:', error);
            this.showNotification('打开提醒详情失败', 'error');
        }
    }

    /**
     * 显示工作流详情 Modal
     * @param {string|number} workflowId - 工作流 ID
     */
    async showWorkflowDetailModal(workflowId) {
        try {
            // 从列表接口获取所有工作流，再按 ID 过滤
            const response = await fetch('/api/agent/memory/workflow-rules/', {
                headers: {
                    'X-CSRFToken': this.csrfToken
                }
            });
            
            if (!response.ok) {
                throw new Error('获取工作流列表失败');
            }
            
            const data = await response.json();
            const workflow = (data.items || []).find(
                w => String(w.id) === String(workflowId)
            );
            
            if (!workflow) {
                this.showNotification('工作流不存在或已被删除', 'warning');
                return;
            }
            
            // 构建工作流详情 HTML
            const modalHtml = `
                <div class="modal fade" id="workflowDetailModal" tabindex="-1">
                    <div class="modal-dialog">
                        <div class="modal-content">
                            <div class="modal-header">
                                <h5 class="modal-title">
                                    <i class="fas fa-project-diagram me-2" style="color: #6f42c1;"></i>工作流详情
                                </h5>
                                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                            </div>
                            <div class="modal-body">
                                <div class="mb-3">
                                    <strong>名称：</strong>${this.escapeHtml(workflow.name)}
                                </div>
                                <div class="mb-3">
                                    <strong>状态：</strong>
                                    <span class="badge ${workflow.is_active ? 'bg-success' : 'bg-secondary'}">
                                        ${workflow.is_active ? '启用' : '禁用'}
                                    </span>
                                </div>
                                <div class="mb-3">
                                    <strong>触发条件：</strong>
                                    <div class="mt-1 p-2 bg-light rounded" style="white-space: pre-wrap;">${this.escapeHtml(workflow.trigger || '无')}</div>
                                </div>
                                <div class="mb-3">
                                    <strong>执行步骤：</strong>
                                    <div class="mt-1 p-2 bg-light rounded" style="white-space: pre-wrap;">${this.escapeHtml(workflow.steps || '无')}</div>
                                </div>
                            </div>
                            <div class="modal-footer">
                                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">关闭</button>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            
            // 移除已存在的 modal
            const existingModal = document.getElementById('workflowDetailModal');
            if (existingModal) {
                existingModal.remove();
            }
            
            // 添加新 modal
            document.body.insertAdjacentHTML('beforeend', modalHtml);
            
            // 显示 modal
            const modal = new bootstrap.Modal(document.getElementById('workflowDetailModal'));
            modal.show();
            
            // 监听关闭事件，移除 DOM
            document.getElementById('workflowDetailModal').addEventListener('hidden.bs.modal', function() {
                this.remove();
            });
            
        } catch (error) {
            console.error('打开工作流详情失败:', error);
            this.showNotification('打开工作流详情失败', 'error');
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
        
        // 提取消息中的附件数据（用于回滚后恢复到待发送栏）
        let attachments = [];
        if (messageDiv.dataset.attachments) {
            try {
                attachments = JSON.parse(messageDiv.dataset.attachments);
            } catch (e) {
                console.warn('解析附件数据失败:', e);
            }
        }
        
        // 直接执行回滚
        this.rollbackToMessage(messageIndex, content, attachments);
    }

    /**
     * 回滚到指定消息
     */
    async rollbackToMessage(messageIndex, messageContent, attachments = []) {
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
                // 【修复】收集该消息及之后的所有元素（包括消息、工具指示器、工具结果）
                const allChildren = Array.from(this.messagesContainer.children);
                const elementsToRemove = [];
                
                // 找到目标消息的位置
                let targetMessageElement = null;
                const allMessages = this.messagesContainer.querySelectorAll('.agent-message');
                
                allMessages.forEach((msgDiv) => {
                    const msgIndex = parseInt(msgDiv.dataset.messageIndex);
                    if (msgIndex === messageIndex) {
                        targetMessageElement = msgDiv;
                    }
                });
                
                // 如果找到目标消息，删除它及其之后的所有元素
                if (targetMessageElement) {
                    let shouldDelete = false;
                    
                    allChildren.forEach((element) => {
                        // 当遇到目标消息时，开始标记删除
                        if (element === targetMessageElement) {
                            shouldDelete = true;
                        }
                        
                        // 删除目标消息及其之后的所有元素
                        if (shouldDelete) {
                            elementsToRemove.push(element);
                        }
                    });
                } else {
                    // 如果没找到目标消息（不应该发生），回退到旧逻辑
                    console.warn('未找到目标消息元素，使用备用删除逻辑');
                    allMessages.forEach((msgDiv) => {
                        const msgIndex = parseInt(msgDiv.dataset.messageIndex);
                        if (!isNaN(msgIndex) && msgIndex >= messageIndex) {
                            elementsToRemove.push(msgDiv);
                        }
                    });
                }
                
                console.log(`准备删除 ${elementsToRemove.length} 个元素（消息+工具指示器+工具结果）`);
                elementsToRemove.forEach(el => el.remove());
                
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
                
                // 恢复附件到待发送栏
                if (attachments && attachments.length > 0) {
                    // 将附件数据转换为 selectedAttachments 格式
                    this.selectedAttachments = attachments.map(att => {
                        const internalTypes = ['event', 'todo', 'reminder', 'workflow'];
                        const isInternal = att.type === 'internal' || internalTypes.includes(att.type);
                        // 统一为原始选择格式: {type, id, name}
                        if (isInternal) {
                            return {
                                type: att.internal_type || att.type,
                                id: att.internal_id || att.id,
                                name: att.name || att.filename || '未命名'
                            };
                        }
                        // 文件类型：保留完整信息
                        return {
                            type: att.type,
                            id: att.id,
                            name: att.name || att.filename,
                            sa_id: att.sa_id,
                            thumbnail_url: att.thumbnail_url,
                            mime_type: att.mime_type,
                            filename: att.filename
                        };
                    });
                    this.updateAttachmentBadge();
                    this.renderSelectedAttachments();
                }
                
                // 刷新数据
                this.refreshData(['events', 'todos', 'reminders']);
                
                // 【新增】更新上下文使用量条形图（回滚后的 token 数据）
                this.updateContextUsageBar();
                
                // 显示成功提示
                let msg = `已回滚，删除了 ${data.rolled_back_messages} 条消息`;
                if (data.rolled_back_transactions > 0) {
                    msg += `，撤销了 ${data.rolled_back_transactions} 个操作`;
                }
                this.showNotification(msg, 'success');
                
                // Save the restored content as a draft
                this.saveDraft();
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
            // loadTodos() 内部会调用 applyFilters()，保持筛选参数
            window.todoManager.loadTodos();
        }
        if (refreshTypes.includes('reminders') && window.reminderManager) {
            // loadReminders() 后由 settingsManager 应用筛选
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
                // 【关键】清除递归限制状态
                this.clearRecursionLimitState();
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
            // 【关键】清除递归限制状态并标记为用户主动停止
            this.clearRecursionLimitState();
            this.isProcessing = false;
            this.updateSendButton();
            // 直接移除这个提示
            container.remove();
            this.showNotification('已停止继续执行', 'info');
        });
        
        this.messagesContainer.appendChild(container);
        this.scrollToBottom();
    }

    /**
     * 显示配额超额提示
     */
    showQuotaExceededMessage(data) {
        const monthlyUsed = data.monthly_used?.toFixed(2) || '0.00';
        const monthlyCredit = data.monthly_credit?.toFixed(2) || '5.00';
        const message = data.message || '您本月的抵用金已用尽';
        
        const container = document.createElement('div');
        container.className = 'message-wrapper agent-message quota-exceeded-wrapper';
        
        container.innerHTML = `
            <div class="message-avatar">
                <i class="fas fa-exclamation-circle text-warning"></i>
            </div>
            <div class="message-content">
                <div class="quota-exceeded-content">
                    <div class="quota-exceeded-icon mb-2">
                        <i class="fas fa-wallet fa-2x text-warning"></i>
                    </div>
                    <div class="quota-exceeded-title fw-bold mb-2">
                        ${message}
                    </div>
                    <div class="quota-exceeded-details small text-muted mb-3">
                        本月已使用: ¥${monthlyUsed} / ¥${monthlyCredit}
                    </div>
                    <div class="quota-exceeded-tips">
                        <div class="alert alert-light small mb-0">
                            <strong><i class="fas fa-lightbulb me-1"></i>建议：</strong>
                            <ul class="mb-0 ps-3">
                                <li>在设置中配置您自己的 API Key（无限制使用）</li>
                                <li>或等待下月1日配额自动重置</li>
                            </ul>
                        </div>
                    </div>
                    <div class="quota-exceeded-actions mt-3">
                        <button class="btn btn-primary btn-sm" onclick="agentChat.openModelConfig();">
                            <i class="fas fa-cog me-1"></i>配置自定义模型
                        </button>
                    </div>
                </div>
            </div>
        `;
        
        this.messagesContainer.appendChild(container);
        this.scrollToBottom();
    }

    /**
     * 打开模型配置页面
     */
    openModelConfig() {
        // 1. 打开设置模态框
        const settingsModal = new bootstrap.Modal(document.getElementById('settingsModal'));
        settingsModal.show();
        
        // 2. 等待模态框显示后，切换到 AI 设置 tab
        setTimeout(() => {
            const aiTab = document.getElementById('ai-tab');
            if (aiTab) {
                aiTab.click();
                
                // 3. 再等待一下，切换到模型配置子 tab
                setTimeout(() => {
                    const modelConfigTab = document.getElementById('ai-model-config-tab');
                    if (modelConfigTab) {
                        modelConfigTab.click();
                    }
                }, 100);
            }
        }, 150);
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
                    if (type === 'file-upload') {
                        this.showUploadZone();
                    } else {
                        this.selectAttachmentType(type);
                    }
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
        if (this.attachmentUploadZone) {
            this.attachmentUploadZone.style.display = 'none';
        }
        if (this.attachmentPanelTitle) {
            this.attachmentPanelTitle.innerHTML = '<i class="fas fa-paperclip me-1"></i>选择附件类型';
        }
        this.currentAttachmentType = null;
    }

    /**
     * 显示文件上传区域
     */
    showUploadZone() {
        if (this.attachmentTypeList) {
            this.attachmentTypeList.style.display = 'none';
        }
        if (this.attachmentContentList) {
            this.attachmentContentList.style.display = 'none';
        }
        if (this.attachmentUploadZone) {
            this.attachmentUploadZone.style.display = 'block';
        }
        if (this.attachmentPanelTitle) {
            this.attachmentPanelTitle.innerHTML = '<i class="fas fa-cloud-upload-alt me-1"></i>上传文件';
        }
        this.currentAttachmentType = 'file-upload';
    }

    /**
     * 处理文件上传
     */
    async handleFileUpload(file) {
        if (!file) return;

        // 客户端校验
        const maxSize = 20 * 1024 * 1024; // 20MB
        if (file.size > maxSize) {
            this.showNotification('文件过大，最大支持 20MB', 'warning');
            return;
        }

        const allowedTypes = [
            'image/jpeg', 'image/png', 'image/gif', 'image/webp',
            'application/pdf',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.ms-excel',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        ];
        if (!allowedTypes.includes(file.type)) {
            this.showNotification('不支持的文件类型', 'warning');
            return;
        }

        // 显示上传进度
        if (this.uploadProgress) this.uploadProgress.style.display = 'block';
        if (this.uploadDropzone) this.uploadDropzone.style.display = 'none';
        if (this.uploadProgressText) this.uploadProgressText.textContent = `上传中: ${file.name}`;

        try {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('session_id', this.sessionId || `user_${this.userId}_default`);

            const response = await fetch('/api/agent/attachments/upload/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.csrfToken,
                },
                body: formData,
            });

            const data = await response.json();

            if (data.success && data.attachment) {
                const att = data.attachment;
                this.selectedAttachments.push({
                    type: att.type,
                    id: att.internal_id || att.id,
                    name: att.filename,
                    sa_id: att.id,  // SessionAttachment ID
                    thumbnail_url: att.thumbnail_url,  // 缩略图 URL（用于前端显示）
                    mime_type: att.mime_type,
                    _full_data: att  // 存储完整数据
                });
                this.updateAttachmentBadge();
                this.renderSelectedAttachments();
                this.saveDraft();
                this.showNotification(`已添加: ${att.filename}`, 'success');
                // 回到类型列表
                this.showAttachmentTypeList();
            } else {
                this.showNotification(data.error || '上传失败', 'error');
            }
        } catch (error) {
            console.error('文件上传失败:', error);
            this.showNotification('文件上传失败', 'error');
        } finally {
            // 恢复上传区
            if (this.uploadProgress) this.uploadProgress.style.display = 'none';
            if (this.uploadDropzone) this.uploadDropzone.style.display = 'flex';
        }
    }

    /**
     * 选择附件类型，显示内容列表（第二级）
     */
    async selectAttachmentType(type) {
        this.currentAttachmentType = type;
        
        // 更新标题
        const typeLabels = {
            'workflow': '工作流规则',
            'event': '日程事件',
            'todo': '待办事项',
            'reminder': '提醒',
        };
        const typeIcons = {
            'workflow': 'fa-project-diagram',
            'event': 'fa-calendar-alt',
            'todo': 'fa-tasks',
            'reminder': 'fa-bell',
        };
        if (this.attachmentPanelTitle) {
            const icon = typeIcons[type] || 'fa-paperclip';
            this.attachmentPanelTitle.innerHTML = `<i class="fas ${icon} me-1"></i>${typeLabels[type] || type}`;
        }
        
        // 切换视图
        if (this.attachmentTypeList) {
            this.attachmentTypeList.style.display = 'none';
        }
        if (this.attachmentUploadZone) {
            this.attachmentUploadZone.style.display = 'none';
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
            this.renderAttachmentContentList(data.items, type);
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
     * 渲染附件内容列表（多选模式）
     */
    renderAttachmentContentList(items, type) {
        if (!this.attachmentContentItems) return;
        
        const emptyHints = {
            'workflow': '在"记忆设置"中添加工作流规则',
            'event': '在日历中创建日程事件',
            'todo': '在待办中添加任务',
            'reminder': '创建新的提醒',
        };

        if (!items || items.length === 0) {
            this.attachmentContentItems.innerHTML = `
                <div class="attachment-empty">
                    <i class="fas fa-folder-open"></i>
                    <p>暂无可用内容</p>
                    <small class="text-muted">${emptyHints[type] || ''}</small>
                </div>
            `;
            return;
        }

        let html = '';
        items.forEach(item => {
            // 判断是否已选中（多选，对比 type + id）
            const isSelected = this.selectedAttachments.some(
                a => a.type === item.type && String(a.id) === String(item.id)
            );
            
            html += `
                <div class="attachment-item ${isSelected ? 'selected' : ''}" 
                     data-type="${item.type}" 
                     data-id="${item.id}"
                     data-name="${this.escapeHtml(item.title || item.name || '')}">
                    <input type="checkbox" class="attachment-item-checkbox" 
                           ${isSelected ? 'checked' : ''}>
                    <div class="attachment-item-content">
                        <div class="attachment-item-name">${this.escapeHtml(item.title || item.name || '')}</div>
                        <div class="attachment-item-preview">${this.escapeHtml(item.subtitle || item.preview || '')}</div>
                    </div>
                </div>
            `;
        });

        this.attachmentContentItems.innerHTML = html;

        // 绑定点击事件
        this.attachmentContentItems.querySelectorAll('.attachment-item').forEach(el => {
            el.addEventListener('click', () => {
                const elType = el.dataset.type;
                const elId = el.dataset.id;
                const elName = el.dataset.name;
                this.toggleAttachmentMulti(elType, elId, elName);
            });
        });
    }

    /**
     * 切换附件选择状态（多选模式）
     */
    toggleAttachmentMulti(type, id, name) {
        const idx = this.selectedAttachments.findIndex(
            a => a.type === type && String(a.id) === String(id)
        );

        if (idx >= 0) {
            // 取消选择
            this.selectedAttachments.splice(idx, 1);
        } else {
            // 添加选择
            this.selectedAttachments.push({ type, id, name });
        }

        this.updateAttachmentBadge();
        this.renderSelectedAttachments();
        this.saveDraft();
        
        // 就地更新列表项的选中状态（不重新加载）
        if (this.attachmentContentItems) {
            const item = this.attachmentContentItems.querySelector(
                `.attachment-item[data-type="${type}"][data-id="${id}"]`
            );
            if (item) {
                const checkbox = item.querySelector('.attachment-item-checkbox');
                const isNowSelected = idx < 0; // 之前不存在，现在添加了
                if (checkbox) checkbox.checked = isNowSelected;
                item.classList.toggle('selected', isNowSelected);
            }
        }
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
            'workflow': 'fa-project-diagram',
            'event': 'fa-calendar-alt',
            'todo': 'fa-tasks',
            'reminder': 'fa-bell',
            'image': 'fa-image',
            'pdf': 'fa-file-pdf',
            'word': 'fa-file-word',
            'excel': 'fa-file-excel',
        };

        this.selectedAttachmentsContainer.innerHTML = this.selectedAttachments.map(att => `
            <span class="selected-attachment-tag" data-type="${att.type}" data-id="${att.id}">
                <i class="fas ${typeIcons[att.type] || 'fa-file'}"></i>
                ${this.escapeHtml(att.name)}
                <i class="fas fa-times remove-attachment"></i>
            </span>
        `).join('');

        // 绑定移除事件和预览事件
        this.selectedAttachmentsContainer.querySelectorAll('.selected-attachment-tag').forEach(tag => {
            // 点击标签本身预览附件
            tag.addEventListener('click', (e) => {
                // 如果点击的是移除按钮，不触发预览
                if (e.target.closest('.remove-attachment')) return;
                const type = tag.dataset.type;
                const id = tag.dataset.id;
                this.previewAttachment(type, id);
            });
            
            // 移除按钮
            const removeBtn = tag.querySelector('.remove-attachment');
            if (removeBtn) {
                removeBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const type = tag.dataset.type;
                    const id = tag.dataset.id;
                    this.removeAttachment(type, id);
                });
            }
        });
    }

    /**
     * 预览待发送附件
     */
    previewAttachment(type, id) {
        const internalTypes = ['event', 'todo', 'reminder', 'workflow'];
        if (internalTypes.includes(type)) {
            // 内部元素：调用对应的详情 modal（ID 保持原始类型，不强制 parseInt）
            switch (type) {
                case 'event':
                    this.showEventDetailModal(id);
                    break;
                case 'todo':
                    this.showTodoDetailModal(id);
                    break;
                case 'reminder':
                    this.showReminderDetailModal(id);
                    break;
                case 'workflow':
                    this.showWorkflowDetailModal(id);
                    break;
            }
        } else if (type === 'image') {
            // 图片：找到缩略图 URL 并全屏预览
            const att = this.selectedAttachments.find(a => a.type === type && String(a.id) === String(id));
            if (att && att.thumbnail_url) {
                this.showImagePreview(att.thumbnail_url);
            }
        } else if (['pdf', 'word', 'excel'].includes(type)) {
            // 文档：找到文件 URL 并打开文档预览
            const att = this.selectedAttachments.find(a => a.type === type && String(a.sa_id) === String(id));
            const fileUrl = att && att._full_data && att._full_data.file_url;
            const mimeType = att && att.mime_type || '';
            const filename = att && (att.name || att.filename || '文件');
            if (fileUrl) {
                this.showDocumentPreview(fileUrl, mimeType, filename, type);
            }
        }
    }

    /**
     * 移除附件
     */
    removeAttachment(type, id) {
        this.selectedAttachments = this.selectedAttachments.filter(
            a => !(a.type === type && String(a.id) === String(id))
        );
        this.updateAttachmentBadge();
        this.renderSelectedAttachments();
        
        // 如果面板打开，重新渲染内容列表
        if (this.attachmentPanelVisible && this.currentAttachmentType && this.currentAttachmentType !== 'file-upload') {
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
        this.saveDraft();
    }

    /**
     * 获取附件格式化内容（发送消息时调用）
     * 新逻辑：
     *   - 有 sa_id 的附件（文件上传）→ 用 attachment_ids
     *   - 无 sa_id 的内部元素 → 先调 attach-internal 创建 SA 再用 attachment_ids
     *   - 旧格式 workflow（兼容）→ 走旧 API
     */
    async getFormattedAttachmentContent() {
        if (this.selectedAttachments.length === 0) {
            return { sa_ids: [], formatted_content: '' };
        }

        try {
            const sessionId = this.sessionId || `user_${this.userId}_default`;
            const saIds = [];

            // 1. 收集已有 sa_id 的附件（文件上传的）
            for (const att of this.selectedAttachments) {
                if (att.sa_id) {
                    saIds.push(att.sa_id);
                }
            }

            // 2. 没有 sa_id 的内部元素，创建 SessionAttachment
            const internalAtts = this.selectedAttachments.filter(a => !a.sa_id);
            for (const att of internalAtts) {
                try {
                    const resp = await fetch('/api/agent/attachments/internal/', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': this.csrfToken,
                        },
                        body: JSON.stringify({
                            session_id: sessionId,
                            element_type: att.type,
                            element_id: String(att.id),
                        }),
                    });
                    const data = await resp.json();
                    if (data.success && data.attachment) {
                        saIds.push(data.attachment.id);
                    }
                } catch (e) {
                    console.warn('创建内部附件失败:', att, e);
                }
            }

            // 3. 用 attachment_ids 获取格式化文本（用于用户侧显示）
            let displayText = '';
            if (saIds.length > 0) {
                try {
                    const resp = await fetch('/api/agent/attachments/format/', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': this.csrfToken,
                        },
                        body: JSON.stringify({ attachment_ids: saIds }),
                    });
                    const data = await resp.json();
                    displayText = data.formatted_content || '';
                } catch (e) {
                    console.warn('获取附件格式化内容失败:', e);
                }
            }

            return { sa_ids: saIds, formatted_content: displayText };

        } catch (error) {
            console.error('获取附件内容失败:', error);
            return { sa_ids: [], formatted_content: '' };
        }
    }

    // ==========================================
    // 递归限制状态管理（刷新恢复）
    // ==========================================

    /**
     * 获取递归限制状态存储键
     */
    getRecursionLimitStateKey() {
        return `agent_recursion_limit_${this.userId}_${this.sessionId}`;
    }

    /**
     * 保存递归限制状态到 localStorage
     */
    saveRecursionLimitState(message) {
        try {
            const state = {
                message: message,
                timestamp: Date.now(),
                sessionId: this.sessionId
            };
            const key = this.getRecursionLimitStateKey();
            localStorage.setItem(key, JSON.stringify(state));
            console.log('💾 保存递归限制状态:', {
                key: key,
                message: message,
                sessionId: state.sessionId
            });
        } catch (error) {
            console.error('保存递归限制状态失败:', error);
        }
    }

    /**
     * 清除递归限制状态
     */
    clearRecursionLimitState() {
        try {
            localStorage.removeItem(this.getRecursionLimitStateKey());
            console.log('🧹 清除递归限制状态');
        } catch (error) {
            console.error('清除递归限制状态失败:', error);
        }
    }

    /**
     * 恢复递归限制状态（页面刷新后调用）
     */
    restoreRecursionLimitState() {
        try {
            const key = this.getRecursionLimitStateKey();
            const stateJson = localStorage.getItem(key);
            
            console.log('🔍 检查递归限制状态:', {
                key: key,
                hasState: !!stateJson,
                userId: this.userId,
                sessionId: this.sessionId
            });
            
            if (!stateJson) {
                console.log('ℹ️ 无需恢复递归限制状态');
                return;
            }

            const state = JSON.parse(stateJson);
            console.log('📦 读取到递归限制状态:', {
                message: state.message,
                timestamp: new Date(state.timestamp).toLocaleString(),
                sessionId: state.sessionId
            });
            
            // 检查状态是否过期（超过 10 分钟则认为无效）
            const now = Date.now();
            const age = now - state.timestamp;
            if (age > 10 * 60 * 1000) {
                console.log('⏰ 递归限制状态已过期，清除', { ageMinutes: (age / 60000).toFixed(1) });
                this.clearRecursionLimitState();
                return;
            }

            // 检查会话 ID 是否匹配
            if (state.sessionId !== this.sessionId) {
                console.log('🔄 会话 ID 不匹配，清除旧递归限制状态', {
                    expected: this.sessionId,
                    actual: state.sessionId
                });
                this.clearRecursionLimitState();
                return;
            }

            // 状态有效，恢复显示
            console.log('✅ 恢复递归限制提示');
            this.showRecursionLimitMessage(state.message);
            this.isProcessing = false;
            this.updateSendButton();
        } catch (error) {
            console.error('恢复递归限制状态失败:', error);
            this.clearRecursionLimitState();
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
     * 只恢复流式状态的内部变量（不创建UI）
     * 用于命名期间刷新的情况，等命名结束后再显示流式UI
     */
    restoreStreamingStateVariables() {
        try {
            const key = this.getStreamingStateKey();
            const stateJson = localStorage.getItem(key);
            
            if (!stateJson) {
                console.log('ℹ️ 无需恢复流式状态变量');
                return;
            }
            
            const state = JSON.parse(stateJson);
            
            // 检查状态是否过期
            const now = Date.now();
            const age = now - state.timestamp;
            if (age > 5 * 60 * 1000) {
                console.log('⏰ 流式状态已过期，清除');
                this.clearStreamingState();
                return;
            }
            
            // 检查会话 ID 是否匹配
            if (state.sessionId !== this.sessionId) {
                console.log('🔄 会话 ID 不匹配，清除旧状态');
                this.clearStreamingState();
                return;
            }
            
            // 只恢复内部变量，不创建UI
            if (state.isActive) {
                console.log('🔄 恢复流式状态变量（命名中，暂不显示UI）:', {
                    contentLength: state.content?.length || 0
                });
                
                this.isStreamingActive = true;
                this.streamingContent = state.content || '';
                this.isProcessing = true;
                this.updateSendButton();
            }
        } catch (error) {
            console.error('恢复流式状态变量失败:', error);
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

    // ==========================================
    // 上下文使用量条形图
    // ==========================================

    /**
     * 更新上下文使用量条形图
     * 在以下时机调用：
     * - 初始化/刷新页面
     * - 用户发送消息后
     * - Agent 回复完成后
     * - 历史总结完成后
     * - 切换会话后
     */
    async updateContextUsageBar() {
        try {
            const response = await fetch(`/api/agent/context-usage/?session_id=${encodeURIComponent(this.sessionId)}`, {
                headers: {
                    'X-CSRFToken': this.csrfToken
                }
            });
            
            if (!response.ok) {
                console.warn('获取上下文使用情况失败:', response.status);
                return;
            }
            
            const data = await response.json();
            this.renderContextUsageBar(data);
            
            // 保存到 localStorage 以便会话恢复
            this.saveContextUsageData(data);
            
        } catch (error) {
            console.error('更新上下文使用量条形图失败:', error);
            // 尝试从缓存恢复
            this.restoreContextUsageBar();
        }
    }

    /**
     * 渲染上下文使用量条形图
     */
    renderContextUsageBar(data) {
        const container = document.getElementById('contextUsageBarContainer');
        const summaryBar = document.getElementById('contextSummaryBar');
        const recentBar = document.getElementById('contextRecentBar');
        const remainingBar = document.getElementById('contextRemainingBar');
        const triggerLine = document.getElementById('contextTriggerLine');
        
        if (!container || !summaryBar || !recentBar || !remainingBar || !triggerLine) {
            console.warn('上下文使用量条形图元素未找到');
            return;
        }
        
        const {
            target_max_tokens,
            trigger_tokens,
            summary_tokens,
            recent_tokens,
            remaining_tokens,
            total_tokens,
            has_summary
        } = data;
        
        // 计算百分比
        const total = target_max_tokens || 1;  // 避免除零
        const summaryPercent = (summary_tokens / total) * 100;
        const recentPercent = (recent_tokens / total) * 100;
        const remainingPercent = Math.max(0, (remaining_tokens / total) * 100);
        const triggerPercent = (trigger_tokens / total) * 100;
        
        // 设置条形图宽度
        summaryBar.style.width = `${summaryPercent}%`;
        recentBar.style.width = `${recentPercent}%`;
        remainingBar.style.width = `${remainingPercent}%`;
        
        // 设置触发线位置
        triggerLine.style.left = `${triggerPercent}%`;
        
        // 处理圆角
        if (summaryPercent === 0) {
            recentBar.style.borderRadius = '4px 0 0 4px';
        } else {
            recentBar.style.borderRadius = '0';
        }
        
        if (remainingPercent === 0) {
            if (recentPercent > 0) {
                recentBar.style.borderRadius = summaryPercent === 0 ? '4px' : '0 4px 4px 0';
            } else if (summaryPercent > 0) {
                summaryBar.style.borderRadius = '4px';
            }
        }
        
        // 构建 tooltip 内容（HTML）
        let tooltipHTML = '<div class="context-usage-tooltip-content">';
        if (has_summary) {
            tooltipHTML += `<div><span class="tooltip-dot dot-summary"></span> 历史总结: ${this.formatTokens(summary_tokens)}</div>`;
        }
        tooltipHTML += `<div><span class="tooltip-dot dot-recent"></span> 新消息: ${this.formatTokens(recent_tokens)}</div>`;
        tooltipHTML += `<div><span class="tooltip-dot dot-remaining"></span> 余量: ${this.formatTokens(remaining_tokens)}</div>`;
        tooltipHTML += `<div class="tooltip-divider"></div>`;
        tooltipHTML += `<div>总计: ${this.formatTokens(total_tokens)} / ${this.formatTokens(target_max_tokens)}</div>`;
        tooltipHTML += `<div><span class="tooltip-trigger">⚡</span> ${triggerPercent.toFixed(0)}% 时触发总结</div>`;
        tooltipHTML += '</div>';
        
        // 移除旧 tooltip
        let tooltip = container.querySelector('.context-usage-tooltip');
        if (tooltip) {
            tooltip.remove();
        }
        
        // 创建新 tooltip
        tooltip = document.createElement('div');
        tooltip.className = 'context-usage-tooltip';
        tooltip.innerHTML = tooltipHTML;
        container.appendChild(tooltip);
    }

    /**
     * 格式化 token 数量显示
     */
    formatTokens(tokens) {
        if (tokens >= 10240) {  // 10*1024
            return `${(tokens / 1024).toFixed(1)}k`;
        } else if (tokens >= 1024) {
            return `${(tokens / 1024).toFixed(2)}k`;
        }
        return `${tokens}`;
    }

    /**
     * 保存上下文使用数据到 localStorage
     */
    saveContextUsageData(data) {
        try {
            const key = `context_usage_${this.sessionId}`;
            localStorage.setItem(key, JSON.stringify(data));
        } catch (e) {
            console.warn('保存上下文使用数据失败:', e);
        }
    }

    /**
     * 从 localStorage 恢复上下文使用条形图
     */
    restoreContextUsageBar() {
        try {
            const key = `context_usage_${this.sessionId}`;
            const cached = localStorage.getItem(key);
            if (cached) {
                const data = JSON.parse(cached);
                this.renderContextUsageBar(data);
            }
        } catch (e) {
            console.warn('恢复上下文使用数据失败:', e);
        }
    }
}

// 全局变量，在 HTML 中初始化
let agentChat = null;
