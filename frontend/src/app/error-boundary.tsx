import { Component, type ErrorInfo, type ReactNode } from "react";

import { Button } from "../components/ui/button";

interface ErrorBoundaryState {
  hasError: boolean;
}

export class AppErrorBoundary extends Component<
  { children: ReactNode },
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    if (import.meta.env.DEV) {
      console.error("React application error", error, info);
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="placeholder-page mx-auto mt-12 max-w-xl" role="alert">
          <h1 className="text-xl font-semibold">页面暂时无法加载</h1>
          <p className="mt-2 text-[var(--text-muted)]">
            请刷新页面；不会自动重复提交任何操作。
          </p>
          <Button className="mt-4" onClick={() => window.location.reload()}>
            刷新页面
          </Button>
        </main>
      );
    }
    return this.props.children;
  }
}
