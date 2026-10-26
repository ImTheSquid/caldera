"""Finger strokes captured from Contact/Release events, and their rasterization."""

import numpy as np

from scene import COLUMN, Pad

COMMIT = 1.0  # seconds after lifting before the strokes so far count as one letter
SIZE = 16  # raster side
MARGIN = 2

Stroke = list[Pad]


def line(a: Pad, b: Pad) -> list[Pad]:
    """Pads from a to b inclusive, one pad per step."""
    n = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
    return [(round(a[0] + (b[0] - a[0]) * i / n), round(a[1] + (b[1] - a[1]) * i / n)) for i in range(n + 1)] if n else [a]


class Ink:
    def __init__(self):
        self.strokes: list[Stroke] = []
        self.down = False
        self.lifted = 0.0

    def contact(self, pad: Pad) -> None:
        if not self.down:
            self.strokes.append([])
            self.down = True
        self.strokes[-1].append(pad)

    def release(self, now: float) -> None:
        self.down = False
        self.lifted = now

    def ready(self, now: float) -> bool:
        return bool(self.strokes) and not self.down and now - self.lifted >= COMMIT

    def take(self) -> list[Stroke]:
        strokes, self.strokes, self.down = self.strokes, [], False
        return strokes

    def pads(self) -> set[Pad]:
        """Every pad the strokes pass over, gaps between samples filled in."""
        out = set()
        for s in self.strokes:
            out.update(s)
            for a, b in zip(s, s[1:]):
                out.update(line(a, b))
        return out


def physical(strokes: list[Stroke]) -> list[np.ndarray]:
    """Strokes as (x, y) point arrays in row units."""
    return [np.array([((m - 1) * COLUMN, d - 1) for m, d in s], dtype=float) for s in strokes]


def augment(paths: list[np.ndarray], rng: np.random.Generator) -> list[np.ndarray]:
    """Random affine and jitter, snapped back to the pad grid like real input."""
    a = rng.uniform(-0.15, 0.15)
    sx, sy = rng.uniform(0.85, 1.15, 2)
    shear = rng.uniform(-0.2, 0.2)
    m = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]]) @ np.array([[sx, shear], [0, sy]])
    out = []
    for p in paths:
        q = p @ m.T + rng.normal(0, (0.6, 0.4), p.shape)
        q = np.round(q / (COLUMN, 1)) * (COLUMN, 1)
        keep = rng.random(len(q)) > 0.1
        keep[[0, -1]] = True
        out.append(q[keep])
    return out


def rasterize(paths: list[np.ndarray]) -> np.ndarray:
    """Paths scaled to fit a SIZE x SIZE image, centered, drawn as thick lines; flattened."""
    pts = np.concatenate(paths)
    lo, hi = pts.min(0), pts.max(0)
    scale = (SIZE - 1 - 2 * MARGIN) / max((hi - lo).max(), 1.0)
    img = np.zeros((SIZE, SIZE))
    for p in paths:
        p = (p - (lo + hi) / 2) * scale + (SIZE - 1) / 2
        seg = np.diff(p, axis=0)
        steps = np.maximum(np.ceil(np.abs(seg).max(1, initial=0) * 2), 1).astype(int)
        samples = [a + d * (np.arange(n) / n)[:, None] for a, d, n in zip(p[:-1], seg, steps)]
        ij = np.rint(np.concatenate([*samples, p[-1:]])).astype(int)
        for dx, dy, v in ((0, 0, 1.0), (1, 0, 0.5), (-1, 0, 0.5), (0, 1, 0.5), (0, -1, 0.5)):
            x = np.clip(ij[:, 0] + dx, 0, SIZE - 1)
            y = np.clip(ij[:, 1] + dy, 0, SIZE - 1)
            img[y, x] = np.maximum(img[y, x], v)
    return img.ravel()
