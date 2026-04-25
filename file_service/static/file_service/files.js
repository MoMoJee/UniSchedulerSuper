/**
 * 文件管理器 - files.js
 * v20260328-001
 */

/* ============================================
   全局状态
   ============================================ */

const API_BASE = '/api/files';

const state = {
    currentFolderId: null,
    currentCategory: '',
    viewMode: 'list',         // 'list' | 'grid'
    folders: [],
    files: [],
    allFolders: [],           // 完整文件夹树
    quota: null,
    breadcrumb: [],
    searchTimeout: null,
    ctxTarget: null,           // 右键菜单的目标文件/文件夹
    ctxTargetType: null,       // 'file' | 'folder'
    moveTargetFolderId: undefined,
    renameTargetType: null,    // 'file' | 'folder'
    renameTargetId: null,
    dragItem: null,            // 当前被拖拽的文件/文件夹 { type, id, name }
};

/* ============================================
   工具函数
   ============================================ */

function getCsrfToken() {
    const c = document.cookie.match(/csrftoken=([^;]+)/);
    return c ? c[1] : '';
}

function apiHeaders() {
    return {
        'X-CSRFToken': getCsrfToken(),
    };
}

function apiJsonHeaders() {
    return {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
    };
}

function formatSize(bytes) {
    if (bytes === 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
}

function formatDate(isoStr) {
    const d = new Date(isoStr);
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    if (isToday) return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
}

function getFileIconClass(category, mimeType, filename) {
    if (category === 'image') return ['fas fa-image', 'icon-image'];
    if (!mimeType) return ['fas fa-file', 'icon-document'];
    if (mimeType.includes('pdf')) return ['fas fa-file-pdf', 'icon-pdf'];
    if (mimeType.includes('word') || mimeType.includes('document')) return ['fas fa-file-word', 'icon-word'];
    if (mimeType.includes('excel') || mimeType.includes('sheet')) return ['fas fa-file-excel', 'icon-excel'];
    return ['fas fa-file-alt', 'icon-document'];
}

function getStatusLabel(parseStatus) {
    const map = {
        'none': '',
        'pending': '<span class="file-status">待解析</span>',
        'processing': '<span class="file-status processing">解析中</span>',
        'completed': '<span class="file-status completed">已解析</span>',
        'failed': '<span class="file-status failed">解析失败</span>',
    };
    return map[parseStatus] || '';
}

/* ============================================
   文件管理器
   ============================================ */

const fileManager = {
    // ---------- 初始化 ----------
    init() {
        // 支持通过 URL 参数跳转到指定文件夹
        const urlParams = new URLSearchParams(window.location.search);
        const folderIdParam = urlParams.get('folder_id');
        if (folderIdParam) {
            state.currentFolderId = parseInt(folderIdParam);
        }
        this.loadFiles();
        this.loadFileTree();
        this.initDragDrop();
        this.initContextMenuClose();
    },

    // ---------- 加载文件列表 ----------
    async loadFiles() {
        const params = new URLSearchParams();
        if (state.currentFolderId) params.set('folder_id', state.currentFolderId);
        if (state.currentCategory) params.set('category', state.currentCategory);

        try {
            const res = await fetch(`${API_BASE}/?${params}`, { credentials: 'same-origin' });
            const data = await res.json();
            state.folders = data.folders || [];
            state.files = data.files || [];
            state.breadcrumb = data.breadcrumb || [];
            state.quota = data.quota || null;

            this.renderBreadcrumb();
            this.renderFileList();
            this.renderQuota();
            this.highlightTreeNode();
        } catch (e) {
            showToast('加载文件失败: ' + e.message, 'error');
        }
    },

    // ---------- 文件树 ----------
    async loadFileTree() {
        try {
            const res = await fetch(`${API_BASE}/pick/`, { credentials: 'same-origin' });
            const data = await res.json();
            state.allFolders = data.folders || [];
            this.renderFileTree();
        } catch (e) {
            document.getElementById('fileTree').innerHTML = '<div class="tree-empty">加载失败</div>';
        }
    },

    renderFileTree() {
        const tree = document.getElementById('fileTree');
        const folders = state.allFolders;

        // 构建层级
        const childrenMap = {};   // parent_id -> [folder]
        folders.forEach(f => {
            const pid = f.parent_id || 'root';
            if (!childrenMap[pid]) childrenMap[pid] = [];
            childrenMap[pid].push(f);
        });

        const buildNode = (parentId) => {
            const children = childrenMap[parentId] || [];
            if (children.length === 0) return '';
            return children.map(f => {
                const hasChildren = !!childrenMap[f.id];
                const isActive = state.currentFolderId === f.id;
                const chevron = hasChildren
                    ? `<i class="fas fa-chevron-right tree-chevron" onclick="event.stopPropagation(); fileManager.toggleTreeNode(this)"></i>`
                    : '<span class="tree-chevron-placeholder"></span>';
                return `<div class="tree-node">
                    <div class="tree-item${isActive ? ' active' : ''}" data-folder-id="${f.id}"
                         onclick="fileManager.navigate(${f.id})"
                         ondragover="event.preventDefault(); this.classList.add('drag-over')"
                         ondragleave="this.classList.remove('drag-over')"
                         ondrop="fileManager.handleTreeDrop(event, ${f.id}); this.classList.remove('drag-over')">
                        ${chevron}
                        <i class="fas fa-folder me-1 tree-folder-icon"></i>
                        <span class="tree-item-name" title="${this.escAttr(f.name)}">${this.escHtml(f.name)}</span>
                    </div>
                    <div class="tree-children" style="display:none;">${buildNode(f.id)}</div>
                </div>`;
            }).join('');
        };

        const rootActive = state.currentFolderId === null;
        tree.innerHTML = `
            <div class="tree-item root-tree-item${rootActive ? ' active' : ''}" data-folder-id=""
                 onclick="fileManager.navigate(null)"
                 ondragover="event.preventDefault(); this.classList.add('drag-over')"
                 ondragleave="this.classList.remove('drag-over')"
                 ondrop="fileManager.handleTreeDrop(event, null); this.classList.remove('drag-over')">
                <i class="fas fa-home me-1"></i>
                <span class="tree-item-name">全部文件</span>
            </div>
            ${buildNode('root')}
        `;

        this.highlightTreeNode();
    },

    toggleTreeNode(chevron) {
        chevron.classList.toggle('expanded');
        const children = chevron.closest('.tree-node').querySelector('.tree-children');
        if (children) children.style.display = children.style.display === 'none' ? '' : 'none';
    },

    highlightTreeNode() {
        document.querySelectorAll('.tree-item').forEach(el => {
            const fid = el.dataset.folderId;
            const isActive = fid === '' ? state.currentFolderId === null : parseInt(fid) === state.currentFolderId;
            el.classList.toggle('active', isActive);
        });
        // 自动展开到当前节点的祖先
        if (state.currentFolderId !== null) {
            const active = document.querySelector(`.tree-item[data-folder-id="${state.currentFolderId}"]`);
            if (active) {
                let parent = active.closest('.tree-children');
                while (parent) {
                    parent.style.display = '';
                    const chevron = parent.previousElementSibling?.querySelector('.tree-chevron');
                    if (chevron) chevron.classList.add('expanded');
                    parent = parent.parentElement?.closest('.tree-children');
                }
            }
        }
    },

    handleTreeDrop(event, targetFolderId) {
        event.preventDefault();
        // 如果是从外部拖入的文件
        if (event.dataTransfer.files.length > 0) {
            const prevFolder = state.currentFolderId;
            state.currentFolderId = targetFolderId;
            this.uploadFiles(Array.from(event.dataTransfer.files));
            state.currentFolderId = prevFolder;
            return;
        }
        if (!state.dragItem) return;
        const { type, id } = state.dragItem;
        if (type === 'file') {
            this.moveFileTo(id, targetFolderId);
        }
        state.dragItem = null;
        this.hideDragTrash();
    },

    // ---------- 渲染面包屑 ----------
    renderBreadcrumb() {
        const nav = document.getElementById('breadcrumbNav');
        let html = '';
        state.breadcrumb.forEach((item, i) => {
            if (i > 0) html += '<span class="breadcrumb-sep">/</span>';
            const isLast = i === state.breadcrumb.length - 1;
            if (item.id === null) {
                html += `<a href="#" class="breadcrumb-item ${isLast ? 'active' : ''}" onclick="fileManager.navigate(null); return false;"><i class="fas fa-home"></i></a>`;
            } else {
                html += `<a href="#" class="breadcrumb-item ${isLast ? 'active' : ''}" onclick="fileManager.navigate(${item.id}); return false;">${this.escHtml(item.name)}</a>`;
            }
        });
        nav.innerHTML = html;
    },

    // ---------- 渲染文件列表 ----------
    renderFileList() {
        const container = document.getElementById('filesList');
        const emptyState = document.getElementById('emptyState');
        const searchResults = document.getElementById('searchResults');
        searchResults.style.display = 'none';

        const isGrid = state.viewMode === 'grid';
        container.className = 'files-list' + (isGrid ? ' grid-view' : '');

        if (state.folders.length === 0 && state.files.length === 0) {
            container.style.display = 'none';
            emptyState.style.display = '';
            return;
        }
        container.style.display = '';
        emptyState.style.display = 'none';

        let html = '';

        // 返回上级目录按钮 (当不在根目录时)
        if (state.currentFolderId !== null) {
            const parentId = this.getParentFolderId();
            if (isGrid) {
                html += `<div class="file-item-grid parent-dir-item"
                    ondblclick="fileManager.navigate(${parentId === null ? 'null' : parentId})"
                    ondragover="event.preventDefault(); this.classList.add('drag-over')"
                    ondragleave="this.classList.remove('drag-over')"
                    ondrop="fileManager.handleFolderItemDrop(event, ${parentId === null ? 'null' : parentId}); this.classList.remove('drag-over')">
                    <div class="file-icon icon-parent"><i class="fas fa-level-up-alt"></i></div>
                    <div class="file-name">返回上级</div>
                </div>`;
            } else {
                html += `<div class="file-item-list parent-dir-item"
                    ondblclick="fileManager.navigate(${parentId === null ? 'null' : parentId})"
                    ondragover="event.preventDefault(); this.classList.add('drag-over')"
                    ondragleave="this.classList.remove('drag-over')"
                    ondrop="fileManager.handleFolderItemDrop(event, ${parentId === null ? 'null' : parentId}); this.classList.remove('drag-over')">
                    <div class="file-icon icon-parent"><i class="fas fa-level-up-alt"></i></div>
                    <div class="file-info">
                        <div class="file-name">返回上级</div>
                    </div>
                </div>`;
            }
        }

        // 文件夹
        state.folders.forEach(f => {
            if (isGrid) {
                html += `<div class="file-item-grid" ondblclick="fileManager.navigate(${f.id})" oncontextmenu="fileManager.showFolderMenu(event, ${f.id}, '${this.escAttr(f.name)}')"
                    ondragover="event.preventDefault(); this.classList.add('drag-over')"
                    ondragleave="this.classList.remove('drag-over')"
                    ondrop="fileManager.handleFolderItemDrop(event, ${f.id}); this.classList.remove('drag-over')">
                    <div class="file-icon icon-folder"><i class="fas fa-folder"></i></div>
                    <div class="file-name" title="${this.escAttr(f.name)}">${this.escHtml(f.name)}</div>
                    <div class="file-meta">${f.file_count || 0} 个文件</div>
                </div>`;
            } else {
                html += `<div class="file-item-list" ondblclick="fileManager.navigate(${f.id})" oncontextmenu="fileManager.showFolderMenu(event, ${f.id}, '${this.escAttr(f.name)}')"
                    ondragover="event.preventDefault(); this.classList.add('drag-over')"
                    ondragleave="this.classList.remove('drag-over')"
                    ondrop="fileManager.handleFolderItemDrop(event, ${f.id}); this.classList.remove('drag-over')">
                    <div class="file-icon icon-folder"><i class="fas fa-folder"></i></div>
                    <div class="file-info">
                        <div class="file-name">${this.escHtml(f.name)}</div>
                        <div class="file-meta">${f.file_count || 0} 个文件</div>
                    </div>
                </div>`;
            }
        });

        // 文件
        state.files.forEach(f => {
            const [iconCls, iconBg] = getFileIconClass(f.category, f.mime_type, f.filename);
            const statusHtml = getStatusLabel(f.parse_status);
            const ctxCallArgs = `event, ${f.id}, '${this.escAttr(f.filename)}', '${f.category}', '${f.parse_status}'`;
            const dragStart = `fileManager.startDragItem(event, 'file', ${f.id}, '${this.escAttr(f.filename)}')`;
            const dragEnd = `fileManager.endDragItem()`;

            if (isGrid) {
                html += `<div class="file-item-grid" draggable="true" ondragstart="${dragStart}" ondragend="${dragEnd}"
                    ondblclick="fileManager.openFile(${f.id}, '${f.category}', '${f.parse_status}')" oncontextmenu="fileManager.showFileMenu(${ctxCallArgs})">
                    <div class="file-icon ${iconBg}"><i class="${iconCls}"></i></div>
                    <div class="file-name" title="${this.escAttr(f.filename)}">${this.escHtml(f.filename)}</div>
                    <div class="file-meta">${formatSize(f.file_size)}</div>
                </div>`;
            } else {
                html += `<div class="file-item-list" draggable="true" ondragstart="${dragStart}" ondragend="${dragEnd}"
                    ondblclick="fileManager.openFile(${f.id}, '${f.category}', '${f.parse_status}')" oncontextmenu="fileManager.showFileMenu(${ctxCallArgs})">
                    <div class="file-icon ${iconBg}"><i class="${iconCls}"></i></div>
                    <div class="file-info">
                        <div class="file-name">${this.escHtml(f.filename)}</div>
                        <div class="file-meta">${formatSize(f.file_size)} · ${formatDate(f.created_at)}</div>
                    </div>
                    ${statusHtml}
                </div>`;
            }
        });

        container.innerHTML = html;
    },

    // ---------- 渲染配额 ----------
    renderQuota() {
        if (!state.quota) return;
        const q = state.quota;
        const usedMB = (q.used_bytes / 1024 / 1024).toFixed(1);
        const maxMB = (q.max_storage_bytes / 1024 / 1024).toFixed(0);
        document.getElementById('quotaBar').style.width = q.usage_percent + '%';
        document.getElementById('quotaText').textContent = `${usedMB} / ${maxMB} MB（${q.file_count} 个文件）`;
        document.getElementById('quotaMini').textContent = `${usedMB}/${maxMB} MB`;
    },

    // ---------- 导航 ----------
    navigate(folderId) {
        state.currentFolderId = folderId;
        state.currentCategory = '';
        this.loadFiles();
    },

    toggleView() {
        state.viewMode = state.viewMode === 'list' ? 'grid' : 'list';
        const icon = document.querySelector('#viewToggle i');
        icon.className = state.viewMode === 'list' ? 'fas fa-th-large' : 'fas fa-list';
        this.renderFileList();
    },

    // ---------- 文件上传 ----------
    triggerUpload() {
        document.getElementById('fileUploadInput').click();
    },

    async handleFileSelect(files) {
        if (!files || files.length === 0) return;
        await this.uploadFiles(Array.from(files));
        document.getElementById('fileUploadInput').value = '';
    },

    async uploadFiles(fileArray) {
        const area = document.getElementById('uploadProgressArea');
        const list = document.getElementById('uploadProgressList');
        area.style.display = '';
        list.innerHTML = '';

        // 创建进度条
        const items = fileArray.map((f, i) => {
            const el = document.createElement('div');
            el.className = 'upload-progress-item';
            el.innerHTML = `<span class="filename">${this.escHtml(f.name)}</span>
                <div class="progress-bar-mini"><div class="progress-fill" id="pf${i}" style="width:0%"></div></div>
                <span class="status-icon" id="ps${i}"><i class="fas fa-spinner fa-spin"></i></span>`;
            list.appendChild(el);
            return el;
        });

        for (let i = 0; i < fileArray.length; i++) {
            const fd = new FormData();
            fd.append('file', fileArray[i]);
            if (state.currentFolderId) fd.append('folder_id', state.currentFolderId);

            try {
                document.getElementById('pf' + i).style.width = '60%';
                const res = await fetch(`${API_BASE}/upload/`, {
                    method: 'POST',
                    headers: apiHeaders(),
                    credentials: 'same-origin',
                    body: fd,
                });
                const data = await res.json();
                document.getElementById('pf' + i).style.width = '100%';

                if (res.ok && data.uploaded && data.uploaded.length > 0) {
                    document.getElementById('ps' + i).innerHTML = '<i class="fas fa-check status-icon success"></i>';
                } else {
                    const errMsg = data.errors?.[0]?.error || data.error || '上传失败';
                    document.getElementById('ps' + i).innerHTML = `<i class="fas fa-times status-icon error" title="${this.escAttr(errMsg)}"></i>`;
                    showToast(fileArray[i].name + ': ' + errMsg, 'error');
                }
            } catch (e) {
                document.getElementById('pf' + i).style.width = '100%';
                document.getElementById('ps' + i).innerHTML = '<i class="fas fa-times status-icon error"></i>';
                showToast(fileArray[i].name + ': 上传失败', 'error');
            }
        }

        this.loadFiles();
        setTimeout(() => { area.style.display = 'none'; list.innerHTML = ''; }, 3000);
    },

    // ---------- 拖拽上传 ----------
    initDragDrop() {
        const main = document.querySelector('.files-main');
        const overlay = document.getElementById('dropOverlay');
        let dragCounter = 0;

        main.addEventListener('dragenter', e => {
            e.preventDefault();
            dragCounter++;
            // 仅对外部文件显示上传覆盖层
            if (!state.dragItem) overlay.classList.add('active');
        });
        main.addEventListener('dragleave', e => { e.preventDefault(); dragCounter--; if (dragCounter <= 0) { overlay.classList.remove('active'); dragCounter = 0; } });
        main.addEventListener('dragover', e => e.preventDefault());
        main.addEventListener('drop', e => {
            e.preventDefault();
            dragCounter = 0;
            overlay.classList.remove('active');
            if (e.dataTransfer.files.length > 0 && !state.dragItem) {
                this.uploadFiles(Array.from(e.dataTransfer.files));
            }
        });

        // 垃圾桶拖拽区域
        const trashZone = document.getElementById('dragTrashZone');
        if (trashZone) {
            trashZone.addEventListener('dragover', e => { e.preventDefault(); trashZone.classList.add('drag-over'); });
            trashZone.addEventListener('dragleave', () => trashZone.classList.remove('drag-over'));
            trashZone.addEventListener('drop', e => this.handleTrashDrop(e));
        }
    },

    // ---------- URL 上传 ----------
    showUrlUploadDialog() {
        document.getElementById('urlUploadInput').value = '';
        const status = document.getElementById('urlUploadStatus');
        status.style.display = 'none';
        document.getElementById('urlUploadBtn').disabled = false;
        this.showModal('urlUploadModal');
        setTimeout(() => document.getElementById('urlUploadInput').focus(), 100);
    },

    async uploadFromUrl() {
        const url = document.getElementById('urlUploadInput').value.trim();
        if (!url) return showToast('请输入 URL', 'error');

        const status = document.getElementById('urlUploadStatus');
        const btn = document.getElementById('urlUploadBtn');
        btn.disabled = true;
        status.style.display = '';
        status.className = 'upload-status loading';
        status.textContent = '正在下载文件...';

        try {
            const res = await fetch(`${API_BASE}/upload-url/`, {
                method: 'POST',
                headers: apiJsonHeaders(),
                credentials: 'same-origin',
                body: JSON.stringify({
                    url: url,
                    folder_id: state.currentFolderId,
                }),
            });
            const data = await res.json();
            if (res.ok) {
                status.className = 'upload-status success';
                status.textContent = '导入成功: ' + (data.file?.filename || '');
                this.loadFiles();
                setTimeout(() => this.closeModal('urlUploadModal'), 1500);
            } else {
                status.className = 'upload-status error';
                status.textContent = data.error || '导入失败';
                btn.disabled = false;
            }
        } catch (e) {
            status.className = 'upload-status error';
            status.textContent = '请求失败: ' + e.message;
            btn.disabled = false;
        }
    },

    // ---------- 文件夹操作 ----------
    showCreateFolderDialog() {
        document.getElementById('newFolderName').value = '';
        this.showModal('createFolderModal');
        setTimeout(() => document.getElementById('newFolderName').focus(), 100);
    },

    async createFolder() {
        const name = document.getElementById('newFolderName').value.trim();
        if (!name) return showToast('请输入文件夹名称', 'error');

        try {
            const res = await fetch(`${API_BASE}/folders/`, {
                method: 'POST',
                headers: apiJsonHeaders(),
                credentials: 'same-origin',
                body: JSON.stringify({ name, parent_id: state.currentFolderId }),
            });
            const data = await res.json();
            if (res.ok) {
                showToast('文件夹已创建', 'success');
                this.closeModal('createFolderModal');
                this.loadFiles();
                this.loadFileTree();
            } else {
                showToast(data.error || '创建失败', 'error');
            }
        } catch (e) {
            showToast('创建失败: ' + e.message, 'error');
        }
    },

    // ---------- 搜索 ----------
    handleSearch(query) {
        const clear = document.getElementById('searchClear');
        clear.style.display = query ? '' : 'none';

        clearTimeout(state.searchTimeout);
        if (!query.trim()) {
            this.clearSearch();
            return;
        }
        state.searchTimeout = setTimeout(() => this.doSearch(query.trim()), 400);
    },

    async doSearch(query) {
        try {
            const params = new URLSearchParams({ q: query, limit: 20 });
            if (state.currentCategory) params.set('category', state.currentCategory);
            const res = await fetch(`${API_BASE}/search/?${params}`, { credentials: 'same-origin' });
            const data = await res.json();
            this.renderSearchResults(data);
        } catch (e) {
            showToast('搜索失败', 'error');
        }
    },

    renderSearchResults(data) {
        const container = document.getElementById('searchResults');
        const list = document.getElementById('searchResultsList');
        const title = document.getElementById('searchResultsTitle');
        const filesList = document.getElementById('filesList');
        const emptyState = document.getElementById('emptyState');

        filesList.style.display = 'none';
        emptyState.style.display = 'none';
        container.style.display = '';

        title.textContent = `找到 ${data.total} 个结果（"${data.query}"）`;

        if (data.results.length === 0) {
            list.innerHTML = '<div class="empty-state" style="padding:40px"><p>未找到匹配的文件</p></div>';
            return;
        }

        list.innerHTML = data.results.map(r => `
            <div class="search-result-item" ondblclick="fileManager.openFile(${r.id}, '${r.category}', 'completed')">
                <div class="sr-filename">${this.escHtml(r.filename)}</div>
                <div class="sr-snippet">${this.escHtml(r.snippet)}</div>
            </div>
        `).join('');
    },

    clearSearch() {
        document.getElementById('searchInput').value = '';
        document.getElementById('searchClear').style.display = 'none';
        document.getElementById('searchResults').style.display = 'none';
        document.getElementById('filesList').style.display = '';
        this.renderFileList();
    },

    // ---------- 右键菜单 ----------
    showFileMenu(event, fileId, filename, category, parseStatus) {
        event.preventDefault();
        state.ctxTarget = { id: fileId, filename, category, parseStatus };
        state.ctxTargetType = 'file';

        const menu = document.getElementById('contextMenu');
        const mdItems = category === 'document' && parseStatus === 'completed';
        document.getElementById('ctxDownloadMd').style.display = mdItems ? '' : 'none';
        document.getElementById('ctxViewMd').style.display = mdItems ? '' : 'none';

        this.positionMenu(menu, event);
    },

    showFolderMenu(event, folderId, folderName) {
        event.preventDefault();
        state.ctxTarget = { id: folderId, name: folderName };
        state.ctxTargetType = 'folder';

        this.positionMenu(document.getElementById('folderContextMenu'), event);
    },

    positionMenu(menu, event) {
        // 隐藏所有菜单
        document.querySelectorAll('.context-menu').forEach(m => m.style.display = 'none');
        menu.style.display = '';
        menu.style.left = Math.min(event.clientX, window.innerWidth - 200) + 'px';
        menu.style.top = Math.min(event.clientY, window.innerHeight - 250) + 'px';
    },

    initContextMenuClose() {
        document.addEventListener('click', () => {
            document.querySelectorAll('.context-menu').forEach(m => m.style.display = 'none');
        });
    },

    // ---------- 右键菜单操作 ----------
    ctxDownload() {
        if (!state.ctxTarget) return;
        window.open(`${API_BASE}/${state.ctxTarget.id}/download/`, '_blank');
    },

    ctxDownloadMd() {
        if (!state.ctxTarget) return;
        window.open(`${API_BASE}/${state.ctxTarget.id}/download-md/`, '_blank');
    },

    ctxViewMd() {
        if (!state.ctxTarget) return;
        mdEditor.open(state.ctxTarget.id, state.ctxTarget.filename);
    },

    ctxRename() {
        if (!state.ctxTarget) return;
        state.renameTargetType = 'file';
        state.renameTargetId = state.ctxTarget.id;
        document.getElementById('renameModalTitle').textContent = '重命名文件';
        document.getElementById('renameInput').value = state.ctxTarget.filename;
        this.showModal('renameModal');
        setTimeout(() => {
            const input = document.getElementById('renameInput');
            input.focus();
            // 选中不含扩展名的部分
            const dot = state.ctxTarget.filename.lastIndexOf('.');
            input.setSelectionRange(0, dot > 0 ? dot : state.ctxTarget.filename.length);
        }, 100);
    },

    ctxRenameFolder() {
        if (!state.ctxTarget) return;
        state.renameTargetType = 'folder';
        state.renameTargetId = state.ctxTarget.id;
        document.getElementById('renameModalTitle').textContent = '重命名文件夹';
        document.getElementById('renameInput').value = state.ctxTarget.name;
        this.showModal('renameModal');
        setTimeout(() => document.getElementById('renameInput').select(), 100);
    },

    async confirmRename() {
        const name = document.getElementById('renameInput').value.trim();
        if (!name) return showToast('名称不能为空', 'error');

        let url, body;
        if (state.renameTargetType === 'file') {
            url = `${API_BASE}/${state.renameTargetId}/rename/`;
            body = { filename: name };
        } else {
            url = `${API_BASE}/folders/${state.renameTargetId}/rename/`;
            body = { name };
        }

        try {
            const res = await fetch(url, {
                method: 'PUT',
                headers: apiJsonHeaders(),
                credentials: 'same-origin',
                body: JSON.stringify(body),
            });
            if (res.ok) {
                showToast('已重命名', 'success');
                this.closeModal('renameModal');
                this.loadFiles();
                this.loadFileTree();
            } else {
                const data = await res.json();
                showToast(data.error || '重命名失败', 'error');
            }
        } catch (e) {
            showToast('重命名失败', 'error');
        }
    },

    ctxMove() {
        if (!state.ctxTarget) return;
        state.moveTargetFolderId = undefined;
        this.showModal('moveModal');
        this.loadFolderPicker();
    },

    async loadFolderPicker() {
        const picker = document.getElementById('folderPicker');
        picker.innerHTML = '<div class="folder-picker-item" data-folder-id="" onclick="fileManager.selectMoveTarget(this, null)"><i class="fas fa-home me-2"></i>根目录</div>';

        try {
            const res = await fetch(`${API_BASE}/pick/`, { credentials: 'same-origin' });
            const data = await res.json();
            (data.folders || []).forEach(f => {
                picker.innerHTML += `<div class="folder-picker-item" onclick="fileManager.selectMoveTarget(this, ${f.id})">
                    <i class="fas fa-folder me-2" style="margin-left:${(f.path.split('/').length - 2) * 16}px"></i>${this.escHtml(f.name)}
                </div>`;
            });
        } catch (e) {}
    },

    selectMoveTarget(el, folderId) {
        document.querySelectorAll('.folder-picker-item').forEach(i => i.classList.remove('selected'));
        el.classList.add('selected');
        state.moveTargetFolderId = folderId;
    },

    async confirmMove() {
        if (state.moveTargetFolderId === undefined) return showToast('请选择目标文件夹', 'error');

        try {
            const res = await fetch(`${API_BASE}/${state.ctxTarget.id}/move/`, {
                method: 'PUT',
                headers: apiJsonHeaders(),
                credentials: 'same-origin',
                body: JSON.stringify({ folder_id: state.moveTargetFolderId }),
            });
            if (res.ok) {
                showToast('已移动', 'success');
                this.closeModal('moveModal');
                this.loadFiles();
            } else {
                const data = await res.json();
                showToast(data.error || '移动失败', 'error');
            }
        } catch (e) {
            showToast('移动失败', 'error');
        }
    },

    async ctxDelete() {
        if (!state.ctxTarget) return;
        if (!confirm(`确定要删除"${state.ctxTarget.filename}"吗？`)) return;

        try {
            const res = await fetch(`${API_BASE}/${state.ctxTarget.id}/`, {
                method: 'DELETE',
                headers: apiHeaders(),
                credentials: 'same-origin',
            });
            if (res.ok) {
                showToast('文件已删除', 'success');
                this.loadFiles();
            } else {
                const data = await res.json();
                showToast(data.error || '删除失败', 'error');
            }
        } catch (e) {
            showToast('删除失败', 'error');
        }
    },

    async ctxDeleteFolder() {
        if (!state.ctxTarget) return;
        if (!confirm(`确定要删除文件夹"${state.ctxTarget.name}"及其所有内容吗？`)) return;

        try {
            const res = await fetch(`${API_BASE}/folders/${state.ctxTarget.id}/`, {
                method: 'DELETE',
                headers: apiHeaders(),
                credentials: 'same-origin',
            });
            if (res.ok) {
                showToast('文件夹已删除', 'success');
                this.loadFiles();
                this.loadFileTree();
            } else {
                const data = await res.json();
                showToast(data.error || '删除失败', 'error');
            }
        } catch (e) {
            showToast('删除失败', 'error');
        }
    },

    // ---------- 拖拽移动/删除 ----------
    getParentFolderId() {
        if (state.breadcrumb.length >= 2) {
            return state.breadcrumb[state.breadcrumb.length - 2].id;
        }
        return null;
    },

    startDragItem(event, type, id, name) {
        state.dragItem = { type, id, name };
        event.dataTransfer.setData('text/plain', `${type}:${id}`);
        event.dataTransfer.effectAllowed = 'move';
        // 显示垃圾桶
        setTimeout(() => this.showDragTrash(), 0);
    },

    endDragItem() {
        state.dragItem = null;
        this.hideDragTrash();
        document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
    },

    showDragTrash() {
        const zone = document.getElementById('dragTrashZone');
        if (zone) zone.style.display = '';
    },

    hideDragTrash() {
        const zone = document.getElementById('dragTrashZone');
        if (zone) {
            zone.style.display = 'none';
            zone.classList.remove('drag-over');
        }
    },

    handleFolderItemDrop(event, targetFolderId) {
        event.preventDefault();
        event.currentTarget.classList.remove('drag-over');
        // 外部文件
        if (event.dataTransfer.files.length > 0) {
            const prevFolder = state.currentFolderId;
            state.currentFolderId = targetFolderId;
            this.uploadFiles(Array.from(event.dataTransfer.files));
            state.currentFolderId = prevFolder;
            return;
        }
        if (!state.dragItem) return;
        const { type, id } = state.dragItem;
        if (type === 'file') {
            this.moveFileTo(id, targetFolderId);
        }
        state.dragItem = null;
        this.hideDragTrash();
    },

    async moveFileTo(fileId, targetFolderId) {
        try {
            const res = await fetch(`${API_BASE}/${fileId}/move/`, {
                method: 'PUT',
                headers: apiJsonHeaders(),
                credentials: 'same-origin',
                body: JSON.stringify({ folder_id: targetFolderId }),
            });
            if (res.ok) {
                showToast('已移动', 'success');
                this.loadFiles();
                this.loadFileTree();
            } else {
                const data = await res.json();
                showToast(data.error || '移动失败', 'error');
            }
        } catch (e) {
            showToast('移动失败', 'error');
        }
    },

    async handleTrashDrop(event) {
        event.preventDefault();
        const zone = document.getElementById('dragTrashZone');
        if (zone) zone.classList.remove('drag-over');
        if (!state.dragItem) return;
        const { type, id, name } = state.dragItem;
        state.dragItem = null;
        this.hideDragTrash();

        if (!confirm(`确定要删除"${name}"吗？`)) return;

        try {
            const url = type === 'file' ? `${API_BASE}/${id}/` : `${API_BASE}/folders/${id}/`;
            const res = await fetch(url, {
                method: 'DELETE',
                headers: apiHeaders(),
                credentials: 'same-origin',
            });
            if (res.ok) {
                showToast('已删除', 'success');
                this.loadFiles();
                this.loadFileTree();
            } else {
                const data = await res.json();
                showToast(data.error || '删除失败', 'error');
            }
        } catch (e) {
            showToast('删除失败', 'error');
        }
    },

    // ---------- 双击打开文件 ----------
    openFile(fileId, category, parseStatus) {
        if (category === 'document' && parseStatus === 'completed') {
            mdEditor.open(fileId);
        } else if (category === 'image') {
            window.open(`${API_BASE}/${fileId}/download/`, '_blank');
        } else {
            window.open(`${API_BASE}/${fileId}/download/`, '_blank');
        }
    },

    // ---------- 模态框 ----------
    showModal(id) {
        document.getElementById(id).style.display = '';
    },
    closeModal(id) {
        document.getElementById(id).style.display = 'none';
    },

    // ---------- HTML 转义 ----------
    escHtml(s) {
        const div = document.createElement('div');
        div.appendChild(document.createTextNode(s || ''));
        return div.innerHTML;
    },
    escAttr(s) {
        return (s || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
    },
};


/* ============================================
   Markdown 编辑器
   ============================================ */

const mdEditor = {
    fileId: null,
    filename: '',
    originalContent: '',
    isEditing: false,

    async open(fileId, filename) {
        this.fileId = fileId;
        this.isEditing = false;

        try {
            const res = await fetch(`${API_BASE}/${fileId}/markdown/`, { credentials: 'same-origin' });
            const data = await res.json();

            this.filename = data.filename || filename || '';
            this.originalContent = data.parsed_markdown || '';

            document.getElementById('mdPanelFilename').textContent = this.filename;
            document.getElementById('mdEditedBadge').style.display = data.markdown_edited ? '' : 'none';

            // 渲染预览
            this.renderPreview(this.originalContent, 'mdPreview');

            // 显示面板
            document.getElementById('mdPreview').style.display = '';
            document.getElementById('mdEditorSplit').style.display = 'none';
            document.getElementById('mdEditBtn').style.display = '';
            document.getElementById('mdSaveBtn').style.display = 'none';
            document.getElementById('mdCancelBtn').style.display = 'none';

            document.getElementById('mdPanelOverlay').style.display = '';
            document.getElementById('mdPanel').style.display = '';
        } catch (e) {
            showToast('加载 Markdown 失败', 'error');
        }
    },

    close() {
        document.getElementById('mdPanelOverlay').style.display = 'none';
        document.getElementById('mdPanel').style.display = 'none';
        this.isEditing = false;
    },

    toggleEdit() {
        this.isEditing = true;

        document.getElementById('mdPreview').style.display = 'none';
        document.getElementById('mdEditorSplit').style.display = '';
        document.getElementById('mdEditBtn').style.display = 'none';
        document.getElementById('mdSaveBtn').style.display = '';
        document.getElementById('mdCancelBtn').style.display = '';

        const textarea = document.getElementById('mdEditorTextarea');
        textarea.value = this.originalContent;
        this.renderPreview(this.originalContent, 'mdPreviewPane');
        textarea.focus();
    },

    cancelEdit() {
        this.isEditing = false;
        document.getElementById('mdPreview').style.display = '';
        document.getElementById('mdEditorSplit').style.display = 'none';
        document.getElementById('mdEditBtn').style.display = '';
        document.getElementById('mdSaveBtn').style.display = 'none';
        document.getElementById('mdCancelBtn').style.display = 'none';
    },

    onInput() {
        const content = document.getElementById('mdEditorTextarea').value;
        this.renderPreview(content, 'mdPreviewPane');
    },

    async save() {
        const content = document.getElementById('mdEditorTextarea').value;
        if (!content.trim()) return showToast('内容不能为空', 'error');

        try {
            const res = await fetch(`${API_BASE}/${this.fileId}/markdown/`, {
                method: 'PUT',
                headers: apiJsonHeaders(),
                credentials: 'same-origin',
                body: JSON.stringify({ content }),
            });
            const data = await res.json();
            if (res.ok) {
                this.originalContent = content;
                showToast('保存成功', 'success');
                document.getElementById('mdEditedBadge').style.display = '';

                // 切换回预览模式
                this.cancelEdit();
                this.renderPreview(content, 'mdPreview');
                fileManager.loadFiles(); // 刷新列表
            } else {
                showToast(data.error || '保存失败', 'error');
            }
        } catch (e) {
            showToast('保存失败: ' + e.message, 'error');
        }
    },

    renderPreview(markdown, elementId) {
        const el = document.getElementById(elementId);
        if (typeof marked !== 'undefined') {
            el.innerHTML = marked.parse(markdown || '*暂无内容*');
        } else {
            // marked.js 未加载，显示原始文本
            el.textContent = markdown || '暂无内容';
        }
    },
};


/* ============================================
   Toast 通知
   ============================================ */

function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = 'toast-item ' + type;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 3000);
}


/* ============================================
   主题管理
   ============================================ */

const filesTheme = {
    async init() {
        try {
            const resp = await fetch('/get_calendar/user_settings/', {
                credentials: 'same-origin',
            });
            if (resp.ok) {
                window.userSettings = await resp.json();
            }
        } catch (e) {
            console.warn('加载用户设置失败', e);
        }
        if (window.themeManager) {
            window.themeManager.init();
            const current = document.documentElement.getAttribute('data-theme') || 'light';
            this.highlightActive(current);
        }
        // 点击外部关闭下拉
        document.addEventListener('click', (e) => {
            const dropdown = document.getElementById('themeDropdown');
            if (dropdown && !e.target.closest('.theme-switcher')) {
                dropdown.style.display = 'none';
            }
        });
    },

    toggle() {
        const dropdown = document.getElementById('themeDropdown');
        if (!dropdown) return;
        dropdown.style.display = dropdown.style.display === 'none' ? '' : 'none';
    },

    apply(theme) {
        if (window.themeManager) {
            window.themeManager.applyTheme(theme, false); // 不依赖 settingsManager 保存
        } else {
            document.documentElement.setAttribute('data-theme', theme);
        }
        this.highlightActive(theme);
        const dropdown = document.getElementById('themeDropdown');
        if (dropdown) dropdown.style.display = 'none';

        // 直接保存到用户设置
        this.saveThemeToServer(theme);
    },

    async saveThemeToServer(theme) {
        // 更新本地
        if (window.userSettings) {
            window.userSettings.theme = theme;
        }
        try {
            const settings = window.userSettings || {};
            settings.theme = theme;
            await fetch('/get_calendar/user_settings/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken(),
                },
                credentials: 'same-origin',
                body: JSON.stringify(settings),
            });
        } catch (e) {
            console.warn('保存主题失败', e);
        }
    },

    highlightActive(theme) {
        document.querySelectorAll('.theme-option').forEach(opt => {
            opt.classList.toggle('active', opt.dataset.theme === theme);
        });
    },
};


/* ============================================
   初始化
   ============================================ */

document.addEventListener('DOMContentLoaded', () => {
    filesTheme.init();
    fileManager.init();
});
