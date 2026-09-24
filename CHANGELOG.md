# Changelog

*[Leer en español](docs/es/CHANGELOG.md)*

Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project doesn't use version numbers yet -- it's a single dedicated
appliance build, not a versioned library -- so entries are grouped by
date instead until that changes.

## [Unreleased]

- Added `setlist-admin`: an **optional** companion web app for managing
  the library USB (shows/Sets/tracks, full CRUD) and the Pi's WiFi
  (home network + phone-hotspot fallback) from a phone or computer
  browser. Design doc: `SETLIST_ADMIN_SPECIFICATION.md`; usage guide:
  `SETLIST_ADMIN_APP.md` (en/es). Never installed by default and never
  modifies `pedal-core.service` or any of `src/core/`, `src/adapter/`,
  `src/mapper/` -- install via `scripts/install_setlist_admin.sh`, back
  out cleanly via `scripts/rollback_setlist_admin.sh`. Highlights:
  - Stdlib-only Python backend (`http.server`), vanilla responsive
    frontend -- no new `pip`/`apt` dependency for the web app itself.
  - WiFi credentials encrypted at rest on the USB (`openssl enc
    -aes-256-cbc`, not GCM -- `openssl enc` turned out not to support
    AEAD ciphers, found while building this) with a key derived from
    this specific Pi + USB pairing.
  - Every write to the library goes through a structured API that
    makes LIBRARY.md's "double space before the dash" class of silent
    failure impossible to reproduce by construction, not just
    documented.
  - Upload-time H.264 codec validation (warns, doesn't block).
  - 108 new unit/integration tests (135 total project-wide) -- found
    and fixed two real bugs before this ever touches hardware: a
    Set-cookie ordering bug that silently broke every login, and a
    missing filename-length bound that could exceed a filesystem's
    per-component limit.
  - Not yet validated on real hardware -- see
    `SETLIST_ADMIN_SPECIFICATION.md` section 8a's staged, Ethernet-backed
    safety protocol for how that validation must proceed.
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
