"""
Core routing-logic tests. Player/AudioPlayer/Library are all mocked --
no real mpv process, no real USB -- this is pure decision logic (which
lane a track goes to, when the video lane itself is started/stopped).

Real hardware concerns (mpv IPC, ALSA/dmix, DRM) stay covered by manual
checks (src/core_smoke_test.py, TESTING.md) rather than unit tests here,
same as this project's existing convention for player.py itself.

Run with: python -m unittest tests/test_core.py
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mapper import SelectTrack, Stop  # noqa: E402
from core.core import Core  # noqa: E402
from core.library import ResolvedTrack  # noqa: E402


def _video(path="video.mp4"):
    return ResolvedTrack(path=path, is_audio_only=False)


def _audio(path="song.mp3"):
    return ResolvedTrack(path=path, is_audio_only=True)


class CoreTestCase(unittest.TestCase):
    def setUp(self):
        self.library = MagicMock()
        self.player = MagicMock()
        self.audio_player = MagicMock()
        self.core = Core(library=self.library, player=self.player, audio_player=self.audio_player)


class TestStartStop(CoreTestCase):
    def test_start_does_not_start_the_video_lane(self):
        """Real user request (2026-10-03): the video lane costs a full
        CPU core and ~300MB RAM continuously just to loop standby --
        it's only started via set_display_connected(), driven by
        whoever's actually watching the hardware (main.py's
        DisplayMonitor), not unconditionally here."""
        self.core.start()

        self.player.start.assert_not_called()
        self.audio_player.start.assert_called_once()

    def test_stop_only_stops_the_video_lane_if_it_was_running(self):
        self.core.start()

        self.core.stop()

        self.player.stop.assert_not_called()  # never started -- nothing to stop
        self.audio_player.stop.assert_called_once()

    def test_stop_stops_the_video_lane_if_it_was_started(self):
        self.core.start()
        self.core.set_display_connected(True)

        self.core.stop()

        self.player.stop.assert_called_once()


class TestDisplayConnected(CoreTestCase):
    def test_connecting_starts_the_video_lane(self):
        self.core.set_display_connected(True)

        self.player.start.assert_called_once()

    def test_connecting_again_does_not_restart_an_already_running_lane(self):
        self.core.set_display_connected(True)

        self.core.set_display_connected(True)

        self.player.start.assert_called_once()

    def test_disconnecting_while_idle_stops_the_video_lane(self):
        self.core.set_display_connected(True)

        self.core.set_display_connected(False)

        self.player.stop.assert_called_once()

    def test_disconnecting_when_never_connected_does_not_call_stop(self):
        self.core.set_display_connected(False)

        self.player.stop.assert_not_called()

    def test_disconnecting_mid_video_clip_defers_stopping_the_lane(self):
        """The video lane's mpv process provides this clip's audio too
        -- stopping it immediately would cut the audio, not just the
        picture. Real user request (2026-10-03): never interrupt
        what's already playing."""
        self.library.resolve.return_value = _video()
        self.core.set_display_connected(True)
        self.core.handle_action(SelectTrack(setlist=1, track=1))

        self.core.set_display_connected(False)

        self.player.stop.assert_not_called()

    def test_deferred_stop_happens_when_the_clip_finishes_on_its_own(self):
        self.library.resolve.return_value = _video()
        self.core.set_display_connected(True)
        self.core.handle_action(SelectTrack(setlist=1, track=1))
        self.core.set_display_connected(False)

        self.core._on_video_clip_finished()

        self.player.stop.assert_called_once()

    def test_deferred_stop_happens_on_stop_button(self):
        self.library.resolve.return_value = _video()
        self.core.set_display_connected(True)
        self.core.handle_action(SelectTrack(setlist=1, track=1))
        self.core.set_display_connected(False)

        self.core.handle_action(Stop())

        self.player.stop.assert_called_once()

    def test_reconnecting_before_the_clip_ends_cancels_the_deferred_stop(self):
        self.library.resolve.return_value = _video()
        self.core.set_display_connected(True)
        self.core.handle_action(SelectTrack(setlist=1, track=1))
        self.core.set_display_connected(False)

        self.core.set_display_connected(True)
        self.core._on_video_clip_finished()

        self.player.stop.assert_not_called()

    def test_disconnecting_during_audio_only_playback_stops_the_lane_immediately(self):
        """Nothing audible comes from the video lane while an
        audio-only track is playing (it's just looping muted standby
        in the background) -- safe to stop it right away, no clip
        audio at risk."""
        self.library.resolve.return_value = _audio()
        self.core.set_display_connected(True)
        self.core.handle_action(SelectTrack(setlist=1, track=1))

        self.core.set_display_connected(False)

        self.player.stop.assert_called_once()


class TestSelectTrackRouting(CoreTestCase):
    def test_video_track_with_display_connected_plays_on_the_video_lane(self):
        self.library.resolve.return_value = _video("clip.mp4")
        self.core.set_display_connected(True)

        self.core.handle_action(SelectTrack(setlist=1, track=1))

        self.player.play.assert_called_once_with("clip.mp4")
        self.audio_player.play.assert_not_called()

    def test_video_track_with_no_display_plays_audio_only(self):
        """Real user request (2026-10-03): with no display connected,
        the whole system still works -- a video track just plays its
        audio, same lane as a real audio-only track, instead of doing
        nothing."""
        self.library.resolve.return_value = _video("clip.mp4")

        self.core.handle_action(SelectTrack(setlist=1, track=1))

        self.audio_player.play.assert_called_once_with("clip.mp4")
        self.player.play.assert_not_called()

    def test_video_track_with_no_display_does_not_touch_the_stopped_video_lane(self):
        self.library.resolve.return_value = _video("clip.mp4")

        self.core.handle_action(SelectTrack(setlist=1, track=1))

        self.player.go_to_standby.assert_not_called()

    def test_audio_only_track_with_display_connected_still_shows_muted_standby(self):
        self.library.resolve.return_value = _audio("song.mp3")
        self.core.set_display_connected(True)

        self.core.handle_action(SelectTrack(setlist=1, track=1))

        self.player.go_to_standby.assert_called_once()
        self.audio_player.play.assert_called_once_with("song.mp3")

    def test_unknown_slot_is_ignored(self):
        self.library.resolve.return_value = None

        self.core.handle_action(SelectTrack(setlist=9, track=9))

        self.player.play.assert_not_called()
        self.audio_player.play.assert_not_called()

    def test_stop_with_no_display_does_not_touch_the_stopped_video_lane(self):
        self.core.handle_action(Stop())

        self.player.go_to_standby.assert_not_called()
        self.audio_player.silence.assert_called_once()


if __name__ == "__main__":
    unittest.main()
