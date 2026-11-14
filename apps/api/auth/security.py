"""Users and sessions: bcrypt password hashes, short-lived JWT bearer tokens.
OAuth tokens for marketplaces are stored encrypted via common.token_store."""
from __future__ import annotations

import time
import uuid

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from apps.api import db
from common.config import env

_bearer = HTTPBearer(auto_error=False)
TTL = 60 * 60 * 12


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def check_password(pw: str, h: str) -> bool:
    return bcrypt.checkpw(pw.encode(), h.encode())


def issue_token(user_id: str) -> str:
    return jwt.encode({"sub": user_id, "exp": int(time.time()) + TTL}, env("JWT_SECRET"), algorithm="HS256")


def create_user(email: str, password: str, name: str, tenant: str | None = None, settings: dict | None = None) -> dict:
    uid = "u_" + uuid.uuid4().hex[:10]
    db.q("INSERT INTO users (id, email, password_hash, name, tenant, settings) VALUES (%s,%s,%s,%s,%s,%s)",
         (uid, email.lower(), hash_password(password), name, tenant or uid, db.jb(settings or {})))
    return db.one("SELECT * FROM users WHERE id=%s", (uid,))


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    if not cred:
        raise HTTPException(401, "not signed in")
    try:
        claims = jwt.decode(cred.credentials, env("JWT_SECRET"), algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(401, "invalid or expired session") from e
    user = db.one("SELECT id, email, name, tenant, settings, onboarded FROM users WHERE id=%s", (claims["sub"],))
    if not user:
        raise HTTPException(401, "user not found")
    return user
