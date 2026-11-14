import { useEffect, useState } from "react";
import { ErrorState, Loading } from "../../components/States";
import { api, errorText } from "../../lib/api/client";
import { useAuth } from "../../lib/auth";
import { ago } from "../../lib/format";
import { useLoad } from "../../lib/hooks";

/** Autonomy, budgets, saved searches, connected accounts, portfolio and the memory viewer. */
export function SettingsPage() {
  const { user, refresh } = useAuth();
  const s = (user?.settings ?? {}) as Record<string, string | number>;
  const [form, setForm] = useState({
    rate_floor: String(s.rate_floor ?? ""),
    hourly_rate: String(s.hourly_rate ?? ""),
    weekly_connects_budget: String(s.weekly_connects_budget ?? ""),
    autonomy: String(s.autonomy ?? "suggest_only"),
  });
  useEffect(() => {
    setForm({
      rate_floor: String(s.rate_floor ?? ""),
      hourly_rate: String(s.hourly_rate ?? ""),
      weekly_connects_budget: String(s.weekly_connects_budget ?? ""),
      autonomy: String(s.autonomy ?? "suggest_only"),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);
  const [saved, setSaved] = useState<string | null>(null);
  const searches = useLoad(() => api.GET("/api/settings/searches"));
  const memory = useLoad(() => api.GET("/api/settings/memory"));
  const accounts = useLoad(() => api.GET("/api/auth/accounts"));
  const portfolio = useLoad(() => api.GET("/api/portfolio/items"));
  const [newSearch, setNewSearch] = useState({ query: "", category: "" });
  const [item, setItem] = useState({ title: "", text: "" });
  const [itemMsg, setItemMsg] = useState<string | null>(null);
  const [gh, setGh] = useState("");
  const importGithub = async () => {
    const { error } = await api.POST("/api/portfolio/github", { params: { query: { login: gh.trim() } } });
    setItemMsg(error ? errorText(error) : "Importing your repositories. They appear in your portfolio in a minute or two.");
  };

  const save = async () => {
    const { error } = await api.PUT("/api/settings", {
      body: {
        rate_floor: Number(form.rate_floor) || undefined,
        hourly_rate: Number(form.hourly_rate) || undefined,
        weekly_connects_budget: Number(form.weekly_connects_budget),
        autonomy: form.autonomy as "suggest_only" | "auto_skip_low_fit",
      },
    });
    setSaved(error ? errorText(error) : "Saved.");
    void refresh();
  };
  const addSearch = async () => {
    await api.POST("/api/settings/searches", { body: { ...newSearch, interval_minutes: 10 } });
    setNewSearch({ query: "", category: "" });
    void searches.reload();
  };
  const forget = async (kind: string, key: string) => {
    await api.DELETE("/api/settings/memory/{kind}/{key}", { params: { path: { kind, key } } });
    void memory.reload();
  };
  const addItem = async () => {
    const { data, error } = await api.POST("/api/portfolio/items", { body: { ...item, type: "case_study" } });
    setItemMsg(error ? errorText(error) : `Added and indexed (${data?.chunks_indexed} chunks). It is used from the next draft on.`);
    if (!error) setItem({ title: "", text: "" });
    void portfolio.reload();
  };

  const acc = (accounts.data ?? {}) as { marketplace?: string; gigsim?: string; upwork?: boolean };
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p>How GigBid works for you, and what it has learned.</p>
        </div>
      </div>
      <div className="grid2">
        <section className="panel">
          <h2>Rates and autonomy</h2>
          <div className="grid2">
            <div className="field">
              <label htmlFor="floor">Rate floor ($/h)</label>
              <input id="floor" type="number" value={form.rate_floor} onChange={(e) => setForm({ ...form, rate_floor: e.target.value })} />
            </div>
            <div className="field">
              <label htmlFor="rate">Usual rate ($/h)</label>
              <input id="rate" type="number" value={form.hourly_rate} onChange={(e) => setForm({ ...form, hourly_rate: e.target.value })} />
            </div>
          </div>
          <div className="field">
            <label htmlFor="budget">Weekly Connects budget</label>
            <input id="budget" type="number" value={form.weekly_connects_budget} onChange={(e) => setForm({ ...form, weekly_connects_budget: e.target.value })} />
          </div>
          <fieldset className="field" style={{ border: 0, padding: 0 }}>
            <legend className="label">Autonomy</legend>
            <label className="choice">
              <input type="radio" name="aut" checked={form.autonomy === "suggest_only"} onChange={() => setForm({ ...form, autonomy: "suggest_only" })} />
              <span>
                Suggest only
                <div className="small muted">Every recommendation waits for you.</div>
              </span>
            </label>
            <label className="choice">
              <input type="radio" name="aut" checked={form.autonomy === "auto_skip_low_fit"} onChange={() => setForm({ ...form, autonomy: "auto_skip_low_fit" })} />
              <span>
                Skip clear mismatches automatically
                <div className="small muted">Very low-fit jobs are skipped without asking. Proposals and messages are never sent without you.</div>
              </span>
            </label>
          </fieldset>
          <button className="btn primary" onClick={save}>
            Save settings
          </button>
          {saved && <span className="small" style={{ marginLeft: 12 }}>{saved}</span>}
        </section>

        <section className="panel">
          <h2>Connected accounts</h2>
          {accounts.loading ? (
            <Loading />
          ) : (
            <dl className="facts">
              <dt>Marketplace</dt>
              <dd>{acc.marketplace === "upwork_live" ? "Upwork (live, drafts only)" : "GigSim"}</dd>
              <dt>GigSim</dt>
              <dd>{acc.gigsim}</dd>
              <dt>Upwork</dt>
              <dd>
                {acc.upwork ? "Connected" : "Not connected"}{" "}
                {!acc.upwork && (
                  <button
                    className="btn quiet"
                    onClick={async () => {
                      const { data, error } = await api.GET("/api/auth/upwork/start");
                      if (data && (data as { authorize_url?: string }).authorize_url) location.assign((data as { authorize_url: string }).authorize_url);
                      else alert(errorText(error, "Live mode is not configured on this deployment."));
                    }}
                  >
                    Connect Upwork
                  </button>
                )}
              </dd>
            </dl>
          )}
          <h2 style={{ marginTop: 24 }}>Saved searches</h2>
          {!!searches.error && <ErrorState error={searches.error} retry={searches.reload} />}
          <ul>
            {(searches.data ?? []).map((x) => (
              <li key={x.id}>
                {x.query || "Any keywords"} in {x.category || "all categories"}, every {x.interval_minutes} min
                <span className="small muted"> (last checked {x.last_run ? ago(x.last_run) : "never"})</span>{" "}
                <button className="btn quiet" onClick={async () => { await api.DELETE("/api/settings/searches/{sid}", { params: { path: { sid: x.id } } }); void searches.reload(); }}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
          <div className="grid2">
            <input type="text" aria-label="Search keywords" placeholder="Keywords" value={newSearch.query} onChange={(e) => setNewSearch({ ...newSearch, query: e.target.value })} />
            <input type="text" aria-label="Category" placeholder="Category (optional)" value={newSearch.category} onChange={(e) => setNewSearch({ ...newSearch, category: e.target.value })} />
          </div>
          <button className="btn" style={{ marginTop: 8 }} onClick={addSearch}>
            Add search
          </button>
        </section>
      </div>

      <section className="panel" data-testid="memory-viewer">
        <h2>What GigBid has learned</h2>
        <p className="small muted">
          Style rules come from your edits and are kept only after the same change shows up in at least two edits. Outcome
          lessons need at least three results in a category. Delete anything you disagree with.
        </p>
        {memory.loading && <Loading />}
        {!!memory.error && <ErrorState error={memory.error} retry={memory.reload} />}
        {memory.data && (
          <div className="grid2">
            <div>
              <h3>Style</h3>
              {memory.data.style.length === 0 && <p className="small muted">Nothing yet. Edit a few drafts.</p>}
              <ul>
                {memory.data.style.map((m) => (
                  <li key={String(m.key)}>
                    {String(m.rule)} <span className="small muted">(seen in {String(m.support)} edits)</span>{" "}
                    <button className="btn quiet" onClick={() => forget("style", String(m.key))}>
                      Delete
                    </button>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h3>Outcomes</h3>
              {memory.data.outcome.length === 0 && <p className="small muted">Nothing yet. Results arrive as clients respond.</p>}
              <ul>
                {memory.data.outcome.map((m) => (
                  <li key={String(m.key)}>
                    {String(m.key)}: reply rate {Math.round(Number(m.reply_rate) * 100)}% over {String(m.n)} proposals{" "}
                    <button className="btn quiet" onClick={() => forget("outcome", String(m.key))}>
                      Delete
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </section>

      <section className="panel">
        <h2>Portfolio</h2>
        <p className="small muted">
          {(portfolio.data ?? []).length} items. Add a case study and it is indexed right away; claims about it become possible in the next draft.
        </p>
        <div className="field">
          <label htmlFor="ititle">Title</label>
          <input id="ititle" type="text" value={item.title} onChange={(e) => setItem({ ...item, title: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="itext">What you built and the result</label>
          <textarea id="itext" rows={5} value={item.text} onChange={(e) => setItem({ ...item, text: e.target.value })} />
        </div>
        <button className="btn" disabled={item.title.length < 3 || item.text.length < 40} onClick={addItem}>
          Add to portfolio
        </button>
        {itemMsg && <p className="small" role="status">{itemMsg}</p>}
        <div className="row" style={{ marginTop: 16 }}>
          <label className="sr-only" htmlFor="gh">GitHub username</label>
          <input id="gh" type="text" placeholder="GitHub username" style={{ maxWidth: 220 }} value={gh}
                 onChange={(e) => setGh(e.target.value)} />
          <button className="btn" disabled={!gh.trim()} onClick={importGithub}>
            Import repos from GitHub
          </button>
        </div>
        <p className="small muted">Reads public READMEs and code through the official GitHub connection. Nothing is written to GitHub.</p>
      </section>
    </>
  );
}
