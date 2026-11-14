"""Encrypted per-user secret store (OAuth tokens, marketplace tokens).

Values are encrypted with Fernet (TOKEN_ENCRYPTION_KEY) before they touch disk
or the database and are never logged. Backend: Postgres table `user_secrets`
when DATABASE_URL is reachable, otherwise an encrypted JSON file (dev/tests).
"""
from __future__ import annotations

import json
import threading
from functools import lru_cache

from cryptography.fernet import Fernet

from common.config import ROOT, env

_FILE = ROOT / "data" / "processed" / "secrets.enc.json"
_lock = threading.Lock()


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = env("TOKEN_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is not set")
    return Fernet(key.encode())


def _pg():
    url = env("DATABASE_URL")
    if not url or env("GIGBID_SECRETS_BACKEND") == "file":
        return None
    try:
        import psycopg
        conn = psycopg.connect(url, connect_timeout=2, autocommit=True)
        conn.execute("CREATE TABLE IF NOT EXISTS user_secrets (user_id TEXT, provider TEXT, ciphertext TEXT, "
                     "updated_at TIMESTAMPTZ DEFAULT now(), PRIMARY KEY (user_id, provider))")
        return conn
    except Exception:
        return None


def put(user_id: str, provider: str, value: dict | str) -> None:
    ct = _fernet().encrypt(json.dumps(value).encode()).decode()
    conn = _pg()
    if conn:
        with conn:
            conn.execute("INSERT INTO user_secrets (user_id, provider, ciphertext) VALUES (%s,%s,%s) "
                         "ON CONFLICT (user_id, provider) DO UPDATE SET ciphertext=excluded.ciphertext, "
                         "updated_at=now()", (user_id, provider, ct))
        return
    with _lock:
        data = json.loads(_FILE.read_text()) if _FILE.exists() else {}
        data[f"{user_id}|{provider}"] = ct
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(data))


def get(user_id: str, provider: str):
    conn = _pg()
    ct = None
    if conn:
        with conn:
            row = conn.execute("SELECT ciphertext FROM user_secrets WHERE user_id=%s AND provider=%s",
                               (user_id, provider)).fetchone()
            ct = row[0] if row else None
    elif _FILE.exists():
        ct = json.loads(_FILE.read_text()).get(f"{user_id}|{provider}")
    if not ct:
        return None
    return json.loads(_fernet().decrypt(ct.encode()))


def delete(user_id: str, provider: str) -> None:
    conn = _pg()
    if conn:
        with conn:
            conn.execute("DELETE FROM user_secrets WHERE user_id=%s AND provider=%s", (user_id, provider))
        return
    with _lock:
        if _FILE.exists():
            data = json.loads(_FILE.read_text())
            data.pop(f"{user_id}|{provider}", None)
            _FILE.write_text(json.dumps(data))
