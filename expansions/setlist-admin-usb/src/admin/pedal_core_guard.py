"""
Writable-USB access, with a fallback for when pedal-core.service's `mpv`
won't let go -- extracted out of `api.py` (2026-10-01) once a second
caller (`library_optimizer.py`, an independent always-on daemon) needed
the exact same logic. Deliberately its own module, not folded into
`usb_mount.py`: that module stays mount-only, with no idea
`pedal-core.service` exists, testable against a plain temp directory
with no `sudo`/`systemctl` involved at all.

Real incident found on real hardware (2026-10-01): `pedal-core.service`'s
`mpv` keeps whatever it's currently looping (in practice, always
`standby.mp4`) open for as long as it runs -- confirmed to never let go
on its own, not even briefly, for as long as the service keeps running
without being restarted. `usb_mount._remount()`'s own bounded retry
(built for a genuinely brief, transient busy window) can't get past
that: it isn't brief here, so every write failed with a 500 the whole
time the service ran continuously and stayed stable.

Second real incident, same day, live-testing the "Optimize" feature: a
large (multi-GB) upload is slow enough to span one of `mpv`'s own loop
boundaries (it re-opens `standby.mp4` every time it loops), so the probe
below can find the mount free at the start, the write itself can fully
succeed, and *then* the cleanup remount back to `ro` can still fail
because `mpv` grabbed the mount again mid-upload. Confirmed live: the
uploaded file was intact and already on disk, but the phone saw a scary
"internal error" for an upload that had, in fact, already worked.
`writable_usb()` now catches exactly that case (the write succeeded; it
was the ro remount that failed) and recovers instead of raising.
"""

import contextlib
import logging
import subprocess

from admin import usb_mount

logger = logging.getLogger(__name__)

PEDAL_CORE_SERVICE_NAME = "pedal-core.service"


@contextlib.contextmanager
def writable_usb(mount_point: str):
    """Every mutating caller uses this instead of calling
    `usb_mount.writable_usb()` directly.

    Tries the normal fast path first with a cheap, side-effect-free
    probe (an immediate rw-then-ro round trip, nothing written) -- if
    the mount is free, behavior is unchanged, no disruption. Only if
    that probe itself fails does this stop `pedal-core.service`
    (releasing every file it has open, including the looping standby
    video -- briefly interrupting playback, screen goes black for a few
    seconds) before the real write, then restarts it afterward. The
    probe runs as a fully separate, no-op remount cycle specifically so
    the real write never has to be attempted twice -- retrying the
    actual operation after a partial failure would risk doing it twice
    over (e.g. a duplicate write, or in the worst case the "ro" remount
    itself being what failed, which would mean the write had already
    happened)."""
    stopped = False
    if not _can_remount_rw_quickly(mount_point):
        stopped = _stop_pedal_core()
    write_succeeded = False
    try:
        with usb_mount.writable_usb(mount_point):
            yield
            write_succeeded = True
    except usb_mount.RemountError:
        if not write_succeeded:
            raise
        # Real incident found live (2026-10-01), deploying the "Optimize"
        # feature: the probe above only checks whether the mount is free
        # *right now* -- it says nothing about a slow operation that
        # follows. pedal-core.service's mpv re-opens standby.mp4 every
        # time it loops (every couple of minutes in practice), so a big
        # upload slow enough to span a loop boundary can find the mount
        # busy again right when it's time to remount back to ro, even
        # though the probe found it free moments earlier and the write
        # itself (the `yield` above) already finished successfully.
        # Surfacing that as a fatal error to the caller would be actively
        # misleading -- confirmed live: the uploaded file was intact and
        # already on disk, but the phone saw a scary "internal error" for
        # an upload that had, in fact, already worked. Stop
        # pedal-core.service now (releasing the handle, same fallback as
        # above) and force the ro remount directly instead of failing an
        # operation that actually succeeded.
        logger.warning(
            "%s's write succeeded but the cleanup remount to ro failed "
            "(pedal-core.service's mpv likely re-opened its file "
            "mid-write) -- stopping it and retrying.", mount_point,
        )
        if not stopped:
            stopped = _stop_pedal_core()
        usb_mount.remount_ro(mount_point)
    finally:
        if stopped:
            # Real incident (2026-10-01): the write's own remount-back-
            # to-ro can itself fail (observed: a "mount -o ro" timing
            # out after 10s, following a client disconnect mid-upload)
            # and leave the FUSE mount genuinely dead -- `mount` still
            # lists it, but every access returns ENOTCONN ("Transport
            # endpoint is not connected"), because the ntfs-3g process
            # backing it is simply gone. Restarting pedal-core.service
            # blindly at that point made it worse: mpv immediately
            # tried to open standby.mp4 against the broken mount. Check
            # first, and self-heal (the same umount -l + fresh mount a
            # human would do over SSH) before handing control back to
            # pedal-core.service.
            _ensure_usb_accessible_before_restart(mount_point)
            _start_pedal_core()


def _can_remount_rw_quickly(mount_point: str) -> bool:
    """A cheap, side-effect-free probe: can `mount_point` be remounted
    rw right now without anything holding it busy? Immediately remounts
    back to `ro` either way -- nothing is written in between. Used only
    to decide whether `writable_usb()` needs to stop
    `pedal-core.service` first."""
    try:
        with usb_mount.writable_usb(mount_point):
            pass
        return True
    except usb_mount.RemountError:
        return False


def _stop_pedal_core() -> bool:
    """Returns True only if the service was actually running (and is
    now stopped by this call) -- False if it was already stopped, or if
    stopping it failed, so `writable_usb()`'s `finally` never
    "helpfully" starts a service back up that this call didn't actually
    stop itself."""
    try:
        was_active = subprocess.run(
            ["systemctl", "is-active", PEDAL_CORE_SERVICE_NAME],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip() == "active"
        if not was_active:
            return False
        subprocess.run(
            ["sudo", "systemctl", "stop", PEDAL_CORE_SERVICE_NAME],
            capture_output=True, timeout=15,
        )
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _start_pedal_core() -> None:
    try:
        subprocess.run(
            ["sudo", "systemctl", "start", PEDAL_CORE_SERVICE_NAME],
            capture_output=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.error(
            "Could not restart %s after a library write -- it may need "
            "a manual 'sudo systemctl start %s' over SSH: %s",
            PEDAL_CORE_SERVICE_NAME, PEDAL_CORE_SERVICE_NAME, e,
        )


def _ensure_usb_accessible_before_restart(mount_point: str) -> None:
    """Called only when this call itself stopped pedal-core.service
    (about to start it back up, which makes mpv immediately try to open
    standby.mp4 again). A no-op if the mount is fine -- the common case.
    If it's dead, runs the same recovery a human would do over SSH
    (force-unmount, fresh mount) first, so pedal-core.service comes back
    up against a working mount instead of a broken one."""
    if _usb_mount_is_healthy(mount_point):
        return
    logger.error(
        "%s looks broken after a library write (a dead FUSE mount, not "
        "just empty) -- attempting automatic recovery before restarting "
        "%s.", mount_point, PEDAL_CORE_SERVICE_NAME,
    )
    _recover_broken_mount(mount_point)


def _usb_mount_is_healthy(mount_point: str) -> bool:
    """A real filesystem access, not just checking `mount`'s own output
    -- a dead FUSE mount still shows up there as mounted even though
    every access to it fails with ENOTCONN ("Transport endpoint is not
    connected"). Run through `subprocess` (not `os.listdir()` directly)
    specifically so a backing process that's hung rather than fully dead
    can't block this indefinitely -- bounded by `timeout` either way."""
    try:
        result = subprocess.run(
            ["ls", mount_point],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def _recover_broken_mount(mount_point: str) -> None:
    try:
        subprocess.run(
            ["sudo", "umount", "-l", mount_point],
            capture_output=True, timeout=10,
        )
        subprocess.run(
            ["sudo", "mount", "-o", "ro", mount_point],
            capture_output=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.error("Automatic USB mount recovery failed: %s", e)
        return
    if _usb_mount_is_healthy(mount_point):
        logger.info("%s recovered automatically.", mount_point)
    else:
        logger.error(
            "%s is still not accessible after automatic recovery -- "
            "needs manual attention over SSH (umount -l, then mount -o ro).",
            mount_point,
        )
