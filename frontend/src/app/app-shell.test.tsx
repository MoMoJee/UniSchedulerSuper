import axe from "axe-core";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "../App";

const bootstrap = {
  mode: "react" as const,
  user: { username: "测试用户" },
  csrfToken: "csrf-token",
  endpoints: { home: "/home/", agentWebSocketPath: "/ws/agent/" },
};

describe("FR-2 app shell", () => {
  it("provides labelled desktop navigation and panel controls", async () => {
    render(<App bootstrap={bootstrap} />);

    expect(
      await screen.findByRole("navigation", { name: "主导航" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("complementary", { name: "Agent 面板" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "打开导航" }),
    ).toBeInTheDocument();
  });

  it("has no serious axe violations in the initial desktop shell", async () => {
    const { container } = render(<App bootstrap={bootstrap} />);
    expect(
      (
        await within(container).findAllByRole("navigation", {
          name: "主导航",
        })
      ).length,
    ).toBeGreaterThan(0);
    const result = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });

    expect(
      result.violations.filter((violation) =>
        ["critical", "serious"].includes(violation.impact ?? ""),
      ),
    ).toEqual([]);
  });
});
