import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { ApiError } from "./errors";
import { apiClient } from "./http";
import { server } from "../test/msw/server";

describe("ApiClient", () => {
  it("sends same-origin CSRF JSON requests and preserves a structured 409", async () => {
    document.body.innerHTML = `
      <script id="frontend-bootstrap" type="application/json">
        {"mode":"react","user":{"username":"测试用户"},"csrfToken":"csrf-123","endpoints":{"home":"/home/","agentWebSocketPath":"/ws/agent/"}}
      </script>
    `;

    await expect(
      apiClient.request("/api/v2/events/version-conflict/", {
        method: "PATCH",
        body: { title: "冲突" },
      }),
    ).rejects.toMatchObject({
      status: 409,
      code: "version_conflict",
      method: "PATCH",
    } satisfies Partial<ApiError>);
  });

  it("preserves server field details for 422 instead of collapsing them into a generic failure", async () => {
    server.use(
      http.patch("*/api/v2/events/invalid/", () =>
        HttpResponse.json(
          {
            error: "结束时间无效",
            code: "validation_error",
            end_at: ["结束必须晚于开始"],
          },
          { status: 422 },
        ),
      ),
    );

    await expect(
      apiClient.request("/api/v2/events/invalid/", {
        method: "PATCH",
        body: { title: "测试" },
      }),
    ).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      details: { end_at: ["结束必须晚于开始"] },
    } satisfies Partial<ApiError>);
  });

  it("does not turn an AbortSignal cancellation into a network error", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(
      apiClient.request("/api/v2/events/occurrences/", {
        signal: controller.signal,
      }),
    ).rejects.toMatchObject({
      name: "AbortError",
    });
  });
});
