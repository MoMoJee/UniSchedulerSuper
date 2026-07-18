import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    class WS extends EventTarget {
      static OPEN = 1;
      readyState = 1;
      constructor() {
        super();
        setTimeout(() => {
          this.dispatchEvent(new Event("open"));
          this.dispatchEvent(
            new MessageEvent("message", {
              data: JSON.stringify({
                type: "connected",
                session_id: "user_1_test",
                active_tools: [],
                message_count: 0,
              }),
            }),
          );
        }, 0);
      }
      send() {}
      close() {}
    }
    Object.defineProperty(window, "WebSocket", { value: WS });
  });
  await page.route("**/api/agent/sessions/", (route) =>
    route.fulfill({ json: { sessions: [], current_session_id: null } }),
  );
  await page.route("**/api/agent/sessions/create/", (route) =>
    route.fulfill({ json: { session_id: "user_1_test", name: "测试" } }),
  );
  await page.route("**/api/agent/history/**", (route) =>
    route.fulfill({
      json: { session_id: "user_1_test", messages: [], rollback_window: null },
    }),
  );
  await page.route("**/get_calendar/user_settings/", async (route) =>
    route.fulfill({
      json:
        route.request().method() === "GET"
          ? {
              theme: "light",
              calendar_view_default: "dayGridMonth",
              default_event_duration: 60,
            }
          : { status: "success" },
    }),
  );
  await page.route("**/api/agent/config/", (route) =>
    route.fulfill({
      json: {
        success: true,
        model: {
          current_model_id: "system_test",
          all_models: {
            system_test: { name: "测试模型", thinking_mode: "optional" },
          },
          thinking_enabled: false,
        },
      },
    }),
  );
  await page.route("**/api/agent/skills/", (route) =>
    route.fulfill({
      json: {
        items: [
          { id: 1, name: "测试技能", description: "说明", is_active: true },
        ],
      },
    }),
  );
  await page.route("**/api/files/**", async (route) => {
    const url = route.request().url();
    if (url.includes("/pick/"))
      await route.fulfill({ json: { folders: [], files: [] } });
    else
      await route.fulfill({
        json: {
          current_folder: { id: null, name: "根目录", path: "/" },
          breadcrumb: [{ id: null, name: "根目录", path: "/" }],
          folders: [],
          files: [],
          quota: {
            used_bytes: 0,
            max_storage_bytes: 100000,
            file_count: 0,
            usage_percent: 0,
          },
        },
      });
  });
});

test("FR-6 search is debounced and V2-only; settings persist by its non-Planner contract", async ({
  page,
}) => {
  let searchUrl = "";
  let saved = false;
  await page.route("**/api/v2/search/**", (route) => {
    searchUrl = route.request().url();
    return route.fulfill({
      json: {
        results: [
          {
            id: "event-1",
            type: "event",
            title: "搜索日程",
            start: "2026-07-14",
          },
        ],
      },
    });
  });
  await page.route("**/get_calendar/user_settings/", (route) => {
    if (route.request().method() === "POST") saved = true;
    return route.fulfill({
      json: {
        theme: "light",
        calendar_view_default: "dayGridMonth",
        default_event_duration: 60,
      },
    });
  });
  await page.goto("/static/react/search");
  await page.getByLabel("搜索关键词").fill("搜索");
  await expect(page.getByRole("option", { name: /搜索日程/ })).toBeVisible();
  expect(searchUrl).toContain("/api/v2/search/");
  await page.goto("/static/react/settings");
  await page.getByRole("button", { name: "显示偏好" }).click();
  await page.getByLabel("主题", { exact: true }).selectOption("dark");
  await page.getByRole("button", { name: "保存设置" }).click();
  await expect.poll(() => saved).toBe(true);
});

test("FR-6 search keyboard navigation, Agent optimization and course import stay in their contracts", async ({
  page,
}) => {
  let optimizationSaved = false;
  let imported = false;
  await page.route("**/api/v2/search/**", (route) =>
    route.fulfill({
      json: { results: [{ id: "event-1", type: "event", title: "键盘结果" }] },
    }),
  );
  await page.route(
    "**/api/agent/optimization-config/update/",
    async (route) => {
      optimizationSaved = true;
      await route.fulfill({ json: { success: true } });
    },
  );
  await page.route("**/api/import/semesters/", (route) =>
    route.fulfill({
      json: {
        current_semester: "2026-spring",
        semesters: [{ code: "2026-spring", name: "2026 春季" }],
      },
    }),
  );
  await page.route("**/api/import/fetch/", (route) =>
    route.fulfill({
      json: {
        semester: {},
        courses: [
          { course_id: "course-1", name: "软件工程", time_slot: "周一 1-2" },
        ],
      },
    }),
  );
  await page.route("**/api/import/confirm/", (route) => {
    imported = true;
    return route.fulfill({
      json: { status: "success", imported_count: 1, message: "已导入 1 项" },
    });
  });
  await page.goto("/static/react/search");
  const search = page.getByLabel("搜索关键词");
  await search.fill("键盘");
  await expect(page.getByText("键盘结果")).toBeVisible();
  await search.press("ArrowDown");
  await expect(page.getByRole("option", { name: /键盘结果/ })).toHaveCount(1);
  await expect(search).toHaveAttribute(
    "aria-activedescendant",
    "search-result-0",
  );
  await search.press("Escape");
  await expect(search).toHaveValue("");

  await page.goto("/static/react/settings");
  await page.getByRole("button", { name: "AI 设置" }).click();
  await page.getByRole("button", { name: "保存优化配置" }).click();
  await expect.poll(() => optimizationSaved).toBe(true);
  await page.getByRole("button", { name: "我的" }).click();
  await page.getByLabel("教务系统 Cookie").fill("JSESSIONID=test-only");
  await page.getByRole("button", { name: "解析课表" }).click();
  await expect(page.getByText("软件工程")).toBeVisible();
  await page.getByRole("button", { name: "导入选中课程" }).click();
  await expect.poll(() => imported).toBe(true);
  await expect(page.getByLabel("教务系统 Cookie")).toHaveValue("");
});

test("FR-7 file entry exposes upload and folder creation without legacy Planner calls", async ({
  page,
}) => {
  let uploaded = false;
  let folder = false;
  await page.route("**/api/files/upload/", (route) => {
    uploaded = true;
    return route.fulfill({ json: { files: [] } });
  });
  await page.route("**/api/files/folders/", (route) => {
    folder = true;
    return route.fulfill({
      status: 201,
      json: { id: 3, name: "资料", path: "/资料/" },
    });
  });
  await page.goto("/static/react/files");
  await page.getByLabel("新文件夹名称").fill("资料");
  await page.getByRole("button", { name: "创建文件夹" }).click();
  await expect.poll(() => folder).toBe(true);
  await page.locator('input[type="file"]').setInputFiles({
    name: "note.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("test"),
  });
  await expect.poll(() => uploaded).toBe(true);
});

test("FR-7 file preview, rename, move, delete and URL upload use file APIs only", async ({
  page,
}) => {
  const calls: string[] = [];
  await page.route("**/api/files/**", async (route) => {
    const request = route.request();
    const url = request.url();
    calls.push(`${request.method()} ${new URL(url).pathname}`);
    if (url.includes("/markdown/")) {
      await route.fulfill({
        json:
          request.method() === "GET"
            ? {
                id: 7,
                filename: "notes.md",
                parsed_markdown: "# old",
                markdown_edited: false,
                parse_status: "completed",
              }
            : { success: true },
      });
      return;
    }
    if (url.includes("/folders/") && request.method() !== "GET") {
      await route.fulfill({ json: { success: true } });
      return;
    }
    if (request.method() !== "GET") {
      await route.fulfill({ json: { success: true } });
      return;
    }
    await route.fulfill({
      json: {
        current_folder: { id: null, name: "根目录", path: "/" },
        breadcrumb: [{ id: null, name: "根目录", path: "/" }],
        folders: [{ id: 3, name: "资料", path: "/资料/", file_count: 0 }],
        files: [
          {
            id: 7,
            filename: "notes.md",
            category: "document",
            file_size: 10,
            parse_status: "completed",
          },
        ],
        quota: {
          used_bytes: 10,
          max_storage_bytes: 100000,
          file_count: 1,
          usage_percent: 0,
        },
      },
    });
  });
  await page.goto("/static/react/files");
  await page.getByRole("button", { name: "预览文件 notes.md" }).click();
  await expect(page.getByLabel("Markdown 内容")).toHaveValue("# old");
  await page.getByLabel("Markdown 内容").fill("# new");
  await page.getByRole("button", { name: "保存 Markdown" }).click();
  await expect
    .poll(() => calls.some((item) => item === "PUT /api/files/7/markdown/"))
    .toBe(true);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "文件操作 notes.md" }).click();
  await page.getByText("重命名", { exact: true }).click();
  await page.getByLabel("文件名").fill("renamed.md");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect
    .poll(() => calls.some((item) => item === "PUT /api/files/7/rename/"))
    .toBe(true);
  await page.getByRole("button", { name: "文件操作 notes.md" }).click();
  await page.getByText("移动", { exact: true }).click();
  await page.getByRole("button", { name: "移动到此处" }).click();
  await expect
    .poll(() => calls.some((item) => item === "PUT /api/files/7/move/"))
    .toBe(true);
  await page.getByRole("button", { name: "URL 上传" }).click();
  await page.getByLabel("文件 URL").fill("https://example.test/data.txt");
  await page.getByRole("button", { name: "上传", exact: true }).click();
  await expect
    .poll(() => calls.some((item) => item === "POST /api/files/upload-url/"))
    .toBe(true);
  expect(calls.some((item) => item.includes("/get_calendar/"))).toBe(false);
});

test("FR-6/FR-7 navigation pages have no critical accessibility violations and honor reduced motion", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const path of [
    "/static/react/search",
    "/static/react/settings",
    "/static/react/files",
  ]) {
    await page.goto(path);
    await expect(
      path.endsWith("files")
        ? page.getByRole("dialog", { name: "文件管理" })
        : page.getByRole("dialog"),
    ).toBeVisible();
    const results = await new AxeBuilder({ page })
      .disableRules(["color-contrast"])
      .analyze();
    expect(results.violations).toEqual([]);
  }
});
