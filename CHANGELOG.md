# Changelog

*[Leer en español](docs/es/CHANGELOG.md)*

Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Versioning

This project uses **date-based version numbers** (`vYYYY.MM.DD`), not
semantic versioning -- there is no compatibility contract between
versions to track (it's a single dedicated appliance build deployed to
one Pi, not a versioned library with multiple independent consumers).
A version is just "the state of this component as of this date,"
matching the date-grouped structure this changelog already used before
versioning was introduced.

Each independently-installable component tracks its **own** version, in
its own `VERSION` file, bumped whenever a meaningful change to it lands
on `main`:

- [`VERSION`](VERSION) -- the base pedal system (`src/`, `systemd/`,
  root docs).
- [`expansions/setlist-admin-usb/VERSION`](expansions/setlist-admin-usb/VERSION)
- [`expansions/setlist-admin-wifi/VERSION`](expansions/setlist-admin-wifi/VERSION)

**To check what's actually deployed on the real Pi**: `ssh -4 pedal
"cat ~/chocolatepi-repo/VERSION ~/chocolatepi-repo/expansions/*/VERSION"`
(compare against the git commit it's checked out to, since a `VERSION`
file only changes when someone remembers to bump it -- the commit hash
is always the ultimate source of truth; the version number exists to
give a human a memorable string to reference instead of a hash).

This changelog stays the source of truth for *what* changed and *why*;
`[Unreleased]` collects changes not yet cut into a dated version below
it. Cutting a version means: confirm the change actually works
end-to-end (real hardware for anything touching it, not just unit
tests), bump the affected component(s)' `VERSION` file(s), and rename
`[Unreleased]` to that date -- reopening a fresh empty `[Unreleased]`
above it for whatever comes next.

## [Unreleased]

## [v2026.10.01] -- MIDI-disconnect resilience, standby video management

- **Reverted same day**: this version briefly logged `mpv`'s own
  `stderr` into `pedal-core.log` (see the next bullet for why it was
  added) -- rolled back a few hours later. Reasoning: `pedal-core.log`
  lives under `/home/`, which under the normal, protective root overlay
  is RAM-backed (`tmpfs`), not disk -- and nothing rotates it. Checked on
  the real Pi: the overlay's effective cap is ~461MB (half of this Pi's
  921MB RAM, `tmpfs`'s own default sizing), with **no rotation on any of
  this project's three long-running logs** (`pedal-core.log`,
  `setlist-admin.log`, `usb-tether-watchdog.log`). Unbounded log growth
  on an appliance meant to run indefinitely without a reboot is a real
  RAM-exhaustion risk, not just a disk-space one. A log that only earns
  its keep during an active debugging session isn't worth that standing
  cost left on permanently -- `core/player.py` is back to sending both
  `mpv` lanes' `stdout`/`stderr` to `DEVNULL`. If a future investigation
  genuinely needs `mpv`'s own error output, capture it temporarily for
  that session (e.g. patch `stderr=subprocess.PIPE` and tail it live
  over SSH) rather than leaving it logged permanently.
  `TROUBLESHOOTING.md`'s "Audio (and video) stop completely..." entry
  reflects the final (reverted) state.
- **Fixed**: a real, reproduced incident -- the M-VAVE being off or
  disconnected (at startup, or mid-session: a loose cable, a USB hub
  glitch, the kind of brief dropout a real undervoltage event can cause,
  see TESTING.md) used to be treated as fatal by `src/main.py`: the
  whole process exited and depended entirely on `systemd` blindly
  restarting it every `RestartSec=5`, which also killed and relaunched
  both `mpv` lanes every single cycle (visible as the screen flickering
  back to black) for as long as the controller stayed missing -- total
  silence, no footswitch could do anything, and nothing on screen
  indicated why. `main.py` now retries the MIDI connection in-process,
  without tearing Core/`mpv` down in between attempts: standby keeps
  looping solidly the whole time a reconnect is pending, and a
  footswitch press works again the instant the controller reappears.
  Confirmed live: powering the M-VAVE back on mid-session was picked up
  on the very next retry (a few seconds later), no reboot needed.
- Both the MIDI fix above and the `mpv`-`stderr`-logging attempt (first
  bullet, reverted the same day) came out of investigating a real
  report of audio stopping entirely after about an hour of intensive
  real-hardware testing -- see `TROUBLESHOOTING.md`'s new entry for the
  full writeup. The M-VAVE gap is the strongest confirmed lead; no
  direct log evidence of the Behringer itself losing power was found,
  since the relevant boot's logs didn't survive a reboot.
- Added **standby video management** to both `setlist-admin` expansions:
  a new "Standby video" panel shows what's currently looping
  (`standby.mp4`'s size/last-changed time) and lets you pick any video
  already in the shared song library (`_Songs/`) to become the new one.
  To use a brand new file: upload it to the library first (already
  supported), then choose it here -- reuses the existing upload/rename/
  delete song-library UI rather than duplicating it, so "save it to the
  library, rename it, or delete it" all already work for standby
  candidates the same way they do for any other song. New
  `library_ops.set_standby_video()`/`get_standby_info()`, always writing
  the chosen file to the fixed `standby.mp4` name regardless of the
  source's own extension (mpv plays by sniffing content, not by
  filename, same as every other assignment in this app).

## [v2026.09.27] -- Set/Bank rename, real-hardware validation, Export Set, active-Set-on-reboot fix, power-loss documentation

- Renamed the library's terminology throughout the whole project (code,
  tests, and docs): the top-level folder, previously called a "Show", is
  now a **Set** (a group of Banks + songs usable in a single live
  performance); what was previously called a "Set" (the mid-level
  folder holding up to three `A`/`B`/`C` tracks) is now a **Bank**,
  matching the M-VAVE PD41's own bank/group terminology. Track letters
  (`A`/`B`/`C`) are unchanged. `active_show.txt` is now `active_set.txt`;
  folders go from `<Show Name>/Set N/` to `<Set Name>/Bank N/`. Both
  `setlist-admin` expansions' REST routes moved from `/api/shows` and
  `/api/shows/{show}/sets/...` to `/api/sets` and
  `/api/sets/{set}/banks/...`. The internal Mapper/Core protocol
  parameter name `setlist` (`Library.resolve(setlist, track)`,
  `src/core/library.py`) is deliberately **not** part of this rename --
  it's an internal implementation detail never surfaced to a user, kept
  stable on purpose. Existing library USBs need their folders/file
  renamed by hand to match (see `LIBRARY.md`) before this version's code
  will find anything on them.
- Real-hardware validation of `expansions/setlist-admin-usb/` (iPhone USB
  tethering), which found and fixed several real bugs:
  - Transient `umount` failures (`pedal-core.service`'s mpv holds
    `/media/usb` open continuously) now get a bounded retry instead of
    failing the whole write.
  - The library USB has been observed to spontaneously unmount itself on
    real hardware with no corresponding log evidence anywhere -- root
    cause not confirmed, but a real power-supply brownout was caught in
    the act (`vcgencmd get_throttled` showed under-voltage) during the
    same session, the strongest lead so far. `usb_mount.py` now
    self-heals: `_remount()` treats "already not mounted" as success
    instead of erroring, and new `usb_mount.ensure_mounted()` (used by
    `is_first_run()`) attempts a recovery mount before a read-only check
    ever draws a wrong conclusion from an empty directory (previously
    misreported as "first run," prompting to overwrite an existing PIN).
  - Two overlapping requests (e.g. a real double-tap on a button) used to
    race each other's raw `umount`/`mount` calls with no coordination,
    occasionally corrupting the remount state. `writable_usb()` is now
    held under a process-wide lock, serializing every write.
  - A phone disconnecting mid-upload (`usb-tether-watchdog.service`
    stopping the admin server via SIGTERM the instant the tethered
    interface disappears) never corrupted real data (the atomic
    temp-file write design held), but did leave large orphaned
    `.part`/`.swaptmp` files behind forever, since SIGTERM skips Python's
    normal exception-cleanup path. New `library_ops.cleanup_stale_temp_files()`
    sweeps these on every server startup.
  - `rename_song()`/`delete_song()` didn't verify a song file still
    existed before touching it (unlike every other function in
    `library_ops.py`) -- a stale reference to a song deleted by hand
    directly on the USB hit a raw, unhandled `FileNotFoundError` instead
    of a clean error message.
  - Frontend: several button handlers had no error handling at all (a
    server error was an invisible unhandled promise rejection); the
    per-track upload handler never checked the response status; list
    reloads reset scroll to the top of the page after every
    save/assign/rename (root cause: the container was genuinely empty,
    sometimes for as long as several sequential network round-trips,
    forcing the browser to clamp scroll -- fixed by building new content
    off-screen first and swapping it in in one step); and the
    "this worked" button flash fired only after the server responded
    instead of the instant the button was tapped, so a slow upload
    looked unresponsive for its whole duration.
- Added an **Export Set** view to both `setlist-admin` expansions: a
  full-screen, large-print running order for the selected Set (each
  track's exact stored filename + extension, in Bank/letter order),
  with a supported-formats disclaimer and a "Share" button that renders
  the list to a PNG image and hands it to the phone's native share sheet
  (desktop/unsupported-browser fallback: plain download). Closes via an
  on-screen ✕, Escape, or the browser back gesture.
- **Fixed**: in `setlist-admin-usb`, picking a different Set from the
  dropdown only changed what the app was showing/editing -- it never
  told the pedal which Set to actually play. Only *creating* a new Set
  called the `set_active_set` API; switching between Sets that already
  existed had no way to become "the" active one at all short of
  deleting and recreating one. Fixed by having "Reboot now to apply"
  set whichever Set is currently selected as active immediately before
  rebooting -- the one moment this app already asks the user to
  confirm intent, so also the right moment to commit to it. (Not yet
  ported to `setlist-admin-wifi`, which has no reboot button of its own
  -- see `expansions/setlist-admin-usb/NEXT_STEPS.md`.)
- Documented (en/es `TROUBLESHOOTING.md`, plus `systemd/README.md`
  section 4) a consolidated answer to "is the Pi safe against a power
  cut, and what are the actual risk windows": during normal band use,
  `/`, `/boot/firmware`, and `/media/usb` are all RAM-backed or `ro`, so
  there's nothing for a power loss to corrupt; the real (brief) windows
  are a library edit's `/media/usb` `rw` remount, the overlay being
  disabled for development, and hand-editing `cmdline.txt` -- the last
  two are maintenance-only, never during a show. Also calls out that an
  underpowered supply, not a clean unplug, is the more likely real-world
  trigger, per this project's own directly-observed under-voltage event.
- Added a shared song library (`_Songs/` at the USB root) to both
  `setlist-admin` expansions, so a song only needs to be uploaded once
  and can be reused across any number of Sets instead of
  re-uploading it into every new Set. Documented as a base-project
  convention in `LIBRARY.md` (en/es) -- works by hand over SSH too, not
  just through either app -- with an explicit warning not to delete
  songs from it, since doing so only removes them from future picking,
  never from a Bank they're already assigned to (that's always an
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
  segments (Set names, now also song filenames) were never
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
  companion web app for managing the library USB (Sets/Banks/tracks,
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
  fails completely silently -- found live while testing a Bank 5 video
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
