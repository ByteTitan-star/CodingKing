"""Entrance splash: a little boy + CNU block letters (Claude-Code-style intro).

Plays a short frame animation on interactive terminals only; skipped when
output is piped, when CI is detected, or when CODEKING_NO_SPLASH is set.
"""

from __future__ import annotations

import os
import time

from rich.align import Align
from rich.console import Console
from rich.live import Live
from rich.text import Text

from coderking import __version__

BOY = [
    "   _____   ",
    "  |_____|  ",
    "   (◕‿◕)  ",
    "   ──┼──  ",
    "    ╱ ╲   ",
]

# "CNU" in ANSI-shadow block letters (6 lines, 9 chars per glyph).
CNU = [
    " ██████╗ ███╗   ██╗██████╗ ",
    "██╔════╝ ████╗  ██║██╔══██╗",
    "██║      ██╔██╗ ██║██║  ██║",
    "██║      ██║╚██╗██║██║  ██║",
    "╚██████╗ ██║ ╚████║██████╔╝",
    " ╚═════╝ ╚═╝  ╚═══╝╚═════╝ ",
]

FRAME_INTERVAL = 0.11
FRAMES = 9

_ACCENT = "#D97757"
_TEXT = "#E8E4DC"
_DIM = "#8B867C"


def _glyph(line: str, index: int, lit: bool) -> Text:
    if not lit:
        return Text(" " * 9)
    return Text(line[index * 9 : (index + 1) * 9], style=_TEXT if lit else _ACCENT)


def _compose(frame: int) -> Text:
    """Boy bounces then settles; C·N·U light up one per frame."""
    bounce = 1 if frame in (1, 3, 5) else 0
    boy_lines = ([""] * bounce) + BOY
    boy_lines = ([""] * (len(CNU) - len(boy_lines))) + boy_lines
    lit_columns = frame - 2  # C at frame 3, N at 4, U at 5

    out = Text()
    for i in range(len(CNU)):
        out.append(Text(boy_lines[i], style=_ACCENT))
        out.append(Text("  "))
        for glyph in range(3):
            out.append(_glyph(CNU[i], glyph, lit_columns >= glyph + 1))
        out.append(Text("\n"))
    out.append(Text(f"CoderKing · 自主编码代理 v{__version__}", style=_DIM))
    return out


def play_splash(console: Console | None = None) -> bool:
    """Play the intro animation; returns False when skipped (non-TTY/CI/NO_SPLASH)."""
    console = console or Console()
    if (
        not console.is_terminal
        or os.environ.get("CODEKING_NO_SPLASH")
        or os.environ.get("CI")
    ):
        return False
    with Live(Align.center(_compose(0)), console=console, refresh_per_second=16) as live:
        for frame in range(FRAMES):
            live.update(Align.center(_compose(frame)), refresh=True)
            time.sleep(FRAME_INTERVAL)
        time.sleep(0.25)
    return True
