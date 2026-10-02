"""
codec_check.py tests -- specifically the per-(path, mtime, size) cache
added 2026-10-02 (in the sibling setlist-admin-usb expansion -- ported
here unchanged) after a real incident: list_songs() re-ran ffprobe for
every video on every single GET /api/songs, confirmed live as a ~37
second login-to-songs-loaded gap with ~24 songs, several multi-GB.

Run with: python -m unittest tests/test_codec_check.py
"""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from admin import codec_check  # noqa: E402


def _ffprobe_result(codec_name: str) -> MagicMock:
    return MagicMock(
        stdout=f'{{"streams": [{{"codec_name": "{codec_name}"}}]}}',
        returncode=0,
    )


class CodecCheckTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "Video.mp4")
        with open(self.path, "wb") as f:
            f.write(b"fake video bytes")
        # The real cache is module-level (process-lifetime) -- clear it
        # so one test's probes can't leak into another's.
        codec_check._codec_cache.clear()

    def tearDown(self):
        self.tmpdir.cleanup()


class TestProbeCaching(CodecCheckTestCase):
    @patch("admin.codec_check.subprocess.run")
    def test_second_call_on_an_unchanged_file_does_not_re_probe(self, mock_run):
        mock_run.return_value = _ffprobe_result("h264")

        first = codec_check.is_optimized(self.path, "mp4")
        second = codec_check.is_optimized(self.path, "mp4")

        self.assertTrue(first)
        self.assertTrue(second)
        mock_run.assert_called_once()

    @patch("admin.codec_check.subprocess.run")
    def test_a_replaced_file_is_re_probed(self, mock_run):
        """A new upload or a finished Optimize job both replace the file
        in place -- the new mtime/size must bust the cache automatically,
        with no manual invalidation anywhere in those code paths."""
        mock_run.return_value = _ffprobe_result("hevc")
        self.assertFalse(codec_check.is_optimized(self.path, "mp4"))

        time.sleep(0.01)  # ensure a distinct mtime on this filesystem
        with open(self.path, "wb") as f:
            f.write(b"different bytes, now optimized")
        mock_run.return_value = _ffprobe_result("h264")

        self.assertTrue(codec_check.is_optimized(self.path, "mp4"))
        self.assertEqual(mock_run.call_count, 2)

    @patch("admin.codec_check.subprocess.run")
    def test_different_files_are_cached_independently(self, mock_run):
        other_path = os.path.join(self.tmpdir.name, "Other.mp4")
        with open(other_path, "wb") as f:
            f.write(b"other bytes")
        mock_run.return_value = _ffprobe_result("h264")

        codec_check.is_optimized(self.path, "mp4")
        codec_check.is_optimized(other_path, "mp4")

        self.assertEqual(mock_run.call_count, 2)

    @patch("admin.codec_check.subprocess.run")
    def test_a_transient_probe_failure_on_an_existing_file_is_not_cached(self, mock_run):
        """Real incident (2026-10-02, in the sibling setlist-admin-usb
        expansion), minutes after this cache first shipped: several
        ffprobes run concurrently (list_songs()'s ThreadPoolExecutor)
        while the Pi was already saturated by a real Optimize job hit
        the 30s timeout at once -- caching that failure the same way as
        a success left an already-H.264 file permanently stuck showing
        "Optimize", no refresh or retry ever fixing it, since the
        file's own (path, mtime, size) never changes just because the
        *system* was briefly overloaded."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["ffprobe"], timeout=30)
        self.assertFalse(codec_check.is_optimized(self.path, "mp4"))

        mock_run.side_effect = None
        mock_run.return_value = _ffprobe_result("h264")

        self.assertTrue(codec_check.is_optimized(self.path, "mp4"))
        self.assertEqual(mock_run.call_count, 2)

    @patch("admin.codec_check.subprocess.run")
    def test_a_missing_file_is_never_cached(self, mock_run):
        missing_path = os.path.join(self.tmpdir.name, "Gone.mp4")
        mock_run.side_effect = subprocess.CalledProcessError(1, ["ffprobe"])

        codec_check.is_optimized(missing_path, "mp4")
        codec_check.is_optimized(missing_path, "mp4")

        self.assertEqual(mock_run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
