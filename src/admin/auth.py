"""
PIN-based auth for the setlist-admin web app, reused unchanged from the
earlier WiFi design (SETLIST_ADMIN_USB_SPECIFICATION.md section 7: a
single shared PIN, not per-user accounts).

Standard library only: `hashlib`/`hmac`/`secrets`, the same way the rest
of this project avoids new dependencies. The PIN itself is never stored
-- only a salted hash (`PinRecord`), so reading `pin.hash` off the USB
never recovers the actual PIN.

Session tokens are HMAC-signed, not just random -- verify_session() can
check a token is genuinely one this server issued without keeping every
issued token in memory, which matters because this process can be
stopped and restarted by setlist-network-watchdog.service at any time
(section 5, step 4) and shouldn't need a persisted session store to
survive that.
"""

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

_SALT_BYTES = 16
_HASH_ITERATIONS = 200_000
_SESSION_TTL_SECONDS = 8 * 60 * 60  # a rehearsal/show-prep session, not a persistent login


@dataclass(frozen=True)
class PinRecord:
    """What gets written to/read from .setlist-admin/pin.hash. Plain
    text (colon-separated hex fields) -- it's a salted hash, not a
    secret, so it doesn't need crypto.py's encryption."""
    salt_hex: str
    hash_hex: str

    def to_line(self) -> str:
        return f"{self.salt_hex}:{self.hash_hex}"

    @classmethod
    def from_line(cls, line: str) -> "PinRecord":
        salt_hex, hash_hex = line.strip().split(":", 1)
        return cls(salt_hex=salt_hex, hash_hex=hash_hex)


def hash_pin(pin: str) -> PinRecord:
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", pin.encode("utf-8"), salt, _HASH_ITERATIONS
    )
    return PinRecord(salt_hex=salt.hex(), hash_hex=digest.hex())


def verify_pin(pin: str, record: PinRecord) -> bool:
    salt = bytes.fromhex(record.salt_hex)
    digest = hashlib.pbkdf2_hmac(
        "sha256", pin.encode("utf-8"), salt, _HASH_ITERATIONS
    )
    # Constant-time compare -- this is a login check, don't leak timing
    # information about how much of the hash matched.
    return hmac.compare_digest(digest.hex(), record.hash_hex)


class SessionManager:
    """Issues and verifies HMAC-signed session tokens. `secret_key`
    should be generated once (secrets.token_bytes) and persisted
    alongside pin.hash -- if it changes, every existing session is
    invalidated, which is the correct behavior after a PIN reset
    (section 5a): losing the PIN and resetting it should also log out
    anyone with an old session, not just block new logins."""

    def __init__(self, secret_key: bytes, ttl_seconds: int = _SESSION_TTL_SECONDS):
        self._secret_key = secret_key
        self._ttl_seconds = ttl_seconds

    def issue(self) -> str:
        issued_at = int(time.time())
        payload = str(issued_at)
        signature = self._sign(payload)
        return f"{payload}.{signature}"

    def verify(self, token: str) -> bool:
        try:
            payload, signature = token.split(".", 1)
            issued_at = int(payload)
        except (ValueError, AttributeError):
            return False

        if not hmac.compare_digest(signature, self._sign(payload)):
            return False

        return (time.time() - issued_at) <= self._ttl_seconds

    def _sign(self, payload: str) -> str:
        return hmac.new(
            self._secret_key, payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
