"""
Library: resolves an abstract SelectTrack(setlist, track) into a real file
path on the library USB drive (section 2 of MASTER_SPECIFICATION.md).

Directory convention on the USB (agreed with the user):

    <usb_root>/
    ├── active_set.txt           -- one line: exact name of the active Set folder
    ├── <Set name>/
    │   ├── Bank 1/
    │   │   ├── A - Song name.mp3
    │   │   ├── B - Song name.mp4
    │   │   └── C - Song name.wav
    │   └── Bank 7/
    │       └── ...
    └── standby.mp4

Terminology (renamed from an earlier "Show"/"Set" naming -- see
CHANGELOG.md): a **Set** is the whole collection played in one live
show, made up of up to 8 **Banks**, each with up to 3 tracks (A/B/C).
This matches the controller's own terminology (`MAVAVE_ANALYSIS.md`).
The `setlist` parameter below is the internal Mapper/Core action
protocol's name for "which Bank" -- kept as-is on purpose, since it's
never user-facing (see CHANGELOG.md for why this one name didn't change
along with everything else).

track 1/2/3 map to letters A/B/C respectively -- track 4 (D) never reaches
this class in practice, since the Mapper already turns it into Stop()
before the Core sees it.

Supported file types (section 2 of MASTER_SPECIFICATION.md):
- Video, with embedded audio: .mp4, .mov, .mpeg/.mpg
- Audio-only: .mp3, .wav -- these behave the same way (the standby video
  keeps looping on screen while the audio plays over it)

resolve() reports which kind a file is via ResolvedTrack.is_audio_only,
so the Core (via the Player) knows whether to switch the video or just
overlay audio on top of the current standby loop.

Robustness rule (explicitly requested by the user): if more than one
folder matches the requested Bank number (e.g. "Bank 7" and "Bank 07"
both present by mistake), or more than one file matches the requested
track letter within a Bank, the first one found is used, in whatever
order the filesystem happens to list them -- no specific order is
guaranteed or required. The goal is that a naming mistake in the
library never makes a Bank/track unreachable; it just makes which
duplicate gets picked unspecified.

This class never writes to or deletes anything on the USB -- read-only,
matching the "never format/delete the library" requirement in section 2.
"""

import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_TRACK_LETTERS = {1: "A", 2: "B", 3: "C"}
_BANK_FOLDER_RE = re.compile(r"^Bank (\d+)$")
_AUDIO_ONLY_EXTENSIONS = {"mp3", "wav"}
_VIDEO_EXTENSIONS = {"mp4", "mov", "mpeg", "mpg"}
_ALL_EXTENSIONS = _AUDIO_ONLY_EXTENSIONS | _VIDEO_EXTENSIONS


@dataclass(frozen=True)
class ResolvedTrack:
    """What Library.resolve() hands back: a real file path plus enough
    information for the Player to decide how to play it."""
    path: str
    is_audio_only: bool


# Precompiled once at import time, for each of the 3 possible track
# letters -- resolve() runs on every footswitch press, and recompiling a
# fresh regex from a formatted string on every single call was repeated
# work for no reason (there are only ever 3 patterns, know in advance).
_TRACK_FILE_PATTERNS = {
    letter: re.compile(
        rf"^{letter} - .+\.({'|'.join(_ALL_EXTENSIONS)})$", re.IGNORECASE
    )
    for letter in _TRACK_LETTERS.values()
}


class Library:
    def __init__(self, usb_root: str):
        self.usb_root = usb_root

    def active_set_path(self) -> Optional[str]:
        """Returns the absolute path to the active Set's folder, or None
        if active_set.txt is missing, empty, or points to a folder that
        doesn't exist."""
        pointer_path = os.path.join(self.usb_root, "active_set.txt")
        try:
            with open(pointer_path, "r", encoding="utf-8") as f:
                set_name = f.read().strip()
        except OSError:
            logger.warning("Could not read %s", pointer_path)
            return None

        if not set_name:
            logger.warning("%s is empty", pointer_path)
            return None

        set_path = os.path.join(self.usb_root, set_name)
        if not os.path.isdir(set_path):
            logger.warning(
                "active_set.txt points to '%s', but that folder doesn't "
                "exist under %s",
                set_name, self.usb_root,
            )
            return None

        return set_path

    def resolve(self, setlist: int, track: int) -> Optional[ResolvedTrack]:
        """Returns a ResolvedTrack for this Bank/track, or None if it
        can't be found (missing Set, missing Bank folder, or no file for
        that letter -- an empty slot is a normal, expected situation, not
        an error)."""
        letter = _TRACK_LETTERS.get(track)
        if letter is None:
            logger.warning(
                "track %d has no assigned letter (only 1-3 / A-C are valid)",
                track,
            )
            return None

        set_path = self.active_set_path()
        if set_path is None:
            return None

        bank_folder = self._find_bank_folder(set_path, setlist)
        if bank_folder is None:
            logger.info("Bank %d not found in '%s'", setlist, set_path)
            return None

        file_path = self._find_track_file(bank_folder, letter)
        if file_path is None:
            logger.info(
                "No file for track %s in '%s' (empty slot)", letter, bank_folder
            )
            return None

        extension = file_path.rsplit(".", 1)[-1].lower()
        return ResolvedTrack(path=file_path, is_audio_only=extension in _AUDIO_ONLY_EXTENSIONS)

    def _find_bank_folder(self, set_path: str, bank_number: int) -> Optional[str]:
        try:
            entries = sorted(os.listdir(set_path))
        except OSError:
            return None

        # If more than one entry matches this Bank number, the first one
        # found wins -- see the robustness rule in the module docstring.
        for entry in entries:
            match = _BANK_FOLDER_RE.match(entry)
            if match and int(match.group(1)) == bank_number:
                full_path = os.path.join(set_path, entry)
                if os.path.isdir(full_path):
                    return full_path
        return None

    def _find_track_file(self, bank_folder: str, letter: str) -> Optional[str]:
        pattern = _TRACK_FILE_PATTERNS[letter]
        try:
            entries = sorted(os.listdir(bank_folder))
        except OSError:
            return None

        # Same rule as above: first match wins if there happen to be
        # duplicates for the same letter.
        for entry in entries:
            if pattern.match(entry):
                return os.path.join(bank_folder, entry)
        return None
