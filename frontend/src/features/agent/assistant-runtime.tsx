import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  type ExternalStoreAdapter,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import { useMemo, type ReactNode } from "react";

import type { AgentMessage } from "../../api/agent";

function convertMessage(message: AgentMessage): ThreadMessageLike {
  if (message.role === "tool") {
    return {
      id: message.id,
      role: "assistant",
      content: [
        {
          type: "tool-call",
          toolCallId: message.id,
          toolName: message.toolName ?? "tool",
          args: (message.toolPayload ?? {}) as never,
          argsText: JSON.stringify(message.toolPayload ?? {}),
          ...(message.content ? { result: message.content } : {}),
        },
      ],
      status: { type: "complete", reason: "stop" },
    };
  }
  return {
    id: message.id,
    role: message.role === "system" ? "system" : message.role,
    content: [
      ...(message.reasoning
        ? [{ type: "reasoning" as const, text: message.reasoning }]
        : []),
      { type: "text" as const, text: message.content },
    ],
    ...(message.role === "assistant"
      ? {
          status: message.isStreaming
            ? { type: "running" as const }
            : { type: "complete" as const, reason: "stop" as const },
        }
      : {}),
  };
}

function Runtime({
  messages,
  isRunning,
  children,
}: {
  messages: AgentMessage[];
  isRunning: boolean;
  children: ReactNode;
}) {
  const adapter = useMemo<ExternalStoreAdapter<AgentMessage>>(
    () => ({
      messages,
      isRunning,
      // AgentTransport is intentionally the command boundary: assistant-ui receives
      // external state only and must not invent a second HTTP/WebSocket protocol.
      onNew: async () => undefined,
      convertMessage,
      unstable_capabilities: { copy: true },
    }),
    [isRunning, messages],
  );
  const runtime = useExternalStoreRuntime(adapter);
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  );
}

/** assistant-ui External Store bridge; domain UI remains responsible for rollback and attachments. */
export function AgentAssistantRuntime({
  messages,
  isRunning,
  children,
}: {
  messages: AgentMessage[];
  isRunning: boolean;
  children: ReactNode;
}) {
  return (
    <Runtime isRunning={isRunning} messages={messages}>
      {children}
    </Runtime>
  );
}
