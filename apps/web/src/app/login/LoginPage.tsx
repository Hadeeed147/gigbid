import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, errorText } from "../../lib/api/client";
import { useAuth } from "../../lib/auth";

export function LoginPage() {
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { signIn } = useAuth();
  const nav = useNavigate();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    const r =
      mode === "in"
        ? await api.POST("/api/auth/login", { body: { email, password } })
        : await api.POST("/api/auth/register", { body: { email, password, name } });
    setBusy(false);
    if (r.error || !r.data) {
      setErr(errorText(r.error, "Could not sign in."));
      return;
    }
    signIn(r.data.token, r.data.user);
    nav(r.data.user.onboarded ? "/inbox" : "/onboarding");
  };

  return (
    <div className="auth">
      <div className="panel">
        <h1>GigBid</h1>
        <p className="lede">
          Finds the jobs worth your Connects and drafts proposals where <mark>every claim points to your own work</mark>.
          Nothing is sent until you approve it.
        </p>
        <form onSubmit={submit} noValidate>
          {mode === "up" && (
            <div className="field">
              <label htmlFor="name">Your name</label>
              <input id="name" type="text" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
          )}
          <div className="field">
            <label htmlFor="email">Email</label>
            <input id="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete={mode === "in" ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
            />
            {mode === "up" && <span className="hint">At least 8 characters.</span>}
          </div>
          {err && <p className="error-text" role="alert">{err}</p>}
          <div className="row">
            <button className="btn primary" type="submit" disabled={busy}>
              {mode === "in" ? "Sign in" : "Create account"}
            </button>
            <button className="btn quiet" type="button" onClick={() => setMode(mode === "in" ? "up" : "in")}>
              {mode === "in" ? "Create an account" : "I already have an account"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
