"""
The rw/ro remount discipline from SETLIST_ADMIN_SPECIFICATION.md section 6,
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
import os
import subprocess
import threading
import time
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DEFAULT_MOUNT_POINT = "/media/usb"

# Every writable_usb() caller shares this one mount point, but nothing
# serialized access to it -- two overlapping requests (a real double-tap
# on a button, or two independent actions moments apart) each ran their
# own unmount/mount cycle against the same device with no coordination,
# racing each other. Found live on real hardware: a double-tap on
# "save to library" logged "Failed to mount /media/usb as ro: ...exit
# status 16" -- one request's own closing remount colliding with the
# other's opening one. This lock makes every writable_usb() window fully
# serial, process-wide.
_usb_lock = threading.Lock()

# pedal-core.service continuously loops standby.mp4 straight off this same
# USB via mpv, so an umount attempted at exactly the wrong instant can hit a
# transient EBUSY from mpv's own in-flight read -- found live on real
# hardware (two admin-app writes failed with "returned non-zero exit status
# 32" seconds after a footswitch test, then succeeded immediately on retry).
# This bounded retry clears that almost instantly; it does not mask a real
# problem -- if the mount point stays busy past this budget, the plain
# failure below still fires.
_UMOUNT_MAX_ATTEMPTS = 5
_UMOUNT_RETRY_DELAY_SECONDS = 0.3


class RemountError(Exception):
    """Raised if remounting rw or ro fails. Callers should treat this as
    fatal for the operation being attempted -- proceeding to write
    without confirming rw succeeded risks the same silent failure this
    whole app exists to eliminate."""


def ensure_mounted(mount_point: str = DEFAULT_MOUNT_POINT) -> None:
    """Real anomaly seen on hardware: the library USB has turned up
    spontaneously unmounted -- the ntfs-3g FUSE daemon simply gone, no
    corresponding log evidence anywhere, unrelated to any write this app
    was doing at the time -- root cause never identified despite repeated
    investigation (see CHANGELOG). Read-only callers (e.g. checking
    whether a PIN is already set) never go through `writable_usb()`'s
    remount logic at all, so without this they'd just silently see an
    empty directory and draw the wrong conclusion -- "no pin.hash found,
    must be first run" -- even though a PIN really is set, just
    unreachable right now. Call this before drawing any conclusion from
    what's on disk under `mount_point`; it attempts one self-heal mount
    and raises `RemountError` if that doesn't fix it, rather than letting
    a caller silently misread an empty directory as "nothing here yet."
    """
    if os.path.ismount(mount_point):
        return
    try:
        subprocess.run(["sudo", "mount", mount_point], capture_output=True, timeout=10)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    if not os.path.ismount(mount_point):
        raise RemountError(f"{mount_point} is not mounted and a recovery mount attempt failed")


@contextmanager
def writable_usb(mount_point: str = DEFAULT_MOUNT_POINT):
    """Remounts `mount_point` read-write for the duration of the `with`
    block, then always remounts it read-only again on the way out --
    including if the block raises. The window this stays writable is
    exactly one caller-defined operation, never longer.

    Held under a process-wide lock: two of these overlapping is exactly
    what let two concurrent requests race each other's raw umount/mount
    calls (see module docstring/comment above) -- a second caller now
    simply waits its turn instead of colliding."""
    with _usb_lock:
        _remount(mount_point, "rw")
        try:
            yield
        finally:
            _remount(mount_point, "ro")


def _remount(mount_point: str, mode: str) -> None:
    # Real incident found live (2026-10-01, in the sibling setlist-admin-usb
    # expansion -- ported here unchanged): remounting straight back to ro
    # right after a large write (a multi-hundred-MB video) timed out at
    # 10s more than once, even though the write itself had already
    # completed and returned successfully -- the FUSE layer appears to
    # still be flushing buffered data to the physical device at that
    # point, and that can outlast the write call itself. A sync first
    # (best-effort -- failing to sync here isn't itself fatal, the real,
    # checked operation is still the umount/mount pair below) forces that
    # flush to happen up front, instead of leaving it to block inside the
    # time-limited umount/mount calls that follow.
    try:
        subprocess.run(["sync", "-f", mount_point], capture_output=True, timeout=15)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # ntfs-3g (a FUSE filesystem, unlike vfat/ext4's in-kernel drivers) does
    # not support `mount -o remount,X` at all -- it refuses outright with
    # "Remounting is not supported at present. You have to umount volume
    # and then mount it once again.", confirmed against the real library
    # USB. So this does exactly what that message says: a real umount
    # followed by a fresh mount in the target mode, using the existing
    # /etc/fstab entry for device/fstype/other options.
    last_error = None
    for attempt in range(_UMOUNT_MAX_ATTEMPTS):
        if attempt:
            time.sleep(_UMOUNT_RETRY_DELAY_SECONDS)
        try:
            result = subprocess.run(
                ["sudo", "umount", mount_point],
                capture_output=True, timeout=10, text=True,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            last_error = e
            continue
        if result.returncode == 0:
            last_error = None
            break
        if "not mounted" in (result.stderr or "").lower():
            # Real anomaly seen on hardware: the library USB has been
            # found spontaneously unmounted with zero corresponding log
            # evidence anywhere (not this app's doing -- no prior write
            # was in flight), root cause never identified despite repeated
            # investigation -- see CHANGELOG. Retrying the exact same
            # umount could never help here, but the precondition it exists
            # to guarantee ("not currently mounted") is already true, so
            # there is nothing to retry -- fall straight through to
            # (re)mounting it in the requested mode below instead of
            # failing an operation that has nothing left to undo.
            last_error = None
            break
        last_error = subprocess.CalledProcessError(
            result.returncode, ["sudo", "umount", mount_point], result.stdout, result.stderr,
        )
    if last_error is not None:
        logger.error("Failed to unmount %s before remounting as %s: %s", mount_point, mode, last_error)
        raise RemountError(f"Could not remount {mount_point} as {mode}") from last_error

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
