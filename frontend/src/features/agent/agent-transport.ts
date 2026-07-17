import {
  parseAgentWsEvent,
  type AgentMessage,
  type AgentWsEvent,
} from "../../api/agent";

export type AgentConnectionState =
  "idle" | "connecting" | "connected" | "reconnecting" | "offline" | "error";

export interface AgentTransportState {
  connection: AgentConnectionState;
  isProcessing: boolean;
  statusMessage: string | null;
  error: string | null;
  messages: AgentMessage[];
  activeTools: string[];
  sessionId: string | null;
}

export const initialAgentTransportState: AgentTransportState = {
  connection: "idle",
  isProcessing: false,
  statusMessage: null,
  error: null,
  messages: [],
  activeTools: [],
  sessionId: null,
};

export type AgentTransportAction =
  | { type: "connect"; reconnecting?: boolean; sessionId?: string }
  | { type: "connected"; sessionId: string; activeTools: string[] }
  | { type: "history"; sessionId: string; messages: AgentMessage[] }
  | { type: "event"; event: AgentWsEvent }
  | { type: "queue-user"; message: AgentMessage }
  | { type: "disconnected"; recoverable: boolean; message?: string }
  | { type: "clear-error" };

function newStreamingMessage(content = ""): AgentMessage {
  return {
    id: `stream-${crypto.randomUUID()}`,
    index: -1,
    role: "assistant",
    content,
    attachments: [],
    canRollback: false,
    toolName: null,
    toolPayload: null,
    reasoning: null,
    isStreaming: true,
  };
}

function updateLastStreaming(
  state: AgentTransportState,
  update: (message: AgentMessage) => AgentMessage,
): AgentMessage[] {
  const index = [...state.messages]
    .reverse()
    .findIndex((item) => item.isStreaming);
  if (index < 0) return [...state.messages, update(newStreamingMessage())];
  const actual = state.messages.length - index - 1;
  return state.messages.map((item, itemIndex) =>
    itemIndex === actual ? update(item) : item,
  );
}

export function agentTransportReducer(
  state: AgentTransportState,
  action: AgentTransportAction,
): AgentTransportState {
  switch (action.type) {
    case "connect":
      return {
        ...state,
        connection: action.reconnecting ? "reconnecting" : "connecting",
        sessionId: action.sessionId ?? state.sessionId,
        error: null,
      };
    case "connected":
      return {
        ...state,
        connection: "connected",
        error: null,
        sessionId: action.sessionId,
        activeTools: action.activeTools,
      };
    case "history":
      return {
        ...state,
        messages: action.messages,
        sessionId: action.sessionId,
        isProcessing: false,
        statusMessage: null,
      };
    case "queue-user":
      return {
        ...state,
        messages: [...state.messages, action.message],
        isProcessing: true,
        error: null,
      };
    case "clear-error":
      return { ...state, error: null };
    case "disconnected":
      return {
        ...state,
        connection: action.recoverable ? "reconnecting" : "offline",
        isProcessing: false,
        statusMessage: null,
        error:
          action.message ??
          (action.recoverable ? "连接中断，正在重连…" : "Agent 连接已关闭。"),
      };
    case "event": {
      const event = action.event;
      if (event.type === "connected")
        return agentTransportReducer(state, {
          type: "connected",
          sessionId: event.sessionId,
          activeTools: event.activeTools,
        });
      if (event.type === "processing")
        return {
          ...state,
          isProcessing: true,
          statusMessage: event.message ?? "正在思考…",
          error: null,
        };
      if (event.type === "stream_start")
        return {
          ...state,
          isProcessing: true,
          statusMessage: null,
          messages: state.messages.some((message) => message.isStreaming)
            ? state.messages
            : [...state.messages, newStreamingMessage()],
        };
      if (event.type === "stream_chunk")
        return {
          ...state,
          isProcessing: true,
          statusMessage: null,
          messages: updateLastStreaming(state, (message) => ({
            ...message,
            content: `${message.content}${event.content}`,
          })),
        };
      if (event.type === "reasoning")
        return {
          ...state,
          messages: updateLastStreaming(state, (message) => ({
            ...message,
            reasoning: `${message.reasoning ?? ""}${event.content}`,
          })),
        };
      if (event.type === "tool_call") {
        const message: AgentMessage = {
          id: `tool-${crypto.randomUUID()}`,
          index: -1,
          role: "tool",
          content: "",
          attachments: [],
          canRollback: false,
          toolName: event.name,
          toolPayload: event.payload,
          reasoning: null,
        };
        return {
          ...state,
          isProcessing: true,
          messages: [
            ...state.messages.map((item) =>
              item.isStreaming ? { ...item, isStreaming: false } : item,
            ),
            message,
          ],
        };
      }
      if (event.type === "tool_result") {
        const message: AgentMessage = {
          id: `result-${crypto.randomUUID()}`,
          index: -1,
          role: "tool",
          content:
            typeof event.payload.value === "string"
              ? event.payload.value
              : JSON.stringify(event.payload),
          attachments: [],
          canRollback: false,
          toolName: event.name,
          toolPayload: event.payload,
          reasoning: null,
        };
        return {
          ...state,
          isProcessing: true,
          messages: [...state.messages, message],
        };
      }
      if (event.type === "stream_end")
        return {
          ...state,
          messages: state.messages.map((message) =>
            message.isStreaming ? { ...message, isStreaming: false } : message,
          ),
        };
      if (event.type === "finished" || event.type === "stopped")
        return {
          ...state,
          isProcessing: false,
          statusMessage: event.message ?? null,
          messages: state.messages.map((message) =>
            message.isStreaming ? { ...message, isStreaming: false } : message,
          ),
        };
      if (event.type === "status_response")
        return {
          ...state,
          isProcessing: event.isProcessing,
          statusMessage: event.isProcessing ? "正在恢复执行状态…" : null,
        };
      if (
        event.type === "recursion_limit" ||
        event.type === "quota_exceeded" ||
        event.type === "error"
      )
        return {
          ...state,
          isProcessing: false,
          statusMessage: null,
          error: event.message,
          messages: state.messages.map((message) =>
            message.isStreaming ? { ...message, isStreaming: false } : message,
          ),
        };
      return state;
    }
  }
}

export interface AgentTransportOptions {
  url: string;
  onEvent: (event: AgentWsEvent) => void;
  onConnectionChange: (
    connected: boolean,
    recoverable: boolean,
    message?: string,
  ) => void;
}

/** Browser-only WS transport. It never persists message content and reconnects only after an unexpected close. */
export class AgentTransport {
  private socket: WebSocket | null = null;
  private stopped = false;
  private attempts = 0;
  private timer: number | null = null;

  constructor(private readonly options: AgentTransportOptions) {}

  connect(): void {
    this.stopped = false;
    this.open();
  }

  disconnect(): void {
    this.stopped = true;
    if (this.timer !== null) window.clearTimeout(this.timer);
    this.timer = null;
    this.socket?.close(1000, "session-switch");
    this.socket = null;
  }

  send(
    type: "message" | "ping" | "stop" | "continue" | "check_status",
    payload: Record<string, unknown> = {},
  ): boolean {
    if (this.socket?.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify({ type, ...payload }));
    return true;
  }

  private open(): void {
    try {
      this.socket = new WebSocket(this.options.url);
    } catch {
      this.schedule("无法创建 Agent 连接。");
      return;
    }
    this.socket.addEventListener("open", () => {
      this.attempts = 0;
      this.options.onConnectionChange(true, false);
      this.send("check_status");
    });
    this.socket.addEventListener("message", (message) => {
      try {
        this.options.onEvent(
          parseAgentWsEvent(JSON.parse(String(message.data))),
        );
      } catch {
        this.options.onEvent({
          type: "error",
          message: "Agent 返回了无法识别的数据。",
          code: "invalid_ws_payload",
        });
      }
    });
    this.socket.addEventListener("error", () =>
      this.options.onConnectionChange(
        false,
        !this.stopped,
        "Agent 网络连接异常。",
      ),
    );
    this.socket.addEventListener("close", () => {
      this.socket = null;
      if (!this.stopped) this.schedule("连接中断，正在重连…");
    });
  }

  private schedule(message: string): void {
    if (this.stopped) return;
    if (this.attempts >= 4) {
      this.options.onConnectionChange(
        false,
        false,
        "Agent 暂时无法连接，请稍后重试。",
      );
      return;
    }
    const delay = Math.min(8000, 500 * 2 ** this.attempts++);
    this.options.onConnectionChange(false, true, message);
    this.timer = window.setTimeout(() => this.open(), delay);
  }
}
