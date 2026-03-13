#!/usr/bin/env python3
# lyricspot - live synced lyrics in your terminal
# Copyright (C) 2026 vlensys
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# See <https://www.gnu.org/licenses/> for details.

# i really do like you!

__version__ = "1.5.0"

import os
import sys
import time
import threading
import signal
import urllib.request
import urllib.parse
import json
import re
import subprocess
import curses

try:
    import colorthief as _lsct
    HAS_COLOR = True
except ImportError:
    print("lsct (https://github.com/vlensys/lyricspot/blob/main/colorthief.py) not installed, proceeding without dynamic colors")
    HAS_COLOR = False

LRCLIB_URL    = "https://lrclib.net/api/get"
POLL_INTERVAL = 0.3
OFFSET_STEP   = 0.25

CONFIG_DIR  = os.path.expanduser("~/.config/lyricspot")
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")
CACHE_DIR   = os.path.expanduser("~/.cache/lyricspot")

SETTINGS_KEYS = [
    "show_ui", "lyrics_centered", "current_bold", "current_uppercase",
    "inactive_dim", "dynamic", "offset", "ui_style",
]

_IDLE_MSG = "nothing playing"

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
        if r < 8:   return 16
        if r > 248: return 231
        return round((r - 8) / 247 * 24) + 232
    return 16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5)

def palette_from_url(url):
    if not HAS_COLOR or not url:
        return None, None
    try:
        req = urllib.request.urlopen(url, timeout=4)
        pal = _lsct.get_palette(req.read(), color_count=6)
        def sat(c):
            mx, mn = max(c) / 255, min(c) / 255
            return (mx - mn) / (mx + 1e-9)
        pal_s     = sorted(pal, key=sat, reverse=True)
        primary   = rgb_to_256(*pal_s[0])
        secondary = rgb_to_256(*pal_s[min(2, len(pal_s) - 1)])
        return primary, secondary
    except:
        return None, None


class playerctlpoller:
    def _cmd(self, args):
        try:
            out = subprocess.check_output(["playerctl"] + args, stderr=subprocess.DEVNULL)
            return out.decode().strip()
        except:
            return None

    def now_playing(self):
        status = self._cmd(["status"])
        if status not in ("Playing", "Paused"):
            return None
        fmt  = "{{title}}|{{artist}}|{{album}}|{{mpris:length}}|{{mpris:artUrl}}|{{mpris:trackid}}"
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
            pos = float(self._cmd(["position"]) or "0")
        except:
            pos = 0
        return {
            "title":    title    or "Unknown Title",
            "artist":   artist   or "",
            "album":    album    or "",
            "duration": duration,
            "progress": pos,
            "art_url":  art_url,
            "track_id": track_id,
            "status":   status,
        }


class LyricSpot:
    def __init__(self):
        self.poller          = playerctlpoller()
        self.track           = None
        self.lyrics          = []
        self.synced          = False
        self.dynamic         = True
        self.show_ui         = True
        self.lyrics_centered = True
        self.current_bold    = True
        self.current_uppercase = True
        self.inactive_dim    = True
        self.col_primary     = None
        self.col_second      = None
        self.offset          = 0.0
        self.lock            = threading.Lock()
        self.running         = True
        self._last_id        = None
        self.ui_style        = "minimal"
        self._recolor        = False
        self._fetching       = False
        saved = load_settings()
        for k, v in saved.items():
            if hasattr(self, k):
                setattr(self, k, v)

    def _fetch_lyrics(self, title, artist, album="", duration=0):
        os.makedirs(CACHE_DIR, exist_ok=True)
        key        = re.sub(r"[^\w]+", "_", f"{artist}_{title}").strip("_").lower()
        cache_file = os.path.join(CACHE_DIR, f"{key}.json")

        # try cache first
        try:
            with open(cache_file) as f:
                data = json.load(f)
            if data.get("synced"):
                return self._parse_lrc(data["lyrics"]), True
            else:
                return [(0, l) for l in data["lyrics"].splitlines()], False
        except FileNotFoundError:
            pass
        except json.JSONDecodeError:
            try: os.remove(cache_file)
            except: pass

        # lrclib /api/get
        p = {"track_name": title, "artist_name": artist, "album_name": album}
        if duration:
            p["duration"] = int(duration)
        try:
            with urllib.request.urlopen(f"{LRCLIB_URL}?{urllib.parse.urlencode(p)}", timeout=6) as req:
                data = json.loads(req.read())
            if synced_lyrics := data.get("syncedLyrics"):
                with open(cache_file, "w") as f:
                    json.dump({"synced": True, "lyrics": synced_lyrics}, f)
                return self._parse_lrc(synced_lyrics), True
            if plain := data.get("plainLyrics"):
                with open(cache_file, "w") as f:
                    json.dump({"synced": False, "lyrics": plain}, f)
                return [(0, l) for l in plain.splitlines()], False
        except:
            pass

        # lrclib /api/search
        try:
            search_params = urllib.parse.urlencode({"q": f"{artist} {title}"})
            with urllib.request.urlopen(f"https://lrclib.net/api/search?{search_params}", timeout=6) as req:
                results = json.loads(req.read())
            # because sync tastes better than plain
            synced_result = next((r for r in results if r.get("syncedLyrics")), None)
            plain_result  = next((r for r in results if r.get("plainLyrics")), None)
            if synced_result:
                sl = synced_result["syncedLyrics"]
                with open(cache_file, "w") as f:
                    json.dump({"synced": True, "lyrics": sl}, f)
                return self._parse_lrc(sl), True
            if plain_result:
                pl = plain_result["plainLyrics"]
                with open(cache_file, "w") as f:
                    json.dump({"synced": False, "lyrics": pl}, f)
                return [(0, l) for l in pl.splitlines()], False
        except:
            pass

        # try netease if everything else fails
        try:
            # track search
            ne_search = urllib.parse.urlencode({"s": f"{artist} {title}", "type": 1, "limit": 5})
            req = urllib.request.Request(
                f"https://music.163.com/api/search/get?{ne_search}",
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com"}
            )
            with urllib.request.urlopen(req, timeout=6) as r:
                ne_data = json.loads(r.read())
            songs = ne_data.get("result", {}).get("songs", [])
            if songs:
                song_id = songs[0]["id"]
                lrc_req = urllib.request.Request(
                    f"https://music.163.com/api/song/lyric?id={song_id}&lv=1&kv=1&tv=-1",
                    headers={"User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com"}
                )
                with urllib.request.urlopen(lrc_req, timeout=6) as r:
                    lrc_data = json.loads(r.read())
                lrc_text = lrc_data.get("lrc", {}).get("lyric", "")
                if lrc_text and not lrc_text.strip().startswith("//"):
                    parsed = self._parse_lrc(lrc_text)
                    if parsed:
                        with open(cache_file, "w") as f:
                            json.dump({"synced": True, "lyrics": lrc_text}, f)
                        return parsed, True
        except:
            pass

        return [(0, "no lyrics found :(")], False

    def _parse_lrc(self, lrc):
        lines = []
        for raw in lrc.splitlines():
            if m := re.match(r"\[(\d+):(\d+\.\d+)\](.*)", raw):
                t    = int(m.group(1)) * 60 + float(m.group(2))
                text = re.sub(r"<[^>]+>", "", m.group(3)).strip() or "__BREAK__"
                lines.append((t, text))
        return sorted(lines)

    def _fetch_colors(self, url):
        primary, second = palette_from_url(url)
        with self.lock:
            self.col_primary = primary
            self.col_second  = second
            self._recolor    = True

    def _fetch_colors(self, url):
        primary, second = palette_from_url(url)
        with self.lock:
            self.col_primary = primary
            self.col_second  = second
            self._recolor    = True

    def _poll(self):
        while self.running:
            t = self.poller.now_playing()
            with self.lock:
                self.track = t
                track_key  = (t["track_id"], t["title"], t["artist"]) if t else None
                if t and track_key != self._last_id:
                    self._last_id  = track_key
                    self._fetching = True
                    self.lyrics, self.synced = self._fetch_lyrics(
                        t["title"], t["artist"], t["album"], t["duration"]
                    )
                    self._fetching = False
                    threading.Thread(
                        target=self._fetch_colors,
                        args=(t["art_url"],),
                        daemon=True
                    ).start()
            time.sleep(POLL_INTERVAL)

    def run(self):
        threading.Thread(target=self._poll, daemon=True).start()
        curses.wrapper(self._main)

    def _apply_colors(self):
        if curses.COLORS < 8:
            for i in range(1, 9):
                curses.init_pair(i, -1, -1)
            return

        if self.dynamic and self.col_primary is not None:
            fg_active = self.col_primary
            fg_dim    = self.col_second if self.col_second else -1
            fg_header = self.col_primary
        else:
            term      = os.getenv("TERM", "").lower()
            bright    = 231 if ("kitty" in term or "alacritty" in term) else 255
            fg_active = bright
            fg_dim    = 252
            fg_header = bright

        curses.init_pair(1, fg_active, -1)  # current lyric (standout handles highlight)
        curses.init_pair(2, fg_dim,    -1)  # future dist 1
        curses.init_pair(3, 249,       -1)  # future dist 2-3
        curses.init_pair(4, 245,       -1)  # future dist 4+
        curses.init_pair(5, 240,       -1)  # past dist -1
        curses.init_pair(6, 238,       -1)  # past dist -2 to -3
        curses.init_pair(7, 236,       -1)  # past dist -4+
        curses.init_pair(8, fg_header, -1)  # header / progress bar

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
            if key in (ord("y"), ord("Y")):
                self.ui_style = "classic" if self.ui_style == "minimal" else "minimal"
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
                track  = self.track
                lyrics = list(self.lyrics)
                synced = self.synced
                offset = self.offset

            h, w = scr.getmaxyx()
            if self._recolor:
                self._apply_colors()
                self._recolor = False
            scr.erase()

            if not track:
                msg = _IDLE_MSG
                scr.addstr(h // 2, max(0, (w - len(msg)) // 2), msg, curses.A_DIM)
                scr.refresh()
                time.sleep(0.5)
                continue

            if self._fetching:
                msg = "fetching lyrics..."
                scr.addstr(h // 2, max(0, (w - len(msg)) // 2), msg, curses.A_DIM)
                scr.refresh()
                continue

            is_paused = track.get("status") == "Paused"

            if self.show_ui:
                dur  = track["duration"] or 1
                prog = track["progress"]
                if self.ui_style == "minimal":
                    pause_prefix = "⏸  " if is_paused else ""
                    title_text   = pause_prefix + track["title"]
                    artist_text  = f" - {track['artist']}" if track["artist"] else ""
                    if len(title_text + artist_text) > w - 28:
                        available = w - 31
                        if len(title_text) > available:
                            title_text  = title_text[:available] + "…"
                            artist_text = ""
                        else:
                            artist_text = artist_text[:available - len(title_text)] + "…"
                    status   = f"offset:{offset:+.2f}s  q:quit"
                    status_x = max(6, w - len(status) - 2)
                    bar_w    = w - 4
                    filled   = int(bar_w * min(prog / dur, 1))
                    try:
                        scr.addstr(0, 2, title_text, curses.color_pair(8) | curses.A_BOLD)
                        if artist_text and 2 + len(title_text) + len(artist_text) < status_x - 2:
                            scr.addstr(0, 2 + len(title_text), artist_text, curses.color_pair(4) | curses.A_DIM)
                        scr.addstr(0, status_x, status, curses.color_pair(4) | curses.A_DIM)
                        scr.addstr(1, 2, "━" * filled, curses.color_pair(8))
                        if filled < bar_w:
                            scr.addstr(1, 2 + filled, "━" * (bar_w - filled), curses.color_pair(7) | curses.A_DIM)
                    except curses.error:
                        pass
                    lyric_start = 3
                else:
                    bar_w    = max(10, w - 22)
                    filled   = int(bar_w * min(prog / dur, 1))
                    bar      = "─" * filled + "╸" + " " * (bar_w - filled)
                    time_str = f"{int(prog)//60}:{int(prog)%60:02d} / {int(dur)//60}:{int(dur)%60:02d}"
                    hint     = f"[↑/↓] offset:{offset:+.2f}s  [Q] quit"
                    try:
                        prefix = " ⏸  " if is_paused else " ♪  "
                        scr.addstr(0, 0, f"{prefix}{track['title']}"[:w-1],  curses.color_pair(8) | curses.A_BOLD)
                        scr.addstr(1, 0, f"    {track['artist']}"[:w-1],     curses.color_pair(4))
                        scr.addstr(2, 0, f" {bar} {time_str}"[:w-1],         curses.color_pair(4))
                        scr.addstr(3, max(0, w-len(hint)-1), hint[:w-1],     curses.color_pair(4) | curses.A_DIM)
                        scr.addstr(4, 0, "─" * (w-1),                        curses.color_pair(7) | curses.A_DIM)
                    except curses.error:
                        pass
                    lyric_start = 5
            else:
                lyric_start = 0

            progress = track["progress"] + offset
            cur = 0
            if synced:
                for i, (ts, _) in enumerate(lyrics):
                    if ts <= progress:
                        cur = i

            lyric_area = h - lyric_start
            half       = lyric_area // 2 + 1
            start      = max(0, cur - half)
            end        = min(len(lyrics), start + lyric_area)
            start      = max(0, end - lyric_area)

            for row, idx in enumerate(range(start, end)):
                if lyric_start + row >= h - 1:
                    break
                ts, text = lyrics[idx]
                dist     = idx - cur if synced else 0

                is_break = text == "__BREAK__"

                if not synced:
                    line = f"  {text}"
                    attr = curses.color_pair(1)
                elif dist == 0 and is_break:
                    next_ts = lyrics[idx + 1][0] if idx + 1 < len(lyrics) else ts + 3
                    gap     = max(next_ts - ts, 0.01)
                    elapsed = max(0, progress - ts)
                    frac    = min(elapsed / gap, 1.0)
                    dots    = ("·  ", "·· ", "···")[min(int(frac * 3), 2)]
                    line    = f"  {dots}"
                    attr    = curses.color_pair(1) | curses.A_BOLD
                elif is_break:
                    line = "  ···"
                    attr = curses.color_pair(5 if dist == -1 else 6 if dist >= -3 else 7) if dist < 0 else curses.color_pair(2 if dist == 1 else 3 if dist <= 3 else 4)
                elif dist == 0:
                    label = text.upper() if self.current_uppercase else text
                    line  = f"  ▶ {label}"
                    attr  = curses.color_pair(1) | (curses.A_BOLD if self.current_bold else 0)
                elif dist > 0:
                    line = f"    {text}"
                    attr = curses.color_pair(2 if dist == 1 else 3 if dist <= 3 else 4)
                else:
                    line = f"    {text}"
                    attr = curses.color_pair(5 if dist == -1 else 6 if dist >= -3 else 7)

                x, clipped = self._place(line, w)
                scr.addstr(lyric_start + row, x, clipped, attr)

            scr.refresh()


def main():
    if "--version" in sys.argv or "-v" in sys.argv:
        print(f"lyricspot {__version__}")
        return
    if "--help" in sys.argv or "-h" in sys.argv:
        print("usage: lyricspot [--reset] [--version]")
        print()
        print("args:")
        print("[--reset] resets your cache")
        print("[--version] prints your version")

        return
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
