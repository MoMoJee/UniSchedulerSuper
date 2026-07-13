/** Cohort-aware Planner v2 client. A page session fixes its mode after bootstrap. */
class PlannerV2Client {
    constructor() {
        this.entrypoints = Object.freeze(this.readEmbeddedEntrypoints());
        this.ready = this.bootstrap();
    }

    readEmbeddedEntrypoints() {
        const element = document.getElementById('planner-entrypoints-data');
        if (!element) return {};
        try {
            return JSON.parse(element.textContent || '{}');
        } catch (error) {
            console.error('[PlannerV2] invalid embedded entrypoints', error);
            return {};
        }
    }

    async bootstrap() {
        try {
            const response = await fetch('/api/v2/planner/bootstrap/', { credentials: 'same-origin' });
            if (!response.ok) throw new Error(`Planner bootstrap ${response.status}`);
            const payload = await response.json();
            this.entrypoints = Object.freeze(payload.entrypoints || {});
            document.documentElement.dataset.plannerStorageMode = this.mode('web_calendar');
            console.info('[PlannerV2] fixed page-session entrypoints', this.entrypoints);
        } catch (error) {
            // P6 has sealed legacy Planner writes. Unknown state must fail closed and
            // continue to V2, never silently reopen a legacy JSON route.
            console.error('[PlannerV2] bootstrap failed; blocking legacy fallback', error);
        }
        document.documentElement.dataset.plannerStorageMode = this.mode('web_calendar');
        return this.entrypoints;
    }

    mode(entrypoint = 'api_v2') { return this.entrypoints[entrypoint]?.mode || 'blocked'; }
    canRead(entrypoint = 'api_v2') { return Boolean(this.entrypoints[entrypoint]?.can_read_normalized); }
    canWrite(entrypoint = 'api_v2') { return Boolean(this.entrypoints[entrypoint]?.can_write_normalized); }
    isNormalized(entrypoint = 'api_v2') {
        const mode = this.mode(entrypoint);
        // Quarantine/blocked users must call V2 and receive its stable denial;
        // selecting a legacy UI branch would reopen old JSON paths.
        return mode === 'normalized' || mode === 'quarantined' || mode === 'blocked';
    }

    async request(url, options = {}) {
        await this.ready;
        const response = await fetch(url, { credentials: 'same-origin', ...options });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            const error = new Error(payload.error || payload.message || `HTTP ${response.status}`);
            error.code = payload.code;
            error.status = response.status;
            throw error;
        }
        return payload;
    }

    csrfToken() {
        return window.CSRF_TOKEN || document.cookie.split(';').map(v => v.trim()).find(v => v.startsWith('csrftoken='))?.split('=')[1] || '';
    }

    jsonOptions(method, body) {
        return {
            method,
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.csrfToken() },
            body: JSON.stringify(body),
        };
    }

    async fetchCalendar(start, end) {
        const from = encodeURIComponent(start instanceof Date ? start.toISOString() : start);
        const to = encodeURIComponent(end instanceof Date ? end.toISOString() : end);
        const [occurrenceData, definitionData, groupData, reminderData] = await Promise.all([
            this.request(`/api/v2/events/occurrences/?from=${from}&to=${to}`),
            this.request(`/api/v2/events/definitions/?from=${from}&to=${to}`),
            this.request('/api/v2/groups/'),
            this.request(`/api/v2/reminders/?from=${from}&to=${to}`),
        ]);
        const definitions = new Map((definitionData.definitions || []).map(item => [item.event_id, item]));
        const groups = (groupData.groups || []).map(group => ({ ...group, id: group.group_id }));
        const events = (occurrenceData.occurrences || []).map(item => {
            const definition = definitions.get(item.occurrence_ref.entity_id) || {};
            return {
                id: item.id,
                title: item.title,
                start: item.start,
                end: item.end,
                allDay: item.is_all_day,
                groupID: item.group_id,
                description: item.description,
                location: item.location,
                status: item.status,
                importance: item.importance,
                urgency: item.urgency,
                ddl: definition.ddl_at,
                shared_to_groups: definition.share_group_ids || [],
                rrule: definition.recurrence?.rrule || '',
                series_id: item.occurrence_ref.series_id,
                is_recurring: Boolean(item.occurrence_ref.series_id),
                extendedProps: {
                    occurrence_ref: item.occurrence_ref,
                    source_version: item.occurrence_ref.source_version,
                    entity_id: item.occurrence_ref.entity_id,
                    series_id: item.occurrence_ref.series_id,
                    recurrence_id: item.occurrence_ref.recurrence_id,
                    is_recurring: Boolean(item.occurrence_ref.series_id),
                    description: item.description,
                    location: item.location,
                    status: item.status,
                    importance: item.importance,
                    urgency: item.urgency,
                    shared_to_groups: definition.share_group_ids || [],
                    ddl: definition.ddl_at,
                    groupID: item.group_id,
                    rrule: definition.recurrence?.rrule || '',
                    series_id: item.occurrence_ref.series_id || '',
                    is_recurring: Boolean(item.occurrence_ref.series_id),
                    is_main_event: Boolean(item.occurrence_ref.series_id && item.start === definition.start),
                    is_detached: false,
                    master_start: definition.start,
                    master_end: definition.end,
                    isPlannerV2: true,
                },
            };
        });
        const reminders = (reminderData.occurrences || []).map(item => ({
            id: item.id,
            title: `🔔 ${item.title}`,
            start: item.start,
            end: item.end,
            allDay: item.is_all_day,
            backgroundColor: 'rgba(0, 123, 255, 0.6)',
            borderColor: '#007bff',
            extendedProps: {
                isReminder: true,
                isPlannerV2: true,
                occurrence_ref: item.occurrence_ref,
                reminderId: item.occurrence_ref.entity_id,
                status: item.status,
                priority: item.priority,
                description: item.content,
                reminderData: {
                    id: item.occurrence_ref.entity_id,
                    title: item.title,
                    content: item.content,
                    description: item.content,
                    status: item.status,
                    priority: item.priority,
                    trigger_time: item.start,
                    occurrence_ref: item.occurrence_ref,
                    series_id: item.occurrence_ref.series_id,
                },
            },
        }));
        return { events, reminders, groups };
    }

    async fetchSharedCalendar(shareGroupId, start, end) {
        const from = encodeURIComponent(start instanceof Date ? start.toISOString() : start);
        const to = encodeURIComponent(end instanceof Date ? end.toISOString() : end);
        return this.request(
            `/api/v2/share-groups/${encodeURIComponent(shareGroupId)}/occurrences/?from=${from}&to=${to}`,
        );
    }

    normalizeEventPayload(data) {
        const payload = {
            title: data.title,
            description: data.description || '',
            location: data.location || '',
            importance: data.importance || '',
            urgency: data.urgency || '',
            group_id: (data.group_id ?? data.groupID) || null,
            start: data.start ?? data.newStart,
            end: data.end ?? data.newEnd,
            is_all_day: Boolean(data.is_all_day ?? data.allDay),
            tzid: data.tzid || 'Asia/Shanghai',
        };
        if (data.ddl) payload.ddl_at = data.ddl;
        if (data.rrule) payload.recurrence = { rrule: data.rrule };
        if (Array.isArray(data.share_group_ids ?? data.shared_to_groups)) {
            payload.share_group_ids = data.share_group_ids ?? data.shared_to_groups;
        }
        return payload;
    }

    createEvent(data) {
        return this.request('/api/v2/events/', this.jsonOptions('POST', this.normalizeEventPayload(data)));
    }

    patchEvent(ref, scope, changes) {
        const normalizedScope = scope === 'future' ? 'this_and_future' : scope;
        const recurrenceSpecified = Object.prototype.hasOwnProperty.call(changes, 'recurrence');
        const overridePolicy = recurrenceSpecified
            ? (changes.recurrence === null ? 'discard_with_audit' : 'keep_as_single')
            : 'map_by_ordinal';
        return this.request(
            `/api/v2/events/${encodeURIComponent(ref.entity_id)}/`,
            this.jsonOptions('PATCH', {
                ...changes,
                scope: normalizedScope,
                occurrence_ref: ref,
                expected_version: ref.source_version,
                ...(normalizedScope === 'this_and_future' ? { override_policy: overridePolicy } : {}),
            }),
        );
    }

    deleteEvent(ref, scope) {
        const normalizedScope = scope === 'future' ? 'this_and_future' : scope;
        return this.request(
            `/api/v2/events/${encodeURIComponent(ref.entity_id)}/`,
            this.jsonOptions('DELETE', {
                scope: normalizedScope,
                occurrence_ref: ref,
                expected_version: ref.source_version,
            }),
        );
    }

    patchReminder(ref, scope, changes) {
        const normalizedScope = scope === 'from_this' || scope === 'from_time' || scope === 'future'
            ? 'this_and_future'
            : (scope === 'this_only' ? 'single' : scope);
        return this.request(
            `/api/v2/reminders/${encodeURIComponent(ref.entity_id)}/`,
            this.jsonOptions('PATCH', {
                ...changes,
                scope: normalizedScope,
                occurrence_ref: ref,
                expected_version: ref.source_version,
            }),
        );
    }

    deleteReminder(ref, scope) {
        const normalizedScope = scope === 'from_this' || scope === 'from_time' || scope === 'future'
            ? 'this_and_future'
            : (scope === 'this_only' ? 'single' : scope);
        return this.request(
            `/api/v2/reminders/${encodeURIComponent(ref.entity_id)}/`,
            this.jsonOptions('DELETE', {
                scope: normalizedScope,
                occurrence_ref: ref,
                expected_version: ref.source_version,
            }),
        );
    }
}

window.plannerV2Client = new PlannerV2Client();
window.PlannerV2Client = PlannerV2Client;
