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
     * 更新 Token 统计 UI
     */
    updateTokenStatsUI(stats) {
        if (!stats) return;
        
        // 总体统计
        document.getElementById('totalInputTokens').textContent = 
            this.formatNumber(stats.total_input_tokens || 0);
        document.getElementById('totalOutputTokens').textContent = 
            this.formatNumber(stats.total_output_tokens || 0);
        document.getElementById('totalCost').textContent = 
            '￥' + (stats.total_cost || 0).toFixed(4);
        document.getElementById('quotaUsedRatio').textContent = 
            ((stats.quota_used_ratio || 0) * 100).toFixed(2) + '%';
        
        // 配额
        const quotaInput = document.getElementById('tokenQuota');
        if (quotaInput) quotaInput.value = stats.quota || 9999999;
        
        // 按模型统计表格
        this.updateModelStatsTable(stats.model_stats || {});
    },
    
    /**
     * 更新模型统计表格
     */
    updateModelStatsTable(modelStats) {
        const container = document.getElementById('modelStatsTable');
        if (!container) return;
        
        if (Object.keys(modelStats).length === 0) {
            container.innerHTML = `
                <div class="text-center text-muted py-3">
                    <i class="fas fa-info-circle me-2"></i>暂无使用记录
                </div>
            `;
            return;
        }
        
        let html = `
            <table class="table table-sm table-hover">
                <thead>
                    <tr>
                        <th>模型</th>
                        <th class="text-end">输入</th>
                        <th class="text-end">输出</th>
                        <th class="text-end">成本</th>
                    </tr>
                </thead>
                <tbody>
        `;
        
        for (const [modelId, stat] of Object.entries(modelStats)) {
            const modelName = this.allModels[modelId]?.name || modelId;
            html += `
                <tr>
                    <td>${modelName}</td>
                    <td class="text-end">${this.formatNumber(stat.input_tokens || 0)}</td>
                    <td class="text-end">${this.formatNumber(stat.output_tokens || 0)}</td>
                    <td class="text-end">￥${(stat.cost || 0).toFixed(4)}</td>
                </tr>
            `;
        }
        
        html += '</tbody></table>';
        container.innerHTML = html;
    },
    
    /**
     * 加载 Token 统计（新版）
     */
    async loadTokenStats() {
        try {
            const response = await fetch('/api/agent/token-usage/');
            const data = await response.json();
            
            if (data.success) {
                this.updateTokenStatsUI(data);
            }
        } catch (error) {
            console.error('[AgentConfig] 加载统计失败:', error);
        }
    },
    
    /**
     * 更新 Token 统计 UI（新版）
     */
    updateTokenStatsUI(data) {
        // 更新配额信息
        const monthlyCredit = data.monthly_credit || 5.0;
        const monthlyUsed = data.monthly_used || 0;
        const remaining = data.remaining || monthlyCredit;
        const currentMonth = data.current_month || '-';
        
        // 格式化货币
        const formatCNY = (val) => `¥${val.toFixed(2)}`;
        
        document.getElementById('tokenMonthlyUsed').textContent = formatCNY(monthlyUsed);
        document.getElementById('tokenMonthlyCredit').textContent = formatCNY(monthlyCredit);
        document.getElementById('tokenRemaining').textContent = formatCNY(remaining);
        document.getElementById('tokenCurrentMonth').textContent = currentMonth;
        
        // 更新进度条
        const usedPercent = monthlyCredit > 0 ? Math.min(100, (monthlyUsed / monthlyCredit) * 100) : 0;
        const progressBar = document.getElementById('tokenQuotaProgressBar');
        progressBar.style.width = `${usedPercent}%`;
        progressBar.setAttribute('aria-valuenow', usedPercent);
        document.getElementById('tokenQuotaPercent').textContent = `${usedPercent.toFixed(1)}%`;
        
        // 根据使用率改变进度条颜色
        progressBar.classList.remove('bg-success', 'bg-warning', 'bg-danger');
        if (usedPercent >= 90) {
            progressBar.classList.add('bg-danger');
        } else if (usedPercent >= 70) {
            progressBar.classList.add('bg-warning');
        } else {
            progressBar.classList.add('bg-success');
        }
        
        // 更新状态提示
        const statusAlert = document.getElementById('quotaStatusAlert');
        const statusText = document.getElementById('quotaStatusText');
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
        
        // 更新模型统计表格
        const tbody = document.getElementById('modelStatsTableBody');
        const models = data.models || {};
        
        if (Object.keys(models).length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" class="text-center text-muted py-3">
                        <i class="fas fa-info-circle me-2"></i>本月暂无使用记录
                    </td>
                </tr>
            `;
        } else {
            let rows = '';
            for (const [modelId, stats] of Object.entries(models)) {
                const isSystem = stats.is_system || modelId.startsWith('system_');
                const modelName = stats.name || modelId;
                rows += `
                    <tr>
                        <td>
                            <i class="fas fa-${isSystem ? 'server' : 'user-cog'} me-2 text-${isSystem ? 'primary' : 'secondary'}"></i>
                            ${this.escapeHtml(modelName)}
                        </td>
                        <td class="text-end">${this.formatNumber(stats.input_tokens || 0)}</td>
                        <td class="text-end">${this.formatNumber(stats.output_tokens || 0)}</td>
                        <td class="text-end">¥${(stats.cost || 0).toFixed(4)}</td>
                        <td>
                            <span class="badge bg-${isSystem ? 'primary' : 'secondary'}">
                                ${isSystem ? '系统' : '自定义'}
                            </span>
                        </td>
                    </tr>
                `;
            }
            tbody.innerHTML = rows;
        }
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
