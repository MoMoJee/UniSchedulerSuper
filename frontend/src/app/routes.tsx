import { CircleDashed } from "lucide-react";
import { useId } from "react";
import { createBrowserRouter } from "react-router-dom";

import type { FrontendBootstrap } from "../bootstrap";
import { Badge } from "../components/ui/status";
import { AppShell } from "./app-shell";

function MigrationPlaceholder({
  title,
  phase,
}: {
  title: string;
  phase: string;
}) {
  const titleId = useId();
  return (
    <section aria-labelledby={titleId} className="placeholder-page">
      <Badge>{phase}</Badge>
      <CircleDashed
        aria-hidden="true"
        className="mt-4 text-[var(--accent)]"
        size={34}
      />
      <h1 id={titleId} className="mt-4 text-2xl font-semibold">
        {title}
      </h1>
      <p className="mt-3 max-w-2xl leading-7 text-[var(--text-muted)]">
        此处正在按前端重构验收方案迁移。当前页面不读取、不写入任何业务数据；原生工作台仍是默认入口。
      </p>
    </section>
  );
}

export function createAppRouter(bootstrap: FrontendBootstrap) {
  const pathname = window.location.pathname;
  const basename = pathname.startsWith("/static/react/")
    ? "/static/react"
    : pathname.startsWith("/home/")
      ? "/home"
      : "/";
  return createBrowserRouter(
    [
      {
        element: <AppShell bootstrap={bootstrap} />,
        children: [
          {
            index: true,
            lazy: async () => {
              const { PlannerWorkspace } =
                await import("../features/planner/planner-workspace");
              return {
                Component: () => (
                  <PlannerWorkspace username={bootstrap.user.username} />
                ),
              };
            },
          },
          {
            path: "/todos",
            lazy: async () => {
              const { TodoWorkspace } =
                await import("../features/planner/todo-workspace");
              return {
                Component: () => (
                  <TodoWorkspace username={bootstrap.user.username} />
                ),
              };
            },
          },
          {
            path: "/search",
            element: <MigrationPlaceholder phase="FR-6" title="搜索" />,
          },
          {
            path: "/files",
            element: <MigrationPlaceholder phase="FR-7" title="文件管理" />,
          },
          {
            path: "/settings",
            element: <MigrationPlaceholder phase="FR-6" title="设置" />,
          },
        ],
      },
    ],
    { basename },
  );
}
