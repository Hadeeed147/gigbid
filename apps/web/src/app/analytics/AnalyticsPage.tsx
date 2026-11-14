import { Empty, ErrorState, Loading } from "../../components/States";
import { api } from "../../lib/api/client";
import { pct } from "../../lib/format";
import { useLoad } from "../../lib/hooks";

/** Reply and hire rate by category, Connects versus outcomes, cost and latency, rejection reasons. */
export function AnalyticsPage() {
  const a = useLoad(() => api.GET("/api/analytics"));
  if (a.loading && !a.data) return <Loading label="Crunching your numbers" />;
  if (a.error || !a.data) return <ErrorState error={a.error} retry={a.reload} />;
  const { by_category, connects, cost_latency, rejection_reasons, funnel } = a.data;
  const c = cost_latency as Record<string, number | null>;
  const k = connects as Record<string, number | null>;
  const maxReason = Math.max(1, ...rejection_reasons.map((r) => Number(r.count)));
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Analytics</h1>
          <p>What your proposals achieved and what they cost to produce.</p>
        </div>
      </div>
      <div className="stats">
        <div className="stat">
          <div className="small muted">Jobs analysed</div>
          <div className="v">{c.jobs_analysed ?? 0}</div>
        </div>
        <div className="stat">
          <div className="small muted">Proposals drafted</div>
          <div className="v">{c.proposals ?? 0}</div>
        </div>
        <div className="stat">
          <div className="small muted">Connects spent</div>
          <div className="v">{k.spent ?? 0}</div>
          <div className="small">{k.connects_per_reply ? `${k.connects_per_reply} per reply` : "No replies yet"}</div>
        </div>
        <div className="stat">
          <div className="small muted">Cost per proposal</div>
          <div className="v">${Number(c.avg_usd_per_proposal ?? 0).toFixed(4)}</div>
          <div className="small">p95 {c.p95_latency_s_per_proposal != null ? `${Number(c.p95_latency_s_per_proposal).toFixed(1)} s` : "–"}</div>
        </div>
      </div>
      <div className="grid2">
        <section className="panel">
          <h2>Reply rate by category</h2>
          {by_category.length === 0 && <p className="muted small">Approve and send a few proposals to see results.</p>}
          {by_category.map((r) => (
            <div className="hbar" key={String(r.category)}>
              <span>{String(r.category)}</span>
              <span className="track" aria-hidden="true">
                <span className="fill" style={{ width: pct(Number(r.reply_rate)), display: "block" }} />
              </span>
              <span>{pct(Number(r.reply_rate))}</span>
            </div>
          ))}
          {by_category.length > 0 && (
            <p className="small muted">Hire rate: {by_category.map((r) => `${r.category} ${pct(Number(r.hire_rate))}`).join("; ")}</p>
          )}
        </section>
        <section className="panel">
          <h2>Why you rejected drafts</h2>
          {rejection_reasons.length === 0 ? (
            <Empty title="No rejections">
              <p className="small">Reasons you give when rejecting a draft appear here.</p>
            </Empty>
          ) : (
            rejection_reasons.map((r) => (
              <div className="hbar" key={String(r.reason)}>
                <span>{String(r.reason)}</span>
                <span className="track" aria-hidden="true">
                  <span className="fill" style={{ width: `${(Number(r.count) / maxReason) * 100}%`, display: "block" }} />
                </span>
                <span>{String(r.count)}</span>
              </div>
            ))
          )}
        </section>
      </div>
      <section className="panel">
        <h2>Where jobs ended up</h2>
        <dl className="facts">
          {Object.entries(funnel).map(([s, n]) => (
            <div key={s} style={{ display: "contents" }}>
              <dt>{s.replace(/_/g, " ")}</dt>
              <dd>{n}</dd>
            </div>
          ))}
        </dl>
      </section>
    </>
  );
}
