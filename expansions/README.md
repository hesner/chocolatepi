# Expansions

*[Leer en español](../docs/es/expansions/README.md)*

An **expansion** is an optional, self-contained addon to the base
pedal system (`src/core/`, `src/adapter/`, `src/mapper/`,
`pedal-core.service` -- everything described in
`MASTER_SPECIFICATION.md`). The base system works identically whether
or not any expansion is ever installed. Installing or removing one
expansion never touches, depends on, or is affected by any other
expansion.

## The model

Each expansion lives entirely under `expansions/<name>/`, with its own:

```
expansions/<name>/
├── SPECIFICATION.md       Design doc: architecture, decisions, why
├── USAGE.md                End-user usage guide (en)
├── docs/es/USAGE.md         ...and its Spanish translation
├── src/                    Its own code
├── systemd/                 Its own systemd unit files (template placeholders)
├── scripts/
│   ├── install.sh           Installs it -- never run automatically
│   └── rollback.sh          Uninstalls it -- stops/removes its services only
└── tests/                   Its own tests, run independently of the base suite
```

Consequences of this shape, deliberately:

- **Nothing in `src/core/`, `src/adapter/`, `src/mapper/`, or
  `pedal-core.service` ever imports from, references, or depends on
  anything under `expansions/`.** The base system has no idea any
  expansion exists.
- **An expansion may depend on the base project's own `src/`** (e.g.
  reading `core.library`'s file-extension constants as a single source
  of truth) -- that's a normal addon-depends-on-host-app relationship.
  **An expansion must never depend on another expansion.** If two
  expansions happen to solve overlapping problems, they duplicate the
  code they need rather than reference each other's folder.
- **Nothing is installed automatically.** The base `systemd/README.md`
  setup never enables an expansion's services; that's always a
  separate, deliberate `sh expansions/<name>/scripts/install.sh` step.
- **`rollback.sh` never touches git state.** It only stops/disables the
  expansion's own systemd services and removes their unit files. It
  deliberately does *not* `git checkout` anything -- doing so could
  collaterally revert a different expansion or unrelated base-project
  work added after this expansion's own history began. An expansion's
  source files are inert on disk once its services are gone; deleting
  the folder (`rm -rf expansions/<name>`) is a separate, optional,
  manual step if you want it fully gone from the checkout too.
- **Each expansion's tests run independently**:
  `python -m unittest discover -s expansions/<name>/tests`. CI
  (`.github/workflows/tests.yml`) runs the base suite and every
  expansion's suite as separate steps, so one failing expansion's tests
  don't hide a base-project regression or vice versa.

## Current expansions

| Expansion | What it does | Status |
|---|---|---|
| [`setlist-admin-usb`](setlist-admin-usb/USAGE.md) | Manage the library USB (shows/Sets/tracks) from a phone's browser, reachable by plugging the phone into the Pi over USB (Android tethering / iPhone Personal Hotspot over cable) | Implemented, not yet validated on real hardware |
| [`setlist-admin-wifi`](setlist-admin-wifi/USAGE.md) | The same library management, plus Pi WiFi configuration (home network / phone hotspot fallback), reachable over WiFi | Implemented and unit-tested; real-hardware validation shelved on a dead USB WiFi dongle (hardware, not design/code) |

Both were designed to stay convergeable: `setlist-admin-usb` reuses
`setlist-admin-wifi`'s CRUD backend and frontend UX unchanged, only
replacing the connectivity layer underneath. See each one's
`SPECIFICATION.md` for the full reasoning.
