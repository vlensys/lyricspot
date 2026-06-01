import argparse
import curses

from lyricspot.config import SETTINGS, CACHE
from lyricspot.utils import reset, clear_cache
from lyricspot.tui import main


def entry():
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


if __name__ == "__main__":
    entry()
