"""Tests for admin.usb_mount -- specifically that _remount uses a real
umount+mount cycle, not `mount -o remount,X`, since ntfs-3g (the library
USB's actual filesystem driver, a FUSE filesystem) refuses in-place
remounts outright. Found the hard way against real hardware: SETLIST_ADMIN_USB_SPECIFICATION.md's
own section 8a testing protocol is what caught this, since no unit test
exercised the real subprocess calls before then.
"""

import subprocess
import unittest
from unittest.mock import call, patch

from admin import usb_mount


class RemountTests(unittest.TestCase):
    @patch("admin.usb_mount.subprocess.run")
    def test_remount_rw_does_umount_then_mount_not_inplace_remount(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        usb_mount._remount("/media/usb", "rw")

        mock_run.assert_has_calls([
            call(["sudo", "umount", "/media/usb"], capture_output=True, check=True, timeout=10),
            call(["sudo", "mount", "-o", "rw", "/media/usb"], capture_output=True, check=True, timeout=10),
        ])
        for c in mock_run.call_args_list:
            self.assertNotIn("remount", " ".join(c.args[0]))

    @patch("admin.usb_mount.subprocess.run")
    def test_remount_failure_to_unmount_raises_without_attempting_mount(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(11, ["sudo", "umount", "/media/usb"])

        with self.assertRaises(usb_mount.RemountError):
            usb_mount._remount("/media/usb", "rw")

        self.assertEqual(mock_run.call_count, 1)

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
            call(["sudo", "umount", "/media/usb"], capture_output=True, check=True, timeout=10),
            call(["sudo", "mount", "-o", "rw", "/media/usb"], capture_output=True, check=True, timeout=10),
            call(["sudo", "mount", "-o", "ro", "/media/usb"], capture_output=True, timeout=10),
        ])


if __name__ == "__main__":
    unittest.main()
