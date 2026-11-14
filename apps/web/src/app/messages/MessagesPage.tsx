import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Empty, ErrorState, Loading } from "../../components/States";
import { api, errorText } from "../../lib/api/client";
import { ago, statusText } from "../../lib/format";
import { useInterval, useLoad } from "../../lib/hooks";

const INTENT_TEXT: Record<string, string> = {
  question: "Question",
  negotiation: "Negotiation",
  interview_request: "Interview request",
  scam_signal: "Possible scam",
  other: "Other",
};

/** Client threads with suggested replies and interview slots; approve before anything is sent. */
export function MessagesPage() {
  const { threadId } = useParams();
  const list = useLoad(() => api.GET("/api/messages"));
  useInterval(() => void list.reload(), 10000);
  const convs = list.data ?? [];
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Messages</h1>
          <p>When a client replies, GigBid drafts an answer. Nothing is sent until you approve it.</p>
        </div>
      </div>
      {list.loading && !list.data && <Loading label="Loading conversations" />}
      {list.error && !list.data && <ErrorState error={list.error} retry={list.reload} />}
      {list.data && convs.length === 0 && (
        <Empty title="No client replies yet">
          <p>Replies to proposals you send show up here, with a suggested response ready to review.</p>
        </Empty>
      )}
      {convs.length > 0 && (
        <div className="inbox2">
          <ul className="threads">
            {convs.map((c) => (
              <li key={c.thread_id}>
                <Link to={`/messages/${c.thread_id}`} aria-current={c.thread_id === threadId ? "page" : undefined}>
                  <strong>{c.title || "Client conversation"}</strong>
                  <div className="small muted">
                    {statusText(c.status)}
                    {c.intent ? `, ${INTENT_TEXT[c.intent] ?? c.intent}` : ""}, {ago(c.updated_at)}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
          <div>{threadId ? <Thread threadId={threadId} /> : <p className="muted">Choose a conversation.</p>}</div>
        </div>
      )}
    </>
  );
}

type Pending = {
  reply?: { text: string };
  intent?: { intent: string; reason?: string };
  slots?: { start: string; timezone: string }[];
  compliance?: { verdict: string };
};

function Thread({ threadId }: { threadId: string }) {
  const t = useLoad(() => api.GET("/api/messages/{thread_id}", { params: { path: { thread_id: threadId } } }), [threadId]);
  const [text, setText] = useState<string | null>(null);
  const [slot, setSlot] = useState<string>("");
  const [reason, setReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  useInterval(() => void t.reload(), 5000, msg !== null);
  if (t.loading && !t.data) return <Loading label="Loading the thread" />;
  if (t.error || !t.data) return <ErrorState error={t.error} retry={t.reload} />;
  const pending = (t.data.pending ?? null) as Pending | null;
  const draft = text ?? pending?.reply?.text ?? "";

  const decide = async (action: "approve" | "edit" | "reject") => {
    const body =
      action === "reject"
        ? { action, reason }
        : { action: text !== null && text !== pending?.reply?.text ? ("edit" as const) : action, text: draft, slot_start: slot || undefined };
    const { error } = await api.POST("/api/messages/{thread_id}/approve", { params: { path: { thread_id: threadId } }, body });
    setMsg(error ? errorText(error) : action === "reject" ? "Reply discarded." : "Approved. Sending the reply…");
    void t.reload();
  };

  return (
    <section aria-label="Conversation">
      {(t.data.messages as { id: string; sender: string; text: string; at?: string }[]).map((m) => (
        <div key={m.id} className={`msg ${m.sender}`}>
          <div className="who">
            {m.sender === "client" ? "Client" : "You"}, {ago(m.at)}
          </div>
          {m.text}
        </div>
      ))}
      {msg && <div className="banner info" role="status">{msg}</div>}
      {pending && (
        <div className="panel" data-testid="reply-approval">
          <h2>Suggested reply</h2>
          {pending.intent && (
            <p className="small">
              Read as <strong>{INTENT_TEXT[pending.intent.intent] ?? pending.intent.intent}</strong>
              {pending.intent.intent === "scam_signal" && (
                <span className="badge danger" style={{ marginLeft: 8 }}>
                  Keep it on the platform
                </span>
              )}
            </p>
          )}
          <div className="field">
            <label htmlFor="reply">Reply</label>
            <textarea id="reply" rows={6} className="editor" style={{ minHeight: 140 }} value={draft} onChange={(e) => setText(e.target.value)} />
          </div>
          {(pending.slots ?? []).length > 0 && (
            <fieldset className="field" style={{ border: 0, padding: 0 }}>
              <legend className="label">Hold an interview slot (tentative)</legend>
              {(pending.slots ?? []).map((s) => (
                <label className="choice" key={s.start}>
                  <input type="radio" name="slot" value={s.start} checked={slot === s.start} onChange={() => setSlot(s.start)} />
                  <span>
                    {new Date(s.start).toLocaleString()} ({s.timezone})
                  </span>
                </label>
              ))}
            </fieldset>
          )}
          {rejecting ? (
            <div className="field">
              <label htmlFor="rreason">Why discard this reply?</label>
              <input id="rreason" type="text" value={reason} onChange={(e) => setReason(e.target.value)} />
              <div className="row" style={{ marginTop: 8 }}>
                <button className="btn" onClick={() => setRejecting(false)}>
                  Cancel
                </button>
                <button className="btn danger" disabled={!reason.trim()} onClick={() => decide("reject")}>
                  Discard reply
                </button>
              </div>
            </div>
          ) : (
            <div className="row">
              <button className="btn danger" onClick={() => setRejecting(true)}>
                Discard
              </button>
              <button className="btn primary" onClick={() => decide("approve")} disabled={!draft.trim()}>
                Approve and send
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
