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

from admin.api import AdminAPI, AdminConfig, ApiError  # noqa: E402


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

    def tearDown(self):
        self.tmpdir.cleanup()


class TestFirstRunAndPin(ApiTestCase):
    def test_is_first_run_true_before_any_pin_set(self):
        self.assertTrue(self.api.is_first_run())

    def test_is_first_run_false_after_pin_set(self):
        self.api.set_pin("1234")
        self.assertFalse(self.api.is_first_run())

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


class TestShowsSetsTracks(ApiTestCase):
    def test_create_and_list_show(self):
        self.api.create_show("Live")
        self.assertEqual(self.api.list_shows()["shows"], ["Live"])

    def test_full_flow_show_set_track(self):
        self.api.create_show("Live")
        self.api.set_active_show("Live")
        self.api.create_set("Live", 1)
        self.api.assign_track("Live", 1, "A", "My Song", "mp3", io.BytesIO(b"data"))

        tracks = self.api.list_tracks("Live", 1)

        self.assertEqual(tracks["A"]["display_name"], "My Song")
        self.assertIsNone(tracks["B"])

    def test_swap_tracks_through_the_api(self):
        self.api.create_show("Live")
        self.api.create_set("Live", 1)
        self.api.assign_track("Live", 1, "A", "Song A", "mp3", io.BytesIO(b"a"))
        self.api.assign_track("Live", 1, "B", "Song B", "mp3", io.BytesIO(b"b"))

        self.api.swap_tracks("Live", 1, "A", "B")

        tracks = self.api.list_tracks("Live", 1)
        self.assertEqual(tracks["A"]["display_name"], "Song B")
        self.assertEqual(tracks["B"]["display_name"], "Song A")

    def test_every_mutating_method_remounts_rw_then_ro(self):
        self.api.create_show("Live")
        self.api.create_set("Live", 1)
        self.api.assign_track("Live", 1, "A", "Song", "mp3", io.BytesIO(b"data"))
        self.api.rename_track("Live", 1, "A", "New Name")
        self.api.delete_track("Live", 1, "A")
        self.api.delete_set("Live", 1)

        modes = [call.args[1] for call in self.mock_remount.call_args_list]
        # Every single logical operation above got its own rw+ro pair --
        # the number of "rw" calls equals the number of mutations, none
        # of them share or extend a window (specification section 6).
        self.assertEqual(modes.count("rw"), 6)
        self.assertEqual(modes.count("ro"), 6)


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


if __name__ == "__main__":
    unittest.main()
