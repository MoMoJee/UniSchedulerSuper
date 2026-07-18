import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v2/events/occurrences/**", (route) =>
    route.fulfill({
      json: {
        occurrences: [
          {
            id: "event-1",
            entity_type: "event",
            title: "无限重复测试",
            start: "2026-07-14T09:00:00+08:00",
            end: "2026-07-14T10:00:00+08:00",
            occurrence_ref: {
              entity_id: "event-1",
              series_id: "series-1",
              recurrence_id: "20260714T090000",
              source_version: 3,
            },
          },
        ],
        count: 1,
      },
    }),
  );
  await page.route("**/api/v2/events/definitions/**", (route) =>
    route.fulfill({
      json: {
        definitions: [
          {
            event_id: "event-1",
            recurrence: { rrule: "FREQ=WEEKLY;BYDAY=MO" },
          },
        ],
      },
    }),
  );
  await page.route("**/api/v2/reminders/**", (route) =>
    route.fulfill({
      json: {
        occurrences: [
          {
            id: "reminder-1",
            entity_type: "reminder",
            title: "测试提醒",
            start: "2026-07-14T11:00:00+08:00",
            end: null,
            occurrence_ref: { entity_id: "reminder-1", source_version: 2 },
          },
        ],
        count: 1,
      },
    }),
  );
  await page.route("**/api/v2/groups/**", (route) =>
    route.fulfill({
      json: {
        groups: [
          { group_id: "group-1", name: "工作", color: "#1769e0", version: 2 },
        ],
        count: 1,
      },
    }),
  );
});

test("FR-3/FR-4 calendar uses V2 projections without a legacy Planner manager", async ({
  page,
}) => {
  await page.goto("/?date=2026-07-14");

  await expect(page.getByRole("heading", { name: "我的日程" })).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Planner 工作区" }),
  ).toBeVisible();
  await expect(page.locator(".fc").first()).toBeVisible();
  await expect(page.getByText("目标资源已不存在或无法访问。")).toHaveCount(0);
  await expect(page.locator('script[src*="planner-v2-client"]')).toHaveCount(0);
});

test("FR-4A Event creation submits only the V2 endpoint", async ({ page }) => {
  let body: Record<string, unknown> | null = null;
  await page.route("**/api/v2/events/", async (route) => {
    body = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({
      status: 201,
      json: { event: { event_id: "event-created", version: 1 } },
    });
  });
  await page.goto("/?date=2026-07-14");
  await page.getByRole("button", { name: "创建日程" }).first().click();
  await page.getByLabel("标题").fill("E2E 创建日程");
  await page.getByLabel("开始").fill("2026-07-14T09:00");
  await page.getByLabel("结束").fill("2026-07-14T10:00");
  await page.getByRole("button", { name: "保存" }).click();
  await expect.poll(() => body?.title).toBe("E2E 创建日程");
  expect(body).not.toHaveProperty("expected_version");
});

test("FR-4A repeated Event edits send occurrence_ref, version and scope", async ({
  page,
}) => {
  let body: Record<string, unknown> | null = null;
  await page.route("**/api/v2/events/event-1/", async (route) => {
    body = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({ json: { event_id: "event-1", version: 4 } });
  });
  await page.goto("/?date=2026-07-14");
  await page.getByRole("button", { name: "Next month" }).click();
  await page.getByText("无限重复测试").first().click();
  await page.getByRole("button", { name: "编辑日程" }).click();
  await page.getByLabel("标题").fill("范围编辑");
  await page.getByRole("button", { name: "保存" }).click();
  await expect.poll(() => body?.expected_version).toBe(3);
  expect(body).toMatchObject({
    title: "范围编辑",
    scope: "all",
    occurrence_ref: {
      entity_id: "event-1",
      series_id: "series-1",
      recurrence_id: "20260714T090000",
      source_version: 3,
    },
  });
});

test("FR-4B Todo create and real conversion only use V2 contracts", async ({
  page,
}) => {
  const calls: Array<{ method: string; body: Record<string, unknown> }> = [];
  await page.route("**/api/v2/todos/**", async (route) => {
    const method = route.request().method();
    if (method === "GET") {
      await route.fulfill({
        json: {
          todos: [
            {
              todo_id: "todo-1",
              title: "已有待办",
              description: "转换验证",
              status: "pending",
              version: 2,
            },
          ],
        },
      });
      return;
    }
    calls.push({
      method,
      body: route.request().postDataJSON() as Record<string, unknown>,
    });
    await route.fulfill({ json: { todo: { todo_id: "todo-1", version: 3 } } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "创建待办" }).click();
  await page.getByLabel("标题").fill("E2E 待办");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByLabel("待办操作").first().click();
  await page.getByRole("button", { name: "转日程" }).click();
  await expect.poll(() => calls.length).toBe(2);
  expect(calls[0]).toMatchObject({
    method: "POST",
    body: { title: "E2E 待办" },
  });
  expect(calls[1]).toMatchObject({
    method: "POST",
    body: { expected_version: 2, title: "已有待办" },
  });
});

test("FR-4C Reminder creation persists an explicit recurrence rule through V2", async ({
  page,
}) => {
  let body: Record<string, unknown> | null = null;
  await page.unroute("**/api/v2/reminders/**");
  await page.route("**/api/v2/reminders/", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        json: {
          occurrences: [
            {
              id: "reminder-1",
              entity_type: "reminder",
              title: "测试提醒",
              start: "2026-07-14T11:00:00+08:00",
              end: null,
              occurrence_ref: {
                entity_id: "reminder-1",
                source_version: 2,
              },
            },
          ],
          count: 1,
        },
      });
      return;
    }
    body = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({
      status: 201,
      json: { reminder: { reminder_id: "r-2" } },
    });
  });
  await page.goto("/?date=2026-07-14");
  const reminderDialog = page.getByRole("dialog", { name: "创建提醒" }).last();
  await page
    .getByRole("region", { name: "Planner 工作区" })
    .getByRole("button", { name: "创建提醒" })
    .click();
  await reminderDialog.getByLabel("标题").fill("E2E 重复提醒");
  await reminderDialog.getByLabel("触发时间").fill("2026-07-14T11:00");
  await reminderDialog.getByLabel("重复规则").click();
  await page.getByRole("option", { name: "每周", exact: true }).click();
  await expect(reminderDialog.getByLabel("间隔")).toBeVisible();
  await reminderDialog.getByRole("button", { name: "保存" }).click();
  await expect.poll(() => body?.title).toBe("E2E 重复提醒");
  expect(body).toMatchObject({ recurrence: { rrule: "FREQ=WEEKLY" } });
});

test("FR-2 keeps navigation and Agent controls reachable at 320px", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto("/");

  await page.getByRole("button", { name: "打开导航" }).click();
  await expect(page.getByRole("button", { name: "关闭导航" })).toBeVisible();
  await page.getByRole("button", { name: "关闭导航" }).click();

  await page.getByRole("button", { name: "打开 Agent 面板" }).click();
  await expect(page.getByRole("button", { name: "关闭助手" })).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("fr-2-mobile-320.png"),
    fullPage: true,
  });
});

test("FR-2 keeps the compact workspace usable at a tablet breakpoint", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 768, height: 900 });
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "我的日程" })).toBeVisible();
  await page.getByRole("button", { name: "打开 Agent 面板" }).click();
  await expect(
    page.getByRole("complementary", { name: "Agent 面板" }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("fr-2-tablet-768.png"),
    fullPage: true,
  });
});

test("FR-2 restores the persisted dark-theme preference", async ({
  page,
}, testInfo) => {
  await page.addInitScript(() => {
    localStorage.setItem(
      "unischedulersuper-ui",
      JSON.stringify({
        state: {
          theme: "dark",
          panelLayout: { navigation: 22, workspace: 56, agent: 22 },
        },
        version: 0,
      }),
    );
  });
  await page.goto("/");

  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.screenshot({
    path: testInfo.outputPath("fr-2-dark-desktop.png"),
    fullPage: true,
  });
});
