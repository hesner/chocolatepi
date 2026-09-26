"""
Read/write operations over the library USB's show/Set/track structure,
for the setlist-admin web app, reused unchanged from the earlier WiFi
design (SETLIST_ADMIN_USB_SPECIFICATION.md section 3).

Deliberately hardware-agnostic, like `core.library.Library` itself: this
module knows nothing about mounting, remounting, or the USB being
read-only day to day (section 6 of the specification) -- that's
`usb_mount.py`'s job, invoked by `api.py` around each call here. This
split is what makes every function below testable against a plain
`tempfile.TemporaryDirectory()`, the same way `tests/test_library.py`
already tests `core.library.Library`.

The single most important property of this module: **it is structurally
impossible to produce a filename that violates LIBRARY.md's naming
rule** through any function here. Every write builds
"<Letter> - <name>.<ext>" from validated, separately-typed components
(letter, display name, extension) -- there is no code path that accepts
a raw, hand-typed filename from the API and writes it as-is. This is
what closes off the whole "double space before the dash" class of
silent failure (see LIBRARY.md) at the source, rather than just
documenting it.
"""

import logging
import os
import re
import shutil
from dataclasses import dataclass
from typing import BinaryIO, Dict, List, Optional

# Reusing core.library's own extension sets rather than redefining them
# -- if a supported format is ever added there, this module picks it up
# automatically instead of silently drifting out of sync. Assumes `src/`
# is already on sys.path, the same convention main.py sets up for every
# other cross-package import in this project.
from core.library import _AUDIO_ONLY_EXTENSIONS, _VIDEO_EXTENSIONS, _TRACK_LETTERS

logger = logging.getLogger(__name__)

_ALL_EXTENSIONS = _AUDIO_ONLY_EXTENSIONS | _VIDEO_EXTENSIONS
_VALID_LETTERS = set(_TRACK_LETTERS.values())  # {"A", "B", "C"} -- D is always STOP, never a file
_SET_FOLDER_RE = re.compile(r"^Set (\d+)$")
_UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MiB -- streamed, never the whole file in RAM (section 7)

# What a "display name" may contain -- deliberately conservative (no " - ",
# no path separators, no leading/trailing dots or spaces) so it can never
# combine with the "<Letter> - " prefix to accidentally produce something
# LIBRARY.md's own strict filename pattern would reject.
_INVALID_NAME_CHARS = re.compile(r'[/\\:*?"<>|]')


class LibraryOpsError(ValueError):
    """Raised for any invalid input (bad letter, bad extension, name
    that would break the naming convention, Set/show that doesn't
    exist). api.py catches this and turns it into a 400 response with
    the message shown to the user -- these are always meant to be
    readable as-is, not internal details to hide."""


@dataclass(frozen=True)
class TrackInfo:
    letter: str
    display_name: str
    extension: str
    is_audio_only: bool

    @property
    def filename(self) -> str:
        return f"{self.letter} - {self.display_name}.{self.extension}"


# ---------------------------------------------------------------------------
# Shows
# ---------------------------------------------------------------------------

def list_shows(usb_root: str) -> List[str]:
    """Every top-level folder under the USB root, except this app's own
    dotfile directory -- i.e. every folder LIBRARY.md's Show convention
    would recognize."""
    try:
        entries = os.listdir(usb_root)
    except OSError:
        return []
    return sorted(
        e for e in entries
        if not e.startswith(".") and os.path.isdir(os.path.join(usb_root, e))
    )


def get_active_show(usb_root: str) -> Optional[str]:
    pointer_path = os.path.join(usb_root, "active_show.txt")
    try:
        with open(pointer_path, "r", encoding="utf-8") as f:
            name = f.read().strip()
    except OSError:
        return None
    return name or None


def set_active_show(usb_root: str, show_name: str) -> None:
    show_path = os.path.join(usb_root, show_name)
    if not os.path.isdir(show_path):
        raise LibraryOpsError(f'Show "{show_name}" does not exist')

    pointer_path = os.path.join(usb_root, "active_show.txt")
    with open(pointer_path, "w", encoding="utf-8") as f:
        f.write(show_name)


def create_show(usb_root: str, show_name: str) -> None:
    _validate_display_name(show_name, what="show name")
    show_path = os.path.join(usb_root, show_name)
    if os.path.isdir(show_path):
        raise LibraryOpsError(f'Show "{show_name}" already exists')
    os.makedirs(show_path)


# ---------------------------------------------------------------------------
# Sets
# ---------------------------------------------------------------------------

def list_sets(usb_root: str, show_name: str) -> List[int]:
    show_path = _require_show(usb_root, show_name)
    try:
        entries = os.listdir(show_path)
    except OSError:
        return []
    numbers = []
    for entry in entries:
        match = _SET_FOLDER_RE.match(entry)
        if match and os.path.isdir(os.path.join(show_path, entry)):
            numbers.append(int(match.group(1)))
    return sorted(numbers)


def create_set(usb_root: str, show_name: str, set_number: int) -> None:
    show_path = _require_show(usb_root, show_name)
    _validate_set_number(set_number)
    set_path = os.path.join(show_path, f"Set {set_number}")
    if os.path.isdir(set_path):
        raise LibraryOpsError(f"Set {set_number} already exists")
    os.makedirs(set_path)


def rename_set(usb_root: str, show_name: str, old_number: int, new_number: int) -> None:
    show_path = _require_show(usb_root, show_name)
    _validate_set_number(new_number)
    old_path = _require_set(show_path, old_number)
    new_path = os.path.join(show_path, f"Set {new_number}")
    if os.path.exists(new_path):
        raise LibraryOpsError(f"Set {new_number} already exists")
    os.rename(old_path, new_path)


def delete_set(usb_root: str, show_name: str, set_number: int) -> None:
    show_path = _require_show(usb_root, show_name)
    set_path = _require_set(show_path, set_number)
    shutil.rmtree(set_path)


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------

def list_tracks(usb_root: str, show_name: str, set_number: int) -> Dict[str, Optional[TrackInfo]]:
    """Returns all 3 letters, mapping to a TrackInfo if that slot is
    filled or None if it's an empty slot -- the caller always gets a
    complete A/B/C picture, matching how Library.resolve() treats a
    missing letter as normal, not an error."""
    show_path = _require_show(usb_root, show_name)
    set_path = _require_set(show_path, set_number)

    result: Dict[str, Optional[TrackInfo]] = {letter: None for letter in sorted(_VALID_LETTERS)}
    try:
        entries = sorted(os.listdir(set_path))
    except OSError:
        return result

    for entry in entries:
        info = _parse_track_filename(entry)
        if info is not None and result.get(info.letter) is None:
            # First match wins if duplicates exist -- same rule as
            # core.library.Library, for the same reason (a naming
            # mistake should never make a slot look broken, just make
            # which duplicate is "the" one for editing purposes
            # unspecified until the duplicate is cleaned up).
            result[info.letter] = info
    return result


def assign_track(
    usb_root: str,
    show_name: str,
    set_number: int,
    letter: str,
    display_name: str,
    extension: str,
    source: BinaryIO,
) -> TrackInfo:
    """Streams `source` to "<Letter> - <display_name>.<extension>" in
    the given Set, replacing whatever was there for that letter, if
    anything. Streamed in chunks (never the whole file read into
    memory at once) -- required given this runs on a 1GB-RAM Pi 2,
    matching section 7."""
    show_path = _require_show(usb_root, show_name)
    set_path = _require_set(show_path, set_number)
    letter = _validate_letter(letter)
    extension = _validate_extension(extension)
    _validate_display_name(display_name, what="track name")

    _remove_existing_track(set_path, letter)

    info = TrackInfo(
        letter=letter, display_name=display_name, extension=extension,
        is_audio_only=extension in _AUDIO_ONLY_EXTENSIONS,
    )
    dest_path = os.path.join(set_path, info.filename)

    # Write to a temp name first, rename into place at the end -- so a
    # failed/interrupted upload (dropped WiFi mid-transfer, the classic
    # risk this app is designed around) never leaves a half-written file
    # sitting under the real "<Letter> - ..." name where
    # Library.resolve() could find and try to play it.
    tmp_path = dest_path + ".part"
    try:
        with open(tmp_path, "wb") as dest:
            while True:
                chunk = source.read(_UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                dest.write(chunk)
        os.replace(tmp_path, dest_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    return info


def rename_track(usb_root: str, show_name: str, set_number: int, letter: str, new_display_name: str) -> TrackInfo:
    """Renames the display-name part only -- the letter (its "position")
    and extension stay the same. To move a track to a different letter,
    see swap_tracks()."""
    show_path = _require_show(usb_root, show_name)
    set_path = _require_set(show_path, set_number)
    letter = _validate_letter(letter)
    _validate_display_name(new_display_name, what="track name")

    tracks = list_tracks(usb_root, show_name, set_number)
    current = tracks.get(letter)
    if current is None:
        raise LibraryOpsError(f"Track {letter} is empty, nothing to rename")

    old_path = os.path.join(set_path, current.filename)
    new_info = TrackInfo(
        letter=letter, display_name=new_display_name,
        extension=current.extension, is_audio_only=current.is_audio_only,
    )
    new_path = os.path.join(set_path, new_info.filename)
    os.rename(old_path, new_path)
    return new_info


def swap_tracks(usb_root: str, show_name: str, set_number: int, letter_a: str, letter_b: str) -> None:
    """Swaps which physical file is assigned to each of two letters --
    this *is* "reordering" a Set, since a track's letter is its position
    (LIBRARY.md). Either slot may be empty; swapping with an empty slot
    is just "move this track to the other letter"."""
    show_path = _require_show(usb_root, show_name)
    set_path = _require_set(show_path, set_number)
    letter_a = _validate_letter(letter_a)
    letter_b = _validate_letter(letter_b)
    if letter_a == letter_b:
        return

    tracks = list_tracks(usb_root, show_name, set_number)
    track_a, track_b = tracks.get(letter_a), tracks.get(letter_b)

    # Stage both moves through temp names first -- doing a direct
    # rename(a -> b) when b already exists would silently overwrite it
    # on POSIX, destroying a track instead of swapping it.
    if track_a is not None:
        os.rename(
            os.path.join(set_path, track_a.filename),
            os.path.join(set_path, track_a.filename + ".swaptmp"),
        )
    if track_b is not None:
        os.rename(
            os.path.join(set_path, track_b.filename),
            os.path.join(set_path, TrackInfo(letter_a, track_b.display_name, track_b.extension, track_b.is_audio_only).filename),
        )
    if track_a is not None:
        os.rename(
            os.path.join(set_path, track_a.filename + ".swaptmp"),
            os.path.join(set_path, TrackInfo(letter_b, track_a.display_name, track_a.extension, track_a.is_audio_only).filename),
        )


def delete_track(usb_root: str, show_name: str, set_number: int, letter: str) -> None:
    show_path = _require_show(usb_root, show_name)
    set_path = _require_set(show_path, set_number)
    letter = _validate_letter(letter)
    _remove_existing_track(set_path, letter)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _require_show(usb_root: str, show_name: str) -> str:
    show_path = os.path.join(usb_root, show_name)
    if not os.path.isdir(show_path):
        raise LibraryOpsError(f'Show "{show_name}" does not exist')
    return show_path


def _require_set(show_path: str, set_number: int) -> str:
    set_path = os.path.join(show_path, f"Set {set_number}")
    if not os.path.isdir(set_path):
        raise LibraryOpsError(f"Set {set_number} does not exist")
    return set_path


def _validate_set_number(set_number: int) -> None:
    if not isinstance(set_number, int) or set_number < 1:
        raise LibraryOpsError("Set number must be a positive integer")


def _validate_letter(letter: str) -> str:
    letter = (letter or "").strip().upper()
    if letter not in _VALID_LETTERS:
        raise LibraryOpsError(
            f'"{letter}" is not a valid track letter (must be one of '
            f'{", ".join(sorted(_VALID_LETTERS))} -- D is always STOP)'
        )
    return letter


def _validate_extension(extension: str) -> str:
    extension = (extension or "").strip().lower().lstrip(".")
    if extension not in _ALL_EXTENSIONS:
        raise LibraryOpsError(
            f'".{extension}" is not a supported format (must be one of '
            f'{", ".join(sorted(_ALL_EXTENSIONS))})'
        )
    return extension


def _validate_display_name(name: str, what: str) -> None:
    name = name or ""
    if not name.strip():
        raise LibraryOpsError(f"{what} cannot be empty")
    if name != name.strip():
        raise LibraryOpsError(f"{what} cannot start or end with whitespace")
    if _INVALID_NAME_CHARS.search(name):
        raise LibraryOpsError(f'{what} cannot contain any of: / \\ : * ? " < > |')
    # Most Linux filesystems (ext4, and NTFS via ntfs-3g) cap a single
    # path component at 255 bytes. Bounding the display name well below
    # that leaves room for "<Letter> - " and ".<extension>" around it
    # without ever risking a write that the filesystem itself would
    # reject -- found by a test using an unrealistically long name that
    # happened to also exceed Windows' own MAX_PATH during development,
    # which is what prompted adding this check in the first place.
    if len(name.encode("utf-8")) > 200:
        raise LibraryOpsError(f"{what} is too long (200 bytes max)")


def _parse_track_filename(filename: str) -> Optional[TrackInfo]:
    """The inverse of TrackInfo.filename -- parses an existing file back
    into structured form, or returns None if it doesn't match
    LIBRARY.md's pattern at all (an unrelated file sitting in the
    folder, or exactly the kind of malformed name LIBRARY.md warns
    about -- either way, not something this app should try to manage)."""
    for letter in _VALID_LETTERS:
        prefix = f"{letter} - "
        if filename[:len(prefix)].upper() == prefix.upper() and filename.startswith(letter):
            rest = filename[len(prefix):]
            if "." not in rest:
                continue
            display_name, extension = rest.rsplit(".", 1)
            if extension.lower() not in _ALL_EXTENSIONS or not display_name:
                continue
            return TrackInfo(
                letter=letter, display_name=display_name, extension=extension.lower(),
                is_audio_only=extension.lower() in _AUDIO_ONLY_EXTENSIONS,
            )
    return None


def _remove_existing_track(set_path: str, letter: str) -> None:
    tracks_by_letter = {}
    try:
        entries = os.listdir(set_path)
    except OSError:
        return
    for entry in entries:
        info = _parse_track_filename(entry)
        if info is not None:
            tracks_by_letter[info.letter] = entry
    existing = tracks_by_letter.get(letter)
    if existing is not None:
        os.remove(os.path.join(set_path, existing))
