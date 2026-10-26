"""Grid geometry shared by the haunted mirror. Pads are 1-based (month, day)."""

import math
from collections.abc import Iterable

from caldera import Frame
from caldera.protocol import DAYS_IN_MONTH

COLUMN = 2.5  # month column pitch relative to day row pitch
PADS = [(m, d) for m in range(1, 13) for d in range(1, DAYS_IN_MONTH[m - 1] + 1)]
VALID = frozenset(PADS)

Pad = tuple[int, int]


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Physical distance between two (month, day) points, in rows."""
    return math.hypot((a[0] - b[0]) * COLUMN, a[1] - b[1])


def compose(*layers: Iterable[Pad]) -> Frame:
    """OR the layers into one frame, dropping pads that do not exist."""
    frame = Frame()
    for layer in layers:
        for pad in layer:
            if pad in VALID:
                frame[pad] = True
    return frame
