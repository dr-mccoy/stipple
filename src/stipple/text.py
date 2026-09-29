from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from functools import cache
from importlib.resources import files

from .model import DiagramError, Location


@cache
def font_metrics() -> dict:
    return json.loads(files("stipple").joinpath("assets/metrics.json").read_text("utf-8"))


@dataclass(frozen=True)
class TextSize:
    width: float
    height: float
    ascent: float
    line_height: float
    lines: tuple[str, ...]


def measure(text: str, size: float, location: Location | None = None) -> TextSize:
    metrics = font_metrics()
    scale = size / metrics["units_per_em"]
    lines = tuple(text.split("\n"))
    widths = []
    # common reference keeps labels with different letters on the same base
    reference = [metrics["glyphs"][str(ord(c))] for c in "Hg"]
    ascent = max(g[2] for g in reference)
    descent = min(g[1] for g in reference)
    for line in lines:
        width = 0
        for char in line:
            glyph = metrics["glyphs"].get(str(ord(char)))
            if glyph is None or unicodedata.category(char).startswith("M"):
                raise DiagramError(
                    f"the bundled font cannot set {char!r} (U+{ord(char):04X}); "
                    "use a supported character",
                    location,
                )
            width += glyph[0]
            ascent = max(ascent, glyph[2])
            descent = min(descent, glyph[1])
        widths.append(width * scale)
    line_height = size * 1.35
    return TextSize(
        max(widths),
        (ascent - descent) * scale + (len(lines) - 1) * line_height,
        ascent * scale,
        line_height,
        lines,
    )
