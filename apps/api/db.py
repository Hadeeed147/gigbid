"""Postgres access for the API and worker (read models, users, settings, audit).

Graph state itself lives in the LangGraph Postgres checkpointer; these tables
are fast read models for the UI. Every query is scoped by user_id (tenant, E4).
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from common.config import env

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, name TEXT NOT NULL,
  tenant TEXT NOT NULL, settings JSONB NOT NULL DEFAULT '{}'::jsonb, onboarded BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS saved_searches (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, query TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT '', interval_minutes INT NOT NULL DEFAULT 10, last_run TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS seen_jobs (
  user_id TEXT NOT NULL, job_id TEXT NOT NULL, fingerprint TEXT NOT NULL, seen_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (user_id, job_id));
CREATE INDEX IF NOT EXISTS seen_jobs_fp ON seen_jobs (user_id, fingerprint);
CREATE TABLE IF NOT EXISTS inbox (
  user_id TEXT NOT NULL, job_id TEXT NOT NULL, thread_id TEXT NOT NULL, title TEXT NOT NULL, category TEXT,
  status TEXT NOT NULL, action TEXT, fit REAL, risk REAL, is_scam BOOLEAN DEFAULT false, flags JSONB DEFAULT '[]',
  price JSONB, connects_cost INT, budget JSONB, reasons JSONB DEFAULT '[]', attention_reason TEXT,
  usage JSONB DEFAULT '{}', latency_s REAL, trace_id TEXT, trace_url TEXT, proposal_id TEXT,
  created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now(), PRIMARY KEY (user_id, job_id));
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, thread_id TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
  trace_id TEXT, trace_url TEXT, started_at TIMESTAMPTZ DEFAULT now(), finished_at TIMESTAMPTZ, error TEXT);
CREATE INDEX IF NOT EXISTS runs_thread ON runs (user_id, thread_id);
CREATE TABLE IF NOT EXISTS approvals (
  id BIGSERIAL PRIMARY KEY, user_id TEXT NOT NULL, thread_id TEXT NOT NULL, kind TEXT NOT NULL, action TEXT NOT NULL,
  reason TEXT, diff TEXT, at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS pipeline (
  user_id TEXT NOT NULL, proposal_id TEXT NOT NULL, job_id TEXT NOT NULL, title TEXT, category TEXT,
  stage TEXT NOT NULL, connects_spent INT DEFAULT 0, thread_id TEXT, updated_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (user_id, proposal_id));
CREATE TABLE IF NOT EXISTS conversations (
  user_id TEXT NOT NULL, thread_id TEXT NOT NULL, job_id TEXT, title TEXT, status TEXT NOT NULL,
  last_message TEXT, intent TEXT, updated_at TIMESTAMPTZ DEFAULT now(), PRIMARY KEY (user_id, thread_id));
CREATE TABLE IF NOT EXISTS cursors (user_id TEXT PRIMARY KEY, event_seq INT NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS system_status (k TEXT PRIMARY KEY, v JSONB NOT NULL, updated_at TIMESTAMPTZ DEFAULT now());
"""


@lru_cache(maxsize=1)
def pool() -> ConnectionPool:
    p = ConnectionPool(env("DATABASE_URL"), min_size=1, max_size=10, open=True,
                       kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": None})
    with p.connection() as c:
        c.execute(SCHEMA)
    return p


@contextmanager
def conn():
    with pool().connection() as c:
        yield c


def q(sql: str, params: tuple | dict = ()) -> list[dict]:
    with conn() as c:
        cur = c.execute(sql, params)
        return cur.fetchall() if cur.description else []


def one(sql: str, params: tuple | dict = ()) -> dict | None:
    rows = q(sql, params)
    return rows[0] if rows else None


def jb(v: Any) -> Jsonb:
    return Jsonb(json.loads(json.dumps(v, default=str)))


def set_status(key: str, value: dict) -> None:
    q("INSERT INTO system_status (k, v, updated_at) VALUES (%s,%s,now()) ON CONFLICT (k) DO UPDATE "
      "SET v=excluded.v, updated_at=now()", (key, jb(value)))


def get_status(key: str) -> dict | None:
    r = one("SELECT v, updated_at FROM system_status WHERE k=%s", (key,))
    return {**r["v"], "updated_at": r["updated_at"].isoformat()} if r else None
