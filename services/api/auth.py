"""RevelaCode session verification for independent NEXORA ownership.

NEXORA never trusts a user ID supplied by the browser. It forwards the bearer
credential to RevelaCode's existing /api/auth/me endpoint and only accepts the
canonical identity returned by that authenticated service.
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import Depends, Header, HTTPException


def _identity_url() -> str:
    value = os.getenv("PGF_IDENTITY_INTROSPECTION_URL", "").strip()
    if not value:
        raise HTTPException(
            status_code=503,
            detail="NEXORA identity verification is not configured.",
        )
    return value


def _canonical_profile(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    # A profile-shaped error response is not an authenticated identity. Keep
    # the NEXORA trust boundary fail-closed even if an upstream error payload
    # accidentally includes cached user fields.
    if (
        payload.get("success") is False
        or payload.get("ok") is False
        or payload.get("authenticated") is False
        or payload.get("error") is not None
    ):
        return None
    candidates = [
        payload.get("user"),
        payload.get("data", {}).get("user") if isinstance(payload.get("data"), dict) else None,
        payload.get("account"),
        payload.get("data") if isinstance(payload.get("data"), dict) else None,
        payload,
    ]
    for profile in candidates:
        if isinstance(profile, dict):
            identity = str(
                profile.get("id")
                or profile.get("_id")
                or profile.get("user_id")
                or profile.get("userId")
                or ""
            ).strip()
            if identity and len(identity) <= 128:
                return {
                    "id": identity,
                    "name": str(profile.get("full_name") or profile.get("fullName") or profile.get("name") or "")[:160],
                }
    return None


def verify_identity_token(authorization: str | None) -> dict[str, str]:
    value = str(authorization or "").strip()
    scheme, _, token = value.partition(" ")
    if scheme.casefold() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="A valid RevelaCode bearer session is required.")

    try:
        response = httpx.get(
            _identity_url(),
            headers={"Authorization": f"Bearer {token.strip()}", "Accept": "application/json"},
            timeout=httpx.Timeout(15.0, connect=4.0),
            follow_redirects=False,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="RevelaCode identity verification is temporarily unavailable.") from exc

    if response.status_code in (401, 403):
        raise HTTPException(status_code=401, detail="The RevelaCode session is invalid or expired.")
    if response.status_code != 200:
        raise HTTPException(status_code=503, detail="RevelaCode identity verification failed.")

    try:
        profile = _canonical_profile(response.json())
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=503, detail="RevelaCode identity verification returned an invalid response.") from exc
    if not profile:
        raise HTTPException(status_code=401, detail="The identity service did not return a canonical user ID.")
    return profile


def current_principal(authorization: str | None = Header(default=None, alias="Authorization")) -> dict[str, str]:
    return verify_identity_token(authorization)
