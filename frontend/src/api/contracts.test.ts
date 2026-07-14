import { describe, expect, it } from "vitest";

import {
  mapPlannerEntitySummary,
  type ReminderWire,
  type TodoWire,
} from "./contracts";

describe("Planner DTO contracts", () => {
  it("maps Todo and Reminder IDs and versions without leaking their wire names", () => {
    const todo: TodoWire = {
      entity_type: "todo",
      todo_id: "todo-1",
      version: 3,
      title: "提交报告",
      description: "",
      status: "open",
      importance: "normal",
      urgency: "normal",
      priority_score: 0,
      estimated_duration_seconds: null,
      group_id: null,
      due: null,
      tags: [],
      dependencies: [],
      converted_to_event_id: null,
    };
    const reminder: ReminderWire = {
      entity_type: "reminder",
      reminder_id: "reminder-1",
      version: 4,
      title: "喝水",
      content: "",
      priority: "normal",
      status: "active",
      tzid: "Asia/Shanghai",
      trigger: null,
      snooze_until: null,
      notification_sent_at: null,
      recurrence: null,
    };
    expect(mapPlannerEntitySummary(todo)).toEqual({
      id: "todo-1",
      version: 3,
      title: "提交报告",
      entityType: "todo",
    });
    expect(mapPlannerEntitySummary(reminder)).toEqual({
      id: "reminder-1",
      version: 4,
      title: "喝水",
      entityType: "reminder",
    });
  });
});
