// 待办事项管理模块
class TodoManager {
    constructor() {
        this.todos = [];
        this.todoContainer = null;
    }

    // 初始化待办事项管理器
    init() {
        this.todoContainer = document.getElementById('todoList');
        this.loadTodos();
        this.initDragDrop();
        this.initFilters();
    }

    // 初始化筛选功能
    initFilters() {
        const statusFilter = document.getElementById('todoStatusFilter');
        const sortFilter = document.getElementById('todoSortBy');

        if (statusFilter) {
            statusFilter.addEventListener('change', () => {
                console.log('待办状态筛选变化:', statusFilter.value);
                this.applyFilters();
                // 保存筛选状态
                if (window.settingsManager) {
                    window.settingsManager.onTodoFilterChange('statusFilter', statusFilter.value);
                }
            });
        }

        if (sortFilter) {
            sortFilter.addEventListener('change', () => {
                console.log('待办排序变化:', sortFilter.value);
                this.applyFilters();
                // 保存排序状态
                if (window.settingsManager) {
                    window.settingsManager.onTodoFilterChange('sortBy', sortFilter.value);
                }
            });
        }

        console.log('待办筛选器已初始化');
    }

    // 应用筛选和排序
    applyFilters() {
        const statusFilter = document.getElementById('todoStatusFilter');
        const sortFilter = document.getElementById('todoSortBy');

        let filteredTodos = [...this.todos];

        // 状态筛选
        if (statusFilter && statusFilter.value) {
            filteredTodos = filteredTodos.filter(todo => todo.status === statusFilter.value);
        } else {
            // 默认只显示未完成的
            filteredTodos = filteredTodos.filter(todo =>
                todo.status === 'pending' || todo.status === 'in_progress'
            );
        }

        // 排序
        const sortBy = sortFilter ? sortFilter.value : 'priority';
        filteredTodos.sort((a, b) => {
            switch (sortBy) {
                case 'due_date':
                    return new Date(a.due_date || '9999-12-31') - new Date(b.due_date || '9999-12-31');
                case 'created_at':
                    return new Date(b.created_at) - new Date(a.created_at);
                case 'priority':
                default:
                    return b.priority_score - a.priority_score;
            }
        });

        this.renderFilteredTodos(filteredTodos);
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
            this.renderTodos();
        } catch (error) {
            console.error('Error loading todos:', error);
            this.todos = [];
            this.renderTodos();
        }
    }

    // 渲染待办事项列表
    renderTodos() {
        // 使用筛选方法来渲染
        this.applyFilters();
    }

    // 创建待办事项元素
    createTodoElement(todo) {
        const div = document.createElement('div');
        div.className = `todo-item ${this.getPriorityClass(todo.importance, todo.urgency)}`;
        div.draggable = true;
        div.dataset.todoId = todo.id;

        // 如果有日程组，应用日程组颜色
        if (todo.groupID && window.groupManager) {
            const group = window.groupManager.getGroupById(todo.groupID);
            if (group) {
                div.style.borderLeft = `4px solid ${group.color}`;
            }
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
            todoContent.addEventListener('click', (e) => {
                console.log('TODO content clicked, target:', e.target, 'closest .todo-actions:', e.target.closest('.todo-actions'));
                // 如果点击的是按钮或按钮内的元素，不触发详情查看
                if (e.target.closest('.todo-actions')) {
                    console.log('Click on action buttons, ignoring');
                    return;
                }
                console.log('Opening todo detail modal for:', todo.id);
                this.openTodoDetailModal(todo);
            });
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
}

// 待办管理器类已定义，实例将在HTML中创建
