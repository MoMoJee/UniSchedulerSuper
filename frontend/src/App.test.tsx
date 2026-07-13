import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("renders the isolated FR-0 shell without planner data access", () => {
    render(
      <App
        bootstrap={{
          mode: "react",
          user: { username: "测试用户" },
          csrfToken: "csrf-token",
          endpoints: { home: "/home/", agentWebSocketPath: "/ws/agent/" },
        }}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "React 工程基座已就绪" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("你好，测试用户。现有工作台仍保持默认入口。"),
    ).toBeInTheDocument();
    expect(screen.getByText(/不会读取或写入 Planner 数据/)).toBeInTheDocument();
  });
});
