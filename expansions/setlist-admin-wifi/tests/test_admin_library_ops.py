"""
library_ops.py tests. No hardware needed -- a plain temp directory,
same style as tests/test_library.py.

Run with: python -m unittest tests/test_admin_library_ops.py
"""

import io
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from admin import library_ops  # noqa: E402


# Mirrors core.library's own naming rule exactly -- used to check, from
# the outside, that nothing this module writes could ever violate it.
_VALID_FILENAME_RE = re.compile(r"^[ABC] - .+\.(mp3|wav|mp4|mov|mpeg|mpg)$")


class LibraryOpsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.usb_root = self.tmpdir.name

    def tearDown(self):
        self.tmpdir.cleanup()

    def _make_set_with_bank(self, set_name="Live", bank_number=1):
        os.makedirs(os.path.join(self.usb_root, set_name, f"Bank {bank_number}"))
        return set_name, bank_number


class TestSets(LibraryOpsTestCase):
    def test_create_and_list_set(self):
        library_ops.create_set(self.usb_root, "Live")
        self.assertEqual(library_ops.list_sets(self.usb_root), ["Live"])

    def test_list_sets_excludes_dotfile_directories(self):
        library_ops.create_set(self.usb_root, "Live")
        os.makedirs(os.path.join(self.usb_root, ".setlist-admin"))
        self.assertEqual(library_ops.list_sets(self.usb_root), ["Live"])

    def test_creating_duplicate_set_raises(self):
        library_ops.create_set(self.usb_root, "Live")
        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.create_set(self.usb_root, "Live")

    def test_set_active_set_requires_existing_set(self):
        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.set_active_set(self.usb_root, "Does Not Exist")

    def test_set_and_get_active_set(self):
        library_ops.create_set(self.usb_root, "Live")
        library_ops.set_active_set(self.usb_root, "Live")
        self.assertEqual(library_ops.get_active_set(self.usb_root), "Live")

    def test_get_active_set_with_no_pointer_file_returns_none(self):
        self.assertIsNone(library_ops.get_active_set(self.usb_root))


class TestBanks(LibraryOpsTestCase):
    def test_create_and_list_bank(self):
        library_ops.create_set(self.usb_root, "Live")
        library_ops.create_bank(self.usb_root, "Live", 1)
        self.assertEqual(library_ops.list_banks(self.usb_root, "Live"), [1])

    def test_banks_are_listed_numerically_sorted(self):
        library_ops.create_set(self.usb_root, "Live")
        for n in [10, 2, 1]:
            library_ops.create_bank(self.usb_root, "Live", n)
        self.assertEqual(library_ops.list_banks(self.usb_root, "Live"), [1, 2, 10])

    def test_create_bank_requires_existing_set(self):
        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.create_bank(self.usb_root, "Nope", 1)

    def test_create_duplicate_bank_raises(self):
        library_ops.create_set(self.usb_root, "Live")
        library_ops.create_bank(self.usb_root, "Live", 1)
        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.create_bank(self.usb_root, "Live", 1)

    def test_invalid_bank_number_raises(self):
        library_ops.create_set(self.usb_root, "Live")
        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.create_bank(self.usb_root, "Live", 0)
        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.create_bank(self.usb_root, "Live", -1)

    def test_rename_bank(self):
        set_name, _ = self._make_set_with_bank()
        library_ops.rename_bank(self.usb_root, set_name, 1, 2)
        self.assertEqual(library_ops.list_banks(self.usb_root, set_name), [2])

    def test_rename_bank_to_existing_number_raises(self):
        set_name, _ = self._make_set_with_bank(bank_number=1)
        library_ops.create_bank(self.usb_root, set_name, 2)
        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.rename_bank(self.usb_root, set_name, 1, 2)

    def test_delete_bank(self):
        set_name, bank_number = self._make_set_with_bank()
        library_ops.delete_bank(self.usb_root, set_name, bank_number)
        self.assertEqual(library_ops.list_banks(self.usb_root, set_name), [])

    def test_delete_bank_removes_its_tracks_too(self):
        set_name, bank_number = self._make_set_with_bank()
        bank_path = os.path.join(self.usb_root, set_name, f"Bank {bank_number}")
        with open(os.path.join(bank_path, "A - Song.mp3"), "wb") as f:
            f.write(b"data")
        library_ops.delete_bank(self.usb_root, set_name, bank_number)
        self.assertFalse(os.path.exists(bank_path))


class TestListTracks(LibraryOpsTestCase):
    def test_empty_set_reports_all_three_letters_as_none(self):
        set_name, bank_number = self._make_set_with_bank()
        tracks = library_ops.list_tracks(self.usb_root, set_name, bank_number)
        self.assertEqual(tracks, {"A": None, "B": None, "C": None})

    def test_existing_file_is_parsed_correctly(self):
        set_name, bank_number = self._make_set_with_bank()
        bank_path = os.path.join(self.usb_root, set_name, f"Bank {bank_number}")
        with open(os.path.join(bank_path, "B - My Song.mp4"), "wb") as f:
            f.write(b"data")

        tracks = library_ops.list_tracks(self.usb_root, set_name, bank_number)

        self.assertIsNotNone(tracks["B"])
        self.assertEqual(tracks["B"].display_name, "My Song")
        self.assertEqual(tracks["B"].extension, "mp4")
        self.assertFalse(tracks["B"].is_audio_only)

    def test_mp3_and_wav_are_audio_only(self):
        set_name, bank_number = self._make_set_with_bank()
        bank_path = os.path.join(self.usb_root, set_name, f"Bank {bank_number}")
        with open(os.path.join(bank_path, "A - Song.mp3"), "wb") as f:
            f.write(b"")
        with open(os.path.join(bank_path, "B - Song.wav"), "wb") as f:
            f.write(b"")

        tracks = library_ops.list_tracks(self.usb_root, set_name, bank_number)

        self.assertTrue(tracks["A"].is_audio_only)
        self.assertTrue(tracks["B"].is_audio_only)

    def test_unrelated_file_in_the_folder_is_ignored(self):
        set_name, bank_number = self._make_set_with_bank()
        bank_path = os.path.join(self.usb_root, set_name, f"Bank {bank_number}")
        with open(os.path.join(bank_path, "readme.txt"), "w") as f:
            f.write("not a track")

        tracks = library_ops.list_tracks(self.usb_root, set_name, bank_number)

        self.assertEqual(tracks, {"A": None, "B": None, "C": None})

    def test_malformed_filename_from_a_manual_edit_is_treated_as_empty(self):
        # The exact real-world case LIBRARY.md documents: a double space
        # before the dash. list_tracks() must not crash on this, and
        # must not treat it as a valid track A -- matching
        # Library.resolve()'s own "empty slot" behavior for the same
        # file (core/library.py).
        set_name, bank_number = self._make_set_with_bank()
        bank_path = os.path.join(self.usb_root, set_name, f"Bank {bank_number}")
        with open(os.path.join(bank_path, "A  - Bad Spacing.mp4"), "wb") as f:
            f.write(b"data")

        tracks = library_ops.list_tracks(self.usb_root, set_name, bank_number)

        self.assertIsNone(tracks["A"])


class TestAssignTrack(LibraryOpsTestCase):
    def test_upload_creates_correctly_named_file(self):
        set_name, bank_number = self._make_set_with_bank()

        library_ops.assign_track(
            self.usb_root, set_name, bank_number, "a", "My Song", "MP4",
            io.BytesIO(b"fake video bytes"),
        )

        bank_path = os.path.join(self.usb_root, set_name, f"Bank {bank_number}")
        entries = os.listdir(bank_path)
        self.assertEqual(entries, ["A - My Song.mp4"])
        with open(os.path.join(bank_path, "A - My Song.mp4"), "rb") as f:
            self.assertEqual(f.read(), b"fake video bytes")

    def test_upload_large_file_is_streamed_not_buffered(self):
        # Exercises the chunked-write path with a file bigger than one
        # chunk, without actually needing gigabytes -- shrink the chunk
        # size just for this test via direct constant patching would be
        # more invasive than useful; instead just confirm multi-MB
        # content round-trips correctly, which already proves chunking
        # works (a naive single .read() would too, but a broken chunk
        # loop wouldn't).
        set_name, bank_number = self._make_set_with_bank()
        content = b"x" * (3 * 1024 * 1024)  # 3 MiB, > the 1 MiB chunk size

        library_ops.assign_track(
            self.usb_root, set_name, bank_number, "A", "Big File", "mp4",
            io.BytesIO(content),
        )

        bank_path = os.path.join(self.usb_root, set_name, f"Bank {bank_number}")
        with open(os.path.join(bank_path, "A - Big File.mp4"), "rb") as f:
            self.assertEqual(f.read(), content)

    def test_upload_replaces_existing_track_for_that_letter(self):
        set_name, bank_number = self._make_set_with_bank()
        library_ops.assign_track(self.usb_root, set_name, bank_number, "A", "Old", "mp3", io.BytesIO(b"old"))

        library_ops.assign_track(self.usb_root, set_name, bank_number, "A", "New", "mp3", io.BytesIO(b"new"))

        bank_path = os.path.join(self.usb_root, set_name, f"Bank {bank_number}")
        entries = os.listdir(bank_path)
        self.assertEqual(entries, ["A - New.mp3"])

    def test_no_leftover_part_file_after_successful_upload(self):
        set_name, bank_number = self._make_set_with_bank()
        library_ops.assign_track(self.usb_root, set_name, bank_number, "A", "Song", "mp3", io.BytesIO(b"data"))
        bank_path = os.path.join(self.usb_root, set_name, f"Bank {bank_number}")
        self.assertEqual(os.listdir(bank_path), ["A - Song.mp3"])

    def test_invalid_letter_raises_and_writes_nothing(self):
        set_name, bank_number = self._make_set_with_bank()
        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.assign_track(self.usb_root, set_name, bank_number, "X", "Song", "mp3", io.BytesIO(b"data"))
        bank_path = os.path.join(self.usb_root, set_name, f"Bank {bank_number}")
        self.assertEqual(os.listdir(bank_path), [])

    def test_unsupported_extension_raises(self):
        set_name, bank_number = self._make_set_with_bank()
        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.assign_track(self.usb_root, set_name, bank_number, "A", "Song", "exe", io.BytesIO(b"data"))

    def test_extension_is_case_insensitive(self):
        set_name, bank_number = self._make_set_with_bank()
        library_ops.assign_track(self.usb_root, set_name, bank_number, "A", "Song", "MP3", io.BytesIO(b"data"))
        bank_path = os.path.join(self.usb_root, set_name, f"Bank {bank_number}")
        self.assertIn("A - Song.mp3", os.listdir(bank_path))

    def test_empty_display_name_raises(self):
        set_name, bank_number = self._make_set_with_bank()
        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.assign_track(self.usb_root, set_name, bank_number, "A", "", "mp3", io.BytesIO(b"data"))

    def test_display_name_with_path_separator_raises(self):
        set_name, bank_number = self._make_set_with_bank()
        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.assign_track(self.usb_root, set_name, bank_number, "A", "../../etc/passwd", "mp3", io.BytesIO(b"data"))

    def test_display_name_with_leading_or_trailing_whitespace_raises(self):
        # This is the actual property that matters most: it must be
        # impossible to accidentally reproduce LIBRARY.md's "double
        # space before the dash" bug through this API. A trailing space
        # on the *display name* would, combined with the " - " this
        # module adds itself, produce exactly that kind of malformed
        # spacing -- so it's rejected outright instead.
        set_name, bank_number = self._make_set_with_bank()
        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.assign_track(self.usb_root, set_name, bank_number, "A", " Song", "mp3", io.BytesIO(b"data"))
        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.assign_track(self.usb_root, set_name, bank_number, "A", "Song ", "mp3", io.BytesIO(b"data"))

    def test_excessively_long_display_name_raises(self):
        # Bounds the name well under the 255-byte-per-component limit
        # most Linux filesystems enforce (ext4, NTFS via ntfs-3g), so a
        # write here can never fail at the filesystem level instead of
        # with a clear error from this module.
        set_name, bank_number = self._make_set_with_bank()
        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.assign_track(self.usb_root, set_name, bank_number, "A", "A" * 201, "mp3", io.BytesIO(b"data"))


class TestNamingIsAlwaysValid(LibraryOpsTestCase):
    """The core guarantee of this whole module: no combination of valid
    inputs can produce a filename LIBRARY.md's own naming rule would
    reject. Fuzzes a range of "awkward but technically allowed" display
    names and checks every resulting filename against the same pattern
    core.library.Library actually matches tracks with."""

    def test_a_range_of_display_names_all_produce_valid_filenames(self):
        set_name, bank_number = self._make_set_with_bank()
        candidate_names = [
            "Song",
            "Song - With A Dash",
            "Song.With.Dots",
            "123 Numbers First",
            "Ünïcödé Name",
            "A" * 100,  # long-ish but realistic name
            "Song (Live Version)",
        ]
        for i, name in enumerate(candidate_names):
            letter = "ABC"[i % 3]
            if letter == "A" and i >= 3:
                # avoid clobbering across the small A/B/C letter space
                library_ops.delete_track(self.usb_root, set_name, bank_number, letter)
            library_ops.assign_track(
                self.usb_root, set_name, bank_number, letter, name, "mp3", io.BytesIO(b"x"),
            )
            bank_path = os.path.join(self.usb_root, set_name, f"Bank {bank_number}")
            filenames = [f for f in os.listdir(bank_path) if f.startswith(letter)]
            self.assertEqual(len(filenames), 1)
            self.assertRegex(filenames[0], _VALID_FILENAME_RE,
                              f"filename produced from display name {name!r} is invalid: {filenames[0]!r}")


class TestRenameTrack(LibraryOpsTestCase):
    def test_rename_changes_display_name_keeps_letter_and_extension(self):
        set_name, bank_number = self._make_set_with_bank()
        library_ops.assign_track(self.usb_root, set_name, bank_number, "A", "Old Name", "mp3", io.BytesIO(b"data"))

        library_ops.rename_track(self.usb_root, set_name, bank_number, "A", "New Name")

        tracks = library_ops.list_tracks(self.usb_root, set_name, bank_number)
        self.assertEqual(tracks["A"].display_name, "New Name")
        self.assertEqual(tracks["A"].extension, "mp3")

    def test_renaming_empty_slot_raises(self):
        set_name, bank_number = self._make_set_with_bank()
        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.rename_track(self.usb_root, set_name, bank_number, "A", "New Name")


class TestSwapTracks(LibraryOpsTestCase):
    def test_swap_two_filled_slots(self):
        set_name, bank_number = self._make_set_with_bank()
        library_ops.assign_track(self.usb_root, set_name, bank_number, "A", "Song A", "mp3", io.BytesIO(b"aaa"))
        library_ops.assign_track(self.usb_root, set_name, bank_number, "B", "Song B", "mp4", io.BytesIO(b"bbb"))

        library_ops.swap_tracks(self.usb_root, set_name, bank_number, "A", "B")

        tracks = library_ops.list_tracks(self.usb_root, set_name, bank_number)
        self.assertEqual(tracks["A"].display_name, "Song B")
        self.assertEqual(tracks["B"].display_name, "Song A")
        # Content actually moved with the name, not just relabeled.
        bank_path = os.path.join(self.usb_root, set_name, f"Bank {bank_number}")
        with open(os.path.join(bank_path, "A - Song B.mp4"), "rb") as f:
            self.assertEqual(f.read(), b"bbb")
        with open(os.path.join(bank_path, "B - Song A.mp3"), "rb") as f:
            self.assertEqual(f.read(), b"aaa")

    def test_swap_filled_slot_with_empty_slot_moves_the_track(self):
        set_name, bank_number = self._make_set_with_bank()
        library_ops.assign_track(self.usb_root, set_name, bank_number, "A", "Song", "mp3", io.BytesIO(b"data"))

        library_ops.swap_tracks(self.usb_root, set_name, bank_number, "A", "C")

        tracks = library_ops.list_tracks(self.usb_root, set_name, bank_number)
        self.assertIsNone(tracks["A"])
        self.assertEqual(tracks["C"].display_name, "Song")

    def test_swap_with_itself_is_a_no_op(self):
        set_name, bank_number = self._make_set_with_bank()
        library_ops.assign_track(self.usb_root, set_name, bank_number, "A", "Song", "mp3", io.BytesIO(b"data"))
        library_ops.swap_tracks(self.usb_root, set_name, bank_number, "A", "A")
        tracks = library_ops.list_tracks(self.usb_root, set_name, bank_number)
        self.assertEqual(tracks["A"].display_name, "Song")

    def test_swapping_two_empty_slots_does_nothing(self):
        set_name, bank_number = self._make_set_with_bank()
        library_ops.swap_tracks(self.usb_root, set_name, bank_number, "A", "B")
        tracks = library_ops.list_tracks(self.usb_root, set_name, bank_number)
        self.assertEqual(tracks, {"A": None, "B": None, "C": None})


class TestDeleteTrack(LibraryOpsTestCase):
    def test_delete_removes_the_file(self):
        set_name, bank_number = self._make_set_with_bank()
        library_ops.assign_track(self.usb_root, set_name, bank_number, "A", "Song", "mp3", io.BytesIO(b"data"))

        library_ops.delete_track(self.usb_root, set_name, bank_number, "A")

        tracks = library_ops.list_tracks(self.usb_root, set_name, bank_number)
        self.assertIsNone(tracks["A"])

    def test_deleting_already_empty_slot_does_not_raise(self):
        set_name, bank_number = self._make_set_with_bank()
        library_ops.delete_track(self.usb_root, set_name, bank_number, "A")  # should not raise


class TestSongLibrary(LibraryOpsTestCase):
    def test_upload_song_creates_file_in_songs_folder(self):
        library_ops.upload_song(self.usb_root, "My Song", "mp4", io.BytesIO(b"video bytes"))

        songs_path = os.path.join(self.usb_root, "_Songs")
        self.assertEqual(os.listdir(songs_path), ["My Song.mp4"])
        with open(os.path.join(songs_path, "My Song.mp4"), "rb") as f:
            self.assertEqual(f.read(), b"video bytes")

    def test_upload_song_rejects_duplicate_name(self):
        library_ops.upload_song(self.usb_root, "Song", "mp3", io.BytesIO(b"a"))

        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.upload_song(self.usb_root, "Song", "mp3", io.BytesIO(b"b"))

    def test_upload_song_duplicate_raises_the_specific_already_exists_subclass(self):
        """api.py catches this specific type (not just LibraryOpsError
        generically) to offer "replace it?" instead of just failing."""
        library_ops.upload_song(self.usb_root, "Song", "mp3", io.BytesIO(b"a"))

        with self.assertRaises(library_ops.SongAlreadyExistsError):
            library_ops.upload_song(self.usb_root, "Song", "mp3", io.BytesIO(b"b"))

    def test_upload_song_with_overwrite_replaces_existing_content(self):
        library_ops.upload_song(self.usb_root, "Song", "mp3", io.BytesIO(b"original"))

        library_ops.upload_song(self.usb_root, "Song", "mp3", io.BytesIO(b"replaced"), overwrite=True)

        with open(os.path.join(self.usb_root, "_Songs", "Song.mp3"), "rb") as f:
            self.assertEqual(f.read(), b"replaced")
        self.assertEqual(len(library_ops.list_songs(self.usb_root)), 1)

    def test_list_songs_returns_uploaded_songs_sorted(self):
        library_ops.upload_song(self.usb_root, "Zeta", "mp3", io.BytesIO(b"a"))
        library_ops.upload_song(self.usb_root, "Alpha", "wav", io.BytesIO(b"b"))

        songs = library_ops.list_songs(self.usb_root)

        self.assertEqual([s.filename for s in songs], ["Alpha.wav", "Zeta.mp3"])

    def test_list_songs_on_missing_folder_returns_empty(self):
        self.assertEqual(library_ops.list_songs(self.usb_root), [])

    def test_rename_song(self):
        library_ops.upload_song(self.usb_root, "Old Name", "mp3", io.BytesIO(b"a"))

        library_ops.rename_song(self.usb_root, "Old Name.mp3", "New Name")

        songs = library_ops.list_songs(self.usb_root)
        self.assertEqual([s.filename for s in songs], ["New Name.mp3"])

    def test_rename_song_rejects_collision_with_existing_song(self):
        library_ops.upload_song(self.usb_root, "First", "mp3", io.BytesIO(b"a"))
        library_ops.upload_song(self.usb_root, "Second", "mp3", io.BytesIO(b"b"))

        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.rename_song(self.usb_root, "First.mp3", "Second")

    def test_rename_song_already_deleted_by_hand_on_the_usb_raises_cleanly(self):
        # Real bug found on real hardware: a stale UI reference to a song
        # someone deleted directly on the USB (outside the app) used to
        # hit a raw, unhandled FileNotFoundError instead of a clean
        # LibraryOpsError.
        library_ops.upload_song(self.usb_root, "Song", "mp3", io.BytesIO(b"a"))
        os.remove(os.path.join(self.usb_root, "_Songs", "Song.mp3"))

        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.rename_song(self.usb_root, "Song.mp3", "New Name")

    def test_delete_song_removes_it(self):
        library_ops.upload_song(self.usb_root, "Song", "mp3", io.BytesIO(b"a"))

        library_ops.delete_song(self.usb_root, "Song.mp3")

        self.assertEqual(library_ops.list_songs(self.usb_root), [])

    def test_delete_song_already_deleted_by_hand_on_the_usb_raises_cleanly(self):
        library_ops.upload_song(self.usb_root, "Song", "mp3", io.BytesIO(b"a"))
        os.remove(os.path.join(self.usb_root, "_Songs", "Song.mp3"))

        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.delete_song(self.usb_root, "Song.mp3")

    def test_delete_song_does_not_touch_copies_already_assigned_to_sets(self):
        set_name, bank_number = self._make_set_with_bank()
        library_ops.assign_track(self.usb_root, set_name, bank_number, "A", "Song", "mp3", io.BytesIO(b"a"))

        library_ops.delete_song(self.usb_root, "Song.mp3")

        tracks = library_ops.list_tracks(self.usb_root, set_name, bank_number)
        self.assertIsNotNone(tracks["A"])

    def test_assigning_track_also_adds_it_to_the_library(self):
        set_name, bank_number = self._make_set_with_bank()

        library_ops.assign_track(self.usb_root, set_name, bank_number, "A", "New Song", "mp3", io.BytesIO(b"data"))

        songs = library_ops.list_songs(self.usb_root)
        self.assertEqual([s.filename for s in songs], ["New Song.mp3"])

    def test_assigning_track_does_not_clobber_an_existing_library_song_of_the_same_name(self):
        library_ops.upload_song(self.usb_root, "Song", "mp3", io.BytesIO(b"library version"))
        set_name, bank_number = self._make_set_with_bank()

        library_ops.assign_track(self.usb_root, set_name, bank_number, "A", "Song", "mp3", io.BytesIO(b"different bytes"))

        songs_path = os.path.join(self.usb_root, "_Songs")
        with open(os.path.join(songs_path, "Song.mp3"), "rb") as f:
            self.assertEqual(f.read(), b"library version")

    def test_assign_song_to_slot_copies_from_the_library(self):
        library_ops.upload_song(self.usb_root, "Song", "mp4", io.BytesIO(b"library bytes"))
        set_name, bank_number = self._make_set_with_bank()

        info = library_ops.assign_song_to_slot(self.usb_root, set_name, bank_number, "B", "Song.mp4")

        self.assertEqual(info.filename, "B - Song.mp4")
        bank_path = os.path.join(self.usb_root, set_name, f"Bank {bank_number}")
        with open(os.path.join(bank_path, "B - Song.mp4"), "rb") as f:
            self.assertEqual(f.read(), b"library bytes")
        # The library's own copy is untouched -- still there for reuse.
        songs = library_ops.list_songs(self.usb_root)
        self.assertEqual([s.filename for s in songs], ["Song.mp4"])

    def test_assign_song_to_slot_replaces_whatever_was_in_that_letter(self):
        library_ops.upload_song(self.usb_root, "New Song", "mp3", io.BytesIO(b"new"))
        set_name, bank_number = self._make_set_with_bank()
        library_ops.assign_track(self.usb_root, set_name, bank_number, "A", "Old Song", "mp3", io.BytesIO(b"old"))

        library_ops.assign_song_to_slot(self.usb_root, set_name, bank_number, "A", "New Song.mp3")

        bank_path = os.path.join(self.usb_root, set_name, f"Bank {bank_number}")
        self.assertEqual(os.listdir(bank_path), ["A - New Song.mp3"])

    def test_assign_song_to_slot_raises_for_unknown_song(self):
        set_name, bank_number = self._make_set_with_bank()

        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.assign_song_to_slot(self.usb_root, set_name, bank_number, "A", "Nonexistent.mp3")

    def test_save_track_to_library_copies_an_existing_assignment(self):
        set_name, bank_number = self._make_set_with_bank()
        library_ops.assign_track(self.usb_root, set_name, bank_number, "A", "Song", "mp3", io.BytesIO(b"data"))
        library_ops.delete_song(self.usb_root, "Song.mp3")  # undo the automatic add, to test this path in isolation

        library_ops.save_track_to_library(self.usb_root, set_name, bank_number, "A")

        songs = library_ops.list_songs(self.usb_root)
        self.assertEqual([s.filename for s in songs], ["Song.mp3"])

    def test_save_track_to_library_raises_for_empty_slot(self):
        set_name, bank_number = self._make_set_with_bank()

        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.save_track_to_library(self.usb_root, set_name, bank_number, "A")

    def test_save_track_to_library_rejects_collision(self):
        library_ops.upload_song(self.usb_root, "Song", "mp3", io.BytesIO(b"library version"))
        set_name, bank_number = self._make_set_with_bank()
        library_ops.assign_song_to_slot(self.usb_root, set_name, bank_number, "A", "Song.mp3")
        # Manually place a different file under the same assigned name to
        # simulate an out-of-band collision, without going through
        # assign_track()'s own auto-add (which would just no-op here).
        library_ops.delete_song(self.usb_root, "Song.mp3")
        library_ops.upload_song(self.usb_root, "Song", "mp3", io.BytesIO(b"a different song entirely"))

        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.save_track_to_library(self.usb_root, set_name, bank_number, "A")

    def test_songs_folder_is_excluded_from_list_sets(self):
        library_ops.upload_song(self.usb_root, "Song", "mp3", io.BytesIO(b"data"))

        result_sets = library_ops.list_sets(self.usb_root)

        self.assertEqual(result_sets, [])


class TestCleanupStaleTempFiles(LibraryOpsTestCase):
    # Real bug found on real hardware: unplugging a phone mid-upload
    # makes usb-tether-watchdog.service stop this service (SIGTERM) the
    # instant the tethered interface disappears, killing the upload
    # before its own except-block cleanup could run and leaving a
    # multi-megabyte ".part" file behind in _Songs/ forever.
    def test_removes_part_and_swaptmp_files_anywhere_under_root(self):
        set_name, bank_number = self._make_set_with_bank()
        bank_path = os.path.join(self.usb_root, set_name, f"Bank {bank_number}")
        songs_path = os.path.join(self.usb_root, "_Songs")
        os.makedirs(songs_path, exist_ok=True)
        stale_part = os.path.join(songs_path, "Interrupted Upload.mp4.part")
        stale_swaptmp = os.path.join(bank_path, "A - Song.mp3.swaptmp")
        with open(stale_part, "wb") as f:
            f.write(b"partial data")
        with open(stale_swaptmp, "wb") as f:
            f.write(b"partial data")

        removed = library_ops.cleanup_stale_temp_files(self.usb_root)

        self.assertEqual(removed, 2)
        self.assertFalse(os.path.exists(stale_part))
        self.assertFalse(os.path.exists(stale_swaptmp))

    def test_does_not_touch_real_files(self):
        set_name, bank_number = self._make_set_with_bank()
        library_ops.assign_track(
            self.usb_root, set_name, bank_number, "A", "Real Song", "mp3", io.BytesIO(b"real data"),
        )

        removed = library_ops.cleanup_stale_temp_files(self.usb_root)

        self.assertEqual(removed, 0)
        tracks = library_ops.list_tracks(self.usb_root, set_name, bank_number)
        self.assertEqual(tracks["A"].display_name, "Real Song")

    def test_on_a_clean_library_removes_nothing(self):
        set_name, bank_number = self._make_set_with_bank()

        removed = library_ops.cleanup_stale_temp_files(self.usb_root)

        self.assertEqual(removed, 0)


class TestStandbyVideo(LibraryOpsTestCase):
    def test_get_standby_info_when_none_set(self):
        info = library_ops.get_standby_info(self.usb_root)

        self.assertFalse(info.exists)
        self.assertEqual(info.size_bytes, 0)

    def test_set_standby_video_copies_from_the_library(self):
        library_ops.upload_song(self.usb_root, "My Loop", "mp4", io.BytesIO(b"video bytes"))

        library_ops.set_standby_video(self.usb_root, "My Loop.mp4")

        standby_path = os.path.join(self.usb_root, "standby.mp4")
        with open(standby_path, "rb") as f:
            self.assertEqual(f.read(), b"video bytes")
        # The library's own copy is untouched -- same "copy, not move" rule
        # as assign_song_to_slot().
        self.assertTrue(os.path.isfile(os.path.join(self.usb_root, "_Songs", "My Loop.mp4")))

    def test_set_standby_video_is_always_named_standby_mp4_regardless_of_source_extension(self):
        library_ops.upload_song(self.usb_root, "My Loop", "mov", io.BytesIO(b"mov bytes"))

        library_ops.set_standby_video(self.usb_root, "My Loop.mov")

        self.assertTrue(os.path.isfile(os.path.join(self.usb_root, "standby.mp4")))

    def test_set_standby_video_replaces_whatever_was_there(self):
        library_ops.upload_song(self.usb_root, "First", "mp4", io.BytesIO(b"first"))
        library_ops.upload_song(self.usb_root, "Second", "mp4", io.BytesIO(b"second"))
        library_ops.set_standby_video(self.usb_root, "First.mp4")

        library_ops.set_standby_video(self.usb_root, "Second.mp4")

        with open(os.path.join(self.usb_root, "standby.mp4"), "rb") as f:
            self.assertEqual(f.read(), b"second")

    def test_get_standby_info_after_set(self):
        library_ops.upload_song(self.usb_root, "My Loop", "mp4", io.BytesIO(b"video bytes"))
        library_ops.set_standby_video(self.usb_root, "My Loop.mp4")

        info = library_ops.get_standby_info(self.usb_root)

        self.assertTrue(info.exists)
        self.assertEqual(info.size_bytes, len(b"video bytes"))

    def test_set_standby_video_rejects_audio_only_song(self):
        library_ops.upload_song(self.usb_root, "Just Audio", "mp3", io.BytesIO(b"a"))

        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.set_standby_video(self.usb_root, "Just Audio.mp3")

    def test_set_standby_video_raises_for_unknown_song(self):
        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.set_standby_video(self.usb_root, "Does Not Exist.mp4")

    def test_set_standby_video_already_deleted_by_hand_on_the_usb_raises_cleanly(self):
        library_ops.upload_song(self.usb_root, "My Loop", "mp4", io.BytesIO(b"a"))
        os.remove(os.path.join(self.usb_root, "_Songs", "My Loop.mp4"))

        with self.assertRaises(library_ops.LibraryOpsError):
            library_ops.set_standby_video(self.usb_root, "My Loop.mp4")


if __name__ == "__main__":
    unittest.main()
