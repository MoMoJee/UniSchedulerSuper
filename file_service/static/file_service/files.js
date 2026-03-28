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
    quota: null,
    breadcrumb: [],
    searchTimeout: null,
    ctxTarget: null,           // 右键菜单的目标文件/文件夹
    ctxTargetType: null,       // 'file' | 'folder'
    moveTargetFolderId: undefined,
    renameTargetType: null,    // 'file' | 'folder'
    renameTargetId: null,
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
        this.loadFiles();
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
        } catch (e) {
            showToast('加载文件失败: ' + e.message, 'error');
        }
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

        // 文件夹
        state.folders.forEach(f => {
            if (isGrid) {
                html += `<div class="file-item-grid" ondblclick="fileManager.navigate(${f.id})" oncontextmenu="fileManager.showFolderMenu(event, ${f.id}, '${this.escAttr(f.name)}')">
                    <div class="file-icon icon-folder"><i class="fas fa-folder"></i></div>
                    <div class="file-name" title="${this.escAttr(f.name)}">${this.escHtml(f.name)}</div>
                    <div class="file-meta">${f.file_count || 0} 个文件</div>
                </div>`;
            } else {
                html += `<div class="file-item-list" ondblclick="fileManager.navigate(${f.id})" oncontextmenu="fileManager.showFolderMenu(event, ${f.id}, '${this.escAttr(f.name)}')">
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

            if (isGrid) {
                html += `<div class="file-item-grid" ondblclick="fileManager.openFile(${f.id}, '${f.category}', '${f.parse_status}')" oncontextmenu="fileManager.showFileMenu(${ctxCallArgs})">
                    <div class="file-icon ${iconBg}"><i class="${iconCls}"></i></div>
                    <div class="file-name" title="${this.escAttr(f.filename)}">${this.escHtml(f.filename)}</div>
                    <div class="file-meta">${formatSize(f.file_size)}</div>
                </div>`;
            } else {
                html += `<div class="file-item-list" ondblclick="fileManager.openFile(${f.id}, '${f.category}', '${f.parse_status}')" oncontextmenu="fileManager.showFileMenu(${ctxCallArgs})">
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
        this.loadFiles();
    },

    filterCategory(el, category) {
        state.currentCategory = category;
        document.querySelectorAll('.sidebar-item').forEach(b => b.classList.remove('active'));
        el.classList.add('active');
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

        main.addEventListener('dragenter', e => { e.preventDefault(); dragCounter++; overlay.classList.add('active'); });
        main.addEventListener('dragleave', e => { e.preventDefault(); dragCounter--; if (dragCounter <= 0) { overlay.classList.remove('active'); dragCounter = 0; } });
        main.addEventListener('dragover', e => e.preventDefault());
        main.addEventListener('drop', e => {
            e.preventDefault();
            dragCounter = 0;
            overlay.classList.remove('active');
            if (e.dataTransfer.files.length > 0) {
                this.uploadFiles(Array.from(e.dataTransfer.files));
            }
        });
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
   初始化
   ============================================ */

document.addEventListener('DOMContentLoaded', () => {
    fileManager.init();
});
