// 提醒管理模块
class ReminderManager {
    constructor() {
        this.reminders = [];
        this.reminderContainer = null;
        this.pendingBulkEdit = null;  // 初始化为null
    }

    // 获取CSRF Token
    getCSRFToken() {
        return window.CSRF_TOKEN || '';
    }

    // 初始化提醒管理器
    init() {
        this.reminderContainer = document.getElementById('reminderList');
        
        this.loadReminders();
        this.startReminderCheck();
        this.initFilterListeners();
    }

    // 初始化筛选器事件监听器
    initFilterListeners() {
        const timeRangeSelect = document.getElementById('reminderTimeRange');
        const statusSelect = document.getElementById('reminderStatusFilter');
        const prioritySelect = document.getElementById('reminderPriorityFilter');
        const typeSelect = document.getElementById('reminderTypeFilter');

        if (timeRangeSelect) {
            timeRangeSelect.addEventListener('change', () => {
                console.log('提醒时间范围筛选变化:', timeRangeSelect.value);
                this.applyFilters();
            });
        }

        if (statusSelect) {
            statusSelect.addEventListener('change', () => {
                console.log('提醒状态筛选变化:', statusSelect.value);
                this.applyFilters();
            });
        }

        if (prioritySelect) {
            prioritySelect.addEventListener('change', () => {
                console.log('提醒优先级筛选变化:', prioritySelect.value);
                this.applyFilters();
            });
        }

        if (typeSelect) {
            typeSelect.addEventListener('change', () => {
                console.log('提醒类型筛选变化:', typeSelect.value);
                this.applyFilters();
            });
        }

        console.log('提醒筛选器事件监听器已初始化');
        console.log('✅ 提醒筛选器初始化成功');
    }

    // 加载提醒列表
    async loadReminders() {
        try {
            const response = await fetch('/api/reminders/');
            const data = await response.json();
            this.reminders = data.reminders || [];
            
            console.log('提醒数据加载完成，等待设置管理器应用筛选');
            // 移除自动调用，改为由设置管理器统一控制
            // this.applyFilters();
        } catch (error) {
            console.error('Error loading reminders:', error);
            this.reminders = [];
            this.renderReminders();
        }
    }

    // 渲染提醒列表
    renderReminders(filters = {}) {
        if (!this.reminderContainer) return;
        
        // 应用筛选条件
        let filteredReminders = this.reminders.filter(reminder => {
            // 时间范围筛选
            if (filters.timeRange && filters.timeRange !== 'all') {
                const triggerTime = new Date(reminder.trigger_time);
                const now = new Date();
                let rangeStart = new Date(now);
                let rangeEnd = new Date(now);
                
                switch (filters.timeRange) {
                    case 'today':
                        rangeStart.setHours(0, 0, 0, 0);
                        rangeEnd.setHours(23, 59, 59, 999);
                        break;
                    case 'week':
                        rangeStart.setDate(now.getDate() - now.getDay());
                        rangeStart.setHours(0, 0, 0, 0);
                        rangeEnd.setDate(rangeStart.getDate() + 6);
                        rangeEnd.setHours(23, 59, 59, 999);
                        break;
                    case 'month':
                        rangeStart.setDate(1);
                        rangeStart.setHours(0, 0, 0, 0);
                        rangeEnd.setMonth(rangeEnd.getMonth() + 1, 0);
                        rangeEnd.setHours(23, 59, 59, 999);
                        break;
                    case 'quarter':
                        const quarterMonth = Math.floor(now.getMonth() / 3) * 3;
                        rangeStart.setMonth(quarterMonth, 1);
                        rangeStart.setHours(0, 0, 0, 0);
                        rangeEnd.setMonth(quarterMonth + 3, 0);
                        rangeEnd.setHours(23, 59, 59, 999);
                        break;
                    case 'year':
                        rangeStart.setMonth(0, 1);
                        rangeStart.setHours(0, 0, 0, 0);
                        rangeEnd.setFullYear(rangeEnd.getFullYear() + 1, 0, 0);
                        rangeEnd.setHours(23, 59, 59, 999);
                        break;
                }
                
                if (triggerTime < rangeStart || triggerTime > rangeEnd) {
                    return false;
                }
            }
            
            // 状态筛选
            if (filters.status && filters.status !== 'all') {
                if (filters.status === 'snoozed') {
                    // 检查是否是延后状态
                    if (!reminder.status.startsWith('snoozed_')) return false;
                } else {
                    if (reminder.status !== filters.status) return false;
                }
            }
            
            // 优先级筛选
            if (filters.priority && filters.priority !== 'all') {
                if (reminder.priority !== filters.priority) return false;
            }
            
            // 类型筛选
            if (filters.type && filters.type !== 'all') {
                const hasRRule = reminder.rrule && reminder.rrule.includes('FREQ=');
                if (filters.type === 'recurring' && !hasRRule) return false;
                if (filters.type === 'single' && hasRRule) return false;
                if (filters.type === 'detached' && !reminder.is_detached) return false;
            }
            
            return true;
        });
        
        // 按触发时间排序
        filteredReminders.sort((a, b) => new Date(a.trigger_time) - new Date(b.trigger_time));

        this.reminderContainer.innerHTML = '';

        if (filteredReminders.length === 0) {
            this.reminderContainer.innerHTML = '<div class="empty-state">暂无符合条件的提醒</div>';
            return;
        }

        filteredReminders.forEach(reminder => {
            const reminderElement = this.createReminderElement(reminder);
            this.reminderContainer.appendChild(reminderElement);
        });
    }

    // 创建提醒元素
    createReminderElement(reminder) {
        const div = document.createElement('div');
        div.className = `reminder-item ${reminder.priority}`;
        div.dataset.reminderId = reminder.id;
        
        const priorityIcon = this.getPriorityIcon(reminder.priority);
        // 如果提醒被延后，显示延后后的时间；否则显示原始触发时间
        const displayTime = this.getEffectiveReminderTime(reminder);
        const timeStr = this.formatTriggerTime(displayTime);
        const isOverdue = new Date(displayTime) < new Date();
        
        div.innerHTML = `
            <div class="reminder-content">
                <div class="reminder-header">
                    <span class="reminder-priority">${priorityIcon}</span>
                    <span class="reminder-title ${isOverdue ? 'overdue' : ''}">${this.escapeHtml(reminder.title)}</span>
                    <div class="reminder-actions">
                        ${this.renderStatusButtons(reminder)}
                        <button class="btn-small" onclick="reminderManager.editReminder('${reminder.id}', '${reminder.series_id}')">编辑</button>
                        ${this.renderSnoozeButton(reminder)}
                        <button class="btn-small btn-danger" onclick="reminderManager.deleteReminder('${reminder.id}', '${reminder.series_id}')">删除</button>
                    </div>
                </div>
                ${reminder.content ? `<div class="reminder-content-text">${this.escapeHtml(reminder.content)}</div>` : ''}
                <div class="reminder-meta">
                    <span class="reminder-time ${isOverdue ? 'overdue' : ''}">${timeStr}</span>
                    ${reminder.rrule ? '<span class="reminder-repeat">🔄 重复</span>' : ''}
                </div>
                ${reminder.advance_triggers && reminder.advance_triggers.length > 0 ? 
                    `<div class="reminder-advance">
                        提前提醒: ${reminder.advance_triggers.map(at => at.time_before).join(', ')}
                    </div>` : ''
                }
            </div>
        `;

        return div;
    }

    // 获取优先级图标
    getPriorityIcon(priority) {
        const iconMap = {
            'urgent': '🔥',
            'high': '❗',
            'normal': '🔔',
            'low': '🔕',
            'debug': '🐛'
        };
        return iconMap[priority] || '🔔';
    }

    // 渲染状态按钮
    renderStatusButtons(reminder) {
        const status = reminder.status || 'active';
        const completedClass = status === 'completed' ? 'btn-success active' : 'btn-outline-success';
        const dismissedClass = status === 'dismissed' ? 'btn-secondary active' : 'btn-outline-secondary';
        
        return `
            <button class="btn-small ${completedClass}" onclick="reminderManager.toggleStatus('${reminder.id}', 'completed')" title="标记为完成">
                ✓
            </button>
            <button class="btn-small ${dismissedClass}" onclick="reminderManager.toggleStatus('${reminder.id}', 'dismissed')" title="标记为忽略">
                ✕
            </button>
        `;
    }

    // 渲染延后按钮
    renderSnoozeButton(reminder) {
        const isSnoozing = reminder.status && reminder.status.startsWith('snoozed_');
        
        if (isSnoozing) {
            // 显示当前延后状态和取消按钮
            const snoozeType = reminder.status.replace('snoozed_', '');
            let snoozeText = '';
            
            switch (snoozeType) {
                case '15m':
                    snoozeText = '15分钟后';
                    break;
                case '1h':
                    snoozeText = '1小时后';
                    break;
                case '1d':
                    snoozeText = '一天后';
                    break;
                case 'custom':
                    if (reminder.snooze_until) {
                        const snoozeTime = new Date(reminder.snooze_until);
                        snoozeText = this.formatTriggerTime(snoozeTime);
                    } else {
                        snoozeText = '已延后';
                    }
                    break;
                default:
                    snoozeText = '已延后';
            }
            
            return `
                <div class="snooze-group">
                    <button class="btn-small btn-warning active" disabled>${snoozeText}</button>
                    <button class="btn-small btn-outline-warning" onclick="reminderManager.cancelSnooze('${reminder.id}')" title="取消延后">✕</button>
                </div>
            `;
        } else {
            // 显示延后选项按钮
            return `
                <div class="dropdown d-inline">
                    <button class="btn-small btn-info" onclick="reminderManager.toggleSnoozeMenu('${reminder.id}')">延后▼</button>
                    <div class="snooze-menu" id="snoozeMenu_${reminder.id}" style="display: none;">
                        <button class="dropdown-item" onclick="reminderManager.snoozeReminder('${reminder.id}', '15m')">15分钟后</button>
                        <button class="dropdown-item" onclick="reminderManager.snoozeReminder('${reminder.id}', '1h')">1小时后</button>
                        <button class="dropdown-item" onclick="reminderManager.snoozeReminder('${reminder.id}', '1d')">一天后</button>
                        <button class="dropdown-item" onclick="reminderManager.customSnooze('${reminder.id}')">自定义</button>
                    </div>
                </div>
            `;
        }
    }

    // 切换延后菜单
    toggleSnoozeMenu(reminderId) {
        // 关闭所有其他菜单
        document.querySelectorAll('.snooze-menu').forEach(menu => {
            if (menu.id !== `snoozeMenu_${reminderId}`) {
                menu.style.display = 'none';
            }
        });
        
        // 切换当前菜单
        const menu = document.getElementById(`snoozeMenu_${reminderId}`);
        if (menu) {
            menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
        }
        
        // 添加点击外部关闭功能
        setTimeout(() => {
            document.addEventListener('click', this.closeSnoozeMenus.bind(this), { once: true });
        }, 0);
    }

    // 关闭所有延后菜单
    closeSnoozeMenus(event) {
        if (!event.target.closest('.dropdown')) {
            document.querySelectorAll('.snooze-menu').forEach(menu => {
                menu.style.display = 'none';
            });
        }
    }

    // 取消延后
    async cancelSnooze(reminderId) {
        return await this.updateReminderStatus(reminderId, 'active', '');
    }

    // 切换状态
    async toggleStatus(reminderId, targetStatus) {
        const reminder = this.reminders.find(r => r.id === reminderId);
        if (!reminder) return;
        
        // 如果当前状态与目标状态相同，则切换为active
        const newStatus = reminder.status === targetStatus ? 'active' : targetStatus;
        
        try {
            const response = await fetch('/api/reminders/update-status/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({
                    id: reminderId,
                    status: newStatus
                })
            });
            
            if (response.ok) {
                await this.loadReminders();
                // 重新应用当前筛选器设置
                this.applyFilters();
                return true;
            }
        } catch (error) {
            console.error('Error updating reminder status:', error);
        }
        return false;
    }

    // 获取提醒的有效时间（考虑延后）
    getEffectiveReminderTime(reminder) {
        // 如果提醒被延后且有snooze_until时间，使用延后时间
        if (reminder.status && reminder.status.startsWith('snoozed_') && reminder.snooze_until) {
            return reminder.snooze_until;
        }
        // 否则使用原始触发时间
        return reminder.trigger_time;
    }

    // 格式化触发时间
    formatTriggerTime(timeStr) {
        const date = new Date(timeStr);
        const now = new Date();
        const diff = date - now;
        const minutes = Math.floor(diff / (1000 * 60));
        const hours = Math.floor(minutes / 60);
        const days = Math.floor(hours / 24);
        
        if (diff < 0) {
            // 已过期的提醒
            const overdue = Math.abs(minutes);
            if (overdue < 60) {
                return `已过期 ${overdue} 分钟`;
            } else if (overdue < 1440) {
                return `已过期 ${Math.floor(overdue / 60)} 小时`;
            } else {
                return `已过期 ${Math.floor(overdue / 1440)} 天`;
            }
        } else if (minutes <= 600) {  // 10小时内(600分钟)显示倒计时
            if (minutes < 60) {
                return `${minutes} 分钟后`;
            } else {
                // 大于1小时的显示x时x分格式
                const remainingHours = Math.floor(minutes / 60);
                const remainingMinutes = minutes % 60;
                if (remainingMinutes === 0) {
                    return `${remainingHours} 小时后`;
                } else {
                    return `${remainingHours} 时 ${remainingMinutes} 分后`;
                }
            }
        } else {
            // 大于10小时，显示日期+时+分
            return date.toLocaleDateString('zh-CN', {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        }
    }

    // 转义HTML
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // 开始提醒检查
    startReminderCheck() {
        // 每分钟检查一次提醒
        setInterval(() => {
            this.checkReminders();
        }, 60000);
        
        // 立即检查一次
        this.checkReminders();
    }

    // 检查提醒
    checkReminders() {
        const now = new Date();
        
        this.reminders.forEach(reminder => {
            if (reminder.status !== 'active') return;
            
            const triggerTime = new Date(reminder.trigger_time);
            
            // 检查主提醒
            if (triggerTime <= now && !reminder.notification_sent) {
                this.triggerReminder(reminder);
            }
            
            // 检查提前提醒
            if (reminder.advance_triggers) {
                reminder.advance_triggers.forEach(advanceTrigger => {
                    const advanceTime = new Date(triggerTime.getTime() - this.parseDuration(advanceTrigger.time_before));
                    if (advanceTime <= now && !advanceTrigger.notification_sent) {
                        this.triggerAdvanceReminder(reminder, advanceTrigger);
                    }
                });
            }
        });
    }

    // 触发提醒
    triggerReminder(reminder) {
        // 立即标记为已发送，防止重复触发
        reminder.notification_sent = true;
        
        // 显示前端弹窗
        this.showReminderAlert(reminder);
        
        // 异步发送到后端（不阻塞）
        this.markNotificationSent(reminder.id);
    }

    // 触发提前提醒
    triggerAdvanceReminder(reminder, advanceTrigger) {
        // 立即标记为已发送，防止重复触发
        advanceTrigger.notification_sent = true;
        
        const message = advanceTrigger.message || `${advanceTrigger.time_before}后有提醒: ${reminder.title}`;
        this.showNotification(message, reminder.content, advanceTrigger.priority);
    }

    // 显示通知
    showNotification(title, content, priority) {
        // 浏览器通知
        if (Notification.permission === 'granted') {
            new Notification(title, {
                body: content,
                icon: '/static/images/reminder-icon.png'
            });
        }
        
        // 页面内通知
        this.showInPageNotification(title, content, priority);
    }

    // 显示页面内通知
    showInPageNotification(title, content, priority) {
        const notification = document.createElement('div');
        notification.className = `notification notification-${priority}`;
        notification.innerHTML = `
            <div class="notification-content">
                <div class="notification-title">${this.escapeHtml(title)}</div>
                ${content ? `<div class="notification-body">${this.escapeHtml(content)}</div>` : ''}
            </div>
            <button class="notification-close" onclick="this.parentElement.remove()">×</button>
        `;
        
        document.body.appendChild(notification);
        
        // 5秒后自动消失
        setTimeout(() => {
            if (notification.parentElement) {
                notification.remove();
            }
        }, 5000);
    }

    // 显示消息提示框（用于操作反馈）
    showMessage(message, type) {
        const messageBox = document.createElement('div');
        messageBox.className = 'message-box-overlay';
        messageBox.innerHTML = `
            <div class="message-box message-box-${type}">
                <div class="message-box-content">
                    <div class="message-box-icon">
                        ${type === 'success' ? '✓' : type === 'error' ? '✗' : 'ℹ'}
                    </div>
                    <div class="message-box-text">${this.escapeHtml(message)}</div>
                </div>
                <button class="message-box-close" onclick="this.parentElement.remove()">确定</button>
            </div>
        `;
        
        document.body.appendChild(messageBox);
        
        // 3秒后自动消失
        setTimeout(() => {
            if (messageBox.parentElement) {
                messageBox.remove();
            }
        }, 3000);
    }

    // 显示提醒触发弹窗
    showReminderAlert(reminder) {
        const alertBox = document.createElement('div');
        alertBox.className = 'reminder-alert-overlay';
        alertBox.innerHTML = `
            <div class="reminder-alert-box ${reminder.priority}">
                <div class="reminder-alert-header">
                    <span class="reminder-alert-priority">${this.getPriorityIcon(reminder.priority)}</span>
                    <span class="reminder-alert-title">${this.escapeHtml(reminder.title)}</span>
                    <span class="reminder-alert-time">${this.formatTriggerTime(reminder.trigger_time)}</span>
                </div>
                <div class="reminder-alert-content">
                    <div class="reminder-alert-content-text">${this.escapeHtml(reminder.content || '无详细内容')}</div>
                    ${reminder.rrule ? '<div style="margin-top: 10px; color: #666; font-size: 14px;">🔄 重复提醒</div>' : ''}
                </div>
                <div class="reminder-alert-actions">
                    <button class="reminder-alert-btn reminder-alert-btn-ignore" onclick="reminderManager.handleReminderAlertAction('${reminder.id}', 'ignore')">忽略</button>
                    <button class="reminder-alert-btn reminder-alert-btn-snooze" onclick="reminderManager.handleReminderAlertAction('${reminder.id}', 'snooze')">延后</button>
                    <button class="reminder-alert-btn reminder-alert-btn-complete" onclick="reminderManager.handleReminderAlertAction('${reminder.id}', 'complete')">完成</button>
                </div>
            </div>
        `;
        
        document.body.appendChild(alertBox);
        
        // 点击背景关闭（相当于忽略）
        alertBox.addEventListener('click', (e) => {
            if (e.target === alertBox) {
                this.handleReminderAlertAction(reminder.id, 'ignore');
            }
        });
    }

    // 处理提醒弹窗操作
    async handleReminderAlertAction(reminderId, action) {
        // 关闭弹窗
        const alertBox = document.querySelector('.reminder-alert-overlay');
        if (alertBox) {
            alertBox.remove();
        }

        // 执行对应操作
        switch (action) {
            case 'ignore':
                await this.dismissReminder(reminderId);
                break;
            case 'snooze':
                // 显示延后选项
                this.showSnoozeOptions(reminderId);
                break;
            case 'complete':
                await this.completeReminder(reminderId);
                break;
        }
    }

    // 显示延后选项
    showSnoozeOptions(reminderId) {
        // 找到原提醒数据，以便取消时能重新显示
        const reminder = this.reminders.find(r => r.id === reminderId);
        
        const snoozeBox = document.createElement('div');
        snoozeBox.className = 'message-box-overlay';
        snoozeBox.innerHTML = `
            <div class="message-box">
                <div class="message-box-content">
                    <div class="message-box-text">选择延后时间：</div>
                    <div style="margin: 15px 0;">
                        <button class="reminder-alert-btn reminder-alert-btn-snooze" onclick="reminderManager.executeSnooze('${reminderId}', '15m')" style="margin: 5px;">15分钟后</button>
                        <button class="reminder-alert-btn reminder-alert-btn-snooze" onclick="reminderManager.executeSnooze('${reminderId}', '1h')" style="margin: 5px;">1小时后</button>
                        <button class="reminder-alert-btn reminder-alert-btn-snooze" onclick="reminderManager.executeSnooze('${reminderId}', '1d')" style="margin: 5px;">一天后</button>
                    </div>
                    <div style="margin-top: 10px;">
                        <button class="reminder-alert-btn reminder-alert-btn-snooze" onclick="reminderManager.customSnoozeFromAlert('${reminderId}')" style="margin: 5px;">自定义时间</button>
                    </div>
                </div>
                <button class="message-box-close" onclick="reminderManager.cancelSnoozeAndRestoreAlert('${reminderId}')">取消</button>
            </div>
        `;
        
        document.body.appendChild(snoozeBox);
    }

    // 取消延后并恢复提醒弹窗
    cancelSnoozeAndRestoreAlert(reminderId) {
        // 关闭延后选项弹窗
        const snoozeBox = document.querySelector('.message-box-overlay');
        if (snoozeBox) {
            snoozeBox.remove();
        }
        
        // 重新显示原提醒弹窗
        const reminder = this.reminders.find(r => r.id === reminderId);
        if (reminder) {
            this.showReminderAlert(reminder);
        }
    }

    // 执行延后操作（从弹窗调用）
    async executeSnooze(reminderId, snoozeType) {
        // 关闭延后选项弹窗
        const snoozeBox = document.querySelector('.message-box-overlay');
        if (snoozeBox) {
            snoozeBox.remove();
        }
        
        await this.snoozeReminder(reminderId, snoozeType);
    }

    // 自定义延后时间（从弹窗调用）
    async customSnoozeFromAlert(reminderId) {
        // 关闭延后选项弹窗
        const snoozeBox = document.querySelector('.message-box-overlay');
        if (snoozeBox) {
            snoozeBox.remove();
        }
        
        const timeInput = prompt('请输入延后时间（格式：YYYY-MM-DD HH:MM）：');
        if (timeInput) {
            try {
                const snoozeUntil = new Date(timeInput);
                if (snoozeUntil > new Date()) {
                    await this.updateReminderStatus(reminderId, 'snoozed_custom', snoozeUntil.toISOString());
                } else {
                    alert('延后时间必须在未来');
                    // 时间无效，重新显示提醒弹窗
                    const reminder = this.reminders.find(r => r.id === reminderId);
                    if (reminder) {
                        this.showReminderAlert(reminder);
                    }
                }
            } catch (error) {
                alert('时间格式错误');
                // 格式错误，重新显示提醒弹窗
                const reminder = this.reminders.find(r => r.id === reminderId);
                if (reminder) {
                    this.showReminderAlert(reminder);
                }
            }
        } else {
            // 用户取消了输入，重新显示提醒弹窗
            const reminder = this.reminders.find(r => r.id === reminderId);
            if (reminder) {
                this.showReminderAlert(reminder);
            }
        }
    }

    // 解析时间长度
    parseDuration(duration) {
        const match = duration.match(/(\d+)([mhd])/);
        if (!match) return 0;
        
        const value = parseInt(match[1]);
        const unit = match[2];
        
        switch (unit) {
            case 'm': return value * 60 * 1000;
            case 'h': return value * 60 * 60 * 1000;
            case 'd': return value * 24 * 60 * 60 * 1000;
            default: return 0;
        }
    }

    // 标记通知已发送
    async markNotificationSent(reminderId) {
        // 异步发送到后端，不阻塞前端提醒显示
        fetch('/api/reminders/mark-sent/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCSRFToken()
            },
            body: JSON.stringify({ reminder_id: reminderId })
        }).catch(error => {
            // 静默处理错误，不影响前端提醒功能
            console.warn('Failed to mark notification sent (non-critical):', error);
        });
    }

    // 创建新提醒
    async createReminder(reminderData) {
        try {
            const response = await fetch('/api/reminders/create/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify(reminderData)
            });
            
            if (response.ok) {
                await this.loadReminders();
                // 重新应用当前筛选器设置
                this.applyFilters();
                return true;
            }
        } catch (error) {
            console.error('Error creating reminder:', error);
        }
        return false;
    }

    // 更新提醒
    async updateReminder(reminderId, reminderData) {
        console.log('DEBUG: updateReminder called with:', reminderId, reminderData);
        
        try {
            // 检查是否有待处理的批量编辑（来自模态框管理器）
            const hasPendingBulkEdit = this.pendingBulkEdit != null;  // 使用 != null 同时检查 null 和 undefined
            console.log('DEBUG: hasPendingBulkEdit =', hasPendingBulkEdit, 'pendingBulkEdit =', this.pendingBulkEdit);
            
            // 检查是否是创建新系列模式
            const isCreateNewSeries = reminderData.create_new_series === true;
            console.log('DEBUG: isCreateNewSeries =', isCreateNewSeries);
            
            // 只有在非批量编辑模式且非创建新系列模式下才检查重复规则变化
            if (!hasPendingBulkEdit && !isCreateNewSeries) {
                // 检查是否涉及重复规则变化
                const originalReminder = this.reminders.find(r => r.id === reminderId);
                if (!originalReminder) {
                    console.error('未找到原始提醒');
                    return false;
                }
                
                const originalRrule = originalReminder.rrule;
                const newRrule = reminderData.rrule;
                const changeType = this.analyzeRruleChange(originalRrule, newRrule);
                
                console.log('DEBUG: originalRrule =', originalRrule);
                console.log('DEBUG: newRrule =', newRrule);
                console.log('DEBUG: changeType =', changeType);
                
                // 如果是重复规则变化，需要用户选择影响范围
                if (changeType === 'recurring_rule_change') {
                    const scope = await this.showRruleChangeDialog(reminderId, originalReminder);
                    if (!scope) {
                        return false; // 用户取消
                    }
                    reminderData.rrule_change_scope = scope;
                } else if (changeType === 'recurring_to_single') {
                    // 重复变单个，确认操作并设置scope
                    if (!confirm('确定要将此重复提醒转换为单个提醒吗？这将从系列中分离此提醒。')) {
                        return false;
                    }
                    // 设置scope为single，表示只影响当前提醒
                    reminderData.rrule_change_scope = 'this_only';
                } else if (changeType === 'single_to_recurring') {
                    // 单个变重复，确认操作并设置scope
                    if (!confirm('确定要将此单个提醒转换为重复提醒吗？系统将根据重复规则生成未来的提醒实例。')) {
                        return false;
                    }
                    // 设置scope为all，表示创建新的重复系列
                    reminderData.rrule_change_scope = 'all';
                }
            }
            
            const response = await fetch('/api/reminders/update/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({
                    id: reminderId,
                    ...reminderData
                })
            });
            
            if (response.ok) {
                await this.loadReminders();
                // 重新应用当前筛选器设置
                this.applyFilters();
                
                // 确保日历视图刷新
                if (window.eventManager && window.eventManager.calendar) {
                    console.log('updateReminder成功后刷新日历');
                    window.eventManager.calendar.refetchEvents();
                }
                
                return true;
            }
        } catch (error) {
            console.error('Error updating reminder:', error);
        }
        return false;
    }

    // 分析重复规则变化类型
    analyzeRruleChange(originalRrule, newRrule) {
        if (originalRrule === newRrule) {
            return 'no_change';
        } else if (!originalRrule && newRrule) {
            return 'single_to_recurring';
        } else if (originalRrule && !newRrule) {
            return 'recurring_to_single';
        } else if (originalRrule && newRrule && originalRrule !== newRrule) {
            return 'recurring_rule_change';
        } else {
            return 'no_change';
        }
    }

    // 显示重复规则变化对话框
    async showRruleChangeDialog(reminderId, reminder) {
        return new Promise((resolve) => {
            const dialogHTML = `
                <div class="modal fade" id="rruleChangeModal" tabindex="-1">
                    <div class="modal-dialog">
                        <div class="modal-content">
                            <div class="modal-header">
                                <h5 class="modal-title">重复规则已变更</h5>
                                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                            </div>
                            <div class="modal-body">
                                <p>您修改了重复提醒的重复规则，请选择变更的影响范围：</p>
                                <div class="form-check">
                                    <input class="form-check-input" type="radio" name="rruleChangeScope" id="scope_this_only" value="this_only">
                                    <label class="form-check-label" for="scope_this_only">
                                        <strong>仅此提醒</strong><br>
                                        <small class="text-muted">将此提醒从系列中分离，只对此提醒应用新规则</small>
                                    </label>
                                </div>
                                <div class="form-check mt-2">
                                    <input class="form-check-input" type="radio" name="rruleChangeScope" id="scope_from_this" value="from_this" checked>
                                    <label class="form-check-label" for="scope_from_this">
                                        <strong>此提醒及之后</strong><br>
                                        <small class="text-muted">对此提醒及所有未来的提醒应用新规则</small>
                                    </label>
                                </div>
                                <div class="form-check mt-2">
                                    <input class="form-check-input" type="radio" name="rruleChangeScope" id="scope_all" value="all">
                                    <label class="form-check-label" for="scope_all">
                                        <strong>整个系列</strong><br>
                                        <small class="text-muted">对整个重复提醒系列应用新规则（包括过去的提醒）</small>
                                    </label>
                                </div>
                            </div>
                            <div class="modal-footer">
                                <button type="button" class="btn btn-secondary" onclick="reminderManager.cancelRruleChangeDialog()">取消</button>
                                <button type="button" class="btn btn-primary" onclick="reminderManager.confirmRruleChange()">确认</button>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            
            // 移除已存在的对话框
            const existingModal = document.getElementById('rruleChangeModal');
            if (existingModal) {
                existingModal.remove();
            }
            
            // 添加新对话框
            document.body.insertAdjacentHTML('beforeend', dialogHTML);
            
            // 显示对话框
            const modal = document.getElementById('rruleChangeModal');
            modal.style.display = 'block';
            modal.classList.add('show');
            
            // 保存 resolve 函数供后续调用
            this.rruleChangeResolve = resolve;
            
            // 添加关闭事件
            modal.querySelector('.btn-close').onclick = () => this.cancelRruleChangeDialog();
            
            // 点击背景关闭
            modal.onclick = (e) => {
                if (e.target === modal) {
                    this.cancelRruleChangeDialog();
                }
            };
        });
    }

    // 确认重复规则变更
    confirmRruleChange() {
        const scope = document.querySelector('input[name="rruleChangeScope"]:checked')?.value;
        if (scope) {
            this.closeRruleChangeModal();
            if (this.rruleChangeResolve) {
                this.rruleChangeResolve(scope);
            }
        } else {
            alert('请选择影响范围');
        }
    }

    // 取消重复规则变更
    cancelRruleChangeDialog() {
        this.closeRruleChangeModal();
        if (this.rruleChangeResolve) {
            this.rruleChangeResolve(null);
        }
    }

    // 关闭重复规则变更对话框
    closeRruleChangeModal() {
        const modal = document.getElementById('rruleChangeModal');
        if (modal) {
            modal.style.display = 'none';
            modal.classList.remove('show');
            modal.remove();
        }
        this.rruleChangeResolve = null;
    }
    

    // 编辑提醒
    editReminder(reminderId, seriesId) {
        console.log('=== editReminder called ===');
        console.log('reminderId:', reminderId, 'seriesId:', seriesId);
        
        const reminder = this.reminders.find(r => r.id === reminderId);
        if (!reminder) return;
        
        console.log('Found reminder:', reminder);
        
        // 检查是否是重复提醒 - 改进逻辑：有rrule就认为是重复提醒
        const hasRrule = reminder.rrule && reminder.rrule.includes('FREQ=');
        const seriesReminders = this.reminders.filter(r => r.series_id === seriesId && r.rrule && r.rrule.includes('FREQ='));
        
        console.log('hasRrule:', hasRrule, 'is_detached:', reminder.is_detached);
        
        if (hasRrule && !reminder.is_detached) {
            // 这是重复提醒，显示选择对话框（即使只有一个实例）
            console.log('Showing bulk edit dialog for recurring reminder');
            this.showBulkEditDialog(reminderId, seriesId, 'edit');
        } else {
            // 单独提醒，直接编辑
            console.log('Opening edit modal for single reminder');
            modalManager.openEditReminderModal(reminder);
        }
    }
    

    // 删除提醒
    deleteReminder(reminderId, seriesId) {
        const reminder = this.reminders.find(r => r.id === reminderId);
        if (!reminder) return;
        
        // 检查是否是重复提醒 - 改进逻辑：有rrule就认为是重复提醒
        const hasRrule = reminder.rrule && reminder.rrule.includes('FREQ=');
        const seriesReminders = this.reminders.filter(r => r.series_id === seriesId && r.rrule && r.rrule.includes('FREQ='));
        
        if (hasRrule && !reminder.is_detached) {
            // 这是重复提醒，显示选择对话框（即使只有一个实例）
            this.showBulkEditDialog(reminderId, seriesId, 'delete');
        } else {
            // 单独提醒，直接删除
            if (confirm('确定要删除这个提醒吗？')) {
                this.deleteSingleReminder(reminderId);
            }
        }
    }

    // 显示批量编辑对话框
    showBulkEditDialog(reminderId, seriesId, operation) {
        const reminder = this.reminders.find(r => r.id === reminderId);
        const seriesReminders = this.reminders.filter(r => r.series_id === seriesId).sort((a, b) => new Date(a.trigger_time) - new Date(b.trigger_time));
        
        // 生成未来时间点选项
        const futureOptions = seriesReminders
            .filter(r => new Date(r.trigger_time) >= new Date())
            .slice(0, 10) // 最多显示10个选项
            .map(r => ({
                value: r.trigger_time,
                label: this.formatTriggerTime(r.trigger_time)
            }));
        
        const operationText = operation === 'edit' ? '编辑' : '删除';
        
        const dialogHTML = `
            <div class="modal fade" id="bulkEditModal" tabindex="-1">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">${operationText}重复提醒</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <p>这是一个重复提醒，请选择${operationText}范围：</p>
                            <div class="form-check">
                                <input class="form-check-input" type="radio" name="editScope" id="scope_this_only" value="this_only">
                                <label class="form-check-label" for="scope_this_only">
                                    仅此提醒 (分离后单独${operationText})
                                </label>
                            </div>
                            <div class="form-check">
                                <input class="form-check-input" type="radio" name="editScope" id="scope_all" value="all">
                                <label class="form-check-label" for="scope_all">
                                    所有提醒 (整个系列)
                                </label>
                            </div>
                            <div class="form-check">
                                <input class="form-check-input" type="radio" name="editScope" id="scope_from_this" value="from_this" checked>
                                <label class="form-check-label" for="scope_from_this">
                                    此提醒及之后
                                </label>
                            </div>
                            <div class="form-check">
                                <input class="form-check-input" type="radio" name="editScope" id="scope_from_time" value="from_time">
                                <label class="form-check-label" for="scope_from_time">
                                    从指定时间开始：
                                </label>
                                <select class="form-select form-select-sm mt-2" id="timeSelect">
                                    ${futureOptions.map(opt => `<option value="${opt.value}">${opt.label}</option>`).join('')}
                                </select>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" onclick="reminderManager.cancelBulkEdit()">取消</button>
                            <button type="button" class="btn btn-primary" onclick="reminderManager.executeBulkEdit('${reminderId}', '${seriesId}', '${operation}')">确认${operationText}</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // 移除已存在的对话框
        const existingModal = document.getElementById('bulkEditModal');
        if (existingModal) {
            existingModal.remove();
        }
        
        // 添加新对话框
        document.body.insertAdjacentHTML('beforeend', dialogHTML);
        
        // 显示对话框（不依赖Bootstrap JS）
        const modal = document.getElementById('bulkEditModal');
        modal.style.display = 'block';
        modal.classList.add('show');
        
        // 添加关闭事件
        modal.querySelector('.btn-close').onclick = () => this.closeBulkEditModal();
        modal.querySelector('[data-bs-dismiss="modal"]').onclick = () => this.closeBulkEditModal();
        
        // 点击背景关闭
        modal.onclick = (e) => {
            if (e.target === modal) {
                this.closeBulkEditModal();
            }
        };
    }

    // 关闭批量编辑对话框
    closeBulkEditModal() {
        const modal = document.getElementById('bulkEditModal');
        if (modal) {
            // 尝试使用Bootstrap API关闭
            const bsModal = bootstrap.Modal.getInstance(modal);
            if (bsModal) {
                bsModal.hide();
            } else {
                // 手动关闭
                modal.style.display = 'none';
                modal.classList.remove('show');
                // 移除背景遮罩
                const backdrop = document.querySelector('.modal-backdrop');
                if (backdrop) {
                    backdrop.remove();
                }
                // 恢复body的滚动
                document.body.classList.remove('modal-open');
                document.body.style.paddingRight = '';
            }
            modal.remove();
        }
        
        // 清除待处理的批量编辑信息
        this.pendingBulkEdit = null;
    }

    // 忽略提醒
    async dismissReminder(reminderId) {
        try {
            const response = await fetch('/api/reminders/dismiss/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({ id: reminderId })
            });
            
            if (response.ok) {
                await this.loadReminders();
                // 重新应用当前筛选器设置
                this.applyFilters();
                
                // 确保日历视图刷新
                if (window.eventManager && window.eventManager.calendar) {
                    console.log('dismissReminder成功后刷新日历');
                    window.eventManager.calendar.refetchEvents();
                }
                
                return true;
            }
        } catch (error) {
            console.error('Error dismissing reminder:', error);
        }
        return false;
    }

    // 完成提醒
    async completeReminder(reminderId) {
        try {
            const response = await fetch('/api/reminders/complete/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({ id: reminderId })
            });
            
            if (response.ok) {
                await this.loadReminders();
                // 重新应用当前筛选器设置
                this.applyFilters();
                
                // 确保日历视图刷新
                if (window.eventManager && window.eventManager.calendar) {
                    console.log('completeReminder成功后刷新日历');
                    window.eventManager.calendar.refetchEvents();
                }
                
                return true;
            }
        } catch (error) {
            console.error('Error completing reminder:', error);
        }
        return false;
    }

    // 应用筛选条件
    applyFilters(providedFilters = null) {
        console.log('=== 提醒筛选器 applyFilters() 方法开始执行 ===');
        console.log('传入的 providedFilters 参数:', providedFilters);
        console.log('参数类型:', typeof providedFilters);
        console.log('参数是否为空:', providedFilters === null);
        
        let filters = {};
        
        if (providedFilters) {
            // 如果提供了筛选条件参数，使用参数
            filters = { ...providedFilters };
            console.log('使用提供的筛选条件:', filters);
        } else {
            console.log('没有提供筛选条件，从DOM读取');
            // 否则从DOM读取当前值
            const timeRangeFilter = document.getElementById('reminderTimeRange')?.value || 'today';
            const statusFilter = document.getElementById('reminderStatusFilter')?.value || 'active';
            const priorityFilter = document.getElementById('reminderPriorityFilter')?.value || 'all';
            const typeFilter = document.getElementById('reminderTypeFilter')?.value || 'all';
            
            console.log('DOM元素值检查:');
            console.log('- reminderTimeRange element:', document.getElementById('reminderTimeRange'));
            console.log('- reminderTimeRange value:', document.getElementById('reminderTimeRange')?.value);
            console.log('- reminderStatusFilter element:', document.getElementById('reminderStatusFilter'));
            console.log('- reminderStatusFilter value:', document.getElementById('reminderStatusFilter')?.value);
            
            filters = {
                timeRange: timeRangeFilter,
                status: statusFilter,
                priority: priorityFilter,
                type: typeFilter
            };
            
            console.log('从DOM提取的筛选器值:', filters);
        }
        
        console.log('最终筛选器对象:', filters);
        
        // 保存筛选器设置到后端
        if (window.settingsManager) {
            console.log('找到 settingsManager，准备保存筛选器设置');
            window.settingsManager.updateCategorySettings('reminderFilters', filters);
            console.log('筛选器设置保存完成');
        } else {
            console.warn('未找到 settingsManager，无法保存筛选器设置');
        }
        
        this.renderReminders(filters);
        
        // 同步刷新日历视图中的提醒显示
        if (window.eventManager && window.eventManager.calendar) {
            console.log('刷新日历视图中的提醒');
            window.eventManager.calendar.refetchEvents();
        }
        
        console.log('=== 提醒筛选器 applyFilters() 方法执行完成 ===');
    }

    // 执行批量编辑
    async executeBulkEdit(reminderId, seriesId, operation) {
        console.log('=== executeBulkEdit called ===');
        console.log('reminderId:', reminderId, 'seriesId:', seriesId, 'operation:', operation);
        
        const scope = document.querySelector('input[name="editScope"]:checked')?.value;
        console.log('Selected scope:', scope);
        
        if (!scope) {
            alert('请选择操作范围');
            return;
        }
        
        let fromTime = '';
        if (scope === 'from_time') {
            fromTime = document.getElementById('timeSelect')?.value;
        } else if (scope === 'from_this') {
            const reminder = this.reminders.find(r => r.id === reminderId);
            fromTime = reminder?.trigger_time;
        }
        
        console.log('fromTime:', fromTime);
        
        if (operation === 'edit') {
            // 关闭批量对话框，打开编辑对话框
            console.log('Closing bulk edit modal and opening edit modal');
            this.closeBulkEditModal();
            
            // 保存批量编辑信息到临时变量
            this.pendingBulkEdit = { reminderId, seriesId, scope, fromTime };
            console.log('Set pendingBulkEdit:', this.pendingBulkEdit);
            
            // 打开编辑对话框
            const reminder = this.reminders.find(r => r.id === reminderId);
            console.log('Opening edit reminder modal with reminder:', reminder);
            modalManager.openEditReminderModal(reminder);
        } else if (operation === 'delete') {
            if (confirm(`确定要删除选定范围的提醒吗？`)) {
                await this.performBulkOperation(seriesId, operation, scope, fromTime, reminderId);
                this.closeBulkEditModal();
            }
        }
    }

    // 执行批量操作
    async performBulkOperation(seriesId, operation, scope, fromTime, reminderId, updateData = {}) {
        console.log(updateData)
        try {
            const response = await fetch('/api/reminders/bulk-edit/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },

                body: JSON.stringify({
                    reminder_id: reminderId,
                    operation: operation,
                    edit_scope: scope,
                    from_time: fromTime,
                    series_id: seriesId,
                    // 传递更新数据
                    title: updateData.title,
                    content: updateData.content,  // 修正：使用 content 而不是 description
                    description: updateData.description,
                    priority: updateData.priority,  // 添加缺失的 priority 字段
                    importance: updateData.importance,
                    urgency: updateData.urgency,
                    trigger_time: updateData.trigger_time,
                    rrule: updateData.rrule,
                    reminder_mode: updateData.reminder_mode
                })
            });
            
            if (response.ok) {
                const result = await response.json();
                await this.loadReminders();
                // 重新应用当前筛选器设置
                this.applyFilters();
                
                // 确保日历视图刷新
                if (window.eventManager && window.eventManager.calendar) {
                    console.log('performBulkOperation成功后刷新日历');
                    window.eventManager.calendar.refetchEvents();
                }
                
                console.log(`批量${operation}完成`);
                return true;
            } else {
                const errorData = await response.json();
                console.error('批量操作失败:', errorData);
                
                // 检查是否是重复提醒转单次提醒的错误
                if (errorData.message && errorData.message.includes('RRule是必填项') && 
                    updateData && !updateData.rrule && operation === 'edit') {
                    
                    // 显示转换确认对话框
                    const userConfirmed = confirm(
                        '检测到您要将重复提醒转换为单次提醒。\n\n' +
                        '这将执行以下操作：\n' +
                        '• 将当前提醒转换为单次提醒\n' +
                        '• 删除该系列中所有未来的提醒\n' +
                        '• 为过去的提醒设置截止时间\n\n' +
                        '确定要继续吗？'
                    );
                    
                    if (userConfirmed) {
                        // 发送特殊的转换请求
                        return await this.convertRecurringToSingle(seriesId, reminderId, updateData);
                    }
                } else {
                    alert(errorData.message || '操作失败');
                }
            }
        } catch (error) {
            console.error(`Error performing bulk ${operation}:`, error);
            
            // 检查是否是重复提醒转单次提醒的错误
            if (error.message && error.message.includes('RRule是必填项') && 
                updateData && !updateData.rrule && operation === 'edit') {
                
                // 显示转换确认对话框
                const userConfirmed = confirm(
                    '检测到您要将重复提醒转换为单次提醒。\n\n' +
                    '这将执行以下操作：\n' +
                    '• 将当前提醒转换为单次提醒\n' +
                    '• 删除该系列中所有未来的提醒\n' +
                    '• 为过去的提醒设置截止时间\n\n' +
                    '确定要继续吗？'
                );
                
                if (userConfirmed) {
                    // 发送特殊的转换请求
                    return await this.convertRecurringToSingle(seriesId, reminderId, updateData);
                }
            } else {
                alert('网络错误，请重试');
            }
        }
        return false;
    }

    // 将重复提醒转换为单次提醒
    async convertRecurringToSingle(seriesId, reminderId, updateData) {
        try {
            const response = await fetch('/api/reminders/convert-to-single/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({
                    series_id: seriesId,
                    reminder_id: reminderId,
                    update_data: updateData
                })
            });
            
            if (response.ok) {
                const result = await response.json();
                await this.loadReminders();
                this.applyFilters();
                console.log('重复提醒转换为单次提醒成功');
                return true;
            } else {
                const errorData = await response.json();
                console.error('转换失败:', errorData);
                alert(errorData.message || '转换失败');
            }
        } catch (error) {
            console.error('Error converting recurring to single:', error);
            alert('网络错误，请重试');
        }
        return false;
    }

    // 新的延后功能
    async snoozeReminder(reminderId, snoozeType) {
        // 找到要延后的提醒
        const reminder = this.reminders.find(r => r.id === reminderId);
        if (!reminder) {
            this.showMessage('未找到提醒', 'error');
            return false;
        }
        
        let snoozeUntil;
        const originalTriggerTime = new Date(reminder.trigger_time);
        const now = new Date();
        
        // 如果原始触发时间还未到，基于原始时间延后；否则基于当前时间延后
        const baseTime = originalTriggerTime > now ? originalTriggerTime : now;
        
        switch (snoozeType) {
            case '15m':
                snoozeUntil = new Date(baseTime.getTime() + 15 * 60 * 1000);
                break;
            case '1h':
                snoozeUntil = new Date(baseTime.getTime() + 60 * 60 * 1000);
                break;
            case '1d':
                snoozeUntil = new Date(baseTime.getTime() + 24 * 60 * 60 * 1000);
                break;
            default:
                // 自定义延后时间
                return this.customSnooze(reminderId);
        }
        
        // 关闭延后菜单
        this.closeSnoozeMenus({ target: document.body });
        
        try {
            const response = await fetch('/api/reminders/update-status/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({
                    id: reminderId,
                    status: `snoozed_${snoozeType}`,
                    snooze_until: snoozeUntil.toISOString()
                })
            });
            
            if (response.ok) {
                const result = await response.json();
                
                // 更新本地数据
                const reminder = this.reminders.find(r => r.id === reminderId);
                if (reminder) {
                    reminder.status = `snoozed_${snoozeType}`;
                    reminder.snooze_until = snoozeUntil.toISOString();
                    reminder.trigger_time = snoozeUntil.toISOString();
                    reminder.is_snoozed = true;
                }
                
                // 重新加载提醒数据并应用筛选器（会同时刷新左下角列表和日历）
                await this.loadReminders();
                this.applyFilters();
                
                // 显示成功消息
                const snoozeText = this.formatTriggerTime(snoozeUntil.toISOString());
                this.showMessage(`提醒已延后到 ${snoozeText}`, 'success');
                
                return true;
            } else {
                const error = await response.json();
                this.showMessage(`延后失败: ${error.error || '未知错误'}`, 'error');
                return false;
            }
        } catch (error) {
            console.error('延后提醒时出错:', error);
            this.showMessage('延后提醒时出错', 'error');
            return false;
        }
    }

    // 自定义延后时间
    customSnooze(reminderId) {
        const timeInput = prompt('请输入延后时间（格式：YYYY-MM-DD HH:MM）：');
        if (timeInput) {
            try {
                const snoozeUntil = new Date(timeInput);
                if (snoozeUntil > new Date()) {
                    return this.updateReminderStatus(reminderId, 'snoozed_custom', snoozeUntil.toISOString());
                } else {
                    alert('延后时间必须在未来');
                }
            } catch (error) {
                alert('时间格式错误');
            }
        }
    }

    // 单独删除提醒
    async deleteSingleReminder(reminderId) {
        try {
            const response = await fetch('/api/reminders/delete/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({ id: reminderId })
            });
            
            if (response.ok) {
                await this.loadReminders();
                // 重新应用当前筛选器设置
                this.applyFilters();
                return true;
            }
        } catch (error) {
            console.error('Error deleting reminder:', error);
        }
        return false;
    }

    // 取消批量编辑
    cancelBulkEdit() {
        // 清除待处理的批量编辑信息
        this.pendingBulkEdit = null;
        
        // 关闭模态框
        const modal = document.getElementById('bulkEditModal');
        if (modal) {
            const bsModal = bootstrap.Modal.getInstance(modal);
            if (bsModal) {
                bsModal.hide();
            } else {
                // 如果没有Bootstrap实例，直接移除模态框
                modal.style.display = 'none';
                modal.classList.remove('show');
                // 移除背景遮罩
                const backdrop = document.querySelector('.modal-backdrop');
                if (backdrop) {
                    backdrop.remove();
                }
                // 恢复body的滚动
                document.body.classList.remove('modal-open');
                document.body.style.paddingRight = '';
            }
        }
    }

    // 通用的状态更新方法
    async updateReminderStatus(reminderId, status, snoozeUntil = '') {
        try {
            const response = await fetch('/api/reminders/update-status/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({
                    id: reminderId,
                    status: status,
                    snooze_until: snoozeUntil
                })
            });
            
            if (response.ok) {
                await this.loadReminders();
                // 重新应用当前筛选器设置
                this.applyFilters();
                
                // 确保日历视图刷新
                if (window.eventManager && window.eventManager.calendar) {
                    console.log('updateReminderStatus成功后刷新日历');
                    window.eventManager.calendar.refetchEvents();
                }
                
                return true;
            }
        } catch (error) {
            console.error('Error updating reminder status:', error);
        }
        return false;
    }

    // 请求通知权限
    requestNotificationPermission() {
        if ('Notification' in window && Notification.permission === 'default') {
            Notification.requestPermission();
        }
    }
}

// 重复提醒UI处理函数
function toggleRepeatOptions(mode) {
    console.log('=== toggleRepeatOptions called with mode:', mode);
    
    let repeatCheckbox, repeatOptions, scopeSelection;
    
    if (mode === 'editEvent') {
        // Events编辑模式
        repeatCheckbox = document.getElementById('eventRepeat');
        repeatOptions = document.getElementById('editEventRecurringOptions');
        scopeSelection = document.getElementById('editEventRecurringInfo');
    } else {
        // Reminder模式
        repeatCheckbox = document.getElementById(mode === 'new' ? 'newReminderRepeat' : 'reminderRepeat');
        repeatOptions = document.getElementById(mode === 'new' ? 'newRepeatOptions' : 'editRepeatOptions');
        scopeSelection = mode === 'edit' ? document.getElementById('editScopeSelection') : null;
    }
    
    console.log('toggleRepeatOptions - repeatCheckbox:', {
        id: repeatCheckbox?.id,
        checked: repeatCheckbox?.checked,
        disabled: repeatCheckbox?.disabled
    });
    
    // 如果重复按钮被禁用，则不允许操作
    if (repeatCheckbox && repeatCheckbox.disabled) {
        console.log('repeatCheckbox is disabled, returning');
        return;
    }
    
    if (repeatCheckbox && repeatCheckbox.checked) {
        console.log('repeatCheckbox is checked, showing options');
        repeatOptions.style.display = 'block';
        if (mode === 'edit' && scopeSelection) {
            // 检查当前提醒是否是重复提醒的一部分
            const currentReminder = reminderManager.reminders.find(r => r.id == modalManager.currentReminderId);
            if (currentReminder && currentReminder.rrule) {
                scopeSelection.style.display = 'block';
                // 监听范围选择变化
                document.querySelectorAll('input[name="editScope"]').forEach(radio => {
                    radio.addEventListener('change', function() {
                        updateEditScopeFields(this.value);
                    });
                });
            } else {
                scopeSelection.style.display = 'none';
                updateEditScopeFields('all'); // 新建重复，允许所有编辑
            }
        } else if (mode === 'editEvent' && scopeSelection) {
            // Events编辑模式的范围选择逻辑
            // 检查当前事件是否已经是重复事件的一部分
            const currentEvent = window.modalManager && window.modalManager.currentEvent;
            if (currentEvent && currentEvent.extendedProps) {
                const eventData = currentEvent.extendedProps;
                const hasRRule = eventData.rrule && eventData.rrule.includes('FREQ=');
                const hasSeriesId = eventData.series_id && eventData.series_id.trim() !== '';
                
                // 只有当事件已经是重复事件时才显示范围选择器
                if ((hasRRule || hasSeriesId) && !eventData.is_detached) {
                    scopeSelection.style.display = 'block';
                    // 监听范围选择变化
                    document.querySelectorAll('input[name="editEventScope"]').forEach(radio => {
                        radio.addEventListener('change', function() {
                            updateEventEditScopeFields(this.value);
                        });
                    });
                } else {
                    // 新建重复事件或已分离的事件，不显示范围选择器
                    scopeSelection.style.display = 'none';
                }
            } else {
                // 无法获取事件数据，不显示范围选择器
                scopeSelection.style.display = 'none';
            }
        }
        updateRepeatPreview(mode);
    } else {
        repeatOptions.style.display = 'none';
        if (scopeSelection) {
            scopeSelection.style.display = 'none';
        }
        updateRepeatPreview(mode);
    }
}

function updateRepeatOptions(mode) {
    const freq = document.getElementById(mode === 'new' ? 'newRepeatFreq' : 'reminderRepeatFreq').value;
    const weekdaysOptions = document.getElementById(mode === 'new' ? 'newWeekdaysOptions' : 'reminderWeekdaysOptions');
    const monthlyOptions = document.getElementById(mode === 'new' ? 'newMonthlyOptions' : 'reminderMonthlyOptions');
    const intervalUnit = document.getElementById(mode === 'new' ? 'newIntervalUnit' : 'reminderIntervalUnit');
    
    // 更新间隔单位文本
    const unitTexts = {
        'DAILY': '天',
        'WEEKLY': '周',
        'MONTHLY': '月',
        'YEARLY': '年'
    };
    intervalUnit.textContent = unitTexts[freq] || '天';
    
    // 显示/隐藏相关选项
    if (freq === 'WEEKLY') {
        weekdaysOptions.style.display = 'block';
        monthlyOptions.style.display = 'none';
        // 隐藏月重复详细选项
        const monthlyDateOptions = document.getElementById(mode === 'new' ? 'newMonthlyDateOptions' : 'editMonthlyDateOptions');
        const monthlyWeekOptions = document.getElementById(mode === 'new' ? 'newMonthlyWeekOptions' : 'editMonthlyWeekOptions');
        const monthlyWeekdayOptions = document.getElementById(mode === 'new' ? 'newMonthlyWeekdayOptions' : 'editMonthlyWeekdayOptions');
        if (monthlyDateOptions) monthlyDateOptions.style.display = 'none';
        if (monthlyWeekOptions) monthlyWeekOptions.style.display = 'none';
        if (monthlyWeekdayOptions) monthlyWeekdayOptions.style.display = 'none';
    } else if (freq === 'MONTHLY') {
        weekdaysOptions.style.display = 'none';
        monthlyOptions.style.display = 'block';
        // 根据月重复类型显示对应选项
        updateMonthlyOptions(mode);
    } else {
        weekdaysOptions.style.display = 'none';
        monthlyOptions.style.display = 'none';
        // 隐藏月重复详细选项
        const monthlyDateOptions = document.getElementById(mode === 'new' ? 'newMonthlyDateOptions' : 'editMonthlyDateOptions');
        const monthlyWeekOptions = document.getElementById(mode === 'new' ? 'newMonthlyWeekOptions' : 'editMonthlyWeekOptions');
        const monthlyWeekdayOptions = document.getElementById(mode === 'new' ? 'newMonthlyWeekdayOptions' : 'editMonthlyWeekdayOptions');
        if (monthlyDateOptions) monthlyDateOptions.style.display = 'none';
        if (monthlyWeekOptions) monthlyWeekOptions.style.display = 'none';
        if (monthlyWeekdayOptions) monthlyWeekdayOptions.style.display = 'none';
    }
    
    updateRepeatPreview(mode);
}

function updateMonthlyOptions(mode) {
    // 获取正确的ID前缀
    const prefix = mode === 'new' ? 'new' : (mode === 'edit' ? 'edit' : 'reminder');
    
    // 获取月重复类型
    const monthlyTypeId = mode === 'new' ? 'newMonthlyType' : 'reminderRepeatBy';
    const monthlyType = document.getElementById(monthlyTypeId).value;
    
    // 获取各种选项元素
    const monthlyDateOptions = document.getElementById(prefix + 'MonthlyDateOptions');
    const monthlyWeekOptions = document.getElementById(prefix + 'MonthlyWeekOptions');
    const monthlyWeekdayOptions = document.getElementById(prefix + 'MonthlyWeekdayOptions');
    
    // 首先隐藏所有选项
    if (monthlyDateOptions) monthlyDateOptions.style.display = 'none';
    if (monthlyWeekOptions) monthlyWeekOptions.style.display = 'none';
    if (monthlyWeekdayOptions) monthlyWeekdayOptions.style.display = 'none';
    
    // 根据类型显示对应选项
    if (monthlyType === 'bymonthday') {
        // 按日期重复 - 显示日期选择器
        if (monthlyDateOptions) monthlyDateOptions.style.display = 'block';
    } else if (monthlyType === 'byweekday') {
        // 按星期重复 - 显示星期选择器
        if (monthlyWeekOptions) monthlyWeekOptions.style.display = 'block';
        if (monthlyWeekdayOptions) monthlyWeekdayOptions.style.display = 'block';
    }
    
    updateRepeatPreview(mode);
}

// 将updateMonthlyOptions添加到全局作用域
window.updateMonthlyOptions = updateMonthlyOptions;

function updateEditScopeFields(scope) {
    console.log('updateEditScopeFields called with scope:', scope);
    
    // 根据编辑范围启用/禁用字段
    const fields = [
        'editRepeatFreq', 'editRepeatInterval', 'editMonthlyType', 'editRepeatUntil',
        'editMO', 'editTU', 'editWE', 'editTH', 'editFR', 'editSA', 'editSU'
    ];
    
    // 只有在"仅此提醒"模式下才禁用重复字段，其他模式都应该允许编辑重复选项
    const enableRepeatFields = scope !== 'this_only';
    console.log('enableRepeatFields will be:', enableRepeatFields, 'for scope:', scope);
    
    fields.forEach(fieldId => {
        const field = document.getElementById(fieldId);
        if (field) {
            field.disabled = !enableRepeatFields;
            if (field.type === 'checkbox') {
                const label = document.querySelector(`label[for="${fieldId}"]`);
                if (label) {
                    label.style.opacity = enableRepeatFields ? '1' : '0.5';
                }
            }
        }
    });
    
    // 如果只编辑单次，隐藏重复选项
    const repeatOptions = document.getElementById('editRepeatOptions');
    if (scope === 'single') {
        repeatOptions.style.display = 'none';
        document.getElementById('reminderRepeat').checked = false;
    }
}

function updateRepeatPreview(mode) {
    // Events模式的简化处理
    if (mode === 'editEvent') {
        const eventRepeatCheckbox = document.getElementById('eventRepeat');
        // Events编辑模式目前主要是显示/隐藏重复选项，不需要复杂的预览
        if (eventRepeatCheckbox && eventRepeatCheckbox.checked) {
            console.log('Event repeat checkbox is checked, repeat options should be visible');
        }
        return;
    }
    
    // Reminder模式的原有逻辑
    const prefix = mode === 'new' ? 'new' : 'reminder';
    const previewElement = document.getElementById(mode === 'new' ? 'newRepeatPreview' : 'reminderRepeatPreview');
    
    // 对于新建模式，检查重复开关
    if (mode === 'new') {
        const repeatCheckbox = document.getElementById('newReminderRepeat');
        if (!repeatCheckbox || !repeatCheckbox.checked) {
            if (previewElement) previewElement.textContent = '预览：不重复';
            return;
        }
    }
    
    const freqElement = document.getElementById(`${prefix}RepeatFreq`);
    if (!freqElement) {
        if (previewElement) previewElement.textContent = '预览：不重复';
        return;
    }
    
    const freq = freqElement.value;
    const intervalElement = document.getElementById(`${prefix}RepeatInterval`);
    const untilElement = document.getElementById(`${prefix}RepeatUntil`);
    const interval = intervalElement ? intervalElement.value : '1';
    const until = untilElement ? untilElement.value : '';
    
    let preview = '预览：';
    
    if (interval == 1) {
        const freqTexts = {
            'DAILY': '每天',
            'WEEKLY': '每周',
            'MONTHLY': '每月',
            'YEARLY': '每年'
        };
        preview += freqTexts[freq];
    } else {
        const unitTexts = {
            'DAILY': '天',
            'WEEKLY': '周',  
            'MONTHLY': '月',
            'YEARLY': '年'
        };
        preview += `每${interval}${unitTexts[freq]}`;
    }
    
    // 添加星期几的信息
    if (freq === 'WEEKLY') {
        const weekdays = [];
        const weekdayLabels = ['一', '二', '三', '四', '五', '六', '日'];
        const weekdayIds = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'];
        
        weekdayIds.forEach((day, index) => {
            const checkbox = document.getElementById(`${prefix}${day}`);
            if (checkbox && checkbox.checked) {
                weekdays.push(weekdayLabels[index]);
            }
        });
        
        if (weekdays.length > 0) {
            preview += `（${weekdays.join('、')}）`;
        }
    }
    
    // 添加月重复方式信息
    if (freq === 'MONTHLY') {
        const monthlyTypeElement = document.getElementById(`${prefix}MonthlyType`);
        if (monthlyTypeElement) {
            const monthlyType = monthlyTypeElement.value;
            if (monthlyType === 'simple') {
                // 简单的每隔x个月，不添加额外信息
            } else if (monthlyType === 'byweekday') {
                preview += '（按星期重复）';
            } else if (monthlyType === 'bymonthday') {
                preview += '（按日期重复）';
            }
        }
    }
    
    // 添加结束时间信息
    if (until) {
        const endDate = new Date(until);
        preview += `，直到${endDate.getFullYear()}年${endDate.getMonth() + 1}月${endDate.getDate()}日`;
    }
    
    if (previewElement) {
        previewElement.textContent = preview;
    }
}

function buildRruleFromUI(mode) {
    const prefix = mode === 'new' ? 'new' : 'reminder';
    
    // 检查重复开关
    const repeatCheckbox = document.getElementById(mode === 'new' ? 'newReminderRepeat' : 'reminderRepeat');
    if (!repeatCheckbox || !repeatCheckbox.checked) {
        return '';
    }
    
    const freqElement = document.getElementById(`${prefix}RepeatFreq`);
    const intervalElement = document.getElementById(`${prefix}RepeatInterval`);
    const untilElement = document.getElementById(`${prefix}RepeatUntil`);
    
    if (!freqElement) {
        return '';
    }
    
    const freq = freqElement.value;
    const interval = intervalElement ? intervalElement.value : '1';
    const until = untilElement ? untilElement.value : '';
    
    let rrule = `FREQ=${freq}`;
    
    if (interval && interval != 1) {
        rrule += `;INTERVAL=${interval}`;
    }
    
    // 添加星期几规则
    if (freq === 'WEEKLY') {
        const weekdays = [];
        const weekdayIds = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'];
        
        weekdayIds.forEach(day => {
            const checkbox = document.getElementById(`${prefix}${day}`);
            if (checkbox && checkbox.checked) {
                weekdays.push(day);
            }
        });
        
        if (weekdays.length > 0) {
            rrule += `;BYDAY=${weekdays.join(',')}`;
        }
    }
    
    // 添加月重复规则
    if (freq === 'MONTHLY') {
        const monthlyTypeId = mode === 'new' ? 'newMonthlyType' : 'reminderRepeatBy';
        const monthlyTypeElement = document.getElementById(monthlyTypeId);
        const monthlyType = monthlyTypeElement ? monthlyTypeElement.value : 'simple';
        
        if (monthlyType === 'bymonthday') {
            // 按日期重复
            const monthlyDateId = mode === 'new' ? 'newMonthlyDate' : 'editMonthlyDate';
            const monthlyDate = document.getElementById(monthlyDateId);
            if (monthlyDate && monthlyDate.value) {
                const day = monthlyDate.value;
                if (day === '-1') {
                    // 月末
                    rrule += `;BYMONTHDAY=-1`;
                } else {
                    rrule += `;BYMONTHDAY=${day}`;
                }
            }
        } else if (monthlyType === 'byweekday') {
            // 按星期重复
            const monthlyWeekId = mode === 'new' ? 'newMonthlyWeek' : 'editMonthlyWeek';
            const monthlyWeekdayId = mode === 'new' ? 'newMonthlyWeekday' : 'editMonthlyWeekday';
            const monthlyWeek = document.getElementById(monthlyWeekId);
            const monthlyWeekday = document.getElementById(monthlyWeekdayId);
            
            if (monthlyWeek && monthlyWeekday && monthlyWeek.value && monthlyWeekday.value) {
                const week = monthlyWeek.value;
                const weekday = monthlyWeekday.value;
                rrule += `;BYDAY=${week}${weekday}`;
            }
        }
        // simple类型不需要额外的规则，只用FREQ=MONTHLY和INTERVAL
    }
    
    // 添加结束时间
    if (until) {
        const endDate = new Date(until);
        // 不添加Z后缀，保持与trigger_time格式一致（本地时间）
        const untilStr = endDate.toISOString().replace(/[-:]/g, '').split('.')[0];
        rrule += `;UNTIL=${untilStr}`;
    }
    
    return rrule;
}

function parseRruleToUI(rrule, mode) {
    console.log('=== parseRruleToUI called ===');
    console.log('rrule:', rrule, 'mode:', mode);
    
    const prefix = mode === 'new' ? 'new' : 'reminder';
    
    if (!rrule) {
        // 关闭重复选项
        const repeatCheckbox = document.getElementById(`${prefix}${mode === 'new' ? 'ReminderRepeat' : 'Repeat'}`);
        console.log('No rrule, disabling repeat checkbox:', repeatCheckbox?.id);
        if (repeatCheckbox) {
            repeatCheckbox.checked = false;
            toggleRepeatOptions(mode);
        }
        return;
    }
    
    // 启用重复选项
    const repeatCheckbox = document.getElementById(`${prefix}${mode === 'new' ? 'ReminderRepeat' : 'Repeat'}`);
    console.log('Found rrule, enabling repeat checkbox:', repeatCheckbox?.id);
    if (repeatCheckbox) {
        console.log('Setting repeatCheckbox.checked = true');
        repeatCheckbox.checked = true;
        toggleRepeatOptions(mode);
        console.log('After setting, repeatCheckbox.checked:', repeatCheckbox.checked);
    }
    
    // 解析RRULE
    const rules = rrule.split(';');
    const ruleObj = {};
    
    rules.forEach(rule => {
        const [key, value] = rule.split('=');
        ruleObj[key] = value;
    });
    
    console.log('Parsed ruleObj:', ruleObj);
    
    // 设置频率
    if (ruleObj.FREQ) {
        const freqElementId = `${prefix}RepeatFreq`;
        const freqElement = document.getElementById(freqElementId);
        console.log(`Setting frequency: ${freqElementId} = ${ruleObj.FREQ}`, freqElement);
        if (freqElement) {
            freqElement.value = ruleObj.FREQ;
            updateRepeatOptions(mode);
            console.log('Frequency set and updateRepeatOptions called');
        } else {
            console.error('Frequency element not found:', freqElementId);
        }
    }
    
    // 设置间隔
    if (ruleObj.INTERVAL) {
        const intervalElementId = `${prefix}RepeatInterval`;
        const intervalElement = document.getElementById(intervalElementId);
        console.log(`Setting interval: ${intervalElementId} = ${ruleObj.INTERVAL}`, intervalElement);
        if (intervalElement) {
            intervalElement.value = ruleObj.INTERVAL;
        } else {
            console.error('Interval element not found:', intervalElementId);
        }
    }
    
    // 设置星期几和月重复方式
    if (ruleObj.BYDAY) {
        const weekdays = ruleObj.BYDAY.split(',');
        
        // 检查是否是月重复的星期模式（如2MO表示第2个星期一）
        if (ruleObj.FREQ === 'MONTHLY' && weekdays.some(day => /^\d/.test(day) || /^-\d/.test(day))) {
            // 设置为按星期重复
            const monthlyTypeSelectId = mode === 'new' ? 'newMonthlyType' : 'reminderRepeatBy';
            const monthlyTypeSelect = document.getElementById(monthlyTypeSelectId);
            if (monthlyTypeSelect) {
                monthlyTypeSelect.value = 'byweekday';
                updateMonthlyOptions(mode);
                
                // 解析第几周和星期几
                const dayRule = weekdays[0]; // 取第一个规则
                const match = dayRule.match(/^(-?\d+)([A-Z]{2})$/);
                if (match) {
                    const week = match[1];
                    const weekday = match[2];
                    
                    const weekSelectId = mode === 'new' ? 'newMonthlyWeek' : 'editMonthlyWeek';
                    const weekdaySelectId = mode === 'new' ? 'newMonthlyWeekday' : 'editMonthlyWeekday';
                    const weekSelect = document.getElementById(weekSelectId);
                    const weekdaySelect = document.getElementById(weekdaySelectId);
                    
                    if (weekSelect) weekSelect.value = week;
                    if (weekdaySelect) weekdaySelect.value = weekday;
                }
            }
        } else if (ruleObj.FREQ === 'WEEKLY') {
            // 周重复，设置星期几选择框
            weekdays.forEach(day => {
                const checkbox = document.getElementById(`${prefix}${day}`);
                if (checkbox) {
                    checkbox.checked = true;
                }
            });
        }
    } else if (ruleObj.FREQ === 'MONTHLY') {
        // 月重复但没有BYDAY，检查是否有BYMONTHDAY
        const monthlyTypeSelectId = mode === 'new' ? 'newMonthlyType' : 'reminderRepeatBy';
        const monthlyTypeSelect = document.getElementById(monthlyTypeSelectId);
        if (monthlyTypeSelect) {
            if (ruleObj.BYMONTHDAY) {
                // 按日期重复
                monthlyTypeSelect.value = 'bymonthday';
                updateMonthlyOptions(mode);
                
                // 设置月日期
                const monthlyDateSelectId = mode === 'new' ? 'newMonthlyDate' : 'editMonthlyDate';
                const monthlyDateSelect = document.getElementById(monthlyDateSelectId);
                if (monthlyDateSelect) {
                    monthlyDateSelect.value = ruleObj.BYMONTHDAY;
                }
            } else {
                // 简单的每隔x个月重复
                monthlyTypeSelect.value = 'simple';
                updateMonthlyOptions(mode);
            }
        }
    }
    
    // 设置结束时间
    if (ruleObj.UNTIL) {
        try {
            let untilDate;
            // 处理不同格式的UNTIL时间
            if (ruleObj.UNTIL.includes('T')) {
                // 格式如：20251023T000000Z、20251023T000000 或 2025-10-23T00:00:00Z
                let dateStr = ruleObj.UNTIL;
                if (dateStr.length === 15 || dateStr.length === 16) {
                    // 格式：20251023T000000 或 20251023T000000Z -> 2025-10-23T00:00:00
                    const hasZ = dateStr.endsWith('Z');
                    if (hasZ) {
                        dateStr = dateStr.slice(0, -1); // 移除Z后缀
                    }
                    if (dateStr.length === 15) {
                        dateStr = dateStr.slice(0, 4) + '-' + dateStr.slice(4, 6) + '-' + dateStr.slice(6, 8) + 
                                 'T' + dateStr.slice(9, 11) + ':' + dateStr.slice(11, 13) + ':' + dateStr.slice(13, 15);
                    }
                }
                untilDate = new Date(dateStr);
            } else {
                // 简单日期格式
                untilDate = new Date(ruleObj.UNTIL);
            }
            
            if (!isNaN(untilDate.getTime())) {
                const dateStr = untilDate.toISOString().split('T')[0];
                const untilField = document.getElementById(`${prefix}RepeatUntil`);
                if (untilField) {
                    untilField.value = dateStr;
                }
            }
        } catch (e) {
            console.warn('Failed to parse UNTIL date:', ruleObj.UNTIL, e);
        }
    }
    
    updateRepeatPreview(mode);
}

// 将函数添加到window对象以便HTML可以访问
window.updateMonthlyOptions = updateMonthlyOptions;
window.toggleRepeatOptions = toggleRepeatOptions;
window.updateRepeatOptions = updateRepeatOptions;
window.parseRruleToUI = parseRruleToUI;

// 提醒管理器类已定义，实例将在HTML中创建
