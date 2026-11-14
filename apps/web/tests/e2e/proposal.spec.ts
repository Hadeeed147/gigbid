import { expect, test } from "@playwright/test";
import { API, signIn, userWithPendingProposal } from "./helpers";

test("approve a proposal: evidence on hover, dry-run preview, submitted exactly once", async ({ page, request }) => {
  const u = await userWithPendingProposal(request, "approve");
  await signIn(page, u.email);
  await page.goto(`/studio/${u.jobId}`);

  const claim = page.locator("mark.claim").first();
  await expect(claim).toBeVisible();
  await claim.hover();
  await expect(page.getByTestId("evidence-card").first()).toBeVisible();

  await page.getByRole("button", { name: "Review and send" }).click();
  await expect(page.getByTestId("dry-run-preview")).toBeVisible();
  await expect(page.getByTestId("dry-run-preview")).not.toContainText("[ai_ml:"); // evidence tags never reach the client
  await page.getByRole("button", { name: "Approve and submit" }).click();
  await expect(page.getByText(/^Submitted/)).toBeVisible({ timeout: 90_000 });

  const pipe = await (await request.get(`${API}/api/pipeline`, { headers: { Authorization: `Bearer ${u.token}` } })).json();
  expect(pipe.filter((c: { job_id: string; stage: string }) => c.job_id === u.jobId && c.stage !== "drafted")).toHaveLength(1);
});

test("reject with a reason: the reason is required and recorded", async ({ page, request }) => {
  const u = await userWithPendingProposal(request, "reject");
  await signIn(page, u.email);
  await page.goto(`/studio/${u.jobId}`);
  await page.getByRole("button", { name: "Reject" }).click();
  const confirm = page.getByRole("button", { name: "Reject proposal" });
  await expect(confirm).toBeDisabled();
  await page.getByLabel(/Why\?/).fill("Too generic for this client");
  await confirm.click();
  await expect(page.getByText(/Rejected by you/)).toBeVisible({ timeout: 90_000 });

  const a = await (await request.get(`${API}/api/analytics`, { headers: { Authorization: `Bearer ${u.token}` } })).json();
  expect(a.rejection_reasons.map((r: { reason: string }) => r.reason)).toContain("Too generic for this client");
});

test("edit a draft: compliance re-checks the edit and strips contact details", async ({ page, request }) => {
  const u = await userWithPendingProposal(request, "edit");
  await signIn(page, u.email);
  await page.goto(`/studio/${u.jobId}`);
  await page.getByRole("button", { name: "Edit" }).click();
  const editor = page.getByLabel("Cover letter");
  const original = await editor.inputValue();
  await editor.fill(`${original}\n\nYou can also reach me at me@example.com for a faster reply.`);
  await page.getByRole("button", { name: "Save edit and re-check" }).click();

  // the graph re-runs Compliance and comes back to approval with the violation removed
  await expect(page.getByRole("button", { name: "Review and send" })).toBeVisible({ timeout: 90_000 });
  await expect(page.getByTestId("letter")).not.toContainText("me@example.com");
  await expect(page.getByText(/Removed \(no off platform contact\)/)).toBeVisible();
});
