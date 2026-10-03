"""
DisplayMonitor tests. read_connected()'s file-reading logic is tested
directly against a real temp file (no mocking needed, no hardware
required); the debounce/polling behavior is tested with a mocked
read_connected() and a tiny poll_interval so these stay fast.

Run with: python -m unittest tests/test_display_monitor.py
"""

import itertools
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.display_monitor import DisplayMonitor  # noqa: E402


class TestReadConnected(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.status_path = os.path.join(self.tmpdir.name, "status")

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write(self, content):
        with open(self.status_path, "w", encoding="utf-8") as f:
            f.write(content)

    def test_connected_is_true(self):
        self._write("connected\n")
        monitor = DisplayMonitor(on_change=lambda c: None, status_path=self.status_path)

        self.assertTrue(monitor.read_connected())

    def test_disconnected_is_false(self):
        self._write("disconnected\n")
        monitor = DisplayMonitor(on_change=lambda c: None, status_path=self.status_path)

        self.assertFalse(monitor.read_connected())

    def test_unknown_is_false(self):
        """mpv's own DRM probe reported "unknown" for a second, non-HDMI
        connector on the real Pi -- only an exact "connected" counts."""
        self._write("unknown\n")
        monitor = DisplayMonitor(on_change=lambda c: None, status_path=self.status_path)

        self.assertFalse(monitor.read_connected())

    def test_missing_file_assumes_connected(self):
        """A detection failure (wrong connector name, no DRM HDMI output
        on this board) must never be the reason the video lane silently
        stops working -- only a confirmed real disconnect should."""
        monitor = DisplayMonitor(
            on_change=lambda c: None,
            status_path=os.path.join(self.tmpdir.name, "does-not-exist"),
        )

        self.assertTrue(monitor.read_connected())


class TestPollingAndDebounce(unittest.TestCase):
    def _make_monitor(self, readings, poll_interval=0.01):
        calls = []
        monitor = DisplayMonitor(on_change=calls.append, poll_interval=poll_interval)
        monitor.read_connected = MagicMock(side_effect=lambda: next(readings))
        return monitor, calls

    def test_start_reports_the_initial_state_synchronously(self):
        readings = itertools.chain([True], itertools.repeat(True))
        monitor, calls = self._make_monitor(readings)

        monitor.start()
        try:
            self.assertEqual(calls, [True])
        finally:
            monitor.stop()

    def test_a_sustained_change_is_reported_exactly_once(self):
        readings = itertools.chain([True], itertools.repeat(False))
        monitor, calls = self._make_monitor(readings)

        monitor.start()
        time.sleep(0.1)
        monitor.stop()

        self.assertEqual(calls, [True, False])

    def test_a_single_stray_reading_is_not_reported(self):
        """Real scenario this exists for: a loose/flickering cable --
        one bad read must not tear down and respawn the video lane's
        mpv process."""
        readings = itertools.chain([True, False], itertools.repeat(True))
        monitor, calls = self._make_monitor(readings)

        monitor.start()
        time.sleep(0.1)
        monitor.stop()

        self.assertEqual(calls, [True])

    def test_flapping_back_before_confirmation_cancels_the_pending_change(self):
        readings = itertools.chain([True, False, True], itertools.repeat(True))
        monitor, calls = self._make_monitor(readings)

        monitor.start()
        time.sleep(0.1)
        monitor.stop()

        self.assertEqual(calls, [True])


if __name__ == "__main__":
    unittest.main()
