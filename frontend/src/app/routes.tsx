import { createBrowserRouter, Navigate } from "react-router-dom";

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
            element: <Navigate replace to="/" />,
          },
          {
            path: "/share",
            element: <Navigate replace to="/?surface=share" />,
          },
          {
            path: "/search",
            element: <Navigate replace to="/?surface=search" />,
          },
          {
            path: "/files",
            element: <Navigate replace to="/?surface=files" />,
          },
          {
            path: "/settings",
            element: <Navigate replace to="/?surface=settings" />,
          },
        ],
      },
    ],
    { basename },
  );
}
