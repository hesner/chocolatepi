"""
Request handling logic for setlist-admin, kept separate from `server.py`'s
raw HTTP plumbing so it's testable by calling methods directly, with a
mocked filesystem/subprocess layer -- no real HTTP server, no real USB,
no real `nmcli` needed to exercise this (SETLIST_ADMIN_SPECIFICATION.md
section 8).

Every method that mutates the library wraps its single filesystem
operation in `self._writable_usb()` -- the rw window is exactly one
operation wide, never the whole request, matching section 6.
"""

import contextlib
import logging
import os
import subprocess
from dataclasses import dataclass
from typing import BinaryIO, Optional

from admin import auth, codec_check, crypto, library_ops, usb_mount, wifi

logger = logging.getLogger(__name__)

PIN_FILENAME = ".setlist-admin/pin.hash"
SESSION_KEY_FILENAME = ".setlist-admin/session.key"
_PEDAL_CORE_SERVICE_NAME = "pedal-core.service"


class ApiError(Exception):
    """Carries an HTTP status code alongside a user-facing message --
    server.py catches this and turns it into a JSON error response with
    that exact status/message, nothing translated or hidden."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class AdminConfig:
    usb_root: str
    mount_point: str = usb_mount.DEFAULT_MOUNT_POINT
    usb_uuid: str = ""


class AdminAPI:
    def __init__(self, config: AdminConfig):
        self.config = config
        self._sessions: Optional[auth.SessionManager] = None

    # -- Auth -----------------------------------------------------------

    def pin_path(self) -> str:
        return os.path.join(self.config.usb_root, PIN_FILENAME)

    def is_first_run(self) -> bool:
        # Real anomaly seen on hardware: the library USB has turned up
        # spontaneously unmounted, and without this check that just looks
        # like an empty USB -- "no pin.hash, must be first run" -- even
        # though a PIN really is set, just unreachable right now.
        try:
            usb_mount.ensure_mounted(self.config.mount_point)
        except usb_mount.RemountError as e:
            raise ApiError(503, "Library USB not detected -- check the physical connection and try again.") from e
        return not os.path.exists(self.pin_path())

    def set_pin(self, pin: str) -> None:
        """Used both for genuine first-run setup and for finishing a
        recovery (section 5a: once pin.hash is deleted over SSH, the app
        treats the next visit as first-run and this is what completes it)."""
        if not pin or len(pin) < 4:
            raise ApiError(400, "PIN must be at least 4 characters")
        record = auth.hash_pin(pin)
        session_key = os.urandom(32)
        with self._writable_usb():
            os.makedirs(os.path.dirname(self.pin_path()), exist_ok=True)
            with open(self.pin_path(), "w", encoding="utf-8") as f:
                f.write(record.to_line())
            with open(os.path.join(self.config.usb_root, SESSION_KEY_FILENAME), "wb") as f:
                f.write(session_key)
        self._sessions = None  # force reload with the new key

    def login(self, pin: str) -> str:
        """Returns a session token on success, raises ApiError(401) on
        a wrong PIN."""
        if self.is_first_run():
            raise ApiError(409, "No PIN has been set yet")
        with open(self.pin_path(), "r", encoding="utf-8") as f:
            record = auth.PinRecord.from_line(f.read())
        if not auth.verify_pin(pin, record):
            raise ApiError(401, "Incorrect PIN")
        return self._session_manager().issue()

    def require_session(self, token: Optional[str]) -> None:
        if not token or not self._session_manager().verify(token):
            raise ApiError(401, "Not authenticated")

    def _session_manager(self) -> auth.SessionManager:
        if self._sessions is None:
            key_path = os.path.join(self.config.usb_root, SESSION_KEY_FILENAME)
            with open(key_path, "rb") as f:
                self._sessions = auth.SessionManager(f.read())
        return self._sessions

    # -- Writable-USB access, with a fallback for when pedal-core.service's
    # mpv won't let go ----------------------------------------------------

    @contextlib.contextmanager
    def _writable_usb(self):
        """Every mutating method below uses this instead of calling
        `usb_mount.writable_usb()` directly.

        Real incident found on real hardware (2026-10-01, in the sibling
        `setlist-admin-usb` expansion -- ported here unchanged, kept
        convergent): `pedal-core.service`'s `mpv` keeps whatever it's
        currently looping (in practice, always `standby.mp4`) open for as
        long as it runs -- confirmed to never let go on its own, not even
        briefly, for as long as the service keeps running without being
        restarted. `usb_mount._remount()`'s own bounded retry (built for
        a genuinely brief, transient busy window) can't get past that: it
        isn't brief here, so every write failed with a 500 the whole time
        the service ran continuously and stayed stable -- which directly
        contradicts the "once playing, don't touch it" design: the system
        staying *more* stable (not restarting `mpv` on every MIDI hiccup,
        see `CHANGELOG.md`) is exactly what exposed this, since restarts
        used to create brief incidental gaps.

        Fixed here, not in `usb_mount.py` (which is deliberately
        mount-only, with no idea `pedal-core.service` exists): try the
        normal fast path first with a cheap, side-effect-free probe (an
        immediate rw-then-ro round trip, nothing written) -- if the mount
        is free, every existing call site's behavior is unchanged,
        no disruption. Only if that probe itself fails does this stop
        `pedal-core.service` (releasing every file it has open, including
        the looping standby video -- briefly interrupting playback,
        screen goes black for a few seconds) before the real write, then
        restarts it afterward. The probe runs as a fully separate,
        no-op remount cycle specifically so the real write never has to
        be attempted twice -- retrying the actual operation after a
        partial failure would risk doing it twice over (e.g. a duplicate
        write, or in the worst case the "ro" remount itself being what
        failed, which would mean the write had already happened)."""
        stopped = False
        if not self._can_remount_rw_quickly():
            stopped = self._stop_pedal_core()
        try:
            with usb_mount.writable_usb(self.config.mount_point):
                yield
        finally:
            if stopped:
                self._start_pedal_core()

    def _can_remount_rw_quickly(self) -> bool:
        """A cheap, side-effect-free probe: can `/media/usb` be remounted
        rw right now without anything holding it busy? Immediately
        remounts back to `ro` either way -- nothing is written in
        between. Used only to decide whether `_writable_usb()` needs to
        stop `pedal-core.service` first."""
        try:
            with usb_mount.writable_usb(self.config.mount_point):
                pass
            return True
        except usb_mount.RemountError:
            return False

    def _stop_pedal_core(self) -> bool:
        """Returns True only if the service was actually running (and is
        now stopped by this call) -- False if it was already stopped, or
        if stopping it failed, so `_writable_usb()`'s `finally` never
        "helpfully" starts a service back up that this call didn't
        actually stop itself."""
        try:
            was_active = subprocess.run(
                ["systemctl", "is-active", _PEDAL_CORE_SERVICE_NAME],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip() == "active"
            if not was_active:
                return False
            subprocess.run(
                ["sudo", "systemctl", "stop", _PEDAL_CORE_SERVICE_NAME],
                capture_output=True, timeout=15,
            )
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _start_pedal_core(self) -> None:
        try:
            subprocess.run(
                ["sudo", "systemctl", "start", _PEDAL_CORE_SERVICE_NAME],
                capture_output=True, timeout=15,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.error(
                "Could not restart %s after a library write -- it may need "
                "a manual 'sudo systemctl start %s' over SSH: %s",
                _PEDAL_CORE_SERVICE_NAME, _PEDAL_CORE_SERVICE_NAME, e,
            )

    # -- Sets ------------------------------------------------------------

    def list_sets(self) -> dict:
        return {
            "sets": library_ops.list_sets(self.config.usb_root),
            "active": library_ops.get_active_set(self.config.usb_root),
        }

    def create_set(self, set_name: str) -> None:
        with self._writable_usb():
            library_ops.create_set(self.config.usb_root, set_name)

    def set_active_set(self, set_name: str) -> None:
        with self._writable_usb():
            library_ops.set_active_set(self.config.usb_root, set_name)

    # -- Banks ---------------------------------------------------------------

    def list_banks(self, set_name: str) -> dict:
        return {"banks": library_ops.list_banks(self.config.usb_root, set_name)}

    def create_bank(self, set_name: str, bank_number: int) -> None:
        with self._writable_usb():
            library_ops.create_bank(self.config.usb_root, set_name, bank_number)

    def rename_bank(self, set_name: str, old_number: int, new_number: int) -> None:
        with self._writable_usb():
            library_ops.rename_bank(self.config.usb_root, set_name, old_number, new_number)

    def delete_bank(self, set_name: str, bank_number: int) -> None:
        with self._writable_usb():
            library_ops.delete_bank(self.config.usb_root, set_name, bank_number)

    # -- Tracks -------------------------------------------------------------

    def list_tracks(self, set_name: str, bank_number: int) -> dict:
        tracks = library_ops.list_tracks(self.config.usb_root, set_name, bank_number)
        return {
            letter: (
                {"display_name": t.display_name, "extension": t.extension, "is_audio_only": t.is_audio_only}
                if t else None
            )
            for letter, t in tracks.items()
        }

    def assign_track(self, set_name: str, bank_number: int, letter: str,
                      display_name: str, extension: str, source: BinaryIO) -> Optional[str]:
        """Returns a codec warning string if the upload is a video that
        isn't H.264, or None if it's fine (or not a video). The warning
        never blocks the upload -- see codec_check.py's docstring."""
        with self._writable_usb():
            info = library_ops.assign_track(
                self.config.usb_root, set_name, bank_number, letter,
                display_name, extension, source,
            )
        bank_path = os.path.join(self.config.usb_root, set_name, f"Bank {bank_number}")
        return codec_check.check_video_codec(os.path.join(bank_path, info.filename), extension)

    def rename_track(self, set_name: str, bank_number: int, letter: str, new_display_name: str) -> None:
        with self._writable_usb():
            library_ops.rename_track(self.config.usb_root, set_name, bank_number, letter, new_display_name)

    def swap_tracks(self, set_name: str, bank_number: int, letter_a: str, letter_b: str) -> None:
        with self._writable_usb():
            library_ops.swap_tracks(self.config.usb_root, set_name, bank_number, letter_a, letter_b)

    def delete_track(self, set_name: str, bank_number: int, letter: str) -> None:
        with self._writable_usb():
            library_ops.delete_track(self.config.usb_root, set_name, bank_number, letter)

    # -- Song library (reuse across Sets) -------------------------------------

    def list_songs(self) -> dict:
        return {
            "songs": [
                {"filename": s.filename, "display_name": s.display_name,
                 "extension": s.extension, "is_audio_only": s.is_audio_only}
                for s in library_ops.list_songs(self.config.usb_root)
            ]
        }

    def upload_song(self, display_name: str, extension: str, source: BinaryIO) -> Optional[str]:
        """Same codec-warning contract as assign_track()."""
        with self._writable_usb():
            info = library_ops.upload_song(self.config.usb_root, display_name, extension, source)
        songs_path = os.path.join(self.config.usb_root, "_Songs")
        return codec_check.check_video_codec(os.path.join(songs_path, info.filename), extension)

    def rename_song(self, filename: str, new_display_name: str) -> None:
        with self._writable_usb():
            library_ops.rename_song(self.config.usb_root, filename, new_display_name)

    def delete_song(self, filename: str) -> None:
        with self._writable_usb():
            library_ops.delete_song(self.config.usb_root, filename)

    def assign_song_to_slot(self, set_name: str, bank_number: int, letter: str, song_filename: str) -> None:
        with self._writable_usb():
            library_ops.assign_song_to_slot(self.config.usb_root, set_name, bank_number, letter, song_filename)

    def save_track_to_library(self, set_name: str, bank_number: int, letter: str) -> None:
        with self._writable_usb():
            library_ops.save_track_to_library(self.config.usb_root, set_name, bank_number, letter)

    def cleanup_stale_temp_files(self) -> int:
        """Called once at server startup -- see
        library_ops.cleanup_stale_temp_files()'s docstring for why this
        is needed (a SIGTERM mid-upload, e.g. from usb-tether-watchdog
        stopping this service the instant a phone disconnects, skips the
        normal per-write cleanup)."""
        with self._writable_usb():
            return library_ops.cleanup_stale_temp_files(self.config.usb_root)

    # -- Standby video (the looped idle screen) --------------------------------

    def get_standby(self) -> dict:
        info = library_ops.get_standby_info(self.config.usb_root)
        return {"exists": info.exists, "size_bytes": info.size_bytes, "modified_at": info.modified_at}

    def set_standby(self, song_filename: str) -> None:
        with self._writable_usb():
            library_ops.set_standby_video(self.config.usb_root, song_filename)

    # -- Playback status (advisory warning, section 6) -----------------------

    def is_playback_likely_active(self) -> bool:
        """Best-effort check for whether pedal-core.service looks like
        it's actively playing something other than standby right now --
        used to show a warning, never to block an edit outright (section
        6: pre/post-show is policy, not a hard technical lock in v1)."""
        try:
            result = subprocess.run(
                ["systemctl", "is-active", "pedal-core.service"],
                capture_output=True, text=True, timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
        return result.stdout.strip() == "active"

    # -- WiFi -----------------------------------------------------------------

    def wifi_status(self) -> dict:
        config = self._load_network_config()
        return {
            "home_configured": bool(config and config.home),
            "hotspot_configured": bool(config and config.hotspot),
            "connected": wifi.has_usable_ip(),
            "active_connection": wifi.active_connection_name(),
        }

    def set_home_wifi(self, ssid: str, password: str) -> None:
        if not ssid:
            raise ApiError(400, "SSID cannot be empty")
        key = self._network_key()
        config_path = self._network_config_path()
        existing = wifi.load_config(config_path, key)
        new_config = wifi.NetworkConfig(
            home=wifi.WifiProfile(ssid=ssid, password=password),
            hotspot=existing.hotspot if existing else None,
        )
        with self._writable_usb():
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            wifi.save_config(config_path, key, new_config)
        wifi.apply_home_profile(new_config.home)

    def _network_config_path(self) -> str:
        return os.path.join(self.config.usb_root, wifi.NETWORK_CONFIG_FILENAME)

    def _network_key(self) -> str:
        machine_id = crypto.read_machine_id()
        return crypto.derive_key(machine_id, self.config.usb_uuid)

    def _load_network_config(self):
        return wifi.load_config(self._network_config_path(), self._network_key())
