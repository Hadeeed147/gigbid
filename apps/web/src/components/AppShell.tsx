import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { api } from "../lib/api/client";
import { useAuth } from "../lib/auth";
import { useInterval, useLoad } from "../lib/hooks";
import { DegradedBanner } from "./DegradedBanner";

const NAV = [
  { to: "/inbox", label: "Inbox" },
  { to: "/pipeline", label: "Pipeline" },
  { to: "/messages", label: "Messages" },
  { to: "/analytics", label: "Analytics" },
  { to: "/settings", label: "Settings" },
];

export function AppShell() {
  const { user, signOut } = useAuth();
  const nav = useNavigate();
  const pending = useLoad(() => api.GET("/api/approvals/pending"));
  useInterval(() => void pending.reload(), 20000);
  const counts = (pending.data ?? {}) as { proposals?: unknown[]; messages?: unknown[] };
  const badge: Record<string, number> = {
    "/inbox": counts.proposals?.length ?? 0,
    "/messages": counts.messages?.length ?? 0,
  };
  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <nav className="rail" aria-label="Main">
        <div className="brand">
          <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
            <rect width="32" height="32" rx="7" fill="#18212B" />
            <path d="M8 20.5h16" stroke="#FFEFA3" strokeWidth="5" strokeLinecap="round" />
            <path d="M9 12.5h10" stroke="#F5F7F9" strokeWidth="2.4" strokeLinecap="round" />
          </svg>
          GigBid
        </div>
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} className={({ isActive }) => `nav${isActive ? " active" : ""}`}>
            <span>{n.label}</span>
            {badge[n.to] ? (
              <span className="count" aria-label={`${badge[n.to]} waiting for approval`}>
                {badge[n.to]}
              </span>
            ) : null}
          </NavLink>
        ))}
        <div className="who">
          <div>{user?.name}</div>
          <button
            onClick={() => {
              signOut();
              nav("/login");
            }}
          >
            Sign out
          </button>
        </div>
      </nav>
      <main id="main">
        <DegradedBanner />
        <Outlet />
      </main>
    </div>
  );
}
