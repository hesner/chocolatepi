# Setlist Admin (USB) — usage guide

*[Leer en español](docs/es/USAGE.md)*

This is one **expansion** (`expansions/setlist-admin-usb/`) -- see the
repo root's `expansions/README.md` for what that means. It's the
optional web app for managing the library USB (shows, Sets, tracks)
from a phone's browser, reachable by plugging the phone into the Pi
with a USB cable -- instead of SSH + `nano` + copying files by hand.
Design and rationale: [`SPECIFICATION.md`](SPECIFICATION.md). Not
installed by default -- see "Installing" below.

**Pre/post-show only.** This isn't designed or tested for editing the
library while a show is in progress -- the app shows a warning if it
detects the pedal is actively playing, but doesn't block you; treat
that warning as a real one, not a formality.

## Installing

Optional, and separate from the base pedal setup
(`systemd/README.md` at the repo root). Requires the read-only root
overlay to be temporarily disabled first, same as any other install
step that writes to `/etc/systemd/system` (`systemd/README.md`
section 4):

```
sudo raspi-config nonint do_overlayfs 1
sudo reboot
```

Then, from anywhere inside the repo checkout on the Pi:

```
sh expansions/setlist-admin-usb/scripts/install.sh
```

If you'll ever connect an iPhone (not just Android), also install its
one extra dependency:

```
sudo apt install -y usbmuxd
```

Installing starts `usb-tether-watchdog.service`, which decides on its
own when `setlist-admin.service` itself should be running (see "How
the connection works" below) -- you don't start the admin server
directly.

Re-enable the overlay once done:

```
sudo raspi-config nonint do_overlayfs 0
```

Then edit `/boot/firmware/cmdline.txt` and re-add `:recurse=0` -- see
`systemd/README.md` section 4, the same step required after any overlay
re-enable.

## First use

1. Plug your phone into the Pi with a USB cable.
2. **Android**: Settings → Network & internet → Hotspot & tethering →
   turn on **USB tethering**.
   **iPhone**: Settings → Personal Hotspot → turn it on, then accept
   the "Trust This Computer?" prompt that appears on the phone.
3. Visit `http://pedal.local:8080` from the phone's browser. If that
   doesn't load (some Android browsers are inconsistent resolving
   `.local` addresses): on iPhone, try `http://172.20.10.2:8080`
   directly -- Personal Hotspot over USB almost always assigns the Pi
   that exact address. On Android, check your phone's own tethering
   settings screen for the connected device's address, or find it over
   SSH the way this project's own development does
   (`ip -4 addr show` on the Pi, looking for the interface that just
   appeared).
4. First visit: set a PIN (at least 4 characters). This is shared,
   single-PIN auth (`SPECIFICATION.md` section 7) --
   not a per-person account.
5. From then on, visiting the app asks for that PIN.

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

Pick or create a show, create/delete `Set` folders, and for each track
slot (A/B/C):
- **Upload** replaces whatever's there for that letter.
- **Rename** changes the display name only (the letter -- its position
  -- and file extension stay the same).
- **Delete** clears the slot.

There's no separate "reorder" button -- to swap which song is in which
position, upload/rename so the right file ends up under the right
letter, or use the swap action.

Every upload gets its codec checked (`ffprobe`) -- a non-H.264 video
gets a warning, not a block, pointing at `LIBRARY.md`'s encoding
guidance. It still uploads; playback may not work until you re-encode
it, same as if you'd copied it in by hand.

**Changes need a reboot to apply.** The pedal only reads the library's
structure when it starts up (same as always -- this app doesn't change
that). Once you're done editing, tap **"Reboot now to apply"** at the
bottom of the app instead of needing SSH. It's fine to make several
edits first and reboot once at the end -- no need to reboot after every
single change.

## How the connection works

`usb-tether-watchdog.service` checks every few seconds whether a phone
is currently tethered, identified by its network driver (Android's
`rndis_host`/`cdc_ether`/`cdc_ncm`, or iPhone's `ipheth`) rather than
by IP address, so a permanently-attached Ethernet cable never
accidentally starts the admin server. When a phone is detected,
`setlist-admin.service` starts; when the cable is unplugged or
tethering is turned off, it stops a few seconds later.

Unplugging mid-edit is safe -- every write to the USB completes fully
or not at all (never partially), so a dropped cable can't corrupt the
library. Just plug back in and pick up where you left off.

## Uninstalling / rolling back

If this ever needs to come out -- a bug, or just deciding not to use
it -- `pedal-core.service`, the actual live-critical pedal, is never
touched by installing or removing this:

```
sh expansions/setlist-admin-usb/scripts/rollback.sh
```

Add `--purge` to also delete the stored PIN from the USB; omit it to
keep it so a future reinstall doesn't need reconfiguring from scratch.
See `SPECIFICATION.md` section 11 for exactly what
this does and doesn't touch.
