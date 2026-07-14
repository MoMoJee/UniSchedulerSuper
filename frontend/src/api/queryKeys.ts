export const plannerKeys = {
  all: ["planner"] as const,
  bootstrap: (username: string) =>
    [...plannerKeys.all, "bootstrap", username] as const,
  calendar: (
    username: string,
    from: string,
    to: string,
    filters: Record<string, string>,
  ) => [...plannerKeys.all, "calendar", username, from, to, filters] as const,
  event: (eventId: string) => [...plannerKeys.all, "event", eventId] as const,
  todo: (todoId: string) => [...plannerKeys.all, "todo", todoId] as const,
  reminder: (reminderId: string) =>
    [...plannerKeys.all, "reminder", reminderId] as const,
  groups: (username: string) =>
    [...plannerKeys.all, "groups", username] as const,
  share: (shareGroupId: string) =>
    [...plannerKeys.all, "share", shareGroupId] as const,
};

export const agentKeys = {
  all: ["agent"] as const,
  sessions: (username: string) =>
    [...agentKeys.all, "sessions", username] as const,
  history: (sessionId: string) =>
    [...agentKeys.all, "history", sessionId] as const,
  rollbackWindow: (sessionId: string) =>
    [...agentKeys.all, "rollback-window", sessionId] as const,
};

export const fileKeys = {
  all: ["files"] as const,
  list: (folderId: number | null) =>
    [...fileKeys.all, "list", folderId] as const,
  detail: (fileId: number) => [...fileKeys.all, "detail", fileId] as const,
};
