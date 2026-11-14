import { Link } from "react-router-dom";
import { ErrorState, Loading } from "../../components/States";
import { api } from "../../lib/api/client";
import { ago } from "../../lib/format";
import { useInterval, useLoad } from "../../lib/hooks";

const STAGES = [
  { key: "drafted", label: "Drafted" },
  { key: "submitted", label: "Submitted" },
  { key: "viewed", label: "Viewed" },
  { key: "replied", label: "Replied" },
  { key: "interview", label: "Interview" },
  { key: "hired", label: "Hired" },
  { key: "lost", label: "Lost" },
];

/** Kanban of every proposal; cards move as marketplace events arrive. */
export function PipelinePage() {
  const board = useLoad(() => api.GET("/api/pipeline"));
  useInterval(() => void board.reload(), 10000);
  const sync = async () => {
    await api.POST("/api/pipeline/sync");
    setTimeout(() => void board.reload(), 2500);
  };
  const cards = board.data ?? [];
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Pipeline</h1>
          <p>Every proposal you approved, updated from marketplace events.</p>
        </div>
        <button className="btn" onClick={sync}>
          Refresh from marketplace
        </button>
      </div>
      {board.loading && !board.data && <Loading label="Loading the pipeline" />}
      {board.error && !board.data && <ErrorState error={board.error} retry={board.reload} />}
      {board.data && (
        <div className="board" data-testid="pipeline">
          {STAGES.map((s) => {
            const col = cards.filter((c) => c.stage === s.key);
            return (
              <section className="col" key={s.key} aria-label={s.label}>
                <h2>
                  {s.label} <span className="muted">{col.length}</span>
                </h2>
                {col.length === 0 && <p className="small muted">None</p>}
                {col.map((c) => (
                  <Link
                    key={c.proposal_id}
                    className="card"
                    to={c.thread_id && ["replied", "interview", "hired"].includes(c.stage) ? `/messages/${c.thread_id}` : `/studio/${c.job_id}`}
                  >
                    <strong>{c.title}</strong>
                    <div className="small muted">
                      {c.category}
                      {c.connects_spent ? `, ${c.connects_spent} Connects` : ""}, {ago(c.updated_at)}
                    </div>
                  </Link>
                ))}
              </section>
            );
          })}
        </div>
      )}
    </>
  );
}
