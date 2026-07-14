import { http, HttpResponse } from "msw";

export const handlers = [
  http.get("*/api/agent/sessions/", () =>
    HttpResponse.json({
      sessions: [
        {
          session_id: "user_1_test",
          name: "测试会话",
          message_count: 0,
          updated_at: "2026-07-14T00:00:00+08:00",
        },
      ],
      current_session_id: "user_1_test",
    }),
  ),
  http.get("*/api/agent/history/", ({ request }) =>
    HttpResponse.json({
      session_id:
        new URL(request.url).searchParams.get("session_id") ?? "user_1_test",
      messages: [],
      rollback_window: { status: "active", floor_message_index: 0 },
    }),
  ),
  http.get("*/api/v2/planner/bootstrap/", () =>
    HttpResponse.json({
      entrypoints: {
        web_calendar: {
          mode: "normalized",
          can_read_normalized: true,
          can_write_normalized: true,
        },
      },
    }),
  ),
  http.get("*/api/v2/events/occurrences/", ({ request }) => {
    const url = new URL(request.url);
    if (!url.searchParams.get("from") || !url.searchParams.get("to")) {
      return HttpResponse.json(
        { error: "查询参数 from 与 to 均为必填", code: "invalid_command" },
        { status: 422 },
      );
    }
    return HttpResponse.json({
      occurrences: [
        {
          event_id: "event-1",
          title: "V2 测试事件",
          start: "2026-07-14T09:00:00+08:00",
          end: "2026-07-14T10:00:00+08:00",
          occurrence_ref: {
            entity_id: "event-1",
            series_id: "series-1",
            recurrence_id: "20260714T090000",
            source_version: 3,
          },
        },
      ],
      count: 1,
    });
  }),
  http.get("*/api/v2/events/definitions/", () =>
    HttpResponse.json({
      definitions: [
        {
          event_id: "event-1",
          recurrence: { rrule: "FREQ=WEEKLY;BYDAY=MO" },
        },
      ],
      count: 1,
    }),
  ),
  http.patch("*/api/v2/events/version-conflict/", () =>
    HttpResponse.json(
      { error: "版本冲突", code: "version_conflict" },
      { status: 409 },
    ),
  ),
  http.get("*/api/v2/groups/", () =>
    HttpResponse.json({
      groups: [
        { group_id: "group-1", name: "工作", color: "#1769e0", version: 2 },
      ],
      count: 1,
    }),
  ),
  http.get("*/api/v2/reminders/", ({ request }) => {
    const url = new URL(request.url);
    if (url.searchParams.get("from") && url.searchParams.get("to")) {
      return HttpResponse.json({
        occurrences: [
          {
            id: "reminder:1",
            entity_type: "reminder",
            title: "测试提醒",
            start: "2026-07-14T11:00:00+08:00",
            end: null,
            content: "按时完成",
            occurrence_ref: { entity_id: "reminder-1", source_version: 2 },
          },
        ],
        count: 1,
      });
    }
    return HttpResponse.json({ reminders: [], count: 0 });
  }),
];
