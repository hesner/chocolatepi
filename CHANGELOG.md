# Changelog

*[Leer en español](docs/es/CHANGELOG.md)*

Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project doesn't use version numbers yet -- it's a single dedicated
appliance build, not a versioned library -- so entries are grouped by
date instead until that changes.

## [Unreleased]

- Added a shared song library (`_Songs/` at the USB root) to both
  `setlist-admin` expansions, so a song only needs to be uploaded once
  and can be reused across any number of setlists instead of
  re-uploading it into every new show. Documented as a base-project
  convention in `LIBRARY.md` (en/es) -- works by hand over SSH too, not
  just through either app -- with an explicit warning not to delete
  songs from it, since doing so only removes them from future picking,
  never from a Set they're already assigned to (that's always an
  independent copy). `library_ops.py`'s new functions
  (`list_songs`/`upload_song`/`rename_song`/`delete_song`/
  `assign_song_to_slot`/`save_track_to_library`) are identical between
  the two expansions. `scripts/rollback.sh` gained a separate
  `--purge-library` flag (distinct from `--purge`, which only ever
  touched the small PIN/credentials file) since deleting actual song
  files is a bigger, more deliberate action. Also fixed two real,
  pre-existing bugs found while building this (present since the
  original WiFi design, unrelated to the song library itself):
  `library_ops.LibraryOpsError` was never translated into a proper HTTP
  response (fell through to a generic 500 "Internal error" instead of
  the 400 with a helpful message it should have been), and URL path
  segments (show names, now also song filenames) were never
  percent-decoded server-side despite the frontend percent-encoding
  them, so any name actually needing encoding (any space or accented
  character) silently failed.
- Introduced `expansions/`: a top-level home for optional, independently
  installable/removable addons to the base pedal system -- moved
  `setlist-admin` (USB-tether design) into `expansions/setlist-admin-usb/`
  as the first one, fully self-contained (its own `src/`, `systemd/`,
  `scripts/install.sh`+`rollback.sh`, `tests/`, docs), so installing or
  rolling it back can never collaterally affect the base project or any
  other expansion. See `expansions/README.md` for the model. The earlier
  WiFi-based attempt, previously only living on the `explore/setlist-admin`
  branch, was brought onto `main` too as a second, equally independent
  expansion (`expansions/setlist-admin-wifi/`) -- still paused on its
  dead USB WiFi dongle blocker, not installed by default, but now visible
  in the same checkout instead of requiring a branch switch to see.
- Added `setlist-admin` (USB-tether design): a second attempt at the
  companion web app for managing the library USB (shows/Sets/tracks,
  full CRUD) from a phone's browser, this time reachable by plugging
  the phone into the Pi with a USB cable (Android USB tethering or
  iPhone Personal Hotspot over cable) instead of the Pi needing its own
  WiFi radio -- see `expansions/setlist-admin-usb/SPECIFICATION.md` for
  the design and why (the earlier WiFi-based attempt is paused on a
  dead USB WiFi dongle, not this feature's fault). Reuses that design's
  CRUD backend and frontend UX
  unchanged (`library_ops.py`, `usb_mount.py` including its `ntfs-3g`
  fix, `auth.py`, the CRUD screens) so the two stay convergeable later.
  A phone is identified by its USB network driver name
  (`rndis_host`/`cdc_ether`/`cdc_ncm` for Android, `ipheth` for
  iPhone), not by IP range, so a permanently-attached Ethernet cable
  never spuriously starts the admin server. No WiFi credential storage,
  no NetworkManager profile juggling -- that whole layer is gone.
  Applying a setlist change still requires a reboot (this project
  already tried and abandoned a live-reload mechanism once, see below
  in this same file); the app adds a "Reboot now to apply" button so
  that doesn't need SSH. Not yet validated on real hardware.
- Designed and implemented `setlist-admin` (a companion web app for
  managing the library USB and the Pi's WiFi from a phone/computer
  browser), then reverted it from `main`: real-hardware validation
  (`SETLIST_ADMIN_SPECIFICATION.md` section 8a) went cleanly through
  install and the watchdog's dry-run/live stages, but then the USB WiFi
  dongle (Realtek rtl8192cu) turned out to be failing hardware --
  confirmed by testing it on a separate computer, where it didn't
  enumerate as any USB device at all. Since the whole feature depends
  on a working WiFi adapter, further testing is blocked until there's a
  known-good one. The full design, implementation, tests, and a real
  bug found along the way (`ntfs-3g` doesn't support `mount -o
  remount,rw` -- fixed to a real umount+mount cycle) are preserved on
  the `explore/setlist-admin` branch for a future attempt with an
  alternative design.
- Added `REBUILD.md` (en/es): execution-order runbook for reproducing
  this project on a new PC + new Raspberry Pi, written for an AI coding
  agent working cold, without conversation history.
- Added `TROUBLESHOOTING.md` (en/es): symptom-indexed reference of every
  real failure this project hit during development/testing.
- `systemd/README.md` (en/es): added a "can a human actually do this
  alone" review chapter (walked the guide as a non-programmer musician
  would), which found and fixed several real gaps -- `git`/cloning the
  repo onto the Pi was never mentioned, no SSH-client guidance, no
  text-editor (`nano`) instructions for the two files that need manual
  edits, and the power supply requirement was only documented reactively
  (after the fact in `TESTING.md`) instead of as an upfront requirement
  (now also in `README.md`'s hardware list).
- Fixed a real EN/ES content gap in `TESTING.md`: the Spanish version
  was missing the section that closes out test 4.0 (the real-TV
  frame-rate follow-up), leaving a Spanish-only reader thinking it was
  still open when it had already been resolved.
- **Fixed**: booting without the library USB dropped into systemd
  emergency mode (no SSH, unrecoverable on a headless appliance) instead
  of the local standby fallback. Cause: the overlay filesystem's default
  `recurse=1` wraps every mount (including `/media/usb`) in its own
  overlay with no `nofail`, so a missing USB failed a boot-critical mount.
  Fixed by setting `recurse=0` (root only) in `cmdline.txt` -- see
  `systemd/README.md` section 4.
- Added `LIBRARY.md` (en/es): how to name library USB folders/files, and
  the exact filename-spacing mistake (`A  - x.mov` vs `A - x.mov`) that
  fails completely silently -- found live while testing a Set 5 video
  that didn't play.
- Project renamed from "Sequence Pedal" / "Pedal de Secuencias" to
  **Chocolate Pi** -- a proper product name (playing on the M-VAVE
  Chocolate foot controller + Raspberry Pi actually used) instead of a
  literal description. Repo, badges, and docs updated to match; GitHub
  redirects the old repo URL automatically.

## 2026-09-05 -- Initial public release

First open-source release. Actively used and validated against real
hardware (Raspberry Pi 2, Behringer U-PHORIA UM2 USB audio interface,
M-VAVE PD41 MIDI controller, library USB drive).

- Layered architecture (Adapter → Mapper → Core) so controller-specific
  code never leaks into playback logic.
- `Adapter` validated against an M-VAVE PD41 in Program Change A mode
  (see `MAVAVE_ANALYSIS.md` for the empirical mapping and its
  correction: 8 groups, not 32).
- `Core`: library resolution from a USB drive, `mpv`-driven video with a
  standby loop, a dedicated audio-only lane for standalone tracks, and
  audio always prioritized over video.
- Local fallback standby video for when the library USB isn't present at
  boot.
- `systemd` auto-boot service; USB presence checked once at boot only
  (no live hot-swap -- a reboot is required to pick up library changes).
- Read-only root filesystem (Raspberry Pi OS overlay) so the Pi can be
  power-cycled at any moment without filesystem corruption risk.
- MIT license, bilingual documentation (English primary, Spanish under
  `docs/es/`), GitHub Sponsors.
