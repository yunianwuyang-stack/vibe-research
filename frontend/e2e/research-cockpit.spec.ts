import { test, expect } from "@playwright/test";

/**
 * P9 journey prep: cockpit first screen + feature route boundaries.
 * Full backend golden path is REQ-P9-01 (later); this asserts shell IA.
 */
test.describe("P9 research cockpit shell", () => {
  test("first screen is research cockpit and routes restore", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("region", { name: "研究驾驶舱" })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByRole("heading", { name: "研究驾驶舱" })).toBeVisible();

    // feature nav includes research map
    const mapNav = page.getByRole("navigation", { name: "功能导航" }).getByRole("button", {
      name: "研究地图",
    });
    await mapNav.click();
    await expect(page).toHaveURL(/\/research-map\/?$/);
    await expect(page.getByRole("heading", { name: "研究地图" }).first()).toBeVisible();

    await page.goto("/evidence");
    await expect(page).toHaveURL(/\/evidence\/?$/);
  });
});
