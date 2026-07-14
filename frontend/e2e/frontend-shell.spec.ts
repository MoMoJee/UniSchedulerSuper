import { expect, test } from "@playwright/test";

test("FR-2 dev shell loads without a legacy Planner manager", async ({
  page,
}) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "日程工作区" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible();
  await expect(page.locator("#root")).toContainText(
    "当前页面不读取、不写入任何业务数据",
  );
  await expect(page.locator('script[src*="planner-v2-client"]')).toHaveCount(0);
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

  await expect(page.getByRole("heading", { name: "日程工作区" })).toBeVisible();
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
