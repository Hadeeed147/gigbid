"""Seed users: the reviewer login (preloaded with a persona) plus one user per persona.

Credentials come from env (REVIEWER_EMAIL / REVIEWER_PASSWORD); nothing secret is
committed. Idempotent: existing users are left alone.
Run:  uv run python -m scripts.seed
"""
from __future__ import annotations

import uuid

from apps.api import db
from apps.api.auth.security import create_user
from common.config import env

PERSONA_DEFAULTS = {
    "ai_ml": {"rate_floor": 35, "hourly_rate": 45, "searches": [("", "AI & Machine Learning"), ("python", "")]},
    "fullstack": {"rate_floor": 30, "hourly_rate": 40, "searches": [("", "Web Development")]},
    "data_analyst": {"rate_floor": 22, "hourly_rate": 30, "searches": [("", "Data Analytics")]},
}


def ensure(email: str, password: str, name: str, persona: str) -> str:
    row = db.one("SELECT id FROM users WHERE email=%s", (email.lower(),))
    if row:
        return row["id"]
    d = PERSONA_DEFAULTS[persona]
    u = create_user(email, password, name, tenant=persona,
                    settings={"rate_floor": d["rate_floor"], "hourly_rate": d["hourly_rate"],
                              "weekly_connects_budget": 60, "marketplace": "gigsim", "autonomy": "suggest_only"})
    db.q("UPDATE users SET onboarded=true WHERE id=%s", (u["id"],))
    for q, cat in d["searches"]:
        db.q("INSERT INTO saved_searches (id, user_id, query, category, interval_minutes) VALUES (%s,%s,%s,%s,%s)",
             ("s_" + uuid.uuid4().hex[:8], u["id"], q, cat, 10))
    return u["id"]


def main() -> None:
    pw = env("REVIEWER_PASSWORD")
    if not pw:
        raise SystemExit("set REVIEWER_PASSWORD in .env first")
    uid = ensure(env("REVIEWER_EMAIL", "reviewer@gigbid.dev"), pw, "Reviewer (AI/ML persona)", "ai_ml")
    print(f"reviewer user: {uid}")
    for persona in ("fullstack", "data_analyst"):
        print(persona, ensure(f"{persona}@gigbid.dev", pw, f"Demo {persona}", persona))
    warm_gigsim()


def warm_gigsim(days: float = 2.0) -> None:
    """GigSim releases jobs over a simulated week; fast-forward so a fresh deployment
    has jobs to show the reviewer immediately (the rest keep trickling in)."""
    import httpx
    base = env("GIGSIM_URL", "http://localhost:8100")
    try:
        h = httpx.get(f"{base}/health", timeout=5).json()
        from datetime import datetime
        sim = datetime.fromisoformat(h["sim_time"])
        start = datetime.fromisoformat("2026-10-27T09:00:00+00:00")
        if (sim - start).total_seconds() < days * 86400:
            httpx.post(f"{base}/admin/clock", json={"advance_minutes": days * 1440},
                       headers={"X-Admin-Key": env("GIGSIM_ADMIN_KEY", "gigsim-admin")}, timeout=5)
            print(f"GigSim clock advanced {days} days")
    except Exception as e:  # noqa: BLE001 - GigSim may not be running during seeding
        print(f"GigSim not reachable ({type(e).__name__}); skipped clock warm-up")


if __name__ == "__main__":
    main()
