import type { FrontendBootstrap } from "./bootstrap";

interface AppProps {
  bootstrap: FrontendBootstrap;
}

export function App({ bootstrap }: AppProps) {
  return (
    <div className="frontend-shell">
      <header className="frontend-shell__header">
        <span className="frontend-shell__eyebrow">UniSchedulerSuper</span>
        <h1>React 工程基座已就绪</h1>
      </header>
      <main className="frontend-shell__content">
        <p>你好，{bootstrap.user.username}。现有工作台仍保持默认入口。</p>
        <p className="frontend-shell__hint">
          FR-1 将接入类型化 V2 API；当前页面不会读取或写入 Planner 数据。
        </p>
      </main>
    </div>
  );
}
