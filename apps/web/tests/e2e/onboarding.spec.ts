import { expect, test } from "@playwright/test";
import { newEmail, PASSWORD } from "./helpers";

test("onboarding: create an account, choose a persona, set rates and land in the inbox", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Create an account" }).click();
  await page.getByLabel("Your name").fill("E2E Onboarding");
  await page.getByLabel("Email").fill(newEmail("onboard"));
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page.getByRole("heading", { name: "Set up GigBid" })).toBeVisible();
  await page.getByLabel(/Data analyst/).check();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel(/GigSim/).check();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Lowest rate you accept ($/h)").fill("24");
  await page.getByLabel("Weekly Connects budget").fill("50");
  await page.getByLabel("Search keywords").fill("dashboard");
  await page.getByRole("button", { name: "Start finding jobs" }).click();

  await expect(page).toHaveURL(/\/inbox/);
  await expect(page.getByRole("heading", { name: "Inbox" })).toBeVisible();
  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page.getByLabel("Rate floor ($/h)")).toHaveValue("24");
  // no horizontal page scroll at any viewport
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);
});
