import { describe, expect, it } from "vitest";

import { buildRRule, parseRRule } from "./recurrence-editor";

describe("RecurrenceEditor rule codec", () => {
  it("round-trips weekly interval, weekdays and finite count", () => {
    const draft = parseRRule("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE;COUNT=10");
    expect(draft).toMatchObject({
      frequency: "WEEKLY",
      interval: 2,
      byDay: ["MO", "WE"],
      count: "10",
    });
    expect(buildRRule(draft)).toBe(
      "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE;COUNT=10",
    );
  });

  it("represents no rule as null and rejects mutually exclusive end modes", () => {
    expect(buildRRule(parseRRule(null))).toBeNull();
    expect(() =>
      buildRRule({
        frequency: "DAILY",
        interval: 1,
        byDay: [],
        count: "3",
        until: "2026-08-01T00:00",
      }),
    ).toThrow("不能同时设置次数和结束日期");
  });
});
