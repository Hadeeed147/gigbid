import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, errorText } from "../../lib/api/client";
import { useAuth } from "../../lib/auth";

const PROFILES = [
  { key: "ai_ml", title: "AI/ML engineer", text: "LLM apps, RAG, agents, computer vision. Sample portfolio of 20 projects.", floor: 35, rate: 45, cat: "AI & Machine Learning" },
  { key: "fullstack", title: "Full-stack web developer", text: "React, Next.js, Node, Django, payments. Sample portfolio of 22 projects.", floor: 30, rate: 40, cat: "Web Development" },
  { key: "data_analyst", title: "Data analyst", text: "SQL, dbt, Power BI, Tableau, experiments. Sample portfolio of 22 projects.", floor: 22, rate: 30, cat: "Data Analytics" },
  { key: "own", title: "My own profile", text: "Start empty and add your own case studies in Settings.", floor: 25, rate: 35, cat: "" },
] as const;

/** Choose a persona or your own profile, connect a marketplace, set rates, filters and a weekly Connects budget. */
export function OnboardingPage() {
  const [step, setStep] = useState(0);
  const [profile, setProfile] = useState<(typeof PROFILES)[number]["key"]>("ai_ml");
  const [marketplace, setMarketplace] = useState<"gigsim" | "upwork_live">("gigsim");
  const p = PROFILES.find((x) => x.key === profile)!;
  const [floor, setFloor] = useState<string>(String(p.floor));
  const [rate, setRate] = useState<string>(String(p.rate));
  const [budget, setBudget] = useState("60");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>(p.cat);
  const [err, setErr] = useState<string | null>(null);
  const { refresh } = useAuth();
  const nav = useNavigate();
  const steps = ["Profile", "Marketplace", "Rates and searches"];

  const choose = (k: (typeof PROFILES)[number]["key"]) => {
    const x = PROFILES.find((y) => y.key === k)!;
    setProfile(k);
    setFloor(String(x.floor));
    setRate(String(x.rate));
    setCategory(x.cat);
  };

  const finish = async () => {
    setErr(null);
    const { error } = await api.POST("/api/auth/onboarding", {
      body: {
        profile,
        marketplace,
        rate_floor: Number(floor),
        hourly_rate: Number(rate),
        weekly_connects_budget: Number(budget),
        searches: [{ query, category, interval_minutes: 10 }],
      },
    });
    if (error) {
      setErr(errorText(error));
      return;
    }
    await refresh();
    nav("/inbox");
  };

  return (
    <div className="onboard">
      <h1>Set up GigBid</h1>
      <ol className="steps">
        {steps.map((s, i) => (
          <li key={s} aria-current={i === step ? "step" : undefined}>
            {i + 1}. {s}
          </li>
        ))}
      </ol>
      <div className="panel">
        {step === 0 && (
          <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="label" style={{ marginBottom: 12 }}>
              Whose portfolio should GigBid use?
            </legend>
            <div className="grid2">
              {PROFILES.map((x) => (
                <label className="choice" key={x.key}>
                  <input type="radio" name="profile" checked={profile === x.key} onChange={() => choose(x.key)} />
                  <span>
                    <strong>{x.title}</strong>
                    <div className="small muted">{x.text}</div>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
        )}
        {step === 1 && (
          <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="label" style={{ marginBottom: 12 }}>
              Where should GigBid look for work?
            </legend>
            <label className="choice">
              <input type="radio" name="mk" checked={marketplace === "gigsim"} onChange={() => setMarketplace("gigsim")} />
              <span>
                <strong>GigSim</strong>
                <div className="small muted">The course marketplace simulator. Safe to experiment with.</div>
              </span>
            </label>
            <label className="choice" style={{ marginTop: 8 }}>
              <input type="radio" name="mk" checked={marketplace === "upwork_live"} onChange={() => setMarketplace("upwork_live")} />
              <span>
                <strong>Upwork (live)</strong>
                <div className="small muted">
                  Through Upwork's official connection. GigBid only creates drafts; you confirm each one on Upwork. Connect it in Settings afterwards.
                </div>
              </span>
            </label>
          </fieldset>
        )}
        {step === 2 && (
          <>
            <div className="grid2">
              <div className="field">
                <label htmlFor="floor">Lowest rate you accept ($/h)</label>
                <input id="floor" type="number" min={1} value={floor} onChange={(e) => setFloor(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="rate">Your usual rate ($/h)</label>
                <input id="rate" type="number" min={1} value={rate} onChange={(e) => setRate(e.target.value)} />
              </div>
            </div>
            <div className="field">
              <label htmlFor="budget">Weekly Connects budget</label>
              <input id="budget" type="number" min={0} value={budget} onChange={(e) => setBudget(e.target.value)} />
              <span className="hint">GigBid flags a bid when the Connects it costs are not worth the fit.</span>
            </div>
            <div className="grid2">
              <div className="field">
                <label htmlFor="q">Search keywords</label>
                <input id="q" type="text" placeholder="e.g. RAG chatbot" value={query} onChange={(e) => setQuery(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="cat">Category</label>
                <select id="cat" value={category} onChange={(e) => setCategory(e.target.value)}>
                  <option value="">All categories</option>
                  <option>AI & Machine Learning</option>
                  <option>Web Development</option>
                  <option>Data Analytics</option>
                  <option>Data Engineering</option>
                  <option>Mobile Development</option>
                  <option>E-commerce</option>
                </select>
              </div>
            </div>
          </>
        )}
        {err && <p className="error-text" role="alert">{err}</p>}
        <div className="row" style={{ marginTop: 16 }}>
          {step > 0 && (
            <button className="btn" onClick={() => setStep(step - 1)}>
              Back
            </button>
          )}
          {step < 2 ? (
            <button className="btn primary" onClick={() => setStep(step + 1)}>
              Continue
            </button>
          ) : (
            <button className="btn primary" onClick={finish} disabled={!Number(floor) || !Number(rate)}>
              Start finding jobs
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
