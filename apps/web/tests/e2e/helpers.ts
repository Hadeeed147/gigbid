import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const API = process.env.E2E_API_URL ?? "http://localhost:8000";

export function newEmail(tag: string) {
  return `e2e-${tag}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@e2e.gigbid.dev`;
}
export const PASSWORD = "e2e-password-123";

export async function register(request: APIRequestContext, tag: string) {
  const email = newEmail(tag);
  const r = await request.post(`${API}/api/auth/register`, { data: { email, password: PASSWORD, name: `E2E ${tag}` } });
  expect(r.ok()).toBeTruthy();
  const body = await r.json();
  return { email, token: body.token as string };
}

/** Register and onboard through the API (AI/ML persona, one saved search). */
export async function onboardedUser(request: APIRequestContext, tag: string) {
  const u = await register(request, tag);
  const ob = await request.post(`${API}/api/auth/onboarding`, {
    headers: { Authorization: `Bearer ${u.token}` },
    data: { profile: "ai_ml", marketplace: "gigsim", rate_floor: 35, hourly_rate: 45, weekly_connects_budget: 60,
            searches: [{ query: "", category: "AI & Machine Learning", interval_minutes: 10 }] },
  });
  expect(ob.ok()).toBeTruthy();
  return u;
}

/** Onboard through the API with the AI/ML persona and wait until a proposal awaits approval. */
export async function userWithPendingProposal(request: APIRequestContext, tag: string) {
  const u = await register(request, tag);
  const h = { Authorization: `Bearer ${u.token}` };
  const ob = await request.post(`${API}/api/auth/onboarding`, {
    headers: h,
    data: { profile: "ai_ml", marketplace: "gigsim", rate_floor: 35, hourly_rate: 45, weekly_connects_budget: 60,
            searches: [{ query: "", category: "AI & Machine Learning", interval_minutes: 10 }] },
  });
  expect(ob.ok()).toBeTruthy();
  let jobId: string | undefined;
  await expect
    .poll(
      async () => {
        const p = await (await request.get(`${API}/api/approvals/pending`, { headers: h })).json();
        jobId = p.proposals?.[0]?.job_id;
        return Boolean(jobId);
      },
      { timeout: 200_000, intervals: [3000] },
    )
    .toBe(true);
  return { ...u, jobId: jobId! };
}

export async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  // wait until the session is stored and the app has navigated away from /login
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
}
