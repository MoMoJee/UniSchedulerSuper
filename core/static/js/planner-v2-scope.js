(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.PlannerV2Scope = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
    function dateKey(value) {
        return new Intl.DateTimeFormat('en-CA', {
            timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
        }).format(value);
    }

    function buildChanges(anchor, scope, updateData) {
        const changes = {
            title: updateData.title,
            description: updateData.description || '',
            importance: updateData.importance || '',
            urgency: updateData.urgency || '',
            group_id: updateData.groupID || null,
        };
        const editedStart = new Date(updateData.start);
        const editedEnd = new Date(updateData.end);
        const anchorStart = new Date(anchor.start);
        const anchorEnd = new Date(anchor.end);
        if ([editedStart, editedEnd, anchorStart, anchorEnd].some(value => Number.isNaN(value.getTime()))) {
            throw new Error('编辑时间格式无效');
        }
        if (editedEnd <= editedStart) throw new Error('结束时间必须晚于开始时间');

        if (scope === 'single') {
            changes.start = editedStart.toISOString();
            changes.end = editedEnd.toISOString();
            return changes;
        }
        if (updateData.ddl) changes.ddl_at = updateData.ddl;
        if (dateKey(editedStart) !== dateKey(anchorStart) || dateKey(editedEnd) !== dateKey(anchorEnd)) {
            throw new Error('批量编辑仅允许修改时间点和时长，不允许修改日期');
        }
        if (scope === 'all') {
            const masterStart = new Date(anchor.extendedProps?.master_start);
            if (Number.isNaN(masterStart.getTime())) throw new Error('缺少重复系列主事件时间，请刷新');
            const shiftedMasterStart = new Date(masterStart.getTime() + editedStart.getTime() - anchorStart.getTime());
            changes.start = shiftedMasterStart.toISOString();
            changes.end = new Date(shiftedMasterStart.getTime() + editedEnd.getTime() - editedStart.getTime()).toISOString();
        } else {
            changes.start = editedStart.toISOString();
            changes.end = editedEnd.toISOString();
        }
        if (updateData.recurrence_changed) {
            changes.recurrence = updateData.rrule ? { rrule: updateData.rrule } : null;
        }
        if (Array.isArray(updateData.shared_to_groups)) {
            changes.share_group_ids = updateData.shared_to_groups;
        }
        return changes;
    }

    return { buildChanges };
});
