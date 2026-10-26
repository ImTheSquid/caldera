"""Hardware round trip. Leaves the saved calendar untouched.

    uv run examples/smoke.py [--touch]
"""

import statistics
import sys
import time

from caldera import Calendar, Frame, Mode, Touch

t0 = time.monotonic()
with Calendar() as cal:
    print(f"boot: {time.monotonic() - t0:.1f}s")
    cal.ping()
    original = cal.read()
    print(f"lit: {len(original.lit())} days")
    try:
        cal.write(original)
        assert cal.read() == original, "write/read mismatch"

        probe = next((m, d) for m in range(1, 13) for d in range(1, 29) if not original[m, d])
        cal[probe] = True
        assert cal[probe], "SET did not stick"
        print(f"lit {probe} for 1s")
        time.sleep(1)
        cal[probe] = False

        level = cal.brightness
        for b in [*range(0, 201, 20), level]:
            cal.brightness = b
            time.sleep(0.1)
        assert cal.brightness == level

        frames = [Frame([0x7FFFFFFF if (m + i) % 2 else 0 for m in range(12)]) for i in range(2)]
        dts = []
        for i in range(100):
            t = time.monotonic()
            cal.write(frames[i % 2])
            dts.append(time.monotonic() - t)
        fps = [1 / dt for dt in dts]
        print(f"full-frame write: {statistics.mean(fps):.1f} ± {statistics.stdev(fps):.1f} fps")

        if "--touch" in sys.argv:
            cal.write(original)
            cal.mode = Mode.HOST
            print("host mode: touch any day pad within 15s")
            ev = next((e for e in cal.events(timeout=15) if isinstance(e, Touch)), None)
            assert ev is not None, "no touch event"
            print(f"got {ev}")
            assert cal.read() == original, "host-mode touch changed the LEDs"
    finally:
        cal.mode = Mode.LOCAL
        cal.revert()
    assert cal.read() == original, "revert did not restore saved state"
    print("ok")
