"""Short-lived pairing and bearer-token authority for the NEXORA desktop agent.

Tokens exist only in process memory and are invalidated when the local agent
restarts. The one-time pairing code is displayed in the local terminal and is
never exposed by a read-only HTTP endpoint.
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass


PAIRING_CODE_TTL_SECONDS = 15 * 60
ACCESS_TOKEN_TTL_SECONDS = 12 * 60 * 60


@dataclass(frozen=True)
class LocalPrincipal:
    user_id: str
    expires_at: float


class PairingAuthority:
    def __init__(self, pairing_code: str | None = None) -> None:
        self._lock = threading.RLock()
        self._pairing_code = pairing_code or f"{secrets.randbelow(100_000_000):08d}"
        self._pairing_expires_at = time.time() + PAIRING_CODE_TTL_SECONDS
        self._tokens: dict[str, LocalPrincipal] = {}

    @property
    def pairing_code_for_terminal(self) -> str:
        return self._pairing_code

    @property
    def pairing_expires_at(self) -> float:
        return self._pairing_expires_at

    def exchange(self, supplied_code: str, user_id: str = "local-owner") -> tuple[str, int]:
        supplied = str(supplied_code or "")
        with self._lock:
            if not self._pairing_code or time.time() > self._pairing_expires_at:
                raise ValueError("The one-time pairing code has expired. Restart the local agent.")
            if not secrets.compare_digest(supplied, self._pairing_code):
                raise ValueError("The pairing code is invalid.")
            self._pairing_code = ""
            token = secrets.token_urlsafe(40)
            expires_at = time.time() + ACCESS_TOKEN_TTL_SECONDS
            self._tokens[self._digest(token)] = LocalPrincipal(
                user_id=str(user_id), expires_at=expires_at
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
