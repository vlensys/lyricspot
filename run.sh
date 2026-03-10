#!/bin/bash
VENV="$HOME/.venv/lyricspot/bin/python"
SCRIPT="$(realpath "$0" | xargs dirname)/lyricspot.py"
"$VENV" "$SCRIPT"
