"""
WiFi profile storage and application, for both setlist-admin (the web
app, when someone sets the home WiFi from the UI) and
setlist_network_watchdog (which reapplies profiles at boot -- see that
module and SETLIST_ADMIN_SPECIFICATION.md section 5).

Two profiles are tracked, both stored the same encrypted way on the USB
for consistency (section 5): "home" (the user's own network, optional)
and "hotspot" (the phone hotspot, this project's default/fallback).
NetworkManager itself is never treated as the source of truth for
either -- its own stored connections live under the read-only root
overlay and don't survive a reboot once changed after the overlay is
enabled (section 3, point 2), so this module's job is reapplying both
profiles to NetworkManager fresh every time, not just once.

All actual `nmcli`/connectivity calls are isolated into the small
`_run_nmcli`-based functions at the bottom, specifically so tests can
mock those and exercise the encryption/priority/decision logic without
touching real networking or requiring root.
"""

import json
import logging
import subprocess
from dataclasses import asdict, dataclass
from typing import Optional

from admin import crypto

logger = logging.getLogger(__name__)

NETWORK_CONFIG_FILENAME = ".setlist-admin/network.enc"

_HOME_CONNECTION_NAME = "setlist-admin-home"
_HOTSPOT_CONNECTION_NAME = "setlist-admin-hotspot"
_HOME_PRIORITY = 10   # higher number = preferred, per NetworkManager's own convention
_HOTSPOT_PRIORITY = 0  # always-available fallback


@dataclass(frozen=True)
class WifiProfile:
    ssid: str
    password: str


@dataclass(frozen=True)
class NetworkConfig:
    home: Optional[WifiProfile]
    hotspot: Optional[WifiProfile]

    def to_json(self) -> str:
        return json.dumps({
            "home": asdict(self.home) if self.home else None,
            "hotspot": asdict(self.hotspot) if self.hotspot else None,
        })

    @classmethod
    def from_json(cls, raw: str) -> "NetworkConfig":
        data = json.loads(raw)
        home = WifiProfile(**data["home"]) if data.get("home") else None
        hotspot = WifiProfile(**data["hotspot"]) if data.get("hotspot") else None
        return cls(home=home, hotspot=hotspot)


def load_config(path: str, key: str) -> Optional[NetworkConfig]:
    """Returns None if the file doesn't exist yet (first run -- no
    error) or fails to decrypt (wrong Pi/USB pairing, or corrupted --
    logged, not raised, since the watchdog needs to keep running either
    way and just fall back to hotspot-only)."""
    try:
        with open(path, "rb") as f:
            ciphertext = f.read()
    except OSError:
        return None

    try:
        plaintext = crypto.decrypt(ciphertext, key)
    except crypto.DecryptionError:
        logger.warning("%s exists but could not be decrypted with this "
                        "Pi/USB pairing's key", path)
        return None

    return NetworkConfig.from_json(plaintext.decode("utf-8"))


def save_config(path: str, key: str, config: NetworkConfig) -> None:
    """Caller is responsible for wrapping this in usb_mount.writable_usb()
    -- this function just writes to `path`, same as any other file
    write, deliberately not aware of mount state (see usb_mount.py's
    docstring for why that split exists)."""
    ciphertext = crypto.encrypt(config.to_json().encode("utf-8"), key)
    with open(path, "wb") as f:
        f.write(ciphertext)


# ---------------------------------------------------------------------------
# NetworkManager application
# ---------------------------------------------------------------------------

def apply_home_profile(profile: Optional[WifiProfile]) -> None:
    if profile is None:
        return
    _ensure_connection(_HOME_CONNECTION_NAME, profile, _HOME_PRIORITY)


def apply_hotspot_profile(profile: Optional[WifiProfile]) -> None:
    if profile is None:
        return
    _ensure_connection(_HOTSPOT_CONNECTION_NAME, profile, _HOTSPOT_PRIORITY)


def has_usable_ip() -> bool:
    """True if NetworkManager reports any interface as fully connected
    -- deliberately just "has an IP", not "has internet" (section 5,
    step 3): this is a local appliance, reachability on the local
    network is what matters, not whether that network can reach the
    wider internet."""
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "STATE", "general", "status"],
            capture_output=True, text=True, check=True, timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("Could not query NetworkManager state: %s", e)
        return False
    return result.stdout.strip() == "connected"


def active_connection_name() -> Optional[str]:
    """Which connection (if any) NetworkManager currently has active on
    a WiFi device -- used for logging/the admin UI's status display,
    not for any decision logic (NetworkManager's own priority handles
    that, per section 5, step 3)."""
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,DEVICE,TYPE", "connection", "show", "--active"],
            capture_output=True, text=True, check=True, timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("Could not query active connections: %s", e)
        return None

    for line in result.stdout.strip().splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[2] == "802-11-wireless":
            return parts[0]
    return None


def _ensure_connection(connection_name: str, profile: WifiProfile, priority: int) -> None:
    """Adds or updates a NetworkManager connection profile for `profile`,
    at the given autoconnect priority. Uses `nmcli connection modify`
    against a profile created with a fixed, predictable name
    (_HOME_CONNECTION_NAME/_HOTSPOT_CONNECTION_NAME) rather than letting
    nmcli name it after the SSID, so re-running this (every boot, or
    whenever the app updates the home network) always updates the same
    profile instead of accumulating duplicates."""
    exists = subprocess.run(
        ["nmcli", "-t", "-f", "NAME", "connection", "show"],
        capture_output=True, text=True, timeout=10,
    ).stdout.splitlines()

    if connection_name not in exists:
        subprocess.run(
            [
                "nmcli", "connection", "add", "type", "wifi",
                "con-name", connection_name, "ifname", "*",
                "ssid", profile.ssid,
            ],
            capture_output=True, check=True, timeout=15,
        )

    subprocess.run(
        [
            "nmcli", "connection", "modify", connection_name,
            "wifi-sec.key-mgmt", "wpa-psk",
            "wifi-sec.psk", profile.password,
            "connection.autoconnect", "yes",
            "connection.autoconnect-priority", str(priority),
        ],
        capture_output=True, check=True, timeout=15,
    )
    logger.info("Applied WiFi profile %s (priority %d)", connection_name, priority)
