"""Short-lived bearer-token authority for the NEXORA desktop agent.

Tokens exist only in process memory and are invalidated when the local agent
restarts. A token is issued only after the signed-in NEXORA account is verified
and the user explicitly approves connecting this computer.
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass


ACCESS_TOKEN_TTL_SECONDS = 12 * 60 * 60


@dataclass(frozen=True)
class LocalPrincipal:
    user_id: str
    expires_at: float
    cloud_access_token: str | None = None


class PairingAuthority:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tokens: dict[str, LocalPrincipal] = {}

    def issue(
        self,
        user_id: str,
        cloud_access_token: str,
    ) -> tuple[str, int]:
        """Issue a local session for an already verified, explicitly approved account."""
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            raise ValueError("A verified NEXORA account is required.")
        if not isinstance(cloud_access_token, str) or len(cloud_access_token) < 20:
            raise ValueError("A verified NEXORA account session is required.")
        with self._lock:
            token = secrets.token_urlsafe(40)
            expires_at = time.time() + ACCESS_TOKEN_TTL_SECONDS
            self._tokens[self._digest(token)] = LocalPrincipal(
                user_id=normalized_user_id,
                expires_at=expires_at,
                cloud_access_token=cloud_access_token,
            )
            return token, int(expires_at)

    def resolve(self, token: str) -> LocalPrincipal | None:
        if not token:
            return None
        digest = self._digest(token)
        with self._lock:
            principal = self._tokens.get(digest)
            if not principal:
                return None
            if time.time() >= principal.expires_at:
                self._tokens.pop(digest, None)
                return None
            return principal

    def revoke(self, token: str) -> bool:
        if not token:
            return False
        with self._lock:
            return self._tokens.pop(self._digest(token), None) is not None

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()


_authority = PairingAuthority()


def get_pairing_authority() -> PairingAuthority:
    return _authority


def verify_local_access_token(token: str) -> LocalPrincipal | None:
    return _authority.resolve(token)


def get_cloud_access_token(user_id: str) -> str | None:
    """Return the paired account credential from memory only."""
    with _authority._lock:
        for principal in _authority._tokens.values():
            if principal.user_id == str(user_id) and principal.expires_at > time.time():
                return principal.cloud_access_token
    return None
