import type { JsonObject } from "./http";
import type { OccurrenceRefWire } from "./planner";

export interface OccurrenceRef {
  entityId: string;
  seriesId: string | null;
  recurrenceId: string | null;
  occurrenceStart: string | null;
  sourceVersion: number;
}

export interface PlannerOccurrence {
  id: string;
  title: string;
  start: string;
  end: string | null;
  type: "event" | "reminder" | "unknown";
  description: string;
  status: string;
  importance: string;
  urgency: string;
  ddlAt: string | null;
  groupId: string | null;
  isAllDay: boolean;
  isOverride: boolean;
  readOnly: boolean;
  ownerUsername: string | null;
  shareGroupId: string | null;
  shareGroupIds: string[];
  occurrenceRef: OccurrenceRef | null;
  /** Present when the matching definition endpoint supplied the RRule. */
  recurrenceRRule?: string | null;
}

function asRecord(value: unknown, message: string): JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(message);
  }
  return value as JsonObject;
}

function requiredString(record: JsonObject, key: string): string {
  const value = record[key];
  if (typeof value !== "string" || !value)
    throw new Error(`服务端响应缺少字符串字段 ${key}。`);
  return value;
}

export function mapOccurrenceRef(value: unknown): OccurrenceRef | null {
  if (value === null || value === undefined) return null;
  const wire = asRecord(
    value,
    "occurrence_ref 必须是对象。",
  ) as unknown as OccurrenceRefWire;
  if (
    typeof wire.entity_id !== "string" ||
    !Number.isInteger(wire.source_version)
  ) {
    throw new Error("occurrence_ref 缺少 entity_id 或 source_version。");
  }
  return {
    entityId: wire.entity_id,
    seriesId: typeof wire.series_id === "string" ? wire.series_id : null,
    recurrenceId:
      typeof wire.recurrence_id === "string" ? wire.recurrence_id : null,
    occurrenceStart:
      typeof wire.occurrence_start === "string" ? wire.occurrence_start : null,
    sourceVersion: wire.source_version,
  };
}

export function mapPlannerOccurrence(value: unknown): PlannerOccurrence {
  const record = asRecord(value, "日程实例必须是对象。");
  const rawType =
    typeof record.entity_type === "string"
      ? record.entity_type
      : typeof record.type === "string"
        ? record.type
        : "event";
  return {
    id:
      typeof record.id === "string"
        ? record.id
        : requiredString(record, "event_id"),
    title: requiredString(record, "title"),
    start: requiredString(record, "start"),
    end: typeof record.end === "string" ? record.end : null,
    type: rawType === "event" || rawType === "reminder" ? rawType : "unknown",
    description:
      typeof record.description === "string"
        ? record.description
        : typeof record.content === "string"
          ? record.content
          : "",
    status: typeof record.status === "string" ? record.status : "",
    importance: typeof record.importance === "string" ? record.importance : "",
    urgency: typeof record.urgency === "string" ? record.urgency : "",
    ddlAt: typeof record.ddl_at === "string" ? record.ddl_at : null,
    groupId: typeof record.group_id === "string" ? record.group_id : null,
    isAllDay: record.is_all_day === true,
    isOverride: record.is_override === true,
    readOnly: record.read_only === true,
    ownerUsername:
      typeof record.owner_username === "string" ? record.owner_username : null,
    shareGroupId:
      typeof record.share_group_id === "string" ? record.share_group_id : null,
    shareGroupIds: Array.isArray(record.share_group_ids)
      ? record.share_group_ids.filter(
          (value): value is string =>
            typeof value === "string" && Boolean(value),
        )
      : [],
    occurrenceRef: mapOccurrenceRef(record.occurrence_ref),
  };
}
