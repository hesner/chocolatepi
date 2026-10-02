# Setlist Admin (USB) — usage guide

*[Leer en español](docs/es/USAGE.md)*

This is one **expansion** (`expansions/setlist-admin-usb/`) -- see the
repo root's `expansions/README.md` for what that means. It's the
optional web app for managing the library USB (Sets, Banks, tracks)
from a phone's browser, reachable by plugging the phone into the Pi
with a USB cable -- instead of SSH + `nano` + copying files by hand.
Design and rationale: [`SPECIFICATION.md`](SPECIFICATION.md). Not
installed by default -- see "Installing" below.

**Pre/post-Set only.** This isn't designed or tested for editing the
library while a Set is in progress -- the app shows a warning if it
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

**Language**: the **EN/ES** dropdown in the top bar switches every
label, button, confirmation, and notification between English and
Spanish, saved on this phone/browser only (each device remembers its
own choice). Song, track, Set, and Bank names are never translated or
altered, in either language -- they're your data, shown exactly as
typed.

Pick or create a Set, create/delete `Bank` folders, and for each track
slot (A/B/C):
- **Upload new** uploads a file straight into that letter, replacing
  whatever was there. It's also automatically added to the **song
  library** (see below), so it's ready to reuse in a future Set
  without uploading it again.
- **Assign** (next to the song-picker dropdown) puts an existing song
  from the library into that letter instead, without uploading
  anything -- an instant copy on the USB itself.
- **Rename** changes the display name only (the letter -- its position
  -- and file extension stay the same).
- **Delete** clears the slot. This does **not** remove the song from
  the library -- it's an independent copy (see below).
- **Save to library**, shown once a slot is filled, adds that specific
  copy to the library if it isn't there already -- useful for songs
  assigned before this feature existed, or from a different device.

There's no separate "reorder" button -- to swap which song is in which
position, upload/rename so the right file ends up under the right
letter, or use the swap action.

Every upload gets its codec checked (`ffprobe`) -- a non-H.264 video
gets a warning, not a block, pointing at `LIBRARY.md`'s encoding
guidance. It still uploads; playback may not work until you re-encode
it, same as if you'd copied it in by hand.

### Export Set: a large-print running order to read on stage

The **"Export Set"** button (next to the Set selector) opens a
full-screen, large-print list of every track currently assigned in that
Set, in order (Bank 1 A, B, C, then Bank 2, and so on) -- each line
shows the track's exact stored filename and extension, so what you see
here always matches what's really on the USB. Meant to be glanced at
while performing, not read up close.

Close it with the **✕** in the corner, the Escape key, or your phone's
own back gesture/button.

**Share** renders the list as a PNG image and hands it to your phone's
own share sheet (WhatsApp, Messages, email, save to Photos -- whatever
you have installed); on a desktop browser without that sharing support
it downloads the PNG directly instead (support from a PC browser is
still being verified separately).

### Song library: reuse songs across Sets

The **"Song library"** section at the top of the app (tap to expand)
lists every song available for reuse -- this is the on-disk `_Songs/`
folder at the USB root (`LIBRARY.md` documents the same convention for
editing the USB by hand, without this app). It's meant to hold **every
song the band has**, not just the ones in the Set you're currently
building, so that starting a Set for the next performance is a matter
of picking from what's already there instead of re-uploading
everything.

From here you can upload a new song directly into the library (without
assigning it to any Bank yet), rename one, or delete one. If you upload
a name that's already there, the app asks **"... already exists in the
library. Replace it?"** -- confirm to overwrite it in place, or cancel
to leave the existing one untouched.

If a song's video isn't in the recommended format (H.264 -- see the
upload hint, or `LIBRARY.md`), it still uploads, but an **"Optimize"**
button appears next to it. Tap it to re-encode the file in place to
the recommended format, without having to do it by hand. You'll see a
warning first: **do not unplug the Raspberry Pi while it's running**
-- the re-encode writes to the Pi's own local storage for its full
duration, and this can take a while on this hardware (confirmed up to
roughly 90 minutes, or several hours for a large 4K video) -- while
it's running the button shows a standing green **"Optimizing"**, which
sticks around (alongside a **"Cancel"** button) even if you disconnect
your phone and come back later, so you can check on it whenever's
convenient. The app automatically re-checks every few seconds while a
job is active, so you don't need to manually refresh to see it finish
or get cancelled. If it fails (a corrupt or unreadable file), the
button becomes **"Optimize (retry)"** with the reason shown on
tap-and-hold.

**Changed your mind, or need the Pi for something else right now?**
Tap **"Cancel"** -- it stops the re-encode within a few seconds and
leaves the file exactly as it was, not yet optimized. Safe to tap
"Optimize" again later to retry.

The optimization itself runs
independently of this app and of any Set currently playing -- a song
in the library isn't loaded into any live Set or the standby slot
until you separately assign it, so an in-progress optimization never
affects what's actually playable right now. **Deleting a
song from the library is discouraged -- if you're not sure, don't.**
`LIBRARY.md` recommends treating it as a permanent record of everything
the band has ready to play, even songs not currently used in any Set,
so the library stays an honest answer to "how many songs do we
actually have." Once deleted, a song can no longer be chosen when
building a Bank (it won't show up in the picker for any future Set) --
but deleting it does **not** remove it from any Bank it's already
assigned to; those keep playing normally, since assigning a song
already made an independent copy. The app's delete confirmation spells
this out too. Uninstalling either `setlist-admin` expansion never
deletes `_Songs/` either, by default -- only an explicit
`--purge-library` flag does (see "Uninstalling" below). And in the
other direction: assigning a song to a Bank never removes it from the
library -- every assignment is a copy, the library's own copy always
stays put.

**Changes need a reboot to apply.** The pedal only reads the library's
structure when it starts up (same as always -- this app doesn't change
that). Once you're done editing, tap **"Reboot now to apply"** at the
bottom of the app instead of needing SSH. It's fine to make several
edits first and reboot once at the end -- no need to reboot after every
single change.

### Standby video: what loops when nothing is playing

The **"Standby video"** section shows what's currently looping on
screen (file size and when it was last changed) and lets you replace
it: pick any video from the **song library** above and tap **"Set as
standby"**. To use a video that isn't in the library yet, upload it
there first (the same "+ Upload song to library" button used for
regular songs), then choose it here.

Only videos can be set as standby (audio-only files won't show up in
the picker) -- standby has no footswitch pointing at it, so there'd be
nothing to see or hear from an audio-only file looping silently.
Renaming or deleting it afterward works exactly like any other song in
the library (see above). Same rule as everything else here: **needs a
reboot to apply.**

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
Add `--purge-library` (separately) to also delete `_Songs/`, the shared
song library -- not included in `--purge` since it deletes actual song
files, a bigger step than resetting a PIN; see `LIBRARY.md`'s
recommendation to treat that library as permanent before using this.
See `SPECIFICATION.md` sections 11 and 13 for exactly what each flag
does and doesn't touch.
