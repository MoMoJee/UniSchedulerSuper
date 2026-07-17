import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("renders the FR-4 shell and starts its V2 projection", async () => {
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

    expect(await screen.findByText("UniSchedulerSuper")).toBeInTheDocument();
    expect(
      (await screen.findAllByRole("heading", { name: "我的日程" })).length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText("日程工作区").length).toBeGreaterThan(0);
  });
});
