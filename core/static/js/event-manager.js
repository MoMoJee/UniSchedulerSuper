// 事件管理模块
class EventManager {
    constructor() {
        this.calendar = null;
        this.events = [];
        this.groups = [];
        this.isGroupView = false;  // 新增：标记当前是否是群组视图
        this._inFlightFetchKey = null;  // 防止同一日期范围并发重复请求，格式 "startISO|endISO"
    }

    // 初始化事件管理器
    init() {
        this.initCalendar();
        this.setupTodoDropZone();
    }

    // 设置TODO拖拽到日历的监听
    setupTodoDropZone() {
        const calendarEl = document.getElementById('calendar');
        if (!calendarEl) return;

        // 允许放置
        calendarEl.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
        });

        // 处理放置
        calendarEl.addEventListener('drop', (e) => {
            e.preventDefault();
            
            try {
                const data = JSON.parse(e.dataTransfer.getData('text/plain'));
                
                // 检查是否是TODO项
                if (data.type === 'todo') {
                    this.handleTodoDropToCalendar(data);
                }
            } catch (error) {
                console.error('处理拖拽数据时出错:', error);
            }
        });
    }

    // 处理TODO拖拽到日历
    handleTodoDropToCalendar(todoData) {
        console.log('TODO拖拽到日历:', todoData);
        
        // 转换TODO数据为Event格式
        const eventData = this.convertTodoToEvent(todoData);
        
        // 打开创建Event模态框并自动填充数据
        this.openCreateEventModalWithTodoData(eventData);
    }

    // 将TODO数据转换为Event数据
    convertTodoToEvent(todoData) {
        // 计算起始时间：当前时间 + 1小时
        const now = new Date();
        const startTime = new Date(now.getTime() + 60 * 60 * 1000);
        
        // 计算结束时间：起始时间 + 预计耗时
        let endTime;
        if (todoData.estimatedDuration) {
            const duration = this.parseDuration(todoData.estimatedDuration);
            endTime = new Date(startTime.getTime() + duration);
        } else {
            // 默认1小时
            endTime = new Date(startTime.getTime() + 60 * 60 * 1000);
        }
        
        return {
            title: todoData.title,
            todoId: todoData.id,  // 保存TODO的ID
            groupID: todoData.groupID,
            description: todoData.description,
            startTime: this.formatDateTimeLocal(startTime),
            endTime: this.formatDateTimeLocal(endTime),
            ddl: todoData.dueDate ? this.formatDateTimeLocal(new Date(todoData.dueDate)) : '',
            importance: todoData.importance,
            urgency: todoData.urgency
        };
    }

    // 解析时长字符串（如 "2h", "30m", "1.5h"）
    parseDuration(durationStr) {
        if (!durationStr) return 60 * 60 * 1000; // 默认1小时
        
        const match = durationStr.match(/^([\d.]+)\s*([hm])$/i);
        if (!match) return 60 * 60 * 1000;
        
        const value = parseFloat(match[1]);
        const unit = match[2].toLowerCase();
        
        if (unit === 'h') {
            return value * 60 * 60 * 1000; // 小时转毫秒
        } else if (unit === 'm') {
            return value * 60 * 1000; // 分钟转毫秒
        }
        
        return 60 * 60 * 1000;
    }

    // 格式化日期时间为本地时间格式（YYYY-MM-DDTHH:mm）
    formatDateTimeLocal(date) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');
        return `${year}-${month}-${day}T${hours}:${minutes}`;
    }

    // 打开创建Event模态框并填充TODO数据
    openCreateEventModalWithTodoData(eventData) {
        if (!window.modalManager) {
            console.error('ModalManager未初始化');
            return;
        }
        
        // 标记这个事件来源于TODO转换，并保存TODO的ID
        window.modalManager.fromTodoConversion = true;
        window.modalManager.sourceTodoId = eventData.todoId;
        
        // 先打开模态框
        window.modalManager.openCreateEventModal(eventData.startTime, eventData.endTime);
        
        // 延迟填充其他数据，确保模态框已完全打开
        setTimeout(() => {
            // 填充标题
            const titleInput = document.getElementById('newEventTitle');
            if (titleInput) titleInput.value = eventData.title;
            
            // 填充描述
            const descInput = document.getElementById('newEventDescription');
            if (descInput) descInput.value = eventData.description;
            
            // 填充DDL
            if (eventData.ddl) {
                const ddlInput = document.getElementById('creatEventDdl');
                if (ddlInput) ddlInput.value = eventData.ddl;
            }
            
            // 填充日程组
            if (eventData.groupID) {
                const groupSelect = document.getElementById('newEventGroupId');
                if (groupSelect) groupSelect.value = eventData.groupID;
            }
            
            // 设置重要性和紧急性
            if (eventData.importance && eventData.urgency && window.modalManager) {
                window.modalManager.setImportanceUrgency(
                    eventData.importance, 
                    eventData.urgency, 
                    'create'
                );
            }
        }, 100);
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
        
        // 从用户设置中读取每周起始日,默认为周一(1)
        const weekStartsOn = window.userSettings?.week_starts_on || 1;
        
        // 从settingsManager获取保存的视图状态
        const savedView = window.settingsManager?.getCategorySettings('calendarView') || {};
        
        // 确定初始视图: 优先使用保存的视图,否则使用默认视图,最后回退到周视图
        let initialView = 'timeGridWeek'; // 最后的回退值
        if (savedView.viewType) {
            initialView = savedView.viewType; // 刷新页面场景
            console.log('使用保存的视图类型:', initialView);
        } else if (window.userSettings?.calendar_view_default) {
            initialView = window.userSettings.calendar_view_default; // 重新登录场景
            console.log('使用默认视图类型:', initialView);
        }
        
        // 确定初始日期: 使用保存的日期,否则使用今天
        const initialDate = savedView.currentDate || undefined; // undefined让FullCalendar使用今天
        if (initialDate) {
            console.log('使用保存的日期:', initialDate);
        }
        
        this.calendar = new FullCalendar.Calendar(calendarEl, {
            height: '100%', // 使用100%高度填满容器
            locale: 'zh-cn',
            allDayText: '全天',
            initialView: initialView, // 使用计算出的初始视图
            initialDate: initialDate, // 使用保存的日期(如果有)
            firstDay: weekStartsOn, // 设置每周起始日: 0=周日, 1=周一, ..., 6=周六
            weekNumbers: true, // 启用周数显示（在月视图左侧显示周数）
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
            
            // 自定义按钮文字
            buttonText: {
                today: '今天',
                month: '月',
                week: '周',
                day: '日',
                list: '列表'
            },
            
            // 自定义星期名称
            dayHeaderContent: (args) => {
                const dayNames = ['日', '一', '二', '三', '四', '五', '六'];
                const dayOfWeek = dayNames[args.date.getDay()];
                const dayOfMonth = args.date.getDate();
                
                // 判断当前视图类型
                const viewType = args.view.type;
                
                // 月视图只显示日期数字（FullCalendar默认会显示）
                if (viewType === 'dayGridMonth') {
                    return dayOfMonth;
                }
                
                // 周视图和2日视图显示日期+圆形星期
                // 返回HTML结构，星期用span包裹以便添加样式
                return {
                    html: `${dayOfMonth}日 <span class="day-of-week-badge">${dayOfWeek}</span>`
                };
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

            // 拖拽开始：记录当前拖拽的事件，供拖入 Agent 面板时使用；同时显示 Agent 面板视觉提示
            eventDragStart: (info) => {
                const isReminder = info.event.extendedProps.isReminder;
                // 保留原始字符串 ID，不做 parseInt（事件 ID 可能是 UUID）
                const rawId = info.event.id;
                const elementId = isReminder ? rawId.replace('reminder_', '') : rawId;
                window._fcDraggedEvent = {
                    type: isReminder ? 'reminder' : 'event',
                    id: elementId,
                    title: info.event.title,
                };
                // 直接给 Agent 面板加 element-drag-over class，提供视觉反馈
                const agentPanel = document.querySelector('.agent-panel-content');
                if (agentPanel) agentPanel.classList.add('element-drag-over');
            },

            // 拖拽结束：检测是否落在 Agent 面板上，并清除视觉提示
            eventDragStop: (info) => {
                const agentPanel = document.querySelector('.agent-panel-content');
                if (agentPanel) agentPanel.classList.remove('element-drag-over');
                if (!window._fcDraggedEvent) return;
                const jsEvent = info.jsEvent;
                if (agentPanel && jsEvent) {
                    const rect = agentPanel.getBoundingClientRect();
                    const x = jsEvent.clientX;
                    const y = jsEvent.clientY;
                    if (x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom) {
                        agentPanel.dispatchEvent(new CustomEvent('fcEventDropped', {
                            detail: { ...window._fcDraggedEvent }
                        }));
                    }
                }
                window._fcDraggedEvent = null;
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
                        // 普通事件，打开详情预览
                        this.openEventDetailModal(info.event);
                    }
                } catch (error) {
                    console.error('打开事件详情模态框时出错:', error);
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
                right: 'calendarFilterButton,timeGridTwoDay,dayGridMonth,timeGridWeek,listWeek'
            },
            
            // 自定义按钮
            customButtons: {
                calendarFilterButton: {
                    text: '筛选',
                    hint: '日历筛选',
                    click: () => {
                        this.toggleFilterDropdown();
                    }
                }
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
                console.log('[EventManager] 初始 events 回调被触发');
                
                // 这个回调只在初始化时使用一次，之后由 addEventSource 管理
                // 如果已经有 my-calendar 事件源，返回空
                const sources = this.calendar?.getEventSources() || [];
                const hasMyCalendarSource = sources.some(s => s.id === 'my-calendar');
                
                if (hasMyCalendarSource) {
                    console.log('[EventManager] 已存在 my-calendar 事件源，跳过初始回调');
                    successCallback([]);
                    return;
                }
                
                // 防止同一日期范围的并发重复请求（FullCalendar 多次渲染时会触发多次回调）
                const fetchKey = `${info.start?.toISOString()}|${info.end?.toISOString()}`;
                if (this._inFlightFetchKey === fetchKey) {
                    console.log('[EventManager] 相同范围已在加载中，跳过重复调用');
                    successCallback([]);
                    return;
                }
                this._inFlightFetchKey = fetchKey;
                
                // 初始加载
                console.log('[EventManager] 执行初始事件加载');
                this.fetchEvents(info.start, info.end)
                    .then(events => {
                        console.log(`[EventManager] 初始加载完成，返回 ${events.length} 个事件`);
                        successCallback(events);
                    })
                    .catch(error => {
                        console.error('[EventManager] 初始加载失败:', error);
                        failureCallback(error);
                    })
                    .finally(() => {
                        if (this._inFlightFetchKey === fetchKey) {
                            this._inFlightFetchKey = null;
                        }
                    });
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
            },
            
            // 事件渲染完成后的钩子，用于自定义样式（成员颜色）
            eventDidMount: (info) => {
                this.customizeEventAppearance(info);
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
                            // 普通事件，打开详情预览
                            this.openEventDetailModal(info.event);
                        }
                    } catch (error) {
                        console.error('处理事件点击时出错:', error);
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
        console.log('[EventManager] fetchEvents 开始执行');
        try {
            // 构建带日期范围参数的URL，只获取当前视图范围内的事件
            let eventsUrl = '/get_calendar/events/';
            if (start && end) {
                const startISO = (start instanceof Date) ? start.toISOString() : start;
                const endISO = (end instanceof Date) ? end.toISOString() : end;
                eventsUrl += `?start=${encodeURIComponent(startISO)}&end=${encodeURIComponent(endISO)}`;
            }
            
            // 获取日程数据
            const response = await fetch(eventsUrl);
            const data = await response.json();
            
            this.events = data.events;
            this.groups = data.events_groups;
            window.events_groups = this.groups; // 保持兼容性
            
            console.log(`[EventManager] 获取到 ${data.events.length} 个日程`);
            
            // 获取提醒数据（带服务端筛选参数）
            // 如果 reminderManager 最近已加载过数据（30秒内），复用缓存
            let reminders;
            const CACHE_TTL = 30000; // 30秒缓存有效期
            const canUseCachedReminders = window.reminderManager 
                && window.reminderManager._lastFetched 
                && (Date.now() - window.reminderManager._lastFetched < CACHE_TTL)
                && window.reminderManager.reminders.length > 0;
            
            if (canUseCachedReminders) {
                console.log('[EventManager] 使用 reminderManager 缓存的提醒数据');
                reminders = window.reminderManager.reminders;
            } else {
                const reminderParams = new URLSearchParams();
                const statusFilter = document.getElementById('reminderStatusFilter')?.value || 'active';
                const priorityFilter = document.getElementById('reminderPriorityFilter')?.value || 'all';
                const typeFilter = document.getElementById('reminderTypeFilter')?.value || 'all';
                
                if (statusFilter && statusFilter !== 'all') reminderParams.set('status', statusFilter);
                if (priorityFilter && priorityFilter !== 'all') reminderParams.set('priority', priorityFilter);
                if (typeFilter && typeFilter !== 'all') reminderParams.set('type', typeFilter);
                // 传入当前视图的日期范围，只获取视图内的提醒
                if (start && end) {
                    reminderParams.set('start', (start instanceof Date) ? start.toISOString() : start);
                    reminderParams.set('end', (end instanceof Date) ? end.toISOString() : end);
                }
                
                const reminderQuery = reminderParams.toString();
                const reminderUrl = '/api/reminders/' + (reminderQuery ? `?${reminderQuery}` : '');
                const reminderResponse = await fetch(reminderUrl);
                const reminderData = await reminderResponse.json();
                reminders = reminderData.reminders || [];
            }
            
            console.log(`[EventManager] 获取到 ${reminders.length} 个提醒`);
            
            // 服务端已经过滤，直接使用返回的结果
            const filteredReminders = reminders;
            
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
            let allEvents = [
                ...this.events.map(event => ({
                    ...event,
                    backgroundColor: this.getEventColor(event.groupID),
                    borderColor: this.getEventColor(event.groupID),
                    extendedProps: {
                        ...(event.extendedProps || {}),
                        owner_color: event.owner_color,
                        owner_name: event.owner_name,
                        is_readonly: event.is_readonly || false,
                        shared_groups: event.shared_groups || []  // 添加分享群组信息
                    }
                })),
                ...reminderEvents
            ];
            
            console.log(`[EventManager] 合并后共 ${allEvents.length} 个事件`);
            
            // 应用日历筛选
            allEvents = this.applyCalendarFilters(allEvents);
            
            console.log(`[EventManager] 筛选后剩余 ${allEvents.length} 个事件`);
            console.log('[EventManager] fetchEvents 执行完成');
            
            return allEvents;
        } catch (error) {
            console.error('Error fetching events:', error);
            return [];
        }
    }
    
    /**
     * 应用日历筛选条件
     * @param {Array} events - 待筛选的事件数组
     * @returns {Array} 筛选后的事件数组
     */
    applyCalendarFilters(events) {
        // 从设置管理器获取筛选配置
        const filters = window.settingsManager?.settings?.calendarFilters;
        
        if (!filters) {
            console.log('未找到日历筛选配置，显示所有事件');
            return events;
        }
        
        // 检查是否在群组视图
        const isGroupView = window.shareGroupManager?.state?.currentViewType === 'share-group';
        
        console.log('[EventManager] 应用筛选:', {
            totalEvents: events.length,
            isGroupView,
            filters: {
                members: filters.members,
                quadrants: filters.quadrants,
                hasDDL: filters.hasDDL,
                noDDL: filters.noDDL
            }
        });
        
        const filteredEvents = events.filter(event => {
            // 提醒事件只受 showReminders 控制
            if (event.extendedProps?.isReminder) {
                return filters.showReminders;
            }
            
            // 群组视图特殊处理
            if (isGroupView) {
                // 1. 成员筛选：对所有事件生效（我的+别人的）
                if (filters.members && filters.members.length > 0) {
                    const eventUserId = event.user_id || event.owner_id || event.extendedProps?.user_id || event.extendedProps?.owner_id;
                    
                    if (eventUserId) {
                        const isInSelectedMembers = filters.members.includes(parseInt(eventUserId));
                        if (!isInSelectedMembers) {
                            console.log('[筛选] 过滤事件（不在选中成员）:', {
                                title: event.title,
                                userId: eventUserId,
                                selectedMembers: filters.members
                            });
                            return false;  // 不在选中成员列表中，过滤掉
                        }
                    }
                }
                
                // 2. 其他筛选：只对我的日程生效
                const isMyEvent = event.extendedProps?.isMyEvent;
                if (!isMyEvent) {
                    // 不是我的事件，直接显示（不应用其他筛选）
                    return true;
                }
                
                // 是我的事件，继续应用其他筛选...
            }
            
            // 普通事件的筛选逻辑（或群组中"我的事件"）
            
            // 1. 检查象限筛选（重要性 + 紧急性）
            const quadrant = this.getEventQuadrant(event.importance, event.urgency);
            if (!filters.quadrants[quadrant]) {
                return false;
            }
            
            // 2. 检查DDL筛选
            const hasDDL = event.ddl && event.ddl.trim() !== '';
            if (hasDDL && !filters.hasDDL) {
                return false;
            }
            if (!hasDDL && !filters.noDDL) {
                return false;
            }
            
            // 3. 检查重复事件筛选
            const isRecurring = event.rrule && event.rrule.includes('FREQ=');
            if (isRecurring && !filters.isRecurring) {
                return false;
            }
            if (!isRecurring && !filters.notRecurring) {
                return false;
            }
            
            // 4. 检查分组筛选
            if (filters.groups && filters.groups.length > 0) {
                // 检查是否属于"无日程组"类别
                const hasNoGroup = !event.groupID || event.groupID === '';
                const noneSelected = filters.groups.includes('none');
                
                // 检查是否属于某个选中的日程组
                const groupMatched = event.groupID && filters.groups.includes(event.groupID);
                
                // 如果选中了"无日程组"，且事件确实无日程组，则显示
                if (noneSelected && hasNoGroup) {
                    return true;
                }
                
                // 如果事件属于某个选中的日程组，则显示
                if (groupMatched) {
                    return true;
                }
                
                // 都不匹配，则过滤掉
                return false;
            }
            
            return true;
        });
        
        console.log('[EventManager] 筛选完成:', {
            原始事件数: events.length,
            筛选后事件数: filteredEvents.length,
            被过滤掉: events.length - filteredEvents.length
        });
        
        return filteredEvents;
    }
    
    /**
     * 根据重要性和紧急性获取象限
     * @param {string} importance - 重要性: 'important' 或 'not-important'
     * @param {string} urgency - 紧急性: 'urgent' 或 'not-urgent'
     * @returns {string} 象限名称
     */
    getEventQuadrant(importance, urgency) {
        const isImportant = importance === 'important';
        const isUrgent = urgency === 'urgent';
        
        if (isImportant && isUrgent) return 'importantUrgent';
        if (isImportant && !isUrgent) return 'importantNotUrgent';
        if (!isImportant && isUrgent) return 'notImportantUrgent';
        return 'notImportantNotUrgent';
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
        
        // 检查截止时间限制
        const ddl = event.extendedProps.ddl;
        if (ddl) {
            const ddlDate = new Date(ddl);
            const newEnd = event.end ? new Date(event.end) : new Date(event.start);
            
            if (newEnd > ddlDate) {
                // 超过截止时间，弹回并提示
                const formatDateTime = (date) => {
                    return date.toLocaleString('zh-CN', {
                        year: 'numeric',
                        month: '2-digit',
                        day: '2-digit',
                        hour: '2-digit',
                        minute: '2-digit'
                    });
                };
                
                alert(
                    `❌ 操作失败：日程结束时间不能超过截止时间！\n\n` +
                    `日程标题：${event.title}\n` +
                    `新结束时间：${formatDateTime(newEnd)}\n` +
                    `截止时间：${formatDateTime(ddlDate)}\n\n` +
                    `请将日程安排在截止时间之前。`
                );
                
                info.revert();
                return;
            }
        }
        
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
            event.extendedProps.shared_to_groups || [],  // 【修复】传递群组信息
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
    async updateEventDrag(eventId, newStart, newEnd, title, description, importance, urgency, groupID, ddl, shared_to_groups = [], rruleChangeScope = 'single') {
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
                shared_to_groups: shared_to_groups,  // 【修复】添加群组信息
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
                // 拖拽更新：FullCalendar已在UI上移动了事件，无需刷新
                // 仅同步本地数据
                const idx = this.events.findIndex(e => e.id === eventData.eventId);
                if (idx !== -1) {
                    this.events[idx] = { ...this.events[idx], ...eventData };
                }
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
    async updateEvent(eventId, newStart, newEnd, title, description, importance, urgency, groupID, ddl, rrule = '', shared_to_groups = []) {
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
                rrule: rrule,
                shared_to_groups: shared_to_groups  // 新增
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
                // 非重复事件：尝试本地更新日历
                if (!rrule && this.calendar) {
                    const calEvent = this.calendar.getEventById(eventId);
                    if (calEvent) {
                        calEvent.remove();
                    }
                    // 添加更新后的事件
                    this.calendar.addEvent({
                        id: eventId,
                        title: title,
                        start: newStart,
                        end: newEnd,
                        description: description,
                        importance: importance,
                        urgency: urgency,
                        groupID: groupID,
                        ddl: ddl,
                        rrule: rrule,
                        shared_to_groups: shared_to_groups,
                        backgroundColor: this.getEventColor(groupID),
                        borderColor: this.getEventColor(groupID),
                        extendedProps: {
                            shared_groups: []
                        }
                    });
                    // 同步本地数据
                    const idx = this.events.findIndex(e => e.id === eventId);
                    if (idx !== -1) {
                        this.events[idx] = { ...this.events[idx], title, start: newStart, end: newEnd, description, importance, urgency, groupID, ddl, rrule, shared_to_groups };
                    }
                } else {
                    // 有重复规则或找不到本地事件：刷新（已有日期过滤）
                    this.refreshCalendar();
                }
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
                // 判断是否为重复事件
                if (eventData.rrule) {
                    // 重复事件：服务端会生成多个实例，需要从服务端获取（已有日期范围过滤，量小）
                    this.refreshCalendar();
                } else if (result.event && this.calendar) {
                    // 非重复事件：直接添加到本地日历
                    const newEvent = result.event;
                    this.events.push(newEvent);
                    this.calendar.addEvent({
                        ...newEvent,
                        backgroundColor: this.getEventColor(newEvent.groupID),
                        borderColor: this.getEventColor(newEvent.groupID),
                        extendedProps: {
                            ...(newEvent.extendedProps || {}),
                            shared_groups: newEvent.shared_groups || []
                        }
                    });
                } else {
                    this.refreshCalendar();
                }
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
                    series_id: seriesId || eventId
                })
            });
            
            const result = await response.json();
            
            if (response.ok && result.status === 'success') {
                console.log('Event deleted successfully');
                // 单个非重复事件删除：本地移除
                if (scope === 'single' && this.calendar) {
                    const calEvent = this.calendar.getEventById(eventId);
                    if (calEvent) {
                        calEvent.remove();
                    } else {
                        this.refreshCalendar();
                    }
                    // 同步本地数据
                    this.events = this.events.filter(e => e.id !== eventId);
                } else {
                    // 批量删除（all/future）需要刷新
                    this.refreshCalendar();
                }
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
        console.log('[EventManager] refreshCalendar 被调用, isGroupView:', this.isGroupView);
        
        // 如果是群组视图，由 shareGroupManager 处理刷新
        if (this.isGroupView && window.shareGroupManager) {
            console.log('[EventManager] 群组视图模式，委托给 shareGroupManager 刷新');
            const currentGroupId = window.shareGroupManager.state.currentGroupId;
            if (currentGroupId) {
                window.shareGroupManager.loadGroupCalendar(currentGroupId);
            }
            return;
        }
        
        // 我的日历视图
        console.log('[EventManager] 我的日历模式，触发 refetchEvents');
        
        // 检查是否有 my-calendar 事件源
        const sources = this.calendar.getEventSources();
        const myCalendarSource = sources.find(s => s.id === 'my-calendar');
        
        if (myCalendarSource) {
            // 如果有 my-calendar 事件源，直接刷新
            console.log('[EventManager] 找到 my-calendar 事件源，刷新');
            this.calendar.refetchEvents();
        } else {
            // 如果没有事件源，重新加载（可能是初始状态）
            console.log('[EventManager] 未找到 my-calendar 事件源，使用 shareGroupManager 重新加载');
            if (window.shareGroupManager) {
                window.shareGroupManager.loadMyCalendar();
            } else {
                // 兜底：使用原始的 refetchEvents
                this.calendar.refetchEvents();
            }
        }
    }

    // 检查是否是重复事件，显示编辑范围选择器
    // 打开事件详情模态框（预览模式）
    openEventDetailModal(eventInfo) {
        console.log('Opening event detail modal:', eventInfo);
        
        const modal = document.getElementById('eventDetailModal');
        if (!modal) {
            console.error('事件详情模态框未找到');
            return;
        }
        
        const eventData = eventInfo.extendedProps || {};
        const isMyEvent = eventData.isMyEvent !== false; // 默认为true（我的事件）
        
        // 设置标题
        const titleElement = document.getElementById('eventDetailTitle');
        if (titleElement) {
            titleElement.textContent = eventInfo.title || '';
        }
        
        // 设置时间
        const timeElement = document.getElementById('eventDetailTime');
        if (timeElement) {
            const startTime = new Date(eventInfo.start);
            const endTime = eventInfo.end ? new Date(eventInfo.end) : null;
            const formattedStart = startTime.toLocaleString('zh-CN', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                weekday: 'short'
            });
            if (endTime) {
                const formattedEnd = endTime.toLocaleString('zh-CN', {
                    hour: '2-digit',
                    minute: '2-digit'
                });
                timeElement.textContent = `${formattedStart} - ${formattedEnd}`;
            } else {
                timeElement.textContent = formattedStart;
            }
        }
        
        // 设置归属信息（仅对不是自己的事件显示）
        const ownerElement = document.getElementById('eventDetailOwner');
        const ownerRow = document.getElementById('eventDetailOwnerRow');
        if (!isMyEvent && ownerRow && ownerElement) {
            // 显示归属用户信息
            const ownerName = eventData.owner_username || eventData.ownerUsername || '其他用户';
            ownerElement.innerHTML = `<i class="fas fa-user me-2"></i>${ownerName}`;
            ownerRow.style.display = 'flex';
        } else if (ownerRow) {
            ownerRow.style.display = 'none';
        }
        
        // 设置日程组（仅对自己的事件且有日程组时显示）
        const groupElement = document.getElementById('eventDetailGroup');
        const groupRow = document.getElementById('eventDetailGroupRow');
        if (isMyEvent && eventData.groupID && window.groupManager) {
            const group = window.groupManager.getGroupById(eventData.groupID);
            if (group && groupElement && groupRow) {
                groupElement.textContent = group.name;
                groupElement.style.color = group.color;
                groupElement.style.fontWeight = '600';
                groupRow.style.display = 'flex';
            } else if (groupRow) {
                groupRow.style.display = 'none';
            }
        } else if (groupRow) {
            // 不是自己的事件或没有日程组，隐藏
            groupRow.style.display = 'none';
            // 清除可能残留的内容
            if (groupElement) {
                groupElement.textContent = '';
            }
        }
        
        // 设置优先级（重要性/紧急性）
        const priorityElement = document.getElementById('eventDetailPriority');
        const priorityRow = document.getElementById('eventDetailPriorityRow');
        if ((eventData.importance || eventData.urgency) && priorityElement && priorityRow) {
            const importanceText = eventData.importance === 'important' ? '重要' : '不重要';
            const urgencyText = eventData.urgency === 'urgent' ? '紧急' : '不紧急';
            const icon = this.getEventPriorityIcon(eventData.importance, eventData.urgency);
            priorityElement.innerHTML = `${icon} ${importanceText} / ${urgencyText}`;
            priorityRow.style.display = 'flex';
        } else if (priorityRow) {
            priorityRow.style.display = 'none';
        }
        
        // 设置描述（仅在有内容时显示）
        const descElement = document.getElementById('eventDetailDescription');
        const descRow = document.getElementById('eventDetailDescriptionRow');
        if (eventData.description && descElement && descRow) {
            descElement.textContent = eventData.description;
            descRow.style.display = 'flex';
        } else if (descRow) {
            descRow.style.display = 'none';
        }
        
        // 设置DDL（仅在有时显示）
        const ddlElement = document.getElementById('eventDetailDdl');
        const ddlRow = document.getElementById('eventDetailDdlRow');
        if (eventData.ddl && ddlElement && ddlRow) {
            const ddlTime = new Date(eventData.ddl);
            const formattedDdl = ddlTime.toLocaleString('zh-CN', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                weekday: 'short'
            });
            ddlElement.textContent = formattedDdl;
            ddlRow.style.display = 'flex';
        } else if (ddlRow) {
            ddlRow.style.display = 'none';
        }
        
        // 设置重复规则（仅在有时显示）
        const rruleElement = document.getElementById('eventDetailRRule');
        const rruleRow = document.getElementById('eventDetailRRuleRow');
        if (eventData.rrule && rruleElement && rruleRow) {
            rruleElement.textContent = eventData.rrule;
            rruleRow.style.display = 'flex';
        } else if (rruleRow) {
            rruleRow.style.display = 'none';
        }
        
        // 设置编辑按钮（只对自己的事件显示）
        const editBtn = document.getElementById('eventDetailEditBtn');
        if (editBtn) {
            if (isMyEvent) {
                // 自己的事件：显示编辑按钮
                editBtn.style.display = 'inline-block';
                editBtn.onclick = () => {
                    this.closeEventDetailModal();
                    this.handleEventEdit(eventInfo);
                };
            } else {
                // 他人的事件：隐藏编辑按钮
                editBtn.style.display = 'none';
            }
        }
        
        // 显示模态框
        modal.style.display = 'flex';
        requestAnimationFrame(() => {
            modal.classList.add('show');
        });
        document.body.style.overflow = 'hidden';
        
        console.log('Event detail modal opened, isMyEvent:', isMyEvent);
    }
    
    // 关闭事件详情模态框
    closeEventDetailModal() {
        const modal = document.getElementById('eventDetailModal');
        if (modal) {
            if (modal.classList.contains('show')) {
                modal.style.opacity = '0';
                modal.classList.remove('show');
                setTimeout(() => {
                    modal.style.display = 'none';
                    modal.style.removeProperty('opacity');
                }, 300);
            } else {
                modal.style.display = 'none';
            }
            document.body.style.overflow = 'auto';
        }
    }
    
    // 获取事件优先级图标
    getEventPriorityIcon(importance, urgency) {
        if (importance === 'important' && urgency === 'urgent') {
            return '🔴';  // 重要紧急
        } else if (importance === 'important' && urgency === 'not-urgent') {
            return '🟡';  // 重要不紧急
        } else if (importance === 'not-important' && urgency === 'urgent') {
            return '🟠';  // 不重要紧急
        } else {
            return '🟢';  // 不重要不紧急
        }
    }

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
        
        // 调用统一的详情展示方法
        this.openReminderDetailModal(reminderData, reminderId);
    }
    
    // 打开提醒详情模态框（统一方法，从日历或列表调用）
    openReminderDetailModal(reminderData, reminderId) {
        console.log('Opening reminder detail modal:', reminderData);
        
        const modal = document.getElementById('reminderDetailModal');
        if (!modal) {
            console.error('提醒详情模态框未找到');
            return;
        }
        
        // 设置标题（显示优先级图标 + 标题）
        const titleElement = document.getElementById('reminderDetailTitle');
        const priorityIcon = this.getPriorityIcon(reminderData.priority);
        if (titleElement) {
            titleElement.innerHTML = `${priorityIcon} ${reminderData.title || ''}`;
        }
        
        // 设置优先级
        const priorityElement = document.getElementById('reminderDetailPriority');
        if (priorityElement) {
            const priorityText = this.getPriorityText(reminderData.priority);
            priorityElement.innerHTML = `${priorityIcon} ${priorityText}`;
        }
        
        // 设置提醒时间
        const timeElement = document.getElementById('reminderDetailTime');
        if (timeElement) {
            const triggerTime = new Date(reminderData.snooze_until || reminderData.trigger_time);
            const formattedTime = this.formatReminderTime(triggerTime);
            const isOverdue = triggerTime < new Date();
            timeElement.innerHTML = isOverdue ? 
                `<span class="text-danger">${formattedTime} (已过期)</span>` : 
                formattedTime;
        }
        
        // 设置描述（仅在有内容时显示）
        const descElement = document.getElementById('reminderDetailDescription');
        const descRow = document.getElementById('reminderDetailDescriptionRow');
        const contentText = reminderData.content || reminderData.description || '';
        if (contentText && descElement && descRow) {
            descElement.textContent = contentText;
            descRow.style.display = 'flex';
        } else if (descRow) {
            descRow.style.display = 'none';
        }
        
        // 设置重复规则（仅在有时显示）
        const rruleElement = document.getElementById('reminderDetailRRule');
        const rruleRow = document.getElementById('reminderDetailRRuleRow');
        if (reminderData.rrule && rruleElement && rruleRow) {
            rruleElement.textContent = reminderData.rrule;
            rruleRow.style.display = 'flex';
        } else if (rruleRow) {
            rruleRow.style.display = 'none';
        }
        
        // 设置提前提醒（仅在有时显示）
        const advanceElement = document.getElementById('reminderDetailAdvance');
        const advanceRow = document.getElementById('reminderDetailAdvanceRow');
        if (reminderData.advance_triggers && reminderData.advance_triggers.length > 0 && advanceElement && advanceRow) {
            const advanceText = reminderData.advance_triggers.map(at => at.time_before).join(', ');
            advanceElement.textContent = advanceText;
            advanceRow.style.display = 'flex';
        } else if (advanceRow) {
            advanceRow.style.display = 'none';
        }
        
        // 生成状态和延后按钮
        const statusButtonsContainer = document.getElementById('reminderDetailStatusButtons');
        if (statusButtonsContainer) {
            statusButtonsContainer.innerHTML = this.generateReminderStatusButtons(reminderData, reminderId);
        }
        
        // 设置编辑和删除按钮
        const editBtn = document.getElementById('reminderDetailEditBtn');
        const deleteBtn = document.getElementById('reminderDetailDeleteBtn');
        
        if (editBtn) {
            editBtn.onclick = () => {
                this.closeReminderDetailModal();
                this.editReminderFromCalendar(reminderId);
            };
        }
        
        if (deleteBtn) {
            deleteBtn.onclick = () => {
                this.closeReminderDetailModal();
                this.deleteReminderFromCalendar(reminderId);
            };
        }
        
        // 显示模态框
        modal.style.display = 'flex';
        requestAnimationFrame(() => {
            modal.classList.add('show');
        });
        document.body.style.overflow = 'hidden';
        
        // 禁用日历交互
        if (this.calendar) {
            this.calendar.setOption('selectable', false);
            this.calendar.setOption('selectMirror', false);
        }
        
        console.log('Reminder detail modal opened');
    }
    
    // 关闭提醒详情模态框
    closeReminderDetailModal() {
        const modal = document.getElementById('reminderDetailModal');
        if (modal) {
            if (modal.classList.contains('show')) {
                modal.style.opacity = '0';
                modal.classList.remove('show');
                setTimeout(() => {
                    modal.style.display = 'none';
                    modal.style.removeProperty('opacity');
                }, 300);
            } else {
                modal.style.display = 'none';
            }
            document.body.style.overflow = 'auto';
        }
        
        // 重新启用日历交互
        if (this.calendar) {
            this.calendar.setOption('selectable', true);
            this.calendar.setOption('selectMirror', true);
        }
    }
    
    // 生成状态和延后按钮HTML
    generateReminderStatusButtons(reminderData, reminderId) {
        const status = reminderData.status || 'active';
        const completedClass = status === 'completed' ? 'btn-success active' : 'btn-outline-success';
        const dismissedClass = status === 'dismissed' ? 'btn-secondary active' : 'btn-outline-secondary';
        
        let html = `
            <button class="btn btn-sm ${completedClass}" onclick="eventManager.toggleReminderStatus('${reminderId}', 'completed')">
                <i class="fas fa-check me-1"></i>完成
            </button>
            <button class="btn btn-sm ${dismissedClass}" onclick="eventManager.toggleReminderStatus('${reminderId}', 'dismissed')">
                <i class="fas fa-times me-1"></i>忽略
            </button>
        `;
        
        // 延后按钮
        const isSnoozing = status && status.startsWith('snoozed_');
        if (isSnoozing) {
            const snoozeType = status.replace('snoozed_', '');
            const snoozeText = this.getSnoozeText(snoozeType, reminderData.snooze_until);
            html += `
                <button class="btn btn-sm btn-warning active" disabled>${snoozeText}</button>
                <button class="btn btn-sm btn-outline-warning" onclick="eventManager.cancelReminderSnooze('${reminderId}')">
                    <i class="fas fa-undo me-1"></i>取消延后
                </button>
            `;
        } else {
            html += `
                <div class="dropdown d-inline-block">
                    <button class="btn btn-sm btn-info dropdown-toggle" type="button" data-bs-toggle="dropdown">
                        <i class="fas fa-clock me-1"></i>延后
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
        
        return html;
    }
    
    // 获取优先级文本
    getPriorityText(priority) {
        const textMap = {
            'urgent': '紧急',
            'high': '高',
            'normal': '普通',
            'low': '低',
            'debug': '调试'
        };
        return textMap[priority] || '普通';
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
        // 先获取当前提醒数据，判断是否需要切换为 active
        const currentReminder = window.reminderManager ? 
            window.reminderManager.reminders.find(r => r.id === reminderId) : null;
        
        // 如果当前状态与目标状态相同，则切换为 active（取消标记）
        const newStatus = currentReminder && currentReminder.status === targetStatus ? 'active' : targetStatus;
        
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
                // 关闭模态框
                this.closeReminderDetailModal();
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
        // 先关闭模态框
        this.closeReminderDetailModal();
        
        // 调用 reminderManager 的方法
        if (window.reminderManager) {
            await window.reminderManager.snoozeReminder(reminderId, duration);
            // 重新加载日历（reminderManager.snoozeReminder 已经处理了刷新）
            this.calendar.refetchEvents();
        } else {
            alert('提醒管理器未初始化');
        }
    }
    
    // 取消延后
    async cancelReminderSnooze(reminderId) {
        // 先关闭模态框
        this.closeReminderDetailModal();
        
        if (window.reminderManager) {
            await window.reminderManager.cancelSnooze(reminderId);
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
        // 调用 modal-manager 的编辑提醒方法
        if (window.modalManager) {
            // 需要先获取提醒数据
            fetch('/api/reminders/')
                .then(res => res.json())
                .then(data => {
                    const reminder = data.reminders.find(r => r.id === reminderId);
                    if (reminder) {
                        // 检查是否是重复提醒
                        if (reminder.rrule && reminder.series_id) {
                            // 调用提醒管理器的批量编辑对话框
                            if (window.reminderManager) {
                                reminderManager.showBulkEditDialog(
                                    reminder.id,
                                    reminder.series_id,
                                    'edit'
                                );
                            } else {
                                console.error('reminderManager not available');
                                modalManager.openEditReminderModal(reminder);
                            }
                        } else {
                            // 单个提醒，直接编辑
                            modalManager.openEditReminderModal(reminder);
                        }
                    }
                })
                .catch(err => console.error('Error loading reminder:', err));
        }
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
                    ddl: updateData.ddl,
                    shared_to_groups: updateData.shared_to_groups || []  // 新增：群组分享
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
    
    /**
     * 切换筛选下拉菜单的显示/隐藏
     */
    toggleFilterDropdown() {
        const dropdown = document.getElementById('calendarFilterDropdown');
        if (!dropdown) return;
        
        const isVisible = dropdown.style.display !== 'none';
        
        if (isVisible) {
            dropdown.style.display = 'none';
        } else {
            // 显示下拉菜单
            dropdown.style.display = 'block';
            
            // 定位到筛选按钮下方
            const filterButton = document.querySelector('.fc-calendarFilterButton-button');
            if (filterButton) {
                const rect = filterButton.getBoundingClientRect();
                const calendarRect = document.getElementById('calendar').getBoundingClientRect();
                
                dropdown.style.top = (rect.bottom - calendarRect.top + 5) + 'px';
                dropdown.style.right = (calendarRect.right - rect.right) + 'px';
            }
            
            // 加载当前筛选设置到UI
            this.loadFiltersToUI();
            
            // 更新日程组列表
            this.updateGroupFilterList();
        }
        
        // 点击外部关闭下拉菜单
        if (!isVisible) {
            setTimeout(() => {
                const closeHandler = (e) => {
                    if (!dropdown.contains(e.target) && !e.target.closest('.fc-calendarFilterButton-button')) {
                        dropdown.style.display = 'none';
                        document.removeEventListener('click', closeHandler);
                    }
                };
                document.addEventListener('click', closeHandler);
            }, 100);
        }
    }
    
    /**
     * 加载当前筛选设置到UI
     */
    loadFiltersToUI() {
        const filters = window.settingsManager?.settings?.calendarFilters;
        if (!filters) return;
        
        // 象限筛选
        document.getElementById('filter-important-urgent').checked = filters.quadrants.importantUrgent;
        document.getElementById('filter-important-not-urgent').checked = filters.quadrants.importantNotUrgent;
        document.getElementById('filter-not-important-urgent').checked = filters.quadrants.notImportantUrgent;
        document.getElementById('filter-not-important-not-urgent').checked = filters.quadrants.notImportantNotUrgent;
        
        // DDL筛选
        document.getElementById('filter-has-ddl').checked = filters.hasDDL;
        document.getElementById('filter-no-ddl').checked = filters.noDDL;
        
        // 重复事件筛选
        document.getElementById('filter-recurring').checked = filters.isRecurring;
        document.getElementById('filter-not-recurring').checked = filters.notRecurring;
        
        // 提醒筛选
        document.getElementById('filter-show-reminders').checked = filters.showReminders;
        
        // 成员筛选（恢复选中状态）
        this.loadMemberFiltersToUI(filters);
    }
    
    /**
     * 恢复成员筛选状态到UI
     */
    loadMemberFiltersToUI(filters) {
        const memberFilterList = document.getElementById('memberFilterList');
        if (!memberFilterList || memberFilterList.parentElement.style.display === 'none') {
            return;  // 成员筛选区域不可见，跳过
        }
        
        const selectedMembers = filters?.members || [];
        const allCheckboxes = memberFilterList.querySelectorAll('input[type="checkbox"]');
        
        if (selectedMembers.length === 0) {
            // 如果没有保存的筛选，默认全选
            allCheckboxes.forEach(cb => cb.checked = true);
        } else {
            // 恢复保存的筛选状态
            allCheckboxes.forEach(cb => {
                const userId = parseInt(cb.value);
                cb.checked = selectedMembers.includes(userId);
            });
        }
        
        console.log('[EventManager] 恢复成员筛选状态:', selectedMembers);
    }
    
    /**
     * 更新日程组筛选列表
     */
    updateGroupFilterList() {
        const groupList = document.getElementById('groupFilterList');
        if (!groupList || !this.groups) return;
        
        const filters = window.settingsManager?.settings?.calendarFilters;
        const selectedGroups = filters?.groups || [];
        
        groupList.innerHTML = '';
        
        // 添加"无日程组"选项
        const noneCheckbox = document.createElement('div');
        noneCheckbox.className = 'form-check';
        noneCheckbox.innerHTML = `
            <input class="form-check-input group-filter-checkbox" 
                   type="checkbox" 
                   id="filter-group-none" 
                   value="none"
                   ${selectedGroups.length === 0 || selectedGroups.includes('none') ? 'checked' : ''}>
            <label class="form-check-label" for="filter-group-none">
                📋 其他
            </label>
        `;
        groupList.appendChild(noneCheckbox);
        
        // 添加所有日程组
        this.groups.forEach(group => {
            const checkbox = document.createElement('div');
            checkbox.className = 'form-check';
            checkbox.innerHTML = `
                <input class="form-check-input group-filter-checkbox" 
                       type="checkbox" 
                       id="filter-group-${group.id}" 
                       value="${group.id}"
                       ${selectedGroups.length === 0 || selectedGroups.includes(group.id) ? 'checked' : ''}>
                <label class="form-check-label" for="filter-group-${group.id}">
                    <span class="group-color-dot" style="background-color: ${group.color}"></span>
                    ${group.name}
                </label>
            `;
            groupList.appendChild(checkbox);
        });
    }
    
    /**
     * 从UI应用筛选设置
     */
    applyFiltersFromUI() {
        // 读取UI中的筛选设置
        const filters = {
            quadrants: {
                importantUrgent: document.getElementById('filter-important-urgent').checked,
                importantNotUrgent: document.getElementById('filter-important-not-urgent').checked,
                notImportantUrgent: document.getElementById('filter-not-important-urgent').checked,
                notImportantNotUrgent: document.getElementById('filter-not-important-not-urgent').checked
            },
            hasDDL: document.getElementById('filter-has-ddl').checked,
            noDDL: document.getElementById('filter-no-ddl').checked,
            isRecurring: document.getElementById('filter-recurring').checked,
            notRecurring: document.getElementById('filter-not-recurring').checked,
            showReminders: document.getElementById('filter-show-reminders').checked,
            groups: []
        };
        
        // 收集选中的日程组
        const groupCheckboxes = document.querySelectorAll('.group-filter-checkbox:checked');
        groupCheckboxes.forEach(cb => {
            filters.groups.push(cb.value);
        });
        
        // 如果所有日程组都选中（包括"无日程组"），则清空数组（表示显示所有）
        // 总数 = 日程组数量 + 1（"无日程组"选项）
        if (groupCheckboxes.length === this.groups.length + 1) {
            filters.groups = [];
        }
        
        // 收集选中的成员（仅在群组视图下）
        filters.members = [];
        const memberFilterList = document.getElementById('memberFilterList');
        if (memberFilterList && memberFilterList.parentElement.style.display !== 'none') {
            const memberCheckboxes = memberFilterList.querySelectorAll('input[type="checkbox"]:checked');
            memberCheckboxes.forEach(cb => {
                filters.members.push(parseInt(cb.value));
            });
            
            // 如果所有成员都选中，则清空数组（表示显示所有）
            const allMemberCheckboxes = memberFilterList.querySelectorAll('input[type="checkbox"]');
            if (memberCheckboxes.length === allMemberCheckboxes.length) {
                filters.members = [];
            }
            
            console.log('[EventManager] 应用成员筛选:', {
                selectedCount: memberCheckboxes.length,
                totalCount: allMemberCheckboxes.length,
                memberIds: filters.members
            });
        }
        
        console.log('[EventManager] 保存筛选配置:', filters);
        
        // 更新设置
        window.settingsManager.updateCategorySettings('calendarFilters', filters);
        
        // 刷新日历
        this.refreshCalendar();
        
        // 隐藏下拉菜单
        document.getElementById('calendarFilterDropdown').style.display = 'none';
    }
    
    /**
     * 重置筛选为默认值
     */
    resetFilters() {
        const defaultFilters = {
            quadrants: {
                importantUrgent: true,
                importantNotUrgent: true,
                notImportantUrgent: true,
                notImportantNotUrgent: true
            },
            hasDDL: true,
            noDDL: true,
            isRecurring: true,
            notRecurring: true,
            showReminders: true,
            groups: [],
            members: []
        };
        
        // 更新设置
        window.settingsManager.updateCategorySettings('calendarFilters', defaultFilters);
        
        // 刷新UI
        this.loadFiltersToUI();
        this.updateGroupFilterList();
        
        // 重置成员筛选（全选）
        const memberCheckboxes = document.querySelectorAll('#memberFilterList input[type="checkbox"]');
        memberCheckboxes.forEach(cb => cb.checked = true);
        
        // 刷新日历
        this.refreshCalendar();
    }

    /**
     * 自定义事件外观（成员颜色）
     * @param {Object} info - FullCalendar 事件信息对象
     */
    customizeEventAppearance(info) {
        const event = info.event;
        const el = info.el;
        const view = info.view;
        
        // 提醒事件不做处理
        if (event.extendedProps.isReminder) {
            return;
        }
        
        // 在"我的日程"视图中，为被分享的日程添加彩色小圆点
        if (!event.extendedProps.isGroupView) {
            this.addSharedGroupDots(el, event, view.type);
        }
        
        // 只在群组视图中应用成员颜色
        if (!event.extendedProps.isGroupView) {
            return;
        }
        
        // 获取当前视图类型
        const viewType = view.type;
        
        // 获取事件的扩展属性
        const isMyEvent = event.extendedProps.isMyEvent || false;  // 使用已设置的 isMyEvent
        const ownerColor = event.extendedProps.owner_color;
        // 优先从 extendedProps 获取 groupColor，其次从 backgroundColor 获取
        const groupColor = event.extendedProps.groupColor || event.backgroundColor;
        
        // 调试信息
        console.log('[EventManager] 自定义事件外观:', {
            title: event.title,
            isMyEvent: isMyEvent,
            ownerColor: ownerColor,
            groupColor: groupColor,
            backgroundColor: event.backgroundColor,
            editable: event.editable
        });
        
        // 根据视图类型应用不同的样式
        if (viewType === 'timeGridWeek' || viewType === 'timeGridDay' || viewType === 'timeGridTwoDay') {
            // 周视图/日视图/2日视图：使用分色或斜杠线
            this.applyTimeGridStyle(el, isMyEvent, groupColor, ownerColor);
        } else if (viewType === 'dayGridMonth') {
            // 月视图：添加颜色标记
            this.applyMonthViewStyle(el, isMyEvent, groupColor, ownerColor);
        } else if (viewType === 'listWeek') {
            // 列表视图：添加颜色标记
            this.applyListViewStyle(el, isMyEvent, groupColor, ownerColor);
        }
    }

    /**
     * 周视图/日视图样式
     */
    applyTimeGridStyle(el, isMyEvent, groupColor, ownerColor) {
        console.log('[applyTimeGridStyle] 调用参数:', {
            isMyEvent,
            groupColor,
            ownerColor,
            element: el.className
        });
        
        if (isMyEvent) {
            // 自己的日程：左右分色
            if (ownerColor && groupColor && groupColor !== ownerColor) {
                // 使用 background 属性（包含所有背景相关属性）
                const gradient = `linear-gradient(90deg, ${groupColor} 50%, ${ownerColor} 50%)`;
                
                // 先清除所有背景相关样式
                el.style.removeProperty('background-color');
                el.style.removeProperty('background-image');
                
                // 使用 background 简写属性并强制覆盖
                el.style.setProperty('background', gradient, 'important');
                el.style.setProperty('border-color', groupColor, 'important');
                
                console.log('[applyTimeGridStyle] ✅ 应用自己日程左右分色:', {
                    gradient,
                    actualBg: el.style.background
                });
            } else {
                console.log('[applyTimeGridStyle] ⚠️ 颜色相同或无成员颜色，保持原样');
            }
        } else {
            // 他人的日程：成员颜色底色 + 半透明白色斜杠滤镜
            if (ownerColor) {
                // 先设置纯色背景
                el.style.setProperty('background-color', ownerColor, 'important');
                
                // 再在上面叠加半透明白色斜杠图案
                const stripePattern = `repeating-linear-gradient(
                    45deg,
                    transparent,
                    transparent 5px,
                    rgba(255, 255, 255, 0.4) 5px,
                    rgba(255, 255, 255, 0.4) 10px
                )`;
                
                el.style.setProperty('background-image', stripePattern, 'important');
                el.style.setProperty('border-color', ownerColor, 'important');
                
                // 添加特殊类标识
                el.classList.add('readonly-event');
                
                console.log('[applyTimeGridStyle] ✅ 应用他人日程样式:', {
                    bgColor: ownerColor,
                    actualBgColor: el.style.backgroundColor,
                    actualBgImage: el.style.backgroundImage
                });
            }
        }
    }

    /**
     * 月视图样式
     */
    applyMonthViewStyle(el, isMyEvent, groupColor, ownerColor) {
        if (!isMyEvent && ownerColor) {
            // 他人的日程：使用成员颜色，添加图标标识
            el.style.setProperty('background-color', ownerColor, 'important');
            el.style.setProperty('border-color', ownerColor, 'important');
            
            // 在标题前添加一个小图标
            const titleEl = el.querySelector('.fc-event-title');
            if (titleEl && !titleEl.querySelector('.owner-indicator')) {
                const indicator = document.createElement('span');
                indicator.className = 'owner-indicator';
                indicator.innerHTML = '👤 ';
                indicator.style.opacity = '0.7';
                titleEl.insertBefore(indicator, titleEl.firstChild);
            }
        } else if (isMyEvent && ownerColor && groupColor !== ownerColor) {
            // 自己的日程：显示双色边框
            el.style.setProperty('border-left', `4px solid ${groupColor}`, 'important');
            el.style.setProperty('border-right', `4px solid ${ownerColor}`, 'important');
            el.style.setProperty('background-color', groupColor, 'important');
        }
    }

    /**
     * 列表视图样式
     */
    applyListViewStyle(el, isMyEvent, groupColor, ownerColor) {
        // 在列表视图中添加颜色圆点
        if (!el.querySelector('.event-color-dot')) {
            const dotContainer = document.createElement('span');
            dotContainer.className = 'event-color-dots';
            dotContainer.style.marginRight = '8px';
            
            if (isMyEvent && ownerColor && groupColor !== ownerColor) {
                // 自己的日程：显示两个圆点
                dotContainer.innerHTML = `
                    <span class="event-color-dot" style="background-color: ${groupColor}; display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 2px;"></span>
                    <span class="event-color-dot" style="background-color: ${ownerColor}; display: inline-block; width: 10px; height: 10px; border-radius: 50%;"></span>
                `;
            } else if (!isMyEvent && ownerColor) {
                // 他人的日程：显示成员颜色圆点 + 图标
                dotContainer.innerHTML = `
                    <span class="event-color-dot" style="background-color: ${ownerColor}; display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px;"></span>
                    <span style="opacity: 0.7;">👤</span>
                `;
            } else {
                // 只有日程组颜色
                dotContainer.innerHTML = `
                    <span class="event-color-dot" style="background-color: ${groupColor}; display: inline-block; width: 10px; height: 10px; border-radius: 50%;"></span>
                `;
            }
            
            // 插入到事件标题前
            const titleEl = el.querySelector('.fc-list-event-title');
            if (titleEl) {
                titleEl.insertBefore(dotContainer, titleEl.firstChild);
            }
        }
    }

    /**
     * 为被分享的日程添加彩色小圆点
     * @param {HTMLElement} el - 事件元素
     * @param {Object} event - 事件对象
     * @param {string} viewType - 视图类型
     */
    addSharedGroupDots(el, event, viewType) {
        // 获取分享群组信息
        const sharedGroups = event.extendedProps?.shared_groups || [];
        
        if (sharedGroups.length === 0) {
            return;  // 没有分享，不添加圆点
        }
        
        console.log('[addSharedGroupDots] 事件被分享到群组:', {
            title: event.title,
            groups: sharedGroups
        });
        
        // 创建圆点容器
        const dotsContainer = document.createElement('div');
        dotsContainer.className = 'shared-group-dots';
        dotsContainer.style.cssText = 'position: absolute; top: 2px; right: 2px; display: flex; gap: 2px; z-index: 10;';
        
        // 为每个群组添加一个彩色圆点
        sharedGroups.forEach(group => {
            const dot = document.createElement('span');
            dot.className = 'shared-group-dot';
            dot.style.cssText = `
                display: inline-block;
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background-color: ${group.share_group_color || '#3498db'};
                box-shadow: 0 0 2px rgba(0,0,0,0.3);
            `;
            dot.title = `已分享到: ${group.share_group_name}`;
            dotsContainer.appendChild(dot);
        });
        
        // 根据视图类型选择插入位置
        if (viewType === 'timeGridWeek' || viewType === 'timeGridDay' || viewType === 'timeGridTwoDay') {
            // 周视图/日视图：添加到事件元素右上角
            // ⚠️ 不要修改 el 的 position 属性，避免影响 FullCalendar 的高度计算
            // FullCalendar 的时间轴事件已经是定位容器，直接添加绝对定位的圆点即可
            el.appendChild(dotsContainer);
        } else if (viewType === 'dayGridMonth') {
            // 月视图：添加到事件元素右上角
            // FullCalendar 的月视图事件也是定位容器
            el.appendChild(dotsContainer);
        } else if (viewType === 'listWeek') {
            // 列表视图：添加到标题前
            dotsContainer.style.position = 'static';
            dotsContainer.style.display = 'inline-flex';
            dotsContainer.style.marginRight = '6px';
            dotsContainer.style.verticalAlign = 'middle';
            
            const titleEl = el.querySelector('.fc-list-event-title');
            if (titleEl) {
                titleEl.insertBefore(dotsContainer, titleEl.firstChild);
            }
        }
    }
}

// 事件管理器类已定义，实例将在HTML中创建

