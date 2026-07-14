import { apiClient, type JsonObject } from "./http";

export type AttachmentKind =
  | "event"
  | "todo"
  | "reminder"
  | "file"
  | "image"
  | "workflow"
  | "text-reference"
  | "unknown";

export interface AttachmentWire {
  id: number | string;
  type: string;
  filename?: string;
  name?: string;
  resource_id?: string | number;
  internal_id?: string | number;
  internal_type?: string;
  file_url?: string;
  preview_url?: string;
  thumbnail_url?: string;
  preview?: string;
  parse_status?: string;
  is_deleted?: boolean;
}

export interface AgentAttachment {
  id: string;
  kind: AttachmentKind;
  label: string;
  resourceId: string | null;
  occurrenceRef: JsonObject | null;
  previewUrl: string | null;
  preview: string | null;
  parseStatus: string | null;
  isAvailable: boolean;
}

export interface AgentMessage {
  id: string;
  index: number;
  role: "user" | "assistant" | "tool" | "system";
  content: string;
  attachments: AgentAttachment[];
  canRollback: boolean;
  toolName: string | null;
  toolPayload: JsonObject | null;
  reasoning: string | null;
  isStreaming?: boolean;
}

export type AgentWsEvent =
  | {
      type: "connected";
      sessionId: string;
      activeTools: string[];
      messageCount: number;
    }
  | {
      type:
        | "processing"
        | "stream_start"
        | "stream_end"
        | "finished"
        | "stopped"
        | "pong"
        | "info";
      message?: string;
    }
  | { type: "stream_chunk"; content: string }
  | { type: "reasoning"; content: string }
  | { type: "tool_call"; name: string; payload: JsonObject }
  | {
      type: "tool_result";
      name: string;
      payload: JsonObject;
      refresh: string[];
    }
  | {
      type: "status_response";
      isProcessing: boolean;
      shouldSyncImmediately: boolean;
    }
  | { type: "recursion_limit"; message: string }
  | { type: "quota_exceeded"; message: string }
  | { type: "error"; message: string; code?: string }
  | { type: "unknown"; raw: JsonObject };

function asObject(value: unknown): JsonObject | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonObject)
    : null;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
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
    "workflow",
    "text-reference",
    "pdf",
    "word",
    "excel",
  ].includes(rawKind)
    ? rawKind === "pdf" || rawKind === "word" || rawKind === "excel"
      ? "file"
      : (rawKind as AttachmentKind)
    : "unknown";
  const occurrenceRef = asObject(wire.occurrence_ref);
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
        : typeof wire.internal_id === "string" ||
            typeof wire.internal_id === "number"
          ? String(wire.internal_id)
          : null,
    occurrenceRef,
    previewUrl:
      typeof wire.preview_url === "string"
        ? wire.preview_url
        : typeof wire.thumbnail_url === "string"
          ? wire.thumbnail_url
          : typeof wire.file_url === "string"
            ? wire.file_url
            : null,
    preview: typeof wire.preview === "string" ? wire.preview : null,
    parseStatus:
      typeof wire.parse_status === "string" ? wire.parse_status : null,
    isAvailable: wire.is_deleted !== true,
  };
}

export function parseAgentWsEvent(value: unknown): AgentWsEvent {
  const raw = asObject(value);
  if (!raw || typeof raw.type !== "string")
    return { type: "unknown", raw: raw ?? {} };
  const message = typeof raw.message === "string" ? raw.message : undefined;
  if (raw.type === "connected") {
    return {
      type: "connected",
      sessionId: typeof raw.session_id === "string" ? raw.session_id : "",
      activeTools: asStringArray(raw.active_tools),
      messageCount:
        typeof raw.message_count === "number" ? raw.message_count : 0,
    };
  }
  if (
    [
      "processing",
      "stream_start",
      "stream_end",
      "finished",
      "stopped",
      "pong",
      "info",
    ].includes(raw.type)
  ) {
    return {
      type: raw.type as Extract<
        AgentWsEvent,
        {
          type:
            | "processing"
            | "stream_start"
            | "stream_end"
            | "finished"
            | "stopped"
            | "pong"
            | "info";
        }
      >["type"],
      message,
    };
  }
  if (raw.type === "stream_chunk" && typeof raw.content === "string")
    return { type: "stream_chunk", content: raw.content };
  if (raw.type === "reasoning" && typeof raw.content === "string")
    return { type: "reasoning", content: raw.content };
  if (raw.type === "tool_call" && typeof raw.name === "string")
    return {
      type: "tool_call",
      name: raw.name,
      payload: asObject(raw.args) ?? {},
    };
  if (raw.type === "tool_result" && typeof raw.name === "string")
    return {
      type: "tool_result",
      name: raw.name,
      payload: asObject(raw.result) ?? { value: raw.result },
      refresh: asStringArray(raw.refresh),
    };
  if (raw.type === "status_response")
    return {
      type: "status_response",
      isProcessing: raw.is_processing === true,
      shouldSyncImmediately: raw.should_sync_immediately === true,
    };
  if (
    (raw.type === "recursion_limit" || raw.type === "quota_exceeded") &&
    typeof raw.message === "string"
  )
    return { type: raw.type, message: raw.message };
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
  last_message_preview?: string;
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
    name?: string;
    tool_call_id?: string;
    tool_calls?: Array<{ name?: string; args?: JsonObject }>;
    reasoning_content?: string;
  }>;
  rollback_window: JsonObject | null;
}

export interface AttachableItemWire {
  type: "event" | "todo" | "reminder" | "workflow";
  id: string;
  title: string;
  subtitle?: string;
  occurrence_ref?: JsonObject;
}

export interface QuickActionTask {
  task_id: string;
  status: "pending" | "processing" | "success" | "failed" | "timeout";
  result_type?: string;
  result?: { message?: string; tool_calls?: unknown[] } | null;
  input_text: string;
  created_at?: string;
  completed_at?: string | null;
}

export interface AgentToolCategory {
  id: string;
  display_name: string;
  description: string;
  tools: Array<{ name: string; display_name: string; enabled: boolean }>;
}

export const agentApi = {
  getAvailableTools: (signal?: AbortSignal) =>
    apiClient.request<{
      categories: AgentToolCategory[];
      default_tools: string[];
    }>("/api/agent/tools/", { signal }),
  listSessions: (signal?: AbortSignal) =>
    apiClient.request<{
      sessions: AgentSessionWire[];
      current_session_id: string | null;
    }>("/api/agent/sessions/", { signal }),
  createSession: (name?: string) =>
    apiClient.request<{ session_id: string; name: string }>(
      "/api/agent/sessions/create/",
      { method: "POST", body: name ? { name } : {} },
    ),
  renameSession: (sessionId: string, name: string) =>
    apiClient.request<{ session_id: string; name: string }>(
      `/api/agent/sessions/${encodeURIComponent(sessionId)}/rename/`,
      { method: "PUT", body: { name } },
    ),
  deleteSession: (sessionId: string) =>
    apiClient.request<{ status: string }>(
      `/api/agent/sessions/${encodeURIComponent(sessionId)}/`,
      { method: "DELETE" },
    ),
  getHistory: (sessionId: string, signal?: AbortSignal) =>
    apiClient.request<AgentHistoryWire>(
      `/api/agent/history/?${new URLSearchParams({ session_id: sessionId })}`,
      { signal },
    ),
  getSessionTodos: (sessionId: string, signal?: AbortSignal) =>
    apiClient.request<{
      todos: Array<{ id: number; title: string; status: string }>;
      count: number;
    }>(
      `/api/agent/session-todos/?${new URLSearchParams({ session_id: sessionId })}`,
      { signal },
    ),
  getContextUsage: (sessionId: string, signal?: AbortSignal) =>
    apiClient.request<{
      total_tokens: number;
      target_max_tokens: number;
      remaining_tokens: number;
      has_summary: boolean;
    }>(
      `/api/agent/context-usage/?${new URLSearchParams({ session_id: sessionId })}`,
      { signal },
    ),
  optimizeMemory: (sessionId: string) =>
    apiClient.request<JsonObject>("/api/agent/optimize-memory/", {
      method: "POST",
      body: { session_id: sessionId },
    }),
  rollbackToMessage: (sessionId: string, messageIndex: number) =>
    apiClient.request<JsonObject>("/api/agent/rollback/to-message/", {
      method: "POST",
      body: { session_id: sessionId, message_index: messageIndex },
    }),
  listAttachable: (type?: string, search?: string, signal?: AbortSignal) =>
    apiClient.request<{ items: AttachableItemWire[]; types: string[] }>(
      `/api/agent/attachments/?${new URLSearchParams({ ...(type ? { type } : {}), ...(search ? { search } : {}) })}`,
      { signal },
    ),
  attachInternal: (sessionId: string, item: AttachableItemWire) =>
    apiClient.request<{ attachment: AttachmentWire }>(
      "/api/agent/attachments/internal/",
      {
        method: "POST",
        body: {
          session_id: sessionId,
          element_type: item.type,
          element_id: item.id,
          ...(item.occurrence_ref
            ? { occurrence_ref: item.occurrence_ref }
            : {}),
        },
      },
    ),
  uploadAttachment: (sessionId: string, file: File) => {
    const body = new FormData();
    body.append("session_id", sessionId);
    body.append("file", file);
    return apiClient.request<{ attachment: AttachmentWire }>(
      "/api/agent/attachments/upload/",
      { method: "POST", body },
    );
  },
  attachCloudFiles: (sessionId: string, fileIds: number[]) =>
    apiClient.request<{ attachments: AttachmentWire[] }>(
      "/api/agent/attachments/from-cloud/",
      { method: "POST", body: { session_id: sessionId, file_ids: fileIds } },
    ),
  previewAttachment: (attachmentId: string) =>
    apiClient.request<JsonObject>(
      `/api/agent/attachments/${encodeURIComponent(attachmentId)}/preview/`,
    ),
  createQuickAction: (text: string) =>
    apiClient.request<QuickActionTask>("/api/agent/quick-action/", {
      method: "POST",
      body: { text },
    }),
  getQuickAction: (taskId: string) =>
    apiClient.request<QuickActionTask>(
      `/api/agent/quick-action/${encodeURIComponent(taskId)}/`,
    ),
  cancelQuickAction: (taskId: string) =>
    apiClient.request<JsonObject>(
      `/api/agent/quick-action/${encodeURIComponent(taskId)}/cancel/`,
      { method: "DELETE" },
    ),
};
