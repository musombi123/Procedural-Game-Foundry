"""Google Drive OAuth for the local NEXORA agent.

Refresh tokens are stored only in the operating-system credential vault through
Python keyring. Access tokens and pending PKCE state remain in process memory.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


_SERVICE = "NEXORA Desktop Studio"
_SCOPE = "https://www.googleapis.com/auth/drive.file"
_REDIRECT_URI = "http://127.0.0.1:8765/drive/oauth/callback"
_PENDING: dict[str, dict[str, Any]] = {}
_ACCESS: dict[str, tuple[str, float]] = {}
_LOCK = threading.RLock()


def _keyring():
    try:
        import keyring
        backend = keyring.get_keyring()
        priority = getattr(backend, "priority", 0)
        if not priority:
            return None, "No supported operating-system credential vault is available."
        return keyring, None
    except Exception as exc:
        return None, str(exc)[:240]


def _client_config() -> tuple[str, str | None]:
    client_id = os.environ.get("NEXORA_GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("NEXORA_GOOGLE_OAUTH_CLIENT_SECRET", "").strip() or None
    if not client_id:
        raise RuntimeError("Set NEXORA_GOOGLE_OAUTH_CLIENT_ID to a Google OAuth Desktop client ID.")
    return client_id, client_secret


def drive_status(user_id: str) -> dict:
    client_id = os.environ.get("NEXORA_GOOGLE_OAUTH_CLIENT_ID", "").strip()
    keyring, error = _keyring()
    connected = False
    if keyring:
        try:
            connected = bool(keyring.get_password(_SERVICE, "refresh:" + str(user_id)))
        except Exception as exc:
            error = str(exc)[:240]
    return {
        "configured": bool(client_id),
        "credential_vault_ready": keyring is not None,
        "credential_vault_error": error,
        "connected": connected,
        "scope": _SCOPE,
        "storage": "operating_system_credential_vault",
    }


def begin_drive_oauth(user_id: str) -> str:
    client_id, _ = _client_config()
    keyring, error = _keyring()
    if not keyring:
        raise RuntimeError("Google Drive backup requires a supported OS credential vault: " + str(error))
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    state = secrets.token_urlsafe(32)
    with _LOCK:
        _PENDING[state] = {
            "user_id": str(user_id), "verifier": verifier,
            "created_at": time.time(),
        }
    query = urlencode({
        "client_id": client_id,
        "redirect_uri": _REDIRECT_URI,
        "response_type": "code",
        "scope": _SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return "https://accounts.google.com/o/oauth2/v2/auth?" + query


def finish_drive_oauth(code: str, state: str) -> dict:
    with _LOCK:
        pending = _PENDING.pop(str(state), None)
    if not pending or time.time() - pending["created_at"] > 600:
        raise RuntimeError("The Google authorization state is invalid or expired. Start Drive connection again.")
    client_id, client_secret = _client_config()
    fields = {
        "client_id": client_id,
        "code": code,
        "code_verifier": pending["verifier"],
        "grant_type": "authorization_code",
        "redirect_uri": _REDIRECT_URI,
    }
    if client_secret:
        fields["client_secret"] = client_secret
    request = Request(
        "https://oauth2.googleapis.com/token",
        data=urlencode(fields).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            token = json.loads(response.read(128 * 1024).decode("utf-8"))
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise RuntimeError("Google token exchange failed. Check the OAuth client and local network connection.") from exc
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("Google did not return a refresh token. Revoke the NEXORA grant in Google Account permissions and connect again.")
    keyring, error = _keyring()
    if not keyring:
        raise RuntimeError("Cannot safely store the Google refresh token: " + str(error))
    user_id = str(pending["user_id"])
    keyring.set_password(_SERVICE, "refresh:" + user_id, refresh_token)
    access_token = token.get("access_token")
    expires_in = int(token.get("expires_in") or 3600)
    if access_token:
        with _LOCK:
            _ACCESS[user_id] = (access_token, time.time() + max(60, expires_in - 90))
    return {"connected": True, "scope": token.get("scope") or _SCOPE}


def drive_access_token(user_id: str) -> str:
    with _LOCK:
        cached = _ACCESS.get(str(user_id))
        if cached and cached[1] > time.time():
            return cached[0]
    keyring, error = _keyring()
    if not keyring:
        raise RuntimeError("The operating-system credential vault is unavailable: " + str(error))
    refresh_token = keyring.get_password(_SERVICE, "refresh:" + str(user_id))
    if not refresh_token:
        raise RuntimeError("Google Drive is not connected for this NEXORA account.")
    client_id, client_secret = _client_config()
    fields = {"client_id": client_id, "refresh_token": refresh_token, "grant_type": "refresh_token"}
    if client_secret:
        fields["client_secret"] = client_secret
    request = Request(
        "https://oauth2.googleapis.com/token",
        data=urlencode(fields).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            token = json.loads(response.read(128 * 1024).decode("utf-8"))
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise RuntimeError("Google Drive access-token refresh failed.") from exc
    value = token.get("access_token")
    if not value:
        raise RuntimeError("Google did not return an access token.")
    with _LOCK:
        _ACCESS[str(user_id)] = (value, time.time() + max(60, int(token.get("expires_in") or 3600) - 90))
    return value


def disconnect_drive(user_id: str) -> None:
    keyring, error = _keyring()
    if not keyring:
        raise RuntimeError("The operating-system credential vault is unavailable: " + str(error))
    try:
        keyring.delete_password(_SERVICE, "refresh:" + str(user_id))
    except Exception:
        pass
    with _LOCK:
        _ACCESS.pop(str(user_id), None)
