# SETLIST ADMIN SPECIFICATION — "Chocolate Pi" companion admin app

**Status: draft for review — not approved, not implemented.** Mirrors
`MASTER_SPECIFICATION.md`'s own process: this document is proposed,
discussed, and approved before any code is written (section 6 of that
file).

---

## 1. What this is

A web app, running on the Raspberry Pi itself, for managing the library
USB's content (shows, Sets, tracks) and the Pi's own WiFi connectivity,
from a phone or computer's browser — instead of the manual SSH +
`nano`/file-copy workflow this project has used until now.

**Explicitly not a replacement for `pedal-core.service`** -- a
completely separate service, separate concern, lower priority for CPU
than live playback, never allowed to affect it.

## 2. Decisions approved so far

| Area | Decision |
|---|---|
| Scope | Full CRUD: rename/reorder tracks, create/rename/delete `Set` folders, upload/delete track files, switch the active show |
| When it's usable | Pre/post-show only, by policy -- not designed or tested for use during an active performance (matches the existing "no live library hot-swap" decision in `systemd/README.md`) |
| Authentication | Required -- a single shared PIN, not per-user accounts. Recovery via SSH (section 5a) if forgotten |
| Backend | Python standard library only (`http.server`/`socketserver`), no `pip install`, no new apt package for the web framework itself -- consistent with the rest of `src/` |
| Frontend | Vanilla HTML/CSS/JS, mobile-first responsive, no build step, no framework |
| Home WiFi credential storage | Encrypted, on the library USB (survives reboots; the root overlay does not). Encryption via `openssl` (already installed) invoked as a subprocess, not a new Python crypto dependency |
| Encryption key | Derived from this specific Pi's `/etc/machine-id` + the library USB's own UUID (see section 5) -- the credential file is useless off this exact Pi/USB pairing |
| Network strategy | The app's own watchdog is the source of truth for which WiFi to (re)apply each boot, not NetworkManager's own persisted state (which lives under the overlaid `/etc` and would not survive a reboot) |

## 3. Why this needs its own design pass, not just "add a web server"

Three real conflicts with already-established, hard-won project
decisions, found by analysis before writing any code:

1. **The library USB is always mounted `ro` during normal operation**
   (a deliberate policy). This app needs write access. Resolved by the
   same remount-`rw`/act/remount-`ro` pattern already used manually all
   project long -- see section 6.
2. **`/etc/NetworkManager/system-connections/` lives under the
   read-only root overlay.** `recurse=0` (the fix from the
   emergency-mode bug, see `TROUBLESHOOTING.md`) only stops *other
   mounts* from being wrapped in their own overlay -- it does nothing
   for paths inside `/` itself. Any WiFi profile added via `nmcli`
   while the overlay is active is RAM-only and gone on reboot, exactly
   like the pre-`recurse=0` `/media/usb` bug. This is why WiFi
   credentials must live on the USB and get reapplied at every boot
   (section 5), not rely on NetworkManager remembering them itself.
3. **"Editing the library while the show is running" was already
   explicitly rejected** as a supported workflow (`systemd/README.md`).
   This app, by definition, makes editing far easier and more tempting
   mid-event -- the pre/post-show-only decision (section 2) is what
   keeps this app from silently reopening that already-closed question.

## 4. Architecture

```
Phone/PC browser
      │  HTTP, PIN-authenticated session
      ▼
setlist-admin.service  (new, separate from pedal-core.service)
      │
      ├─ static/            vanilla HTML/CSS/JS, mobile-first
      ├─ api.py             JSON endpoints: shows/sets/tracks CRUD,
      │                     active show, WiFi status/config
      ├─ auth.py            PIN check + signed session cookie
      │                     (stdlib hmac/secrets/hashlib only)
      ├─ library_ops.py     the actual filesystem operations --
      │                     enforces LIBRARY.md's naming rules
      │                     server-side (no more hand-typed filenames)
      └─ wifi.py            wraps nmcli; reads/writes the encrypted
                             credential file on the USB via openssl

pedal-network-watchdog.service  (new, runs continuously, very light)
      │
      ├─ at boot and periodically: decrypts + (re)applies WiFi
      │  profiles to NetworkManager via nmcli, home-network priority
      │  over phone-hotspot fallback
      └─ starts/stops setlist-admin.service based on whether there's
         an actual usable IP -- no network, no admin server running,
         no wasted RAM/CPU
```

`pedal-core.service` is untouched by any of this -- no shared code path
with the MIDI-driven playback loop, only the same filesystem (the
library USB) as a shared resource, mediated by the `ro`/`rw` remount
discipline in section 6.

## 5. WiFi credential storage and network flow

On the library USB, a new file: `.setlist-admin/network.enc` (dotfile
directory so it doesn't show up as a "track" to anything scanning
`Set N/` folders).

**Encryption**: `openssl enc -aes-256-gcm -pbkdf2` (subprocess call),
key derived as `sha256(machine_id + usb_uuid)`. Both inputs are already
knowable to anything with SSH access to this Pi with this USB inserted
-- the real value isn't secrecy from someone who's fully compromised
the running system, it's that **the file is useless if the USB alone is
lost, copied, or plugged into a different Pi**.

**Boot-time flow** (`pedal-network-watchdog.service`, starts early,
independent of whether the USB or a network is even present yet):

1. Ensure the phone-hotspot profile exists and is applied via `nmcli`
   (credentials for this one are set once during initial setup --
   `systemd/README.md` gets a new section for this -- and stored the
   same encrypted way on the USB for consistency, not hardcoded).
2. If the library USB is present and `.setlist-admin/network.enc` decrypts
   successfully (i.e. it's genuinely this Pi/USB pairing), apply the
   home-WiFi profile too, at higher `autoconnect-priority` than the
   hotspot.
3. Poll actual connectivity (has a usable IP, not necessarily internet)
   every 30s. Prefer home WiFi when reachable; fall back to the hotspot
   automatically otherwise -- NetworkManager's own priority mechanism
   handles the retry/switch once both profiles exist, this watchdog's
   job is making sure they *exist* every boot (given point 2 in section
   3) and reacting to sustained total connectivity loss.
4. `setlist-admin.service` is started only while step 3 reports a usable
   IP; stopped otherwise.

**Setting the home WiFi from the app**: the admin UI's WiFi page posts
the new SSID/password, the backend re-encrypts and overwrites
`.setlist-admin/network.enc` on the USB (temporary `rw` remount, same as
any other library write -- section 6), then applies it immediately via
`nmcli` rather than waiting for the next boot.

### 5a. PIN recovery

The PIN's hash lives in the same `.setlist-admin/` directory on the USB
(`.setlist-admin/pin.hash`, salted, via `hashlib` -- this one's just a
hash, not a secret to decrypt, so no `openssl` step needed here).

**If forgotten**: there is no "email me a reset link" -- this is a
local appliance with no account system. Recovery is via the same SSH
access the whole rest of this project already treats as the ultimate
admin channel:

```
ssh pedal
sudo mount -o remount,rw /media/usb
rm /media/usb/.setlist-admin/pin.hash
sudo mount -o remount,ro /media/usb
```

With `pin.hash` missing, `setlist-admin` treats its next visit as first-run
and prompts to set a new PIN before allowing anything else. This adds
no new attack surface -- whoever already has SSH access to the Pi
already has unrestricted access to everything the PIN would have
protected anyway (the library USB itself, mounted `rw` on demand,
exactly like this).

## 6. Concurrency and the read-only USB

Every write operation (library edit or WiFi credential update) follows
the same short-lived sequence, wrapping the exact manual steps this
project has used by hand all along:

```
sudo mount -o remount,rw /media/usb
<single filesystem operation>
sudo mount -o remount,ro /media/usb
```

The `rw` window stays open only for the duration of one logical
operation (one rename, one file upload completing, one credential
update) -- not for the whole time the app is open. `Library.resolve()`
reads the filesystem fresh on every footswitch press (confirmed in
`src/core/library.py` -- no caching), so a change should be visible to
`pedal-core.service` on its very next read, live, no reboot required.
**This needs to be confirmed on real hardware, not assumed** -- see the
test plan in section 8.

Given the pre/post-show-only policy (section 2), true simultaneous
write-during-playback races are out of scope to defend against in v1;
the app should still visibly warn if it detects `pedal-core.service` is
in the middle of active playback (not just running -- actually playing
something other than standby) when an edit is attempted, as a safety
net, not a hard block.

## 7. Resource footprint

- `setlist-admin.service`: `Nice=10` and a cgroup `CPUWeight=` below
  `pedal-core.service`'s default, so if they ever do contend for CPU,
  playback wins without question.
- Idle cost when no one's using the app: a `ThreadingHTTPServer`
  blocked on `accept()` is effectively zero CPU. The real cost is
  RAM (a Python process's baseline footprint) and the network watchdog's
  periodic `nmcli`/connectivity checks -- both need to be measured on
  the real Pi 2 (1GB RAM total), not assumed acceptable.
- Not starting `setlist-admin.service` at all when there's no usable
  network (section 5, step 4) directly avoids paying that RAM cost on
  every boot regardless of whether anyone ever connects.
- File uploads are streamed to disk (chunked, never buffering a whole
  video in RAM) -- required given total system RAM, not optional.

## 8. Testing strategy

**Unit tests (no hardware, `tests/test_admin_*.py`, same style as
existing `tests/`)**:
- `library_ops.py`'s operations against a temp directory (rename,
  create/delete Set, reorder) -- including that it's impossible to
  produce a filename that violates `LIBRARY.md`'s naming rule through
  the API, closing off the whole silent-failure class of bug by
  construction.
- Encrypt/decrypt round-trip of the WiFi credential file (mocking the
  key-derivation inputs).
- Auth/session logic (PIN check, session expiry, rejecting unauthenticated
  API calls).
- API route logic with a mocked filesystem/mocked `nmcli` calls.

**Hardware validation (documented in `TESTING.md`-style entries, same
rigor as the original section 4.0 audio+video test)**:
- Resource impact: CPU/RAM with the admin service idle vs. actively
  serving vs. mid-upload, confirmed against a baseline with
  `pedal-core.service` alone.
- Network fallback: physically disable home WiFi, measure real time to
  fall back to the hotspot; re-enable, measure time to switch back.
- Cold boot with no known network in range at all: confirm
  `setlist-admin.service` never starts, no crash-restart loop, no wasted
  resources.
- End-to-end library edit: reorder/rename a track via the app, confirm
  whether `pedal-core.service` picks it up on the next footswitch press
  without a reboot, exactly as section 6 predicts -- document the real
  result either way.
- Security: confirm the PIN actually gates access; confirm
  `.setlist-admin/network.enc` isn't readable as plaintext; confirm a copy
  of that file on a different Pi/USB fails to decrypt.

## 9. Decided this round

- **Naming**: `setlist-admin` for the service/module names in code
  (not user-facing).
- **PIN mechanism**: a single shared PIN, not per-user accounts.
  Recovery via SSH -- section 5a.
- **Upload-time codec validation**: the app runs `ffprobe` on any
  uploaded video and warns (not blocks) if it's not H.264, pointing at
  `LIBRARY.md`'s guidance. Auto-transcoding on upload stays a later
  phase, not v1.
- **Repo location**: inside the existing `chocolatepi` repo
  (`src/admin/` + a new `setlist-admin.service` /
  `pedal-network-watchdog.service` under `systemd/`), not a separate
  repository -- it shares `Library`'s data model and the same target
  hardware.

**No open items remain from this specification.**

## 10. Deferred task: consolidated setup script (test at the end)

Decided direction (not scope of v1's build, tracked here so it isn't
lost): once `setlist-admin` itself is built, tested, and running on the
real Pi, consolidate `REBUILD.md`'s manual phases 3-8 (install
packages, clone the repo, detect the USB UUID, write the `/etc/fstab`
line, install the `.service` files, enable the overlay) into a single
setup script run once over SSH after first boot -- no custom OS image,
still the stock Raspberry Pi Imager flow from `systemd/README.md`
section 0. With `setlist-admin` already in place, that same script can
end by prompting for the PIN and the phone-hotspot WiFi credentials,
covering the "choose parameters during installation" goal without the
staleness risk of maintaining a separate pre-built image (option A,
rejected for now -- see the discussion this section resolves).

**To do, after `setlist-admin` is certified working:**
- [ ] Write `scripts/setup.sh` (or similar) consolidating those phases.
- [ ] Test it end to end on a genuinely fresh SD card / fresh Pi.
- [ ] Update `REBUILD.md` to point to it as the fast path, keeping the
      manual phases as the documented fallback/explanation of what it
      automates.
