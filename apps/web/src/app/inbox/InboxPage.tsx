import { useState } from "react";
import { Link } from "react-router-dom";
import { ActionChip, FitMeter, RiskBadges } from "../../components/Badges";
import { Empty, ErrorState, Loading } from "../../components/States";
import { api, errorText } from "../../lib/api/client";
import { budgetText, money, statusText } from "../../lib/format";
import { useInterval, useLoad } from "../../lib/hooks";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "approve", label: "Needs approval" },
  { key: "bid", label: "Bid" },
  { key: "watch", label: "Watch" },
  { key: "skip", label: "Skipped" },
] as const;

/** New jobs ranked by fit, with risk, the recommended action, price and Connects cost. */
export function InboxPage() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const query = {
    action: filter === "bid" || filter === "watch" || filter === "skip" ? filter : undefined,
    status: filter === "approve" ? "awaiting_approval" : undefined,
    q: q || undefined,
  };
  const inbox = useLoad(() => api.GET("/api/jobs", { params: { query } }), [filter, q]);
  useInterval(() => void inbox.reload(), 8000);

  const scout = async () => {
    const { error } = await api.POST("/api/jobs/scout");
    setMsg(error ? errorText(error) : "Checking your saved searches now. New jobs appear here as they are analysed.");
  };
  const skip = async (jobId: string) => {
    await api.POST("/api/jobs/{job_id}/skip", { params: { path: { job_id: jobId } } });
    void inbox.reload();
  };

  const items = inbox.data?.items ?? [];
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Inbox</h1>
          <p>Jobs from your saved searches, best fit first. GigBid recommends; you decide.</p>
        </div>
        <button className="btn" onClick={scout}>
          Check for new jobs
        </button>
      </div>
      {msg && <div className="banner info" role="status">{msg}</div>}
      <div className="filters">
        <div className="seg" role="group" aria-label="Filter jobs">
          {FILTERS.map((f) => (
            <button key={f.key} aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>
              {f.label}
            </button>
          ))}
        </div>
        <label className="sr-only" htmlFor="search">
          Search job titles
        </label>
        <input
          id="search"
          type="text"
          placeholder="Search titles"
          style={{ maxWidth: 260 }}
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>
      {inbox.loading && !inbox.data && <Loading label="Loading your inbox" />}
      {inbox.error && !inbox.data && <ErrorState error={inbox.error} retry={inbox.reload} />}
      {inbox.data && items.length === 0 && (
        <Empty title={filter === "all" ? "No jobs yet" : "Nothing here"}>
          <p>
            {filter === "all"
              ? "GigBid checks your saved searches on a schedule. Run a check now, or add searches in Settings."
              : "Try another filter."}
          </p>
          {filter === "all" && (
            <button className="btn primary" onClick={scout}>
              Check for new jobs
            </button>
          )}
        </Empty>
      )}
      {items.length > 0 && (
        <ul className="desk" data-testid="inbox-list">
          {items.map((j) => (
            <li key={j.job_id}>
              <div className={`lead${j.status === "awaiting_approval" ? " awaiting" : ""}`}>
                <div className="c-action">
                  <ActionChip action={j.action} status={j.status} />
                </div>
                <div>
                  <Link
                    className="title"
                    to={j.status === "awaiting_approval" ? `/studio/${j.job_id}` : `/jobs/${j.job_id}`}
                    style={{ color: "inherit" }}
                  >
                    {j.title}
                  </Link>
                  <div className="sub">
                    {j.category ?? "Uncategorised"}, {budgetText(j.budget)}
                    {j.status !== "awaiting_approval" && j.action ? "" : `, ${statusText(j.status)}`}
                  </div>
                  <div className="c-risk">
                    <RiskBadges risk={j.risk} isScam={j.is_scam} flags={j.flags} />
                  </div>
                </div>
                <div className="c-fit">
                  <FitMeter fit={j.fit} />
                </div>
                <div className="price">
                  {j.price ? money((j.price as { amount: number }).amount, (j.price as { unit: string }).unit) : "–"}
                  <div className="sub">{j.connects_cost != null ? `${j.connects_cost} Connects` : ""}</div>
                </div>
                <div className="row-actions">
                  {j.action !== "skip" && j.status !== "submitted" ? (
                    <button className="btn quiet" onClick={() => skip(j.job_id)} aria-label={`Skip ${j.title}`}>
                      Skip
                    </button>
                  ) : (
                    <span className="small muted">{statusText(j.status)}</span>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
