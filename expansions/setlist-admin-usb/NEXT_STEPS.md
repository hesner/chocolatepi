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
changes for parity but has **not** been hardware-tested itself (this
snapshot is from 2026-09-27, before a working WiFi dongle was found --
see "Where things stand" entries below and its own `SPECIFICATION.md`
for the current status).

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

**Also documented (2026-09-27, no code change)**: a consolidated answer
to "is the Pi safe against a power cut, and where are the real risk
windows" in `TROUBLESHOOTING.md`/`docs/es/TROUBLESHOOTING.md` (new
section near the top) and `systemd/README.md` section 4. Short version:
safe during normal band use (root/`boot`/USB are all RAM-backed or `ro`
at that point); the real windows are a library edit's brief
`/media/usb` `rw` remount, the overlay disabled for development, and
hand-editing `cmdline.txt` -- the last two maintenance-only. An
underpowered supply (not a clean unplug) is flagged as the more likely
real-world trigger, per this project's own observed under-voltage event.

**2026-10-01, real incident investigated and fixed (code change, not yet
deployed to the Pi as of this file -- check `VERSION`/git log for
whether it's landed there yet)**: the user reported audio stopping
completely after about an hour of intensive real-hardware testing.
While investigating live over SSH, the M-VAVE turned out to be powered
off, and `pedal-core.service` was caught mid-crash-loop (restart counter
climbing every ~10s) -- `main.py` used to treat "MIDI controller not
found" as fatal, exiting and relying entirely on `systemd` blindly
restarting the whole process (tearing down and relaunching both `mpv`
lanes every cycle -- visible flicker, total silence, zero on-screen
explanation) for as long as the controller stayed missing. Fixed: see
`CHANGELOG.md`'s Unreleased entry and `TROUBLESHOOTING.md`'s new "Audio
(and video) stop completely..." section for the full writeup: `main.py`
now retries the MIDI connection in-process without tearing `mpv` down.
(A second fix landed the same pass -- logging `mpv`'s own `stderr`
instead of discarding it -- but was **reverted the same day**: that log
lives in the RAM-backed root overlay with no rotation, so leaving it on
permanently was judged not worth the standing RAM-exhaustion risk for a
benefit that's only useful during an active debugging session. Capture
it temporarily, by hand, next time it's actually needed -- don't
redeploy that patch permanently. See `CHANGELOG.md`'s `v2026.10.01`
entry for the full reasoning.) **Also added, same session, per explicit
user request**: standby video
management in both `setlist-admin` apps (pick any library video as the
new `standby.mp4` -- `USAGE.md`, `library_ops.set_standby_video()`).
**Deployed and verified on the real Pi (2026-10-01, commit `886d4d0`,
cut as `v2026.10.01`)**: full overlay-disable/deploy/test/re-enable/
reboot dance completed; all 324 tests (27+139+158) passed on the Pi
itself; `pedal-core.service` restarted cleanly with the M-VAVE connected
and confirmed persistent after the final reboot; `get_standby()`
confirmed reading the real mounted USB's actual `standby.mp4`
correctly. **Not independently confirmed**: actually tapping "Set as
standby" from a phone and visually seeing the new video loop -- this
would overwrite the band's real, currently-in-use `standby.mp4`
(754MB), so it wasn't done live without the user there to confirm the
result and restore if needed. Do this first, same as the Export Set
precedent below.

**2026-10-01, later the same day -- library-wide "Optimize" button,
built, deployed, and real-hardware-tested (commits `e1fafe6`,
`8f187fb`)**: real user request, right after the standby-video manual
conversion above -- instead of re-encoding a flagged video by hand
over SSH every time, the Song library now shows an "Optimize" button
next to any file `codec_check.is_optimized()` flags, backed by a new
always-on `library-optimizer.service` daemon and a persistent,
file-based job queue (`optimize_queue.py`) so a long job survives the
phone that queued it disconnecting. See `CHANGELOG.md`'s Unreleased
entry and `SPECIFICATION.md` section 15 for the full design. Ported to
both expansions, 181 (USB) + 200 (WiFi) tests passing.

Deployed to the real Pi the same session, full overlay dance (see
"Operational notes" below -- `raspi-config nonint do_overlayfs 1`
alone did **not** strip the custom `:recurse=0` suffix from
`cmdline.txt`, needed a manual `sed` on top, same as disabling it;
worth remembering next time instead of re-discovering it). Found and
fixed a real bug in the process: `library-optimizer.service`
crash-looped under `systemd` (`ModuleNotFoundError: No module named
'admin'`) because `library_optimizer.py` never added `src/` to
`sys.path` the way `server.py` does -- invisible to the test suite,
which already puts `src/` on the path itself. Fixed, redeployed,
confirmed genuinely running (not just "active" mid-crash-loop).

Then ran a real end-to-end test over SSH: a tiny synthetic HEVC clip
(`ffmpeg -f lavfi testsrc`, 3s) uploaded via `AdminAPI.upload_song()`,
queued via `request_song_optimization()`, picked up by the daemon in
a few seconds, confirmed re-encoded to H.264 and the queue cleared
(`needs_optimization: False` afterward). `pedal-core.service` and
`standby.mp4` playback were unaffected throughout. Test song deleted
afterward. **Not yet confirmed**: the actual phone UI flow -- tapping
"Optimize" from the app itself, watching the button read
"Optimizing...", and specifically disconnecting/reconnecting the
phone mid-job to confirm the state really does persist visually, not
just at the `AdminAPI`/queue-file level already proven above. **Do
this next** -- the user is about to run it as of this writing.

**2026-10-01, later the same day -- a real standby.mp4 data-loss
incident, found and recovered**: the user reported the band's actual
standby video (~55 minutes, ~754MB) was gone -- replaced earlier that
day through the app's own "Set as standby" picker with no way back.
Root cause, confirmed in code: `library_ops.set_standby_video()` just
does `_atomic_copy_file()` straight over `standby.mp4`; it never backs
up whatever it's replacing. Searched the whole USB (library, every
Set/Bank, the old `backup/` folder) -- no trace. Recovered only
because the user still had the original, unconverted source file
(a real band video file, 6.68GB, H.264 1080p but at ~15.7Mbps -- far
too heavy to use directly) on a separate computer. Re-encoded it
to ~1.8Mbps (matching the lost original's own bitrate almost exactly:
754MB over 55.66 minutes is ~1.8Mbps) using `h264_v4l2m2m` for *both*
decode and encode -- confirmed live at ~0.87x realtime, dramatically
faster than the ~0.1x this project saw earlier for software-only HEVC
decode, since the source here was already H.264 and this Pi's
hardware codec handles that natively both ways. Uploaded the ~800MB
result into the library under a new name (plain
`AdminAPI.upload_song()`, deliberately not `set_standby_video()` --
the user wanted to choose if/when to make it standby again themselves,
not have it forced). They later did exactly that through a temporary
web session (see below) and rebooted to apply it -- confirmed via
`mpv`'s own IPC socket that `standby.mp4` is now that exact file.
**`set_standby_video()` still has no backup step -- see "Deferred
product decisions" below.**

Same investigation also surfaced a transfer-side gotcha worth
remembering: a new USB WiFi dongle (see "Where things stand" above)
was connected while a 6.68GB file was mid-`scp`-transfer to the Pi, and
the user asked to switch off Ethernet once it was safe -- confirmed
dual-interface (`eth0`+`wlan0`) `mDNS`/`pedal.local` resolution gets
flaky once both are up (same root cause as the long-documented
`eth0`+`eth1` version of this issue, just with a WiFi interface
instead of a second wired/tethered one). Falling back to the direct
WiFi IP with the right `-i ~/.ssh/id_ed25519_pedal -o
IdentitiesOnly=yes` resolved it every time.

Also found live, worth remembering verbatim: **`pkill -f '<pattern>'`
run over SSH can kill its own SSH session** if the pattern text you
pass happens to appear in the invoking shell's own command line (which
it will, trivially, since you just typed that exact string as an
argument) -- `pkill -f` matches full command lines, not just the
target process's. Killed the remote bash wrapper instead of `ffmpeg`,
surfacing as a bare SSH exit 255 with no remote-side error at all. Fix:
match by exact process name instead (`pkill -TERM ffmpeg`, no `-f`),
or make the pattern specific enough that it can't also match its own
invocation.

**Also this same investigation**: a code fix that was only ever
"quick-deployed" (pulled while the protective overlay was active, so
it only ever lived in the RAM-backed upper layer) was silently lost
when the overlay was later disabled-and-rebooted for an *unrelated*
reason (needing real disk space for the 6.68GB conversion above) --
the git checkout reverted to the last commit that had actually been
durably deployed. Re-pulled once noticed (confirm with `git log
--oneline -1` after any reboot, any reboot, not just ones from your own
deploy work -- don't assume a quick-deployed commit survived just
because nothing *you* did should have rebooted the Pi).

## 2026-10-02: Optimize/Cancel UI confirmed live, a full day of
real-hardware bugs, and a language toggle

**The "Optimize" button's real phone-UI flow (item 1 below, as it
stood at the end of 2026-10-01) is now thoroughly confirmed** -- not
just once, but across an extended real-usage session: tapped
"Optimize" from the phone itself multiple times, watched the warning
popup, watched the standing green "Optimizing" button alongside
"Cancel", tapped "Cancel" itself (including while `ffmpeg` was
actively mid-encode, confirmed via direct `AdminAPI` timing: the call
returned in ~0.02s and the real `ffmpeg` process was gone within
~10s), and confirmed the song returns to a clean, un-optimized state
afterward ready for a fresh "Optimize" tap. The disconnect/reconnect
persistence this item asked for is inherent to the design (the queue
is file-based, the daemon is a separate systemd unit) and was
exercised incidentally throughout the day's testing without issue.

A long chain of real bugs were found and fixed the same day, each from
a genuine user report while actively using the app, not from a review
pass -- full detail, one entry per fix, in `CHANGELOG.md`'s
`[Unreleased]` section (newest first): a tablet-only form-centering
bug; a ~37s login-to-songs-loaded delay (serial, uncached `ffprobe`
calls); a transient `ffprobe` timeout under load getting cached
*permanently* as "not optimized"; `ffmpeg` holding the USB-mounted
source open for an encode's *entire* duration, blocking every other
library write (e.g. an unrelated "create Bank") the whole time; a
leftover disclaimer baked into the Export Set share image specifically
(the on-screen one had already been removed); no `Cache-Control` on
static files, letting a stale `app.js`/`index.html` combination serve
a page that looked stuck showing only the topbar; the same gap for
`GET /api/songs` specifically, showing a song as already-optimized
while a job was genuinely still running; and, found last, cancelling a
job could 500 if tapped within roughly the first minute (while the
new scratch-copy step was still reading the source off the USB) --
fixed by moving the cancel marker off the USB entirely, onto local Pi
storage (`optimize_queue.DEFAULT_STATE_DIR`), since it never needed to
live there in the first place. **Confirmed live** via a direct,
timed `AdminAPI.cancel_song_optimization()` call against a real,
actively-encoding job.

**Also added, same day, real user request**: a full ES/EN language
toggle (`static/i18n.js`, both expansions) -- a dropdown in the topbar
(now reading "ChocolatePi - Setlist Admin") switches every label,
button, confirm, alert, and toast between English and Spanish,
persisted per-browser via `localStorage`. Song/track/Set/Bank names are
explicitly never translated (they're user data, not UI chrome) --
every render function in `app.js` keeps those out of the translation
calls on purpose. Server-sent error messages stay in English for now,
a separate, explicitly deferred piece of work if ever wanted. An
auto-refresh (`GET /api/songs` every 5s while anything is
queued/running, stopping itself otherwise) was added alongside it so
the Cancel/Optimize button state never needs a manual refresh to catch
up.

**Not yet done, worth doing soon**: `USAGE.md`/`docs/es/USAGE.md` (both
expansions) and `CHANGELOG.md`/`docs/es/CHANGELOG.md` were updated for
all of the above as of this writing -- but `VERSION` was **not**
bumped (no version was "cut" this session; everything above still sits
in `[Unreleased]`). If a clean checkpoint is wanted, that's the next
small step: confirm nothing's regressed, bump both expansions'
`VERSION` files, rename `[Unreleased]` to today's date.

**2026-10-02, later the same day -- a second real incident, a full
user QA pass, and a disk-space cleanup.** Starting a second "Optimize"
job while another's source was still mid-copy off the USB could also
500, for the same underlying reason as the cancel fix above
(`setlist-admin.service` and `library-optimizer.service` are two
separate processes -- the in-process lock in `usb_mount.py` never
coordinated between them). Fixed with a real cross-process file lock;
see `CHANGELOG.md`'s Unreleased entry.

The user then ran a full manual QA pass against every feature touched
today, reporting back item by item. Real findings, all fixed the same
session (detailed, one per item, in `CHANGELOG.md`): a `pedal-core.
service` crash-loop under heavy CPU load (confirmed live -- the pedal
showed `mpv`'s idle screen for a couple of minutes); `list_sets()`
listing filesystem-reserved folders as selectable Sets; "Queued" and
"Optimizing" rendering identically (confirmed live: this caused
cancelling the wrong job by mistake); a slow library upload with no
early duplicate-name check; raw untranslated network errors; missing
tap feedback on the login/standby buttons; and manual Bank numbering
(now auto-sequential, real user request: a MIDI controller steps
through Banks one at a time, so there's never a real reason to pick
anything but the next number -- not capped at any specific
controller's own physical bank count).

Two things that came up during this pass are **not code bugs,
confirmed by digging into the actual behavior rather than guessing**:
- A delay the user measured informally as "~40 seconds" for an
  Optimize/Cancel action to visually update turned out, per the
  server's own access log timestamps, to be ~2 seconds end to end --
  no backend bottleneck found. Noted for next time: if this recurs,
  capture the exact wall-clock tap time to compare against the log,
  since "it felt slow" isn't enough on its own to chase a specific fix.
- Setting a large, not-yet-optimized video directly as standby failed
  outright with a real `OSError: [Errno 28] No space left on device`
  -- the library USB was down to ~925MB free (89% used, confirmed via
  `df`), nowhere near enough for a multi-GB raw video copy. Not a code
  bug -- the fix was freeing space, not changing behavior.

That low-disk-space finding led to a real cleanup: the two largest
not-yet-optimized video files in the library (several GB combined)
were deleted by the user from the app itself, freeing roughly 2.7GB
(from ~925MB to ~3.7GB free, confirmed via `df` before/after). A
smaller handful of oddly-generic-named `.wav` files (named like
"track N" rather than a real song title, ~180MB combined) were
flagged as possible leftover test data but intentionally **left
alone** pending the user's own confirmation -- don't delete those
without being told to.

**Operational note, worth remembering**: `usb-tether-watchdog.service`
actively enforces "`setlist-admin.service` only runs while a phone is
USB-tethered" -- it re-stops the admin app within a few seconds of any
manual `systemctl start`, confirmed live via its own `journalctl`
output (repeated `systemctl stop setlist-admin.service` calls, several
seconds apart). To reach the admin app over WiFi with no phone
tethered (the same need as item 5 at the very top of this file):
`sudo systemctl stop usb-tether-watchdog.service` *first*, then
`sudo systemctl start setlist-admin.service` -- and remember to
`sudo systemctl start usb-tether-watchdog.service` again afterward to
restore the normal automatic behavior, or the admin app will simply
stay up (and reachable) indefinitely instead of following the
USB-tether convention the rest of this project relies on.

## 2026-10-03: resource-aware video lane (base pedal), and the WiFi
expansion formally deferred to the roadmap

**Base pedal change, not this expansion, but relevant to anyone
touching the Pi this week.** `src/core/` gained a resource-aware video
lane: with no HDMI display connected, the video-playing `mpv` process
(confirmed costing ~106% CPU and ~300MB RAM continuously, even just
looping standby) is never started at all, audio-only tracks still play
normally, and video tracks fall back to audio-only until a display
shows up. Plugging in HDMI starts the video lane fresh (including
catching a display connected *after* boot, which previously needed a
manual `pedal-core.service` restart -- confirmed as today's opening
bug report). Unplugging HDMI mid-clip never cuts the clip's audio --
the lane only actually stops once the current clip (or standby) is
free to do so. A real regression was found and fixed the same day:
`_MpvProcess`'s stop flag was never reset between stop/start cycles,
so the first reconnect after a disconnect left mpv showing its idle
screen ("Drop files or urls to play here") instead of standby --
confirmed fixed across multiple real disconnect/reconnect cycles via
the user's own pasted logs. Unrelated to this expansion's own code;
mentioned here only because it changes what "the pedal is idle" looks
like on the Pi this expansion also runs on.

**`setlist-admin-wifi` is now formally a roadmap item, not a
near-term one.** Confirmed live via `nmcli` that the Pi's initial setup
(Raspberry Pi Imager's wireless-LAN configuration step) already saved
a WiFi profile (`autoconnect: yes`) for the band's home network --
meaning any USB WiFi dongle plugged into the Pi reconnects to that
same network by default, with no extra configuration needed. Given
that, a full revival of the `setlist-admin-wifi` expansion (its own
hotspot-configuration UI, encrypted on-USB credential storage, etc.)
isn't worth doing short-term. Instead, a smaller, independent feature
was added right here in `setlist-admin-usb`: see "Reaching the app
over WiFi" in `USAGE.md`. `setlist-admin-wifi` itself is untouched
code-wise -- just reframed in its own docs as "implemented, unit-
tested, deliberately not being taken further for now."

## What's genuinely unconfirmed -- do these before trusting them

1. ~~Export Set's visual fix~~ -- **confirmed by the user, 2026-10-02**,
   during the full QA pass: opened with "Live" selected (title +
   numbered list populated correctly), closed via ✕ and via the
   phone's back gesture, "Share" produced a clean image with no leftover
   disclaimer. Done.
2. ~~The scroll-jump fix~~ -- never got one isolated, dedicated check,
   but was exercised incidentally dozens of times across the same QA
   pass (renames, deletes, Bank/track edits) with no complaint raised.
   Treating this as confirmed by extensive informal use; revisit only
   if a jump is ever actually seen again.
3. **Desktop/PC browser support for Export Set's "Share" button is
   still explicitly uncertified** -- `navigator.share()` with file
   attachments has poor desktop browser support; the code falls back to
   a plain download, but this has never been tested from an actual PC.
   Do this once `setlist-admin-wifi`'s own real-hardware validation
   happens (see "Where things stand" above), since that's the expansion
   meant to be reached from a computer on the home network.
4. **Whether the four oddly-generic-named `.wav` files in the library
   ("track N" rather than a real song title, ~180MB combined) are real
   setlist content or leftover test data is still an open question** --
   flagged to the user 2026-10-02, never answered. Don't delete them
   without being told to; ask again if it comes up.

## Ordered test plan -- continue here

This is the same list the user asked to go through "paso a paso"
(step by step), several sessions ago. Items 1-3 are done; **item 4 has
never been started, across this entire project, and is the one
genuinely open item here**:

1. ~~Reboot-to-apply~~ -- done, validated with a real reboot.
2. ~~Mid-edit disconnect resilience~~ -- done; found and fixed the
   orphaned-temp-file bug (see above).
3. ~~Rename/delete a song from the library UI~~ -- confirmed working,
   including the scroll-jump concern (see "genuinely unconfirmed" #2
   above).
4. **Uninstall / rollback -- still not started.** Run
   `expansions/setlist-admin-usb/scripts/rollback.sh` on the real Pi
   and confirm: `pedal-core.service` is never stopped/restarted/
   touched, the two setlist-admin systemd units are gone, and (without
   `--purge`/`--purge-library`) the PIN and `_Songs/` survive for a
   future reinstall. See `SPECIFICATION.md` section 11 for exactly what
   should and shouldn't be touched. **Do this next.**
5. *(Optional, non-blocking)* Test with a second phone (ideally
   Android, to exercise the `rndis_host`/`cdc_ether`/`cdc_ncm` driver
   paths that this session only ever exercised with one iPhone's
   `ipheth`).

## Deferred product decisions -- not yet built, need a decision first

**Highest priority of the three below, given it already cost real
data once**: back up the previous `standby.mp4` before replacing it.
`library_ops.set_standby_video()` currently just copies the chosen
library song straight over `standby.mp4`, no questions asked -- fine
right up until someone picks the wrong one, which is exactly what
happened 2026-10-01 (see "Where things stand" above): the band's real
~55-minute standby was gone, unrecoverable from the Pi itself, and
only came back because a copy happened to still exist elsewhere. The
user was asked in the moment whether to add an automatic backup and
said yes to recovering the lost video specifically, but the actual
backup feature itself was never built in the session that followed --
revisit this explicitly rather than assuming it's done. A reasonable
shape: before the copy, move the current `standby.mp4` into something
like `backup/standby-previous.mp4` (single slot, overwritten each
time, not an ever-growing history -- this USB has limited space and a
full history isn't the goal, just "don't lose the one before this
one"). Same `_atomic_copy_file()`/`writable_usb()` machinery already
in use elsewhere, so this is a small, self-contained change once
someone decides on the exact backup naming/retention shape.

Two other things the user raised and explicitly asked to defer:

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

- **Checking versions**: this project and each expansion now track a
  date-based `VERSION` file (`vYYYY.MM.DD`) -- see the root
  `CHANGELOG.md`'s "Versioning" section for the scheme. On the real Pi:
  `ssh -4 pedal "cat ~/chocolatepi-repo/VERSION ~/chocolatepi-repo/expansions/*/VERSION"`.
  Remember a `VERSION` file only reflects reality if someone bumped it
  in the same commit as the change -- the git commit hash it's checked
  out to is always the ultimate source of truth.
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
     (confirmed again 2026-10-01: `sudo raspi-config nonint
     do_overlayfs 1` by itself does **not** work here -- its matching
     logic doesn't recognize the custom `:recurse=0` suffix, so it
     leaves `cmdline.txt` completely untouched and the overlay stays
     mounted after the reboot. Always use the direct `sed` above, not
     `do_overlayfs 1`, to disable.)
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
