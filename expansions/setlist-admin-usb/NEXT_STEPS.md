# Next steps for setlist-admin-usb

*[Leer en español](docs/es/NEXT_STEPS.md)*

**Read this first if you're picking this project back up** -- whether
you're Claude or any other AI agent, human contributor, or future-me.
It's written to be understood cold, without the conversation history
that produced it.

## Where things stand (as of commit `9209a29`, 2026-09-27 -- see the
git log for anything newer, this file lags slightly behind commits by
nature)

The Show/Set/Bank terminology rename (see `CHANGELOG.md`'s "Renamed the
library's terminology..." entry) and a full real-hardware validation
pass of `setlist-admin-usb` are **committed, pushed to `main`, and
confirmed persistent on the real Pi** (survived an actual reboot cycle
after being deployed correctly -- see "Deploying to the Pi" below for
why that's not automatic). `setlist-admin-wifi` got the same code
changes for parity but has **not** been hardware-tested itself (still
blocked on a dead USB WiFi dongle -- see its own `SPECIFICATION.md`).

Real bugs found and fixed during this pass are listed in detail in
`CHANGELOG.md`'s Unreleased section and in `SPECIFICATION.md` sections
0/14 -- don't re-discover these:
- Transient `umount` EBUSY -> retried.
- The library USB has been observed to spontaneously unmount itself
  with zero corresponding log evidence -- root cause **not confirmed**,
  but a real power-supply brownout was caught in the act
  (`vcgencmd get_throttled` showed under-voltage) during this session,
  the strongest lead so far. `usb_mount.py` now self-heals either way.
- A double-tap could race two remount cycles -> `writable_usb()` is now
  a process-wide lock.
- A phone disconnecting mid-upload left orphaned `.part`/`.swaptmp`
  files forever -> cleaned up on every server startup now.
- `rename_song()`/`delete_song()` didn't check the file still existed
  -> fixed, matches the rest of `library_ops.py`'s pattern now.
- Frontend: missing error handling, scroll jumping on list reloads, and
  button-tap feedback firing on response instead of on tap -> all
  fixed. See the `flashSuccess()`/`clearFlash()`/
  `beginScrollPreservation()` comments in `static/app.js` for the
  reasoning -- follow that pattern for any new button you add.

An **Export Set** feature was added: a full-screen, large-print running
order for the selected Set, with a "Share" button that renders it to a
PNG and hands it to the phone's native share sheet. See
`SPECIFICATION.md` section 14 for the design.

**Fixed and user-confirmed working (2026-09-27, after the above)**:
selecting a Set from the dropdown never actually marked it as the
pedal's active Set -- only *creating* a new Set did, via
`set_active_set`. Switching between Sets that already existed silently
did nothing for playback, no matter how many times you selected a
different one. Fixed: "Reboot now to apply" now calls
`POST /api/sets/active` for whichever Set is currently selected
immediately before rebooting. **Not ported to `setlist-admin-wifi`** --
that expansion has no reboot button of its own (its `USAGE.md` already
tells users to `ssh pedal sudo reboot` by hand instead), so the
equivalent fix there would need its own UI decision (e.g. set-active
immediately on dropdown selection, since there's no "apply" moment to
hook into) -- not yet designed, let alone built.

## What's genuinely unconfirmed -- do these before trusting them

1. **Export Set's visual fix is deployed but not re-confirmed.** It
   first shipped with a real CSS bug (`.export-view` had an
   unconditional `display: flex` that overrode the browser's own
   `[hidden] { display: none }` rule, so the view showed, empty, on
   every page load -- see `SPECIFICATION.md` section 14's last
   paragraph). That was fixed and deployed, but the user was never
   asked to re-open "Export Set" and confirm it now looks right
   end-to-end (title populated, numbered list populated, close via ✕/
   Escape/back all working). **Do this first.**
2. **The second scroll-jump fix (the "~1s flash to top" one) was
   deployed but never explicitly re-confirmed either** -- the user
   moved on to requesting Export Set right after it was deployed,
   without confirming. Ask them to rename or delete a song while
   scrolled down to a later Bank and confirm there's no visible jump at
   all now.
3. **Desktop/PC browser support for Export Set's "Share" button is
   explicitly uncertified** -- `navigator.share()` with file attachments
   has poor desktop browser support; the code falls back to a plain
   download, but this has never been tested from an actual PC. Do this
   once `setlist-admin-wifi`'s PC-accessibility work happens (see the
   ordered list below), since that's the expansion meant to be reached
   from a computer on the home network.

## Ordered test plan -- continue here

This is the same list the user asked to go through "paso a paso"
(step by step) this session. Items 1-2 are done; resume at 3:

1. ~~Reboot-to-apply~~ -- done, validated with a real reboot.
2. ~~Mid-edit disconnect resilience~~ -- done; found and fixed the
   orphaned-temp-file bug (see above).
3. **Rename/delete a song from the library UI** -- functionally
   confirmed working by the user, but see "genuinely unconfirmed" #2
   above (the scroll-jump fix on this exact flow needs a fresh check).
4. **Uninstall / rollback** -- not started. Run
   `expansions/setlist-admin-usb/scripts/rollback.sh` on the real Pi
   and confirm: `pedal-core.service` is never stopped/restarted/
   touched, the two setlist-admin systemd units are gone, and (without
   `--purge`/`--purge-library`) the PIN and `_Songs/` survive for a
   future reinstall. See `SPECIFICATION.md` section 11 for exactly what
   should and shouldn't be touched.
5. *(Optional, non-blocking)* Test with a second phone (ideally
   Android, to exercise the `rndis_host`/`cdc_ether`/`cdc_ncm` driver
   paths that this session only ever exercised with one iPhone's
   `ipheth`).

## Deferred product decisions -- not yet built, need a decision first

Two things the user raised and explicitly asked to defer:

- **Show the raw stored filename (e.g. "A - Perro.wav") instead of the
  friendly display name in the main Bank/track cards** (not Export Set,
  which already does this by design -- see section 14). Discussed at
  length; real risks identified (redundant with the letter badge
  already shown, longer text truncates more aggressively, extension
  casing becomes visible/inconsistent, and it does **not** actually
  reveal a manually-malformed filename on the USB, since those are
  invisible to `list_tracks()`/`list_songs()` either way). If picked
  back up: this should be a **display-only** change -- the "Rename"
  flow must keep editing only the display-name portion, never the
  letter/extension directly, or it reopens the exact
  silent-filename-failure risk `library_ops.py` was built to make
  structurally impossible (see its own module docstring).
- **A formal in-app/doc recommendation against editing the USB by hand
  once an expansion is installed.** The user asked how the app
  currently handles someone renaming/deleting files directly on the USB
  outside the app. Answer (verified in code, this session): it's
  **mostly safe already** -- nothing is cached, every screen re-reads
  the USB fresh, and `list_tracks()`/`_require_set()`/`_require_bank()`/
  `assign_song_to_slot()` all defensively re-check current state. The
  one real gap found (`rename_song()`/`delete_song()` not checking
  existence) is now fixed. What was **not** done: actually writing a
  "don't edit the USB by hand once you're using the app" recommendation
  into `LIBRARY.md`/`USAGE.md`. Worth doing if the user still wants it,
  but it's a documentation addition, not a code fix -- nothing is
  currently broken by manual edits beyond that one already-fixed gap.

## Operational notes for whoever deploys to the Pi next

These cost real time to discover this session -- don't re-learn them
the hard way:

- **SSH**: always `ssh -4 pedal` / `scp -4 ... pedal:...` (force IPv4;
  mixed `eth0`+`eth1`+mDNS otherwise causes multi-minute hangs on
  trivial commands).
- **The Pi has TWO independent network interfaces that matter**: `eth0`
  is the home Ethernet/LAN (what SSH uses); `eth1` is whatever phone is
  currently USB-tethered (e.g. `172.20.10.2/28` for an iPhone Personal
  Hotspot). They're fully independent -- unplugging Ethernet does
  **not** affect a tethered phone's ability to reach `setlist-admin`,
  and vice versa.
- **`pedal-core.service` does NOT run from the git checkout.** Its
  `ExecStart` points at `/home/hesner/pedal_src_test/src/main.py`, a
  separate plain-file copy. Any change to `src/core/library.py`/
  `core.py`/`main.py` must be copied to **both**
  `~/chocolatepi-repo/src/` and `~/pedal_src_test/src/` (and clear
  `__pycache__` under `pedal_src_test/src/*/`) -- updating only the git
  checkout silently does nothing for the live pedal. This mismatch
  should probably get cleaned up properly at some point (point
  `pedal-core.service` at the git checkout instead), but hasn't been,
  to avoid an unrelated risky change mid-session.
- **CRITICAL: the Pi's root filesystem is a RAM-backed overlay by
  default** (`overlayroot=tmpfs:recurse=0` in `cmdline.txt`, per
  `systemd/README.md` section 4). Anything written under `/home/` (the
  git checkout, `pedal_src_test`, anything) while the overlay is active
  -- a plain `scp`/`tar xzf`/`git pull` -- works for the *current* boot
  but is **silently wiped on the next reboot**. This bit us for real
  this session (hours of "deployed" work vanished after an unplanned
  reboot). To deploy something that must survive a reboot:
  1. `ssh -4 pedal "sudo mount -o remount,rw /boot/firmware && sudo sed -i 's/overlayroot=tmpfs:recurse=0 //' /boot/firmware/cmdline.txt && sudo mount -o remount,ro /boot/firmware && sudo reboot"`
  2. Wait for it to come back (`until ssh -4 pedal "echo up" 2>/dev/null; do sleep 3; done`), then confirm with `mount | grep -E ' / '` that root is a plain `ext4 rw` mount, not `overlay`.
  3. Deploy (see below), run the test suites on the Pi itself, restart
     the affected systemd services, verify.
  4. Re-enable: `ssh -4 pedal "sudo raspi-config nonint do_overlayfs 0 && sudo mount -o remount,rw /boot/firmware && sudo sed -i 's/overlayroot=tmpfs /overlayroot=tmpfs:recurse=0 /' /boot/firmware/cmdline.txt && sudo mount -o remount,ro /boot/firmware && sudo reboot"`
     (note: `do_overlayfs 0` strips `:recurse=0` again every time --
     always re-append it by hand before this reboot, or you'll hit the
     old emergency-mode-on-missing-USB bug from `TROUBLESHOOTING.md`).
  5. Wait for it to come back, then verify persistence actually held:
     `git status --porcelain` in `~/chocolatepi-repo` should show
     whatever you just committed as clean (or your intended diff if not
     yet committed), and the affected services should already be
     running the new code (they start automatically at boot).
  - A quick, low-risk deploy you're only testing (not yet trying to make
    durable) can skip all of this and just `scp`/`tar` into the
    already-running overlay -- just remember it won't survive a reboot
    until you do the dance above.
- **Bundle multi-file deploys as a tarball, not a loop of individual
  `scp` calls.** A loop of per-file `scp`s was tried once and silently
  failed to transfer most files (no error shown). Reliable pattern:
  `tar czf /tmp/x.tar.gz <files>`, `scp -4 /tmp/x.tar.gz pedal:/tmp/`,
  then `ssh -4 pedal "cd ~/chocolatepi-repo && tar xzf /tmp/x.tar.gz && rm /tmp/x.tar.gz"`.
- **`ntfs-3g` (the library USB's filesystem) does not support
  `mount -o remount,rw/ro`** -- it refuses outright. Every remount,
  automated or manual over SSH, must be a real `umount` followed by a
  fresh `mount -o <mode>`.
- **Claude specifically has no browser/visual-automation tool in this
  environment.** Server-side logic (HTTP calls, timing, error
  responses) can and should be verified directly -- either real HTTP
  requests against the running service, or by importing `AdminAPI`
  directly in a one-off Python script over SSH against the real mounted
  USB (using a disposable test Set, cleaned up afterward). But anything
  visual -- button colors, toast placement, whether a full-screen view
  actually renders -- needs the user to look at their phone and report
  back. Don't claim a visual fix is confirmed working without that.
