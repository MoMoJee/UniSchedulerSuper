import { describe, expect, it, vi } from "vitest";

import { mapAgentAttachment, parseAgentWsEvent } from "./agent";

describe("Agent API contracts", () => {
  it("maps structured Planner attachments without treating the visual label as the resource identity", () => {
    expect(
      mapAgentAttachment({
        id: 12,
        type: "event",
        name: "答辩",
        resource_id: "event-12",
      }),
    ).toEqual({
      id: "12",
      kind: "event",
      label: "答辩",
      resourceId: "event-12",
      previewUrl: null,
      isAvailable: true,
    });
  });

  it("accepts known stream frames and safely ignores an unknown frame", () => {
    expect(
      parseAgentWsEvent({ type: "partial", content: "正在" }),
    ).toMatchObject({ type: "partial", content: "正在" });
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    expect(
      parseAgentWsEvent({ type: "future_protocol", sequence: 9 }),
    ).toMatchObject({ type: "unknown" });
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});
