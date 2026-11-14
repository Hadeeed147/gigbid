import { useParams } from "react-router-dom";
import { RunTimeline } from "../../components/RunTimeline";
import { ErrorState, Loading } from "../../components/States";
import { api } from "../../lib/api/client";
import { ago } from "../../lib/format";
import { useLoad, useRunStream } from "../../lib/hooks";

/** Live node-by-node progress streamed from LangGraph, plus every past run of this thread. */
export function RunPage() {
  const { id = "" } = useParams();
  const threadId = decodeURIComponent(id);
  const stream = useRunStream(threadId);
  const runs = useLoad(() => api.GET("/api/runs", { params: { query: { thread_id: threadId } } }), [threadId]);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Agent run</h1>
          <p>Every step the agents took on this {threadId.startsWith("conv") ? "conversation" : "job"}, as it happens.</p>
        </div>
        <span className="small muted">{stream.connected ? "Live" : "Reconnecting"}</span>
      </div>
      <div className="split">
        <section className="panel" aria-label="Timeline">
          <h2>Timeline</h2>
          <RunTimeline events={stream.events} connected={stream.connected} />
        </section>
        <section className="panel">
          <h2>Runs on this thread</h2>
          {runs.loading && <Loading />}
          {!!runs.error && <ErrorState error={runs.error} retry={runs.reload} />}
          <table className="matrix">
            <thead>
              <tr>
                <th scope="col">Run</th>
                <th scope="col">Status</th>
                <th scope="col">Trace</th>
              </tr>
            </thead>
            <tbody>
              {(runs.data ?? []).map((r) => (
                <tr key={r.id}>
                  <td>
                    {r.kind.replace("_", " ")}
                    <div className="small muted">{ago(r.started_at)}</div>
                  </td>
                  <td>
                    {r.status}
                    {r.error && <div className="error-text small">{r.error}</div>}
                  </td>
                  <td>
                    {r.trace_url ? (
                      <a href={r.trace_url} target="_blank" rel="noreferrer">
                        Open trace
                      </a>
                    ) : (
                      <span className="small muted">trace id {r.trace_id?.slice(0, 8)}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </>
  );
}
