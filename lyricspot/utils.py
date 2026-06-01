import json
import math
import os
import re
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from lyricspot.config import (
    API, CACHE, CFG, HAS_NUMPY, SETTINGS, UA,
    HAMMING_256, JUNK, RE_FEAT, RE_WS, SEQ_MATCHER, STAMP, TWIDDLES,
    AUDIO_STATE
)


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


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
    s = RE_FEAT.sub("", s)
    s = RE_WS.sub(" ", s).strip(" -_")
    return s


def search_terms(meta):
    raw_title = meta.get("title", "")
    raw_artist = meta.get("artist", "")
    title, artist = raw_title, raw_artist
    if not artist and " - " in title:
        a, t = title.split(" - ", 1)
        artist, title = a.strip(), t.strip()
    norm_title = norm(title)
    norm_artist = norm(clean_artist(artist))
    pairs = [(raw_title, clean_artist(raw_artist)), (norm_title, norm_artist)]
    seen = set()
    out = []
    for t, a in pairs:
        if t and a and (t, a) not in seen:
            seen.add((t, a))
            out.append((t, a))
    return out or [(norm_title, norm_artist)]


def sim(a, b):
    SEQ_MATCHER.set_seqs(norm(a).casefold(), norm(b).casefold())
    return SEQ_MATCHER.ratio()


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
    artist = clean_artist(meta["artist"])
    title = meta["title"]
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


def fft(a):
    n = len(a)
    if HAS_NUMPY:
        return np.fft.fft(a).tolist()
    return _fft_iterative(list(a), n)


def _fft_iterative(a, n):
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    length = 2
    while length <= n:
        half = length // 2
        w = TWIDDLES[length]
        for i in range(0, n, length):
            for k in range(half):
                even = a[i + k]
                odd = a[i + k + half] * w[k]
                a[i + k] = even + odd
                a[i + k + half] = even - odd
        length <<= 1
    return a


_EQ_BAND_CACHE = {}


def get_eq_bands(magnitudes, num_bars):
    if not magnitudes:
        return [0.0] * num_bars
    n_mags = len(magnitudes)
    if num_bars not in _EQ_BAND_CACHE:
        min_bin = 1.0
        max_bin = n_mags - 1.0
        ratio = max_bin / min_bin
        bands = []
        for i in range(num_bars):
            f_start = min_bin * (ratio ** (i / num_bars))
            f_end = min_bin * (ratio ** ((i + 1) / num_bars))
            start_idx = max(1, int(f_start))
            end_idx = min(n_mags, max(start_idx + 1, int(f_end)))
            bands.append((start_idx, end_idx))
        _EQ_BAND_CACHE[num_bars] = bands
    out = [0.0] * num_bars
    bands = _EQ_BAND_CACHE[num_bars]
    for i, (start_idx, end_idx) in enumerate(bands):
        width = end_idx - start_idx
        if width == 1:
            out[i] = magnitudes[start_idx]
        elif width > 1:
            total = 0.0
            for j in range(start_idx, end_idx):
                total += magnitudes[j]
            out[i] = total / width
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
            data = proc.stdout.read(1024)
            if len(data) < 1024:
                proc = None
                continue
            samples = struct.unpack("<512h", data)
            left = samples[0::2]
            right = samples[1::2]
            x_l = [(left[i] / 32768.0) * HAMMING_256[i] for i in range(256)]
            x_r = [(right[i] / 32768.0) * HAMMING_256[i] for i in range(256)]
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
