/**
 * Agent Skills Manager
 * 管理 Agent 技能的 CRUD、导入、以及 is_active 开关
 */
class AgentSkillsManager {
    constructor(csrfToken) {
        this.csrfToken = csrfToken;
        this.skills = [];
        this.apiBase = '/api/agent/skills';
    }

    // ==========================================
    // API 调用
    // ==========================================

    async _fetch(url, options = {}) {
        const defaults = {
            headers: {
                'X-CSRFToken': this.csrfToken,
                'Content-Type': 'application/json',
            },
            credentials: 'include',
        };
        // 如果是 FormData（上传文件），不设置 Content-Type（浏览器自动设置 boundary）
        if (options.body instanceof FormData) {
            defaults.headers = { 'X-CSRFToken': this.csrfToken };
        }
        const resp = await fetch(url, { ...defaults, ...options });
        return resp;
    }

    async loadSkills() {
        const container = document.getElementById('skillsList');
        if (!container) return;

        container.innerHTML = '<div class="text-center text-muted py-4"><i class="fas fa-spinner fa-spin me-2"></i>加载中...</div>';

        try {
            const resp = await this._fetch(`${this.apiBase}/`);
            if (!resp.ok) throw new Error('加载失败');
            const data = await resp.json();
            this.skills = data.items || [];
            this._renderList(container);
        } catch (e) {
            container.innerHTML = `<div class="text-center text-danger py-4"><i class="fas fa-exclamation-circle me-2"></i>${e.message}</div>`;
        }
    }

    _renderList(container) {
        if (this.skills.length === 0) {
            container.innerHTML = `
                <div class="text-center text-muted py-4">
                    <i class="fas fa-bolt fa-2x mb-2 d-block" style="opacity:0.3;"></i>
                    还没有技能，点击"新建"或"导入"创建第一个
                </div>`;
            return;
        }

        const sourceLabels = { manual: '手动', ai: 'AI', imported: '导入' };
        const sourceBadgeClass = { manual: 'bg-primary', ai: 'bg-success', imported: 'bg-info' };

        container.innerHTML = this.skills.map(s => `
            <div class="memory-item" data-id="${s.id}">
                <div class="memory-item-content" style="flex:1;min-width:0;">
                    <div class="d-flex align-items-center gap-2 mb-1">
                        <div class="form-check form-switch mb-0">
                            <input class="form-check-input" type="checkbox" role="switch"
                                   id="skillToggle${s.id}" ${s.is_active ? 'checked' : ''}
                                   onchange="agentSkills.toggleSkill(${s.id})" title="${s.is_active ? '已启用' : '已禁用'}">
                        </div>
                        <strong class="text-truncate">${escapeHtml(s.name)}</strong>
                        <span class="badge ${sourceBadgeClass[s.source] || 'bg-secondary'}" style="font-size:0.7em;">${sourceLabels[s.source] || s.source}</span>
                    </div>
                    <small class="text-muted d-block text-truncate">${escapeHtml(s.description)}</small>
                </div>
                <div class="memory-item-actions">
                    <button class="btn btn-sm btn-outline-primary" onclick="agentSkills.editSkill(${s.id})" title="编辑">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-danger" onclick="agentSkills.deleteSkill(${s.id}, '${escapeHtml(s.name)}')" title="删除">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </div>
        `).join('');
    }

    // ==========================================
    // 切换 is_active
    // ==========================================

    async toggleSkill(id) {
        try {
            const resp = await this._fetch(`${this.apiBase}/${id}/toggle/`, { method: 'POST' });
            if (!resp.ok) throw new Error('切换失败');
            const data = await resp.json();
            // 更新本地缓存
            const skill = this.skills.find(s => s.id === id);
            if (skill) skill.is_active = data.is_active;
            if (typeof showToast === 'function') showToast(data.message, 'success');
        } catch (e) {
            if (typeof showToast === 'function') showToast(e.message, 'error');
            // 回滚 checkbox 状态
            const cb = document.getElementById(`skillToggle${id}`);
            if (cb) cb.checked = !cb.checked;
        }
    }

    // ==========================================
    // 新建/编辑
    // ==========================================

    showCreateForm() {
        this._hideImportContainer();
        const container = document.getElementById('skillFormContainer');
        document.getElementById('skillFormTitle').textContent = '新建技能';
        document.getElementById('skillFormId').value = '';
        document.getElementById('skillFormName').value = '';
        document.getElementById('skillFormDescription').value = '';
        document.getElementById('skillFormContent').value = '';
        container.style.display = '';
    }

    async editSkill(id) {
        this._hideImportContainer();
        try {
            const resp = await this._fetch(`${this.apiBase}/${id}/`);
            if (!resp.ok) throw new Error('加载失败');
            const data = await resp.json();

            const container = document.getElementById('skillFormContainer');
            document.getElementById('skillFormTitle').textContent = '编辑技能';
            document.getElementById('skillFormId').value = data.id;
            document.getElementById('skillFormName').value = data.name;
            document.getElementById('skillFormDescription').value = data.description;
            document.getElementById('skillFormContent').value = data.content;
            container.style.display = '';
        } catch (e) {
            if (typeof showToast === 'function') showToast(e.message, 'error');
        }
    }

    hideForm() {
        document.getElementById('skillFormContainer').style.display = 'none';
    }

    async submitForm() {
        const id = document.getElementById('skillFormId').value;
        const name = document.getElementById('skillFormName').value.trim();
        const description = document.getElementById('skillFormDescription').value.trim();
        const content = document.getElementById('skillFormContent').value.trim();

        if (!name || !description || !content) {
            if (typeof showToast === 'function') showToast('名称、描述和内容均不能为空', 'warning');
            return;
        }

        const payload = { name, description, content };

        try {
            let resp;
            if (id) {
                resp = await this._fetch(`${this.apiBase}/${id}/`, {
                    method: 'PUT',
                    body: JSON.stringify(payload),
                });
            } else {
                resp = await this._fetch(`${this.apiBase}/create/`, {
                    method: 'POST',
                    body: JSON.stringify(payload),
                });
            }

            const data = await resp.json();
            if (!resp.ok) throw new Error(data.error || '保存失败');

            if (typeof showToast === 'function') showToast(data.message, 'success');
            this.hideForm();
            await this.loadSkills();
        } catch (e) {
            if (typeof showToast === 'function') showToast(e.message, 'error');
        }
    }

    // ==========================================
    // 删除
    // ==========================================

    async deleteSkill(id, name) {
        if (!confirm(`确定删除技能「${name}」？`)) return;

        try {
            const resp = await this._fetch(`${this.apiBase}/${id}/delete/`, { method: 'DELETE' });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.error || '删除失败');
            if (typeof showToast === 'function') showToast(data.message, 'success');
            await this.loadSkills();
        } catch (e) {
            if (typeof showToast === 'function') showToast(e.message, 'error');
        }
    }

    // ==========================================
    // 导入
    // ==========================================

    showImportForm() {
        this.hideForm();
        const container = document.getElementById('skillImportContainer');
        container.style.display = '';
        this.switchImportMode('file');
    }

    hideImportForm() {
        document.getElementById('skillImportContainer').style.display = 'none';
    }

    _hideImportContainer() {
        const el = document.getElementById('skillImportContainer');
        if (el) el.style.display = 'none';
    }

    switchImportMode(mode) {
        document.getElementById('importFileMode').style.display = mode === 'file' ? '' : 'none';
        document.getElementById('importTextMode').style.display = mode === 'text' ? '' : 'none';
        document.querySelectorAll('#importModeTabs .nav-link').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.importMode === mode);
        });
        this._currentImportMode = mode;
    }

    async submitImport() {
        const mode = this._currentImportMode || 'file';

        try {
            let resp;
            if (mode === 'file') {
                const fileInput = document.getElementById('skillImportFile');
                const file = fileInput.files[0];
                if (!file) {
                    if (typeof showToast === 'function') showToast('请选择文件', 'warning');
                    return;
                }
                const desc = document.getElementById('skillImportFileDesc').value.trim();
                if (!desc) {
                    if (typeof showToast === 'function') showToast('请填写技能描述', 'warning');
                    return;
                }
                const formData = new FormData();
                formData.append('file', file);
                formData.append('description', desc);
                const name = document.getElementById('skillImportFileName').value.trim();
                if (name) formData.append('name', name);

                resp = await this._fetch(`${this.apiBase}/import/`, {
                    method: 'POST',
                    body: formData,
                });
            } else {
                const name = document.getElementById('skillImportTextName').value.trim();
                const desc = document.getElementById('skillImportTextDesc').value.trim();
                const content = document.getElementById('skillImportTextContent').value.trim();
                if (!name || !desc || !content) {
                    if (typeof showToast === 'function') showToast('名称、描述和内容均不能为空', 'warning');
                    return;
                }
                resp = await this._fetch(`${this.apiBase}/import/`, {
                    method: 'POST',
                    body: JSON.stringify({ name, description: desc, content }),
                });
            }

            const data = await resp.json();
            if (!resp.ok) throw new Error(data.error || '导入失败');
            if (typeof showToast === 'function') showToast(data.message, 'success');
            this.hideImportForm();
            await this.loadSkills();
        } catch (e) {
            if (typeof showToast === 'function') showToast(e.message, 'error');
        }
    }
}
