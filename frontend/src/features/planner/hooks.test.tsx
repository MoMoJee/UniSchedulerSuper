import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { server } from "../../test/msw/server";
import { useCalendarProjection } from "./hooks";

describe("calendar scope isolation", () => {
  it("shows shared occurrences without leaking personal events or reminders", async () => {
    server.use(
      http.get("*/api/v2/share-groups/share-1/occurrences/", () =>
        HttpResponse.json({
          occurrences: [
            {
              event_id: "shared-event",
              entity_type: "event",
              title: "共享事项",
              start: "2026-07-15T09:00:00+08:00",
              end: "2026-07-15T10:00:00+08:00",
              occurrence_ref: { entity_id: "shared-event", source_version: 1 },
            },
          ],
        }),
      ),
    );
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(
      () =>
        useCalendarProjection(
          "MoMoJee",
          "2026-07-01T00:00:00Z",
          "2026-08-01T00:00:00Z",
          "share-1",
        ),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.occurrences.map((item) => item.id)).toEqual([
      "shared-event",
    ]);
    expect(result.current.data?.reminders).toEqual([]);
  });
});
