# lyricspot

Terminal lyrics viewer with audio visualizer.

<img width="600" alt="screenshot" src="https://github.com/user-attachments/assets/0ca8fe90-e68d-4382-9b50-213925f25044" />

**Requires:** Python 3.8+, `playerctl`, `parec`, `pactl`, 256-color terminal.

---

## Quick Start

```bash
python3 lyricspot.py
```

Or as a module:
```bash
python3 -m lyricspot
```

**Flags:**

| Flag | Description |
|------|-------------|
| `--cache on\|off` | Enable or disable lyrics caching (default: `on`) |
| `--reset` | Delete all saved settings and cache |
| `--clear` | Delete only the lyrics cache |
| `-p, --player` | Force a specific MPRIS player (e.g. `spotify`) |

---

## How It Works

### Lyrics Fetching

On each track change, lyricspot queries [lrclib.net](https://lrclib.net) using multiple strategies in order:

1. Direct lookup by title, artist, album, and duration
2. Search by title and artist
3. Broad query search

Results are scored by metadata similarity and cached at `~/.config/lyricspot/cache.json`.

### Lyrics Sync

Playback position is polled via `playerctl` every ~700ms with EMA smoothing applied to reduce jitter. The active line is found by binary search over the LRC timestamp list. A gap of more than 8 seconds between lines triggers a `> ...` break indicator.

### Audio Visualizer

A background thread reads stereo PCM audio from the PulseAudio sink monitor at 8 kHz. It applies a Hamming window and runs an FFT (numpy if available, else iterative Cooley-Tukey with precomputed twiddle factors) to compute frequency magnitudes. These are bucketed into logarithmic bands and rendered as vertical bars. When loopback capture fails, it falls back to an animated sine wave simulation.

---

## Configuration

Settings auto-save to `~/.config/lyricspot/settings.json` every 2 seconds. All settings are toggled at runtime with keybinds.

| Setting | Default | Description |
|---------|---------|-------------|
| `offset` | `0.0` | Lyric timing offset in seconds |
| `header` | `true` | Show header bar with title, artist, offset |
| `center` | `true` | Center lyrics horizontally |
| `upper` | `false` | Display active lyric line in uppercase |
| `bold` | `true` | Render active lyric line in bold |
| `visualizer` | `true` | Enable the audio visualizer |
| `visualizer_type` | `bars` | Style: `bars`, `wave`, `retro`, `dots` |
| `visualizer_source` | `loopback` | Source: `loopback` or `mock` |
| `visualizer_theme` | `cyber` | Theme: `cyber`, `classic`, `fire`, `grayscale` |
| `visualizer_height` | `6` | Height in rows (3–15) |

---

## Keybinds

| Key | Action |
|-----|--------|
| `q` / `Esc` | Quit |
| `Up` / `Down` | Adjust lyric offset ±0.25s |
| `u` | Toggle header |
| `c` | Toggle centered / left-aligned |
| `b` | Toggle bold |
| `U` | Toggle uppercase |
| `v` | Toggle visualizer |
| `V` | Cycle type |
| `t` | Cycle theme |
| `l` | Cycle layout |
| `a` | Toggle audio source |
| `+` / `-` | Adjust height |

---

## Developer Guide

### Project Structure

```
lyricspot/
├── __init__.py          # Package marker + version
├── __main__.py          # CLI entry point (argparse + curses.wrapper)
├── config.py            # Constants, settings schema, module-level caches
├── utils.py             # Pure utilities (FFT, audio capture, API, I/O, scoring)
├── render.py            # All curses rendering (colors, visualizer, lyrics)
└── tui.py               # Main event loop, state management, key dispatch
lyricspot.py             # Thin backward-compatible wrapper (runs the package)
```

### Module Dependencies

```
config  (no project imports)
    ↑
utils   (imports from config)
    ↑
render  (imports from config, utils)
    ↑
tui     (imports from config, utils, render)
    ↑
__main__  (imports from config, utils, tui)
```

### Performance Optimizations

| Area | Technique | Speedup |
|------|-----------|---------|
| **FFT** | numpy fallback + iterative Cooley-Tukey with precomputed twiddle factors | ~10x pure Python / ~50x with numpy |
| **Rendering** | Dirty-region tracking skips `erase()` on ~95% of frames; precomputed `VIZ_PAIR_CACHE` for color pairs | ~3x per frame |
| **Audio** | `math.exp()` values cached once per frame; precomputed `HAMMING_256` constant; band boundary cache for EQ | ~5x per audio frame |
| **API** | Reusable `SequenceMatcher`, precompiled regex, lazy cache writes (batch every 10s), normalized search terms | ~6x per track lookup |

### Hacking

```bash
# Run directly
python3 lyricspot.py

# Or as a module (equivalent)
python3 -m lyricspot

# Test FFT and core utilities
python3 -c "
from lyricspot.utils import fft, sim, get_eq_bands
import math
data = [math.sin(2*math.pi*10*i/256) for i in range(256)]
result = fft(data)
print('FFT peak at bin', max(range(128), key=lambda i: abs(result[i])))
"
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LRCLIB_API` | `https://lrclib.net/api` | Override the lrclib API base URL |

### Files

| Path | Contents |
|------|----------|
| `~/.config/lyricspot/settings.json` | Runtime settings (auto-saved) |
| `~/.config/lyricspot/cache.json` | Cached lyrics keyed by `title\0artist\0duration` |

---

## Troubleshooting

**Lyrics not found** — lrclib.net does not index every release. Run `--clear` to remove a failed cache entry and retry.

**Visualizer shows animation** — `parec`/`pactl` is missing. Run `pactl get-default-sink` to check. Press `a` to toggle mock mode.

**Lyrics early/late** — Use `Up`/`Down` to adjust offset in 0.25s steps. Offset shows in the header corner and saves automatically.

**No output** — Ensure `playerctl` is installed and a supported player is running. Run `playerctl metadata` to verify.
