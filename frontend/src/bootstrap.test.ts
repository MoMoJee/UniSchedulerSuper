import { describe, expect, it } from "vitest";

import { readFrontendBootstrap } from "./bootstrap";

describe("readFrontendBootstrap", () => {
  it("accepts the server JSON contract", () => {
    document.body.innerHTML = `
      <script id="frontend-bootstrap" type="application/json">
        {"mode":"react","user":{"username":"测试用户"},"csrfToken":"csrf","endpoints":{"home":"/home/","agentWebSocketPath":"/ws/agent/"}}
      </script>
    `;

    expect(readFrontendBootstrap()).toMatchObject({
      user: { username: "测试用户" },
      endpoints: { agentWebSocketPath: "/ws/agent/" },
    });
  });

  it("fails closed when the contract is missing required fields", () => {
    document.body.innerHTML =
      '<script id="frontend-bootstrap" type="application/json">{}</script>';

    expect(() => readFrontendBootstrap()).toThrow(
      "前端启动配置不完整或版本不兼容。",
    );
  });
});
