/**
 * 群组协作功能 JavaScript
 * 实现选项卡切换、群组管理、事件分享等功能
 * Created: 2025-11-11
 */

const shareGroupManager = {
    // 状态管理
    state: {
        myGroups: [],
        currentGroupId: null,
        currentViewType: 'my', // 'my' or 'share-group'
        groupVersions: {}, // {groupId: version}
        pollingInterval: null
    },

    /**
     * 初始化群组管理器
     */
    async init() {
        console.log('[ShareGroupManager] 初始化群组管理器');
        
        // 绑定事件
        this.bindEvents();
        
        // 加载用户的群组列表
        await this.loadMyGroups();
        
        // 渲染群组选项卡
        this.renderGroupTabs();
        
        // 启动轮询检测更新
        this.startPolling();
        
        console.log('[ShareGroupManager] 初始化完成');
    },

    /**
     * 绑定DOM事件
     */
    bindEvents() {
        // 选项卡点击事件（使用事件委托）
        document.addEventListener('click', (e) => {
            const tab = e.target.closest('.calendar-tab');
            if (tab) {
                const type = tab.getAttribute('data-type');
                const id = tab.getAttribute('data-id');
                this.switchTab(type, id);
            }
        });

        // 添加群组按钮 - 直接打开管理面板
        const addButton = document.getElementById('addGroupTab');
        if (addButton) {
            addButton.addEventListener('click', () => {
                console.log('[ShareGroupManager] 点击添加群组按钮 - 直接打开管理面板');
                this.showManageGroupsModal();
            });
        } else {
            console.error('[ShareGroupManager] 未找到 addGroupTab 元素');
        }
    },

    /**
     * 加载用户的群组列表
     */
    async loadMyGroups() {
        try {
            // 添加时间戳防止缓存
            const timestamp = new Date().getTime();
            const response = await fetch(`/api/share-groups/my-groups/?_t=${timestamp}`, {
                credentials: 'same-origin',
                headers: {
                    'X-CSRFToken': window.CSRF_TOKEN
                }
            });

            if (response.ok) {
                const data = await response.json();
                this.state.myGroups = data.groups || [];
                console.log('[ShareGroupManager] 加载群组列表成功:', this.state.myGroups.length, '个群组');
                
                // 渲染群组选项卡和选择器
                this.renderGroupTabs();
                this.renderGroupSelectors();
            } else {
                console.error('[ShareGroupManager] 加载群组列表失败');
            }
        } catch (error) {
            console.error('[ShareGroupManager] 加载群组列表错误:', error);
        }
    },

    /**
     * 渲染群组选项卡
     */
    renderGroupTabs() {
        const container = document.getElementById('calendarTabsContainer');
        if (!container) {
            console.error('[ShareGroupManager] 未找到 calendarTabsContainer');
            return;
        }
        
        // 保存当前激活的选项卡信息
        const activeTab = container.querySelector('.calendar-tab.active');
        let activeType = null;
        let activeId = null;
        if (activeTab) {
            activeType = activeTab.getAttribute('data-type');
            activeId = activeTab.getAttribute('data-id');
        }
        
        console.log('[ShareGroupManager] 保存当前激活状态:', {activeType, activeId});
        
        // 移除现有的群组选项卡（保留"我的日程"和"+"按钮）
        const existingGroupTabs = container.querySelectorAll('.calendar-tab[data-type="share-group"]');
        existingGroupTabs.forEach(tab => tab.remove());
        
        // 在"+"按钮之前插入群组选项卡
        const addButton = container.querySelector('.calendar-tab-add');
        
        this.state.myGroups.forEach(group => {
            const tab = document.createElement('div');
            tab.className = 'calendar-tab';
            tab.setAttribute('data-type', 'share-group');
            tab.setAttribute('data-id', group.share_group_id);
            
            // 恢复激活状态
            if (activeType === 'share-group' && activeId === group.share_group_id) {
                tab.classList.add('active');
                console.log('[ShareGroupManager] ✅ 恢复群组选项卡激活状态:', group.share_group_name);
            }
            
            // 获取群组颜色
            const groupColor = group.share_group_color || '#3498db';
            
            tab.innerHTML = `
                <i class="fas fa-users" style="color: ${groupColor};"></i>
                <span>${this.escapeHtml(group.share_group_name)}</span>
                <span class="update-badge" style="display:none;">•</span>
            `;
            
            if (addButton) {
                container.insertBefore(tab, addButton);
            } else {
                container.appendChild(tab);
            }
        });
        
        // 如果"我的日程"是激活的，确保保持激活状态
        if (activeType === 'my') {
            const myTab = container.querySelector('.calendar-tab[data-type="my"]');
            if (myTab && !myTab.classList.contains('active')) {
                myTab.classList.add('active');
                console.log('[ShareGroupManager] ✅ 恢复我的日程选项卡激活状态');
            }
        }
    },

    /**
     * 切换选项卡
     */
    async switchTab(type, id) {
        console.log('[ShareGroupManager] 切换选项卡:', type, id);
        
        // 更新激活状态
        document.querySelectorAll('.calendar-tab').forEach(tab => {
            tab.classList.remove('active');
        });
        
        const activeTab = document.querySelector(`.calendar-tab[data-type="${type}"][data-id="${id}"]`);
        if (activeTab) {
            activeTab.classList.add('active');
            
            // 隐藏更新徽章
            const badge = activeTab.querySelector('.update-badge');
            if (badge) badge.style.display = 'none';
        }
        
        this.state.currentViewType = type;
        this.state.currentGroupId = (type === 'share-group') ? id : null;
        
        if (type === 'my') {
            // 隐藏成员筛选区域
            this.hideMemberFilter();
            // 加载我的日程
            await this.loadMyCalendar();
        } else if (type === 'share-group') {
            // 加载群组日程（会自动显示成员筛选）
            await this.loadGroupCalendar(id);
        }
    },

    /**
     * 加载我的日程
     */
    async loadMyCalendar() {
        console.log('[ShareGroupManager] 加载我的日程');
        
        if (!window.eventManager || !window.eventManager.calendar) {
            console.error('[ShareGroupManager] EventManager 或 Calendar 未初始化');
            return;
        }
        
        // 设置为非群组视图模式
        window.eventManager.isGroupView = false;
        
        const calendar = window.eventManager.calendar;
        
        // 1. 移除所有事件源（包括群组事件源）
        const sources = calendar.getEventSources();
        console.log(`[ShareGroupManager] 移除 ${sources.length} 个事件源`);
        sources.forEach(source => source.remove());
        
        // 2. 移除所有事件
        calendar.removeAllEvents();
        
        // 3. 等待一下确保清理完成
        await new Promise(resolve => setTimeout(resolve, 50));
        
        // 4. 获取我的日程数据
        console.log('[ShareGroupManager] 开始获取我的日程数据');
        try {
            const events = await window.eventManager.fetchEvents();
            console.log(`[ShareGroupManager] 获取到 ${events.length} 个事件`);
            
            // 5. 添加为新的事件源（使用函数回调，支持动态刷新）
            calendar.addEventSource({
                events: async (info, successCallback, failureCallback) => {
                    try {
                        // 如果切换到群组视图，不加载
                        if (window.eventManager.isGroupView) {
                            successCallback([]);
                            return;
                        }
                        
                        const events = await window.eventManager.fetchEvents(info.start, info.end);
                        successCallback(events);
                    } catch (error) {
                        console.error('[MyCalendar] 加载事件失败:', error);
                        failureCallback(error);
                    }
                },
                id: 'my-calendar'
            });
            
            console.log('[ShareGroupManager] 我的日程加载完成');
        } catch (error) {
            console.error('[ShareGroupManager] 获取日程数据失败:', error);
        }
    },

    /**
     * 加载群组日程
     */
    async loadGroupCalendar(groupId) {
        console.log('[ShareGroupManager] 加载群组日程:', groupId);
        
        if (!window.eventManager || !window.eventManager.calendar) {
            console.error('[ShareGroupManager] EventManager 或 Calendar 未初始化');
            return;
        }
        
        // 设置为群组视图模式
        window.eventManager.isGroupView = true;
        
        const calendar = window.eventManager.calendar;
        
        try {
            // 1. 先清除所有事件源和事件
            const sources = calendar.getEventSources();
            console.log(`[ShareGroupManager] 移除 ${sources.length} 个事件源`);
            sources.forEach(source => source.remove());
            calendar.removeAllEvents();
            
            // 2. 获取群组事件数据
            const response = await fetch(`/api/share-groups/${groupId}/events/`, {
                credentials: 'same-origin',
                headers: {
                    'X-CSRFToken': window.CSRF_TOKEN
                }
            });

            if (!response.ok) {
                console.error('[ShareGroupManager] 加载群组日程失败:', response.status);
                return;
            }

            const data = await response.json();
            
            // 3. 更新版本号
            if (data.version) {
                this.state.groupVersions[groupId] = data.version;
            }
            
            // 4. 获取当前用户ID
            const currentUserId = data.current_user_id;
            
            // 5. 处理事件：区分自己的事件和他人的事件
            const events = (data.events || []).map(event => {
                const isMyEvent = event.user_id === currentUserId || event.owner_id === currentUserId;
                
                // 获取日程组颜色
                const groupColor = this.getEventGroupColor(event.groupID);
                
                return {
                    ...event,
                    // 确保 user_id 和 owner_id 在顶层可访问（用于筛选）
                    user_id: event.user_id || event.owner_id,
                    owner_id: event.owner_id || event.user_id,
                    backgroundColor: groupColor,  // 设置背景色（用于获取）
                    borderColor: groupColor,      // 设置边框色
                    editable: isMyEvent,  // 只有自己的事件可编辑
                    className: isMyEvent ? 'my-event-in-group' : 'readonly-event',
                    extendedProps: {
                        ...event.extendedProps,
                        isGroupView: true,
                        isMyEvent: isMyEvent,
                        user_id: event.user_id || event.owner_id,  // 确保在 extendedProps 中也有
                        owner_id: event.owner_id || event.user_id,
                        owner_username: event.owner_name || event.owner_username,  // 添加归属用户名
                        owner_color: event.owner_color,  // 添加成员颜色
                        owner_name: event.owner_name,
                        is_readonly: !isMyEvent,  // 是否只读
                        groupColor: groupColor  // 显式传递日程组颜色
                    }
                };
            });
            
            console.log('[ShareGroupManager] 处理事件:', {
                total: events.length,
                myEvents: events.filter(e => e.editable).length,
                otherEvents: events.filter(e => !e.editable).length
            });
            
            // 6. 应用筛选（在添加到日历之前）
            let filteredEvents = events;
            if (window.eventManager && window.eventManager.applyCalendarFilters) {
                filteredEvents = window.eventManager.applyCalendarFilters(events);
                console.log('[ShareGroupManager] 应用筛选后:', {
                    原始: events.length,
                    筛选后: filteredEvents.length,
                    被过滤: events.length - filteredEvents.length
                });
            }
            
            // 7. 等待 DOM 更新
            await new Promise(resolve => setTimeout(resolve, 100));
            
            // 8. 添加群组事件源（使用筛选后的事件）
            calendar.addEventSource({
                events: filteredEvents,
                id: `group-${groupId}`  // 添加唯一ID便于管理
            });
            
            console.log('[ShareGroupManager] 群组日程加载成功');
            
            // 9. 更新成员筛选列表
            this.updateMemberFilterList(groupId, data.members || []);
            
        } catch (error) {
            console.error('[ShareGroupManager] 加载群组日程错误:', error);
        }
    },

    /**
     * 更新成员筛选列表
     */
    updateMemberFilterList(groupId, members) {
        const filterSection = document.getElementById('memberFilterSection');
        const filterList = document.getElementById('memberFilterList');
        
        if (!filterSection || !filterList) {
            console.warn('[ShareGroupManager] 成员筛选元素未找到');
            return;
        }
        
        if (!members || members.length === 0) {
            console.warn('[ShareGroupManager] 没有成员数据');
            filterSection.style.display = 'none';
            return;
        }
        
        console.log('[ShareGroupManager] 更新成员筛选列表:', members);
        
        // 显示成员筛选区域
        filterSection.style.display = 'block';
        
        // 清空现有列表
        filterList.innerHTML = '';
        
        // 创建成员复选框
        members.forEach(member => {
            const div = document.createElement('div');
            div.className = 'form-check';
            
            const checkbox = document.createElement('input');
            checkbox.className = 'form-check-input';
            checkbox.type = 'checkbox';
            checkbox.id = `memberFilter_${member.user_id}`;
            checkbox.value = member.user_id;
            checkbox.checked = true; // 默认全选
            
            const label = document.createElement('label');
            label.className = 'form-check-label d-flex align-items-center';
            label.htmlFor = checkbox.id;
            
            // 成员颜色圆点
            const colorDot = document.createElement('span');
            colorDot.className = 'share-group-color-dot me-2';
            colorDot.style.backgroundColor = member.member_color || '#6c757d';
            
            label.appendChild(colorDot);
            label.appendChild(document.createTextNode(member.username || '未知用户'));
            
            div.appendChild(checkbox);
            div.appendChild(label);
            filterList.appendChild(div);
        });
        
        console.log('[ShareGroupManager] 成员筛选列表已更新:', members.length, '个成员');
        
        // 恢复之前保存的筛选状态
        if (window.eventManager && window.eventManager.loadMemberFiltersToUI) {
            const filters = window.settingsManager?.settings?.calendarFilters;
            window.eventManager.loadMemberFiltersToUI(filters || {});
        }
    },

    /**
     * 获取选中的成员ID列表
     */
    getSelectedMemberIds() {
        const filterList = document.getElementById('memberFilterList');
        if (!filterList) return null;
        
        const checkboxes = filterList.querySelectorAll('input[type="checkbox"]:checked');
        return Array.from(checkboxes).map(cb => parseInt(cb.value));
    },

    /**
     * 隐藏成员筛选区域（切换到非群组视图时）
     */
    hideMemberFilter() {
        const filterSection = document.getElementById('memberFilterSection');
        if (filterSection) {
            filterSection.style.display = 'none';
        }
    },

    /**
     * 启动轮询检测更新
     */
    startPolling() {
        // 每30秒检查一次群组更新
        this.state.pollingInterval = setInterval(() => {
            this.checkGroupUpdates();
        }, 30000);
    },

    /**
     * 检查群组更新
     */
    async checkGroupUpdates() {
        for (const group of this.state.myGroups) {
            const groupId = group.share_group_id;
            const localVersion = this.state.groupVersions[groupId] || 0;
            
            try {
                const response = await fetch(`/api/share-groups/${groupId}/check-update/?version=${localVersion}`, {
                    credentials: 'same-origin',
                    headers: {
                        'X-CSRFToken': window.CSRF_TOKEN
                    }
                });

                if (response.ok) {
                    const data = await response.json();
                    
                    if (data.has_update) {
                        // 显示更新徽章
                        const tab = document.querySelector(`.calendar-tab[data-id="${groupId}"]`);
                        if (tab) {
                            const badge = tab.querySelector('.update-badge');
                            if (badge) badge.style.display = 'inline';
                        }
                        
                        // 如果当前正在查看该群组，自动刷新
                        if (this.state.currentGroupId === groupId) {
                            await this.loadGroupCalendar(groupId);
                        }
                    }
                }
            } catch (error) {
                console.error('[ShareGroupManager] 检查更新错误:', error);
            }
        }
    },

    /**
     * 显示群组操作菜单
     */
    /**
     * 显示创建群组弹窗（改为直接打开管理面板）
     */
    showCreateGroupModal() {
        this.showManageGroupsModal();
        // 切换到创建群组标签
        setTimeout(() => {
            document.getElementById('create-group-tab')?.click();
        }, 100);
    },

    /**
     * 创建群组（兼容旧代码，调用面板方法）
     */
    async createGroup() {
        return this.createGroupInPanel();
    },

    /**
     * 显示加入群组弹窗（改为直接打开管理面板）
     */
    showJoinGroupModal() {
        this.showManageGroupsModal();
        // 切换到加入群组标签
        setTimeout(() => {
            document.getElementById('join-group-tab')?.click();
        }, 100);
    },

    /**
     * 加入群组（兼容旧代码，调用面板方法）
     */
    async joinGroup() {
        return this.joinGroupInPanel();
    },

    /**
     * 渲染群组选择器（用于事件编辑）
     */
    renderGroupSelectors() {
        const newEventSelector = document.getElementById('newEventShareGroupsSelector');
        const editEventSelector = document.getElementById('eventShareGroupsSelector');
        
        if (this.state.myGroups.length === 0) {
            const emptyHTML = '<small class="text-muted">暂无群组，请先创建或加入群组</small>';
            if (newEventSelector) newEventSelector.innerHTML = emptyHTML;
            if (editEventSelector) editEventSelector.innerHTML = emptyHTML;
            return;
        }
        
        let html = '';
        this.state.myGroups.forEach(group => {
            html += `
                <div class="share-group-option">
                    <input type="checkbox" id="share_group_${group.share_group_id}" 
                           value="${group.share_group_id}">
                    <label for="share_group_${group.share_group_id}">
                        <i class="fas fa-users"></i>
                        ${this.escapeHtml(group.share_group_name)}
                    </label>
                </div>
            `;
        });
        
        if (newEventSelector) newEventSelector.innerHTML = html;
        if (editEventSelector) editEventSelector.innerHTML = html;
    },

    /**
     * 获取选中的群组ID列表
     */
    getSelectedGroups(selectorId) {
        const selector = document.getElementById(selectorId);
        if (!selector) return [];
        
        const selected = [];
        const checkboxes = selector.querySelectorAll('input:checked');
        checkboxes.forEach(checkbox => {
            selected.push(checkbox.value);
        });
        return selected;
    },

    /**
     * 设置选中的群组（用于编辑）
     */
    setSelectedGroups(selectorId, groupIds) {
        const selector = document.getElementById(selectorId);
        if (!selector) return;
        
        // 取消所有选中
        const allCheckboxes = selector.querySelectorAll('input');
        allCheckboxes.forEach(checkbox => {
            checkbox.checked = false;
        });
        
        // 设置指定的选中
        groupIds.forEach(id => {
            const checkbox = selector.querySelector(`input[value="${id}"]`);
            if (checkbox) checkbox.checked = true;
        });
    },

    /**
     * 显示管理群组弹窗
     */
    async showManageGroupsModal() {
        // 显示管理弹窗
        const modalEl = document.getElementById('manageShareGroupsModal');
        if (modalEl) {
            const modal = new bootstrap.Modal(modalEl);
            modal.show();
            
            // 加载群组列表
            await this.loadGroupsForManagement();
            
            // 确保切换到"我的群组"标签，并隐藏编辑/详情标签
            setTimeout(() => {
                document.getElementById('my-groups-tab')?.click();
                document.getElementById('edit-group-tab-item').style.display = 'none';
                document.getElementById('group-detail-tab-item').style.display = 'none';
            }, 100);
        }
    },

    /**
     * 加载群组列表用于管理界面
     */
    async loadGroupsForManagement() {
        try {
            // 添加时间戳防止缓存
            const timestamp = new Date().getTime();
            const response = await fetch(`/api/share-groups/my-groups/?_t=${timestamp}`, {
                credentials: 'same-origin',
                headers: {
                    'X-CSRFToken': window.CSRF_TOKEN
                }
            });

            if (response.ok) {
                const data = await response.json();
                this.renderGroupsList(data.groups || []);
            } else {
                console.error('[ShareGroupManager] 加载群组列表失败');
            }
        } catch (error) {
            console.error('[ShareGroupManager] 加载群组列表错误:', error);
        }
    },

    /**
     * 渲染群组列表
     */
    renderGroupsList(groups) {
        const container = document.getElementById('shareGroupsList');
        if (!container) return;
        
        if (!groups || groups.length === 0) {
            container.innerHTML = `
                <div class="empty-groups-state">
                    <i class="fas fa-users-slash"></i>
                    <p>您还没有加入任何群组</p>
                    <button class="btn btn-primary" onclick="document.getElementById('join-group-tab').click()">
                        <i class="fas fa-plus me-2"></i>加入群组
                    </button>
                </div>
            `;
            return;
        }

        const groupsHtml = groups.map(group => {
            const roleClass = group.role === 'owner' ? 'owner' : (group.role === 'admin' ? 'admin' : 'member');
            const roleText = group.role === 'owner' ? '群主' : (group.role === 'admin' ? '管理员' : '成员');
            
            // 转义文本内容
            const escapedName = this.escapeHtml(group.share_group_name);
            const escapedDesc = this.escapeHtml(group.share_group_description || '');
            const groupColor = group.share_group_color || '#007bff';  // 修复：使用正确的字段名
            
            // 只有群主才能显示编辑和删除按钮
            const ownerButtons = group.role === 'owner' ? `
                <button class="btn btn-sm btn-outline-warning" onclick="shareGroupManager.showEditGroupModal('${group.share_group_id}', \`${escapedName}\`, \`${escapedDesc}\`, '${groupColor}')">
                    <i class="fas fa-edit me-1"></i>编辑信息
                </button>
                <button class="btn btn-sm btn-outline-danger" onclick="shareGroupManager.confirmDeleteGroup('${group.share_group_id}', \`${escapedName}\`)">
                    <i class="fas fa-trash-alt me-1"></i>删除群组
                </button>
            ` : '';

            return `
                <div class="share-group-card" data-group-id="${group.share_group_id}">
                    <div class="share-group-header">
                        <div class="share-group-info">
                            <h4>
                                <span class="share-group-color-dot" style="background-color: ${groupColor}"></span>
                                ${escapedName}
                                <span class="share-group-role-badge ${roleClass}">${roleText}</span>
                            </h4>
                            <div class="share-group-id">
                                ID: ${group.share_group_id}
                                <i class="fas fa-copy" onclick="shareGroupManager.copyGroupId('${group.share_group_id}')" title="复制ID"></i>
                            </div>
                            ${group.description ? `<div class="share-group-description">${escapedDesc}</div>` : ''}
                            <div class="share-group-meta">
                                <span><i class="fas fa-users me-1"></i>${group.member_count || 1} 人</span>
                                <span><i class="fas fa-calendar me-1"></i>创建于 ${new Date(group.created_at).toLocaleDateString()}</span>
                            </div>
                        </div>
                        <div class="share-group-actions">
                            <button class="btn btn-sm btn-outline-primary" onclick="shareGroupManager.showGroupDetails('${group.share_group_id}')">
                                <i class="fas fa-info-circle me-1"></i>详情
                            </button>
                            ${ownerButtons}
                            ${group.role !== 'owner' ? `
                                <button class="btn btn-sm btn-outline-warning" onclick="shareGroupManager.confirmLeaveGroup('${group.share_group_id}', \`${escapedName}\`)">
                                    <i class="fas fa-sign-out-alt me-1"></i>退出群组
                                </button>
                            ` : ''}
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        container.innerHTML = groupsHtml;
    },
    /**
     * 在面板中创建群组
     */
    async createGroupInPanel() {
        const nameInput = document.getElementById('createGroupName');
        const colorInput = document.getElementById('createGroupColor');
        const descInput = document.getElementById('createGroupDescription');
        const memberColorInput = document.getElementById('createMemberColor');
        
        const name = nameInput?.value.trim();
        const color = colorInput?.value || '#3498db';
        const description = descInput?.value.trim() || '';
        const memberColor = memberColorInput?.value || '#3498db';
        
        if (!name) {
            alert('请输入群组名称');
            return;
        }
        
        try {
            const response = await fetch('/api/share-groups/create/', {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.CSRF_TOKEN
                },
                body: JSON.stringify({
                    share_group_name: name,
                    share_group_color: color,
                    share_group_description: description,
                    member_color: memberColor
                })
            });

            if (response.ok) {
                const data = await response.json();
                alert('群组创建成功！\n群组ID: ' + data.group.share_group_id);
                
                // 重置表单
                this.resetCreateForm();
                
                // 重新加载群组列表
                await this.loadMyGroups();
                await this.loadGroupsForManagement();
                
                // 切换到"我的群组"标签
                document.getElementById('my-groups-tab').click();
            } else {
                const error = await response.json();
                alert('创建失败: ' + (error.message || '未知错误'));
            }
        } catch (error) {
            console.error('[ShareGroupManager] 创建群组错误:', error);
            alert('创建失败，请稍后重试');
        }
    },

    /**
     * 重置创建表单
     */
    resetCreateForm() {
        const nameInput = document.getElementById('createGroupName');
        const colorInput = document.getElementById('createGroupColor');
        const descInput = document.getElementById('createGroupDescription');
        const memberColorInput = document.getElementById('createMemberColor');
        
        if (nameInput) nameInput.value = '';
        if (colorInput) colorInput.value = '#3498db';
        if (descInput) descInput.value = '';
        if (memberColorInput) memberColorInput.value = '#3498db';
    },

    /**
     * 在面板中加入群组
     */
    async joinGroupInPanel() {
        const idInput = document.getElementById('joinGroupIdInput');
        const memberColorInput = document.getElementById('joinMemberColor');
        
        const groupId = idInput?.value.trim();
        const memberColor = memberColorInput?.value || '#3498db';
        
        if (!groupId) {
            alert('请输入群组ID');
            return;
        }
        
        try {
            const response = await fetch('/api/share-groups/join/', {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.CSRF_TOKEN
                },
                body: JSON.stringify({
                    share_group_id: groupId,
                    member_color: memberColor
                })
            });

            if (response.ok) {
                alert('加入群组成功！');
                
                // 重置表单
                this.resetJoinForm();
                
                // 重新加载群组列表
                await this.loadMyGroups();
                await this.loadGroupsForManagement();
                
                // 切换到"我的群组"标签
                document.getElementById('my-groups-tab').click();
            } else {
                const error = await response.json();
                alert('加入失败: ' + (error.message || '未知错误'));
            }
        } catch (error) {
            console.error('[ShareGroupManager] 加入群组错误:', error);
            alert('加入失败，请稍后重试');
        }
    },

    /**
     * 重置加入表单
     */
    resetJoinForm() {
        const idInput = document.getElementById('joinGroupIdInput');
        const memberColorInput = document.getElementById('joinMemberColor');
        
        if (idInput) idInput.value = '';
        if (memberColorInput) memberColorInput.value = '#3498db';
    },

    /**
     * 显示编辑群组面板（在同一弹窗的标签页中）
     */
    showEditGroupModal(groupId, groupName, groupDescription, groupColor) {
        // 填充编辑表单（使用 ShareGroup 专用的 ID）
        document.getElementById('editShareGroupId').value = groupId;
        document.getElementById('editShareGroupName').value = groupName;
        document.getElementById('editShareGroupColor').value = groupColor || '#3498db';
        document.getElementById('editShareGroupDescription').value = groupDescription || '';
        
        // 显示编辑标签
        document.getElementById('edit-group-tab-item').style.display = 'block';
        
        // 切换到编辑标签
        document.getElementById('edit-group-tab').click();
    },

    /**
     * 关闭编辑标签
     */
    closeEditTab(event) {
        if (event) {
            event.stopPropagation();
            event.preventDefault();
        }
        
        // 隐藏编辑标签
        document.getElementById('edit-group-tab-item').style.display = 'none';
        
        // 切换回我的群组标签
        document.getElementById('my-groups-tab').click();
    },

    /**
     * 在面板中更新群组信息
     */
    async updateGroupInfoInPanel() {
        const groupId = document.getElementById('editShareGroupId')?.value;
        const name = document.getElementById('editShareGroupName')?.value.trim();
        const color = document.getElementById('editShareGroupColor')?.value;
        const description = document.getElementById('editShareGroupDescription')?.value.trim();
        
        if (!name) {
            alert('群组名称不能为空');
            return;
        }
        
        console.log('[ShareGroupManager] 准备更新群组:', {groupId, name, color, description});
        
        try {
            const response = await fetch(`/api/share-groups/${groupId}/update/`, {
                method: 'PUT',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.CSRF_TOKEN
                },
                body: JSON.stringify({
                    share_group_name: name,
                    share_group_color: color,
                    share_group_description: description
                })
            });

            if (response.ok) {
                alert('群组信息更新成功！');
                
                // 关闭编辑标签
                this.closeEditTab();
                
                // 重新加载群组列表
                await this.loadMyGroups();
                await this.loadGroupsForManagement();
            } else {
                const error = await response.json();
                alert('更新失败: ' + (error.message || '未知错误'));
            }
        } catch (error) {
            console.error('[ShareGroupManager] 更新群组信息错误:', error);
            alert('更新失败，请稍后重试');
        }
    },

    /**
     * 复制群组ID
     */
    copyGroupId(groupId) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(groupId).then(() => {
                // 临时提示
                const tooltip = document.createElement('div');
                tooltip.textContent = '已复制';
                tooltip.style.cssText = 'position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: #333; color: white; padding: 8px 16px; border-radius: 4px; z-index: 9999;';
                document.body.appendChild(tooltip);
                setTimeout(() => tooltip.remove(), 1500);
            }).catch(err => {
                console.error('Failed to copy:', err);
                alert('复制失败，请手动复制');
            });
        } else {
            // 降级方案：使用旧的 execCommand
            const input = document.createElement('input');
            input.value = groupId;
            document.body.appendChild(input);
            input.select();
            try {
                document.execCommand('copy');
                alert('已复制群组ID');
            } catch (err) {
                alert('复制失败，请手动复制');
            }
            document.body.removeChild(input);
        }
    },

    /**
     * 确认退出群组
     */
    confirmLeaveGroup(groupId, groupName) {
        if (confirm(`确定要退出群组"${groupName}"吗？`)) {
            this.leaveGroup(groupId);
        }
    },

    /**
     * 退出群组
     */
    async leaveGroup(groupId) {
        try {
            const response = await fetch(`/api/share-groups/${groupId}/leave/`, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'X-CSRFToken': window.CSRF_TOKEN
                }
            });

            if (response.ok) {
                alert('已成功退出群组');
                
                // 如果当前正在查看该群组，切换回我的日历
                if (this.state.currentGroupId === groupId) {
                    this.loadMyCalendar();
                }
                
                // 重新加载群组列表
                await this.loadMyGroups();
                await this.loadGroupsForManagement();
            } else {
                const error = await response.json();
                alert('退出失败: ' + (error.error || '未知错误'));
            }
        } catch (error) {
            console.error('[ShareGroupManager] 退出群组错误:', error);
            alert('退出群组失败，请稍后重试');
        }
    },

    /**
     * 确认删除群组
     */
    confirmDeleteGroup(groupId, groupName) {
        if (confirm(`确定要删除群组"${groupName}"吗？\n\n此操作不可恢复，将删除所有群组数据！`)) {
            this.deleteGroup(groupId);
        }
    },

    /**
     * 删除群组（仅群主）
     */
    async deleteGroup(groupId) {
        try {
            const response = await fetch(`/api/share-groups/${groupId}/delete/`, {
                method: 'DELETE',
                credentials: 'same-origin',
                headers: {
                    'X-CSRFToken': window.CSRF_TOKEN
                }
            });

            if (response.ok) {
                alert('群组已成功删除');
                
                // 如果当前正在查看该群组，切换回我的日历
                if (this.state.currentGroupId === groupId) {
                    this.loadMyCalendar();
                }
                
                // 重新加载群组列表
                await this.loadMyGroups();
                await this.loadGroupsForManagement();
            } else {
                const error = await response.json();
                alert('删除失败: ' + (error.error || '未知错误'));
            }
        } catch (error) {
            console.error('[ShareGroupManager] 删除群组错误:', error);
            alert('删除群组失败，请稍后重试');
        }
    },

    /**
     * 显示群组详情
     */
    /**
     * 显示群组详情面板（在同一弹窗的标签页中）
     */
    async showGroupDetails(groupId) {
        try {
            const response = await fetch(`/api/share-groups/${groupId}/members/`, {
                credentials: 'same-origin',
                headers: {
                    'X-CSRFToken': window.CSRF_TOKEN
                }
            });

            if (response.ok) {
                const data = await response.json();
                this.fillGroupDetailPanel(groupId, data.group, data.members);
            } else {
                const error = await response.json();
                alert('加载详情失败: ' + (error.error || '未知错误'));
            }
        } catch (error) {
            console.error('[ShareGroupManager] 加载群组详情错误:', error);
            alert('加载群组详情失败，请稍后重试');
        }
    },

    /**
     * 填充群组详情面板
     */
    fillGroupDetailPanel(groupId, group, members) {
        // 保存当前群组ID到实例变量（用于更新成员颜色）
        this.currentDetailGroupId = groupId;
        
        // 填充群组名称和颜色
        const nameEl = document.getElementById('detailGroupName');
        if (nameEl) {
            nameEl.textContent = group.name;
        }
        
        const colorDot = document.getElementById('detailGroupColorDot');
        if (colorDot && group.color) {
            colorDot.style.backgroundColor = group.color;
        }
        
        // 填充群组ID
        const idEl = document.getElementById('detailGroupId');
        if (idEl) {
            idEl.textContent = groupId;
        }
        
        // 填充描述（如果有）
        const descEl = document.getElementById('detailGroupDesc');
        const descContainer = document.getElementById('detailGroupDescContainer');
        if (descEl && descContainer) {
            if (group.description) {
                descEl.textContent = group.description;
                descContainer.style.display = 'block';
            } else {
                descContainer.style.display = 'none';
            }
        }
        
        // 填充我的成员颜色
        // 尝试多种方式找到当前用户的成员信息
        let myMembership = null;
        
        // 方式1: 使用 window.currentUserName
        if (window.currentUserName) {
            myMembership = members.find(m => m.username === window.currentUserName);
        }
        
        // 方式2: 使用 currentUsername 输入框的值
        if (!myMembership) {
            const usernameInput = document.getElementById('currentUsername');
            if (usernameInput && usernameInput.value) {
                myMembership = members.find(m => m.username === usernameInput.value);
            }
        }
        
        // 方式3: 使用 role='owner' 且是第一个加入的成员（不太可靠，仅作后备）
        if (!myMembership && group.owner_id) {
            myMembership = members.find(m => m.user_id === group.owner_id);
        }
        
        const memberColorInput = document.getElementById('detailMyMemberColor');
        
        console.log('[ShareGroupManager] 设置我的成员颜色:', {
            currentUserName: window.currentUserName,
            myMembership,
            memberColor: myMembership?.member_color,
            allMembers: members
        });
        
        if (memberColorInput) {
            if (myMembership && myMembership.member_color) {
                memberColorInput.value = myMembership.member_color;
                console.log('[ShareGroupManager] ✅ 设置颜色选择器为:', myMembership.member_color);
            } else {
                memberColorInput.value = '#3498db';
                console.log('[ShareGroupManager] ⚠️ 未找到我的成员信息，使用默认颜色');
            }
        }
        
        // 填充成员列表
        const membersEl = document.getElementById('detailMembersList');
        if (membersEl) {
            const membersHtml = members.map(member => {
                const roleClass = member.role === 'owner' ? 'owner' : (member.role === 'admin' ? 'admin' : 'member');
                const roleText = member.role === 'owner' ? '群主' : (member.role === 'admin' ? '管理员' : '成员');
                const escapedUsername = this.escapeHtml(member.username);
                const memberColor = member.member_color || '#3498db';
                
                return `
                    <div class="member-item">
                        <div class="member-info">
                            <i class="fas fa-circle me-2" style="color: ${memberColor};"></i>
                            <span>${escapedUsername}</span>
                        </div>
                        <span class="share-group-role-badge ${roleClass}">${roleText}</span>
                    </div>
                `;
            }).join('');
            
            membersEl.innerHTML = membersHtml;
        }
        
        // 显示详情标签
        document.getElementById('group-detail-tab-item').style.display = 'block';
        
        // 切换到详情标签
        document.getElementById('group-detail-tab').click();
    },

    /**
     * 关闭详情标签
     */
    closeDetailTab(event) {
        if (event) {
            event.stopPropagation();
            event.preventDefault();
        }
        
        // 隐藏详情标签
        document.getElementById('group-detail-tab-item').style.display = 'none';
        
        // 切换回我的群组标签
        document.getElementById('my-groups-tab').click();
    },

    /**
     * 从详情面板复制群组ID
     */
    copyGroupIdFromDetail() {
        const groupId = document.getElementById('detailGroupId')?.textContent;
        if (groupId) {
            this.copyGroupId(groupId);
        }
    },

    /**
     * 更新我的成员颜色
     */
    async updateMyMemberColor() {
        const groupId = this.currentDetailGroupId;
        const memberColorInput = document.getElementById('detailMyMemberColor');
        const memberColor = memberColorInput?.value;
        
        if (!groupId) {
            alert('无法获取当前群组ID');
            return;
        }
        
        if (!memberColor) {
            alert('请选择一个颜色');
            return;
        }
        
        try {
            const response = await fetch(`/api/share-groups/${groupId}/update-member-color/`, {
                method: 'PUT',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.CSRF_TOKEN
                },
                body: JSON.stringify({
                    member_color: memberColor
                })
            });

            if (response.ok) {
                alert('成员颜色更新成功！');
                
                // 重新加载群组数据
                await this.loadMyGroups();
                await this.loadGroupsForManagement();
                
                // 刷新详情面板
                await this.showGroupDetails(groupId);
                
                // 如果当前正在查看该群组的日历，刷新日历
                if (window.currentGroupId === groupId) {
                    if (typeof window.loadGroupCalendar === 'function') {
                        await window.loadGroupCalendar(groupId);
                    }
                }
            } else {
                const error = await response.json();
                alert('更新失败: ' + (error.message || '未知错误'));
            }
        } catch (error) {
            console.error('[ShareGroupManager] 更新成员颜色错误:', error);
            alert('更新失败，请稍后重试');
        }
    },

    /**
     * 获取事件的日程组颜色
     */
    getEventGroupColor(groupID) {
        // 尝试从 window.eventManager 获取日程组颜色
        if (window.eventManager && window.eventManager.groups) {
            const group = window.eventManager.groups.find(g => g.id === groupID);
            if (group && group.color) {
                return group.color;
            }
        }
        
        // 尝试从 window.events_groups 获取
        if (window.events_groups) {
            const group = window.events_groups.find(g => g.id === groupID);
            if (group && group.color) {
                return group.color;
            }
        }
        
        // 默认颜色
        return '#3498db';
    },

    /**
     * HTML转义
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    /**
     * 清理资源
     */
    destroy() {
        if (this.state.pollingInterval) {
            clearInterval(this.state.pollingInterval);
        }
    }
};

// 将 shareGroupManager 暴露到全局作用域
window.shareGroupManager = shareGroupManager;

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    console.log('[ShareGroupManager] DOM加载完成，立即初始化');
    
    // 立即初始化，不再延迟
    shareGroupManager.init().catch(err => {
        console.error('[ShareGroupManager] 初始化失败:', err);
    });
});
