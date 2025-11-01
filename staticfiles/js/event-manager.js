// 事件管理模块
class EventManager {
    constructor() {
        this.calendar = null;
        this.events = [];
        this.groups = [];
    }

    // 初始化事件管理器
    init() {
        this.initCalendar();
    }

    // 加载事件数据
    async loadEvents() {
        if (this.calendar) {
            this.calendar.refetchEvents();
        }
    }

    // 初始化日历
    initCalendar() {
        const calendarEl = document.getElementById('calendar');
        
        this.calendar = new FullCalendar.Calendar(calendarEl, {
            height: '100%', // 使用100%高度填满容器
            locale: 'zh-cn',
            allDayText: '全天',
            initialView: 'timeGridWeek',
            editable: true,
            nowIndicator: true,
            slotMinTime: '00:00', // 显示从0点开始
            slotMaxTime: '24:00', // 显示到24点
            scrollTime: '08:00', // 初始滚动到8点
            expandRows: true, // 展开行来填充高度
            allDaySlot: true, // 启用全天槽
            businessHours: {
                daysOfWeek: [1, 2, 3, 4, 5, 6, 0],
                startTime: '10:00',
                endTime: '23:00',
            },
            
            // 事件拖拽
            eventDrop: (info) => {
                // 检查是否是提醒事件
                if (info.event.extendedProps.isReminder) {
                    alert('提醒不支持拖拽操作，请在提醒管理界面中编辑');
                    info.revert();
                    return;
                }
                this.handleEventDragDrop(info, 'drop');
            },
            
            // 事件调整大小
            eventResize: (info) => {
                // 检查是否是提醒事件
                if (info.event.extendedProps.isReminder) {
                    alert('提醒不支持调整大小操作，请在提醒管理界面中编辑');
                    info.revert();
                    return;
                }
                this.handleEventDragDrop(info, 'resize');
            },
            
            // 视图变化
            datesSet: (viewInfo) => {
                this.saveCurrentView(viewInfo.view.type, viewInfo.start, viewInfo.end);
                // 视图变化后重新应用滚动设置
                setTimeout(() => {
                    this.forceScrollable();
                    this.setInitialScrollTime();
                }, 200);
            },
            
            // 事件点击
            eventClick: (info) => {
                console.log('FullCalendar eventClick触发:', info);
                try {
                    // 检查是否是提醒事件
                    if (info.event.extendedProps.isReminder) {
                        this.handleReminderClick(info.event);
                    } else {
                        this.handleEventEdit(info.event);
                    }
                } catch (error) {
                    console.error('打开编辑事件模态框时出错:', error);
                }
            },
            
            // 时间选择
            selectable: true,
            selectMirror: true,
            select: (info) => {
                console.log('FullCalendar select触发:', info);
                try {
                    modalManager.openCreateEventModal(info.startStr, info.endStr);
                } catch (error) {
                    console.error('打开创建事件模态框时出错:', error);
                }
            },
            
            // 移除aspectRatio，让日历填满整个容器
            headerToolbar: {
                right: 'timeGridTwoDay,dayGridMonth,timeGridWeek,listWeek'
            },
            
            // 自定义视图：两天日视图
            views: {
                timeGridTwoDay: {
                    type: 'timeGrid',
                    duration: { days: 2 },      // 显示2天
                    dateIncrement: { days: 1 }, // 每次前进/后退1天
                    buttonText: '2日'
                }
            },
            
            // 获取事件数据
            events: (info, successCallback, failureCallback) => {
                this.fetchEvents(info.start, info.end)
                    .then(events => {
                        successCallback(events);
                    })
                    .catch(error => failureCallback(error));
            },
            
            // 自定义事件内容渲染（用于修改提醒的时间显示）
            eventContent: (arg) => {
                // 如果是提醒事件，自定义显示格式
                if (arg.event.extendedProps.isReminder) {
                    const startTime = arg.event.start;
                    const timeStr = startTime.toLocaleTimeString('zh-CN', { 
                        hour: '2-digit', 
                        minute: '2-digit',
                        hour12: false 
                    });
                    
                    return {
                        html: `
                            <div class="fc-event-main-frame">
                                <div class="fc-event-title-container">
                                    <div class="fc-event-title fc-sticky">${timeStr} ${arg.event.title}</div>
                                </div>
                            </div>
                        `
                    };
                }
                // 普通事件使用默认渲染
                return true;
            }
        });
        
        this.calendar.render();
        
        // 强制设置滚动属性并设置初始滚动位置
        setTimeout(() => {
            this.forceScrollable();
            this.setInitialScrollTime();
            this.setupScrollObserver();
            console.log('FullCalendar渲染完成');
            console.log('日历容器高度:', document.getElementById('calendar').offsetHeight);
        }, 500);
    }

    // 设置初始滚动位置
    setInitialScrollTime() {
        // 首先尝试在主滚动容器上设置滚动
        const scrollContainer = document.querySelector('.fc-scroller-harness .fc-scroller');
        if (scrollContainer) {
            // 滚动到8点位置 (8 * 30px = 240px)
            scrollContainer.scrollTop = 240;
            console.log('在主滚动容器设置初始滚动位置到8点');
            return;
        }
        
        // 如果没有找到主滚动容器，尝试在时间网格上设置
        const timegrid = document.querySelector('.fc-timegrid');
        if (timegrid) {
            // 滚动到8点位置 (8 * 30px = 240px)
            timegrid.scrollTop = 240;
            console.log('在时间网格设置初始滚动位置到8点');
        }
    }

    // 设置DOM变化监控
    setupScrollObserver() {
        const calendarEl = document.getElementById('calendar');
        if (!calendarEl) return;

        let timeoutId = null;
        const observer = new MutationObserver((mutations) => {
            let shouldReapply = false;
            mutations.forEach((mutation) => {
                // 只在重要的DOM变化时重新应用
                if (mutation.type === 'childList' && mutation.addedNodes.length > 0) {
                    // 检查是否添加了FullCalendar相关的重要节点
                    for (let node of mutation.addedNodes) {
                        if (node.nodeType === Node.ELEMENT_NODE && 
                            (node.classList?.contains('fc-view') || 
                             node.classList?.contains('fc-scroller') ||
                             node.querySelector?.('.fc-view, .fc-scroller'))) {
                            shouldReapply = true;
                            break;
                        }
                    }
                }
            });
            
            if (shouldReapply) {
                // 清除之前的延时，避免频繁调用
                if (timeoutId) clearTimeout(timeoutId);
                timeoutId = setTimeout(() => {
                    this.forceScrollable();
                    timeoutId = null;
                }, 100); // 延长延时，减少频繁调用
            }
        });

        observer.observe(calendarEl, {
            childList: true,
            subtree: true
        });

        console.log('设置了DOM变化监控');
    }

    // 强制设置FullCalendar的滚动属性
    forceScrollable() {
        // 获取当前视图类型
        const currentView = this.calendar ? this.calendar.view.type : null;
        console.log('当前视图类型:', currentView);
        
        // 找到真正的时间网格滚动容器（包含时间槽的那个）
        const timegridScrollers = document.querySelectorAll('.fc-timegrid-body .fc-scroller, .fc-scroller:has(.fc-timegrid-slots)');
        timegridScrollers.forEach((scroller) => {
            // 让时间网格滚动容器自适应剩余高度
            scroller.style.overflowY = 'auto';
            scroller.style.overflowX = 'hidden';
            scroller.style.maxHeight = 'none'; // 移除固定高度
            scroller.style.height = '100%'; // 填满父容器
            scroller.style.flex = '1'; // 占据剩余空间
            console.log('设置时间网格滚动容器（真正的）:', scroller);
        });
        
        // 更通用的方法：检查滚动器内容来判断类型
        const allScrollers = document.querySelectorAll('.fc-scroller');
        allScrollers.forEach((scroller) => {
            const hasTimegridSlots = scroller.querySelector('.fc-timegrid-slots');
            const hasDaygridBody = scroller.querySelector('.fc-daygrid-body');
            
            if (hasTimegridSlots) {
                // 这是时间网格滚动器（周视图/日视图）
                scroller.style.overflowY = 'auto';
                scroller.style.overflowX = 'hidden';
                scroller.style.maxHeight = 'none';
                scroller.style.height = '100%';
                scroller.style.flex = '1';
                console.log('识别并设置时间网格滚动器:', scroller);
            } else if (hasDaygridBody) {
                // 检查是否是月视图
                if (currentView === 'dayGridMonth') {
                    // 月视图：让daygrid-body正常显示，可以滚动
                    scroller.style.overflowY = 'auto';
                    scroller.style.overflowX = 'hidden';
                    scroller.style.maxHeight = 'none';
                    scroller.style.height = '100%';
                    scroller.style.flex = '1';
                    console.log('识别并设置月视图滚动器（允许完整显示）:', scroller);
                } else {
                    // 其他视图中的全天槽：限制高度为50px
                    scroller.style.setProperty('overflow', 'hidden', 'important');
                    scroller.style.setProperty('max-height', '50px', 'important');
                    scroller.style.setProperty('height', '50px', 'important');
                    scroller.style.setProperty('flex', '0 0 50px', 'important');
                    console.log('识别并设置全天槽滚动器（限制高度）:', scroller);
                }
            }
        });
        
        // 确保视图容器使用flex布局
        const viewHarness = document.querySelector('.fc-view-harness');
        if (viewHarness) {
            viewHarness.style.height = '100%';
            viewHarness.style.display = 'flex';
            viewHarness.style.flexDirection = 'column';
        }
        
        // 确保时间网格容器也使用flex
        const timegrid = document.querySelector('.fc-timegrid');
        if (timegrid) {
            timegrid.style.display = 'flex';
            timegrid.style.flexDirection = 'column';
            timegrid.style.flex = '1';
            timegrid.style.minHeight = '0'; // 允许收缩
        }
        
        // 重新启用选择功能（解决操作后选择失效的问题）
        this.ensureSelectableEnabled();
        
        console.log('已设置日历滚动功能，使用自适应高度');
    }
    
    // 确保选择功能启用
    ensureSelectableEnabled() {
        if (this.calendar) {
            try {
                // 强制重新设置选择相关选项
                this.calendar.setOption('selectable', true);
                this.calendar.setOption('selectMirror', true);
                
                // 强制重新设置select回调
                this.calendar.setOption('select', (info) => {
                    console.log('新的select回调被触发:', info);
                    modalManager.openCreateEventModal(info.startStr, info.endStr);
                });
                
                // 强制重新设置eventClick回调
                this.calendar.setOption('eventClick', (info) => {
                    console.log('新的eventClick回调被触发:', info);
                    try {
                        // 检查是否是提醒事件
                        if (info.event.extendedProps.isReminder) {
                            this.handleReminderClick(info.event);
                        } else {
                            this.handleEventEdit(info.event);
                        }
                    } catch (error) {
                        console.error('处理事件编辑时出错:', error);
                    }
                });
                
                console.log('已重新启用所有FullCalendar交互功能');
                console.log('当前selectable:', this.calendar.getOption('selectable'));
                console.log('当前selectMirror:', this.calendar.getOption('selectMirror'));
            } catch (error) {
                console.error('重新启用选择功能时出错:', error);
            }
        }
    }

    // 获取事件数据
    async fetchEvents(start, end) {
        try {
            // 获取日程数据
            const response = await fetch('/get_calendar/events/');
            const data = await response.json();
            
            this.events = data.events;
            this.groups = data.events_groups;
            window.events_groups = this.groups; // 保持兼容性
            
            // 获取提醒数据
            const reminderResponse = await fetch('/api/reminders/');
            const reminderData = await reminderResponse.json();
            const reminders = reminderData.reminders || [];
            
            // 获取左下角提醒框的所有筛选器设置
            const statusFilter = document.getElementById('reminderStatusFilter')?.value || 'active';
            const priorityFilter = document.getElementById('reminderPriorityFilter')?.value || 'all';
            const typeFilter = document.getElementById('reminderTypeFilter')?.value || 'all';
            
            console.log('日历fetchEvents - 筛选器设置:', {
                status: statusFilter,
                priority: priorityFilter,
                type: typeFilter
            });
            
            // 根据筛选器过滤提醒（与左下角提醒框保持一致，不包括时间筛选）
            const filteredReminders = reminders.filter(reminder => {
                // 状态筛选
                if (statusFilter && statusFilter !== 'all') {
                    if (statusFilter === 'snoozed') {
                        // 检查是否是延后状态
                        if (!reminder.status.startsWith('snoozed_')) return false;
                    } else {
                        if (reminder.status !== statusFilter) return false;
                    }
                }
                
                // 优先级筛选
                if (priorityFilter && priorityFilter !== 'all') {
                    if (reminder.priority !== priorityFilter) return false;
                }
                
                // 类型筛选（单次/重复）
                if (typeFilter && typeFilter !== 'all') {
                    const hasRRule = reminder.rrule && reminder.rrule.includes('FREQ=');
                    if (typeFilter === 'recurring' && !hasRRule) return false;
                    if (typeFilter === 'single' && hasRRule) return false;
                    if (typeFilter === 'detached' && !reminder.is_detached) return false;
                }
                
                return true;
            });
            
            // 将提醒转换为日历事件格式
            const reminderEvents = filteredReminders
                .map(reminder => {
                    // 使用 trigger_time 或 snooze_until（如果被延后）
                    const triggerTime = new Date(reminder.snooze_until || reminder.trigger_time);
                    const endTime = new Date(triggerTime.getTime() + 30 * 60 * 1000); // 30分钟后
                    const now = new Date();
                    
                    // 判断是否超时（只有active状态才判断超时）
                    const isOverdue = reminder.status === 'active' && triggerTime < now;
                    
                    // 获取状态颜色（背景色）
                    const statusColor = this.getReminderStatusColor(reminder.status, isOverdue);
                    
                    // 获取优先级颜色（边框色）
                    const priorityColor = this.getReminderPriorityBorderColor(reminder.priority);
                    
                    return {
                        id: `reminder_${reminder.id}`, // 添加前缀以区分
                        title: `🔔 ${reminder.title}`,
                        start: triggerTime.toISOString(),
                        end: endTime.toISOString(),
                        backgroundColor: statusColor,
                        borderColor: priorityColor,
                        display: 'block',
                        extendedProps: {
                            isReminder: true,
                            reminderId: reminder.id,
                            reminderData: reminder,
                            description: reminder.description || '',
                            priority: reminder.priority,
                            status: reminder.status,
                            isOverdue: isOverdue
                        },
                        classNames: ['reminder-event'] // 添加特殊class用于样式
                    };
                });
            
            // 合并日程和提醒事件
            const allEvents = [
                ...this.events.map(event => ({
                    ...event,
                    backgroundColor: this.getEventColor(event.groupID),
                    borderColor: this.getEventColor(event.groupID)
                })),
                ...reminderEvents
            ];
            
            return allEvents;
        } catch (error) {
            console.error('Error fetching events:', error);
            return [];
        }
    }
    
    // 获取提醒颜色（根据优先级）- 旧版本，保留以兼容
    getReminderColor(priority) {
        const colorMap = {
            'urgent': 'rgba(220, 53, 69, 0.6)',    // 红色半透明
            'high': 'rgba(255, 193, 7, 0.6)',      // 黄色半透明
            'normal': 'rgba(0, 123, 255, 0.6)',    // 蓝色半透明
            'low': 'rgba(108, 117, 125, 0.6)',     // 灰色半透明
            'debug': 'rgba(111, 66, 193, 0.6)'     // 紫色半透明
        };
        return colorMap[priority] || 'rgba(0, 123, 255, 0.6)';
    }
    
    // 获取提醒优先级边框颜色（不透明，与左下角提醒框一致）
    getReminderPriorityBorderColor(priority) {
        const colorMap = {
            'urgent': '#dc3545',   // 红色 - 紧急
            'high': '#fd7e14',     // 橙色 - 高
            'normal': '#007bff',   // 蓝色 - 普通
            'low': '#6c757d',      // 灰色 - 低
            'debug': '#6f42c1'     // 紫色 - 调试
        };
        return colorMap[priority] || '#007bff';
    }
    
    // 获取提醒状态背景颜色
    getReminderStatusColor(status, isOverdue) {
        // 如果是active状态且超时，返回红色
        if (status === 'active' && isOverdue) {
            return 'rgba(220, 53, 69, 0.6)';  // 红色半透明 - 超时
        }
        
        // 根据状态返回颜色
        const colorMap = {
            'active': 'rgba(0, 123, 255, 0.6)',        // 蓝色半透明 - 正在进行中
            'completed': 'rgba(40, 167, 69, 0.6)',     // 绿色半透明 - 已完成
            'dismissed': 'rgba(108, 117, 125, 0.5)',   // 灰色半透明 - 已忽略
            'snoozed_15m': 'rgba(255, 193, 7, 0.6)',   // 黄色半透明 - 延后
            'snoozed_1h': 'rgba(255, 193, 7, 0.6)',    // 黄色半透明 - 延后
            'snoozed_1d': 'rgba(255, 193, 7, 0.6)',    // 黄色半透明 - 延后
            'snoozed_custom': 'rgba(255, 193, 7, 0.6)' // 黄色半透明 - 延后
        };
        
        // 所有延后状态都返回黄色
        if (status && status.startsWith('snoozed_')) {
            return 'rgba(255, 193, 7, 0.6)';
        }
        
        return colorMap[status] || 'rgba(0, 123, 255, 0.6)';
    }

    // 获取事件颜色
    getEventColor(groupID) {
        const group = this.groups.find(g => g.id === groupID);
        return group ? group.color : '#007bff';
    }

    /**
     * 处理事件拖拽和调整大小
     */
    async handleEventDragDrop(info, actionType) {
        const event = info.event;
        const isRecurring = event.extendedProps.is_recurring;
        const seriesId = event.extendedProps.series_id;
        
        console.log('拖拽/调整事件:', {
            id: event.id,
            title: event.title,
            isRecurring: isRecurring,
            seriesId: seriesId,
            actionType: actionType
        });
        
        // 如果是重复事件，显示确认对话框
        if (isRecurring && seriesId) {
            const actionText = actionType === 'drop' ? '移动' : '调整大小';
            const formatDate = (date) => {
                return date.toLocaleString('zh-CN', {
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit'
                });
            };
            
            const confirmed = confirm(
                `您正在${actionText}一个重复日程中的单个实例。\n\n` +
                `日程标题：${event.title}\n` +
                `原始时间：${formatDate(info.oldEvent.start)}\n` +
                `新时间：${formatDate(event.start)}\n\n` +
                `此操作将把这个实例从重复序列中独立出去，成为一个单独的例外日程。\n\n` +
                `是否确认此操作？`
            );
            
            if (!confirmed) {
                // 用户取消，恢复事件
                info.revert();
                return;
            }
        }
        
        // 执行更新
        const success = await this.updateEventDrag(
            event.id,
            event.start.toISOString(),
            event.end ? event.end.toISOString() : null,
            event.title,
            event.extendedProps.description,
            event.extendedProps.importance,
            event.extendedProps.urgency,
            event.extendedProps.groupID,
            event.extendedProps.ddl,
            isRecurring && seriesId ? 'single' : undefined
        );
        
        if (!success) {
            // 更新失败，恢复事件
            info.revert();
        }
    }

    /**
     * 更新事件（拖拽专用，包含 rrule_change_scope 参数）
     */
    async updateEventDrag(eventId, newStart, newEnd, title, description, importance, urgency, groupID, ddl, rruleChangeScope = 'single') {
        try {
            // 构建事件数据
            const eventData = {
                eventId: eventId,
                title: title,
                newStart: newStart,
                newEnd: newEnd,
                description: description,
                importance: importance,
                urgency: urgency,
                groupID: groupID,
                ddl: ddl,
                rrule_change_scope: rruleChangeScope
            };

            console.log('通过拖拽更新事件:', eventData);

            const response = await fetch('/get_calendar/update_events/', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify(eventData)
            });
            
            const result = await response.json();
            
            if (response.ok && result.status === 'success') {
                console.log('事件更新成功');
                this.refreshCalendar();
                return true;
            } else {
                console.error('更新事件失败:', result.message || result.error);
                alert(`更新失败: ${result.message || result.error || '未知错误'}`);
                return false;
            }
        } catch (error) {
            console.error('更新事件时出错:', error);
            alert(`更新失败: ${error.message || '网络错误'}`);
            return false;
        }
    }

    // 更新事件
    async updateEvent(eventId, newStart, newEnd, title, description, importance, urgency, groupID, ddl, rrule = '') {
        try {
            // 构建事件数据 - 使用后端期望的字段名
            const eventData = {
                eventId: eventId,           // 后端期望 eventId
                title: title,
                newStart: newStart,         // 后端期望 newStart
                newEnd: newEnd,             // 后端期望 newEnd
                description: description,
                importance: importance,
                urgency: urgency,
                groupID: groupID,           // 后端期望 groupID
                ddl: ddl,
                rrule: rrule
            };

            console.log('Updating event with data:', eventData);

            // 使用新的Events RRule API
            const response = await fetch('/get_calendar/update_events/', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify(eventData)
            });
            
            const result = await response.json();
            
            if (response.ok && result.status === 'success') {
                console.log('Event updated successfully');
                this.refreshCalendar();
                return true;
            } else {
                console.error('Error updating event:', result.message || result.error);
                alert(`更新失败: ${result.message || result.error || '未知错误'}`);
                return false;
            }
        } catch (error) {
            console.error('Error updating event:', error);
            alert(`更新失败: ${error.message || '网络错误'}`);
            return false;
        }
    }

    // 创建事件
    async createEvent(eventData) {
        try {
            // 使用新的Events RRule API
            const response = await fetch('/events/create_event/', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify(eventData)
            });
            
            const result = await response.json();
            
            if (response.ok && result.status === 'success') {
                console.log('Event created successfully');
                this.refreshCalendar();
                return true;
            } else {
                console.error('Error creating event:', result.message || result.error);
                alert(`创建失败: ${result.message || result.error || '未知错误'}`);
                return false;
            }
        } catch (error) {
            console.error('Error creating event:', error);
            alert(`创建失败: ${error.message || '网络错误'}`);
            return false;
        }
    }

    // 删除事件
    async deleteEvent(eventId, scope = 'single', seriesId = null) {
        try {
            // 使用bulk-edit API删除事件
            const response = await fetch('/api/events/bulk-edit/', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({ 
                    operation: 'delete',
                    event_id: eventId,
                    edit_scope: scope,
                    series_id: seriesId || eventId  // 如果没有提供seriesId，使用eventId
                })
            });
            
            const result = await response.json();
            
            if (response.ok && result.status === 'success') {
                console.log('Event deleted successfully');
                this.refreshCalendar();
                return true;
            } else {
                console.error('Error deleting event:', result.message || result.error);
                alert(`删除失败: ${result.message || result.error || '未知错误'}`);
                return false;
            }
        } catch (error) {
            console.error('Error deleting event:', error);
            alert(`删除失败: ${error.message || '网络错误'}`);
            return false;
        }
    }

    // 删除重复事件
    async deleteRecurringEvent(eventId, scope) {
        try {
            const response = await fetch('/events/delete_events/', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({ 
                    event_id: eventId,
                    scope: scope
                })
            });
            
            const result = await response.json();
            
            if (response.ok && result.status === 'success') {
                console.log('Recurring event deleted successfully');
                this.refreshCalendar();
                return true;
            } else {
                console.error('Error deleting recurring event:', result.message || result.error);
                alert(`删除重复事件失败: ${result.message || result.error || '未知错误'}`);
                return false;
            }
        } catch (error) {
            console.error('Error deleting recurring event:', error);
            alert(`删除重复事件失败: ${error.message || '网络错误'}`);
            return false;
        }
    }

    // 保存当前视图
    saveCurrentView(viewType, start, end) {
        // 使用新的设置管理器保存视图状态
        if (window.settingsManager) {
            // 修复时区问题：将UTC时间转换为本地时间再提取日期
            const localStart = new Date(start.getTime() - start.getTimezoneOffset() * 60000);
            let currentDate;
            
            if (viewType === 'dayGridMonth') {
                // 月视图特殊处理：如果获取到的日期不是该月1日，则获取显示范围内的实际月份
                const localEnd = new Date(end.getTime() - end.getTimezoneOffset() * 60000);
                
                // 计算start和end之间的中点日期，这样可以确保获取到当前显示月份
                const midPoint = new Date((localStart.getTime() + localEnd.getTime()) / 2);
                
                // 安全地设置为该月的第一天，避免时区问题
                const year = midPoint.getFullYear();
                const month = midPoint.getMonth();
                
                // 使用本地时间创建该月第一天的日期字符串
                const targetDate = `${year}-${String(month + 1).padStart(2, '0')}-01`;
                currentDate = targetDate;
                
                console.log('月视图特殊处理:', { 
                    originalStart: localStart, 
                    originalEnd: localEnd, 
                    midPoint, 
                    year,
                    month: month + 1,
                    currentDate 
                });
            } else {
                // 其他视图正常处理
                currentDate = localStart.toISOString().split('T')[0];
                console.log('其他视图处理:', { viewType, originalStart: localStart, currentDate });
            }
            
            window.settingsManager.onCalendarViewChange(viewType, currentDate);
        }
        
        // 保留原有的API调用作为备份（可选）
        // fetch('/get_calendar/change_view/', {
        //     method: 'POST',
        //     headers: { 'Content-Type': 'application/json' },
        //     body: JSON.stringify({
        //         viewType: viewType,
        //         start: start.toISOString(),
        //         end: end.toISOString()
        //     })
        // }).catch(error => console.error('Error saving view:', error));
    }

    // 刷新日历
    refreshCalendar() {
        this.calendar.refetchEvents();
    }

    // 检查是否是重复事件，显示编辑范围选择器
    async handleEventEdit(eventInfo) {
        console.log('handleEventEdit called with:', eventInfo);
        
        const eventData = eventInfo.extendedProps || {};
        console.log('Event extended props:', eventData);
        console.log('Event rrule from extendedProps:', eventData.rrule);
        
        // 多种方式判断是否为重复事件
        const hasRRule = eventData.rrule && eventData.rrule.trim() !== '';
        const isRecurring = eventData.is_recurring;
        const hasSeriesId = eventData.series_id && eventData.series_id.trim() !== '';
        
        console.log('Recurring check:', { hasRRule, isRecurring, hasSeriesId, rruleValue: eventData.rrule });
        
        // 如果有RRule或明确标记为重复事件，就当做重复事件处理
        if (hasRRule || (isRecurring && hasSeriesId)) {
            // 重复事件，显示编辑范围选择器
            const seriesId = hasSeriesId ? eventData.series_id : eventInfo.id; // 如果没有series_id，使用event id
            console.log('Treating as recurring event, series_id:', seriesId);
            console.log('About to show edit scope dialog...');
            this.showEventEditScopeDialog(eventInfo.id, seriesId, 'edit');
        } else {
            // 单次事件，直接打开编辑模态框
            console.log('Treating as single event');
            modalManager.openEditEventModal(eventInfo);
        }
    }
    
    // 处理提醒点击事件 - 显示提醒详情和操作按钮
    handleReminderClick(eventInfo) {
        const reminderData = eventInfo.extendedProps.reminderData;
        const reminderId = eventInfo.extendedProps.reminderId;
        
        console.log('Reminder clicked:', reminderData);
        
        // 打开提醒详情模态框
        const modal = document.getElementById('reminderDetailModal');
        const contentDiv = document.getElementById('reminderDetailContent');
        
        if (!modal || !contentDiv) {
            console.error('提醒详情模态框未找到');
            return;
        }
        
        // 生成提醒详情HTML（复用 reminder-manager.js 的样式）
        const triggerTime = new Date(reminderData.snooze_until || reminderData.trigger_time);
        const formattedTime = this.formatReminderTime(triggerTime);
        const priorityIcon = this.getPriorityIcon(reminderData.priority);
        const status = reminderData.status || 'active';
        
        // 构建状态按钮
        const completedClass = status === 'completed' ? 'btn-success active' : 'btn-outline-success';
        const dismissedClass = status === 'dismissed' ? 'btn-secondary active' : 'btn-outline-secondary';
        
        // 构建延后按钮
        const isSnoozing = status && status.startsWith('snoozed_');
        let snoozeButtons = '';
        if (isSnoozing) {
            const snoozeType = status.replace('snoozed_', '');
            let snoozeText = this.getSnoozeText(snoozeType, reminderData.snooze_until);
            snoozeButtons = `
                <div class="d-inline-flex gap-2">
                    <button class="btn btn-sm btn-warning active" disabled>${snoozeText}</button>
                    <button class="btn btn-sm btn-outline-warning" onclick="eventManager.cancelReminderSnooze('${reminderId}')">取消延后</button>
                </div>
            `;
        } else {
            snoozeButtons = `
                <div class="dropdown d-inline-block">
                    <button class="btn btn-sm btn-info dropdown-toggle" type="button" id="snoozeDropdown" data-bs-toggle="dropdown">
                        延后
                    </button>
                    <ul class="dropdown-menu">
                        <li><a class="dropdown-item" href="#" onclick="eventManager.snoozeReminderFromCalendar('${reminderId}', '15m'); return false;">15分钟后</a></li>
                        <li><a class="dropdown-item" href="#" onclick="eventManager.snoozeReminderFromCalendar('${reminderId}', '1h'); return false;">1小时后</a></li>
                        <li><a class="dropdown-item" href="#" onclick="eventManager.snoozeReminderFromCalendar('${reminderId}', '1d'); return false;">一天后</a></li>
                        <li><a class="dropdown-item" href="#" onclick="eventManager.customSnoozeReminder('${reminderId}'); return false;">自定义</a></li>
                    </ul>
                </div>
            `;
        }
        
        contentDiv.innerHTML = `
            <div class="reminder-detail-card">
                <div class="d-flex justify-content-between align-items-start mb-3">
                    <h6 class="mb-0">${priorityIcon} ${reminderData.title}</h6>
                </div>
                
                <div class="mb-3">
                    <p class="text-muted mb-1"><i class="far fa-clock me-2"></i>提醒时间</p>
                    <p class="mb-0">${formattedTime}</p>
                </div>
                
                ${reminderData.description ? `
                <div class="mb-3">
                    <p class="text-muted mb-1"><i class="far fa-file-alt me-2"></i>内容</p>
                    <p class="mb-0">${reminderData.description}</p>
                </div>
                ` : ''}
                
                ${reminderData.rrule ? `
                <div class="mb-3">
                    <p class="text-muted mb-1"><i class="fas fa-repeat me-2"></i>重复规则</p>
                    <p class="mb-0"><code>${reminderData.rrule}</code></p>
                </div>
                ` : ''}
                
                <div class="d-flex flex-wrap gap-2 mb-3">
                    <button class="btn btn-sm ${completedClass}" onclick="eventManager.toggleReminderStatus('${reminderId}', 'completed')">
                        <i class="fas fa-check me-1"></i>完成
                    </button>
                    <button class="btn btn-sm ${dismissedClass}" onclick="eventManager.toggleReminderStatus('${reminderId}', 'dismissed')">
                        <i class="fas fa-times me-1"></i>忽略
                    </button>
                    ${snoozeButtons}
                </div>
                
                <div class="d-flex gap-2">
                    <button class="btn btn-sm btn-primary" onclick="eventManager.editReminderFromCalendar('${reminderId}')">
                        <i class="fas fa-edit me-1"></i>编辑
                    </button>
                    <button class="btn btn-sm btn-danger" onclick="eventManager.deleteReminderFromCalendar('${reminderId}')">
                        <i class="fas fa-trash me-1"></i>删除
                    </button>
                </div>
            </div>
        `;
        
        // 显示模态框（使用与其他模态框一致的显示方式）
        modal.style.display = 'block';
        modal.classList.add('show');
        
        // 禁用日历交互，防止在查看提醒时误触发其他操作
        if (window.eventManager && window.eventManager.calendar) {
            window.eventManager.calendar.setOption('selectable', false);
            window.eventManager.calendar.setOption('selectMirror', false);
        }
    }
    
    // 格式化提醒时间
    formatReminderTime(date) {
        return date.toLocaleString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            weekday: 'short'
        });
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
    
    // 获取延后文本
    getSnoozeText(snoozeType, snoozeUntil) {
        switch (snoozeType) {
            case '15m':
                return '15分钟后';
            case '1h':
                return '1小时后';
            case '1d':
                return '一天后';
            case 'custom':
                if (snoozeUntil) {
                    return this.formatReminderTime(new Date(snoozeUntil));
                }
                return '已延后';
            default:
                return '已延后';
        }
    }
    
    // 切换提醒状态（完成/忽略）
    async toggleReminderStatus(reminderId, targetStatus) {
        try {
            const response = await fetch('/api/reminders/update-status/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({
                    id: reminderId,
                    status: targetStatus
                })
            });
            
            if (response.ok) {
                // 关闭模态框
                modalManager.closeAllModals();
                // 重新加载日历
                this.calendar.refetchEvents();
                // 通知 reminder-manager 也刷新
                if (window.reminderManager) {
                    await window.reminderManager.loadReminders();
                    window.reminderManager.applyFilters();
                }
            } else {
                alert('更新提醒状态失败');
            }
        } catch (error) {
            console.error('Error updating reminder status:', error);
            alert('更新提醒状态时出错');
        }
    }
    
    // 延后提醒
    async snoozeReminderFromCalendar(reminderId, duration) {
        // 调用 reminderManager 的方法
        if (window.reminderManager) {
            await window.reminderManager.snoozeReminder(reminderId, duration);
            // 关闭模态框
            modalManager.closeAllModals();
            // 重新加载日历
            this.calendar.refetchEvents();
        } else {
            alert('提醒管理器未初始化');
        }
    }
    
    // 取消延后
    async cancelReminderSnooze(reminderId) {
        if (window.reminderManager) {
            await window.reminderManager.cancelSnooze(reminderId);
            modalManager.closeAllModals();
            this.calendar.refetchEvents();
        } else {
            alert('提醒管理器未初始化');
        }
    }
    
    // 自定义延后
    customSnoozeReminder(reminderId) {
        if (window.reminderManager) {
            window.reminderManager.customSnooze(reminderId);
        } else {
            alert('提醒管理器未初始化');
        }
    }
    
    // 编辑提醒
    editReminderFromCalendar(reminderId) {
        modalManager.closeAllModals();
        
        // 需要先获取提醒数据以判断是否为重复提醒
        fetch('/api/reminders/')
            .then(res => res.json())
            .then(data => {
                const reminder = data.reminders.find(r => r.id === reminderId);
                if (!reminder) {
                    alert('提醒不存在');
                    return;
                }
                
                // 判断是否为重复提醒
                if (reminder.rrule && reminder.series_id) {
                    // 重复提醒，显示范围选择对话框
                    if (window.reminderManager) {
                        window.reminderManager.showBulkEditDialog(reminderId, reminder.series_id, 'edit');
                    } else {
                        alert('提醒管理器未初始化');
                    }
                } else {
                    // 单次提醒，直接打开编辑对话框
                    if (window.modalManager) {
                        modalManager.openEditReminderModal(reminder);
                    }
                }
            })
            .catch(err => {
                console.error('Error loading reminder:', err);
                alert('加载提醒数据失败');
            });
    }
    
    // 删除提醒
    async deleteReminderFromCalendar(reminderId) {
        if (!confirm('确定要删除这个提醒吗？')) {
            return;
        }
        
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
                modalManager.closeAllModals();
                this.calendar.refetchEvents();
                if (window.reminderManager) {
                    await window.reminderManager.loadReminders();
                    window.reminderManager.applyFilters();
                }
            } else {
                alert('删除提醒失败');
            }
        } catch (error) {
            console.error('Error deleting reminder:', error);
            alert('删除提醒时出错');
        }
    }
    
    // 获取CSRF Token
    getCSRFToken() {
        return window.CSRF_TOKEN || '';
    }

    // 检查是否是重复事件，显示删除范围选择器
    async handleEventDelete(eventId, seriesId) {
        console.log('handleEventDelete called with:', { eventId, seriesId });
        
        // 获取事件信息
        const eventInfo = this.calendar.getEventById(eventId);
        const eventData = eventInfo ? eventInfo.extendedProps || {} : {};
        
        // 多种方式判断是否为重复事件
        const hasRRule = eventData.rrule && eventData.rrule.trim() !== '';
        const isRecurring = eventData.is_recurring;
        const hasSeriesId = (seriesId && seriesId.trim() !== '') || (eventData.series_id && eventData.series_id.trim() !== '');
        
        console.log('Delete recurring check:', { hasRRule, isRecurring, hasSeriesId });
        
        if (hasRRule || (isRecurring && hasSeriesId)) {
            // 重复事件，显示删除范围选择器
            const actualSeriesId = seriesId || eventData.series_id || eventId; // 优先使用传入的seriesId
            console.log('Treating as recurring event for deletion, series_id:', actualSeriesId);
            this.showEventEditScopeDialog(eventId, actualSeriesId, 'delete');
        } else {
            // 单次事件，直接删除
            console.log('Treating as single event for deletion');
            this.deleteEvent(eventId);
        }
    }

    // 显示编辑范围选择对话框
    showEventEditScopeDialog(eventId, seriesId, operation) {
        console.log('showEventEditScopeDialog called with:', { eventId, seriesId, operation });
        
        const operationText = operation === 'edit' ? '编辑' : '删除';
        
        // 获取未来的事件选项
        const futureOptions = this.getFutureEventOptions(seriesId);
        
        const dialogHTML = `
            <div class="modal fade" id="eventEditScopeModal" tabindex="-1">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">${operationText}重复事件</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <p>这是一个重复事件，请选择${operationText}范围：</p>
                            <div class="form-check">
                                <input class="form-check-input" type="radio" name="eventEditScope" id="eventScope_this_only" value="single">
                                <label class="form-check-label" for="eventScope_this_only">
                                    仅此事件 (分离后单独${operationText})
                                </label>
                            </div>
                            <div class="form-check">
                                <input class="form-check-input" type="radio" name="eventEditScope" id="eventScope_all" value="all">
                                <label class="form-check-label" for="eventScope_all">
                                    所有事件 (整个系列)
                                </label>
                            </div>
                            <div class="form-check">
                                <input class="form-check-input" type="radio" name="eventEditScope" id="eventScope_from_this" value="future" checked>
                                <label class="form-check-label" for="eventScope_from_this">
                                    此事件及之后
                                </label>
                            </div>
                            <div class="form-check">
                                <input class="form-check-input" type="radio" name="eventEditScope" id="eventScope_from_time" value="from_time">
                                <label class="form-check-label" for="eventScope_from_time">
                                    从指定时间开始：
                                </label>
                                <select class="form-select form-select-sm mt-2" id="eventTimeSelect">
                                    ${futureOptions.map(opt => `<option value="${opt.value}">${opt.label}</option>`).join('')}
                                </select>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" onclick="eventManager.cancelEventEditScope()">取消</button>
                            <button type="button" class="btn btn-primary" onclick="eventManager.executeEventEditScope('${eventId}', '${seriesId}', '${operation}')">确认${operationText}</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // 移除现有的对话框
        const existingModal = document.getElementById('eventEditScopeModal');
        if (existingModal) {
            console.log('Removing existing modal');
            existingModal.remove();
        }
        
        // 添加新的对话框
        console.log('Adding new modal to DOM');
        document.body.insertAdjacentHTML('beforeend', dialogHTML);
        
        // 显示对话框
        console.log('Attempting to show modal');
        try {
            // 尝试使用Bootstrap 5的方式
            if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
                console.log('Using Bootstrap 5 Modal');
                const modal = new bootstrap.Modal(document.getElementById('eventEditScopeModal'));
                modal.show();
            } 
            // 尝试使用jQuery/Bootstrap 4的方式
            else if (typeof $ !== 'undefined' && $.fn.modal) {
                console.log('Using jQuery/Bootstrap 4 Modal');
                $('#eventEditScopeModal').modal('show');
            }
            // 手动显示
            else {
                console.log('Manually showing modal');
                const modalEl = document.getElementById('eventEditScopeModal');
                modalEl.style.display = 'block';
                modalEl.classList.add('show');
                document.body.classList.add('modal-open');
                
                // 添加背景层
                const backdrop = document.createElement('div');
                backdrop.className = 'modal-backdrop fade show';
                backdrop.id = 'eventEditScopeModalBackdrop';
                document.body.appendChild(backdrop);
            }
        } catch (error) {
            console.error('Error showing modal:', error);
        }
    }

    // 获取未来事件选项
    getFutureEventOptions(seriesId) {
        // 从实际的事件数据中获取该系列的所有实例
        const options = [];
        
        if (!seriesId || !this.events) {
            console.warn('seriesId or events data not available');
            return options;
        }
        
        // 获取当前时间
        const now = new Date();
        
        // 查找该系列的所有事件实例
        const seriesEvents = this.events.filter(event => 
            event.series_id === seriesId && 
            event.start && 
            !event.is_detached // 排除已分离的事件
        );
        
        if (seriesEvents.length === 0) {
            console.warn(`No events found for series ${seriesId}`);
            return options;
        }
        
        // 按开始时间排序
        seriesEvents.sort((a, b) => {
            const dateA = new Date(a.start);
            const dateB = new Date(b.start);
            return dateA - dateB;
        });
        
        // 只返回当前时间之后的事件（包括当前）
        const futureEvents = seriesEvents.filter(event => {
            const eventDate = new Date(event.start);
            return eventDate >= now || Math.abs(eventDate - now) < 24 * 60 * 60 * 1000; // 包括24小时内的事件
        });
        
        // 如果没有未来事件，至少包括最后几个事件
        const eventsToShow = futureEvents.length > 0 ? futureEvents : seriesEvents.slice(-5);
        
        // 转换为选项格式
        eventsToShow.forEach(event => {
            const eventDate = new Date(event.start);
            options.push({
                value: event.start, // 使用原始ISO格式时间字符串
                label: `${eventDate.toLocaleDateString('zh-CN')} ${eventDate.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'})}`
            });
        });
        
        console.log(`Found ${options.length} event instances for series ${seriesId}`);
        return options;
    }

    // 取消编辑范围选择
    cancelEventEditScope() {
        console.log('Canceling event edit scope');
        
        // 先尝试使用Bootstrap Modal API
        const modal = bootstrap.Modal.getInstance(document.getElementById('eventEditScopeModal'));
        if (modal) {
            modal.hide();
        }
        
        // 如果Modal实例不存在，手动清理
        const modalElement = document.getElementById('eventEditScopeModal');
        const backdrop = document.querySelector('.modal-backdrop');
        
        if (modalElement) {
            modalElement.remove();
        }
        if (backdrop) {
            backdrop.remove();
        }
        
        // 确保清理body状态
        document.body.classList.remove('modal-open');
        document.body.style.overflow = '';
        document.body.style.paddingRight = '';
    }

    // 执行批量编辑
    async executeEventEditScope(eventId, seriesId, operation) {
        const scope = document.querySelector('input[name="eventEditScope"]:checked')?.value;
        if (!scope) {
            alert('请选择操作范围');
            return;
        }
        
        let fromTime = '';
        if (scope === 'from_time') {
            fromTime = document.getElementById('eventTimeSelect')?.value;
        } else if (scope === 'future') {
            // 获取当前事件的时间
            const eventInfo = this.calendar.getEventById(eventId);
            fromTime = eventInfo?.start?.toISOString();
        }
        
        console.log('executeEventEditScope called with:', { eventId, seriesId, operation, scope, fromTime });
        
        if (operation === 'edit') {
            // 关闭范围选择对话框，打开编辑对话框
            this.cancelEventEditScope();
            
            // 保存批量编辑信息到临时变量（确保使用一致的字段名）
            this.pendingBulkEdit = {
                event_id: eventId,  // 注意：使用下划线格式保持与后端一致
                series_id: seriesId,
                scope: scope,
                fromTime: fromTime
            };
            
            console.log('Set pendingBulkEdit:', this.pendingBulkEdit);
            
            // 打开编辑对话框
            const eventInfo = this.calendar.getEventById(eventId);
            modalManager.openEditEventModal(eventInfo);
        } else if (operation === 'delete') {
            if (confirm(`确定要删除选定范围的事件吗？`)) {
                await this.performBulkOperation(seriesId, operation, scope, fromTime, eventId);
                this.cancelEventEditScope();
            }
        }
    }

    // 更新编辑范围字段
    updateEventEditScopeFields() {
        const scope = this.pendingBulkEdit?.scope;
        
        // 如果没有pendingBulkEdit，说明这是普通的单个事件编辑，不应用任何限制
        if (!this.pendingBulkEdit) {
            console.log('No pending bulk edit, setting up normal event edit mode');
            this.setupNormalEventEditMode();
            return;
        }
        
        // 正确判断是否为重复事件 - 从当前事件数据中获取
        let isRecurring = false;
        if (window.currentEventData && window.currentEventData.extendedProps) {
            const eventData = window.currentEventData.extendedProps;
            isRecurring = (eventData.rrule && eventData.rrule.includes('FREQ=')) || eventData.is_recurring || false;
        }
        
        console.log('updateEventEditScopeFields called with scope:', scope, 'isRecurring:', isRecurring);
        console.log('pendingBulkEdit:', this.pendingBulkEdit);
        console.log('currentEventData:', window.currentEventData);
        
        // 强制隐藏editEventRecurringInfo（无论在什么模式下都不应该显示模板中的四选一框）
        this.forceHideEditEventRecurringInfo();
        
        // 获取相关的DOM元素
        const titleInput = document.getElementById('eventTitle');
        const descriptionInput = document.getElementById('eventDescription');
        const startInput = document.getElementById('eventStart');
        const endInput = document.getElementById('eventEnd');
        const ddlInput = document.getElementById('eventDdl');
        const recurringInfo = editEventRecurringInfo; // 重用上面的变量
        const recurringOptions = document.getElementById('editEventRecurringOptions');
        
        // 获取重复选择框（需要确保存在）
        let isRecurringCheckbox = document.getElementById('eventIsRecurring');
        if (!isRecurringCheckbox) {
            isRecurringCheckbox = document.getElementById('eventRepeat');
        }
        
        console.log('Before processing - isRecurringCheckbox:', isRecurringCheckbox);
        console.log('Before processing - isRecurringCheckbox.checked:', isRecurringCheckbox?.checked);
        console.log('Before processing - isRecurring:', isRecurring);
        console.log('Before processing - _rruleParsed:', this._rruleParsed);
        
        // 如果已经进行了RRule解析，应该保留重复选择框的当前状态
        if (this._rruleParsed && isRecurringCheckbox && isRecurringCheckbox.checked) {
            isRecurring = true;
            console.log('RRule was parsed, keeping isRecurring as true');
        }
        
        if (!isRecurringCheckbox) {
            // 如果不存在，创建一个重复事件复选框
            this.createRecurringCheckbox();
            isRecurringCheckbox = document.getElementById('eventIsRecurring');
        }
        
        // 获取重复选项容器（尝试多个可能的ID）
        let repeatOptionsContainer = document.getElementById('eventRecurringOptions');
        if (!repeatOptionsContainer) {
            repeatOptionsContainer = document.getElementById('editEventRecurringOptions');
        }
        
        // 根据不同的编辑范围设置UI状态
        if (scope === 'single') {
            // 仅此次模式：完全隐藏重复相关控件
            console.log('Setting UI for single event edit mode');
            
            // 确保四选一框隐藏
            if (recurringInfo) {
                recurringInfo.style.display = 'none';
            }
            
            // 隐藏所有重复相关容器
            if (recurringOptions) {
                recurringOptions.style.display = 'none';
            }
            
            if (repeatOptionsContainer) {
                repeatOptionsContainer.style.display = 'none';
            }
            
            // 隐藏重复选择框本身及其容器
            if (isRecurringCheckbox) {
                // 完全隐藏重复复选框
                const checkboxContainer = isRecurringCheckbox.closest('.form-check, .mb-3');
                if (checkboxContainer) {
                    checkboxContainer.style.display = 'none';
                } else {
                    isRecurringCheckbox.style.display = 'none';
                    const label = document.querySelector(`label[for="${isRecurringCheckbox.id}"]`);
                    if (label) {
                        label.style.display = 'none';
                    }
                }
            }
            
            // 隐藏任何可能存在的重复相关UI元素
            const repeatElements = [
                'editEventRecurringInfo',
                'eventRecurringInfo', 
                'eventRepeatOptions',
                'editEventRepeatOptions'
            ];
            
            repeatElements.forEach(elementId => {
                const element = document.getElementById(elementId);
                if (element) {
                    element.style.display = 'none';
                }
            });
            
            // 移除任何"更改重复规则"按钮
            this.removeChangeRuleButton();
            
            // 所有基本字段可编辑
            this.setBasicFieldsState(false);
            
            // 添加说明文本
            this.addEditModeHint('仅编辑此单个事件 - 将从重复系列中分离为独立事件');
            
        } else if (scope === 'all') {
            // 全部模式：显示重复设置但锁定，不显示"更改重复规则"按钮
            console.log('Setting UI for all events edit mode');
            
            // 确保四选一框隐藏
            if (recurringInfo) {
                recurringInfo.style.display = 'none';
            }
            
            // 确保重复相关元素可见
            this.restoreRecurringUIVisibility(isRecurringCheckbox, recurringOptions, repeatOptionsContainer);
            
            if (recurringOptions) {
                recurringOptions.style.display = 'block';
            }
            
            // 重复选择框锁定为选中（因为这是修改整个重复系列）
            if (isRecurringCheckbox) {
                isRecurringCheckbox.checked = true;
                isRecurringCheckbox.disabled = true;
                isRecurringCheckbox.style.opacity = '0.5';
                
                // 添加说明文本
                this.addEditModeHint('编辑整个重复系列 - 所有重复事件的基本信息将被修改');
            }
            
            // 显示重复选项但设为只读
            if (repeatOptionsContainer) {
                repeatOptionsContainer.style.display = 'block';
            }
            
            // 所有基本字段可编辑
            this.setBasicFieldsState(false);
            
            // 设置重复相关字段为只读，不显示"更改重复规则"按钮
            this.setRepeatFieldsReadonly(true);
            this.removeChangeRuleButton();
            
        } else if (scope === 'future' || scope === 'from_time') {
            // 此及之后/从指定时间开始模式：显示重复设置，提供"更改重复规则"按钮
            console.log('Setting UI for future/from_time edit mode');
            
            // 确保四选一框隐藏
            if (recurringInfo) {
                recurringInfo.style.display = 'none';
            }
            
            // 确保重复相关元素可见
            this.restoreRecurringUIVisibility(isRecurringCheckbox, recurringOptions, repeatOptionsContainer);
            
            if (recurringOptions) {
                recurringOptions.style.display = 'block';
                this.addChangeRuleButton();
            }
            
            // 重复选择框可编辑（用户可以选择继续重复或停止重复）
            if (isRecurringCheckbox) {
                isRecurringCheckbox.checked = isRecurring;
                isRecurringCheckbox.disabled = false;
                isRecurringCheckbox.style.opacity = '1';
                
                // 根据具体的编辑范围提供准确的说明文本
                const modeHint = scope === 'future' ? 
                    '编辑此事件及未来事件 - 可修改基本信息和重复规则' :
                    '编辑指定时间后的事件 - 可修改基本信息和重复规则';
                this.addEditModeHint(modeHint);
                
                // 移除之前的监听器，添加新的监听器
                isRecurringCheckbox.removeEventListener('change', this.handleFutureEditRecurringChange);
                isRecurringCheckbox.addEventListener('change', this.handleFutureEditRecurringChange.bind(this));
            }
            
            // 显示重复选项（对于重复事件编辑，应该始终显示）
            if (repeatOptionsContainer) {
                // 在批量编辑模式下，如果事件已经是重复事件，应该显示重复选项
                const shouldShow = (isRecurringCheckbox && isRecurringCheckbox.checked) || isRecurring;
                repeatOptionsContainer.style.display = shouldShow ? 'block' : 'none';
                console.log('Setting repeatOptionsContainer display:', shouldShow ? 'block' : 'none', 
                           'isRecurringCheckbox.checked:', isRecurringCheckbox?.checked, 'isRecurring:', isRecurring);
            }
            
            // 所有基本字段可编辑
            this.setBasicFieldsState(false);
            
            // 设置重复相关字段为只读（除非点击"更改重复规则"）
            this.setRepeatFieldsReadonly(true);
            // 同时设置重复复选框为只读，防止用户绕过修改重复规则按钮直接关闭重复
            this.setRecurringCheckboxReadonly(true);
        } else {
            // 默认情况 - 清除所有限制
            console.log('Setting UI for default edit mode');
            
            // 确保四选一框隐藏
            if (recurringInfo) {
                recurringInfo.style.display = 'none';
            }
            
            // 确保重复相关元素可见
            this.restoreRecurringUIVisibility(isRecurringCheckbox, recurringOptions, repeatOptionsContainer);
            
            // 确保重复复选框可编辑
            this.setRecurringCheckboxReadonly(false);
            
            this.setBasicFieldsState(false);
            this.setRepeatFieldsReadonly(false);
            this.removeEditModeHint();
        }
        
        // 清除RRule解析标记
        this._rruleParsed = false;
        console.log('updateEventEditScopeFields completed, cleared _rruleParsed flag');
    }

    // 设置普通事件编辑模式（非批量编辑）
    setupNormalEventEditMode() {
        console.log('Setting up normal event edit mode');
        
        // 获取重复选择框
        let isRecurringCheckbox = document.getElementById('eventIsRecurring');
        if (!isRecurringCheckbox) {
            isRecurringCheckbox = document.getElementById('eventRepeat');
        }
        
        const recurringOptions = document.getElementById('editEventRecurringOptions');
        const repeatOptionsContainer = document.getElementById('eventRecurringOptions');
        
        // 确保所有元素可见和可编辑
        this.restoreRecurringUIVisibility(isRecurringCheckbox, recurringOptions, repeatOptionsContainer);
        
        if (isRecurringCheckbox) {
            isRecurringCheckbox.disabled = false;
            isRecurringCheckbox.style.opacity = '1';
            
            // 根据当前事件状态设置复选框
            if (window.currentEventData && window.currentEventData.extendedProps) {
                const eventData = window.currentEventData.extendedProps;
                const isCurrentlyRecurring = (eventData.rrule && eventData.rrule.includes('FREQ=')) || eventData.is_recurring || false;
                isRecurringCheckbox.checked = isCurrentlyRecurring;
                
                console.log('Normal event edit mode - isCurrentlyRecurring:', isCurrentlyRecurring);
                
                // 立即根据状态设置重复选项容器的显示
                if (repeatOptionsContainer) {
                    repeatOptionsContainer.style.display = isCurrentlyRecurring ? 'block' : 'none';
                    console.log('Set repeatOptionsContainer display to:', isCurrentlyRecurring ? 'block' : 'none');
                }
                
                if (isCurrentlyRecurring) {
                    this.addEditModeHint('重复事件编辑 - 可修改基本信息，点击重复选项可选择编辑范围');
                } else {
                    this.addEditModeHint('普通事件编辑 - 可修改所有信息，开启重复可转为重复事件');
                }
            } else {
                // 如果没有事件数据，默认设置为非重复
                isRecurringCheckbox.checked = false;
                if (repeatOptionsContainer) {
                    repeatOptionsContainer.style.display = 'none';
                }
                this.addEditModeHint('普通事件编辑 - 可修改所有信息，开启重复可转为重复事件');
            }
        }
        
        // 所有基本字段可编辑
        this.setBasicFieldsState(false);
        this.setRepeatFieldsReadonly(false);
        // 确保重复复选框也可编辑
        this.setRecurringCheckboxReadonly(false);
    }

    // 恢复重复相关UI元素的可见性
    restoreRecurringUIVisibility(isRecurringCheckbox, recurringOptions, repeatOptionsContainer) {
        // 恢复重复复选框的显示
        if (isRecurringCheckbox) {
            const checkboxContainer = isRecurringCheckbox.closest('.form-check, .mb-3');
            if (checkboxContainer) {
                checkboxContainer.style.display = 'block';
            } else {
                isRecurringCheckbox.style.display = 'inline-block';
                const label = document.querySelector(`label[for="${isRecurringCheckbox.id}"]`);
                if (label) {
                    label.style.display = 'inline-block';
                }
            }
        }
        
        // 恢复其他重复相关元素的显示
        const repeatElements = [
            'eventRecurringInfo', 
            'eventRepeatOptions',
            'editEventRepeatOptions'
        ];
        
        repeatElements.forEach(elementId => {
            const element = document.getElementById(elementId);
            if (element) {
                element.style.display = 'block';
            }
        });
        
        // 确保editEventRecurringInfo始终隐藏（这是模板中的四选一框，应该由独立对话框处理）
        this.forceHideEditEventRecurringInfo();
    }

    // 强制隐藏editEventRecurringInfo元素的工具方法
    forceHideEditEventRecurringInfo() {
        const editEventRecurringInfo = document.getElementById('editEventRecurringInfo');
        if (editEventRecurringInfo) {
            editEventRecurringInfo.style.display = 'none';
            editEventRecurringInfo.style.visibility = 'hidden';
            // 添加一个特殊属性以防其他代码重新显示
            editEventRecurringInfo.setAttribute('data-force-hidden', 'true');
            console.log('Force hidden editEventRecurringInfo with all methods');
        }
    }

    // 处理未来编辑模式下的重复选项变化
    handleFutureEditRecurringChange(event) {
        const isChecked = event.target.checked;
        // 获取重复选项容器（尝试多个可能的ID）
        let repeatOptionsContainer = document.getElementById('eventRecurringOptions');
        if (!repeatOptionsContainer) {
            repeatOptionsContainer = document.getElementById('editEventRecurringOptions');
        }
        
        if (repeatOptionsContainer) {
            repeatOptionsContainer.style.display = isChecked ? 'block' : 'none';
        }
        
        // 如果取消重复，则隐藏"更改重复规则"按钮
        if (!isChecked) {
            this.removeChangeRuleButton();
        } else {
            this.addChangeRuleButton();
        }
    }

    // 设置基本字段的状态
    setBasicFieldsState(disabled) {
        const basicFields = [
            'eventTitle', 'eventDescription', 'eventStart', 
            'eventEnd', 'eventDdl'
        ];
        
        basicFields.forEach(fieldId => {
            const field = document.getElementById(fieldId);
            if (field) {
                field.disabled = disabled;
                field.style.opacity = disabled ? '0.6' : '1';
            }
        });
    }

    // 添加编辑模式提示
    addEditModeHint(message) {
        // 移除之前的提示
        this.removeEditModeHint();
        
        // 找到合适的位置插入提示
        const modal = document.getElementById('editEventModal');
        const modalBody = modal?.querySelector('.modal-body');
        
        if (modalBody) {
            const hintElement = document.createElement('div');
            hintElement.id = 'editModeHint';
            hintElement.className = 'alert alert-info alert-sm mb-3';
            hintElement.innerHTML = `<i class="fas fa-info-circle me-2"></i>${message}`;
            
            // 插入到modal-body的第一个位置
            modalBody.insertBefore(hintElement, modalBody.firstChild);
        }
    }

    // 移除编辑模式提示
    removeEditModeHint() {
        const hintElement = document.getElementById('editModeHint');
        if (hintElement) {
            hintElement.remove();
        }
    }

    // 设置重复复选框为只读状态
    setRecurringCheckboxReadonly(readonly) {
        // 查找重复选择框（多种可能的ID）
        let isRecurringCheckbox = document.getElementById('eventIsRecurring');
        if (!isRecurringCheckbox) {
            isRecurringCheckbox = document.getElementById('eventRepeat');
        }
        
        if (isRecurringCheckbox) {
            isRecurringCheckbox.disabled = readonly;
            isRecurringCheckbox.style.opacity = readonly ? '0.6' : '1';
            
            // 如果设为只读，添加视觉提示
            if (readonly) {
                isRecurringCheckbox.style.pointerEvents = 'none';
                // 找到对应的标签并添加只读样式
                const label = document.querySelector(`label[for="${isRecurringCheckbox.id}"]`);
                if (label) {
                    label.style.opacity = '0.6';
                    label.style.pointerEvents = 'none';
                }
            } else {
                isRecurringCheckbox.style.pointerEvents = 'auto';
                const label = document.querySelector(`label[for="${isRecurringCheckbox.id}"]`);
                if (label) {
                    label.style.opacity = '1';
                    label.style.pointerEvents = 'auto';
                }
            }
        }
    }

    // 设置重复字段为只读状态
    setRepeatFieldsReadonly(readonly) {
        console.log(`setRepeatFieldsReadonly called with readonly=${readonly}`);
        
        const repeatFields = [
            'eventFreq', 'eventInterval', 'eventEndType',
            'eventCount', 'eventUntil', 'eventMonthlyType',
            'eventMonthlyDate', 'eventMonthlyWeek', 'eventMonthlyWeekday',
            // 编辑模式下的字段
            'editEventFreq', 'editEventInterval', 'editEventEndType',
            'editEventCount', 'editEventUntil', 'editEventMonthlyType',
            'editEventMonthlyDate', 'editEventMonthlyWeek', 'editEventMonthlyWeekday'
        ];
        
        repeatFields.forEach(fieldId => {
            const field = document.getElementById(fieldId);
            if (field) {
                field.disabled = readonly;
                field.style.opacity = readonly ? '0.6' : '1';
            }
        });
        
        // 处理星期复选框 - Events使用不同的ID结构
        const weekdays = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'];
        weekdays.forEach(day => {
            // 尝试多种可能的ID格式
            const possibleIds = [`event${day}`, `editEvent${day}`, `eventWeekday${day}`];
            
            possibleIds.forEach(id => {
                const checkbox = document.getElementById(id);
                if (checkbox) {
                    checkbox.disabled = readonly;
                    const label = document.querySelector(`label[for="${id}"]`);
                    if (label) {
                        label.style.opacity = readonly ? '0.6' : '1';
                    }
                }
            });
        });
        
        // 处理星期按钮（如果存在） - 同时处理创建和编辑模式的容器
        const weekdayContainers = [
            document.getElementById('eventWeekdaysContainer'),      // 创建模式
            document.getElementById('editEventWeekdaysContainer')   // 编辑模式
        ];
        
        console.log(`Processing weekday containers, readonly=${readonly}`);
        
        weekdayContainers.forEach((weekdayContainer, containerIndex) => {
            const containerName = containerIndex === 0 ? 'eventWeekdaysContainer' : 'editEventWeekdaysContainer';
            console.log(`Checking ${containerName}: ${weekdayContainer ? 'found' : 'not found'}`);
            
            if (weekdayContainer) {
                const weekdayButtons = weekdayContainer.querySelectorAll('.weekday-btn');
                console.log(`Found ${weekdayButtons.length} weekday buttons in ${containerName}`);
                
                weekdayButtons.forEach((btn, btnIndex) => {
                    const beforeState = {
                        disabled: btn.disabled,
                        opacity: btn.style.opacity,
                        pointerEvents: btn.style.pointerEvents
                    };
                    
                    btn.disabled = readonly;
                    btn.style.opacity = readonly ? '0.6' : '1';
                    if (readonly) {
                        btn.style.pointerEvents = 'none';
                    } else {
                        btn.style.pointerEvents = 'auto';
                    }
                    
                    const afterState = {
                        disabled: btn.disabled,
                        opacity: btn.style.opacity,
                        pointerEvents: btn.style.pointerEvents
                    };
                    
                    console.log(`Button ${btnIndex} (${btn.dataset.day}): before=${JSON.stringify(beforeState)}, after=${JSON.stringify(afterState)}`);
                });
            }
        });
    }

    // 添加"更改重复规则"按钮
    addChangeRuleButton() {
        const recurringOptions = document.getElementById('eventRecurringOptions');
        if (!recurringOptions) {
            // 如果没有找到 eventRecurringOptions，尝试其他可能的ID
            const altContainer = document.getElementById('editEventRecurringOptions');
            if (altContainer) {
                this.addChangeRuleButtonToContainer(altContainer);
            }
            return;
        }
        
        this.addChangeRuleButtonToContainer(recurringOptions);
    }
    
    // 添加"更改重复规则"按钮到指定容器
    addChangeRuleButtonToContainer(container) {
        // 检查是否已存在按钮
        let changeRuleBtn = document.getElementById('changeEventRuleBtn');
        if (changeRuleBtn) return;
        
        // 创建按钮容器
        const buttonContainer = document.createElement('div');
        buttonContainer.className = 'text-center mt-3';
        buttonContainer.id = 'changeEventRuleBtnContainer';
        
        // 创建按钮
        changeRuleBtn = document.createElement('button');
        changeRuleBtn.id = 'changeEventRuleBtn';
        changeRuleBtn.type = 'button';
        changeRuleBtn.className = 'btn btn-outline-primary btn-sm';
        changeRuleBtn.innerHTML = '<i class="fas fa-edit me-2"></i>更改重复规则';
        
        // 添加点击事件
        changeRuleBtn.addEventListener('click', () => {
            console.log('Change rule button clicked');
            
            // 解除重复字段的只读状态
            console.log('Before calling setRepeatFieldsReadonly(false)');
            this.setRepeatFieldsReadonly(false);
            console.log('After calling setRepeatFieldsReadonly(false)');
            
            // 同时解除重复复选框的只读状态
            this.setRecurringCheckboxReadonly(false);
            changeRuleBtn.style.display = 'none';
            
            // 检查周一到周日按钮的状态
            const editWeekdayContainer = document.getElementById('editEventWeekdaysContainer');
            if (editWeekdayContainer) {
                const weekdayButtons = editWeekdayContainer.querySelectorAll('.weekday-btn');
                console.log(`Found ${weekdayButtons.length} weekday buttons in editEventWeekdaysContainer`);
                
                // 检查容器的显示状态
                const containerStyles = window.getComputedStyle(editWeekdayContainer);
                console.log(`Container styles: display=${containerStyles.display}, visibility=${containerStyles.visibility}, opacity=${containerStyles.opacity}`);
                
                weekdayButtons.forEach((btn, index) => {
                    const btnStyles = window.getComputedStyle(btn);
                    console.log(`Weekday button ${index}: disabled=${btn.disabled}, opacity=${btn.style.opacity}, pointerEvents=${btn.style.pointerEvents}, day=${btn.dataset.day}`);
                    console.log(`  - Computed styles: opacity=${btnStyles.opacity}, pointerEvents=${btnStyles.pointerEvents}, display=${btnStyles.display}`);
                    console.log(`  - Classes: ${btn.className}`);
                    
                    // 检查是否有点击事件监听器
                    const hasClickListener = btn.onclick !== null || btn.addEventListener !== undefined;
                    console.log(`  - Has click handler: ${hasClickListener}`);
                    
                    // 尝试手动添加测试点击事件
                    btn.addEventListener('click', function testClick(e) {
                        console.log(`TEST CLICK: Button ${btn.dataset.day} was clicked!`);
                        btn.removeEventListener('click', testClick);
                    });
                });
            } else {
                console.log('editEventWeekdaysContainer not found');
            }
            
            // 重新设置周一到周日按钮的事件监听器
            console.log('Reattaching weekday button listeners');
            if (window.rruleManager && window.rruleManager.setupWeekdayListeners) {
                window.rruleManager.setupWeekdayListeners();
            }
            
            // 更新提示信息
            this.addEditModeHint('重复规则编辑模式 - 可修改所有重复设置');
        });
        
        buttonContainer.appendChild(changeRuleBtn);
        container.appendChild(buttonContainer);
    }

    // 移除"更改重复规则"按钮
    removeChangeRuleButton() {
        const changeRuleBtn = document.getElementById('changeEventRuleBtn');
        if (changeRuleBtn) {
            const container = changeRuleBtn.closest('#changeEventRuleBtnContainer');
            if (container) {
                container.remove();
            } else {
                // 如果没有找到容器，直接删除按钮和其父容器
                const parent = changeRuleBtn.parentElement;
                if (parent) {
                    parent.remove();
                } else {
                    changeRuleBtn.remove();
                }
            }
        }
    }

    // 创建重复事件复选框
    createRecurringCheckbox() {
        // 查找插入位置 - 在事件基本信息表单后面
        const formContainer = document.querySelector('#editEventModal .modal-body');
        if (!formContainer) return;
        
        // 检查是否已存在
        if (document.getElementById('eventIsRecurring')) return;
        
        // 创建复选框容器
        const checkboxContainer = document.createElement('div');
        checkboxContainer.className = 'mb-3';
        checkboxContainer.innerHTML = `
            <div class="form-check">
                <input class="form-check-input" type="checkbox" id="eventIsRecurring" value="">
                <label class="form-check-label" for="eventIsRecurring">
                    <i class="fas fa-redo me-2"></i>重复事件
                </label>
            </div>
        `;
        
        // 找到基本信息字段后插入
        const ddlGroup = document.querySelector('#editEventModal .modal-body .mb-3:has(#eventDdl)');
        if (ddlGroup) {
            ddlGroup.parentNode.insertBefore(checkboxContainer, ddlGroup.nextSibling);
        } else {
            // 如果找不到DDL字段，插入到表单开头
            const firstGroup = formContainer.querySelector('.mb-3');
            if (firstGroup) {
                formContainer.insertBefore(checkboxContainer, firstGroup.nextSibling);
            }
        }
    }

    // 执行批量操作
    async performBulkOperation(seriesId, operation, scope, fromTime, eventId, updateData = {}) {
        try {
            console.log('performBulkOperation called with:', {
                seriesId, operation, scope, fromTime, eventId, updateData
            });
            
            // 创建AbortController用于超时控制
            const controller = new AbortController();
            const timeoutId = setTimeout(() => {
                controller.abort();
                console.log('Request aborted due to timeout');
            }, 35000); // 35秒超时
            
            const response = await fetch('/api/events/bulk-edit/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                signal: controller.signal,
                body: JSON.stringify({
                    event_id: eventId,
                    operation: operation,
                    edit_scope: scope,
                    from_time: fromTime,
                    series_id: seriesId,
                    // 传递更新数据
                    title: updateData.title,
                    description: updateData.description,
                    importance: updateData.importance,
                    urgency: updateData.urgency,
                    start: updateData.start,
                    end: updateData.end,
                    rrule: updateData.rrule,
                    groupID: updateData.groupID,
                    ddl: updateData.ddl
                })
            });
            
            // 清除超时定时器
            clearTimeout(timeoutId);
            
            console.log('API response status:', response.status);
            
            if (response.ok) {
                try {
                    const result = await response.json();
                    console.log('API response result:', result);
                    
                    // 检查结果状态
                    if (result.status === 'success') {
                        // 刷新日历
                        this.refreshCalendar();
                        console.log(`批量${operation}完成`);
                        
                        // 清理pendingBulkEdit信息
                        if (operation === 'delete') {
                            this.pendingBulkEdit = null;
                        }
                        
                        return true;
                    } else {
                        console.error('批量操作返回错误状态:', result);
                        alert(`批量${operation}失败: ${result.message || '服务器返回错误状态'}`);
                        return false;
                    }
                } catch (jsonError) {
                    console.error('解析响应JSON时出错:', jsonError);
                    // 如果JSON解析失败，但HTTP状态是OK，可能是响应被截断了
                    // 在这种情况下，我们仍然认为操作可能成功了
                    console.log('响应可能被截断，但HTTP状态为OK，假设操作成功');
                    this.refreshCalendar();
                    console.log(`批量${operation}可能完成（响应解析失败）`);
                    
                    // 清理pendingBulkEdit信息
                    if (operation === 'delete') {
                        this.pendingBulkEdit = null;
                    }
                    
                    return true;
                }
            } else {
                try {
                    const errorData = await response.json();
                    console.error('批量操作失败:', errorData);
                    alert(`批量${operation}失败: ${errorData.message || '未知错误'}`);
                } catch (jsonError) {
                    console.error('解析错误响应JSON时出错:', jsonError);
                    alert(`批量${operation}失败: HTTP ${response.status}`);
                }
                return false;
            }
        } catch (error) {
            console.error('批量操作时出错:', error);
            
            // 处理不同类型的错误
            if (error.name === 'AbortError') {
                console.log('请求被用户或超时中止');
                // 超时的情况下，我们假设操作可能成功了，但需要刷新页面确认
                this.refreshCalendar();
                alert(`批量${operation}超时，操作可能已完成，页面已刷新`);
                return true; // 返回true让调用者关闭对话框
            } else if (error.message && error.message.includes('Failed to fetch')) {
                console.log('网络错误或服务器连接问题');
                this.refreshCalendar();
                alert(`批量${operation}时网络错误，操作可能已完成，页面已刷新`);
                return true; // 网络错误时也假设可能成功
            } else {
                alert(`批量${operation}时出错: ${error.message || '未知错误'}`);
                return false;
            }
        }
    }

    // 获取CSRF Token
    getCSRFToken() {
        // 首先尝试从window.CSRF_TOKEN获取
        if (window.CSRF_TOKEN) {
            return window.CSRF_TOKEN;
        }
        // 备用方案：从DOM中查找
        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
        if (csrfToken) {
            return csrfToken;
        }
        // 最后尝试从meta标签获取
        const metaToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
        return metaToken || '';
    }
}

// 事件管理器类已定义，实例将在HTML中创建
