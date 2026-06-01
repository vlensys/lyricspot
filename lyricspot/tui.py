import curses
import threading
import time

from lyricspot.config import (
    SETTINGS, CACHE, AUDIO_STATE,
    DIRTY_ALL, DIRTY_NONE, DIRTY_POS, DIRTY_VIZ,
)
from lyricspot.utils import (
    key_for, load_json, save_json, smooth_pos, get_meta,
    get_pos, begin_fetch, audio_capture_loop, fetch_lyrics,
)
from lyricspot.render import init_colors, draw


def main(stdscr, use_cache=True, player_arg=None):
    global AUDIO_STATE
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(30)

    from lyricspot.config import merge_settings
    settings = merge_settings(load_json(SETTINGS, {}))
    init_colors(settings)
    cache = load_json(CACHE, {})
    meta = {}
    lines, plain = [], ""
    last_key = ""
    last_meta = 0
    last_save = 0
    last_cache_save = 0
    cache_dirty_count = 0
    pos_state = {"pos": None, "seen": 0.0, "t": 0.0}
    viz_state = {}
    job = None
    last_pos = -1.0
    dirty = DIRTY_ALL

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
                    dirty = DIRTY_ALL
                elif new:
                    meta = new
                last_meta = now
            if job and job["done"] and job["key"] == last_key:
                lines, plain = job["lines"], job["plain"]
                job = None
                dirty = DIRTY_ALL
                cache_dirty_count += 1
            pos = smooth_pos(get_pos(meta.get("player")), pos_state)
            if abs(pos - last_pos) > 0.5:
                dirty |= DIRTY_POS
                last_pos = pos
            dirty |= DIRTY_VIZ
            draw(stdscr, meta, lines, plain, settings, pos, viz_state, dirty)
            dirty = DIRTY_NONE
            ch = stdscr.getch()
            if ch in (27, ord("q"), ord("Q")):
                break
            elif ch in (curses.KEY_UP, curses.KEY_DOWN):
                settings["offset"] = round(settings["offset"] + (0.25 if ch == curses.KEY_UP else -0.25), 2)
                dirty |= DIRTY_ALL
            elif ch == ord("u"):
                settings["header"] = not settings["header"]
                dirty |= DIRTY_ALL
            elif ch == ord("c"):
                settings["center"] = not settings["center"]
                dirty |= DIRTY_ALL
            elif ch == ord("b"):
                settings["bold"] = not settings["bold"]
                dirty |= DIRTY_ALL
            elif ch == ord("U"):
                settings["upper"] = not settings["upper"]
                dirty |= DIRTY_ALL
            elif ch == ord("v"):
                settings["visualizer"] = not settings.get("visualizer", True)
                dirty |= DIRTY_ALL
            elif ch == ord("V"):
                types_list = ["bars", "wave", "retro", "dots"]
                current = settings.get("visualizer_type", "bars")
                idx = (types_list.index(current) + 1) if current in types_list else 1
                settings["visualizer_type"] = types_list[idx % len(types_list)]
                dirty |= DIRTY_ALL
            elif ch == ord("a"):
                current_source = settings.get("visualizer_source", "loopback")
                settings["visualizer_source"] = "mock" if current_source == "loopback" else "loopback"
                dirty |= DIRTY_ALL
            elif ch == ord("l"):
                layouts_list = ["center", "stereo", "bars"]
                curr_layout = settings.get("visualizer_layout", "center")
                idx = (layouts_list.index(curr_layout) + 1) if curr_layout in layouts_list else 1
                settings["visualizer_layout"] = layouts_list[idx % len(layouts_list)]
                dirty |= DIRTY_ALL
            elif ch == ord("t"):
                themes_list = ["cyber", "classic", "fire", "grayscale"]
                curr_theme = settings.get("visualizer_theme", "cyber")
                idx = (themes_list.index(curr_theme) + 1) if curr_theme in themes_list else 1
                settings["visualizer_theme"] = themes_list[idx % len(themes_list)]
                init_colors(settings)
                dirty |= DIRTY_ALL
            elif ch == ord("+"):
                settings["visualizer_height"] = min(15, settings.get("visualizer_height", 6) + 1)
                dirty |= DIRTY_ALL
            elif ch == ord("-"):
                settings["visualizer_height"] = max(3, settings.get("visualizer_height", 6) - 1)
                dirty |= DIRTY_ALL
            if now - last_save > 2:
                save_json(SETTINGS, settings)
                last_save = now
            if cache_dirty_count > 0 and now - last_cache_save > 10:
                save_json(CACHE, cache)
                last_cache_save = now
                cache_dirty_count = 0
    finally:
        AUDIO_STATE["enabled"] = False
        save_json(SETTINGS, settings)
        if cache_dirty_count > 0:
            save_json(CACHE, cache)
