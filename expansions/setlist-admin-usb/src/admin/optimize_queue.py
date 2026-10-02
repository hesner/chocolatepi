"""
File-based job queue for the song-library optimizer (see
library_optimizer.py for the always-on daemon that processes it, and
api.py for how the admin app requests a job and reports its status).

Deliberately file-based, not in-memory: the request (from
setlist-admin.service, when a user taps "Optimize") and the processing
(library_optimizer.service, an independent, always-on daemon -- see its
own module docstring for why) run in two different, independently
starting/stopping processes. setlist-admin.service itself gets stopped
the moment a phone disconnects (usb-tether-watchdog.service, for
resource conservation); a queued or in-progress job must survive that,
not vanish with whatever was in memory.

Pure filesystem logic, like library_ops.py -- knows nothing about
mounting or pedal-core.service. Callers (api.py, library_optimizer.py)
wrap every write in pedal_core_guard.writable_usb(), same as any other
library write in this app.
"""

import json
import os
import time

_QUEUE_DIRNAME = os.path.join(".setlist-admin", "optimize-queue")

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_ERROR = "error"

# Where the cancel marker lives -- deliberately NOT on the USB, unlike
# every other marker in this module. Real incident (2026-10-02): a
# cancel request used to live at _queue_dir(usb_root), which meant
# writing it needed a writable-USB remount like any other write here --
# but library_optimizer.py's own scratch-copy step (_process_job(),
# copying the source off the USB before encoding) holds a read handle
# open on the mount for as long as that copy takes, which can run well
# past the bounded EBUSY retry usb_mount.py's remount already has
# (tuned for a *brief* collision with pedal-core.service's mpv, not a
# multi-second-to-minutes file copy) -- confirmed live: "Cancel" failed
# with a 500 while a job's source copy was still in flight. A cancel
# marker only ever needs to reach *this Pi's own* library_optimizer.py
# process, on the same machine as whatever writes it (setlist-admin.
# service, via api.py) -- it never needs to survive this Pi rebooting,
# nor travel with the USB stick itself, so local storage needs no
# remount at all and can't collide with anything on the mount. This
# also closes a latent correctness gap for free: a cancel request that
# was in flight when the daemon died/rebooted used to survive on the
# USB and would immediately re-cancel the *next*, unrelated run of the
# same job once recover_orphaned_jobs() requeued it -- local,
# non-persistent storage can't outlive the very reboot that resets
# everything else too.
DEFAULT_STATE_DIR = os.path.expanduser("~/.pedal-optimizer-state")


def get_status(usb_root: str, filename: str) -> "dict | None":
    """Returns the job marker's content ({"status": ..., ...}) if one
    exists for this song, or None if there's no active job -- the
    normal case (not optimized yet and nothing queued, or already
    optimized)."""
    try:
        with open(_job_path(usb_root, filename), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def enqueue(usb_root: str, filename: str) -> None:
    """Called from api.py when the user taps "Optimize". Overwrites any
    existing marker -- in particular, this is also how a previously
    failed job (status "error") gets retried: tapping the button again
    just re-queues it."""
    _write(usb_root, filename, {"status": STATUS_QUEUED, "requested_at": time.time()})


def mark_running(usb_root: str, filename: str) -> None:
    _write(usb_root, filename, {"status": STATUS_RUNNING, "requested_at": time.time()})


def mark_error(usb_root: str, filename: str, message: str) -> None:
    _write(usb_root, filename, {"status": STATUS_ERROR, "message": message, "requested_at": time.time()})


def clear(usb_root: str, filename: str) -> None:
    """Called once a job finishes successfully (or is cancelled) -- the
    optimized file itself (now passing codec_check.is_optimized()) is
    the only signal needed from then on for a success; no "done" marker
    is kept lying around. Also clears any leftover cancel request, so a
    later, unrelated "Optimize" tap on the same filename doesn't start
    out pre-cancelled."""
    try:
        os.remove(_job_path(usb_root, filename))
    except OSError:
        pass
    try:
        os.remove(_cancel_path(filename))
    except OSError:
        pass


def request_cancel(filename: str) -> None:
    """Called from api.py when the user taps "Cancel" on a job that's
    queued or actively running. Real user request (2026-10-02), after a
    real incident: an optimize job can run for hours; someone watching
    it with no visible progress could reasonably think it's stuck and
    be tempted to just unplug the Pi. A separate marker file from the
    job's own status JSON, deliberately -- library_optimizer.py's main
    loop is busy blocking on ffmpeg for most of a job's life and polls
    for this specifically (see its own module docstring), independent
    of whatever write the job's own status is mid-transition through.
    Lives under DEFAULT_STATE_DIR, not the USB -- see that constant's
    comment for why."""
    os.makedirs(DEFAULT_STATE_DIR, exist_ok=True)
    with open(_cancel_path(filename), "w", encoding="utf-8"):
        pass


def is_cancel_requested(filename: str) -> bool:
    return os.path.isfile(_cancel_path(filename))


def recover_orphaned_jobs(usb_root: str) -> None:
    """Called once by library_optimizer.py at startup, before its main
    loop. Real incident (2026-10-01): a job can be marked "running" and
    then the daemon itself gets killed mid-encode (a Pi reboot, a
    service restart) -- `list_queued()` deliberately never picks
    "running" jobs back up (see its own docstring), on the assumption
    that "running" always means a *different*, currently-live tick is
    still working on it. That assumption breaks the moment this
    process itself is the one that died: a single daemon instance only
    ever processes one job at a time, synchronously, so at the moment
    this function runs (startup, before the loop has done anything),
    this process cannot possibly have a job "running" of its own --
    any marker still saying "running" here is necessarily orphaned from
    a previous, now-dead instance. Found live: a song stuck showing
    "Optimizing..." forever in the app, with no "retry" option (that
    only appears for "error"), after the Pi was rebooted mid-job.
    Resets every orphaned "running" marker back to "queued" so the next
    tick picks it up again, same as a fresh request."""
    queue_dir = _queue_dir(usb_root)
    try:
        entries = os.listdir(queue_dir)
    except OSError:
        return
    for entry in sorted(entries):
        if not entry.endswith(".json"):
            continue
        filename = entry[: -len(".json")]
        job = get_status(usb_root, filename)
        if job and job.get("status") == STATUS_RUNNING:
            enqueue(usb_root, filename)


def list_queued(usb_root: str):
    """Yields filenames with a status of "queued" -- what
    library_optimizer.py's main loop processes each tick. Skips
    anything already "running" (a previous tick, still in flight --
    jobs are processed one at a time, sequentially, deliberately: this
    hardware can barely keep up with one encode at a time, confirmed
    live: roughly 90 minutes for a single ~2.5 minute problematic video)
    or "error" (needs a fresh tap on "Optimize" in the app to retry, not
    picked up on its own -- a silently-retrying job that keeps failing
    the same way forever would just waste this hardware's limited CPU
    indefinitely)."""
    queue_dir = _queue_dir(usb_root)
    try:
        entries = os.listdir(queue_dir)
    except OSError:
        return
    for entry in sorted(entries):
        if not entry.endswith(".json"):
            continue
        filename = entry[: -len(".json")]
        job = get_status(usb_root, filename)
        if job and job.get("status") == STATUS_QUEUED:
            yield filename


def _queue_dir(usb_root: str) -> str:
    return os.path.join(usb_root, _QUEUE_DIRNAME)


def _job_path(usb_root: str, filename: str) -> str:
    return os.path.join(_queue_dir(usb_root), f"{filename}.json")


def _cancel_path(filename: str) -> str:
    return os.path.join(DEFAULT_STATE_DIR, f"{filename}.cancel")


def _write(usb_root: str, filename: str, data: dict) -> None:
    queue_dir = _queue_dir(usb_root)
    os.makedirs(queue_dir, exist_ok=True)
    path = _job_path(usb_root, filename)
    tmp_path = path + ".part"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp_path, path)
