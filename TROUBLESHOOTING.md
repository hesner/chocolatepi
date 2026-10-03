# Troubleshooting

*[Leer en español](docs/es/TROUBLESHOOTING.md)*

Symptom-first reference. Find what you're seeing, jump straight there.
Every entry here is a real failure this project hit once during its own
development or testing -- not a hypothetical.

## Can't reach the Pi over SSH

**`ssh: Could not resolve hostname <name>.local`, intermittently** --
`.local` (mDNS) resolution is not fully reliable in practice, especially
over WiFi or after the Pi's been physically moved. Not a configuration
mistake to chase; just retry, or get the Pi's real IP from your router's
DHCP client list and connect by IP instead. Prefer Ethernet over WiFi
for setup/debugging sessions if this keeps happening.

**Slow, high-latency, or flaky WiFi generally** -- this project measured
real packet loss and ~200ms latency over WiFi at distance from the
router during its own testing. Move closer, or switch to Ethernet --
there's no software fix for physical WiFi range.

## Boots into "You are in emergency mode" (no SSH, stuck)

This is the read-only-root-overlay bug, and it's serious on a headless
appliance: emergency mode doesn't bring up networking, so SSH is not an
option to fix it remotely -- you need a keyboard and monitor physically
on the Pi, or to boot from the SD card on another machine.

**Cause**: the overlay filesystem's default `recurse=1` wraps *every*
mount (not just `/`) in its own overlay, including `/media/usb` -- and
that auto-generated overlay has no `nofail`. If the library USB is
absent at boot, that overlay mount fails, and since it's boot-critical,
systemd drops to emergency mode instead of continuing.

**Fix**: `/boot/firmware/cmdline.txt` needs `overlayroot=tmpfs:recurse=0`,
not bare `overlayroot=tmpfs`. See `systemd/README.md` section 4 for the
exact steps (it requires remounting `/boot/firmware` read-write
temporarily to edit it). **Gotcha**: every time you disable and
re-enable the overlay (`raspi-config nonint do_overlayfs 1` then `0`)
for future development, `do_overlayfs 0` resets the parameter to bare
`overlayroot=tmpfs` -- you have to redo the `:recurse=0` edit each time,
or this bug comes back.

## Is it safe to just unplug the Pi / what happens on a power cut?

**Short answer: yes, during normal band use.** Right now (confirmed
against the live Pi's `/etc/fstab` and `mount` output), all three
filesystems that matter are either read-only or RAM-backed during
normal operation:

- `/` is an `overlay` whose `upperdir` is `tmpfs` (RAM) -- see
  `systemd/README.md` section 4. Nothing written during normal use ever
  touches the SD card.
- `/boot/firmware` is mounted `ro`.
- `/media/usb` (the library) is mounted `ro`.

Since nothing is actually being written to physical storage while the
band is playing, an abrupt power loss at that moment has nothing to
corrupt.

**The real risk windows** -- all brief, and all outside normal
show-time use:

1. **Editing the library from the admin app (USB or WiFi expansion).**
   The one risk window that happens during ordinary use, not just
   maintenance: `/media/usb` gets remounted `rw` for a fraction of a
   second per write. Already well-mitigated (atomic temp-file writes,
   so the real file is never touched mid-write; self-healing remounts;
   a process-wide lock) -- but a power cut in that exact instant could
   still leave the NTFS volume needing a `chkdsk`, even though song
   content itself stays safe. See "Library changes don't show up" and
   `library_ops.py`'s module docstring.
2. **Deploying/maintaining code on the Pi with the overlay temporarily
   disabled.** The only time `/` becomes a real, writable ext4 instead
   of RAM. Only happens during development, never during band use --
   see "Code/config changes on the Pi disappear after a reboot" below
   and `systemd/README.md` section 4.
3. **Hand-editing `/boot/firmware/cmdline.txt`.** Requires remounting
   `/boot/firmware` `rw` briefly. Same profile as #2 -- maintenance
   only, and already flagged as "the single riskiest edit in this whole
   guide" in `systemd/README.md` section 4.

**The more likely real-world trigger isn't a clean unplug at all --
it's an underpowered supply.** This project directly observed
`vcgencmd get_throttled` showing real under-voltage plus at least one
spontaneous reboot during a single testing session (see "Random freeze,
Undervoltage detected!" below). A marginal power supply can cause
erratic behavior with nobody touching the plug. Use a genuine 5V/2.5A+
supply, and avoid charging a phone from the Pi's own USB port while
it's under load.

## A footswitch does nothing -- no video, no audio, no error

This is almost always a silent "empty slot" match failure in
`Library.resolve()`, not a hardware or MIDI problem. Check, in order:

1. **`active_set.txt`** on the USB root -- does its content exactly
   match a real folder name under the USB root?
2. **The `Bank N` folder** -- does it exist for the group this footswitch
   maps to? (See `MAVAVE_ANALYSIS.md` for the M-VAVE PD41's group
   numbering if that's the controller in use.)
3. **The filename itself** -- `LIBRARY.md` has the full rule, but the
   short version: it must be exactly `<Letter> - name.ext`, one space
   before the dash, one space after, nothing more or less. `A  -
   x.mp4` (two spaces) or `A- x.mp4` (no space) silently fail the same
   way an intentionally empty slot does -- there is no error anywhere
   for this, by design (an empty slot is normal). If in doubt, rename
   the file to eliminate spacing as a variable before assuming
   anything else is wrong.

## A video is misnamed correctly but still won't play

Codec problem, not a naming problem -- these are independent and a file
can have both problems stacked (see `LIBRARY.md`'s worked example: a
`.MOV` with a spacing mistake that was *also* 4K 10-bit HEVC, neither
of which was the cause of the other).

Check with `ffmpeg -i <file>` and look at the `Video:` line. This
hardware only hardware-decodes **H.264**. Phone footage (iPhone
especially) is very often HEVC/H.265 by default, sometimes 10-bit/HDR,
sometimes 4K -- any one of those alone can be enough to fail. Re-encode
per `LIBRARY.md`'s "Recommended encoding for phone-sourced video"
table and command before assuming anything else is broken.

## Audio crackles/pops when switching tracks

If this reappears after previously being fixed, check for these three
independent causes (all were real root causes at different points):

1. **Reloading standby when it's already playing** -- `go_to_standby()`
   must be a no-op if the standby path is already loaded; reloading it
   on every footswitch press causes an audible glitch each time even
   though nothing visibly changes.
2. **Sample rate mismatch** -- confirm `--audio-samplerate=48000
   --audio-channels=stereo` are still being forced on both mpv
   instances (`src/core/player.py`); letting the source dictate the
   rate causes ALSA to reconfigure mid-session, which clicks.
3. **Toggling `aid=no`/`aid=auto`** instead of `mute` -- switching the
   active audio track ID tears down and rebuilds the ALSA connection,
   which clicks. Use `mute true`/`mute false` instead; it doesn't touch
   the underlying stream.

## Brief black screen / console flash when a clip changes

`mpv` needs `--force-window=yes` on the video lane, or the console/login
screen becomes briefly visible underneath during a transition. Also
check that `Player.play()` pre-queues the standby video as an appended
item (`loadfile ... append`) rather than waiting for the clip to end
naturally and reacting afterward -- without the pre-queue, mpv's own
"Drop files or URLs to play here" idle screen flashes for a frame or two
between the clip ending and standby starting.

## No standby video after connecting the HDMI cable after power-on

Expected with the real hardware's HDMI hotplug behavior, not a bug: if
the Pi is powered on with no display connected, the kernel's own DRM
subsystem may not properly bring up the HDMI output even once a cable
is plugged in afterward -- a process that already started rendering
before the display was connected doesn't automatically rebind to it.

**As of 2026-10-03, this self-heals within a few seconds**: the video
lane now only runs while a display is detected connected
(`src/core/display_monitor.py` polls `/sys/class/drm/.../status` every
~2s, confirmed over 2 consecutive agreeing reads before acting --
see "Resource-aware video lane" in `MASTER_SPECIFICATION.md`). Plugging
in HDMI after boot is detected automatically and starts the video lane
fresh, which correctly binds to the now-connected display -- no manual
`systemctl restart pedal-core.service` needed anymore. If it still
doesn't recover within ~10s of connecting the cable, check
`~/pedal-core.log` for "Display connected -- video lane started" to
confirm the monitor actually saw the change; if that line never
appears, confirm the real connector name with `ls /sys/class/drm/` on
the Pi and pass the right one via `--display-status-path` (see
`src/main.py --help`) -- the default assumes `card0-HDMI-A-1`.

For the most reliable experience regardless, still prefer connecting
HDMI **before** powering the Pi on, same as before this fix existed --
this just makes the "connected it after boot" case recover on its own
instead of needing a manual restart.

## Random freeze, "Undervoltage detected!" on screen

Underpowered charger. A generic phone charger (measured: a Chromecast
charger) is not necessarily enough for a Pi 2 doing simultaneous
1080p decode + dual audio streams + a USB hub's worth of peripherals --
confirmed via `dmesg` showing the USB hub repeatedly disconnecting and
reconnecting at boot. Fix: a proper 5V/2.5A supply. Check
`vcgencmd get_throttled` -- a nonzero low bit means undervoltage is (or
recently was) actually happening, not a red herring.

## Library changes don't show up

Editing the USB while the Pi is running and expecting it to pick up
changes live is not supported, by design (see `systemd/README.md`'s
"USB behavior" section for why automatic hot-swap was tried and
abandoned). The approved workflow is: power off, edit the USB on
another computer, reconnect it, power back on. A reboot is *always*
required to pick up a library change, even one made while the Pi was
already off.

## `mount: /media/usb: Read-only file system` when trying to edit directly on the Pi

Expected -- the library USB is deliberately mounted `ro` at all times
except during deliberate management. To edit it directly on the Pi (as
opposed to swapping it to another computer, the normal workflow):
`sudo umount /media/usb && sudo mount -o rw,nofail,x-systemd.device-timeout=10
/dev/sda1 /media/usb` (adjust the device), make changes, then remount
`ro` the same way before leaving it. **If the root overlay is active**,
writes to `/media/usb` land in a RAM-backed overlay layer and are
**discarded on the next reboot** unless you also temporarily disable
the root overlay first (`do_overlayfs 1`, reboot) -- otherwise your
edits will appear to work over SSH and then silently vanish.

## Code/config changes on the Pi disappear after a reboot

The read-only root overlay (`systemd/README.md` section 4) discards
every write to `/` on every reboot, on purpose -- that's the power-loss
protection. If you're actively developing on the Pi itself, disable the
overlay first, make and verify your changes, then re-enable it once done.

**`sudo raspi-config nonint do_overlayfs 1` does not actually disable
it here** -- confirmed live (2026-10-01): its matching logic doesn't
recognize the custom `:recurse=0` suffix this project's `cmdline.txt`
uses, so it leaves the file completely untouched and the overlay stays
active after the reboot, silently discarding whatever you just tried to
deploy. Use the direct edit instead:

```
sudo mount -o remount,rw /boot/firmware
sudo sed -i 's/overlayroot=tmpfs:recurse=0 //' /boot/firmware/cmdline.txt
sudo mount -o remount,ro /boot/firmware
sudo reboot
```

Confirm with `mount | grep ' / '` after reboot: it should show a plain
`ext4 rw` root, not `overlay`. Make and verify your changes, then
re-enable:

```
sudo raspi-config nonint do_overlayfs 0
sudo mount -o remount,rw /boot/firmware
sudo sed -i 's/overlayroot=tmpfs /overlayroot=tmpfs:recurse=0 /' /boot/firmware/cmdline.txt
sudo mount -o remount,ro /boot/firmware
sudo reboot
```

`do_overlayfs 0` strips `:recurse=0` again every time it runs -- always
re-append it by hand before this reboot, or you'll hit the
emergency-mode bug above the next time the library USB isn't present at
boot.

**Deploying several files back onto the Pi?** A loop of individual `scp`
calls has been observed to silently fail to transfer most of them (no
error shown) -- confirmed live. Bundle them into one tarball instead:
`tar czf /tmp/x.tar.gz <files>`, `scp /tmp/x.tar.gz <host>:/tmp/`, then
`ssh <host> "cd <repo> && tar xzf /tmp/x.tar.gz && rm /tmp/x.tar.gz"`.

## Service fails once immediately after boot, then recovers on its own

Usually expected, not a bug: `RuntimeError: Could not connect to mpv's
IPC socket ... No such file or directory` on the very first start
attempt is a startup-order race (the Python process starts slightly
before `mpv`'s socket is ready). `Restart=always` retries after 5
seconds and normally recovers on the second attempt.

**If this repeats for more than a couple of cycles (confirmed live,
2026-10-02: a multi-minute crash-loop)**, it's CPU starvation, not the
normal startup race: `mpv` has up to 20s (`_CONNECT_TIMEOUT_S` in
`src/core/player.py`) to open its socket, but a fresh `mpv` process
spawned while something else is pinning the CPU (confirmed cause: a
`setlist-admin` expansion's "Optimize" job running `ffmpeg` at ~200%)
can still miss even that window. This only bites when `pedal-core.
service` has to *restart* while something else is already CPU-heavy --
normal playback alone never triggers it. If it keeps happening, check
`ps aux` for a competing CPU-heavy process before assuming the timeout
itself needs raising further.

## Audio (and video) stop completely after a while, screen flickering

Real incident, reproduced live while investigating: check first whether
the M-VAVE is actually powered on and connected -- `ssh pedal "lsusb"`
should show a `Jieli Technology SINCO` device (that's the string the
M-VAVE reports, not "M-VAVE" -- see `MAVAVE_ANALYSIS.md`). If it's
missing, `sudo journalctl -u pedal-core.service` will show repeating
`No MIDI input port containing 'SINCO' was found` errors.

**Before this was fixed**, that exact condition (controller off at
startup, or disconnected mid-session -- a loose cable, a USB hub
glitch, or the kind of brief dropout a real undervoltage event causes,
see "Random freeze, Undervoltage detected!" below) made `main.py` exit
entirely, relying on `systemd` to blindly restart the whole process
every 5 seconds -- which also killed and relaunched both `mpv` lanes
each cycle (the screen flickering back to black), with total silence
and nothing to explain why, for as long as the controller stayed
missing. **Now**, `main.py` retries the MIDI connection in-process
without tearing `mpv` down -- standby keeps playing solidly while
waiting, and a footswitch works again the instant the controller
reappears, with no reboot needed. If you still see this behavior,
you're on an older deployed version; redeploy `src/main.py` and
`src/core/player.py` (see `NEXT_STEPS.md`'s "checking versions" note).

If the M-VAVE **is** connected and this still happens, it's likely a
real ALSA/audio-hardware error from `mpv` itself (device busy,
underrun) -- but `mpv`'s own `stdout`/`stderr` are both sent to
`DEVNULL` by design (`core/player.py`), so nothing from `mpv` directly
lands in any log. This was tried the other way once (`stderr` piped
into `pedal-core.log`) and deliberately reverted the same day -- see
`CHANGELOG.md`'s Unreleased entry for why (in short: that log lives in
the RAM-backed root overlay with no rotation, so leaving it on
permanently is a standing RAM-exhaustion risk for a benefit that's only
ever useful during an active debugging session). To get that visibility
back **temporarily** while actively investigating: SSH in, stop
`pedal-core.service`, and run `main.py` by hand in the foreground
without redirecting `mpv`'s output -- or patch `stderr=subprocess.PIPE`
into `_MpvProcess.start()` just for that session and revert it
afterward. Don't leave a permanent stderr-capture patch deployed.

## `chocolatepi.org` doesn't load / no HTTPS

1. Confirm DNS has actually propagated (https://dnschecker.org) before
   assuming anything is broken -- this routinely takes 10-30 minutes.
2. In Cloudflare, the DNS records for the domain must be **DNS-only
   (grey cloud)**, not Proxied (orange) -- GitHub can't validate domain
   ownership or issue a certificate through Cloudflare's proxy.
3. In GitHub repo Settings → Pages, "Enforce HTTPS" stays disabled
   until GitHub's own DNS check passes -- this is downstream of point 1,
   not a separate problem to debug.

## An SSH command with a filename that has multiple/unusual spaces fails with "No such file or directory" even though the file exists

Shell-quoting artifact, not a missing file -- typing an exact double
space (or other unusual whitespace) inside quotes through an SSH
command line does not always survive faithfully depending on the local
shell. Use a glob instead of typing the exact spacing: `ssh host "cat
/path/to/dir/*partial-name*"` rather than trying to reproduce the exact
filename by hand.
