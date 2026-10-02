"""
library-optimizer: an always-on background daemon that processes
"please optimize this file" requests queued by the admin app's
"Optimize" button (see optimize_queue.py for the job-marker format and
api.py for how a request gets queued).

Runs as its own systemd service, deliberately never tied to
setlist-admin.service's own lifecycle: that service gets stopped the
instant a tethered phone disconnects (usb-tether-watchdog.service, for
resource conservation), but a re-encode job can take a very long time
on this hardware -- confirmed live, 2026-10-01: roughly 90 minutes for
a single ~2.5-minute problematic video (this Pi has no working hardware
HEVC decode, despite ffmpeg listing a `hevc_v4l2m2m` wrapper for it --
confirmed live, it fails with "Could not find a valid device"; software
decode of a high-bitrate/high-framerate source is what actually takes
so long). A job must survive the phone disconnecting partway through,
not get killed along with the app that queued it.

Real user request (2026-10-01): every library song gets an "Optimize"
button in the app whenever codec_check.is_optimized() says it isn't
(today, only video files, only the H.264-vs-anything-else check --
audio files are always considered fine, see codec_check.py). Tapping it
queues a job here; this daemon picks it up independent of whether the
phone that tapped it is still connected.

Design, so the long part of the job never needs pedal-core.service
stopped or the USB held read-write for anywhere near its full duration
(unlike how this exact fix was first done by hand over SSH, which held
the Pi's own pedal offline for the full ~90 minutes -- unacceptable for
a live-show appliance): the source file is read directly off the
normally-read-only mount (reading never needs rw access at all), the
actual encode writes to local scratch space on the Pi itself, and only
the already-finished (and typically much smaller -- a 396MB source
became a 38MB output in the real incident this was built for) output
file is copied onto the USB at the end -- a brief pedal_core_guard.
writable_usb() window, the same few-seconds pattern every other write
in this app already uses, not the whole encode.

Real incident found live (2026-10-02, in the sibling setlist-admin-usb
expansion -- ported here unchanged): the source file was originally
read *in place* off the USB -- `ffmpeg -i /media/usb/_Songs/<file>`,
no local copy first -- which meant ffmpeg kept that file open for its
*entire* encode, confirmed live at 45+ minutes for one 4K source.
`umount` refuses outright while anything holds a file open on that
mount, for any reason, reading included -- so every other library
write (even an unrelated "create Bank") failed with a 500 the whole
time, since `pedal_core_guard`'s fallback only knows how to stop
`pedal-core.service`, not this daemon. Fixed: the source is now copied
to local scratch *first* (a brief, bounded read, same as any other file
copy) and `ffmpeg` runs entirely against that local copy -- the USB
mount is never held open for anywhere near the encode's own duration,
closing the same class of problem the output side was already designed
to avoid.

Cancellation (real user request, 2026-10-02, after a real incident: a
job running for hours with no visible progress is a real temptation to
just unplug the Pi): `_encode()` no longer blocks on a single
`subprocess.run()` -- it launches `ffmpeg` with `Popen` and polls it in
short intervals instead, checking `optimize_queue.is_cancel_requested()`
on each one. A cancel request can arrive at any point in a job's life
(still queued, or mid-encode) -- see `_process_job()` for both cases.
"""

import argparse
import logging
import os
import shutil
import subprocess
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from admin import library_ops, optimize_queue, pedal_core_guard  # noqa: E402

logger = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL_SECONDS = 5
_DEFAULT_SCRATCH_DIR = os.path.expanduser("~/pedal-optimizer-scratch")
# Generous, not an expected duration -- a safety bound against a
# genuinely stuck/hung ffmpeg process running forever, not a target.
# The real incident this was built for took roughly 90 minutes; this
# leaves over double that before giving up.
_FFMPEG_TIMEOUT_SECONDS = 4 * 60 * 60
# How often _encode() checks in on the running ffmpeg process -- both
# for a cancel request and for the overall timeout above. Frequent
# enough that tapping "Cancel" feels responsive, not so frequent that
# polling itself costs anything meaningful next to an encode that runs
# for hours.
_CANCEL_CHECK_INTERVAL_SECONDS = 2


class OptimizationCancelled(Exception):
    """Raised by _encode() when optimize_queue.is_cancel_requested()
    turns up true mid-encode, after the ffmpeg process has already been
    terminated -- distinct from a real failure (CalledProcessError) or
    a runaway job (TimeoutExpired): this is the user's own choice, so
    _process_job() clears the job outright rather than recording it as
    an error needing a retry tap."""


def run_forever(usb_root: str, mount_point: str, scratch_dir: str, poll_interval: int) -> None:
    logger.info("library-optimizer starting (usb_root=%s)", usb_root)
    os.makedirs(scratch_dir, exist_ok=True)
    try:
        with pedal_core_guard.writable_usb(mount_point):
            optimize_queue.recover_orphaned_jobs(usb_root)
    except Exception:
        # Best-effort: a failure here must not stop the daemon from
        # starting at all -- worst case, an orphaned job stays stuck
        # exactly as it already was, no worse off than before this
        # existed.
        logger.exception("Could not recover orphaned jobs at startup, continuing")
    while True:
        try:
            _tick(usb_root, mount_point, scratch_dir)
        except Exception:
            # A single bad tick must never kill the daemon -- there is
            # no one to restart it by hand on a headless appliance, same
            # reasoning as pedal-core.service's own Restart=always.
            logger.exception("Unhandled error in optimizer tick, continuing")
        time.sleep(poll_interval)


def _tick(usb_root: str, mount_point: str, scratch_dir: str) -> None:
    # One job per tick, deliberately: this hardware can barely keep up
    # with a single encode at a time (see module docstring) -- running
    # several in parallel would only make each of them slower, not
    # finish the batch any sooner, while starving pedal-core.service's
    # own CPU budget far more than one job alone already does.
    for filename in optimize_queue.list_queued(usb_root):
        _process_job(usb_root, mount_point, scratch_dir, filename)
        break


def _process_job(usb_root: str, mount_point: str, scratch_dir: str, filename: str) -> None:
    # A cancel tapped while the job was still merely "queued" (never
    # even started) -- nothing to tear down, just honor it immediately
    # without ever touching ffmpeg.
    if optimize_queue.is_cancel_requested(usb_root, filename):
        logger.info("Optimization of %s was cancelled before it started", filename)
        with pedal_core_guard.writable_usb(mount_point):
            optimize_queue.clear(usb_root, filename)
        return

    logger.info("Optimizing %s", filename)
    with pedal_core_guard.writable_usb(mount_point):
        optimize_queue.mark_running(usb_root, filename)

    source_path = os.path.join(usb_root, "_Songs", filename)
    if not os.path.isfile(source_path):
        _fail(usb_root, mount_point, filename, "Song no longer in the library")
        return

    # Real incident (2026-10-02): copy to local scratch *before*
    # encoding, rather than pointing ffmpeg straight at the USB-mounted
    # source -- see the module docstring. This copy is the only moment
    # the USB is touched for the source at all, and it needs no
    # pedal_core_guard window of its own: reading from the normally-ro
    # mount never needs rw access.
    _, source_ext = os.path.splitext(filename)
    scratch_input = os.path.join(scratch_dir, f"{uuid.uuid4().hex}{source_ext}")
    scratch_output = os.path.join(scratch_dir, f"{uuid.uuid4().hex}.mp4")
    try:
        try:
            shutil.copyfile(source_path, scratch_input)
        except OSError as e:
            logger.error("Could not copy %s to local scratch: %s", filename, e)
            _fail(usb_root, mount_point, filename, "Could not read the source file")
            return

        try:
            _encode(scratch_input, scratch_output, usb_root, filename)
        except OptimizationCancelled:
            logger.info("Optimization of %s was cancelled", filename)
            with pedal_core_guard.writable_usb(mount_point):
                optimize_queue.clear(usb_root, filename)
            return
        except subprocess.TimeoutExpired:
            _fail(usb_root, mount_point, filename, "Encoding took too long and was stopped")
            return
        except subprocess.CalledProcessError as e:
            stderr_tail = (e.stderr or "")[-500:]
            logger.error("ffmpeg failed optimizing %s: %s", filename, stderr_tail)
            _fail(usb_root, mount_point, filename, "Encoding failed -- the file may be corrupt or unreadable")
            return

        try:
            with pedal_core_guard.writable_usb(mount_point):
                library_ops._atomic_copy_file(scratch_output, source_path)
                optimize_queue.clear(usb_root, filename)
            logger.info("Optimized %s", filename)
        finally:
            if os.path.exists(scratch_output):
                os.remove(scratch_output)
    finally:
        if os.path.exists(scratch_input):
            os.remove(scratch_input)


def _fail(usb_root: str, mount_point: str, filename: str, message: str) -> None:
    with pedal_core_guard.writable_usb(mount_point):
        optimize_queue.mark_error(usb_root, filename, message)


def _encode(source_path: str, output_path: str, usb_root: str, filename: str) -> None:
    """Re-encodes to this project's recommended format (LIBRARY.md):
    H.264, 1080p max, ~8-12 Mbps for a regular clip -- but this targets
    the leaner ~1.8 Mbps LIBRARY.md specifically calls out for the
    standby video (the one real case this was built against), which is
    still comfortably good quality for anything shown on a TV, and
    keeps every optimized file's size down regardless of whether it
    ends up assigned as standby or not. 25fps -- more than enough for
    looped/background video content, and a real source seen in
    practice was a needless 120fps that did nothing but multiply
    decode cost for no visible benefit on a TV.

    Runs ffmpeg via Popen and polls it, rather than a single blocking
    subprocess.run(), specifically so a "Cancel" tap can actually stop
    the real ffmpeg process -- not just the bookkeeping around it --
    within a couple of seconds, instead of waiting out however long is
    left (confirmed live: hours, for a large 4K source)."""
    cmd = [
        "ffmpeg", "-y", "-i", source_path,
        "-vf", "scale=-2:1080,fps=25",
        "-c:v", "libx264", "-profile:v", "high", "-level", "4.0",
        "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-b:v", "1800k", "-maxrate", "1800k", "-bufsize", "3600k",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", "-f", "mp4",
        output_path,
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    elapsed = 0.0
    while True:
        try:
            proc.wait(timeout=_CANCEL_CHECK_INTERVAL_SECONDS)
            break
        except subprocess.TimeoutExpired:
            elapsed += _CANCEL_CHECK_INTERVAL_SECONDS
            if optimize_queue.is_cancel_requested(usb_root, filename):
                _terminate(proc)
                raise OptimizationCancelled()
            if elapsed > _FFMPEG_TIMEOUT_SECONDS:
                _terminate(proc)
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=_FFMPEG_TIMEOUT_SECONDS)

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, cmd, output=proc.stdout.read(), stderr=proc.stderr.read(),
        )


def _terminate(proc: subprocess.Popen) -> None:
    """SIGTERM first -- ffmpeg handles it cleanly and exits quickly;
    SIGKILL only if it somehow doesn't, so this can't itself hang."""
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usb-root", required=True)
    parser.add_argument("--mount-point", default="/media/usb")
    parser.add_argument("--scratch-dir", default=_DEFAULT_SCRATCH_DIR)
    parser.add_argument("--poll-interval", type=int, default=_DEFAULT_POLL_INTERVAL_SECONDS)
    parser.add_argument("--log-file", default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        filename=args.log_file,
    )
    run_forever(args.usb_root, args.mount_point, args.scratch_dir, args.poll_interval)


if __name__ == "__main__":
    main()
