# Library USB — folder and file naming

*[Leer en español](docs/es/LIBRARY.md)*

How to organize the library USB drive so `Library.resolve()`
(`src/core/library.py`) actually finds what you put on it. This isn't
enforced by any tool -- get a name wrong and the track is silently
treated as an empty slot (no error, nothing plays when the footswitch is
pressed). Read this before editing the library, not after a show goes
wrong.

## Structure

```
<USB root>/
├── active_show.txt          -- plain text, one line: the active show's folder name
├── standby.mp4               -- looped when nothing is playing
├── _Songs/                    -- recommended: the band's master song library (see below)
│   ├── song name.mp3
│   └── another song.mp4
└── <Show Name>/               -- e.g. "Live", one folder per show/setlist collection
    ├── Set 1/
    │   ├── A - song name.mp3
    │   ├── B - another song.mp4
    │   └── C - a third one.wav
    ├── Set 2/
    │   └── ...
    └── Set N/
```

- **`active_show.txt`**: its content (trimmed) must exactly match a
  folder name directly under the USB root. If it points to a folder
  that doesn't exist, or is empty/unreadable, the standby fallback plays
  instead of any real content.
- **`Set N/`**: `N` is the setlist number, matching the controller group
  (see `MAVAVE_ANALYSIS.md` for how a group number maps to `N` for the
  M-VAVE PD41 specifically). Folder names are matched exactly as `Set `
  followed by digits -- `Set 1`, `Set 12`, not `set 1`, `Set1`, or `Set 01`.
- **Track files**: exactly one file per letter, `A`/`B`/`C` (footswitch
  `D` is always STOP -- it never needs a file). An empty slot (no file
  for a letter) is normal and expected, not an error.
- **`_Songs/`** and anything else starting with `_`: reserved, never
  treated as a Show. `Library.resolve()` (`src/core/library.py`) never
  even lists the USB root's contents -- it only ever reads
  `active_show.txt` and looks inside that one named folder -- so `_Songs/`
  is completely invisible to playback no matter what's in it. See the
  next section for what it's for.

## Recommended: keep a master song library in `_Songs/`

Put **every song the band has** -- not just the ones in the current
setlist -- as plain files directly under `_Songs/` at the USB root,
named `<song name>.<extension>` (no `<Letter> - ` prefix here; that
prefix only means something inside a `Set` folder, where it marks
*which footswitch position* plays the file). This is the band's
complete, standing song library, independent of any one show.

To build or edit an actual setlist: **copy** (don't move) the specific
songs a given show needs from `_Songs/` into that show's `Set N/`
folders, adding the `<Letter> - ` prefix as you go. `_Songs/` keeps its
copy untouched, so the same song is one copy away from reuse in the
next setlist too, without re-encoding or re-transferring it.

**Never delete a song from `_Songs/` unless you're sure.** Treat it as a
permanent, append-only record of everything the band has ever had ready
to play -- even a song currently unused in any active show is worth
keeping there, both so nothing has to be re-sourced/re-encoded from
scratch later and so `_Songs/`'s file count is always an honest answer
to "how many songs does the band actually have."

What deleting from `_Songs/` actually does and doesn't affect:
- It **does** mean that song can no longer be picked when putting
  together a future `Set` -- it simply won't be there to choose from
  anymore.
- It does **not** touch any `Set` that already has a copy of that song
  assigned to a letter -- that copy is a completely separate file, made
  at the moment it was assigned, so it keeps playing normally regardless
  of what later happens in `_Songs/`.
- Removing a show or a `Set` never touches `_Songs/` either, in the
  other direction (same reasoning: independent copies, not the same
  file).

This is a discipline to keep on your own -- nothing on the USB enforces
it. If using the optional `setlist-admin` expansions, the app's own
delete confirmation repeats this warning before it lets you delete a
song from the library.

If you're using the optional `setlist-admin` expansions
(`expansions/setlist-admin-usb/` or `expansions/setlist-admin-wifi/`),
this whole workflow is automated: uploading a song anywhere adds it to
`_Songs/` automatically, and assigning a `Set` slot from the library is
a one-tap copy instead of a manual `cp`. Same convention either way --
this section describes what the app is actually doing under the hood,
and what to do by hand if you're not using it.

## The one rule that actually matters: the filename pattern

```
<Letter> - <anything>.<extension>
```

**Exactly one space before the dash, one space after it.** The letter
must be immediately followed by ` - ` (space, dash, space), then any
name, then a supported extension:

- Audio-only (loops standby underneath, audio plays over it): `.mp3`, `.wav`
- Video with embedded audio: `.mp4`, `.mov`, `.mpeg`, `.mpg`

Case doesn't matter for the letter or the extension (`a - x.MOV` matches
fine). The only thing that has to be exact is that single space on each
side of the dash.

**This is the single easiest mistake to make**, and it fails completely
silently -- no error anywhere, the footswitch just does nothing, because
an unmatched filename looks identical to an intentionally empty slot.

```
A - my song.mp3        <- correct
A  - my song.mp3       <- WRONG (two spaces before the dash) -- silently ignored
A- my song.mp3         <- WRONG (no space before the dash) -- silently ignored
A -my song.mp3         <- WRONG (no space after the dash) -- silently ignored
```

**Safest way to avoid this**: don't type a new filename from scratch.
Duplicate an existing, already-working track file in the same or another
`Set` folder and rename only the part after ` - `, so the ` - ` itself
is never retyped.

If a track won't play and everything else looks right (file is really
there, right `Set` folder, right show active), rename the file to
double-check spacing first before assuming it's a codec or hardware
problem.

## Recommended encoding for phone-sourced video

`Set` folder videos are decoded in hardware (`mpv --hwdec=v4l2m2m-copy`
on the Raspberry Pi 2), which only supports **H.264**. Camera apps --
especially iPhone's -- default to settings this hardware can't touch at
all. Before copying phone footage into the library, re-encode it to:

| Setting | Recommended | Why |
|---|---|---|
| Video codec | H.264 (`libx264`) | The only codec this hardware decodes; `MASTER_SPECIFICATION.md`'s "Video" row |
| Pixel format | `yuv420p` (8-bit) | Phone HEVC/HDR footage is often 10-bit; the hardware decoder expects plain 8-bit 4:2:0 |
| Resolution | 1080p max (`scale=-2:1080`) | This project's target output resolution; 4K just adds decode work for no visible gain on an HDMI TV fed 1080p |
| Video bitrate | ~8-12 Mbps for 1080p | Comfortably good quality for a short clip. This is **not** the standby video's situation (`scripts/generate_fallback_standby.sh`'s output and the real `standby.mp4` are both encoded far leaner, around 1.8 Mbps) -- standby loops for the entire show and its file size actually matters; an individual song/video clip on the library USB doesn't have that constraint, so there's no reason to starve it on bitrate too |
| Audio codec | AAC, 44.1 or 48kHz, stereo | `Player` re-forces 48kHz/stereo on output regardless of the source, so the source just needs to be a normal AAC stream, not a specific sample rate |
| Container | `.mp4` | Regardless of the source's original extension -- a `.mov` input encodes to a `.mp4` output fine |

```
ffmpeg -i input.mov -c:v libx264 -pix_fmt yuv420p -vf scale=-2:1080 \
       -b:v 10M -c:a aac -b:a 192k -movflags +faststart "A - song name.mp4"
```

If a video plays fine on a phone/computer but not through the pedal,
check its codec (`ffmpeg -i <file>` shows it on the `Video:` line)
before suspecting the filename, and re-encode with the command above --
a wrong filename and the wrong codec can both be true of the same file
at once, so fixing one doesn't guarantee the other isn't also a problem.
