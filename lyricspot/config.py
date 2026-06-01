import difflib
import math
import os
import re
import threading

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


def _precompute_twiddles(n):
    return {
        length: [math.e ** (-2j * math.pi * k / length) for k in range(length // 2)]
        for length in (2 << i for i in range(n.bit_length() - 1))
        if length <= n
    }


TWIDDLES = _precompute_twiddles(256)
HAMMING_256 = tuple(0.54 - 0.46 * math.cos(2 * math.pi * n / 255) for n in range(256))

API = os.environ.get("LRCLIB_API", "https://lrclib.net/api").rstrip("/")
CFG = os.path.join(os.path.expanduser("~"), ".config", "lyricspot")
SETTINGS = os.path.join(CFG, "settings.json")
CACHE = os.path.join(CFG, "cache.json")
UA = "lyricspot/1.0 (https://github.com/vlensys/lyricspot)"

STAMP = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")
JUNK = re.compile(r"\s*[\[(](official|audio|video|lyrics?|lyric video|visualizer|remaster(?:ed)?(?: \d{4})?)[^\])]*[\])]|\s+-\s+(official|audio|video|lyrics?|lyric video|visualizer|remaster(?:ed)?(?: \d{4})?).*$", re.I)
BREAK_AFTER = 8

DIRTY_NONE = 0
DIRTY_ALL = 1 << 0
DIRTY_POS = 1 << 1
DIRTY_VIZ = 1 << 2

BLOCK_CHARS = [" ", " ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
VIZ_PAIR_CACHE = {}
SEQ_MATCHER = difflib.SequenceMatcher()
RE_FEAT = re.compile(r"\s+(feat\.?|ft\.?|featuring)\s+.*$", re.I)
RE_WS = re.compile(r"\s+")

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
