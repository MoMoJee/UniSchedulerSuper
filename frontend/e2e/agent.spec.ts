import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    type Frame = Record<string, unknown>;
    class FakeWebSocket extends EventTarget {
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSING = 2;
      static readonly CLOSED = 3;
      readonly CONNECTING = FakeWebSocket.CONNECTING;
      readonly OPEN = FakeWebSocket.OPEN;
      readonly CLOSING = FakeWebSocket.CLOSING;
      readonly CLOSED = FakeWebSocket.CLOSED;
      readyState = FakeWebSocket.CONNECTING;
      constructor(url: string) {
        super();
        (window as Window & { __agentWsUrls?: string[] }).__agentWsUrls ??= [];
        (window as Window & { __agentWsUrls: string[] }).__agentWsUrls.push(
          url,
        );
        window.setTimeout(() => {
          this.readyState = FakeWebSocket.OPEN;
          this.dispatchEvent(new Event("open"));
          this.frame({
            type: "connected",
            session_id: "user_1_test",
            active_tools: ["calendar"],
            message_count: 4,
          });
        }, 0);
      }
      send(raw: string) {
        const data = JSON.parse(raw) as Frame;
        (window as Window & { __agentWsSent?: Frame[] }).__agentWsSent ??= [];
        (window as Window & { __agentWsSent: Frame[] }).__agentWsSent.push(
          data,
        );
        if (data.type === "check_status")
          this.frame({
            type: "status_response",
            is_processing: false,
            should_sync_immediately: false,
          });
        if (data.type === "message") {
          const frames: Frame[] = [
            { type: "processing", message: "正在思考…" },
            { type: "stream_start" },
            { type: "stream_chunk", content: "已收到结构化附件。" },
            { type: "tool_call", name: "search_items", args: { q: "测试" } },
            {
              type: "tool_result",
              name: "search_items",
              result: "查询完成",
              refresh: ["events"],
            },
            { type: "stream_end" },
            { type: "finished" },
          ];
          frames.forEach((frame, index) =>
            window.setTimeout(() => this.frame(frame), 20 * (index + 1)),
          );
        }
      }
      close() {
        this.readyState = FakeWebSocket.CLOSED;
        this.dispatchEvent(new CloseEvent("close"));
      }
      frame(data: Frame) {
        this.dispatchEvent(
          new MessageEvent("message", { data: JSON.stringify(data) }),
        );
      }
    }
    Object.defineProperty(window, "WebSocket", {
      configurable: true,
      value: FakeWebSocket,
    });
  });
  await page.route("**/api/agent/sessions/", async (route) => {
    if (route.request().method() === "GET")
      await route.fulfill({
        json: {
          sessions: [
            {
              session_id: "user_1_test",
              name: "FR5 会话",
              message_count: 2,
              updated_at: "2026-07-14T00:00:00+08:00",
            },
          ],
          current_session_id: "user_1_test",
        },
      });
    else await route.fulfill({ json: { status: "deleted" } });
  });
  await page.route("**/api/agent/history/**", (route) =>
    route.fulfill({
      json: {
        session_id: "user_1_test",
        rollback_window: { status: "active", floor_message_index: 0 },
        messages: [
          {
            role: "user",
            id: "m-3",
            index: 3,
            content: "请检查这个日程附件",
            can_rollback: true,
            attachments: [
              {
                id: 12,
                type: "event",
                filename: "答辩",
                internal_id: "event-12",
                parse_status: "completed",
              },
            ],
          },
          { role: "assistant", id: "m-4", index: 4, content: "已读取。" },
        ],
      },
    }),
  );
  await page.route("**/api/agent/attachments/**", async (route) => {
    const url = route.request().url();
    const method = route.request().method();
    if (method === "GET" && url.includes("/attachments/?")) {
      await route.fulfill({
        json: {
          types: ["event"],
          items: [
            {
              type: "event",
              id: "event-12",
              title: "答辩",
              subtitle: "明天 09:00",
            },
          ],
        },
      });
      return;
    }
    if (method === "POST" && url.includes("/internal/")) {
      await route.fulfill({
        json: {
          success: true,
          attachment: {
            id: 12,
            type: "event",
            filename: "答辩",
            internal_id: "event-12",
            parse_status: "completed",
          },
        },
      });
      return;
    }
    if (method === "POST" && url.includes("/from-cloud/")) {
      await route.fulfill({
        json: {
          attachments: [
            {
              id: 22,
              type: "file",
              filename: "资料.md",
              parse_status: "completed",
            },
          ],
        },
      });
      return;
    }
    if (method === "POST" && url.includes("/upload/")) {
      await route.fulfill({
        json: {
          attachment: {
            id: 23,
            type: "file",
            filename: "本地.txt",
            parse_status: "completed",
          },
        },
      });
      return;
    }
    if (method === "GET" && url.includes("/12/preview/")) {
      await route.fulfill({
        json: { id: 12, type: "markdown", content_preview: "答辩" },
      });
      return;
    }
    await route.fulfill({ json: { attachments: [] } });
  });
  await page.route("**/api/agent/tools/", (route) =>
    route.fulfill({
      json: {
        categories: [
          {
            id: "planner",
            display_name: "日程管理",
            description: "读取与更新日程",
            tools: [
              { name: "search_items", display_name: "统一搜索", enabled: true },
              { name: "create_item", display_name: "创建项目", enabled: true },
            ],
          },
        ],
        default_tools: ["search_items", "create_item"],
      },
    }),
  );
  await page.route("**/api/files/pick/**", (route) =>
    route.fulfill({
      json: {
        folders: [{ id: 8, name: "测试文件夹" }],
        files: [
          {
            id: 9,
            filename: "资料.md",
            category: "document",
            parse_status: "completed",
          },
        ],
      },
    }),
  );
  await page.route("**/api/agent/rollback/to-message/", (route) =>
    route.fulfill({ json: { status: "rolled_back" } }),
  );
  await page.route("**/api/agent/quick-action/**", async (route) => {
    if (route.request().method() === "POST")
      await route.fulfill({
        status: 201,
        json: {
          task_id: "task-1",
          status: "pending",
          input_text: "创建测试待办",
        },
      });
    else
      await route.fulfill({
        json: {
          task_id: "task-1",
          status: "success",
          input_text: "创建测试待办",
          result: { message: "快捷操作完成" },
        },
      });
  });
});

test("FR-5 Agent sends an internal Event attachment by server attachment id and renders stream/tool frames", async ({
  page,
}) => {
  const legacyPlannerRequests: string[] = [];
  page.on("request", (request) => {
    if (/\/events\/create_event\/|\/get_calendar\/events\//.test(request.url()))
      legacyPlannerRequests.push(request.url());
  });
  await page.goto("/");
  await expect(page.getByText("已连接")).toBeVisible();
  await page.getByRole("button", { name: "添加附件" }).click();
  await page.locator(".agent-picker-results button").first().click();
  await expect(
    page.locator(".agent-composer").getByText("日程 · 答辩"),
  ).toBeVisible();
  await page.getByLabel("发送给 Agent 的消息").fill("请读取附件");
  await page.getByRole("button", { name: "发送消息" }).click();
  await expect
    .poll(() =>
      page.evaluate(() =>
        (
          window as Window & { __agentWsSent?: Array<Record<string, unknown>> }
        ).__agentWsSent?.find((frame) => frame.type === "message"),
      ),
    )
    .toMatchObject({ content: "请读取附件", attachment_ids: [12] });
  await expect(page.getByText("已收到结构化附件。")).toBeVisible();
  await expect(page.getByText("search_items").first()).toBeVisible();
  expect(legacyPlannerRequests).toEqual([]);
});

test("FR-5 rollback restores the current-message attachment reference and Quick Action polls through its API", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "回滚到此消息" }).click();
  await page.getByRole("button", { name: "回滚", exact: true }).click();
  await expect(page.getByLabel("发送给 Agent 的消息")).toHaveValue(
    "请检查这个日程附件",
  );
  await expect(
    page.locator(".agent-composer").getByText("日程 · 答辩"),
  ).toBeVisible();
  await page.getByRole("button", { name: "发送消息" }).click();
  await expect
    .poll(() =>
      page.evaluate(() =>
        (
          window as Window & { __agentWsSent?: Array<Record<string, unknown>> }
        ).__agentWsSent
          ?.filter((frame) => frame.type === "message")
          .at(-1),
      ),
    )
    .toMatchObject({ attachment_ids: [12] });
  await page.getByRole("button", { name: "打开 Quick Action" }).click();
  await page.getByLabel("快捷指令").fill("创建测试待办");
  await page.getByRole("button", { name: "执行" }).click();
  await expect(page.getByText("快捷操作完成")).toBeVisible();
});

test("FR-5 preserves all Agent session, tool-selection, cloud and local attachment controls", async ({
  page,
}) => {
  let renamed = "";
  await page.route(
    "**/api/agent/sessions/user_1_test/rename/",
    async (route) => {
      renamed = String((await route.request().postDataJSON()).name);
      await route.fulfill({
        json: { session_id: "user_1_test", name: renamed },
      });
    },
  );
  await page.goto("/");
  await page.getByRole("button", { name: "切换 Agent 会话" }).click();
  await expect(page.getByRole("button", { name: "移除附件 答辩" })).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "重命名会话 FR5 会话" }).click();
  await page.getByLabel("会话名称").fill("已重命名会话");
  await page.getByRole("button", { name: "保存名称" }).click();
  await expect.poll(() => renamed).toBe("已重命名会话");

  await page.getByRole("button", { name: "选择 Agent 工具" }).click();
  await page.getByLabel("创建项目").uncheck();
  await page.getByRole("button", { name: "完成" }).click();
  await expect
    .poll(() =>
      page.evaluate(() =>
        (window as Window & { __agentWsUrls?: string[] }).__agentWsUrls?.at(-1),
      ),
    )
    .toContain("active_tools=search_items");

  await page.getByRole("button", { name: "添加附件" }).click();
  await page.getByRole("button", { name: "我的文件" }).click();
  await page.getByRole("button", { name: "打开云盘文件选择器" }).click();
  await page.getByLabel("搜索云盘文件").waitFor();
  await page.getByText("资料.md").click();
  await page.getByRole("button", { name: "选择文件" }).click();
  await expect(
    page.locator(".agent-composer").getByText("文件 · 资料.md"),
  ).toBeVisible();

  await page.getByRole("button", { name: "添加附件" }).click();
  await page.getByRole("button", { name: "上传" }).click();
  await page.getByLabel("上传本地附件").setInputFiles({
    name: "本地.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("local"),
  });
  await expect(
    page.locator(".agent-composer").getByText("文件 · 本地.txt"),
  ).toBeVisible();
});

test("FR-5 Agent sidebar is keyboard-accessible with no critical Axe violations", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(
    page.getByRole("complementary", { name: "Agent 面板" }),
  ).toBeVisible();
  const results = await new AxeBuilder({ page })
    .disableRules(["color-contrast"])
    .analyze();
  expect(results.violations).toEqual([]);
  await page.getByRole("button", { name: "添加附件" }).focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { name: "添加 Agent 附件" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
});
