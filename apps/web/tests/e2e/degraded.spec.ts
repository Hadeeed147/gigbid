import { expect, test } from "@playwright/test";
import { onboardedUser, signIn } from "./helpers";

// The real outage path (marketplace MCP server down -> work queued -> resumed from the
// checkpoint) is covered by the Python tests; here we check what the user sees when the
// health endpoint reports the marketplace as unreachable, and when the API itself is down.
test("degraded mode: banner appears when the marketplace is unavailable", async ({ page, request }) => {
  const u = await onboardedUser(request, "degraded");
  await page.route("**/api/health", (route) =>
    route.fulfill({
      json: { api: true, marketplace: { up: false, reason: "marketplace_unavailable: GigSim unreachable" }, mode: "gigsim", profile: "open" },
    }),
  );
  await signIn(page, u.email);
  await page.goto("/settings");
  const banner = page.getByTestId("degraded-banner");
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("Marketplace unavailable");
  await expect(banner).toContainText("queued");
});

test("degraded mode: banner appears when the API is unreachable", async ({ page, request }) => {
  const u = await onboardedUser(request, "apidown");
  await signIn(page, u.email);
  await page.route("**/api/health", (route) => route.abort("connectionrefused"));
  await page.reload();
  await expect(page.getByTestId("degraded-banner")).toContainText("unreachable", { timeout: 30_000 });
});
