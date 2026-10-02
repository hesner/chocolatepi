# Setlist Admin (WiFi) — usage guide

*[Leer en español](docs/es/USAGE.md)*

This is one **expansion** (`expansions/setlist-admin-wifi/`) -- see
the repo root's `expansions/README.md` for what that means. It's the
optional web app for managing the library USB and the Pi's WiFi from a
phone or computer's browser, instead of SSH + `nano` + copying files by
hand. Design and rationale: [`SPECIFICATION.md`](SPECIFICATION.md).
Not installed by default -- see "Installing" below.

**Status**: shelved on a hardware blocker (a dead USB WiFi dongle, not
a design/code problem -- see `SPECIFICATION.md`'s status note and the
repo root's `CHANGELOG.md`). Install this once there's a known-good
WiFi adapter to test against.

**Pre/post-Set only.** This isn't designed or tested for editing the
library while a Set is in progress -- the app shows a warning if it
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

Then, from anywhere inside the repo checkout on the Pi:

```
sh expansions/setlist-admin-wifi/scripts/install.sh <your-usb-uuid>
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
   single-PIN auth (`SPECIFICATION.md` section 2) -- not
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

**Language**: the **EN/ES** dropdown in the top bar switches every
label, button, confirmation, and notification between English and
Spanish, saved on this phone/browser only (each device remembers its
own choice). Song, track, Set, and Bank names are never translated or
altered, in either language -- they're your data, shown exactly as
typed.

**Library tab**: pick or create a Set, create/delete `Bank` folders,
and for each track slot (A/B/C):
- **Upload new** uploads a file straight into that letter, replacing
  whatever was there. It's also automatically added to the **song
  library** (see below), ready to reuse in a future Set without
  uploading it again.
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
letter, or use the swap action (drag-and-drop reordering may be added
later; today it's letter-by-letter).

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

The **"Song library"** section at the top of the Library tab (tap to
expand) lists every song available for reuse -- this is the on-disk
`_Songs/` folder at the USB root (`LIBRARY.md` documents the same
convention for editing the USB by hand, without this app). It's meant
to hold **every song the band has**, not just the ones in the Set
you're currently building, so starting a Set for the next performance
is a matter of picking from what's already there instead of
re-uploading everything.

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
structure when it starts up (`MASTER_SPECIFICATION.md`) -- this app
doesn't change that; edit as much as you need, then `ssh pedal sudo
reboot` once you're done (this expansion's UI doesn't have a built-in
reboot button the way `setlist-admin-usb`'s does).

### Standby video: what loops when nothing is playing

The **"Standby video"** section shows what's currently looping on
screen (file size and when it was last changed) and lets you replace
it: pick any video from the **song library** above and tap **"Set as
standby"**. To use a video that isn't in the library yet, upload it
there first, then choose it here. Only videos can be set as standby
(audio-only files won't show up in the picker). Renaming or deleting it
afterward works exactly like any other song in the library. Same rule
as everything else here: needs a reboot to apply.

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
purpose (`SPECIFICATION.md` section 5).

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
sh expansions/setlist-admin-wifi/scripts/rollback.sh
```

Add `--purge` to also delete the stored PIN and WiFi credentials from
the USB; omit it to keep them so a future reinstall doesn't need
reconfiguring from scratch. Add `--purge-library` (separately) to also
delete `_Songs/`, the shared song library -- not included in `--purge`
since it deletes actual song files, a bigger step than resetting a PIN;
see `LIBRARY.md`'s recommendation to treat that library as permanent
before using this. See `SPECIFICATION.md` sections 11-12 for exactly
what each flag does and doesn't touch.
