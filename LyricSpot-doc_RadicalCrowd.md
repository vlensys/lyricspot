# lyricspot

Terminal lyrics viewer with audio visualizer.

**Requires:** Python 3.8+, `playerctl`, `parec`, `pactl`, 256-color terminal.

---

## Overview

lyricspot fetches synced lyrics from lrclib.net for the currently playing track and highlights the active line in real time. An audio visualizer runs at the bottom of the screen using PulseAudio loopback data.

---

## Running

```
python lyricspot.py
```

**Flags:**

| Flag | Description |
|------|-------------|
| `--cache on\|off` | Enable or disable lyrics caching (default: `on`) |
| `--reset` | Delete all saved settings and cache |
| `--clear` | Delete only the lyrics cache |

---

## How It Works

### Lyrics Fetching

On each track change, lyricspot queries lrclib.net using multiple strategies in order:

1. Direct lookup by title, artist, album, and duration
2. Search by title and artist
3. Broad query search

Results are scored by metadata similarity and cached at `~/.config/lyricspot/cache.json`.

### Lyrics Sync

lyricspot polls playback position via `playerctl` every ~700ms with smoothing applied to reduce jitter. The active line is found by binary search over the LRC timestamp list. A gap of more than 8 seconds between lines triggers a `> ...` break indicator.

### Audio Visualizer

A background thread reads stereo PCM audio from the PulseAudio sink monitor. It applies a Hamming window and runs a pure-Python FFT to compute frequency magnitudes, which are bucketed into logarithmic bands and rendered as vertical bars. When loopback capture fails, it falls back to an animated sine wave simulation.

---

## Configuration

Settings auto-save to `~/.config/lyricspot/settings.json` every 2 seconds. All settings are toggled at runtime with keybinds.

| Setting | Default | Description |
|---------|---------|-------------|
| `offset` | `0.0` | Lyric timing offset in seconds. Positive = earlier, negative = later. |
| `header` | `true` | Show header bar with title, artist, and offset. |
| `center` | `true` | Center lyrics horizontally. |
| `upper` | `false` | Display active lyric line in uppercase. |
| `bold` | `true` | Render active lyric line in bold. |
| `visualizer` | `true` | Enable the audio visualizer. |
| `visualizer_type` | `bars` | Visualizer style: `bars`, `wave`, `retro`, `dots`. |
| `visualizer_source` | `loopback` | Audio source: `loopback` or `mock`. |
| `visualizer_theme` | `cyber` | Color theme: `cyber`, `classic`, `fire`, `grayscale`. |
| `visualizer_height` | `6` | Visualizer height in rows. Range: 3 to 15. |

---

## Keybinds

### General

| Key | Action |
|-----|--------|
| `q` / `Q` / `Esc` | Quit |
| `Up` | Increase lyric offset by 0.25s |
| `Down` | Decrease lyric offset by 0.25s |
| `u` | Toggle header bar |
| `c` | Toggle centered / left-aligned lyrics |
| `b` | Toggle bold on active lyric line |
| `U` | Toggle uppercase on active lyric line |

### Visualizer

| Key | Action |
|-----|--------|
| `v` | Toggle visualizer on or off |
| `V` | Cycle type: `bars` > `wave` > `retro` > `dots` |
| `t` | Cycle theme: `cyber` > `classic` > `fire` > `grayscale` |
| `l` | Cycle layout: `center` > `stereo` > `bars` |
| `a` | Toggle audio source between `loopback` and `mock` |
| `+` | Increase visualizer height (max 15) |
| `-` | Decrease visualizer height (min 3) |

---

## Visualizer Detail

### Types

| Type | Description |
|------|-------------|
| `bars` | Filled block bars with fractional heights using Unicode block characters. |
| `wave` | Only the top edge of each bar is drawn, producing a waveform outline. |
| `retro` | ASCII bars using `#`, `=`, and `-`. No Unicode required. |
| `dots` | Single bold dot at the tip of each bar only. |

### Layouts

| Layout | Description |
|--------|-------------|
| `center` | Left and right channels mirror outward from the screen center. |
| `stereo` | Left channel on the left half, right channel on the right half. |
| `bars` | Channels averaged and rendered as a single full-width bar set. |

### Themes

| Theme | Colors |
|-------|--------|
| `cyber` | Cyan to magenta. |
| `classic` | Green > yellow > red. |
| `fire` | Dark red > orange > bright yellow. |
| `grayscale` | Dark gray to white. |

### Peak Indicators

Each bar tracks a peak that rises instantly and decays at 4 units/second. A marker renders above the bar at the peak position in `bars`, `retro`, and `dots` modes.

---

## Files

| Path | Contents |
|------|----------|
| `~/.config/lyricspot/settings.json` | Runtime settings. Auto-saved every 2 seconds. |
| `~/.config/lyricspot/cache.json` | Cached lyrics keyed by title, artist, and duration. |

---

## Troubleshooting

**Lyrics not found**
lrclib.net does not index every release. The failed lookup is cached. Run `--clear` to remove it and retry.

**Visualizer shows animation instead of real audio**
`parec` or `pactl` is missing, or the audio server is not running. Press `a` to switch to `mock` mode. Test with:
```
pactl get-default-sink
```

**Lyrics are consistently early or late**
Use `Up` / `Down` to adjust offset in 0.25s steps. The current offset shows in the top-right corner of the header and saves automatically.

**No output at all**
`playerctl` must be installed and a supported media player must be running. Test with:
```
playerctl metadata
```
