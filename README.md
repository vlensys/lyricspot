# lyricspot
A lightweight terminal tool that live-syncs song lyrics with whatever you’re playing. 
<img width="2553" height="1561" alt="image" src="https://github.com/user-attachments/assets/73d9c495-fbc4-4c68-b75f-eecd7f2b09bc" />

# install

```

### AUR
```
# just install from the AUR!
yay -S lyricspot
```

### dependencies
```
# arch/arch based
pacman -S playerctl
# nix os
nix-env -iA nixpkgs.playerctl
# debian based
sudo apt install playerctl

### manual

```bash
git clone https://github.com/vlensys/lyricspot
cd lyricspot
ln -sf "$(pwd)/lyricspot.py" ~/.local/bin/lyricspot
chmod +x lyricspot.py
```
The bundled colorthief is optional, needed for dynamic colors.

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
