# Automatic boot setup

*[Leer en español](../docs/es/systemd/README.md)*

Makes the pedal start playing (standby loop, listening for the MIDI
controller) automatically when the Raspberry Pi is powered on, with no
screen or keyboard needed (section 1 of `MASTER_SPECIFICATION.md`).

Five pieces, applied in this order: flashing the OS and configuring its
first boot, the software this project depends on, an `/etc/fstab` entry
so the library USB mounts on its own, a `systemd` service that runs
`src/main.py`, and (as the final, deliberately-last step) a read-only
overlay on the Pi's own root filesystem.

## 0. Flash Raspberry Pi OS and configure first boot

Using [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
(official tool, Windows/macOS/Linux):

1. **Choose OS** → "Raspberry Pi OS (other)" → **Raspberry Pi OS Lite
   (Legacy, 32-bit)** -- what `MASTER_SPECIFICATION.md` names as this
   project's base OS.
2. **Choose storage** → your SD card.
3. Before writing, click the gear icon (or press `Ctrl+Shift+X`) to open
   the advanced options and set, in the same sitting:
   - **Hostname**: this project's own reference deployment (and every
     `ssh pedal` example in this repo's docs) uses `pedal`. Use whatever
     you like, just substitute it mentally everywhere these docs say
     `pedal`/`pedal.local`.
   - **Enable SSH**, password authentication (or paste a public key if
     you'd rather not use a password at all).
   - **Username and password**: your choice, no fixed requirement --
     whatever you set here becomes `<YOUR_USER>` in section 3
     (`pedal-core.service`) later.
   - **Configure WiFi** (SSID, password, country) if this Pi won't be on
     Ethernet -- or skip it and use Ethernet instead, which is what this
     project's own testing fell back to when WiFi got flaky (see
     `TESTING.md`).
   - Locale/timezone/keyboard layout as appropriate.
4. Write, then move the card to the Pi and power it on. First boot takes
   a minute or two longer than normal (partition resize, SSH host keys).
5. From another machine on the same network, open a terminal --
   **PowerShell** on Windows 10/11 (it ships with an `ssh` command
   already; search the Start menu for "PowerShell"), **Terminal.app**
   on macOS, or any terminal on Linux -- and run:
   ```
   ssh <your-username>@<hostname>.local
   ```
   `.local` (mDNS) resolution isn't fully reliable in practice (known
   flaky over WiFi). If it doesn't resolve, get the Pi's IP from your
   router's DHCP client list instead and `ssh <your-username>@<that-ip>`.
   The rest of this guide is run from inside this same SSH session,
   unless a step says otherwise.

## 1. Software prerequisites

Raspberry Pi OS (this project was developed against Lite) already ships
`python3`; install the rest:

```
sudo apt update
sudo apt install -y git mpv ffmpeg ntfs-3g
```

- `git` -- to get this project's own code onto the Pi (next step).
- `mpv` -- drives all playback (`src/core/player.py`, over its JSON IPC
  socket; no `python-mpv` or other third-party Python package needed).
- `ffmpeg` -- only used by `scripts/generate_fallback_standby.sh`, to
  generate the local fallback standby video once.
- `ntfs-3g` -- only needed if your library USB is formatted NTFS, as in
  this project's own reference setup; use whatever driver matches your
  own USB drive's filesystem instead (e.g. `exfat-fuse` for exFAT).

No `requirements.txt`: the Python side of this project (`src/`) is
standard-library only, deliberately, so there's nothing to `pip install`.

Now get the project's own code onto the Pi -- every step from here on
assumes you're inside this checkout:

```
git clone https://github.com/hesner/chocolatepi
cd chocolatepi
```

## 2. Library USB — `/etc/fstab`

Add a line like this (get the real UUID for your own USB drive with
`sudo blkid /dev/sda1`, or whatever device it shows up as). `/etc/fstab`
needs `sudo` to edit; `nano` is the simplest editor already on Raspberry
Pi OS -- `sudo nano /etc/fstab`, add the line at the bottom, then
`Ctrl+O` (write out), `Enter` (confirm filename), `Ctrl+X` (exit):

```
UUID=07C1339846657D95  /media/usb  ntfs-3g  ro,nofail,x-systemd.device-timeout=10  0  0
```

- `ro`: mounted read-only by default, matching how this project always
  operates day to day (section 2 of `MASTER_SPECIFICATION.md` -- the
  library USB must never be auto-formatted or have files auto-deleted).
  Remount read-write by hand (`sudo mount -o remount,rw /media/usb`) only
  for deliberate library management, then remount `ro` again afterward.
- `nofail` + `x-systemd.device-timeout=10`: if the USB isn't plugged in
  at boot, don't hang the boot sequence waiting for it -- give up after
  10s and continue. `pedal-core.service` (below) handles the USB still
  being absent after that by falling back to the local standby video
  (see `src/core/player.py`).

Test the line **without rebooting** before trusting it:

```
sudo mount -a
mount | grep /media/usb
```

## 3. The service — `pedal-core.service`

```
sudo cp systemd/pedal-core.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pedal-core.service
```

Check it:

```
sudo systemctl status pedal-core
journalctl -u pedal-core -f
```

The unit as committed here uses placeholders -- `<YOUR_USER>` and
`<YOUR_USB_UUID>` -- in `User=` and `ExecStart=`. Replace both with your
own values before copying it in (this project's own reference deployment
uses `User=hesner`, checkout path `/home/hesner/chocolatepi`, and
UUID `07C1339846657D95`, matching the `/etc/fstab` entry from section 2).
Edit them again later if the checkout path, user, or library USB drive
ever changes.

`Restart=always` means the service keeps retrying every 5s if it exits
for any reason (M-VAVE not enumerated yet, USB not mounted yet, ...) --
there's no keyboard/screen to restart it by hand on a real appliance, so
it needs to recover on its own.

Deliberately uses `Wants=`/`After=` for the USB mount, not
`RequiresMountsFor=`: the latter is a hard dependency, so unplugging the
USB while the service is running makes systemd stop the whole service
(video, audio, everything) instead of letting `Player` fall back to the
local standby video the way it's designed to -- confirmed the hard way,
by unplugging the USB during a live test and getting neither the real
nor the fallback standby on screen, because nothing was running at all.
`Wants=`/`After=` only affects the order things start in at boot; it
never tears this service down because of what the USB does afterward.

## USB behavior (final decision)

Approved operational policy: the musician powers the Pi off, swaps the
USB's content on a separate computer, plugs the USB back into the Pi,
and powers the Pi back on. Editing the library while the show is
actively running is explicitly **not** a supported workflow.

A fully automatic hot-swap (unplug, edit, replug, no reboot) was
attempted via `udev` + a remount service and separately via background
polling; both were abandoned as unreliable on this hardware/filesystem
combination -- see `CHANGELOG.md`/git history if you're tempted to
rebuild one.

**Decided final behavior**, implemented in `Player` (`src/core/player.py`):

- Whether the library USB is present is checked **exactly once, at
  startup** -- via `/dev/disk/by-uuid/<usb_uuid>` (the same UUID as in
  `/etc/fstab` and `--usb-uuid`). Checking `--standby`'s path or its
  mount point directly was tried first and found unreliable under the
  root filesystem overlay below (see the docstring on
  `Player._usb_device_is_present()` for specifics).
- **USB missing at boot**: the local fallback standby plays instead
  ("Please insert the USB into the Raspberry Pi").
- **USB removed while already running**: not detected -- the system
  keeps showing/playing whatever it already had. Recovering (or first
  picking up a library update made while off) always requires a reboot;
  there is no supported way to make it happen without one.

## 4. Read-only root filesystem (final lock-down step)

Requirement: it must be safe to power the Pi off at any moment (pull the
plug) without risking corruption of its own filesystem -- this appliance
has no shutdown button. `MASTER_SPECIFICATION.md`'s read-only-library
requirement (section 2) already covers the USB; this covers the Pi's own
SD card.

Enabled via Raspberry Pi OS's built-in overlay filesystem (`raspi-config`
→ Performance Options → Overlay File System):

```
sudo raspi-config nonint do_overlayfs 0   # enable (1 to disable again)
```

Then edit `/boot/firmware/cmdline.txt` (remount it `rw` first: `sudo
mount -o remount,rw /boot/firmware`, then `sudo nano
/boot/firmware/cmdline.txt`) and append `:recurse=0` to the
`overlayroot=tmpfs` parameter it just added, so the line reads
`overlayroot=tmpfs:recurse=0`. This file is a **single line** -- don't
add a line break, just append to the end of the existing text, then
save (`Ctrl+O`, `Enter`, `Ctrl+X` in `nano`). Remount `/boot/firmware`
back to `ro` and `sudo reboot`.

This is the single riskiest edit in this whole guide -- a mistake in a
kernel command-line parameter can leave the Pi unable to boot at all.
Double check the line before rebooting. If it does fail to boot, nothing
is unrecoverably lost: re-flash the SD card from Imager (section 0) and
start again from there.

**`recurse=0` is required, not optional**: the default (`recurse=1`)
wraps every mount in its own overlay, including `/media/usb` -- and that
auto-generated overlay has no `nofail`, so booting without the library
USB dropped straight into systemd emergency mode (no SSH, unrecoverable
on a headless appliance) instead of falling back to the local standby
the way section 2/3 intend. `recurse=0` limits the overlay to `/` only;
`/media/usb` and `/boot/firmware` already have their own `ro` in
`/etc/fstab` regardless, so they lose no protection.

After reboot, `/` is an `overlay` (`mount | grep ' / '` shows
`lowerdir=/media/root-ro` -- the real SD card, mounted `ro` -- with
`upperdir=/media/root-rw` on `tmpfs`, i.e. RAM). Every write during
normal operation lands in RAM and is discarded on every reboot; the SD
card itself is never touched, so an abrupt power loss can't corrupt it.

**Apply this last, once there's no more Pi-side development expected**:
anything written to the Pi while the overlay is active (including
syncing a new version of this code) is lost on the next reboot, since it
only ever lands in the RAM-backed upper layer. To make further changes:
temporarily disable (`do_overlayfs 1`, reboot), make and verify the
changes normally, then re-enable -- `do_overlayfs 0` resets
`overlayroot=tmpfs` **without** `:recurse=0`, so redo that edit to
`cmdline.txt` every time before rebooting back into it.

Accepted trade-off, confirmed acceptable: `~/pedal-core.log` and the
systemd journal become ephemeral too (wiped every reboot, along with
everything else on `/`) -- acceptable since they're only ever used
live, during an active debugging session over SSH, not read back after
the fact.

## Maintenance / physical access

Running the service means `mpv` permanently occupies the HDMI output
(see `--force-window=yes` in `src/core/player.py`) -- this is a
software-level thing, not an OS-level lockout. To get the physical
console/login back for maintenance:

```
sudo systemctl stop pedal-core
```

SSH access is unaffected either way, regardless of what the service is
doing. If the overlay filesystem (section 4) is active, note that
`sudo` commands still work as usual -- only writes to `/` and
`/boot/firmware` land in the RAM-backed overlay instead of the real SD
card, they don't fail.

## Can a human actually do this alone, with just this site and these docs?

A deliberate review, done by walking through this guide exactly as
written -- not assuming it works, checking it -- from the perspective of
a musician with basic computer skills (comfortable installing software,
copying files, following instructions; not a programmer, no prior Linux
experience assumed).

**Short answer: yes, for the physical setup and configuration, with a
few real gaps in this guide fixed (see below, and check the commit that
added this section -- they should already be fixed by the time you're
reading this, since finding them was the point of doing this review).
No, not independently for anything requiring new code** -- see the
Adapter caveat at the end.

### Walking through it as a first-time builder

1. **Reads `README.md`.** Understands what it does and what hardware to
   buy. Clear.
2. **Follows the link to this file** for the actual install. Section 0:
   flashes the SD card with Raspberry Pi Imager, sets hostname/SSH/user
   in the advanced options. This is a real, well-known GUI tool with its
   own official documentation -- a first-timer can follow it.
3. **Opens a terminal on their own computer to SSH in.** This guide
   says `ssh <user>@<hostname>.local` but never says *what program to
   type that into* -- a musician who's never used SSH doesn't
   necessarily know Windows has a built-in `ssh` command inside
   PowerShell/Terminal, or that Mac has Terminal.app. **Real gap, now
   fixed**: an explicit note belongs here.
4. **Section 1, installs `mpv`/`ffmpeg`/`ntfs-3g`.** Straightforward
   copy-paste of one command. No issue.
5. **Needs the actual project code on the Pi now**, to get
   `pedal-core.service` (section 3) and everything else referenced by
   path. **This guide never said to clone the repository onto the Pi,
   and never listed `git` as something to install.** A reader
   following this document literally, in order, hits a dead end here --
   `sudo cp systemd/pedal-core.service ...` fails because that path
   doesn't exist yet. **Real gap, now fixed.**
6. **Section 2, edits `/etc/fstab`.** The guide says to "add a line"
   but never says *how* -- on a fresh Raspberry Pi OS install there is
   no assumption a first-timer knows `nano` exists, or how to invoke it,
   or how to save and exit it (a famously non-obvious first experience
   even for people with some computer background). **Real gap, now
   fixed.**
7. **Section 3, installs the service.** Once step 5's gap is fixed,
   this works exactly as written.
8. **Section 4, edits `/boot/firmware/cmdline.txt` and adds
   `:recurse=0`.** Same editor gap as step 6, plus this step is
   genuinely the most failure-prone one in the whole guide even for
   someone who *can* use `nano` -- a single typo in a kernel command
   line parameter, or forgetting to remount `/boot/firmware` `rw`
   first, has a much less forgiving failure mode (a Pi that won't boot
   at all) than any other step here. Worth a musician-facing person
   double-checking the line reads exactly right before rebooting, and
   knowing they can always re-flash the SD card from Imager again if
   something goes wrong at this specific step -- that's not stated
   anywhere as reassurance, and probably should be.
9. **Power supply.** Nothing in the hardware list up to this point says
   the power supply matters -- `TESTING.md`/`TROUBLESHOOTING.md`
   document that an underpowered charger causes a real freeze, but that
   information is reactive (you find it *after* hitting the problem),
   not stated as a requirement to buy the right thing *before* starting.
   **Real gap, now fixed**: the hardware list should say **5V/2.5A
   minimum** up front.
10. **`LIBRARY.md`, sets up the USB drive.** Clear, no programming
    involved, just following a naming pattern and copying files -- this
    is exactly at the right level for this persona.
11. **Configuring the MIDI controller itself** (e.g. putting an M-VAVE
    PD41 into "Program Change A" mode) requires the *manufacturer's own
    app and instructions*, which this project deliberately does not
    redistribute (`PD41-Software-Instructions.pdf` is gitignored, by an
    earlier explicit decision in this project). **Real gap**: nothing
    in this repo links to where to actually get that from M-VAVE. A
    buyer of the exact same controller can usually find it from the
    product's own packaging/support page, but this guide doesn't say so
    or point anywhere.

### The one thing a non-programmer genuinely cannot do alone

If the controller isn't an M-VAVE PD41 (or another controller someone
else has already written and contributed an `Adapter` for), **making a
new one work requires writing Python** -- see `REBUILD.md`'s "If the
controller isn't an M-VAVE PD41" note and `CONTRIBUTING.md`. "Basic
computer skills" does not cover this; it's a real, hard line between
"reproduce this exact build" (yes, a non-programmer can) and "adapt it
to different hardware" (no, that needs a developer, or an AI coding
agent following `REBUILD.md`/`MAVAVE_ANALYSIS.md`'s methodology on the
user's behalf).

### Verdict

With the gaps above fixed, a musician with no Linux background and no
programming experience can build this end to end **using the exact
validated hardware** (M-VAVE PD41, a class-compliant USB audio
interface, a Pi 2). The riskiest single step remains section 4's
kernel command-line edit -- not because the instructions are wrong, but
because it's the one place a small mistake has an outsized consequence
(a Pi that won't boot), on a guide otherwise written for people who
haven't done this kind of thing before.
