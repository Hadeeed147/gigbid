import type { RunEvent } from "../lib/hooks";

const NODE_TEXT: Record<string, string> = {
  intake: "Scout hand-off",
  analyst: "Job Analyst",
  risk: "Risk Assessor",
  matcher: "Fit Matcher",
  decide: "Bid or skip",
  pricing: "Pricing Strategist",
  writer: "Proposal Writer",
  verifier: "Claim check",
  critic: "Critic",
  compliance: "Compliance Guard",
  preview: "Dry-run preview",
  approval: "Your approval",
  submit: "Submitted to marketplace",
  load_thread: "Read conversation",
  intent: "Classify message",
  slots: "Find interview slots",
  draft_reply: "Draft reply",
  approve_reply: "Your approval",
  send: "Sent",
};
const PARALLEL = new Set(["analyst", "risk", "matcher"]);

/** Live node-by-node progress, streamed from LangGraph over SSE. */
export function RunTimeline({ events, connected }: { events: RunEvent[]; connected?: boolean }) {
  const rows = events.filter((e) => ["node", "interrupt", "degraded", "run_finished", "run_started"].includes(e.event));
  if (rows.length === 0)
    return <p className="muted small">{connected ? "Waiting for the agents to start." : "No run activity yet."}</p>;
  const last = rows[rows.length - 1];
  const traceUrl = [...rows].reverse().find((e) => e.trace_url)?.trace_url;
  return (
    <>
      <ol className="timeline" aria-live="polite">
        {rows.map((e, i) => {
          if (e.event === "run_started")
            return (
              <li key={i}>
                <span className="dot done" aria-hidden="true" />
                <span className="muted small">{e.run_id ? "Run started" : ""}</span>
                <span />
              </li>
            );
          if (e.event === "run_finished")
            return (
              <li key={i}>
                <span className={`dot ${e.status === "error" ? "fail" : "done"}`} aria-hidden="true" />
                <span>
                  <span className="node">{e.status === "error" ? "Run failed" : "Run paused or finished"}</span>
                  {e.error && <div className="error-text small">{e.error}</div>}
                </span>
                <span />
              </li>
            );
          const failed = e.status === "dead_letter" || e.event === "degraded";
          const waiting = e.event === "interrupt";
          return (
            <li key={i}>
              <span className={`dot ${failed ? "fail" : waiting ? "wait" : "done"}`} aria-hidden="true" />
              <span>
                <span className="node">
                  {e.event === "degraded" ? "Marketplace unavailable" : NODE_TEXT[e.node ?? ""] ?? e.node}
                </span>
                {e.node && PARALLEL.has(e.node) && <span className="parallel"> (runs in parallel)</span>}
                {(e.summary || e.message) && <div className="small muted">{e.summary || e.message}</div>}
                {waiting && <div className="small">Waiting for you to approve, edit or reject.</div>}
              </span>
              <span className="meta">
                {e.latency_s != null ? `${e.latency_s.toFixed(1)} s` : ""}
                {e.tokens ? ` · ${e.tokens} tok` : ""}
              </span>
            </li>
          );
        })}
      </ol>
      {traceUrl && (
        <p className="small">
          <a href={traceUrl} target="_blank" rel="noreferrer">
            Open the full trace
          </a>
        </p>
      )}
      {last.event === "node" && <p className="loading small">Working</p>}
    </>
  );
}
