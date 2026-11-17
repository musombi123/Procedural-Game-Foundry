from __future__ import annotations
import hmac, ipaddress, re, secrets
from dataclasses import dataclass, field

PACKAGE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\\.[A-Za-z][A-Za-z0-9_]*){1,7}$")
SERIAL = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

@dataclass
class PairingState:
    code: str = field(default_factory=lambda: f"{secrets.randbelow(100_000_000):08d}")
    token: str = field(default_factory=lambda: secrets.token_urlsafe(40))
    paired: bool = False
    failed_attempts: int = 0

    def pair(self, candidate: str) -> str | None:
        if self.paired or self.failed_attempts >= 5:
            return None
        if not hmac.compare_digest(str(candidate).strip(), self.code):
            self.failed_attempts += 1
            return None
        self.paired = True
        self.code = ""
        return self.token

    def authorize(self, candidate: str | None) -> bool:
        return bool(self.paired and candidate and hmac.compare_digest(candidate, self.token))

def validate_serial(value: str) -> str:
    serial = str(value or "").strip()
    if not SERIAL.fullmatch(serial):
        raise ValueError("Invalid ADB device serial.")
    return serial

def validate_package_id(value: str) -> str:
    package_id = str(value or "").strip()
    if not PACKAGE_ID.fullmatch(package_id):
        raise ValueError("Invalid Android package ID.")
    return package_id

def validate_private_pair_address(host: str, port: int) -> tuple[str, int]:
    address = ipaddress.ip_address(str(host).strip())
    if not address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified:
        raise ValueError("Wireless ADB pairing is limited to a private LAN address.")
    if not 1024 <= int(port) <= 65535:
        raise ValueError("ADB pairing port must be between 1024 and 65535.")
    return str(address), int(port)
