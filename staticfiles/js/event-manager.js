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
                this.updateEvent(
                    info.event.id,
                    info.event.start.toISOString(),
                    info.event.end.toISOString(),
                    info.event.title,
                    info.event.extendedProps.description,
                    info.event.extendedProps.importance,
                    info.event.extendedProps.urgency,
                    info.event.extendedProps.groupID,
                    info.event.extendedProps.ddl
                );
            },
            
            // 事件调整大小
            eventResize: (info) => {
                this.updateEvent(
                    info.event.id,
                    info.event.start.toISOString(),
                    info.event.end.toISOString(),
                    info.event.title,
                    info.event.extendedProps.description,
                    info.event.extendedProps.importance,
                    info.event.extendedProps.urgency,
                    info.event.extendedProps.groupID,
                    info.event.extendedProps.ddl
                );
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
                    modalManager.openEditEventModal(info.event);
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
                right: 'timeGridDay,dayGridMonth,timeGridWeek,listWeek'
            },
            
            // 获取事件数据
            events: (info, successCallback, failureCallback) => {
                this.fetchEvents(info.start, info.end)
                    .then(events => {
                        successCallback(events);
                    })
                    .catch(error => failureCallback(error));
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
        
        // 查找包含 fc-daygrid-body 的滚动器（这些是全天槽）
        const daygridScrollers = document.querySelectorAll('.fc-scroller:has(.fc-daygrid-body)');
        daygridScrollers.forEach((scroller) => {
            scroller.style.setProperty('overflow', 'hidden', 'important');
            scroller.style.setProperty('max-height', '50px', 'important');
            scroller.style.setProperty('height', '50px', 'important');
            scroller.style.setProperty('flex', '0 0 50px', 'important');
            console.log('设置全天槽滚动器（包含daygrid-body）:', scroller);
        });
        
        // 更通用的方法：检查滚动器内容来判断类型
        const allScrollers = document.querySelectorAll('.fc-scroller');
        allScrollers.forEach((scroller) => {
            const hasTimegridSlots = scroller.querySelector('.fc-timegrid-slots');
            const hasDaygridBody = scroller.querySelector('.fc-daygrid-body');
            
            if (hasTimegridSlots) {
                // 这是时间网格滚动器
                scroller.style.overflowY = 'auto';
                scroller.style.overflowX = 'hidden';
                scroller.style.maxHeight = 'none';
                scroller.style.height = '100%';
                scroller.style.flex = '1';
                console.log('识别并设置时间网格滚动器:', scroller);
            } else if (hasDaygridBody) {
                // 这是全天槽滚动器
                scroller.style.setProperty('overflow', 'hidden', 'important');
                scroller.style.setProperty('max-height', '50px', 'important');
                scroller.style.setProperty('height', '50px', 'important');
                scroller.style.setProperty('flex', '0 0 50px', 'important');
                console.log('识别并设置全天槽滚动器:', scroller);
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
                    modalManager.openEditEventModal(info.event);
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
            const response = await fetch('/get_calendar/events/');
            const data = await response.json();
            
            this.events = data.events;
            this.groups = data.events_groups;
            window.events_groups = this.groups; // 保持兼容性
            
            // 为事件添加颜色
            return this.events.map(event => ({
                ...event,
                backgroundColor: this.getEventColor(event.groupID),
                borderColor: this.getEventColor(event.groupID)
            }));
        } catch (error) {
            console.error('Error fetching events:', error);
            return [];
        }
    }

    // 获取事件颜色
    getEventColor(groupID) {
        const group = this.groups.find(g => g.id === groupID);
        return group ? group.color : '#007bff';
    }

    // 更新事件
    async updateEvent(eventId, newStart, newEnd, title, description, importance, urgency, groupID, ddl) {
        try {
            const response = await fetch('/get_calendar/update_events/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    eventId, newStart, newEnd, title, description, 
                    importance, urgency, groupID, ddl
                })
            });
            
            if (response.ok) {
                console.log('Event updated successfully');
                this.calendar.refetchEvents();
            }
        } catch (error) {
            console.error('Error updating event:', error);
        }
    }

    // 创建事件
    async createEvent(eventData) {
        try {
            const response = await fetch('/get_calendar/create_event/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(eventData)
            });
            
            if (response.ok) {
                console.log('Event created successfully');
                this.calendar.refetchEvents();
                return true;
            }
        } catch (error) {
            console.error('Error creating event:', error);
        }
        return false;
    }

    // 删除事件
    async deleteEvent(eventId) {
        try {
            const response = await fetch('/get_calendar/delete_event/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ eventId })
            });
            
            if (response.ok) {
                console.log('Event deleted successfully');
                this.calendar.refetchEvents();
                return true;
            }
        } catch (error) {
            console.error('Error deleting event:', error);
        }
        return false;
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
}

// 事件管理器类已定义，实例将在HTML中创建
