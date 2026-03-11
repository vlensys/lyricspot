# lyricspot

Live synced lyrics in your terminal, pulled from whatever is playing on Spotify. Colors are extracted from the album art. Toggle to your terminal's native palette with `Y`, nudge the lyric timing with arrow keys.

```
 ♪  Redbone
    Childish Gambino
 ──────────────────────────────────── 1:24 / 5:26
                    [Y] dynamic  [↑/↓] offset:+0.35s  [Q] quit  ◉
────────────────────────────────────────────────────────────────────
     Oh, stay woke
     Niggas creepin'
  ▶  THEY GON' FIND YOU
  ▶  THEY GON' FIND YOU
     Gon' catch you sleepin'
```

## dependencies

```bash
python -m venv ~/.venv/lyricspot
source ~/.venv/lyricspot/bin/activate.fish  # fish
# source ~/.venv/lyricspot/bin/activate     # bash/zsh
pip install spotipy pillow colorthief
```

`pillow` and `colorthief` are optional. Without them dynamic colors are disabled.

## spotify setup

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Create an app
3. In app settings add this redirect URI: `http://127.0.0.1:8888/callback`
4. Run the script once with no credentials set and it will walk you through the rest

On first run lyricspot detects your shell, asks for your Client ID and Secret, and writes the correct export syntax directly to your config file (`config.fish`, `.zshrc`, or `.bashrc`). After that, reload your config and run again.

## running

The cleanest way is a small launcher script so you never have to activate the venv manually:

```bash
echo '#!/bin/bash' > run.sh
echo 'VENV="$HOME/.venv/lyricspot/bin/python"' >> run.sh
echo 'SCRIPT="$(realpath "$0" | xargs dirname)/lyricspot.py"' >> run.sh
echo '"$VENV" "$SCRIPT"' >> run.sh
chmod +x run.sh
ln -sf (pwd)/run.sh ~/.local/bin/lyricspot
```

Then just run:

```bash
lyricspot
```

Alternatively, if you are on an arch-based distro you can download it straight from the AUR 
```
# for yay
yay -S lyricspot
# or maybe for paru
paru -S lyricspot
```
(please note that ive only tested this with arch and artix. (please report issues in... issues)


Make sure `~/.local/bin` is in your PATH. In fish:

```fish
fish_add_path ~/.local/bin
```

## controls

| key | action |
|-----|--------|
| `Y` | toggle dynamic album colors / terminal colors |
| `↑` or `+` | shift lyrics forward 0.25s |
| `↓` or `-` | shift lyrics back 0.25s |
| `Q` / `Esc` | quit |

## tuning

If lyrics feel ahead or behind, use `↑` and `↓` while the song is playing to dial in the offset live. The current value shows in the top right of the UI. To make a new default permanent, change `SYNC_OFFSET` at the top of `lyricspot.py`.
