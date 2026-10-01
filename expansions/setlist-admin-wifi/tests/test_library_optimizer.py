"""
library_optimizer.py tests. pedal_core_guard.writable_usb() is mocked
(a no-op context manager) -- its own real behavior is tested in
test_admin_api.py's TestWritableUsbFallback/TestBrokenMountRecovery,
shared via the same module (pedal_core_guard.py) this daemon also
imports. subprocess.run (the actual ffmpeg call) is mocked throughout
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

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_song(self, filename: str, content: bytes = b"source bytes") -> str:
        path = os.path.join(self.usb_root, "_Songs", filename)
        with open(path, "wb") as f:
            f.write(content)
        return path


class TestProcessJob(LibraryOptimizerTestCase):
    @patch("admin.library_optimizer.subprocess.run")
    def test_successful_encode_replaces_the_file_and_clears_the_job(self, mock_run):
        self._write_song("Song.mp4", b"old hevc bytes")
        optimize_queue.enqueue(self.usb_root, "Song.mp4")

        def fake_ffmpeg(cmd, **kwargs):
            # The real ffmpeg call writes its -f mp4 output path (last
            # positional arg) -- fake that by actually writing a file
            # there, so the "copy into place" step has something real
            # to copy.
            output_path = cmd[-1]
            with open(output_path, "wb") as f:
                f.write(b"optimized h264 bytes")
            return subprocess.CompletedProcess(args=cmd, returncode=0)

        mock_run.side_effect = fake_ffmpeg

        library_optimizer._process_job(self.usb_root, "/media/usb", self.scratch_dir, "Song.mp4")

        with open(os.path.join(self.usb_root, "_Songs", "Song.mp4"), "rb") as f:
            self.assertEqual(f.read(), b"optimized h264 bytes")
        self.assertIsNone(optimize_queue.get_status(self.usb_root, "Song.mp4"))
        # The scratch file is cleaned up, not left behind.
        self.assertEqual(os.listdir(self.scratch_dir), [])

    @patch("admin.library_optimizer.subprocess.run")
    def test_missing_source_file_marks_error_without_calling_ffmpeg(self, mock_run):
        optimize_queue.enqueue(self.usb_root, "Does Not Exist.mp4")

        library_optimizer._process_job(self.usb_root, "/media/usb", self.scratch_dir, "Does Not Exist.mp4")

        mock_run.assert_not_called()
        status = optimize_queue.get_status(self.usb_root, "Does Not Exist.mp4")
        self.assertEqual(status["status"], optimize_queue.STATUS_ERROR)

    @patch("admin.library_optimizer.subprocess.run")
    def test_ffmpeg_failure_marks_error_and_leaves_the_original_untouched(self, mock_run):
        self._write_song("Song.mp4", b"original bytes")
        optimize_queue.enqueue(self.usb_root, "Song.mp4")
        mock_run.side_effect = subprocess.CalledProcessError(1, ["ffmpeg"], stderr="broken input")

        library_optimizer._process_job(self.usb_root, "/media/usb", self.scratch_dir, "Song.mp4")

        with open(os.path.join(self.usb_root, "_Songs", "Song.mp4"), "rb") as f:
            self.assertEqual(f.read(), b"original bytes")
        status = optimize_queue.get_status(self.usb_root, "Song.mp4")
        self.assertEqual(status["status"], optimize_queue.STATUS_ERROR)

    @patch("admin.library_optimizer.subprocess.run")
    def test_ffmpeg_timeout_marks_error(self, mock_run):
        self._write_song("Song.mp4")
        optimize_queue.enqueue(self.usb_root, "Song.mp4")
        mock_run.side_effect = subprocess.TimeoutExpired(["ffmpeg"], 14400)

        library_optimizer._process_job(self.usb_root, "/media/usb", self.scratch_dir, "Song.mp4")

        status = optimize_queue.get_status(self.usb_root, "Song.mp4")
        self.assertEqual(status["status"], optimize_queue.STATUS_ERROR)
        self.assertIn("too long", status["message"])

    @patch("admin.library_optimizer.subprocess.run")
    def test_marks_running_before_encoding_starts(self, mock_run):
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
            return subprocess.CompletedProcess(args=cmd, returncode=0)

        mock_run.side_effect = fake_ffmpeg

        library_optimizer._process_job(self.usb_root, "/media/usb", self.scratch_dir, "Song.mp4")

        self.assertEqual(seen_status["during_encode"], optimize_queue.STATUS_RUNNING)


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


if __name__ == "__main__":
    unittest.main()
