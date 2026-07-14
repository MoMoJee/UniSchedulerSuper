import { http, HttpResponse } from "msw";

export const handlers = [
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
  http.patch("*/api/v2/events/version-conflict/", () =>
    HttpResponse.json(
      { error: "版本冲突", code: "version_conflict" },
      { status: 409 },
    ),
  ),
];
