"""
The rw/ro remount discipline from SETLIST_ADMIN_USB_SPECIFICATION.md section 6,
as a context manager: the library USB is read-only during normal
operation (MASTER_SPECIFICATION.md section 2), so every write this app
makes briefly remounts it read-write, does exactly one logical
operation, then remounts it read-only again -- the same manual sequence
this project has used by hand (via SSH) all along, now automated.

Deliberately its own tiny module, separate from `library_ops.py`: that
module stays pure filesystem logic, testable against a plain temp
directory with no `sudo`/mount calls involved at all. Only `api.py`
(talking to the real, mounted USB) needs this.
"""

import logging
import subprocess
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DEFAULT_MOUNT_POINT = "/media/usb"


class RemountError(Exception):
    """Raised if remounting rw or ro fails. Callers should treat this as
    fatal for the operation being attempted -- proceeding to write
    without confirming rw succeeded risks the same silent failure this
    whole app exists to eliminate."""


@contextmanager
def writable_usb(mount_point: str = DEFAULT_MOUNT_POINT):
    """Remounts `mount_point` read-write for the duration of the `with`
    block, then always remounts it read-only again on the way out --
    including if the block raises. The window this stays writable is
    exactly one caller-defined operation, never longer."""
    _remount(mount_point, "rw")
    try:
        yield
    finally:
        _remount(mount_point, "ro")


def _remount(mount_point: str, mode: str) -> None:
    # ntfs-3g (a FUSE filesystem, unlike vfat/ext4's in-kernel drivers) does
    # not support `mount -o remount,X` at all -- it refuses outright with
    # "Remounting is not supported at present. You have to umount volume
    # and then mount it once again.", confirmed against the real library
    # USB. So this does exactly what that message says: a real umount
    # followed by a fresh mount in the target mode, using the existing
    # /etc/fstab entry for device/fstype/other options.
    try:
        subprocess.run(
            ["sudo", "umount", mount_point],
            capture_output=True, check=True, timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.error("Failed to unmount %s before remounting as %s: %s", mount_point, mode, e)
        raise RemountError(f"Could not remount {mount_point} as {mode}") from e

    try:
        subprocess.run(
            ["sudo", "mount", "-o", mode, mount_point],
            capture_output=True, check=True, timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.error("Failed to mount %s as %s: %s", mount_point, mode, e)
        # Best-effort: leaving the USB fully unmounted is worse than
        # leaving it mounted read-only, so try to at least get back to
        # the safe default before surfacing the failure.
        try:
            subprocess.run(
                ["sudo", "mount", "-o", "ro", mount_point],
                capture_output=True, timeout=10,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            pass
        raise RemountError(f"Could not remount {mount_point} as {mode}") from e
