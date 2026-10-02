"""
library_optimizer.py tests. pedal_core_guard.writable_usb() is mocked
(a no-op context manager) -- its own real behavior is tested in
test_admin_api.py's TestWritableUsbFallback/TestBrokenMountRecovery,
shared via the same module (pedal_core_guard.py) this daemon also
imports. subprocess.Popen (the actual ffmpeg call) is mocked throughout
-- no real encoding in a unit test.

Run with: python -m unittest tests/test_library_optimizer.py
"""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from admin import library_optimizer, optimize_queue  # noqa: E402


def _noop_writable_usb_mock():
    """A MagicMock usable as `with pedal_core_guard.writable_usb(...):`
    that does NOT suppress exceptions raised inside the block -- a bare
    MagicMock's __exit__ return value is truthy by default, which would
    incorrectly swallow errors the tests below need to actually see."""
    cm = MagicMock()
    cm.__exit__.return_value = False
    mock = MagicMock(return_value=cm)
    return mock


def _mock_proc(returncode=0, stdout="", stderr=""):
    """A MagicMock standing in for the subprocess.Popen object -- .wait()
    succeeds immediately (ffmpeg "finished" on the very first poll)."""
    proc = MagicMock()
    proc.wait.return_value = returncode
    proc.returncode = returncode
    proc.stdout.read.return_value = stdout
    proc.stderr.read.return_value = stderr
    return proc


class LibraryOptimizerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.usb_root = os.path.join(self.tmpdir.name, "usb")
        self.scratch_dir = os.path.join(self.tmpdir.name, "scratch")
        os.makedirs(os.path.join(self.usb_root, "_Songs"))
        os.makedirs(self.scratch_dir)

        guard_patcher = patch(
            "admin.library_optimizer.pedal_core_guard.writable_usb",
            new=_noop_writable_usb_mock(),
        )
        self.mock_writable_usb = guard_patcher.start()
        self.addCleanup(guard_patcher.stop)

        # The cancel marker lives outside usb_root now (see
        # optimize_queue.DEFAULT_STATE_DIR's own comment) -- pointed at
        # an isolated per-test directory so tests never touch the real
        # default (a real path under the developer's/Pi's home dir) or
        # collide with each other.
        state_dir = os.path.join(self.tmpdir.name, "state")
        state_dir_patcher = patch("admin.optimize_queue.DEFAULT_STATE_DIR", state_dir)
        state_dir_patcher.start()
        self.addCleanup(state_dir_patcher.stop)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_song(self, filename: str, content: bytes = b"source bytes") -> str:
        path = os.path.join(self.usb_root, "_Songs", filename)
        with open(path, "wb") as f:
            f.write(content)
        return path


class TestProcessJob(LibraryOptimizerTestCase):
    @patch("admin.library_optimizer.subprocess.Popen")
    def test_successful_encode_replaces_the_file_and_clears_the_job(self, mock_popen):
        self._write_song("Song.mp4", b"old hevc bytes")
        optimize_queue.enqueue(self.usb_root, "Song.mp4")

        def fake_ffmpeg(cmd, **kwargs):
            # The real ffmpeg call writes its -f mp4 output path (last
            # positional arg) -- fake that by actually writing a file
            # there, so the "copy into place" step has something real
            # to copy.
            with open(cmd[-1], "wb") as f:
                f.write(b"optimized h264 bytes")
            return _mock_proc()

        mock_popen.side_effect = fake_ffmpeg

        library_optimizer._process_job(self.usb_root, "/media/usb", self.scratch_dir, "Song.mp4")

        with open(os.path.join(self.usb_root, "_Songs", "Song.mp4"), "rb") as f:
            self.assertEqual(f.read(), b"optimized h264 bytes")
        self.assertIsNone(optimize_queue.get_status(self.usb_root, "Song.mp4"))
        # The scratch file is cleaned up, not left behind.
        self.assertEqual(os.listdir(self.scratch_dir), [])

    @patch("admin.library_optimizer.subprocess.Popen")
    def test_ffmpeg_runs_against_a_local_scratch_copy_not_the_usb_path(self, mock_popen):
        """Real incident (2026-10-02): ffmpeg used to run straight
        against the USB-mounted source, keeping it open for the whole
        encode -- long enough (45+ minutes for one real 4K file) that
        every other library write failed, since umount refuses outright
        while anything holds a file open on that mount, reading
        included. The source is now copied to scratch first; ffmpeg
        must never see the real USB path as its input."""
        source_path = self._write_song("Song.mp4", b"old hevc bytes")
        optimize_queue.enqueue(self.usb_root, "Song.mp4")

        def fake_ffmpeg(cmd, **kwargs):
            input_path = cmd[cmd.index("-i") + 1]
            self.assertNotEqual(input_path, source_path)
            self.assertTrue(input_path.startswith(self.scratch_dir))
            self.assertTrue(os.path.isfile(input_path))
            with open(cmd[-1], "wb") as f:
                f.write(b"optimized h264 bytes")
            return _mock_proc()

        mock_popen.side_effect = fake_ffmpeg

        library_optimizer._process_job(self.usb_root, "/media/usb", self.scratch_dir, "Song.mp4")

        # Both the scratch input copy and the scratch output are
        # cleaned up -- nothing lingers once the job is done.
        self.assertEqual(os.listdir(self.scratch_dir), [])

    @patch("admin.library_optimizer.subprocess.Popen")
    def test_missing_source_file_marks_error_without_calling_ffmpeg(self, mock_popen):
        optimize_queue.enqueue(self.usb_root, "Does Not Exist.mp4")

        library_optimizer._process_job(self.usb_root, "/media/usb", self.scratch_dir, "Does Not Exist.mp4")

        mock_popen.assert_not_called()
        status = optimize_queue.get_status(self.usb_root, "Does Not Exist.mp4")
        self.assertEqual(status["status"], optimize_queue.STATUS_ERROR)

    @patch("admin.library_optimizer.shutil.copyfile", side_effect=OSError("boom"))
    @patch("admin.library_optimizer.subprocess.Popen")
    def test_a_failed_scratch_copy_marks_error_without_calling_ffmpeg(self, mock_popen, mock_copy):
        self._write_song("Song.mp4", b"original bytes")
        optimize_queue.enqueue(self.usb_root, "Song.mp4")

        library_optimizer._process_job(self.usb_root, "/media/usb", self.scratch_dir, "Song.mp4")

        mock_popen.assert_not_called()
        status = optimize_queue.get_status(self.usb_root, "Song.mp4")
        self.assertEqual(status["status"], optimize_queue.STATUS_ERROR)

    @patch("admin.library_optimizer.subprocess.Popen")
    def test_ffmpeg_failure_marks_error_and_leaves_the_original_untouched(self, mock_popen):
        self._write_song("Song.mp4", b"original bytes")
        optimize_queue.enqueue(self.usb_root, "Song.mp4")
        mock_popen.return_value = _mock_proc(returncode=1, stderr="broken input")

        library_optimizer._process_job(self.usb_root, "/media/usb", self.scratch_dir, "Song.mp4")

        with open(os.path.join(self.usb_root, "_Songs", "Song.mp4"), "rb") as f:
            self.assertEqual(f.read(), b"original bytes")
        status = optimize_queue.get_status(self.usb_root, "Song.mp4")
        self.assertEqual(status["status"], optimize_queue.STATUS_ERROR)

    @patch("admin.library_optimizer._FFMPEG_TIMEOUT_SECONDS", 1)
    @patch("admin.library_optimizer.subprocess.Popen")
    def test_ffmpeg_timeout_marks_error(self, mock_popen):
        self._write_song("Song.mp4")
        optimize_queue.enqueue(self.usb_root, "Song.mp4")
        proc = MagicMock()
        proc.wait.side_effect = subprocess.TimeoutExpired(["ffmpeg"], 2)
        mock_popen.return_value = proc

        library_optimizer._process_job(self.usb_root, "/media/usb", self.scratch_dir, "Song.mp4")

        status = optimize_queue.get_status(self.usb_root, "Song.mp4")
        self.assertEqual(status["status"], optimize_queue.STATUS_ERROR)
        self.assertIn("too long", status["message"])
        # The runaway process itself is actually killed, not just
        # abandoned to keep eating CPU in the background.
        proc.terminate.assert_called_once()

    @patch("admin.library_optimizer.subprocess.Popen")
    def test_marks_running_before_encoding_starts(self, mock_popen):
        """So a phone reconnecting mid-encode sees "Optimizing...", not
        "Optimize" again (which would let a second job get queued on
        top of one already running)."""
        self._write_song("Song.mp4")
        optimize_queue.enqueue(self.usb_root, "Song.mp4")
        seen_status = {}

        def fake_ffmpeg(cmd, **kwargs):
            seen_status["during_encode"] = optimize_queue.get_status(self.usb_root, "Song.mp4")["status"]
            with open(cmd[-1], "wb") as f:
                f.write(b"x")
            return _mock_proc()

        mock_popen.side_effect = fake_ffmpeg

        library_optimizer._process_job(self.usb_root, "/media/usb", self.scratch_dir, "Song.mp4")

        self.assertEqual(seen_status["during_encode"], optimize_queue.STATUS_RUNNING)


class TestCancellation(LibraryOptimizerTestCase):
    """Real user request (2026-10-02), after a real incident: an
    optimize job can run for hours with no visible progress -- a real
    temptation to just unplug the Pi. These confirm a cancel request
    actually stops the real ffmpeg process (not just the bookkeeping
    around it), whether it arrives before the job starts or mid-encode."""

    @patch("admin.library_optimizer.subprocess.Popen")
    def test_cancel_before_job_starts_clears_it_without_calling_ffmpeg(self, mock_popen):
        self._write_song("Song.mp4", b"original bytes")
        optimize_queue.enqueue(self.usb_root, "Song.mp4")
        optimize_queue.request_cancel("Song.mp4")

        library_optimizer._process_job(self.usb_root, "/media/usb", self.scratch_dir, "Song.mp4")

        mock_popen.assert_not_called()
        self.assertIsNone(optimize_queue.get_status(self.usb_root, "Song.mp4"))
        with open(os.path.join(self.usb_root, "_Songs", "Song.mp4"), "rb") as f:
            self.assertEqual(f.read(), b"original bytes")

    @patch("admin.library_optimizer.subprocess.Popen")
    def test_cancel_mid_encode_terminates_ffmpeg_and_clears_the_job(self, mock_popen):
        self._write_song("Song.mp4", b"original bytes")
        optimize_queue.enqueue(self.usb_root, "Song.mp4")
        proc = MagicMock()
        call_count = {"n": 0}

        def wait_side_effect(timeout=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # Simulates the user tapping "Cancel" while this first
                # poll was "in flight".
                optimize_queue.request_cancel("Song.mp4")
                raise subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=timeout)
            return 0

        proc.wait.side_effect = wait_side_effect
        mock_popen.return_value = proc

        library_optimizer._process_job(self.usb_root, "/media/usb", self.scratch_dir, "Song.mp4")

        proc.terminate.assert_called_once()
        self.assertIsNone(optimize_queue.get_status(self.usb_root, "Song.mp4"))
        # Cancelling leaves the original file exactly as it was --
        # never partially overwritten.
        with open(os.path.join(self.usb_root, "_Songs", "Song.mp4"), "rb") as f:
            self.assertEqual(f.read(), b"original bytes")

    @patch("admin.library_optimizer.subprocess.Popen")
    def test_a_stuck_terminate_escalates_to_kill(self, mock_popen):
        """SIGTERM first, since ffmpeg normally exits cleanly on it --
        SIGKILL only if it somehow doesn't, so cancelling itself can
        never hang."""
        self._write_song("Song.mp4")
        optimize_queue.enqueue(self.usb_root, "Song.mp4")
        proc = MagicMock()
        call_count = {"n": 0}

        def wait_side_effect(timeout=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # The polling wait -- simulate "Cancel" being tapped.
                optimize_queue.request_cancel("Song.mp4")
                raise subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=timeout)
            if call_count["n"] == 2:
                # terminate()'s own wait -- ffmpeg ignores SIGTERM.
                raise subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=timeout)
            return 0  # the wait after kill() -- that one always works

        proc.wait.side_effect = wait_side_effect
        mock_popen.return_value = proc

        library_optimizer._process_job(self.usb_root, "/media/usb", self.scratch_dir, "Song.mp4")

        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()
        self.assertIsNone(optimize_queue.get_status(self.usb_root, "Song.mp4"))


class TestTick(LibraryOptimizerTestCase):
    @patch("admin.library_optimizer._process_job")
    def test_processes_only_one_queued_job_per_tick(self, mock_process):
        """Deliberate: this hardware can barely keep up with one encode
        at a time (see module docstring) -- running several in parallel
        would only make each slower, not finish the batch sooner."""
        optimize_queue.enqueue(self.usb_root, "A.mp4")
        optimize_queue.enqueue(self.usb_root, "B.mp4")

        library_optimizer._tick(self.usb_root, "/media/usb", self.scratch_dir)

        mock_process.assert_called_once()

    @patch("admin.library_optimizer._process_job")
    def test_does_nothing_when_queue_is_empty(self, mock_process):
        library_optimizer._tick(self.usb_root, "/media/usb", self.scratch_dir)

        mock_process.assert_not_called()


class TestRunForeverStartupRecovery(LibraryOptimizerTestCase):
    """Real incident (2026-10-01): a job stuck "running" because a
    *previous* daemon instance died mid-encode (Pi reboot, service
    restart) needs to be swept back to "queued" once, at startup --
    see optimize_queue.recover_orphaned_jobs()'s own docstring."""

    @patch("admin.library_optimizer._tick")
    @patch("admin.library_optimizer.time.sleep", side_effect=KeyboardInterrupt)
    @patch("admin.library_optimizer.optimize_queue.recover_orphaned_jobs")
    def test_recovers_orphaned_jobs_once_at_startup(self, mock_recover, mock_sleep, mock_tick):
        with self.assertRaises(KeyboardInterrupt):
            library_optimizer.run_forever(self.usb_root, "/media/usb", self.scratch_dir, 5)

        mock_recover.assert_called_once_with(self.usb_root)

    @patch("admin.library_optimizer._tick")
    @patch("admin.library_optimizer.time.sleep", side_effect=KeyboardInterrupt)
    @patch(
        "admin.library_optimizer.optimize_queue.recover_orphaned_jobs",
        side_effect=OSError("boom"),
    )
    def test_a_failed_recovery_does_not_stop_the_daemon_from_starting(
        self, mock_recover, mock_sleep, mock_tick,
    ):
        """Best-effort: even if recovery itself blows up, the daemon
        must still reach its main loop, same reasoning as a single bad
        tick never being allowed to kill it."""
        with self.assertRaises(KeyboardInterrupt):
            library_optimizer.run_forever(self.usb_root, "/media/usb", self.scratch_dir, 5)

        mock_tick.assert_called_once()


if __name__ == "__main__":
    unittest.main()
