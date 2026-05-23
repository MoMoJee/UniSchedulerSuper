/**
 * Agent Configuration Manager
 * 处理 AI 模型配置、上下文优化设置、Token 统计
 */

const agentConfig = {
    // 缓存的配置数据
    config: null,
    allModels: {},
    
    /**
     * 初始化 - 加载所有配置
     */
    async init() {
        try {
            await this.loadAllConfig();
            console.log('[AgentConfig] 初始化完成');
        } catch (error) {
            console.error('[AgentConfig] 初始化失败:', error);
        }
    },
    
    /**
     * 加载所有配置
     */
    async loadAllConfig() {
        try {
            const response = await fetch('/api/agent/config/', {
                headers: {
                    'Content-Type': 'application/json',
                }
            });
            
            if (!response.ok) throw new Error('加载配置失败');
            
            const data = await response.json();
            if (data.success) {
                this.config = data;
                this.allModels = data.model.all_models || {};
                
                // 更新各个 UI 组件
                this.updateModelUI(data.model);
                this.updateOptimizationUI(data.optimization);
                
                // 加载 Token 统计（使用新 API）
                await this.loadTokenStats();
            }
        } catch (error) {
            console.error('[AgentConfig] 加载配置失败:', error);
            this.showError('加载配置失败: ' + error.message);
        }
    },
    
    // ==========================================
    // 模型配置相关
    // ==========================================
    
    /**
     * 更新模型选择 UI
     */
    updateModelUI(modelData) {
        const select = document.getElementById('currentModelSelect');
        if (!select) return;
        
        select.innerHTML = '';
        
        // 系统模型
        const systemOptgroup = document.createElement('optgroup');
        systemOptgroup.label = '系统提供';
        for (const [id, model] of Object.entries(modelData.system_models || {})) {
            const option = document.createElement('option');
            option.value = id;
            option.textContent = model.name;
            if (id === modelData.current_model_id) option.selected = true;
            systemOptgroup.appendChild(option);
        }
        select.appendChild(systemOptgroup);
        
        // 自定义模型
        const customModels = modelData.custom_models || {};
        if (Object.keys(customModels).length > 0) {
            const customOptgroup = document.createElement('optgroup');
            customOptgroup.label = '自定义模型';
            for (const [id, model] of Object.entries(customModels)) {
                const option = document.createElement('option');
                option.value = id;
                option.textContent = model.name;
                if (id === modelData.current_model_id) option.selected = true;
                customOptgroup.appendChild(option);
            }
            select.appendChild(customOptgroup);
        }
        
        // 显示当前模型信息
        const currentModel = modelData.current_model || this.allModels[modelData.current_model_id];
        this.showModelInfo(currentModel);

        // 渲染思考开关（依赖当前模型能力）
        this._currentThinkingEnabled = !!modelData.thinking_enabled;
        this.applyThinkingSwitch(currentModel, this._currentThinkingEnabled);

        // 更新自定义模型列表
        this.updateCustomModelsList(customModels);

        // 监听选择变化
        select.onchange = () => {
            const m = this.allModels[select.value];
            this.showModelInfo(m);
            this.applyThinkingSwitch(m, this._currentThinkingEnabled);
        };
    },

    /**
     * 根据模型能力应用思考开关状态
     */
    applyThinkingSwitch(model, currentEnabled) {
        const sw = document.getElementById('thinkingEnabledSwitch');
        const label = document.getElementById('thinkingEnabledLabel');
        const hint = document.getElementById('thinkingModeHint');
        if (!sw || !label) return;
        const mode = (model && model.thinking_mode) || 'unsupported';
        if (mode === 'unsupported') {
            sw.checked = false;
            sw.disabled = true;
            if (hint) hint.textContent = '当前模型不支持思考模式';
        } else if (mode === 'forced') {
            sw.checked = true;
            sw.disabled = true;
            if (hint) hint.textContent = '当前模型始终启用思考模式';
        } else {
            sw.disabled = false;
            sw.checked = !!currentEnabled;
            if (hint) hint.textContent = '启用后模型会先生成推理链，再给出最终答案';
        }
        label.textContent = sw.checked ? '开启' : '关闭';
    },

    /**
     * 切换思考开关
     */
    async toggleThinking() {
        const sw = document.getElementById('thinkingEnabledSwitch');
        if (!sw) return;
        const enabled = !!sw.checked;
        try {
            const response = await fetch('/api/agent/model-config/update/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({ thinking_enabled: enabled })
            });
            const data = await response.json();
            if (data.success) {
                this._currentThinkingEnabled = enabled;
                const label = document.getElementById('thinkingEnabledLabel');
                if (label) label.textContent = enabled ? '开启' : '关闭';
                this.showSuccess(enabled ? '思考模式已开启' : '思考模式已关闭');
            } else {
                sw.checked = !enabled;
                this.showError(data.error || '设置失败');
            }
        } catch (error) {
            sw.checked = !enabled;
            this.showError('设置失败: ' + error.message);
        }
    },
    
    /**
     * 显示模型信息
     */
    showModelInfo(model) {
        const infoDiv = document.getElementById('currentModelInfo');
        if (!infoDiv || !model) return;
        
        infoDiv.style.display = 'block';
        document.getElementById('modelContextWindow').textContent = 
            model.context_window ? `${(model.context_window / 1024).toFixed(0)}K` : '-';
        document.getElementById('modelCostInput').textContent = 
            model.cost_per_1k_input !== undefined ? `￥${model.cost_per_1k_input.toFixed(5)}` : '-';
        document.getElementById('modelCostOutput').textContent = 
            model.cost_per_1k_output !== undefined ? `￥${model.cost_per_1k_output.toFixed(5)}` : '-';
    },
    
    /**
     * 切换模型
     */
    async switchModel() {
        const select = document.getElementById('currentModelSelect');
        if (!select) return;
        
        const newModelId = select.value;
        
        // 记录切换前的模型能力
        const prevModelId = this.config?.model?.current_model_id;
        const prevModel = this.allModels[prevModelId];
        const prevSupportsVision = prevModel?.supports_vision || false;
        
        try {
            const response = await fetch('/api/agent/model-config/update/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({ current_model_id: newModelId })
            });
            
            const data = await response.json();
            if (data.success) {
                this.showSuccess('模型已切换');
                await this.loadAllConfig();
                
                // 刷新上下文使用量条形图
                if (typeof agentChat !== 'undefined' && agentChat && typeof agentChat.updateContextUsageBar === 'function') {
                    console.log('📊 刷新上下文条形图 (模型切换)');
                    agentChat.updateContextUsageBar();
                }
                
                // 检查是否从 Vision 模型切换到纯文本模型
                const newModel = this.allModels[newModelId];
                const newSupportsVision = newModel?.supports_vision || false;
                
                if (prevSupportsVision && !newSupportsVision) {
                    // 从 Vision → 纯文本，检查是否有待 OCR 的图片
                    this.checkPendingOCR();
                }
            } else {
                this.showError(data.error || '切换失败');
            }
        } catch (error) {
            this.showError('切换模型失败: ' + error.message);
        }
    },
    
    /**
     * 检查是否有待 OCR 的图片
     */
    async checkPendingOCR() {
        if (typeof agentChat === 'undefined' || !agentChat || !agentChat.sessionId) {
            return;
        }
        
        try {
            const response = await fetch(
                `/api/agent/attachments/pending-ocr/?session_id=${encodeURIComponent(agentChat.sessionId)}`,
                {
                    headers: { 'X-CSRFToken': this.getCSRFToken() }
                }
            );
            
            if (!response.ok) return;
            
            const data = await response.json();
            
            if (data.has_pending && data.count > 0) {
                this.showOCRPrompt(data.attachments);
            }
        } catch (error) {
            console.warn('[AgentConfig] 检查待 OCR 图片失败:', error);
        }
    },
    
    /**
     * 显示 OCR 提示对话框
     */
    showOCRPrompt(attachments) {
        const count = attachments.length;
        
        // 创建模态框
        const modalHtml = `
            <div class="modal fade" id="ocrPromptModal" tabindex="-1" aria-hidden="true">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">
                                <i class="fas fa-image text-warning me-2"></i>
                                图片 OCR 处理
                            </h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body">
                            <p>您已切换到纯文本模型。当前会话中有 <strong>${count}</strong> 张图片尚未进行 OCR 文字识别。</p>
                            <p class="text-muted small">
                                如果不执行 OCR，这些图片在对话中将显示为占位符。
                                OCR 处理可能需要一些时间，具体取决于图片数量和大小。
                            </p>
                            <div id="ocrProgressContainer" style="display: none;">
                                <div class="progress">
                                    <div class="progress-bar progress-bar-striped progress-bar-animated" 
                                         role="progressbar" style="width: 0%" id="ocrProgressBar"></div>
                                </div>
                                <p class="text-center small mt-2" id="ocrProgressText">正在处理...</p>
                            </div>
                        </div>
                        <div class="modal-footer" id="ocrModalFooter">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">暂不处理</button>
                            <button type="button" class="btn btn-primary" id="startOCRBtn">
                                <i class="fas fa-magic me-1"></i>执行 OCR (${count} 张)
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // 移除可能存在的旧模态框
        const oldModal = document.getElementById('ocrPromptModal');
        if (oldModal) oldModal.remove();
        
        // 添加新模态框
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        
        const modal = new bootstrap.Modal(document.getElementById('ocrPromptModal'));
        modal.show();
        
        // 绑定 OCR 按钮
        document.getElementById('startOCRBtn').onclick = () => {
            this.runBatchOCR(attachments, modal);
        };
    },
    
    /**
     * 执行批量 OCR
     */
    async runBatchOCR(attachments, modal) {
        const ids = attachments.map(a => a.id);
        const progressBar = document.getElementById('ocrProgressBar');
        const progressText = document.getElementById('ocrProgressText');
        const progressContainer = document.getElementById('ocrProgressContainer');
        const footer = document.getElementById('ocrModalFooter');
        
        // 显示进度
        progressContainer.style.display = 'block';
        footer.innerHTML = '<button type="button" class="btn btn-secondary" disabled>处理中...</button>';
        
        try {
            const response = await fetch('/api/agent/attachments/batch-ocr/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({ attachment_ids: ids })
            });
            
            const data = await response.json();
            
            // 更新进度为 100%
            progressBar.style.width = '100%';
            progressText.textContent = `完成: 成功 ${data.success} 张，失败 ${data.failed} 张`;
            
            // 延迟关闭
            setTimeout(() => {
                modal.hide();
                
                if (data.success > 0) {
                    this.showSuccess(`OCR 处理完成: ${data.success} 张图片已识别`);
                }
                if (data.failed > 0) {
                    this.showError(`${data.failed} 张图片 OCR 失败`);
                }
            }, 1500);
            
        } catch (error) {
            progressText.textContent = 'OCR 处理失败: ' + error.message;
            footer.innerHTML = '<button type="button" class="btn btn-secondary" data-bs-dismiss="modal">关闭</button>';
        }
    },
    
    /**
     * 更新自定义模型列表
     */
    updateCustomModelsList(customModels) {
        const container = document.getElementById('customModelsList');
        if (!container) return;
        
        if (Object.keys(customModels).length === 0) {
            container.innerHTML = `
                <div class="text-center text-muted py-3">
                    <i class="fas fa-info-circle me-2"></i>暂无自定义模型
                </div>
            `;
            return;
        }
        
        let html = '<div class="list-group">';
        for (const [id, model] of Object.entries(customModels)) {
            html += `
                <div class="list-group-item d-flex justify-content-between align-items-center">
                    <div>
                        <strong>${model.name}</strong>
                        <br>
                        <small class="text-muted">
                            ${model.provider || 'custom'} | 
                            上下文: ${model.context_window ? (model.context_window/1024).toFixed(0) + 'K' : '-'}
                        </small>
                    </div>
                    <div>
                        <button class="btn btn-sm btn-outline-primary me-1" onclick="agentConfig.editCustomModel('${id}')">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-danger" onclick="agentConfig.deleteCustomModel('${id}')">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
            `;
        }
        html += '</div>';
        container.innerHTML = html;
    },
    
    /**
     * 显示添加模型模态框
     */
    showAddModelModal() {
        const modalHtml = `
            <div class="modal fade" id="addModelModal" tabindex="-1">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title"><i class="fas fa-plus me-2"></i>添加自定义模型</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <form id="addModelForm">
                                <div class="mb-3">
                                    <label class="form-label">模型 ID <span class="text-danger">*</span></label>
                                    <input type="text" class="form-control" id="newModelId" required
                                           placeholder="例如: my_gpt4">
                                    <small class="text-muted">唯一标识符，不能以 system_ 开头</small>
                                </div>
                                <div class="mb-3">
                                    <label class="form-label">显示名称 <span class="text-danger">*</span></label>
                                    <input type="text" class="form-control" id="newModelName" required
                                           placeholder="例如: 我的 GPT-4">
                                </div>
                                <div class="mb-3">
                                    <label class="form-label">API URL <span class="text-danger">*</span></label>
                                    <input type="url" class="form-control" id="newModelApiUrl" required
                                           placeholder="https://api.openai.com/v1/chat/completions">
                                </div>
                                <div class="mb-3">
                                    <label class="form-label">API Key <span class="text-danger">*</span></label>
                                    <input type="password" class="form-control" id="newModelApiKey" required
                                           placeholder="sk-xxx...">
                                </div>
                                <div class="mb-3">
                                    <label class="form-label">模型名称 <span class="text-danger">*</span></label>
                                    <input type="text" class="form-control" id="newModelModelName" required
                                           placeholder="例如: gpt-4-turbo">
                                </div>
                                <div class="row">
                                    <div class="col-md-4 mb-3">
                                        <label class="form-label">上下文窗口</label>
                                        <input type="number" class="form-control" id="newModelContextWindow"
                                               value="8192" min="1024">
                                    </div>
                                    <div class="col-md-4 mb-3">
                                        <label class="form-label">输入成本/1K</label>
                                        <input type="number" class="form-control" id="newModelCostInput"
                                               value="0" min="0" step="0.0001">
                                    </div>
                                    <div class="col-md-4 mb-3">
                                        <label class="form-label">输出成本/1K</label>
                                        <input type="number" class="form-control" id="newModelCostOutput"
                                               value="0" min="0" step="0.0001">
                                    </div>
                                </div>
                            </form>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">取消</button>
                            <button type="button" class="btn btn-primary" onclick="agentConfig.addCustomModel()">
                                <i class="fas fa-plus me-1"></i>添加
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // 移除旧模态框
        const oldModal = document.getElementById('addModelModal');
        if (oldModal) oldModal.remove();
        
        // 添加新模态框
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        const modal = new bootstrap.Modal(document.getElementById('addModelModal'));
        modal.show();
    },
    
    /**
     * 添加自定义模型
     */
    async addCustomModel() {
        const modelData = {
            model_id: document.getElementById('newModelId').value,
            name: document.getElementById('newModelName').value,
            api_url: document.getElementById('newModelApiUrl').value,
            api_key: document.getElementById('newModelApiKey').value,
            model_name: document.getElementById('newModelModelName').value,
            context_window: parseInt(document.getElementById('newModelContextWindow').value) || 8192,
            cost_per_1k_input: parseFloat(document.getElementById('newModelCostInput').value) || 0,
            cost_per_1k_output: parseFloat(document.getElementById('newModelCostOutput').value) || 0
        };
        
        try {
            const response = await fetch('/api/agent/model-config/update/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({ add_custom_model: modelData })
            });
            
            const data = await response.json();
            if (data.success) {
                this.showSuccess('模型已添加');
                bootstrap.Modal.getInstance(document.getElementById('addModelModal')).hide();
                await this.loadAllConfig();
                // 刷新上下文使用量条形图
                if (typeof agentChat !== 'undefined' && agentChat && typeof agentChat.updateContextUsageBar === 'function') {
                    console.log('📊 刷新上下文条形图 (添加模型)');
                    agentChat.updateContextUsageBar();
                }
            } else {
                this.showError(data.error || '添加失败');
            }
        } catch (error) {
            this.showError('添加模型失败: ' + error.message);
        }
    },
    
    /**
     * 删除自定义模型
     */
    async deleteCustomModel(modelId) {
        if (!confirm(`确定要删除模型 "${modelId}" 吗？`)) return;
        
        try {
            const response = await fetch('/api/agent/model-config/update/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({ delete_custom_model: modelId })
            });
            
            const data = await response.json();
            if (data.success) {
                this.showSuccess('模型已删除');
                await this.loadAllConfig();
                // 刷新上下文使用量条形图
                if (typeof agentChat !== 'undefined' && agentChat && typeof agentChat.updateContextUsageBar === 'function') {
                    console.log('📊 刷新上下文条形图 (删除模型)');
                    agentChat.updateContextUsageBar();
                }
            } else {
                this.showError(data.error || '删除失败');
            }
        } catch (error) {
            this.showError('删除模型失败: ' + error.message);
        }
    },
    
    /**
     * 编辑自定义模型
     */
    editCustomModel(modelId) {
        // 从当前配置中获取模型数据
        const model = this.config?.model?.custom_models?.[modelId] || this.allModels?.[modelId];
        if (!model) {
            this.showError('找不到该模型');
            console.error('[AgentConfig] 找不到模型:', modelId, 'config:', this.config);
            return;
        }
        
        const modalHtml = `
            <div class="modal fade" id="editModelModal" tabindex="-1">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title"><i class="fas fa-edit me-2"></i>编辑模型</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <form id="editModelForm">
                                <input type="hidden" id="editModelId" value="${modelId}">
                                <div class="mb-3">
                                    <label class="form-label">模型 ID</label>
                                    <input type="text" class="form-control" value="${modelId}" disabled>
                                    <small class="text-muted">模型 ID 不可修改</small>
                                </div>
                                <div class="mb-3">
                                    <label class="form-label">显示名称 <span class="text-danger">*</span></label>
                                    <input type="text" class="form-control" id="editModelName" required
                                           value="${model.name || ''}">
                                </div>
                                <div class="mb-3">
                                    <label class="form-label">API URL <span class="text-danger">*</span></label>
                                    <input type="url" class="form-control" id="editModelApiUrl" required
                                           value="${model.api_url || ''}">
                                </div>
                                <div class="mb-3">
                                    <label class="form-label">API Key <span class="text-danger">*</span></label>
                                    <input type="password" class="form-control" id="editModelApiKey" required
                                           value="${model.api_key || ''}"
                                           placeholder="留空则保持不变">
                                </div>
                                <div class="mb-3">
                                    <label class="form-label">模型名称 <span class="text-danger">*</span></label>
                                    <input type="text" class="form-control" id="editModelModelName" required
                                           value="${model.model_name || ''}">
                                </div>
                                <div class="row">
                                    <div class="col-md-4 mb-3">
                                        <label class="form-label">上下文窗口</label>
                                        <input type="number" class="form-control" id="editModelContextWindow"
                                               value="${model.context_window || 8192}" min="1024">
                                    </div>
                                    <div class="col-md-4 mb-3">
                                        <label class="form-label">输入成本/1K</label>
                                        <input type="number" class="form-control" id="editModelCostInput"
                                               value="${model.cost_per_1k_input || 0}" min="0" step="0.0001">
                                    </div>
                                    <div class="col-md-4 mb-3">
                                        <label class="form-label">输出成本/1K</label>
                                        <input type="number" class="form-control" id="editModelCostOutput"
                                               value="${model.cost_per_1k_output || 0}" min="0" step="0.0001">
                                    </div>
                                </div>
                            </form>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">取消</button>
                            <button type="button" class="btn btn-primary" onclick="agentConfig.saveEditedModel()">
                                <i class="fas fa-save me-1"></i>保存
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // 移除旧模态框
        const oldModal = document.getElementById('editModelModal');
        if (oldModal) oldModal.remove();
        
        // 添加新模态框
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        const modal = new bootstrap.Modal(document.getElementById('editModelModal'));
        modal.show();
    },
    
    /**
     * 保存编辑后的模型
     */
    async saveEditedModel() {
        const modelId = document.getElementById('editModelId').value;
        const modelData = {
            model_id: modelId,
            name: document.getElementById('editModelName').value,
            api_url: document.getElementById('editModelApiUrl').value,
            api_key: document.getElementById('editModelApiKey').value,
            model_name: document.getElementById('editModelModelName').value,
            context_window: parseInt(document.getElementById('editModelContextWindow').value) || 8192,
            cost_per_1k_input: parseFloat(document.getElementById('editModelCostInput').value) || 0,
            cost_per_1k_output: parseFloat(document.getElementById('editModelCostOutput').value) || 0
        };
        
        try {
            const response = await fetch('/api/agent/model-config/update/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({ add_custom_model: modelData })
            });
            
            const data = await response.json();
            if (data.success) {
                this.showSuccess('模型已更新');
                bootstrap.Modal.getInstance(document.getElementById('editModelModal')).hide();
                await this.loadAllConfig();
                // 刷新上下文使用量条形图
                if (typeof agentChat !== 'undefined' && agentChat && typeof agentChat.updateContextUsageBar === 'function') {
                    console.log('📊 刷新上下文条形图 (更新模型)');
                    agentChat.updateContextUsageBar();
                }
            } else {
                this.showError(data.error || '更新失败');
            }
        } catch (error) {
            this.showError('更新模型失败: ' + error.message);
        }
    },
    
    // ==========================================
    // 上下文优化配置
    // ==========================================
    
    /**
     * 更新优化配置 UI
     */
    updateOptimizationUI(optData) {
        if (!optData) return;
        
        // 总开关
        const enableOpt = document.getElementById('enableContextOptimization');
        if (enableOpt) enableOpt.checked = optData.enable_context_optimization !== false;
        
        const config = optData.config || {};
        
        // Token 预算
        const targetRatio = document.getElementById('targetUsageRatio');
        if (targetRatio) {
            const value = Math.round((config.target_usage_ratio || 0.6) * 100);
            targetRatio.value = value;
            document.getElementById('targetUsageRatioValue').textContent = value + '%';
        }
        
        // Token 计算方式
        const calcMethod = document.getElementById('tokenCalculationMethod');
        if (calcMethod) calcMethod.value = config.token_calculation_method || 'actual';
        
        // 智能总结
        const enableSum = document.getElementById('enableSummarization');
        if (enableSum) enableSum.checked = config.enable_summarization !== false;
        
        const triggerRatio = document.getElementById('summaryTriggerRatio');
        if (triggerRatio) {
            const value = Math.round((config.summary_trigger_ratio || 0.5) * 100);
            triggerRatio.value = value;
            document.getElementById('summaryTriggerRatioValue').textContent = value + '%';
        }
        
        const sumRatio = document.getElementById('summaryTokenRatio');
        if (sumRatio) {
            const value = Math.round((config.summary_token_ratio || 0.26) * 100);
            sumRatio.value = value;
            document.getElementById('summaryTokenRatioValue').textContent = value + '%';
        }
        
        const minMsg = document.getElementById('minMessagesBeforeSummary');
        if (minMsg) minMsg.value = config.min_messages_before_summary || 20;
        
        // 工具压缩
        const compressTool = document.getElementById('compressToolOutput');
        if (compressTool) compressTool.checked = config.compress_tool_output !== false;
        
        const toolMax = document.getElementById('toolOutputMaxTokens');
        if (toolMax) toolMax.value = config.tool_output_max_tokens || 200;
        
        const preserveRecent = document.getElementById('toolCompressPreserveRecent');
        if (preserveRecent) preserveRecent.value = config.tool_compress_preserve_recent_messages || 5;
        
        // 执行控制
        const recursionLimit = document.getElementById('recursionLimit');
        if (recursionLimit) recursionLimit.value = config.recursion_limit || 25;
    },
    
    /**
     * 保存优化配置
     */
    async saveOptimizationConfig() {
        const configData = {
            enable_context_optimization: document.getElementById('enableContextOptimization').checked,
            optimization_config: {
                target_usage_ratio: parseInt(document.getElementById('targetUsageRatio').value) / 100,
                token_calculation_method: document.getElementById('tokenCalculationMethod').value,
                enable_summarization: document.getElementById('enableSummarization').checked,
                summary_trigger_ratio: parseInt(document.getElementById('summaryTriggerRatio').value) / 100,
                summary_token_ratio: parseInt(document.getElementById('summaryTokenRatio').value) / 100,
                min_messages_before_summary: parseInt(document.getElementById('minMessagesBeforeSummary').value),
                compress_tool_output: document.getElementById('compressToolOutput').checked,
                tool_output_max_tokens: parseInt(document.getElementById('toolOutputMaxTokens').value),
                tool_compress_preserve_recent_messages: parseInt(document.getElementById('toolCompressPreserveRecent').value),
                recursion_limit: parseInt(document.getElementById('recursionLimit').value)
            }
        };
        
        try {
            const response = await fetch('/api/agent/optimization-config/update/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify(configData)
            });
            
            const data = await response.json();
            if (data.success) {
                this.showSuccess('优化配置已保存');
                // 刷新上下文使用量条形图
                if (typeof agentChat !== 'undefined' && agentChat && typeof agentChat.updateContextUsageBar === 'function') {
                    console.log('📊 刷新上下文条形图 (保存优化配置)');
                    agentChat.updateContextUsageBar();
                }
            } else {
                this.showError(data.error || '保存失败');
            }
        } catch (error) {
            this.showError('保存配置失败: ' + error.message);
        }
    },
    
    /**
     * 重置优化配置
     */
    resetOptimizationConfig() {
        // 恢复默认值
        document.getElementById('enableContextOptimization').checked = true;
        document.getElementById('targetUsageRatio').value = 60;
        document.getElementById('targetUsageRatioValue').textContent = '60%';
        document.getElementById('tokenCalculationMethod').value = 'actual';
        document.getElementById('enableSummarization').checked = true;
        document.getElementById('summaryTriggerRatio').value = 50;
        document.getElementById('summaryTriggerRatioValue').textContent = '50%';
        document.getElementById('summaryTokenRatio').value = 26;
        document.getElementById('summaryTokenRatioValue').textContent = '26%';
        document.getElementById('minMessagesBeforeSummary').value = 20;
        document.getElementById('compressToolOutput').checked = true;
        document.getElementById('toolOutputMaxTokens').value = 200;
        document.getElementById('toolCompressPreserveRecent').value = 5;
        document.getElementById('recursionLimit').value = 25;
    },
    
    // ==========================================
    // Token 统计
    // ==========================================

    /**
     * 加载 Token 统计
     */
    async loadTokenStats() {
        try {
            this._setTokenStatsLoading();
            const [usageResponse, summaryResponse] = await Promise.all([
                fetch('/api/agent/token-usage/'),
                fetch('/api/agent/token-usage/records/summary/')
            ]);
            const data = await usageResponse.json();

            if (!data.success) {
                this.showError(data.error || '加载 Token 统计失败');
                this._setTokenStatsError(data.error || '加载失败');
                return;
            }

            let recordSummary = { success: false, by_model: {}, by_call_site: {}, by_source: {}, recent_records: [], request_record_count: data.request_record_count || 0 };
            if (summaryResponse.ok) {
                const summaryData = await summaryResponse.json();
                if (summaryData.success) recordSummary = summaryData;
            }

            this.renderTokenStatsDashboard(data, recordSummary);
        } catch (error) {
            console.error('[AgentConfig] 加载统计失败:', error);
            this._setTokenStatsError(error.message);
        }
    },

    /**
     * 渲染 Token 统计总览
     */
    renderTokenStatsDashboard(monthlyData, recordSummary = {}) {
        this._renderTokenQuota(monthlyData);
        const models = this._normalizeModelTokenStats(monthlyData.models || {}, recordSummary);
        const modelContainer = document.getElementById('tokenModelStatsContainer');
        if (modelContainer) modelContainer.innerHTML = this._renderModelTokenCards(models);

        const metadataContainer = document.getElementById('tokenUsageMetadataContainer');
        if (metadataContainer) metadataContainer.innerHTML = this._renderUsageMetadataSummary(monthlyData, recordSummary);

        const recentContainer = document.getElementById('tokenRecentRecordsContainer');
        if (recentContainer) recentContainer.innerHTML = this._renderRecentUsageRecords(recordSummary.recent_records || []);
    },

    _renderTokenQuota(data) {
        const monthlyCredit = data.monthly_credit || 5.0;
        const monthlyUsed = data.monthly_used || 0;
        const remaining = data.remaining || monthlyCredit;
        const currentMonth = data.current_month || '-';

        this._setText('tokenMonthlyUsed', this._formatCNY(monthlyUsed));
        this._setText('tokenMonthlyCredit', this._formatCNY(monthlyCredit));
        this._setText('tokenRemaining', this._formatCNY(remaining));
        this._setText('tokenCurrentMonth', currentMonth);

        const usedPercent = monthlyCredit > 0 ? Math.min(100, (monthlyUsed / monthlyCredit) * 100) : 0;
        const progressBar = document.getElementById('tokenQuotaProgressBar');
        if (!progressBar) return;

        progressBar.style.width = `${usedPercent}%`;
        progressBar.setAttribute('aria-valuenow', usedPercent);
        this._setText('tokenQuotaPercent', `${usedPercent.toFixed(1)}%`);

        progressBar.classList.remove('bg-success', 'bg-warning', 'bg-danger');
        if (usedPercent >= 90) {
            progressBar.classList.add('bg-danger');
        } else if (usedPercent >= 70) {
            progressBar.classList.add('bg-warning');
        } else {
            progressBar.classList.add('bg-success');
        }

        const statusAlert = document.getElementById('quotaStatusAlert');
        const statusText = document.getElementById('quotaStatusText');
        if (!statusAlert || !statusText) return;

        statusAlert.classList.remove('alert-info', 'alert-warning', 'alert-danger');

        if (remaining <= 0) {
            statusAlert.classList.add('alert-danger');
            statusText.innerHTML = '<i class="fas fa-exclamation-circle me-1"></i>配额已用尽';
        } else if (usedPercent >= 80) {
            statusAlert.classList.add('alert-warning');
            statusText.innerHTML = '<i class="fas fa-exclamation-triangle me-1"></i>配额即将用尽';
        } else {
            statusAlert.classList.add('alert-info');
            statusText.innerHTML = '<i class="fas fa-check-circle me-1"></i>配额充足';
        }
    },

    _normalizeModelTokenStats(models, recordSummary) {
        const byModel = recordSummary.by_model || {};
        const modelIds = new Set([...Object.keys(models), ...Object.keys(byModel)]);

        return Array.from(modelIds).map(modelId => {
            const monthly = models[modelId] || {};
            const record = byModel[modelId] || {};
            const inputMiss = Number(record.input_cache_miss_tokens ?? monthly.input_cache_miss_tokens ?? monthly.cache_miss_tokens ?? 0);
            const inputHit = Number(record.input_cache_hit_tokens ?? monthly.input_cache_hit_tokens ?? monthly.cache_hit_tokens ?? monthly.cached_tokens ?? 0);
            const output = Number(record.output_tokens ?? monthly.output_tokens ?? 0);
            const total = inputMiss + inputHit + output || Number(record.total_tokens ?? monthly.total_tokens ?? 0);
            const inputTotal = inputMiss + inputHit;
            const cacheHitRatio = record.avg_cache_hit_ratio !== undefined
                ? Number(record.avg_cache_hit_ratio || 0)
                : (inputTotal > 0 ? inputHit / inputTotal : 0);
            const costBreakdown = monthly.cost_breakdown || {};

            return {
                id: modelId,
                name: record.name || monthly.name || this.allModels[modelId]?.name || modelId,
                isSystem: record.is_system ?? monthly.is_system ?? modelId.startsWith('system_'),
                provider: record.provider || monthly.provider || '',
                style: record.style || monthly.style || '',
                recordCount: Number(record.record_count || 0),
                inputMiss,
                inputHit,
                output,
                total,
                cacheHitRatio,
                costTotal: Number(record.cost_total ?? monthly.cost_total ?? monthly.cost ?? 0),
                costInputMiss: Number(record.cost_input_cache_miss ?? costBreakdown.input_cache_miss_cost ?? 0),
                costInputHit: Number(record.cost_input_cache_hit ?? costBreakdown.input_cache_hit_cost ?? 0),
                costOutput: Number(record.cost_output ?? costBreakdown.output_cost ?? 0),
                prices: record.prices || {},
                sourceCounts: record.source_counts || {},
                styleCounts: record.style_counts || {}
            };
        }).sort((a, b) => b.costTotal - a.costTotal);
    },

    _renderModelTokenCards(models) {
        if (!models.length) {
            return '<div class="agent-token-empty"><i class="fas fa-info-circle me-2"></i>本月暂无使用记录</div>';
        }

        return models.map(model => {
            const stack = this._renderTokenStackBar([
                { label: '输入未命中', value: model.inputMiss, className: 'token-miss' },
                { label: '输入命中', value: model.inputHit, className: 'token-hit' },
                { label: '输出', value: model.output, className: 'token-output' }
            ]);
            const sourceBadges = Object.entries(model.sourceCounts).map(([source, count]) =>
                `<span class="badge bg-${source === 'actual' ? 'success' : 'warning'} text-${source === 'actual' ? 'white' : 'dark'}">${this.escapeHtml(source)} ${count}</span>`
            ).join(' ');

            return `
                <div class="agent-token-model-card">
                    <div class="agent-token-model-header">
                        <div>
                            <div class="fw-semibold">
                                <i class="fas fa-${model.isSystem ? 'server' : 'user-cog'} me-2 text-${model.isSystem ? 'primary' : 'secondary'}"></i>
                                ${this.escapeHtml(model.name)}
                            </div>
                            <div class="small text-muted">${this.escapeHtml(model.id)}${model.provider ? ` · ${this.escapeHtml(model.provider)}` : ''}${model.style ? ` · ${this.escapeHtml(model.style)}` : ''}</div>
                        </div>
                        <div class="text-end">
                            <div class="fw-semibold">${this._formatCNY(model.costTotal, 4)}</div>
                            <div class="small text-muted">${model.recordCount} 次请求</div>
                        </div>
                    </div>
                    ${stack}
                    <div class="agent-token-stat-grid">
                        <span><i class="token-dot token-miss"></i>未命中 ${this.formatNumber(model.inputMiss)}</span>
                        <span><i class="token-dot token-hit"></i>命中 ${this.formatNumber(model.inputHit)}</span>
                        <span><i class="token-dot token-output"></i>输出 ${this.formatNumber(model.output)}</span>
                        <span>命中率 ${(model.cacheHitRatio * 100).toFixed(1)}%</span>
                    </div>
                    <div class="agent-token-cost-row">
                        <span>miss ${this._formatCNY(model.costInputMiss, 6)}</span>
                        <span>hit ${this._formatCNY(model.costInputHit, 6)}</span>
                        <span>output ${this._formatCNY(model.costOutput, 6)}</span>
                        ${sourceBadges || '<span class="badge bg-secondary">暂无 source</span>'}
                    </div>
                </div>
            `;
        }).join('');
    },

    _renderTokenStackBar(parts) {
        const total = parts.reduce((sum, part) => sum + Math.max(0, Number(part.value || 0)), 0);
        if (total <= 0) return '<div class="agent-token-stack agent-token-stack-empty"></div>';

        return `<div class="agent-token-stack">${parts.filter(part => Number(part.value || 0) > 0).map(part => {
            const value = Number(part.value || 0);
            const percent = (value / total) * 100;
            return `<div class="agent-token-segment ${part.className}" style="width:${percent.toFixed(2)}%;" title="${this.escapeHtml(part.label)}: ${this.formatNumber(value)} (${percent.toFixed(1)}%)"></div>`;
        }).join('')}</div>`;
    },

    _renderUsageMetadataSummary(monthlyData, recordSummary) {
        const recordCount = recordSummary.request_record_count ?? recordSummary.record_count ?? monthlyData.request_record_count ?? 0;
        const callSites = Object.entries(recordSummary.by_call_site || {});
        const sources = Object.entries(recordSummary.by_source || {});

        if (!recordCount) {
            return '<div class="agent-token-empty"><i class="fas fa-database me-2"></i>暂无请求级用量记录</div>';
        }

        const callSiteHtml = callSites.map(([name, stats]) => `
            <div class="agent-token-meta-row">
                <span>${this.escapeHtml(name)}</span>
                <strong>${stats.count || stats.record_count || 0}</strong>
                <span>${this._formatCNY(stats.cost_total || 0, 4)}</span>
            </div>
        `).join('');
        const sourceHtml = sources.map(([name, stats]) =>
            `<span class="badge bg-${name === 'actual' ? 'success' : 'warning'} text-${name === 'actual' ? 'white' : 'dark'} me-1">${this.escapeHtml(name)} ${stats.count || 0}</span>`
        ).join('');

        return `
            <div class="agent-token-meta-total">请求记录 <strong>${recordCount}</strong> 条</div>
            <div class="agent-token-meta-title">调用点</div>
            ${callSiteHtml || '<div class="small text-muted">暂无调用点统计</div>'}
            <div class="agent-token-meta-title mt-3">数据来源</div>
            <div>${sourceHtml || '<span class="text-muted small">暂无 source 统计</span>'}</div>
        `;
    },

    _renderRecentUsageRecords(records) {
        if (!records.length) {
            return '<div class="agent-token-empty"><i class="fas fa-clock me-2"></i>暂无最近请求</div>';
        }

        return `
            <div class="table-responsive">
                <table class="table table-sm align-middle mb-0">
                    <thead>
                        <tr>
                            <th>时间</th>
                            <th>模型</th>
                            <th>调用点</th>
                            <th class="text-end">Token</th>
                            <th class="text-end">成本</th>
                            <th>source</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${records.map(record => `
                            <tr>
                                <td class="small text-muted">${this.escapeHtml(new Date(record.created_at).toLocaleString('zh-CN'))}</td>
                                <td>${this.escapeHtml(record.model_name || record.model_id || '-')}</td>
                                <td>${this.escapeHtml(record.call_site || '-')}</td>
                                <td class="text-end">${this.formatNumber(record.total_tokens || 0)}</td>
                                <td class="text-end">${this._formatCNY(record.cost_total || 0, 6)}</td>
                                <td><span class="badge bg-${record.source === 'actual' ? 'success' : 'warning'} text-${record.source === 'actual' ? 'white' : 'dark'}">${this.escapeHtml(record.source || '-')}</span></td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;
    },

    _setTokenStatsLoading() {
        const loading = '<div class="agent-token-empty"><i class="fas fa-spinner fa-spin me-2"></i>加载中...</div>';
        ['tokenModelStatsContainer', 'tokenUsageMetadataContainer', 'tokenRecentRecordsContainer'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = loading;
        });
    },

    _setTokenStatsError(message) {
        const errorHtml = `<div class="agent-token-empty text-danger"><i class="fas fa-exclamation-triangle me-2"></i>${this.escapeHtml(message || '加载失败')}</div>`;
        ['tokenModelStatsContainer', 'tokenUsageMetadataContainer', 'tokenRecentRecordsContainer'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = errorHtml;
        });
    },

    _setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    },

    _formatCNY(value, digits = 2) {
        return `¥${Number(value || 0).toFixed(digits)}`;
    },
    
    /**
     * 重置 Token 统计
     */
    async resetTokenStats() {
        if (!confirm('确定要重置当月 Token 统计数据吗？历史记录将保留。')) return;
        
        try {
            const response = await fetch('/api/agent/token-usage/reset/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({ reset_type: 'current' })
            });
            
            const data = await response.json();
            if (data.success) {
                this.showSuccess('当月统计数据已重置');
                await this.loadTokenStats();
            } else {
                this.showError(data.error || '重置失败');
            }
        } catch (error) {
            this.showError('重置失败: ' + error.message);
        }
    },
    
    /**
     * HTML 转义
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },
    
    // ==========================================
    // 工具函数
    // ==========================================
    
    formatNumber(num) {
        if (num >= 1048576) return (num / 1048576).toFixed(1) + 'M';  // 1024*1024
        if (num >= 1024) return (num / 1024).toFixed(1) + 'K';
        return num.toString();
    },
    
    getCSRFToken() {
        const cookie = document.cookie.split(';').find(c => c.trim().startsWith('csrftoken='));
        return cookie ? cookie.split('=')[1] : '';
    },
    
    showSuccess(message) {
        // 使用现有的通知系统或简单 alert
        if (window.showToast) {
            showToast(message, 'success');
        } else {
            alert('✅ ' + message);
        }
    },
    
    showError(message) {
        if (window.showToast) {
            showToast(message, 'error');
        } else {
            alert('❌ ' + message);
        }
    }
};

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    // 当切换到 AI 设置标签页时加载配置
    const aiTab = document.getElementById('ai-tab');
    if (aiTab) {
        aiTab.addEventListener('shown.bs.tab', () => {
            agentConfig.init();
        });
    }
    
    // 当切换到具体的子标签时刷新
    ['ai-model-config-tab', 'ai-optimization-tab', 'ai-token-stats-tab'].forEach(tabId => {
        const tab = document.getElementById(tabId);
        if (tab) {
            tab.addEventListener('shown.bs.pill', () => {
                if (!agentConfig.config) {
                    agentConfig.init();
                }
            });
        }
    });
});
