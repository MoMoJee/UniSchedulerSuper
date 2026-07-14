import { RouterProvider } from "react-router-dom";

import { AppErrorBoundary } from "./app/error-boundary";
import { createAppRouter } from "./app/routes";
import { AppProviders } from "./app/providers";
import { ThemeController } from "./app/theme-controller";
import type { FrontendBootstrap } from "./bootstrap";

export function App({ bootstrap }: { bootstrap: FrontendBootstrap }) {
  return (
    <AppProviders>
      <ThemeController />
      <AppErrorBoundary>
        <RouterProvider router={createAppRouter(bootstrap)} />
      </AppErrorBoundary>
    </AppProviders>
  );
}
