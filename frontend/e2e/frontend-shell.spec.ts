import { expect, test } from "@playwright/test";

test("FR-0 dev shell loads without a legacy Planner manager", async ({
  page,
}) => {
  await page.goto("/");

  await expect(
    page.getByRole("heading", { name: "React 工程基座已就绪" }),
  ).toBeVisible();
  await expect(page.locator("#root")).toContainText("FR-1 将接入类型化 V2 API");
  await expect(page.locator('script[src*="planner-v2-client"]')).toHaveCount(0);
});
