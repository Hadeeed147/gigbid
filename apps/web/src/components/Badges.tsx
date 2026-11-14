import { pct } from "../lib/format";

export function FitMeter({ fit }: { fit?: number | null }) {
  if (fit == null) return <span className="muted small">Fit pending</span>;
  const cls = fit >= 0.55 ? "" : fit >= 0.4 ? "mid" : "low";
  return (
    <div className="meter" aria-label={`Fit ${pct(fit)}`}>
      <span className="val">Fit {pct(fit)}</span>
      <div className="bar">
        <div className={`fill ${cls}`} style={{ width: `${Math.round(fit * 100)}%` }} />
      </div>
    </div>
  );
}

const ACTION_TEXT: Record<string, string> = { bid: "Bid", watch: "Watch", skip: "Skip" };

export function ActionChip({ action, status }: { action?: string | null; status?: string }) {
  if (status === "awaiting_approval") return <span className="chip approve">Approve</span>;
  if (!action) return <span className="chip pending">Analysing</span>;
  return <span className={`chip ${action}`}>{ACTION_TEXT[action] ?? action}</span>;
}

const FLAG_TEXT: Record<string, string> = {
  off_platform_contact: "Off-platform contact",
  off_platform_payment: "Off-platform payment",
  free_work: "Free work request",
  pay_to_work: "Pay to work",
  unverified_payment: "Payment unverified",
  no_history: "No hiring history",
  prompt_injection: "Injected instructions",
  vague_scope: "Vague scope",
};

export function RiskBadges({ risk, isScam, flags }: { risk?: number | null; isScam?: boolean; flags?: string[] }) {
  const shown = (flags ?? []).filter((f) => FLAG_TEXT[f]).slice(0, 3);
  return (
    <div>
      {isScam && <span className="badge danger">Likely scam</span>}
      {!isScam && risk != null && risk >= 0.5 && <span className="badge danger">Risk {pct(risk)}</span>}
      {shown.map((f) => (
        <span key={f} className={`badge ${f === "prompt_injection" || isScam ? "danger" : ""}`}>
          {FLAG_TEXT[f]}
        </span>
      ))}
      {!isScam && (risk ?? 0) < 0.5 && shown.length === 0 && risk != null && <span className="muted small">Low risk</span>}
    </div>
  );
}
