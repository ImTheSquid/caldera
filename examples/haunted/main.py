"""Haunted mirror: imps skitter over the calendar; poke one to burst it.

    uv run examples/haunted/main.py

Runs in host mode and never saves, so the real calendar returns on Ctrl-C.
"""

import argparse
import time

from caldera import BrightnessButton, Calendar, Mode, Touch
from caldera.protocol import MAX_BRIGHTNESS
from demons import Horde
from scene import compose

FPS = 50
BRIGHTNESS_STEP = 20


def play(cal: Calendar, horde: Horde) -> None:
    level = cal.brightness
    tick = last = time.perf_counter()
    while True:
        while (event := cal.next_event(timeout=0)) is not None:
            now = time.perf_counter()
            if isinstance(event, Touch):
                horde.poke((event.month, event.day), now)
            elif isinstance(event, BrightnessButton):
                step = BRIGHTNESS_STEP if event.kind == "BRIGHT" else -BRIGHTNESS_STEP
                level = max(0, min(MAX_BRIGHTNESS, level + step))
                cal.brightness = level

        now = time.perf_counter()
        horde.step(now, now - last)
        last = now
        cal.write(compose(horde.pads(now)))
        tick = max(tick + 1 / FPS, time.perf_counter())  # never catch up in a burst
        time.sleep(max(0.0, tick - time.perf_counter()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--imps", type=int, default=5)
    args = parser.parse_args()
    with Calendar() as cal:
        original = cal.read()
        cal.mode = Mode.HOST
        print("poke the imps; Ctrl-C to stop")
        try:
            play(cal, Horde(args.imps))
        except KeyboardInterrupt:
            pass
        finally:
            cal.write(original)
            cal.mode = Mode.LOCAL


if __name__ == "__main__":
    main()
