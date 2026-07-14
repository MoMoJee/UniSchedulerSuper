import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("renders the FR-2 app shell without planner data access", () => {
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

    expect(screen.getByText("UniSchedulerSuper")).toBeInTheDocument();
    expect(
      screen.getAllByRole("heading", { name: "日程工作区" }).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText(/当前页面不读取、不写入任何业务数据/).length,
    ).toBeGreaterThan(0);
  });
});
