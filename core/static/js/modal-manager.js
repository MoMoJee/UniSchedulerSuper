// 模态框管理模块
class ModalManager {
    constructor() {
        this.currentEventId = null;
        this.currentEvent = null; // 存储当前编辑的事件完整数据
        this.currentTodoId = null;
        this.currentReminderId = null;
        this.forceUntilRequired = false; // 强制要求设置截止时间标记
        this.isSubmittingEvent = false; // 防重复提交标志
        this.init();
    }

    // 初始化
    init() {
        this.setupEventListeners();
        this.setupFormValidation();
    }

    // 设置事件监听器
    setupEventListeners() {
        // 关闭模态框事件
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('modal')) {
                this.closeAllModals();
            }

            if (e.target.classList.contains('close')) {
                this.closeAllModals();
            }
        });

        // ESC键关闭模态框
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeAllModals();
            }
        });

        // 表单提交事件
        this.setupFormSubmitListeners();
    }


    // 设置表单提交监听器
    setupFormSubmitListeners() {
        // 创建事件表单
        const createEventForm = document.getElementById('createEventForm');
        if (createEventForm) {
            createEventForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.handleCreateEvent();
            });
        }

        // 创建待办表单
        const createTodoForm = document.getElementById('createTodoForm');
        if (createTodoForm) {
            createTodoForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.handleCreateTodo();
            });
        }

        // 创建提醒表单
        const createReminderForm = document.getElementById('createReminderForm');
        if (createReminderForm) {
            createReminderForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.handleCreateReminder();
            });
        }
    }

    // 设置表单验证
    setupFormValidation() {
        // 基本的表单验证
        document.addEventListener('input', (e) => {
            if (e.target.classList.contains('form-input')) {
                this.validateField(e.target);
            }
        });
    }

    // 验证字段
    validateField(field) {
        const value = field.value.trim();
        const isRequired = field.hasAttribute('required');

        if (isRequired && !value) {
            field.classList.add('error');
            return false;
        } else {
            field.classList.remove('error');
            return true;
        }
    }

    // 显示模态框的通用方法
    showModal(modalId) {
        // 检查是否已经显示了同一个模态框
        const modal = document.getElementById(modalId);
        const isAlreadyShowing = modal && modal.classList.contains('show');
        
        if (!isAlreadyShowing) {
            // 只关闭其他模态框，不调用 cleanupCustomControls
            document.querySelectorAll('.custom-modal').forEach(m => {
                if (m.id !== modalId && m.classList.contains('show')) {
                    m.classList.remove('show');
                    m.style.display = 'none';
                }
            });
        }
        
        if (modal) {
            // 直接显示并添加show类
            modal.style.display = 'flex';

            // 使用requestAnimationFrame确保样式更新后再添加show类
            requestAnimationFrame(() => {
                modal.classList.add('show');
            });

            // 防止页面滚动
            document.body.style.overflow = 'hidden';
        }
    }

    // 关闭所有模态框
    closeAllModals() {
        // 清理自定义控件
        this.cleanupCustomControls();
        
        // 清理事件编辑状态
        if (window.eventManager) {
            window.eventManager.pendingBulkEdit = null;
            window.eventManager.currentEditMode = null;
            window.eventManager.isInEditMode = false;
        }
        
        // 清理编辑模式提示
        const hintElements = document.querySelectorAll('.edit-mode-hint');
        hintElements.forEach(el => el.remove());
        
        const modals = document.querySelectorAll('.modal');
        modals.forEach(modal => {
            if (modal.classList.contains('show')) {
                // 开始隐藏动画
                modal.style.opacity = '0';
                modal.classList.remove('show');

                // 动画结束后隐藏元素
                setTimeout(() => {
                    modal.style.display = 'none';
                    modal.style.removeProperty('opacity');
                    modal.style.removeProperty('align-items');
                    modal.style.removeProperty('justify-content');
                }, 300); // 与CSS动画时间一致
            } else {
                // 确保完全隐藏
                modal.style.display = 'none';
                modal.style.removeProperty('opacity');
            }
        });

        // 恢复页面滚动
        document.body.style.overflow = 'auto';

        // 重新启用日历交互
        this.reEnableCalendarInteraction();
        
        // 清除待处理的批量编辑信息（在用户取消时）
        this.clearPendingBulkEdit();

        this.resetCurrentIds();
    }

    // 清除待处理的批量编辑信息
    clearPendingBulkEdit() {
        if (window.reminderManager && window.reminderManager.pendingBulkEdit) {
            window.reminderManager.pendingBulkEdit = null;
            console.log('Cleared pendingBulkEdit');
        }
    }

    // 清除待处理的批量编辑信息（不输出日志）
    clearPendingBulkEditWithoutLog() {
        if (window.reminderManager) {
            window.reminderManager.pendingBulkEdit = null;
        }
    }

    // 清理自定义控件
    cleanupCustomControls() {
        // 清理自定义日期时间控件
        const customDateTimeGroup = document.getElementById('customDateTimeGroup');
        if (customDateTimeGroup) {
            customDateTimeGroup.remove();
            console.log('Cleaned up custom date-time group');
        }

        // 清理"更改重复规则"按钮
        const changeRuleButtonContainer = document.getElementById('changeRuleButtonContainer');
        if (changeRuleButtonContainer) {
            changeRuleButtonContainer.remove();
            console.log('Cleaned up change rule button');
        }

        // 恢复原始的日期时间输入框显示
        const originalDateTimeField = document.getElementById('reminderTriggerTime');
        if (originalDateTimeField) {
            originalDateTimeField.style.display = '';
            console.log('Restored original date-time field');
        }
        
        // 清除完整编辑模式标记
        const editModal = document.getElementById('editReminderModal');
        if (editModal) {
            editModal.removeAttribute('data-full-edit');
        }
    }

    // 重新启用日历交互
    reEnableCalendarInteraction() {
        // 确保日历容器没有被意外禁用
        const calendarEl = document.getElementById('calendar');
        if (calendarEl) {
            calendarEl.style.pointerEvents = 'auto';
        }

        // 重新设置FullCalendar的选择功能
        if (window.eventManager && window.eventManager.calendar) {
            try {
                // 重新启用选择功能
                window.eventManager.calendar.setOption('selectable', true);
                window.eventManager.calendar.setOption('selectMirror', true);
                console.log('重新启用日历交互功能');
            } catch (error) {
                console.error('重新启用日历交互时出错:', error);
            }
        }
    }

    // 重置当前ID
    resetCurrentIds() {
        this.currentEventId = null;
        this.currentEvent = null;
        this.currentTodoId = null;
        this.currentReminderId = null;
    }

    // === 事件相关模态框 ===

    // 打开创建事件模态框
    openCreateEventModal(startStr, endStr) {
        const modal = document.getElementById('createEventModal');

        // 如果没有提供时间参数，设置默认时间（当前时间 + 1小时）
        if (!startStr || !endStr) {
            const now = new Date();
            const start = new Date(now.getTime() + 60 * 60 * 1000); // 1小时后
            const end = new Date(start.getTime() + 60 * 60 * 1000); // 再1小时后

            // 直接使用本地时间格式，不需要转换
            startStr = this.toLocalTime(start.toISOString());
            endStr = this.toLocalTime(end.toISOString());
        } else {
            // 对于提供的时间参数，进行转换
            startStr = this.toLocalTime(startStr);
            endStr = this.toLocalTime(endStr);
        }

        // 设置时间
        document.getElementById('newEventStart').value = startStr;
        document.getElementById('newEventEnd').value = endStr;
        document.getElementById('creatEventDdl').value = endStr;

        // 清除表单
        this.clearEventForm();

        // 填充日程组选项
        this.populateGroupSelect('newEventGroupId');

        this.showModal('createEventModal');
    }

    // 打开编辑事件模态框
    openEditEventModal(event) {
        console.log('Opening edit event modal for:', event);
        
        // 清理之前的编辑状态
        if (window.eventManager) {
            // 清理编辑模式标志（但保留pendingBulkEdit以供后续使用）
            window.eventManager.currentEditMode = null;
            window.eventManager.isInEditMode = false;
            
            // 清理编辑模式提示
            const existingHints = document.querySelectorAll('.edit-mode-hint');
            existingHints.forEach(el => el.remove());
        }
        
        const modal = document.getElementById('editEventModal');
        this.currentEventId = event.id;
        this.currentEvent = event; // 存储完整的事件数据

        // 填充表单数据
        document.getElementById('eventId').value = event.id;
        document.getElementById('eventTitle').value = event.title;
        document.getElementById('eventStart').value = this.toLocalTime(event.start);
        document.getElementById('eventEnd').value = this.toLocalTime(event.end);
        document.getElementById('eventDescription').value = event.extendedProps.description || '';
        document.getElementById('eventDdl').value = event.extendedProps.ddl ? this.toLocalTime(event.extendedProps.ddl) : '';

        // 设置重要性紧急性
        this.setImportanceUrgency(
            event.extendedProps.importance,
            event.extendedProps.urgency,
            'edit'
        );

        // 填充日程组选项
        this.populateGroupSelect('eventGroupId', event.extendedProps.groupID);

        // 处理重复事件信息
        this.setupRecurringEventInfo(event);
        
        // 强制确保editEventRecurringInfo隐藏（防止其他代码意外显示）
        const editEventRecurringInfo = document.getElementById('editEventRecurringInfo');
        if (editEventRecurringInfo) {
            editEventRecurringInfo.style.display = 'none';
            console.log('Force hiding editEventRecurringInfo in openEditEventModal');
        }

        // 解析并填充RRule信息
        if (window.rruleManager && event.extendedProps.rrule) {
            console.log('=== About to call rruleManager.parseRRuleToUI for Events ===');
            console.log('event.extendedProps.rrule:', event.extendedProps.rrule);
            
            try {
                window.rruleManager.parseRRuleToUI(event.extendedProps.rrule, 'edit');
                console.log('rruleManager.parseRRuleToUI call completed');
            } catch (error) {
                console.error('Error calling rruleManager.parseRRuleToUI:', error);
                // 备用方案：手动解析Events的RRule
                this.manualParseEventRrule(event.extendedProps.rrule, 'edit');
            }
        }

        // 如果是通过批量编辑打开的，应用编辑范围字段控制
        if (window.eventManager && window.eventManager.pendingBulkEdit) {
            setTimeout(() => {
                // 标记已经进行了RRule解析，避免范围设置干扰
                window.eventManager._rruleParsed = (event.extendedProps.rrule && window.rruleManager);
                console.log('About to call updateEventEditScopeFields, _rruleParsed:', window.eventManager._rruleParsed);
                
                window.eventManager.updateEventEditScopeFields();
                
                // 强制确保editEventRecurringInfo隐藏（批量编辑模式下不应显示）
                const editEventRecurringInfo = document.getElementById('editEventRecurringInfo');
                if (editEventRecurringInfo) {
                    editEventRecurringInfo.style.display = 'none';
                    console.log('Force hiding editEventRecurringInfo in bulk edit mode');
                }
            }, 100);
        }

        this.showModal('editEventModal');
    }

    // 设置重复事件信息显示
    setupRecurringEventInfo(event) {
        const recurringInfo = document.getElementById('editEventRecurringInfo');
        const recurringOptions = document.getElementById('editEventRecurringOptions');
        const eventRepeatCheckbox = document.getElementById('eventIsRecurring');
        
        console.log('setupRecurringEventInfo called with event:', event);
        console.log('Event extendedProps:', event.extendedProps);
        
        // 存储当前事件数据到全局变量，供其他功能使用
        window.currentEventData = event;
        
        // 多种方式判断是否为重复事件（参考Reminder的判断逻辑）
        const eventData = event.extendedProps || {};
        const hasRRule = eventData.rrule && eventData.rrule.includes('FREQ=');
        const isRecurring = eventData.is_recurring;
        const hasSeriesId = eventData.series_id && eventData.series_id.trim() !== '';
        const isDetached = eventData.is_detached; // 检查是否已脱离系列
        
        console.log('Recurring info check:', { hasRRule, isRecurring, hasSeriesId, isDetached });
        
        // 获取重复选项复选框，确保使用正确的ID
        let recurringCheckbox = document.getElementById('eventIsRecurring');
        if (!recurringCheckbox) {
            // 如果不存在，查找其他可能的ID
            recurringCheckbox = document.getElementById('eventRepeat');
        }
        
        // 根据是否是重复事件来控制重复选项的显示
        // 注意：已脱离系列的事件(is_detached=true)不应显示为重复事件
        if (hasRRule && !isDetached) {
            // 这是重复事件，显示重复选项
            console.log('This is a recurring event, showing repeat options');
            
            if (recurringCheckbox) {
                recurringCheckbox.checked = true;
                // 移除任何之前的事件监听器，避免冲突
                recurringCheckbox.removeEventListener('change', this.handleRecurringCheckboxChange);
                // 添加新的事件监听器
                recurringCheckbox.addEventListener('change', this.handleRecurringCheckboxChange.bind(this));
            }
            
            if (recurringOptions) {
                recurringOptions.style.display = 'block';
            }
        } else {
            // 这是单次事件，隐藏重复选项
            console.log('This is a single event, hiding repeat options');
            
            if (recurringCheckbox) {
                recurringCheckbox.checked = false;
                // 移除任何之前的事件监听器，避免冲突
                recurringCheckbox.removeEventListener('change', this.handleRecurringCheckboxChange);
                // 添加新的事件监听器
                recurringCheckbox.addEventListener('change', this.handleRecurringCheckboxChange.bind(this));
            }
            
            if (recurringOptions) {
                recurringOptions.style.display = 'none';
            }
        }
        
        // 强制隐藏模板中的重复事件选择器，因为现在使用独立的对话框
        console.log('Force hiding template recurring event selector');
        if (recurringInfo) {
            recurringInfo.style.display = 'none';
            // 确保即使其他代码尝试显示它，它也保持隐藏
            recurringInfo.setAttribute('data-force-hidden', 'true');
        }
        
        console.log('setupRecurringEventInfo completed');
    }

    // 处理重复事件复选框变化（专门为Events编辑设计）
    handleRecurringCheckboxChange(event) {
        console.log('handleRecurringCheckboxChange called for event editing');
        
        // 检查是否正在进行批量编辑
        if (window.eventManager && window.eventManager.pendingBulkEdit) {
            console.log('In bulk edit mode, handling recurring checkbox change');
            
            const isChecked = event.target.checked;
            const recurringOptions = document.getElementById('eventRecurringOptions');
            
            if (recurringOptions) {
                recurringOptions.style.display = isChecked ? 'block' : 'none';
            }
            
            // 在批量编辑模式下，直接使用rrule-manager来更新选项，不再显示范围选择对话框
            if (window.rruleManager) {
                window.rruleManager.toggleRepeatOptions('edit');
            }
            
            // 对于future和from_time模式，如果取消重复，需要移除"更改重复规则"按钮
            const scope = window.eventManager.pendingBulkEdit.scope;
            if ((scope === 'future' || scope === 'from_time') && !isChecked) {
                window.eventManager.removeChangeRuleButton();
                window.eventManager.addEditModeHint('已取消重复 - 将结束此时间点后的重复');
            } else if ((scope === 'future' || scope === 'from_time') && isChecked) {
                window.eventManager.addChangeRuleButton();
                const modeHint = scope === 'future' ? 
                    '编辑此事件及未来事件 - 可修改基本信息和重复规则' :
                    '编辑指定时间后的事件 - 可修改基本信息和重复规则';
                window.eventManager.addEditModeHint(modeHint);
            }
            
        } else {
            // 如果不是在批量编辑模式中，可能是普通的新建或编辑
            console.log('Not in bulk edit mode, using standard recurring toggle');
            
            // 检查是否已经有活跃的编辑模式标识
            const hasActiveEditMode = window.eventManager && 
                (window.eventManager.currentEditMode || 
                 window.eventManager.isInEditMode || 
                 document.querySelector('.edit-mode-hint'));
            
            // 对于重复事件的直接编辑（点击编辑按钮），应该先显示编辑范围选择对话框
            // 但如果已经在某种编辑模式下，或者事件已脱离系列，则不需要再次弹出对话框
            if (window.currentEventData && window.currentEventData.extendedProps && 
                window.currentEventData.extendedProps.rrule && 
                !window.currentEventData.extendedProps.is_detached && // 已脱离的事件不显示四选一框
                !window.eventManager.pendingBulkEdit && 
                !hasActiveEditMode) {
                
                console.log('This is a recurring event and not in bulk edit, showing scope dialog');
                
                // 重置复选框状态
                event.target.checked = !event.target.checked;
                
                // 显示编辑范围选择对话框
                const seriesId = window.currentEventData.extendedProps.series_id;
                if (window.eventManager && seriesId) {
                    window.eventManager.showEventEditScopeDialog(window.currentEventData.id, seriesId, 'edit');
                }
                
                return;
            }
            
            // 否则使用标准的重复选项切换
            if (window.rruleManager) {
                window.rruleManager.toggleRepeatOptions('edit');
            }
        }
    }

    // 设置编辑范围监听器
    setupEditScopeListeners(seriesId) {
        const scopeRadios = document.querySelectorAll('input[name="editEventScope"]');
        const timeSelect = document.getElementById('editEventTimeSelect');
        const recurringOptions = document.getElementById('editEventRecurringOptions');
        
        scopeRadios.forEach(radio => {
            radio.addEventListener('change', (e) => {
                const selectedScope = e.target.value;
                
                // 控制时间选择器的显示
                if (timeSelect) {
                    timeSelect.style.display = selectedScope === 'from_time' ? 'block' : 'none';
                }
                
                // 控制重复设置选项的显示
                if (recurringOptions) {
                    const shouldShowRRuleOptions = selectedScope === 'all' || selectedScope === 'future' || selectedScope === 'from_time';
                    recurringOptions.style.display = shouldShowRRuleOptions ? 'block' : 'none';
                }
                
                // 根据编辑范围控制字段状态
                this.updateEventEditScopeFields(selectedScope);
            });
        });
        
        // 初始化显示状态
        const checkedScope = document.querySelector('input[name="editEventScope"]:checked');
        if (checkedScope) {
            checkedScope.dispatchEvent(new Event('change'));
        }
    }
    
    // 更新Events编辑字段状态，类似Reminder的编辑模式控制
    updateEventEditScopeFields(scope) {
        const pendingBulkEdit = window.eventManager && window.eventManager.pendingBulkEdit;
        console.log('updateEventEditScopeFields called, scope:', scope, 'pendingBulkEdit:', pendingBulkEdit);

        if (!pendingBulkEdit) {
            // 普通编辑，所有字段都可编辑
            console.log('No pendingBulkEdit, enabling all fields');
            this.enableAllEventEditFields();
            return;
        }

        const editScope = scope || pendingBulkEdit.scope;
        console.log('Edit scope:', editScope);

        const dateTimeField = document.getElementById('eventStart');
        const endTimeField = document.getElementById('eventEnd');
        const titleField = document.getElementById('eventTitle');
        const descriptionField = document.getElementById('eventDescription');

        switch (editScope) {
            case 'this_only':
                console.log('Configuring for single edit mode');
                // 先重置所有字段
                this.enableAllEventEditFields();
                
                // 仅此条事件：禁用重复规则，强制关闭重复开关
                const repeatCheckbox = document.getElementById('eventRepeat');
                const repeatOptions = document.getElementById('editRepeatOptions');

                console.log('repeatCheckbox:', repeatCheckbox);
                console.log('repeatOptions:', repeatOptions);

                if (repeatCheckbox) {
                    repeatCheckbox.checked = false;
                    repeatCheckbox.disabled = true;
                    repeatCheckbox.style.opacity = '0.5';
                    repeatCheckbox.title = '已脱离重复组，不可修改重复规则';
                    console.log('Disabled repeat checkbox');
                }

                if (repeatOptions) {
                    repeatOptions.style.display = 'none';
                    console.log('Hidden repeat options');
                }

                // 添加视觉提示
                const repeatLabel = document.querySelector('label[for="eventRepeat"]');
                if (repeatLabel) {
                    repeatLabel.style.opacity = '0.5';
                    repeatLabel.style.color = '#6c757d';
                    console.log('Styled repeat label');
                }
                break;

            case 'all':
                console.log('Configuring for all events edit mode');
                // 先重置基本字段，但不重置重复相关字段
                this.enableEventBasicFields();
                
                // 所有事件：禁用重复规则，但保持显示，禁用日期部分，只允许修改时间
                const allRepeatCheckbox = document.getElementById('eventRepeat');
                const allRepeatOptions = document.getElementById('editRepeatOptions');

                console.log('allRepeatCheckbox:', allRepeatCheckbox);
                console.log('allRepeatOptions:', allRepeatOptions);

                // 禁用重复开关但保持原状态
                if (allRepeatCheckbox) {
                    allRepeatCheckbox.disabled = true;
                    allRepeatCheckbox.style.opacity = '0.5';
                    allRepeatCheckbox.title = '编辑整个系列时不可修改重复规则';
                    console.log('Disabled repeat checkbox for all mode');
                }

                // 禁用所有重复选项控件但保持显示
                if (allRepeatOptions) {
                    const repeatControls = allRepeatOptions.querySelectorAll('select, input, button');
                    repeatControls.forEach(control => {
                        control.disabled = true;
                        control.style.opacity = '0.5';
                    });
                    console.log('Disabled all repeat controls');
                }

                // 禁用重复标签
                const allRepeatLabel = document.querySelector('label[for="eventRepeat"]');
                if (allRepeatLabel) {
                    allRepeatLabel.style.opacity = '0.5';
                    allRepeatLabel.style.color = '#6c757d';
                }

                // 锁定日期部分，但允许修改时间（开始时间）
                const dateTimeField = document.getElementById('eventStart');
                const endTimeField = document.getElementById('eventEnd');
                if (dateTimeField && !document.getElementById('customEventStartGroup')) {
                    this.createCustomDateTimeControl(dateTimeField, 'customEventStartGroup', 'eventStartTimeOnly');
                }

                // 锁定结束日期部分，但允许修改时间（结束时间）
                if (endTimeField && !document.getElementById('customEventEndGroup')) {
                    this.createCustomDateTimeControl(endTimeField, 'customEventEndGroup', 'eventEndTimeOnly');
                }
                break;

            case 'from_this':
            case 'from_time':
                // 先重置所有字段
                this.enableAllEventEditFields();
                
                // 默认状态：类似"all"模式 - 不能更改重复规则，只能更改时间
                this.configureEventFromThisDefaultMode();
                break;
        }
    }

    // 创建自定义日期时间控件（用于Events编辑）
    createCustomDateTimeControl(originalField, groupId, timeInputId) {
        const currentDateTime = originalField.value;
        if (currentDateTime) {
            const [datePart, timePart] = currentDateTime.split('T');

            // 创建一个只读的日期显示和可编辑的时间输入
            const container = originalField.parentNode;

            // 隐藏原来的datetime-local输入
            originalField.style.display = 'none';

            // 创建日期显示和时间输入的组合
            const dateTimeGroup = document.createElement('div');
            dateTimeGroup.className = 'input-group';
            dateTimeGroup.id = groupId;

            const dateDisplay = document.createElement('input');
            dateDisplay.type = 'text';
            dateDisplay.className = 'form-control';
            dateDisplay.value = datePart;
            dateDisplay.disabled = true;
            dateDisplay.style.backgroundColor = '#f8f9fa';
            dateDisplay.title = '编辑整个系列时不能修改日期';

            const timeInput = document.createElement('input');
            timeInput.type = 'time';
            timeInput.className = 'form-control';
            timeInput.value = timePart;
            timeInput.id = timeInputId;

            dateTimeGroup.appendChild(dateDisplay);
            dateTimeGroup.appendChild(timeInput);
            container.appendChild(dateTimeGroup);

            console.log('Created custom date-time controls for', groupId);
        }
    }

    // 启用所有Events编辑字段
    enableAllEventEditFields() {
        console.log('enableAllEventEditFields called');
        
        const fields = [
            'eventTitle',
            'eventDescription',
            'eventStart',
            'eventEnd',
            'eventDdl'
        ];

        fields.forEach(fieldId => {
            const field = document.getElementById(fieldId);
            if (field) {
                field.disabled = false;
                field.style.backgroundColor = '';
                field.title = '';
                field.style.display = '';
            }
        });

        // 重置重复按钮状态
        const repeatCheckbox = document.getElementById('eventRepeat');
        const repeatLabel = document.querySelector('label[for="eventRepeat"]');

        if (repeatCheckbox) {
            repeatCheckbox.disabled = false;
            repeatCheckbox.style.opacity = '';
            repeatCheckbox.title = '';
        }

        if (repeatLabel) {
            repeatLabel.style.opacity = '';
            repeatLabel.style.color = '';
        }

        // 重置重复选项状态
        const repeatOptions = document.getElementById('editRepeatOptions');
        const eventRecurringOptions = document.getElementById('editEventRecurringOptions');
        
        if (repeatOptions) {
            console.log('Enabling controls in editRepeatOptions (enableAllEventEditFields)');
            const repeatControls = repeatOptions.querySelectorAll('select, input, button');
            console.log(`Found ${repeatControls.length} controls to enable in editRepeatOptions`);
            repeatControls.forEach(control => {
                control.disabled = false;
                control.style.opacity = '';
            });
        }
        
        // 也确保启用editEventRecurringOptions中的按钮
        if (eventRecurringOptions) {
            console.log('Enabling controls in editEventRecurringOptions (enableAllEventEditFields)');
            const eventRecurringControls = eventRecurringOptions.querySelectorAll('select, input, button');
            console.log(`Found ${eventRecurringControls.length} controls to enable in editEventRecurringOptions`);
            eventRecurringControls.forEach(control => {
                control.disabled = false;
                control.style.opacity = '';
                control.style.pointerEvents = 'auto';
            });
        }

        // 清理自定义控件
        this.cleanupEventCustomControls();
    }

    // 启用Events基本编辑字段（不包括重复相关字段）
    enableEventBasicFields() {
        const fields = [
            'eventTitle',
            'eventDescription',
            'eventStart',
            'eventEnd',
            'eventDdl'
        ];

        fields.forEach(fieldId => {
            const field = document.getElementById(fieldId);
            if (field) {
                field.disabled = false;
                field.style.backgroundColor = '';
                field.title = '';
                field.style.display = '';
            }
        });

        // 清理自定义控件
        this.cleanupEventCustomControls();
    }

    // 启用所有Events编辑字段但不清理自定义控件
    enableAllEventEditFieldsWithoutCleanup() {
        const fields = [
            'eventTitle',
            'eventDescription',
            'eventStart',
            'eventEnd',
            'eventDdl'
        ];

        fields.forEach(fieldId => {
            const field = document.getElementById(fieldId);
            if (field) {
                field.disabled = false;
                field.style.backgroundColor = '';
                field.title = '';
            }
        });

        // 重置重复按钮状态
        const repeatCheckbox = document.getElementById('eventRepeat');
        const repeatLabel = document.querySelector('label[for="eventRepeat"]');

        if (repeatCheckbox) {
            repeatCheckbox.disabled = false;
            repeatCheckbox.style.opacity = '';
            repeatCheckbox.title = '';
        }

        if (repeatLabel) {
            repeatLabel.style.opacity = '';
            repeatLabel.style.color = '';
        }
    }

    // 配置Events的"从此开始"默认模式
    configureEventFromThisDefaultMode() {
        console.log('configureEventFromThisDefaultMode called');
        
        // 禁用重复开关但保持原状态
        const repeatCheckbox = document.getElementById('eventRepeat');
        const repeatOptions = document.getElementById('editRepeatOptions');
        const eventRecurringOptions = document.getElementById('editEventRecurringOptions');

        console.log('repeatCheckbox found:', !!repeatCheckbox);
        console.log('editRepeatOptions found:', !!repeatOptions);
        console.log('editEventRecurringOptions found:', !!eventRecurringOptions);

        if (repeatCheckbox) {
            repeatCheckbox.disabled = true;
            repeatCheckbox.style.opacity = '0.5';
            repeatCheckbox.title = '编辑未来事件时不可修改重复规则';
        }

        // 禁用所有重复选项控件但保持显示
        if (repeatOptions) {
            console.log('Disabling controls in editRepeatOptions');
            const repeatControls = repeatOptions.querySelectorAll('select, input, button');
            console.log(`Found ${repeatControls.length} controls in editRepeatOptions`);
            repeatControls.forEach((control, index) => {
                console.log(`Control ${index}:`, control.tagName, control.id, control.className);
                control.disabled = true;
                control.style.opacity = '0.5';
            });
        }
        
        // 也检查editEventRecurringOptions容器
        if (eventRecurringOptions) {
            console.log('Also checking editEventRecurringOptions for buttons');
            const eventRecurringControls = eventRecurringOptions.querySelectorAll('button');
            console.log(`Found ${eventRecurringControls.length} buttons in editEventRecurringOptions`);
            eventRecurringControls.forEach((btn, index) => {
                console.log(`Button ${index}:`, btn.textContent.trim(), btn.className, 'disabled:', btn.disabled);
            });
        }

        // 禁用重复标签
        const repeatLabel = document.querySelector('label[for="eventRepeat"]');
        if (repeatLabel) {
            repeatLabel.style.opacity = '0.5';
            repeatLabel.style.color = '#6c757d';
        }
    }

    // 清理Events自定义控件
    cleanupEventCustomControls() {
        const customGroups = ['customEventStartGroup', 'customEventEndGroup'];
        
        customGroups.forEach(groupId => {
            const customGroup = document.getElementById(groupId);
            if (customGroup) {
                customGroup.remove();
            }
        });

        // 恢复原始字段显示
        const originalFields = ['eventStart', 'eventEnd'];
        originalFields.forEach(fieldId => {
            const field = document.getElementById(fieldId);
            if (field) {
                field.style.display = '';
            }
        });
    }

    // 填充事件时间选择器选项
    populateEventTimeSelect(seriesId) {
        const timeSelect = document.getElementById('editEventTimeSelect');
        if (!timeSelect) return;
        
        // 获取未来的事件选项
        const futureOptions = eventManager.getFutureEventOptions(seriesId);
        
        // 清空现有选项
        timeSelect.innerHTML = '';
        
        // 添加新选项
        futureOptions.forEach(option => {
            const optionElement = document.createElement('option');
            optionElement.value = option.value;
            optionElement.textContent = option.label;
            timeSelect.appendChild(optionElement);
        });
    }

    // 处理创建事件
    async handleCreateEvent() {
        // 防重复提交
        if (this.isSubmittingEvent) {
            console.log('事件创建正在进行中，忽略重复请求');
            return;
        }
        
        if (!this.validateEventForm('create')) return;

        this.isSubmittingEvent = true;
        try {
            const eventData = this.getEventFormData('create');
            
            // 将时间转换为标准格式再发送给后端
            eventData.start = this.toUTC(eventData.start);
            eventData.end = this.toUTC(eventData.end);
            if (eventData.ddl) {
                eventData.ddl = this.toUTC(eventData.ddl);
            }

            const success = await eventManager.createEvent(eventData);

            if (success) {
                this.closeAllModals();
            } else {
                this.showNotification('事件创建失败', 'error');
            }
        } finally {
            this.isSubmittingEvent = false;
        }
    }

    // 处理更新事件
    async handleUpdateEvent() {
        if (!this.validateEventForm('edit')) return;

        const eventData = this.getEventFormData('edit');
        
        // 检查是否有pending的批量编辑操作
        if (eventManager.pendingBulkEdit) {
            const { event_id, series_id, scope, fromTime } = eventManager.pendingBulkEdit;
            
            console.log('handleUpdateEvent - pendingBulkEdit:', eventManager.pendingBulkEdit);
            console.log('handleUpdateEvent - eventData:', eventData);
            
            // 准备批量更新数据
            const updateData = {
                title: eventData.title,
                description: eventData.description,
                importance: eventData.importance,
                urgency: eventData.urgency,
                start: this.toUTC(eventData.start),
                end: this.toUTC(eventData.end),
                groupID: eventData.groupID,  // 使用 groupID (大写)
                ddl: eventData.ddl ? this.toUTC(eventData.ddl) : ''
            };
            
            // 只有当rrule确实存在且不为空时才包含在更新数据中
            if (eventData.rrule && eventData.rrule.trim() !== '') {
                updateData.rrule = eventData.rrule;
            }
            
            console.log('handleUpdateEvent - updateData:', updateData);
            
            // 执行批量操作
            const success = await eventManager.performBulkOperation(
                series_id, 'edit', scope, fromTime, event_id, updateData
            );
            
            // 清除pending状态和相关状态
            eventManager.pendingBulkEdit = null;
            eventManager.currentEditMode = null;
            eventManager.isInEditMode = false;
            
            // 清理任何编辑模式提示
            const hintElements = document.querySelectorAll('.edit-mode-hint');
            hintElements.forEach(el => el.remove());
            
            if (success) {
                this.closeAllModals();
            } else {
                this.showNotification('事件批量更新失败', 'error');
            }
        } else {
            // 普通单次事件更新
            const success = await eventManager.updateEvent(
                this.currentEventId,
                this.toUTC(eventData.start),
                this.toUTC(eventData.end),
                eventData.title,
                eventData.description,
                eventData.importance,
                eventData.urgency,
                eventData.groupID,  // 使用 groupID (大写)
                eventData.ddl ? this.toUTC(eventData.ddl) : '',
                eventData.rrule
            );

            if (success) {
                this.closeAllModals();
            } else {
                this.showNotification('事件更新失败', 'error');
            }
        }
    }

    // 处理删除事件
    async handleDeleteEvent() {
        // 获取当前事件信息
        const eventId = this.currentEventId;
        const eventInfo = eventManager.calendar.getEventById(eventId);
        
        console.log('handleDeleteEvent called for event:', eventInfo);
        
        if (eventInfo && eventInfo.extendedProps) {
            const eventData = eventInfo.extendedProps;
            
            // 多种方式判断是否为重复事件
            const hasRRule = eventData.rrule && eventData.rrule.trim() !== '';
            const isRecurring = eventData.is_recurring;
            const hasSeriesId = eventData.series_id && eventData.series_id.trim() !== '';
            const isDetached = eventData.is_detached; // 检查是否已脱离系列
            
            console.log('Delete recurring check in modal:', { hasRRule, isRecurring, hasSeriesId, isDetached });
            
            if (hasRRule && !isDetached) {
                // 重复事件，检查是否已有批量编辑信息
                if (eventManager.pendingBulkEdit && eventManager.pendingBulkEdit.scope) {
                    // 使用已选择的范围进行删除
                    const scope = eventManager.pendingBulkEdit.scope;
                    const seriesId = hasSeriesId ? eventData.series_id : eventId;
                    const fromTime = eventManager.pendingBulkEdit.fromTime || '';
                    
                    const scopeNames = {
                        'single': '仅此事件',
                        'all': '全部事件',
                        'future': '此事件及之后',
                        'from_time': '从指定时间开始'
                    };
                    
                    const scopeName = scopeNames[scope] || scope;
                    if (!confirm(`当前选择的范围是"${scopeName}"，确定要删除吗？`)) return;
                    
                    console.log('Using existing scope for deletion:', scope);
                    eventManager.performBulkOperation(seriesId, 'delete', scope, fromTime, eventId);
                    this.closeAllModals();
                    return;
                } else {
                    // 没有预选范围，使用原来的逻辑弹出选择框
                    const seriesId = hasSeriesId ? eventData.series_id : eventId;
                    console.log('No existing scope, calling handleEventDelete with seriesId:', seriesId);
                    eventManager.handleEventDelete(eventId, seriesId);
                    this.closeAllModals(); // 关闭当前模态框，范围选择器会打开新的
                    return;
                }
            }
        }
        
        // 普通事件删除确认
        if (!confirm('确定要删除这个事件吗？')) return;
        
        const success = await eventManager.deleteEvent(this.currentEventId);
        
        if (success) {
            this.closeAllModals();
        } else {
            this.showNotification('事件删除失败', 'error');
        }
    }


    // 显示重复事件删除确认模态框
    showDeleteRecurringEventModal() {
        // 先关闭编辑模态框
        const editModal = document.getElementById('editEventModal');
        if (editModal) {
            editModal.style.display = 'none';
        }
        
        // 显示删除确认模态框
        this.showModal('deleteRecurringEventModal');
    }

    // 确认删除重复事件
    async confirmDeleteRecurringEvent() {
        const selectedScope = document.querySelector('input[name="deleteEventScope"]:checked');
        if (!selectedScope) {
            this.showNotification('请选择删除范围', 'warning');
            return;
        }

        const scope = selectedScope.value;
        const eventId = this.currentEventId;
        
        const success = await eventManager.deleteRecurringEvent(eventId, scope);
        
        if (success) {
            this.closeAllModals();
        } else {
            this.showNotification('删除失败', 'error');
        }
    }

    // === 待办事项相关模态框 ===

    // 打开创建待办模态框
    openCreateTodoModal() {
        this.clearTodoForm();
        this.populateGroupSelect('newTodoGroupId');
        this.showModal('createTodoModal');
    }

    // 打开编辑待办模态框
    openEditTodoModal(todo) {
        const modal = document.getElementById('editTodoModal');
        this.currentTodoId = todo.id;

        // 填充表单数据
        document.getElementById('todoId').value = todo.id;
        document.getElementById('todoTitle').value = todo.title;
        document.getElementById('todoDescription').value = todo.description || '';
        document.getElementById('todoDueDate').value = todo.due_date ? this.toLocalTime(todo.due_date) : '';
        document.getElementById('todoEstimatedDuration').value = todo.estimated_duration || '';
        document.getElementById('todoImportance').value = todo.importance;
        document.getElementById('todoUrgency').value = todo.urgency;

        this.populateGroupSelect('todoGroupId', todo.groupID);

        this.showModal('editTodoModal');
    }

    // 处理创建待办
    async handleCreateTodo() {
        if (!this.validateTodoForm('create')) return;

        const todoData = this.getTodoFormData('create');
        const success = await todoManager.createTodo(todoData);

        if (success) {
            this.closeAllModals();
        } else {
            this.showNotification('待办事项创建失败', 'error');
        }
    }

    // 处理更新待办
    async handleUpdateTodo() {
        if (!this.validateTodoForm('edit')) return;

        const todoData = this.getTodoFormData('edit');
        const success = await todoManager.updateTodo(this.currentTodoId, todoData);

        if (success) {
            this.closeAllModals();
        } else {
            this.showNotification('待办事项更新失败', 'error');
        }
    }

    // === 提醒相关模态框 ===

    // 打开创建提醒模态框
    openCreateReminderModal() {
        const modal = document.getElementById('createReminderModal');
        this.clearReminderForm();

        // 设置默认触发时间（当前时间 + 1小时）
        const now = new Date();
        const defaultTime = new Date(now.getTime() + 60 * 60 * 1000);
        const defaultTimeStr = this.toLocalTime(defaultTime.toISOString());
        document.getElementById('newReminderTriggerTime').value = defaultTimeStr;

        this.showModal('createReminderModal');
    }

    // 打开编辑提醒模态框
    openEditReminderModal(reminder) {
        console.log('=== openEditReminderModal called ===');
        console.log('reminder:', reminder);
        
        const modal = document.getElementById('editReminderModal');
        this.currentReminderId = reminder.id;

        // 重置强制截止时间标记
        this.forceUntilRequired = false;

        // 填充表单数据
        document.getElementById('reminderId').value = reminder.id;
        document.getElementById('reminderTitle').value = reminder.title;
        document.getElementById('reminderContent').value = reminder.content || '';
        
        // 根据批量编辑模式决定使用哪个时间
        const pendingBulkEdit = reminderManager.pendingBulkEdit;
        console.log('pendingBulkEdit in openEditReminderModal:', pendingBulkEdit);
        
        let triggerTime = reminder.trigger_time;
        
        if (pendingBulkEdit && pendingBulkEdit.scope === 'from_time' && pendingBulkEdit.fromTime) {
            // from_time 模式：使用用户选择的时间点
            triggerTime = pendingBulkEdit.fromTime;
            console.log(`DEBUG: Using from_time mode, trigger_time set to: ${triggerTime}`);
        } else {
            console.log(`DEBUG: Using original reminder time: ${triggerTime}`);
        }
        
        document.getElementById('reminderTriggerTime').value = this.toLocalTime(triggerTime);
        document.getElementById('reminderPriority').value = reminder.priority;

        // 调试：检查reminder的rrule
        console.log('=== About to call parseRruleToUI ===');
        console.log('reminder.rrule:', reminder.rrule);
        console.log('reminder object:', reminder);

        // 直接调用手动解析函数，确保调用正确的Reminder解析逻辑
        this.manualParseRrule(reminder.rrule || '', 'edit');

        // 根据批量编辑范围设置字段的启用/禁用状态
        this.configureEditFieldsBasedOnScope();

        this.showModal('editReminderModal');
    }

    // 手动解析RRule（备用方案）
    manualParseRrule(rrule, mode) {
        console.log('=== manualParseRrule called ===');
        console.log('rrule:', rrule, 'mode:', mode);
        
        const prefix = mode === 'new' ? 'new' : 'reminder';
        
        if (!rrule) {
            console.log('No rrule provided');
            return;
        }
        
        // 启用重复选项
        const repeatCheckbox = document.getElementById(`${prefix}Repeat`);
        console.log('repeatCheckbox:', repeatCheckbox);
        if (repeatCheckbox) {
            repeatCheckbox.checked = true;
            console.log('Set repeat checkbox to checked');
            
            // 显示重复选项
            const repeatOptions = document.getElementById(mode === 'new' ? 'newRepeatOptions' : 'editRepeatOptions');
            if (repeatOptions) {
                repeatOptions.style.display = 'block';
                console.log('Showed repeat options');
            }
        }
        
        // 解析RRULE
        const rules = rrule.split(';');
        const ruleObj = {};
        
        rules.forEach(rule => {
            const [key, value] = rule.split('=');
            if (key && value) {
                ruleObj[key] = value;
            }
        });
        
        console.log('Parsed ruleObj:', ruleObj);
        
        // 设置频率
        if (ruleObj.FREQ) {
            const freqElement = document.getElementById(`${prefix}RepeatFreq`);
            console.log(`Setting frequency: ${prefix}RepeatFreq =`, ruleObj.FREQ, freqElement);
            if (freqElement) {
                freqElement.value = ruleObj.FREQ;
                // 触发change事件以更新UI
                freqElement.dispatchEvent(new Event('change'));
                console.log('Frequency set and change event triggered');
            }
        }
        
        // 设置间隔
        if (ruleObj.INTERVAL) {
            const intervalElement = document.getElementById(`${prefix}RepeatInterval`);
            console.log(`Setting interval: ${prefix}RepeatInterval =`, ruleObj.INTERVAL, intervalElement);
            if (intervalElement) {
                intervalElement.value = ruleObj.INTERVAL;
                console.log('Interval set');
            }
        }
        
        // 设置星期几（对于WEEKLY频率）
        if (ruleObj.FREQ === 'WEEKLY' && ruleObj.BYDAY) {
            const weekdays = ruleObj.BYDAY.split(',');
            console.log('Setting weekdays:', weekdays);
            weekdays.forEach(day => {
                const checkbox = document.getElementById(`${prefix}${day}`);
                if (checkbox) {
                    checkbox.checked = true;
                    console.log(`Set ${day} checkbox to checked`);
                }
            });
        }
        
        // 设置月重复方式
        if (ruleObj.FREQ === 'MONTHLY') {
            const monthlyTypeSelect = document.getElementById(`${prefix}RepeatBy`);
            console.log('Setting monthly repeat type:', monthlyTypeSelect);
            
            if (ruleObj.BYMONTHDAY) {
                // 按日期重复
                if (monthlyTypeSelect) {
                    monthlyTypeSelect.value = 'bymonthday';
                    // 触发change事件以更新UI
                    monthlyTypeSelect.dispatchEvent(new Event('change'));
                }
                
                // 设置月日期
                const monthlyDateSelect = document.getElementById(mode === 'new' ? 'newMonthlyDate' : 'editMonthlyDate');
                if (monthlyDateSelect) {
                    monthlyDateSelect.value = ruleObj.BYMONTHDAY;
                }
            } else if (ruleObj.BYDAY) {
                // 按星期重复
                if (monthlyTypeSelect) {
                    monthlyTypeSelect.value = 'byweekday';
                    monthlyTypeSelect.dispatchEvent(new Event('change'));
                }
                
                // 解析第几周和星期几
                const dayRule = ruleObj.BYDAY;
                const match = dayRule.match(/^(-?\d+)([A-Z]{2})$/);
                if (match) {
                    const week = match[1];
                    const weekday = match[2];
                    
                    const weekSelect = document.getElementById(mode === 'new' ? 'newMonthlyWeek' : 'editMonthlyWeek');
                    const weekdaySelect = document.getElementById(mode === 'new' ? 'newMonthlyWeekday' : 'editMonthlyWeekday');
                    
                    if (weekSelect) weekSelect.value = week;
                    if (weekdaySelect) weekdaySelect.value = weekday;
                }
            }
        }
        
        // 设置结束时间
        if (ruleObj.UNTIL) {
            const untilElement = document.getElementById(`${prefix}RepeatUntil`);
            console.log(`Setting until: ${prefix}RepeatUntil =`, ruleObj.UNTIL, untilElement);
            if (untilElement) {
                try {
                    // 转换日期格式
                    let dateStr = ruleObj.UNTIL;
                    if (dateStr.includes('T')) {
                        dateStr = dateStr.split('T')[0];
                    }
                    // 转换格式：20251023 -> 2025-10-23
                    if (dateStr.length === 8 && !dateStr.includes('-')) {
                        dateStr = dateStr.substring(0, 4) + '-' + dateStr.substring(4, 6) + '-' + dateStr.substring(6, 8);
                    }
                    untilElement.value = dateStr;
                    console.log('Until date set to:', dateStr);
                } catch (error) {
                    console.error('Error parsing until date:', error);
                }
            }
        }
        
        console.log('manualParseRrule completed');
    }

    // 手动解析Events的RRule（备用方案）
    manualParseEventRrule(rrule, mode) {
        console.log('=== manualParseEventRrule called ===');
        console.log('rrule:', rrule, 'mode:', mode);
        
        const prefix = mode === 'create' ? 'newEvent' : 'editEvent';
        
        if (!rrule) {
            console.log('No rrule provided');
            return;
        }
        
        // 启用重复选项
        const repeatCheckboxId = mode === 'create' ? `${prefix}IsRecurring` : `${prefix}IsRepeating`;
        const repeatCheckbox = document.getElementById(repeatCheckboxId);
        console.log('Events repeatCheckbox:', repeatCheckbox);
        if (repeatCheckbox) {
            repeatCheckbox.checked = true;
            console.log('Set Events repeat checkbox to checked');
            
            // 显示重复选项
            const repeatOptionsId = mode === 'create' ? `${prefix}RecurringOptions` : `${prefix}RepeatOptions`;
            const repeatOptions = document.getElementById(repeatOptionsId);
            if (repeatOptions) {
                repeatOptions.style.display = 'block';
                console.log('Showed Events repeat options');
            }
        }
        
        // 解析RRULE
        const rules = rrule.split(';');
        const ruleObj = {};
        
        rules.forEach(rule => {
            const [key, value] = rule.split('=');
            if (key && value) {
                ruleObj[key] = value;
            }
        });
        
        console.log('Parsed Events ruleObj:', ruleObj);
        
        // 设置频率
        if (ruleObj.FREQ) {
            const freqElement = document.getElementById(`${prefix}Freq`);
            console.log(`Setting Events frequency: ${prefix}Freq =`, ruleObj.FREQ, freqElement);
            if (freqElement) {
                freqElement.value = ruleObj.FREQ;
                // 触发change事件以更新UI
                freqElement.dispatchEvent(new Event('change'));
                console.log('Events frequency set and change event triggered');
            }
        }
        
        // 设置间隔
        if (ruleObj.INTERVAL) {
            const intervalElement = document.getElementById(`${prefix}Interval`);
            console.log(`Setting Events interval: ${prefix}Interval =`, ruleObj.INTERVAL, intervalElement);
            if (intervalElement) {
                intervalElement.value = ruleObj.INTERVAL;
                console.log('Events interval set');
            }
        }
        
        console.log('manualParseEventRrule completed');
    }

    // 根据批量编辑范围配置字段的启用/禁用状态
    configureEditFieldsBasedOnScope() {
        const pendingBulkEdit = reminderManager.pendingBulkEdit;
        console.log('=== configureEditFieldsBasedOnScope called ===');
        console.log('pendingBulkEdit:', pendingBulkEdit);

        if (!pendingBulkEdit) {
            // 普通编辑，所有字段都可编辑
            console.log('No pendingBulkEdit, enabling all fields');
            this.enableAllEditFields();
            return;
        }

        const scope = pendingBulkEdit.scope;
        console.log('Scope:', scope);

        const dateTimeField = document.getElementById('reminderTriggerTime');
        const titleField = document.getElementById('reminderTitle');
        const contentField = document.getElementById('reminderContent');
        const priorityField = document.getElementById('reminderPriority');

        switch (scope) {
            case 'this_only':
                console.log('Configuring for single edit mode');
                // 先重置所有字段
                this.enableAllEditFields();
                
                // 仅此条提醒：禁用重复规则，强制关闭重复开关
                const repeatCheckbox = document.getElementById('reminderRepeat');
                const repeatOptions = document.getElementById('editRepeatOptions');

                console.log('repeatCheckbox:', repeatCheckbox);
                console.log('repeatOptions:', repeatOptions);

                if (repeatCheckbox) {
                    repeatCheckbox.checked = false;
                    repeatCheckbox.disabled = true;
                    repeatCheckbox.style.opacity = '0.5';
                    repeatCheckbox.title = '已脱离重复组，不可修改重复规则';
                    console.log('Disabled repeat checkbox');
                }

                if (repeatOptions) {
                    repeatOptions.style.display = 'none';
                    console.log('Hidden repeat options');
                }

                // 添加视觉提示
                const repeatLabel = document.querySelector('label[for="reminderRepeat"]');
                if (repeatLabel) {
                    repeatLabel.style.opacity = '0.5';
                    repeatLabel.style.color = '#6c757d';
                    console.log('Styled repeat label');
                }
                break;

            case 'all':
                console.log('Configuring for all reminders edit mode');
                // 先重置所有字段，但不清理自定义控件
                this.enableAllEditFieldsWithoutCleanup();
                
                // 所有提醒：禁用重复规则，但保持显示，禁用日期部分，只允许修改时间
                const allRepeatCheckbox = document.getElementById('reminderRepeat');
                const allRepeatOptions = document.getElementById('editRepeatOptions');

                console.log('allRepeatCheckbox:', allRepeatCheckbox);
                console.log('allRepeatOptions:', allRepeatOptions);

                // 禁用重复开关但保持原状态
                if (allRepeatCheckbox) {
                    allRepeatCheckbox.disabled = true;
                    allRepeatCheckbox.style.opacity = '0.5';
                    allRepeatCheckbox.title = '编辑整个系列时不可修改重复规则';
                    console.log('Disabled repeat checkbox for all mode');
                }

                // 禁用所有重复选项控件但保持显示
                if (allRepeatOptions) {
                    const repeatControls = allRepeatOptions.querySelectorAll('select, input, button');
                    repeatControls.forEach(control => {
                        control.disabled = true;
                        control.style.opacity = '0.5';
                    });
                    console.log('Disabled all repeat controls');
                }

                // 禁用重复标签
                const allRepeatLabel = document.querySelector('label[for="reminderRepeat"]');
                if (allRepeatLabel) {
                    allRepeatLabel.style.opacity = '0.5';
                    allRepeatLabel.style.color = '#6c757d';
                }

                // 锁定日期部分，但允许修改时间
                const allDateTimeField = document.getElementById('reminderTriggerTime');
                if (allDateTimeField && !document.getElementById('customDateTimeGroup')) {
                    // 获取当前值
                    const currentDateTime = allDateTimeField.value;
                    if (currentDateTime) {
                        const [datePart, timePart] = currentDateTime.split('T');

                        // 创建一个只读的日期显示和可编辑的时间输入
                        const container = allDateTimeField.parentNode;

                        // 隐藏原来的datetime-local输入
                        allDateTimeField.style.display = 'none';

                        // 创建日期显示和时间输入的组合
                        const dateTimeGroup = document.createElement('div');
                        dateTimeGroup.className = 'input-group';
                        dateTimeGroup.id = 'customDateTimeGroup';

                        const dateDisplay = document.createElement('input');
                        dateDisplay.type = 'text';
                        dateDisplay.className = 'form-control';
                        dateDisplay.value = datePart;
                        dateDisplay.disabled = true;
                        dateDisplay.style.backgroundColor = '#f8f9fa';
                        dateDisplay.title = '编辑整个系列时不能修改日期';

                        const timeInput = document.createElement('input');
                        timeInput.type = 'time';
                        timeInput.className = 'form-control';
                        timeInput.value = timePart;
                        timeInput.id = 'reminderTimeOnly';

                        dateTimeGroup.appendChild(dateDisplay);
                        dateTimeGroup.appendChild(timeInput);
                        container.appendChild(dateTimeGroup);

                        console.log('Created custom date-time controls');
                    }
                }
                break;

            case 'from_this':
            case 'from_time':
                // 先重置所有字段
                console.log('Before enableAllEditFields - from_this/from_time mode');
                this.enableAllEditFields();
                
                // from_this 和 from_time 模式：重复复选框应该是选中且只读的
                console.log('Configuring for from_this/from_time edit mode');
                
                const fromThisRepeatCheckbox = document.getElementById('reminderRepeat');
                const fromThisRepeatLabel = document.querySelector('label[for="reminderRepeat"]');
                const fromThisRepeatOptions = document.getElementById('editRepeatOptions');
                
                if (fromThisRepeatCheckbox) {
                    // 设为选中且只读（禁用）
                    fromThisRepeatCheckbox.checked = true;
                    fromThisRepeatCheckbox.disabled = true;
                    fromThisRepeatCheckbox.style.opacity = '0.7';
                    fromThisRepeatCheckbox.title = '点击"编辑重复规则"按钮来修改重复设置';
                    console.log('Set repeat checkbox as checked and readonly');
                }
                
                if (fromThisRepeatLabel) {
                    fromThisRepeatLabel.style.opacity = '0.7';
                    fromThisRepeatLabel.style.color = '#6c757d';
                }
                
                // 显示重复选项但禁用所有控件
                if (fromThisRepeatOptions) {
                    fromThisRepeatOptions.style.display = 'block';
                    const repeatControls = fromThisRepeatOptions.querySelectorAll('select, input, button');
                    repeatControls.forEach(control => {
                        control.disabled = true;
                        control.style.opacity = '0.7';
                    });
                    console.log('Showed repeat options but disabled all controls');
                }
                
                // 添加"编辑重复规则"按钮
                this.addChangeRuleButton();
                console.log('Added change rule button for from_this/from_time mode');
                
                // 检查重复按钮状态
                console.log('Final repeatCheckbox state:', {
                    disabled: fromThisRepeatCheckbox?.disabled,
                    opacity: fromThisRepeatCheckbox?.style.opacity,
                    checked: fromThisRepeatCheckbox?.checked
                });
                
                // 延迟检查，看是否有其他代码覆盖了我们的设置
                setTimeout(() => {
                    console.log('After 100ms delay - repeatCheckbox state:', {
                        disabled: fromThisRepeatCheckbox?.disabled,
                        opacity: fromThisRepeatCheckbox?.style.opacity,
                        checked: fromThisRepeatCheckbox?.checked
                    });
                }, 100);
                break;
        }
    }

    // 启用所有编辑字段
    enableAllEditFields() {
        console.log('=== enableAllEditFields called ===');
        const fields = [
            'reminderTitle',
            'reminderContent',
            'reminderTriggerTime',
            'reminderPriority'
        ];

        fields.forEach(fieldId => {
            const field = document.getElementById(fieldId);
            if (field) {
                field.disabled = false;
                field.style.backgroundColor = '';
                field.title = '';
            }
        });

        // 重置重复按钮状态
        const repeatCheckbox = document.getElementById('reminderRepeat');
        const repeatLabel = document.querySelector('label[for="reminderRepeat"]');

        console.log('Before enabling repeatCheckbox:', {
            disabled: repeatCheckbox?.disabled,
            opacity: repeatCheckbox?.style.opacity,
            checked: repeatCheckbox?.checked
        });

        if (repeatCheckbox) {
            repeatCheckbox.disabled = false;
            repeatCheckbox.style.opacity = '';
            repeatCheckbox.title = '';
        }

        if (repeatLabel) {
            repeatLabel.style.opacity = '';
            repeatLabel.style.color = '';
        }

        // 重置重复选项状态
        const repeatOptions = document.getElementById('editRepeatOptions');
        if (repeatOptions) {
            const repeatControls = repeatOptions.querySelectorAll('select, input, button');
            repeatControls.forEach(control => {
                control.disabled = false;
                control.style.opacity = '';
            });
        }

        console.log('After enabling repeatCheckbox:', {
            disabled: repeatCheckbox?.disabled,
            opacity: repeatCheckbox?.style.opacity,
            checked: repeatCheckbox?.checked
        });

        // 清理自定义控件
        this.cleanupCustomControls();
    }

    // 启用所有编辑字段但不清理自定义控件
    enableAllEditFieldsWithoutCleanup() {
        const fields = [
            'reminderTitle',
            'reminderContent',
            'reminderTriggerTime',
            'reminderPriority'
        ];

        fields.forEach(fieldId => {
            const field = document.getElementById(fieldId);
            if (field) {
                field.disabled = false;
                field.style.backgroundColor = '';
                field.title = '';
            }
        });

        // 重置重复按钮状态
        const repeatCheckbox = document.getElementById('reminderRepeat');
        const repeatLabel = document.querySelector('label[for="reminderRepeat"]');

        if (repeatCheckbox) {
            repeatCheckbox.disabled = false;
            repeatCheckbox.style.opacity = '';
            repeatCheckbox.title = '';
        }

        if (repeatLabel) {
            repeatLabel.style.opacity = '';
            repeatLabel.style.color = '';
        }

        // 重置重复选项状态
        const repeatOptions = document.getElementById('editRepeatOptions');
        if (repeatOptions) {
            const repeatControls = repeatOptions.querySelectorAll('select, input, button');
            repeatControls.forEach(control => {
                control.disabled = false;
                control.style.opacity = '';
            });
        }
    }

    // 配置"从此提醒开始"的默认模式（类似all模式）
    configureFromThisDefaultMode() {
        // 禁用重复复选框
        const repeatCheckbox = document.getElementById('reminderRepeat');
        if (repeatCheckbox) {
            repeatCheckbox.disabled = true;
            repeatCheckbox.style.opacity = '0.5';
            repeatCheckbox.title = '点击"更改重复规则"按钮来修改重复设置';
        }

        // 禁用重复选项
        const repeatOptions = document.getElementById('editRepeatOptions');
        if (repeatOptions) {
            const repeatControls = repeatOptions.querySelectorAll('select, input, button');
            repeatControls.forEach(control => {
                control.disabled = true;
                control.style.opacity = '0.5';
            });
        }

        // 禁用重复标签
        const repeatLabel = document.querySelector('label[for="reminderRepeat"]');
        if (repeatLabel) {
            repeatLabel.style.opacity = '0.5';
            repeatLabel.style.color = '#6c757d';
        }

        // 创建自定义日期时间控件（锁定日期，允许修改时间）
        const dateTimeField = document.getElementById('reminderTriggerTime');
        if (dateTimeField && !document.getElementById('customDateTimeGroup')) {
            const currentDateTime = dateTimeField.value;
            if (currentDateTime) {
                const [datePart, timePart] = currentDateTime.split('T');
                const container = dateTimeField.parentNode;

                dateTimeField.style.display = 'none';

                const dateTimeGroup = document.createElement('div');
                dateTimeGroup.className = 'input-group';
                dateTimeGroup.id = 'customDateTimeGroup';

                const dateDisplay = document.createElement('input');
                dateDisplay.type = 'text';
                dateDisplay.className = 'form-control';
                dateDisplay.value = datePart;
                dateDisplay.disabled = true;
                dateDisplay.style.backgroundColor = '#f8f9fa';
                dateDisplay.title = '默认不能修改日期，点击"更改重复规则"按钮可修改';

                const timeInput = document.createElement('input');
                timeInput.type = 'time';
                timeInput.className = 'form-control';
                timeInput.value = timePart;
                timeInput.id = 'reminderTimeOnly';

                dateTimeGroup.appendChild(dateDisplay);
                dateTimeGroup.appendChild(timeInput);
                container.appendChild(dateTimeGroup);
            }
        }
        
        // 添加"更改重复规则"按钮
        this.addChangeRuleButton();
    }

    // 添加"更改重复规则"按钮
    addChangeRuleButton() {
        console.log('DEBUG: addChangeRuleButton called');
        
        // 检查是否已经存在按钮
        if (document.getElementById('changeRuleButton')) {
            console.log('DEBUG: changeRuleButton already exists');
            return;
        }

        // 找到重复选项区域
        const repeatOptions = document.getElementById('editRepeatOptions');
        if (repeatOptions) {
            console.log('DEBUG: Found editRepeatOptions, creating button');
            const buttonContainer = document.createElement('div');
            buttonContainer.className = 'col-12 mb-3 text-center';
            buttonContainer.id = 'changeRuleButtonContainer';

            const changeRuleBtn = document.createElement('button');
            changeRuleBtn.type = 'button';
            changeRuleBtn.className = 'btn btn-outline-primary btn-sm';
            changeRuleBtn.id = 'changeRuleButton';
            changeRuleBtn.innerHTML = '<i class="fas fa-edit"></i> 更改重复规则';
            changeRuleBtn.onclick = () => this.enableFullEditMode();

            buttonContainer.appendChild(changeRuleBtn);
            
            // 插入到重复选项的开头
            repeatOptions.parentNode.insertBefore(buttonContainer, repeatOptions);
            console.log('DEBUG: changeRuleButton added to DOM');
        } else {
            console.log('DEBUG: editRepeatOptions not found');
        }
    }

    // 启用完整编辑模式
    enableFullEditMode() {
        console.log('DEBUG: enableFullEditMode called');
        
        // 移除无限重复修改的强制限制，允许所有重复规则修改
        // 让后端处理无限重复序列到无限重复序列的转换逻辑
        
        // 在清理前保存自定义时间控件的值
        const timeOnlyInput = document.getElementById('reminderTimeOnly');
        const originalDateTimeField = document.getElementById('reminderTriggerTime');
        let savedDateTime = null;
        
        if (timeOnlyInput && originalDateTimeField) {
            const originalDateTime = originalDateTimeField.value;
            if (originalDateTime) {
                const [datePart] = originalDateTime.split('T');
                savedDateTime = `${datePart}T${timeOnlyInput.value}`;
            }
        }
        
        // 清理自定义控件，恢复正常的日期时间输入
        this.cleanupCustomControls();
        
        // 如果有保存的时间值，恢复到原始字段
        if (savedDateTime && originalDateTimeField) {
            originalDateTimeField.value = savedDateTime;
        }
        
        // 启用所有字段
        this.enableAllEditFieldsWithoutCleanup();
        
        // 隐藏"更改重复规则"按钮
        const buttonContainer = document.getElementById('changeRuleButtonContainer');
        if (buttonContainer) {
            buttonContainer.style.display = 'none';
        }
        
        // 标记为完整编辑模式
        const editModal = document.getElementById('editReminderModal');
        if (editModal) {
            editModal.setAttribute('data-full-edit', 'true');
            console.log('DEBUG: Set data-full-edit=true on editReminderModal');
        } else {
            console.log('DEBUG: editReminderModal element not found');
        }
    }

    // 处理创建提醒
    async handleCreateReminder() {
        if (!this.validateReminderForm('create')) return;

        const reminderData = this.getReminderFormData('create');
        const success = await reminderManager.createReminder(reminderData);

        if (success) {
            this.closeAllModals();
        } else {
            this.showNotification('提醒创建失败', 'error');
        }
    }

    // 处理更新提醒
    async handleUpdateReminder() {
        if (!this.validateReminderForm('edit')) return;

        const reminderData = this.getReminderFormData('edit');
        console.log('DEBUG handleUpdateReminder: reminderData =', reminderData);

        // 移除无限重复修改的强制限制，允许后端处理所有重复规则修改场景

        // 检查是否有待处理的批量编辑
        if (reminderManager.pendingBulkEdit) {
            const { reminderId, seriesId, scope, fromTime } = reminderManager.pendingBulkEdit;

            // 检查是否是创建新系列模式
            if (reminderData.create_new_series) {
                // 创建新系列：使用批量编辑API，确保进入正确的处理分支
                const success = await reminderManager.performBulkOperation(seriesId, 'edit', scope, fromTime, reminderId, reminderData);

                if (success) {
                    // 清除待处理的批量编辑信息
                    this.clearPendingBulkEditWithoutLog();
                    this.closeAllModals();
                    // 移除提示消息：this.showNotification('已创建新的重复提醒系列', 'success');
                } else {
                    this.showNotification('创建新系列失败', 'error');
                }
            } else {
                // 执行批量编辑
                const success = await reminderManager.performBulkOperation(seriesId, 'edit', scope, fromTime, reminderId, reminderData);

                if (success) {
                    // 清除待处理的批量编辑信息
                    this.clearPendingBulkEditWithoutLog();
                    this.closeAllModals();
                    // 移除提示消息：this.showNotification('批量编辑成功', 'success');
                } else {
                    this.showNotification('批量编辑失败', 'error');
                }
            }
        } else {
            // 单独更新
            console.log('DEBUG: About to call updateReminder with:', this.currentReminderId, reminderData);
            const success = await reminderManager.updateReminder(this.currentReminderId, reminderData);

            if (success) {
                this.closeAllModals();
            } else {
                this.showNotification('提醒更新失败', 'error');
            }
        }
    }

    // === 工具方法 ===

    // 清除事件表单
    clearEventForm() {
        document.getElementById('newEventTitle').value = '';
        document.getElementById('newEventDescription').value = '';
        document.getElementById('newEventImportance').value = '';
        document.getElementById('newEventUrgency').value = '';

        // 清除重要性紧急性按钮选择
        document.querySelectorAll('.matrix-button').forEach(btn => {
            btn.classList.remove('selected');
        });

        // 清除RRule设置
        const repeatCheckbox = document.getElementById('newEventIsRecurring');
        if (repeatCheckbox) {
            repeatCheckbox.checked = false;
        }
        
        if (window.rruleManager) {
            window.rruleManager.toggleRepeatOptions('create');
        }
    }

    // 清除待办表单
    clearTodoForm() {
        document.getElementById('newTodoTitle').value = '';
        document.getElementById('newTodoDescription').value = '';
        document.getElementById('newTodoDueDate').value = '';
        document.getElementById('newTodoEstimatedDuration').value = '';
        document.getElementById('newTodoImportance').value = 'medium';
        document.getElementById('newTodoUrgency').value = 'normal';
    }

    // 清除提醒表单
    clearReminderForm() {
        document.getElementById('newReminderTitle').value = '';
        document.getElementById('newReminderContent').value = '';
        document.getElementById('newReminderTriggerTime').value = '';
        document.getElementById('newReminderPriority').value = 'normal';

        // 重置重复提醒UI
        document.getElementById('newReminderRepeat').checked = false;
        toggleRepeatOptions('new');

        // 重置所有重复选项
        document.getElementById('newRepeatFreq').value = 'DAILY';
        document.getElementById('newRepeatInterval').value = '1';
        document.getElementById('newRepeatUntil').value = '';
        document.getElementById('newMonthlyType').value = 'bymonthday';

        // 取消选择所有星期几选项
        ['newMO', 'newTU', 'newWE', 'newTH', 'newFR', 'newSA', 'newSU'].forEach(id => {
            document.getElementById(id).checked = false;
        });

        updateRepeatOptions('new');
    }

    // 填充日程组选择器
    populateGroupSelect(selectId, selectedGroupId = '') {
        const select = document.getElementById(selectId);
        if (!select) return;

        select.innerHTML = '<option value="">无</option>';

        if (window.events_groups) {
            window.events_groups.forEach(group => {
                const option = document.createElement('option');
                option.value = group.id;
                option.text = group.name;
                if (group.id === selectedGroupId) {
                    option.selected = true;
                }
                select.appendChild(option);
            });
        }
    }

    // 设置重要性紧急性
    setImportanceUrgency(importance, urgency, mode = 'create') {
        const prefix = mode === 'create' ? 'newEvent' : 'event';

        document.getElementById(`${prefix}Importance`).value = importance || '';
        document.getElementById(`${prefix}Urgency`).value = urgency || '';

        // 更新按钮状态
        document.querySelectorAll('.matrix-button').forEach(btn => {
            btn.classList.remove('selected');
            if (btn.dataset.importance === importance && btn.dataset.urgency === urgency) {
                btn.classList.add('selected');
            }
        });
    }

    // 时间格式转换
    toLocalTime(timeStr) {
        const date = new Date(timeStr);
        // 获取本地时间并格式化为 YYYY-MM-DDTHH:MM 格式
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');
        return `${year}-${month}-${day}T${hours}:${minutes}`;
    }

    toUTC(timeStr) {
        // 不做时区转换，直接使用本地时间
        // 如果时间字符串没有秒，直接添加秒
        if (timeStr && timeStr.match(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/)) {
            // 格式：YYYY-MM-DDTHH:MM，添加秒
            return timeStr + ':00';
        }
        
        // 如果已经是完整格式，直接返回
        if (timeStr && timeStr.match(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/)) {
            return timeStr;
        }
        
        // 如果是其他格式，尝试解析并返回本地时间
        if (timeStr) {
            try {
                const date = new Date(timeStr);
                // 使用本地时间格式，不转换为UTC
                const year = date.getFullYear();
                const month = String(date.getMonth() + 1).padStart(2, '0');
                const day = String(date.getDate()).padStart(2, '0');
                const hour = String(date.getHours()).padStart(2, '0');
                const minute = String(date.getMinutes()).padStart(2, '0');
                const second = String(date.getSeconds()).padStart(2, '0');
                
                return `${year}-${month}-${day}T${hour}:${minute}:${second}`;
            } catch (e) {
                console.error('Failed to parse time:', timeStr, e);
                return timeStr;
            }
        }
        
        return timeStr;
    }

    // 获取事件表单数据
    getEventFormData(mode = 'create') {
        const prefix = mode === 'create' ? 'newEvent' : 'event';

        // 获取基本数据
        let startTime = document.getElementById(`${prefix}Start`).value;
        let endTime = document.getElementById(`${prefix}End`).value;
        
        // 如果是编辑模式且有批量编辑状态，检查是否需要从自定义时间控件获取值
        const pendingBulkEdit = window.eventManager && window.eventManager.pendingBulkEdit;
        if (mode === 'edit' && pendingBulkEdit && pendingBulkEdit.scope === 'all') {
            // 检查是否有自定义时间控件
            const startTimeOnly = document.getElementById('eventStartTimeOnly');
            const endTimeOnly = document.getElementById('eventEndTimeOnly');
            const originalStartDateTime = document.getElementById('eventStart').value;
            const originalEndDateTime = document.getElementById('eventEnd').value;

            if (startTimeOnly && originalStartDateTime) {
                const [startDatePart] = originalStartDateTime.split('T');
                startTime = `${startDatePart}T${startTimeOnly.value}`;
            }

            if (endTimeOnly && originalEndDateTime) {
                const [endDatePart] = originalEndDateTime.split('T');
                endTime = `${endDatePart}T${endTimeOnly.value}`;
            }
        }

        const data = {
            title: document.getElementById(`${prefix}Title`).value,
            start: startTime,
            end: endTime,
            description: document.getElementById(`${prefix}Description`).value,
            importance: document.getElementById(`${prefix}Importance`).value,
            urgency: document.getElementById(`${prefix}Urgency`).value,
            groupID: document.getElementById(`${prefix}GroupId`).value,
            ddl: document.getElementById(`${mode === 'create' ? 'creatEvent' : 'event'}Ddl`).value
        };

        // 添加RRule支持
        if (window.rruleManager) {
            data.rrule = window.rruleManager.buildRRule(mode);
        }

        return data;
    }

    // 获取待办表单数据
    getTodoFormData(mode = 'create') {
        const prefix = mode === 'create' ? 'newTodo' : 'todo';

        return {
            title: document.getElementById(`${prefix}Title`).value,
            description: document.getElementById(`${prefix}Description`).value,
            due_date: document.getElementById(`${prefix}DueDate`).value,
            estimated_duration: document.getElementById(`${prefix}EstimatedDuration`).value,
            importance: document.getElementById(`${prefix}Importance`).value,
            urgency: document.getElementById(`${prefix}Urgency`).value,
            groupID: document.getElementById(`${prefix}GroupId`).value
        };
    }

    // 获取提醒表单数据
    getReminderFormData(mode = 'create') {
        const prefix = mode === 'create' ? 'newReminder' : 'reminder';

        // 获取时间值，考虑自定义时间控件
        let triggerTime = document.getElementById(`${prefix}TriggerTime`).value;
        const pendingBulkEdit = reminderManager.pendingBulkEdit;

        // 如果使用了自定义时间控件，从自定义控件获取时间
        if (mode === 'edit' && pendingBulkEdit && 
            (pendingBulkEdit.scope === 'all' || 
             (pendingBulkEdit.scope === 'from_this' || pendingBulkEdit.scope === 'from_time'))) {
            const timeOnlyInput = document.getElementById('reminderTimeOnly');
            const originalDateTime = document.getElementById('reminderTriggerTime').value;

            if (timeOnlyInput && originalDateTime) {
                const [datePart] = originalDateTime.split('T');
                triggerTime = `${datePart}T${timeOnlyInput.value}`;
            }
        }

        const data = {
            title: document.getElementById(`${prefix}Title`).value,
            content: document.getElementById(`${prefix}Content`).value,
            trigger_time: triggerTime,
            priority: document.getElementById(`${prefix}Priority`).value
        };

        // 检查是否是"仅此条提醒"的编辑模式
        if (mode === 'edit' && pendingBulkEdit && pendingBulkEdit.scope === 'this_only') {
            // 仅此条提醒：强制设置为空RRule，表示脱离重复组
            data.rrule = '';
        } else if (mode === 'edit' && pendingBulkEdit && 
                  (pendingBulkEdit.scope === 'from_this' || pendingBulkEdit.scope === 'from_time')) {
            // 检查是否是完整编辑模式
            const editModal = document.getElementById('editReminderModal');
            const isFullEdit = editModal && editModal.getAttribute('data-full-edit') === 'true';
            
            console.log('DEBUG: Checking full edit mode, isFullEdit =', isFullEdit);
            
            if (isFullEdit) {
                // 完整编辑模式：构建新的RRule，这将创建新系列
                data.rrule = buildRruleFromUI('edit');
                // 标记为完整编辑，后端会创建新系列
                data.create_new_series = true;
                console.log('DEBUG: Setting create_new_series = true, rrule =', data.rrule);
            } else {
                // 默认模式：保持原始重复规则不变，只允许修改时间等基本属性
                // 不构建新的RRule，这样就不会触发重复规则变化检测
                const originalReminder = reminderManager.reminders.find(r => 
                    r.id.toString() === pendingBulkEdit.reminderId || 
                    r.id === pendingBulkEdit.reminderId
                );
                data.rrule = originalReminder ? originalReminder.rrule : '';
            }
        } else {
            // 其他模式：正常构建RRule
            data.rrule = buildRruleFromUI(mode === 'create' ? 'new' : 'edit');
        }

        return data;
    }

    // 验证表单
    validateEventForm(mode) {
        const data = this.getEventFormData(mode);
        
        // 基本验证
        if (!data.title.trim() || !data.start || !data.end) {
            return false;
        }

        // RRule验证
        if (window.rruleManager && !window.rruleManager.validateRRuleSettings(mode)) {
            return false;
        }

        return true;
    }

    validateTodoForm(mode) {
        const data = this.getTodoFormData(mode);
        return data.title.trim();
    }

    validateReminderForm(mode) {
        const data = this.getReminderFormData(mode);
        if (!data.title.trim() || !data.trigger_time) {
            return false;
        }

        // 如果是编辑模式且处于"更改重复规则"状态，需要额外验证
        if (mode === 'edit') {
            const editModal = document.getElementById('editReminderModal');
            const isFullEdit = editModal && editModal.getAttribute('data-full-edit') === 'true';
            
            // 移除强制截止时间的验证，允许无限重复到无限重复的转换
            
            if (isFullEdit && data.is_recurring && data.create_new_series) {
                // "更改重复规则"模式：移除强制截止时间要求，允许后端处理无限重复转换
                console.log('DEBUG: Full edit mode with new series creation - allowing unlimited recurring rules');
            }
        }
        
        return true;
    }

    // 显示通知
    showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.innerHTML = `
            <div class="notification-content">
                <div class="notification-message">${message}</div>
            </div>
            <button class="notification-close" onclick="this.parentElement.remove()">×</button>
        `;

        document.body.appendChild(notification);

        setTimeout(() => {
            if (notification.parentElement) {
                notification.remove();
            }
        }, 3000);
    }
}

// 重要性紧急性矩阵按钮点击处理
function setImportanceUrgency(importance, urgency, button) {
    const isAlreadySelected = button.classList.contains('selected');

    // 清除所有按钮的选中状态
    document.querySelectorAll('.matrix-button').forEach(btn => {
        btn.classList.remove('selected');
    });

    if (!isAlreadySelected) {
        button.classList.add('selected');

        // 设置隐藏字段值
        const importanceField = document.querySelector('input[id$="Importance"]');
        const urgencyField = document.querySelector('input[id$="Urgency"]');

        if (importanceField) importanceField.value = importance;
        if (urgencyField) urgencyField.value = urgency;
    } else {
        // 清除隐藏字段值
        const importanceField = document.querySelector('input[id$="Importance"]');
        const urgencyField = document.querySelector('input[id$="Urgency"]');

        if (importanceField) importanceField.value = '';
        if (urgencyField) urgencyField.value = '';
    }
}

// 导出模态框管理器实例
// modalManager实例将在HTML中创建
