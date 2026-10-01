"""
Read/write operations over the library USB's Set/Bank/track structure,
for the setlist-admin web app (SPECIFICATION.md section 4).

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
import sys
from dataclasses import dataclass
from typing import BinaryIO, Dict, List, Optional

# Reusing core.library's own extension sets rather than redefining them
# -- if a supported format is ever added there, this module picks it up
# automatically instead of silently drifting out of sync. This is this
# expansion's one deliberate dependency on the base project (expansions
# may depend on the base project's own src/, never on each other) -- so
# unlike every other import here, this can't rely on a caller having
# already set up sys.path; it sets up its own path to the base
# project's src/, four levels up from this file
# (expansions/setlist-admin-wifi/src/admin/ -> repo root, then + src).
_BASE_PROJECT_SRC = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "src")
if _BASE_PROJECT_SRC not in sys.path:
    sys.path.insert(0, _BASE_PROJECT_SRC)

from core.library import _AUDIO_ONLY_EXTENSIONS, _VIDEO_EXTENSIONS, _TRACK_LETTERS  # noqa: E402

logger = logging.getLogger(__name__)

_ALL_EXTENSIONS = _AUDIO_ONLY_EXTENSIONS | _VIDEO_EXTENSIONS
_VALID_LETTERS = set(_TRACK_LETTERS.values())  # {"A", "B", "C"} -- D is always STOP, never a file
_BANK_FOLDER_RE = re.compile(r"^Bank (\d+)$")
_UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MiB -- streamed, never the whole file in RAM (section 7)

# The shared song library (SPECIFICATION.md's song-reuse design): a flat
# pool of songs at the USB root, independent of any Set, so the same
# song can be assigned into any number of Sets/Banks without re-uploading
# it each time. A leading "_" is reserved for folders like this one --
# list_sets() excludes anything starting with "_" the same way it
# already excludes dotfiles, so this is invisible to the Set listing
# (and, since core.library.Library never lists the USB root at all --
# only ever active_set.txt's one named folder -- it's invisible to the
# base project too, with zero changes needed there).
_SONGS_FOLDER = "_Songs"

# The looped idle video (core/player.py's --standby) -- a single fixed
# filename at the USB root, not inside any Set/Bank and not subject to
# the "<Letter> - <name>.<ext>" naming convention, since nothing ever
# selects it by letter; Player.start() reads this exact path once at
# boot (see LIBRARY.md). Always written as this exact name regardless of
# the source file's own name/extension -- mpv plays by sniffing content,
# not by file extension, so re-pointing this at a copy of any video file
# works the same way assign_track()/assign_song_to_slot() already does
# for a Bank/Letter slot.
_STANDBY_FILENAME = "standby.mp4"

# What a "display name" may contain -- deliberately conservative (no " - ",
# no path separators, no leading/trailing dots or spaces) so it can never
# combine with the "<Letter> - " prefix to accidentally produce something
# LIBRARY.md's own strict filename pattern would reject.
_INVALID_NAME_CHARS = re.compile(r'[/\\:*?"<>|]')


class LibraryOpsError(ValueError):
    """Raised for any invalid input (bad letter, bad extension, name
    that would break the naming convention, Bank/Set that doesn't
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


@dataclass(frozen=True)
class SongInfo:
    """A song in the shared library (_Songs/) -- not tied to any Set,
    Bank, or letter, unlike TrackInfo."""
    display_name: str
    extension: str
    is_audio_only: bool

    @property
    def filename(self) -> str:
        return f"{self.display_name}.{self.extension}"


@dataclass(frozen=True)
class StandbyInfo:
    """Whatever's currently serving as standby.mp4 -- there's no metadata
    file recording which library song it was copied from (it's always
    just a plain file copy, same as a Bank/Letter slot), so this can only
    describe the file itself, not "where it came from" once set."""
    exists: bool
    size_bytes: int
    modified_at: float  # os.stat().st_mtime -- seconds since epoch


# ---------------------------------------------------------------------------
# Sets
# ---------------------------------------------------------------------------

def list_sets(usb_root: str) -> List[str]:
    """Every top-level folder under the USB root, except this app's own
    dotfile directory and the shared song library -- i.e. every folder
    LIBRARY.md's Set convention would recognize."""
    try:
        entries = os.listdir(usb_root)
    except OSError:
        return []
    return sorted(
        e for e in entries
        if not e.startswith(".") and not e.startswith("_")
        and os.path.isdir(os.path.join(usb_root, e))
    )


def get_active_set(usb_root: str) -> Optional[str]:
    pointer_path = os.path.join(usb_root, "active_set.txt")
    try:
        with open(pointer_path, "r", encoding="utf-8") as f:
            name = f.read().strip()
    except OSError:
        return None
    return name or None


def set_active_set(usb_root: str, set_name: str) -> None:
    set_path = os.path.join(usb_root, set_name)
    if not os.path.isdir(set_path):
        raise LibraryOpsError(f'Set "{set_name}" does not exist')

    pointer_path = os.path.join(usb_root, "active_set.txt")
    with open(pointer_path, "w", encoding="utf-8") as f:
        f.write(set_name)


def create_set(usb_root: str, set_name: str) -> None:
    _validate_display_name(set_name, what="Set name")
    set_path = os.path.join(usb_root, set_name)
    if os.path.isdir(set_path):
        raise LibraryOpsError(f'Set "{set_name}" already exists')
    os.makedirs(set_path)


# ---------------------------------------------------------------------------
# Banks
# ---------------------------------------------------------------------------

def list_banks(usb_root: str, set_name: str) -> List[int]:
    set_path = _require_set(usb_root, set_name)
    try:
        entries = os.listdir(set_path)
    except OSError:
        return []
    numbers = []
    for entry in entries:
        match = _BANK_FOLDER_RE.match(entry)
        if match and os.path.isdir(os.path.join(set_path, entry)):
            numbers.append(int(match.group(1)))
    return sorted(numbers)


def create_bank(usb_root: str, set_name: str, bank_number: int) -> None:
    set_path = _require_set(usb_root, set_name)
    _validate_bank_number(bank_number)
    bank_path = os.path.join(set_path, f"Bank {bank_number}")
    if os.path.isdir(bank_path):
        raise LibraryOpsError(f"Bank {bank_number} already exists")
    os.makedirs(bank_path)


def rename_bank(usb_root: str, set_name: str, old_number: int, new_number: int) -> None:
    set_path = _require_set(usb_root, set_name)
    _validate_bank_number(new_number)
    old_path = _require_bank(set_path, old_number)
    new_path = os.path.join(set_path, f"Bank {new_number}")
    if os.path.exists(new_path):
        raise LibraryOpsError(f"Bank {new_number} already exists")
    os.rename(old_path, new_path)


def delete_bank(usb_root: str, set_name: str, bank_number: int) -> None:
    set_path = _require_set(usb_root, set_name)
    bank_path = _require_bank(set_path, bank_number)
    shutil.rmtree(bank_path)


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------

def list_tracks(usb_root: str, set_name: str, bank_number: int) -> Dict[str, Optional[TrackInfo]]:
    """Returns all 3 letters, mapping to a TrackInfo if that slot is
    filled or None if it's an empty slot -- the caller always gets a
    complete A/B/C picture, matching how Library.resolve() treats a
    missing letter as normal, not an error."""
    set_path = _require_set(usb_root, set_name)
    bank_path = _require_bank(set_path, bank_number)

    result: Dict[str, Optional[TrackInfo]] = {letter: None for letter in sorted(_VALID_LETTERS)}
    try:
        entries = sorted(os.listdir(bank_path))
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
    set_name: str,
    bank_number: int,
    letter: str,
    display_name: str,
    extension: str,
    source: BinaryIO,
) -> TrackInfo:
    """Streams `source` to "<Letter> - <display_name>.<extension>" in
    the given Bank, replacing whatever was there for that letter, if
    anything. Streamed in chunks (never the whole file read into
    memory at once) -- required given this runs on a 1GB-RAM Pi 2,
    matching section 7.

    Also becomes available for reuse in future Sets: best-effort added
    to the shared song library too (skipped, never an error, if a song
    with that exact name is already there -- see _add_to_library_if_new)."""
    set_path = _require_set(usb_root, set_name)
    bank_path = _require_bank(set_path, bank_number)
    letter = _validate_letter(letter)
    extension = _validate_extension(extension)
    _validate_display_name(display_name, what="track name")

    _remove_existing_track(bank_path, letter)

    info = TrackInfo(
        letter=letter, display_name=display_name, extension=extension,
        is_audio_only=extension in _AUDIO_ONLY_EXTENSIONS,
    )
    dest_path = os.path.join(bank_path, info.filename)

    # Write to a temp name first, rename into place at the end -- so a
    # failed/interrupted upload (dropped connection mid-transfer, the
    # classic risk this app is designed around) never leaves a
    # half-written file sitting under the real "<Letter> - ..." name
    # where Library.resolve() could find and try to play it.
    _atomic_write_stream(dest_path, source)
    _add_to_library_if_new(usb_root, dest_path, info.display_name, info.extension, info.is_audio_only)

    return info


def rename_track(usb_root: str, set_name: str, bank_number: int, letter: str, new_display_name: str) -> TrackInfo:
    """Renames the display-name part only -- the letter (its "position")
    and extension stay the same. To move a track to a different letter,
    see swap_tracks()."""
    set_path = _require_set(usb_root, set_name)
    bank_path = _require_bank(set_path, bank_number)
    letter = _validate_letter(letter)
    _validate_display_name(new_display_name, what="track name")

    tracks = list_tracks(usb_root, set_name, bank_number)
    current = tracks.get(letter)
    if current is None:
        raise LibraryOpsError(f"Track {letter} is empty, nothing to rename")

    old_path = os.path.join(bank_path, current.filename)
    new_info = TrackInfo(
        letter=letter, display_name=new_display_name,
        extension=current.extension, is_audio_only=current.is_audio_only,
    )
    new_path = os.path.join(bank_path, new_info.filename)
    os.rename(old_path, new_path)
    return new_info


def swap_tracks(usb_root: str, set_name: str, bank_number: int, letter_a: str, letter_b: str) -> None:
    """Swaps which physical file is assigned to each of two letters --
    this *is* "reordering" a Bank, since a track's letter is its position
    (LIBRARY.md). Either slot may be empty; swapping with an empty slot
    is just "move this track to the other letter"."""
    set_path = _require_set(usb_root, set_name)
    bank_path = _require_bank(set_path, bank_number)
    letter_a = _validate_letter(letter_a)
    letter_b = _validate_letter(letter_b)
    if letter_a == letter_b:
        return

    tracks = list_tracks(usb_root, set_name, bank_number)
    track_a, track_b = tracks.get(letter_a), tracks.get(letter_b)

    # Stage both moves through temp names first -- doing a direct
    # rename(a -> b) when b already exists would silently overwrite it
    # on POSIX, destroying a track instead of swapping it.
    if track_a is not None:
        os.rename(
            os.path.join(bank_path, track_a.filename),
            os.path.join(bank_path, track_a.filename + ".swaptmp"),
        )
    if track_b is not None:
        os.rename(
            os.path.join(bank_path, track_b.filename),
            os.path.join(bank_path, TrackInfo(letter_a, track_b.display_name, track_b.extension, track_b.is_audio_only).filename),
        )
    if track_a is not None:
        os.rename(
            os.path.join(bank_path, track_a.filename + ".swaptmp"),
            os.path.join(bank_path, TrackInfo(letter_b, track_a.display_name, track_a.extension, track_a.is_audio_only).filename),
        )


def delete_track(usb_root: str, set_name: str, bank_number: int, letter: str) -> None:
    set_path = _require_set(usb_root, set_name)
    bank_path = _require_bank(set_path, bank_number)
    letter = _validate_letter(letter)
    _remove_existing_track(bank_path, letter)


# ---------------------------------------------------------------------------
# Song library (_Songs/) -- reusable across every Set. A Set's
# Bank/Letter slot is always a *copy* of a song here, never a reference,
# so each Set stays exactly as self-contained as it always was (nothing
# about core.library.Library's boot-time resolution changes) and a human
# without this app could recreate the same convention by hand over SSH
# with a plain `cp`.
# ---------------------------------------------------------------------------

def list_songs(usb_root: str) -> List[SongInfo]:
    songs_path = _songs_path(usb_root)
    try:
        entries = sorted(os.listdir(songs_path))
    except OSError:
        return []
    songs = []
    for entry in entries:
        info = _parse_song_filename(entry)
        if info is not None:
            songs.append(info)
    return songs


def upload_song(usb_root: str, display_name: str, extension: str, source: BinaryIO) -> SongInfo:
    """Streams `source` straight into the shared library as
    "<display_name>.<extension>". Rejects a name that's already taken --
    delete_song() or rename_song() first to replace it; no silent
    overwrites, same rule as create_set()/create_bank()."""
    extension = _validate_extension(extension)
    _validate_display_name(display_name, what="song name")

    info = SongInfo(
        display_name=display_name, extension=extension,
        is_audio_only=extension in _AUDIO_ONLY_EXTENSIONS,
    )
    songs_path = _songs_path(usb_root)
    dest_path = os.path.join(songs_path, info.filename)
    if os.path.exists(dest_path):
        raise LibraryOpsError(f'A song named "{info.filename}" already exists in the library')

    os.makedirs(songs_path, exist_ok=True)
    _atomic_write_stream(dest_path, source)
    return info


def rename_song(usb_root: str, filename: str, new_display_name: str) -> SongInfo:
    songs_path = _songs_path(usb_root)
    current = _parse_song_filename(filename)
    if current is None:
        raise LibraryOpsError(f'"{filename}" is not a song in the library')
    _validate_display_name(new_display_name, what="song name")

    old_path = os.path.join(songs_path, current.filename)
    # Real bug found on real hardware: unlike every other function here
    # (assign_song_to_slot(), _require_set()/_require_bank(),
    # rename_track()'s fresh list_tracks() re-check), this never
    # verified the file was still actually there before touching it --
    # a stale UI reference to a song someone deleted by hand directly on
    # the USB (a workflow this project explicitly supports/recommends
    # against but can't prevent) hit a raw, unhandled FileNotFoundError
    # instead of a clean error message.
    if not os.path.isfile(old_path):
        raise LibraryOpsError(f'"{current.filename}" is not in the library')

    new_info = SongInfo(
        display_name=new_display_name, extension=current.extension,
        is_audio_only=current.is_audio_only,
    )
    new_path = os.path.join(songs_path, new_info.filename)
    if os.path.exists(new_path):
        raise LibraryOpsError(f'A song named "{new_info.filename}" already exists in the library')
    os.rename(old_path, new_path)
    return new_info


def delete_song(usb_root: str, filename: str) -> None:
    """Removes a song from the shared library only -- copies already
    assigned into a Set's Bank are independent files, untouched by this."""
    songs_path = _songs_path(usb_root)
    info = _parse_song_filename(filename)
    if info is None:
        raise LibraryOpsError(f'"{filename}" is not a song in the library')
    target_path = os.path.join(songs_path, info.filename)
    # Same real bug as rename_song() above -- a stale reference to an
    # already-manually-deleted song must not hit a raw FileNotFoundError.
    if not os.path.isfile(target_path):
        raise LibraryOpsError(f'"{info.filename}" is not in the library')
    os.remove(target_path)


def assign_song_to_slot(
    usb_root: str, set_name: str, bank_number: int, letter: str, song_filename: str,
) -> TrackInfo:
    """Copies a song from the shared library into a Set's Bank/Letter
    slot, replacing whatever was there before -- the library's own copy
    is untouched, so the same song stays available for the next Set.
    This is the "reuse an existing song" path; assign_track() is the
    "upload a new one" path (which also adds it to the library as a
    side effect, so both paths converge)."""
    set_path = _require_set(usb_root, set_name)
    bank_path = _require_bank(set_path, bank_number)
    letter = _validate_letter(letter)

    song = _parse_song_filename(song_filename)
    if song is None:
        raise LibraryOpsError(f'"{song_filename}" is not a song in the library')
    source_path = os.path.join(_songs_path(usb_root), song.filename)
    if not os.path.isfile(source_path):
        raise LibraryOpsError(f'"{song.filename}" is not in the library')

    _remove_existing_track(bank_path, letter)

    info = TrackInfo(
        letter=letter, display_name=song.display_name,
        extension=song.extension, is_audio_only=song.is_audio_only,
    )
    dest_path = os.path.join(bank_path, info.filename)
    _atomic_copy_file(source_path, dest_path)
    return info


def save_track_to_library(usb_root: str, set_name: str, bank_number: int, letter: str) -> SongInfo:
    """The reverse direction: copies whatever is already assigned to a
    Bank/Letter slot into the shared library, so it becomes available for
    future Sets too. Meant for content assigned before this feature
    existed (or from a different Pi/USB) -- no automatic migration or
    dedup is attempted; this is always an explicit, one-track-at-a-time
    action, since guessing whether two files across different Sets are
    "the same song" is exactly the kind of fragile heuristic this
    project avoids (SPECIFICATION.md)."""
    set_path = _require_set(usb_root, set_name)
    bank_path = _require_bank(set_path, bank_number)
    letter = _validate_letter(letter)

    tracks = list_tracks(usb_root, set_name, bank_number)
    track = tracks.get(letter)
    if track is None:
        raise LibraryOpsError(f"Track {letter} is empty, nothing to save")

    info = SongInfo(
        display_name=track.display_name, extension=track.extension,
        is_audio_only=track.is_audio_only,
    )
    songs_path = _songs_path(usb_root)
    dest_path = os.path.join(songs_path, info.filename)
    if os.path.exists(dest_path):
        raise LibraryOpsError(f'A song named "{info.filename}" already exists in the library')

    os.makedirs(songs_path, exist_ok=True)
    source_path = os.path.join(bank_path, track.filename)
    _atomic_copy_file(source_path, dest_path)
    return info


def get_standby_info(usb_root: str) -> StandbyInfo:
    path = os.path.join(usb_root, _STANDBY_FILENAME)
    try:
        st = os.stat(path)
    except OSError:
        return StandbyInfo(exists=False, size_bytes=0, modified_at=0.0)
    return StandbyInfo(exists=True, size_bytes=st.st_size, modified_at=st.st_mtime)


def set_standby_video(usb_root: str, song_filename: str) -> SongInfo:
    """Copies a song already in the shared library to become the new
    standby.mp4 -- the "pick one you already uploaded" path. To use a
    brand new file instead, upload_song() it into the library first (also
    gives it a codec check, same as any other upload), then call this.

    Must be a video: standby has no footswitch pointing at it, so an
    audio-only file here would mean Player.start() loops a track nobody
    can ever see or hear anything of (there's no Bank/Letter slot
    involved for standby.mp4 -- Library.resolve() is never consulted for
    it, only Player.start() resolves this path directly, once, at boot)."""
    song = _parse_song_filename(song_filename)
    if song is None:
        raise LibraryOpsError(f'"{song_filename}" is not a song in the library')
    if song.is_audio_only:
        raise LibraryOpsError("The standby video must be a video file, not audio-only")

    source_path = os.path.join(_songs_path(usb_root), song.filename)
    if not os.path.isfile(source_path):
        raise LibraryOpsError(f'"{song.filename}" is not in the library')

    dest_path = os.path.join(usb_root, _STANDBY_FILENAME)
    _atomic_copy_file(source_path, dest_path)
    return song


def _songs_path(usb_root: str) -> str:
    return os.path.join(usb_root, _SONGS_FOLDER)


def _parse_song_filename(filename: str) -> Optional[SongInfo]:
    if "." not in filename:
        return None
    display_name, extension = filename.rsplit(".", 1)
    if extension.lower() not in _ALL_EXTENSIONS or not display_name:
        return None
    return SongInfo(
        display_name=display_name, extension=extension.lower(),
        is_audio_only=extension.lower() in _AUDIO_ONLY_EXTENSIONS,
    )


def _add_to_library_if_new(
    usb_root: str, source_path: str, display_name: str, extension: str, is_audio_only: bool,
) -> None:
    """Best-effort only: a fresh upload also becomes reusable in future
    Sets, unless a song with that exact name is already in the library
    -- never overwritten, and this never fails the caller's own write
    over it (a convenience side effect, not something the primary
    assign_track() operation should ever fail because of)."""
    songs_path = _songs_path(usb_root)
    dest_path = os.path.join(songs_path, f"{display_name}.{extension}")
    if os.path.exists(dest_path):
        return
    try:
        os.makedirs(songs_path, exist_ok=True)
        _atomic_copy_file(source_path, dest_path)
    except OSError:
        logger.warning("Could not add %s to the song library", os.path.basename(source_path))


def _atomic_write_stream(dest_path: str, source: BinaryIO) -> None:
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


def _atomic_copy_file(source_path: str, dest_path: str) -> None:
    tmp_path = dest_path + ".part"
    try:
        shutil.copyfile(source_path, tmp_path)
        os.replace(tmp_path, dest_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def cleanup_stale_temp_files(usb_root: str) -> int:
    """Removes any leftover `.part`/`.swaptmp` file anywhere under
    `usb_root`. These only ever exist mid-write, as a `_atomic_write_stream`/
    `_atomic_copy_file`/`swap_tracks()` in-progress artifact, and normally
    clean themselves up (on success via `os.replace()`, on a caught
    exception via the `except` blocks above) -- but a write killed
    abruptly by a SIGTERM skips that cleanup entirely, since a signal
    doesn't run Python's except/finally blocks. Confirmed on real
    hardware: unplugging a phone mid-upload makes
    `usb-tether-watchdog.service` stop this service the moment the
    tethered interface disappears, killing an in-progress upload before
    its own cleanup could run and leaving its `.part` file behind
    (harmless -- never promoted to a real filename, so never picked up
    as real data -- but permanent clutter otherwise). Never represents
    valid data by construction, so always safe to remove; called once at
    server startup. Returns the count removed."""
    removed = 0
    for root, _dirs, files in os.walk(usb_root):
        for name in files:
            if name.endswith(".part") or name.endswith(".swaptmp"):
                try:
                    os.remove(os.path.join(root, name))
                    removed += 1
                except OSError:
                    pass
    return removed


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _require_set(usb_root: str, set_name: str) -> str:
    set_path = os.path.join(usb_root, set_name)
    if not os.path.isdir(set_path):
        raise LibraryOpsError(f'Set "{set_name}" does not exist')
    return set_path


def _require_bank(set_path: str, bank_number: int) -> str:
    bank_path = os.path.join(set_path, f"Bank {bank_number}")
    if not os.path.isdir(bank_path):
        raise LibraryOpsError(f"Bank {bank_number} does not exist")
    return bank_path


def _validate_bank_number(bank_number: int) -> None:
    if not isinstance(bank_number, int) or bank_number < 1:
        raise LibraryOpsError("Bank number must be a positive integer")


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


def _remove_existing_track(bank_path: str, letter: str) -> None:
    tracks_by_letter = {}
    try:
        entries = os.listdir(bank_path)
    except OSError:
        return
    for entry in entries:
        info = _parse_track_filename(entry)
        if info is not None:
            tracks_by_letter[info.letter] = entry
    existing = tracks_by_letter.get(letter)
    if existing is not None:
        os.remove(os.path.join(bank_path, existing))
