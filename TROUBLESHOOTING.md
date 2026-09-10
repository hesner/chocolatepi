# Troubleshooting

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

## A footswitch does nothing -- no video, no audio, no error

This is almost always a silent "empty slot" match failure in
`Library.resolve()`, not a hardware or MIDI problem. Check, in order:

1. **`active_show.txt`** on the USB root -- does its content exactly
   match a real folder name under the USB root?
2. **The `Set N` folder** -- does it exist for the group this footswitch
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
overlay first (`sudo raspi-config nonint do_overlayfs 1`, reboot), make
and verify your changes, then re-enable it (`do_overlayfs 0` **plus the
`:recurse=0` edit to `cmdline.txt`**, reboot) once done. Forgetting the
`:recurse=0` step re-introduces the emergency-mode bug above.

## Service fails once immediately after boot, then recovers on its own

Expected, not a bug: `RuntimeError: Could not connect to mpv's IPC
socket ... No such file or directory` on the very first start attempt
is a startup-order race (the Python process starts slightly before
`mpv`'s socket is ready). `Restart=always` retries after 5 seconds and
normally succeeds on the second attempt. Only worth investigating
further if it keeps failing repeatedly rather than recovering.

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
