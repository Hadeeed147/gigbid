export function money(n?: number | null, unit?: string | null): string {
  if (n == null) return "–";
  const s = `$${Math.round(n).toLocaleString()}`;
  return unit === "hourly" ? `${s}/h` : s;
}

export function budgetText(b?: Record<string, unknown> | null): string {
  if (!b) return "Budget not stated";
  if (b.type === "hourly") return `$${b.min ?? "?"}–${b.max ?? "?"}/h`;
  const hours = b.estimated_hours ? `, about ${b.estimated_hours}h` : "";
  return `$${Number(b.amount ?? 0).toLocaleString()} fixed${hours}`;
}

export function pct(n?: number | null): string {
  return n == null ? "–" : `${Math.round(n * 100)}%`;
}

export function ago(iso?: string | null): string {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

export const STATUS_TEXT: Record<string, string> = {
  queued: "Queued",
  analysing: "Analysing",
  pricing: "Pricing",
  verifying: "Checking claims",
  critiquing: "In review",
  critiqued: "In review",
  awaiting_approval: "Needs your approval",
  resuming: "Working on your decision",
  recheck: "Re-checking your edit",
  approved: "Approved",
  submitted: "Submitted",
  skipped: "Skipped",
  watch: "Watching",
  rejected: "Rejected by you",
  blocked: "Blocked by compliance",
  needs_attention: "Needs attention",
  dead_letter: "Failed",
  degraded: "Waiting for marketplace",
};

export function statusText(s?: string | null): string {
  return (s && STATUS_TEXT[s]) || s || "–";
}
