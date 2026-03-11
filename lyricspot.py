#!/usr/bin/env python3

import os, sys, time, threading, signal, urllib.request, urllib.parse, json, io, re
import curses

try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
    HAS_SPOTIPY = True
except ImportError:
    HAS_SPOTIPY = False

try:
    from colorthief import ColorThief
    HAS_COLOR = True
except ImportError:
    HAS_COLOR = False

# config
SPOTIFY_SCOPE     = "user-read-playback-state user-read-currently-playing"
LRCLIB_URL        = "https://lrclib.net/api/get"
POLL_INTERVAL     = 2
SYNC_OFFSET       = 0.85
OFFSET_STEP       = 0.15

LYRICS_CENTERED   = True
SHOW_UI           = True
CURRENT_BOLD      = True
CURRENT_UPPERCASE = True
CURRENT_DOUBLE    = True
CURRENT_STANDOUT  = False
INACTIVE_DIM      = True

CLIENT_ID     = os.environ.get("SPOTIPY_CLIENT_ID",     "YOUR_CLIENT_ID")
CLIENT_SECRET = os.environ.get("SPOTIPY_CLIENT_SECRET", "YOUR_CLIENT_SECRET")
REDIRECT_URI  = os.environ.get("SPOTIPY_REDIRECT_URI",  "http://127.0.0.1:8888/callback")


def rgb_to_256(r, g, b):
    if r == g == b:
        if r < 8:   return 16
        if r > 248: return 231
        return round((r - 8) / 247 * 24) + 232
    return 16 + 36 * round(r/255*5) + 6 * round(g/255*5) + round(b/255*5)

def palette_from_url(url):
    if not HAS_COLOR or not url:
        return None, None
    try:
        req  = urllib.request.urlopen(url, timeout=4)
        ct   = ColorThief(io.BytesIO(req.read()))
        pal  = ct.get_palette(color_count=6, quality=1)
        def sat(c):
            mx, mn = max(c)/255, min(c)/255
            return (mx - mn) / (mx + 1e-9)
        pal_s     = sorted(pal, key=sat, reverse=True)
        primary   = rgb_to_256(*pal_s[0])
        secondary = rgb_to_256(*pal_s[min(2, len(pal_s)-1)])
        return primary, secondary
    except Exception:
        return None, None

def fetch_synced_lyrics(title, artist, album="", duration=0):
    params = urllib.parse.urlencode({
        "track_name":  title,
        "artist_name": artist,
        "album_name":  album,
        "duration":    int(duration),
    })
    try:
        req  = urllib.request.urlopen(f"{LRCLIB_URL}?{params}", timeout=6)
        data = json.loads(req.read())
        if data.get("syncedLyrics"):
            return parse_lrc(data["syncedLyrics"]), True
        if data.get("plainLyrics"):
            return [(0, l) for l in data["plainLyrics"].splitlines()], False
    except Exception:
        pass
    return [(0, "  lyrics not found  ")], False

def parse_lrc(lrc_text):
    lines = []
    for raw in lrc_text.splitlines():
        m = re.match(r'\[(\d+):(\d+\.\d+)\](.*)', raw)
        if m:
            t = int(m.group(1))*60 + float(m.group(2))
            lines.append((t, m.group(3).strip()))
    return sorted(lines, key=lambda x: x[0])


CACHE_DIR  = os.path.expanduser("~/.cache/lyricspot")
CACHE_PATH = os.path.join(CACHE_DIR, ".spotify_cache")


class SpotifyPoller:
    def __init__(self):
        if not HAS_SPOTIPY:
            raise RuntimeError("spotipy not installed")
        os.makedirs(CACHE_DIR, exist_ok=True)
        self.sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
            scope=SPOTIFY_SCOPE,
            cache_path=CACHE_PATH,
        ))

    def now_playing(self):
        try:
            pb = self.sp.current_playback()
            if not pb or not pb.get("is_playing"):
                return None
            item = pb["item"]
            return {
                "title":    item["name"],
                "artist":   ", ".join(a["name"] for a in item["artists"]),
                "album":    item["album"]["name"],
                "duration": item["duration_ms"] / 1000,
                "progress": pb["progress_ms"] / 1000,
                "art_url":  item["album"]["images"][0]["url"] if item["album"]["images"] else None,
                "track_id": item["id"],
            }
        except Exception:
            return None


SETTINGS = [
    ("show ui",           "show_ui"),
    ("lyrics centered",   "lyrics_centered"),
    ("current bold",      "current_bold"),
    ("current uppercase", "current_uppercase"),
    ("current double",    "current_double"),
    ("current standout",  "current_standout"),
    ("inactive dim",      "inactive_dim"),
    ("dynamic colors",    "dynamic"),
]


class LyricSpot:
    def __init__(self):
        self.poller           = SpotifyPoller()
        self.track            = None
        self.lyrics           = []
        self.synced           = False
        self.dynamic          = True
        self.show_ui          = SHOW_UI
        self.lyrics_centered  = LYRICS_CENTERED
        self.current_bold     = CURRENT_BOLD
        self.current_uppercase= CURRENT_UPPERCASE
        self.current_double   = CURRENT_DOUBLE
        self.current_standout = CURRENT_STANDOUT
        self.inactive_dim     = INACTIVE_DIM
        self.col_primary      = None
        self.col_second       = None
        self.offset           = SYNC_OFFSET
        self.lock             = threading.Lock()
        self.running          = True
        self._last_id         = None
        self.settings_open    = False
        self.settings_cursor  = 0

    def _poll(self):
        while self.running:
            t = self.poller.now_playing()
            with self.lock:
                self.track = t
                if t and t["track_id"] != self._last_id:
                    self._last_id = t["track_id"]
                    self.lyrics, self.synced = fetch_synced_lyrics(
                        t["title"], t["artist"], t["album"], t["duration"])
                    self.col_primary, self.col_second = palette_from_url(t["art_url"])
            time.sleep(POLL_INTERVAL)

    def run(self):
        threading.Thread(target=self._poll, daemon=True).start()
        curses.wrapper(self._main)

    def _apply_colors(self):
        if self.dynamic and self.col_primary is not None:
            fg_active = self.col_primary
            fg_dim    = self.col_second if self.col_second else -1
            fg_header = self.col_primary
        else:
            fg_active = fg_dim = fg_header = -1
        curses.init_pair(1, fg_active, -1)
        curses.init_pair(2, fg_dim,    -1)
        curses.init_pair(3, fg_header, -1)

    def _place(self, text, w):
        if self.lyrics_centered:
            x = max(0, (w - len(text)) // 2)
        else:
            x = 0
        return x, text[:max(1, w - x - 1)]

    def _draw_settings(self, scr, h, w):
        panel_w = 36
        panel_h = len(SETTINGS) + 4
        py = max(0, (h - panel_h) // 2)
        px = max(0, (w - panel_w) // 2)

        for row in range(panel_h):
            self._safe_addstr(scr, py + row, px, " " * panel_w, curses.color_pair(3))

        title = "  settings"
        self._safe_addstr(scr, py,     px, title + " " * (panel_w - len(title)), curses.color_pair(3) | curses.A_BOLD)
        self._safe_addstr(scr, py + 1, px, "  " + "─" * (panel_w - 4) + "  ",   curses.color_pair(3))

        for i, (label, attr) in enumerate(SETTINGS):
            val     = getattr(self, attr)
            toggle  = "on " if val else "off"
            row_y   = py + 2 + i
            is_sel  = i == self.settings_cursor
            prefix  = "  ▶ " if is_sel else "    "
            text    = f"{prefix}{label:<22}{toggle}"
            text    = text[:panel_w]
            text   += " " * (panel_w - len(text))
            a = curses.color_pair(3)
            if is_sel: a |= curses.A_BOLD | curses.A_STANDOUT
            self._safe_addstr(scr, row_y, px, text, a)

        hint = "  space/enter: toggle   s: close"
        hint = hint[:panel_w]
        hint += " " * (panel_w - len(hint))
        self._safe_addstr(scr, py + panel_h - 1, px, hint, curses.color_pair(3) | curses.A_DIM)

    def _main(self, scr):
        curses.curs_set(0)
        curses.start_color()
        curses.use_default_colors()
        scr.nodelay(True)
        scr.timeout(80)
        self._apply_colors()

        last_palette = (None, None)

        while self.running:
            key = scr.getch()

            if self.settings_open:
                if key in (ord('s'), ord('S'), 27):
                    self.settings_open = False
                elif key == curses.KEY_UP:
                    self.settings_cursor = (self.settings_cursor - 1) % len(SETTINGS)
                elif key == curses.KEY_DOWN:
                    self.settings_cursor = (self.settings_cursor + 1) % len(SETTINGS)
                elif key in (ord(' '), 10, 13, curses.KEY_ENTER):
                    attr = SETTINGS[self.settings_cursor][1]
                    setattr(self, attr, not getattr(self, attr))
                    if attr == "dynamic":
                        self._apply_colors()
            else:
                if key in (ord('q'), ord('Q'), 27):
                    self.running = False
                    break
                if key in (ord('s'), ord('S')):
                    self.settings_open   = True
                    self.settings_cursor = 0
                if key == curses.KEY_UP or key == ord('+'):
                    self.offset = round(self.offset + OFFSET_STEP, 2)
                if key == curses.KEY_DOWN or key == ord('-'):
                    self.offset = round(self.offset - OFFSET_STEP, 2)

            with self.lock:
                track   = self.track
                lyrics  = list(self.lyrics)
                synced  = self.synced
                pal     = (self.col_primary, self.col_second)
                offset  = self.offset

            if pal != last_palette:
                self._apply_colors()
                last_palette = pal

            h, w = scr.getmaxyx()
            scr.erase()

            if not track:
                msg = "nothing playing on Spotify"
                self._safe_addstr(scr, h//2, max(0,(w-len(msg))//2), msg,
                                  curses.color_pair(2) | curses.A_DIM)
                if self.settings_open:
                    self._draw_settings(scr, h, w)
                scr.refresh()
                time.sleep(0.4)
                continue

            progress = track["progress"] + offset
            cur = 0
            if synced:
                for i, (ts, _) in enumerate(lyrics):
                    if ts <= progress:
                        cur = i

            if self.show_ui:
                dur        = track["duration"]
                prog       = track["progress"]
                bar_w      = max(10, w - 22)
                filled     = int(bar_w * min(prog / max(dur, 1), 1))
                bar        = "─" * filled + "╸" + " " * (bar_w - filled)
                time_str   = f"{int(prog)//60}:{int(prog)%60:02d} / {int(dur)//60}:{int(dur)%60:02d}"
                hint       = f"[S] settings  [↑/↓] offset:{offset:+.2f}s  [Q] quit"

                attr_h = curses.color_pair(3) | curses.A_BOLD
                self._safe_addstr(scr, 0, 0, f" ♪  {track['title']}"[:w-1],  attr_h)
                self._safe_addstr(scr, 1, 0, f"    {track['artist']}"[:w-1], curses.color_pair(2))
                self._safe_addstr(scr, 2, 0, f" {bar} {time_str}"[:w-1],     curses.color_pair(2))
                self._safe_addstr(scr, 3, max(0, w-len(hint)-1), hint[:w-1], curses.color_pair(2) | curses.A_DIM)
                self._safe_addstr(scr, 4, 0, "─" * (w-1),                    curses.color_pair(2) | curses.A_DIM)
                lyric_start = 5
            else:
                lyric_start = 0

            lyric_area = h - lyric_start
            half       = lyric_area // 2
            start      = max(0, cur - half)
            end        = min(len(lyrics), start + lyric_area)
            start      = max(0, end - lyric_area)

            row_i = 0
            li    = start
            while li < end:
                ts, text   = lyrics[li]
                screen_row = lyric_start + row_i

                if li == cur:
                    label = text.upper() if self.current_uppercase else text
                    line  = "  ▶  " + label
                    attr  = curses.color_pair(1)
                    if self.current_bold:     attr |= curses.A_BOLD
                    if self.current_standout: attr |= curses.A_STANDOUT
                    x, line = self._place(line, w)
                    if self.current_double and screen_row < h - 2:
                        self._safe_addstr(scr, screen_row,     x, line, attr)
                        self._safe_addstr(scr, screen_row + 1, x, line, attr)
                        row_i += 2
                    else:
                        self._safe_addstr(scr, screen_row, x, line, attr)
                        row_i += 1
                else:
                    line = "     " + text
                    attr = curses.color_pair(2)
                    if self.inactive_dim: attr |= curses.A_DIM
                    x, line = self._place(line, w)
                    if screen_row < h - 1:
                        self._safe_addstr(scr, screen_row, x, line, attr)
                    row_i += 1

                li += 1
                if lyric_start + row_i >= h - 1:
                    break

            if self.settings_open:
                self._draw_settings(scr, h, w)

            scr.refresh()

    @staticmethod
    def _safe_addstr(scr, y, x, text, attr=0):
        try:
            scr.addstr(y, x, text, attr)
        except curses.error:
            pass


def detect_shell():
    shell = os.environ.get("SHELL", "")
    if "fish" in shell: return "fish"
    if "zsh"  in shell: return "zsh"
    return "bash"

def get_shell_config(shell):
    if shell == "fish": return os.path.expanduser("~/.config/fish/config.fish")
    if shell == "zsh":  return os.path.expanduser("~/.zshrc")
    return os.path.expanduser("~/.bashrc")

def format_env_lines(shell, client_id, client_secret, redirect_uri):
    if shell == "fish":
        return (
            f'set -x SPOTIPY_CLIENT_ID "{client_id}"\n'
            f'set -x SPOTIPY_CLIENT_SECRET "{client_secret}"\n'
            f'set -x SPOTIPY_REDIRECT_URI "{redirect_uri}"\n'
        )
    return (
        f'export SPOTIPY_CLIENT_ID="{client_id}"\n'
        f'export SPOTIPY_CLIENT_SECRET="{client_secret}"\n'
        f'export SPOTIPY_REDIRECT_URI="{redirect_uri}"\n'
    )

def run_setup():
    shell    = detect_shell()
    config   = get_shell_config(shell)
    redirect = "http://127.0.0.1:8888/callback"

    print("╭─────────────────────────────────────────────────────────────╮")
    print("│  lyricspot setup                                            │")
    print("╰─────────────────────────────────────────────────────────────╯")
    print()
    print("  1. Go to https://developer.spotify.com/dashboard")
    print("  2. Create an app")
    print(f"  3. Add this redirect URI:  {redirect}")
    print()

    client_id     = input("  Paste your Client ID:      ").strip()
    client_secret = input("  Paste your Client Secret:  ").strip()

    if not client_id or not client_secret:
        print("\n  nothing entered, exiting.")
        return

    with open(config, "a") as f:
        f.write("\n# lyricspot\n")
        f.write(format_env_lines(shell, client_id, client_secret, redirect))

    print()
    print(f"  saved to {config}  (detected shell: {shell})")
    print()
    if shell == "fish":
        print("  reload with:  source ~/.config/fish/config.fish")
    else:
        print(f"  reload with:  source {config}")
    print()
    print("  then re-run lyricspot.")


def main():
    if not HAS_SPOTIPY:
        print("✗  spotipy missing — run: pip install spotipy pillow colorthief")
        sys.exit(1)

    if CLIENT_ID == "YOUR_CLIENT_ID":
        run_setup()
        sys.exit(0)

    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    sys.stderr = open(os.devnull, "w")
    LyricSpot().run()


if __name__ == "__main__":
    main()
