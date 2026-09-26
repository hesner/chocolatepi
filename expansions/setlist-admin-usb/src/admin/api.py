"""
Request handling logic for setlist-admin, kept separate from `server.py`'s
raw HTTP plumbing so it's testable by calling methods directly, with a
mocked filesystem/subprocess layer -- no real HTTP server, no real USB
needed to exercise this (SETLIST_ADMIN_USB_SPECIFICATION.md section 10).

Every method that mutates the library wraps its single filesystem
operation in `usb_mount.writable_usb()` -- the rw window is exactly one
operation wide, never the whole request, matching section 6.
"""

import logging
import os
import subprocess
from dataclasses import dataclass
from typing import BinaryIO, Optional

from admin import auth, codec_check, library_ops, usb_mount

logger = logging.getLogger(__name__)

PIN_FILENAME = ".setlist-admin/pin.hash"
SESSION_KEY_FILENAME = ".setlist-admin/session.key"


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


class AdminAPI:
    def __init__(self, config: AdminConfig):
        self.config = config
        self._sessions: Optional[auth.SessionManager] = None

    # -- Auth -----------------------------------------------------------

    def pin_path(self) -> str:
        return os.path.join(self.config.usb_root, PIN_FILENAME)

    def is_first_run(self) -> bool:
        return not os.path.exists(self.pin_path())

    def set_pin(self, pin: str) -> None:
        """Used both for genuine first-run setup and for finishing a
        recovery (section 7: once pin.hash is deleted over SSH, the app
        treats the next visit as first-run and this is what completes it)."""
        if not pin or len(pin) < 4:
            raise ApiError(400, "PIN must be at least 4 characters")
        record = auth.hash_pin(pin)
        session_key = os.urandom(32)
        with usb_mount.writable_usb(self.config.mount_point):
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

    # -- Shows ------------------------------------------------------------

    def list_shows(self) -> dict:
        return {
            "shows": library_ops.list_shows(self.config.usb_root),
            "active": library_ops.get_active_show(self.config.usb_root),
        }

    def create_show(self, show_name: str) -> None:
        with usb_mount.writable_usb(self.config.mount_point):
            library_ops.create_show(self.config.usb_root, show_name)

    def set_active_show(self, show_name: str) -> None:
        with usb_mount.writable_usb(self.config.mount_point):
            library_ops.set_active_show(self.config.usb_root, show_name)

    # -- Sets ---------------------------------------------------------------

    def list_sets(self, show_name: str) -> dict:
        return {"sets": library_ops.list_sets(self.config.usb_root, show_name)}

    def create_set(self, show_name: str, set_number: int) -> None:
        with usb_mount.writable_usb(self.config.mount_point):
            library_ops.create_set(self.config.usb_root, show_name, set_number)

    def rename_set(self, show_name: str, old_number: int, new_number: int) -> None:
        with usb_mount.writable_usb(self.config.mount_point):
            library_ops.rename_set(self.config.usb_root, show_name, old_number, new_number)

    def delete_set(self, show_name: str, set_number: int) -> None:
        with usb_mount.writable_usb(self.config.mount_point):
            library_ops.delete_set(self.config.usb_root, show_name, set_number)

    # -- Tracks -------------------------------------------------------------

    def list_tracks(self, show_name: str, set_number: int) -> dict:
        tracks = library_ops.list_tracks(self.config.usb_root, show_name, set_number)
        return {
            letter: (
                {"display_name": t.display_name, "extension": t.extension, "is_audio_only": t.is_audio_only}
                if t else None
            )
            for letter, t in tracks.items()
        }

    def assign_track(self, show_name: str, set_number: int, letter: str,
                      display_name: str, extension: str, source: BinaryIO) -> Optional[str]:
        """Returns a codec warning string if the upload is a video that
        isn't H.264, or None if it's fine (or not a video). The warning
        never blocks the upload -- see codec_check.py's docstring."""
        with usb_mount.writable_usb(self.config.mount_point):
            info = library_ops.assign_track(
                self.config.usb_root, show_name, set_number, letter,
                display_name, extension, source,
            )
        set_path = os.path.join(self.config.usb_root, show_name, f"Set {set_number}")
        return codec_check.check_video_codec(os.path.join(set_path, info.filename), extension)

    def rename_track(self, show_name: str, set_number: int, letter: str, new_display_name: str) -> None:
        with usb_mount.writable_usb(self.config.mount_point):
            library_ops.rename_track(self.config.usb_root, show_name, set_number, letter, new_display_name)

    def swap_tracks(self, show_name: str, set_number: int, letter_a: str, letter_b: str) -> None:
        with usb_mount.writable_usb(self.config.mount_point):
            library_ops.swap_tracks(self.config.usb_root, show_name, set_number, letter_a, letter_b)

    def delete_track(self, show_name: str, set_number: int, letter: str) -> None:
        with usb_mount.writable_usb(self.config.mount_point):
            library_ops.delete_track(self.config.usb_root, show_name, set_number, letter)

    # -- Song library (reuse across Shows) -------------------------------------

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
        with usb_mount.writable_usb(self.config.mount_point):
            info = library_ops.upload_song(self.config.usb_root, display_name, extension, source)
        songs_path = os.path.join(self.config.usb_root, "_Songs")
        return codec_check.check_video_codec(os.path.join(songs_path, info.filename), extension)

    def rename_song(self, filename: str, new_display_name: str) -> None:
        with usb_mount.writable_usb(self.config.mount_point):
            library_ops.rename_song(self.config.usb_root, filename, new_display_name)

    def delete_song(self, filename: str) -> None:
        with usb_mount.writable_usb(self.config.mount_point):
            library_ops.delete_song(self.config.usb_root, filename)

    def assign_song_to_slot(self, show_name: str, set_number: int, letter: str, song_filename: str) -> None:
        with usb_mount.writable_usb(self.config.mount_point):
            library_ops.assign_song_to_slot(self.config.usb_root, show_name, set_number, letter, song_filename)

    def save_track_to_library(self, show_name: str, set_number: int, letter: str) -> None:
        with usb_mount.writable_usb(self.config.mount_point):
            library_ops.save_track_to_library(self.config.usb_root, show_name, set_number, letter)

    # -- Playback status (advisory warning, section 1) -----------------------

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

    # -- Reboot (section 8: applying a library change needs one) --------------

    def reboot(self) -> None:
        """Fire-and-forget: `pedal-core.service` only reads library state at
        its own startup (MASTER_SPECIFICATION.md), so this is how a person
        applies a setlist change without needing SSH. Runs detached --
        by the time systemd actually tears the machine down, this HTTP
        request has almost certainly already returned its response."""
        try:
            subprocess.run(
                ["sudo", "systemctl", "reboot"],
                capture_output=True, timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.error("Failed to trigger reboot: %s", e)
            raise ApiError(500, "Could not reboot") from e
