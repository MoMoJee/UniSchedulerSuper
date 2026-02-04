// 待办事项管理模块
class TodoManager {
    constructor() {
        this.todos = [];
        this.todoContainer = null;
        this.currentViewMode = 'list'; // 'list' 或 'quadrant'
        this.dropZonesInitialized = false; // 标志位：放置区是否已初始化
    }

    // 初始化待办事项管理器
    init() {
        this.todoContainer = document.getElementById('todoList');
        
        // 从设置加载视图模式
        const savedMode = window.settingsManager?.settings?.todoViewMode || 'list';
        this.currentViewMode = savedMode;
        
        this.loadTodos();
        this.initDragDrop();
        this.initFilters();
        this.updateViewModeUI();
        
        // 不在这里检查布局，等待 setLayout 从设置中触发
        // 这样可以避免使用默认宽度进行错误判断
        
        // 监听窗口大小变化
        window.addEventListener('resize', () => {
            if (this.currentViewMode === 'quadrant') {
                this.adjustQuadrantLayout();
            }
        });
    }

    // 切换筛选下拉框显示
    toggleFilterDropdown() {
        const dropdown = document.getElementById('todoFilterDropdown');
        if (dropdown) {
            if (dropdown.style.display === 'none') {
                dropdown.style.display = 'block';
            } else {
                dropdown.style.display = 'none';
            }
        }
    }

    // 初始化筛选功能
    initFilters() {
        // 绑定优先级筛选复选框事件
        const priorityCheckboxes = document.querySelectorAll('#todoPriorityFilterList input[type="checkbox"]');
        priorityCheckboxes.forEach(checkbox => {
            checkbox.addEventListener('change', () => {
                console.log('待办优先级筛选变化');
                this.applyFilters();
                // 保存筛选状态
                if (window.settingsManager) {
                    const selectedValues = Array.from(priorityCheckboxes)
                        .filter(cb => cb.checked)
                        .map(cb => cb.value);
                    window.settingsManager.onTodoFilterChange('priorities', selectedValues);
                }
            });
        });

        // 加载日程组选项
        this.loadGroupOptions();
        
        // 点击外部关闭筛选下拉框
        document.addEventListener('click', (e) => {
            const dropdown = document.getElementById('todoFilterDropdown');
            const filterBtn = e.target.closest('button[onclick*="toggleFilterDropdown"]');
            if (dropdown && dropdown.style.display === 'block' && !dropdown.contains(e.target) && !filterBtn) {
                dropdown.style.display = 'none';
            }
        });
        
        console.log('待办筛选器已初始化');
    }

    // 加载日程组选项
    loadGroupOptions() {
        console.log('=== 加载日程组选项 ===');
        const groupFilterList = document.getElementById('todoGroupFilterList');
        if (!groupFilterList) {
            console.log('groupFilterList 元素不存在');
            return;
        }
        
        if (!window.groupManager) {
            console.log('groupManager 不可用');
            return;
        }

        // 【关键】保存当前筛选状态（在重新生成控件前）
        const currentGroupFilter = Array.from(groupFilterList.querySelectorAll('input[type="checkbox"]:checked'))
            .map(cb => cb.value);
        console.log('保存当前日程组筛选状态:', currentGroupFilter);

        // 清空现有选项
        groupFilterList.innerHTML = '';

        // 从 settingsManager 获取保存的筛选状态（如果有）
        let savedGroupFilter = currentGroupFilter;
        if (window.settingsManager && window.settingsManager.settings && window.settingsManager.settings.todoFilters) {
            const savedFilters = window.settingsManager.settings.todoFilters.groups;
            if (savedFilters && savedFilters.length > 0) {
                savedGroupFilter = savedFilters;
                console.log('从 settingsManager 恢复日程组筛选:', savedGroupFilter);
            }
        }

        // 添加"无日程组"选项
        const noneDiv = document.createElement('div');
        noneDiv.className = 'form-check';
        const noneChecked = savedGroupFilter.length === 0 || savedGroupFilter.includes('none');
        noneDiv.innerHTML = `
            <input class="form-check-input" type="checkbox" value="none" id="todoGroup_none" ${noneChecked ? 'checked' : ''}>
            <label class="form-check-label" for="todoGroup_none">📋 其他</label>
        `;
        groupFilterList.appendChild(noneDiv);

        // 添加所有日程组
        const groups = window.groupManager.getAllGroups();
        console.log('获取到的日程组数量:', groups.length);
        console.log('日程组数据:', groups);
        
        groups.forEach(group => {
            console.log('添加日程组选项:', group.name, group.id, group.color);
            const groupDiv = document.createElement('div');
            groupDiv.className = 'form-check';
            // 【关键】根据保存的筛选状态设置复选框
            const isChecked = savedGroupFilter.length === 0 || savedGroupFilter.includes(group.id);
            groupDiv.innerHTML = `
                <input class="form-check-input" type="checkbox" value="${group.id}" id="todoGroup_${group.id}" ${isChecked ? 'checked' : ''}>
                <label class="form-check-label" for="todoGroup_${group.id}">
                    <span style="display:inline-block;width:10px;height:10px;background-color:${group.color};margin-right:5px;border-radius:2px;"></span>
                    ${group.name}
                </label>
            `;
            groupFilterList.appendChild(groupDiv);
        });

        // 绑定日程组筛选复选框事件
        const groupCheckboxes = groupFilterList.querySelectorAll('input[type="checkbox"]');
        console.log('绑定了', groupCheckboxes.length, '个复选框事件');
        groupCheckboxes.forEach(checkbox => {
            checkbox.addEventListener('change', () => {
                console.log('待办日程组筛选变化');
                this.applyFilters();
                // 保存筛选状态
                if (window.settingsManager) {
                    const selectedValues = Array.from(groupCheckboxes)
                        .filter(cb => cb.checked)
                        .map(cb => cb.value);
                    window.settingsManager.onTodoFilterChange('groups', selectedValues);
                }
            });
        });
    }

    // 应用筛选和排序
    applyFilters() {
        console.log('=== 应用筛选 ===');
        console.log('当前视图模式:', this.currentViewMode);
        
        // 如果是象限视图，直接重新渲染象限视图
        if (this.currentViewMode === 'quadrant') {
            console.log('象限视图模式，调用 renderQuadrantView()');
            this.renderQuadrantView();
            return;
        }
        
        // 以下是列表视图的筛选逻辑
        // 从复选框读取筛选条件
        const priorityCheckboxes = document.querySelectorAll('#todoPriorityFilterList input[type="checkbox"]:checked');
        const groupCheckboxes = document.querySelectorAll('#todoGroupFilterList input[type="checkbox"]:checked');
        
        console.log('已选中的优先级:', Array.from(priorityCheckboxes).map(cb => cb.value));
        console.log('已选中的日程组:', Array.from(groupCheckboxes).map(cb => cb.value));
        
        let filteredTodos = [...this.todos];
        console.log('初始 TODO 数量:', filteredTodos.length);
        
        // 优先级筛选（重要性+紧急性）
        if (priorityCheckboxes.length > 0) {
            const selectedPriorities = Array.from(priorityCheckboxes).map(cb => cb.value);
            filteredTodos = filteredTodos.filter(todo => {
                const priority = this.getTodoPriorityType(todo.importance, todo.urgency);
                return selectedPriorities.includes(priority);
            });
            console.log('优先级筛选后 TODO 数量:', filteredTodos.length);
        }
        
        // 日程组筛选
        if (groupCheckboxes.length > 0) {
            const selectedGroups = Array.from(groupCheckboxes).map(cb => cb.value);
            filteredTodos = filteredTodos.filter(todo => {
                console.log('检查 TODO:', todo.title, 'groupID:', todo.groupID);
                
                // 检查是否属于"无日程组"类别
                const hasNoGroup = !todo.groupID || todo.groupID === '';
                const noneSelected = selectedGroups.includes('none');
                
                // 检查是否属于某个选中的日程组
                const groupMatched = todo.groupID && selectedGroups.includes(todo.groupID);
                
                // 如果选中了"无日程组"，且 TODO 确实无日程组，则匹配
                if (noneSelected && hasNoGroup) {
                    console.log('  -> 匹配"无日程组"');
                    return true;
                }
                
                // 如果 TODO 属于某个选中的日程组，则匹配
                if (groupMatched) {
                    console.log('  -> 匹配日程组:', todo.groupID);
                    return true;
                }
                
                console.log('  -> 不匹配任何选中的筛选条件');
                return false;
            });
            console.log('日程组筛选后 TODO 数量:', filteredTodos.length);
        }
        
        // 默认按到期时间排序
        filteredTodos.sort((a, b) => {
            const dateA = a.due_date ? new Date(a.due_date) : new Date('9999-12-31');
            const dateB = b.due_date ? new Date(b.due_date) : new Date('9999-12-31');
            return dateA - dateB;
        });
        
        this.renderFilteredTodos(filteredTodos);
    }

    // 获取TODO的优先级类型
    getTodoPriorityType(importance, urgency) {
        if (importance === 'important' && urgency === 'urgent') {
            return 'important-urgent';
        } else if (importance === 'important' && urgency === 'not-urgent') {
            return 'important-not-urgent';
        } else if (importance === 'not-important' && urgency === 'urgent') {
            return 'not-important-urgent';
        } else if (importance === 'not-important' && urgency === 'not-urgent') {
            return 'not-important-not-urgent';
        } else {
            return 'unspecified';
        }
    }

    // 渲染筛选后的待办事项
    renderFilteredTodos(todos) {
        if (!this.todoContainer) return;
        
        this.todoContainer.innerHTML = '';

        if (todos.length === 0) {
            this.todoContainer.innerHTML = '<div class="empty-state">暂无符合条件的待办事项</div>';
            return;
        }

        todos.forEach(todo => {
            const todoElement = this.createTodoElement(todo);
            this.todoContainer.appendChild(todoElement);
        });
    }

    // 加载待办事项
    async loadTodos() {
        try {
            const response = await fetch('/api/todos/');
            const data = await response.json();
            this.todos = data.todos || [];
            console.log('=== 加载的 TODOs 数据 ===');
            console.log('TODOs 数量:', this.todos.length);
            if (this.todos.length > 0) {
                console.log('第一个 TODO 示例:', this.todos[0]);
                console.log('groupID 字段:', this.todos[0].groupID);
            }
            
            // 重新加载日程组选项（确保在 groupManager 初始化后）
            this.loadGroupOptions();
            
            // 【关键修复】调用 applyFilters() 而非 renderTodos()，以保持筛选参数
            this.applyFilters();
        } catch (error) {
            console.error('Error loading todos:', error);
            this.todos = [];
            this.applyFilters();
        }
    }

    // 渲染待办事项列表
    renderTodos() {
        if (this.currentViewMode === 'quadrant') {
            // 渲染四象限视图
            this.renderQuadrantView();
        } else {
            // 渲染列表视图（使用筛选方法）
            this.applyFilters();
        }
    }

    // 创建待办事项元素
    createTodoElement(todo) {
        console.log('创建 TODO 元素:', todo.id, 'groupID:', todo.groupID);
        
        const div = document.createElement('div');
        div.className = `todo-item ${this.getPriorityClass(todo.importance, todo.urgency)}`;
        div.draggable = true;
        div.dataset.todoId = todo.id;
        
        // 如果有日程组，应用日程组颜色
        if (todo.groupID && window.groupManager) {
            console.log('TODO 有 groupID:', todo.groupID);
            const group = window.groupManager.getGroupById(todo.groupID);
            console.log('找到的日程组:', group);
            if (group) {
                div.style.borderLeft = `4px solid ${group.color}`;
                console.log('应用颜色线:', group.color);
            }
        } else {
            console.log('TODO 无 groupID 或 groupManager 不可用');
        }
        
        const priorityIcon = this.getPriorityIcon(todo.importance, todo.urgency);
        const dueDateStr = todo.due_date ? this.formatDueDate(todo.due_date) : '';
        
        div.innerHTML = `
            <div class="todo-content">
                <div class="todo-header">
                    <span class="todo-priority">${priorityIcon}</span>
                    <span class="todo-title">${this.escapeHtml(todo.title)}</span>
                    <div class="todo-actions">
                        <button class="btn-small" onclick="todoManager.editTodo('${todo.id}')">编辑</button>
                        <button class="btn-small btn-danger" onclick="todoManager.deleteTodo('${todo.id}')">删除</button>
                    </div>
                </div>
                ${todo.description ? `<div class="todo-description">${this.escapeHtml(todo.description)}</div>` : ''}
                <div class="todo-meta">
                    ${todo.estimated_duration ? `<span class="todo-duration">预计: ${todo.estimated_duration}</span>` : ''}
                    ${dueDateStr ? `<span class="todo-due-date">截止: ${dueDateStr}</span>` : ''}
                </div>
            </div>
        `;

        // 添加拖拽事件
        div.addEventListener('dragstart', (e) => {
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', JSON.stringify({
                type: 'todo',
                id: todo.id,
                title: todo.title,
                groupID: todo.groupID || '',
                description: todo.description || '',
                dueDate: todo.due_date || '',
                estimatedDuration: todo.estimated_duration || '',
                importance: todo.importance || '',
                urgency: todo.urgency || ''
            }));
            
            // 添加拖拽视觉效果
            e.target.style.opacity = '0.5';
        });
        
        div.addEventListener('dragend', (e) => {
            // 恢复透明度
            e.target.style.opacity = '1';
        });

        // 添加点击事件查看详情（排除按钮区域）
        const todoContent = div.querySelector('.todo-content');
        console.log('Setting up click event for todo:', todo.id, 'todoContent found:', !!todoContent);
        if (todoContent) {
            const handleTodoClick = (e) => {
                console.log('TODO content clicked, target:', e.target, 'closest .todo-actions:', e.target.closest('.todo-actions'));
                // 如果点击的是按钮或按钮内的元素，不触发详情查看
                if (e.target.closest('.todo-actions')) {
                    console.log('Click on action buttons, ignoring');
                    return;
                }
                // 阻止事件冒泡和默认行为
                e.preventDefault();
                e.stopPropagation();
                console.log('Opening todo detail modal for:', todo.id);
                this.openTodoDetailModal(todo);
            };
            
            // 同时监听click和touchend事件以支持触屏
            todoContent.addEventListener('click', handleTodoClick);
            todoContent.addEventListener('touchend', handleTodoClick);
            
            // 添加鼠标样式提示可点击
            todoContent.style.cursor = 'pointer';
        }

        return div;
    }

    // 获取优先级类名（基于重要性和紧急性）
    getPriorityClass(importance, urgency) {
        // 根据四象限分类
        if (importance === 'important' && urgency === 'urgent') {
            return 'high-priority';  // 重要紧急
        } else if (importance === 'important' && urgency === 'not-urgent') {
            return 'medium-priority';  // 重要不紧急
        } else if (importance === 'not-important' && urgency === 'urgent') {
            return 'medium-priority';  // 不重要紧急
        } else {
            return 'low-priority';  // 不重要不紧急
        }
    }

    // 获取优先级图标（基于重要性和紧急性）
    getPriorityIcon(importance, urgency) {
        // 根据四象限分类
        if (importance === 'important' && urgency === 'urgent') {
            return '🔴';  // 重要紧急 - 红色
        } else if (importance === 'important' && urgency === 'not-urgent') {
            return '🟡';  // 重要不紧急 - 黄色
        } else if (importance === 'not-important' && urgency === 'urgent') {
            return '🟠';  // 不重要紧急 - 橙色
        } else if (importance === 'not-important' && urgency === 'not-urgent') {
            return '🟢';  // 不重要不紧急 - 绿色
        } else {
            return '⚪';  // 未设定优先级 - 灰色
        }
    }

    // 格式化截止日期
    formatDueDate(dateStr) {
        const date = new Date(dateStr);
        const now = new Date();
        const diff = date - now;
        const days = Math.ceil(diff / (1000 * 60 * 60 * 24));
        
        if (days < 0) {
            return `已过期 ${Math.abs(days)} 天`;
        } else if (days === 0) {
            return '今天截止';
        } else if (days === 1) {
            return '明天截止';
        } else {
            return `${days} 天后截止`;
        }
    }

    // 转义HTML
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // 初始化拖拽功能
    initDragDrop() {
        // 这里可以添加拖拽到日历的功能
        // 与FullCalendar的external events集成
    }

    // 创建新待办事项
    async createTodo(todoData) {
        try {
            const response = await fetch('/api/todos/create/', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.CSRF_TOKEN 
                },
                body: JSON.stringify(todoData)
            });
            
            if (response.ok) {
                await this.loadTodos();
                return true;
            }
        } catch (error) {
            console.error('Error creating todo:', error);
        }
        return false;
    }

    // 更新待办事项
    async updateTodo(todoId, todoData) {
        try {
            const response = await fetch('/api/todos/update/', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.CSRF_TOKEN 
                },
                body: JSON.stringify({ id: todoId, ...todoData })
            });
            
            if (response.ok) {
                await this.loadTodos();
                return true;
            }
        } catch (error) {
            console.error('Error updating todo:', error);
        }
        return false;
    }

    // 删除待办事项
    async deleteTodo(todoId, silent = false) {
        if (!silent && !confirm('确定要删除这个待办事项吗？')) {
            return false;
        }

        try {
            const response = await fetch(`/api/todos/delete/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({ id: todoId })
            });
            
            if (response.ok) {
                await this.loadTodos();
                return true;
            }
        } catch (error) {
            console.error('Error deleting todo:', error);
        }
        return false;
    }

    // 编辑待办事项
    editTodo(todoId) {
        const todo = this.todos.find(t => t.id === todoId);
        if (todo) {
            modalManager.openEditTodoModal(todo);
        }
    }

    // 打开TODO详情模态框
    openTodoDetailModal(todo) {
        console.log('openTodoDetailModal called with todo:', todo);
        const modal = document.getElementById('todoDetailModal');
        console.log('Modal element found:', !!modal);
        if (!modal) {
            console.error('TODO详情模态框不存在');
            return;
        }

        // 设置标题
        const titleElement = document.getElementById('todoDetailTitle');
        if (titleElement) {
            titleElement.textContent = todo.title;
            console.log('Title set to:', todo.title);
        }

        // 设置优先级
        const priorityElement = document.getElementById('todoDetailPriority');
        if (priorityElement) {
            const icon = this.getPriorityIcon(todo.importance, todo.urgency);
            const priorityText = this.getPriorityText(todo.importance, todo.urgency);
            priorityElement.innerHTML = `${icon} ${priorityText}`;
        }

        // 设置日程组
        const groupElement = document.getElementById('todoDetailGroup');
        const groupRow = document.getElementById('todoDetailGroupRow');
        if (todo.groupID && window.groupManager) {
            const group = window.groupManager.getGroupById(todo.groupID);
            if (group && groupElement && groupRow) {
                groupElement.textContent = group.name;
                groupElement.style.color = group.color;
                groupRow.style.display = 'flex';
            }
        } else if (groupRow) {
            groupRow.style.display = 'none';
        }

        // 设置描述
        const descElement = document.getElementById('todoDetailDescription');
        const descRow = document.getElementById('todoDetailDescriptionRow');
        if (todo.description && descElement && descRow) {
            descElement.textContent = todo.description;
            descRow.style.display = 'flex';
        } else if (descRow) {
            descRow.style.display = 'none';
        }

        // 设置预计耗时
        const durationElement = document.getElementById('todoDetailDuration');
        const durationRow = document.getElementById('todoDetailDurationRow');
        if (todo.estimated_duration && durationElement && durationRow) {
            durationElement.textContent = todo.estimated_duration;
            durationRow.style.display = 'flex';
        } else if (durationRow) {
            durationRow.style.display = 'none';
        }

        // 设置截止时间
        const dueDateElement = document.getElementById('todoDetailDueDate');
        const dueDateRow = document.getElementById('todoDetailDueDateRow');
        if (todo.due_date && dueDateElement && dueDateRow) {
            const formattedDate = new Date(todo.due_date).toLocaleString('zh-CN', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
            dueDateElement.textContent = formattedDate;
            dueDateRow.style.display = 'flex';
        } else if (dueDateRow) {
            dueDateRow.style.display = 'none';
        }

        // 设置按钮的todo ID
        const editBtn = document.getElementById('todoDetailEditBtn');
        const deleteBtn = document.getElementById('todoDetailDeleteBtn');
        if (editBtn) {
            editBtn.onclick = () => {
                this.closeTodoDetailModal();
                this.editTodo(todo.id);
            };
        }
        if (deleteBtn) {
            deleteBtn.onclick = async () => {
                this.closeTodoDetailModal();
                await this.deleteTodo(todo.id);
            };
        }

        // 显示模态框
        console.log('About to show modal, current display:', modal.style.display);
        modal.style.display = 'flex';
        
        // 使用 requestAnimationFrame 确保样式更新后再添加 show 类
        requestAnimationFrame(() => {
            modal.classList.add('show');
        });
        
        // 防止页面滚动
        document.body.style.overflow = 'hidden';
        
        console.log('Modal display set and show class added');
    }

    // 关闭TODO详情模态框
    closeTodoDetailModal() {
        const modal = document.getElementById('todoDetailModal');
        if (modal) {
            if (modal.classList.contains('show')) {
                // 开始隐藏动画
                modal.style.opacity = '0';
                modal.classList.remove('show');
                
                // 动画结束后隐藏元素
                setTimeout(() => {
                    modal.style.display = 'none';
                    modal.style.removeProperty('opacity');
                }, 300);
            } else {
                modal.style.display = 'none';
            }
            
            // 恢复页面滚动
            document.body.style.overflow = 'auto';
        }
    }

    // 获取优先级文字描述
    getPriorityText(importance, urgency) {
        if (importance === 'important' && urgency === 'urgent') {
            return '重要且紧急';
        } else if (importance === 'important' && urgency === 'not-urgent') {
            return '重要不紧急';
        } else if (importance === 'not-important' && urgency === 'urgent') {
            return '不重要但紧急';
        } else if (importance === 'not-important' && urgency === 'not-urgent') {
            return '不重要不紧急';
        } else {
            return '未设定优先级';
        }
    }

    // 将待办事项转换为事件
    async convertToEvent(todoId, eventData) {
        try {
            const response = await fetch(`/api/todos/${todoId}/convert-to-event/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(eventData)
            });
            
            if (response.ok) {
                await this.loadTodos();
                eventManager.refreshCalendar();
                return true;
            }
        } catch (error) {
            console.error('Error converting todo to event:', error);
        }
        return false;
    }

    // 获取CSRF令牌
    getCSRFToken() {
        return window.CSRF_TOKEN || '';
    }

    // ========================================
    // 四象限视图相关方法
    // ========================================

    /**
     * 切换视图模式
     */
    switchViewMode() {
        this.currentViewMode = this.currentViewMode === 'list' ? 'quadrant' : 'list';
        
        // 保存到设置
        if (window.settingsManager) {
            window.settingsManager.updateCategorySettings('todoViewMode', this.currentViewMode);
        }
        
        this.updateViewModeUI();
        this.renderTodos();
    }

    /**
     * 更新视图模式 UI
     */
    updateViewModeUI() {
        const listView = document.getElementById('todoListView');
        const quadrantView = document.getElementById('todoQuadrantView');
        const toggleBtn = document.getElementById('todoViewToggle');
        const priorityFilterList = document.getElementById('todoPriorityFilterList');
        
        if (this.currentViewMode === 'quadrant') {
            // 切换到四象限视图
            listView.classList.remove('active');
            listView.style.display = 'none';
            quadrantView.classList.add('active');
            quadrantView.style.display = ''; // 清除 inline style，让 CSS 控制
            toggleBtn.innerHTML = '<i class="fas fa-th"></i>';
            toggleBtn.title = '切换到列表视图';
            
            // 重置放置区标志（切换到象限视图时）
            this.dropZonesInitialized = false;
            
            // 禁用优先级筛选并全选
            if (priorityFilterList) {
                const checkboxes = priorityFilterList.querySelectorAll('input[type="checkbox"]');
                checkboxes.forEach(cb => {
                    cb.checked = true;
                    cb.disabled = true;
                });
            }
        } else {
            // 切换到列表视图
            listView.classList.add('active');
            listView.style.display = 'block';
            quadrantView.classList.remove('active');
            quadrantView.style.display = 'none';
            toggleBtn.innerHTML = '<i class="fas fa-list"></i>';
            toggleBtn.title = '切换到象限视图';
            
            // 启用优先级筛选
            if (priorityFilterList) {
                const checkboxes = priorityFilterList.querySelectorAll('input[type="checkbox"]');
                checkboxes.forEach(cb => {
                    cb.disabled = false;
                });
            }
        }
    }

    /**
     * 动态调整象限视图布局方向
     * 根据左侧面板的实际宽度决定溢出区在右侧还是底部
     */
    adjustQuadrantLayout() {
        const quadrantView = document.getElementById('todoQuadrantView');
        if (!quadrantView) {
            console.log('adjustQuadrantLayout: quadrantView 不存在');
            return;
        }
        
        const leftPanel = document.querySelector('.left-panel');
        if (!leftPanel) {
            console.log('adjustQuadrantLayout: leftPanel 不存在');
            return;
        }
        
        const panelWidth = leftPanel.offsetWidth;
        const threshold = 500; // 宽度阈值：小于500px时切换到垂直布局
        
        console.log(`adjustQuadrantLayout: 面板宽度=${panelWidth}px, 阈值=${threshold}px`);
        
        // 添加或移除类来控制布局
        const wasVertical = quadrantView.classList.contains('force-vertical');
        if (panelWidth < threshold) {
            quadrantView.classList.add('force-vertical');
            console.log('adjustQuadrantLayout: 切换到垂直布局');
        } else {
            quadrantView.classList.remove('force-vertical');
            console.log('adjustQuadrantLayout: 切换到横向布局');
        }
        
        // 如果布局方向发生变化，重新渲染象限内容
        const isVertical = quadrantView.classList.contains('force-vertical');
        if (wasVertical !== isVertical) {
            console.log(`adjustQuadrantLayout: 布局方向改变 (${wasVertical} → ${isVertical})`);
            if (this.currentQuadrants) {
                setTimeout(() => {
                    this.reRenderQuadrants();
                }, 100);
            }
        }
    }
    
    /**
     * 重新渲染所有象限（当布局变化时调用）
     */
    reRenderQuadrants() {
        if (!this.currentQuadrants) return;
        
        const quadrants = this.currentQuadrants;
        const sizes = this.calculateQuadrantSizes(quadrants);
        
        // 等待布局应用后再渲染
        setTimeout(() => {
            // 重新渲染各象限
            this.renderQuadrant('important-urgent', quadrants['important-urgent'], sizes);
            this.renderQuadrant('important-not-urgent', quadrants['important-not-urgent'], sizes);
            this.renderQuadrant('not-important-urgent', quadrants['not-important-urgent'], sizes);
            this.renderQuadrant('not-important-not-urgent', quadrants['not-important-not-urgent'], sizes);
            
            // 重新渲染溢出区
            setTimeout(() => {
                this.renderOverflowArea(quadrants);
            }, 100);
        }, 150);
    }

    /**
     * 渲染四象限视图
     */
    renderQuadrantView() {
        // 按象限分类 TODO
        const quadrants = {
            'important-urgent': [],
            'important-not-urgent': [],
            'not-important-urgent': [],
            'not-important-not-urgent': [],
            'unspecified': []
        };

        // 应用日程组筛选
        const groupCheckboxes = document.querySelectorAll('#todoGroupFilterList input[type="checkbox"]:checked');
        const selectedGroups = Array.from(groupCheckboxes).map(cb => cb.value);
        
        let filteredTodos = this.todos.filter(todo => {
            if (selectedGroups.length === 0) return true;
            
            const hasNoGroup = !todo.groupID || todo.groupID === '';
            const noneSelected = selectedGroups.includes('none');
            const groupMatched = todo.groupID && selectedGroups.includes(todo.groupID);
            
            return (noneSelected && hasNoGroup) || groupMatched;
        });

        // 分类到各象限
        filteredTodos.forEach(todo => {
            const type = this.getTodoPriorityType(todo.importance, todo.urgency);
            if (quadrants[type]) {
                quadrants[type].push(todo);
            }
        });

        // 每个象限按到期时间排序
        Object.keys(quadrants).forEach(key => {
            quadrants[key].sort((a, b) => {
                const dateA = a.due_date ? new Date(a.due_date) : new Date('9999-12-31');
                const dateB = b.due_date ? new Date(b.due_date) : new Date('9999-12-31');
                return dateA - dateB;
            });
        });

        // 计算象限大小（使用对数比例）
        const sizes = this.calculateQuadrantSizes(quadrants);
        
        // 存储象限数据，供后续重新渲染使用
        this.currentQuadrants = quadrants;
        
        // 先检测并调整布局方向，然后渲染内容
        this.adjustQuadrantLayout();
        
        // 使用 setTimeout 确保布局已应用和网格已更新
        setTimeout(() => {
            // 渲染各象限
            this.renderQuadrant('important-urgent', quadrants['important-urgent'], sizes);
            this.renderQuadrant('important-not-urgent', quadrants['important-not-urgent'], sizes);
            this.renderQuadrant('not-important-urgent', quadrants['not-important-urgent'], sizes);
            this.renderQuadrant('not-important-not-urgent', quadrants['not-important-not-urgent'], sizes);
            
            // 使用更长的延迟渲染溢出区，确保象限已完成渲染
            setTimeout(() => {
                this.renderOverflowArea(quadrants);
                
                // 只在第一次渲染时设置放置区
                if (!this.dropZonesInitialized) {
                    setTimeout(() => {
                        this.setupQuadrantDropZones();
                        this.dropZonesInitialized = true;
                        console.log('放置区已初始化');
                    }, 50);
                }
            }, 100);
        }, 150);
    }

    /**
     * 计算象限大小（平方根比例 + 最小保障）
     */
    calculateQuadrantSizes(quadrants) {
        const counts = {
            'important-urgent': quadrants['important-urgent'].length,
            'important-not-urgent': quadrants['important-not-urgent'].length,
            'not-important-urgent': quadrants['not-important-urgent'].length,
            'not-important-not-urgent': quadrants['not-important-not-urgent'].length
        };

        // 使用平方根函数计算权重，比对数函数增长更快，但比线性缓和
        // sqrt(count + 基础权重) - 确保每个象限都有最小空间
        const weights = {};
        let totalWeight = 0;
        const baseWeight = 4; // 基础权重，确保空象限也有合理大小
        
        Object.keys(counts).forEach(key => {
            // 使用平方根，增长速度介于对数和线性之间
            weights[key] = Math.sqrt(counts[key] + baseWeight);
            totalWeight += weights[key];
        });

        // 计算比例
        const ratios = {};
        Object.keys(weights).forEach(key => {
            ratios[key] = weights[key] / totalWeight;
        });

        // 计算行列比例
        const rowTop = ratios['important-urgent'] + ratios['important-not-urgent'];
        const rowBottom = ratios['not-important-urgent'] + ratios['not-important-not-urgent'];
        const colLeft = ratios['important-urgent'] + ratios['not-important-urgent'];
        const colRight = ratios['important-not-urgent'] + ratios['not-important-not-urgent'];

        // 更新网格布局
        const grid = document.getElementById('todoQuadrantGrid');
        if (grid) {
            // 使用 fr 单位设置比例
            grid.style.gridTemplateRows = `${rowTop.toFixed(2)}fr ${rowBottom.toFixed(2)}fr`;
            grid.style.gridTemplateColumns = `${colLeft.toFixed(2)}fr ${colRight.toFixed(2)}fr`;
        }

        return { counts, ratios };
    }

    /**
     * 渲染单个象限
     */
    renderQuadrant(quadrantType, todos, sizes) {
        const quadrant = document.querySelector(`.quadrant-${quadrantType} .quadrant-todos`);
        if (!quadrant) return;

        quadrant.innerHTML = '';

        // 检测当前布局方向
        const quadrantView = document.getElementById('todoQuadrantView');
        const isVertical = quadrantView && quadrantView.classList.contains('force-vertical');
        
        // 计算当前象限可以显示多少个 TODO
        const quadrantElement = quadrant.closest('.quadrant');
        const availableHeight = quadrantElement.clientHeight - 20; // 减去 padding
        
        // 根据布局方向调整高度估算和显示策略
        let todoHeight, extraCapacity, minVisible;
        
        if (isVertical) {
            // 垂直布局（窄面板）：保守估算
            todoHeight = 45;
            extraCapacity = 2;
            minVisible = 2;
        } else {
            // 横向布局（宽面板）：更激进的估算，鼓励显示更多
            todoHeight = 40; // 减小估算值，认为可以显示更多
            extraCapacity = 4; // 额外容量增加到4
            minVisible = 3;
        }
        
        const baseVisible = Math.floor(availableHeight / todoHeight);
        const maxVisible = Math.max(minVisible, Math.min(todos.length, baseVisible + extraCapacity));

        // 只渲染可见的 TODO
        const visibleTodos = todos.slice(0, maxVisible);
        
        visibleTodos.forEach(todo => {
            const element = this.createCompactTodoElement(todo);
            quadrant.appendChild(element);
        });

        // 存储溢出的 TODO（稍后在溢出区显示）
        if (!this.overflowTodos) {
            this.overflowTodos = {};
        }
        this.overflowTodos[quadrantType] = todos.slice(maxVisible);
    }

    /**
     * 渲染溢出区域
     */
    renderOverflowArea(quadrants) {
        const overflowList = document.getElementById('todoOverflowList');
        if (!overflowList) return;

        overflowList.innerHTML = '';

        // 收集所有溢出的 TODO，分为有优先级和无优先级两类
        const withPriority = []; // 有优先级的（从象限溢出的）
        const withoutPriority = []; // 无优先级的（unspecified）
        
        // 添加未指定优先级的 TODO
        if (quadrants['unspecified']) {
            withoutPriority.push(...quadrants['unspecified']);
        }

        // 添加各象限溢出的 TODO（这些都有优先级）
        if (this.overflowTodos) {
            Object.values(this.overflowTodos).forEach(todos => {
                withPriority.push(...todos);
            });
        }

        // 分别按到期时间排序
        const sortByDueDate = (a, b) => {
            const dateA = a.due_date ? new Date(a.due_date) : new Date('9999-12-31');
            const dateB = b.due_date ? new Date(b.due_date) : new Date('9999-12-31');
            return dateA - dateB;
        };
        
        withPriority.sort(sortByDueDate);
        withoutPriority.sort(sortByDueDate);

        // 先渲染有优先级的（在最上面），传入 showPriority=true
        withPriority.forEach(todo => {
            const element = this.createCompactTodoElement(todo, true);
            overflowList.appendChild(element);
        });
        
        // 再渲染无优先级的
        withoutPriority.forEach(todo => {
            const element = this.createCompactTodoElement(todo, false);
            overflowList.appendChild(element);
        });

        // 如果溢出区为空，隐藏它
        const overflowContainer = document.getElementById('todoOverflowContainer');
        if (overflowContainer) {
            const totalCount = withPriority.length + withoutPriority.length;
            overflowContainer.style.display = totalCount > 0 ? 'block' : 'none';
        }
    }

    /**
     * 创建精简 TODO 元素
     * @param {Object} todo - TODO 对象
     * @param {Boolean} showPriority - 是否显示优先级圆点
     */
    createCompactTodoElement(todo, showPriority = false) {
        const div = document.createElement('div');
        div.className = 'todo-item-compact';
        div.dataset.todoId = todo.id;
        div.draggable = true; // 使元素可拖动

        // 应用日程组颜色条
        if (todo.groupID && window.groupManager) {
            const group = window.groupManager.getGroupById(todo.groupID);
            if (group) {
                div.style.borderLeft = `4px solid ${group.color}`;
            }
        }

        // 计算相对到期时间
        const dueText = this.getRelativeDueDate(todo.due_date);

        // 构建 HTML
        let titleHtml = '';
        
        // 标题行（包含优先级圆点）
        if (showPriority) {
            const priorityIcon = this.getPriorityIcon(todo.importance, todo.urgency);
            titleHtml = `
                <div class="todo-title-compact">
                    <span class="todo-priority-compact">${priorityIcon}</span>
                    <span>${this.escapeHtml(todo.title)}</span>
                </div>
            `;
        } else {
            titleHtml = `<div class="todo-title-compact">${this.escapeHtml(todo.title)}</div>`;
        }
        
        // 如果有截止日期，显示日期行
        let dueHtml = '';
        if (dueText.text) {
            dueHtml = `
                <div class="todo-due-compact ${dueText.class}">
                    <i class="fas fa-clock"></i>
                    ${dueText.text}
                </div>
            `;
        }
        
        div.innerHTML = titleHtml + dueHtml;

        // 绑定拖动事件
        this.setupCompactTodoDrag(div, todo);

        // 点击打开详情
        div.addEventListener('click', (e) => {
            // 如果正在拖动，不触发点击
            if (div.classList.contains('dragging')) {
                return;
            }
            this.openTodoDetailModal(todo);
        });

        return div;
    }

    /**
     * 获取相对到期时间
     */
    getRelativeDueDate(dueDate) {
        if (!dueDate) {
            return { text: '', class: '' }; // 返回空字符串，不显示
        }

        const now = new Date();
        now.setHours(0, 0, 0, 0);
        
        const due = new Date(dueDate);
        due.setHours(0, 0, 0, 0);
        
        const diffTime = due - now;
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

        if (diffDays < 0) {
            return { 
                text: `已逾期${Math.abs(diffDays)}天`, 
                class: 'due-overdue' 
            };
        } else if (diffDays === 0) {
            return { 
                text: '今天到期', 
                class: 'due-today' 
            };
        } else if (diffDays === 1) {
            return { 
                text: '明天到期', 
                class: 'due-soon' 
            };
        } else if (diffDays <= 3) {
            return { 
                text: `${diffDays}天后`, 
                class: 'due-soon' 
            };
        } else if (diffDays <= 7) {
            return { 
                text: `${diffDays}天后`, 
                class: 'due-normal' 
            };
        } else {
            return { 
                text: `${diffDays}天后`, 
                class: 'due-normal' 
            };
        }
    }

    /**
     * 设置精简TODO的拖动功能
     */
    setupCompactTodoDrag(element, todo) {
        element.addEventListener('dragstart', (e) => {
            console.log('开始拖动 TODO:', todo.title);
            element.classList.add('dragging');
            
            // 设置拖动数据
            const dragData = {
                type: 'todo',
                id: todo.id,
                title: todo.title,
                description: todo.description,
                estimatedDuration: todo.estimated_duration,
                groupID: todo.groupID,
                importance: todo.importance,
                urgency: todo.urgency
            };
            
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', JSON.stringify(dragData));
            
            // 设置拖动时的视觉反馈（使用元素自身的样式）
            e.dataTransfer.setDragImage(element, element.offsetWidth / 2, element.offsetHeight / 2);
        });

        element.addEventListener('dragend', (e) => {
            console.log('拖动结束');
            element.classList.remove('dragging');
            
            // 清除所有放置区的高亮状态
            this.clearAllDropZoneHighlights();
        });
    }

    /**
     * 清除所有放置区的高亮状态
     */
    clearAllDropZoneHighlights() {
        document.querySelectorAll('.quadrant, .overflow-container').forEach(el => {
            el.classList.remove('drag-over');
        });
    }

    /**
     * 设置象限视图的放置区
     */
    setupQuadrantDropZones() {
        console.log('设置象限视图放置区');
        
        // 获取所有象限
        const quadrants = [
            { element: document.querySelector('.quadrant-important-urgent'), type: 'important-urgent' },
            { element: document.querySelector('.quadrant-important-not-urgent'), type: 'important-not-urgent' },
            { element: document.querySelector('.quadrant-not-important-urgent'), type: 'not-important-urgent' },
            { element: document.querySelector('.quadrant-not-important-not-urgent'), type: 'not-important-not-urgent' },
            { element: document.getElementById('todoOverflowContainer'), type: 'unspecified' }
        ];

        quadrants.forEach(({ element, type }) => {
            if (!element) return;

            element.addEventListener('dragover', (e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                element.classList.add('drag-over');
            });

            element.addEventListener('dragleave', (e) => {
                // 检查是否真的离开了元素（而不是进入子元素）
                const rect = element.getBoundingClientRect();
                const x = e.clientX;
                const y = e.clientY;
                
                if (x < rect.left || x >= rect.right || y < rect.top || y >= rect.bottom) {
                    element.classList.remove('drag-over');
                }
            });

            element.addEventListener('drop', async (e) => {
                e.preventDefault();
                element.classList.remove('drag-over');
                
                try {
                    const data = JSON.parse(e.dataTransfer.getData('text/plain'));
                    
                    if (data.type === 'todo') {
                        console.log(`TODO 拖动到: ${type}`);
                        await this.handleTodoDropToQuadrant(data.id, type);
                    }
                } catch (error) {
                    console.error('处理拖拽数据时出错:', error);
                }
            });
        });
    }

    /**
     * 处理TODO拖动到象限
     */
    async handleTodoDropToQuadrant(todoId, quadrantType) {
        console.log(`将 TODO ${todoId} 移动到象限: ${quadrantType}`);
        
        let importance, urgency;
        
        if (quadrantType === 'important-urgent') {
            importance = 'important';
            urgency = 'urgent';
        } else if (quadrantType === 'important-not-urgent') {
            importance = 'important';
            urgency = 'not-urgent';
        } else if (quadrantType === 'not-important-urgent') {
            importance = 'not-important';
            urgency = 'urgent';
        } else if (quadrantType === 'not-important-not-urgent') {
            importance = 'not-important';
            urgency = 'not-urgent';
        } else if (quadrantType === 'unspecified') {
            // 拖到"其他"栏，清除重要紧急性参数
            importance = null;
            urgency = null;
        }

        // 只更新服务器，不重新加载
        try {
            const response = await fetch('/api/todos/update/', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.CSRF_TOKEN 
                },
                body: JSON.stringify({ 
                    id: todoId, 
                    importance: importance,
                    urgency: urgency
                })
            });
            
            if (response.ok) {
                console.log('TODO 优先级已更新');
                
                // 更新本地数据
                const todo = this.todos.find(t => t.id === todoId);
                if (todo) {
                    todo.importance = importance;
                    todo.urgency = urgency;
                }
                
                // 直接重新渲染象限视图（不重新加载数据）
                this.renderQuadrantView();
            }
        } catch (error) {
            console.error('更新 TODO 失败:', error);
        }
    }
}

// 待办管理器类已定义，实例将在HTML中创建
