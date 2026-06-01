import curses
import math
import random
import re
import time

from lyricspot.config import (
    BLOCK_CHARS, COLOR_NAMES, DEFAULT_SETTINGS, LYRIC_GRADIENT_PAIR,
    PAIR, VIZ_GRADIENT_PAIR, VIZ_PAIR_CACHE, VIZ_THEMES,
    AUDIO_STATE, BREAK_AFTER, DIRTY_ALL, DIRTY_NONE, DIRTY_POS, DIRTY_VIZ,
)
from lyricspot.utils import clamp, get_eq_bands, lyric_index


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
        VIZ_PAIR_CACHE[theme_name] = [curses.color_pair(VIZ_GRADIENT_PAIR + i) for i in range(len(theme_colors))]


def get_viz_pair(y_offset, max_height, settings):
    if curses.COLORS < 256:
        color_idx = clamp(3 - int((y_offset / max_height) * 4), 0, 3)
        return curses.color_pair(LYRIC_GRADIENT_PAIR + color_idx)
    theme_name = settings.get("visualizer_theme", "cyber")
    pairs = VIZ_PAIR_CACHE.get(theme_name)
    if pairs:
        color_idx = clamp(int((y_offset / max_height) * len(pairs)), 0, len(pairs) - 1)
        return pairs[color_idx]
    return curses.color_pair(VIZ_GRADIENT_PAIR)


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

    exp_attack = math.exp(-26.0 * dt)
    exp_release = math.exp(-9.0 * dt)
    exp_peak_attack = math.exp(-20.0 * dt)
    exp_peak_release = math.exp(-7.0 * dt)
    peak_decay = 4.0 * dt

    source = settings.get("visualizer_source", "loopback")
    has_audio = False

    if source == "loopback" and AUDIO_STATE["active"]:
        with AUDIO_STATE["lock"]:
            mags_l = AUDIO_STATE["mags_l"]
            mags_r = AUDIO_STATE["mags_r"]

        pm_l = viz_state["prev_mags_l"]
        pm_r = viz_state["prev_mags_r"]
        for i in range(128):
            pm_l[i] = pm_l[i] * 0.45 + mags_l[i] * 0.55
            pm_r[i] = pm_r[i] * 0.45 + mags_r[i] * 0.55

        bands_l = get_eq_bands(pm_l, num_bars)
        bands_r = get_eq_bands(pm_r, num_bars)
        if any(v > 0.0001 for v in bands_l + bands_r):
            has_audio = True
            peak_l = max(bands_l)
            peak_r = max(bands_r)
            viz_state["running_peak_l"] = 0.97 * viz_state["running_peak_l"] + 0.03 * max(peak_l, 0.001)
            viz_state["running_peak_r"] = 0.97 * viz_state["running_peak_r"] + 0.03 * max(peak_r, 0.001)
            scale_l = max_height / max(0.001, viz_state["running_peak_l"])
            scale_r = max_height / max(0.001, viz_state["running_peak_r"])
            hl = viz_state["heights_l"]
            hr = viz_state["heights_r"]
            for i in range(num_bars):
                val_l = clamp(bands_l[i] * scale_l * 0.85, 0.0, max_height)
                val_r = clamp(bands_r[i] * scale_r * 0.85, 0.0, max_height)

                cur_l = hl[i]
                if val_l > cur_l:
                    cur_l = cur_l * exp_attack + val_l * (1.0 - exp_attack)
                else:
                    cur_l = cur_l * exp_release + val_l * (1.0 - exp_release)
                hl[i] = cur_l

                cur_r = hr[i]
                if val_r > cur_r:
                    cur_r = cur_r * exp_attack + val_r * (1.0 - exp_attack)
                else:
                    cur_r = cur_r * exp_release + val_r * (1.0 - exp_release)
                hr[i] = cur_r

    if not has_audio:
        hl = viz_state["heights_l"]
        hr = viz_state["heights_r"]
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
            cur_l = hl[i]
            if val_l > cur_l:
                hl[i] = cur_l * exp_peak_attack + val_l * (1.0 - exp_peak_attack)
            else:
                hl[i] = cur_l * exp_peak_release + val_l * (1.0 - exp_peak_release)
            cur_r = hr[i]
            if val_r > cur_r:
                hr[i] = cur_r * exp_peak_attack + val_r * (1.0 - exp_peak_attack)
            else:
                hr[i] = cur_r * exp_peak_release + val_r * (1.0 - exp_peak_release)

    for i in range(num_bars):
        for h_key, p_key in (("heights_l", "peaks_l"), ("heights_r", "peaks_r")):
            cur = viz_state[h_key][i]
            peak = viz_state[p_key][i]
            if cur >= peak:
                peak = cur
            else:
                peak = max(0.0, peak - peak_decay)
            viz_state[p_key][i] = peak


def draw_single_bar(stdscr, x, bar_width, h_val, p_val, viz_height, start_y, viz_type, settings):
    full_block = "█" * bar_width
    for y_offset in range(viz_height):
        y = start_y - y_offset
        pair = get_viz_pair(y_offset, viz_height, settings)
        if viz_type == "bars":
            if h_val >= y_offset + 1:
                safe_add(stdscr, y, x, full_block, pair)
            elif h_val > y_offset:
                idx = clamp(int((h_val - y_offset) * 8), 0, 8)
                if idx > 0:
                    safe_add(stdscr, y, x, BLOCK_CHARS[idx] * bar_width, pair)
        elif viz_type == "wave":
            if y_offset <= h_val < y_offset + 1 and h_val > 0.1:
                idx = clamp(int((h_val - y_offset) * 8), 0, 8)
                if idx > 0:
                    safe_add(stdscr, y, x, BLOCK_CHARS[idx] * bar_width, pair)
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


def draw(stdscr, meta, lines, plain, settings, pos, viz_state, dirty=DIRTY_ALL):
    h, w = stdscr.getmaxyx()
    dur = meta.get("duration") or 0
    if dirty & DIRTY_ALL:
        stdscr.erase()
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
    else:
        if settings["header"]:
            draw_bar(stdscr, 1, pos / dur if dur else 0)
        draw_lyrics(stdscr, lines, pos, settings, plain)
        if dirty & DIRTY_VIZ:
            playing = (meta.get("status") == "Playing")
            draw_visualizer(stdscr, settings, playing, viz_state)
    stdscr.refresh()
