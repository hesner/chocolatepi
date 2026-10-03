"""
Core: the layer that owns audio/video playback (section 3 of
MASTER_SPECIFICATION.md). Only knows abstract actions (SelectTrack, Stop)
-- never a Program Change number, a MIDI channel, or any concept from the
physical controller.

Owns both playback lanes (see player.py) and decides which one a given
track goes to, based on Library.resolve()'s is_audio_only classification:
video clips replace what's on screen; audio-only tracks play over the
video lane, which is put on standby first if it wasn't already there.

Real user request (2026-10-03), after measuring it live: the video
lane's mpv process costs a full CPU core and ~300MB RAM continuously
just to loop standby, whether a display is attached or not. Core now
only runs that lane while a display is actually connected --
set_display_connected() is called by whoever's watching the hardware
(main.py wires a DisplayMonitor, see display_monitor.py), including
once at startup with the real boot-time state. A video track selected
with no display connected plays audio-only instead (through the same
audio-only lane as a real audio-only track) -- the whole system still
works, there's just nothing to show. Deliberately never interrupts
whatever's already playing: connecting/disconnecting the display only
ever changes what happens starting with the *next* track selection (or
immediately, for standby/idle) -- see set_display_connected()'s own
docstring for why a live mid-clip handoff between lanes was rejected.
"""

import logging
from typing import Optional, Tuple

from mapper import SelectTrack, Stop

from .library import Library
from .player import Player, AudioPlayer

logger = logging.getLogger(__name__)


class Core:
    def __init__(self, library: Library, player: Player, audio_player: AudioPlayer):
        self.library = library
        self.player = player
        self.audio_player = audio_player
        self._current: Optional[Tuple[int, int]] = None
        self.player.on_clip_finished = self._on_video_clip_finished
        self.audio_player.on_end_file = self._on_audio_end_file
        # Real user request (2026-10-03): the video lane is no longer
        # started unconditionally in start() below -- it's only ever
        # started/stopped via set_display_connected(), which main.py's
        # DisplayMonitor calls once at startup with the real boot-time
        # state (so this starts False here only as a placeholder; it
        # never stays False past that first call in practice).
        self._display_connected = False
        self._video_lane_running = False
        # True only while a real video clip (not standby) is loaded on
        # the video lane -- distinguishes "safe to stop the video lane
        # right now" (standby/idle -- nothing audible comes from it)
        # from "would cut this clip's own audio too" (a real clip is
        # mid-playback, and the *same* mpv process provides both).
        self._video_clip_playing = False
        self._lane_stop_deferred = False

    def start(self):
        self.audio_player.start()
        logger.info("Core started.")

    def stop(self):
        if self._video_lane_running:
            self.player.stop()
        self.audio_player.stop()

    def set_display_connected(self, connected: bool):
        """Called by whoever is watching the hardware (main.py wires a
        DisplayMonitor) on every confirmed connect/disconnect,
        including once at startup with the real boot-time state.

        Deliberately never interrupts whatever's already playing: a
        video clip already playing through the video lane when the
        display disconnects keeps playing there, audio and all, until
        it ends on its own or STOP is pressed (see _lane_stop_deferred
        below) -- only standby/idle state is affected immediately. A
        live mid-clip handoff between lanes (so a clip started
        audio-only could start showing video the instant a display is
        plugged in mid-clip) was considered and deliberately rejected:
        it would need to sync playback position between two
        independent mpv processes in real time, with real risk of the
        exact audio click/glitch this project has otherwise gone to
        real lengths to avoid (see player.py's module docstring). The
        *next* track selected after this call always reflects the
        current connection state."""
        self._display_connected = connected
        if connected:
            self._lane_stop_deferred = False
            if not self._video_lane_running:
                self.player.start()
                self._video_lane_running = True
                logger.info("Display connected -- video lane started, standby playing.")
        else:
            logger.info("Display disconnected.")
            if self._video_clip_playing:
                self._lane_stop_deferred = True
            else:
                self._stop_video_lane()

    def _stop_video_lane(self):
        if self._video_lane_running:
            self.player.stop()
            self._video_lane_running = False
            logger.info("Video lane stopped (no display connected).")
        self._lane_stop_deferred = False

    def handle_action(self, action):
        if isinstance(action, Stop):
            self._go_to_standby()
        elif isinstance(action, SelectTrack):
            self._select_track(action.setlist, action.track)
        else:
            logger.warning("Unknown action received: %r", action)

    def _select_track(self, setlist: int, track: int):
        resolved = self.library.resolve(setlist, track)
        if resolved is None:
            logger.warning(
                "SelectTrack(setlist=%d, track=%d) has no matching file "
                "-- ignoring (empty slot, or missing Set/Bank)",
                setlist, track,
            )
            return

        if resolved.is_audio_only or not self._display_connected:
            if resolved.is_audio_only:
                # Real bug found live (2026-10-03): this unconditionally
                # said "standby video keeps looping" even with no
                # display connected at all (and so no video lane
                # running to loop anything) -- misleading, not just
                # cosmetic, when reading the log to diagnose a real
                # display issue.
                looping_note = (
                    "standby video keeps looping" if self._video_lane_running
                    else "no display connected, nothing to show"
                )
                logger.info(
                    "Playing audio-only setlist=%d track=%d -> %s (%s)",
                    setlist, track, resolved.path, looping_note,
                )
            else:
                logger.info(
                    "Playing video setlist=%d track=%d -> %s as audio-only "
                    "(no display connected)", setlist, track, resolved.path,
                )
            if self._video_lane_running:
                self.player.go_to_standby()
            self.audio_player.play(resolved.path)
            self._video_clip_playing = False
        else:
            logger.info(
                "Playing video setlist=%d track=%d -> %s", setlist, track, resolved.path
            )
            self.audio_player.silence()
            self.player.play(resolved.path)
            self._video_clip_playing = True

        self._current = (setlist, track)

    def _go_to_standby(self):
        logger.info("STOP -- returning to standby.")
        if self._video_lane_running:
            self.player.go_to_standby()
        self.audio_player.silence()
        self._current = None
        self._video_clip_playing = False
        if self._lane_stop_deferred:
            self._stop_video_lane()

    def _on_video_clip_finished(self):
        """Called from the video lane's listener thread when a real clip
        finishes playing on its own. By this point the Player has already
        transitioned to standby itself (it queues standby right behind
        every clip precisely so this doesn't require a fresh command from
        here -- see Player.play()) -- so all that's left is clearing our
        own "currently selected" bookkeeping, and finally honoring a
        display-disconnect that arrived mid-clip, if any."""
        logger.info("Video clip finished on its own -- back to standby.")
        self._current = None
        self._video_clip_playing = False
        if self._lane_stop_deferred:
            self._stop_video_lane()

    def _on_audio_end_file(self, reason: str):
        """Same idea for the audio-only lane: when a standalone MP3/WAV
        finishes on its own, there's nothing to visually return to
        standby (the video lane never left it) -- just clear the
        "currently selected" state."""
        if reason == "eof" and self._current is not None:
            logger.info("Audio-only track finished on its own.")
            self._current = None
