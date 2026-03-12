#!/usr/bin/env python3
__version__ = "1.2.1SR"

import os
import sys
import time
import threading
import signal
import urllib.request
import urllib.parse
import json
import io
import re
import subprocess
import curses

try:
    import colorthief as _lsct
    HAS_COLOR = True
except ImportError:
    print("lsct (https://github.com/vlensys/lyricspot/blob/main/colorthief.py) not installed, proceeding without pulling colors")
    HAS_COLOR = False

LRCLIB_URL = "https://lrclib.net/api/get"
POLL_INTERVAL = 0.5 # smoother :3
SYNC_OFFSET = 0.0
OFFSET_STEP = 0.25
LYRICS_CENTERED = True
SHOW_UI = True
CURRENT_BOLD = True
CURRENT_UPPERCASE = True
CURRENT_DOUBLE = True
CURRENT_STANDOUT = False
INACTIVE_DIM = True
HEADER_MARGIN = 1  # how many lines to leave empty after pb

CONFIG_DIR = os.path.expanduser("~/.config/lyricspot")
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")

SETTINGS_KEYS = [
    "show_ui",
    "lyrics_centered",
    "current_bold",
    "current_uppercase",
    "current_double",
    "current_standout",
    "inactive_dim",
    "dynamic",
    "offset",
]

def load_settings():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except:
        return {}

def save_settings(obj):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        data = {k: getattr(obj, k) for k in SETTINGS_KEYS}
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except:
        pass

def rgb_to_256(r, g, b):
    if r == g == b:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return round((r - 8) / 247 * 24) + 232
    return 16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5)

def palette_from_url(url):
    if not HAS_COLOR or not url:
        return None, None
    try:
        req = urllib.request.urlopen(url, timeout=4)
        pal  = _lsct.get_palette(req.read(), color_count=6)
        def sat(c):
            mx, mn = max(c) / 255, min(c) / 255
            return (mx - mn) / (mx + 1e-9)
        pal_s = sorted(pal, key=sat, reverse=True)
        primary = rgb_to_256(*pal_s[0])
        secondary = rgb_to_256(*pal_s[min(2, len(pal_s) - 1)])
        return primary, secondary
    except:
        return None, None

def fetch_synced_lyrics(title, artist, album="", duration=0):
    params = urllib.parse.urlencode({
        "track_name": title,
        "artist_name": artist,
        "album_name": album,
        "duration": int(duration),
    })
    try:
        req = urllib.request.urlopen(f"{LRCLIB_URL}?{params}", timeout=6)
        data = json.loads(req.read())
        if data.get("syncedLyrics"):
            return parse_lrc(data["syncedLyrics"]), True
        if data.get("plainLyrics"):
            return [(0, l) for l in data["plainLyrics"].splitlines()], False
    except:
        pass
    return [(0, "lyrics not found")], False

def parse_lrc(lrc):
    lines = []
    for raw in lrc.splitlines():
        m = re.match(r"\[(\d+):(\d+\.\d+)\](.*)", raw)
        if m:
            t = int(m.group(1)) * 60 + float(m.group(2))
            lines.append((t, m.group(3).strip()))
    return sorted(lines, key=lambda x: x[0])

class playerctlpoller:
    def _cmd(self, args):
        try:
            out = subprocess.check_output(
                ["playerctl"] + args,
                stderr=subprocess.DEVNULL
            )
            return out.decode().strip()
        except:
            return None

    def now_playing(self):
        status = self._cmd(["status"])
        if status not in ("Playing", "Paused"):
            return None
        fmt = "{{title}}|{{artist}}|{{album}}|{{mpris:length}}|{{mpris:artUrl}}|{{mpris:trackid}}"
        meta = self._cmd(["metadata", "--format", fmt])
        if not meta:
            return None
        parts = meta.split("|")
        if len(parts) < 6:
            return None
        title, artist, album, length, art_url, track_id = parts
        try:
            duration = int(length) / 1_000_000
        except:
            duration = 0
        try:
            pos = float(self._cmd(["position"]) or 0)
        except:
            pos = 0
        return {
            "title": title,
            "artist": artist,
            "album": album,
            "duration": duration,
            "progress": pos,
            "art_url": art_url,
            "track_id": track_id,
        }

class LyricSpot:
    def __init__(self):
        self.poller = playerctlpoller()
        self.track = None
        self.lyrics = []
        self.synced = False
        self.dynamic = True
        self.show_ui = SHOW_UI
        self.lyrics_centered = LYRICS_CENTERED
        self.current_bold = CURRENT_BOLD
        self.current_uppercase = CURRENT_UPPERCASE
        self.current_double = CURRENT_DOUBLE
        self.current_standout = CURRENT_STANDOUT
        self.inactive_dim = INACTIVE_DIM
        self.col_primary = None
        self.col_second = None
        self.offset = SYNC_OFFSET
        self.lock = threading.Lock()
        self.running = True
        self._last_id = None
        saved = load_settings()
        for k, v in saved.items():
            if hasattr(self, k):
                setattr(self, k, v)

    def _poll(self):
        while self.running:
            t = self.poller.now_playing()
            with self.lock:
                self.track = t
                if t and t["track_id"] != self._last_id:
                    self._last_id = t["track_id"]
                    self.lyrics, self.synced = fetch_synced_lyrics(
                        t["title"],
                        t["artist"],
                        t["album"],
                        t["duration"]
                    )
                    self.col_primary, self.col_second = palette_from_url(
                        t["art_url"]
                    )
            time.sleep(POLL_INTERVAL)

    def run(self):
        threading.Thread(target=self._poll, daemon=True).start()
        curses.wrapper(self._main)

    def _apply_colors(self):
        if self.dynamic and self.col_primary is not None:
            fg_active = self.col_primary
            fg_dim = self.col_second if self.col_second else -1
            fg_header = self.col_primary
        else:
            fg_active = fg_dim = fg_header = -1
        curses.init_pair(1, fg_active, -1)
        curses.init_pair(2, fg_dim, -1)
        curses.init_pair(3, fg_header, -1)
        curses.init_pair(4, fg_header, -1) # filled pb
        curses.init_pair(5, -1, -1) # unfilled pb

    def _place(self, text, w):
        if self.lyrics_centered:
            x = max(0, (w - len(text)) // 2)
        else:
            x = 0
        return x, text[:max(1, w - x - 1)]

    def _main(self, scr):
        curses.curs_set(0)
        curses.start_color()
        curses.use_default_colors()
        scr.nodelay(True)
        scr.timeout(80)
        self._apply_colors()

        while self.running:
            key = scr.getch()
            if key in (ord("q"), ord("Q"), 27):
                break
            if key == curses.KEY_UP:
                self.offset = round(self.offset + OFFSET_STEP, 2)
                save_settings(self)
            if key == curses.KEY_DOWN:
                self.offset = round(self.offset - OFFSET_STEP, 2)
                save_settings(self)

            if key == ord("u"):
                self.show_ui = not self.show_ui
                save_settings(self)
            if key == ord("c"):  
                self.lyrics_centered = not self.lyrics_centered
                save_settings(self)
            if key == ord("d"): 
                self.dynamic = not self.dynamic
                self._apply_colors()
                save_settings(self)
            if key == ord("b"):
                self.current_bold = not self.current_bold
                save_settings(self)
            if key == ord("U"): 
                self.current_uppercase = not self.current_uppercase
                save_settings(self)
            if key == ord("i"): 
                self.inactive_dim = not self.inactive_dim
                save_settings(self)
            
            with self.lock:
                track = self.track
                lyrics = list(self.lyrics)
                synced = self.synced
                offset = self.offset

            h, w = scr.getmaxyx()
            scr.erase()

            if not track:
                msg = "nothing playing"
                scr.addstr(h // 2, max(0, (w - len(msg)) // 2), msg, curses.A_DIM)
                scr.refresh()
                time.sleep(0.4)
                continue

            if self.show_ui:
                title_text = track['title']
                artist_text = f" - {track['artist']}"
                full_line = title_text + artist_text
                
                # truncate when needed
                if len(full_line) > w - 28:
                    available = w - 31
                    if len(title_text) > available:
                        title_text = title_text[:available] + "…"
                        artist_text = ""
                    else:
                        artist_text = artist_text[:available - len(title_text)] + "…"

                status = f"offset:{offset:+.2f}s  q:quit"
                status_x = max(6, w - len(status) - 2)

                dur = track["duration"]
                prog = track["progress"]
                bar_w = w - 4
                filled = int(bar_w * min(prog / max(dur, 1), 1))
                
                bar_filled = "━" * filled
                bar_unfilled = "━" * (bar_w - filled)

                scr.addstr(0, 2, title_text, curses.color_pair(3) | curses.A_BOLD)
                if artist_text:
                    scr.addstr(0, 2 + len(title_text), artist_text, curses.color_pair(2) | curses.A_DIM)
                scr.addstr(0, status_x, status, curses.color_pair(2) | curses.A_DIM)
                scr.addstr(1, 2, bar_filled, curses.color_pair(4))
                if bar_unfilled:
                    scr.addstr(1, 2 + filled, bar_unfilled, curses.color_pair(5) | curses.A_DIM)

                lyric_start = 2 + HEADER_MARGIN
            else:
                lyric_start = 0

            progress = track["progress"] + offset
            cur = 0
            if synced:
                for i, (ts, _) in enumerate(lyrics):
                    if ts <= progress:
                        cur = i

            lyric_area = h - lyric_start
            half = lyric_area // 2
            start = max(0, cur - half)
            end = min(len(lyrics), start + lyric_area)
            start = max(0, end - lyric_area)

            row_i = 0
            li = start
            while li < end and lyric_start + row_i < h - 1:
                ts, text = lyrics[li]
                screen_row = lyric_start + row_i

                if li == cur:
                    label = text.upper() if self.current_uppercase else text
                    line = f"  ▶ {label}"
                    attr = curses.color_pair(1) | curses.A_BOLD
                else:
                    line = f"    {text}"
                    attr = curses.color_pair(2)
                    if self.inactive_dim:
                        attr |= curses.A_DIM

                x, clipped = self._place(line, w)
                scr.addstr(screen_row, x, clipped, attr)

                row_i += 1
                li += 1

            scr.refresh()

def main():
    if "--reset" in sys.argv:
        try:
            os.remove(CONFIG_FILE)
            print("settings cleared")
        except:
            print("nothing to clear")
        return
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    LyricSpot().run()

if __name__ == "__main__":
    main()


