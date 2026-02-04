/**
 * Quick Action 悬浮球管理器
 * 快速操作执行器的前端界面
 * 
 * 功能：
 * - 悬浮球主入口
 * - 支持分身（多个同时执行的任务）
 * - 实时状态显示
 * - 简单桌宠特性
 * - 刷新后恢复状态
 */
class QuickActionManager {
    constructor() {
        // 配置
        this.API_BASE = '/api/agent/quick-action/';
        this.POLL_INTERVAL = 500; // 轮询间隔(ms)
        this.AUTO_CLOSE_DELAY = 5000; // 成功后自动关闭延迟(ms)
        this.MAX_BUBBLES = 5; // 最大同时存在的气泡数
        
        // 状态
        this.mainBubble = null;
        this.taskBubbles = new Map(); // task_id -> bubble element
        this.isInputVisible = false;
        this.dragData = null;
        this.idleAnimationTimer = null;
        
        // 存储Key
        this.STORAGE_KEY = 'quick_action_tasks';
        
        // 初始化
        this.init();
    }
    
    init() {
        // 创建主悬浮球
        this.createMainBubble();
        
        // 恢复未完成的任务
        this.restoreTasks();
        
        // 监听模态框状态
        this.watchModalState();
        
        // 开始空闲动画
        this.startIdleAnimation();
        
        console.log('🔮 Quick Action Manager 初始化完成');
    }
    
    // ========================================
    // 主悬浮球
    // ========================================
    
    createMainBubble() {
        // 创建容器
        const container = document.createElement('div');
        container.id = 'quick-action-container';
        container.innerHTML = `
            <div class="qa-main-bubble" id="qa-main-bubble">
                <div class="qa-bubble-icon">
                    <i class="fas fa-bolt"></i>
                </div>
                <div class="qa-bubble-face">
                    <div class="qa-eye qa-eye-left"></div>
                    <div class="qa-eye qa-eye-right"></div>
                    <div class="qa-mouth"></div>
                </div>
                <div class="qa-split-btn" title="分身 - 创建新的快速操作">
                    <i class="fas fa-plus"></i>
                </div>
            </div>
            <div class="qa-input-panel" id="qa-input-panel">
                <div class="qa-input-header">
                    <span>⚡ 快速操作</span>
                    <button class="qa-close-btn" id="qa-close-input">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
                <div class="qa-input-body">
                    <textarea id="qa-input-text" placeholder="输入指令，如：明天下午3点开会讨论项目进度" rows="2"></textarea>
                    <div class="qa-input-hints">
                        <span class="qa-hint">创建日程</span>
                        <span class="qa-hint">完成待办</span>
                        <span class="qa-hint">修改时间</span>
                    </div>
                </div>
                <div class="qa-input-footer">
                    <button class="qa-send-btn" id="qa-send-btn">
                        <i class="fas fa-paper-plane"></i> 执行
                    </button>
                </div>
            </div>
        `;
        
        document.body.appendChild(container);
        
        // 缓存元素
        this.mainBubble = document.getElementById('qa-main-bubble');
        this.inputPanel = document.getElementById('qa-input-panel');
        this.inputText = document.getElementById('qa-input-text');
        
        // 绑定事件
        this.bindMainBubbleEvents();
        
        // 加载保存的位置
        this.loadPosition();
    }
    
    bindMainBubbleEvents() {
        const bubble = this.mainBubble;
        const splitBtn = bubble.querySelector('.qa-split-btn');
        
        // 点击主气泡
        bubble.addEventListener('click', (e) => {
            if (e.target.closest('.qa-split-btn')) return;
            this.toggleInput();
        });
        
        // 分身按钮 - 打开输入面板
        splitBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.showInput();
        });
        
        // 拖拽
        this.setupDrag(bubble);
        
        // 关闭输入面板
        document.getElementById('qa-close-input').addEventListener('click', () => {
            this.hideInput();
        });
        
        // 发送按钮
        document.getElementById('qa-send-btn').addEventListener('click', () => {
            this.sendQuickAction();
        });
        
        // 回车发送
        this.inputText.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendQuickAction();
            }
        });
        
        // 点击外部关闭
        document.addEventListener('click', (e) => {
            if (this.isInputVisible && 
                !e.target.closest('#quick-action-container')) {
                this.hideInput();
            }
        });
    }
    
    setupDrag(element) {
        let isDragging = false;
        let startX, startY, startLeft, startTop;
        
        element.addEventListener('mousedown', (e) => {
            if (e.target.closest('.qa-split-btn')) return;
            isDragging = true;
            startX = e.clientX;
            startY = e.clientY;
            const rect = element.getBoundingClientRect();
            startLeft = rect.left;
            startTop = rect.top;
            element.classList.add('dragging');
        });
        
        document.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            const newLeft = Math.max(0, Math.min(window.innerWidth - 60, startLeft + dx));
            const newTop = Math.max(0, Math.min(window.innerHeight - 60, startTop + dy));
            element.style.left = newLeft + 'px';
            element.style.top = newTop + 'px';
            element.style.right = 'auto';
            element.style.bottom = 'auto';
        });
        
        document.addEventListener('mouseup', () => {
            if (isDragging) {
                isDragging = false;
                element.classList.remove('dragging');
                this.savePosition();
            }
        });
    }
    
    toggleInput() {
        if (this.isInputVisible) {
            this.hideInput();
        } else {
            this.showInput();
        }
    }
    
    showInput() {
        // 计算输入面板位置
        this.positionInputPanel();
        
        this.inputPanel.classList.add('visible');
        this.isInputVisible = true;
        this.inputText.focus();
        this.mainBubble.classList.add('active');
        this.setBubbleMood('excited');
    }
    
    positionInputPanel() {
        const bubbleRect = this.mainBubble.getBoundingClientRect();
        const panelWidth = 320;
        const panelHeight = 250; // 估算高度
        const spacing = 20;
        
        // 计算各个方向的可用空间
        const spaceLeft = bubbleRect.left;
        const spaceRight = window.innerWidth - bubbleRect.right;
        const spaceTop = bubbleRect.top;
        const spaceBottom = window.innerHeight - bubbleRect.bottom;
        
        // 重置样式
        this.inputPanel.style.left = 'auto';
        this.inputPanel.style.right = 'auto';
        this.inputPanel.style.top = 'auto';
        this.inputPanel.style.bottom = 'auto';
        
        // 优先级：右侧 > 左侧 > 上方 > 下方
        if (spaceRight >= panelWidth + spacing) {
            // 显示在右侧
            this.inputPanel.style.left = (bubbleRect.right + spacing) + 'px';
            this.inputPanel.style.top = Math.max(spacing, bubbleRect.top - 50) + 'px';
        } else if (spaceLeft >= panelWidth + spacing) {
            // 显示在左侧
            this.inputPanel.style.right = (window.innerWidth - bubbleRect.left + spacing) + 'px';
            this.inputPanel.style.top = Math.max(spacing, bubbleRect.top - 50) + 'px';
        } else if (spaceTop >= panelHeight + spacing) {
            // 显示在上方
            this.inputPanel.style.bottom = (window.innerHeight - bubbleRect.top + spacing) + 'px';
            this.inputPanel.style.right = Math.max(spacing, window.innerWidth - bubbleRect.right) + 'px';
        } else {
            // 显示在下方
            this.inputPanel.style.top = (bubbleRect.bottom + spacing) + 'px';
            this.inputPanel.style.right = Math.max(spacing, window.innerWidth - bubbleRect.right) + 'px';
        }
    }
    
    hideInput() {
        this.inputPanel.classList.remove('visible');
        this.isInputVisible = false;
        this.mainBubble.classList.remove('active');
        this.setBubbleMood('idle');
    }
    
    // ========================================
    // 任务气泡（分身）
    // ========================================
    
    createTaskBubble(text = '', taskId = null) {
        if (this.taskBubbles.size >= this.MAX_BUBBLES) {
            this.showToast('最多同时执行 ' + this.MAX_BUBBLES + ' 个任务');
            return null;
        }
        
        const id = taskId || 'temp_' + Date.now();
        
        const bubble = document.createElement('div');
        bubble.className = 'qa-task-bubble';
        bubble.dataset.taskId = id;
        bubble.innerHTML = `
            <div class="qa-task-icon">
                <i class="fas fa-circle-notch fa-spin"></i>
            </div>
            <div class="qa-task-content">
                <div class="qa-task-text">${this.escapeHtml(text || '准备中...')}</div>
                <div class="qa-task-status">等待中</div>
            </div>
            <button class="qa-task-close" title="终止" data-action="cancel">
                <i class="fas fa-stop"></i>
            </button>
        `;
        
        // 计算位置（在主气泡附近）
        const mainRect = this.mainBubble.getBoundingClientRect();
        const offset = this.taskBubbles.size * 70;
        bubble.style.right = (window.innerWidth - mainRect.right + 60) + 'px';
        bubble.style.top = (mainRect.top + offset) + 'px';
        
        document.body.appendChild(bubble);
        
        // 绑定事件
        const closeBtn = bubble.querySelector('.qa-task-close');
        closeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            // 关键修复：始终从DOM获取最新的ID，因为任务开始后ID会从temp变更为真实UUID
            // 之前的闭包会锁死 temp ID，导致无法取消真实的后台任务
            const currentId = bubble.dataset.taskId;
            const action = closeBtn.dataset.action;
            
            if (action === 'cancel') {
                this.cancelTask(currentId);
            } else {
                this.closeTaskBubble(currentId);
            }
        });
        
        // 保存
        this.taskBubbles.set(id, bubble);
        
        // 入场动画
        requestAnimationFrame(() => {
            bubble.classList.add('visible');
        });
        
        return { id, bubble };
    }
    
    updateTaskBubble(taskId, status, message, resultType = null) {
        const bubble = this.taskBubbles.get(taskId);
        if (!bubble) return;
        
        const icon = bubble.querySelector('.qa-task-icon i');
        const statusEl = bubble.querySelector('.qa-task-status');
        const textEl = bubble.querySelector('.qa-task-text');
        const closeBtn = bubble.querySelector('.qa-task-close');
        
        // 更新状态文字
        const statusMap = {
            'pending': '等待中',
            'processing': '执行中...',
            'success': '完成',
            'failed': '失败',
            'timeout': '超时'
        };
        statusEl.textContent = statusMap[status] || status;
        
        // 更新图标和样式
        bubble.classList.remove('pending', 'processing', 'success', 'failed', 'error');
        
        switch (status) {
            case 'pending':
                icon.className = 'fas fa-clock';
                bubble.classList.add('pending');
                // 执行中显示终止按钮
                closeBtn.innerHTML = '<i class="fas fa-stop"></i>';
                closeBtn.title = '终止';
                closeBtn.dataset.action = 'cancel';
                break;
            case 'processing':
                icon.className = 'fas fa-circle-notch fa-spin';
                bubble.classList.add('processing');
                // 执行中显示终止按钮
                closeBtn.innerHTML = '<i class="fas fa-stop"></i>';
                closeBtn.title = '终止';
                closeBtn.dataset.action = 'cancel';
                break;
            case 'success':
                if (resultType === 'action_completed') {
                    icon.className = 'fas fa-check';
                    bubble.classList.add('success');
                } else if (resultType === 'need_clarification') {
                    icon.className = 'fas fa-question';
                    bubble.classList.add('pending');
                    statusEl.textContent = '需要补充信息';
                } else {
                    icon.className = 'fas fa-times';
                    bubble.classList.add('error');
                    statusEl.textContent = '操作失败';
                }
                // 完成后显示关闭按钮
                closeBtn.innerHTML = '<i class="fas fa-times"></i>';
                closeBtn.title = '关闭';
                closeBtn.dataset.action = 'close';
                // 重新绑定点击事件
                this.rebindCloseButton(taskId, closeBtn);
                break;
            case 'failed':
            case 'timeout':
                icon.className = 'fas fa-exclamation-triangle';
                bubble.classList.add('failed');
                // 失败后显示关闭按钮
                closeBtn.innerHTML = '<i class="fas fa-times"></i>';
                closeBtn.title = '关闭';
                closeBtn.dataset.action = 'close';
                // 重新绑定点击事件
                this.rebindCloseButton(taskId, closeBtn);
                break;
        }
        
        // 更新消息
        if (message) {
            textEl.textContent = message.substring(0, 100) + (message.length > 100 ? '...' : '');
            textEl.title = message;
        }
    }
    
    rebindCloseButton(taskId, closeBtn) {
        // 移除旧的事件监听器，添加新的
        const newBtn = closeBtn.cloneNode(true);
        closeBtn.parentNode.replaceChild(newBtn, closeBtn);
        
        newBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const action = newBtn.dataset.action;
            if (action === 'cancel') {
                this.cancelTask(taskId);
            } else {
                this.closeTaskBubble(taskId);
            }
        });
    }
    
    async cancelTask(taskId) {
        // 如果是临时ID（还未提交），直接关闭
        if (taskId.startsWith('temp_')) {
            this.closeTaskBubble(taskId);
            return;
        }
        
        // 获取CSRF Token
        const token = window.CSRF_TOKEN || document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
        
        try {
            const response = await fetch(`/api/agent/quick-action/${taskId}/cancel/`, {
                method: 'DELETE',
                headers: {
                    'X-CSRFToken': token
                }
            });
            
            if (response.ok) {
                this.updateTaskBubble(taskId, 'failed', '已取消');
                this.removeTaskFromStorage(taskId);
                setTimeout(() => {
                    this.closeTaskBubble(taskId);
                }, 1500);
            } else {
                console.error('取消任务失败');
                this.showToast('取消失败');
            }
        } catch (error) {
            console.error('取消任务出错:', error);
            this.showToast('取消失败');
        }
    }
    
    closeTaskBubble(taskId, animate = true) {
        const bubble = this.taskBubbles.get(taskId);
        if (!bubble) return;
        
        if (animate) {
            bubble.classList.remove('visible');
            bubble.classList.add('closing');
            setTimeout(() => {
                bubble.remove();
                this.taskBubbles.delete(taskId);
                this.saveTasksToStorage();
            }, 300);
        } else {
            bubble.remove();
            this.taskBubbles.delete(taskId);
        }
    }
    
    // ========================================
    // API 交互
    // ========================================
    
    async sendQuickAction() {
        const text = this.inputText.value.trim();
        if (!text) return;
        
        // 隐藏输入面板
        this.hideInput();
        this.inputText.value = '';
        
        // 创建任务气泡
        const result = this.createTaskBubble(text);
        if (!result) return;
        
        const { id: tempId, bubble } = result;
        
        try {
            // 发送请求
            const response = await fetch(this.API_BASE, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.CSRF_TOKEN
                },
                body: JSON.stringify({
                    text: text,
                    sync: false // 异步模式
                })
            });
            
            if (!response.ok) {
                throw new Error('请求失败: ' + response.status);
            }
            
            const data = await response.json();
            const taskId = data.task_id;
            
            // 更新气泡ID
            bubble.dataset.taskId = taskId;
            this.taskBubbles.delete(tempId);
            this.taskBubbles.set(taskId, bubble);
            
            // 保存到存储
            this.saveTaskToStorage(taskId, text);
            
            // 开始轮询
            this.pollTaskStatus(taskId, text);
            
            // 主气泡反馈
            this.setBubbleMood('working');
            
        } catch (error) {
            console.error('Quick Action 请求失败:', error);
            this.updateTaskBubble(tempId, 'failed', '请求失败: ' + error.message);
            this.addRetryButton(tempId, text);
            this.setBubbleMood('sad');
        }
    }
    
    async pollTaskStatus(taskId, originalText) {
        try {
            // 长轮询
            const response = await fetch(`${this.API_BASE}${taskId}/?wait=true`, {
                headers: {
                    'X-CSRFToken': window.CSRF_TOKEN
                }
            });
            
            if (!response.ok) {
                throw new Error('状态查询失败');
            }
            
            const data = await response.json();
            const status = data.status;
            const result = data.result || {};
            const resultType = data.result_type || result.type;
            const message = result.message || '';
            
            // 更新气泡
            this.updateTaskBubble(taskId, status, message, resultType);
            
            // 继续轮询或处理完成
            if (status === 'pending' || status === 'processing') {
                setTimeout(() => this.pollTaskStatus(taskId, originalText), this.POLL_INTERVAL);
            } else {
                // 任务完成
                this.removeTaskFromStorage(taskId);
                
                if (resultType === 'action_completed') {
                    // 成功
                    this.setBubbleMood('happy');
                    // 自动关闭
                    setTimeout(() => {
                        this.closeTaskBubble(taskId);
                    }, this.AUTO_CLOSE_DELAY);
                    // 刷新日历
                    this.refreshCalendar();
                } else if (resultType === 'need_clarification') {
                    // 需要补充信息
                    this.setBubbleMood('confused');
                    this.addRetryButton(taskId, originalText);
                } else {
                    // 失败
                    this.setBubbleMood('sad');
                    this.addRetryButton(taskId, originalText);
                }
            }
            
        } catch (error) {
            console.error('轮询失败:', error);
            this.updateTaskBubble(taskId, 'failed', '状态查询失败');
            this.addRetryButton(taskId, originalText);
            this.setBubbleMood('sad');
        }
    }
    
    addRetryButton(taskId, originalText) {
        const bubble = this.taskBubbles.get(taskId);
        if (!bubble) return;
        
        // 检查是否已有重试按钮
        if (bubble.querySelector('.qa-retry-btn')) return;
        
        const retryBtn = document.createElement('button');
        retryBtn.className = 'qa-retry-btn';
        retryBtn.innerHTML = '<i class="fas fa-redo"></i> 重试';
        retryBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.closeTaskBubble(taskId);
            this.inputText.value = originalText;
            this.showInput();
        });
        
        bubble.querySelector('.qa-task-content').appendChild(retryBtn);
    }
    
    // ========================================
    // 桌宠特性
    // ========================================
    
    setBubbleMood(mood) {
        const face = this.mainBubble.querySelector('.qa-bubble-face');
        const mouth = face.querySelector('.qa-mouth');
        const eyes = face.querySelectorAll('.qa-eye');
        
        // 移除所有mood类
        face.classList.remove('idle', 'excited', 'working', 'happy', 'sad', 'confused');
        face.classList.add(mood);
        
        // 更新表情
        switch (mood) {
            case 'idle':
                mouth.style.transform = 'translateY(0)';
                break;
            case 'excited':
                mouth.style.transform = 'scale(1.2)';
                break;
            case 'working':
                eyes.forEach(e => e.classList.add('focused'));
                break;
            case 'happy':
                mouth.style.transform = 'scale(1.3) translateY(-2px)';
                break;
            case 'sad':
                mouth.style.transform = 'rotate(180deg) translateY(5px)';
                break;
            case 'confused':
                eyes.forEach((e, i) => {
                    e.style.transform = i === 0 ? 'translateY(-2px)' : 'translateY(2px)';
                });
                break;
        }
    }
    
    startIdleAnimation() {
        const animations = [
            () => this.blinkEyes(),
            () => this.wiggle(),
            () => this.bounce(),
        ];
        
        const runRandomAnimation = () => {
            // 只在空闲时执行动画
            if (!this.isInputVisible && this.taskBubbles.size === 0) {
                const randomAnim = animations[Math.floor(Math.random() * animations.length)];
                randomAnim();
            }
            
            // 随机间隔 3-8 秒
            const nextDelay = 3000 + Math.random() * 5000;
            this.idleAnimationTimer = setTimeout(runRandomAnimation, nextDelay);
        };
        
        this.idleAnimationTimer = setTimeout(runRandomAnimation, 5000);
    }
    
    blinkEyes() {
        const eyes = this.mainBubble.querySelectorAll('.qa-eye');
        eyes.forEach(eye => eye.classList.add('blink'));
        setTimeout(() => {
            eyes.forEach(eye => eye.classList.remove('blink'));
        }, 200);
    }
    
    wiggle() {
        this.mainBubble.classList.add('wiggle');
        setTimeout(() => {
            this.mainBubble.classList.remove('wiggle');
        }, 500);
    }
    
    bounce() {
        this.mainBubble.classList.add('bounce');
        setTimeout(() => {
            this.mainBubble.classList.remove('bounce');
        }, 600);
    }
    
    // ========================================
    // 模态框状态监听
    // ========================================
    
    watchModalState() {
        // 监听 Bootstrap 模态框
        document.addEventListener('show.bs.modal', () => {
            this.setDisabled(true);
        });
        
        document.addEventListener('hidden.bs.modal', () => {
            this.setDisabled(false);
        });
        
        // 监听自定义模态框
        const observer = new MutationObserver(() => {
            const hasActiveModal = document.querySelector('.modal.show, .modal-backdrop.show');
            this.setDisabled(!!hasActiveModal);
        });
        
        observer.observe(document.body, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['class']
        });
    }
    
    setDisabled(disabled) {
        const container = document.getElementById('quick-action-container');
        if (container) {
            container.classList.toggle('disabled', disabled);
        }
    }
    
    // ========================================
    // 存储和恢复
    // ========================================
    
    savePosition() {
        const rect = this.mainBubble.getBoundingClientRect();
        localStorage.setItem('qa_bubble_position', JSON.stringify({
            left: rect.left,
            top: rect.top
        }));
    }
    
    loadPosition() {
        try {
            const saved = localStorage.getItem('qa_bubble_position');
            if (saved) {
                const pos = JSON.parse(saved);
                this.mainBubble.style.left = pos.left + 'px';
                this.mainBubble.style.top = pos.top + 'px';
                this.mainBubble.style.right = 'auto';
                this.mainBubble.style.bottom = 'auto';
            }
        } catch (e) {
            console.warn('无法加载悬浮球位置:', e);
        }
    }
    
    saveTaskToStorage(taskId, text) {
        try {
            const tasks = JSON.parse(localStorage.getItem(this.STORAGE_KEY) || '{}');
            tasks[taskId] = { text, timestamp: Date.now() };
            localStorage.setItem(this.STORAGE_KEY, JSON.stringify(tasks));
        } catch (e) {
            console.warn('无法保存任务:', e);
        }
    }
    
    removeTaskFromStorage(taskId) {
        try {
            const tasks = JSON.parse(localStorage.getItem(this.STORAGE_KEY) || '{}');
            delete tasks[taskId];
            localStorage.setItem(this.STORAGE_KEY, JSON.stringify(tasks));
        } catch (e) {
            console.warn('无法删除任务:', e);
        }
    }
    
    saveTasksToStorage() {
        try {
            const tasks = {};
            this.taskBubbles.forEach((bubble, taskId) => {
                if (!taskId.startsWith('temp_')) {
                    const text = bubble.querySelector('.qa-task-text').textContent;
                    tasks[taskId] = { text, timestamp: Date.now() };
                }
            });
            localStorage.setItem(this.STORAGE_KEY, JSON.stringify(tasks));
        } catch (e) {
            console.warn('无法保存任务列表:', e);
        }
    }
    
    async restoreTasks() {
        try {
            const tasks = JSON.parse(localStorage.getItem(this.STORAGE_KEY) || '{}');
            const now = Date.now();
            const maxAge = 24 * 60 * 60 * 1000; // 24小时
            
            for (const [taskId, info] of Object.entries(tasks)) {
                // 跳过过期任务
                if (now - info.timestamp > maxAge) {
                    this.removeTaskFromStorage(taskId);
                    continue;
                }
                
                // 创建气泡
                this.createTaskBubble(info.text, taskId);
                
                // 查询状态
                this.pollTaskStatus(taskId, info.text);
            }
        } catch (e) {
            console.warn('无法恢复任务:', e);
        }
    }
    
    // ========================================
    // 工具方法
    // ========================================
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    showToast(message) {
        // 使用现有的 toast 系统（如果有）或简单 alert
        if (window.showToast) {
            window.showToast(message, 'warning');
        } else {
            console.warn(message);
        }
    }
    
    refreshCalendar() {
        try {
            // 刷新日历 - 尝试多种可能的方法
            if (window.calendar) {
                if (typeof window.calendar.refetchEvents === 'function') {
                    window.calendar.refetchEvents();
                } else if (typeof window.calendar.render === 'function') {
                    window.calendar.render();
                }
                console.log('📅 日历已刷新');
            }
            
            // 刷新待办列表
            if (window.todoManager) {
                if (typeof window.todoManager.loadTodos === 'function') {
                    // loadTodos() 内部会调用 applyFilters()，保持筛选参数
                    window.todoManager.loadTodos();
                } else if (typeof window.todoManager.refreshTodoList === 'function') {
                    window.todoManager.refreshTodoList();
                }
                console.log('✅ 待办列表已刷新');
            }
            
            // 刷新提醒列表
            if (window.reminderManager && typeof window.reminderManager.loadReminders === 'function') {
                // loadReminders() 后由 settingsManager 应用筛选
                window.reminderManager.loadReminders();
                console.log('🔔 提醒列表已刷新');
            }
            
            // 刷新事件管理器
            if (window.eventManager && typeof window.eventManager.loadEvents === 'function') {
                window.eventManager.loadEvents();
                console.log('📆 事件管理器已刷新');
            }
        } catch (error) {
            console.warn('刷新界面时出错:', error);
            // 不影响用户体验，只记录警告
        }
    }
}

// 初始化
let quickActionManager = null;

document.addEventListener('DOMContentLoaded', () => {
    // 延迟初始化，确保其他组件已加载
    setTimeout(() => {
        quickActionManager = new QuickActionManager();
        window.quickActionManager = quickActionManager;
    }, 1000);
});
