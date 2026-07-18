import { expect, test } from "@playwright/test";

const viewports = [
  { width: 1440, height: 900 },
  { width: 760, height: 900 },
  { width: 390, height: 844 },
];

test.beforeEach(async ({ page }) => {
  await page.route("**/api/share-groups/my-groups/", (route) =>
    route.fulfill({
      json: {
        groups: [
          {
            share_group_id: "share_group_extremely_long_identifier_001",
            share_group_name:
              "非常长的分享组名称，用来验证内容列不会被操作按钮压扁",
            share_group_description:
              "这是一段足够长的描述，必须正常换行，不能逐字竖排，也不能造成横向滚动。",
            role: "owner",
            member_count: 12,
          },
          {
            share_group_id: "share_group_002",
            share_group_name: "测试组",
            role: "member",
            owner_name: "LongOwnerName",
          },
        ],
      },
    }),
  );
  await page.route("**/api/v2/**", (route) => {
    const url = route.request().url();
    if (url.includes("/groups/"))
      return route.fulfill({ json: { groups: [] } });
    if (url.includes("/todos/")) return route.fulfill({ json: { todos: [] } });
    if (url.includes("/reminders/"))
      return route.fulfill({ json: { occurrences: [], reminders: [] } });
    if (url.includes("/events/definitions/"))
      return route.fulfill({ json: { definitions: [] } });
    return route.fulfill({ json: { occurrences: [] } });
  });
  await page.route("**/api/agent/sessions/", (route) =>
    route.fulfill({ json: { sessions: [], current_session_id: null } }),
  );
  await page.route("**/get_calendar/user_settings/", (route) =>
    route.fulfill({
      json: {
        theme: "light",
        calendar_view_default: "dayGridMonth",
        default_event_duration: 60,
      },
    }),
  );
  await page.route("**/api/agent/config/", (route) =>
    route.fulfill({ json: { model: { all_models: {} }, optimization: {} } }),
  );
  await page.route("**/api/agent/skills/", (route) =>
    route.fulfill({ json: { items: [] } }),
  );
  await page.route("**/api/files/**", (route) =>
    route.fulfill({
      json: {
        current_folder: { id: null, name: "根目录", path: "/" },
        breadcrumb: [{ id: null, name: "根目录", path: "/" }],
        folders: [
          {
            id: 1,
            name: "名称特别长但不应该撑破文件管理器的文件夹",
            path: "/long/",
            file_count: 0,
          },
        ],
        files: [],
        quota: {
          used_bytes: 0,
          max_storage_bytes: 100000,
          file_count: 0,
          usage_percent: 0,
        },
      },
    }),
  );
});

for (const viewport of viewports) {
  test(`share cards keep readable grid areas at ${viewport.width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize(viewport);
    await page.goto("/?surface=share");
    const modal = page.locator('[data-ui="centered-modal"]');
    await expect(modal).toBeVisible();
    const cards = modal.locator('[data-ui="share-group-card"]');
    await expect(cards).toHaveCount(2);

    const metrics = await cards.evaluateAll((items) =>
      items.map((card) => {
        const content = card.querySelector<HTMLElement>(
          '[data-ui="share-group-content"]',
        );
        const actions = card.querySelector<HTMLElement>(
          '[data-ui="share-group-actions"]',
        );
        const rect = card.getBoundingClientRect();
        return {
          cardWidth: rect.width,
          contentWidth: content?.getBoundingClientRect().width ?? 0,
          actionsWidth: actions?.getBoundingClientRect().width ?? 0,
          scrollWidth: card.scrollWidth,
          clientWidth: card.clientWidth,
        };
      }),
    );
    for (const item of metrics) {
      expect(item.contentWidth).toBeGreaterThan(160);
      expect(item.actionsWidth).toBeGreaterThan(item.cardWidth * 0.85);
      expect(item.scrollWidth).toBeLessThanOrEqual(item.clientWidth + 1);
    }
    await expect
      .poll(() =>
        page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
      )
      .toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`share-${viewport.width}.png`),
      fullPage: true,
    });
  });
}

test("settings, search and files obey their surface container at 390px", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const surface of ["settings", "search", "files"]) {
    await page.goto(`/?surface=${surface}`);
    await expect(
      page.locator(`[data-ui="${surface}-workspace"]`),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    ).toBe(true);
  }
});

test("desktop home panes align, todo board scrolls, and week titles wrap", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route("**/api/v2/todos/**", (route) =>
    route.fulfill({
      json: {
        todos: Array.from({ length: 14 }, (_, index) => ({
          todo_id: `overflow-todo-${index}`,
          title: `用于验证待办滚动的较长标题 ${index + 1}`,
          description: "待办内容应留在自己的滚动区域内",
          status: "pending",
          version: 1,
          importance: "",
          urgency: "",
        })),
      },
    }),
  );
  await page.route("**/api/v2/events/occurrences/**", (route) =>
    route.fulfill({
      json: {
        occurrences: [
          {
            id: "wrapping-event",
            entity_type: "event",
            title: "这是一条需要在周视图中换行展示的长日程标题",
            start: "2026-07-14T09:00:00+08:00",
            end: "2026-07-14T11:00:00+08:00",
            occurrence_ref: {
              entity_id: "wrapping-event",
              source_version: 1,
            },
          },
        ],
      },
    }),
  );

  await page.goto("/?date=2026-07-14&view=timeGridWeek");
  await expect(
    page.getByRole("region", { name: "Planner 工作区" }),
  ).toBeVisible();
  const paneEdges = () =>
    page
      .locator(".home-sidebar, .planner-workspace, .agent-workspace")
      .evaluateAll((items) =>
        items.map((item) => {
          const rect = item.getBoundingClientRect();
          return { top: rect.top, bottom: rect.bottom };
        }),
      );
  await expect
    .poll(async () => {
      const panes = await paneEdges();
      return (
        Math.max(...panes.map((item) => item.top)) -
        Math.min(...panes.map((item) => item.top))
      );
    })
    .toBeLessThanOrEqual(0.5);
  const panes = await paneEdges();
  expect(
    Math.max(...panes.map((item) => item.bottom)) -
      Math.min(...panes.map((item) => item.bottom)),
  ).toBeLessThanOrEqual(0.5);

  const board = page.locator(".home-sidebar__todo-board");
  await expect(board).toBeVisible();
  const scrollRange = await board.evaluate(
    (item) => item.scrollHeight - item.clientHeight,
  );
  expect(scrollRange).toBeGreaterThan(0);
  await board.hover();
  await page.mouse.wheel(0, 420);
  await expect
    .poll(() => board.evaluate((item) => item.scrollTop))
    .toBeGreaterThan(0);

  const title = page
    .locator(".fc-timegrid-event .planner-event-title")
    .filter({ hasText: "这是一条需要在周视图中换行展示的长日程标题" });
  await expect(title).toHaveCount(1);
  const titleStyle = await title.evaluate((item) => ({
    height: item.getBoundingClientRect().height,
    lineHeight: Number.parseFloat(getComputedStyle(item).lineHeight),
    textOverflow: getComputedStyle(item).textOverflow,
    whiteSpace: getComputedStyle(item).whiteSpace,
  }));
  expect(titleStyle.whiteSpace).toBe("normal");
  expect(titleStyle.textOverflow).toBe("clip");
  expect(titleStyle.height).toBeGreaterThan(titleStyle.lineHeight);
});
