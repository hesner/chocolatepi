"""
Upload-time codec validation (SETLIST_ADMIN_SPECIFICATION.md section 9:
"the app runs ffprobe on any uploaded video and warns -- not blocks --
if it's not H.264").

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
import subprocess

logger = logging.getLogger(__name__)

_VIDEO_EXTENSIONS = {"mp4", "mov", "mpeg", "mpg"}
_EXPECTED_VIDEO_CODEC = "h264"


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
    audio codec choice the way it does H.264 (section 9). If the codec
    can't be determined at all, treated as "not optimized" -- same
    reasoning as check_video_codec()'s warning: better to offer the fix
    than to silently assume the file is fine."""
    if extension.lower() not in _VIDEO_EXTENSIONS:
        return True
    codec = _probe_video_codec(path)
    return codec is not None and codec.lower() == _EXPECTED_VIDEO_CODEC


def _probe_video_codec(path: str) -> "str | None":
    """Returns the file's video stream codec name (e.g. "h264", "hevc"),
    or None if ffprobe failed or the result couldn't be parsed."""
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
