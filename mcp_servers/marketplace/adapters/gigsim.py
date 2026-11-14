"""GigSim adapter: REST client with timeouts, bounded retries with backoff,
Retry-After handling for 429s and a clear MarketplaceUnavailable after retries."""
from __future__ import annotations

import time
from typing import Any

import httpx

from agent.marketplace_port import ClientHistory, Job, MarketplaceRejected, MarketplaceUnavailable
from common import token_store
from common.config import cfg, env

SEED_TOKENS = {"ai_ml": "gs_ai_ml", "fullstack": "gs_fullstack", "data_analyst": "gs_data_analyst"}


class GigSimAdapter:
    name = "gigsim"

    def __init__(self, base_url: str | None = None, http: httpx.Client | None = None):
        self.base = (base_url or cfg("marketplace.gigsim_url") or env("GIGSIM_URL") or "http://localhost:8100").rstrip("/")
        # `http` lets tests inject an in-process client (FastAPI TestClient is an httpx.Client)
        self.http = http or httpx.Client(base_url=self.base, timeout=cfg("node_runtime.timeout_s", 60) / 3)
        self.max_retries = cfg("node_runtime.max_retries", 2) + 1
        self.backoff = cfg("node_runtime.backoff_base_s", 1.5)

    # -- auth: per-user GigSim token from the encrypted store; personas use seeded accounts
    def _token(self, user: str) -> str:
        stored = None
        try:
            stored = token_store.get(user, "gigsim")
        except Exception:
            stored = None
        if stored:
            return stored["token"] if isinstance(stored, dict) else stored
        persona = user.split(":", 1)[-1]
        return SEED_TOKENS.get(persona, SEED_TOKENS.get(user, user))

    def _req(self, user: str, method: str, path: str, *, json: dict | None = None, params: dict | None = None,
             idem: str | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self._token(user)}"}
        if idem:
            headers["Idempotency-Key"] = idem
        last = None
        for attempt in range(self.max_retries):
            try:
                r = self.http.request(method, path, json=json, params=params, headers=headers)
            except httpx.HTTPError as e:
                last = str(e)
                time.sleep(self.backoff ** attempt)
                continue
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", self.backoff ** (attempt + 1)))
                if "policy" in r.text:
                    raise MarketplaceRejected(429, r.json().get("detail", r.text))
                time.sleep(min(wait, 10))
                last = "rate limited"
                continue
            if r.status_code >= 500:
                last = f"{r.status_code} {r.text[:100]}"
                time.sleep(self.backoff ** attempt)
                continue
            if r.status_code >= 400:
                detail = r.json().get("detail", r.text) if r.headers.get("content-type", "").startswith(
                    "application/json") else r.text
                raise MarketplaceRejected(r.status_code, str(detail))
            return r.json()
        raise MarketplaceUnavailable(f"GigSim unavailable after {self.max_retries} attempts: {last}")

    # -- read
    def search_jobs(self, user, query="", category="", posted_after="", limit=20):
        data = self._req(user, "GET", "/jobs", params={"q": query, "category": category,
                                                       "posted_after": posted_after, "limit": limit})
        return [Job(**j) for j in data["jobs"]]

    def get_job(self, user, job_id):
        return Job(**self._req(user, "GET", f"/jobs/{job_id}"))

    def get_client_history(self, user, client_id):
        return ClientHistory(**self._req(user, "GET", f"/clients/{client_id}"))

    def get_connects_balance(self, user):
        return int(self._req(user, "GET", "/me/connects")["balance"])

    def get_policy(self, user):
        return self._req(user, "GET", "/policy")

    def list_threads(self, user):
        return self._req(user, "GET", "/threads")["threads"]

    def list_messages(self, user, thread_id):
        return self._req(user, "GET", f"/threads/{thread_id}/messages")["messages"]

    def list_events(self, user, after_seq=0):
        return self._req(user, "GET", "/events", params={"after_seq": after_seq})["events"]

    # -- write
    def create_proposal_draft(self, user, job_id, cover_letter, bid_amount, screening_answers, idempotency_key,
                              dry_run, extra=None):
        body = {"job_id": job_id, "cover_letter": cover_letter, "bid_amount": bid_amount,
                "screening_answers": screening_answers, "dry_run": dry_run, **(extra or {})}
        return self._req(user, "POST", "/proposals", json=body, idem=None if dry_run else idempotency_key)

    def submit_proposal(self, user, proposal_id, idempotency_key, dry_run, extra=None):
        return self._req(user, "POST", f"/proposals/{proposal_id}/submit", json={"dry_run": dry_run, **(extra or {})},
                         idem=None if dry_run else idempotency_key)

    def send_message(self, user, thread_id, text, idempotency_key, dry_run):
        return self._req(user, "POST", f"/threads/{thread_id}/messages", json={"text": text, "dry_run": dry_run},
                         idem=None if dry_run else idempotency_key)
