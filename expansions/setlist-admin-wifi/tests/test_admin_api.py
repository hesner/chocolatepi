"""
api.py tests. Runs against a real temp directory as the "USB" (so
library_ops runs for real, not mocked) -- only `usb_mount`'s actual
`sudo mount` subprocess call is patched out, since there's no real
mount to remount in a unit test. `nmcli` is likewise patched wherever
WiFi methods are exercised.

Run with: python -m unittest tests/test_admin_api.py
"""

import io
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from admin import library_ops, optimize_queue  # noqa: E402
from admin.api import AdminAPI, AdminConfig, ApiError  # noqa: E402
from admin.usb_mount import RemountError  # noqa: E402


class ApiTestCase(unittest.TestCase):
    """Base class: no real `sudo mount` in tests -- every subclass gets
    self.mock_remount for free via setUp(), which (unlike a class-level
    @patch decorator) correctly applies to test methods defined on
    subclasses, not just on this class itself."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.usb_root = self.tmpdir.name
        self.api = AdminAPI(AdminConfig(usb_root=self.usb_root, usb_uuid="test-usb-uuid"))

        remount_patcher = patch("admin.usb_mount._remount")
        self.mock_remount = remount_patcher.start()
        self.addCleanup(remount_patcher.stop)

        ensure_mounted_patcher = patch("admin.usb_mount.ensure_mounted")
        self.mock_ensure_mounted = ensure_mounted_patcher.start()
        self.addCleanup(ensure_mounted_patcher.stop)

        # The cancel marker lives outside usb_root now (see
        # optimize_queue.DEFAULT_STATE_DIR's own comment) -- pointed at
        # an isolated per-test directory so tests never touch the real
        # default (a real path under the developer's/Pi's home dir) or
        # collide with each other. Nested under usb_root here purely
        # for convenience (this test case's tmpdir *is* usb_root) --
        # nothing about the real default lives on the USB any more.
        state_dir = os.path.join(self.usb_root, "optimizer-state")
        state_dir_patcher = patch("admin.optimize_queue.DEFAULT_STATE_DIR", state_dir)
        state_dir_patcher.start()
        self.addCleanup(state_dir_patcher.stop)

    def tearDown(self):
        self.tmpdir.cleanup()


class TestFirstRunAndPin(ApiTestCase):
    def test_is_first_run_true_before_any_pin_set(self):
        self.assertTrue(self.api.is_first_run())

    def test_is_first_run_false_after_pin_set(self):
        self.api.set_pin("1234")
        self.assertFalse(self.api.is_first_run())

    def test_is_first_run_raises_503_if_usb_unreachable(self):
        # Real anomaly seen on hardware: the library USB turns up
        # spontaneously unmounted with a PIN already set on it -- without
        # this, is_first_run() would just see an empty directory and
        # wrongly report "first run," prompting to set a new PIN over one
        # that's still there, just unreachable.
        from admin import usb_mount
        self.mock_ensure_mounted.side_effect = usb_mount.RemountError("nope")

        with self.assertRaises(ApiError) as ctx:
            self.api.is_first_run()
        self.assertEqual(ctx.exception.status, 503)

    def test_set_pin_wraps_the_write_in_a_remount(self):
        self.api.set_pin("1234")
        # rw then ro -- writable_usb() always does both, even on success.
        modes = [call.args[1] for call in self.mock_remount.call_args_list]
        self.assertIn("rw", modes)
        self.assertIn("ro", modes)

    def test_short_pin_is_rejected(self):
        with self.assertRaises(ApiError) as ctx:
            self.api.set_pin("12")
        self.assertEqual(ctx.exception.status, 400)

    def test_login_with_correct_pin_returns_a_token(self):
        self.api.set_pin("1234")
        token = self.api.login("1234")
        self.assertTrue(token)

    def test_login_with_wrong_pin_raises_401(self):
        self.api.set_pin("1234")
        with self.assertRaises(ApiError) as ctx:
            self.api.login("9999")
        self.assertEqual(ctx.exception.status, 401)

    def test_login_before_any_pin_set_raises_409(self):
        with self.assertRaises(ApiError) as ctx:
            self.api.login("1234")
        self.assertEqual(ctx.exception.status, 409)

    def test_require_session_accepts_a_real_token(self):
        self.api.set_pin("1234")
        token = self.api.login("1234")
        self.api.require_session(token)  # should not raise

    def test_require_session_rejects_missing_token(self):
        self.api.set_pin("1234")
        with self.assertRaises(ApiError) as ctx:
            self.api.require_session(None)
        self.assertEqual(ctx.exception.status, 401)

    def test_require_session_rejects_garbage_token(self):
        self.api.set_pin("1234")
        with self.assertRaises(ApiError):
            self.api.require_session("not-a-real-token")

    def test_resetting_pin_invalidates_old_sessions(self):
        # The actual property PIN recovery depends on (specification
        # section 5a): after a reset (simulated here by calling set_pin
        # again, the same code path SSH-based recovery ends in), an old
        # session token must stop working.
        self.api.set_pin("1234")
        old_token = self.api.login("1234")

        self.api.set_pin("5678")

        with self.assertRaises(ApiError):
            self.api.require_session(old_token)


class TestSetsBanksTracks(ApiTestCase):
    def test_cleanup_stale_temp_files_wraps_in_a_remount(self):
        removed = self.api.cleanup_stale_temp_files()

        self.assertEqual(removed, 0)  # nothing stale on a fresh USB
        modes = [call.args[1] for call in self.mock_remount.call_args_list]
        self.assertIn("rw", modes)
        self.assertIn("ro", modes)

    def test_create_and_list_set(self):
        self.api.create_set("Live")
        self.assertEqual(self.api.list_sets()["sets"], ["Live"])

    def test_full_flow_set_bank_track(self):
        self.api.create_set("Live")
        self.api.set_active_set("Live")
        self.api.create_bank("Live", 1)
        self.api.assign_track("Live", 1, "A", "My Song", "mp3", io.BytesIO(b"data"))

        tracks = self.api.list_tracks("Live", 1)

        self.assertEqual(tracks["A"]["display_name"], "My Song")
        self.assertIsNone(tracks["B"])

    def test_swap_tracks_through_the_api(self):
        self.api.create_set("Live")
        self.api.create_bank("Live", 1)
        self.api.assign_track("Live", 1, "A", "Song A", "mp3", io.BytesIO(b"a"))
        self.api.assign_track("Live", 1, "B", "Song B", "mp3", io.BytesIO(b"b"))

        self.api.swap_tracks("Live", 1, "A", "B")

        tracks = self.api.list_tracks("Live", 1)
        self.assertEqual(tracks["A"]["display_name"], "Song B")
        self.assertEqual(tracks["B"]["display_name"], "Song A")

    def test_every_mutating_method_remounts_rw_then_ro(self):
        self.api.create_set("Live")
        self.api.create_bank("Live", 1)
        self.api.assign_track("Live", 1, "A", "Song", "mp3", io.BytesIO(b"data"))
        self.api.rename_track("Live", 1, "A", "New Name")
        self.api.delete_track("Live", 1, "A")
        self.api.delete_bank("Live", 1)

        modes = [call.args[1] for call in self.mock_remount.call_args_list]
        # Every single logical operation above gets its own rw+ro pair for
        # the real write -- but _writable_usb() (api.py) now also does a
        # cheap, side-effect-free rw+ro probe cycle first (to decide
        # whether pedal-core.service needs stopping -- see its docstring),
        # so each mutation shows up as *two* rw+ro pairs here when the
        # probe succeeds (as it does with _remount mocked to always
        # succeed), not one. None of them share or extend a window either
        # way (specification section 6).
        self.assertEqual(modes.count("rw"), 12)
        self.assertEqual(modes.count("ro"), 12)


class TestWritableUsbFallback(ApiTestCase):
    """_writable_usb() (api.py): real incident found on real hardware
    2026-10-01 (in the sibling setlist-admin-usb expansion, ported here
    unchanged) -- pedal-core.service's mpv can hold /media/usb's
    currently-looping file open indefinitely (confirmed: never releases
    on its own), which the bounded retry inside usb_mount._remount()
    (built for a brief, transient busy window) can't get past. These
    test the fallback: a cheap probe first; if it fails, stop
    pedal-core.service, do the real write, then restart it -- without
    ever attempting the real write itself more than once."""

    @patch("admin.api.subprocess.run")
    def test_fast_path_never_touches_pedal_core(self, mock_run):
        self.api.create_set("Live")
        mock_run.assert_not_called()

    @patch("admin.api.subprocess.run")
    def test_falls_back_to_stopping_pedal_core_when_probe_fails(self, mock_run):
        mock_run.return_value = MagicMock(stdout="active\n", returncode=0)
        self.mock_remount.side_effect = [RemountError("busy")] + [None] * 10

        self.api.create_set("Live")

        commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertIn(["systemctl", "is-active", "pedal-core.service"], commands)
        self.assertIn(["sudo", "systemctl", "stop", "pedal-core.service"], commands)
        self.assertIn(["sudo", "systemctl", "start", "pedal-core.service"], commands)
        self.assertEqual(library_ops.list_sets(self.usb_root), ["Live"])

    @patch("admin.api.subprocess.run")
    def test_does_not_restart_pedal_core_if_it_was_not_running(self, mock_run):
        mock_run.return_value = MagicMock(stdout="inactive\n", returncode=0)
        self.mock_remount.side_effect = [RemountError("busy")] + [None] * 10

        self.api.create_set("Live")

        commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertIn(["systemctl", "is-active", "pedal-core.service"], commands)
        self.assertNotIn(["sudo", "systemctl", "stop", "pedal-core.service"], commands)
        self.assertNotIn(["sudo", "systemctl", "start", "pedal-core.service"], commands)

    @patch("admin.api.subprocess.run")
    def test_probe_failure_alone_does_not_raise_to_the_caller(self, mock_run):
        mock_run.return_value = MagicMock(stdout="active\n", returncode=0)
        self.mock_remount.side_effect = [RemountError("busy")] + [None] * 10

        self.api.create_set("Live")  # must not raise


class TestCleanupRemountRecovery(ApiTestCase):
    """_writable_usb()'s cleanup-recovery branch (pedal_core_guard.py):
    real incident found live (2026-10-01) testing the "Optimize"
    feature's large uploads -- the fast probe only checks whether the
    mount is free *right now*, so a slow, multi-minute write can still
    find pedal-core.service's mpv has grabbed the mount again (on its
    next standby-video loop) by the time it's done, failing only the
    cleanup remount back to ro -- even though the write itself already
    succeeded. Confirmed live: the uploaded file was intact and already
    on disk, but the phone saw a scary "internal error" for an upload
    that had, in fact, already worked. These confirm that case recovers
    instead of surfacing a misleading failure."""

    @patch("admin.api.subprocess.run")
    def test_successful_write_with_a_failed_cleanup_remount_recovers_without_raising(self, mock_run):
        mock_run.return_value = MagicMock(stdout="active\n", returncode=0)
        # Probe: rw, ro (both succeed). Real write: rw (succeeds), the
        # operation itself runs, then the cleanup ro remount fails once
        # -- the retry after stopping pedal-core.service succeeds.
        self.mock_remount.side_effect = [None, None, None, RemountError("busy"), None]

        self.api.create_set("Live")  # must not raise

        self.assertEqual(library_ops.list_sets(self.usb_root), ["Live"])
        commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertIn(["sudo", "systemctl", "stop", "pedal-core.service"], commands)
        self.assertIn(["sudo", "systemctl", "start", "pedal-core.service"], commands)

    @patch("admin.api.subprocess.run")
    def test_does_not_stop_pedal_core_a_second_time_if_the_probe_already_did(self, mock_run):
        mock_run.return_value = MagicMock(stdout="active\n", returncode=0)
        # Probe's rw remount fails -> the existing fallback already
        # stops pedal-core.service up front. The real write's rw then
        # succeeds, the operation runs, and the cleanup ro remount
        # *still* fails -- the retry must not try to stop it again.
        self.mock_remount.side_effect = [RemountError("busy"), None, RemountError("busy"), None]

        self.api.create_set("Live")  # must not raise

        stop_calls = [
            c.args[0] for c in mock_run.call_args_list
            if c.args[0] == ["sudo", "systemctl", "stop", "pedal-core.service"]
        ]
        self.assertEqual(len(stop_calls), 1)


class TestBrokenMountRecovery(ApiTestCase):
    """_ensure_usb_accessible_before_restart() (api.py): real incident
    found live on real hardware 2026-10-01 (in the sibling
    setlist-admin-usb expansion, ported here unchanged) -- the write's
    own remount-back-to-ro can itself fail and leave the FUSE mount
    genuinely dead (`mount` still lists it, but every access returns
    ENOTCONN). Restarting pedal-core.service blindly into that state
    made it worse (mpv immediately tried to open standby.mp4 against the
    broken mount). These confirm the self-healing check-then-recover
    sequence runs before pedal-core.service is ever restarted."""

    @staticmethod
    def _subprocess_side_effect(ls_results):
        remaining = list(ls_results)

        def _run(cmd, **kwargs):
            if cmd[:2] == ["systemctl", "is-active"]:
                return MagicMock(stdout="active\n", returncode=0)
            if cmd[0] == "ls":
                healthy = remaining.pop(0) if remaining else True
                return MagicMock(returncode=0 if healthy else 1)
            return MagicMock(returncode=0)

        return _run

    @patch("admin.api.subprocess.run")
    def test_healthy_mount_skips_recovery_entirely(self, mock_run):
        mock_run.side_effect = self._subprocess_side_effect([True])
        self.mock_remount.side_effect = [RemountError("busy")] + [None] * 10

        self.api.create_set("Live")

        commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertIn(["ls", self.api.config.mount_point], commands)
        self.assertNotIn(["sudo", "umount", "-l", self.api.config.mount_point], commands)
        self.assertIn(["sudo", "systemctl", "start", "pedal-core.service"], commands)

    @patch("admin.api.subprocess.run")
    def test_broken_mount_is_recovered_before_restarting_pedal_core(self, mock_run):
        mock_run.side_effect = self._subprocess_side_effect([False, True])
        self.mock_remount.side_effect = [RemountError("busy")] + [None] * 10

        self.api.create_set("Live")

        commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertIn(["sudo", "umount", "-l", self.api.config.mount_point], commands)
        self.assertIn(["sudo", "mount", "-o", "ro", self.api.config.mount_point], commands)
        umount_idx = commands.index(["sudo", "umount", "-l", self.api.config.mount_point])
        start_idx = commands.index(["sudo", "systemctl", "start", "pedal-core.service"])
        self.assertLess(umount_idx, start_idx)

    @patch("admin.api.subprocess.run")
    def test_still_broken_after_recovery_attempt_still_restarts_pedal_core(self, mock_run):
        mock_run.side_effect = self._subprocess_side_effect([False, False])
        self.mock_remount.side_effect = [RemountError("busy")] + [None] * 10

        self.api.create_set("Live")  # must not raise

        commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertIn(["sudo", "systemctl", "start", "pedal-core.service"], commands)


class TestPlaybackWarning(ApiTestCase):
    @patch("admin.api.subprocess.run")
    def test_reports_active_when_pedal_core_is_running(self, mock_run):
        mock_run.return_value = MagicMock(stdout="active\n")
        self.assertTrue(self.api.is_playback_likely_active())

    @patch("admin.api.subprocess.run")
    def test_reports_inactive_when_pedal_core_is_not_running(self, mock_run):
        mock_run.return_value = MagicMock(stdout="inactive\n")
        self.assertFalse(self.api.is_playback_likely_active())

    @patch("admin.api.subprocess.run")
    def test_never_raises_if_systemctl_is_unavailable(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        self.assertFalse(self.api.is_playback_likely_active())


class TestWifi(ApiTestCase):
    @patch("admin.api.wifi.apply_home_profile")
    @patch("admin.api.crypto.read_machine_id", return_value="test-machine-id")
    def test_set_home_wifi_persists_and_applies(self, mock_machine_id, mock_apply):
        self.api.set_home_wifi("HomeNetwork", "hunter2")

        mock_apply.assert_called_once()
        applied_profile = mock_apply.call_args.args[0]
        self.assertEqual(applied_profile.ssid, "HomeNetwork")

        # And it's readable back through the same encrypted path a
        # reboot would use (network_watchdog.py's own load path).
        config = self.api._load_network_config()
        self.assertEqual(config.home.ssid, "HomeNetwork")

    @patch("admin.api.crypto.read_machine_id", return_value="test-machine-id")
    def test_set_home_wifi_rejects_empty_ssid(self, mock_machine_id):
        with self.assertRaises(ApiError) as ctx:
            self.api.set_home_wifi("", "password")
        self.assertEqual(ctx.exception.status, 400)


class TestUploadSongOverwrite(ApiTestCase):
    """api.py.upload_song()'s overwrite support -- real user request,
    2026-10-01 (in the sibling setlist-admin-usb expansion, ported here
    unchanged). Raises ApiError(409), not a generic 400, specifically
    for this case so the frontend can distinguish it without
    string-matching the error text."""

    def test_duplicate_without_overwrite_raises_409(self):
        self.api.upload_song("Song", "mp3", io.BytesIO(b"first"))

        with self.assertRaises(ApiError) as ctx:
            self.api.upload_song("Song", "mp3", io.BytesIO(b"second"))
        self.assertEqual(ctx.exception.status, 409)
        self.assertIn("already exists", ctx.exception.message)

    def test_overwrite_true_replaces_it(self):
        self.api.upload_song("Song", "mp3", io.BytesIO(b"first"))

        self.api.upload_song("Song", "mp3", io.BytesIO(b"second"), overwrite=True)

        songs = self.api.list_songs()["songs"]
        self.assertEqual(len(songs), 1)


class TestListSongsOptimizationFields(ApiTestCase):
    """list_songs()'s needs_optimization/optimization_status fields --
    real user request, 2026-10-01, for the "Optimize" button feature
    (see library_optimizer.py). codec_check.is_optimized() is mocked
    directly here rather than relying on ffprobe against fake test
    content (which just fails to probe it either way -- mocking makes
    the two cases this exercises deterministic)."""

    def test_audio_only_song_never_needs_optimization(self):
        self.api.upload_song("Song", "mp3", io.BytesIO(b"data"))

        songs = self.api.list_songs()["songs"]

        self.assertFalse(songs[0]["needs_optimization"])
        self.assertIsNone(songs[0]["optimization_status"])

    @patch("admin.api.codec_check.is_optimized", return_value=False)
    def test_unoptimized_video_with_no_job_shows_no_status(self, mock_is_optimized):
        self.api.upload_song("Video", "mp4", io.BytesIO(b"data"))

        songs = self.api.list_songs()["songs"]

        self.assertTrue(songs[0]["needs_optimization"])
        self.assertIsNone(songs[0]["optimization_status"])

    @patch("admin.api.codec_check.is_optimized", return_value=False)
    def test_queued_job_is_reflected_in_status(self, mock_is_optimized):
        self.api.upload_song("Video", "mp4", io.BytesIO(b"data"))

        self.api.request_song_optimization("Video.mp4")

        songs = self.api.list_songs()["songs"]
        self.assertEqual(songs[0]["optimization_status"], "queued")

    @patch("admin.api.codec_check.is_optimized", return_value=True)
    def test_optimized_video_shows_no_button_even_with_a_stale_job_marker(self, mock_is_optimized):
        """Once a file genuinely passes the codec check (e.g. the
        optimizer just finished, or it was already fine), it's reported
        as optimized regardless of any leftover job bookkeeping -- the
        file itself is always the source of truth."""
        self.api.upload_song("Video", "mp4", io.BytesIO(b"data"))

        songs = self.api.list_songs()["songs"]

        self.assertFalse(songs[0]["needs_optimization"])


class TestRequestSongOptimization(ApiTestCase):
    def test_queues_a_job_for_an_existing_song(self):
        self.api.upload_song("Video", "mp4", io.BytesIO(b"data"))

        self.api.request_song_optimization("Video.mp4")

        status = optimize_queue.get_status(self.usb_root, "Video.mp4")
        self.assertEqual(status["status"], "queued")

    def test_raises_404_for_a_song_not_in_the_library(self):
        with self.assertRaises(ApiError) as ctx:
            self.api.request_song_optimization("Does Not Exist.mp4")
        self.assertEqual(ctx.exception.status, 404)


class TestCancelSongOptimization(ApiTestCase):
    """Real user request (2026-10-02, in the sibling setlist-admin-usb
    expansion, ported here unchanged), after a real incident: an
    optimize job can run for hours with no visible progress, which is
    a real temptation to just unplug the Pi."""

    def test_cancelling_a_queued_job_writes_a_cancel_marker(self):
        self.api.upload_song("Video", "mp4", io.BytesIO(b"data"))
        self.api.request_song_optimization("Video.mp4")

        self.api.cancel_song_optimization("Video.mp4")

        self.assertTrue(optimize_queue.is_cancel_requested("Video.mp4"))

    def test_cancelling_a_song_with_no_active_job_does_nothing(self):
        """Not a no-op by accident: writing the marker anyway would sit
        there forever (nothing would ever clear it) and silently
        cancel some unrelated *future* job requested for the same
        filename before it even got to start."""
        self.api.upload_song("Video", "mp4", io.BytesIO(b"data"))

        self.api.cancel_song_optimization("Video.mp4")  # must not raise

        self.assertFalse(optimize_queue.is_cancel_requested("Video.mp4"))

    def test_cancelling_an_unknown_song_does_not_raise(self):
        self.api.cancel_song_optimization("Does Not Exist.mp4")  # must not raise


class TestStandby(ApiTestCase):
    def test_get_standby_when_none_set(self):
        result = self.api.get_standby()
        self.assertEqual(result, {"exists": False, "size_bytes": 0, "modified_at": 0.0})

    def test_set_standby_from_an_uploaded_library_video(self):
        self.api.upload_song("My Loop", "mp4", io.BytesIO(b"video bytes"))

        self.api.set_standby("My Loop.mp4")

        result = self.api.get_standby()
        self.assertTrue(result["exists"])
        self.assertEqual(result["size_bytes"], len(b"video bytes"))

    def test_set_standby_raises_api_error_for_unknown_song(self):
        with self.assertRaises(ValueError):
            self.api.set_standby("Does Not Exist.mp4")


if __name__ == "__main__":
    unittest.main()
