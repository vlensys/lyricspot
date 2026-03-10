# lyricspot

Live synced lyrics in your terminal, pulled from whatever is playing on Spotify.
Colors are extracted from the album art and applied in real time. Toggle to your terminal's native palette with `Y`, nudge the lyric timing with arrow keys.

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

## install

```bash
python -m venv ~/.venv/lyricspot
source ~/.venv/lyricspot/bin/activate.fish  # fish shell
# source ~/.venv/lyricspot/bin/activate     # bash/zsh
pip install spotipy pillow colorthief
```

`pillow` and `colorthief` are optional. Without them dynamic colors are disabled and it falls back to your terminal palette.

## spotify setup

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Create an app
3. In app settings add this redirect URI: `http://127.0.0.1:8888/callback`
4. Copy your Client ID and Client Secret
5. Set them before running:

```fish
set -x SPOTIPY_CLIENT_ID "your_id_here"
set -x SPOTIPY_CLIENT_SECRET "your_secret_here"
set -x SPOTIPY_REDIRECT_URI "http://127.0.0.1:8888/callback"
```

A browser window will open on first run asking you to authorize. After that the token is cached automatically.

## run

```bash
python lyricspot.py
```

## controls

| key | action |
|-----|--------|
| `Y` | toggle dynamic album colors / terminal colors |
| `↑` or `+` | shift lyrics forward by 0.25s |
| `↓` or `-` | shift lyrics back by 0.25s |
| `Q` / `Esc` | quit |

## launcher (optional)

Save this as `lyricspot` somewhere in your `$PATH` like `~/.local/bin/`:

```bash
#!/bin/bash
source ~/.venv/lyricspot/bin/activate
python /path/to/lyricspot.py
```

Then `chmod +x ~/.local/bin/lyricspot` and you can run it from anywhere without activating the venv first.
