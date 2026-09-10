# Rebuild runbook (for an AI coding agent)

*[Leer en español](docs/es/REBUILD.md)*

A cold-start, execution-order runbook for reproducing this project's
full working state -- source checkout, a Raspberry Pi flashed and
configured, the pedal running as an auto-booting appliance -- on a new
PC and a new Raspberry Pi, with no access to the conversation history
that originally built it.

**This is a sequencer, not a duplicate of the real docs.** Each phase
says what to do and which file has the actual how/why; read that file
before acting, don't guess from this summary alone. If a phase's
outcome doesn't match its checkpoint, stop and diagnose before
continuing -- see `TROUBLESHOOTING.md`.

## Before starting

Confirm you actually have:

- A Raspberry Pi (this project targets a **Pi 2**; other models should
  work but are unvalidated -- note that explicitly if used).
- A blank microSD card (8GB+), a way to write it (this runbook assumes
  Raspberry Pi Imager on the PC you're working from).
- A USB MIDI foot controller. If it's not an M-VAVE PD41, you do not
  have a validated Adapter yet -- see "If the controller isn't an
  M-VAVE PD41" below before assuming `src/adapter/mvave_adapter.py`
  applies.
- A class-compliant USB audio interface (validated against a Behringer
  U-PHORIA UM2; any class-compliant interface should work, per
  `MASTER_SPECIFICATION.md` section 2).
- A USB drive for the library (any filesystem `mount` supports on
  Linux; this project's own reference deployment uses NTFS, hence
  `ntfs-3g` below -- substitute the right driver for yours).
- An HDMI display.
- Network access to the Pi (Ethernet strongly preferred for setup --
  this project hit real, repeated WiFi/mDNS flakiness during its own
  development; see `TROUBLESHOOTING.md`).
- Shell/SSH access from the working PC, and enough permission to run
  `sudo` on the Pi.

Do not proceed past a phase whose checkpoint fails. Do not skip a
phase because it "should" be fine -- every gotcha named in
`TROUBLESHOOTING.md` was a real failure this project hit once already.

## Phase 1 -- Get the source

```
git clone https://github.com/hesner/chocolatepi
cd chocolatepi
python3 -m unittest discover -s tests -v
```

**Checkpoint**: 27 tests pass, no hardware involved. If this fails, stop
-- nothing past this point can be trusted until the base code itself is
verified sound on this machine.

Read `MASTER_SPECIFICATION.md` sections 1-4 now (sections 5-9 are about
the original AI-assisted development process, not needed to rebuild).
This is the actual decision record -- don't take this runbook's
paraphrasing of "why" as a substitute for it.

## Phase 2 -- Flash the Pi and get SSH access

Follow `systemd/README.md` section 0 exactly (OS image choice,
Imager's advanced options for hostname/SSH/user/WiFi). Pick a hostname
and remember it -- this runbook uses `pedal` for its own examples, same
as the rest of this repo's docs, but any value works as long as you
substitute consistently.

**Checkpoint**: `ssh <user>@<hostname>.local` (or by IP, if `.local`
doesn't resolve -- expected sometimes, see `TROUBLESHOOTING.md`) gets a
shell.

## Phase 3 -- Install software prerequisites

Follow `systemd/README.md` section 1.

**Checkpoint**: `mpv --version`, `ffmpeg -version`, and (if using NTFS)
`mount.ntfs-3g --version` all succeed.

## Phase 4 -- Set up the library USB

1. Format/prepare the drive with the structure `LIBRARY.md` describes
   (`active_show.txt`, at least one `<Show Name>/Set 1/` with a test
   track in it -- follow `LIBRARY.md`'s naming pattern exactly, the
   single-space-around-the-dash rule especially).
2. Get its UUID: `sudo blkid /dev/sda1` (or whatever device it enumerates
   as -- `lsblk` first if unsure).
3. Follow `systemd/README.md` section 2 to add the `/etc/fstab` line
   with that UUID.

**Checkpoint**: `sudo mount -a && mount | grep /media/usb` shows it
mounted `ro`.

## Phase 5 -- Adapt the code to this specific deployment

Two files need this Pi's/drive's real values, not the repo's own
reference-deployment placeholders:

- `systemd/pedal-core.service`: replace `<YOUR_USER>` and
  `<YOUR_USB_UUID>` (see `systemd/README.md` section 3 for exactly
  where and why).
- Confirm `src/main.py --usb-uuid` in that same `ExecStart=` line
  matches the UUID from Phase 4.

**If the controller isn't an M-VAVE PD41**: stop here and do not write
a new `Adapter` by guessing. `MAVAVE_ANALYSIS.md` is not just a spec for
the PD41 -- it's a worked example of the *methodology* (available MIDI
modes, Program Change range/behavior, empirical validation against real
hardware, the correction that caught a wrong assumption -- 8 groups, not
32) for characterizing an unknown controller before writing an Adapter
for it. Repeat that methodology against the real device first. A new
Adapter must still only ever emit what `src/mapper/mapper.py` already
expects (`SelectTrack`, `Stop`) -- see `CONTRIBUTING.md`'s
Adapter/Mapper/Core boundary rule before touching anything outside
`src/adapter/`.

## Phase 6 -- Install and start the service

Follow `systemd/README.md` section 3.

**Checkpoint**: `sudo systemctl status pedal-core` shows `active
(running)`; the standby video is visible over HDMI; `journalctl -u
pedal-core -f` shows `Core started, standby playing.` and `Connected to
the controller. Listening for actions...` with no repeated
crash/restart loop.

## Phase 7 -- Full functional validation

Don't consider this done until every one of these has actually been
observed, not assumed:

1. **Each of the controller's footswitches** triggers the right
   track/action (confirm against your own Set folder's actual content,
   not just that *something* plays).
2. **STOP** works instantly from any state.
3. **Video and audio-only tracks** both play correctly (an `.mp3`/`.wav`
   should keep the standby looping under it; a video should replace it).
4. **Unplug the library USB, reboot**: the local fallback standby plays
   ("Please insert the USB..."), not emergency mode. If you get
   emergency mode, you have not yet done Phase 8's `recurse=0` step --
   do not skip ahead to Phase 8 and consider it optional, this
   checkpoint is what it exists to fix.
5. **Replug the USB, reboot**: real content plays again.
6. **Pull power abruptly** (no clean shutdown) at least once while
   idle, and once mid-playback, then power back on: boots clean, no
   filesystem errors. Do this test *before* Phase 8 too (the SD card
   isn't protected yet at that point) so you have a baseline, then again
   after, to actually confirm the overlay is what's protecting it.

## Phase 8 -- Lock it down (read-only root, last step on purpose)

Follow `systemd/README.md` section 4 -- **including the `recurse=0`
step**, not just enabling the overlay. This is not optional polish: the
default (`recurse=1`) wraps `/media/usb` in an overlay with no
`nofail`, which breaks Phase 7's checkpoint 4 (missing-USB boot drops
into unrecoverable emergency mode instead of the standby fallback).

**Checkpoint**: re-run Phase 7 checkpoints 4-6 again now that the
overlay is active, to confirm the lock-down didn't silently break any
of them.

## Done

At this point the rebuild matches this project's own validated
reference state. Keep `LIBRARY.md` on hand for day-to-day content
management (it is not a one-time setup doc, it governs every future
edit to the library USB) and `TROUBLESHOOTING.md` for anything that
doesn't match a checkpoint above.
