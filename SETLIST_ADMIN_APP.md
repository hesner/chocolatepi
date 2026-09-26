# Setlist Admin — usage guide

*[Leer en español](docs/es/SETLIST_ADMIN_APP.md)*

The optional web app for managing the library USB and the Pi's WiFi
from a phone or computer's browser, instead of SSH + `nano` + copying
files by hand. Design and rationale: `SETLIST_ADMIN_SPECIFICATION.md`.
Not installed by default -- see "Installing" below.

**Pre/post-show only.** This isn't designed or tested for editing the
library while a show is in progress -- the app shows a warning if it
detects the pedal is actively playing, but doesn't block you; treat
that warning as a real one, not a formality.

## Installing

Optional, and separate from the base pedal setup
(`systemd/README.md`). Requires the read-only root overlay to be
temporarily disabled first, same as any other install step that writes
to `/etc/systemd/system` (`systemd/README.md` section 4):

```
sudo raspi-config nonint do_overlayfs 1
sudo reboot
```

Then, from the repo root on the Pi:

```
sh scripts/install_setlist_admin.sh <your-usb-uuid>
```

`<your-usb-uuid>` is the same UUID `pedal-core.service`'s `--usb-uuid`
already uses (`systemd/README.md` section 3). This starts
`setlist-network-watchdog.service`, which decides on its own when
`setlist-admin.service` itself should be running (see "How the network
side works" below) -- you don't start the admin server directly.

Re-enable the overlay once done:

```
sudo raspi-config nonint do_overlayfs 0
```

Then edit `/boot/firmware/cmdline.txt` and re-add `:recurse=0` -- see
`systemd/README.md` section 4, the same step required after any overlay
re-enable.

## First use

1. Connect your phone to the Pi's hotspot (or your computer to the same
   network the Pi is on).
2. Visit `http://<pi-hostname-or-ip>:8080`.
3. First visit: set a PIN (at least 4 characters). This is shared,
   single-PIN auth (`SETLIST_ADMIN_SPECIFICATION.md` section 2) -- not
   a per-person account.
4. From then on, visiting the app asks for that PIN.

**Forgot the PIN?** There's no email/reset-link flow -- this is a local
appliance with no account system. Recover it over SSH:

```
ssh pedal
sudo umount /media/usb && sudo mount -o rw /media/usb
rm /media/usb/.setlist-admin/pin.hash
sudo umount /media/usb && sudo mount -o ro /media/usb
```

The next visit to the app treats this as first-run again and asks you
to set a new PIN.

## Using it

**Library tab**: pick or create a show, create/delete `Set` folders,
and for each track slot (A/B/C):
- **Upload** replaces whatever's there for that letter.
- **Rename** changes the display name only (the letter -- its position
  -- and file extension stay the same).
- **Delete** clears the slot.

There's no separate "reorder" button -- to swap which song is in which
position, upload/rename so the right file ends up under the right
letter, or use the swap action (drag-and-drop reordering may be added
later; today it's letter-by-letter).

Every upload gets its codec checked (`ffprobe`) -- a non-H.264 video
gets a warning, not a block, pointing at `LIBRARY.md`'s encoding
guidance. It still uploads; playback may not work until you re-encode
it, same as if you'd copied it in by hand.

Changes made through the app apply to the live pedal on its very next
footswitch press -- no reboot needed (confirmed on real hardware per
`SETLIST_ADMIN_SPECIFICATION.md` section 6's test plan).

**WiFi tab**: optionally set the Pi's home WiFi (SSID + password). If
set and reachable, the Pi prefers it over the phone hotspot; if not
reachable, it falls back to the hotspot automatically. See "How the
network side works" below for what this actually does under the hood.

## How the network side works

Two WiFi profiles are tracked: the phone hotspot (this project's
default/fallback, set up once during install) and an optional home
network (set from the WiFi tab, any time). Both are stored encrypted on
the library USB, tied to this specific Pi + this specific USB --
copying the file to a different pairing makes it undecryptable, on
purpose (`SETLIST_ADMIN_SPECIFICATION.md` section 5).

`setlist-network-watchdog.service` reapplies both profiles to
NetworkManager on every boot (they don't survive under the read-only
root overlay otherwise) and checks connectivity every 30 seconds,
starting `setlist-admin.service` only while there's a usable IP --
running it with no network reachable would just waste RAM/CPU for
nothing.

## Uninstalling / rolling back

If this ever needs to come out -- a bug, or just deciding not to use
it -- `pedal-core.service`, the actual live-critical pedal, is never
touched by installing or removing this:

```
sh scripts/rollback_setlist_admin.sh
```

Add `--purge` to also delete the stored PIN and WiFi credentials from
the USB; omit it to keep them so a future reinstall doesn't need
reconfiguring from scratch. See `SETLIST_ADMIN_SPECIFICATION.md` section
11 for exactly what this does and doesn't touch.
