import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { PlannerClientValidationError } from "./errors";
import { mapPlannerOccurrence } from "./mappers";
import { plannerApi } from "./planner";
import { server } from "../test/msw/server";

describe("plannerApi", () => {
  it("reads an explicit finite V2 occurrence range", async () => {
    const response = await plannerApi.listEventOccurrences(
      "2026-07-14T00:00:00+08:00",
      "2026-07-15T00:00:00+08:00",
    );

    expect(response.occurrences).toHaveLength(1);
    expect(mapPlannerOccurrence(response.occurrences?.[0])).toMatchObject({
      id: "event-1",
      occurrenceRef: { entityId: "event-1", sourceVersion: 3 },
    });
  });

  it("rejects a repeated single update without a server occurrence reference", () => {
    expect(() =>
      plannerApi.patchEvent(
        "event-1",
        { title: "不应发送" },
        { expectedVersion: 3, scope: "single" },
      ),
    ).toThrow(PlannerClientValidationError);
  });

  it("rejects invalid finite ranges before requesting the server", () => {
    expect(() =>
      plannerApi.listEventOccurrences(
        "2026-07-15T00:00:00+08:00",
        "2026-07-14T00:00:00+08:00",
      ),
    ).toThrow(PlannerClientValidationError);
  });

  it("sends server occurrence_ref and expected_version for a repeated single update", async () => {
    document.body.innerHTML = `
      <script id="frontend-bootstrap" type="application/json">
        {"mode":"react","user":{"username":"测试用户"},"csrfToken":"csrf-123","endpoints":{"home":"/home/","agentWebSocketPath":"/ws/agent/"}}
      </script>
    `;
    let received: unknown;
    server.use(
      http.patch("*/api/v2/events/event-1/", async ({ request }) => {
        received = await request.json();
        return HttpResponse.json({ event_id: "event-1", version: 4 });
      }),
    );

    await plannerApi.patchEvent(
      "event-1",
      { title: "仅此一次" },
      {
        expectedVersion: 3,
        scope: "single",
        occurrenceRef: {
          entity_id: "event-1",
          series_id: "series-1",
          recurrence_id: "20260714T090000",
          source_version: 3,
        },
      },
    );

    expect(received).toEqual({
      title: "仅此一次",
      expected_version: 3,
      scope: "single",
      occurrence_ref: {
        entity_id: "event-1",
        series_id: "series-1",
        recurrence_id: "20260714T090000",
        source_version: 3,
      },
    });
  });

  it("maps the domain future scope to the V2 this_and_future wire literal", async () => {
    document.body.innerHTML = `<script id="frontend-bootstrap" type="application/json">{"mode":"react","user":{"username":"测试用户"},"csrfToken":"csrf-123","endpoints":{"home":"/home/","agentWebSocketPath":"/ws/agent/"}}</script>`;
    let received: unknown;
    server.use(
      http.delete("*/api/v2/events/event-1/", async ({ request }) => {
        received = await request.json();
        return HttpResponse.json({ deleted: true });
      }),
    );

    await plannerApi.deleteEvent("event-1", {
      expectedVersion: 3,
      scope: "future",
      occurrenceRef: {
        entity_id: "event-1",
        recurrence_id: "20260714T090000",
        source_version: 3,
      },
    });

    expect(received).toMatchObject({
      scope: "this_and_future",
      expected_version: 3,
    });
  });

  it("uses V2-only Todo conversion and Reminder occurrence-action contracts", async () => {
    document.body.innerHTML = `<script id="frontend-bootstrap" type="application/json">{"mode":"react","user":{"username":"测试用户"},"csrfToken":"csrf-123","endpoints":{"home":"/home/","agentWebSocketPath":"/ws/agent/"}}</script>`;
    const calls: Array<{ path: string; body: unknown }> = [];
    server.use(
      http.post("*/api/v2/todos/todo-1/convert/", async ({ request }) => {
        calls.push({
          path: new URL(request.url).pathname,
          body: await request.json(),
        });
        return HttpResponse.json({ event_id: "event-2" });
      }),
      http.post(
        "*/api/v2/reminders/occurrences/action/",
        async ({ request }) => {
          calls.push({
            path: new URL(request.url).pathname,
            body: await request.json(),
          });
          return HttpResponse.json({ action: "complete" });
        },
      ),
    );
    await plannerApi.convertTodo(
      "todo-1",
      {
        start: "2026-07-14T09:00:00+08:00",
        end: "2026-07-14T10:00:00+08:00",
        title: "转换",
      },
      4,
    );
    await plannerApi.actOnReminderOccurrence(
      "complete",
      {
        entity_id: "reminder-1",
        series_id: "series-r",
        recurrence_id: "20260714T110000",
        source_version: 5,
      },
      5,
    );
    expect(calls).toEqual([
      {
        path: "/api/v2/todos/todo-1/convert/",
        body: expect.objectContaining({ expected_version: 4 }),
      },
      {
        path: "/api/v2/reminders/occurrences/action/",
        body: expect.objectContaining({
          action: "complete",
          expected_version: 5,
          occurrence_ref: expect.any(Object),
        }),
      },
    ]);
  });
});
