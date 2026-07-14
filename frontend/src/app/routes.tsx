import { createBrowserRouter } from "react-router-dom";

import type { FrontendBootstrap } from "../bootstrap";
import { AppShell } from "./app-shell";

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
            lazy: async () => {
              const { SearchWorkspace } =
                await import("../features/search/search-workspace");
              return { Component: SearchWorkspace };
            },
          },
          {
            path: "/files",
            lazy: async () => {
              const { FilesWorkspace } =
                await import("../features/files/files-workspace");
              return { Component: FilesWorkspace };
            },
          },
          {
            path: "/settings",
            lazy: async () => {
              const { SettingsWorkspace } =
                await import("../features/settings/settings-workspace");
              return { Component: SettingsWorkspace };
            },
          },
        ],
      },
    ],
    { basename },
  );
}
