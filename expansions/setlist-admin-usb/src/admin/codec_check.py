"""
Upload-time codec validation, reused unchanged (SPECIFICATION.md
section 3): the app runs ffprobe on any uploaded video and warns -- not
blocks -- if it's not H.264.

Warns, never blocks: the file still uploads either way (LIBRARY.md's
own guidance already covers what to do about it -- re-encode and
re-upload -- this just surfaces the same problem this project spent
real debugging time on once already, at upload time instead of
discovering it silently at showtime).

Only applies to video extensions -- audio-only files (mp3/wav) have no
video codec to check.
"""

import json
import logging
import os
import subprocess

logger = logging.getLogger(__name__)

_VIDEO_EXTENSIONS = {"mp4", "mov", "mpeg", "mpg"}
_EXPECTED_VIDEO_CODEC = "h264"

# Real incident found live (2026-10-02): list_songs() calls is_optimized()
# for every song on every GET /api/songs -- with ~24 songs, several of
# them multi-GB videos, on this hardware's weak CPU and slow USB/FUSE
# reads, that meant re-running ffprobe on every single video, every
# single time, and a real login-to-songs-loaded gap of ~37 seconds.
# Keyed by (path, mtime, size): the one thing that can't change about a
# file's codec without the file itself changing, which always bumps at
# least one of those -- a fresh upload, a replace, or Optimize finishing
# all naturally invalidate their own cache entry for free, no manual
# invalidation needed. Process-lifetime cache -- bounded in practice
# since the library itself is small and setlist-admin.service's own
# process already gets recycled whenever the tethered phone disconnects.
_codec_cache: "dict[tuple[str, float, int], str | None]" = {}


def check_video_codec(path: str, extension: str) -> "str | None":
    """Returns a human-readable warning string if the file's video
    codec isn't H.264 (or if it couldn't be determined at all -- better
    to warn than to silently say nothing), or None if it's fine / not a
    video file to begin with."""
    if extension.lower() not in _VIDEO_EXTENSIONS:
        return None

    codec = _probe_video_codec(path)
    if codec is None:
        return (
            "Could not check this file's video codec (ffprobe unavailable "
            "or the file may be invalid) -- verify manually before relying "
            "on it, see LIBRARY.md."
        )

    if codec.lower() != _EXPECTED_VIDEO_CODEC:
        return (
            f'This file is "{codec}", not H.264 -- the Pi only decodes '
            f"H.264 in hardware. It uploaded, but likely won't play until "
            f"re-encoded. See LIBRARY.md's \"Recommended encoding for "
            f"phone-sourced video\"."
        )

    return None


def is_optimized(path: str, extension: str) -> bool:
    """The boolean counterpart to check_video_codec(), used when listing
    existing library songs (not just right after an upload) to decide
    whether to offer an "Optimize" button (see library_optimizer.py).
    Audio-only files (mp3/wav) are always considered optimized -- there's
    no video codec to check, and this project doesn't second-guess an
    audio codec choice the way it does H.264 (section 3). If the codec
    can't be determined at all, treated as "not optimized" -- same
    reasoning as check_video_codec()'s warning: better to offer the fix
    than to silently assume the file is fine."""
    if extension.lower() not in _VIDEO_EXTENSIONS:
        return True
    codec = _probe_video_codec(path)
    return codec is not None and codec.lower() == _EXPECTED_VIDEO_CODEC


def _probe_video_codec(path: str) -> "str | None":
    """Returns the file's video stream codec name (e.g. "h264", "hevc"),
    or None if ffprobe failed or the result couldn't be parsed. A
    successful result is cached by (path, mtime, size) -- see
    _codec_cache's own comment. A *failed* probe (None) is deliberately
    never cached: real incident found live (2026-10-02), minutes after
    this cache first shipped -- running several ffprobes concurrently
    (list_songs()'s new ThreadPoolExecutor) while this hardware was
    already saturated by a real Optimize job's ffmpeg made three of them
    hit the 30s timeout at once, and because that failure used to be
    cached just like a success, those files (including one already
    confirmed H.264) got permanently stuck showing the "Optimize" button
    -- no refresh, no amount of retrying from the app, would ever fix it
    again, since the file's own (path, mtime, size) never changes just
    because the *system* was briefly overloaded. Only ever caching a
    genuine codec result -- never "I couldn't tell" -- means a transient
    failure simply gets retried, for real, on the very next call."""
    try:
        stat = os.stat(path)
    except OSError:
        stat = None
    cache_key = (path, stat.st_mtime, stat.st_size) if stat is not None else None
    if cache_key is not None and cache_key in _codec_cache:
        return _codec_cache[cache_key]

    codec = _probe_video_codec_uncached(path)

    if cache_key is not None and codec is not None:
        _codec_cache[cache_key] = codec
    return codec


def _probe_video_codec_uncached(path: str) -> "str | None":
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=codec_name",
                "-of", "json", path,
            ],
            capture_output=True, text=True, timeout=30, check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("Could not probe codec for %s: %s", path, e)
        return None

    try:
        data = json.loads(result.stdout)
        return data["streams"][0]["codec_name"]
    except (json.JSONDecodeError, KeyError, IndexError):
        return None
