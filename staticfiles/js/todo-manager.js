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
        div.className = `todo-item ${this.getPriorityClass(todo.importance)}`;
        div.draggable = true;
        div.dataset.todoId = todo.id;
        
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
            e.dataTransfer.setData('text/plain', JSON.stringify({
                type: 'todo',
                id: todo.id,
                title: todo.title,
                duration: todo.estimated_duration || '1h'
            }));
        });

        return div;
    }

    // 获取优先级类名
    getPriorityClass(importance) {
        const priorityMap = {
            'critical': 'high-priority',
            'high': 'high-priority',
            'medium': 'medium-priority',
            'low': 'low-priority'
        };
        return priorityMap[importance] || 'medium-priority';
    }

    // 获取优先级图标
    getPriorityIcon(importance, urgency) {
        if (importance === 'critical' || (importance === 'high' && urgency === 'urgent')) {
            return '🔴';
        } else if (importance === 'high' || urgency === 'urgent') {
            return '🟡';
        } else if (importance === 'low') {
            return '🟢';
        }
        return '🔵';
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
    async deleteTodo(todoId) {
        if (!confirm('确定要删除这个待办事项吗？')) {
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
