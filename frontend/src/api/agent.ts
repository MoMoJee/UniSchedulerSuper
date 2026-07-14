import { apiClient, type JsonObject } from "./http";

export type AttachmentKind =
  | "event"
  | "todo"
  | "reminder"
  | "file"
  | "image"
  | "text-reference"
  | "unknown";

export interface AttachmentWire {
  id: number | string;
  type: string;
  filename?: string;
  name?: string;
  resource_id?: string | number;
  preview_url?: string;
  parse_status?: string;
  is_deleted?: boolean;
}

export interface AgentAttachment {
  id: string;
  kind: AttachmentKind;
  label: string;
  resourceId: string | null;
  previewUrl: string | null;
  isAvailable: boolean;
}

export type AgentWsEvent =
  | { type: "connected" | "complete" | "pong"; sessionId?: string }
  | { type: "partial"; content: string; messageId?: string }
  | { type: "tool_call" | "tool_result"; name: string; payload: JsonObject }
  | { type: "attachment"; attachment: AttachmentWire }
  | { type: "error"; message: string; code?: string }
  | { type: "unknown"; raw: JsonObject };

function asObject(value: unknown): JsonObject | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonObject)
    : null;
}

export function mapAgentAttachment(value: unknown): AgentAttachment {
  const wire = asObject(value);
  if (!wire || (typeof wire.id !== "string" && typeof wire.id !== "number")) {
    throw new Error("附件响应缺少可引用的 id。");
  }
  const rawKind = typeof wire.type === "string" ? wire.type : "unknown";
  const kind: AttachmentKind = [
    "event",
    "todo",
    "reminder",
    "file",
    "image",
    "text-reference",
  ].includes(rawKind)
    ? (rawKind as AttachmentKind)
    : "unknown";
  return {
    id: String(wire.id),
    kind,
    label:
      typeof wire.filename === "string"
        ? wire.filename
        : typeof wire.name === "string"
          ? wire.name
          : "未命名附件",
    resourceId:
      typeof wire.resource_id === "string" ||
      typeof wire.resource_id === "number"
        ? String(wire.resource_id)
        : null,
    previewUrl: typeof wire.preview_url === "string" ? wire.preview_url : null,
    isAvailable: wire.is_deleted !== true,
  };
}

/** Unknown frames are intentionally non-fatal so a server rollout cannot break an active conversation. */
export function parseAgentWsEvent(value: unknown): AgentWsEvent {
  const raw = asObject(value);
  if (!raw || typeof raw.type !== "string")
    return { type: "unknown", raw: raw ?? {} };
  const sessionId =
    typeof raw.session_id === "string" ? raw.session_id : undefined;
  if (
    raw.type === "connected" ||
    raw.type === "complete" ||
    raw.type === "pong"
  )
    return { type: raw.type, sessionId };
  if (raw.type === "partial" && typeof raw.content === "string")
    return {
      type: "partial",
      content: raw.content,
      messageId:
        typeof raw.message_id === "string" ? raw.message_id : undefined,
    };
  if (
    (raw.type === "tool_call" || raw.type === "tool_result") &&
    typeof raw.name === "string"
  ) {
    return {
      type: raw.type,
      name: raw.name,
      payload: asObject(raw.payload) ?? {},
    };
  }
  if (raw.type === "attachment")
    return { type: "attachment", attachment: raw as unknown as AttachmentWire };
  if (raw.type === "error" && typeof raw.message === "string")
    return {
      type: "error",
      message: raw.message,
      code: typeof raw.code === "string" ? raw.code : undefined,
    };
  if (import.meta.env.DEV)
    console.warn("Ignoring unknown Agent WebSocket frame", raw);
  return { type: "unknown", raw };
}

export interface AgentSessionWire {
  session_id: string;
  name: string;
  message_count: number;
  updated_at: string;
}

export interface AgentHistoryWire {
  session_id: string;
  messages: Array<{
    role: string;
    content: string;
    id?: string;
    index: number;
    can_rollback?: boolean;
    attachments?: AttachmentWire[];
  }>;
  rollback_window: JsonObject | null;
}

export const agentApi = {
  listSessions: (signal?: AbortSignal) =>
    apiClient.request<{
      sessions: AgentSessionWire[];
      current_session_id: string | null;
    }>("/api/agent/sessions/", { signal }),
  getHistory: (sessionId: string, signal?: AbortSignal) =>
    apiClient.request<AgentHistoryWire>(
      `/api/agent/history/?${new URLSearchParams({ session_id: sessionId })}`,
      { signal },
    ),
  rollbackToMessage: (sessionId: string, messageIndex: number) =>
    apiClient.request<JsonObject>("/api/agent/rollback/to-message/", {
      method: "POST",
      body: { session_id: sessionId, message_index: messageIndex },
    }),
};
