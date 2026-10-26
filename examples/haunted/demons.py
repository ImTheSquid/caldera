"""Imps that skitter over the mirror and burst when poked."""

import math
import random
from dataclasses import dataclass

from scene import COLUMN, PADS, Pad, distance

BAND = (1, 26)  # head rows; bodies reach 2 rows lower, clear of the short-month gaps
SPEED = (3.0, 6.0)  # rows per second
TURN = 2.5  # heading drift, radians per sqrt(second)
REST_RATE = 0.3  # rests per second
REST = (0.4, 1.5)
STRIDE = 8.0  # leg flickers per second
HIT = 1.5  # poke reach from any body pad, in rows
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
    x: float  # month, continuous
    y: float  # head day, continuous
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
        body = [(m, d), (m, d + 1)]
        if now >= self.rest_until and int(now * STRIDE) % 2:
            body.append((m, d + 2))
        return body

    def step(self, now: float, dt: float, band: tuple[int, int], rng: random.Random) -> None:
        top, bottom = band
        if not top <= self.y <= bottom:
            # Outside the band (it moved): head straight for it
            self.heading = math.copysign(math.pi / 2, top - self.y)
            self.rest_until = 0.0
        elif now < self.rest_until:
            return
        elif now >= self.flee_until:
            self.heading += rng.gauss(0, TURN * math.sqrt(dt))
            if rng.random() < REST_RATE * dt:
                self.rest_until = now + rng.uniform(*REST)

        speed = self.speed * (FLEE_BOOST if now < self.flee_until else 1)
        inside = top <= self.y <= bottom
        self.x += math.cos(self.heading) * speed * dt / COLUMN
        self.y += math.sin(self.heading) * speed * dt
        if not 1 <= self.x <= 12:
            self.x = min(max(self.x, 1), 12)
            self.heading = math.pi - self.heading
        if inside and not top <= self.y <= bottom:
            self.y = min(max(self.y, top), bottom)
            self.heading = -self.heading


class Horde:
    def __init__(self, count: int, rng: random.Random | None = None):
        self.rng = rng or random.Random()
        self.band = BAND
        self.visible = True
        self.imps = [self._spawn(edge=False) for _ in range(count)]
        self.bursts: list[Burst] = []

    def _spawn(self, edge: bool) -> Imp:
        top, bottom = self.band
        if edge:
            x = self.rng.choice((1, 12))
            heading = 0.0 if x == 1 else math.pi
        else:
            x = self.rng.uniform(1, 12)
            heading = self.rng.uniform(-math.pi, math.pi)
        return Imp(x, self.rng.uniform(top, bottom), heading, self.rng.uniform(*SPEED))

    def step(self, now: float, dt: float) -> None:
        for i, imp in enumerate(self.imps):
            if imp.respawn_at is None:
                imp.step(now, dt, self.band, self.rng)
            elif now >= imp.respawn_at:
                self.imps[i] = self._spawn(edge=True)
        self.bursts = [b for b in self.bursts if not b.done(now)]

    def poke(self, pad: Pad, now: float) -> bool:
        """Burst every visible imp within reach of the pad and scatter the rest."""
        hit = False
        for imp in self.imps:
            if imp.respawn_at is not None:
                continue
            if self.visible and any(distance(pad, c) <= HIT for c in imp.cells(now)):
                imp.respawn_at = now + self.rng.uniform(*RESPAWN)
                self.bursts.append(Burst(*imp.head, now))
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
