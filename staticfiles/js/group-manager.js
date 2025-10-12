/**
 * 日程组管理器（重构版 - 单模态框多面板设计）
 * 处理日程组的创建、编辑、删除和显示
 */
class GroupManager {
    constructor() {
        this.groups = [];
        this.modal = null;
        this.currentPanel = 'list';  // 当前显示的面板：list, create, edit, delete
    }

    /**
     * 初始化日程组管理器
     */
    init() {
        // 从全局变量加载日程组
        this.groups = window.events_groups || [];
        
        // 初始化模态框
        const modalElement = document.getElementById('manageGroupsModal');
        if (modalElement) {
            this.modal = new bootstrap.Modal(modalElement);
        }
        
        // 初始化日程组选择框
        this.refreshGroupSelects();
        
        console.log('日程组管理器已初始化（单模态框版本），当前有', this.groups.length, '个日程组');
    }

    /**
     * 显示指定面板，隐藏其他面板
     */
    showPanel(panelName) {
        const panels = ['groupListPanel', 'groupCreatePanel', 'groupEditPanel', 'groupDeletePanel'];
        const titles = {
            'list': '<i class="fas fa-layer-group me-2"></i>管理日程组',
            'create': '<i class="fas fa-plus-circle me-2"></i>创建日程组',
            'edit': '<i class="fas fa-edit me-2"></i>编辑日程组',
            'delete': '<i class="fas fa-trash-alt me-2"></i>删除日程组'
        };
        
        panels.forEach(panel => {
            const element = document.getElementById(panel);
            if (element) {
                element.style.display = 'none';
            }
        });
        
        const targetPanel = document.getElementById(`group${panelName.charAt(0).toUpperCase() + panelName.slice(1)}Panel`);
        if (targetPanel) {
            targetPanel.style.display = 'block';
        }
        
        // 更新标题
        const titleElement = document.getElementById('groupModalTitle');
        if (titleElement && titles[panelName]) {
            titleElement.innerHTML = titles[panelName];
        }
        
        this.currentPanel = panelName;
    }

    /**
     * 显示列表面板
     */
    showListPanel() {
        this.renderGroupsList();
        this.showPanel('list');
    }

    /**
     * 显示创建面板
     */
    showCreatePanel() {
        // 清空表单
        document.getElementById('newGroupName').value = '';
        document.getElementById('newGroupDescription').value = '';
        document.getElementById('newGroupColor').value = '#3788d8';
        
        this.showPanel('create');
    }

    /**
     * 显示编辑面板
     */
    showEditPanel(groupId) {
        const group = this.groups.find(g => g.id === groupId);
        if (!group) {
            alert('找不到指定的日程组');
            return;
        }

        document.getElementById('editGroupId').value = group.id;
        document.getElementById('editGroupName').value = group.name;
        document.getElementById('editGroupDescription').value = group.description || '';
        document.getElementById('editGroupColor').value = group.color || '#3788d8';

        this.showPanel('edit');
    }

    /**
     * 显示删除面板
     */
    showDeletePanel(groupId) {
        document.getElementById('deleteGroupId').value = groupId;
        document.getElementById('deleteGroupOnly').checked = true;
        
        this.showPanel('delete');
    }

    /**
     * 显示日程组管理模态框
     */
    showManageGroupsModal() {
        this.showListPanel();
        this.modal.show();
    }

    /**
     * 渲染日程组列表
     */
    renderGroupsList() {
        const groupsList = document.getElementById('groupsList');
        if (!groupsList) return;

        if (this.groups.length === 0) {
            groupsList.innerHTML = `
                <div class="text-center text-muted py-4">
                    <i class="fas fa-inbox fa-3x mb-3"></i>
                    <p>暂无日程组，点击上方按钮创建第一个日程组</p>
                </div>
            `;
            return;
        }

        groupsList.innerHTML = this.groups.map(group => `
            <div class="list-group-item d-flex justify-content-between align-items-center">
                <div class="d-flex align-items-center">
                    <div class="me-3" style="width: 24px; height: 24px; background-color: ${group.color}; border-radius: 4px;"></div>
                    <div>
                        <h6 class="mb-0">${this.escapeHtml(group.name)}</h6>
                        ${group.description ? `<small class="text-muted">${this.escapeHtml(group.description)}</small>` : ''}
                    </div>
                </div>
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-primary" onclick="groupManager.showEditPanel('${group.id}')" title="编辑">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="btn btn-outline-danger" onclick="groupManager.showDeletePanel('${group.id}')" title="删除">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </div>
        `).join('');
    }

    /**
     * 创建日程组
     */
    async createGroup() {
        const name = document.getElementById('newGroupName').value.trim();
        const description = document.getElementById('newGroupDescription').value.trim();
        const color = document.getElementById('newGroupColor').value;

        if (!name) {
            alert('请输入日程组名称');
            return;
        }

        try {
            const response = await fetch('/get_calendar/create_events_group/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.CSRF_TOKEN
                },
                body: JSON.stringify({
                    name: name,
                    description: description,
                    color: color
                })
            });

            const data = await response.json();
            
            if (data.status === 'success') {
                // 重新加载日程组列表
                await this.reloadGroups();
                
                // 刷新所有日程组选择框
                this.refreshGroupSelects();
                
                // 返回列表面板
                this.showListPanel();
                
                console.log('日程组创建成功');
            } else {
                alert('创建失败: ' + (data.message || '未知错误'));
            }
        } catch (error) {
            console.error('创建日程组失败:', error);
            alert('创建失败，请重试');
        }
    }

    /**
     * 更新日程组
     */
    async updateGroup() {
        const groupId = document.getElementById('editGroupId').value;
        const name = document.getElementById('editGroupName').value.trim();
        const description = document.getElementById('editGroupDescription').value.trim();
        const color = document.getElementById('editGroupColor').value;

        if (!name) {
            alert('请输入日程组名称');
            return;
        }

        try {
            const response = await fetch('/get_calendar/update_events_group/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.CSRF_TOKEN
                },
                body: JSON.stringify({
                    groupID: groupId,
                    title: name,
                    description: description,
                    color: color
                })
            });

            const data = await response.json();

            if (data.status === 'success') {
                // 重新加载日程组列表
                await this.reloadGroups();

                // 刷新所有日程组选择框
                this.refreshGroupSelects();

                // 刷新日历以更新事件颜色
                if (window.eventManager && window.eventManager.calendar) {
                    window.eventManager.calendar.refetchEvents();
                }

                // 返回列表面板
                this.showListPanel();

                console.log('日程组更新成功');
            } else {
                alert('更新失败: ' + (data.message || '未知错误'));
            }
        } catch (error) {
            console.error('更新日程组失败:', error);
            alert('更新失败，请重试');
        }
    }

    /**
     * 确认删除日程组
     */
    async confirmDeleteGroup() {
        const groupId = document.getElementById('deleteGroupId').value;
        const deleteEvents = document.getElementById('deleteGroupAndEvents').checked;

        try {
            const response = await fetch('/get_calendar/delete_event_groups/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.CSRF_TOKEN
                },
                body: JSON.stringify({
                    groupIds: [groupId],
                    deleteEvents: deleteEvents
                })
            });

            const data = await response.json();
            
            if (data.status === 'success') {
                // 重新加载日程组列表
                await this.reloadGroups();
                
                // 刷新所有日程组选择框
                this.refreshGroupSelects();
                
                // 如果删除了日程，刷新日历和其他视图
                if (deleteEvents) {
                    if (window.eventManager && window.eventManager.calendar) {
                        window.eventManager.loadEvents();
                    }
                    if (window.todoManager) {
                        window.todoManager.loadTodos();
                    }
                }
                
                // 返回列表面板
                this.showListPanel();
                
                console.log('日程组删除成功');
            } else {
                alert('删除失败: ' + (data.message || '未知错误'));
            }
        } catch (error) {
            console.error('删除日程组失败:', error);
            alert('删除失败，请重试');
        }
    }

    /**
     * 重新从服务器加载日程组列表
     */
    async reloadGroups() {
        try {
            const response = await fetch('/get_calendar/events/', {
                method: 'GET',
                headers: {
                    'X-CSRFToken': window.CSRF_TOKEN
                }
            });

            const data = await response.json();
            
            if (data.events_groups) {
                this.groups = data.events_groups;
                window.events_groups = data.events_groups;
            }
        } catch (error) {
            console.error('重新加载日程组失败:', error);
        }
    }

    /**
     * 刷新所有日程组选择框
     */
    refreshGroupSelects() {
        const selectIds = ['newEventGroupId', 'eventGroupId', 'newTodoGroupId', 'todoGroupId'];
        
        selectIds.forEach(id => {
            const select = document.getElementById(id);
            if (!select) return;

            // 保存当前选中的值
            const currentValue = select.value;

            // 清空现有选项
            select.innerHTML = '<option value="">无</option>';

            // 添加所有日程组选项
            this.groups.forEach(group => {
                const option = document.createElement('option');
                option.value = group.id;
                option.textContent = group.name;
                option.style.color = group.color;
                select.appendChild(option);
            });

            // 恢复之前的选中值（如果还存在）
            if (currentValue && this.groups.find(g => g.id === currentValue)) {
                select.value = currentValue;
            }
        });

        console.log('已刷新日程组选择框');
    }

    /**
     * 根据ID获取日程组
     */
    getGroupById(groupId) {
        return this.groups.find(g => g.id === groupId);
    }

    /**
     * 转义HTML特殊字符
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// 创建全局实例
window.groupManager = new GroupManager();
