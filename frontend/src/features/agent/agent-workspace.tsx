import { useQueryClient } from "@tanstack/react-query";
import {
  CircleAlert,
  LoaderCircle,
  MoreHorizontal,
  Pencil,
  Plus,
  RotateCcw,
  Send,
  Square,
  Trash2,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";

import {
  agentApi,
  mapAgentAttachment,
  type AgentAttachment,
  type AgentHistoryWire,
  type AgentMessage,
} from "../../api/agent";
import { ApiError, toUserFacingApiMessage } from "../../api/errors";
import { agentKeys, plannerKeys } from "../../api/queryKeys";
import { SafeMarkdown } from "../../components/shared/safe-markdown";
import { Button } from "../../components/ui/button";
import { ConfirmDialog, TextInputDialog } from "../../components/ui/dialog";
import { cn } from "../../lib/cn";
import { AgentAssistantRuntime } from "./assistant-runtime";
import { AttachmentChips, AttachmentPicker } from "./attachment-picker";
import { QuickAction } from "./quick-action";
import { ToolPicker } from "./tool-picker";
import {
  AgentTransport,
  agentTransportReducer,
  initialAgentTransportState,
} from "./agent-transport";

const SESSION_KEY = "unischedulersuper.agent.active-session";

function wsUrl(
  path: string,
  sessionId: string,
  activeTools: string[] | null,
): string {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const base = path.startsWith("ws")
    ? path
    : `${protocol}://${window.location.host}${path}`;
  const url = new URL(base, window.location.origin);
  url.searchParams.set("session_id", sessionId);
  if (activeTools !== null)
    url.searchParams.set("active_tools", activeTools.join(","));
  return url.toString();
}

function mapHistory(history: AgentHistoryWire): AgentMessage[] {
  return history.messages.flatMap((message) => {
    const role =
      message.role === "user" ||
      message.role === "assistant" ||
      message.role === "tool"
        ? message.role
        : "system";
    const attachments = (message.attachments ?? []).flatMap((attachment) => {
      try {
        return [mapAgentAttachment(attachment)];
      } catch {
        return [];
      }
    });
    const base: AgentMessage = {
      id: message.id ?? `history-${message.index}`,
      index: message.index,
      role,
      content: message.content ?? "",
      attachments,
      canRollback: message.can_rollback === true,
      toolName: message.name ?? null,
      toolPayload: null,
      reasoning: message.reasoning_content ?? null,
    };
    const toolCalls = message.tool_calls ?? [];
    return [
      base,
      ...toolCalls.map((tool, index): AgentMessage => ({
        id: `${base.id}-call-${index}`,
        index: -1,
        role: "tool",
        content: "",
        attachments: [],
        canRollback: false,
        toolName: tool.name ?? "tool",
        toolPayload: tool.args ?? {},
        reasoning: null,
      })),
    ];
  });
}

function messageLabel(message: AgentMessage): string {
  if (message.role === "user") return "你";
  if (message.role === "tool") return `工具 · ${message.toolName ?? "执行"}`;
  return "Agent";
}

export function AgentWorkspace({
  username,
  webSocketPath,
}: {
  username: string;
  webSocketPath: string;
}) {
  const client = useQueryClient();
  const [state, dispatch] = useReducer(
    agentTransportReducer,
    initialAgentTransportState,
  );
  const [selectedAttachments, setSelectedAttachments] = useState<
    AgentAttachment[]
  >([]);
  const [draft, setDraft] = useState("");
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [sessions, setSessions] = useState<
    Array<{ session_id: string; name: string; message_count: number }>
  >([]);
  const [rollbackTarget, setRollbackTarget] = useState<AgentMessage | null>(
    null,
  );
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [renameTarget, setRenameTarget] = useState<{
    id: string;
    name: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [activeTools, setActiveTools] = useState<string[] | null>(null);
  const [contextUsage, setContextUsage] = useState<{
    total: number;
    target: number;
    remaining: number;
    hasSummary: boolean;
  } | null>(null);
  const [sessionTodos, setSessionTodos] = useState<
    Array<{ id: number; title: string; status: string }>
  >([]);
  const transport = useRef<AgentTransport | null>(null);
  const activeToolsRef = useRef<string[] | null>(null);
  const end = useRef<HTMLDivElement>(null);

  const refreshHistory = useCallback(
    async (sessionId: string) => {
      const history = await agentApi.getHistory(sessionId);
      dispatch({ type: "history", sessionId, messages: mapHistory(history) });
      client.setQueryData(agentKeys.history(sessionId), history);
    },
    [client],
  );
  const refreshSessions = useCallback(async () => {
    const result = await agentApi.listSessions();
    setSessions(result.sessions);
    client.setQueryData(agentKeys.sessions(username), result);
    return result;
  }, [client, username]);
  const invalidatePlanner = useCallback(
    () => client.invalidateQueries({ queryKey: plannerKeys.all }),
    [client],
  );

  const connect = useCallback(
    (sessionId: string, nextActiveTools = activeToolsRef.current) => {
      transport.current?.disconnect();
      dispatch({ type: "connect" });
      transport.current = new AgentTransport({
        url: wsUrl(webSocketPath, sessionId, nextActiveTools),
        onEvent: (event) => {
          dispatch({ type: "event", event });
          if (event.type === "connected")
            void refreshHistory(event.sessionId).catch((error: unknown) =>
              dispatch({
                type: "event",
                event: {
                  type: "error",
                  message:
                    error instanceof Error
                      ? error.message
                      : "无法恢复对话历史。",
                },
              }),
            );
          if (event.type === "finished" || event.type === "stopped") {
            void refreshHistory(sessionId).catch(() => undefined);
            void refreshSessions().catch(() => undefined);
          }
          if (event.type === "tool_result") void invalidatePlanner();
        },
        onConnectionChange: (connected, recoverable, message) =>
          dispatch(
            connected
              ? { type: "connected", sessionId, activeTools: [] }
              : { type: "disconnected", recoverable, message },
          ),
      });
      transport.current.connect();
    },
    [invalidatePlanner, refreshHistory, refreshSessions, webSocketPath],
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const listed = await refreshSessions();
        const saved = window.localStorage.getItem(SESSION_KEY);
        const target =
          saved &&
          listed.sessions.some((session) => session.session_id === saved)
            ? saved
            : (listed.current_session_id ?? listed.sessions[0]?.session_id);
        const sessionId = target ?? (await agentApi.createSession()).session_id;
        if (cancelled) return;
        window.localStorage.setItem(SESSION_KEY, sessionId);
        connect(sessionId);
      } catch (error) {
        dispatch({
          type: "disconnected",
          recoverable: false,
          message:
            error instanceof Error ? error.message : "无法初始化 Agent 会话。",
        });
      }
    })();
    return () => {
      cancelled = true;
      transport.current?.disconnect();
    };
  }, [connect, refreshSessions]);

  useEffect(() => {
    if (!state.sessionId || state.connection !== "connected") return undefined;
    const controller = new AbortController();
    void Promise.all([
      agentApi.getContextUsage(state.sessionId, controller.signal),
      agentApi.getSessionTodos(state.sessionId, controller.signal),
    ])
      .then(([usage, todos]) => {
        if (controller.signal.aborted) return;
        setContextUsage({
          total: usage.total_tokens,
          target: usage.target_max_tokens,
          remaining: usage.remaining_tokens,
          hasSummary: usage.has_summary,
        });
        setSessionTodos(todos.todos);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setContextUsage(null);
          setSessionTodos([]);
        }
      });
    return () => controller.abort();
  }, [state.connection, state.sessionId, state.messages.length]);

  useEffect(() => {
    const scroll = end.current?.scrollIntoView;
    if (typeof scroll === "function") {
      scroll.call(end.current, { behavior: "smooth", block: "end" });
    }
  }, [state.messages.length, state.isProcessing]);

  const activeSessionId = state.sessionId;
  const send = async () => {
    const content = draft.trim();
    if (!content || state.isProcessing || !activeSessionId) return;
    setBusy(true);
    try {
      // Preview validates ownership/deletion before the WebSocket payload is emitted.
      await Promise.all(
        selectedAttachments.map((attachment) =>
          agentApi.previewAttachment(attachment.id),
        ),
      );
      const sent = transport.current?.send("message", {
        content,
        attachment_ids: selectedAttachments.map((attachment) =>
          Number(attachment.id),
        ),
      });
      if (!sent) throw new Error("Agent 当前未连接，消息尚未发送。");
      dispatch({
        type: "queue-user",
        message: {
          id: `local-${crypto.randomUUID()}`,
          index: -1,
          role: "user",
          content,
          attachments: selectedAttachments,
          canRollback: false,
          toolName: null,
          toolPayload: null,
          reasoning: null,
        },
      });
      setDraft("");
      setSelectedAttachments([]);
    } catch (error) {
      dispatch({
        type: "event",
        event: {
          type: "error",
          message:
            error instanceof ApiError
              ? toUserFacingApiMessage(error)
              : error instanceof Error
                ? error.message
                : "发送失败。",
        },
      });
    } finally {
      setBusy(false);
    }
  };
  const attachLocalFiles = async (files: FileList | File[]) => {
    if (!activeSessionId || !files.length || state.isProcessing) return;
    setBusy(true);
    try {
      const uploaded = await Promise.all(
        Array.from(files).map(async (file): Promise<AgentAttachment> => {
          const response = await agentApi.uploadAttachment(
            activeSessionId,
            file,
          );
          return {
            id: String(response.attachment.id),
            kind: response.attachment.type === "image" ? "image" : "file",
            label: response.attachment.filename ?? file.name,
            resourceId: null,
            occurrenceRef: null,
            previewUrl: null,
            preview: null,
            parseStatus: response.attachment.parse_status ?? "pending",
            isAvailable: true,
          };
        }),
      );
      setSelectedAttachments((items) => [...items, ...uploaded]);
    } catch (error) {
      dispatch({
        type: "event",
        event: {
          type: "error",
          message: error instanceof Error ? error.message : "上传附件失败。",
        },
      });
    } finally {
      setBusy(false);
    }
  };
  const switchSession = async (sessionId: string) => {
    if (sessionId === activeSessionId) return;
    window.localStorage.setItem(SESSION_KEY, sessionId);
    setSelectedAttachments([]);
    setDraft("");
    setSessionsOpen(false);
    connect(sessionId);
  };
  const createSession = async () => {
    setBusy(true);
    try {
      const created = await agentApi.createSession();
      await refreshSessions();
      await switchSession(created.session_id);
    } catch (error) {
      dispatch({
        type: "event",
        event: {
          type: "error",
          message: error instanceof Error ? error.message : "创建会话失败。",
        },
      });
    } finally {
      setBusy(false);
    }
  };
  const rollback = async () => {
    if (!rollbackTarget || !activeSessionId) return;
    setBusy(true);
    try {
      await agentApi.rollbackToMessage(activeSessionId, rollbackTarget.index);
      setDraft(rollbackTarget.content);
      setSelectedAttachments(rollbackTarget.attachments);
      await refreshHistory(activeSessionId);
      await invalidatePlanner();
      setRollbackTarget(null);
    } catch (error) {
      dispatch({
        type: "event",
        event: {
          type: "error",
          message:
            error instanceof ApiError && error.status === 410
              ? "这条消息不在当前可回滚窗口内，不能回滚。"
              : error instanceof Error
                ? error.message
                : "回滚失败。",
        },
      });
    } finally {
      setBusy(false);
    }
  };
  const deleteSession = async () => {
    if (!deleteTarget) return;
    setBusy(true);
    try {
      await agentApi.deleteSession(deleteTarget);
      const left = (await refreshSessions()).sessions.filter(
        (session) => session.session_id !== deleteTarget,
      );
      if (deleteTarget === activeSessionId) {
        const next =
          left[0]?.session_id ?? (await agentApi.createSession()).session_id;
        await switchSession(next);
      }
      setDeleteTarget(null);
    } catch (error) {
      dispatch({
        type: "event",
        event: {
          type: "error",
          message: error instanceof Error ? error.message : "删除会话失败。",
        },
      });
    } finally {
      setBusy(false);
    }
  };
  const renameSession = async (name: string) => {
    if (!renameTarget) return;
    setBusy(true);
    try {
      await agentApi.renameSession(renameTarget.id, name);
      await refreshSessions();
      setRenameTarget(null);
      setSessionsOpen(false);
    } catch (error) {
      dispatch({
        type: "event",
        event: {
          type: "error",
          message: error instanceof Error ? error.message : "重命名会话失败。",
        },
      });
    } finally {
      setBusy(false);
    }
  };
  const currentName = useMemo(
    () =>
      sessions.find((session) => session.session_id === activeSessionId)
        ?.name ?? "新对话",
    [activeSessionId, sessions],
  );
  const changeTools = (tools: string[]) => {
    if (!activeSessionId || state.isProcessing) return;
    activeToolsRef.current = tools;
    setActiveTools(tools);
    connect(activeSessionId, tools);
  };
  const optimizeMemory = async () => {
    if (!activeSessionId || state.isProcessing) return;
    setBusy(true);
    try {
      await agentApi.optimizeMemory(activeSessionId);
      await refreshHistory(activeSessionId);
      setContextUsage(null);
    } catch (error) {
      dispatch({
        type: "event",
        event: {
          type: "error",
          message: error instanceof Error ? error.message : "记忆优化失败。",
        },
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <AgentAssistantRuntime
      isRunning={state.isProcessing}
      messages={state.messages}
    >
      <aside aria-label="Agent 面板" className="agent-workspace">
        <header className="agent-header">
          <div>
            <strong>智能助手</strong>
            <span
              className={cn(
                "agent-connection",
                `agent-connection--${state.connection}`,
              )}
            >
              {state.connection === "connected"
                ? "已连接"
                : state.connection === "reconnecting"
                  ? "重连中"
                  : state.connection === "connecting"
                    ? "连接中"
                    : "离线"}
            </span>
          </div>
          <div className="flex gap-1">
            <QuickAction
              onError={(message) =>
                dispatch({ type: "event", event: { type: "error", message } })
              }
            />
            <ToolPicker
              activeTools={activeTools}
              disabled={busy || state.isProcessing}
              onChange={changeTools}
              onError={(message) =>
                dispatch({ type: "event", event: { type: "error", message } })
              }
            />
            <Button
              aria-label="新建 Agent 会话"
              disabled={busy}
              variant="ghost"
              onClick={() => void createSession()}
            >
              <Plus aria-hidden="true" size={18} />
            </Button>
            <Button
              aria-expanded={sessionsOpen}
              aria-label="切换 Agent 会话"
              variant="ghost"
              onClick={() => setSessionsOpen(!sessionsOpen)}
            >
              <MoreHorizontal aria-hidden="true" size={18} />
            </Button>
          </div>
        </header>
        {sessionsOpen ? (
          <section aria-label="Agent 会话列表" className="agent-sessions">
            <p>{currentName}</p>
            {sessions.map((session) => (
              <div key={session.session_id}>
                <button
                  aria-current={
                    session.session_id === activeSessionId ? "page" : undefined
                  }
                  onClick={() => void switchSession(session.session_id)}
                  type="button"
                >
                  {session.name}
                  <small>{session.message_count} 条消息</small>
                </button>
                <Button
                  aria-label={`重命名会话 ${session.name}`}
                  variant="ghost"
                  onClick={() =>
                    setRenameTarget({
                      id: session.session_id,
                      name: session.name,
                    })
                  }
                >
                  <Pencil aria-hidden="true" size={15} />
                </Button>
                <Button
                  aria-label={`删除会话 ${session.name}`}
                  variant="ghost"
                  onClick={() => setDeleteTarget(session.session_id)}
                >
                  <Trash2 aria-hidden="true" size={15} />
                </Button>
              </div>
            ))}
          </section>
        ) : null}
        <details className="agent-session-utility">
          <summary>会话上下文与任务</summary>
          {contextUsage ? (
            <p>
              上下文 {contextUsage.total.toLocaleString()} /{" "}
              {contextUsage.target.toLocaleString()} tokens，剩余{" "}
              {contextUsage.remaining.toLocaleString()}；
              {contextUsage.hasSummary ? "已生成摘要" : "尚无摘要"}
            </p>
          ) : (
            <p>上下文用量暂不可用。</p>
          )}
          <ul>
            {sessionTodos.map((todo) => (
              <li key={todo.id}>
                {todo.title} · {todo.status}
              </li>
            ))}
            {!sessionTodos.length ? <li>当前会话没有 Agent 任务。</li> : null}
          </ul>
          <Button
            disabled={busy || state.isProcessing || !activeSessionId}
            onClick={() => void optimizeMemory()}
            variant="secondary"
          >
            优化当前会话记忆
          </Button>
        </details>
        <section aria-live="polite" className="agent-messages">
          {state.messages.length ? (
            state.messages.map((message) => (
              <article
                className={cn(
                  "agent-message",
                  `agent-message--${message.role}`,
                )}
                key={message.id}
              >
                <div className="agent-message__meta">
                  <span>{messageLabel(message)}</span>
                  {message.canRollback ? (
                    <Button
                      aria-label="回滚到此消息"
                      disabled={busy || state.isProcessing}
                      variant="ghost"
                      onClick={() => setRollbackTarget(message)}
                    >
                      <RotateCcw aria-hidden="true" size={15} />
                    </Button>
                  ) : null}
                </div>
                {message.role === "tool" ? (
                  <details>
                    <summary>{message.toolName ?? "工具"}</summary>
                    <SafeMarkdown
                      content={
                        message.content ||
                        JSON.stringify(message.toolPayload ?? {}, null, 2)
                      }
                    />
                  </details>
                ) : (
                  <>
                    <SafeMarkdown content={message.content} />
                    {message.attachments.length ? (
                      <AttachmentChips
                        attachments={message.attachments}
                        removable={false}
                      />
                    ) : null}
                    {message.reasoning ? (
                      <details>
                        <summary>思考过程</summary>
                        <SafeMarkdown content={message.reasoning} />
                      </details>
                    ) : null}
                  </>
                )}
              </article>
            ))
          ) : (
            <p className="agent-empty">
              选择或新建会话后，即可让 Agent 协助管理日程。
            </p>
          )}
          {state.statusMessage ? (
            <p className="agent-status">
              <LoaderCircle
                aria-hidden="true"
                className={state.isProcessing ? "animate-spin" : ""}
                size={16}
              />
              {state.statusMessage}
            </p>
          ) : null}
          {state.error ? (
            <p className="agent-error">
              <CircleAlert aria-hidden="true" size={16} />
              {state.error}
            </p>
          ) : null}
          <div ref={end} />
        </section>
        <footer className="agent-composer">
          <AttachmentChips
            attachments={selectedAttachments}
            onRemove={(id) =>
              setSelectedAttachments((items) =>
                items.filter((item) => item.id !== id),
              )
            }
          />
          <textarea
            aria-label="发送给 Agent 的消息"
            disabled={state.connection !== "connected" || state.isProcessing}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send();
              }
            }}
            onPaste={(event) => {
              const files = Array.from(event.clipboardData.files);
              if (files.length) {
                event.preventDefault();
                void attachLocalFiles(files);
              }
            }}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              void attachLocalFiles(event.dataTransfer.files);
            }}
            placeholder="描述你想完成的事…"
            value={draft}
          />
          <div className="agent-composer__actions">
            <AttachmentPicker
              disabled={!activeSessionId || state.isProcessing}
              onError={(message) =>
                dispatch({ type: "event", event: { type: "error", message } })
              }
              onSelect={setSelectedAttachments}
              selected={selectedAttachments}
              sessionId={activeSessionId ?? ""}
            />
            {state.isProcessing ? (
              <Button
                aria-label="停止生成"
                onClick={() => transport.current?.send("stop")}
                variant="danger"
              >
                <Square aria-hidden="true" size={16} />
              </Button>
            ) : (
              <Button
                aria-label="发送消息"
                disabled={
                  !draft.trim() || busy || state.connection !== "connected"
                }
                onClick={() => void send()}
                variant="primary"
              >
                <Send aria-hidden="true" size={16} />
              </Button>
            )}
          </div>
        </footer>
        <ConfirmDialog
          confirmLabel="回滚"
          description="将恢复这条消息的文本和附件到输入框，并撤销当前窗口内由它产生的可回滚变更。"
          onConfirm={() => void rollback()}
          onOpenChange={(open) => {
            if (!open) setRollbackTarget(null);
          }}
          open={rollbackTarget !== null}
          title="回滚到此消息？"
        />
        <ConfirmDialog
          confirmLabel="删除会话"
          description="会话将从列表移除；此操作不能恢复历史。"
          onConfirm={() => void deleteSession()}
          onOpenChange={(open) => {
            if (!open) setDeleteTarget(null);
          }}
          open={deleteTarget !== null}
          title="删除 Agent 会话？"
        />
        <TextInputDialog
          confirmLabel="保存名称"
          description="名称只用于当前账号的会话列表，不会改变历史消息。"
          initialValue={renameTarget?.name ?? ""}
          label="会话名称"
          onConfirm={(name) => void renameSession(name)}
          onOpenChange={(open) => {
            if (!open) setRenameTarget(null);
          }}
          open={renameTarget !== null}
          title="重命名 Agent 会话"
        />
      </aside>
    </AgentAssistantRuntime>
  );
}
