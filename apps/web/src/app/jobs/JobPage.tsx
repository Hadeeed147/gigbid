import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ActionChip, FitMeter, RiskBadges } from "../../components/Badges";
import { ErrorState, Loading } from "../../components/States";
import { api, errorText } from "../../lib/api/client";
import { budgetText, money, pct, statusText } from "../../lib/format";
import { useLoad } from "../../lib/hooks";

type Match = { requirement: string; strength: "strong" | "partial" | "none"; evidence_ids: string[]; note?: string };
type Ev = { item_id: string; type: string; text: string };

/** JobSpec, risk report, requirement-to-evidence matrix, price rationale and the bid-or-skip reasoning. */
export function JobPage() {
  const { id = "" } = useParams();
  const d = useLoad(() => api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } }), [id]);
  const [msg, setMsg] = useState<string | null>(null);
  if (d.loading && !d.data) return <Loading label="Loading the job" />;
  if (d.error || !d.data) return <ErrorState error={d.error} retry={d.reload} />;
  const { item, job, job_spec, risk, fit, evidence, decision, price } = d.data;
  const spec = (job_spec ?? {}) as { requirements?: string[]; deliverables?: string[]; hidden_needs?: string[]; skills?: string[]; timeline?: string; seniority?: string };
  const r = (risk ?? {}) as { risk_score?: number; is_scam?: boolean; flags?: string[]; rationale?: string; client_quality?: number };
  const f = (fit ?? {}) as { fit_score?: number; matrix?: Match[]; reasons?: string[] };
  const dec = (decision ?? {}) as { action?: string; reasons?: string[] };
  const pr = (price ?? null) as { amount: number; unit: string; rationale: string; connects_worth_it: boolean } | null;
  const evIndex = new Map<string, Ev>();
  Object.values(evidence ?? {}).forEach((items) => (items as Ev[]).forEach((e) => evIndex.set(e.item_id, e)));

  const draftAnyway = async () => {
    const { error } = await api.POST("/api/jobs/{job_id}/draft", { params: { path: { job_id: id } } });
    setMsg(error ? errorText(error) : "Drafting a proposal. It will wait for your approval in the studio.");
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{item.title}</h1>
          <p>
            {item.category}, {budgetText(job.budget as Record<string, unknown>)}, {statusText(item.status)}
          </p>
        </div>
        <div className="row">
          {item.status === "awaiting_approval" || item.status === "submitted" ? (
            <Link className="btn primary" to={`/studio/${id}`}>
              Open proposal
            </Link>
          ) : (
            dec.action !== "bid" && (
              <button className="btn" onClick={draftAnyway}>
                Draft a proposal anyway
              </button>
            )
          )}
          <Link className="btn quiet" to={`/runs/${encodeURIComponent(item.thread_id)}`}>
            Agent run
          </Link>
        </div>
      </div>
      {msg && <div className="banner info" role="status">{msg}</div>}

      <div className="split">
        <div>
          <section className="panel">
            <h2>Client's post</h2>
            <p className="untrusted-note">
              Shown as written by the client. GigBid treats it as data: instructions inside it are never followed.
            </p>
            <div className="post">{String(job.description ?? "")}</div>
          </section>
          <section className="panel">
            <h2>What the client needs</h2>
            <dl className="facts">
              <dt>Requirements</dt>
              <dd>{(spec.requirements ?? []).join("; ") || "–"}</dd>
              <dt>Deliverables</dt>
              <dd>{(spec.deliverables ?? []).join("; ") || "–"}</dd>
              <dt>Unstated needs</dt>
              <dd>{(spec.hidden_needs ?? []).join("; ") || "–"}</dd>
              <dt>Timeline</dt>
              <dd>{spec.timeline ?? "–"}</dd>
              <dt>Seniority</dt>
              <dd>{spec.seniority ?? "–"}</dd>
            </dl>
          </section>
        </div>
        <div>
          <section className="panel">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h2>Recommendation</h2>
              <ActionChip action={dec.action} status={item.status} />
            </div>
            <ul>
              {(dec.reasons ?? []).map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
            <div className="grid2">
              <FitMeter fit={f.fit_score} />
              <div>
                <div className="small muted">Risk {pct(r.risk_score)}, client quality {pct(r.client_quality)}</div>
                <RiskBadges risk={r.risk_score} isScam={r.is_scam} flags={r.flags} />
              </div>
            </div>
            {r.rationale && <p className="small" style={{ marginTop: 12 }}>{r.rationale}</p>}
          </section>

          <section className="panel">
            <h2>Requirement and evidence</h2>
            <p className="small muted">Each requirement and the portfolio items that prove it.</p>
            <table className="matrix" data-testid="evidence-matrix">
              <thead>
                <tr>
                  <th scope="col">Requirement</th>
                  <th scope="col">Proof</th>
                  <th scope="col">Evidence</th>
                </tr>
              </thead>
              <tbody>
                {(f.matrix ?? []).map((m, i) => (
                  <tr key={i}>
                    <td>{m.requirement}</td>
                    <td>
                      <span className={`strength ${m.strength}`}>{m.strength}</span>
                    </td>
                    <td>
                      {m.evidence_ids.length === 0 && <span className="muted small">Nothing in your portfolio</span>}
                      {m.evidence_ids.map((eid) => (
                        <span className="ev-link" key={eid} title={evIndex.get(eid)?.text.slice(0, 300)}>
                          {eid.split(":").slice(1).join(" ")}
                        </span>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(f.matrix ?? []).length === 0 && <p className="muted small">Not matched yet.</p>}
          </section>

          <section className="panel">
            <h2>Price</h2>
            {pr ? (
              <>
                <p>
                  <strong>{money(pr.amount, pr.unit)}</strong>{" "}
                  {pr.connects_worth_it ? "" : <span className="badge danger">Connects not worth it</span>}
                </p>
                <p className="small">{pr.rationale}</p>
              </>
            ) : (
              <p className="muted small">Priced only for jobs worth bidding on.</p>
            )}
          </section>
        </div>
      </div>
    </>
  );
}
