// 模态框管理模块
class ModalManager {
    constructor() {
        this.currentEventId = null;
        this.currentTodoId = null;
        this.currentReminderId = null;
        this.forceUntilRequired = false; // 强制要求设置截止时间标记
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
        const modal = document.getElementById('editEventModal');
        this.currentEventId = event.id;

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

        this.showModal('editEventModal');
    }

    // 处理创建事件
    async handleCreateEvent() {
        if (!this.validateEventForm('create')) return;

        const eventData = this.getEventFormData('create');
        // 将时间转换为UTC再发送给后端
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
    }

    // 处理更新事件
    async handleUpdateEvent() {
        if (!this.validateEventForm('edit')) return;

        const eventData = this.getEventFormData('edit');
        const success = await eventManager.updateEvent(
            this.currentEventId,
            this.toUTC(eventData.start),
            this.toUTC(eventData.end),
            eventData.title,
            eventData.description,
            eventData.importance,
            eventData.urgency,
            eventData.groupId,
            eventData.ddl
        );

        if (success) {
            this.closeAllModals();
        } else {
            this.showNotification('事件更新失败', 'error');
        }
    }

    // 处理删除事件
    async handleDeleteEvent() {
        if (!confirm('确定要删除这个事件吗？')) return;

        const success = await eventManager.deleteEvent(this.currentEventId);

        if (success) {
            this.closeAllModals();
        } else {
            this.showNotification('事件删除失败', 'error');
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

        // 使用新的重复提醒UI填充RRULE数据
        parseRruleToUI(reminder.rrule || '', 'edit');

        // 根据批量编辑范围设置字段的启用/禁用状态
        this.configureEditFieldsBasedOnScope();

        this.showModal('editReminderModal');
    }

    // 根据批量编辑范围配置字段的启用/禁用状态
    configureEditFieldsBasedOnScope() {
        const pendingBulkEdit = reminderManager.pendingBulkEdit;
        console.log('configureEditFieldsBasedOnScope called, pendingBulkEdit:', pendingBulkEdit);

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
                this.enableAllEditFields();
                
                // 默认状态：类似"all"模式 - 不能更改重复规则，只能更改时间
                this.configureFromThisDefaultMode();
                
                // 添加"更改重复规则"按钮
                this.addChangeRuleButton();
                break;
        }
    }

    // 启用所有编辑字段
    enableAllEditFields() {
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
        
        // 检查当前提醒是否为无截止时间的重复提醒
        const pendingBulkEdit = reminderManager.pendingBulkEdit;
        if (pendingBulkEdit && (pendingBulkEdit.scope === 'from_this' || pendingBulkEdit.scope === 'from_time')) {
            // 找到当前编辑的提醒
            const currentReminder = reminderManager.reminders.find(r => r.id === pendingBulkEdit.reminderId);
            if (currentReminder && currentReminder.rrule && !currentReminder.rrule.includes('UNTIL=')) {
                // 这是一个无截止时间的重复提醒，需要强制用户设置截止时间
                const userChoice = confirm(
                    '您正在修改无截止时间的重复提醒。\n\n' +
                    '为避免产生冲突的重复实例，修改重复规则时必须设置结束时间。\n\n' +
                    '点击"确定"继续修改（需要设置结束时间）\n' +
                    '点击"取消"保持原有规则'
                );
                
                if (!userChoice) {
                    console.log('DEBUG: User cancelled full edit mode for unlimited series');
                    return; // 用户取消，不启用完整编辑模式
                }
                
                // 用户选择继续，标记需要强制设置截止时间
                this.forceUntilRequired = true;
                console.log('DEBUG: Marked until as required for unlimited series edit');
            }
        }
        
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

        // 检查是否为无限重复系列的修改，如果是则阻止提交
        if (this.forceUntilRequired) {
            // 检查当前构建的RRule是否仍然是无限重复的
            const currentRrule = reminderData.rrule;
            const isCurrentlyUnlimited = currentRrule && 
                                       currentRrule.includes('FREQ=') && 
                                       !currentRrule.includes('UNTIL=') && 
                                       !currentRrule.includes('COUNT=');
            
            console.log('DEBUG: forceUntilRequired validation - currentRrule:', currentRrule, 'isCurrentlyUnlimited:', isCurrentlyUnlimited);
            
            if (isCurrentlyUnlimited) {
                const message = '❌ 无法提交：正在修改无限重复的提醒系列\n\n💡 请设置结束条件：\n• 设置"截止日期"（推荐）\n• 或设置"重复次数"\n\n然后再提交修改';
                this.showNotification(message, 'error');
                alert(message); // 确保用户能看到提示
                return; // 阻止提交
            }
        }

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
                    this.showNotification('已创建新的重复提醒系列', 'success');
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
                    this.showNotification('批量编辑成功', 'success');
                } else {
                    this.showNotification('批量编辑失败', 'error');
                }
            }
        } else {
            // 单独更新
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
        const date = new Date(timeStr);
        return date.toISOString();
    }

    // 获取事件表单数据
    getEventFormData(mode = 'create') {
        const prefix = mode === 'create' ? 'newEvent' : 'event';

        return {
            title: document.getElementById(`${prefix}Title`).value,
            start: document.getElementById(`${prefix}Start`).value,
            end: document.getElementById(`${prefix}End`).value,
            description: document.getElementById(`${prefix}Description`).value,
            importance: document.getElementById(`${prefix}Importance`).value,
            urgency: document.getElementById(`${prefix}Urgency`).value,
            groupId: document.getElementById(`${prefix}GroupId`).value,
            ddl: document.getElementById(`${mode === 'create' ? 'creatEvent' : 'event'}Ddl`).value
        };
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
        return data.title.trim() && data.start && data.end;
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
            
            // 检查是否强制要求设置截止时间（针对无截止时间的重复提醒）
            if (this.forceUntilRequired && data.is_recurring) {
                const untilField = document.getElementById('repeatUntil');
                if (!untilField || !untilField.value.trim()) {
                    this.showNotification('修改无截止时间的重复提醒规则时，必须设置截止时间以避免产生冲突的重复实例', 'error');
                    return false;
                }
            }
            
            if (isFullEdit && data.is_recurring && data.create_new_series) {
                // "更改重复规则"模式：必须设置截止时间
                const untilField = document.getElementById('repeatUntil');
                if (!untilField || !untilField.value.trim()) {
                    this.showNotification('更改重复规则时必须设置截止时间，以便系统正确管理重复提醒', 'error');
                    return false;
                }
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
