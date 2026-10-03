"""
A narrow regression test for a real incident (2026-10-03) in
_MpvProcess's stop()/start() lifecycle -- not a general test of
player.py's real mpv/IPC integration, which stays covered by manual
hardware checks (src/core_smoke_test.py, TESTING.md) per this
project's existing convention. subprocess.Popen, _connect(), and
_spawn_reader() are all mocked here specifically to isolate the one
piece of *pure* internal state this bug was actually about, without
needing a real mpv process, a real socket, or real background threads.

Run with: python -m unittest tests/test_player.py
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.player import _MpvProcess  # noqa: E402


class TestMpvProcessRestart(unittest.TestCase):
    @patch("core.player.subprocess.Popen")
    def test_start_resets_a_stop_flag_left_set_by_a_previous_stop(self, mock_popen):
        """Real incident: this same _MpvProcess instance is now
        stopped and started again within one long-running process (the
        video lane stopping/starting as a display disconnects/
        reconnects -- see Core.set_display_connected()), which this
        class was never exercised against before. _stop_listener used
        to stay permanently set after the first stop(), so the *next*
        start()'s brand-new reader threads saw "already told to stop"
        on their very first loop check and closed the just-connected
        sockets immediately -- confirmed live: commands sent right
        after then failed with "Bad file descriptor", leaving mpv
        showing its idle screen instead of the file it was told to
        load."""
        proc = _MpvProcess(socket_path="/tmp/irrelevant-for-this-test.sock", extra_args=[])
        proc._stop_listener.set()  # simulates having been through a real stop() already

        with patch.object(proc, "_connect", return_value=MagicMock()), \
             patch.object(proc, "_spawn_reader"), \
             patch("core.player.os.path.exists", return_value=False):
            proc.start()

        self.assertFalse(proc._stop_listener.is_set())

    @patch("core.player.subprocess.Popen")
    def test_start_clears_reader_threads_from_a_previous_lifecycle(self, mock_popen):
        proc = _MpvProcess(socket_path="/tmp/irrelevant-for-this-test.sock", extra_args=[])
        proc._reader_threads.append(MagicMock())  # simulates a previous start()'s bookkeeping

        with patch.object(proc, "_connect", return_value=MagicMock()), \
             patch.object(proc, "_spawn_reader"), \
             patch("core.player.os.path.exists", return_value=False):
            proc.start()

        self.assertEqual(proc._reader_threads, [])


if __name__ == "__main__":
    unittest.main()
