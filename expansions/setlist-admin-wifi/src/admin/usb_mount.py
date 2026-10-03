"""
The rw/ro remount discipline from SPECIFICATION.md section 6,
as a context manager: the library USB is read-only during normal
operation (MASTER_SPECIFICATION.md section 2), so every write this app
makes briefly remounts it read-write, does exactly one logical
operation, then remounts it read-only again -- the same manual sequence
this project has used by hand (via SSH) all along, now automated.

Deliberately its own tiny module, separate from `library_ops.py`: that
module stays pure filesystem logic, testable against a plain temp
directory with no `sudo`/mount calls involved at all. Only `api.py`
(talking to the real, mounted USB) needs this -- `library_optimizer.py`
(a second, independent process) also uses `exclusive_read()` below, to
coordinate its own long reads against `api.py`'s writes without either
one needing to know the other exists.
"""

import logging
import os
import subprocess
import threading
import time
from contextlib import contextmanager

try:
    import fcntl
except ImportError:
    # Windows dev/test environment -- no real cross-process file locks
    # here. _usb_lock below still serializes *within* this one process,
    # which is all a local test run ever exercises; the real cross-
    # process coordination only matters on the Pi itself (Linux).
    fcntl = None

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

# Real incident (2026-10-02, in the sibling setlist-admin-usb expansion
# -- ported here unchanged): _usb_lock above only serializes threads
# *within one process* -- setlist-admin.service and
# library-optimizer.service are two independent OS processes with
# separate memory, so it does nothing to stop them racing each other.
# library_optimizer.py's scratch-copy step (reading a large source file
# off the USB before encoding -- see its own module docstring) can hold
# the mount busy for as long as that copy takes, well past
# _UMOUNT_RETRY_DELAY_SECONDS's budget below -- confirmed live:
# unrelated writes from setlist-admin.service (tapping "Optimize" on a
# *different* song, creating a Bank, cancelling) all 500'd with
# RemountError while a copy was still in flight. A real, cross-process
# file lock closes this for any two (or more) processes on the same
# Pi, not just threads in one of them.
_CROSS_PROCESS_LOCK_PATH = "/tmp/.chocolatepi-usb-mount.lock"
# Generous, not an expected duration -- bounds how long a caller waits
# for the *other* process to finish, rather than hanging forever if
# something's gone genuinely wrong (a stuck copy, a dead process that
# somehow never released the lock). A real scratch-copy should finish
# in well under this even for a large multi-GB file.
_CROSS_PROCESS_LOCK_TIMEOUT_SECONDS = 300
_CROSS_PROCESS_LOCK_POLL_SECONDS = 0.5

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


class MountBusyError(RemountError):
    """Raised when a bounded wait for exclusive mount access times out
    -- e.g. the other process's scratch-copy held it for longer than
    `_CROSS_PROCESS_LOCK_TIMEOUT_SECONDS`. A `RemountError` subtype, so
    any existing `except RemountError` handling elsewhere still catches
    this too."""


def _acquire_cross_process_lock(fd: int) -> None:
    deadline = time.monotonic() + _CROSS_PROCESS_LOCK_TIMEOUT_SECONDS
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise MountBusyError(
                    f"Timed out after {_CROSS_PROCESS_LOCK_TIMEOUT_SECONDS}s waiting for "
                    "exclusive USB mount access (another process -- most likely "
                    "library_optimizer.py's scratch-copy -- is still holding it)"
                )
            time.sleep(_CROSS_PROCESS_LOCK_POLL_SECONDS)


@contextmanager
def _cross_process_lock():
    if fcntl is None:
        yield
        return
    fd = os.open(_CROSS_PROCESS_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o666)
    try:
        _acquire_cross_process_lock(fd)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@contextmanager
def _exclusive():
    """Combines the in-process lock with the cross-process one -- every
    caller below goes through this one gate, in either process, instead
    of racing a umount against another process's open file handle."""
    with _usb_lock, _cross_process_lock():
        yield


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

    Held under a process-wide *and* cross-process lock (`_exclusive()`):
    two of these overlapping, in the same process or a different one,
    is exactly what let concurrent callers race each other's raw
    umount/mount calls, or race a long read like
    library_optimizer.py's scratch-copy (see module docstring/comments
    above) -- every caller now simply waits its turn instead of
    colliding."""
    with _exclusive():
        _remount(mount_point, "rw")
        try:
            yield
        finally:
            _remount(mount_point, "ro")


def remount_ro(mount_point: str = DEFAULT_MOUNT_POINT) -> None:
    """Forces `mount_point` back to `ro` right now, outside any
    `writable_usb()` window of its own. Used by `pedal_core_guard.py` to
    retry a cleanup remount that failed because something grabbed the
    mount again before the window closed (see its own module docstring
    for the real incident this exists for) -- the write itself already
    happened by the time this runs; this is purely about getting back to
    the safe read-only default."""
    with _exclusive():
        _remount(mount_point, "ro")


@contextmanager
def exclusive_read():
    """For a caller that only ever needs to READ from the USB (never
    `rw`) but whose read can run long enough to otherwise race a
    concurrent `writable_usb()`/`remount_ro()` cycle -- in this process
    or a different one -- and lose. Confirmed live (2026-10-02, in the
    sibling setlist-admin-usb expansion -- ported here unchanged):
    library_optimizer.py's scratch-copy step (reading a large source
    file off the USB before encoding) held the mount busy long enough
    that an unrelated write from the *other* process (setlist-admin.
    service) 500'd with `RemountError` while the copy was still in
    flight. Holding this for the read's duration makes every
    `writable_usb()`/`remount_ro()` call, anywhere, simply wait its
    turn instead of attempting (and losing) a `umount` against an open
    file descriptor. Not mount-point-specific -- there's only ever one
    real USB mount in this whole system -- so it takes no argument."""
    with _exclusive():
        yield


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
