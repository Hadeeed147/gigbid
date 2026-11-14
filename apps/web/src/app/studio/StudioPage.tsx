import { useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  EvidenceLetter,
  EvidenceRail,
  stripCitations,
  type ActiveClaim,
  type ClaimCheck,
  type Evidence,
} from "../../components/EvidenceHover";
import { RunTimeline } from "../../components/RunTimeline";
import { ErrorState, Loading } from "../../components/States";
import { api, errorText, type ApprovalIn } from "../../lib/api/client";
import { money, statusText } from "../../lib/format";
import { useInterval, useLoad, useRunStream } from "../../lib/hooks";

type Payload = {
  draft: { cover_letter: string; screening_answers?: string[] };
  evidence?: Record<string, Evidence[]>;
  price?: { amount: number; unit: string; rationale?: string; connects_cost?: number };
  verification?: { claims?: ClaimCheck[]; claims_total?: number; unsupported_before?: number };
  critiques?: { approved: boolean; score: number; revision?: number; issues?: { problem: string; fix: string }[] }[];
  compliance?: { verdict: string; violations?: { rule: string; quote: string }[] };
  dry_run_preview?: { would_create?: { connects_cost_on_submit?: number; connects_balance?: number; cover_letter?: string } };
  job?: { title?: string; screening_questions?: string[] };
};

/** Proposal studio: the draft as the client will read it, evidence on hover, critic and
 *  compliance notes inline, and the approval bar. Nothing is sent until you approve. */
export function StudioPage() {
  const { id = "" } = useParams();
  const studio = useLoad(() => api.GET("/api/proposals/{job_id}", { params: { path: { job_id: id } } }), [id]);
  const s = studio.data;
  const p = (s?.payload ?? null) as Payload | null;
  const [active, setActive] = useState<ActiveClaim>(null);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [answers, setAnswers] = useState<string[]>([]);
  const [bid, setBid] = useState<string>("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sent, setSent] = useState<string | null>(null);
  const rejectRef = useRef<HTMLDialogElement>(null);
  const previewRef = useRef<HTMLDialogElement>(null);
  const [reason, setReason] = useState("");
  const stream = useRunStream(s?.thread_id);

  const working = s?.status === "resuming" || (sent !== null && s?.pending === false && !["submitted", "rejected", "blocked"].includes(s?.status ?? ""));
  useInterval(() => void studio.reload(), 3000, working || sent !== null);

  const index = useMemo(() => {
    const m = new Map<string, Evidence>();
    Object.values(p?.evidence ?? {}).forEach((items) => items.forEach((e) => m.set(e.item_id, e)));
    return m;
  }, [p]);

  if (studio.loading && !s) return <Loading label="Opening the proposal" />;
  if (studio.error) return <ErrorState error={studio.error} retry={studio.reload} />;
  if (!s || !p)
    return (
      <div className="state">
        <h2>No draft for this job yet</h2>
        <p>GigBid drafts a proposal only for jobs it recommends bidding on, or when you choose to draft anyway.</p>
        <Link className="btn" to={`/jobs/${id}`}>
          Back to the job
        </Link>
      </div>
    );

  const checks = p.verification?.claims ?? [];
  const removed = checks.filter((c) => c.status === "unsupported");
  const lastCritique = p.critiques?.[p.critiques.length - 1];
  const cost = p.dry_run_preview?.would_create?.connects_cost_on_submit ?? p.price?.connects_cost;
  const balance = p.dry_run_preview?.would_create?.connects_balance;
  const questions = p.job?.screening_questions ?? [];

  const startEdit = () => {
    setText(p.draft.cover_letter);
    setAnswers(p.draft.screening_answers ?? []);
    setBid(String(p.price?.amount ?? ""));
    setEditing(true);
  };

  const decide = async (body: ApprovalIn) => {
    setBusy(body.action);
    setErr(null);
    const { error } = await api.POST("/api/approvals/{job_id}", { params: { path: { job_id: id } }, body });
    setBusy(null);
    if (error) {
      setErr(errorText(error));
      return;
    }
    setSent(body.action);
    setEditing(false);
    rejectRef.current?.close();
    previewRef.current?.close();
    void studio.reload();
  };

  const rewrite = async (pi: number) => {
    const paras = (editing ? text : p.draft.cover_letter).split(/\n{2,}/);
    setBusy("rewrite");
    const { data, error } = await api.POST("/api/proposals/{job_id}/paragraph", {
      params: { path: { job_id: id } },
      body: { paragraph: paras[pi], instruction: "Make it more specific to this client's problem" },
    });
    setBusy(null);
    if (error || !data) {
      setErr(errorText(error, "Could not rewrite that paragraph."));
      return;
    }
    paras[pi] = data.paragraph;
    if (!editing) startEdit();
    setText(paras.join("\n\n"));
    setEditing(true);
  };

  const done = ["submitted", "rejected", "blocked"].includes(s.status ?? "");
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{p.job?.title ?? "Proposal"}</h1>
          <p>
            {statusText(s.status)}
            {s.submission ? ` · proposal ${(s.submission as { proposal_id?: string }).proposal_id}` : ""}
          </p>
        </div>
        <div className="row">
          <Link className="btn" to={`/jobs/${id}`}>
            Job details
          </Link>
        </div>
      </div>

      {s.attention_reason && <div className="banner info">{s.attention_reason}</div>}
      {sent && !done && (
        <div className="banner info" role="status">
          {sent === "approve" ? "Approved. Submitting to the marketplace…" : sent === "edit" ? "Re-checking your edit with the Compliance Guard…" : "Recording your rejection…"}
        </div>
      )}
      {err && <div className="banner degraded" role="alert">{err}</div>}

      <div className="studio">
        <div>
          {editing ? (
            <div className="panel">
              <div className="field">
                <label htmlFor="cover">Cover letter</label>
                <span className="hint">Keep the [item id] tags to keep evidence links; they are removed before sending.</span>
                <textarea id="cover" className="editor" value={text} onChange={(e) => setText(e.target.value)} />
              </div>
              {questions.map((q, i) => (
                <div className="field" key={i}>
                  <label htmlFor={`qa${i}`}>{q}</label>
                  <textarea id={`qa${i}`} rows={3} value={answers[i] ?? ""} onChange={(e) => {
                    const a = [...answers];
                    a[i] = e.target.value;
                    setAnswers(a);
                  }} />
                </div>
              ))}
              <div className="field" style={{ maxWidth: 240 }}>
                <label htmlFor="bid">Bid ({p.price?.unit})</label>
                <input id="bid" type="number" min={1} value={bid} onChange={(e) => setBid(e.target.value)} />
              </div>
            </div>
          ) : (
            <>
              <EvidenceLetter
                text={p.draft.cover_letter}
                checks={checks}
                active={active}
                onActivate={setActive}
                onRewrite={s.pending ? rewrite : undefined}
              />
              {(p.draft.screening_answers ?? []).length > 0 && (
                <div className="letter qa">
                  {(p.draft.screening_answers ?? []).map((a, i) => (
                    <div key={i}>
                      <h3>{questions[i] ?? `Screening answer ${i + 1}`}</h3>
                      <EvidenceLetter text={a} checks={checks} active={active} onActivate={setActive} />
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          {s.pending && (
            <div className="approval-bar" data-testid="approval-bar">
              <span className="cost">
                Bid <strong>{money(p.price?.amount, p.price?.unit)}</strong>, costs <strong>{cost ?? "?"} Connects</strong>
                {balance != null ? ` (you have ${balance})` : ""}
              </span>
              {editing ? (
                <>
                  <button className="btn" onClick={() => setEditing(false)}>
                    Cancel edit
                  </button>
                  <button
                    className="btn primary"
                    disabled={!!busy || !text.trim()}
                    onClick={() =>
                      decide({ action: "edit", text, screening_answers: answers, bid_amount: Number(bid) || undefined })
                    }
                  >
                    Save edit and re-check
                  </button>
                </>
              ) : (
                <>
                  <button className="btn danger" onClick={() => rejectRef.current?.showModal()} disabled={!!busy}>
                    Reject
                  </button>
                  <button className="btn" onClick={startEdit} disabled={!!busy}>
                    Edit
                  </button>
                  <button className="btn primary" onClick={() => previewRef.current?.showModal()} disabled={!!busy}>
                    Review and send
                  </button>
                </>
              )}
            </div>
          )}
        </div>

        <aside className="side" aria-label="Review notes">
          <EvidenceRail active={active} index={index} />
          <section className="panel">
            <h2>Claim check</h2>
            <p className="small">
              {p.verification?.claims_total ?? 0} claims checked against your portfolio;{" "}
              {p.verification?.unsupported_before ?? 0} unsupported removed before review.
            </p>
            {removed.map((c, i) => (
              <p key={i} className="removed">
                {stripCitations(c.text)}
              </p>
            ))}
          </section>
          <section className="panel">
            <h2>Critic</h2>
            {!lastCritique && <p className="muted small">No review yet.</p>}
            {p.critiques?.map((c, i) => (
              <div className="comment" key={i}>
                <strong>
                  Round {(c.revision ?? i) + 1}: {c.approved ? "approved" : "sent back"} ({c.score}/10)
                </strong>
                {c.issues?.map((x, j) => (
                  <div key={j} className="small">
                    {x.problem}. {x.fix}.
                  </div>
                ))}
              </div>
            ))}
          </section>
          <section className="panel">
            <h2>Compliance</h2>
            <p className="small">
              {p.compliance?.verdict === "pass" ? "No platform-rule problems found." : `Verdict: ${p.compliance?.verdict}`}
            </p>
            {p.compliance?.violations?.map((v, i) => (
              <div className="comment small" key={i}>
                Removed ({v.rule.replace(/_/g, " ")}): “{v.quote}”
              </div>
            ))}
          </section>
          <section className="panel">
            <h2>Agent run</h2>
            <RunTimeline events={stream.events.slice(-14)} connected={stream.connected} />
            <Link className="small" to={`/runs/${encodeURIComponent(s.thread_id)}`}>
              Full run history
            </Link>
          </section>
        </aside>
      </div>

      <dialog ref={previewRef} aria-labelledby="preview-title">
        <h2 id="preview-title">This is exactly what will be sent</h2>
        <p className="small muted">Dry-run preview from the marketplace. Evidence tags are removed.</p>
        <div className="preview-text" data-testid="dry-run-preview">
          {stripCitations(p.draft.cover_letter)}
        </div>
        <p className="small">
          Bid {money(p.price?.amount, p.price?.unit)}. Submitting spends {cost ?? "?"} Connects
          {balance != null ? `, leaving ${balance - (cost ?? 0)}` : ""}.
        </p>
        <div className="row">
          <button className="btn" onClick={() => previewRef.current?.close()}>
            Go back
          </button>
          <button className="btn primary" disabled={!!busy} onClick={() => decide({ action: "approve" })}>
            Approve and submit
          </button>
        </div>
      </dialog>

      <dialog ref={rejectRef} aria-labelledby="reject-title">
        <h2 id="reject-title">Reject this proposal</h2>
        <div className="field">
          <label htmlFor="reason">Why? This trains what GigBid recommends.</label>
          <textarea id="reason" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
        <div className="row">
          <button className="btn" onClick={() => rejectRef.current?.close()}>
            Keep the draft
          </button>
          <button
            className="btn danger"
            disabled={!reason.trim() || !!busy}
            onClick={() => decide({ action: "reject", reason })}
          >
            Reject proposal
          </button>
        </div>
      </dialog>
    </>
  );
}
