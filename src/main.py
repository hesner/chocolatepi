#!/usr/bin/env python3
"""
Real runtime entry point: wires the MIDI Adapter to the Mapper and the
Mapper to the Core, so every controller action actually drives audio/video
playback -- unlike live_test.py, which only prints what would happen.

Usage (on the Raspberry Pi):
    python3 src/main.py --usb-root /media/usb --standby /media/usb/standby.mp4 \
        --usb-uuid 07C1339846657D95

Ctrl+C to exit.
"""

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from adapter import MVaveAdapter, DeviceNotFoundError  # noqa: E402
from mapper import Mapper  # noqa: E402
from core import Library, Player, AudioPlayer, Core  # noqa: E402

# How often to retry connecting to the M-VAVE while it isn't found (at
# startup, or after a mid-session disconnect) -- see _run_midi_loop()'s
# docstring for why this no longer relies on systemd restarting the whole
# process for this specific, expected-to-happen case.
_MIDI_RETRY_INTERVAL_S = 3.0


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--usb-root",
        required=True,
        help="Path where the library USB drive is mounted (contains active_set.txt)",
    )
    parser.add_argument(
        "--standby",
        required=True,
        help="Path to the standby video (looped when nothing is playing)",
    )
    parser.add_argument(
        "--fallback-standby",
        default=os.path.expanduser("~/pedal-assets/fallback-standby.mp4"),
        help=(
            "Path to a local (non-USB) standby video, used automatically "
            "whenever --standby isn't currently reachable (library USB not "
            "inserted, or removed while running). Generate it with "
            "scripts/generate_fallback_standby.sh. "
            "(default: ~/pedal-assets/fallback-standby.mp4)"
        ),
    )
    parser.add_argument(
        "--usb-uuid",
        required=True,
        help=(
            "Filesystem UUID of the library USB drive (get it with "
            "`sudo blkid /dev/sda1`, or whatever device it shows up as -- "
            "the same UUID used in /etc/fstab, see systemd/README.md). Used "
            "to detect whether the USB is physically plugged in right now "
            "(checks /dev/disk/by-uuid/<this>) -- more reliable than "
            "checking --standby's path directly or its mount point, both of "
            "which can misreport presence (confirmed live, see the note on "
            "Player._usb_device_is_present() in src/core/player.py)."
        ),
    )
    parser.add_argument(
        "--drm-mode",
        default="preferred",
        help=(
            "Display refresh rate to drive the screen at (mpv's --drm-mode). "
            "Default 'preferred' (usually 60Hz) is the recommended choice: "
            "forcing the display's native mode to match the content's real "
            "frame rate (e.g. '1920x1080@25') was tested on the real show TV "
            "and made no measurable difference to frame drops or CPU usage, "
            "while looking visibly worse side by side (see TESTING.md). Left "
            "configurable in case a future display/content combination "
            "benefits where this one didn't -- run `mpv --drm-mode=help` on "
            "the Pi with the real screen connected to see what it supports. "
            "(default: preferred)"
        ),
    )
    parser.add_argument(
        "--log-file",
        default=os.path.expanduser("~/pedal-core.log"),
        help="Where to write the Core's log (default: ~/pedal-core.log)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(args.log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logger = logging.getLogger("main")

    mapper = Mapper(tracks_per_group=4)
    library = Library(usb_root=args.usb_root)
    player = Player(
        standby_path=args.standby,
        fallback_standby_path=args.fallback_standby,
        usb_uuid=args.usb_uuid,
        drm_mode=args.drm_mode,
    )
    audio_player = AudioPlayer()
    core = Core(library=library, player=player, audio_player=audio_player)
    core.start()

    try:
        _run_midi_loop(core, mapper, logger)
    except KeyboardInterrupt:
        logger.info("Exiting.")
    finally:
        core.stop()


def _run_midi_loop(core: Core, mapper: Mapper, logger: logging.Logger) -> None:
    """(Re)connects to the M-VAVE for as long as the process runs, without
    tearing Core/mpv down in between attempts -- a real, reproduced gap
    found during intensive real-hardware testing (TROUBLESHOOTING.md):
    the controller being off/disconnected at the exact moment this starts
    (or going quiet mid-session -- a loose cable, a USB hub glitch, the
    kind of brief dropout a real undervoltage event can cause, see
    TESTING.md) used to be treated as fatal. The whole process exited and
    depended entirely on systemd (`Restart=always`, `RestartSec=5`)
    blindly trying again -- which also killed and relaunched both mpv
    lanes every single cycle (visible as the screen flickering back to
    black) for as long as the controller stayed missing, with total
    silence (no footswitch can do anything with no process running) and
    zero on-screen indication of why. Retrying in-process instead means
    Core/mpv only ever start once; standby keeps looping solidly the
    whole time a reconnect is pending, and a footswitch press works again
    the instant the controller reappears -- confirmed live: powering the
    M-VAVE back on mid-session was picked up on the very next retry.

    Only a genuinely unexpected failure (anything that isn't "controller
    not currently reachable") still propagates up and lets the process
    exit -- systemd's restart stays as the fallback for that case, not
    the primary mechanism for this one anymore."""
    warned = False
    while True:
        try:
            with MVaveAdapter(port_name_pattern="SINCO") as adapter:
                logger.info("Connected to the controller. Listening for actions...")
                warned = False
                for channel, program in adapter.program_changes():
                    action = mapper.map_program_change(program)
                    logger.info("[channel %d] PC=%d -> %r", channel, program, action)
                    core.handle_action(action)
                # The generator above only returns (instead of blocking
                # forever) if the MIDI port itself closed out from under
                # it -- i.e. the controller went away mid-session, not a
                # normal way for this loop to end.
                logger.warning("MIDI connection closed -- retrying.")
        except DeviceNotFoundError as e:
            if not warned:
                logger.error("%s -- will keep retrying every %.0fs.", e, _MIDI_RETRY_INTERVAL_S)
                warned = True
        except OSError as e:
            # Defense-in-depth for a disconnect that surfaces as a lower-
            # level I/O error instead of the generator just ending (not
            # independently confirmed against real hardware which of the
            # two actually happens -- handling both is cheap insurance).
            logger.warning("MIDI connection lost (%s) -- retrying.", e)
            warned = False
        time.sleep(_MIDI_RETRY_INTERVAL_S)


if __name__ == "__main__":
    main()
