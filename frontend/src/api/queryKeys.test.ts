import { describe, expect, it } from "vitest";

import { agentKeys, fileKeys, plannerKeys } from "./queryKeys";

describe("query keys", () => {
  it("separates user, date-window and resource identities", () => {
    expect(
      plannerKeys.calendar("alice", "from", "to", { group: "a" }),
    ).not.toEqual(plannerKeys.calendar("bob", "from", "to", { group: "a" }));
    expect(plannerKeys.event("event-1")).not.toEqual(
      plannerKeys.todo("event-1"),
    );
    expect(agentKeys.history("session-1")).not.toEqual(fileKeys.detail(1));
  });
});
