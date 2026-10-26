"""Imps that skitter over the mirror and burst when poked."""

import math
import random
from dataclasses import dataclass
from itertools import combinations

from scene import COLUMN, PADS, Pad, distance

# Two frames, alternated while running; columns are month - 1, month, month + 1
STAND = ("#.#", "###", "###", ".#.", "#.#")
STRIDE_FRAME = ("#.#", "###", "###", "###", ".#.")
HEIGHT = len(STAND)
LOWEST = 28 - HEIGHT + 1  # lowest head row that keeps the feet above the short-month gaps
ROAM = [(1, LOWEST)]  # bands of head rows imps may wander
SPEED = (3.0, 6.0)  # rows per second
TURN = 2.5  # heading drift, radians per sqrt(second)
REST_RATE = 0.3  # rests per second
REST = (0.4, 1.5)
STRIDE = 8.0  # leg flickers per second
HIT = 1.5  # poke reach from any body pad, in rows
SPACING = (3.5, HEIGHT + 0.5)  # closer than this in (months, days) and two imps turn apart
FLEE = 7.0  # scare radius, in rows
FLEE_TIME = 1.0
FLEE_BOOST = 2.5
RESPAWN = (2.0, 4.0)
BURST_SPEED = 20.0  # rows per second
BURST_REACH = 7.0
RING = 0.8


@dataclass
class Burst:
    x: float
    y: float
    start: float

    def radius(self, now: float) -> float:
        return (now - self.start) * BURST_SPEED

    def done(self, now: float) -> bool:
        return self.radius(now) > BURST_REACH

    def pads(self, now: float) -> list[Pad]:
        r = self.radius(now)
        return [p for p in PADS if abs(distance(p, (self.x, self.y)) - r) < RING]


@dataclass
class Imp:
    x: float  # center month, continuous
    y: float  # horn day, continuous
    heading: float  # radians in physical space, +y is down the calendar
    speed: float
    rest_until: float = 0.0
    flee_until: float = 0.0
    respawn_at: float | None = None  # set while dead

    @property
    def head(self) -> Pad:
        return round(self.x), round(self.y)

    def cells(self, now: float) -> list[Pad]:
        m, d = self.head
        running = now >= self.rest_until and int(now * STRIDE) % 2
        frame = STRIDE_FRAME if running else STAND
        return [(m + c - 1, d + r) for r, row in enumerate(frame) for c, ch in enumerate(row) if ch == "#"]

    def step(self, now: float, dt: float, bands: list[tuple[int, int]], rng: random.Random) -> None:
        top, bottom = min(bands, key=lambda b: max(b[0] - self.y, self.y - b[1], 0))
        inside = top <= self.y <= bottom
        if not inside:
            # Outside every band (they moved): rush straight for the nearest
            self.heading = math.copysign(math.pi / 2, top - self.y)
            self.rest_until = 0.0
        elif now < self.rest_until:
            return
        elif now >= self.flee_until:
            self.heading += rng.gauss(0, TURN * math.sqrt(dt))
            if rng.random() < REST_RATE * dt:
                self.rest_until = now + rng.uniform(*REST)

        speed = self.speed * (FLEE_BOOST if now < self.flee_until or not inside else 1)
        self.x += math.cos(self.heading) * speed * dt / COLUMN
        self.y += math.sin(self.heading) * speed * dt
        if not 2 <= self.x <= 11:
            self.x = min(max(self.x, 2), 11)
            self.heading = math.pi - self.heading
        if inside and not top <= self.y <= bottom:
            self.y = min(max(self.y, top), bottom)
            self.heading = -self.heading


class Horde:
    def __init__(self, count: int, rng: random.Random | None = None):
        self.rng = rng or random.Random()
        self.bands = ROAM
        self.visible = True
        self.imps = [self._spawn(edge=False) for _ in range(count)]
        self.bursts: list[Burst] = []

    def _spawn(self, edge: bool) -> Imp:
        top, bottom = self.rng.choice(self.bands)
        if edge:
            x = self.rng.choice((2, 11))
            heading = 0.0 if x == 2 else math.pi
        else:
            x = self.rng.uniform(2, 11)
            heading = self.rng.uniform(-math.pi, math.pi)
        return Imp(x, self.rng.uniform(top, bottom), heading, self.rng.uniform(*SPEED))

    def step(self, now: float, dt: float) -> None:
        for i, imp in enumerate(self.imps):
            if imp.respawn_at is None:
                imp.step(now, dt, self.bands, self.rng)
            elif now >= imp.respawn_at:
                self.imps[i] = self._spawn(edge=True)
        alive = [imp for imp in self.imps if imp.respawn_at is None]
        for a, b in combinations(alive, 2):
            dx, dy = b.x - a.x, b.y - a.y
            if abs(dx) < SPACING[0] and abs(dy) < SPACING[1]:
                b.heading = math.atan2(dy, dx * COLUMN)
                a.heading = b.heading + math.pi
                a.rest_until = b.rest_until = 0.0
        self.bursts = [b for b in self.bursts if not b.done(now)]

    def poke(self, pad: Pad, now: float) -> bool:
        """Burst every visible imp within reach of the pad and scatter the rest."""
        hit = False
        for imp in self.imps:
            if imp.respawn_at is not None:
                continue
            if self.visible and any(distance(pad, c) <= HIT for c in imp.cells(now)):
                imp.respawn_at = now + self.rng.uniform(*RESPAWN)
                self.bursts.append(Burst(imp.x, imp.y + HEIGHT // 2, now))
                hit = True
            elif distance(pad, (imp.x, imp.y)) <= FLEE:
                imp.heading = math.atan2(imp.y - pad[1], (imp.x - pad[0]) * COLUMN)
                imp.flee_until = now + FLEE_TIME
                imp.rest_until = 0.0
        return hit

    def pads(self, now: float) -> list[Pad]:
        out = [p for b in self.bursts for p in b.pads(now)]
        if self.visible:
            out += [c for imp in self.imps if imp.respawn_at is None for c in imp.cells(now)]
        return out
