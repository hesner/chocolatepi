# SETLIST ADMIN USB SPECIFICATION — "Chocolate Pi" companion admin app (USB-tether design)

**Status: implemented and passing its first real-hardware test
(2026-09-26 -- PIN setup, login, and a track rename all confirmed
working end-to-end over an iPhone's Personal Hotspot connection).**
Mirrors `MASTER_SPECIFICATION.md`'s own process: this document was
proposed, discussed, and approved before any code was written (section
6 of that file). Section 13 (song library) was approved and added the
same day, after the initial hardware test, in response to a real
workflow gap noticed once real songs were actually being assigned.

This is a **separate design track** from the earlier WiFi-based
attempt (preserved, unfinished, on the `explore/setlist-admin` branch
-- not on `main`, not this file). That one is not abandoned, just
paused on a hardware blocker (a dead USB WiFi dongle); it may be
resumed later. This document deliberately keeps its **user experience**
compatible with that one (section 3) so the two can converge cleanly
whenever the WiFi track picks back up.

---

## 0. Why this design, and how it relates to the WiFi track

The WiFi design used the Pi's own WiFi radio: the Pi would host a
phone hotspot or join the band's home WiFi, and the phone would reach
it over that network. It was fully implemented and passed every stage
of hardware testing except one: the USB WiFi dongle itself turned out
to be failing hardware (confirmed dead by testing it on a separate
computer, not a Pi-side power or software problem). The design and
code were never at fault -- the radio was.

**This design removes the WiFi radio from the picture entirely.**
Instead of the phone joining the Pi's network over the air, the phone
plugs into the Pi with a USB cable and shares its own connection over
that cable (Android calls this "USB tethering"; iPhone calls it
"Personal Hotspot" with a cable attached instead of WiFi). The Pi only
ever needs a USB port, which it already has four of and which have
been reliable throughout this whole project. There is no new radio
hardware to depend on.

Worth recording: the Pi 2 Model B's USB ports are **host-only** (no
OTG/gadget mode) -- the Pi can never present itself as a USB device to
a phone. It can only be a host that another USB device plugs into.
USB tethering fits that constraint naturally: the phone is the device,
the Pi is the host, exactly like the Behringer interface or the
library USB already are.

## 1. What this is

A web app, running on the Raspberry Pi itself, for managing the
library USB's content (shows, Sets, tracks) from a phone's browser --
instead of the manual SSH + `nano`/file-copy workflow this project has
used until now. Reachable by plugging the phone into the Pi with a USB
cable before or after a show.

Non-goals (unchanged from the WiFi design): no live show control (that
stays MIDI-only, per `MASTER_SPECIFICATION.md`), no editing while a
track is actively playing without a warning, no touching
`pedal-core.service` or anything in `src/core/`, `src/adapter/`,
`src/mapper/`. **No modification of the standby video or anything the
Pi displays on screen, under any circumstance** -- that screen shows
only the live-concert experience (the standby loop or whatever the
band is playing), never admin/debug/network information. This rules
out an on-screen IP/QR display as a discovery mechanism (see section
4) -- deliberately not pursued here.

## 2. Architecture

```
Phone (Android or iPhone)
   │  USB cable, phone shares its connection over it
   ▼
Pi USB port  ──►  kernel driver brings up a network interface
                   (rndis_host/cdc_ether/cdc_ncm for Android,
                   ipheth for iPhone)
   │
   ▼
usb-tether-watchdog.service   -- notices the interface, starts the
   │                             admin server; notices it vanish, stops it
   ▼
setlist-admin.service (HTTP, stdlib-only Python)
   │
   ▼
library_ops.py + usb_mount.py  -- unchanged from the WiFi design,
   │                              reused as-is
   ▼
Library USB (/media/usb)
```

## 3. UX consistency with the WiFi design (hard requirement)

The two designs must **look and behave identically** to the person
using them, differing only in how the phone and Pi find each other
underneath. Concretely:

- The frontend (`static/index.html`, `style.css`, `app.js`) is ported
  from `explore/setlist-admin` **as-is** for every library-management
  screen (shows/Sets/tracks CRUD, PIN entry, PIN recovery messaging).
  The only removal is the WiFi-settings page/section, which has no
  equivalent here. No redesign of the CRUD screens themselves.
- `library_ops.py`, `usb_mount.py` (including the `ntfs-3g`
  umount+mount fix found during the WiFi design's hardware testing),
  and `auth.py` (PIN + session tokens) are reused verbatim -- same
  API shapes, same validation rules, same error messages.
- `api.py`/`server.py`'s CRUD routes are reused verbatim; only the
  WiFi-specific routes/methods (`set_home_wifi`, `wifi_status`) are
  dropped, nothing else changes.

Dropped entirely (not a UX change, a plumbing one): `crypto.py` (WiFi
credential encryption) and `wifi.py` (home/hotspot NetworkManager
profile juggling) -- there are no WiFi credentials anywhere in this
design, so there's nothing to encrypt and nothing that can strand SSH
access by misconfiguring a network profile.

Practical effect: if the WiFi track resumes later, merging the two
should mean swapping the connectivity/watchdog layer underneath a
frontend and CRUD layer that never diverged.

## 4. Phone connection mechanism

### 4a. Android

Settings → Network & internet → Hotspot & tethering → **USB
tethering** (must be plugged in first for the toggle to appear).
Android then presents a standard USB network-adapter class to the
host -- Raspberry Pi OS's kernel already has the drivers
(`rndis_host`, `cdc_ether`, `cdc_ncm` depending on Android version),
no packages to install. NetworkManager treats it exactly like plugging
in a USB Ethernet adapter: a new interface appears, DHCP client runs
automatically, done.

### 4b. iPhone

Settings → Personal Hotspot → toggle on, then plug in the cable.
iOS offers a system prompt on the phone ("Trust This Computer?") the
first time -- must be accepted once per phone. Unlike Android, this
needs one extra package on the Pi: `usbmuxd` (handles Apple's USB
multiplexing protocol; pulls in `libimobiledevice6` as a dependency).
The kernel's `ipheth` driver is already present in Raspberry Pi OS. Once
`usbmuxd` is running and the phone is trusted, a network interface
appears the same way Android's does, and NetworkManager DHCPs it the
same way.

### 4c. Detecting which one is connected

Not by IP range (subnets vary by device/OS version and aren't reliable
to hardcode) -- by **kernel driver name**, read from
`/sys/class/net/<iface>/device/driver` (or equivalently `ethtool -i
<iface>`). Known phone-tether drivers: `rndis_host`, `cdc_ether`,
`cdc_ncm` (Android), `ipheth` (iPhone). `usb-tether-watchdog.service`
polls for any interface whose driver matches this list and has a
usable IP -- deliberately not "any interface with an IP," so a
permanently-attached Ethernet cable (used for development, as it is
right now) never spuriously starts the admin server. Interface name is
not used for matching (both platforms' names vary by kernel/udev
config); driver name is stable.

## 5. Discovery: how the phone's browser finds the Pi

**The standby screen is off-limits (section 1), so this is purely a
network-side problem, solved with existing, already-proven tools:**

- **Primary**: `http://pedal.local:8080` -- avahi already advertises
  this for SSH, and it keeps working the same way over whichever
  interface is active, including the phone-tether one. No new
  infrastructure. Works reliably on iOS Safari.
- **Known caveat, accepted rather than engineered around**: some
  Android browsers have historically been inconsistent resolving
  `.local` hostnames typed directly into the address bar. Documented
  fallbacks in `SETLIST_ADMIN_APP.md` rather than solved in code:
  - iPhone Personal Hotspot over USB consistently uses the
    `172.20.10.0/28` range with the iPhone itself at `172.20.10.1` --
    `http://172.20.10.2:8080` is very often correct on the first try
    if `pedal.local` doesn't resolve.
  - Android's tethering subnet varies more by manufacturer, so no
    single IP is safe to document -- the fallback there is checking
    the phone's own tethering/hotspot settings screen (most show
    connected-device info) or, once, finding the IP over SSH the way
    this project already did during development.
- Explicitly **not pursued**: any Pi-side "beacon" (DNS hijack,
  captive-portal-style redirect) -- in tethering mode the phone is the
  DHCP/DNS authority on that link, not the Pi, so the Pi has no way to
  intercept or redirect arbitrary lookups the way it could if it were
  hosting the network itself (as in the WiFi design).

## 6. Handling sudden USB disconnections

Explicitly a first-class requirement (this is a cable that gets
unplugged mid-session by design, not an edge case):

- **Mid-write**: `library_ops.py` and `usb_mount.py` already write via
  a temp file (`.part`/`.swaptmp`) and `os.replace()`, so a cable pull
  either happens before the atomic rename (no visible change, no
  corruption) or after it (the write had already fully landed). The
  HTTP connection itself just drops; the phone's browser shows a
  connection error, nothing worse.
- **Interface disappearing**: `usb-tether-watchdog`'s next poll
  (every few seconds) notices the driver-matching interface is gone,
  stops `setlist-admin.service`. NetworkManager/udev tear down the
  dead interface on their own -- no custom cleanup code needed, same
  as any USB hot-unplug.
- **Reconnecting**: plugging back in (or re-toggling tethering on the
  phone) creates a fresh interface from the kernel's point of view;
  DHCP re-acquires automatically. No special-cased reconnect logic --
  it looks identical to a first connection.
- **Multiple phones / switching phones**: also just "the previous
  interface vanished, a new one appeared" -- no per-phone state kept
  anywhere.

## 7. Auth

Keeps the PIN (`auth.py`, unchanged -- section 3) as defense-in-depth.
USB physical access is already a strong gate, but a PIN still matters
here (shared gear, multiple band members, someone plugging in a phone
without asking) and it's already built, tested, and has a documented
recovery path (unmount, delete `pin.hash`, remount -- ported unchanged
from the WiFi design's `SETLIST_ADMIN_APP.md`).

## 8. Applying changes: reboot required, not live hot-swap

`library.py`'s resolution logic (`src/core/`) only reads the library's
structure at `pedal-core.service` startup -- this is an existing,
deliberate `MASTER_SPECIFICATION.md` decision, unrelated to either
admin-app design. **This project already tried building a live-reload
mechanism once** (`CHANGELOG.md`: "A fully automatic hot-swap ...
attempted via `udev` + a remount service and separately via background
polling; both were abandoned as unreliable on this hardware/filesystem
combination"). This design does not reopen that: **applying a setlist
change requires a reboot**, same as any other library edit today.

What this design *does* add for convenience: a "Reboot now to apply"
button in the admin UI itself (`sudo systemctl reboot`, same privilege
model as every other write this app makes), so the person doesn't need
SSH just to restart the Pi after editing. The reboot only needs to
happen once the phone is done editing (create the show, arrange the
Sets, rename tracks, then one reboot) -- not once per edit.

If live-reload is ever revisited, that is its own, separate design
question that touches `src/core/library.py` and the already-documented
failure history above -- out of scope here.

## 9. Resource footprint

Lighter than the WiFi design: no WiFi scanning, no NetworkManager
profile reapply-on-every-tick logic. `usb-tether-watchdog` only needs
to `readlink` a handful of `/sys/class/net/*/device/driver` paths
every few seconds -- negligible CPU, no radio power draw at all.
`setlist-admin.service` itself is identical to the WiFi design's
(stdlib HTTP server, `Nice=10`, `CPUWeight=20`, started/stopped by the
watchdog).

## 10. Testing strategy

Meaningfully easier to validate than the WiFi design's: a USB cable to
a phone is far more reliable to test against than fringe WiFi
signal/hardware, and a bad test here can't strand this project's own
SSH access (SSH stays on Ethernet throughout, completely unaffected by
whatever the phone-tether interface is doing).

1. Unit tests: `library_ops.py`, `usb_mount.py`, `auth.py` ported
   unchanged from `explore/setlist-admin` (already have coverage).
   New: `usb_tether_watchdog.py`'s driver-matching logic (mockable, no
   real hardware needed -- fake `/sys/class/net` trees in a temp dir).
2. Real hardware, staged, Ethernet-backed throughout (SSH access is
   never at risk in this design, but keeping Ethernet connected during
   testing is still good practice for observing logs live):
   a. Plug in an Android phone with USB tethering on, confirm the
      interface appears with a matching driver name and the watchdog
      detects it (dry-run mode first, same pattern as the WiFi
      design's section 8a).
   b. Confirm `pedal.local:8080` (or the documented fallback) reaches
      the app from the phone; set the PIN, exercise the CRUD screens
      end-to-end.
   c. Unplug mid-edit, confirm no corruption and a clean recovery on
      replug.
   d. Repeat a-c with an iPhone.
3. Only after all of the above pass: the "reboot to apply" button,
   confirming `pedal-core.service` picks up the new library state
   correctly on the resulting reboot (this part is already proven --
   it's the same boot-time resolution path the project has used since
   its first release).

## 11. Installation and rollback

This whole feature lives under `expansions/setlist-admin-usb/` -- an
**expansion**: a self-contained, independently installable/removable
addon to the base project, never required for the base pedal to work
(see the repo root's `expansions/README.md` for the general model).
Optional install via `expansions/setlist-admin-usb/scripts/install.sh`
(installs `setlist-admin.service` + `usb-tether-watchdog.service`),
never auto-enabled by the base `systemd/README.md` setup,
`expansions/setlist-admin-usb/scripts/rollback.sh` to remove cleanly
(stops/removes the services only -- doesn't touch git state, so it
can't collaterally affect any other expansion).

## 12. Open questions for approval

- **`usbmuxd` as a dependency**: fine to add for iPhone support (one
  `apt install`, well-maintained, packaged in Raspberry Pi OS's repos)?
- Section 5's Android `.local`-resolution caveat is accepted as a
  documented fallback rather than engineered around, given section 1
  rules out the one mechanism (on-screen display) that would have
  sidestepped it entirely. OK with that trade-off, or is there another
  discovery idea worth exploring first?
- Anything else you want different from the WiFi design's UX while
  we're building this track, given section 3 otherwise keeps them
  identical on purpose?

## 13. Song library (reuse across Shows) -- approved 2026-09-26

**Problem**: originally, a song only ever existed as a copy physically
inside one specific `<Show>/Set N/<Letter> - name.ext`. Building a new
setlist (a new Show) for the next concert meant re-uploading every song
from scratch, even ones already used in a previous Show.

**Design**: a shared, flat pool of songs at the USB root, `_Songs/`,
independent of any Show -- now documented as a base-project convention
in `LIBRARY.md`, not just an implementation detail of this expansion
(a human without any expansion installed can and should use the same
convention by hand, per that document). A Show's `Set`/Letter slot is
still always a real, physical copy -- never a symlink or reference --
so `core.library.Library`'s boot-time resolution needs zero changes,
and each Show stays exactly as self-contained as it always was.
Rejected the symlink/reference alternative specifically because it
would have required `core.library.Library` itself to learn to resolve
them, and this project already had one `ntfs-3g` surprise this month
where an operation that "should just work" didn't.

Two ways a song ends up in `_Songs/`:
1. **Uploading directly into a Set slot** (the original flow,
   unchanged) now *also* copies the result into `_Songs/` automatically
   (`library_ops._add_to_library_if_new`) -- best-effort, silently
   skipped (never an error) if a song with that exact name is already
   there.
2. **Uploading straight into the library** (`upload_song`), from the
   new "Song library" section of the UI, without assigning it anywhere
   yet.

Assigning a Set slot from the library (`assign_song_to_slot`) is a
same-USB file copy, not a re-upload -- fast, and the library's own copy
is left untouched for the next Show. `save_track_to_library` is the
reverse direction, for content that predates this feature or was
assigned before being added to the library -- always an explicit,
one-track-at-a-time action; no automatic cross-Show dedup/migration is
attempted (guessing whether two files in different Shows are "the same
song" is exactly the kind of fragile heuristic this project avoids).

`list_shows()` now excludes anything starting with `_` (previously only
excluded dotfiles) so `_Songs/` never appears in the Shows list.

Two real, pre-existing bugs (present since the WiFi design, unrelated
to this feature) were found and fixed while building this: `server.py`
never translated `library_ops.LibraryOpsError` into a proper HTTP
response (fell through to a generic 500 "Internal error" instead of the
400 with a helpful message it should have been -- fixed by catching
`ValueError` generically in `_handle_action`), and URL path segments
(show names, now also song filenames) were never percent-decoded
server-side despite the frontend percent-encoding them, so any name
actually needing encoding (any space) silently failed.

Per `LIBRARY.md`: songs in `_Songs/` should never be deleted, treated as
a permanent record of everything the band has -- `delete_song()` exists
for real cleanup needs, but the UI's confirmation dialog says this
explicitly rather than just asking "are you sure?".

**Uninstalling**: `_Songs/` is new data this feature introduces, so
`scripts/rollback.sh` gained a second, separate purge flag,
`--purge-library`, distinct from `--purge` (which only ever touched the
small PIN file) -- deleting actual song files is a bigger, more
deliberate action than resetting a PIN, and `_Songs/` is shared with
`setlist-admin-wifi` too (same USB, same convention), so purging it
here removes it there as well.
