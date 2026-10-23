"""Password hashing, signed expiring bearer tokens, and tenant-aware auth."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from db import get_db
from models import User

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
_configured_secret = os.getenv("SECRET_KEY", "")
if APP_ENV in {"production", "prod"} and (
    len(_configured_secret) < 32
    or any(word in _configured_secret.lower() for word in ("replace-with", "change-me", "example", "placeholder"))
):
    raise RuntimeError("Production requires a unique SECRET_KEY with at least 32 characters; do not use a placeholder.")
SECRET_KEY = os.getenv("SECRET_KEY", "local-development-secret-change-before-deploy").encode("utf-8")
try:
    _token_ttl_hours = int(os.getenv("TOKEN_TTL_HOURS", "12"))
except ValueError as exc:
    raise RuntimeError("TOKEN_TTL_HOURS must be an integer between 1 and 168") from exc
if not 1 <= _token_ttl_hours <= 168:
    raise RuntimeError("TOKEN_TTL_HOURS must be an integer between 1 and 168")
TOKEN_TTL_HOURS = _token_ttl_hours
PASSWORD_ITERATIONS = 310_000
MIN_ACCEPTED_PASSWORD_ITERATIONS = 100_000
MAX_ACCEPTED_PASSWORD_ITERATIONS = 1_000_000


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${_b64url(salt)}${_b64url(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        rounds = int(iterations)
        if not MIN_ACCEPTED_PASSWORD_ITERATIONS <= rounds <= MAX_ACCEPTED_PASSWORD_ITERATIONS:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _unb64url(salt), rounds)
        return hmac.compare_digest(_b64url(actual), expected)
    except (ValueError, TypeError):
        return False


def create_access_token(user: User) -> str:
    now = int(time.time())
    payload = {"sub": user.id, "org": user.organization_id, "iat": now, "exp": now + TOKEN_TTL_HOURS * 3600}
    encoded_payload = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signed = f"v1.{encoded_payload}".encode("ascii")
    signature = _b64url(hmac.new(SECRET_KEY, signed, hashlib.sha256).digest())
    return f"v1.{encoded_payload}.{signature}"


def read_access_token(token: str) -> dict[str, Any]:
    try:
        version, payload, signature = token.split(".", 2)
        if version != "v1":
            raise ValueError("unsupported token")
        signed = f"{version}.{payload}".encode("ascii")
        expected = _b64url(hmac.new(SECRET_KEY, signed, hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        data = json.loads(_unb64url(payload))
        if int(data.get("exp", 0)) <= int(time.time()):
            raise ValueError("expired token")
        if not isinstance(data.get("sub"), int) or not isinstance(data.get("org"), int):
            raise ValueError("invalid claims")
        return data
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired. Please log in again.") from exc


def get_current_user(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Please log in to continue")
    claims = read_access_token(authorization.split(" ", 1)[1].strip())
    user = db.get(User, claims["sub"])
    if user is None or user.organization_id != claims["org"]:
        raise HTTPException(status_code=401, detail="Session is no longer valid")
    return user
