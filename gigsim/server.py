"""GigSim: a marketplace simulator for GigBid development and grading.

Built for this assignment (no simulator was distributed). Treat as frozen after
the first release: CI checks gigsim/ against gigsim/CHECKSUM.

Features: jobs released on a simulated clock (synthetic labelled jobs + real
Kaggle postings), clients with public histories and hidden preferences,
Connects, proposal drafts + submission, client replies and conversation threads,
marketplace events, per-token rate limits, random 5xx errors, idempotency keys,
dry_run previews and versioned platform policies.

Run:  uv run uvicorn gigsim.server:app --port 8100
"""
from __future__ import annotations

import json
import os
import random
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gigsim.client_model import decide
from gigsim.policies import POLICIES, connects_cost

DATA = Path(__file__).parent / "data"
DB_PATH = Path(os.environ.get("GIGSIM_DB", str(DATA / "gigsim.sqlite")))
ERROR_RATE = float(os.environ.get("GIGSIM_ERROR_RATE", "0.02"))
RATE_LIMIT = int(os.environ.get("GIGSIM_RATE_LIMIT", "60"))
TIME_SCALE = float(os.environ.get("GIGSIM_TIME_SCALE", "60"))  # sim minutes per real minute
ADMIN_KEY = os.environ.get("GIGSIM_ADMIN_KEY", "gigsim-admin")
START_CONNECTS = int(os.environ.get("GIGSIM_START_CONNECTS", "120"))

SEED_ACCOUNTS = {
    "gs_ai_ml": {"persona": "ai_ml", "name": "Sana Malik"},
    "gs_fullstack": {"persona": "fullstack", "name": "Bilal Ahmed"},
    "gs_data_analyst": {"persona": "data_analyst", "name": "Hira Qureshi"},
}

app = FastAPI(title="GigSim", version="1.0.0",
              description="Marketplace simulator for GigBid (AI-4016). Synthetic + Kaggle data.")
_lock = threading.RLock()
_rate: dict[str, deque] = defaultdict(deque)
_err_rng = random.Random(1234)


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------
def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init_db(reset: bool = False) -> None:
    with _lock:
        if reset and DB_PATH.exists():
            DB_PATH.unlink()
        con = db()
        con.executescript("""
        CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS accounts (token TEXT PRIMARY KEY, persona TEXT, name TEXT, connects INTEGER);
        CREATE TABLE IF NOT EXISTS proposals (id TEXT PRIMARY KEY, token TEXT, job_id TEXT, status TEXT,
            body TEXT, connects_spent INTEGER DEFAULT 0, created_sim REAL, submitted_sim REAL);
        CREATE TABLE IF NOT EXISTS threads (id TEXT PRIMARY KEY, token TEXT, job_id TEXT, client_id TEXT,
            proposal_id TEXT, created_sim REAL);
        CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, thread_id TEXT, sender TEXT, text TEXT,
            intent TEXT, visible_at REAL);
        CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT, type TEXT,
            proposal_id TEXT, job_id TEXT, payload TEXT, visible_at REAL);
        CREATE TABLE IF NOT EXISTS idem (key TEXT PRIMARY KEY, response TEXT);
        """)
        if not con.execute("SELECT 1 FROM kv WHERE k='start'").fetchone():
            con.execute("INSERT INTO kv VALUES ('start', ?)", (str(time.time()),))
            con.execute("INSERT INTO kv VALUES ('offset_min', '0')")
            con.execute("INSERT INTO kv VALUES ('policy', ?)", (os.environ.get("GIGSIM_POLICY_VERSION", "1"),))
            for tok, a in SEED_ACCOUNTS.items():
                con.execute("INSERT INTO accounts VALUES (?,?,?,?)", (tok, a["persona"], a["name"], START_CONNECTS))
        con.commit()
        con.close()


def kv(key: str) -> str:
    con = db()
    row = con.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
    con.close()
    return row["v"] if row else ""


def set_kv(key: str, value: str) -> None:
    with _lock:
        con = db()
        con.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, value))
        con.commit()
        con.close()


def now_sim() -> float:
    """Simulated minutes since GigSim started."""
    return (time.time() - float(kv("start"))) / 60 * TIME_SCALE + float(kv("offset_min"))


def sim_iso(minutes: float) -> str:
    base = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
    return (base + timedelta(minutes=minutes)).isoformat()


def policy() -> dict:
    return POLICIES[int(kv("policy") or 1)]


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
def _load_json(name: str, default: Any) -> Any:
    p = DATA / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


CLIENTS = {c["id"]: c for c in _load_json("clients.json", [])}
SKILL_NAMES = _load_json("skill_names.json", {})
JOBS: dict[str, dict] = {}
for j in _load_json("jobs.json", []) + _load_json("market_jobs.json", []):
    JOBS[j["id"]] = j
EXTRA_JOBS: dict[str, dict] = {}  # injected by admin (hidden test runs)

PUBLIC_JOB_FIELDS = ["id", "title", "description", "category", "budget", "client_id", "screening_questions",
                     "connects_cost", "source"]


def all_jobs() -> dict[str, dict]:
    return {**JOBS, **EXTRA_JOBS}


def public_job(j: dict) -> dict:
    out = {k: j.get(k) for k in PUBLIC_JOB_FIELDS}
    out["posted_at"] = sim_iso(j.get("posted_at_offset_min", 0))
    client = CLIENTS.get(j["client_id"], {})
    out["connects_cost"] = connects_cost(policy(), j, client)
    return out


def public_client(c: dict) -> dict:
    hidden = {"hidden_prefs", "is_scam", "responsiveness"}
    return {k: v for k, v in c.items() if k not in hidden}


# ---------------------------------------------------------------------------
# middleware: auth, rate limit, random failures
# ---------------------------------------------------------------------------
@app.middleware("http")
async def chaos_and_limits(request: Request, call_next):
    path = request.url.path
    if path.startswith("/admin") or path in ("/health", "/docs", "/openapi.json"):
        return await call_next(request)
    token = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip() or "anon"
    q = _rate[token]
    t = time.time()
    while q and t - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        return JSONResponse({"error": "rate_limited", "retry_after_s": int(60 - (t - q[0])) + 1}, status_code=429,
                            headers={"Retry-After": str(int(60 - (t - q[0])) + 1)})
    q.append(t)
    if ERROR_RATE and _err_rng.random() < ERROR_RATE:
        return JSONResponse({"error": "upstream_unavailable"}, status_code=503)
    return await call_next(request)


def account(authorization: str = Header(default="")) -> dict:
    tok = authorization.removeprefix("Bearer ").strip()
    con = db()
    row = con.execute("SELECT * FROM accounts WHERE token=?", (tok,)).fetchone()
    con.close()
    if not row:
        raise HTTPException(401, "invalid token")
    return dict(row)


def admin(x_admin_key: str = Header(default="")) -> None:
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(403, "admin key required")


def idem_get(key: str | None) -> dict | None:
    if not key:
        return None
    con = db()
    row = con.execute("SELECT response FROM idem WHERE key=?", (key,)).fetchone()
    con.close()
    return json.loads(row["response"]) if row else None


def idem_put(key: str | None, resp: dict) -> None:
    if key:
        con = db()
        con.execute("INSERT OR IGNORE INTO idem VALUES (?,?)", (key, json.dumps(resp)))
        con.commit()
        con.close()


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "sim_time": sim_iso(now_sim()), "policy_version": policy()["version"], "jobs": len(all_jobs())}


@app.get("/policy")
def get_policy() -> dict:
    return policy()


@app.get("/me")
def me(acc: dict = Depends(account)) -> dict:
    return {"name": acc["name"], "persona": acc["persona"], "connects": acc["connects"]}


@app.get("/me/connects")
def my_connects(acc: dict = Depends(account)) -> dict:
    return {"balance": acc["connects"]}


@app.get("/jobs")
def search_jobs(acc: dict = Depends(account), q: str = "", category: str = "", posted_after: str = "",
                limit: int = Query(20, le=100), offset: int = 0) -> dict:
    t = now_sim()
    rows = [j for j in all_jobs().values() if j.get("posted_at_offset_min", 0) <= t]
    if q:
        terms = q.lower().split()
        rows = [j for j in rows if all(w in (j["title"] + " " + j["description"]).lower() for w in terms)]
    if category:
        rows = [j for j in rows if j.get("category") == category]
    if posted_after:
        rows = [j for j in rows if sim_iso(j.get("posted_at_offset_min", 0)) > posted_after]
    rows.sort(key=lambda j: -j.get("posted_at_offset_min", 0))
    return {"total": len(rows), "jobs": [public_job(j) for j in rows[offset:offset + limit]]}


@app.get("/jobs/{job_id}")
def get_job(job_id: str, acc: dict = Depends(account)) -> dict:
    j = all_jobs().get(job_id)
    if not j or j.get("posted_at_offset_min", 0) > now_sim():
        raise HTTPException(404, "job not found")
    return public_job(j)


@app.get("/clients/{client_id}")
def get_client(client_id: str, acc: dict = Depends(account)) -> dict:
    c = CLIENTS.get(client_id)
    if not c:
        raise HTTPException(404, "client not found")
    return public_client(c)


class ProposalIn(BaseModel):
    job_id: str
    cover_letter: str = Field(min_length=1, max_length=5000)
    bid_amount: float = Field(gt=0)
    screening_answers: list[str] = []
    ai_assisted: bool | None = None
    dry_run: bool = False


@app.post("/proposals")
def create_proposal(body: ProposalIn, acc: dict = Depends(account),
                    idempotency_key: str | None = Header(default=None)) -> dict:
    if (cached := idem_get(idempotency_key)) is not None:
        return cached
    job = all_jobs().get(body.job_id)
    if not job:
        raise HTTPException(404, "job not found")
    cost = connects_cost(policy(), job, CLIENTS.get(job["client_id"], {}))
    preview = {"job_id": body.job_id, "cover_letter": body.cover_letter, "bid_amount": body.bid_amount,
               "screening_answers": body.screening_answers, "connects_cost_on_submit": cost,
               "connects_balance": acc["connects"], "policy_version": policy()["version"]}
    if body.dry_run:
        return {"dry_run": True, "would_create": preview}
    pid = "pr_" + uuid.uuid4().hex[:10]
    with _lock:
        con = db()
        con.execute("INSERT INTO proposals VALUES (?,?,?,?,?,?,?,?)",
                    (pid, acc["token"], body.job_id, "draft", body.model_dump_json(), 0, now_sim(), None))
        con.commit()
        con.close()
    resp = {"id": pid, "status": "draft", **preview}
    idem_put(idempotency_key, resp)
    return resp


class SubmitIn(BaseModel):
    dry_run: bool = False
    ai_assisted: bool | None = None


def _schedule_outcome(con: sqlite3.Connection, token: str, pid: str, job: dict, body: dict) -> None:
    client = dict(CLIENTS.get(job["client_id"], {}))
    client["hidden_prefs"] = {**client.get("hidden_prefs", {}), **job.get("_hidden", {})}
    d = decide(job=job, client=client, proposal_text=body["cover_letter"], bid_amount=body["bid_amount"],
               screening_answers=body.get("screening_answers"), skill_names=SKILL_NAMES)
    t = now_sim()

    def ev(kind: str, at: float, payload: dict | None = None) -> None:
        con.execute("INSERT INTO events (token,type,proposal_id,job_id,payload,visible_at) VALUES (?,?,?,?,?,?)",
                    (token, kind, pid, job["id"], json.dumps(payload or {}), at))

    if d.viewed:
        ev("viewed", t + 90)
    if d.replied:
        tid = "th_" + uuid.uuid4().hex[:10]
        con.execute("INSERT INTO threads VALUES (?,?,?,?,?,?)", (tid, token, job["id"], job["client_id"], pid, t + 360))
        rng = random.Random(pid)
        opener = rng.choice([
            ("question", "Thanks for the proposal. Could you tell me more about how you'd handle the first milestone?"),
            ("interview_request", "Your proposal stood out. Are you free for a 30-minute call this week?"),
            ("negotiation", "Interested, but our budget is tighter. Could you do it for 15% less?"),
        ])
        if CLIENTS.get(job["client_id"], {}).get("is_scam"):
            opener = ("scam_signal", "Great! Please add me on WhatsApp so we can discuss payment outside the site.")
        con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?)",
                    ("m_" + uuid.uuid4().hex[:10], tid, "client", opener[1], opener[0], t + 360))
        ev("replied", t + 360, {"thread_id": tid})
        if d.interview:
            ev("interview", t + 60 * 24, {"thread_id": tid})
        if d.hired:
            ev("hired", t + 60 * 72, {"thread_id": tid})
        elif d.interview:
            ev("lost", t + 60 * 96)
    else:
        ev("lost", t + 60 * 24 * 5)
    con.execute("INSERT INTO kv VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (f"decision:{pid}", json.dumps(d.__dict__)))


@app.post("/proposals/{pid}/submit")
def submit_proposal(pid: str, body: SubmitIn, acc: dict = Depends(account),
                    idempotency_key: str | None = Header(default=None)) -> dict:
    if (cached := idem_get(idempotency_key)) is not None:
        return cached
    pol = policy()
    with _lock:
        con = db()
        row = con.execute("SELECT * FROM proposals WHERE id=? AND token=?", (pid, acc["token"])).fetchone()
        if not row:
            con.close()
            raise HTTPException(404, "proposal not found")
        if row["status"] != "draft":
            con.close()
            return {"id": pid, "status": row["status"], "connects_spent": row["connects_spent"], "note": "already submitted"}
        pbody = json.loads(row["body"])
        job = all_jobs()[row["job_id"]]
        cost = connects_cost(pol, job, CLIENTS.get(job["client_id"], {}))
        ai_flag = body.ai_assisted if body.ai_assisted is not None else pbody.get("ai_assisted")
        if "ai_assisted" in pol["required_submission_fields"] and ai_flag is None:
            con.close()
            raise HTTPException(422, "policy v2: field ai_assisted is required on every proposal")
        if pol.get("max_submissions_per_hour"):
            n = con.execute("SELECT COUNT(*) c FROM proposals WHERE token=? AND submitted_sim>?",
                            (acc["token"], now_sim() - 60)).fetchone()["c"]
            if n >= pol["max_submissions_per_hour"]:
                con.close()
                raise HTTPException(429, f"policy v2: max {pol['max_submissions_per_hour']} submissions per hour")
        if body.dry_run:
            con.close()
            return {"dry_run": True, "would_submit": {"id": pid, "connects_cost": cost,
                                                      "balance_after": acc["connects"] - cost, **pbody}}
        if acc["connects"] < cost:
            con.close()
            raise HTTPException(402, f"not enough Connects: need {cost}, have {acc['connects']}")
        con.execute("UPDATE accounts SET connects=connects-? WHERE token=?", (cost, acc["token"]))
        con.execute("UPDATE proposals SET status='submitted', connects_spent=?, submitted_sim=? WHERE id=?",
                    (cost, now_sim(), pid))
        con.execute("INSERT INTO events (token,type,proposal_id,job_id,payload,visible_at) VALUES (?,?,?,?,?,?)",
                    (acc["token"], "submitted", pid, job["id"], "{}", now_sim()))
        _schedule_outcome(con, acc["token"], pid, job, pbody)
        con.commit()
        con.close()
    resp = {"id": pid, "status": "submitted", "connects_spent": cost, "balance": acc["connects"] - cost}
    idem_put(idempotency_key, resp)
    return resp


@app.get("/proposals")
def list_proposals(acc: dict = Depends(account)) -> dict:
    con = db()
    rows = con.execute("SELECT id, job_id, status, connects_spent FROM proposals WHERE token=? ORDER BY created_sim DESC",
                       (acc["token"],)).fetchall()
    con.close()
    return {"proposals": [dict(r) for r in rows]}


@app.get("/proposals/{pid}")
def get_proposal(pid: str, acc: dict = Depends(account)) -> dict:
    con = db()
    row = con.execute("SELECT * FROM proposals WHERE id=? AND token=?", (pid, acc["token"])).fetchone()
    con.close()
    if not row:
        raise HTTPException(404, "proposal not found")
    return {"id": row["id"], "job_id": row["job_id"], "status": row["status"], **json.loads(row["body"])}


@app.get("/events")
def list_events(acc: dict = Depends(account), after_seq: int = 0, limit: int = 200) -> dict:
    con = db()
    rows = con.execute("SELECT * FROM events WHERE token=? AND seq>? AND visible_at<=? ORDER BY seq LIMIT ?",
                       (acc["token"], after_seq, now_sim(), limit)).fetchall()
    con.close()
    return {"events": [{"seq": r["seq"], "type": r["type"], "proposal_id": r["proposal_id"], "job_id": r["job_id"],
                        "at": sim_iso(r["visible_at"]), **json.loads(r["payload"])} for r in rows]}


@app.get("/threads")
def list_threads(acc: dict = Depends(account)) -> dict:
    con = db()
    rows = con.execute("SELECT * FROM threads WHERE token=? AND created_sim<=? ORDER BY created_sim DESC",
                       (acc["token"], now_sim())).fetchall()
    con.close()
    return {"threads": [dict(r) for r in rows]}


@app.get("/threads/{tid}/messages")
def thread_messages(tid: str, acc: dict = Depends(account)) -> dict:
    con = db()
    th = con.execute("SELECT * FROM threads WHERE id=? AND token=?", (tid, acc["token"])).fetchone()
    if not th:
        con.close()
        raise HTTPException(404, "thread not found")
    rows = con.execute("SELECT * FROM messages WHERE thread_id=? AND visible_at<=? ORDER BY visible_at",
                       (tid, now_sim())).fetchall()
    con.close()
    return {"thread": dict(th), "messages": [{"id": r["id"], "sender": r["sender"], "text": r["text"],
                                              "at": sim_iso(r["visible_at"])} for r in rows]}


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    dry_run: bool = False


@app.post("/threads/{tid}/messages")
def send_message(tid: str, body: MessageIn, acc: dict = Depends(account),
                 idempotency_key: str | None = Header(default=None)) -> dict:
    if (cached := idem_get(idempotency_key)) is not None:
        return cached
    con = db()
    th = con.execute("SELECT * FROM threads WHERE id=? AND token=?", (tid, acc["token"])).fetchone()
    if not th:
        con.close()
        raise HTTPException(404, "thread not found")
    if body.dry_run:
        con.close()
        return {"dry_run": True, "would_send": {"thread_id": tid, "text": body.text}}
    mid = "m_" + uuid.uuid4().hex[:10]
    t = now_sim()
    with _lock:
        con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?)", (mid, tid, "freelancer", body.text, None, t))
        rng = random.Random(mid)
        follow = rng.choice(["Thanks, that works. Let's lock in the call.",
                             "Sounds good. Can you share a rough milestone plan?",
                             "Great, I'll send the contract offer shortly."])
        con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?)",
                    ("m_" + uuid.uuid4().hex[:10], tid, "client", follow, "question", t + 120))
        con.commit()
        con.close()
    resp = {"id": mid, "status": "sent"}
    idem_put(idempotency_key, resp)
    return resp


# ---------------------------------------------------------------------------
# admin (grading + evals)
# ---------------------------------------------------------------------------
@app.post("/admin/reset", dependencies=[Depends(admin)])
def admin_reset() -> dict:
    init_db(reset=True)
    EXTRA_JOBS.clear()
    _rate.clear()
    return {"ok": True}


class ClockIn(BaseModel):
    advance_minutes: float


@app.post("/admin/clock", dependencies=[Depends(admin)])
def admin_clock(body: ClockIn) -> dict:
    set_kv("offset_min", str(float(kv("offset_min")) + body.advance_minutes))
    return {"sim_time": sim_iso(now_sim())}


class PolicyIn(BaseModel):
    version: int


@app.post("/admin/policy", dependencies=[Depends(admin)])
def admin_policy(body: PolicyIn) -> dict:
    if body.version not in POLICIES:
        raise HTTPException(400, "unknown policy version")
    set_kv("policy", str(body.version))
    return POLICIES[body.version]


class AccountIn(BaseModel):
    token: str
    name: str
    persona: str = "custom"
    connects: int = START_CONNECTS


@app.post("/admin/accounts", dependencies=[Depends(admin)])
def admin_account(body: AccountIn) -> dict:
    con = db()
    con.execute("INSERT OR REPLACE INTO accounts VALUES (?,?,?,?)", (body.token, body.persona, body.name, body.connects))
    con.commit()
    con.close()
    return {"ok": True}


@app.post("/admin/jobs", dependencies=[Depends(admin)])
def admin_jobs(jobs: list[dict]) -> dict:
    for j in jobs:
        j.setdefault("posted_at_offset_min", now_sim())
        EXTRA_JOBS[j["id"]] = j
    return {"added": len(jobs)}


@app.get("/admin/outcomes", dependencies=[Depends(admin)])
def admin_outcomes(token: str | None = None) -> dict:
    con = db()
    q = "SELECT p.id, p.job_id, p.token, p.status FROM proposals p WHERE p.status='submitted'"
    rows = [dict(r) for r in con.execute(q).fetchall() if token is None or r["token"] == token]
    out = []
    for r in rows:
        d = con.execute("SELECT v FROM kv WHERE k=?", (f"decision:{r['id']}",)).fetchone()
        out.append({**r, "decision": json.loads(d["v"]) if d else None})
    con.close()
    n = len(out) or 1
    return {"n": len(out), "reply_rate": sum(1 for o in out if o["decision"] and o["decision"]["replied"]) / n,
            "hire_rate": sum(1 for o in out if o["decision"] and o["decision"]["hired"]) / n, "proposals": out}
