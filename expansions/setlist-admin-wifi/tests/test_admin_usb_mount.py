"""Tests for admin.usb_mount -- specifically that _remount uses a real
umount+mount cycle, not `mount -o remount,X`, since ntfs-3g (the library
USB's actual filesystem driver, a FUSE filesystem) refuses in-place
remounts outright. Found the hard way against real hardware: SETLIST_ADMIN_SPECIFICATION.md's
own section 8a testing protocol is what caught this, since no unit test
exercised the real subprocess calls before then.
"""

import subprocess
import threading
import time
import unittest
from unittest.mock import call, patch

from admin import usb_mount


class RemountTests(unittest.TestCase):
    @patch("admin.usb_mount.subprocess.run")
    def test_remount_rw_does_umount_then_mount_not_inplace_remount(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        usb_mount._remount("/media/usb", "rw")

        mock_run.assert_has_calls([
            call(["sudo", "umount", "/media/usb"], capture_output=True, timeout=10, text=True),
            call(["sudo", "mount", "-o", "rw", "/media/usb"], capture_output=True, check=True, timeout=10),
        ])
        for c in mock_run.call_args_list:
            self.assertNotIn("remount", " ".join(c.args[0]))

    @patch("admin.usb_mount.time.sleep")
    @patch("admin.usb_mount.subprocess.run")
    def test_remount_failure_to_unmount_raises_without_attempting_mount(self, mock_run, mock_sleep):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["sudo", "umount", "/media/usb"], returncode=32,
            stdout="", stderr="umount: /media/usb: target is busy.",
        )

        with self.assertRaises(usb_mount.RemountError):
            usb_mount._remount("/media/usb", "rw")

        # Every attempt is a real, persistent EBUSY here (never clears), so
        # this exhausts the whole retry budget before giving up -- not just
        # one immediate failure.
        self.assertEqual(mock_run.call_count, usb_mount._UMOUNT_MAX_ATTEMPTS)

    @patch("admin.usb_mount.time.sleep")
    @patch("admin.usb_mount.subprocess.run")
    def test_remount_retries_transient_umount_busy_then_succeeds(self, mock_run, mock_sleep):
        # Real scenario found on hardware: pedal-core.service's mpv holds
        # /media/usb transiently busy (EBUSY) for an instant; the very next
        # attempt, moments later, succeeds cleanly.
        calls = {"umount": 0}

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["sudo", "umount"]:
                calls["umount"] += 1
                if calls["umount"] < 3:
                    return subprocess.CompletedProcess(
                        args=cmd, returncode=32, stdout="", stderr="umount: /media/usb: target is busy.",
                    )
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0)

        mock_run.side_effect = side_effect

        usb_mount._remount("/media/usb", "rw")

        self.assertEqual(calls["umount"], 3)
        mock_sleep.assert_called()

    @patch("admin.usb_mount.time.sleep")
    @patch("admin.usb_mount.subprocess.run")
    def test_remount_self_heals_when_umount_says_not_mounted(self, mock_run, mock_sleep):
        # Real anomaly found on hardware: the library USB has turned up
        # spontaneously unmounted with no corresponding log evidence
        # anywhere, unrelated to any write this app was doing (see
        # CHANGELOG). umount then fails, but only because there is
        # nothing left to unmount -- retrying the same umount is
        # pointless, but proceeding straight to the mount step below
        # self-heals instead of permanently failing every write until a
        # human notices and runs `sudo mount -a` by hand.
        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["sudo", "umount"]:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=32, stdout="", stderr="umount: /media/usb: not mounted.",
                )
            return subprocess.CompletedProcess(args=cmd, returncode=0)

        mock_run.side_effect = side_effect

        usb_mount._remount("/media/usb", "rw")  # must not raise

        mock_run.assert_has_calls([
            call(["sudo", "umount", "/media/usb"], capture_output=True, timeout=10, text=True),
            call(["sudo", "mount", "-o", "rw", "/media/usb"], capture_output=True, check=True, timeout=10),
        ])
        # Already achieved on the very first try -- no retry delay needed.
        mock_sleep.assert_not_called()

    @patch("admin.usb_mount.subprocess.run")
    def test_remount_failure_to_mount_falls_back_to_ro_then_raises(self, mock_run):
        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["sudo", "umount"]:
                return subprocess.CompletedProcess(args=cmd, returncode=0)
            if cmd == ["sudo", "mount", "-o", "rw", "/media/usb"]:
                raise subprocess.CalledProcessError(1, cmd)
            if cmd == ["sudo", "mount", "-o", "ro", "/media/usb"]:
                return subprocess.CompletedProcess(args=cmd, returncode=0)
            raise AssertionError(f"unexpected command: {cmd}")

        mock_run.side_effect = side_effect

        with self.assertRaises(usb_mount.RemountError):
            usb_mount._remount("/media/usb", "rw")

        mock_run.assert_has_calls([
            call(["sudo", "umount", "/media/usb"], capture_output=True, timeout=10, text=True),
            call(["sudo", "mount", "-o", "rw", "/media/usb"], capture_output=True, check=True, timeout=10),
            call(["sudo", "mount", "-o", "ro", "/media/usb"], capture_output=True, timeout=10),
        ])


class EnsureMountedTests(unittest.TestCase):
    @patch("admin.usb_mount.os.path.ismount")
    @patch("admin.usb_mount.subprocess.run")
    def test_already_mounted_does_nothing(self, mock_run, mock_ismount):
        mock_ismount.return_value = True

        usb_mount.ensure_mounted("/media/usb")

        mock_run.assert_not_called()

    @patch("admin.usb_mount.os.path.ismount")
    @patch("admin.usb_mount.subprocess.run")
    def test_not_mounted_self_heals_by_mounting(self, mock_run, mock_ismount):
        # Real anomaly seen on hardware: a read-only check (e.g. "is a
        # PIN already set?") found the USB spontaneously unmounted with
        # no corresponding log evidence anywhere. A plain `sudo mount`
        # recovers it without needing writable_usb()'s umount+mount
        # cycle -- there's nothing to unmount first.
        mock_ismount.side_effect = [False, True]  # unmounted, then recovered
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        usb_mount.ensure_mounted("/media/usb")

        mock_run.assert_called_once_with(
            ["sudo", "mount", "/media/usb"], capture_output=True, timeout=10,
        )

    @patch("admin.usb_mount.os.path.ismount")
    @patch("admin.usb_mount.subprocess.run")
    def test_not_mounted_and_recovery_fails_raises(self, mock_run, mock_ismount):
        mock_ismount.return_value = False  # never recovers
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1)

        with self.assertRaises(usb_mount.RemountError):
            usb_mount.ensure_mounted("/media/usb")


class WritableUsbLockingTests(unittest.TestCase):
    @patch("admin.usb_mount.subprocess.run")
    def test_concurrent_writable_usb_calls_are_serialized(self, mock_run):
        # Real bug found on hardware: a double-tap on "Save to library"
        # fired two overlapping requests, each running its own raw
        # umount/mount cycle against the same mount point with no
        # coordination -- one request's closing remount collided with the
        # other's opening one ("Failed to mount /media/usb as ro: ...exit
        # status 16"). writable_usb() must let only one caller through at
        # a time, process-wide.
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        concurrent = {"count": 0, "max": 0}
        counter_lock = threading.Lock()

        def worker():
            with usb_mount.writable_usb("/media/usb"):
                with counter_lock:
                    concurrent["count"] += 1
                    concurrent["max"] = max(concurrent["max"], concurrent["count"])
                time.sleep(0.05)
                with counter_lock:
                    concurrent["count"] -= 1

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(concurrent["max"], 1)


if __name__ == "__main__":
    unittest.main()
