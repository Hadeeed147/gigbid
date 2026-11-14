// Typed client generated from FastAPI's OpenAPI schema (schema.d.ts is generated: npm run gen:api).
import createClient, { type Middleware } from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type InboxItem = Schemas["InboxItem"];
export type JobDetail = Schemas["JobDetail"];
export type StudioOut = Schemas["StudioOut"];
export type UserOut = Schemas["UserOut"];
export type ApprovalIn = Schemas["ApprovalIn"];

const TOKEN_KEY = "gigbid.session";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode: session lasts for this tab only */
  }
}

function traceId(): string {
  return crypto.randomUUID().replace(/-/g, "");
}

// Every request carries the session and a fresh trace id; the API forwards the
// trace id to the worker, graph, MCP servers and audit log.
const authAndTrace: Middleware = {
  async onRequest({ request }) {
    const t = getToken();
    if (t) request.headers.set("Authorization", `Bearer ${t}`);
    request.headers.set("X-Trace-Id", traceId());
    return request;
  },
  async onResponse({ response }) {
    if (response.status === 401 && !response.url.includes("/auth/login")) {
      setToken(null);
      if (!location.pathname.startsWith("/login")) location.assign("/login");
    }
    return response;
  },
};

export const api = createClient<paths>({ baseUrl: import.meta.env.VITE_API_URL ?? "" });
api.use(authAndTrace);

export function errorText(error: unknown, fallback = "Something went wrong."): string {
  if (!error) return fallback;
  if (typeof error === "string") return error;
  const e = error as { detail?: unknown };
  if (typeof e.detail === "string") return e.detail;
  if (Array.isArray(e.detail)) return e.detail.map((d: { msg?: string }) => d.msg).join("; ");
  return fallback;
}
