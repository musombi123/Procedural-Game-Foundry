"""Independent NEXORA account identity backed by NEXORA's Neon PostgreSQL database.

Passwords are PBKDF2-HMAC-SHA256 hashes. Opaque bearer tokens are stored only
as SHA-256 digests and can be revoked independently of RevelaCode sessions.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PASSWORD_ROUNDS = 310_000
_TOKEN_BYTES = 48


class NexoraIdentityUnavailable(RuntimeError):
    """The NEXORA identity database is not configured or reachable."""


def _database_url() -> str:
    # Do not silently fall back to a generic DATABASE_URL that may belong to
    # RevelaCode or another product. NEXORA identity and billing share this
    # explicitly named, product-owned database.
    return os.environ.get("NEXORA_DATABASE_URL", "").strip()


def _connect():
    url = _database_url()
    if not url:
        raise NexoraIdentityUnavailable(
            "NEXORA accounts are not available until NEXORA_DATABASE_URL is configured."
        )
    try:
        import psycopg
        return psycopg.connect(url)
    except ImportError as exc:
        raise NexoraIdentityUnavailable(
            "The PostgreSQL driver is missing from the NEXORA service."
        ) from exc
    except Exception as exc:
        raise NexoraIdentityUnavailable(
            "The NEXORA account database could not be reached."
        ) from exc


def ensure_identity_schema() -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS nexora_accounts (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS nexora_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES nexora_accounts(id) ON DELETE CASCADE,
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    revoked_at TIMESTAMPTZ
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_nexora_sessions_user ON nexora_sessions(user_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_nexora_sessions_expiry ON nexora_sessions(expires_at)"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS nexora_account_tour_progress (
                    user_id TEXT PRIMARY KEY REFERENCES nexora_accounts(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL DEFAULT 1,
                    completed BOOLEAN NOT NULL DEFAULT FALSE,
                    skipped BOOLEAN NOT NULL DEFAULT FALSE,
                    last_step INTEGER NOT NULL DEFAULT 0 CHECK (last_step >= 0),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PASSWORD_ROUNDS
    )
    return "pbkdf2_sha256$" + str(_PASSWORD_ROUNDS) + "$" + _b64(salt) + "$" + _b64(digest)


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds_text, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        rounds = int(rounds_text)
        if rounds < 100_000 or rounds > 1_000_000:
            return False
        expected = _unb64(digest_text)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), _unb64(salt_text), rounds
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, UnicodeError):
        return False


def _session_days() -> int:
    try:
        return max(1, min(90, int(os.environ.get("NEXORA_SESSION_DAYS", "30"))))
    except (TypeError, ValueError):
        return 30


def _issue_session(conn, user: dict[str, Any]) -> dict[str, Any]:
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=_session_days())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO nexora_sessions(token_hash, user_id, expires_at)
            VALUES (%s, %s, %s)
            """,
            (token_hash, user["id"], expires_at),
        )
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_at": expires_at.isoformat(),
        "user": user,
    }


def create_account(email: str, display_name: str, password: str) -> dict[str, Any]:
    ensure_identity_schema()
    conn = _connect()
    try:
        user = {
            "id": uuid4().hex,
            "email": email,
            "display_name": display_name,
        }
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO nexora_accounts(id, email, display_name, password_hash)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (email) DO NOTHING
                RETURNING id, email, display_name, created_at
                """,
                (user["id"], email, display_name, hash_password(password)),
            )
            row = cur.fetchone()
        if not row:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail="A NEXORA account already exists for this email address.",
            )
        user = {
            "id": row[0],
            "email": row[1],
            "display_name": row[2],
            "created_at": row[3].isoformat() if row[3] else None,
        }
        session = _issue_session(conn, user)
        conn.commit()
        return session
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise NexoraIdentityUnavailable(
            "The NEXORA account could not be created."
        ) from exc
    finally:
        conn.close()


def login_account(email: str, password: str) -> dict[str, Any]:
    ensure_identity_schema()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, email, display_name, password_hash, created_at
                FROM nexora_accounts
                WHERE email = %s AND is_active = TRUE
                """,
                (email,),
            )
            row = cur.fetchone()
        if not row or not verify_password(password, row[3]):
            raise HTTPException(status_code=401, detail="Email or password is incorrect.")
        user = {
            "id": row[0],
            "email": row[1],
            "display_name": row[2],
            "created_at": row[4].isoformat() if row[4] else None,
        }
        session = _issue_session(conn, user)
        conn.commit()
        return session
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise NexoraIdentityUnavailable(
            "NEXORA sign-in is temporarily unavailable."
        ) from exc
    finally:
        conn.close()


def verify_access_token(token: str) -> dict[str, Any] | None:
    token = str(token or "").strip()
    if not token or len(token) > 512:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.id, a.email, a.display_name, a.created_at
                FROM nexora_sessions s
                JOIN nexora_accounts a ON a.id = s.user_id
                WHERE s.token_hash = %s
                  AND s.revoked_at IS NULL
                  AND s.expires_at > NOW()
                  AND a.is_active = TRUE
                """,
                (token_hash,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "email": row[1],
            "display_name": row[2],
            "created_at": row[3].isoformat() if row[3] else None,
        }
    finally:
        conn.close()


def revoke_access_token(token: str) -> None:
    token = str(token or "").strip()
    if not token:
        return
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE nexora_sessions
                SET revoked_at = NOW()
                WHERE token_hash = %s AND revoked_at IS NULL
                """,
                (token_hash,),
            )
        conn.commit()
    finally:
        conn.close()


class RegistrationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=6, max_length=254)
    display_name: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        result = value.strip().lower()
        if not _EMAIL_RE.fullmatch(result):
            raise ValueError("Enter a valid email address.")
        return result

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str) -> str:
        result = " ".join(value.split())
        if len(result) < 2:
            raise ValueError("Enter a name with at least two characters.")
        return result


class LoginPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=6, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        result = value.strip().lower()
        if not _EMAIL_RE.fullmatch(result):
            raise ValueError("Enter a valid email address.")
        return result


def register_nexora_auth_routes(app: Any) -> None:
    router = APIRouter()

    @router.post("/api/v1/auth/register", status_code=201)
    def register_account_route(payload: RegistrationPayload):
        try:
            return create_account(payload.email, payload.display_name, payload.password)
        except NexoraIdentityUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post("/api/v1/auth/login")
    def login_account_route(payload: LoginPayload):
        try:
            return login_account(payload.email, payload.password)
        except NexoraIdentityUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/api/v1/auth/me")
    def current_account(request: Request):
        user = getattr(request.state, "nexora_user", None)
        if not user or user.get("id") == "local":
            raise HTTPException(status_code=401, detail="Sign in to your NEXORA account.")
        return {"user": user}


class TourProgressPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(default=1, ge=1, le=100)
    completed: bool = False
    skipped: bool = False
    last_step: int = Field(default=0, ge=0, le=100)

    @model_validator(mode="after")
    def finished_states_are_exclusive(self):
        if self.completed and self.skipped:
            raise ValueError("Tour progress cannot be both completed and skipped.")
        return self


def _account_id(request: Request) -> str:
    user = getattr(request.state, "nexora_user", None)
    if not user or user.get("id") == "local":
        raise HTTPException(status_code=401, detail="Sign in to your NEXORA account.")
    return str(user["id"])


def get_tour_progress(user_id: str) -> dict[str, Any]:
    ensure_identity_schema()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT version, completed, skipped, last_step, updated_at
                FROM nexora_account_tour_progress WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()
        if not row:
            return {"version": 1, "completed": False, "skipped": False, "last_step": 0}
        return {
            "version": row[0], "completed": row[1], "skipped": row[2],
            "last_step": row[3], "updated_at": row[4].isoformat() if row[4] else None,
        }
    finally:
        conn.close()


def save_tour_progress(user_id: str, payload: TourProgressPayload) -> dict[str, Any]:
    ensure_identity_schema()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO nexora_account_tour_progress(user_id, version, completed, skipped, last_step)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    version = EXCLUDED.version,
                    completed = EXCLUDED.completed,
                    skipped = EXCLUDED.skipped,
                    last_step = EXCLUDED.last_step,
                    updated_at = NOW()
                RETURNING version, completed, skipped, last_step, updated_at
                """,
                (user_id, payload.version, payload.completed, payload.skipped, payload.last_step),
            )
            row = cur.fetchone()
        conn.commit()
        return {
            "version": row[0], "completed": row[1], "skipped": row[2],
            "last_step": row[3], "updated_at": row[4].isoformat() if row[4] else None,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


    @router.get("/api/v1/profile/tour")
    def read_tour_progress(request: Request):
        try:
            return {"tour": get_tour_progress(_account_id(request))}
        except NexoraIdentityUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.put("/api/v1/profile/tour")
    def write_tour_progress(payload: TourProgressPayload, request: Request):
        try:
            return {"tour": save_tour_progress(_account_id(request), payload)}
        except NexoraIdentityUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post("/api/v1/auth/logout")
    def logout_account(
        authorization: str = Header(default="", alias="Authorization")
    ):
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(status_code=401, detail="A NEXORA session is required.")
        try:
            revoke_access_token(token.strip())
        except NexoraIdentityUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"logged_out": True}

    app.include_router(router)
