"""
Encryption for the one secret this project needs to persist somewhere
other than git: the home WiFi password (SETLIST_ADMIN_SPECIFICATION.md
section 5).

Deliberately not a Python crypto library (no `cryptography`, no `pip
install`) -- `openssl` is already present on Raspberry Pi OS, so this
shells out to it exactly the way `Player` shells out to `mpv` elsewhere
in this project, instead of adding a new dependency for one feature.

Key derivation: sha256(machine_id + usb_uuid). Both are readable by
anything that already has SSH access to this Pi with this USB inserted
-- the point isn't secrecy from a fully-compromised session, it's that
the encrypted file is useless if the USB alone is lost, copied, or
plugged into a different Pi (see the specification for the full
reasoning).
"""

import hashlib
import logging
import subprocess

logger = logging.getLogger(__name__)

MACHINE_ID_PATH = "/etc/machine-id"

# AES-256-CBC via openssl's PBKDF2-backed enc command -- not GCM: `openssl
# enc` (the CLI subcommand used here, as opposed to the lower-level EVP
# API) does not support AEAD ciphers at all ("AEAD ciphers not
# supported"), confirmed against the actual openssl binary while
# building this, not assumed from documentation. CBC has no built-in
# authentication tag the way GCM would, but that's an acceptable
# trade-off here: the threat this defends against is the credential file
# being useless if copied off this Pi/USB pairing (specification section
# 5), not tampering by someone who already has write access to the USB
# -- at that point they've already compromised more than this file.
# -iter kept explicit (not just relying on openssl's default) so a
# future openssl version changing its default doesn't silently change
# how existing encrypted files need to be decrypted.
_OPENSSL_CIPHER = "aes-256-cbc"
_PBKDF2_ITERATIONS = 200_000


class DecryptionError(Exception):
    """Raised when decryption fails -- wrong key (wrong Pi/USB pairing),
    corrupted file, or openssl itself is missing. Callers should treat
    this the same as "no home WiFi configured yet", not crash."""


def derive_key(machine_id: str, usb_uuid: str) -> str:
    """Returns a hex-encoded sha256 digest to use as the openssl
    passphrase. Takes the raw values rather than reading them itself,
    so this stays trivially unit-testable without a real
    /etc/machine-id or a real USB attached."""
    combined = f"{machine_id.strip()}:{usb_uuid.strip()}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def read_machine_id(path: str = MACHINE_ID_PATH) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def encrypt(plaintext: bytes, key: str) -> bytes:
    """Encrypts plaintext, returns the raw encrypted bytes (openssl's
    own salted/binary output -- nothing this project needs to parse,
    just store and hand back to decrypt())."""
    result = subprocess.run(
        [
            "openssl", "enc", f"-{_OPENSSL_CIPHER}", "-pbkdf2",
            "-iter", str(_PBKDF2_ITERATIONS),
            "-pass", f"pass:{key}",
        ],
        input=plaintext,
        capture_output=True,
        check=True,
    )
    return result.stdout


def decrypt(ciphertext: bytes, key: str) -> bytes:
    """Decrypts ciphertext produced by encrypt() with the same key.
    Raises DecryptionError on any failure -- wrong key, corrupted data,
    or an openssl version mismatch in cipher support -- rather than
    letting a raw CalledProcessError leak to callers that just want to
    know "is there a valid home WiFi config or not"."""
    try:
        result = subprocess.run(
            [
                "openssl", "enc", "-d", f"-{_OPENSSL_CIPHER}", "-pbkdf2",
                "-iter", str(_PBKDF2_ITERATIONS),
                "-pass", f"pass:{key}",
            ],
            input=ciphertext,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        logger.info("Decryption failed (expected if this Pi/USB pairing "
                    "never set a home WiFi, or it's a different pairing): %s",
                    stderr.strip())
        raise DecryptionError(stderr.strip()) from e
    except FileNotFoundError as e:
        raise DecryptionError("openssl is not installed") from e

    return result.stdout
