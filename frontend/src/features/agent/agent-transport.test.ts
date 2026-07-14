import { describe, expect, it } from "vitest";

import {
  agentTransportReducer,
  initialAgentTransportState,
} from "./agent-transport";

describe("Agent transport reducer", () => {
  it("merges real server stream_chunk frames and clears the running state only at finished", () => {
    const connected = agentTransportReducer(initialAgentTransportState, {
      type: "event",
      event: {
        type: "connected",
        sessionId: "user_1_a",
        activeTools: [],
        messageCount: 0,
      },
    });
    const streaming = agentTransportReducer(
      agentTransportReducer(connected, {
        type: "event",
        event: { type: "stream_start" },
      }),
      { type: "event", event: { type: "stream_chunk", content: "第一段" } },
    );
    const complete = agentTransportReducer(
      agentTransportReducer(streaming, {
        type: "event",
        event: { type: "stream_chunk", content: "第二段" },
      }),
      { type: "event", event: { type: "finished" } },
    );
    expect(complete.messages.at(-1)).toMatchObject({
      content: "第一段第二段",
      isStreaming: false,
    });
    expect(complete.isProcessing).toBe(false);
  });

  it("keeps tool calls structured and never treats unknown frames as a fatal error", () => {
    const next = agentTransportReducer(initialAgentTransportState, {
      type: "event",
      event: {
        type: "tool_call",
        name: "create_event",
        payload: { title: "测试" },
      },
    });
    expect(next.messages[0]).toMatchObject({
      role: "tool",
      toolName: "create_event",
      toolPayload: { title: "测试" },
    });
    expect(
      agentTransportReducer(next, {
        type: "event",
        event: { type: "unknown", raw: { type: "future" } },
      }),
    ).toEqual(next);
  });
});
