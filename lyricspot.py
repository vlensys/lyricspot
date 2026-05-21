#!/usr/bin/env python3
import argparse
import curses
import difflib
import json
import math
import os
import random
import re
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("LRCLIB_API", "https://lrclib.net/api").rstrip("/")
CFG = os.path.join(os.path.expanduser("~"), ".config", "lyricspot")
SETTINGS = os.path.join(CFG, "settings.json")
CACHE = os.path.join(CFG, "cache.json")
UA = "lyricspot/1.0 (https://github.com/vlensys/lyricspot)"
STAMP = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")
JUNK = re.compile(r"\s*[\[(](official|audio|video|lyrics?|lyric video|visualizer|remaster(?:ed)?(?: \d{4})?)[^\])]*[\])]|\s+-\s+(official|audio|video|lyrics?|lyric video|visualizer|remaster(?:ed)?(?: \d{4})?).*$", re.I)
BREAK_AFTER = 8
COLOR_NAMES = {
    "default": -1,
    "black": 0,
    "red": 1,
    "green": 2,
    "yellow": 3,
    "blue": 4,
    "magenta": 5,
    "cyan": 6,
    "white": 7,
    "gray": 8,
    "grey": 8,
}
DEFAULT_SETTINGS = {
    "offset": 0.0,
    "header": True,
    "center": True,
    "upper": False,
    "bold": True,
    "visualizer": True,
    "visualizer_type": "bars",
    "visualizer_source": "loopback",
    "visualizer_theme": "cyber",
    "visualizer_height": 6,
    "colors": {
        "header_title": 231,
        "header_artist": 244,
        "header_offset": 244,
        "current_lyric": 231,
        "lyric_gradient": [250, 245, 240, 236],
        "progress_filled": 231,
        "progress_empty": 240,
        "status": 8,
        "muted": 8,
    },
}

VIZ_THEMES = {
    "classic": [46, 82, 118, 154, 190, 226, 214, 202, 196],
    "cyber": [51, 45, 39, 93, 129, 165, 201, 198],
    "fire": [52, 88, 124, 160, 196, 202, 208, 220, 226],
    "grayscale": [234, 238, 242, 246, 250, 254, 231],
}

VIZ_GRADIENT_PAIR = 20

AUDIO_STATE = {
    "enabled": True,
    "mags_l": [0.0] * 128,
    "mags_r": [0.0] * 128,
    "active": False,
    "lock": threading.Lock(),
}


def fft(a):
    n = len(a)
    if n <= 1:
        return a
    ev = fft(a[0::2])
    od = fft(a[1::2])
    t = [math.e ** (-2j * math.pi * k / n) * od[k] for k in range(n // 2)]
    return [ev[k] + t[k] for k in range(n // 2)] + [ev[k] - t[k] for k in range(n // 2)]


def get_eq_bands(magnitudes, num_bars):
    if not magnitudes:
        return [0.0] * num_bars
    out = []
    min_bin = 1.0
    max_bin = len(magnitudes) - 1.0
    for i in range(num_bars):
        f_start = min_bin * ((max_bin / min_bin) ** (i / num_bars))
        f_end = min_bin * ((max_bin / min_bin) ** ((i + 1) / num_bars))
        start_idx = max(1, int(f_start))
        end_idx = min(len(magnitudes), max(start_idx + 1, int(f_end)))
        val = sum(magnitudes[start_idx:end_idx]) / (end_idx - start_idx)
        out.append(val)
    return out


def start_audio_capture():
    sink = sh("pactl", "get-default-sink")
    if not sink:
        return None
    source = sink + ".monitor"
    cmd = [
        "parec",
        "-d", source,
        "--latency-msec=10",
        "--raw",
        "--channels=2",
        "--rate=8000",
        "--format=s16le"
    ]
    try:
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except Exception:
        return None


def audio_capture_loop():
    global AUDIO_STATE
    N = 256
    hamming = [0.54 - 0.46 * math.cos(2 * math.pi * n / (N - 1)) for n in range(N)]
    proc = None
    while AUDIO_STATE["enabled"]:
        if proc is None or proc.poll() is not None:
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass
            proc = start_audio_capture()
            if proc is None:
                time.sleep(1.0)
                continue
        try:
            # Stereo: 2 channels * 2 bytes * 256 samples = 1024 bytes
            data = proc.stdout.read(1024)
            if len(data) < 1024:
                proc = None
                continue
            samples = struct.unpack("<512h", data)
            left = samples[0::2]
            right = samples[1::2]
            x_l = [(left[i] / 32768.0) * hamming[i] for i in range(256)]
            x_r = [(right[i] / 32768.0) * hamming[i] for i in range(256)]
            spectrum_l = fft(x_l)
            spectrum_r = fft(x_r)
            mags_l = [abs(spectrum_l[i]) for i in range(128)]
            mags_r = [abs(spectrum_r[i]) for i in range(128)]
            with AUDIO_STATE["lock"]:
                AUDIO_STATE["mags_l"] = mags_l
                AUDIO_STATE["mags_r"] = mags_r
                AUDIO_STATE["active"] = True
        except Exception:
            proc = None
            time.sleep(0.1)
    if proc:
        try:
            proc.kill()
        except Exception:
            pass
PAIR = {
    "header_artist": 1,
    "current_lyric": 2,
    "muted": 3,
    "progress_filled": 4,
    "progress_empty": 5,
    "header_title": 10,
    "header_offset": 11,
    "status": 12,
}
LYRIC_GRADIENT_PAIR = 6


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def merge_settings(saved):
    settings = dict(DEFAULT_SETTINGS)
    settings["colors"] = dict(DEFAULT_SETTINGS["colors"])
    if isinstance(saved, dict):
        for key in ("offset", "header", "center", "upper", "bold", "visualizer", "visualizer_type", "visualizer_source", "visualizer_theme", "visualizer_height"):
            if key in saved:
                settings[key] = saved[key]
        if isinstance(saved.get("colors"), dict):
            settings["colors"].update(saved["colors"])
    return settings


def save_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, separators=(",", ":"))
        os.replace(tmp, path)
    except OSError:
        pass


def sh(*args):
    try:
        p = subprocess.run(args, text=True, capture_output=True, timeout=0.7)
        return p.stdout.strip() if p.returncode == 0 else ""
    except Exception:
        return ""


def http_json(path, params, timeout=3):
    url = API + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def err(e):
    return str(getattr(e, "reason", e)).splitlines()[0].lower()[:48]


def is_ellipsis(text):
    return text.strip() in ("...", "…")


def parse_lrc(text):
    out = []
    for line in (text or "").splitlines():
        m = STAMP.match(line)
        if m and not is_ellipsis(m[3]):
            out.append((int(m[1]) * 60 + float(m[2]), m[3].strip()))
    return sorted((t, s) for t, s in out if s)


def key_for(meta):
    return "\0".join((meta.get("title", ""), meta.get("artist", ""), str(round(meta.get("duration", 0)))))


def clean_artist(s):
    return s.split(",")[0].strip() if s else ""


def norm(s):
    s = JUNK.sub("", s or "")
    s = re.sub(r"\s+(feat\.?|ft\.?|featuring)\s+.*$", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" -_")
    return s


def search_terms(meta):
    title, artist = meta.get("title", ""), meta.get("artist", "")
    if not artist and " - " in title:
        a, t = title.split(" - ", 1)
        artist, title = a.strip(), t.strip()
    title, artist = norm(title), norm(clean_artist(artist))
    pairs = [(meta.get("title", ""), clean_artist(meta.get("artist", ""))), (title, artist)]
    out = []
    for t, a in pairs:
        if t and a and (t, a) not in out:
            out.append((t, a))
    return out or [(title, artist)]


def sim(a, b):
    return difflib.SequenceMatcher(None, norm(a).casefold(), norm(b).casefold()).ratio()


def pick(rows, title, artist, dur):
    def score(r):
        s = sim(title, r.get("trackName", "")) * 4 + sim(artist, r.get("artistName", "")) * 2
        if r.get("syncedLyrics"):
            s += 2
        if dur and r.get("duration"):
            s -= min(abs(r["duration"] - dur), 40) / 20
        return s
    rows = [r for r in rows if r.get("syncedLyrics")]
    return max(rows, key=score) if rows else None


def fetch_lyrics(meta, cache, use_cache=True):
    key = key_for(meta)
    if use_cache and key in cache and cache[key].get("syncedLyrics"):
        return parse_lrc(cache[key].get("syncedLyrics")) or [], ""
    title, artist = meta["title"], clean_artist(meta["artist"])
    album, dur = meta.get("album", ""), int(meta.get("duration", 0))
    found = None
    failed = False
    reason = ""
    deadline = time.monotonic() + 45
    for t, a in search_terms(meta):
        if time.monotonic() > deadline:
            break
        try:
            p = {"track_name": t, "artist_name": a}
            if album and t == title:
                p["album_name"] = album
            if dur:
                p["duration"] = dur
            found = http_json("/get", p, timeout=15)
            if found and found.get("syncedLyrics"):
                break
        except urllib.error.HTTPError as e:
            failed = failed or e.code not in (400, 404)
            reason = f"http {e.code}"
        except Exception as e:
            failed = True
            reason = err(e)
        for p in ({"track_name": t, "artist_name": a}, {"q": f"{t} {a}"}, {"query": f"{t} {a}"}):
            if time.monotonic() > deadline:
                break
            try:
                found = pick(http_json("/search", p, timeout=15), t, a, dur)
                if found:
                    break
            except urllib.error.HTTPError as e:
                failed = failed or e.code not in (400, 404)
                reason = f"http {e.code}"
            except Exception as e:
                failed = True
                reason = err(e)
        if found:
            break
    if found and use_cache:
        cache[key] = {"syncedLyrics": found.get("syncedLyrics", "")}
        save_json(CACHE, cache)
    if not found and failed:
        return [], f"could not reach lrclib ({reason})"
    return parse_lrc((found or {}).get("syncedLyrics")), ""


def get_meta(player_arg=None):
    fmt = "{{title}}\t{{artist}}\t{{album}}\t{{mpris:length}}\t{{status}}\t{{playerName}}"
    if player_arg:
        raw = sh("playerctl", "-p", player_arg, "metadata", "--format", fmt)
    else:
        raw = sh("playerctl", "-a", "metadata", "--format", fmt)
        if not raw:
            raw = sh("playerctl", "metadata", "--format", fmt)
    if not raw:
        return {}
    
    candidates = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = (line.split("\t") + [""] * 6)[:6]
        title, artist, album, length_str, status, player = parts
        dur = 0
        try:
            dur = int(length_str) / 1000000
        except Exception:
            pass
        candidates.append({
            "title": title,
            "artist": artist,
            "album": album,
            "duration": dur,
            "status": status,
            "player": player
        })
    if not candidates:
        return {}
    if player_arg:
        for c in candidates:
            if player_arg.lower() in c["player"].lower():
                return c
        return candidates[0]
    
    def get_score(c):
        score = 0
        if c["status"] == "Playing":
            score += 10
        elif c["status"] == "Paused":
            score += 5
        if c["artist"].strip():
            score += 8
        if c["title"].strip():
            score += 4
        title_lower = c["title"].lower()
        if (
            title_lower.endswith(".html") or
            title_lower.endswith(".htm") or
            title_lower.endswith(".php") or
            title_lower.endswith(".js") or
            "windowtype=" in title_lower or
            "http://" in title_lower or
            "https://" in title_lower or
            "file://" in title_lower
        ):
            score -= 15
        player_lower = c["player"].lower()
        browsers = ["chromium", "firefox", "chrome", "brave", "opera", "vivaldi", "edge", "epiphany", "webkit"]
        music_players = ["spotify", "vlc", "audacious", "mpd", "rhythmbox", "clementine", "strawberry", "cmus", "mplayer", "mpv", "lollypop", "sayonara", "quodlibet"]
        is_browser = any(b in player_lower for b in browsers)
        is_music = any(m in player_lower for m in music_players)
        if is_music:
            score += 5
        if is_browser:
            score -= 5
        return score
    
    return max(candidates, key=get_score)


def get_pos(player=None):
    try:
        args = ["playerctl", "position"]
        if player:
            args = ["playerctl", "-p", player, "position"]
        return float(sh(*args) or 0)
    except Exception:
        return 0.0


def smooth_pos(raw, state, reset=False):
    now = time.monotonic()
    if reset or state["pos"] is None:
        state.update(pos=raw, seen=raw, t=now)
        return raw
    last = state["pos"]
    if raw + 2 < last and raw < 3 and last > 5:
        if now - state["t"] < 1.5:
            state["pos"] = min(state["seen"], last + max(0, now - state["t"]))
            state["t"] = now
            return state["pos"]
    state.update(pos=raw, seen=max(state["seen"], raw), t=now)
    return raw


def clamp(n, lo, hi):
    return max(lo, min(hi, n))


def lyric_index(lines, pos):
    lo, hi = 0, len(lines)
    while lo < hi:
        mid = (lo + hi) // 2
        if lines[mid][0] <= pos:
            lo = mid + 1
        else:
            hi = mid
    return max(0, lo - 1)


def safe_add(stdscr, y, x, text, attr=0):
    h, w = stdscr.getmaxyx()
    if 0 <= y < h and x < w:
        stdscr.addnstr(y, max(0, x), text[max(0, -x):], max(0, w - max(0, x) - 1), attr)


def centered(stdscr, y, text, attr=0):
    _, w = stdscr.getmaxyx()
    safe_add(stdscr, y, max(0, (w - len(text)) // 2), text, attr)


def rgb_to_ansi(c):
    r, g, b = c
    if curses.COLORS >= 256:
        return 16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5)
    return 15


def color_value(value, fallback):
    if isinstance(value, int):
        return value
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return rgb_to_ansi(tuple(clamp(int(n), 0, 255) for n in value))
        except Exception:
            return fallback
    if isinstance(value, str):
        value = value.strip().lower()
        if value in COLOR_NAMES:
            return COLOR_NAMES[value]
        if value.isdigit():
            return int(value)
        if re.fullmatch(r"#?[0-9a-f]{6}", value):
            h = value.lstrip("#")
            return rgb_to_ansi(tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)))
    return fallback


def color_list(value, fallback):
    if not isinstance(value, list):
        return list(fallback)
    out = []
    for i, item in enumerate(value[:4]):
        out.append(color_value(item, fallback[min(i, len(fallback) - 1)]))
    while len(out) < 4:
        out.append(out[-1] if out else fallback[len(out)])
    return out


def init_pair(pair, fg, bg=-1):
    try:
        curses.init_pair(pair, fg, bg)
    except Exception:
        pass


def init_colors(settings):
    curses.start_color()
    curses.use_default_colors()
    colors = settings["colors"]
    defaults = DEFAULT_SETTINGS["colors"]
    for name, pair in PAIR.items():
        init_pair(pair, color_value(colors.get(name), defaults.get(name, 231)))
    for i, fg in enumerate(color_list(colors.get("lyric_gradient"), defaults["lyric_gradient"])):
        init_pair(LYRIC_GRADIENT_PAIR + i, fg)
    if curses.COLORS >= 256:
        theme_name = settings.get("visualizer_theme", "cyber")
        theme_colors = VIZ_THEMES.get(theme_name, VIZ_THEMES["cyber"])
        for i, fg in enumerate(theme_colors):
            init_pair(VIZ_GRADIENT_PAIR + i, fg)


def get_viz_pair(y_offset, max_height, settings):
    if curses.COLORS < 256:
        color_idx = clamp(3 - int((y_offset / max_height) * 4), 0, 3)
        return curses.color_pair(LYRIC_GRADIENT_PAIR + color_idx)
    theme_name = settings.get("visualizer_theme", "cyber")
    theme_colors = VIZ_THEMES.get(theme_name, VIZ_THEMES["cyber"])
    theme_len = len(theme_colors)
    color_idx = clamp(int((y_offset / max_height) * theme_len), 0, theme_len - 1)
    return curses.color_pair(VIZ_GRADIENT_PAIR + color_idx)


def update_visualizer(viz_state, num_bars, max_height, playing, settings):
    if "heights_l" not in viz_state or len(viz_state.get("heights_l", [])) != num_bars:
        viz_state["heights_l"] = [0.0] * num_bars
        viz_state["peaks_l"] = [0.0] * num_bars
        viz_state["heights_r"] = [0.0] * num_bars
        viz_state["peaks_r"] = [0.0] * num_bars
        viz_state["prev_mags_l"] = [0.0] * 128
        viz_state["prev_mags_r"] = [0.0] * 128
        viz_state["phase"] = [random.random() * 100 for _ in range(num_bars)]
        viz_state["speed"] = [0.05 + random.random() * 0.15 for _ in range(num_bars)]
        viz_state["last_t"] = time.monotonic()
        viz_state["running_peak_l"] = 0.05
        viz_state["running_peak_r"] = 0.05

    now = time.monotonic()
    dt = max(0.001, min(0.5, now - viz_state.get("last_t", now)))
    viz_state["last_t"] = now

    source = settings.get("visualizer_source", "loopback")
    has_audio = False

    if source == "loopback" and AUDIO_STATE["active"]:
        with AUDIO_STATE["lock"]:
            mags_l = list(AUDIO_STATE["mags_l"])
            mags_r = list(AUDIO_STATE["mags_r"])
        
        # Temporal smoothing of raw magnitudes to eliminate high-frequency jitter
        for i in range(128):
            viz_state["prev_mags_l"][i] = viz_state["prev_mags_l"][i] * 0.45 + mags_l[i] * 0.55
            viz_state["prev_mags_r"][i] = viz_state["prev_mags_r"][i] * 0.45 + mags_r[i] * 0.55
            
        bands_l = get_eq_bands(viz_state["prev_mags_l"], num_bars)
        bands_r = get_eq_bands(viz_state["prev_mags_r"], num_bars)
        if any(v > 0.0001 for v in bands_l + bands_r):
            has_audio = True
            peak_l = max(bands_l)
            peak_r = max(bands_r)
            viz_state["running_peak_l"] = 0.97 * viz_state["running_peak_l"] + 0.03 * max(peak_l, 0.001)
            viz_state["running_peak_r"] = 0.97 * viz_state["running_peak_r"] + 0.03 * max(peak_r, 0.001)
            scale_l = max_height / max(0.001, viz_state["running_peak_l"])
            scale_r = max_height / max(0.001, viz_state["running_peak_r"])
            for i in range(num_bars):
                val_l = clamp(bands_l[i] * scale_l * 0.85, 0.0, max_height)
                val_r = clamp(bands_r[i] * scale_r * 0.85, 0.0, max_height)
                
                # Exponential smoothing physics for Left Channel
                cur_l = viz_state["heights_l"][i]
                if val_l > cur_l:
                    alpha = math.exp(-26.0 * dt)
                    cur_l = cur_l * alpha + val_l * (1.0 - alpha)
                else:
                    alpha = math.exp(-9.0 * dt)
                    cur_l = cur_l * alpha + val_l * (1.0 - alpha)
                viz_state["heights_l"][i] = cur_l
                
                # Exponential smoothing physics for Right Channel
                cur_r = viz_state["heights_r"][i]
                if val_r > cur_r:
                    alpha = math.exp(-26.0 * dt)
                    cur_r = cur_r * alpha + val_r * (1.0 - alpha)
                else:
                    alpha = math.exp(-9.0 * dt)
                    cur_r = cur_r * alpha + val_r * (1.0 - alpha)
                viz_state["heights_r"][i] = cur_r

    if not has_audio:
        for i in range(num_bars):
            if playing:
                viz_state["phase"][i] += viz_state["speed"][i] * dt * 30.0
                pos_frac = i / max(1, num_bars - 1)
                val_l = math.sin(viz_state["phase"][i]) * 0.4 + 0.5
                val_l += math.sin(now * 15.0 + i) * 0.15
                val_r = math.cos(viz_state["phase"][i] * 0.9) * 0.4 + 0.5
                val_r += math.cos(now * 12.0 + i * 1.2) * 0.15
                if pos_frac < 0.3:
                    val_l *= 1.1 + math.sin(now * 4.0) * 0.2
                    val_r *= 1.1 + math.cos(now * 3.5) * 0.2
                elif pos_frac > 0.7:
                    val_l *= 0.7 + math.cos(now * 8.0) * 0.3
                    val_r *= 0.7 + math.sin(now * 7.5) * 0.3
                else:
                    val_l *= 0.8 + math.sin(now * 5.0) * 0.1
                    val_r *= 0.8 + math.cos(now * 4.5) * 0.1
                val_l = clamp(val_l * max_height, 0, max_height)
                val_r = clamp(val_r * max_height, 0, max_height)
            else:
                val_l = 0.0
                val_r = 0.0
            for ch_key, val in (("heights_l", val_l), ("heights_r", val_r)):
                cur = viz_state[ch_key][i]
                if val > cur:
                    alpha = math.exp(-20.0 * dt)
                    cur = cur * alpha + val * (1.0 - alpha)
                else:
                    alpha = math.exp(-7.0 * dt)
                    cur = cur * alpha + val * (1.0 - alpha)
                viz_state[ch_key][i] = cur

    peak_decay = 4.0 * dt
    for i in range(num_bars):
        for ch_h, ch_p in (("heights_l", "peaks_l"), ("heights_r", "peaks_r")):
            cur = viz_state[ch_h][i]
            peak = viz_state[ch_p][i]
            if cur >= peak:
                peak = cur
            else:
                peak = max(0.0, peak - peak_decay)
            viz_state[ch_p][i] = peak


def draw_single_bar(stdscr, x, bar_width, h_val, p_val, viz_height, start_y, viz_type, settings):
    BLOCKS = [" ", " ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
    char_bar = "█" * bar_width
    for y_offset in range(viz_height):
        y = start_y - y_offset
        pair = get_viz_pair(y_offset, viz_height, settings)
        if viz_type == "bars":
            if h_val >= y_offset + 1:
                safe_add(stdscr, y, x, char_bar, pair)
            elif h_val > y_offset:
                frac = h_val - y_offset
                idx = clamp(int(frac * 8), 0, 8)
                if idx > 0:
                    safe_add(stdscr, y, x, BLOCKS[idx] * bar_width, pair)
        elif viz_type == "wave":
            if y_offset <= h_val < y_offset + 1 and h_val > 0.1:
                frac = h_val - y_offset
                idx = clamp(int(frac * 8), 0, 8)
                if idx > 0:
                    safe_add(stdscr, y, x, BLOCKS[idx] * bar_width, pair)
                else:
                    safe_add(stdscr, y, x, "-" * bar_width, pair)
        elif viz_type == "retro":
            if h_val >= y_offset + 1:
                safe_add(stdscr, y, x, "#" * bar_width, pair)
            elif h_val > y_offset + 0.5:
                safe_add(stdscr, y, x, "=" * bar_width, pair)
            elif h_val > y_offset:
                safe_add(stdscr, y, x, "-" * bar_width, pair)
        elif viz_type == "dots":
            if y_offset <= h_val < y_offset + 1 and h_val > 0.1:
                safe_add(stdscr, y, x, "•" * bar_width, pair | curses.A_BOLD)
    if viz_type in ("bars", "retro", "dots"):
        peak_y = start_y - int(p_val)
        if int(p_val) > int(h_val) and 0 <= int(p_val) < viz_height:
            pair = get_viz_pair(int(p_val), viz_height, settings)
            if viz_type == "bars":
                char = "▔" * bar_width
            elif viz_type == "retro":
                char = "-" * bar_width
            else:
                char = "•" * bar_width
            safe_add(stdscr, peak_y, x, char, pair | (curses.A_BOLD if viz_type == "dots" else 0))


def draw_visualizer(stdscr, settings, playing, viz_state):
    if not settings.get("visualizer", True):
        return
    h, w = stdscr.getmaxyx()
    viz_height = settings.get("visualizer_height", 6)
    start_y = h - 2
    bar_width = 2 if w >= 60 else 1
    col_width = bar_width + 1
    viz_layout = settings.get("visualizer_layout", "center")
    viz_type = settings.get("visualizer_type", "bars")
    if viz_layout == "stereo":
        half_w = (w - 6) // 2
        num_bars = max(3, half_w // col_width)
        update_visualizer(viz_state, num_bars, viz_height, playing, settings)
        for i in range(num_bars):
            h_val = viz_state["heights_l"][i]
            p_val = viz_state["peaks_l"][i]
            x = 2 + i * col_width
            draw_single_bar(stdscr, x, bar_width, h_val, p_val, viz_height, start_y, viz_type, settings)
        for i in range(num_bars):
            h_val = viz_state["heights_r"][i]
            p_val = viz_state["peaks_r"][i]
            x = 2 + half_w + 2 + i * col_width
            draw_single_bar(stdscr, x, bar_width, h_val, p_val, viz_height, start_y, viz_type, settings)
    elif viz_layout == "center":
        mid_x = w // 2
        num_bars = max(3, (w - 6) // (2 * col_width))
        update_visualizer(viz_state, num_bars, viz_height, playing, settings)
        for i in range(num_bars):
            h_val = viz_state["heights_l"][i]
            p_val = viz_state["peaks_l"][i]
            x = mid_x - 1 - i * col_width - bar_width
            draw_single_bar(stdscr, x, bar_width, h_val, p_val, viz_height, start_y, viz_type, settings)
        for i in range(num_bars):
            h_val = viz_state["heights_r"][i]
            p_val = viz_state["peaks_r"][i]
            x = mid_x + 1 + i * col_width
            draw_single_bar(stdscr, x, bar_width, h_val, p_val, viz_height, start_y, viz_type, settings)
    else:
        num_bars = max(3, (w - 4) // col_width)
        update_visualizer(viz_state, num_bars, viz_height, playing, settings)
        for i in range(num_bars):
            h_val = (viz_state["heights_l"][i] + viz_state["heights_r"][i]) / 2.0
            p_val = max(viz_state["peaks_l"][i], viz_state["peaks_r"][i])
            x = 2 + i * col_width
            draw_single_bar(stdscr, x, bar_width, h_val, p_val, viz_height, start_y, viz_type, settings)


def draw_bar(stdscr, y, frac):
    _, w = stdscr.getmaxyx()
    width = max(1, w - 4)
    fill = int(width * clamp(frac, 0, 1))
    safe_add(stdscr, y, 2, "━" * fill, curses.color_pair(PAIR["progress_filled"]) | curses.A_BOLD)
    safe_add(stdscr, y, 2 + fill, "━" * (width - fill), curses.color_pair(PAIR["progress_empty"]))


def lyric_attr(i, cur, settings):
    if i == cur:
        attr = curses.color_pair(PAIR["current_lyric"])
        return attr | curses.A_BOLD if settings["bold"] else attr
    dist = min(abs(i - cur), 3)
    return curses.color_pair(LYRIC_GRADIENT_PAIR + dist)


def draw_lyrics(stdscr, lines, pos, settings, plain=""):
    h, _ = stdscr.getmaxyx()
    top = 3 if settings["header"] else 1
    viz_height = settings.get("visualizer_height", 6) if settings.get("visualizer", True) else 0
    rows = max(1, h - top - viz_height - 1)
    if not lines:
        msg = "lyrics not found :("
        if plain:
            msg = plain.splitlines()[0][:80].lower()
        centered(stdscr, top + rows // 2, msg, curses.color_pair(PAIR["muted"]))
        return
    lyric_pos = pos + settings["offset"]
    cur = lyric_index(lines, lyric_pos)
    break_after = None
    if cur + 1 < len(lines) and lines[cur + 1][0] - lines[cur][0] > BREAK_AFTER and lines[cur][0] + BREAK_AFTER <= lyric_pos < lines[cur + 1][0]:
        break_after = cur
    start = clamp(cur - rows // 2, 0, max(0, len(lines) - rows))
    shown = lines[start:start + rows]
    y = top
    for i, (t, text) in enumerate(shown, start):
        if y >= h - 1 - viz_height:
            break
        attr = lyric_attr(i, cur, settings)
        if break_after == i:
            attr = curses.color_pair(LYRIC_GRADIENT_PAIR)
        if settings["upper"] and i == cur and break_after != i:
            text = text.upper()
        if i == cur and break_after != i:
            text = "> " + text
        if settings["center"]:
            centered(stdscr, y, text, attr)
        else:
            safe_add(stdscr, y, 2, text, attr)
        y += 1
        if break_after == i and y < h - 1 - viz_height:
            attr = lyric_attr(i, i, settings)
            text = "> ..."
            if settings["center"]:
                centered(stdscr, y, text, attr)
            else:
                safe_add(stdscr, y, 2, text, attr)
            y += 1


def draw(stdscr, meta, lines, plain, settings, pos, viz_state):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    dur = meta.get("duration") or 0
    if not lines and not plain:
        centered(stdscr, h // 2, "lyrics not found :(", curses.color_pair(PAIR["muted"]))
        stdscr.refresh()
        return
    if settings["header"]:
        name = (meta.get("title") or "nothing playing").strip()
        artist = (meta.get("artist") or "").strip()
        safe_add(stdscr, 0, 1, name, curses.color_pair(PAIR["header_title"]) | curses.A_BOLD)
        if artist:
            safe_add(stdscr, 0, 1 + len(name), " - " + artist, curses.color_pair(PAIR["header_artist"]))
        off = f"{settings['offset']:+.2f}s"
        safe_add(stdscr, 0, max(1, w - len(off) - 1), off, curses.color_pair(PAIR["header_offset"]))
        draw_bar(stdscr, 1, pos / dur if dur else 0)
    draw_lyrics(stdscr, lines, pos, settings, plain)
    playing = (meta.get("status") == "Playing")
    draw_visualizer(stdscr, settings, playing, viz_state)
    status = []
    if meta.get("player"):
        status.append(f"player: {meta['player']}")
    if meta.get("status") == "Paused":
        status.append("paused")
    if settings.get("visualizer", True):
        src = settings.get("visualizer_source", "loopback")
        layout = settings.get("visualizer_layout", "center")
        theme = settings.get("visualizer_theme", "cyber")
        status.append(f"EQ: {src} ({layout}, {theme})")
    status_str = " | ".join(status)
    safe_add(stdscr, h - 1, 1, status_str, curses.color_pair(PAIR["status"]))
    stdscr.refresh()


def reset():
    for path in (SETTINGS, CACHE):
        try:
            os.remove(path)
        except OSError:
            pass


def clear_cache():
    try:
        os.remove(CACHE)
    except OSError:
        pass


def begin_fetch(meta, cache, use_cache):
    box = {"key": key_for(meta), "done": False, "lines": [], "plain": "searching"}

    def run():
        try:
            box["lines"], box["plain"] = fetch_lyrics(dict(meta), cache, use_cache)
        finally:
            box["done"] = True

    threading.Thread(target=run, daemon=True).start()
    return box


def main(stdscr, use_cache=True, player_arg=None):
    global AUDIO_STATE
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(30)
    settings = merge_settings(load_json(SETTINGS, {}))
    init_colors(settings)
    cache = load_json(CACHE, {})
    meta = {}
    lines, plain = [], ""
    last_key = ""
    last_meta = 0
    last_save = 0
    pos_state = {"pos": None, "seen": 0.0, "t": 0.0}
    viz_state = {}
    job = None

    AUDIO_STATE["enabled"] = True
    threading.Thread(target=audio_capture_loop, daemon=True).start()

    try:
        while True:
            now = time.monotonic()
            if now - last_meta > 0.7:
                new = get_meta(player_arg)
                if new and key_for(new) != last_key:
                    meta = new
                    last_key = key_for(meta)
                    smooth_pos(0, pos_state, True)
                    lines, plain = [], "searching"
                    job = begin_fetch(meta, cache, use_cache)
                elif new:
                    meta = new
                last_meta = now
            if job and job["done"] and job["key"] == last_key:
                lines, plain = job["lines"], job["plain"]
                job = None
            pos = smooth_pos(get_pos(meta.get("player")), pos_state)
            draw(stdscr, meta, lines, plain, settings, pos, viz_state)
            ch = stdscr.getch()
            if ch in (27, ord("q"), ord("Q")):
                break
            elif ch == curses.KEY_UP:
                settings["offset"] = round(settings["offset"] + 0.25, 2)
            elif ch == curses.KEY_DOWN:
                settings["offset"] = round(settings["offset"] - 0.25, 2)
            elif ch == ord("u"):
                settings["header"] = not settings["header"]
            elif ch == ord("c"):
                settings["center"] = not settings["center"]
            elif ch == ord("b"):
                settings["bold"] = not settings["bold"]
            elif ch == ord("U"):
                settings["upper"] = not settings["upper"]
            elif ch == ord("v"):
                settings["visualizer"] = not settings.get("visualizer", True)
            elif ch == ord("V"):
                types = ["bars", "wave", "retro", "dots"]
                current = settings.get("visualizer_type", "bars")
                idx = (types.index(current) + 1) if current in types else 1
                settings["visualizer_type"] = types[idx % len(types)]
            elif ch == ord("a"):
                current_source = settings.get("visualizer_source", "loopback")
                settings["visualizer_source"] = "mock" if current_source == "loopback" else "loopback"
            elif ch == ord("l"):
                layouts = ["center", "stereo", "bars"]
                curr_layout = settings.get("visualizer_layout", "center")
                idx = (layouts.index(curr_layout) + 1) if curr_layout in layouts else 1
                settings["visualizer_layout"] = layouts[idx % len(layouts)]
            elif ch == ord("t"):
                themes = ["cyber", "classic", "fire", "grayscale"]
                curr_theme = settings.get("visualizer_theme", "cyber")
                idx = (themes.index(curr_theme) + 1) if curr_theme in themes else 1
                settings["visualizer_theme"] = themes[idx % len(themes)]
                init_colors(settings)
            elif ch == ord("+"):
                settings["visualizer_height"] = min(15, settings.get("visualizer_height", 6) + 1)
            elif ch == ord("-"):
                settings["visualizer_height"] = max(3, settings.get("visualizer_height", 6) - 1)
            if now - last_save > 2:
                save_json(SETTINGS, settings)
                last_save = now
    finally:
        AUDIO_STATE["enabled"] = False
        save_json(SETTINGS, settings)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--cache", choices=("on", "off"), default="on")
    ap.add_argument("-p", "--player", help="Force playerctl to use a specific player (e.g. spotify)")
    args = ap.parse_args()
    if args.reset:
        reset()
    elif args.clear:
        clear_cache()
    else:
        try:
            curses.wrapper(main, args.cache == "on", args.player)
        except KeyboardInterrupt:
            pass
