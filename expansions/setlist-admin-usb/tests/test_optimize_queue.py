"""
optimize_queue.py tests. No hardware needed -- a plain temp directory,
same style as tests/test_library.py.

Run with: python -m unittest tests/test_optimize_queue.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from admin import optimize_queue  # noqa: E402


class OptimizeQueueTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.usb_root = self.tmpdir.name

    def tearDown(self):
        self.tmpdir.cleanup()


class TestBasicLifecycle(OptimizeQueueTestCase):
    def test_no_job_returns_none(self):
        self.assertIsNone(optimize_queue.get_status(self.usb_root, "Song.mp4"))

    def test_enqueue_then_get_status(self):
        optimize_queue.enqueue(self.usb_root, "Song.mp4")

        status = optimize_queue.get_status(self.usb_root, "Song.mp4")

        self.assertEqual(status["status"], optimize_queue.STATUS_QUEUED)
        self.assertIn("requested_at", status)

    def test_mark_running_overwrites_queued(self):
        optimize_queue.enqueue(self.usb_root, "Song.mp4")

        optimize_queue.mark_running(self.usb_root, "Song.mp4")

        self.assertEqual(
            optimize_queue.get_status(self.usb_root, "Song.mp4")["status"],
            optimize_queue.STATUS_RUNNING,
        )

    def test_mark_error_includes_message(self):
        optimize_queue.enqueue(self.usb_root, "Song.mp4")

        optimize_queue.mark_error(self.usb_root, "Song.mp4", "Encoding failed")

        status = optimize_queue.get_status(self.usb_root, "Song.mp4")
        self.assertEqual(status["status"], optimize_queue.STATUS_ERROR)
        self.assertEqual(status["message"], "Encoding failed")

    def test_clear_removes_the_job(self):
        optimize_queue.enqueue(self.usb_root, "Song.mp4")

        optimize_queue.clear(self.usb_root, "Song.mp4")

        self.assertIsNone(optimize_queue.get_status(self.usb_root, "Song.mp4"))

    def test_clear_on_a_job_that_was_never_queued_does_not_raise(self):
        optimize_queue.clear(self.usb_root, "Never Queued.mp4")  # must not raise

    def test_enqueue_again_retries_an_errored_job(self):
        """Real design point: tapping "Optimize" again after a failure
        is how a job gets retried -- enqueue() always overwrites
        whatever marker (queued/running/error) was already there."""
        optimize_queue.enqueue(self.usb_root, "Song.mp4")
        optimize_queue.mark_error(self.usb_root, "Song.mp4", "boom")

        optimize_queue.enqueue(self.usb_root, "Song.mp4")

        self.assertEqual(
            optimize_queue.get_status(self.usb_root, "Song.mp4")["status"],
            optimize_queue.STATUS_QUEUED,
        )


class TestListQueued(OptimizeQueueTestCase):
    def test_lists_only_queued_jobs(self):
        optimize_queue.enqueue(self.usb_root, "A.mp4")
        optimize_queue.enqueue(self.usb_root, "B.mp4")
        optimize_queue.mark_running(self.usb_root, "B.mp4")
        optimize_queue.enqueue(self.usb_root, "C.mp4")
        optimize_queue.mark_error(self.usb_root, "C.mp4", "boom")

        self.assertEqual(list(optimize_queue.list_queued(self.usb_root)), ["A.mp4"])

    def test_empty_when_no_queue_directory_exists_yet(self):
        self.assertEqual(list(optimize_queue.list_queued(self.usb_root)), [])

    def test_filenames_with_spaces_and_accents_round_trip(self):
        optimize_queue.enqueue(self.usb_root, "Canción - Año.mp4")

        self.assertEqual(
            list(optimize_queue.list_queued(self.usb_root)), ["Canción - Año.mp4"],
        )


class TestRecoverOrphanedJobs(OptimizeQueueTestCase):
    """Real incident (2026-10-01): a job marked "running" whose daemon
    then dies (a Pi reboot, a service restart) before finishing stays
    stuck forever -- list_queued() never picks "running" back up on
    its own. recover_orphaned_jobs() is called once at daemon startup
    to reset any such orphan back to "queued"."""

    def test_running_job_is_reset_to_queued(self):
        optimize_queue.enqueue(self.usb_root, "Song.mp4")
        optimize_queue.mark_running(self.usb_root, "Song.mp4")

        optimize_queue.recover_orphaned_jobs(self.usb_root)

        self.assertEqual(
            optimize_queue.get_status(self.usb_root, "Song.mp4")["status"],
            optimize_queue.STATUS_QUEUED,
        )
        self.assertEqual(list(optimize_queue.list_queued(self.usb_root)), ["Song.mp4"])

    def test_leaves_queued_and_error_jobs_untouched(self):
        optimize_queue.enqueue(self.usb_root, "Queued.mp4")
        optimize_queue.enqueue(self.usb_root, "Errored.mp4")
        optimize_queue.mark_error(self.usb_root, "Errored.mp4", "boom")

        optimize_queue.recover_orphaned_jobs(self.usb_root)

        self.assertEqual(
            optimize_queue.get_status(self.usb_root, "Queued.mp4")["status"],
            optimize_queue.STATUS_QUEUED,
        )
        self.assertEqual(
            optimize_queue.get_status(self.usb_root, "Errored.mp4")["status"],
            optimize_queue.STATUS_ERROR,
        )

    def test_empty_queue_does_not_raise(self):
        optimize_queue.recover_orphaned_jobs(self.usb_root)  # must not raise


if __name__ == "__main__":
    unittest.main()
