# lyricspot

Live synced lyrics in your terminal for whatever is playing via MPRIS. Colors are extracted from the album art using the bundled `colorthief.py`. Nudge the lyric timing with arrow keys, toggle UI styles with `Y`.

```
## dependencies

- `playerctl` — reads your media player via MPRIS (mpv, vlc, cmus, etc.)
- `colorthief.py` — bundled, no install needed

That's it. No pip installs required.

## install

### AUR (Arch / Artix)

```bash
yay -S lyricspot
# or
paru -S lyricspot
```

### manual

```bash
git clone https://github.com/vlensys/lyricspot
cd lyricspot
ln -sf "$(pwd)/lyricspot.py" ~/.local/bin/lyricspot
chmod +x lyricspot.py
```

Make sure `~/.local/bin` is in your PATH. In fish:

```fish
fish_add_path ~/.local/bin
```

## running

```bash
lyricspot
```

## controls

| key | action |
|-----|--------|
| `Y` | toggle UI style (minimal / classic) |
| `↑` / `↓` | shift lyrics ±0.25s |
| `u` | toggle header UI |
| `c` | toggle centered lyrics |
| `d` | toggle dynamic album colors |
| `b` | toggle bold on current lyric |
| `U` | toggle uppercase on current lyric |
| `i` | toggle dim on inactive lyrics |
| `Q` / `Esc` | quit |

## tuning

If lyrics feel ahead or behind, use `↑` and `↓` while the song is playing. The offset shows live in the top right. Settings persist across sessions in `~/.config/lyricspot/settings.json`.

To reset all settings:

```bash
lyricspot --reset
```

## notes

- Works with any MPRIS-compatible player: mpv, vlc, cmus, rhythmbox, etc.
- Lyrics are fetched from [lrclib.net](https://lrclib.net)
- Tested on Arch and Artix. Report issues in [issues](https://github.com/vlensys/lyricspot/issues).
