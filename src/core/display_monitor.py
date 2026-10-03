"""
DisplayMonitor: polls a DRM connector's sysfs `status` file to detect
whether an HDMI display is physically connected, and calls back on a
confirmed (debounced) state change.

Real user request (2026-10-03), after measuring it live: the video
lane's mpv process (see player.py's Player) costs a full CPU core
(~106%) and ~300MB RAM continuously just to loop standby, whether a
display is attached to actually show it or not -- on this Pi (4 cores,
~921MB total RAM, already seen genuinely under memory pressure this
project's own history), that's real, ongoing cost for nothing if no
one can see the output. Core starts/stops the video lane based on this
monitor's signal, instead of always running it (see Core.
set_display_connected()).

Deliberately polling, not udev events: this project is stdlib-only (no
pyudev, no subprocess parsing of `udevadm monitor`), and a cable being
plugged in isn't latency-sensitive -- a few seconds' detection delay
before the video lane spins back up is an acceptable, disclosed
trade-off, not a bug. Debounced (requires _CONFIRM_READS consecutive
agreeing reads before calling back) so a loose or flickering cable
doesn't repeatedly tear down and respawn mpv.
"""

import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_STATUS_PATH = "/sys/class/drm/card0-HDMI-A-1/status"
_DEFAULT_POLL_INTERVAL_SECONDS = 2.0
# How many consecutive polls must agree on a *changed* reading before
# acting on it. 2 means one single stray/bouncing read is ignored, but
# a real, sustained change is still caught within ~2 poll intervals.
_CONFIRM_READS = 2


class DisplayMonitor:
    def __init__(
        self,
        on_change: Callable[[bool], None],
        status_path: str = DEFAULT_STATUS_PATH,
        poll_interval: float = _DEFAULT_POLL_INTERVAL_SECONDS,
    ):
        self.status_path = status_path
        self.poll_interval = poll_interval
        self._on_change = on_change
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_reported: Optional[bool] = None

    def read_connected(self) -> bool:
        """Best-effort: a missing/unreadable status file (a renamed
        connector, or no DRM HDMI output at all on this board) is
        treated as "connected" -- a detection failure should never be
        the reason the video lane silently stops working; only a
        confirmed real disconnect should."""
        try:
            with open(self.status_path, "r", encoding="utf-8") as f:
                return f.read().strip() == "connected"
        except OSError as e:
            logger.warning(
                "Could not read display status from %s (%s) -- assuming connected",
                self.status_path, e,
            )
            return True

    def start(self):
        """Reports the real, current state once synchronously (so the
        caller's very first on_change() call reflects reality at
        startup, not an assumed default) before spawning the
        background poll loop."""
        initial = self.read_connected()
        self._last_reported = initial
        self._on_change(initial)
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _poll_loop(self):
        pending: Optional[bool] = None
        pending_count = 0
        while not self._stop_event.wait(self.poll_interval):
            current = self.read_connected()
            if current == self._last_reported:
                pending = None
                pending_count = 0
                continue
            if current == pending:
                pending_count += 1
            else:
                pending = current
                pending_count = 1
            if pending_count >= _CONFIRM_READS:
                self._last_reported = current
                pending = None
                pending_count = 0
                try:
                    self._on_change(current)
                except Exception:
                    logger.exception("display-connected callback failed")
