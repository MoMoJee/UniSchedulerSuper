import { apiClient, type JsonObject } from "./http";
import { PlannerClientValidationError } from "./errors";

export type PlannerScope = "single" | "future" | "all";

export interface OccurrenceRefWire {
  entity_id: string;
  series_id?: string | null;
  recurrence_id?: string | null;
  source_version: number;
}

export interface PlannerBootstrapWire {
  entrypoints: Record<
    string,
    {
      mode: string;
      can_read_normalized: boolean;
      can_write_normalized: boolean;
    }
  >;
}

export interface PlannerListWire {
  occurrences?: JsonObject[];
  definitions?: JsonObject[];
  groups?: JsonObject[];
  todos?: JsonObject[];
  reminders?: JsonObject[];
  count?: number;
}

export interface PlannerCommandOptions {
  expectedVersion: number;
  scope?: PlannerScope;
  occurrenceRef?: OccurrenceRefWire;
}

function assertExpectedVersion(expectedVersion: number): void {
  if (!Number.isInteger(expectedVersion) || expectedVersion < 1) {
    throw new PlannerClientValidationError(
      "expected_version 必须是大于 0 的整数。",
    );
  }
}

function commandMetadata(options: PlannerCommandOptions): JsonObject {
  assertExpectedVersion(options.expectedVersion);
  const scope = options.scope ?? "all";
  if ((scope === "single" || scope === "future") && !options.occurrenceRef) {
    throw new PlannerClientValidationError(
      `${scope} 范围操作必须带有服务端 occurrence_ref。`,
    );
  }
  return {
    expected_version: options.expectedVersion,
    // V2 intentionally exposes a concise UI/domain name, while the existing
    // normalized backend command contract uses this explicit wire literal.
    scope: scope === "future" ? "this_and_future" : scope,
    ...(options.occurrenceRef ? { occurrence_ref: options.occurrenceRef } : {}),
  };
}

function rangeParams(from: string, to: string): URLSearchParams {
  if (!from || !to || new Date(from) >= new Date(to)) {
    throw new PlannerClientValidationError(
      "Planner 查询必须提供合法的半开区间 from、to。",
    );
  }
  return new URLSearchParams({ from, to });
}

export const plannerApi = {
  bootstrap: () =>
    apiClient.request<PlannerBootstrapWire>("/api/v2/planner/bootstrap/"),

  listEventOccurrences: (from: string, to: string, signal?: AbortSignal) =>
    apiClient.request<PlannerListWire>(
      `/api/v2/events/occurrences/?${rangeParams(from, to)}`,
      { signal },
    ),
  listEventDefinitions: (from: string, to: string, signal?: AbortSignal) =>
    apiClient.request<PlannerListWire>(
      `/api/v2/events/definitions/?${rangeParams(from, to)}`,
      { signal },
    ),
  listGroups: (signal?: AbortSignal) =>
    apiClient.request<PlannerListWire>("/api/v2/groups/", { signal }),
  listTodos: (
    filters: { status?: string; groupId?: string } = {},
    signal?: AbortSignal,
  ) => {
    const params = new URLSearchParams();
    if (filters.status) params.set("status", filters.status);
    if (filters.groupId) params.set("group_id", filters.groupId);
    return apiClient.request<PlannerListWire>(
      `/api/v2/todos/${params.size ? `?${params}` : ""}`,
      { signal },
    );
  },
  listReminders: (from?: string, to?: string, signal?: AbortSignal) =>
    apiClient.request<PlannerListWire>(
      from && to
        ? `/api/v2/reminders/?${rangeParams(from, to)}`
        : "/api/v2/reminders/",
      { signal },
    ),

  createEvent: (payload: JsonObject) =>
    apiClient.request<JsonObject>("/api/v2/events/", {
      method: "POST",
      body: payload,
    }),
  patchEvent: (
    eventId: string,
    payload: JsonObject,
    options: PlannerCommandOptions,
  ) =>
    apiClient.request<JsonObject>(
      `/api/v2/events/${encodeURIComponent(eventId)}/`,
      {
        method: "PATCH",
        body: { ...payload, ...commandMetadata(options) },
      },
    ),
  deleteEvent: (eventId: string, options: PlannerCommandOptions) =>
    apiClient.request<JsonObject>(
      `/api/v2/events/${encodeURIComponent(eventId)}/`,
      {
        method: "DELETE",
        body: commandMetadata(options),
      },
    ),
  createGroup: (payload: JsonObject) =>
    apiClient.request<JsonObject>("/api/v2/groups/", {
      method: "POST",
      body: payload,
    }),
  patchGroup: (
    groupId: string,
    payload: JsonObject,
    expectedVersion: number,
  ) => {
    assertExpectedVersion(expectedVersion);
    return apiClient.request<JsonObject>(
      `/api/v2/groups/${encodeURIComponent(groupId)}/`,
      {
        method: "PATCH",
        body: { ...payload, expected_version: expectedVersion },
      },
    );
  },
  createTodo: (payload: JsonObject) =>
    apiClient.request<JsonObject>("/api/v2/todos/", {
      method: "POST",
      body: payload,
    }),
  patchTodo: (todoId: string, payload: JsonObject, expectedVersion: number) => {
    assertExpectedVersion(expectedVersion);
    return apiClient.request<JsonObject>(
      `/api/v2/todos/${encodeURIComponent(todoId)}/`,
      {
        method: "PATCH",
        body: { ...payload, expected_version: expectedVersion },
      },
    );
  },
  deleteTodo: (todoId: string, expectedVersion: number) => {
    assertExpectedVersion(expectedVersion);
    return apiClient.request<JsonObject>(
      `/api/v2/todos/${encodeURIComponent(todoId)}/`,
      { method: "DELETE", body: { expected_version: expectedVersion } },
    );
  },
  createReminder: (payload: JsonObject) =>
    apiClient.request<JsonObject>("/api/v2/reminders/", {
      method: "POST",
      body: payload,
    }),
  patchReminder: (
    reminderId: string,
    payload: JsonObject,
    options: PlannerCommandOptions,
  ) =>
    apiClient.request<JsonObject>(
      `/api/v2/reminders/${encodeURIComponent(reminderId)}/`,
      {
        method: "PATCH",
        body: { ...payload, ...commandMetadata(options) },
      },
    ),
  deleteReminder: (reminderId: string, options: PlannerCommandOptions) =>
    apiClient.request<JsonObject>(
      `/api/v2/reminders/${encodeURIComponent(reminderId)}/`,
      { method: "DELETE", body: commandMetadata(options) },
    ),
};
