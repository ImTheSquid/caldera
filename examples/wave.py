"""Ripple from each touched day. Each touch toggles and saves that day.

    uv run examples/wave.py

Turning a day on sends rings outward from it; turning it off collapses rings
into it. Overlapping waves interfere. Runs in host mode, so the brightness
buttons are handled here and the Jan 1 reset hold is disabled until Ctrl-C.
"""

import math
import time
from dataclasses import dataclass, field

from caldera import BrightnessButton, Calendar, Frame, Mode, Touch
from caldera.protocol import DAYS_IN_MONTH, MAX_BRIGHTNESS

FPS = 100
SPEED = 45.0  # rows per second
RING = 1.0  # ring half-thickness, in rows
TRAIL = 5.0  # gap between the two rings of a wave, in rows
COLUMN = 2.5  # month column pitch relative to day row pitch
BRIGHTNESS_STEP = 20
PADS = [(m, d) for m in range(1, 13) for d in range(1, DAYS_IN_MONTH[m - 1] + 1)]
REACH = math.hypot(11 * COLUMN, 30) + TRAIL + RING


@dataclass
class Wave:
    month: int
    day: int
    outward: bool
    start: float
    dist: dict[tuple[int, int], float] = field(init=False)

    def __post_init__(self) -> None:
        self.dist = {p: math.hypot((p[0] - self.month) * COLUMN, p[1] - self.day) for p in PADS}

    def radius(self, now: float) -> float:
        travelled = (now - self.start) * SPEED
        return travelled if self.outward else REACH - travelled

    def done(self, now: float) -> bool:
        return (now - self.start) * SPEED > REACH

    def lit(self, pad: tuple[int, int], r: float) -> bool:
        trail = r - TRAIL if self.outward else r + TRAIL
        d = self.dist[pad]
        return abs(d - r) < RING or abs(d - trail) < RING


def render(base: Frame, waves: list[Wave], now: float) -> Frame:
    """Invert the base under each ring; where waves overlap they cancel."""
    frame = Frame(base.words)
    radii = [(w, w.radius(now)) for w in waves]
    for pad in PADS:
        if sum(w.lit(pad, r) for w, r in radii) % 2:
            frame[pad] = not base[pad]
    return frame


def play(cal: Calendar) -> None:
    base = cal.read()
    level = cal.brightness
    waves: list[Wave] = []
    cal.mode = Mode.HOST
    try:
        tick = time.perf_counter()
        while True:
            # Wait while idle; otherwise just drain what has arrived.
            event = cal.next_event(timeout=0.5 if not waves else 0)
            if event is None and not waves:
                continue
            while event is not None:
                if isinstance(event, Touch):
                    pad = (event.month, event.day)
                    on = not base[pad]
                    base[pad] = on
                    cal.write(base)  # the device saves whatever it is displaying
                    cal.save()
                    waves.append(Wave(*pad, outward=on, start=time.perf_counter()))
                    print(f"{pad[0]}/{pad[1]} {'on' if on else 'off'}, saved")
                elif isinstance(event, BrightnessButton):
                    step = BRIGHTNESS_STEP if event.kind == "BRIGHT" else -BRIGHTNESS_STEP
                    level = max(0, min(MAX_BRIGHTNESS, level + step))
                    cal.brightness = level
                event = cal.next_event(timeout=0)

            now = time.perf_counter()
            waves = [w for w in waves if not w.done(now)]
            cal.write(render(base, waves, now))
            if waves:
                tick = max(tick + 1 / FPS, time.perf_counter())  # never catch up in a burst
                time.sleep(max(0.0, tick - time.perf_counter()))
    except KeyboardInterrupt:
        pass
    finally:
        cal.write(base)
        cal.mode = Mode.LOCAL


if __name__ == "__main__":
    with Calendar() as cal:
        print("touch a day; Ctrl-C to stop")
        play(cal)
