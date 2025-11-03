/**
 * 用户界面设置管理器
 * 负责保存和恢复用户的界面状态
 */
class SettingsManager {
    constructor() {
        this.debounceTimers = new Map();
        this.settings = {
            todoFilters: {
                statusFilter: '', // 空字符串表示显示所有未完成的
                sortBy: 'priority'
            },
            reminderFilters: {
                timeRange: 'today',
                statusFilter: 'active'
            },
            calendarFilters: {
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
                groups: [], // 空数组表示显示所有分组
                showReminders: true
            },
            calendarView: {
                viewType: 'timeGridWeek',
                currentDate: new Date().toISOString().split('T')[0]
            },
            panelLayout: {
                leftPanelWidth: 20,
                centerPanelWidth: 50,
                rightPanelWidth: 30
            }
        };
        
        this.init();
    }

    // 初始化设置管理器
    async init() {
        await this.loadSettings();
        this.setupAutoSave();
        // console.log('设置管理器已初始化，当前设置:', this.settings);
    }

    // 从localStorage和服务器加载设置
    async loadSettings() {
        try {
            // 优先从localStorage加载（更快）
            const localSettings = localStorage.getItem('userInterfaceSettings');
            if (localSettings) {
                const parsed = JSON.parse(localSettings);
                this.settings = { ...this.settings, ...parsed };
                // console.log('从localStorage加载设置:', parsed);
            }

            // 异步从服务器加载最新设置
            const response = await fetch('/get_calendar/user_settings/');
            if (response.ok) {
                const serverSettings = await response.json();
                if (serverSettings) {
                    this.settings = { ...this.settings, ...serverSettings };
                    // 同步到localStorage
                    localStorage.setItem('userInterfaceSettings', JSON.stringify(this.settings));
                    // console.log('从服务器同步设置:', serverSettings);
                }
            }
        } catch (error) {
            console.warn('加载设置失败，使用默认设置:', error);
        }
    }

    // 设置自动保存机制
    setupAutoSave() {
        let lastSaveTime = 0;
        const minSaveInterval = 1000; // 最小保存间隔1秒
        
        const throttledSave = () => {
            const now = Date.now();
            if (now - lastSaveTime >= minSaveInterval) {
                lastSaveTime = now;
                this.saveSettingsImmediate();
            }
        };
        
        // 监听页面关闭时保存设置
        window.addEventListener('beforeunload', () => {
            this.saveSettingsImmediate();
        });

        // 监听页面隐藏时保存设置（切换标签页等）
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                throttledSave();
            }
        });
    }

    // 获取设置值
    getSetting(category, key) {
        return this.settings[category]?.[key];
    }

    // 获取整个分类的设置
    getCategorySettings(category) {
        return this.settings[category] || {};
    }

    // 更新设置值
    updateSetting(category, key, value) {
        if (!this.settings[category]) {
            this.settings[category] = {};
        }
        this.settings[category][key] = value;
        
        // 立即保存到localStorage
        localStorage.setItem('userInterfaceSettings', JSON.stringify(this.settings));
        
        // 防抖保存到服务器
        this.debouncedSaveToServer();
        
        // console.log(`设置已更新: ${category}.${key} = ${value}`, this.settings);
    }

    // 批量更新设置
    updateCategorySettings(category, settings) {
        this.settings[category] = { ...this.settings[category], ...settings };
        
        // 立即保存到localStorage
        localStorage.setItem('userInterfaceSettings', JSON.stringify(this.settings));
        
        // 防抖保存到服务器
        this.debouncedSaveToServer();
        
        // console.log(`批量更新设置: ${category}`, settings, '完整设置:', this.settings);
    }

    // 防抖保存到服务器
    debouncedSaveToServer() {
        const timerId = 'serverSave';
        
        // 清除之前的定时器
        if (this.debounceTimers.has(timerId)) {
            clearTimeout(this.debounceTimers.get(timerId));
        }
        
        // 设置新的定时器
        const timer = setTimeout(() => {
            this.saveToServer();
            this.debounceTimers.delete(timerId);
        }, 1000); // 1秒后保存
        
        this.debounceTimers.set(timerId, timer);
    }

    // 保存设置到服务器
    async saveToServer() {
        try {
            // console.log('开始保存设置到服务器:', this.settings);
            // console.log('CSRF Token:', this.getCSRFToken());
            const response = await fetch('/get_calendar/change_view/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify(this.settings)
            });
            
            if (response.ok) {
                const result = await response.json();
                // console.log('设置已保存到服务器:', result);
            } else {
                const errorText = await response.text();
                console.warn('保存设置到服务器失败:', response.status, response.statusText, errorText);
            }
        } catch (error) {
            console.error('保存设置到服务器时出错:', error);
        }
    }

    // 立即保存设置
    saveSettingsImmediate() {
        // 立即保存到localStorage
        localStorage.setItem('userInterfaceSettings', JSON.stringify(this.settings));
        
        // 取消防抖，立即保存到服务器
        this.debounceTimers.forEach(timer => clearTimeout(timer));
        this.debounceTimers.clear();
        this.saveToServer();
    }

    // 获取CSRF token
    getCSRFToken() {
        // 优先从Django模板变量获取
        if (window.CSRF_TOKEN) {
            return window.CSRF_TOKEN;
        }
        
        // 从Cookie获取
        const name = 'csrftoken';
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        
        // 从meta标签获取
        if (!cookieValue) {
            const csrfMeta = document.querySelector('[name=csrfmiddlewaretoken]');
            if (csrfMeta) {
                cookieValue = csrfMeta.value;
            }
        }
        
        return cookieValue || '';
    }

    // 应用设置到界面
    applySettings() {
        // console.log('开始应用设置到界面:', this.settings);
        
        // 应用待办筛选设置
        this.applyTodoFilters();
        
        // 应用提醒筛选设置
        this.applyReminderFilters();
        
        // 应用日历视图设置
        this.applyCalendarView();
        
        // 应用面板布局设置
        this.applyPanelLayout();
        
        // console.log('设置应用完成');
    }

    // 应用待办筛选设置
    applyTodoFilters() {
        const filters = this.settings.todoFilters;
        if (window.todoManager) {
            if (filters.statusFilter !== undefined) {
                const statusSelect = document.querySelector('#todoStatusFilter');
                if (statusSelect) statusSelect.value = filters.statusFilter;
            }
            if (filters.sortBy) {
                const sortSelect = document.querySelector('#todoSortBy');
                if (sortSelect) sortSelect.value = filters.sortBy;
            }
            // 触发筛选
            setTimeout(() => window.todoManager?.applyFilters(), 100);
        }
    }

    // 应用提醒筛选设置
    applyReminderFilters() {
        // console.log('=== 开始应用提醒筛选设置 ===');
        // console.log('当前完整设置对象:', this.settings);
        // console.log('提醒筛选设置:', this.settings.reminderFilters);
        
        const filters = this.settings.reminderFilters;
        // console.log('应用提醒筛选设置:', filters);
        // console.log('filters 类型:', typeof filters);
        // console.log('filters 是否为undefined:', filters === undefined);
        // console.log('filters 是否为null:', filters === null);
        // console.log('filters 是否为空对象:', filters && Object.keys(filters).length === 0);
        
        if (!filters) {
            // console.log('警告：没有找到 reminderFilters 设置');
            return;
        }
        
        if (window.reminderManager) {
            // console.log('找到 reminderManager，开始设置DOM元素');
            
            // 时间范围筛选
            if (filters.timeRange) {
                const timeRangeSelect = document.querySelector('#reminderTimeRange');
                if (timeRangeSelect) {
                    // console.log('设置时间范围从', timeRangeSelect.value, '到', filters.timeRange);
                    timeRangeSelect.value = filters.timeRange;
                    // console.log('设置时间范围完成，当前值:', timeRangeSelect.value);
                } else {
                    console.warn('未找到 #reminderTimeRange 元素');
                }
            }
            
            // 状态筛选
            if (filters.status) {
                const statusSelect = document.querySelector('#reminderStatusFilter');
                if (statusSelect) {
                    statusSelect.value = filters.status;
                    // console.log('设置状态筛选为:', filters.status);
                }
            }
            
            // 优先级筛选
            if (filters.priority) {
                const prioritySelect = document.querySelector('#reminderPriorityFilter');
                if (prioritySelect) {
                    prioritySelect.value = filters.priority;
                    // console.log('设置优先级筛选为:', filters.priority);
                }
            }
            
            // 类型筛选
            if (filters.type) {
                const typeSelect = document.querySelector('#reminderTypeFilter');
                if (typeSelect) {
                    typeSelect.value = filters.type;
                    // console.log('设置类型筛选为:', filters.type);
                }
            }
            
            // 触发筛选
            setTimeout(() => {
                // console.log('=== 准备触发筛选器应用 ===');
                // console.log('使用的筛选设置:', filters);
                // console.log('filters 是否为空:', !filters);
                // console.log('filters 的值:', JSON.stringify(filters));
                // console.log('window.reminderManager 状态:', !!window.reminderManager);
                if (window.reminderManager && filters) {
                    // console.log('调用 reminderManager.applyFilters() 并传入参数');
                    window.reminderManager.applyFilters(filters);
                    // console.log('reminderManager.applyFilters() 调用完成');
                    // console.log('✅ 提醒筛选器初始化成功');
                } else {
                    console.error('无法应用筛选:', {
                        hasReminderManager: !!window.reminderManager,
                        hasFilters: !!filters,
                        filters: filters
                    });
                }
                // console.log('=== 筛选器应用触发完成 ===');
            }, 100);
        } else {
            console.error('window.reminderManager 不存在，无法应用筛选设置');
        }
        
        // console.log('=== 应用提醒筛选设置完成 ===');
    }

    // 应用日历视图设置
    applyCalendarView() {
        // ⚠️ 注意：initialView 和 initialDate 已在 event-manager.js 的 initCalendar() 中处理
        // 这里不再需要重复应用，避免二次设置导致的问题
        
        const calendarSettings = this.settings.calendarView;
        console.log('日历视图已在初始化时应用:', calendarSettings);
        
        // 如果需要在日历初始化后做额外处理,可以在这里添加
        // 但通常不需要,因为 initialView 和 initialDate 已经正确设置
    }

    // 应用面板布局设置
    applyPanelLayout() {
        const layout = this.settings.panelLayout;
        if (window.panelResizer) {
            window.panelResizer.setLayout(
                layout.leftPanelWidth,
                layout.centerPanelWidth,
                layout.rightPanelWidth
            );
        }
    }

    // 监听待办筛选变化
    onTodoFilterChange(filterType, value) {
        this.updateSetting('todoFilters', filterType, value);
    }

    // 监听提醒筛选变化
    onReminderFilterChange(filterType, value) {
        this.updateSetting('reminderFilters', filterType, value);
    }

    // 监听日历筛选变化
    onCalendarFilterChange(filterType, value) {
        this.updateSetting('calendarFilters', filterType, value);
        // 筛选变化时立即刷新日历
        if (window.eventManager) {
            window.eventManager.refreshCalendar();
        }
    }

    // 应用日历筛选设置
    applyCalendarFilters() {
        const filters = this.settings.calendarFilters;
        if (!filters) {
            console.warn('警告：没有找到 calendarFilters 设置');
            return;
        }
        
        console.log('应用日历筛选设置:', filters);
        // 筛选会在fetchEvents时自动应用，这里不需要额外操作
    }

    // 监听日历视图变化
    onCalendarViewChange(viewType, currentDate) {
        this.updateCategorySettings('calendarView', {
            viewType: viewType,
            currentDate: currentDate
        });
    }

    // 监听面板布局变化
    onPanelLayoutChange(leftWidth, centerWidth, rightWidth) {
        this.updateCategorySettings('panelLayout', {
            leftPanelWidth: leftWidth,
            centerPanelWidth: centerWidth,
            rightPanelWidth: rightWidth
        });
    }
}

// 创建全局设置管理器实例
window.settingsManager = new SettingsManager();
